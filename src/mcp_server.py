#!/usr/bin/env python3
"""MCP server — exposes briefing.json as context resources and action tools
so Claude Code (local or via remote tunnel) has your full daily context."""
import asyncio
import json
import os
import shlex
import subprocess
import sys

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp import types

BASE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
DATA_DIR = os.path.join(BASE_DIR, 'data')
CONFIG_DIR = os.path.join(BASE_DIR, 'config')
CONVERSATIONS_DIR = os.path.join(DATA_DIR, 'conversations')

app = Server('daily-briefing-agent')

# Holds references to in-flight delayed-send tasks so they aren't GC'd
_pending_tasks: set = set()


async def _send_after_delay(delay_seconds: float, bridge_url: str, address: str,
                             is_reply: bool, service: str, message: str, display_name: str):
    import requests as req
    await asyncio.sleep(delay_seconds)
    try:
        payload = {'address': address, 'isReply': is_reply, 'service': service, 'message': message}
        r = req.post(bridge_url + '/chats', json=payload, timeout=10)
        r.raise_for_status()
        print(f'[send_message] Sent to {display_name}: {message[:60]}', file=sys.stderr, flush=True)
    except Exception as e:
        print(f'[send_message] Failed to send to {display_name}: {e}', file=sys.stderr, flush=True)


def _load_briefing():
    try:
        with open(os.path.join(DATA_DIR, 'briefing.json')) as f:
            return json.load(f)
    except FileNotFoundError:
        raise ValueError('briefing.json not found — run build_briefing.py first')
    except json.JSONDecodeError as e:
        raise ValueError(f'briefing.json is malformed: {e}')


def _load_config():
    try:
        with open(os.path.join(CONFIG_DIR, 'config.json')) as f:
            return json.load(f)
    except FileNotFoundError:
        raise ValueError('config.json not found — copy config.json.example and fill it in')
    except json.JSONDecodeError as e:
        raise ValueError(f'config.json is malformed: {e}')


def _ensure_conversations_dir():
    os.makedirs(CONVERSATIONS_DIR, exist_ok=True)


def _resolve_dialectic_ref(ref):
    """Resolve an id-or-topic reference to a real UUID id.

    Returns one of:
      ('found',     id_str)         single match (by id or unique substring)
      ('ambiguous', [match dicts])  multiple topic matches
      ('missing',   None)           nothing matched
    """
    import re
    ref = (ref or '').strip()
    if not ref:
        return ('missing', None)

    # Direct UUID hit: file exists with this exact id.
    path = os.path.join(CONVERSATIONS_DIR, f'{ref}.json')
    if os.path.isfile(path):
        return ('found', ref)

    items = _list_dialectics()

    # Allow id prefix match too (UUIDs are long; first 8 chars are usually unique).
    if re.match(r'^[0-9a-f-]+$', ref.lower()):
        id_hits = [d for d in items if d['id'].lower().startswith(ref.lower())]
        if len(id_hits) == 1:
            return ('found', id_hits[0]['id'])
        if len(id_hits) > 1:
            return ('ambiguous', id_hits)

    # Topic substring (case-insensitive). Also try ref-with-spaces in case the
    # agent passed a kebab-case version like "polanyi-bottom-up".
    needle  = ref.lower()
    spaces  = ref.replace('-', ' ').replace('_', ' ').lower()
    matches = [d for d in items
               if needle in d['topic'].lower() or spaces in d['topic'].lower()]
    if len(matches) == 1:
        return ('found', matches[0]['id'])
    if len(matches) > 1:
        return ('ambiguous', matches)

    return ('missing', None)


def _format_ambiguous(matches):
    lines = ['Multiple dialectics match — pick an id:']
    for d in matches[:10]:
        lines.append(f'  {d["id"]} | {d["topic"]} | {d["turn_count"]} turns | {d["updated_at"]}')
    if len(matches) > 10:
        lines.append(f'  …and {len(matches) - 10} more')
    return '\n'.join(lines)


def _list_dialectics():
    if not os.path.isdir(CONVERSATIONS_DIR):
        return []
    results = []
    for fname in sorted(os.listdir(CONVERSATIONS_DIR)):
        if not fname.endswith('.json'):
            continue
        path = os.path.join(CONVERSATIONS_DIR, fname)
        try:
            with open(path) as f:
                d = json.load(f)
            results.append({
                'id': d.get('id', fname[:-5]),
                'topic': d.get('topic', ''),
                'created_at': d.get('created_at', ''),
                'updated_at': d.get('updated_at', ''),
                'turn_count': len(d.get('turns', [])),
            })
        except (json.JSONDecodeError, OSError):
            pass
    return results


@app.list_resources()
async def list_resources():
    return [
        types.Resource(
            uri='briefing://current',
            name='Current Daily Briefing',
            description='Latest briefing.json — calendar, todos, news, weather, security events',
            mimeType='application/json',
        ),
        types.Resource(
            uri='briefing://memory',
            name='Agent Memory',
            description='agent_state.json — push history, acknowledgments, rule stats',
            mimeType='application/json',
        ),
        types.Resource(
            uri='briefing://dialectics',
            name='Dialectics',
            description='Index of saved dialectic conversations (id, topic, date, turn count)',
            mimeType='application/json',
        ),
    ]


@app.read_resource()
async def read_resource(uri: str):
    if uri == 'briefing://current':
        return json.dumps(_load_briefing(), indent=2, default=str)
    if uri == 'briefing://memory':
        path = os.path.join(DATA_DIR, 'agent_state.json')
        if os.path.exists(path):
            with open(path) as f:
                return f.read()
        return '{}'
    if uri == 'briefing://dialectics':
        return json.dumps(_list_dialectics(), indent=2)
    raise ValueError(f'Unknown resource: {uri}')


@app.list_tools()
async def list_tools():
    return [
        types.Tool(
            name='add_todo',
            description='Add a todo item via checkmate',
            inputSchema={
                'type': 'object',
                'properties': {
                    'title': {'type': 'string', 'description': 'Todo title'},
                },
                'required': ['title'],
            },
        ),
        types.Tool(
            name='send_notification',
            description="Send a Pushover notification to Jon's phone",
            inputSchema={
                'type': 'object',
                'properties': {
                    'title': {'type': 'string', 'description': 'Notification title (max 40 chars)'},
                    'message': {'type': 'string', 'description': 'Notification body (max 120 chars)'},
                    'priority': {
                        'type': 'integer',
                        'description': '-1 quiet, 0 normal, 1 high (requires acknowledge)',
                        'default': 0,
                    },
                },
                'required': ['title', 'message'],
            },
        ),
        types.Tool(
            name='refresh_briefing',
            description='Rebuild briefing.json by running build_briefing.py',
            inputSchema={'type': 'object', 'properties': {}},
        ),
        types.Tool(
            name='add_calendar_event',
            description=(
                'Add an event to a writable CalDAV calendar. '
                'Omit start_time for an all-day event. '
                'calendar defaults to the first writable calendar in config.'
            ),
            inputSchema={
                'type': 'object',
                'properties': {
                    'title': {'type': 'string', 'description': 'Event title'},
                    'date': {
                        'type': 'string',
                        'description': 'Date: "today", "tomorrow", or ISO date "YYYY-MM-DD"',
                    },
                    'start_time': {
                        'type': 'string',
                        'description': 'Start time, e.g. "14:00" or "2:00 PM". Omit for all-day.',
                    },
                    'end_time': {
                        'type': 'string',
                        'description': 'End time, e.g. "15:00" or "3:00 PM". Defaults to 1 hour after start.',
                    },
                    'location': {'type': 'string', 'description': 'Optional location'},
                    'notes': {'type': 'string', 'description': 'Optional description / notes'},
                    'calendar': {
                        'type': 'string',
                        'description': 'Calendar name to write to (must have writable:true in config)',
                    },
                },
                'required': ['title', 'date'],
            },
        ),
        types.Tool(
            name='dialectic_save',
            description=(
                'Save an exploratory conversation as a named dialectic. '
                'Call this when the user marks a discussion as a dialectic. '
                'Creates a new file in data/conversations/ keyed by a generated ID.'
            ),
            inputSchema={
                'type': 'object',
                'properties': {
                    'topic': {
                        'type': 'string',
                        'description': 'Short title / topic for this dialectic',
                    },
                    'turns': {
                        'type': 'array',
                        'description': 'Ordered list of conversation turns',
                        'items': {
                            'type': 'object',
                            'properties': {
                                'role': {
                                    'type': 'string',
                                    'enum': ['user', 'assistant'],
                                    'description': 'Who spoke this turn',
                                },
                                'content': {
                                    'type': 'string',
                                    'description': 'Text of the turn',
                                },
                            },
                            'required': ['role', 'content'],
                        },
                    },
                    'tags': {
                        'type': 'array',
                        'items': {'type': 'string'},
                        'description': 'Optional keyword tags for the dialectic',
                    },
                },
                'required': ['topic', 'turns'],
            },
        ),
        types.Tool(
            name='dialectic_append',
            description='Append one or more turns to an existing dialectic by ID.',
            inputSchema={
                'type': 'object',
                'properties': {
                    'id': {
                        'type': 'string',
                        'description': 'Dialectic UUID, short id prefix, or a topic substring (e.g. "polanyi")',
                    },
                    'turns': {
                        'type': 'array',
                        'description': 'New turns to append',
                        'items': {
                            'type': 'object',
                            'properties': {
                                'role': {
                                    'type': 'string',
                                    'enum': ['user', 'assistant'],
                                },
                                'content': {'type': 'string'},
                            },
                            'required': ['role', 'content'],
                        },
                    },
                },
                'required': ['id', 'turns'],
            },
        ),
        types.Tool(
            name='dialectic_list',
            description='List all saved dialectics — returns id, topic, dates, and turn count.',
            inputSchema={'type': 'object', 'properties': {}},
        ),
        types.Tool(
            name='dialectic_get',
            description='Load the full content of a dialectic by ID.',
            inputSchema={
                'type': 'object',
                'properties': {
                    'id': {
                        'type': 'string',
                        'description': 'Dialectic UUID, short id prefix, or a topic substring',
                    },
                },
                'required': ['id'],
            },
        ),
        types.Tool(
            name='dialectic_summary',
            description=(
                'Return a compact summary of a dialectic: topic, dates, status, '
                'turn count, plus the first turn and the last few turns (default '
                '4). Use this — NOT dialectic_get — when the user asks "what was '
                'that about", "summarize", "remind me of the X dialectic", or '
                'any other request that does not require the full conversation '
                'body. Accepts a UUID, id prefix, or topic substring.'
            ),
            inputSchema={
                'type': 'object',
                'properties': {
                    'id': {
                        'type': 'string',
                        'description': 'Dialectic UUID, short id prefix, or topic substring',
                    },
                    'tail_turns': {
                        'type': 'integer',
                        'description': 'How many trailing turns to include after the first. Default 4, max 20.',
                        'default': 4,
                    },
                },
                'required': ['id'],
            },
        ),
        types.Tool(
            name='dialectic_close',
            description=(
                'Mark a dialectic as closed. Call this when the user signals the conversation is over '
                '(e.g. "thanks for the chat", "I\'m done with this topic"). '
                'Sets closed_at and status=closed on the record. No more turns should be appended after this.'
            ),
            inputSchema={
                'type': 'object',
                'properties': {
                    'id': {
                        'type': 'string',
                        'description': 'Dialectic UUID, short id prefix, or topic substring to close',
                    },
                },
                'required': ['id'],
            },
        ),
        types.Tool(
            name='dialectic_resume',
            description=(
                'Re-open a previously closed dialectic so the conversation can continue. '
                'Clears the closed_at timestamp and sets status back to open. '
                'Returns the full record (including prior turns and topic) so the session can resume. '
                'Call this when the user asks to resume, reopen, or continue a past dialectic.'
            ),
            inputSchema={
                'type': 'object',
                'properties': {
                    'id': {
                        'type': 'string',
                        'description': 'Dialectic UUID, short id prefix, or topic substring to re-open',
                    },
                },
                'required': ['id'],
            },
        ),
        types.Tool(
            name='send_message',
            description=(
                'Send an iMessage/SMS via the local message bridge. '
                'Recipient can be a name (matched against recent chats) or a phone number/email. '
                'Use delay_minutes to schedule the send for later.'
            ),
            inputSchema={
                'type': 'object',
                'properties': {
                    'recipient': {
                        'type': 'string',
                        'description': 'Name (e.g. "Nicole Wise"), phone number, or email address',
                    },
                    'message': {'type': 'string', 'description': 'Message text'},
                    'service': {
                        'type': 'string',
                        'description': 'iMessage, SMS, or RCS (only needed for new threads)',
                        'default': 'iMessage',
                    },
                    'delay_minutes': {
                        'type': 'integer',
                        'description': 'Minutes from now to send. 0 or omitted = send immediately.',
                        'default': 0,
                    },
                },
                'required': ['recipient', 'message'],
            },
        ),
        types.Tool(
            name='log_weight',
            description=(
                'Log a weight measurement. The chat agent should ask the user for '
                'their weight in pounds and pass it as a number. If the user gives '
                'a date other than today (e.g. "yesterday morning"), include date '
                'as YYYY-MM-DD.'
            ),
            inputSchema={
                'type': 'object',
                'properties': {
                    'pounds': {
                        'type': 'number',
                        'description': 'Weight in pounds (lbs).',
                    },
                    'date': {
                        'type': 'string',
                        'description': 'Optional ISO date YYYY-MM-DD. Defaults to today.',
                    },
                    'note': {'type': 'string', 'description': 'Optional free-text note.'},
                },
                'required': ['pounds'],
            },
        ),
        types.Tool(
            name='log_alcohol',
            description=(
                'Log an alcohol consumption episode. The chat agent converts the '
                "user's natural-language description into US standard drinks "
                '(1 drink = 14g pure ethanol = 5oz wine = 12oz 5% beer = 1.5oz '
                'spirit) and passes the count. ALWAYS include the original raw '
                'description so the user can review it later.'
            ),
            inputSchema={
                'type': 'object',
                'properties': {
                    'drinks': {
                        'type': 'number',
                        'description': 'Total US standard drinks consumed in this episode.',
                    },
                    'raw_input': {
                        'type': 'string',
                        'description': "The user's original natural-language description.",
                    },
                    'items': {
                        'type': 'array',
                        'description': 'Optional itemization, e.g. [{"kind":"wine","count":2.5}]',
                        'items': {
                            'type': 'object',
                            'properties': {
                                'kind':  {'type': 'string'},
                                'count': {'type': 'number'},
                            },
                        },
                    },
                    'date': {
                        'type': 'string',
                        'description': 'Optional ISO date YYYY-MM-DD. Defaults to today.',
                    },
                },
                'required': ['drinks', 'raw_input'],
            },
        ),
        types.Tool(
            name='log_exercise',
            description=(
                'Log an exercise session. The chat agent extracts duration in '
                'minutes and intensity ("light"/"moderate"/"vigorous") from the '
                "user's description. ALWAYS include raw_input."
            ),
            inputSchema={
                'type': 'object',
                'properties': {
                    'minutes':   {'type': 'number',  'description': 'Duration in minutes.'},
                    'intensity': {
                        'type': 'string',
                        'enum': ['light', 'moderate', 'vigorous'],
                        'description': 'Perceived intensity.',
                    },
                    'kind':      {'type': 'string', 'description': 'Free-text kind (e.g. "run", "yoga").'},
                    'raw_input': {'type': 'string', 'description': "User's original description."},
                    'date': {
                        'type': 'string',
                        'description': 'Optional ISO date YYYY-MM-DD. Defaults to today.',
                    },
                },
                'required': ['minutes', 'intensity', 'raw_input'],
            },
        ),
        types.Tool(
            name='get_health_summary',
            description=(
                'Return fresh health-metric status (weight, alcohol, exercise) from '
                'the JSONL log files: latest values, today_logged status, 7- and '
                '30-day totals, and trend direction. Use this when the user asks '
                'how they are doing on a metric instead of relying on the briefing '
                'snapshot, which may be stale.'
            ),
            inputSchema={'type': 'object', 'properties': {}},
        ),
        types.Tool(
            name='get_time',
            description=(
                "Get the current local date and time on the briefing server. "
                "Call this whenever the user asks what time/day/date it is, or when "
                "you need 'now' to interpret a relative time."
            ),
            inputSchema={'type': 'object', 'properties': {}},
        ),
        types.Tool(
            name='get_public_ip',
            description=(
                "Get the public IPv4 address of the home internet connection the "
                "briefing server is on. Useful for remote access checks and "
                "diagnostics."
            ),
            inputSchema={'type': 'object', 'properties': {}},
        ),
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict):
    import requests as req

    config = _load_config()
    agent_cfg = config.get('agent', {})

    if name == 'add_todo':
        title = arguments.get('title', '').strip()
        if not title:
            return [types.TextContent(type='text', text='Error: title is required')]
        import shutil
        add_cmd = config.get('todos', {}).get('add_command', 'checkmate add')
        cmd_parts = shlex.split(add_cmd)
        resolved = shutil.which(cmd_parts[0])
        if resolved:
            cmd_parts[0] = resolved
        try:
            result = subprocess.run(
                cmd_parts + ['--', title],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode == 0:
                return [types.TextContent(type='text', text=f'Added todo: {title}')]
            return [types.TextContent(type='text', text=f'Error: {result.stderr.strip()}')]
        except Exception as e:
            return [types.TextContent(type='text', text=f'Error: {e}')]

    if name == 'send_notification':
        title = arguments.get('title', '')
        message = arguments.get('message', '')
        priority = int(arguments.get('priority', 0))
        if priority not in (-1, 0, 1):
            return [types.TextContent(type='text', text='Error: priority must be -1, 0, or 1')]
        app_token = agent_cfg.get('pushover_app_token', '')
        user_key = agent_cfg.get('pushover_user_key', '')
        if not app_token or not user_key:
            return [types.TextContent(type='text', text='Pushover not configured in config.json agent section')]
        payload = {
            'token': app_token, 'user': user_key,
            'title': title, 'message': message, 'priority': priority,
        }
        if priority == 1:
            payload.update({'retry': 60, 'expire': 3600})
        device = agent_cfg.get('pushover_device', '')
        if device:
            payload['device'] = device
        sound = agent_cfg.get('pushover_sound', '')
        if sound:
            payload['sound'] = sound
        try:
            r = req.post('https://api.pushover.net/1/messages.json', data=payload, timeout=10)
            r.raise_for_status()
        except req.exceptions.HTTPError:
            return [types.TextContent(type='text', text=f'Pushover error: HTTP {r.status_code}')]
        except req.exceptions.RequestException:
            return [types.TextContent(type='text', text='Network error sending notification')]
        return [types.TextContent(type='text', text=f'Sent: {title}')]

    if name == 'refresh_briefing':
        script = os.path.join(BASE_DIR, 'src', 'build_briefing.py')
        venv_python = os.path.join(BASE_DIR, '.venv', 'bin', 'python3')
        python = venv_python if os.path.exists(venv_python) else sys.executable
        try:
            proc = await asyncio.create_subprocess_exec(
                python, script,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)
            output = (stdout.decode() + stderr.decode()).strip()
            lines = output.split('\n')
            return [types.TextContent(type='text', text='\n'.join(lines[-8:]))]
        except asyncio.TimeoutError:
            proc.kill()
            return [types.TextContent(type='text', text='Error: timed out after 120s')]
        except Exception as e:
            return [types.TextContent(type='text', text=f'Error: {e}')]

    if name == 'add_calendar_event':
        import uuid
        import icalendar
        from datetime import date as date_type, datetime as datetime_type, timedelta

        def _parse_date(s):
            s = s.strip().lower()
            today = date_type.today()
            if s == 'today':
                return today
            if s == 'tomorrow':
                return today + timedelta(days=1)
            return date_type.fromisoformat(s)

        def _parse_time(s):
            s = s.strip().upper().replace('.', '')
            ampm = None
            if s.endswith('AM') or s.endswith('PM'):
                ampm = s[-2:]
                s = s[:-2].strip()
            parts = s.split(':')
            hour = int(parts[0])
            minute = int(parts[1]) if len(parts) > 1 else 0
            if ampm == 'PM' and hour != 12:
                hour += 12
            elif ampm == 'AM' and hour == 12:
                hour = 0
            return hour, minute

        title = arguments.get('title', '').strip()
        date_str = arguments.get('date', '').strip()
        start_time_str = arguments.get('start_time', '')
        end_time_str = arguments.get('end_time', '')
        location = arguments.get('location', '').strip()
        notes = arguments.get('notes', '').strip()
        cal_name = arguments.get('calendar', '').strip()

        if not title or not date_str:
            return [types.TextContent(type='text', text='Error: title and date are required')]

        try:
            event_date = _parse_date(date_str)
        except ValueError:
            return [types.TextContent(type='text', text=f'Error: could not parse date "{date_str}"')]

        # Build dtstart / dtend
        all_day = not start_time_str
        if all_day:
            dtstart = event_date
            dtend = event_date + timedelta(days=1)
        else:
            try:
                sh, sm = _parse_time(start_time_str)
            except (ValueError, IndexError):
                return [types.TextContent(type='text', text=f'Error: could not parse start_time "{start_time_str}"')]
            dtstart = datetime_type(event_date.year, event_date.month, event_date.day, sh, sm)
            if end_time_str:
                try:
                    eh, em = _parse_time(end_time_str)
                except (ValueError, IndexError):
                    return [types.TextContent(type='text', text=f'Error: could not parse end_time "{end_time_str}"')]
                dtend = datetime_type(event_date.year, event_date.month, event_date.day, eh, em)
            else:
                dtend = dtstart + timedelta(hours=1)

        # Find writable calendar
        all_cals = (config.get('calendars', {}).get('mine', []) +
                    config.get('calendars', {}).get('family', []))
        writable = [c for c in all_cals if c.get('writable')]
        if not writable:
            return [types.TextContent(type='text', text='No writable calendars configured. Add "writable": true to a calendar entry in config.json.')]
        if cal_name:
            target = next((c for c in writable if c['name'].lower() == cal_name.lower()), None)
            if not target:
                names = ', '.join(c['name'] for c in writable)
                return [types.TextContent(type='text', text=f'Calendar "{cal_name}" not found or not writable. Writable: {names}')]
        else:
            target = next((c for c in writable if c.get('default')), writable[0])

        # Resolve CalDAV write URL and auth
        url = target.get('caldav_write_url') or target.get('url', '')
        # Strip ?export suffix to get the CalDAV collection URL
        if '?' in url:
            url = url[:url.index('?')]
        if not url.endswith('/'):
            url += '/'

        owncloud_cfg = config.get('owncloud', {})
        if url.startswith('http://') or url.startswith('https://'):
            cdav_user = target.get('caldav_username', '')
            cdav_pass = target.get('caldav_password', '')
            auth = (cdav_user, cdav_pass) if cdav_user else None
            ssl_verify = True
            full_url = url
        else:
            base = owncloud_cfg.get('base_url', '').rstrip('/')
            auth = (owncloud_cfg['username'], owncloud_cfg['password'])
            ssl_verify = owncloud_cfg.get('ssl_verify', True)
            full_url = base + url

        # Build iCalendar payload
        uid = str(uuid.uuid4()) + '@daily-briefing'
        cal_obj = icalendar.Calendar()
        cal_obj.add('prodid', '-//Daily Briefing MCP//EN')
        cal_obj.add('version', '2.0')
        ev = icalendar.Event()
        ev.add('uid', uid)
        ev.add('summary', title)
        ev.add('dtstart', dtstart)
        ev.add('dtend', dtend)
        ev.add('dtstamp', datetime_type.utcnow())
        if location:
            ev.add('location', location)
        if notes:
            ev.add('description', notes)
        cal_obj.add_component(ev)
        ics_bytes = cal_obj.to_ical()

        put_url = full_url + uid + '.ics'
        try:
            r = req.put(
                put_url, data=ics_bytes, auth=auth, verify=ssl_verify,
                headers={'Content-Type': 'text/calendar; charset=utf-8'},
                timeout=15,
            )
            r.raise_for_status()
        except req.exceptions.HTTPError:
            return [types.TextContent(type='text', text=f'CalDAV error: HTTP {r.status_code}')]
        except req.exceptions.RequestException as e:
            return [types.TextContent(type='text', text=f'Error reaching CalDAV server: {e}')]

        date_label = event_date.strftime('%A, %B %-d')
        if all_day:
            time_label = 'all day'
        else:
            time_label = dtstart.strftime('%-I:%M %p')
            if end_time_str:
                time_label += '–' + dtend.strftime('%-I:%M %p')
        return [types.TextContent(type='text', text=f'Added "{title}" to {target["name"]} on {date_label} ({time_label})')]

    if name == 'send_message':
        from datetime import datetime, timedelta
        recipient = arguments.get('recipient', '').strip()
        message = arguments.get('message', '').strip()
        service = arguments.get('service', 'iMessage')
        delay_minutes = int(arguments.get('delay_minutes', 0))

        if not recipient or not message:
            return [types.TextContent(type='text', text='Error: recipient and message are required')]
        if service not in ('iMessage', 'SMS', 'RCS'):
            return [types.TextContent(type='text', text='Error: service must be iMessage, SMS, or RCS')]

        bridge_cfg = config.get('imessage', {})
        bridge_url = bridge_cfg.get('url', '').rstrip('/')
        if not bridge_url:
            return [types.TextContent(type='text', text='Error: imessage.url not set in config.json')]

        # Resolve a name to a replyId by searching recent chats
        address = recipient
        is_reply = False
        display_name = recipient
        phone_like = recipient.startswith('+') or recipient.replace('-', '').replace(' ', '').isdigit()
        email_like = '@' in recipient
        if not phone_like and not email_like:
            try:
                resp = req.get(bridge_url + '/chats', params={'limit': 50}, timeout=10)
                resp.raise_for_status()
                chats = resp.json()
                name_lower = recipient.lower()
                match = next((c for c in chats if name_lower in c.get('name', '').lower()), None)
                if match:
                    address = match['replyId']
                    is_reply = True
                    display_name = match['name']
                else:
                    return [types.TextContent(type='text', text=f'No chat found matching "{recipient}". Use a phone number or email to start a new thread.')]
            except req.exceptions.RequestException as e:
                return [types.TextContent(type='text', text=f'Error reaching message bridge: {e}')]

        if delay_minutes <= 0:
            try:
                payload = {'address': address, 'isReply': is_reply, 'service': service, 'message': message}
                r = req.post(bridge_url + '/chats', json=payload, timeout=10)
                r.raise_for_status()
                return [types.TextContent(type='text', text=f'Sent to {display_name}: {message}')]
            except req.exceptions.HTTPError:
                return [types.TextContent(type='text', text=f'Bridge error: HTTP {r.status_code}')]
            except req.exceptions.RequestException as e:
                return [types.TextContent(type='text', text=f'Error reaching message bridge: {e}')]
        else:
            send_at = (datetime.now() + timedelta(minutes=delay_minutes)).replace(second=0, microsecond=0)
            task = asyncio.create_task(
                _send_after_delay(delay_minutes * 60, bridge_url, address, is_reply, service, message, display_name)
            )
            _pending_tasks.add(task)
            task.add_done_callback(_pending_tasks.discard)
            when = send_at.strftime('%-I:%M %p')
            return [types.TextContent(type='text', text=f'Scheduled to {display_name} at {when}: {message}')]

    if name == 'dialectic_save':
        import uuid
        from datetime import datetime, timezone
        topic = arguments.get('topic', '').strip()
        turns_raw = arguments.get('turns', [])
        tags = arguments.get('tags', [])
        if not topic:
            return [types.TextContent(type='text', text='Error: topic is required')]
        if not turns_raw:
            return [types.TextContent(type='text', text='Error: turns must not be empty')]
        _ensure_conversations_dir()
        now = datetime.now(timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')
        dialectic_id = str(uuid.uuid4())
        now_ts = now
        turns = [
            {'role': t['role'], 'content': t['content'], 'timestamp': now_ts}
            for t in turns_raw
            if t.get('role') in ('user', 'assistant') and t.get('content')
        ]
        record = {
            'id': dialectic_id,
            'topic': topic,
            'tags': tags,
            'created_at': now,
            'updated_at': now,
            'turns': turns,
        }
        path = os.path.join(CONVERSATIONS_DIR, f'{dialectic_id}.json')
        with open(path, 'w') as f:
            json.dump(record, f, indent=2)
        try:
            dialectic_prompt = _load_config().get('dialectic', {}).get('system_prompt', '')
        except Exception:
            dialectic_prompt = ''
        reply = f'Dialectic saved — id: {dialectic_id}, topic: "{topic}", {len(turns)} turns'
        if dialectic_prompt:
            reply += f'\n\nDialectic stance for this session: {dialectic_prompt}'
        return [types.TextContent(type='text', text=reply)]

    if name == 'dialectic_append':
        from datetime import datetime, timezone
        ref = arguments.get('id', '').strip()
        turns_raw = arguments.get('turns', [])
        if not ref:
            raise ValueError('id is required')
        if not turns_raw:
            raise ValueError('turns must not be empty')
        _ensure_conversations_dir()
        status, payload = _resolve_dialectic_ref(ref)
        if status == 'missing':
            raise ValueError(f'dialectic "{ref}" not found')
        if status == 'ambiguous':
            return [types.TextContent(type='text', text=_format_ambiguous(payload))]
        dialectic_id = payload
        path = os.path.join(CONVERSATIONS_DIR, f'{dialectic_id}.json')
        with open(path) as f:
            record = json.load(f)
        now = datetime.now(timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')
        new_turns = [
            {'role': t['role'], 'content': t['content'], 'timestamp': now}
            for t in turns_raw
            if t.get('role') in ('user', 'assistant') and t.get('content')
        ]
        record['turns'].extend(new_turns)
        record['updated_at'] = now
        with open(path, 'w') as f:
            json.dump(record, f, indent=2)
        total = len(record['turns'])
        return [types.TextContent(type='text', text=f'Appended {len(new_turns)} turn(s) to "{record["topic"]}" — now {total} turns total')]

    if name == 'dialectic_list':
        items = _list_dialectics()
        if not items:
            return [types.TextContent(type='text', text='No dialectics saved yet.')]
        lines = ['Saved dialectics:']
        for d in items:
            lines.append(f'  {d["id"]} | {d["topic"]} | {d["turn_count"]} turns | {d["updated_at"]}')
        return [types.TextContent(type='text', text='\n'.join(lines))]

    if name == 'dialectic_get':
        ref = arguments.get('id', '').strip()
        if not ref:
            raise ValueError('id is required')
        _ensure_conversations_dir()
        status, payload = _resolve_dialectic_ref(ref)
        if status == 'missing':
            raise ValueError(f'dialectic "{ref}" not found')
        if status == 'ambiguous':
            return [types.TextContent(type='text', text=_format_ambiguous(payload))]
        path = os.path.join(CONVERSATIONS_DIR, f'{payload}.json')
        with open(path) as f:
            record = json.load(f)
        return [types.TextContent(type='text', text=json.dumps(record, indent=2))]

    if name == 'dialectic_summary':
        ref = arguments.get('id', '').strip()
        if not ref:
            raise ValueError('id is required')
        try:
            tail_turns = int(arguments.get('tail_turns', 4))
        except (TypeError, ValueError):
            tail_turns = 4
        tail_turns = max(1, min(20, tail_turns))
        _ensure_conversations_dir()
        status, payload = _resolve_dialectic_ref(ref)
        if status == 'missing':
            raise ValueError(f'dialectic "{ref}" not found')
        if status == 'ambiguous':
            return [types.TextContent(type='text', text=_format_ambiguous(payload))]
        path = os.path.join(CONVERSATIONS_DIR, f'{payload}.json')
        with open(path) as f:
            record = json.load(f)
        turns = record.get('turns', [])
        n = len(turns)
        if n <= tail_turns + 1:
            included = turns
            elided = 0
        else:
            included = [turns[0]] + turns[-tail_turns:]
            elided = n - tail_turns - 1
        summary = {
            'id':         record.get('id'),
            'topic':      record.get('topic'),
            'tags':       record.get('tags', []),
            'status':     record.get('status', 'open'),
            'created_at': record.get('created_at'),
            'updated_at': record.get('updated_at'),
            'closed_at':  record.get('closed_at'),
            'turn_count': n,
            'turns_elided_from_middle': elided,
            'turns':      included,
        }
        return [types.TextContent(type='text', text=json.dumps(summary, indent=2))]

    if name == 'dialectic_close':
        from datetime import datetime, timezone
        ref = arguments.get('id', '').strip()
        if not ref:
            raise ValueError('id is required')
        _ensure_conversations_dir()
        status, payload = _resolve_dialectic_ref(ref)
        if status == 'missing':
            raise ValueError(f'dialectic "{ref}" not found')
        if status == 'ambiguous':
            return [types.TextContent(type='text', text=_format_ambiguous(payload))]
        dialectic_id = payload
        path = os.path.join(CONVERSATIONS_DIR, f'{dialectic_id}.json')
        try:
            with open(path) as f:
                record = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            return [types.TextContent(type='text', text=f'Error reading dialectic: {e}')]
        if record.get('status') == 'closed':
            return [types.TextContent(type='text', text=f'Dialectic "{record["topic"]}" is already closed.')]
        now = datetime.now(timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')
        record['status'] = 'closed'
        record['closed_at'] = now
        record['updated_at'] = now
        try:
            with open(path, 'w') as f:
                json.dump(record, f, indent=2)
        except OSError as e:
            return [types.TextContent(type='text', text=f'Error writing dialectic: {e}')]
        return [types.TextContent(type='text', text=f'Dialectic "{record["topic"]}" closed.')]

    if name == 'dialectic_resume':
        from datetime import datetime, timezone
        ref = arguments.get('id', '').strip()
        if not ref:
            raise ValueError('id is required')
        _ensure_conversations_dir()
        status, payload = _resolve_dialectic_ref(ref)
        if status == 'missing':
            raise ValueError(f'dialectic "{ref}" not found')
        if status == 'ambiguous':
            return [types.TextContent(type='text', text=_format_ambiguous(payload))]
        dialectic_id = payload
        path = os.path.join(CONVERSATIONS_DIR, f'{dialectic_id}.json')
        try:
            with open(path) as f:
                record = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            return [types.TextContent(type='text', text=f'Error reading dialectic: {e}')]
        if record.get('status') != 'closed':
            return [types.TextContent(type='text', text=f'Dialectic "{record["topic"]}" is already open.')]
        now = datetime.now(timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')
        record['status'] = 'open'
        record.pop('closed_at', None)
        record['updated_at'] = now
        try:
            with open(path, 'w') as f:
                json.dump(record, f, indent=2)
        except OSError as e:
            return [types.TextContent(type='text', text=f'Error writing dialectic: {e}')]
        try:
            dialectic_prompt = _load_config().get('dialectic', {}).get('system_prompt', '')
        except Exception:
            dialectic_prompt = ''
        reply = f'Dialectic "{record["topic"]}" reopened — id: {dialectic_id}, {len(record.get("turns", []))} prior turns'
        if dialectic_prompt:
            reply += f'\n\nDialectic stance for this session: {dialectic_prompt}'
        reply += f'\n\nPrior conversation:\n{json.dumps(record, indent=2)}'
        return [types.TextContent(type='text', text=reply)]

    if name in ('log_weight', 'log_alcohol', 'log_exercise'):
        from datetime import datetime, timezone
        health_dir = os.path.join(DATA_DIR, 'health')
        os.makedirs(health_dir, exist_ok=True)
        now = datetime.now(timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')
        local_date = arguments.get('date') or datetime.now().strftime('%Y-%m-%d')
        try:
            datetime.strptime(local_date, '%Y-%m-%d')
        except ValueError:
            return [types.TextContent(type='text', text=f'Error: invalid date "{local_date}", expected YYYY-MM-DD')]

        if name == 'log_weight':
            try:
                pounds = float(arguments['pounds'])
            except (KeyError, TypeError, ValueError):
                return [types.TextContent(type='text', text='Error: pounds must be a number')]
            if pounds <= 0 or pounds > 1000:
                return [types.TextContent(type='text', text='Error: pounds out of range')]
            entry = {
                'ts': now, 'date': local_date, 'pounds': round(pounds, 1),
                'note': arguments.get('note', ''),
            }
            path = os.path.join(health_dir, 'weight.jsonl')
            reply = f'Logged weight: {entry["pounds"]} lbs on {local_date}.'
        elif name == 'log_alcohol':
            try:
                drinks = float(arguments['drinks'])
            except (KeyError, TypeError, ValueError):
                return [types.TextContent(type='text', text='Error: drinks must be a number')]
            if drinks < 0 or drinks > 50:
                return [types.TextContent(type='text', text='Error: drinks out of range')]
            entry = {
                'ts': now, 'date': local_date,
                'drinks': round(drinks, 2),
                'raw_input': arguments.get('raw_input', '').strip(),
                'items': arguments.get('items', []),
            }
            path = os.path.join(health_dir, 'alcohol.jsonl')
            reply = f'Logged {entry["drinks"]} standard drink(s) on {local_date}: {entry["raw_input"]}'
        else:  # log_exercise
            try:
                minutes = float(arguments['minutes'])
            except (KeyError, TypeError, ValueError):
                return [types.TextContent(type='text', text='Error: minutes must be a number')]
            intensity = arguments.get('intensity', '')
            if intensity not in ('light', 'moderate', 'vigorous'):
                return [types.TextContent(type='text', text='Error: intensity must be light/moderate/vigorous')]
            if minutes <= 0 or minutes > 1440:
                return [types.TextContent(type='text', text='Error: minutes out of range')]
            entry = {
                'ts': now, 'date': local_date,
                'minutes': int(round(minutes)),
                'intensity': intensity,
                'kind': arguments.get('kind', ''),
                'raw_input': arguments.get('raw_input', '').strip(),
            }
            path = os.path.join(health_dir, 'exercise.jsonl')
            reply = (f'Logged {entry["minutes"]} min of {intensity} '
                     f'{entry["kind"] or "exercise"} on {local_date}.')

        with open(path, 'a') as f:
            f.write(json.dumps(entry) + '\n')
        return [types.TextContent(type='text', text=reply)]

    if name == 'get_health_summary':
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from fetch_health import fetch_health  # type: ignore
        summary = fetch_health(config, compact=True)
        return [types.TextContent(type='text', text=json.dumps(summary, indent=2))]

    if name == 'get_time':
        from datetime import datetime, timezone
        local = datetime.now().astimezone()
        utc = datetime.now(timezone.utc)
        tz_name = local.strftime('%Z') or local.tzname() or 'local'
        reply = (
            f'Local: {local.strftime("%A, %B %-d, %Y at %-I:%M:%S %p")} ({tz_name})\n'
            f'ISO local: {local.isoformat(timespec="seconds")}\n'
            f'UTC: {utc.isoformat(timespec="seconds").replace("+00:00", "Z")}'
        )
        return [types.TextContent(type='text', text=reply)]

    if name == 'get_public_ip':
        try:
            r = req.get('https://api.ipify.org', timeout=5)
            r.raise_for_status()
            ip = r.text.strip()
            return [types.TextContent(type='text', text=f'Public IP: {ip}')]
        except Exception as e:
            return [types.TextContent(type='text', text=f'Error fetching public IP: {e}')]

    raise ValueError(f'Unknown tool: {name}')


async def _main():
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


if __name__ == '__main__':
    asyncio.run(_main())
