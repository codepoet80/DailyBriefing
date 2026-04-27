import urllib.request
import json
from concurrent.futures import ThreadPoolExecutor, as_completed


HN_BASE = 'https://hacker-news.firebaseio.com/v0'


def fetch_hackernews(count=25):
    try:
        req = urllib.request.Request(
            HN_BASE + '/topstories.json',
            headers={'User-Agent': 'DailyBriefing/1.0'}
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            top_ids = json.loads(r.read().decode('utf-8'))[:count]
    except Exception as e:
        print('Warning: Could not fetch HN top stories: ' + str(e))
        return []

    print('    Fetching ' + str(len(top_ids)) + ' story details...')
    id_to_rank = {item_id: i for i, item_id in enumerate(top_ids)}
    stories = []

    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = {executor.submit(_fetch_item, item_id): item_id for item_id in top_ids}
        for future in as_completed(futures):
            item = future.result()
            if item:
                stories.append(item)

    stories.sort(key=lambda s: id_to_rank.get(s['id'], 999))

    for i, story in enumerate(stories):
        story['rank'] = i + 1

    print('    Got ' + str(len(stories)) + ' stories')
    return stories


def _fetch_item(item_id):
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
                'by': item.get('by', '')
            }
    except Exception:
        pass
    return None
