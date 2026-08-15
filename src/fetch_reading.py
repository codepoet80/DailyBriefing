#!/usr/bin/env python3
"""Reading progress from the Papyrus eReader.

Two sources, selected by `reading.mode`:

- `account` (default) — the webOS Account cloud storage the community's
  webOS Archive service provides. Papyrus (`syncMode: "account"`) stores one
  record per book at an opaque key `book:<scrambled>` under app id
  `com.palm.codepoet.papyrus`. Keys are deliberately unreadable, but every
  record VALUE unscrambles to the same payload the WebDAV backend used:
  {title, author, position, timestamp, bookmarks}. So we read them all and
  keep the ones whose key is a book.
- `webdav` (legacy) — per-book JSON files in a locally synced `.papyrus`
  directory. Kept for anyone still on the ownCloud/Dropbox sync path.

Both produce the same output shape, consumed by build_briefing.py,
run_agent.py's `reading` rule, and web/index.php.
"""
import json
import os
from datetime import datetime

import webos_account

DEFAULT_APP_ID = 'com.palm.codepoet.papyrus'
BOOK_KEY_PREFIX = 'book:'


def _load_from_account(cfg, base_dir):
    """Return raw book payloads from the webOS Account storage service."""
    acct = cfg.get('account', {})
    login = acct.get('login')
    password = acct.get('password')
    if not login or not password:
        print('    Skipping reading: reading.account.login/password not configured')
        return None

    app_id = acct.get('app_id', DEFAULT_APP_ID)
    session_path = acct.get(
        'session_file', os.path.join(base_dir, 'data', 'webos_session.json')
    )
    session = webos_account.load_session(session_path)

    store = webos_account.WebOSAppStorage(
        app_id=app_id,
        app_name=acct.get('device_name', 'DailyBriefing'),
        base=acct.get('service_base'),
        token=session.get('token'),
        device_id=session.get('device_id') or webos_account.make_device_id(),
    )

    def _sign_in_and_save():
        store.token = None
        store.sign_in(login, password)
        webos_account.save_session(session_path, {
            'token': store.token,
            'device_id': store.device_id,
            'account': store.account,
        })

    try:
        if not store.token:
            _sign_in_and_save()
        try:
            records = store.get_all()
        except webos_account.AuthError:
            # Cached token expired or was revoked (e.g. the account was signed
            # out on the device, which kills tokens server-side) — re-auth once.
            print('    Reading: account token rejected, signing in again')
            _sign_in_and_save()
            records = store.get_all()
    except webos_account.AuthError as e:
        print(f'    Skipping reading: webOS Account sign-in failed ({e})')
        return None
    except Exception as e:
        print(f'    Skipping reading: could not reach webOS Account service ({e})')
        return None

    books = []
    for rec in records:
        key = rec.get('key') or ''
        if not key.startswith(BOOK_KEY_PREFIX):
            continue  # the "settings" record, or anything else the app stores
        value = rec.get('value')
        if not isinstance(value, dict):
            continue  # unreadable blob (rec['raw']) — not scrambled by this app
        books.append(value)
    return books


def _load_from_dir(cfg):
    """Return raw book payloads from a locally synced .papyrus directory."""
    papyrus_dir = os.path.expanduser(
        cfg.get('papyrus_dir', '~/ownCloud/Dropbox/.papyrus')
    )
    if not os.path.exists(papyrus_dir):
        print(f'    Skipping reading: {papyrus_dir} not found')
        return None

    books = []
    for fname in sorted(os.listdir(papyrus_dir)):
        if not fname.endswith('.json'):
            continue
        try:
            with open(os.path.join(papyrus_dir, fname)) as f:
                books.append(json.load(f))
        except Exception:
            continue
    return books


def fetch_reading(config, base_dir=None):
    cfg = config.get('reading', {})
    mode = cfg.get('mode', 'account')
    stagnant_days = cfg.get('stagnant_days', 5)
    max_inactive_days = cfg.get('max_inactive_days', 30)
    exclude_titles = {t.lower() for t in cfg.get('exclude_titles', [])}

    if base_dir is None:
        base_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')

    if mode == 'account':
        raw = _load_from_account(cfg, base_dir)
    elif mode == 'webdav':
        raw = _load_from_dir(cfg)
    else:
        print(f'    Skipping reading: unknown reading.mode "{mode}"')
        return None

    if raw is None:
        return None

    now = datetime.now()
    books = []

    for data in raw:
        title = (data.get('title') or '').strip()
        author = (data.get('author') or '').strip()
        ts_ms = data.get('timestamp', 0)
        position = data.get('position', 0)

        if not title or not ts_ms:
            continue

        last_read_dt = datetime.fromtimestamp(ts_ms / 1000)
        days_since = (now - last_read_dt).days

        if days_since > max_inactive_days:
            continue

        if title.lower() in exclude_titles:
            continue

        if round(position / 100) >= 99:
            continue

        if days_since == 0:
            last_read_label = 'today'
        elif days_since == 1:
            last_read_label = 'yesterday'
        else:
            last_read_label = f'{days_since} days ago'

        books.append({
            'title': title,
            'author': author,
            'last_read_date': last_read_dt.strftime('%Y-%m-%d'),
            'last_read_label': last_read_label,
            'days_since': days_since,
            'stagnant': days_since >= stagnant_days,
            'percent': round(position / 100),
        })

    books.sort(key=lambda b: b['days_since'])
    stagnant = [b for b in books if b['stagnant']]
    print(f'    {len(books)} active book(s), {len(stagnant)} stagnant')

    return {'books': books, 'stagnant': stagnant}
