import urllib.request
import json
import requests
import feedparser
import re
import html as html_module
from concurrent.futures import ThreadPoolExecutor, as_completed

HN_BASE = 'https://hacker-news.firebaseio.com/v0'


def fetch_geek_news(config, feeds_config):
    count = config.get('geek_news', {}).get('count', 20)

    slashdot_url = _slashdot_url(feeds_config)

    hn_stories = _fetch_hn(count)
    sd_stories = _fetch_slashdot(slashdot_url, count) if slashdot_url else []

    print('    HN: ' + str(len(hn_stories)) + ', Slashdot: ' + str(len(sd_stories)))

    combined = _interleave(hn_stories, sd_stories)[:count]
    return combined


def _slashdot_url(feeds_config):
    for feed in feeds_config:
        if feed.get('geek_only') and 'slashdot' in feed['name'].lower():
            return feed['url']
    return None


def _fetch_hn(count):
    try:
        req = urllib.request.Request(
            HN_BASE + '/topstories.json',
            headers={'User-Agent': 'DailyBriefing/1.0'}
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            top_ids = json.loads(r.read().decode('utf-8'))[:count]
    except Exception as e:
        print('    Warning: Could not fetch HN top stories: ' + str(e))
        return []

    id_to_rank = {item_id: i for i, item_id in enumerate(top_ids)}
    stories = []

    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = {executor.submit(_fetch_hn_item, item_id): item_id for item_id in top_ids}
        for future in as_completed(futures):
            item = future.result()
            if item:
                stories.append(item)

    stories.sort(key=lambda s: id_to_rank.get(s['id'], 999))
    return stories


def _fetch_hn_item(item_id):
    try:
        req = urllib.request.Request(
            HN_BASE + '/item/' + str(item_id) + '.json',
            headers={'User-Agent': 'DailyBriefing/1.0'}
        )
        with urllib.request.urlopen(req, timeout=5) as r:
            item = json.loads(r.read().decode('utf-8'))
        if item and item.get('type') == 'story':
            return {
                'id': item['id'],
                'title': item.get('title', ''),
                'url': item.get('url', 'https://news.ycombinator.com/item?id=' + str(item['id'])),
                'score': item.get('score', 0),
                'comments': item.get('descendants', 0),
                'source': 'HN',
            }
    except Exception:
        pass
    return None


def _fetch_slashdot(url, count):
    try:
        resp = requests.get(url, timeout=15, headers={'User-Agent': 'DailyBriefing/1.0'})
        resp.raise_for_status()
        d = feedparser.parse(resp.content)
        stories = []
        for entry in d.entries[:count]:
            title = entry.get('title', '').strip()
            link  = entry.get('link', '')
            if title and link:
                stories.append({
                    'id': None,
                    'title': title,
                    'url': link,
                    'score': None,
                    'comments': None,
                    'source': 'Slashdot',
                })
        return stories
    except Exception as e:
        print('    Warning: Could not fetch Slashdot: ' + str(e))
        return []


def _interleave(a, b):
    result = []
    i, j = 0, 0
    while i < len(a) or j < len(b):
        if i < len(a):
            result.append(a[i])
            i += 1
        if j < len(b):
            result.append(b[j])
            j += 1
    return result
