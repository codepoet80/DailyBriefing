# Daily Briefing

A self-hosted morning dashboard. A Python cron script fetches data from a dozen sources and writes `data/briefing.json`; a PHP page renders it as a clean, read-only daily briefing.

Runs on macOS or Raspberry Pi. Frontend is compatible with a 2011 webOS TouchPad (WebKit 534, ES5 only, no CSS Grid).

## What it shows

- Verse of the Day
- Server status (green/amber banner)
- Weather — current + 5-day forecast
- Today's calendar events
- Todo list (from `checkmate`)
- Top news stories (cross-source clustered)
- More news (collapsible)
- Hacker News top stories
- Family calendar — full week, grouped by day
- Tomorrow preview (afternoon run only)
- XKCD (when a new comic is out)
- NPR Up First podcast player

## Setup

```bash
cp config/config.json.example config/config.json
# edit config/config.json with your credentials and settings

cp config/feeds.json.example config/feeds.json
# edit feeds.json if you want different news sources

./run.sh                        # first run — creates .venv and builds briefing.json
php -S 0.0.0.0:8181 -t web/    # dev server
```

Add to crontab for automatic updates:
```
30 6  * * * /path/to/daily-briefing/run.sh
30 11 * * * /path/to/daily-briefing/run.sh
30 16 * * * /path/to/daily-briefing/run.sh
```

## Requirements

- Python 3.9+
- PHP 7.4+
- Dependencies installed automatically by `run.sh` into `.venv/`

See `CLAUDE.md` for full architecture documentation.
