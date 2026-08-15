#!/usr/bin/env python3
"""Read-only client for the webOS Archive app-storage service.

Python port of the read path of `webos-common/AppStorage/webos-app-storage.js`
(vendored in Papyrus as `app/app/common/webos-app-storage.js`) — enough to sign
in with a webOS Account and read back the records an app stored. Write support
is deliberately absent: the briefing only ever reads reading progress.

Protocol (webos-catalog-service: device.php / storage.php):
  POST {base}/device.php?m=authenticateWeb
       {login, password, device_id, device_name} -> {token, account}
  GET  {base}/storage.php?m=getAll&app_id=...
       -> {items: [{key, value, revision, updated_at}], usage}
  Auth header on every call: `Authorization: PalmAuth token=<token>`

Record VALUES are XXTEA-scrambled client-side with a per-record key derived from
`app_id + ":" + record_key`. The master key is public by design (it ships in the
JS) — this is obfuscation against casual reading of a shared server, not
encryption. Record KEYS are stored as-is, which is why Papyrus scrambles book
keys itself before using them (see SyncManager._scrambledBookKey).

Keep in sync with the JS SDK; if the scramble format changes there ("v1:"
prefix), it must change here.
"""
import base64
import json
import os
import re
import struct
import uuid

import requests

DEFAULT_BASE = 'https://appcatalog.webosarchive.org/WebService'

# Fixed scramble master key, mirroring MASTER in the JS SDK.
_MASTER = [0x77656253, 0x41726368, 0x53746F72, 0x65763101]
_DELTA = 0x9E3779B9
_M32 = 0xFFFFFFFF


# ---- Scramble internals (XXTEA + UTF-8 + base64) ------------------------

def _mx(total, y, z, p, e, k):
    # JS coerces each side to int32 before the final xor; masking to 32 bits is
    # the same operation mod 2**32.
    left = (((z >> 5) ^ ((y << 2) & _M32)) + ((y >> 3) ^ ((z << 4) & _M32))) & _M32
    right = ((total ^ y) + (k[(p & 3) ^ e] ^ z)) & _M32
    return (left ^ right) & _M32


def _xxtea_encrypt(v, k):
    n = len(v) - 1
    if n < 1:
        return v
    z = v[n]
    total = 0
    q = 6 + 52 // (n + 1)
    while q > 0:
        q -= 1
        total = (total + _DELTA) & _M32
        e = (total >> 2) & 3
        for p in range(n):
            y = v[p + 1]
            v[p] = (v[p] + _mx(total, y, z, p, e, k)) & _M32
            z = v[p]
        y = v[0]
        v[n] = (v[n] + _mx(total, y, z, n, e, k)) & _M32
        z = v[n]
    return v


def _xxtea_decrypt(v, k):
    n = len(v) - 1
    if n < 1:
        return v
    y = v[0]
    q = 6 + 52 // (n + 1)
    total = (q * _DELTA) & _M32
    while total != 0:
        e = (total >> 2) & 3
        for p in range(n, 0, -1):
            z = v[p - 1]
            v[p] = (v[p] - _mx(total, y, z, p, e, k)) & _M32
            y = v[p]
        z = v[n]
        v[0] = (v[0] - _mx(total, y, z, 0, e, k)) & _M32
        y = v[0]
        total = (total - _DELTA) & _M32
    return v


def _bytes_to_words(data):
    """First word is the byte length, so decode can strip block padding."""
    words = [len(data) & _M32]
    for i, b in enumerate(data):
        idx = 1 + (i >> 2)
        while len(words) <= idx:
            words.append(0)
        words[idx] |= (b & 0xFF) << ((i & 3) * 8)
    if len(words) < 2:
        words.append(0)
    return [w & _M32 for w in words]


def _words_to_bytes(words):
    length = words[0]
    if length > (len(words) - 1) * 4:
        return None
    return bytes((words[1 + (i >> 2)] >> ((i & 3) * 8)) & 0xFF for i in range(length))


def _record_key(app_id, data_key):
    """Per-record key: master mixed with app_id + ':' + data_key."""
    s = app_id + ':' + data_key
    k = list(_MASTER)
    for i, ch in enumerate(s):
        w = k[i & 3]
        k[i & 3] = (w ^ (((w << 5) & _M32) + ord(ch) + (w >> 2))) & _M32
    return k


def scramble(app_id, data_key, plaintext):
    words = _bytes_to_words(plaintext.encode('utf-8'))
    packed = _xxtea_encrypt(words, _record_key(app_id, data_key))
    raw = struct.pack('<%dI' % len(packed), *packed)
    return 'v1:' + base64.b64encode(raw).decode('ascii')


def unscramble(app_id, data_key, blob):
    """Return the plaintext string, or None if this isn't a v1 blob."""
    if not isinstance(blob, str) or not blob.startswith('v1:'):
        return None
    b64 = re.sub(r'[^A-Za-z0-9+/]', '', blob[3:])
    try:
        raw = base64.b64decode(b64 + '=' * (-len(b64) % 4))
    except Exception:
        return None
    if len(raw) < 8 or len(raw) % 4 != 0:
        return None
    words = list(struct.unpack('<%dI' % (len(raw) // 4), raw))
    plain = _words_to_bytes(_xxtea_decrypt(words, _record_key(app_id, data_key)))
    if plain is None:
        return None
    try:
        return plain.decode('utf-8')
    except UnicodeDecodeError:
        return None


# ---- Session persistence ------------------------------------------------

def load_session(path):
    """Cached {token, device_id, account}; empty dict when absent/unreadable."""
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def save_session(path, session):
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    with open(path, 'w') as f:
        json.dump(session, f)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def make_device_id():
    """Match the SDK's synthetic 'pwa-<uuid>' shape so the account's device
    list shows one stable, revocable entry for this client."""
    return 'pwa-' + str(uuid.uuid4())


class AuthError(Exception):
    """Raised when the service rejects our token or credentials."""


class WebOSAppStorage:
    def __init__(self, app_id, app_name=None, base=None, token=None,
                 device_id=None, timeout=15):
        if not app_id:
            raise ValueError('app_id is required')
        self.app_id = app_id
        self.app_name = app_name or app_id.split('.')[-1].capitalize()
        self.base = (base or DEFAULT_BASE).rstrip('/')
        self.token = token
        self.device_id = device_id
        self.timeout = timeout
        self.account = None

    def _request(self, method, endpoint, m, query=None, body=None):
        url = '%s/%s?m=%s' % (self.base, endpoint, m)
        params = {k: v for k, v in (query or {}).items() if v is not None}
        headers = {'Content-Type': 'application/json'}
        if self.token:
            headers['Authorization'] = 'PalmAuth token=' + self.token
        if self.device_id:
            headers['X-Palm-Device-Id'] = self.device_id
        resp = requests.request(method, url, params=params, json=body,
                                headers=headers, timeout=self.timeout)
        try:
            payload = resp.json()
        except ValueError:
            payload = None
        if resp.status_code == 401:
            raise AuthError((payload or {}).get('message', 'Invalid or expired account token'))
        if not (200 <= resp.status_code < 300):
            msg = (payload or {}).get('message') or 'HTTP %d' % resp.status_code
            raise RuntimeError('%s %s failed: %s' % (endpoint, m, msg))
        return payload or {}

    def sign_in(self, login, password):
        """Exchange account credentials for a long-lived (365-day) token."""
        if not self.device_id:
            self.device_id = make_device_id()
        data = self._request('POST', 'device.php', 'authenticateWeb', body={
            'login': login,
            'password': password,
            'device_id': self.device_id,
            'device_name': self.app_name,
        })
        self.token = data.get('token')
        self.account = data.get('account')
        if not self.token:
            raise AuthError('sign-in returned no token')
        return self.token

    def _unscramble_record(self, rec):
        plain = unscramble(self.app_id, rec.get('key', ''), rec.get('value'))
        if plain is None:
            # Not one of our blobs (or corrupted) — surface the raw string.
            return {'key': rec.get('key'), 'value': rec.get('value'), 'raw': True,
                    'revision': rec.get('revision'), 'updated_at': rec.get('updated_at')}
        try:
            value = json.loads(plain)
        except ValueError:
            value = plain
        return {'key': rec.get('key'), 'value': value,
                'revision': rec.get('revision'), 'updated_at': rec.get('updated_at')}

    def get_all(self):
        data = self._request('GET', 'storage.php', 'getAll', {'app_id': self.app_id})
        return [self._unscramble_record(r) for r in data.get('items', [])]

    def get(self, key):
        data = self._request('GET', 'storage.php', 'get',
                             {'app_id': self.app_id, 'key': key})
        return self._unscramble_record(data)
