"""Check that locally-running application servers on this box are alive.

Each configured service is one of two check types:
  - "process" (default): the `match` string appears in `ps aux` output
  - "docker": the `match` string appears in running `docker ps` output

`ps aux` / `docker ps` are each run at most once per build and reused across
all services. A service whose match is absent is reported down.

Returns None when nothing is configured, else:
  { "all_up": bool, "services": [ {"name", "up", "type"} ] }
"""
import os
import subprocess

# cron runs run.sh with a bare PATH (/usr/bin:/bin), so `docker` — installed at
# /usr/local/bin or a Homebrew/Docker.app location — isn't found and every
# docker-type service would falsely read as down. Prepend the usual locations
# so the lookup works under cron as well as an interactive shell.
_EXTRA_PATHS = ['/usr/local/bin', '/opt/homebrew/bin',
                '/Applications/Docker.app/Contents/Resources/bin']


def _env():
    env = dict(os.environ)
    parts = _EXTRA_PATHS + env.get('PATH', '').split(os.pathsep)
    seen, ordered = set(), []
    for p in parts:
        if p and p not in seen:
            seen.add(p)
            ordered.append(p)
    env['PATH'] = os.pathsep.join(ordered)
    return env


def _run(cmd, exclude_pid=None):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=10, env=_env())
        if r.returncode != 0:
            return ''
        out = r.stdout
        if exclude_pid is not None:
            # Drop this checker's own process line so a service match string
            # that happens to appear in our argv (e.g. build_briefing.py) can't
            # match itself. PID is the 2nd whitespace field of `ps aux`.
            pid = str(exclude_pid)
            out = '\n'.join(ln for ln in out.splitlines()
                            if ln.split()[1:2] != [pid])
        return out.lower()
    except Exception as e:
        print('    Warning: ' + ' '.join(cmd) + ' failed: ' + str(e))
        return ''


def fetch_local_services(config):
    services = config.get('local_services', [])
    if not services:
        return None

    caches = {}

    def source(kind):
        if kind not in caches:
            caches[kind] = _run(['ps', 'aux'], exclude_pid=os.getpid()) if kind == 'process' else \
                _run(['docker', 'ps', '--format', '{{.Names}} {{.Image}} {{.Status}}'])
        return caches[kind]

    results = []
    all_up = True
    for svc in services:
        name = svc.get('name', '?')
        stype = svc.get('type', 'process')
        match = (svc.get('match') or name).lower()
        up = match in source('docker' if stype == 'docker' else 'process')
        results.append({'name': name, 'up': up, 'type': stype})
        if not up:
            all_up = False
        print('    ' + name + ': ' + ('up' if up else 'DOWN'))

    down = [r['name'] for r in results if not r['up']]
    print('    ' + ('All local services up' if all_up
                    else str(len(down)) + ' down: ' + ', '.join(down)))
    return {'all_up': all_up, 'services': results}
