#!/usr/bin/env python3
import re
import requests
from datetime import datetime, timezone


REASON_LABELS = {
    'assign':           'assigned',
    'author':           'author',
    'comment':          'comment',
    'mention':          'mentioned',
    'review_requested': 'review requested',
    'security_alert':   'security',
    'state_change':     'state changed',
    'subscribed':       'watching',
    'team_mention':     'team mention',
    'ci_activity':      'CI',
    'invitation':       'invited',
    'manual':           'manual',
}

TYPE_LABELS = {
    'PullRequest':                  'PR',
    'Issue':                        'Issue',
    'Release':                      'Release',
    'Commit':                       'Commit',
    'Discussion':                   'Discussion',
    'CheckSuite':                   'CI',
    'RepositoryVulnerabilityAlert': 'Security',
}


def _to_web_url(api_url, subject_type, repo_html_url):
    if not api_url:
        return repo_html_url
    u = api_url
    u = re.sub(r'https://api\.github\.com/repos/([^/]+/[^/]+)/pulls/(\d+)',
               r'https://github.com/\1/pull/\2', u)
    u = re.sub(r'https://api\.github\.com/repos/([^/]+/[^/]+)/issues/(\d+)',
               r'https://github.com/\1/issues/\2', u)
    u = re.sub(r'https://api\.github\.com/repos/([^/]+/[^/]+)/commits/([0-9a-f]+)',
               r'https://github.com/\1/commit/\2', u)
    if u.startswith('https://api.github.com'):
        return repo_html_url
    return u


def fetch_github(config):
    cfg = config.get('github', {})
    token = cfg.get('token', '')
    if not token:
        return None

    max_count = cfg.get('max_count', 30)
    headers = {
        'Authorization': f'Bearer {token}',
        'Accept': 'application/vnd.github+json',
        'X-GitHub-Api-Version': '2022-11-28',
    }

    try:
        resp = requests.get(
            'https://api.github.com/notifications',
            headers=headers,
            params={'all': 'false', 'per_page': min(max_count, 50)},
            timeout=10,
        )
        resp.raise_for_status()
        raw = resp.json()
    except Exception as e:
        print(f'    Warning: GitHub fetch failed: {e}')
        return None

    notifications = []
    for n in raw[:max_count]:
        subject = n.get('subject', {})
        repo = n.get('repository', {})
        subject_type = subject.get('type', '')
        api_url = subject.get('url', '')
        web_url = _to_web_url(api_url, subject_type, repo.get('html_url', ''))

        updated_raw = n.get('updated_at', '')
        try:
            dt = datetime.fromisoformat(updated_raw.replace('Z', '+00:00'))
            updated_label = dt.astimezone().strftime('%-I:%M %p')
        except Exception:
            updated_label = ''

        notifications.append({
            'id':      n.get('id', ''),
            'title':   subject.get('title', ''),
            'type':    TYPE_LABELS.get(subject_type, subject_type),
            'repo':    repo.get('full_name', ''),
            'reason':  REASON_LABELS.get(n.get('reason', ''), n.get('reason', '')),
            'reason_raw': n.get('reason', ''),
            'updated': updated_label,
            'updated_at': updated_raw,
            'url':     web_url,
        })

    print(f'    {len(notifications)} unread GitHub notification(s)')
    return notifications
