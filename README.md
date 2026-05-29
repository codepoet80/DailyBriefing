# Daily Briefing

A self-hosted morning dashboard and personal push agent. A Python cron script fetches data from a dozen sources, writes `data/briefing.json`, and optionally pushes smart notifications via Pushover. A PHP page renders the JSON as a clean, read-only daily briefing.

Runs on macOS or Raspberry Pi. Frontend is compatible with a 2011 webOS TouchPad (WebKit 534, ES5 only, no CSS Grid).

## What it shows

- Verse of the Day
- Server status (green/amber banner)
- Weather — current + 5-day forecast
- Today's calendar events
- Todo list (from `checkmate`)
- GitHub notifications (unread, with type + reason)
- Top news stories (cross-source clustered)
- More news (collapsible)
- Geek News — HackerNews + Slashdot combined
- Family calendar — full week, grouped by day
- Tomorrow preview (afternoon run only)
- XKCD (when a new comic is out)

## Setup

```bash
cp config/config.json.example config/config.json
# edit config/config.json with your credentials and settings

cp config/feeds.json.example config/feeds.json
# edit feeds.json if you want different news sources

cp config/agent_rules.json.example config/agent_rules.json
# edit agent_rules.json if you want different notification rules

cp mcp.json .mcp.json
# edit .mcp.json with the path to this project


./run.sh                        # first run — creates .venv and builds briefing.json
php -S 0.0.0.0:8181 -t web/    # dev server
```

Add to crontab for automatic updates:
```
30 6  * * * /path/to/daily-briefing/run.sh
30 11 * * * /path/to/daily-briefing/run.sh
30 16 * * * /path/to/daily-briefing/run.sh
```

## Push agent (Pushover notifications)

After each briefing build, `run_agent.py` evaluates configured rules against the fresh data and sends Pushover notifications for anything new and matched.

```bash
cp config/agent_rules.json.example config/agent_rules.json
# edit agent_rules.json to configure rules
```

Add to `config/config.json`:
```json
"agent": {
  "enabled": true,
  "anthropic_api_key": "sk-ant-...",
  "model": "claude-haiku-4-5-20251001",
  "pushover_app_token": "YOUR_APP_TOKEN",
  "pushover_user_key": "YOUR_USER_KEY",
  "pushover_device": ""
}
```

### Rule types

| Type | Triggers when |
|------|--------------|
| `calendar` | A calendar event title matches `keywords` and starts within `window_minutes` |
| `family_calendar` | Any family calendar event falls on today |
| `server_status` | One or more monitored servers is down |
| `security` | Unifi Protect detected overnight events |
| `github` | Unread GitHub notifications match the `reasons` list |
| `news_keyword` | A news story title contains one of the `keywords` |
| `todos` | Open todos match `keywords` (e.g. `"!"`) at the configured `hour` |
| `weather` | Today's condition contains one of the `conditions` strings |

Each rule has `dedupe_hours` — the same match won't re-notify within that window. For `github`, dedup is also keyed on `updated_at`, so a notification only re-fires when there's new activity on the thread.

## Claude Code / MCP server

`src/mcp_server.py` exposes the briefing as an MCP resource so any Claude Code session has your full daily context automatically.

Install Claude Code, then add to `~/.claude/settings.json`:
```json
{
  "mcpServers": {
    "daily-briefing": {
      "command": "/path/to/DailyBriefing/.venv/bin/python3",
      "args": ["/path/to/DailyBriefing/src/mcp_server.py"]
    }
  }
}
```

Available resources and tools:

| Name | Type | Description |
|------|------|-------------|
| `briefing://current` | resource | Full briefing.json — calendar, todos, news, weather, GitHub |
| `briefing://memory` | resource | Agent push history and rule stats |
| `add_todo` | tool | Add a todo via `checkmate add` |
| `send_notification` | tool | Send a Pushover notification |
| `refresh_briefing` | tool | Rebuild briefing.json on demand |

For remote access (phone, another machine), run `claude --tunnel` on the host — it gives you a URL that connects to your local Claude Code session with MCP context attached.

## News feeds (`config/feeds.json`)

Each entry is an RSS feed. Optional flags control how stories are elevated to Top Stories:

| Flag | Effect |
|------|--------|
| `"always_important": true` | Every story from this feed is elevated to Top Stories |
| `"verge_wired_pair": true` | Elevated if 2+ feeds sharing this flag cover the same story |
| `"geek_only": true` | Appears only in Geek News, not Top Stories or More News |

Cross-source matching is controlled in `config.json`:
- `similarity_threshold` — how closely two headlines must match (default `0.65`)
- `importance_threshold` — how many sources must cover a story to elevate it (default `2`)

## Requirements

- Python 3.9+
- PHP 7.4+
- Dependencies installed automatically by `run.sh` into `.venv/`

See `CLAUDE.md` for full architecture documentation.
