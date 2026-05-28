#!/usr/bin/env python3
import json
import os
from datetime import datetime, timedelta


def fetch_reading(config):
    cfg = config.get('reading', {})
    papyrus_dir = os.path.expanduser(
        cfg.get('papyrus_dir', '~/ownCloud/Dropbox/.papyrus')
    )
    stagnant_days = cfg.get('stagnant_days', 5)
    max_inactive_days = cfg.get('max_inactive_days', 30)
    exclude_titles = {t.lower() for t in cfg.get('exclude_titles', [])}

    if not os.path.exists(papyrus_dir):
        print(f'    Skipping reading: {papyrus_dir} not found')
        return None

    now = datetime.now()
    books = []

    for fname in sorted(os.listdir(papyrus_dir)):
        if not fname.endswith('.json'):
            continue
        try:
            with open(os.path.join(papyrus_dir, fname)) as f:
                data = json.load(f)
        except Exception:
            continue

        title = data.get('title', '').strip()
        author = data.get('author', '').strip()
        ts_ms = data.get('timestamp', 0)

        if not title or not ts_ms:
            continue

        last_read_dt = datetime.fromtimestamp(ts_ms / 1000)
        days_since = (now - last_read_dt).days

        if days_since > max_inactive_days:
            continue

        if title.lower() in exclude_titles:
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
        })

    books.sort(key=lambda b: b['days_since'])
    stagnant = [b for b in books if b['stagnant']]
    print(f'    {len(books)} active book(s), {len(stagnant)} stagnant')

    return {'books': books, 'stagnant': stagnant}
