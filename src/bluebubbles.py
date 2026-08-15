"""Thin client for the BlueBubbles server REST API.

All requests authenticate with the server password as a query parameter and
unwrap the standard {status, message, data} response envelope.
https://docs.bluebubbles.app/server/developer-guides/rest-api-and-webhooks
"""
import uuid

import requests

import contacts_mac

# Chats are matched by address, and a thread that has been quiet for months
# still sorts last. The old default of 100 silently missed those and fell back
# to creating a new chat, which needs the Private API and fails under
# apple-script. Cover the whole list instead.
CHAT_QUERY_LIMIT = 1000

# An apple-script send can sit inside Messages for a long time before returning.
# 30s was low enough that healthy-but-slow sends looked like failures; the
# sweeper now treats a timeout as "unknown" and verifies, but a longer window
# still means fewer ambiguous outcomes to reconcile.
SEND_TIMEOUT = 90


class AmbiguousRecipient(Exception):
    """More than one contact/number could be meant. Carries a pick-list."""

    def __init__(self, reason, options):
        super().__init__(reason)
        self.reason = reason
        self.options = options


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


def query_chats(cfg, limit=CHAT_QUERY_LIMIT):
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
    }, timeout=SEND_TIMEOUT)


def create_chat(cfg, address, message, service='iMessage'):
    """Create a new chat with one recipient and send the first message."""
    return _request(cfg, 'POST', '/api/v1/chat/new', json_body={
        'addresses': [address],
        'message': message,
        'service': service,
        'method': cfg.get('method', 'apple-script'),
        'tempGuid': str(uuid.uuid4()),
    }, timeout=SEND_TIMEOUT)


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

    def direct_chat(address, display):
        """Existing one-on-one thread for an address, else a new-chat target.
        Chats come back newest-first, so the first hit is the thread most
        recently used with that person."""
        want = normalize_address(address)
        for chat in chats:
            participants = chat.get('participants') or []
            if len(participants) == 1 and normalize_address(participants[0].get('address')) == want:
                return 'chat', chat['guid'], display or names.get(want, address)
        return 'new', address, display or names.get(want, address)

    if phone_like or email_like:
        return direct_chat(recipient, None)

    # Names resolve against this Mac's Contacts first. Matching against recent
    # chats instead is how a personal name once resolved to a nine-person group
    # whose participant list happened to contain that person.
    status, payload = (None, None)
    try:
        status, payload = contacts_mac.resolve_name(recipient)
    except Exception:
        status = None  # Contacts unreadable — fall through to chat matching

    # A confident contact match (exact full/first/last name) wins outright.
    if status == 'found' and payload.get('tier', 0) <= 1:
        return direct_chat(payload['address'], payload['name'])

    # Otherwise a named group thread beats a weak contact hit, so "Family"
    # reaches the family group rather than a contact filed under "Family
    # Dental". Only a group's own displayName counts: matching the synthesized
    # "Alice, Bob, Carol" participant label is what sent a personal name to a
    # nine-person group, so a name must never reach a thread that way.
    want = recipient.strip().lower()
    named = [c for c in chats if (c.get('displayName') or '').strip()]
    exact = [c for c in named if c['displayName'].strip().lower() == want]
    partial = [c for c in named if want in c['displayName'].strip().lower()]
    # An exact group name always wins. A partial one only when Contacts had
    # nothing to say — otherwise "Wise" would reach a group named "WiseGirlz"
    # instead of asking which of ten people named Wise was meant.
    group = exact[0] if exact else (
        partial[0] if len(partial) == 1 and status != 'ambiguous' else None)
    if group is not None:
        return 'chat', group['guid'], group['displayName'].strip()
    if not exact and len(partial) > 1 and status != 'ambiguous':
        raise AmbiguousRecipient(
            'several group chats match "%s"' % recipient,
            [{'name': c['displayName'].strip(), 'address': c['guid'], 'label': 'group'}
             for c in partial])

    # Weak-but-specific contact match (all words present, e.g. "Sam Okafor"
    # inside "Robin & Sam Okafor"). A bare substring hit is too loose to send on.
    if status == 'found' and payload.get('tier', 0) <= 2:
        return direct_chat(payload['address'], payload['name'])
    if status == 'found':
        raise AmbiguousRecipient(
            'only a loose match for "%s"' % recipient,
            [{'name': payload['name'], 'address': payload['address'],
              'label': payload.get('label', '')}])
    if status == 'ambiguous':
        raise AmbiguousRecipient(payload['reason'], payload['options'])

    # Contacts unreadable (no Full Disk Access) or the name isn't in it: fall
    # back to BlueBubbles' own contact list. Exact name match only — it carries
    # no Mobile/Work labels, so there is nothing to choose between numbers with.
    hits, phone_hits = [], []
    for contact in get_contacts(cfg):
        if contact_name(contact).strip().lower() != want:
            continue
        for entry in (contact.get('phoneNumbers') or []) + (contact.get('emails') or []):
            if entry.get('address'):
                hits.append((contact_name(contact), entry['address']))
        for entry in contact.get('phoneNumbers') or []:
            if entry.get('address'):
                phone_hits.append((contact_name(contact), entry['address']))
    # A single phone number is unambiguous even when emails are also on file.
    if len(phone_hits) == 1:
        return direct_chat(phone_hits[0][1], phone_hits[0][0])
    if len(hits) == 1:
        return direct_chat(hits[0][1], hits[0][0])
    if len(hits) > 1:
        raise AmbiguousRecipient(
            'several numbers for "%s" (Contacts unavailable, so no Mobile/Work '
            'labels to choose by)' % recipient,
            [{'name': n, 'address': a, 'label': ''} for n, a in hits])

    raise ValueError(
        f'No contact or chat found matching "{recipient}". '
        f'Use a phone number or email to start a new thread.'
    )
