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
- Health metrics — weight, alcohol, exercise with 30-day sparklines and target-aware trend badges
- Chat box — talk to the same MCP-tool surface from any device that can render basic HTML (incl. legacy browsers like the 2011 webOS TouchPad)

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
| `send_notification` | tool | Send a Pushover notification (priority -1/0/1) |
| `refresh_briefing` | tool | Rebuild briefing.json on demand |
| `add_calendar_event` | tool | Create a CalDAV event on any writable calendar |
| `send_message` | tool | Send an iMessage/SMS via the message bridge, optionally delayed |
| `log_weight` / `log_alcohol` / `log_exercise` | tool | Append health logs; chat agent converts natural language to standard units |
| `get_health_summary` | tool | Live read of `data/health/*.jsonl` (fresher than briefing.json) |
| `get_time` / `get_public_ip` | tool | System clock + outbound IP for diagnostics |
| `dialectic_save` / `_append` / `_list` / `_get` / `_summary` / `_close` / `_resume` | tool | Persist and resume exploratory conversations (`_summary` returns a compact recap) |

### Adding calendar events

Mark any calendar in `config.json` as writable with `"writable": true`. For ownCloud-hosted calendars the write URL is derived automatically from the existing export URL. For external CalDAV providers (e.g. Zoho) add the CalDAV-specific credentials:

```json
{
  "name": "Personal",
  "url": "https://calendar.zoho.com/ical/your-read-token",
  "writable": true,
  "default": true,
  "caldav_write_url": "https://calendar.zoho.com/caldav/your_account_id/events/your_calendar_uid/",
  "caldav_username": "you@zoho.com",
  "caldav_password": "your-app-password"
}
```

Set `"default": true` on the calendar Claude should use when none is specified. Then ask naturally:

> "Add a dentist appointment next Thursday at 2pm"  
> "Add a team lunch to my Work calendar on Friday from noon to 1pm at the pizza place"

Calendars can live in either the `mine` or `family` section — the tool searches both, so no need to move a calendar just to make it writable.

### Sending messages

Requires the [message-bridge](https://github.com/dremin/message-bridge) running locally. Configure its URL under `imessage.url` in `config.json`. Recipients can be matched by name against recent chats or given as a phone number/email. Use `delay_minutes` to schedule a send:

> "Send a message to Nicole in 15 minutes saying I'm on my way"  
> "Text Ben at 555-1234 to say happy birthday"

Delayed sends are held as asyncio tasks in the running MCP server — if the Claude Code session ends before the delay expires the send will not fire.

### Updating after code changes

After a `git pull` on the host machine, restart just the MCP server from within your Claude Code session (use `/mcp` to find the reconnect option) — no need to quit the session.

For remote access (phone, another machine), run `claude --tunnel` on the host — it gives you a URL that connects to your local Claude Code session with MCP context attached.

## Web chat

A chat box at the bottom of the briefing page lets you reach the same MCP tool surface from a browser — handy when the Claude desktop/mobile app isn't an option (legacy device, kiosk, etc.). Enable in `config/config.json`:

```json
"chat_agent": {
  "enabled": true,
  "model": "claude-sonnet-4-6",
  "shared_secret": "",
  "allowed_tools": ["dialectic_save", "log_weight", "refresh_briefing", "..."]
}
```

`allowed_tools` is a subset of the MCP server's full surface — set it to whatever you're comfortable exposing through a webpage. The chat box only renders when `enabled: true`. Leave `shared_secret` blank to skip auth (page reachability == chat reachability) or set a passphrase the browser stores in `localStorage`.

Per-device sessions are persisted under `data/chat_sessions/<id>.json`; on page load the last few turns are pre-rendered so the chat doesn't feel "empty."

## Health tracking

Add a `health` block to `config/config.json` to enable weight / alcohol / exercise tracking with sparklines on the briefing page:

```json
"health": {
  "weight":   { "unit": "lbs", "goal_direction": "down" },
  "alcohol":  { "weekly_target_drinks": 15 },
  "exercise": { "weekly_target_minutes": 150 },
  "missed_notify_hour": 7,
  "chart_days": 30
}
```

Then log in plain English via the chat — "shared a bottle of wine with Nicole" or "ran 4 miles this morning" — and the agent converts to US standard drinks / minutes+intensity before appending to `data/health/*.jsonl`. Add a `health_missing` entry to `agent_rules.json` to get a Pushover reminder when a metric hasn't been logged today.

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
