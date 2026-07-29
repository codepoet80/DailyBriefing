# Daily Briefing

A self-hosted morning dashboard and personal push agent. A Python cron script fetches data from ~15 sources, writes `data/briefing.json`, and optionally pushes smart notifications via Pushover. A PHP page renders the JSON as a clean, read-only daily briefing.

Runs on macOS or Raspberry Pi. Frontend is compatible with a 2011 webOS TouchPad (WebKit 534, ES5 only, no CSS Grid).

## What it shows

- Greeting — time-of-day salutation + a daily inspirational quote
- Verse of the Day
- Server status — remote status pages (green/amber banner)
- App services — apps running on *this* box (`ps aux` / `docker ps`), green/amber banner
- Weather — current + 5-day forecast
- Today's calendar events
- Todo list (from `checkmate`)
- Health metrics — weight, alcohol, exercise, joy, with sparklines / weekly bar charts and target-aware trend badges
- Overnight messages — summary of iMessages received overnight (via BlueBubbles)
- Overnight security — Unifi Protect smart-detection summary (hidden when quiet)
- Reading — book progress from Papyrus, flags stagnant books
- Top news stories (cross-source clustered)
- More news (collapsible)
- Geek News — HackerNews + Slashdot combined
- GitHub notifications (unread, with type + reason)
- Family calendar — full week, grouped by day
- Tomorrow preview (afternoon/evening runs)
- XKCD (when a new comic is out)
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

Add to crontab for automatic updates. `run.sh` is designed to run **hourly** — each run rebuilds `briefing.json` and then fires the notification agent:

```
0 * * * * /path/to/daily-briefing/run.sh
```

Content varies by time-of-day bucket, derived from the run's hour:

| Bucket | Hours | Notable content |
|---|---|---|
| `morning` | `< 10` | full briefing |
| `midday` | `10–13` | full briefing |
| `afternoon` | `14–18` | adds tomorrow's calendar preview |
| `evening` | `19+` | adds tomorrow's preview; omits today's schedule, More News, and XKCD |

## Push agent (Pushover notifications)

After each briefing build, `run_agent.py` evaluates configured rules against the fresh data and sends Pushover notifications for anything new and matched. Notification text is generated with the Claude API (falls back to the rule's static `summary` on error).

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
  "pushover_device": "",
  "pushover_sound": ""
}
```

### Rule types

| Type | Triggers when |
|------|--------------|
| `calendar` | A "mine" calendar event title matches `keywords` and starts within `window_minutes` |
| `family_calendar` | Any family calendar event falls on today |
| `server_status` | One or more monitored (remote) servers is down |
| `local_services` | An app server on this box (`ps aux` / `docker ps`) is down |
| `security` | Unifi Protect detected overnight smart events of the given `event_types` |
| `news_keyword` | A news story title contains one of the `keywords` |
| `reading` | No tracked book has progressed within `stale_days`; gated to a set `hour` |
| `todos` | Morning todo digest at the configured `hour` |
| `github` | Unread GitHub notifications match the `reasons` list |
| `weather` | Today's condition contains one of the `conditions` strings (plain substring — keep it narrow, e.g. `storm`/`thunderstorm`) |
| `health_missing` | A metric isn't logged yet today, after `not_before_hour` |

Each rule has `dedupe_hours` — the same match won't re-notify within that window (keyed on rule id + a per-item key). For `github`, dedup is also keyed on `updated_at`, so a notification only re-fires when there's new activity on the thread.

**Batched pushes:** within a single run, low-priority notifications (Pushover priority ≤ 0) are combined into **one digest push** (e.g. "Morning briefing (3)") instead of one push per rule. Emergencies (priority ≥ 1, e.g. `server_status`, `local_services`) are sent individually so they keep their own alert sound and retry/receipt behavior.

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
| `briefing://current` | resource | Full briefing.json — calendar, todos, news, weather, health, GitHub, … |
| `briefing://memory` | resource | Agent push history and rule stats |
| `briefing://dialectics` | resource | Index of saved dialectics |
| `refresh_briefing` | tool | Rebuild briefing.json on demand |
| `add_todo` | tool | Add a todo via `checkmate add` |
| `add_calendar_event` | tool | Create a CalDAV event on any writable calendar |
| `send_notification` | tool | Send a Pushover notification (priority -1/0/1) |
| `send_message` | tool | Send an iMessage/SMS via the local BlueBubbles server, optionally delayed |
| `log_weight` / `log_alcohol` / `log_exercise` / `log_joy` | tool | Append health logs; chat agent converts natural language to standard units |
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
  "caldav_write_url": "https://caldav.zoho.com/v2/your_account_id/events/your_calendar_uid/",
  "caldav_username": "you@zoho.com",
  "caldav_password": "your-app-password"
}
```

Set `"default": true` on the calendar Claude should use when none is specified. Then ask naturally:

> "Add a dentist appointment next Thursday at 2pm"  
> "Add a team lunch to my Work calendar on Friday from noon to 1pm at the pizza place"

Calendars can live in either the `mine` or `family` section — the tool searches both, so no need to move a calendar just to make it writable.

### Updating after code changes

After a `git pull` on the host machine, restart just the MCP server from within your Claude Code session (use `/mcp` to find the reconnect option) — no need to quit the session. The MCP server imports modules once and caches them, so after editing a fetcher, reconnect before its live tool reflects the change. (`refresh_briefing` always spawns a fresh process, so the *briefing* picks up code changes immediately.)

For remote access (phone, another machine), run `claude --tunnel` on the host — it gives you a URL that connects to your local Claude Code session with MCP context attached.

## Messaging (BlueBubbles)

Both the overnight-message summary and the `send_message` tool talk to a local [BlueBubbles](https://bluebubbles.app) server (its [REST API](https://docs.bluebubbles.app/server/developer-guides/rest-api-and-webhooks)). Configure it in `config.json`:

```json
"bluebubbles": {
  "url": "http://localhost:1234",
  "password": "your-bluebubbles-server-password",
  "method": "apple-script",
  "night_start_hour": 22,
  "night_end_hour": 6,
  "night_end_minute": 30
}
```

- **Overnight summary** — incoming messages in the night window, grouped by thread, with contact names resolved from the BlueBubbles contact list. Rendered as a collapsible "Messages" section.
- **Sending** — recipients match by name against recent chats, or are given as a phone number/email. `method` is `apple-script` (default, no extra setup) or `private-api` (needs the BlueBubbles Private API helper; required to start brand-new chats on macOS 11+).

> "Send a message to Nicole in 15 minutes saying I'm on my way"  
> "Text Ben at 555-1234 to say happy birthday"

**Delayed sends** (`delay_minutes`) are handled **out of process** by `scheduled_send.py`: the MCP server writes a job under `data/scheduled_messages/` and spawns a detached worker that sleeps until the due time and sends. This survives the MCP server / chat request being torn down — but because it's a live sleeping process, a delayed job does **not** survive a machine reboot mid-wait.

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

`allowed_tools` is a subset of the MCP server's full surface — set it to whatever you're comfortable exposing through a webpage. Adding a tool to `mcp_server.py` does **not** auto-expose it to the web chat; the name must also appear in this list. The chat box only renders when `enabled: true`. Leave `shared_secret` blank to skip auth (page reachability == chat reachability) or set a passphrase the browser stores in `localStorage`.

Per-device sessions are persisted under `data/chat_sessions/<id>.json`; on page load the last few turns are pre-rendered so the chat doesn't feel "empty."

**If you serve behind nginx**, raise its upstream timeout — `chat.php` sets PHP's own limit to 300s, but nginx defaults to 60s and will return `504 Gateway Time-out` on long tool loops (refreshing the briefing, summarizing a large dialectic, etc.):

```nginx
# in the server block, or scoped to location = /chat.php
fastcgi_read_timeout 300;
fastcgi_send_timeout 300;
```

(Use `proxy_read_timeout` / `proxy_send_timeout` if your nginx proxies via `proxy_pass` rather than `fastcgi_pass`.) The same applies to other reverse proxies.

## Health tracking

Add a `health` block to `config/config.json` to enable weight / alcohol / exercise / joy tracking with charts on the briefing page:

```json
"health": {
  "weight":   { "unit": "lbs", "goal_direction": "down", "target": 150 },
  "alcohol":  { "weekly_target_drinks": 7 },
  "exercise": { "weekly_target_minutes": 150 },
  "joy":      { "scale_max": 5 },
  "missed_notify_hour": 7,
  "chart_days": 30
}
```

Each metric appends to `data/health/*.jsonl` and renders latest value, weekly total vs target (or week average for joy), a trend badge, and a chart:

- **Weight** and **joy** show a 30-day daily sparkline (joy pinned to a fixed `1..scale_max` scale so bar heights read as absolute mood).
- **Alcohol** and **exercise** show a **weekly bar chart** (one Sun–Sat bar vs the weekly target line — green on-target, red off, gray for the in-progress week).

Log in plain English via the chat — "shared a bottle of wine with Nicole" or "ran 4 miles this morning" — and the agent converts to US standard drinks / minutes+intensity in-conversation before logging (no second server-side LLM hop). Add a `health_missing` entry to `agent_rules.json` to get a Pushover reminder when a metric hasn't been logged today.

## Dialectics

Dialectics are exploratory conversations saved to `data/conversations/<uuid>.json` via the MCP server. Tell Claude a conversation is a "dialectic" (or "save this as a dialectic") and it starts persisting the exchange, applies an exploratory conversational stance, and appends each subsequent turn automatically until you close it. Later, ask Claude to "resume" or "summarize" a past dialectic by UUID, id-prefix, or a fuzzy topic substring. See `CLAUDE.md` for the full protocol.

## News feeds (`config/feeds.json`)

Each entry is an RSS feed. Optional flags control how stories are elevated to Top Stories:

| Flag | Effect |
|------|--------|
| `"always_important": true` | Every story from this feed is elevated to Top Stories |
| `"verge_wired_pair": true` | Elevated if 2+ feeds sharing this flag cover the same story |
| `"geek_only": true` | Appears only in Geek News, not Top Stories or More News |

Cross-source matching is controlled in `config.json` under `news`:
- `similarity_threshold` — how closely two headlines must match (default `0.65`)
- `importance_threshold` — how many sources must cover a story to elevate it (default `2`)
- `title_filters` — case-insensitive substrings; matching titles are dropped before clustering (e.g. `"coupon"`, `"promo code"`)

## Requirements

- Python 3.9+
- PHP 7.4+
- Dependencies installed automatically by `run.sh` into `.venv/`

See `CLAUDE.md` for full architecture documentation.
