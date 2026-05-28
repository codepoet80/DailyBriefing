#!/usr/bin/env python3
import hashlib
import json
import os
from datetime import datetime, timedelta

import requests

STATE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data', 'agent_state.json')


class AgentMemory:
    def __init__(self, path=None):
        self._path = os.path.abspath(path or STATE_PATH)
        self._state = self._load()

    def _load(self):
        if os.path.exists(self._path):
            with open(self._path) as f:
                return json.load(f)
        return {'pushed': {}, 'rule_stats': {}}

    def save(self):
        with open(self._path, 'w') as f:
            json.dump(self._state, f, indent=2, default=str)

    @staticmethod
    def content_hash(rule_id, item_key):
        return hashlib.md5(f'{rule_id}:{item_key}'.encode()).hexdigest()[:12]

    def already_pushed(self, hash_key, dedupe_hours):
        entry = self._state['pushed'].get(hash_key)
        if not entry:
            return False
        pushed_at = datetime.fromisoformat(entry['pushed_at'])
        return datetime.now() - pushed_at < timedelta(hours=dedupe_hours)

    def record_push(self, hash_key, rule_id, description, receipt=None):
        self._state['pushed'][hash_key] = {
            'pushed_at': datetime.now().isoformat(),
            'rule_id': rule_id,
            'description': description,
            'receipt': receipt,
            'acked': False,
        }

    def record_ack(self, receipt):
        for entry in self._state['pushed'].values():
            if entry.get('receipt') == receipt:
                entry['acked'] = True

    def increment_stat(self, rule_id, field):
        stats = self._state['rule_stats'].setdefault(rule_id, {'fired': 0, 'acked': 0})
        stats[field] = stats.get(field, 0) + 1

    def check_receipts(self, app_token):
        """Poll Pushover for unacknowledged priority-1 receipts and update state."""
        for entry in self._state['pushed'].values():
            receipt = entry.get('receipt')
            if not receipt or entry.get('acked'):
                continue
            try:
                r = requests.get(
                    f'https://api.pushover.net/1/receipts/{receipt}.json',
                    params={'token': app_token},
                    timeout=5,
                )
                data = r.json()
                if data.get('acknowledged'):
                    entry['acked'] = True
                    self.increment_stat(entry.get('rule_id', ''), 'acked')
            except Exception:
                pass

    def prune(self, max_age_days=30):
        cutoff = datetime.now() - timedelta(days=max_age_days)
        self._state['pushed'] = {
            k: v for k, v in self._state['pushed'].items()
            if datetime.fromisoformat(v['pushed_at']) > cutoff
        }

    def get_stats(self):
        return self._state.get('rule_stats', {})
