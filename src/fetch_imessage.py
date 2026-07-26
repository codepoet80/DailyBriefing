import requests
from datetime import datetime, timedelta


def fetch_imessage(config):
    cfg = config.get('imessage', {})
    if not cfg:
        return None

    url = cfg.get('url', '').rstrip('/')
    if not url:
        print('    Warning: imessage config missing url, skipping')
        return None

    night_start     = cfg.get('night_start_hour', 22)
    night_end       = cfg.get('night_end_hour', 6)
    night_end_min   = cfg.get('night_end_minute', 30)

    now   = datetime.now()
    today = now.date()
    window_end   = datetime(today.year, today.month, today.day, night_end, night_end_min, 0)
    window_start = datetime(today.year, today.month, today.day, night_start, 0, 0) - timedelta(days=1)

    print('    Night window: ' + window_start.strftime('%a %-I:%M %p') + ' - ' + window_end.strftime('%-I:%M %p'))

    try:
        resp = requests.get(url + '/chats', timeout=10)
        resp.raise_for_status()
        chats = resp.json()
    except Exception as e:
        print('    Warning: iMessage bridge fetch failed: ' + str(e))
        return None

    overnight = []
    for chat in chats:
        received_str = chat.get('lastReceived', '')
        if not received_str:
            continue
        try:
            received = datetime.strptime(received_str, '%Y-%m-%d %H:%M:%S')
        except ValueError:
            continue
        if window_start <= received <= window_end:
            overnight.append({
                'name':    chat.get('name', 'Unknown'),
                'service': chat.get('service', ''),
                'time':    received.strftime('%-I:%M %p'),
                'preview': chat.get('lastMessage', '')[:80],
            })

    overnight.sort(key=lambda x: x['time'])

    # Build label like "10pm–6:30am"
    start_label = window_start.strftime('%-I%p').lower()
    if night_end_min:
        end_label = window_end.strftime('%-I:%M%p').lower()
    else:
        end_label = window_end.strftime('%-I%p').lower()
    window_label = start_label + '\u2013' + end_label

    count = len(overnight)
    print('    ' + str(count) + ' messages overnight')

    return {
        'window_label': window_label,
        'count': count,
        'messages': overnight,
    }
