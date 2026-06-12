# Daily Briefing

A self-hosted morning dashboard that aggregates calendars, news, todos, Geek News (HN + Slashdot), XKCD, and more into a single read-only web page. Built to run on macOS or Raspberry Pi, with a PHP frontend compatible with a 2011 webOS TouchPad.

## Architecture

- **Python 3.9+** cron scripts fetch all data sources and write `data/briefing.json`
- **PHP 7.4+** renderer reads the JSON and serves HTML — no ES6, no CSS Grid, ES5 JS only
- No Node.js, no build step

### Cron schedule (`crontab -e`)
```
30 6  * * * /path/to/daily-briefing/run.sh
30 11 * * * /path/to/daily-briefing/run.sh
30 16 * * * /path/to/daily-briefing/run.sh
30 19 * * * /path/to/daily-briefing/run.sh
```
The afternoon run (16:30) and evening run (19:30) both include tomorrow's calendar preview. The evening run omits today's schedule, More News, and XKCD.

### Dev server
```bash
php -S 0.0.0.0:8181 -t web/
```

## File Layout

```
config/
  config.json          # Live config with credentials (gitignored)
  config.json.example  # Safe template to commit
  feeds.json           # RSS feed list
  feeds.json.example   # Template
data/
  briefing.json        # Written by cron, read by PHP
  xkcd_state.json      # Persists last-seen XKCD comic number
  briefing.log         # Cron output log
  conversations/       # Saved dialectics (one JSON per id)
  chat_sessions/       # Per-device web-chat sessions (rolling 20-turn window)
  health/              # weight.jsonl / alcohol.jsonl / exercise.jsonl
src/
  build_briefing.py    # Orchestrator — run this directly to test
  fetch_verse.py       # BibleGateway VOTD RSS (falls back to ESV API if key provided)
  fetch_calendars.py   # CalDAV/ics fetcher — supports ownCloud WebDAV and direct URLs
  fetch_news.py        # RSS feed fetcher (uses requests for timeout safety)
  cluster_news.py      # Story deduplication/importance module (swappable)
  fetch_geek_news.py   # HN Firebase API + Slashdot RSS, interleaved
  fetch_xkcd.py        # XKCD API with new-comic state tracking
  fetch_todos.py       # Runs `checkmate ls` and parses output
  fetch_weather.py     # Open-Meteo API (no key needed), lat/lon from config
  fetch_servers.py     # Fetches status pages, parses btn-success/btn-danger Bootstrap classes
  fetch_greeting.py    # Time-of-day greeting + ZenQuotes daily quote
  fetch_unifi.py       # Unifi Protect overnight security event summary
  fetch_health.py      # Reads data/health/*.jsonl, returns latest+sparkline+trend per metric
  mcp_server.py        # MCP server — exposes briefing + ~17 tools (dialectic, todos, calendar,
                       # message, push, refresh, health logging, get_time, get_public_ip, ...)
  run_agent.py         # Proactive Pushover agent (rules-based, runs after every build)
  agent/
    chat_handler.py    # Web-chat agent loop. Stdin JSON -> Anthropic tool-use loop -> stdout JSON.
                       # System prompt is split: stable (cached) + volatile briefing data.
    mcp_bridge.py      # Spawns src/mcp_server.py over stdio MCP, adapts schemas for Anthropic API
    sessions.py        # Read/write data/chat_sessions/<id>.json; prune CLI for run.sh
web/
  index.php            # PHP renderer, PHP 7.4 compatible. Pre-renders trailing chat turns from cookie.
  style.css            # Old WebKit compatible (no Grid, no CSS vars)
  chat.php             # POST endpoint: shells out to src/agent/chat_handler.py, sets session cookie
  chat.js              # ES5 + XHR chat client. Manages local secret, spinner, status line.
  spinner.gif          # 24x24 8-frame animated GIF (ImageMagick-generated) for thinking state
  manifest.json        # PWA manifest for Android installability
  icon.png             # 512px source icon (generate resized icons with ImageMagick)
run.sh                 # Entry point: creates .venv, installs deps, runs build + agent + prune sessions
requirements.txt       # requests, icalendar, recurring_ical_events, feedparser, anthropic, mcp
```

## Config Reference (`config/config.json`)

```json
{
  "owncloud": {
    "base_url": "https://your-owncloud",
    "username": "...",
    "password": "...",
    "ssl_verify": false        // false for self-signed LAN certs
  },
  "calendars": {
    "mine": [
      { "name": "Work", "url": "/remote.php/dav/calendars/user/cal/?export" },
      { "name": "Jon",  "url": "https://calendar.zoho.com/ical/..." }
    ],
    "family": [
      { "name": "Nicole", "url": "https://...", "color": "#6600cc" },
      { "name": "Ben",    "url": "https://...", "color": "#993333" }
    ]
  },
  "servers": [
    { "name": "my-site.com", "url": "https://my-site.com/status/" }
  ],
  "weather": {
    "latitude": 41.58,
    "longitude": -81.20,
    "units": "fahrenheit"   // or "celsius"
  },
  "bible": {
    "translation": "ESV",
    "esv_api_key": ""          // get free key at esv.org/api; blank = BibleGateway NIV
  },
  "geek_news": { "count": 20 },
  "news": {
    "importance_threshold": 2, // min sources for a story to be elevated
    "similarity_threshold": 0.65,
    "max_important": 15,
    "max_regular": 30,
    "title_filters": ["coupon"]  // case-insensitive substrings; matching titles excluded before counting
  },
  "greeting": {
    "name": "Jon"              // first name for time-of-day greeting
  },
  "unifi": {
    "host": "https://192.168.x.x",
    "username": "...",
    "password": "...",
    "night_start_hour": 22,    // overnight window start (default 10pm)
    "night_end_hour": 6        // overnight window end (default 6am)
  },
  "todos": {
    "command": "checkmate ls", // any CLI that outputs "○ N. Title" lines
    "count": 8
  },
  "calendar_filters": {
    "exclude_titles": ["Morning Routine"]  // exact-match event titles to suppress
  },
  "health": {
    "weight":   { "unit": "lbs", "goal_direction": "down" },
    "alcohol":  { "weekly_target_drinks": 15 },
    "exercise": { "weekly_target_minutes": 150 },
    "missed_notify_hour": 7,    // health_missing rule won't fire before this hour
    "chart_days": 30            // sparkline length
  },
  "chat_agent": {
    "enabled": true,
    "model": "claude-sonnet-4-6",
    "shared_secret": "",        // blank = no auth (page reachable = chat reachable)
    "max_turns_in_context": 20,
    "session_ttl_hours": 24,
    "max_tool_iterations": 8,
    "allowed_tools": ["dialectic_save", "refresh_briefing", ...],  // subset of mcp_server.py tools
    "system_prompt_extra": ""
  }
}
```

## Feed Config (`config/feeds.json`)

Each feed entry:
```json
{
  "name": "Example",
  "url": "https://example.com/rss",
  "tier": "tech",
  "region": "global",
  "tech": true,
  "always_important": true,    // always elevated regardless of cross-source count
  "verge_wired_pair": true,    // elevated if 2+ feeds with this flag share a story
  "geek_only": true            // excluded from news sections; appears only in Geek News
}
```

Current feeds: BBC News, AP News (feedx.net), CBC News, Globe and Mail, The Guardian, Cleveland.com, NPR News, The Verge (verge_wired_pair), Wired (verge_wired_pair), Slashdot (geek_only).

## Calendar Notes

- **mine** calendars: today only (+ tomorrow on afternoon run)
- **family** calendars: full 7-day week, grouped by day in the UI
- Calendar URLs starting with `/` are fetched via ownCloud WebDAV with Basic auth
- Calendar URLs starting with `http(s)://` are fetched directly (no auth) — works for Zoho, Google, etc.
- `ssl_verify: false` suppresses urllib3 warnings for LAN self-signed certs

## Story Clustering (`cluster_news.py`)

Swappable module. Current implementation uses `difflib.SequenceMatcher` on normalized titles (stop words removed). Rules:
- 2+ different sources with ≥65% title similarity → elevated to "Top Stories"
- `always_important: true` feeds → always elevated
- 2+ `verge_wired_pair` feeds share a story → elevated

To replace with a smarter implementation (TF-IDF, embeddings, LLM), keep the same function signature:
```python
def cluster_stories(stories, threshold, importance_threshold) -> (important, regular)
```

## Server Status (`fetch_servers.py`)

Fetches status pages built with [bash-http-monitoring](https://github.com/RaymiiOrg/bash-http-monitoring). Parses `btn-success` / `btn-danger` Bootstrap classes to determine up/down state per service. Displayed as a slim banner (green if all up, amber if any down). Unreachable status pages are treated as a site-level failure.

## Weather (`fetch_weather.py`)

Uses [Open-Meteo](https://open-meteo.com/) — no API key required. Returns current conditions plus a 5-day forecast. WMO weather code table maps numeric codes to human-readable strings. Displayed collapsed by default showing temp + condition summary.

## XKCD State (`fetch_xkcd.py`)

`data/xkcd_state.json` persists the last-seen comic number. The state file is only updated when the comic is **not** new, so a new comic stays visible across all three daily runs until the next one publishes.

## UI Sections (top to bottom)

1. **Verse of the Day** — distinct dark blue banner, serif, centered
2. **Server Status** — slim green/amber banner; only shown when data present
3. **Weather** — collapsible (collapsed), summary shows temp + condition
4. **Today** — my calendar, time-sorted, today only
5. **Check Mate** — top N todos from `checkmate ls`
6. **Health** — weight / alcohol / exercise. Per metric: latest value, weekly total vs target, trend badge (good/bad/flat), 30-day sparkline. "Log…" pill highlights anything not logged today.
7. **Top Stories** — cross-source clustered news, collapsible (expanded by default)
8. **More News** — regular feed items, collapsible (collapsed by default)
9. **Geek News** — HN + Slashdot interleaved, collapsible (collapsed by default)
10. **Family This Week** — 7-day family calendars, grouped by day with "today" badge, color-coded per person
11. **Tomorrow** — my calendars only, afternoon run only
12. **XKCD** — only shown when a new comic is detected
13. **Chat** — only when `chat_agent.enabled`. Last 4 turns pre-rendered server-side from the `db_chat_sid` cookie; new turns appended client-side.

## Geek News (`fetch_geek_news.py`)

Combines HackerNews (Firebase API, parallel fetch) and Slashdot (RSS, `geek_only` flag in feeds.json) into a single section. Stories are interleaved by rank (HN #1, Slashdot #1, HN #2, …) up to `geek_news.count`. HN items show score and comment count; Slashdot items show a source tag only.

## Greeting (`fetch_greeting.py`)

Time-of-day salutation (Good morning/afternoon/evening) using the name from `greeting.name` in config. Daily inspirational quote from [ZenQuotes](https://zenquotes.io/) `/api/today` endpoint — same quote across all three runs.

## Unifi Security (`fetch_unifi.py`)

Fetches events from Unifi Protect's local REST API for a configurable overnight window (default 10pm–6am). Authenticates with username/password; requires `X-CSRF-Token` header on subsequent requests. Summarises smart detections (Person, Vehicle, etc.) and motion counts per camera. Section hidden if no overnight events.

## Web Chat (`web/chat.php` + `src/agent/`)

A chat box at the bottom of `index.php` lets legacy devices (e.g. the 2011 webOS TouchPad) talk to the same MCP tool surface the desktop session uses. **Tool logic is not duplicated** — the chat handler spawns `src/mcp_server.py` as a stdio MCP subprocess and forwards calls.

Flow per request:
```
Browser → POST /chat.php (json: session_id, user_message, shared_secret)
chat.php → proc_open .venv/bin/python3 src/agent/chat_handler.py (stdin: same json)
chat_handler.py → spawns src/mcp_server.py (stdio MCP) → Anthropic tool-use loop → stdout json
chat.php → sets db_chat_sid cookie, returns json to browser
chat.js → renders reply + tool events; spinner toggles via setBusy()
```

Key files:
- `src/agent/chat_handler.py` — Anthropic loop. System prompt is split into two blocks:
  - **Stable** (cached, ~4KB): assistant guidance, tool-use rules, briefing JSON schema reference, dialectic protocol, health-logging cheat sheets, reply style. Above the 1024-token cache minimum so it survives across briefing.json refreshes.
  - **Volatile** (uncached): `active_dialectic_id` + full `briefing.json`. Re-tokenized each turn but doesn't bust the stable cache.
- `src/agent/mcp_bridge.py` — `mcp_session()` async context manager, `to_anthropic_tools()` schema adapter, `call_mcp_tool()` invoker.
- `src/agent/sessions.py` — per-cookie JSON files under `data/chat_sessions/`. Rolling 20-turn window. `python3 src/agent/sessions.py prune 24` clears stale sessions (called from `run.sh`).
- `web/chat.php` — validates shared secret (timing-safe `hash_equals`), spawns the handler, 300s `set_time_limit`. Cookie is `HttpOnly`, `SameSite=Lax`.
- `web/chat.js` — ES5/XHR only, no fetch, no arrow functions. Handles the spinner, secret prompt + `localStorage` cache, and the trailing scroll-to-bottom on initial render.

Session continuity: every reply rotates the cookie's session forward; on page reload, `index.php` reads the cookie, loads the session JSON, and renders the last 4 turns into `#chat-log` so the chat doesn't feel "empty" each load. Independent of dialectic persistence.

Tool allowlist: `config.chat_agent.allowed_tools` is the source of truth for what the web chat can call. Adding a tool to `mcp_server.py` does NOT automatically expose it to the web chat — the name must also be added to this list. Desktop sessions get the full surface regardless.

## Health Tracking

Three metrics, three append-only JSONL files under `data/health/`:

| File | Schema |
|---|---|
| `weight.jsonl` | `{ts, date, pounds, note}` |
| `alcohol.jsonl` | `{ts, date, drinks, raw_input, items:[{kind,count}]}` |
| `exercise.jsonl` | `{ts, date, minutes, intensity, kind, raw_input}` |

### Logging via the chat agent

The chat agent converts natural language into structured values **in-conversation** and passes both the parsed numbers AND the user's original wording (as `raw_input`) to the log tools — no second LLM hop server-side. Built-in cheat sheet is in `chat_handler.py`'s stable system prompt:

- **Alcohol** = US standard drinks (14g pure ethanol). 5oz wine = 12oz 5% beer = 1.5oz spirit = 1. Wine bottle = 5; shared bottle = 2.5 each. Double pour / old fashioned / martini ≈ 2.
- **Exercise** = minutes + intensity (`light`/`moderate`/`vigorous`) + free-text kind. Rough fallback estimates: "ran 3 miles" ≈ 30 min vigorous, "yoga class" ≈ 60 min moderate.
- **Weight** = pounds. Agent multiplies if user gives kg.

### Aggregation (`fetch_health.py`)

Called from `build_briefing.py`. Produces per-metric: `latest`, `today_logged`, 30-day `sparkline` (list of numbers or `null` for "no log"), and `trend` (`good`/`bad`/`flat`).

Trend logic:
- **Weight** — slope-based. Compares last 3 logs to prior 3. Threshold: 0.5% of prior avg or 0.3 lb (whichever bigger). Requires ≥4 data points.
- **Alcohol** — target-based. `good` when week ≤ 60% of `weekly_target_drinks`, `bad` when over target, else `flat`.
- **Exercise** — target-based. `good` when week ≥ `weekly_target_minutes`, `bad` when below 60%, else `flat`.

The target-based design for alcohol/exercise is intentional: slope alone misleads when there's no prior-week data (looks like "going up from zero").

### Missed-log nagging

`run_agent.py` adds rule type `health_missing` — fires Pushover "remember to log your X" for any metric where `today_logged` is false, gated by `not_before_hour` in the rule. Standard dedupe keys on `health_missing:<metric>:<YYYY-MM-DD>` so it nags once per day per metric.

### Fresh-data query

`get_health_summary` MCP tool reads the JSONL files directly (skipping `briefing.json`), so when the user asks "how am I doing on drinking?" right after logging, they get up-to-the-minute numbers instead of the cron snapshot.

### UI

`render_sparkline()` in `index.php` emits a row of `<div class="bar">`s with percentage heights. Old-WebKit safe — no SVG, no canvas. Weight uses tight min-max scaling (small changes visible); alcohol/exercise use 0-baseline (so zero days look like zero).

## MCP Tools (full inventory)

Defined in `src/mcp_server.py`. The desktop session has all of them; the web chat sees only those listed in `config.chat_agent.allowed_tools`.

| Tool | Purpose |
|---|---|
| `refresh_briefing` | Rebuild `data/briefing.json` by shelling out to `build_briefing.py` |
| `add_todo` | Append via `checkmate add` |
| `add_calendar_event` | Create a CalDAV event on any `writable: true` calendar |
| `send_notification` | Push via Pushover (priority -1/0/1) |
| `send_message` | iMessage/SMS via the message-bridge sidecar, optional `delay_minutes` |
| `dialectic_save` / `_append` / `_list` / `_get` / `_close` / `_resume` | See Dialectics section |
| `log_weight` / `log_alcohol` / `log_exercise` | Append to `data/health/*.jsonl` |
| `get_health_summary` | Live read of `data/health/*.jsonl`, returns compact stats |
| `get_time` | Local time + ISO + UTC |
| `get_public_ip` | Hits `api.ipify.org` (5s timeout) |

## Dialectics

Dialectics are exploratory conversations between Jon and Claude, saved to `data/conversations/<uuid>.json` via the MCP server.

### Starting a dialectic

When Jon says a conversation is a "dialectic", labels it as one, or uses words like "mark this" or "save this as a dialectic":
1. Call `dialectic_save` with the topic (Jon's label or one you derive) and the full exchange so far as `turns`
2. The tool response will include a **dialectic stance** — read it and apply it as your conversational tone for the rest of the session. If no stance is returned, default to: be curious, explore multiple angles, gently challenge when Jon takes a strong position, favor questions over declarations.
3. Keep the returned ID in mind for the rest of the session — this session is now an active dialectic

### Every subsequent exchange

Once a dialectic is active in the session, **after every response you give**, call `dialectic_append` with the two new turns (the user's question and your answer) before finishing. Do not wait to be asked. This applies for the remainder of the session unless Jon closes the dialectic.

### Closing a dialectic

Call `dialectic_close` with the active dialectic ID when either:
- Jon explicitly signs off — "thanks for the chat", "good talk", "I'm done with this topic", "let's stop here", or any clear wind-down
- Jon's next message is clearly about a different briefing domain — calendars, todos, messages, news, weather, servers, or any other operational topic unrelated to the ideas being explored

Stop appending after closing. Do not close on ambiguous pauses or short clarifying questions that are still within the dialectic topic.

### Resuming a saved dialectic

When Jon asks to "resume", "continue", or "reopen" a past dialectic: call `dialectic_resume` with the ID. This re-opens the record (clears `closed_at`, sets `status=open`) and returns the full prior conversation. Treat the session as an active dialectic from that point — appending every exchange automatically as above.

To read a dialectic without re-opening it (e.g. Jon just wants to review it), call `dialectic_get` instead.

**When to call `dialectic_list` / `dialectic_get`:** When Jon asks to see or review a past dialectic without continuing it.

The `briefing://dialectics` MCP resource gives a quick index of all saved dialectics.

## Known Issues / Future Ideas

- ESV API key needed for ESV translation; blank key falls back to BibleGateway (NIV)
- Story clustering module is intentionally swappable — could add LLM summarization
- InoReader API integration planned (currently using raw RSS feeds)
- Unifi Protect API is unofficial — may break on firmware updates
