#!/usr/bin/env python3
"""Proactive push agent — evaluates briefing.json against configured rules,
calls Claude API for notification text, sends via Pushover."""
import json
import os
import sys
from datetime import datetime

import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from agent_memory import AgentMemory

BASE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
CONFIG_DIR = os.path.join(BASE_DIR, 'config')
DATA_DIR = os.path.join(BASE_DIR, 'data')


def load_config():
    with open(os.path.join(CONFIG_DIR, 'config.json')) as f:
        config = json.load(f)
    rules_path = os.path.join(CONFIG_DIR, 'agent_rules.json')
    rules = None
    if os.path.exists(rules_path):
        with open(rules_path) as f:
            rules = json.load(f)
    return config, rules


def load_briefing():
    with open(os.path.join(DATA_DIR, 'briefing.json')) as f:
        return json.load(f)


def evaluate_rules(briefing, rules):
    """Return list of candidate dicts for each triggered rule condition."""
    now = datetime.now()
    candidates = []

    for rule in rules.get('rules', []):
        if not rule.get('enabled', True):
            continue
        rule_id = rule['id']
        rule_type = rule['type']

        if rule_type == 'calendar':
            window = rule.get('window_minutes', 90)
            keywords = [k.lower() for k in rule.get('keywords', [])]
            for event in briefing.get('my_calendar', []):
                if event.get('all_day'):
                    continue
                sort_key = event.get('sort_key', '')
                date_iso = event.get('date_iso', now.strftime('%Y-%m-%d'))
                if not sort_key:
                    continue
                if keywords and not any(k in event.get('title', '').lower() for k in keywords):
                    continue
                try:
                    event_dt = datetime.strptime(f'{date_iso} {sort_key}', '%Y-%m-%d %H:%M')
                    minutes_until = (event_dt - now).total_seconds() / 60
                    if 0 < minutes_until <= window:
                        candidates.append({
                            'rule': rule,
                            'item_key': event.get('title', '') + ':' + date_iso,
                            'data': event,
                            'summary': f"Event in {int(minutes_until)} min: {event.get('title')}",
                        })
                except ValueError:
                    pass

        elif rule_type == 'family_calendar':
            today_str = now.strftime('%Y-%m-%d')
            today_events = [e for e in briefing.get('family_calendar', [])
                            if e.get('date_iso') == today_str]
            if today_events:
                key = today_str + ':' + ':'.join(e.get('title', '') for e in today_events)
                candidates.append({
                    'rule': rule,
                    'item_key': key,
                    'data': {'events': today_events},
                    'summary': f"{len(today_events)} family event(s) today",
                })

        elif rule_type == 'server_status':
            servers = briefing.get('servers', {})
            if servers and not servers.get('all_up', True):
                down = [s['name'] for s in servers.get('sites', [])
                        if not s.get('all_up', True)]
                if down:
                    key = ':'.join(sorted(down))
                    candidates.append({
                        'rule': rule,
                        'item_key': key,
                        'data': {'down': down, 'sites': servers.get('sites', [])},
                        'summary': f"Servers down: {', '.join(down)}",
                    })

        elif rule_type == 'security':
            unifi = briefing.get('unifi')
            if unifi and unifi.get('total_events', 0) > 0:
                today_str = now.strftime('%Y-%m-%d')
                candidates.append({
                    'rule': rule,
                    'item_key': f'security:{today_str}:{unifi["total_events"]}',
                    'data': unifi,
                    'summary': f"{unifi['total_events']} security events {unifi.get('window_label', 'overnight')}",
                })

        elif rule_type == 'news_keyword':
            keywords = [k.lower() for k in rule.get('keywords', [])]
            if not keywords:
                continue
            all_news = briefing.get('news_important', []) + briefing.get('news_regular', [])
            for story in all_news:
                title_lower = story.get('title', '').lower()
                if any(k in title_lower for k in keywords):
                    candidates.append({
                        'rule': rule,
                        'item_key': story.get('title', ''),
                        'data': story,
                        'summary': f"News match: {story.get('title', '')}",
                    })

        elif rule_type == 'todos':
            trigger_hour = rule.get('hour')
            if trigger_hour is not None and now.hour != trigger_hour:
                continue
            keywords = [k.lower() for k in rule.get('keywords', [])]
            open_todos = [t for t in briefing.get('todos', []) if not t.get('done')]
            if keywords:
                open_todos = [t for t in open_todos if any(k in t.get('title', '').lower() for k in keywords)]
            if open_todos:
                max_count = rule.get('max_count', 3)
                top = open_todos[:max_count]
                today_str = now.strftime('%Y-%m-%d')
                candidates.append({
                    'rule': rule,
                    'item_key': f'todos:{today_str}',
                    'data': {'todos': top, 'total_open': len(open_todos)},
                    'summary': f"{len(open_todos)} open todos; top: {top[0]['title']}",
                })

        elif rule_type == 'github':
            notifications = briefing.get('github') or []
            reasons = rule.get('reasons', [])
            for n in notifications:
                if reasons and n.get('reason_raw', '') not in reasons:
                    continue
                key = f"{n.get('id')}:{n.get('updated_at', '')}"
                candidates.append({
                    'rule': rule,
                    'item_key': key,
                    'data': n,
                    'summary': f"GitHub {n.get('type')} [{n.get('reason')}]: {n.get('title')} ({n.get('repo')})",
                })

        elif rule_type == 'weather':
            weather = briefing.get('weather', {})
            if not weather:
                continue
            conditions = [c.lower() for c in rule.get('conditions', [])]
            today_wx = weather.get('today', {})
            wx_desc = today_wx.get('condition', '').lower()
            if any(c in wx_desc for c in conditions):
                today_str = now.strftime('%Y-%m-%d')
                candidates.append({
                    'rule': rule,
                    'item_key': f'weather:{today_str}:{wx_desc}',
                    'data': today_wx,
                    'summary': f"Weather today: {today_wx.get('condition')}",
                })

    return candidates


def write_notification_texts(candidates, config):
    import anthropic

    agent_cfg = config.get('agent', {})
    api_key = agent_cfg.get('anthropic_api_key', '')
    model = agent_cfg.get('model', 'claude-haiku-4-5-20251001')
    name = config.get('greeting', {}).get('name', 'there')

    client = anthropic.Anthropic(api_key=api_key)

    items = [
        {'id': i, 'rule_type': c['rule']['type'], 'summary': c['summary'], 'data': c['data']}
        for i, c in enumerate(candidates)
    ]

    prompt = (
        'Write a Pushover notification for each item. '
        'Return ONLY a JSON array: [{"id": 0, "title": "...", "message": "..."}]\n'
        '- title: max 40 chars, specific and action-oriented\n'
        '- message: max 120 chars, the key fact needed\n'
        '- No filler phrases, no emoji unless meaningful\n'
        '- Tone: concise personal assistant\n\n'
        f'Items:\n{json.dumps(items, indent=2)}'
    )

    response = client.messages.create(
        model=model,
        max_tokens=1024,
        system=f'You are a concise personal briefing agent for {name}.',
        messages=[{'role': 'user', 'content': prompt}],
    )

    text = response.content[0].text.strip()
    if text.startswith('```'):
        text = text.split('\n', 1)[1].rsplit('```', 1)[0].strip()

    return {t['id']: t for t in json.loads(text)}


def send_pushover(app_token, user_key, title, message, priority=0, device=''):
    payload = {
        'token': app_token,
        'user': user_key,
        'title': title,
        'message': message,
        'priority': priority,
    }
    if device:
        payload['device'] = device
    if priority == 1:
        payload['retry'] = 60
        payload['expire'] = 3600

    r = requests.post('https://api.pushover.net/1/messages.json', data=payload, timeout=10)
    r.raise_for_status()
    return r.json().get('receipt')  # only present for priority 1


def main():
    config, rules = load_config()

    agent_cfg = config.get('agent', {})
    if not agent_cfg.get('enabled', False):
        print('Agent: not enabled, skipping.')
        return

    app_token = agent_cfg.get('pushover_app_token', '')
    user_key = agent_cfg.get('pushover_user_key', '')
    if not app_token or not user_key:
        print('Agent: Pushover credentials not configured, skipping.')
        return

    if not rules:
        print('Agent: config/agent_rules.json not found — copy agent_rules.json.example to get started.')
        return

    briefing = load_briefing()
    memory = AgentMemory()

    memory.check_receipts(app_token)

    candidates = evaluate_rules(briefing, rules)
    print(f'Agent: {len(candidates)} rule candidate(s)')

    to_notify = []
    for c in candidates:
        hash_key = AgentMemory.content_hash(c['rule']['id'], c['item_key'])
        dedupe_hours = c['rule'].get('dedupe_hours', 24)
        if not memory.already_pushed(hash_key, dedupe_hours):
            to_notify.append((c, hash_key))

    if not to_notify:
        print('Agent: all candidates within dedupe window, nothing to push.')
        memory.save()
        return

    print(f'Agent: {len(to_notify)} new notification(s) to send')

    candidates_to_write = [c for c, _ in to_notify]
    try:
        text_map = write_notification_texts(candidates_to_write, config)
    except Exception as e:
        print(f'Agent: Claude API error: {e}; using summary fallback')
        text_map = {
            i: {
                'id': i,
                'title': c['rule']['type'].replace('_', ' ').title(),
                'message': c['summary'][:120],
            }
            for i, (c, _) in enumerate(to_notify)
        }

    for i, (candidate, hash_key) in enumerate(to_notify):
        text = text_map.get(i, {})
        title = text.get('title', candidate['rule']['type'])
        message = text.get('message', candidate['summary'])
        priority = candidate['rule'].get('pushover_priority', 0)

        try:
            receipt = send_pushover(app_token, user_key, title, message, priority,
                                    device=agent_cfg.get('pushover_device', ''))
            memory.record_push(hash_key, candidate['rule']['id'], candidate['summary'], receipt)
            memory.increment_stat(candidate['rule']['id'], 'fired')
            print(f'  Pushed [{candidate["rule"]["id"]}]: {title}')
        except Exception as e:
            print(f'  Pushover error [{candidate["rule"]["id"]}]: {e}')

    memory.prune()
    memory.save()


if __name__ == '__main__':
    main()
