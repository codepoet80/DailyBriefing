#!/usr/bin/env python3
"""Sweeper for delayed BlueBubbles messages.

Run periodically by a launchd agent (see config/launchd/). Each pass picks up
every due job in data/scheduled_messages/ and tries to deliver it.

Why a sweep instead of a sleeping process: the original design spawned a
detached worker that slept until the due time and sent once. It fired on time
but had no memory — when a send failed, the job rotted on disk, nothing retried,
and nothing told anyone. On 2026-08-10 two messages timed out that way: one was
never delivered at all, the other surfaced three days later when the stuck
AppleScript call finally completed. A sweep survives reboots, retries, and
reports.

The rule that makes retrying safe: **a timeout is not a failure, it is an
unknown**. BlueBubbles can time out client-side while the send is still in
flight inside Messages. So before every attempt the job is checked against the
message history (`already_delivered`); a job whose text already appears in the
target thread is closed out rather than sent again.

Job file (data/scheduled_messages/<uuid>.json):
  {send_at (ISO/UTC), kind ("chat"|"new"), target, service, message,
   display_name, attempts, last_error, last_attempt}

Terminal outcomes move the file to failed/ or expired/ rather than deleting it,
so nothing disappears silently.
"""
import contextlib
import fcntl
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone

BASE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bluebubbles as bb  # noqa: E402

SCHED_DIR = os.path.join(BASE_DIR, 'data', 'scheduled_messages')
FAILED_DIR = os.path.join(SCHED_DIR, 'failed')
EXPIRED_DIR = os.path.join(SCHED_DIR, 'expired')
LOCK_PATH = os.path.join(SCHED_DIR, '.sweep.lock')

# Give up rather than deliver a reminder long after it was any use. Sized well
# above the sweep interval so an ordinary late sweep still sends.
MAX_LATE = timedelta(hours=2)
MAX_ATTEMPTS = 5
# How far back to look when checking whether a job already went out.
LOOKBACK = timedelta(minutes=15)
# Must match StartInterval in the launchd plist. Delays shorter than this get a
# one-shot timer as well, so "in 5 minutes" isn't rounded up to the next sweep.
SWEEP_INTERVAL = timedelta(minutes=10)
# After a send the server accepted but we cannot yet see, wait this long before
# considering another attempt. Duplicates are worse than a small delay.
RESEND_GRACE = timedelta(minutes=30)
# Longest single nap in the one-shot timer. Short hops mean the wall clock is
# re-read often: time.sleep() is monotonic and does NOT advance while a Mac is
# asleep, so one long sleep would overshoot by however long the lid was shut.
TIMER_TICK = 30


def _log(msg):
    print('[scheduled_send] %s %s' % (datetime.now().isoformat(timespec='seconds'), msg),
          flush=True)


def _load_config():
    with open(os.path.join(BASE_DIR, 'config', 'config.json')) as f:
        return json.load(f)


def _notify(config, title, message, priority=0):
    """Best-effort Pushover alert. Never let a notification failure mask the
    delivery outcome we are trying to report."""
    try:
        from run_agent import send_pushover
        agent = config.get('agent', {})
        token, user = agent.get('pushover_app_token'), agent.get('pushover_user_key')
        if token and user:
            send_pushover(token, user, title, message, priority)
    except Exception as e:
        _log('could not send Pushover alert: %s' % e)


def already_delivered(cfg, job, send_at):
    """True when this job's text is already in the target thread AND went out
    cleanly (`error == 0`).

    Guards against the timed-out-but-actually-sent case. The error check is not
    optional: a send that fails still leaves a message row behind (e.g. error 4,
    no dateDelivered), and counting that as delivered would silently drop the
    message — precisely the failure this sweeper exists to prevent.
    """
    after = send_at - LOOKBACK
    try:
        msgs = bb.query_messages(cfg, int(after.timestamp() * 1000), limit=1000)
    except Exception as e:
        _log('could not check history (%s) — assuming not delivered' % e)
        return False

    return any(_matches_job(m, job) and (m.get('error') or 0) == 0 for m in msgs)


def job_target_address(job):
    """The single address a job is aimed at, or None for a group thread.

    A 1:1 chat guid looks like 'iMessage;-;+12165551234'; the '+' form is a
    group and has no single address.
    """
    target = job.get('target') or ''
    if job.get('kind') == 'new':
        return bb.normalize_address(target)
    parts = target.split(';')
    if len(parts) == 3 and parts[1] == '-':
        return bb.normalize_address(parts[2])
    return None


def chat_guid_address(guid):
    """Recipient address out of a 1:1 chat guid ('iMessage;-;+1216...'), else
    None for a group ('...;+;chat123...').

    Parsed from the guid rather than the chat's participants list because
    message/query returns participants empty even when asked for them.
    """
    parts = (guid or '').split(';')
    if len(parts) == 3 and parts[1] == '-':
        return bb.normalize_address(parts[2])
    return None


_ADDRESS_GROUPS = None


def _address_groups():
    """Sets of normalized addresses that belong to one person, from Contacts."""
    global _ADDRESS_GROUPS
    if _ADDRESS_GROUPS is None:
        _ADDRESS_GROUPS = []
        try:
            import contacts_mac
            for c in contacts_mac.load_contacts():
                addrs = {p['normalized'] for p in c.get('phones') or [] if p.get('normalized')}
                addrs |= {e['normalized'] for e in c.get('emails') or [] if e.get('normalized')}
                if len(addrs) > 1:
                    _ADDRESS_GROUPS.append(addrs)
        except Exception as e:
            _log('Contacts unavailable for address matching (%s)' % e)
    return _ADDRESS_GROUPS


def equivalent_addresses(addr):
    """Every address that reaches the same person as `addr`.

    iMessage delivers to an Apple ID, not to the handle you aimed at: a send to
    someone's work number lands in the iMessage thread for their mobile. Judging
    delivery by the target handle alone therefore marks a delivered message
    unconfirmed, and the next sweep sends it AGAIN. That happened for real.
    """
    if not addr:
        return set()
    out = {addr}
    for group in _address_groups():
        if addr in group:
            out |= group
    return out


def _matches_job(m, job):
    """Is this outgoing message the one this job was trying to send?

    Matched on recipient rather than chat guid, and across every handle that
    reaches that person — see equivalent_addresses().
    """
    if not m.get('isFromMe'):
        return False
    if (m.get('text') or '').strip() != (job.get('message') or '').strip():
        return False
    want = equivalent_addresses(job_target_address(job))
    for chat in m.get('chats') or []:
        if chat.get('guid') == job.get('target'):
            return True
        landed = chat_guid_address(chat.get('guid'))
        if landed and landed in want:
            return True
    return False


def confirm_send(cfg, job, send_at, tries=5, pause=3):
    """After the API accepts a send, wait briefly for the message to show up
    clean in the history.

    A 200 from BlueBubbles only means the request was accepted, not that
    iMessage delivered anything: an undeliverable send returns 200 and then
    lands with error=4. Returns True (confirmed), False (a row exists but
    errored) or None (nothing yet — undecided, let the next sweep re-check).
    """
    for attempt in range(tries):
        if already_delivered(cfg, job, send_at):
            return True
        if _errored_copy(cfg, job, send_at):
            return False
        if attempt < tries - 1:
            time.sleep(pause)
    return None


def _errored_copy(cfg, job, send_at):
    """True when our text is in the thread but flagged with a send error."""
    try:
        msgs = bb.query_messages(cfg, int((send_at - LOOKBACK).timestamp() * 1000), limit=1000)
    except Exception:
        return False
    return any(_matches_job(m, job) and (m.get('error') or 0) != 0 for m in msgs)


def _move(job_path, dest_dir):
    os.makedirs(dest_dir, exist_ok=True)
    dest = os.path.join(dest_dir, os.path.basename(job_path))
    os.replace(job_path, dest)
    return dest


def _save(job_path, job):
    with open(job_path, 'w') as f:
        json.dump(job, f)


def process_job(cfg, config, job_path, now):
    """Handle one job file. Returns a short status string for logging."""
    try:
        with open(job_path) as f:
            job = json.load(f)
    except (OSError, ValueError) as e:
        _log('unreadable job %s: %s' % (os.path.basename(job_path), e))
        return 'unreadable'

    try:
        send_at = datetime.fromisoformat(job['send_at'])
        if send_at.tzinfo is None:
            send_at = send_at.replace(tzinfo=timezone.utc)
    except (KeyError, ValueError):
        _log('job %s has no usable send_at — moving to failed/' % os.path.basename(job_path))
        _move(job_path, FAILED_DIR)
        return 'malformed'

    who = job.get('display_name', job.get('target', '?'))

    if now < send_at:
        return 'pending'

    # Already out? Covers a previous attempt that timed out but landed anyway.
    if already_delivered(cfg, job, send_at):
        _log('already delivered to %s — closing job' % who)
        _move(job_path, EXPIRED_DIR)
        return 'already-delivered'

    if now - send_at > MAX_LATE:
        late = now - send_at
        _log('EXPIRED for %s (due %s, %s late) — not sending'
             % (who, send_at.astimezone().strftime('%Y-%m-%d %H:%M'), _human(late)))
        _move(job_path, EXPIRED_DIR)
        _notify(config, 'Scheduled message expired',
                'Never sent to %s (%s late): %s' % (who, _human(late), job.get('message', '')[:80]),
                priority=1)
        return 'expired'

    # A previous attempt was accepted by the server but never confirmed. Do not
    # fire another send straight away: an accepted-but-unseen message is far
    # more likely to be in flight than lost, and re-sending is what puts two
    # copies in someone's thread. Only a visible send error, or a long silence
    # with nothing recorded at all, justifies trying again.
    accepted_at = job.get('accepted_at')
    if accepted_at:
        try:
            accepted_dt = datetime.fromisoformat(accepted_at)
        except ValueError:
            accepted_dt = None
        if accepted_dt and not _errored_copy(cfg, job, send_at):
            if now - accepted_dt < RESEND_GRACE:
                _log('%s: accepted %s ago, still unconfirmed — waiting, not resending'
                     % (who, _human(now - accepted_dt)))
                return 'awaiting'

    job['attempts'] = job.get('attempts', 0) + 1
    job['last_attempt'] = now.isoformat(timespec='seconds')

    def give_up_or_retry():
        _log('attempt %d/%d failed for %s: %s'
             % (job['attempts'], MAX_ATTEMPTS, who, job['last_error']))
        if job['attempts'] >= MAX_ATTEMPTS:
            _save(job_path, job)
            _move(job_path, FAILED_DIR)
            _notify(config, 'Scheduled message failed',
                    'Gave up after %d attempts to %s: %s\nLast error: %s'
                    % (job['attempts'], who, job.get('message', '')[:60], job['last_error'][:120]),
                    priority=1)
            return 'failed'
        _save(job_path, job)
        return 'retry'

    try:
        if job['kind'] == 'chat':
            bb.send_text(cfg, job['target'], job['message'])
        else:
            bb.create_chat(cfg, job['target'], job['message'], job.get('service', 'iMessage'))
    except Exception as e:
        job['last_error'] = str(e)[:300]
        return give_up_or_retry()

    # Accepted != delivered. Confirm against the message history before
    # treating this as done.
    confirmed = confirm_send(cfg, job, send_at)
    if confirmed is True:
        _log('sent to %s: %s' % (who, job['message'][:60]))
        os.remove(job_path)
        return 'sent'
    if confirmed is False:
        job['last_error'] = 'iMessage reported a send error (message not delivered)'
        return give_up_or_retry()
    # Undecided: nothing in the history yet. Leave it for the next sweep, which
    # re-checks delivery before doing anything else, so a slow-but-successful
    # send is closed out rather than sent twice.
    job['last_error'] = 'accepted but not yet confirmed in history'
    job['accepted_at'] = now.isoformat(timespec='seconds')
    _log('send to %s accepted, awaiting confirmation' % who)
    _save(job_path, job)
    return 'unconfirmed'


def _human(delta):
    mins = int(delta.total_seconds() // 60)
    if mins < 60:
        return '%dm' % mins
    if mins < 1440:
        return '%dh%02dm' % (mins // 60, mins % 60)
    return '%dd%dh' % (mins // 1440, (mins % 1440) // 60)


@contextlib.contextmanager
def _exclusive(what):
    """Serialize every path that can send: the sweep and any one-shot timer.
    Without this a timer firing at 3:36 and the 3:36 sweep could both send."""
    os.makedirs(SCHED_DIR, exist_ok=True)
    lock = open(LOCK_PATH, 'w')
    try:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield True
    finally:
        fcntl.flock(lock, fcntl.LOCK_UN)
        lock.close()


def run_once(job_path):
    """Precise one-shot delivery for a short delay.

    Waits until the job is due and processes it immediately, so "in 5 minutes"
    is not rounded up to the next 10-minute sweep. This is punctuality only —
    the sweeper still owns the job. If this process is killed (reboot, logout)
    the job file is untouched and the next sweep delivers it, and because the
    file is only removed once delivery is *confirmed*, the two cannot
    double-send.
    """
    name = os.path.basename(job_path)
    while True:
        if not os.path.exists(job_path):
            _log('timer: job %s already handled — exiting' % name)
            return 0
        try:
            with open(job_path) as f:
                send_at = datetime.fromisoformat(json.load(f)['send_at'])
        except (OSError, ValueError, KeyError) as e:
            _log('timer: cannot read %s (%s) — leaving it to the sweeper' % (name, e))
            return 1
        if send_at.tzinfo is None:
            send_at = send_at.replace(tzinfo=timezone.utc)
        remaining = (send_at - datetime.now(timezone.utc)).total_seconds()
        if remaining <= 0:
            break
        time.sleep(min(remaining, TIMER_TICK))

    with _exclusive('timer'):
        if not os.path.exists(job_path):
            _log('timer: job %s handled by a sweep — nothing to do' % name)
            return 0
        config = _load_config()
        cfg = bb.get_bb_config(config)
        if not cfg:
            _log('timer: bluebubbles not configured — leaving %s for the sweeper' % name)
            return 1
        status = process_job(cfg, config, job_path, datetime.now(timezone.utc))
        _log('timer: %s -> %s' % (name, status))
        return 0


def sweep():
    os.makedirs(SCHED_DIR, exist_ok=True)
    # One sweep at a time — overlapping passes could double-send.
    lock = open(LOCK_PATH, 'w')
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        _log('another sweep is running — skipping')
        return 0

    try:
        jobs = sorted(f for f in os.listdir(SCHED_DIR) if f.endswith('.json'))
        if not jobs:
            return 0
        config = _load_config()
        cfg = bb.get_bb_config(config)
        if not cfg:
            _log('bluebubbles not configured — leaving %d job(s)' % len(jobs))
            return 1

        now = datetime.now(timezone.utc)
        counts = {}
        for fname in jobs:
            status = process_job(cfg, config, os.path.join(SCHED_DIR, fname), now)
            counts[status] = counts.get(status, 0) + 1
        if set(counts) - {'pending'}:
            _log('sweep: ' + ', '.join('%s=%d' % kv for kv in sorted(counts.items())))
        return 0
    finally:
        fcntl.flock(lock, fcntl.LOCK_UN)
        lock.close()


if __name__ == '__main__':
    mode = sys.argv[1] if len(sys.argv) > 1 else 'sweep'
    if mode == 'sweep':
        sys.exit(sweep())
    if mode == 'once' and len(sys.argv) == 3:
        sys.exit(run_once(sys.argv[2]))
    print('usage: scheduled_send.py [sweep | once <job.json>]', file=sys.stderr)
    sys.exit(2)
