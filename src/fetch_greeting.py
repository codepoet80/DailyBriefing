import urllib.request
import json
from datetime import datetime

ZENQUOTES_URL = 'https://zenquotes.io/api/today'


def fetch_greeting(config):
    name = config.get('greeting', {}).get('name', '')
    hour = datetime.now().hour

    if hour < 12:
        salutation = 'Good morning'
    elif hour < 17:
        salutation = 'Good afternoon'
    else:
        salutation = 'Good evening'

    greeting = salutation + (', ' + name if name else '') + '.'

    quote = _fetch_quote()

    return {
        'greeting': greeting,
        'quote': quote.get('text', ''),
        'author': quote.get('author', ''),
    }


def _fetch_quote():
    try:
        req = urllib.request.Request(
            ZENQUOTES_URL,
            headers={'User-Agent': 'DailyBriefing/1.0'}
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read().decode('utf-8'))
        item = data[0]
        text = item.get('q', '').strip()
        author = item.get('a', '').strip()
        print('    Quote: \u201c' + text[:60] + ('\u2026' if len(text) > 60 else '') + '\u201d \u2014 ' + author)
        return {'text': text, 'author': author}
    except Exception as e:
        print('    Warning: Could not fetch quote: ' + str(e))
        return {'text': '', 'author': ''}
