import urllib.request
import json
import re
import html as html_module


def fetch_verse(config):
    bible_cfg = config.get('bible', {})
    translation = bible_cfg.get('translation', 'NIV')
    esv_key = bible_cfg.get('esv_api_key', '').strip()

    if esv_key:
        print('    Trying ESV API...')
        result = _fetch_esv(esv_key)
        if result:
            print('    Got: ' + result['reference'])
            return result
        print('    ESV API failed, falling back to BibleGateway')

    print('    Fetching BibleGateway VOTD (' + translation + ')...')
    result = _fetch_biblegateway(translation)
    print('    Got: ' + result['reference'])
    return result


def _fetch_esv(api_key):
    url = (
        'https://api.esv.org/v3/passage/text/'
        '?q=votd'
        '&include-headings=false'
        '&include-footnotes=false'
        '&include-verse-numbers=false'
        '&include-passage-references=true'
        '&indent-paragraphs=0'
        '&indent-poetry=false'
    )
    req = urllib.request.Request(url, headers={
        'Authorization': 'Token ' + api_key,
        'User-Agent': 'DailyBriefing/1.0'
    })
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read().decode('utf-8'))
        passages = data.get('passages', [])
        canonical = data.get('canonical', '')
        if passages:
            text = re.sub(r'\s+', ' ', passages[0]).strip()
            return {'text': text, 'reference': canonical, 'translation': 'ESV'}
    except Exception as e:
        print('Warning: ESV API failed: ' + str(e))
    return None


def _fetch_biblegateway(translation):
    url = 'https://www.biblegateway.com/usage/votd/rss/votd.rdf'
    req = urllib.request.Request(url, headers={'User-Agent': 'DailyBriefing/1.0'})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            raw = r.read().decode('utf-8', errors='replace')

        # Extract verse text from content:encoded — handle optional whitespace around CDATA
        m = re.search(r'<content:encoded>\s*<!\[CDATA\[(.*?)\]\]>', raw, re.DOTALL)
        if not m:
            m = re.search(r'<content:encoded>(.*?)</content:encoded>', raw, re.DOTALL)

        titles = re.findall(r'<title[^>]*>(.*?)</title>', raw, re.DOTALL)

        if m:
            # Strip any stray CDATA markers if the fallback regex was used
            cdata = m.group(1).strip()
            cdata = re.sub(r'^<!\[CDATA\[', '', cdata).rstrip(']]>')

            # The block is: verse text <br/><br/> attribution — take only the verse
            verse_part = re.split(r'<br\s*/?>\s*<br\s*/?>', cdata)[0]
            text = re.sub(r'<br\s*/?>', ' ', verse_part)
            text = re.sub(r'<[^>]+>', '', text)
            text = html_module.unescape(text)
            # Strip surrounding smart quotes BibleGateway wraps around the verse
            text = text.strip('\u201c\u201d\u2018\u2019"\'')
            text = re.sub(r'\s+', ' ', text).strip()

            # Second <title> is the verse reference; first is the feed title
            reference = html_module.unescape(titles[1]).strip() if len(titles) >= 2 else ''
            if text and reference:
                return {'text': text, 'reference': reference, 'translation': translation}

    except Exception as e:
        print('Warning: BibleGateway fetch failed: ' + str(e))

    return {
        'text': (
            'For God so loved the world that he gave his one and only Son, '
            'that whoever believes in him shall not perish but have eternal life.'
        ),
        'reference': 'John 3:16',
        'translation': 'NIV'
    }
