from datetime import datetime, timedelta

from bluebubbles import (
    get_bb_config, query_messages, contact_name_map,
    chat_display_name, chat_service, normalize_address,
)


def fetch_imessage(config):
    cfg = get_bb_config(config)
    if not cfg:
        return None

    night_start   = cfg.get('night_start_hour', 22)
    night_end     = cfg.get('night_end_hour', 6)
    night_end_min = cfg.get('night_end_minute', 30)

    now   = datetime.now()
    today = now.date()
    window_end   = datetime(today.year, today.month, today.day, night_end, night_end_min, 0)
    window_start = datetime(today.year, today.month, today.day, night_start, 0, 0) - timedelta(days=1)

    print('    Night window: ' + window_start.strftime('%a %-I:%M %p') + ' - ' + window_end.strftime('%-I:%M %p'))

    try:
        messages = query_messages(cfg, window_start.timestamp() * 1000)
        names = contact_name_map(cfg)
    except Exception as e:
        print('    Warning: BlueBubbles fetch failed: ' + str(e))
        return None

    # Group incoming messages by chat; keep the newest as the preview
    # (query returns newest-first, so the first message seen per chat wins).
    threads = {}
    total = 0
    for msg in messages:
        if msg.get('isFromMe'):
            continue
        received = datetime.fromtimestamp(msg.get('dateCreated', 0) / 1000.0)
        if not (window_start <= received <= window_end):
            continue
        total += 1

        chats = msg.get('chats') or []
        chat = chats[0] if chats else {}
        key = chat.get('guid') or normalize_address((msg.get('handle') or {}).get('address'))
        if key in threads:
            continue

        if chat:
            name = chat_display_name(chat, names)
        else:
            addr = (msg.get('handle') or {}).get('address', 'Unknown')
            name = names.get(normalize_address(addr), addr)

        threads[key] = {
            'name':     name,
            'service':  chat_service(chat),
            'received': received,
            'time':     received.strftime('%-I:%M %p'),
            'preview':  (msg.get('text') or '[attachment]')[:80],
        }

    overnight = sorted(threads.values(), key=lambda x: x['received'])
    for t in overnight:
        del t['received']

    # Build label like "10pm–6:30am"
    start_label = window_start.strftime('%-I%p').lower()
    if night_end_min:
        end_label = window_end.strftime('%-I:%M%p').lower()
    else:
        end_label = window_end.strftime('%-I%p').lower()
    window_label = start_label + '–' + end_label

    print('    ' + str(total) + ' messages overnight in ' + str(len(overnight)) + ' threads')

    return {
        'window_label': window_label,
        'count': total,
        'messages': overnight,
    }
