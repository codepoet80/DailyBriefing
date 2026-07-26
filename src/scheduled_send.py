#!/usr/bin/env python3
"""Detached worker that sends one scheduled BlueBubbles message at its due time.

Spawned (start_new_session) by mcp_server.py's send_message tool when a delay is
requested. Running in its own session is the whole point: the MCP server is a
short-lived stdio subprocess that gets torn down at the end of a chat request,
so an in-process asyncio timer would be killed before it fires. This worker
survives that teardown, waits until send_at, sends, and removes the job file.

Job file schema (data/scheduled_messages/<uuid>.json):
  { send_at (ISO/UTC), kind ("chat"|"new"), target, service, message, display_name }

The BlueBubbles config (incl. password) is NOT stored in the job — the worker
reloads it from config/config.json at send time.
"""
import json
import os
import sys
import time
from datetime import datetime, timezone

BASE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bluebubbles as bb  # noqa: E402


def _log(msg):
    print(f'[scheduled_send] {datetime.now().isoformat(timespec="seconds")} {msg}',
          flush=True)


def main(job_path):
    try:
        with open(job_path) as f:
            job = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        _log(f'could not read job {job_path}: {e}')
        return 1

    send_at = datetime.fromisoformat(job['send_at'])
    delay = (send_at - datetime.now(timezone.utc)).total_seconds()
    if delay > 0:
        time.sleep(delay)

    with open(os.path.join(BASE_DIR, 'config', 'config.json')) as f:
        cfg = bb.get_bb_config(json.load(f))
    if not cfg:
        _log('bluebubbles not configured; leaving job for inspection')
        return 1

    who = job.get('display_name', job.get('target', '?'))
    try:
        if job['kind'] == 'chat':
            bb.send_text(cfg, job['target'], job['message'])
        else:
            bb.create_chat(cfg, job['target'], job['message'], job.get('service', 'iMessage'))
        _log(f'sent to {who}: {job["message"][:60]}')
        try:
            os.remove(job_path)
        except OSError:
            pass
        return 0
    except Exception as e:
        _log(f'FAILED to {who}: {e}')
        return 1


if __name__ == '__main__':
    if len(sys.argv) != 2:
        print('usage: scheduled_send.py <job.json>', file=sys.stderr)
        sys.exit(2)
    sys.exit(main(sys.argv[1]))
