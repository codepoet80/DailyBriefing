import requests
import requests.packages.urllib3
import icalendar
import recurring_ical_events
from datetime import date, datetime, timedelta

requests.packages.urllib3.disable_warnings(
    requests.packages.urllib3.exceptions.InsecureRequestWarning
)


def fetch_calendars(config, include_tomorrow=False):
    owncloud = config['owncloud']
    base_url = owncloud['base_url'].rstrip('/')
    auth = (owncloud['username'], owncloud['password'])
    ssl_verify = owncloud.get('ssl_verify', True)
    exclude_titles = set(
        t.lower() for t in config.get('calendar_filters', {}).get('exclude_titles', [])
    )

    today = date.today()
    tomorrow = today + timedelta(days=1)
    week_end = today + timedelta(days=6)

    my_events = []
    family_events = []
    tomorrow_events = []

    for cal_cfg in config['calendars'].get('mine', []):
        url, cal_auth, verify = _resolve_url(cal_cfg['url'], base_url, auth, ssl_verify)
        print('    [mine] ' + cal_cfg['name'] + ' <- ' + url)
        events = _fetch_filtered(url, cal_auth, verify, today, today, cal_cfg['name'], exclude_titles)
        print('      ' + str(len(events)) + ' event(s) today')
        my_events.extend(events)
        if include_tomorrow:
            t_events = _fetch_filtered(url, cal_auth, verify, tomorrow, tomorrow, cal_cfg['name'], exclude_titles)
            print('      ' + str(len(t_events)) + ' event(s) tomorrow')
            tomorrow_events.extend(t_events)

    for cal_cfg in config['calendars'].get('family', []):
        url, cal_auth, verify = _resolve_url(cal_cfg['url'], base_url, auth, ssl_verify)
        color = cal_cfg.get('color', '')
        print('    [family] ' + cal_cfg['name'] + ' <- ' + url)
        events = _fetch_filtered(url, cal_auth, verify, today, week_end, cal_cfg['name'], exclude_titles, color)
        print('      ' + str(len(events)) + ' event(s) this week')
        family_events.extend(events)

    my_events.sort(key=_sort_key)
    family_events.sort(key=lambda e: (e.get('date_iso', ''), e.get('sort_key', '99:99')))
    tomorrow_events.sort(key=_sort_key)

    return my_events, family_events, tomorrow_events


def _resolve_url(url, base_url, auth, ssl_verify):
    if url.startswith('http://') or url.startswith('https://'):
        return url, None, True
    return base_url + url, auth, ssl_verify


def _fetch_filtered(url, auth, ssl_verify, start_date, end_date, calendar_name, exclude_titles, color=''):
    events = _fetch_range(url, auth, ssl_verify, start_date, end_date, calendar_name, color)
    return [e for e in events if e and e['title'].lower() not in exclude_titles]


def _fetch_range(url, auth, ssl_verify, start_date, end_date, calendar_name, color=''):
    try:
        resp = requests.get(url, auth=auth, verify=ssl_verify, timeout=15)
        resp.raise_for_status()
        cal = icalendar.Calendar.from_ical(resp.content)

        local_tz = datetime.now().astimezone().tzinfo
        start = datetime(start_date.year, start_date.month, start_date.day, 0, 0, 0, tzinfo=local_tz)
        end = datetime(end_date.year, end_date.month, end_date.day, 23, 59, 59, tzinfo=local_tz)

        events = recurring_ical_events.of(cal).between(start, end)
        return [_parse_event(e, calendar_name, color) for e in events if e is not None]

    except Exception as e:
        print('Warning: Could not fetch calendar ' + url + ': ' + str(e))
        return []


def _parse_event(event, calendar_name, color=''):
    dtstart = event.get('DTSTART')
    if dtstart is None:
        return None

    dt = dtstart.dt
    all_day = isinstance(dt, date) and not isinstance(dt, datetime)

    if all_day:
        event_date = dt
        time_str = 'All day'
        sort_val = '00:00'
    else:
        if dt.tzinfo is not None:
            dt = dt.astimezone().replace(tzinfo=None)
        event_date = dt.date()
        h = dt.hour % 12 or 12
        ampm = 'AM' if dt.hour < 12 else 'PM'
        time_str = '{0}:{1:02d} {2}'.format(h, dt.minute, ampm)
        sort_val = '{0:02d}:{1:02d}'.format(dt.hour, dt.minute)

    summary = str(event.get('SUMMARY', '(No title)'))
    loc = event.get('LOCATION')
    location = str(loc) if loc else None

    return {
        'time': time_str,
        'sort_key': sort_val,
        'date_iso': event_date.strftime('%Y-%m-%d'),
        'date_label': event_date.strftime('%A, %B %-d'),
        'title': summary,
        'location': location,
        'all_day': all_day,
        'calendar': calendar_name,
        'color': color,
    }


def _sort_key(event):
    if event is None:
        return '99:99'
    return event.get('sort_key', '99:99')
