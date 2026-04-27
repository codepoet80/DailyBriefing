import feedparser
import requests
import re
import html as html_module

FEED_TIMEOUT = 15


def fetch_news(feeds_config):
    stories = []
    for feed in feeds_config:
        try:
            print('    ' + feed['name'] + ' <- ' + feed['url'])
            resp = requests.get(feed['url'], timeout=FEED_TIMEOUT,
                                headers={'User-Agent': 'DailyBriefing/1.0'})
            resp.raise_for_status()
            d = feedparser.parse(resp.content)
            count = min(len(d.entries), 20)
            print('      ' + str(count) + ' stories')
            for entry in d.entries[:20]:
                stories.append({
                    'title': entry.get('title', '').strip(),
                    'url': entry.get('link', ''),
                    'summary': _clean_summary(
                        entry.get('summary', '') or entry.get('description', '')
                    ),
                    'source': feed['name'],
                    'source_tier': feed.get('tier', 'general'),
                    'source_tech': feed.get('tech', False),
                    'always_important': feed.get('always_important', False),
                    'verge_wired_pair': feed.get('verge_wired_pair', False),
                })
        except Exception as e:
            print('Warning: Could not fetch feed ' + feed['name'] + ': ' + str(e))

    return stories


def _clean_summary(text):
    if not text:
        return ''
    text = re.sub(r'<[^>]+>', ' ', text)
    text = html_module.unescape(text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text[:300] if len(text) > 300 else text
