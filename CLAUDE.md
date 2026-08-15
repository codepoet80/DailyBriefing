# Daily Briefing

A self-hosted morning dashboard that aggregates calendars, news, todos, Geek News (HN + Slashdot), XKCD, and more into a single read-only web page. Built to run on macOS or Raspberry Pi, with a PHP frontend compatible with a 2011 webOS TouchPad.

## Architecture

- **Python 3.9+** cron scripts fetch all data sources and write `data/briefing.json`
- **PHP 7.4+** renderer reads the JSON and serves HTML — no ES6, no CSS Grid, ES5 JS only
- No Node.js, no build step

### Cron schedule (`crontab -e`)
```
0 * * * * /path/to/daily-briefing/run.sh
```
`run.sh` runs **hourly**; each run rebuilds `briefing.json` and then fires the notification agent. Content varies by time-of-day bucket, derived from the run's hour in `determine_run_type()`:

| Bucket | Hours | Notable content |
|---|---|---|
| `morning` | `< 10` | full briefing |
| `midday` | `10–13` | full briefing |
| `afternoon` | `14–18` | adds tomorrow's calendar preview |
| `evening` | `19+` | adds tomorrow's preview; omits today's schedule, More News, and XKCD |

(Sunday from 10:00 on also includes tomorrow's preview.) Time-gated agent rules — e.g. `todos` and `reading` (`hour: 9`) — fire on the run whose hour matches.

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
  fetch_local_services.py # Checks this box's own app servers via `ps aux` / `docker ps`
  fetch_greeting.py    # Time-of-day greeting + ZenQuotes daily quote
  fetch_unifi.py       # Unifi Protect overnight security event summary
  fetch_imessage.py    # Overnight iMessage summary via the BlueBubbles server API
  bluebubbles.py       # Shared BlueBubbles REST client (auth, chat/message/contact queries, send)
  contacts_mac.py      # Name -> number lookup from this Mac's Contacts (labels, couple convention)
  scheduled_send.py    # launchd-driven sweeper for delayed send_message (retry + delivery confirmation)
  fetch_health.py      # Reads data/health/*.jsonl, returns latest+sparkline+trend per metric
  fetch_reading.py     # Papyrus eReader book progress (webOS Account sync, or legacy local dir)
  webos_account.py     # Read-only client for the webOS Archive app-storage service
                       # (auth + scrambled-record decode; port of the community JS SDK)
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
  "local_services": [   // app servers on THIS box; type "process" (ps aux) or "docker" (docker ps)
    { "name": "BlueBubbles", "type": "process", "match": "bluebubbles" },
    { "name": "Docker",      "type": "process", "match": "docker.app" },
    { "name": "Plex",        "type": "process", "match": "plex media server" }
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
  "bluebubbles": {
    "url": "http://localhost:1234",
    "password": "...",         // BlueBubbles server password (Settings > API & Webhooks)
    "method": "apple-script",  // send method: "apple-script" (default) or "private-api"
    "night_start_hour": 22,    // overnight message summary window
    "night_end_hour": 6,
    "night_end_minute": 30
  },
  "todos": {
    "command": "checkmate ls", // any CLI that outputs "○ N. Title" lines
    "count": 8
  },
  "calendar_filters": {
    "exclude_titles": ["Morning Routine"]  // exact-match event titles to suppress
  },
  "reading": {
    "mode": "account",         // "account" (webOS Account sync) or "webdav" (legacy local dir)
    "account": {
      "login": "you@example.com",   // webOS Account email
      "password": "",               // webOS Account password
      "app_id": "com.palm.codepoet.papyrus",
      "device_name": "DailyBriefing"  // label in the account's device list
    },
    "papyrus_dir": "~/ownCloud/Dropbox/.papyrus",  // mode "webdav" only
    "stagnant_days": 7,        // days without progress before a book reads as stagnant
    "max_inactive_days": 30,   // books untouched longer than this are dropped
    "exclude_titles": []
  },
  "health": {
    "weight":   { "unit": "lbs", "goal_direction": "down" },
    "alcohol":  { "weekly_target_drinks": 15 },
    "exercise": { "weekly_target_minutes": 150 },
    "joy":      { "scale_max": 5 },   // subjective 1..scale_max mood rating
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

## Local Services (`fetch_local_services.py`)

Checks that application servers running **on this box** are alive (as opposed to
`fetch_servers.py`, which polls remote HTTP status pages). Configured via a
`local_services` list; each entry is one of two check types:

- `process` (default) — the `match` string appears in `ps aux` output
- `docker` — the `match` string appears in running `docker ps` output

`ps aux` and `docker ps` are each shelled out **at most once per build** and
reused across all services. Matching is a case-insensitive substring; `match`
defaults to `name` if omitted. A service whose match is absent is reported down.
The checker's own PID line is stripped from `ps aux` so a `match` that happens to
appear in the build process's argv can't self-match. Returns
`{all_up, services:[{name, up, type}]}`, or None when nothing is configured.
Rendered as a slim green/amber banner right below the remote Server Status banner
(reuses the `.section-servers` styles). The `local_services` agent rule pushes a
priority-1 alert when any service is down.

## Weather (`fetch_weather.py`)

Uses [Open-Meteo](https://open-meteo.com/) — no API key required. Returns current conditions plus a 5-day forecast. WMO weather code table maps numeric codes to human-readable strings. Displayed collapsed by default showing temp + condition summary.

## Reading Progress (`fetch_reading.py` + `webos_account.py`)

Book progress comes from the [Papyrus eReader](https://github.com/codepoet80/webos-papyrus-ereader)
running on webOS. `reading.mode` picks the source:

- **`account`** (default) — the webOS Account cloud storage run by the community's
  webOS Archive service. This is what Papyrus's `syncMode: "account"` writes to.
- **`webdav`** (legacy) — per-book JSON files in a locally synced `.papyrus`
  directory. This was the original path; it only works while some other process
  (ownCloud/Dropbox client) is still syncing that folder down.

Both yield the same output — `{books: [...], stagnant: [...]}`, one entry per book
with `title`, `author`, `percent`, `days_since`, `last_read_label`, `stagnant` —
consumed by `web/index.php` and the `reading` agent rule.

### The account protocol

`webos_account.py` is a **read-only Python port** of the read path of the
community JS SDK (`webos-common/AppStorage/webos-app-storage.js`, vendored in
Papyrus as `app/app/common/webos-app-storage.js`). Service base is
`https://appcatalog.webosarchive.org/WebService`:

| Call | Purpose |
|---|---|
| `POST device.php?m=authenticateWeb` | `{login, password, device_id, device_name}` → `{token, account}`; token is good for 365 days |
| `GET storage.php?m=getAll&app_id=…` | → `{items: [{key, value, revision, updated_at}], usage}` |

Every request carries `Authorization: PalmAuth token=<token>` and
`X-Palm-Device-Id`.

**Record values are scrambled client-side** with XXTEA, keyed on
`app_id + ":" + record_key`, base64'd behind a `v1:` prefix. The master key is
public by design (it ships in the JS) — it is obfuscation on a shared server, not
encryption. `webos_account.scramble()` / `unscramble()` reproduce it exactly; the
port is verified byte-for-byte against the original JS.

**Book keys are opaque.** The SDK only scrambles values, so Papyrus scrambles the
key itself (`SyncManager._scrambledBookKey`, salt `papyrus_book_key_v1`,
URL-safe base64) to keep titles and ISBNs off a shared server. That means you
**cannot look a book up by name** — `fetch_reading` calls `getAll`, keeps records
whose key starts with `book:`, and reads title/author out of the decoded *value*.
The app's `settings` record is skipped, as is any blob that fails to unscramble.

### Auth lifecycle

On webOS the device adopts its own account token over the Luna bus. Off-device
there is no Luna bus, so this client signs in with the account email/password from
config and caches `{token, device_id, account}` in `data/webos_session.json`
(mode `0600`; `data/*` is gitignored). The **`device_id` is generated once and
reused** — a fresh one per run would litter the account's device list with a new
revocable entry every hour.

A cached token can be revoked server-side (signing the device out of its webOS
Account kills it — see Papyrus fix #30), which surfaces as a 401. `fetch_reading`
catches that, re-signs-in once, and retries. Any other failure — bad credentials,
service unreachable, no credentials configured — logs a line and returns `None`,
so the briefing build continues and the Reading section simply drops out.

## XKCD State (`fetch_xkcd.py`)

`data/xkcd_state.json` persists the last-seen comic number. The state file is only updated when the comic is **not** new, so a new comic stays visible across the day's runs until the next one publishes.

## UI Sections (top to bottom)

1. **Verse of the Day** — distinct dark blue banner, serif, centered
2. **Server Status** — slim green/amber banner; only shown when data present
2b. **App Services** — slim green/amber banner for this box's local services; only shown when configured
3. **Weather** — collapsible (collapsed), summary shows temp + condition
4. **Today** — my calendar, time-sorted, today only
5. **Check Mate** — top N todos from `checkmate ls`
6. **Health** — weight / alcohol / exercise / joy. Per metric: latest value, weekly total vs target (or week average for joy), trend badge (good/bad/flat), and a chart. **Weight and joy** show a 30-day daily sparkline (joy pinned to a fixed 1..scale_max scale so bar heights read as absolute mood). **Alcohol and exercise** show a **weekly bar chart** instead (`render_week_bars()`): one bar per Sun–Sat week vs the weekly target line — green = on-target, red = off-target, gray = current in-progress week. "Log…" pill highlights anything not logged today.
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

Time-of-day salutation (Good morning/afternoon/evening) using the name from `greeting.name` in config. Daily inspirational quote from [ZenQuotes](https://zenquotes.io/) `/api/today` endpoint — same quote across all of the day's runs.

## Unifi Security (`fetch_unifi.py`)

Fetches events from Unifi Protect's local REST API for a configurable overnight window (default 10pm–6am). Authenticates with username/password; requires `X-CSRF-Token` header on subsequent requests. Summarises smart detections (Person, Vehicle, etc.) and motion counts per camera. Section hidden if no overnight events.

## Messaging (`bluebubbles.py` + `fetch_imessage.py`)

Both the overnight-message summary and the `send_message` MCP tool talk to a local
[BlueBubbles](https://bluebubbles.app) server ([REST API docs](https://docs.bluebubbles.app/server/developer-guides/rest-api-and-webhooks)).
Auth is the server password passed as a `password` query param; every response is a
`{status, message, data}` envelope that `bluebubbles._request()` unwraps.

- **`fetch_imessage.py`** — POSTs `/api/v1/message/query` with `after` = the overnight
  window start (epoch **ms**) and `with: [chat, chat.participants, handle]`, drops
  `isFromMe` messages, and groups the rest by chat. `count` is total incoming messages;
  `messages` is one row per thread (newest message as preview). Contact names come from
  `GET /api/v1/contact`, matched on normalized addresses (digits-only phones, US country
  code stripped). Output shape `{window_label, count, messages:[{name, service, time, preview}]}`
  is unchanged from the old bridge, so `index.php` renders it as-is.
- **`send_message`** — see Recipient Resolution below. Existing chats send via
  `POST /api/v1/message/text` (`chatGuid` + `tempGuid`); unknown addresses fall back
  to `POST /api/v1/chat/new`. Send method comes from
  `bluebubbles.method` — **`private-api`** (current setting; needs the BlueBubbles
  Private API helper, which also makes `chat/new` work on macOS 11+) or
  `apple-script` (no extra setup, but prone to hanging — see Delayed Sends).
  Confirm the helper is live with `GET /api/v1/server/info` →
  `private_api: true, helper_connected: true`. `delay_minutes` scheduling is
  covered in Delayed Sends below.

## Delayed Sends (`scheduled_send.py` + launchd)

`send_message` with `delay_minutes` **only writes a job file** —
`data/scheduled_messages/<uuid>.json`. Delivery belongs to a launchd agent that
sweeps that directory **every 10 minutes**:

```
config/launchd/net.jonathanwise.dailybriefing.scheduler.plist   # StartInterval 600
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/net.jonathanwise.dailybriefing.scheduler.plist
launchctl kickstart -p gui/$(id -u)/net.jonathanwise.dailybriefing.scheduler   # sweep now
```

So a message is sent within 10 minutes of its due time, not to the second.
`StartInterval` (not `StartCalendarInterval`) so a sweep missed while the Mac
slept runs on wake instead of being skipped.

### Why it works this way

The original design spawned a detached process that slept until the due time and
sent **once**. Timing was never the problem — on 2026-08-10 two jobs fired within
a second of schedule. Delivery was: both timed out at the old 30s limit, and
because nothing retried, watched, or reported, one message was never delivered at
all and the other surfaced three days later when the stuck AppleScript call
finally completed. The sweep model exists to close each of those gaps.

### The rules that keep retrying safe

- **A timeout is an unknown, not a failure.** BlueBubbles can time out
  client-side while the send is still moving inside Messages.
- **Accepted ≠ delivered.** HTTP 200 only means the request was accepted; an
  undeliverable send returns 200 and then lands with `error=4` and no
  `dateDelivered`. `confirm_send()` polls the history briefly after every send;
  only `error == 0` counts. A row with a non-zero error is a *failure*, so
  `already_delivered` must never treat it as proof.
- **Match on recipient, not chat guid.** iMessage re-routes a send to its
  canonical thread — aim at `RCS;-;+1206…` and it can land in
  `iMessage;-;+1206…`. Address comes from parsing the chat guid
  (`SERVICE;-;ADDRESS`), because `message/query` returns `participants` **empty**
  even when `with: [chat.participants]` is requested. Requiring guid equality
  made real deliveries look unconfirmed and produced a duplicate resend in
  testing.
- **Match across every handle that reaches the person**
  (`equivalent_addresses()`, built from Contacts). iMessage delivers to an
  *Apple ID*, not to the handle you addressed: a message sent to someone's work
  number lands in the iMessage thread for their mobile. Comparing only the
  target handle marked a delivered message unconfirmed and the next sweep sent
  it again — this shipped and put two copies in a thread before it was caught.
  Matching stays tight across *different* people; only handles Contacts groups
  under one person are treated as equivalent.
- **An accepted send is not retried on the next sweep.** Once the server
  accepts a send, the job records `accepted_at`; for `RESEND_GRACE` (30 min)
  afterwards a still-unconfirmed job waits rather than re-sending, unless an
  errored copy is actually visible. Accepted-but-unseen is far more often
  in-flight than lost, and re-sending is what duplicates.

### You cannot pick which handle an iMessage contact receives on

If a number belongs to a contact who has iMessage, Apple routes the message to
their Apple ID regardless of the thread you send to. Sending to a work number
and having it arrive on the mobile is Apple's behaviour, not a bug in this code.
Addressing the SMS thread does **not** override this: a send addressed to the
SMS thread for a work number was still delivered to the iMessage thread for that
person's mobile. The chat
guid selects a thread, not a transport — Messages picks iMessage whenever the
recipient's Apple ID is reachable. Short of disabling iMessage for that account,
a specific non-Apple-ID handle is not addressable from here.

### Job lifecycle

| Outcome | What happens |
|---|---|
| not yet due | left alone |
| already in history, `error == 0` | closed out, moved to `expired/` — never re-sent |
| sent and confirmed | job deleted |
| accepted, unconfirmed | left pending; next sweep re-checks delivery *before* retrying |
| send failed | attempt counted, retried next sweep, up to `MAX_ATTEMPTS` (5) → `failed/` + priority-1 Pushover |
| due more than `MAX_LATE` (2h) ago | `expired/` + priority-1 Pushover, **not** sent — no reminder arrives days late |

Terminal outcomes move the file to `failed/` or `expired/` rather than deleting,
so nothing vanishes silently. A `flock` on `.sweep.lock` keeps overlapping sweeps
from double-sending.

## Recipient Resolution (`contacts_mac.py` + `bluebubbles.resolve_recipient`)

Turning "text Dana Rivera" into a send target. `resolve_recipient` returns
`(kind, target, display_name)` — `kind` is `chat` (target is a chat guid) or `new`
(target is a raw address) — or raises `AmbiguousRecipient`, which carries a
pick-list the MCP layer prints instead of sending.

**Contacts is the source of truth for names**, not chat history. Names used to be
substring-matched against recent chats, which is how a personal name once resolved
to a nine-person group that merely contained that person. `contacts_mac.py` reads the Contacts
SQLite stores directly (read-only, `?immutable=1`):

```
~/Library/Application Support/AddressBook/AddressBook-v22.abcddb
~/Library/Application Support/AddressBook/Sources/<uuid>/AddressBook-v22.abcddb
```

One store per account, so the same person appears more than once with different
labels on the same number; records merge by normalized name, numbers dedupe by
digits, and the better label wins. This beats BlueBubbles' `/api/v1/contact`,
which exposes one source (232 of 335 contacts here) and returns **no labels**.

### Resolution order

1. Phone/email input → existing 1:1 chat with that address, else `new`.
2. **Strong** contact match (exact full, first, or last name) → that person.
3. Group chat by its own `displayName` — exact always; partial only when
   Contacts had no opinion. The synthesized "Alice, Bob, Carol" participant
   label is **never** matched, which is what keeps a personal name off a group.
4. **Weak-but-specific** contact match (every query word present, e.g.
   "Sam Okafor" inside "Robin & Sam Okafor") → that person.
5. BlueBubbles contacts, exact name only — the degraded path when Contacts is
   unreadable (no Full Disk Access).
6. Otherwise `ValueError`.

Anything genuinely ambiguous raises rather than guesses: several contacts at the
same match strength, a lone substring hit, or a contact whose best number isn't a
handset. **Nothing is sent on an ambiguous match.**

### Number preference and the couple convention

Label rank: `iphone` → `mobile` → `pager` → `main` → `home` → `work` → `other`.
A contact with one number uses it whatever the label.

In this address book a couple filed as one contact ("Alex and Dana Rivera")
keeps **the man's number under Mobile and the woman's under Pager**. Position is
not the signal — "Robin & Sam Okafor" and "Jo & Chris Vance" both list the woman
first — so the rule needs the first name's gender, read from
`contacts.couple_gender` in **config.json** (kept there, not in source, because
it is a list of real people and config.json is gitignored). Names absent from
that table produce a pick-list rather than a guess; add to it freely. The convention only applies when the
contact carries **both** a mobile and a pager.

So "text Dana" → Dana's pager number, `Dana Rivera`; "text Alex Rivera" → the
mobile; "text Alex And Dana Rivera" → asks which.

### Gotchas

- `query_chats` defaults to `CHAT_QUERY_LIMIT = 1000`. It was 100, and a 1:1
  thread quiet for months sorted past it — resolution then fell through to
  `chat/new`, which needs the Private API and fails silently under
  `method: apple-script`.
- Reading Contacts needs Full Disk Access for whatever process runs the MCP
  server. `contacts_mac.available()` reports this; resolution degrades to step 5
  rather than raising.
- `python3 src/contacts_mac.py "Some Name"` prints what a name resolves to.

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

Four metrics, four append-only JSONL files under `data/health/`:

| File | Schema |
|---|---|
| `weight.jsonl` | `{ts, date, pounds, note}` |
| `alcohol.jsonl` | `{ts, date, drinks, raw_input, items:[{kind,count}]}` |
| `exercise.jsonl` | `{ts, date, minutes, intensity, kind, raw_input}` |
| `joy.jsonl` | `{ts, date, rating, note}` — subjective mood, 1-5 (5 = most joyful); half-steps allowed, snapped to nearest 0.5 |

### Logging via the chat agent

The chat agent converts natural language into structured values **in-conversation** and passes both the parsed numbers AND the user's original wording (as `raw_input`) to the log tools — no second LLM hop server-side. Built-in cheat sheet is in `chat_handler.py`'s stable system prompt:

- **Alcohol** = US standard drinks (14g pure ethanol). 5oz wine = 12oz 5% beer = 1.5oz spirit = 1. Wine bottle = 5; shared bottle = 2.5 each. Double pour / old fashioned / martini ≈ 2.
- **Exercise** = minutes + intensity (`light`/`moderate`/`vigorous`) + free-text kind. Rough fallback estimates: "ran 3 miles" ≈ 30 min vigorous, "yoga class" ≈ 60 min moderate.
- **Weight** = pounds. Agent multiplies if user gives kg.
- **Joy** = 1-5 (5 = most joyful); half-steps like 3.5 allowed (snapped to nearest 0.5). Agent maps free-text mood to the scale ("great day" ≈ 5, "meh" ≈ 3, "awful" ≈ 1); original wording goes in `note`. One rating per day (latest wins, like weight).

### Aggregation (`fetch_health.py`)

Called from `build_briefing.py`. Produces per-metric: `latest`, `today_logged`, weekly total (`week_drinks` / `week_minutes`) or average (`week_avg` for joy), 30-day `sparkline` (list of numbers or `null` for "no log"), and `trend` (`good`/`bad`/`flat`). Alcohol and exercise additionally carry `weekly` — a list of the last `chart_weeks` (default 6) Sun–Sat weeks as `{start, total, partial}` (current week flagged `partial`), computed by `_weekly_totals()` on the same week boundary as `_week_dates()`. This feeds the weekly bar chart in the UI.

**Weekly totals use a Sunday–Saturday calendar week** (`_week_dates()` in `fetch_health.py`), not a rolling 7-day window — a workout on Saturday counts toward that week; Sunday starts a fresh one. The 30-day sparkline still uses a rolling window (`_day_range`).

Trend logic:
- **Weight** — slope-based. Compares last 3 logs to prior 3. Threshold: 0.5% of prior avg or 0.3 lb (whichever bigger). Requires ≥4 data points.
- **Alcohol** — target-based. `good` when week ≤ 60% of `weekly_target_drinks`, `bad` when over target, else `flat`.
- **Exercise** — target-based. `good` when week ≥ `weekly_target_minutes`, `bad` when below 60%, else `flat`.
- **Joy** — slope-based with up-is-good (reuses the weight slope logic, `goal_direction='up'`). Rising mood → `good`. Requires ≥4 data points.

The target-based design for alcohol/exercise is intentional: slope alone misleads when there's no prior-week data (looks like "going up from zero").

### Missed-log nagging

`run_agent.py` adds rule type `health_missing` — fires Pushover "remember to log your X" for any metric where `today_logged` is false, gated by `not_before_hour` in the rule. Standard dedupe keys on `health_missing:<metric>:<YYYY-MM-DD>` so it nags once per day per metric.

### Fresh-data query

`get_health_summary` MCP tool reads the JSONL files directly (skipping `briefing.json`), so when the user asks "how am I doing on drinking?" right after logging, they get up-to-the-minute numbers instead of the cron snapshot.

**Reload caveat:** the MCP server is a long-running process that imports `fetch_health` (and other modules) once and caches them. After editing `fetch_health.py` or any server module, **reload the MCP server** (`/mcp` reconnect) before `get_health_summary` reflects the change. `refresh_briefing` / `build_briefing.py` always spawn a fresh process, so the *briefing* picks up code changes immediately while the live tool lags until reload.

### UI

`render_sparkline()` in `index.php` emits a row of `<div class="bar">`s with percentage heights (weight and joy only). Old-WebKit safe — no SVG, no canvas. Weight uses tight min-max scaling (small changes visible); joy uses a fixed 1..scale_max scale (via `$fixed_min`/`$fixed_max`) so a "5" is full height and a "2" is low.

`render_week_bars()` renders the alcohol/exercise weekly charts. Both the bars and the dashed target line are **absolutely positioned from the same 2px floor over a 28px range**, so a bar of value `v` tops out at exactly `2 + (v/maxv)*28` — the same coordinate the target line uses. (Do not revert the bars to in-flow inline-block: mixing in-flow bars with an absolute target line puts them in different vertical frames and the "above/below target" read drifts by a couple pixels.) Weekly `maxv` gets 1.2× headroom above the taller of the max bar / target.

## MCP Tools (full inventory)

Defined in `src/mcp_server.py`. The desktop session has all of them; the web chat sees only those listed in `config.chat_agent.allowed_tools`.

| Tool | Purpose |
|---|---|
| `refresh_briefing` | Rebuild `data/briefing.json` by shelling out to `build_briefing.py` |
| `add_todo` | Append via `checkmate add` |
| `add_calendar_event` | Create a CalDAV event on any `writable: true` calendar |
| `send_notification` | Push via Pushover (priority -1/0/1) |
| `send_message` | iMessage/SMS via the local BlueBubbles server, optional `delay_minutes` |
| `dialectic_save` / `_append` / `_list` / `_get` / `_summary` / `_close` / `_resume` | See Dialectics section. `_summary` returns compact recap (first + last N turns) — use for "what was that about"-style asks. |
| `log_weight` / `log_alcohol` / `log_exercise` / `log_joy` | Append to `data/health/*.jsonl` |
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

**When to call `dialectic_list` / `dialectic_summary` / `dialectic_get`:**
- `dialectic_list` — browse what's there.
- `dialectic_summary` — Jon wants a recap ("what was that about", "remind me of X", "how did Y end"). Returns first + last few turns; preferred for any summarize-style request.
- `dialectic_get` — Jon wants the raw conversation body.

**Referring to a dialectic by name:** `_get`, `_summary`, `_append`, `_close`, and `_resume` all accept a UUID, a short id prefix, OR a topic substring. Token-based fuzzy match means refs like "bottom-up top-down" find a topic like "Polanyi: bottom-up vs top-down" even though the words aren't contiguous. If the ref matches multiple topics, the tool returns a pick-list (not flagged as an error) and the agent disambiguates. Only truly-missing refs raise an error and surface in the chat log with ✗.

The `briefing://dialectics` MCP resource gives a quick index of all saved dialectics.

## Notification Agent (`run_agent.py` + `config/agent_rules.json`)

Runs after every build (via `run.sh`, so hourly). Evaluates `config/agent_rules.json` against the freshly written `briefing.json`, generates concise notification text with the Claude API (`agent.model`, default Haiku; falls back to the rule's `summary` on API error), and sends via Pushover. State (dedupe + priority-1 receipts) lives in `data/agent_state.json` via `agent_memory.py`.

Each rule shares: `id`, `type`, `enabled`, `pushover_priority` (-1/0/1), `dedupe_hours` (suppress re-fire within window; keyed on rule id + a per-item key). Rule types and their type-specific fields:

| `type` | Fires when | Key fields |
|---|---|---|
| `calendar` | a "mine" event title matches a keyword within the window | `keywords`, `window_minutes` |
| `family_calendar` | family events today | — |
| `server_status` | any monitored server is down | — |
| `local_services` | an app server on this box (`ps aux`/`docker ps`) is down | — |
| `security` | overnight Unifi smart-detection of given types | `event_types` |
| `news_keyword` | a news headline matches | `keywords` |
| `reading` | no book progressed within `stale_days` (default 3); gated to `hour` | `hour`, `stale_days` |
| `todos` | morning todo digest at a set hour | `hour`, `max_count` |
| `github` | GitHub notifications of given reasons | `reasons` |
| `weather` | today's `condition` *substring*-matches any listed term | `conditions` |
| `health_missing` | a metric isn't logged today (after `not_before_hour`) | `metrics`, `not_before_hour` |

Gotcha: `weather.conditions` is a plain substring match on the day's condition string, so `"rain"` matches "Light rain" and fires on nearly any wet day. Keep the list narrow (e.g. `storm`/`severe`/`thunderstorm`) for true alerts only.

### Batched pushes

Within a single agent run, low-priority notifications (Pushover priority ≤ 0) are **combined into one digest push** (`digest_title()` gives a time-of-day label like "Morning briefing (3)", body is one `• title: message` line per item) instead of one push per rule. Because each cron run is its own process, the 6am run yields one morning digest and the 9am run another. Emergencies (priority ≥ 1, e.g. `server_status`) are sent individually so they keep their own alert sound, retry/expire, and receipt — they are never folded into the digest.

The `reading` rule is gated to `hour: 9`, so its reminder lands in the 9am digest. It only fires when *no* tracked book has progressed within `stale_days` (any single book read more recently silences it), and its stable `item_key` (`reading:no_progress`) plus `dedupe_hours: 72` paces re-nags to once every 3 days.

## Known Issues / Future Ideas

- ESV API key needed for ESV translation; blank key falls back to BibleGateway (NIV)
- Story clustering module is intentionally swappable — could add LLM summarization
- InoReader API integration planned (currently using raw RSS feeds)
- Unifi Protect API is unofficial — may break on firmware updates
