#!/usr/bin/env python3
"""Outlook watchdog + heartbeat, for the locked-down Windows laptop.

Runs on the WINDOWS machine from Task Scheduler, every few minutes. Each run:

  1. Is OUTLOOK.EXE running?             -> if not, try to start it
  2. Is the mailbox actually syncing?    -> .ost file modified recently?
  3. POST the result to the briefing box's /heartbeat.php

The relaunch in step 1 is the point. Monitoring alone means a trip to the
basement every time a Windows Update kills Outlook; relaunching means most
incidents resolve themselves and the notification is "it fixed itself" rather
than "go fix it".

Step 2 exists because a running OUTLOOK.EXE is not the same as a syncing one —
Outlook can sit with a wedged connection and a live process, which is the
silent failure that started all this. The .ost mtime is a proxy for "the
mailbox is still being written to". Tune OST_STALE_MINUTES after watching what
your own profile does; set it to 0 to disable that check entirely.

Nothing here needs admin rights: it reads the process list, starts a user
process, stats a file in the user's own AppData, and makes one outbound HTTPS
call.

Install (PowerShell, as the logged-in user):

    schtasks /create /tn "OutlookHeartbeat" /sc minute /mo 5 ^
      /tr "python.exe C:\\path\\to\\outlook_heartbeat.py" /f

pythonw.exe also works (no console window); logging is guarded for the missing
stdout that comes with it.

Check it:   schtasks /run /tn "OutlookHeartbeat"
Logs to:    %LOCALAPPDATA%\\outlook_heartbeat.log
"""
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime

# Bumped whenever this file changes, and reported in every heartbeat's `extra`.
# Getting files onto the laptop is painful, so "did my copy actually take?" has
# to be answerable from here rather than by trusting that it did.
VERSION = '2026-09-17.2'

# ---- settings ----------------------------------------------------------
# The briefing's nginx server block listens on 8113 (not 80 — that vhost is
# ownCloud). Use the Mac's LAN IP; .local mDNS names are unreliable from a
# domain-joined Windows box.
HEARTBEAT_URL = 'http://192.168.10.3:8113/heartbeat.php'
# Leave empty unless you set heartbeats.token on the briefing side.
TOKEN = ''
MACHINE_NAME = 'work-laptop'

# Where Outlook lives. The launcher tries these in order; the first that exists
# wins. Add your own path if Office is installed somewhere unusual.
OUTLOOK_PATHS = [
    r'C:\Program Files\Microsoft Office\root\Office16\OUTLOOK.EXE',
    r'C:\Program Files (x86)\Microsoft Office\root\Office16\OUTLOOK.EXE',
    r'C:\Program Files\Microsoft Office\Office16\OUTLOOK.EXE',
]

# Consider sync stalled if no .ost file has been written in this long.
# 0 disables the check (process-alive only).
OST_STALE_MINUTES = 60

# Give Outlook this long to appear in the process list after a relaunch.
RELAUNCH_WAIT_SECONDS = 25

LOG_PATH = os.path.join(os.environ.get('LOCALAPPDATA', os.path.expanduser('~')),
                        'outlook_heartbeat.log')


def log(msg):
    line = '%s %s' % (datetime.now().strftime('%Y-%m-%d %H:%M:%S'), msg)
    try:
        with open(LOG_PATH, 'a') as f:
            f.write(line + '\n')
    except OSError:
        pass
    # Under pythonw.exe there is no console and sys.stdout is None, so a bare
    # print() raises AttributeError. That would be fatal here: the first log()
    # of the relaunch path runs BEFORE start_outlook(), so a crash would stop
    # the self-heal from ever happening. The file is the real log; stdout is a
    # convenience for running it by hand.
    try:
        print(line)
    except Exception:
        pass


def outlook_running():
    """True if OUTLOOK.EXE is in the task list."""
    try:
        out = subprocess.run(
            ['tasklist', '/FI', 'IMAGENAME eq OUTLOOK.EXE', '/NH'],
            capture_output=True, text=True, timeout=30,
            # Without this a console window flickers on screen every run.
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
        ).stdout
    except (OSError, subprocess.SubprocessError) as e:
        log('tasklist failed: %s' % e)
        return None            # unknown, not "down"
    return 'OUTLOOK.EXE' in out.upper()


def start_outlook():
    """Launch Outlook. Returns True if it is running afterwards."""
    exe = next((p for p in OUTLOOK_PATHS if os.path.exists(p)), None)
    detached = getattr(subprocess, 'DETACHED_PROCESS', 0)
    try:
        if exe:
            # DETACHED_PROCESS so Outlook outlives this script when the
            # scheduled task's process tree is torn down.
            subprocess.Popen([exe], close_fds=True, creationflags=detached)
        else:
            # No known path matched — an Office major-version bump moves these,
            # and a silently broken self-heal only shows up during a real
            # outage. Fall back to the shell association, which is what
            # Start > Outlook uses and does not care where it is installed.
            log('no OUTLOOK.EXE at a known path; trying the shell association')
            subprocess.Popen(['cmd', '/c', 'start', '', 'outlook'],
                             close_fds=True, creationflags=detached)
    except OSError as e:
        log('could not start Outlook: %s' % e)
        return False

    deadline = time.time() + RELAUNCH_WAIT_SECONDS
    while time.time() < deadline:
        time.sleep(2)
        if outlook_running():
            return True
    return False


def newest_ost_age_minutes():
    """Minutes since the most recently modified .ost, or None if none found."""
    root = os.path.join(os.environ.get('LOCALAPPDATA', ''), 'Microsoft', 'Outlook')
    if not os.path.isdir(root):
        return None
    newest = None
    for dirpath, _dirs, files in os.walk(root):
        for fname in files:
            if fname.lower().endswith('.ost'):
                try:
                    mtime = os.path.getmtime(os.path.join(dirpath, fname))
                except OSError:
                    continue
                if newest is None or mtime > newest:
                    newest = mtime
    if newest is None:
        return None
    return max(0.0, (time.time() - newest) / 60.0)


def post(record):
    data = json.dumps(record).encode('utf-8')
    headers = {'Content-Type': 'application/json'}
    if TOKEN:
        headers['Authorization'] = 'Bearer ' + TOKEN
    req = urllib.request.Request(HEARTBEAT_URL, data=data, method='POST',
                                 headers=headers)
    with urllib.request.urlopen(req, timeout=20) as resp:
        return resp.status, resp.read().decode('utf-8', 'replace')[:200]


def main():
    running = outlook_running()
    status, detail, ok = 'ok', '', True

    if running is False:
        log('Outlook not running — attempting relaunch')
        if start_outlook():
            status, detail = 'outlook_relaunched', 'Outlook was down; restarted it here.'
            # Reflect the POST-relaunch state. Reporting the stale `False` here
            # made a successful self-heal read as "outlook_relaunched" with
            # "outlook_running: false" — a record that contradicts itself.
            running = True
            log('relaunch succeeded')
        else:
            status, ok = 'outlook_down', False
            detail = 'Outlook is not running and could not be restarted.'
            log('relaunch FAILED')
    elif running is None:
        # Could not read the process list. Say so rather than guessing healthy.
        status, detail = 'process_check_failed', 'Could not read the task list.'

    ost_age = newest_ost_age_minutes()
    if ok and OST_STALE_MINUTES and status == 'ok':
        if ost_age is None:
            status, detail = 'ost_missing', 'No .ost file found for this profile.'
        elif ost_age > OST_STALE_MINUTES:
            status, ok = 'sync_stalled', False
            detail = ('Outlook is running but the mailbox file has not changed '
                      'in %d minutes.' % int(ost_age))

    record = {
        'name': MACHINE_NAME,
        'ok': ok,
        'status': status,
        'detail': detail,
        'extra': {
            'version': VERSION,
            'outlook_running': running,
            'ost_age_minutes': None if ost_age is None else int(ost_age),
        },
    }

    try:
        code, body = post(record)
        log('posted %s (%s) -> HTTP %s %s' % (status, 'ok' if ok else 'PROBLEM', code, body))
    except (urllib.error.URLError, OSError) as e:
        # The briefing box being unreachable is not this machine's problem to
        # solve, and silence is exactly what the far end alarms on anyway.
        log('post failed: %s' % e)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
