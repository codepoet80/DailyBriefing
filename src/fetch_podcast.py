import base64
import feedparser
import requests

FETCH_TIMEOUT = 15


def fetch_podcast(config):
    podcast_cfg = config.get('podcast', {})
    feed_url  = podcast_cfg.get('feed_url', 'https://feeds.npr.org/510318/podcast.xml')
    name      = podcast_cfg.get('name', 'NPR Up First')
    proxy_base = podcast_cfg.get('proxy_base_url', '')

    if proxy_base:
        fetch_url = proxy_base + base64.b64encode(feed_url.encode()).decode()
        print('    ' + name + ' <- proxy -> ' + feed_url)
    else:
        fetch_url = feed_url
        print('    ' + name + ' <- ' + feed_url)
    try:
        resp = requests.get(fetch_url, timeout=FETCH_TIMEOUT,
                            headers={'User-Agent': 'DailyBriefing/1.0'})
        resp.raise_for_status()
        d = feedparser.parse(resp.content)

        if not d.entries:
            print('    No episodes found')
            return None

        entry = d.entries[0]
        audio_url = None
        for enc in entry.get('enclosures', []):
            if enc.get('type', '').startswith('audio/'):
                audio_url = enc.get('href') or enc.get('url')
                break

        if not audio_url:
            print('    No audio enclosure found')
            return None

        print('    Latest: ' + entry.get('title', ''))
        return {
            'name': name,
            'title': entry.get('title', ''),
            'audio_url': audio_url,
        }

    except Exception as e:
        print('    Warning: Could not fetch podcast: ' + str(e))
        return None
