"""Single source of truth for where runtime data lives.

Everything the app writes — briefing.json, chat sessions, health logs,
dialectics, scheduled messages, agent state, webhook state — sits under one
directory. That directory is normally <repo>/data, but `DB_DATA_DIR` overrides
it.

The override exists so tests never touch real data. Point DB_DATA_DIR at a temp
directory and the whole app — the briefing build, the MCP server, the chat
handler, the webhook — reads and writes there instead, so a test run cannot
delete or truncate a live chat session, health log, or dialectic. There is no
"clean up afterwards" step to get wrong: throw the temp directory away.

The PHP half of the app resolves the same variable in web/paths.php; the two
must agree, since web/chat.php and web/webhook.php spawn the Python handler and
pass DB_DATA_DIR through to it.
"""
import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def data_dir():
    """Absolute path to the runtime data directory. Honours DB_DATA_DIR."""
    override = os.environ.get('DB_DATA_DIR', '').strip()
    if override:
        return os.path.abspath(os.path.expanduser(override))
    return os.path.join(BASE_DIR, 'data')


def data_path(*parts):
    """Path to something inside the data directory."""
    return os.path.join(data_dir(), *parts)


def ensure_data_dir(*parts):
    """Like data_path, but creates the containing directory first."""
    path = data_path(*parts)
    parent = path if not parts else os.path.dirname(path)
    os.makedirs(parent, exist_ok=True)
    return path
