"""Per-device chat session store.

Each chat client (browser cookie) gets a JSON file under data/chat_sessions/.
Sessions hold a rolling window of turns plus the active dialectic id (if any).
"""
import json
import os
import re
import secrets
import time
from datetime import datetime

SESSION_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    'data', 'chat_sessions',
)

_SAFE_ID = re.compile(r'^[A-Za-z0-9_-]{8,64}$')


def _now():
    return datetime.now().isoformat(timespec='seconds')


def _path(session_id):
    return os.path.join(SESSION_DIR, f'{session_id}.json')


def ensure_dir():
    os.makedirs(SESSION_DIR, exist_ok=True)


def new_session_id():
    return secrets.token_urlsafe(18)


def is_valid_id(session_id):
    return bool(session_id) and bool(_SAFE_ID.match(session_id))


def load(session_id):
    if not is_valid_id(session_id):
        return None
    p = _path(session_id)
    if not os.path.exists(p):
        return None
    try:
        with open(p) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def save(session_id, state):
    ensure_dir()
    state['last_used'] = _now()
    tmp = _path(session_id) + '.tmp'
    with open(tmp, 'w') as f:
        json.dump(state, f, indent=2)
    os.replace(tmp, _path(session_id))


def new_state():
    return {
        'created_at': _now(),
        'last_used': _now(),
        'turns': [],
        'active_dialectic_id': None,
    }


def append_turn(state, role, content):
    state['turns'].append({'role': role, 'content': content, 'at': _now()})


def trim(state, max_turns):
    if max_turns and len(state['turns']) > max_turns:
        state['turns'] = state['turns'][-max_turns:]


def prune(ttl_hours):
    """Delete session files idle for longer than ttl_hours."""
    if not os.path.isdir(SESSION_DIR):
        return 0
    cutoff = time.time() - (ttl_hours * 3600)
    removed = 0
    for name in os.listdir(SESSION_DIR):
        if not name.endswith('.json'):
            continue
        p = os.path.join(SESSION_DIR, name)
        try:
            if os.path.getmtime(p) < cutoff:
                os.remove(p)
                removed += 1
        except OSError:
            pass
    return removed


if __name__ == '__main__':
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == 'prune':
        hours = float(sys.argv[2]) if len(sys.argv) > 2 else 24
        n = prune(hours)
        print(f'Pruned {n} session(s) older than {hours}h')
