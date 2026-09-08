#!/usr/bin/env python3
"""Add a todo directly, without going through the agent.

    python3 src/capture_todo.py "Some title"

Exists so the webhook can ENFORCE the ring's capture-on-doubt rule instead of
asking the model to honour it. The ring has no way to receive a question, so a
question-shaped reply is a dropped request. When the agent produces one anyway,
webhook.php files the transcription itself by calling this — no model in the
loop, no way for it to be talked out of.

Shares fetch_todos.resolve_command so the ${HOME}/~/bare-name handling stays in
one place; exits non-zero with a message on stderr if the write fails.
"""
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fetch_todos import resolve_command  # noqa: E402

BASE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')


def capture(title, config=None):
    """Add a todo. Returns the resolved title, raises RuntimeError on failure."""
    title = (title or '').strip()
    if not title:
        raise RuntimeError('empty title')

    if config is None:
        import json
        with open(os.path.join(BASE_DIR, 'config', 'config.json')) as f:
            config = json.load(f)

    add_cmd = (config.get('todos') or {}).get('add_command', 'checkmate add')
    parts = resolve_command(add_cmd)
    if not parts:
        raise RuntimeError('todos.add_command is not configured')

    try:
        result = subprocess.run(parts + ['--', title],
                                capture_output=True, text=True, timeout=15)
    except FileNotFoundError:
        raise RuntimeError('todo command not found: %s' % parts[0])
    except subprocess.TimeoutExpired:
        raise RuntimeError('todo command timed out: %s' % parts[0])
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip()
                           or 'exit %d' % result.returncode)
    return title


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print('usage: capture_todo.py <title>', file=sys.stderr)
        sys.exit(2)
    try:
        print(capture(' '.join(sys.argv[1:])))
    except RuntimeError as e:
        print(str(e), file=sys.stderr)
        sys.exit(1)
