#!/usr/bin/env python3
"""Name -> phone/email lookup against this Mac's Contacts (Address Book).

Reads the Contacts SQLite stores directly, read-only:

    ~/Library/Application Support/AddressBook/AddressBook-v22.abcddb
    ~/Library/Application Support/AddressBook/Sources/<uuid>/AddressBook-v22.abcddb

One store per account (iCloud, Google, Exchange, On My Mac), so the same person
can appear more than once with different labels on the same number. Records are
merged by normalized name and numbers deduped by digits.

Why not BlueBubbles' /api/v1/contact: it only exposes one source (232 of this
Mac's 335 contacts here) and returns numbers with no labels, so it cannot tell a
mobile from a work line. Contacts has both. BlueBubbles remains the fallback when
this database is unreadable.

Opened with `?immutable=1` — no locking, no writes, safe against a live Contacts
app. Requires the calling process to hold Full Disk Access (or Contacts access);
`available()` reports whether that is the case rather than raising.
"""
import glob
import json
import os
import re
import sqlite3

ADDRESSBOOK_DIR = os.path.expanduser('~/Library/Application Support/AddressBook')

# Apple stores labels as _$!<Mobile>!$_; iPhone/custom labels come through bare.
_LABEL_RE = re.compile(r'^_\$!<(.+)>!\$_$')

# Preference when a contact has several numbers and the user didn't say which.
# Mobile first, then pager — in this address book Pager is not a real pager, it
# is the second person of a couple (see couple_gender() below) — then landlines.
LABEL_RANK = {
    'iphone': 0,
    'mobile': 1,
    'pager': 2,
    'main': 3,
    'home': 4,
    'work': 5,
    'other': 6,
}
_UNLABELED_RANK = 7

# "Alex and Dana Rivera", "Robin & Sam Okafor"
_COUPLE_RE = re.compile(r'^\s*(.+?)\s+(?:and|&)\s+(.+?)\s*$', re.I)

CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           '..', 'config', 'config.json')
_COUPLE_GENDER = None


def couple_gender():
    """{first name: 'm'|'f'} from `contacts.couple_gender` in config.json.

    Lives in config, not here, because it is a list of real people from the
    user's address book — and config.json is gitignored while this file is not.
    A name that is absent produces a pick-list rather than a guess, so an empty
    or missing table degrades to "always ask", never to a wrong recipient.
    """
    global _COUPLE_GENDER
    if _COUPLE_GENDER is None:
        try:
            with open(CONFIG_PATH) as f:
                table = (json.load(f).get('contacts') or {}).get('couple_gender') or {}
            _COUPLE_GENDER = {str(k).strip().lower(): v for k, v in table.items()}
        except (OSError, ValueError):
            _COUPLE_GENDER = {}
    return _COUPLE_GENDER


def _clean_label(raw):
    if not raw:
        return ''
    m = _LABEL_RE.match(raw)
    return (m.group(1) if m else raw).strip().lower()


def normalize_number(addr):
    """Digits-only for phones, lowercased for emails. Mirrors
    bluebubbles.normalize_address so the two can be compared directly."""
    addr = (addr or '').strip().lower()
    if '@' in addr:
        return addr
    digits = ''.join(ch for ch in addr if ch.isdigit())
    if len(digits) == 11 and digits.startswith('1'):
        digits = digits[1:]
    return digits


def normalize_name(name):
    """Casefolded, punctuation-stripped, single-spaced."""
    s = re.sub(r"[.,'\-_]", ' ', (name or '').lower())
    return ' '.join(s.split())


def store_paths():
    paths = []
    top = os.path.join(ADDRESSBOOK_DIR, 'AddressBook-v22.abcddb')
    if os.path.exists(top):
        paths.append(top)
    paths.extend(sorted(glob.glob(
        os.path.join(ADDRESSBOOK_DIR, 'Sources', '*', 'AddressBook-v22.abcddb'))))
    return paths


def _read_store(path):
    """Return [{name, first, last, nickname, org, phones, emails}] from one store."""
    uri = 'file:%s?immutable=1' % path.replace('?', '%3f').replace('#', '%23')
    conn = sqlite3.connect(uri, uri=True, timeout=5)
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT Z_PK, ZFIRSTNAME, ZLASTNAME, ZNICKNAME, ZORGANIZATION
            FROM ZABCDRECORD
            WHERE ZFIRSTNAME IS NOT NULL OR ZLASTNAME IS NOT NULL
               OR ZNICKNAME IS NOT NULL OR ZORGANIZATION IS NOT NULL
        """)
        people = {}
        for pk, first, last, nick, org in cur.fetchall():
            people[pk] = {
                'first': (first or '').strip(),
                'last': (last or '').strip(),
                'nickname': (nick or '').strip(),
                'org': (org or '').strip(),
                'phones': [],
                'emails': [],
            }

        cur.execute('SELECT ZOWNER, ZFULLNUMBER, ZLABEL FROM ZABCDPHONENUMBER')
        for owner, number, label in cur.fetchall():
            if owner in people and (number or '').strip():
                people[owner]['phones'].append({
                    'number': number.strip(),
                    'normalized': normalize_number(number),
                    'label': _clean_label(label),
                })

        cur.execute('SELECT ZOWNER, ZADDRESS, ZLABEL FROM ZABCDEMAILADDRESS')
        for owner, addr, label in cur.fetchall():
            if owner in people and (addr or '').strip():
                people[owner]['emails'].append({
                    'address': addr.strip(),
                    'normalized': normalize_number(addr),
                    'label': _clean_label(label),
                })
    finally:
        conn.close()

    out = []
    for p in people.values():
        p['name'] = ' '.join(x for x in (p['first'], p['last']) if x) or p['org'] or p['nickname']
        if p['name']:
            out.append(p)
    return out


def available():
    """(ok, reason) — whether the Contacts stores can actually be read."""
    paths = store_paths()
    if not paths:
        return False, 'no Address Book database found at %s' % ADDRESSBOOK_DIR
    for path in paths:
        try:
            _read_store(path)
            return True, ''
        except sqlite3.OperationalError as e:
            last = str(e)
        except Exception as e:  # pragma: no cover - defensive
            last = str(e)
    return False, ('cannot read Contacts (%s) — grant Full Disk Access to the '
                   'process running the briefing' % last)


def _merge(contacts):
    """Merge the same person across account stores; dedupe numbers by digits."""
    merged = {}
    for c in contacts:
        key = normalize_name(c['name'])
        if not key:
            continue
        if key not in merged:
            merged[key] = {
                'name': c['name'], 'first': c['first'], 'last': c['last'],
                'nickname': c['nickname'], 'org': c['org'],
                'phones': [], 'emails': [],
            }
        tgt = merged[key]
        for field, id_key in (('phones', 'normalized'), ('emails', 'normalized')):
            for entry in c[field]:
                if not entry[id_key]:
                    continue
                existing = next((e for e in tgt[field]
                                 if e[id_key] == entry[id_key]), None)
                if existing is None:
                    tgt[field].append(dict(entry))
                else:
                    # Same number in two accounts, different labels — keep the
                    # one that ranks better for texting (Mobile beats Home).
                    if _rank(entry['label']) < _rank(existing['label']):
                        existing['label'] = entry['label']
        for k in ('nickname', 'org', 'first', 'last'):
            if not tgt[k] and c[k]:
                tgt[k] = c[k]
    return list(merged.values())


def _rank(label):
    return LABEL_RANK.get((label or '').lower(), _UNLABELED_RANK)


def load_contacts():
    """All contacts from every readable store, merged. [] if unreadable."""
    all_rows = []
    for path in store_paths():
        try:
            all_rows.extend(_read_store(path))
        except Exception:
            continue  # one unreadable store shouldn't sink the rest
    return _merge(all_rows)


def best_phone(contact):
    """Preferred number for texting, or None. Labels first, original order
    breaks ties (Contacts keeps the user's own ordering)."""
    phones = [p for p in contact.get('phones') or [] if p.get('normalized')]
    if not phones:
        return None
    return min(phones, key=lambda p: _rank(p['label']))


def textable_phones(contact):
    """Numbers that plausibly receive texts, best first."""
    phones = [p for p in contact.get('phones') or [] if p.get('normalized')]
    return sorted(phones, key=lambda p: _rank(p['label']))


def find_scored(query, contacts=None):
    """[(tier, contact)] matching a name, best tier first.

    Tiers, strongest first: 0 exact full name or nickname, 1 exact first or last
    name, 2 all query words present, 3 substring. Ties keep alphabetical order so
    the result is stable run to run.
    """
    if contacts is None:
        contacts = load_contacts()
    q = normalize_name(query)
    if not q:
        return []
    q_words = q.split()

    scored = []
    for c in contacts:
        name = normalize_name(c['name'])
        nick = normalize_name(c.get('nickname'))
        first = normalize_name(c.get('first'))
        last = normalize_name(c.get('last'))
        org = normalize_name(c.get('org'))
        haystack = ' '.join(x for x in (name, nick, org) if x)

        if name == q or (nick and nick == q):
            tier = 0
        elif first == q or last == q:
            tier = 1
        elif q_words and all(w in haystack.split() for w in q_words):
            tier = 2
        elif q in haystack:
            tier = 3
        else:
            continue
        scored.append((tier, name, c))

    scored.sort(key=lambda t: (t[0], t[1]))
    return [(tier, c) for tier, _, c in scored]


def find(query, contacts=None):
    """Contacts matching a name, best match first."""
    return [c for _, c in find_scored(query, contacts)]


# A match this weak (substring only) doesn't compete with a strong one.
_WEAK_TIER = 3


def resolve_name(query, contacts=None):
    """Resolve a name to one sending address.

    Returns (status, payload):
      ('found', {name, address, label, contact})
      ('ambiguous', {reason, options: [{name, address, label}]})
      ('missing', None)

    Deliberately conservative: it only auto-picks when one contact is clearly
    the best match AND the chosen number is plausibly a handset. Anything else
    comes back as a pick-list, because silently guessing a recipient means
    texting the wrong person.
    """
    scored = find_scored(query, contacts)
    if not scored:
        return 'missing', None

    best_tier = scored[0][0]
    top = [c for tier, c in scored if tier == best_tier]
    others = [(tier, c) for tier, c in scored if tier != best_tier]

    def opt(contact, phone):
        return {'name': contact['name'],
                'address': phone['number'] if phone else None,
                'label': (phone or {}).get('label', '')}

    if len(top) > 1:
        return 'ambiguous', {
            'reason': 'several contacts match "%s"' % query,
            'tier': best_tier,
            'options': [opt(c, best_phone(c)) for c in top],
        }

    # A single strong match still loses to a near-equal runner-up.
    if others and best_tier <= 1 and any(t < _WEAK_TIER for t, _ in others):
        return 'ambiguous', {
            'reason': 'more than one contact could match "%s"' % query,
            'tier': best_tier,
            'options': [opt(c, best_phone(c)) for c in top]
                       + [opt(c, best_phone(c)) for t, c in others if t < _WEAK_TIER],
        }

    contact = top[0]
    phones = textable_phones(contact)
    if not phones:
        return 'ambiguous', {
            'reason': '%s has no phone number in Contacts' % contact['name'],
            'options': [],
        }

    couple = couple_members(contact)
    if couple:
        status, payload = _resolve_couple(query, contact, couple, phones, opt)
        if status:
            payload.setdefault('tier', best_tier)
            return status, payload

    chosen = phones[0]
    # One number: use it whatever the label. Several: only auto-pick a handset
    # or pager, otherwise ask rather than text a work landline.
    if len(phones) > 1 and _rank(chosen['label']) > LABEL_RANK['pager']:
        return 'ambiguous', {
            'reason': 'which number for %s?' % contact['name'],
            'options': [opt(contact, p) for p in phones],
        }
    return 'found', {'name': contact['name'], 'address': chosen['number'],
                     'label': chosen['label'], 'tier': best_tier,
                     'contact': contact}


def couple_members(contact):
    """('alex', 'dana') for a couple contact carrying both a mobile and a
    pager, else None. Both labels must be present — a lone mobile means the
    convention isn't in play and the number is simply the household's."""
    m = _COUPLE_RE.match(contact.get('name') or '')
    if not m:
        return None
    labels = {p['label'] for p in contact.get('phones') or []}
    if not ({'mobile', 'iphone'} & labels) or 'pager' not in labels:
        return None
    first = normalize_name(m.group(1)).split()
    second = normalize_name(m.group(2)).split()
    if not first or not second:
        return None
    # "Alex And Dana Rivera" -> the surname rides on the second name
    return first[-1], second[0]


def _member_label(person, contact, members):
    """'Sam Okafor' rather than 'Sam Robin & Sam Okafor'."""
    surname = (normalize_name(contact['name']).split() or [''])[-1]
    if surname and surname not in members:
        return '%s %s' % (person.title(), surname.title())
    return person.title()


def _phone_by_label(phones, labels):
    for p in phones:
        if p['label'] in labels:
            return p
    return None


def _resolve_couple(query, contact, members, phones, opt):
    """Apply the mobile=man / pager=woman convention. Returns (status, payload)
    or (None, None) to fall through to normal label ranking."""
    a, b = members
    q_words = set(normalize_name(query).split())
    named = [n for n in (a, b) if n in q_words]

    mobile = _phone_by_label(phones, ('mobile', 'iphone'))
    pager = _phone_by_label(phones, ('pager',))

    def person_option(person, phone):
        o = opt(contact, phone)
        o['name'] = _member_label(person, contact, members)
        return o

    if len(named) != 1:
        # Asked for the couple as a whole (or neither name) — which of them?
        return 'ambiguous', {
            'reason': '"%s" is a couple — who did you mean?' % contact['name'],
            'options': [o for o in (person_option(a, mobile if couple_gender().get(a) != 'f' else pager),
                                    person_option(b, pager if couple_gender().get(b) == 'f' else mobile))
                        if o['address']],
        }

    person = named[0]
    gender = couple_gender().get(person)
    if gender == 'm' and mobile:
        return 'found', {'name': _member_label(person, contact, members),
                         'address': mobile['number'], 'label': mobile['label'],
                         'contact': contact}
    if gender == 'f' and pager:
        return 'found', {'name': _member_label(person, contact, members),
                         'address': pager['number'], 'label': pager['label'],
                         'contact': contact}
    return 'ambiguous', {
        'reason': ('"%s" is a couple contact and I can\'t tell which number is '
                   '%s\'s — mobile is the man\'s, pager the woman\'s'
                   % (contact['name'], person.title())),
        'options': [o for o in (person_option(a, mobile), person_option(b, pager))
                    if o['address']],
    }


if __name__ == '__main__':
    import json
    import sys

    ok, reason = available()
    if not ok:
        print('Contacts unavailable: %s' % reason)
        sys.exit(1)
    if len(sys.argv) > 1:
        matches = find(' '.join(sys.argv[1:]))
        print(json.dumps([{
            'name': m['name'],
            'best': best_phone(m),
            'phones': m['phones'],
            'emails': [e['address'] for e in m['emails']],
        } for m in matches], indent=2))
    else:
        contacts = load_contacts()
        print('%d contacts, %d with a phone number'
              % (len(contacts), sum(1 for c in contacts if c['phones'])))
