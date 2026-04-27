import requests
import urllib3
from datetime import datetime, timedelta

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Smart detection types reported by Unifi Protect
SMART_LABELS = {
    'person':       'Person',
    'vehicle':      'Vehicle',
    'animal':       'Animal',
    'package':      'Package',
    'licensePlate': 'License Plate',
}


def fetch_unifi(config):
    cfg = config.get('unifi', {})
    if not cfg:
        return None

    host     = cfg.get('host', '').rstrip('/')
    username = cfg.get('username', '')
    password = cfg.get('password', '')
    night_start = cfg.get('night_start_hour', 22)
    night_end   = cfg.get('night_end_hour', 6)

    if not host or not username or not password:
        print('    Warning: unifi config incomplete, skipping')
        return None

    session = requests.Session()
    session.verify = False

    # Authenticate — session stores the TOKEN cookie automatically;
    # Protect also requires the X-CSRF-Token from the login response headers.
    try:
        resp = session.post(
            host + '/api/auth/login',
            json={'username': username, 'password': password},
            timeout=10,
        )
        resp.raise_for_status()
    except Exception as e:
        print('    Warning: Unifi auth failed: ' + str(e))
        return None

    csrf = resp.headers.get('X-CSRF-Token', '')
    if csrf:
        session.headers.update({'X-CSRF-Token': csrf})

    # Overnight window: most recent 10pm–6am
    now   = datetime.now()
    today = now.date()
    window_end   = datetime(today.year, today.month, today.day, night_end, 0, 0)
    window_start = datetime(today.year, today.month, today.day, night_start, 0, 0) - timedelta(days=1)

    start_ms = int(window_start.timestamp() * 1000)
    end_ms   = int(window_end.timestamp() * 1000)
    print('    Night window: ' + window_start.strftime('%a %I:%M %p') + ' - ' + window_end.strftime('%I:%M %p'))

    try:
        resp = session.get(
            host + '/proxy/protect/api/events',
            params={'start': start_ms, 'end': end_ms, 'limit': 500},
            timeout=15,
        )
        resp.raise_for_status()
        events = resp.json()
    except Exception as e:
        print('    Warning: Unifi events fetch failed: ' + str(e))
        return None

    # Fetch camera name map
    camera_names = {}
    try:
        resp = session.get(host + '/proxy/protect/api/cameras', timeout=10)
        resp.raise_for_status()
        for cam in resp.json():
            camera_names[cam.get('id', '')] = cam.get('name', 'Unknown')
    except Exception as e:
        print('    Warning: Unifi cameras fetch failed: ' + str(e))

    session.close()

    label = window_start.strftime('%-I%p').lower() + '\u2013' + window_end.strftime('%-I%p').lower()
    return _summarize(events, camera_names, label)


def _summarize(events, camera_names, window_label):
    motion_count = 0
    smart_counts = {}   # label -> count
    by_camera = {}      # camera name -> {'motion': N, 'smart': {label: N}}

    for ev in events:
        ev_type  = ev.get('type', '')
        cam_id   = ev.get('camera', '')
        cam_name = camera_names.get(cam_id, cam_id or 'Unknown')

        if cam_name not in by_camera:
            by_camera[cam_name] = {'motion': 0, 'smart': {}}

        if ev_type == 'motion':
            motion_count += 1
            by_camera[cam_name]['motion'] += 1

        elif ev_type == 'smartDetectZone':
            for label in ev.get('smartDetectTypes', []):
                friendly = SMART_LABELS.get(label, label)
                smart_counts[friendly] = smart_counts.get(friendly, 0) + 1
                by_camera[cam_name]['smart'][friendly] = \
                    by_camera[cam_name]['smart'].get(friendly, 0) + 1

    total_events = motion_count + sum(smart_counts.values())
    print('    ' + str(total_events) + ' events overnight'
          + ' (' + str(motion_count) + ' motion, '
          + ', '.join(str(v) + ' ' + k for k, v in smart_counts.items()) + ')')

    cameras = []
    for cam_name, counts in sorted(by_camera.items()):
        if counts['motion'] == 0 and not counts['smart']:
            continue
        cameras.append({
            'name': cam_name,
            'motion': counts['motion'],
            'smart': counts['smart'],
        })

    return {
        'window_label': window_label,
        'total_events': total_events,
        'motion': motion_count,
        'smart': smart_counts,
        'cameras': cameras,
    }
