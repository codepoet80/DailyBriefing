import subprocess
import re
from html import unescape


def fetch_todos(config):
    todo_cfg = config.get('todos', {})
    command = todo_cfg.get('command', 'checkmate ls')
    count = todo_cfg.get('count', 8)

    print('    Running: ' + command)
    try:
        result = subprocess.run(
            command.split(),
            capture_output=True,
            text=True,
            timeout=10
        )
        lines = result.stdout.splitlines()
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
