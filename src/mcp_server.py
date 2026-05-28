#!/usr/bin/env python3
"""MCP server — exposes briefing.json as context resources and action tools
so Claude Code (local or via remote tunnel) has your full daily context."""
import asyncio
import json
import os
import subprocess
import sys

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp import types

BASE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
DATA_DIR = os.path.join(BASE_DIR, 'data')
CONFIG_DIR = os.path.join(BASE_DIR, 'config')

app = Server('daily-briefing-agent')


def _load_briefing():
    with open(os.path.join(DATA_DIR, 'briefing.json')) as f:
        return json.load(f)


def _load_config():
    with open(os.path.join(CONFIG_DIR, 'config.json')) as f:
        return json.load(f)


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
        add_cmd = config.get('todos', {}).get('add_command', 'checkmate add')
        try:
            result = subprocess.run(
                add_cmd.split() + [title],
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
        priority = arguments.get('priority', 0)
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
        r = req.post('https://api.pushover.net/1/messages.json', data=payload, timeout=10)
        r.raise_for_status()
        return [types.TextContent(type='text', text=f'Sent: {title}')]

    if name == 'refresh_briefing':
        script = os.path.join(BASE_DIR, 'src', 'build_briefing.py')
        venv_python = os.path.join(BASE_DIR, '.venv', 'bin', 'python3')
        python = venv_python if os.path.exists(venv_python) else sys.executable
        try:
            result = subprocess.run(
                [python, script], capture_output=True, text=True, timeout=120,
            )
            lines = (result.stdout + result.stderr).strip().split('\n')
            return [types.TextContent(type='text', text='\n'.join(lines[-8:]))]
        except Exception as e:
            return [types.TextContent(type='text', text=f'Error: {e}')]

    raise ValueError(f'Unknown tool: {name}')


async def _main():
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


if __name__ == '__main__':
    asyncio.run(_main())
