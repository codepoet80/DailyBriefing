import requests
import re


def fetch_servers(config):
    sites = config.get('servers', [])
    if not sites:
        return None

    results = []
    all_up = True

    for site in sites:
        name = site['name']
        url  = site['url']
        print('    ' + name + ' <- ' + url)
        result = _fetch_status(name, url)
        results.append(result)
        if not result['all_up']:
            all_up = False

    total_down = sum(len(r['down']) for r in results)
    print('    ' + ('All servers up' if all_up else str(total_down) + ' service(s) down'))
    return {'all_up': all_up, 'sites': results}


def _fetch_status(name, url):
    try:
        resp = requests.get(url, timeout=10, headers={'User-Agent': 'DailyBriefing/1.0'})
        resp.raise_for_status()
        html = resp.text
    except Exception as e:
        print('      Warning: could not reach ' + url + ': ' + str(e))
        return {'name': name, 'url': url, 'all_up': False, 'down': ['(unreachable)'], 'up': []}

    # Parse individual service buttons
    up   = []
    down = []
    for m in re.finditer(r'<a[^>]+class="btn btn-(success|danger)[^"]*"[^>]*>\s*([^<\n]+?)\s*(?:<font|$)', html):
        status, service_name = m.group(1), m.group(2).strip()
        if status == 'success':
            up.append(service_name)
        else:
            down.append(service_name)

    all_up = len(down) == 0
    return {'name': name, 'url': url, 'all_up': all_up, 'down': down, 'up': up}
