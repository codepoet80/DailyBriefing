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
        print(f'[send_message] Sent to {display_name}: {message[:60]}', flush=True)
    except Exception as e:
        print(f'[send_message] Failed to send to {display_name}: {e}', flush=True)


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

    raise ValueError(f'Unknown tool: {name}')


async def _main():
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


if __name__ == '__main__':
    asyncio.run(_main())
