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
web/
  index.php            # PHP renderer, PHP 7.4 compatible
  style.css            # Old WebKit compatible (no Grid, no CSS vars)
  manifest.json        # PWA manifest for Android installability
  icon.png             # 512px source icon (generate resized icons with ImageMagick)
run.sh                 # Entry point: creates .venv, installs deps, runs build
requirements.txt       # requests, icalendar, recurring_ical_events, feedparser
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
    "max_regular": 30
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
6. **Top Stories** — cross-source clustered news, collapsible (expanded by default)
7. **More News** — regular feed items, collapsible (collapsed by default)
8. **Geek News** — HN + Slashdot interleaved, collapsible (collapsed by default)
9. **Family This Week** — 7-day family calendars, grouped by day with "today" badge, color-coded per person
10. **Tomorrow** — my calendars only, afternoon run only
11. **XKCD** — only shown when a new comic is detected

## Geek News (`fetch_geek_news.py`)

Combines HackerNews (Firebase API, parallel fetch) and Slashdot (RSS, `geek_only` flag in feeds.json) into a single section. Stories are interleaved by rank (HN #1, Slashdot #1, HN #2, …) up to `geek_news.count`. HN items show score and comment count; Slashdot items show a source tag only.

## Greeting (`fetch_greeting.py`)

Time-of-day salutation (Good morning/afternoon/evening) using the name from `greeting.name` in config. Daily inspirational quote from [ZenQuotes](https://zenquotes.io/) `/api/today` endpoint — same quote across all three runs.

## Unifi Security (`fetch_unifi.py`)

Fetches events from Unifi Protect's local REST API for a configurable overnight window (default 10pm–6am). Authenticates with username/password; requires `X-CSRF-Token` header on subsequent requests. Summarises smart detections (Person, Vehicle, etc.) and motion counts per camera. Section hidden if no overnight events.

## Known Issues / Future Ideas

- ESV API key needed for ESV translation; blank key falls back to BibleGateway (NIV)
- Story clustering module is intentionally swappable — could add LLM summarization
- InoReader API integration planned (currently using raw RSS feeds)
- Unifi Protect API is unofficial — may break on firmware updates
