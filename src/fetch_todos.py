import os
import shlex
import shutil
import subprocess
import re
from html import unescape


def resolve_command(command):
    """Split a configured todo command into argv with a usable executable.

    Shared with add_todo in mcp_server.py so the read and write sides accept the
    same config. Handles the three forms config.json can carry:
      - "${HOME}/bin/checkmate.py ls" / "~/bin/checkmate.py ls" — expanded
      - "/abs/path/checkmate.py ls"                             — used as-is
      - "checkmate ls"                                          — looked up on PATH

    shlex (not str.split) so a path containing spaces survives quoting.
    """
    parts = shlex.split(command)
    if not parts:
        return []
    parts[0] = os.path.expanduser(os.path.expandvars(parts[0]))
    resolved = shutil.which(parts[0])
    if resolved:
        parts[0] = resolved
    return parts


def fetch_todos(config):
    todo_cfg = config.get('todos', {})
    command = todo_cfg.get('command', 'checkmate ls')
    count = todo_cfg.get('count', 8)

    cmd_parts = resolve_command(command)
    if not cmd_parts:
        print('    Warning: todos.command is empty')
        return []

    print('    Running: ' + ' '.join(cmd_parts))
    try:
        result = subprocess.run(
            cmd_parts,
            capture_output=True,
            text=True,
            timeout=10
        )
        lines = result.stdout.splitlines()
    except FileNotFoundError:
        print('    Warning: todo command not found: ' + cmd_parts[0]
              + ' (check todos.command in config.json)')
        return []
    except Exception as e:
        print('    Warning: Could not run todo command: ' + str(e))
        return []

    todos = []
    for line in lines:
        # Match both incomplete (○) and complete (●) tasks: "  ○  N. Title"
        m = re.match(r'\s*([○●])\s+\d+\.\s+(.*)', line)
        if m:
            todos.append({
                'title': unescape(m.group(2).strip()),
                'done': m.group(1) == '●',
            })

    incomplete = [t for t in todos if not t['done']]
    print('    Got ' + str(len(incomplete)) + ' incomplete tasks (showing ' + str(min(count, len(incomplete))) + ')')
    return incomplete[:count]
