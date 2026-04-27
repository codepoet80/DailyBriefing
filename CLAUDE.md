# Daily Briefing

A self-hosted morning dashboard that aggregates calendars, news, todos, HackerNews, XKCD, and a podcast into a single read-only web page. Built to run on macOS or Raspberry Pi, with a PHP frontend compatible with a 2011 webOS TouchPad.

## Architecture

- **Python 3.9+** cron scripts fetch all data sources and write `data/briefing.json`
- **PHP 7.4+** renderer reads the JSON and serves HTML — no ES6, no CSS Grid, ES5 JS only
- No Node.js, no build step

### Cron schedule (`crontab -e`)
```
30 6  * * * /path/to/daily-briefing/run.sh
30 11 * * * /path/to/daily-briefing/run.sh
30 16 * * * /path/to/daily-briefing/run.sh
```
The afternoon run (16:30) also includes tomorrow's calendar preview.

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
  fetch_hackernews.py  # HN Firebase API, parallel fetch
  fetch_xkcd.py        # XKCD API with new-comic state tracking
  fetch_todos.py       # Runs `checkmate ls` and parses output
  fetch_podcast.py     # Fetches latest episode MP3 from podcast RSS feed
  fetch_weather.py     # Open-Meteo API (no key needed), lat/lon from config
  fetch_servers.py     # Fetches status pages, parses btn-success/btn-danger Bootstrap classes
web/
  index.php            # PHP renderer, PHP 7.4 compatible
  podcast.php          # Standalone audio player page (opened in new tab)
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
  "hackernews": { "top_count": 20 },
  "news": {
    "importance_threshold": 2, // min sources for a story to be elevated
    "similarity_threshold": 0.65,
    "max_important": 15,
    "max_regular": 30
  },
  "podcast": {
    "name": "NPR Up First",
    "feed_url": "https://feeds.npr.org/510318/podcast.xml"
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
  "name": "Slashdot",
  "url": "https://rss.slashdot.org/Slashdot/slashdotMain",
  "tier": "tech",
  "region": "global",
  "tech": true,
  "always_important": true,    // always elevated regardless of cross-source count
  "verge_wired_pair": true     // elevated if 2+ feeds with this flag share a story
}
```

Current feeds: BBC News, AP News (feedx.net), CBC News, Globe and Mail, The Guardian, Cleveland.com, NPR News, Slashdot (always_important), The Verge (verge_wired_pair), Wired (verge_wired_pair).

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
8. **Hacker News** — top N stories, collapsible (expanded by default)
9. **Family This Week** — 7-day family calendars, grouped by day with "today" badge, color-coded per person
10. **Tomorrow** — my calendars only, afternoon run only
11. **XKCD** — only shown when a new comic is detected
12. **NPR Up First** — dark banner with play button linking to `podcast.php` player

## Known Issues / Future Ideas

- Reuters RSS is dead (discontinued 2020) — already replaced with The Guardian
- ESV API key needed for ESV translation; blank key falls back to BibleGateway (NIV)
- story clustering module is intentionally swappable — could add LLM summarization
- InoReader API integration planned (currently using raw RSS feeds)
- No auth needed — LAN-only deployment
