#!/usr/bin/env python3
"""Dead-man's-switch monitoring for machines that report in to web/heartbeat.php.

Unlike fetch_local_services (processes on this box) and fetch_servers (remote
HTTP status pages we poll), these machines cannot be reached from here — the
locked-down Windows laptop this was built for accepts no inbound connections.
So it pushes, and we alarm on **silence**. That is the whole point: a machine
that has been shut down, lost its network, or whose reporting script has died
cannot tell us anything, and each of those is exactly the failure worth knowing
about.

Two independent failure modes, deliberately kept separate:
  - stale   — no heartbeat within `stale_minutes`. Covers power/network/script.
  - not ok  — a heartbeat arrived saying something is wrong (Outlook down and
              could not be relaunched). Detected within one heartbeat interval
              rather than waiting out the staleness window.

Returns None when nothing is configured, else:
  {"all_ok": bool,
   "machines": [{name, label, ok, stale, status, detail, age_minutes,
                 last_seen, last_seen_label, problem}]}
"""
import json
import os
from datetime import datetime, timezone

from paths import data_path

DEFAULT_STALE_MINUTES = 25


def _read(path):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _age_label(minutes):
    if minutes is None:
        return 'never'
    if minutes < 1:
        return 'just now'
    if minutes < 60:
        return f'{int(minutes)} min ago'
    hours = minutes / 60
    if hours < 24:
        return f'{int(hours)}h ago'
    return f'{int(hours / 24)}d ago'


def fetch_heartbeats(config, now=None):
    cfg = config.get('heartbeats') or {}
    machines_cfg = cfg.get('machines') or []
    if not cfg.get('enabled') or not machines_cfg:
        return None

    hb_dir = data_path('heartbeats')
    now = now or datetime.now(timezone.utc)
    default_stale = int(cfg.get('stale_minutes', DEFAULT_STALE_MINUTES))

    machines = []
    for entry in machines_cfg:
        name = entry.get('name')
        if not name:
            continue
        stale_minutes = int(entry.get('stale_minutes', default_stale))
        record = _read(os.path.join(hb_dir, f'{name}.json'))

        age = None
        if record:
            try:
                seen = datetime.fromisoformat(record['received_at'])
                if seen.tzinfo is None:
                    seen = seen.replace(tzinfo=timezone.utc)
                age = max(0.0, (now - seen).total_seconds() / 60.0)
            except (KeyError, ValueError):
                age = None

        # No file at all reads as stale, not as healthy. A machine that has
        # never reported is not a machine that is fine.
        stale = age is None or age > stale_minutes
        reported_ok = bool(record.get('ok', True)) if record else False
        ok = (not stale) and reported_ok

        if stale:
            problem = ('no heartbeat yet' if age is None
                       else f'last seen {_age_label(age)}')
        elif not reported_ok:
            problem = (record.get('detail') or record.get('status')
                       or 'reported a problem')
        else:
            problem = ''

        machines.append({
            'name': name,
            'label': entry.get('label') or name,
            'ok': ok,
            'stale': stale,
            'status': (record or {}).get('status', ''),
            'detail': (record or {}).get('detail', ''),
            'age_minutes': None if age is None else int(age),
            'last_seen': (record or {}).get('received_at', ''),
            'last_seen_label': _age_label(age),
            'stale_minutes': stale_minutes,
            'problem': problem,
        })

    down = [m for m in machines if not m['ok']]
    print(f'    {len(machines)} heartbeat machine(s), {len(down)} needing attention')
    return {'all_ok': not down, 'machines': machines}
