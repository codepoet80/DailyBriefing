"""Thin client for the BlueBubbles server REST API.

All requests authenticate with the server password as a query parameter and
unwrap the standard {status, message, data} response envelope.
https://docs.bluebubbles.app/server/developer-guides/rest-api-and-webhooks
"""
import uuid

import requests


def get_bb_config(config):
    """Return the bluebubbles config dict, or None if not usable."""
    cfg = config.get('bluebubbles', {})
    if not cfg.get('url') or not cfg.get('password'):
        return None
    return cfg


def _request(cfg, method, path, json_body=None, params=None, timeout=15):
    url = cfg['url'].rstrip('/') + path
    params = dict(params or {})
    params['password'] = cfg['password']
    resp = requests.request(method, url, params=params, json=json_body, timeout=timeout)
    resp.raise_for_status()
    return resp.json().get('data')


def query_messages(cfg, after_ms, limit=500):
    """Messages created after the given epoch-ms timestamp, newest first."""
    return _request(cfg, 'POST', '/api/v1/message/query', json_body={
        'after': int(after_ms),
        'limit': limit,
        'offset': 0,
        'sort': 'DESC',
        'with': ['chat', 'chat.participants', 'handle'],
    }) or []


def query_chats(cfg, limit=100):
    """Recent chats ordered by last activity."""
    return _request(cfg, 'POST', '/api/v1/chat/query', json_body={
        'limit': limit,
        'offset': 0,
        'sort': 'lastmessage',
        'with': ['participants'],
    }) or []


def get_contacts(cfg):
    try:
        return _request(cfg, 'GET', '/api/v1/contact') or []
    except Exception:
        return []


def normalize_address(addr):
    """Canonical form for matching: digits-only for phones, lowercase for emails."""
    addr = (addr or '').strip().lower()
    if '@' in addr:
        return addr
    digits = ''.join(ch for ch in addr if ch.isdigit())
    # Drop US country code so +12165551234 matches 2165551234
    if len(digits) == 11 and digits.startswith('1'):
        digits = digits[1:]
    return digits


def contact_name(contact):
    name = (contact.get('displayName') or contact.get('nickname') or '').strip()
    if not name:
        name = ' '.join(p for p in (contact.get('firstName'), contact.get('lastName')) if p).strip()
    return name


def contact_name_map(cfg):
    """Map of normalized address -> contact display name."""
    names = {}
    for contact in get_contacts(cfg):
        name = contact_name(contact)
        if not name:
            continue
        for entry in (contact.get('phoneNumbers') or []) + (contact.get('emails') or []):
            addr = normalize_address(entry.get('address'))
            if addr:
                names.setdefault(addr, name)
    return names


def chat_display_name(chat, names):
    """Human label for a chat: group displayName, else participant contact names."""
    if (chat.get('displayName') or '').strip():
        return chat['displayName'].strip()
    labels = []
    for p in chat.get('participants') or []:
        addr = p.get('address', '')
        labels.append(names.get(normalize_address(addr), addr))
    return ', '.join(labels) if labels else chat.get('chatIdentifier', 'Unknown')


def chat_service(chat):
    """Service name from a chat guid like 'iMessage;-;+12165551234'."""
    return (chat.get('guid') or '').split(';')[0] or 'iMessage'


def send_text(cfg, chat_guid, message):
    """Send a text to an existing chat."""
    return _request(cfg, 'POST', '/api/v1/message/text', json_body={
        'chatGuid': chat_guid,
        'message': message,
        'method': cfg.get('method', 'apple-script'),
        'tempGuid': str(uuid.uuid4()),
    }, timeout=30)


def create_chat(cfg, address, message, service='iMessage'):
    """Create a new chat with one recipient and send the first message."""
    return _request(cfg, 'POST', '/api/v1/chat/new', json_body={
        'addresses': [address],
        'message': message,
        'service': service,
        'method': cfg.get('method', 'apple-script'),
        'tempGuid': str(uuid.uuid4()),
    }, timeout=30)


def resolve_recipient(cfg, recipient):
    """Resolve a name/phone/email to a send target.

    Returns (kind, target, display_name) where kind is 'chat' (target is a
    chat guid) or 'new' (target is a raw address for chat creation).
    Raises ValueError with a user-facing message when a name can't be matched.
    """
    phone_like = recipient.startswith('+') or recipient.replace('-', '').replace(' ', '').replace('(', '').replace(')', '').isdigit()
    email_like = '@' in recipient

    chats = query_chats(cfg)
    names = contact_name_map(cfg)

    if phone_like or email_like:
        want = normalize_address(recipient)
        for chat in chats:
            participants = chat.get('participants') or []
            if len(participants) == 1 and normalize_address(participants[0].get('address')) == want:
                return 'chat', chat['guid'], names.get(want, recipient)
        return 'new', recipient, names.get(want, recipient)

    # Name: match against group display names and participant contact names
    want = recipient.lower()
    for chat in chats:
        label = chat_display_name(chat, names)
        if want in label.lower():
            return 'chat', chat['guid'], label
    raise ValueError(
        f'No chat found matching "{recipient}". Use a phone number or email to start a new thread.'
    )
