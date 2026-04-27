import urllib.request
import json
import os


XKCD_API = 'https://xkcd.com/info.0.json'


def fetch_xkcd(data_dir):
    state_file = os.path.join(data_dir, 'xkcd_state.json')

    try:
        req = urllib.request.Request(XKCD_API, headers={'User-Agent': 'DailyBriefing/1.0'})
        with urllib.request.urlopen(req, timeout=10) as r:
            comic = json.loads(r.read().decode('utf-8'))
    except Exception as e:
        print('Warning: Could not fetch XKCD: ' + str(e))
        return None

    current_num = comic.get('num', 0)
    print('    Latest comic: #' + str(current_num) + ' — ' + comic.get('title', ''))

    last_seen = 0
    if os.path.exists(state_file):
        try:
            with open(state_file) as f:
                state = json.load(f)
            last_seen = state.get('last_seen_num', 0)
        except Exception:
            pass

    is_new = current_num > last_seen
    print('    Last seen: #' + str(last_seen) + ' -> ' + ('NEW' if is_new else 'not new'))

    # Only advance the state once we've seen the comic — keep showing it until the next new one
    if not is_new:
        try:
            with open(state_file, 'w') as f:
                json.dump({'last_seen_num': current_num}, f)
        except Exception as e:
            print('Warning: Could not save XKCD state: ' + str(e))

    return {
        'num': current_num,
        'title': comic.get('title', ''),
        'img_url': comic.get('img', ''),
        'alt': comic.get('alt', ''),
        'is_new': is_new
    }
