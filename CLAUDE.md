# Daily Briefing

## Never delete anything under `data/`

**`data/` is live user data. Do not delete, truncate, or overwrite any file in
it — ever, for any reason, including cleaning up after your own tests.** It holds
chat sessions, health logs, dialectics, scheduled messages, and the briefing
itself. None of it is in git, none of it is backed up, and there is no undo.

This is written down because it has already gone wrong twice in one session.
Both times the reasoning was "these are just my test artifacts":

1. `rm -f data/chat_sessions/*.json` — a glob that cannot tell a test fixture
   from a live session.
2. `rm -f data/chat_sessions/index01-ring.json` — by exact name, which felt
   safer and wasn't. That file had stopped being a test artifact the moment ring
   turns began rendering on the briefing page; it was the live ring
   conversation.

The lesson from the second one is the important one: **a file you created during
testing does not stay yours.** Ownership isn't decided by who wrote it first.

Leaving test data in place is harmless — sessions expire on their own via
`chat_agent.session_ttl_hours`, and a stray row in a log bothers nobody. There is
no cleanup obligation to weigh against the risk.

### Testing without touching real data

`DB_DATA_DIR` relocates the entire data directory. Set it and the whole app —
briefing build, MCP server, chat handler, web chat, webhook — reads and writes
there instead:

```bash
export DB_DATA_DIR=/tmp/db-test-data
mkdir -p "$DB_DATA_DIR"
cp data/briefing.json "$DB_DATA_DIR/"      # if the test needs briefing content
DB_DATA_DIR="$DB_DATA_DIR" php -S 127.0.0.1:8199 -t web/
```

Then throw the directory away — there is no cleanup step in the real `data/` to
get wrong. Resolvers are `src/paths.py` (`data_dir()` / `data_path()`) and
`web/paths.php` (`db_data_dir()` / `db_data_path()`); **both** must honour it,
and `db_run_agent()` passes it down to the Python handler it spawns, because a
half-applied override is worse than none — it looks isolated when it isn't.

Verify isolation by fingerprinting `data/` before and after:
`find data -type f | sort | xargs shasum | shasum`.

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

## Todos (`fetch_todos.py`)

Reads whatever `todos.command` prints, keeping lines matching `○/● N. Title`
(the format of [checkmate-cli](https://github.com/codepoet80/checkmate-cli),
which is itself a client for a remote checkmate-service and needs its own
`~/.checkmate.conf`). `todos.add_command` is the write side, used by the
`add_todo` MCP tool.

Both go through `resolve_command()`, so either key may be given as
`${HOME}/path/checkmate.py ls`, `~/path/checkmate.py ls`, an absolute path, or a
bare name found on `PATH`. **Expand-then-`which` is the point:** the config
string used to be handed to `str.split()` verbatim, so the `${HOME}` form shipped
in `config.json.example` looked for a directory literally named `${HOME}` and
silently produced an empty todo list on every hourly run. Splitting is `shlex`,
not `str.split`, so a path containing spaces survives.

A missing or failing command is *not* silent on the write side: `add_todo` raises
(so MCP marks the result `isError` and the chat/webhook show ✗). It used to
return `Error: ...` as ordinary text, which surfaced as a **successful** tool call
and let the agent claim it had added a todo that was never written. The read side
still degrades quietly to `[]` — a broken todo binary shouldn't take down the
whole briefing build — but logs which path it tried.

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
13. **Chat** — only when `chat_agent.enabled`. Last `chat_agent.history_turns` (6) turns pre-rendered server-side, merging the `db_chat_sid` cookie session with the Index.01 ring's session (marked "via ring"); new turns appended client-side.

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

0. **Nickname** — an exact match in `contacts.nicknames` (config.json) short-
   circuits everything: `{"nick": "Nicole Wise", "my wife": "Nicole Wise"}`.
   Values may be a contact name, a phone number, or an email. This is the only
   way to make a word mean someone the address book spells differently, and it
   outranks the name search on purpose — otherwise "nick" reaches whichever
   real contact is named Nick. If the mapped name matches **no** contact the
   resolver reports that and sends nothing; it deliberately does *not* fall
   back to searching for the alias itself, because that is exactly how an alias
   would reach a stranger who shares the nickname.
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

## Index.01 Webhook (`web/webhook.php`)

Voice access to the same agent from a [Index.01 ring](https://help.repebble.com/en/articles/15724406-index-advanced-features-mcp-webhook).
The ring records, transcribes on-device, and POSTs to a configured URL; this
endpoint feeds that transcription to `chat_handler.py` — the identical agent,
prompt, and MCP tool surface the chat box uses — and pushes the reply back.

```
Ring → HTTPS POST /webhook.php (multipart/form-data, Authorization header)
webhook.php → db_run_agent() → chat_handler.py → mcp_server.py → reply
webhook.php → Pushover push to Jon's phone  +  JSON body with the same text
```

Setup steps, the ring's multipart field table, and the `webhook` config
block live in the `index01-webhook` skill — load it when configuring the
endpoint. What stays here is the part you need without asking: the security
gotchas, the capture-on-doubt rule, and the dedupe rationale.

### Publishing it

The briefing runs on the home box's own nginx and is not meant to face the
internet. The webhook alone is published by reverse-proxying **one exact path**
from a public server to the briefing host **over Tailscale** — both are already
on the tailnet, so there is no port-forward and no inbound hole in the home
firewall.

The live nginx for this lives in `config/nginx/`, which is **gitignored**: it
carries real hostnames, Tailscale addresses, and the topology of which box
fronts which. Keep it that way — don't paste those values into this file, the
README, or commit messages.

Two things that bite here:

**`location ~ \.php$` outranks `location /`.** The `$is_internal` guard lives in
`location /`, but nginx matches regex locations first, so it never applied to
any PHP file — `/chat.php` answered anything that could reach the briefing port,
and `chat_agent.shared_secret` is `""`. The guard has to be repeated inside the
regex block. Check with `curl -so /dev/null -w '%{http_code}\n'
http://<briefing-host>:<port>/chat.php` from a tailnet address: `301` good,
`405` still open. (Tailscale's `100.64.0.0/10` is *not* in the `geo $is_internal`
block, which lists only RFC1918 + loopback, so tailnet peers correctly read as
external.)

**Use `location =`, never a prefix,** for the proxied path: under a prefix match
`/<path>/../chat.php` reaches the unauthenticated chat agent. Allow-list the
proxy's tailnet address on the home side as defence in depth.

**60-second timeouts on both hops.** `webhook.php` and `chat.php` both set
`set_time_limit(300)`, but nginx defaults `fastcgi_read_timeout` and
`proxy_read_timeout` to 60s. A long tool loop 504s at the proxy while the agent
keeps running and still fires its Pushover reply — confusing to debug. Set 300s
at both the public proxy and the home fastcgi block.

Test without the ring:
```bash
curl -X POST https://your-host/webhook.php \
  -H 'Authorization: Bearer <token>' \
  -F 'transcription=what is on my calendar today' \
  -F "recordedAt=$(date +%s)000" -F 'client=ring'
```
A JSON body (`{"transcription": "..."}`) is accepted too, for testing only.

### Reply delivery

The ring has no screen and the vendor docs **do not specify** whether the HTTP
response is surfaced anywhere, so the reply is delivered two ways: pushed to the
phone via Pushover (reusing `config.agent.pushover_*`) **and** returned in the
response body as both `reply` and `text`. Turn the push off with
`reply_via_pushover: false` if the device ever starts reading responses.

Because of that same unknown, the endpoint sets `ignore_user_abort(true)`: if the
ring gives up waiting, the turn still finishes and the push still lands. Typical
round trip is 3–6s.

### Capture-on-doubt

The ring's context tells the agent that when a transcription is **too garbled or
ambiguous to act on confidently**, it must not guess and must not just ask a
question back: it calls `add_todo` with its best literal reading and appends
` [via ring]` to the title, then says so in one line. Jon is talking to a
screen-less device and may not read the push for hours, so a capture he can
correct later beats a wrong action or a question left hanging.

The rule is deliberately fenced on both sides — noise the agent can confidently
read through is *not* doubt, and neither is a question answerable from the
briefing data. Without that fence it turns every loosely-phrased request into a
todo instead of doing the thing. Verified: "tell marsh about the thing on choose
day before it gets too" → todo *"Tell Marsh about the thing on Tuesday before it
gets too [via ring]"* (recovers `choose day`, preserves the unresolvable tail),
while "what is the temperature" still just answers.

`add_todo` must stay in `chat_agent.allowed_tools` for this to work — the webhook
shares that allowlist.

### Never write synthetic notes into assistant message content

`chat_handler.py` replays history as plain text (real `tool_use`/`tool_result`
blocks can't be replayed — the rolling window may trim a `tool_use` away from
its `tool_result`, which the API rejects). It therefore has to tell the model
what previous turns actually *did*.

That note must go in the **system block** (`_completed_actions()`), never
appended to the assistant's own text. An earlier version appended
`[Already completed in this turn: add_todo]` to the stored reply. Inside an
assistant turn it is indistinguishable from words the model wrote, so the model
learned the pattern and started **emitting the marker instead of calling the
tool** — replying "added to your todo list" with no `add_todo` call behind it.
Ring todos silently stopped appearing while every Pushover reply said they had.

Reproduced at **2 failures in 3 runs** against a real ring session; 4 of 4
correct after moving the note to the system block. It is self-reinforcing:
a faked reply is saved with the marker in its content, which teaches the next
turn the same trick.

Two guards now: `_turns_to_messages()` strips the marker from stored content on
read (so poisoned sessions recover without editing saved history), and the
stable prompt says never to claim an action without a successful tool call in
the current turn.

The general rule: **anything the model can mistake for its own prior output is
a format it will imitate.** Annotations about the conversation belong in the
system prompt.

### A fabricated reply keeps causing harm after the fake is fixed

Stopping new fakes is not enough: the false claims already sitting in a session
are read back as fact. After the marker fix, "put test webhook on my todo list"
got *"that's already on your list"* — the model believed its own earlier
"Done — added to your todo list", which had never run a tool.

Two mitigations, both needed:

- `_turns_to_messages()` detects the signature of a fabricated turn (it carried
  the marker **and** recorded no tools) and replaces that content with an
  explicit note that nothing was written. The saved session file is untouched.
- The stable prompt states that the assistant's own earlier replies are **not**
  evidence about external state, and that it must never decline a write, or say
  something "is already on your list", on the strength of conversation history.
  A duplicate entry is a nuisance; a silently missing one is a broken promise.

Residual false claims with no marker (e.g. the "already on your list" reply
itself) are only covered by the prompt rule — verified 3/3 correct against the
live poisoned session.

### The push reports effects, not intentions

`webhook.php` builds the Pushover body from **`tool_events`**, not from the
agent's prose:

```
✓ Added todo: Test webhook          <- the tool's own result
                                       (✗ … FAILED, and priority raised to 1,
                                        when a write fails)
Done — "Test webhook" added…        <- the agent's narration, secondary
```

A turn that ran no tools (a question) still pushes just the reply — nothing was
claimed to change, so there is nothing to verify. The consequence that matters:
an action-shaped request whose push has **no ✓ line did not happen**.

This exists because narration is not evidence. The agent spent two days
replying "added to your todo list" on turns where no tool ran, and the push
repeated it faithfully every time. Tool results come from the effect, so they
cannot report a write that did not occur.

Same principle as the scheduled-send sweeper, which alerts on what happened at
send time rather than confirming at schedule time: **confirm on effect, never on
intent.** Apply it to any new notification path.

### Reading the webhook log

`OUT tools=[...]` lists tools that ran; a failed one is suffixed `(failed)`
(since the endpoint's first commit, so its absence in an old line is
meaningful). An **empty** `tools=[]` on a turn whose reply claims a write is the
signature of the faking bug above, not of a tool error.

### The ring never sends anything by accident

Reaching this endpoint takes a press-and-hold, speech, and a release. There is
no background capture and no accidental trigger, so **every transcription is
deliberate** and the agent is told so explicitly. It must never decline an
action because the message looks stray, unintended, blunt, or out of character —
that is not its call. It once refused to send a text with *"That looks like a
stray message… I'll let it go"*, which is a failure twice over: it asked a
question (banned on a screen-less device) and then dropped the request entirely.

Every turn must end in exactly one of: the action performed, a question answered
from briefing data, or `add_todo` capture. Doing nothing is not an option.

The context also says to read each message against the previous one — a bare
fragment right after a texting exchange is the message he wants sent, not a
stray remark.

### The agent never reads CLAUDE.md — rules live in the prompt

This file is documentation for whoever is editing the code. **No runtime code
loads it.** The ring agent's actual rules come from three places:

| Where | What |
|---|---|
| `webhook.php` `$DEFAULT_CLIENT_CONTEXT` | ring-specific rules (the two rules, capture-on-doubt, reply shape) |
| `chat_handler.py` `_build_stable_system_text()` | shared assistant rules, tool guidance, briefing schema |
| `config.webhook.system_prompt_extra` / `chat_agent.system_prompt_extra` | per-install additions, no code edit needed |

Writing a rule here and nowhere else changes nothing about how the agent behaves.

### The two ring rules are enforced, not requested

The context has banned clarifying questions since the endpoint was written, and
the agent asked them anyway — repeatedly, on a device with no way to answer.
Prompt text is a probability, so the rule that matters most is also enforced in
code:

**`webhook.php`: if the reply is a question and no tool call SUCCEEDED, the
transcription is filed as a todo (`wh_force_capture()` → `src/capture_todo.py`)
and the question is discarded**, replaced with "I wasn't sure, so I put it on
your todo list." No model in the loop, nothing to be talked out of. The
substitution is logged as `ENFORCE ...`.

Keyed on a *successful* tool call, not merely on one being attempted. An
ambiguous recipient used to come back `ok=True` with a pick-list — a menu
nobody could answer — so `send_message` now **raises** on
`AmbiguousRecipient`. Nothing was sent, so it is a failed send, and the ring
path treats it as doubt and captures.

Question detection is a trailing `?` after stripping quotes and brackets:
answers to Jon's questions do not end that way, and clarifying questions always
do.

### Known mis-transcriptions (`webhook.transcription_fixes`)

The ring's speech-to-text mishears the same command openings repeatedly —
"text Nicole" arrives as "technically" often enough to be worth a lookup table
instead of hoping the agent infers it:

```json
"transcription_fixes": { "technically": "text Nicole" }
```

**Anchored to the start of the message**, case-insensitive, on a word boundary.
These are command openings; an unanchored rewrite would corrupt ordinary speech
("that's technically true" must not become "that's text Nicole true"). Verified
that mid-sentence uses and "Technicalities" are left alone.

A false match is still possible ("Technically the server is down"), so the
substitution is **logged** (`fix=[...] read_as=...`, alongside the original
text) and **appended to the push** as `(heard "…")`. A rewrite that guessed
wrong has to be visible — the push is the only place he sees anything.

### Voice-shaped replies

`chat_handler.py` takes an optional `client_context` in its stdin payload,
prepended to the **volatile** system block (not the cached stable one, so it
can't bust the prompt cache for the chat box). `webhook.php` uses it to tell the
agent the input is a transcription — read for intent, expect mangled proper
nouns — and that the answer lands as a push notification, so: two or three short
sentences, no markdown, no lists. Extend it via `webhook.system_prompt_extra`.

### Ring turns in the page's chat log

`index.php` renders the trailing turns of **both** the browser's own cookie
session and the ring's fixed session, merged by each turn's `at` timestamp, so
anything said to the Index.01 shows up in the Chat section on the next page load.
Ring turns carry a `chat-turn-ring` class and a small "via ring" marker.
`chat_session_turns()` loads and tags one session file; the merge and slice
happen at the render site. Count is `chat_agent.history_turns` (default 6, up
from the old hard-coded 4 — two sources need more room).

`usort` is not stable before PHP 8 and a ring turn can share a wall-clock second
with a web turn, so turns are decorated with their position and that breaks ties.
Ring turns are skipped entirely when `webhook.enabled` is false.

This is a **display** merge only: the two sessions stay separate as far as the
agent is concerned, so a ring conversation and a browser conversation don't
share context or compete for the same rolling turn window. Pointing both at one
session id would give cross-device continuity ("add milk" on the ring, then
"make that oat milk" in the browser) at the cost of every browser sharing one
conversation.

### Session continuity and replay

The ring has no cookie, so it pins one **fixed** `session_id`. Consecutive taps
therefore continue one conversation ("what time is it" → "and in UTC?"), and
`run.sh`'s session prune clears it on the normal `chat_agent.session_ttl_hours`
schedule.

This required a fix in `chat_handler.py`: it used to mint a **new random id**
whenever `sessions.load()` came back `None`, so a caller-supplied fixed id could
never bootstrap — the first request silently landed in a random session and every
"follow-up" started over. A well-formed supplied id is now kept even with no file
behind it yet. (Same benefit for a browser whose session file was pruned: it
keeps its cookie instead of being reassigned.)

Retry behaviour is also undocumented, and a retried turn would re-run the agent's
*tools* — sending a message or logging a workout twice. `data/webhook_state.json`
remembers the last handled request and **two** things disqualify a repeat within
`dedupe_seconds`; either one replays the cached reply, returns `duplicate: true`,
and never reaches the agent (so no second Pushover either):

| matched on | catches |
|---|---|
| `recordedAt` | the same recording re-delivered — a retry of one press |
| normalised transcription text | the same words said twice in a row — a double press, or the ring re-sending under a fresh `recordedAt` |

`wh_text_key()` lowercases, strips punctuation, and collapses whitespace before
hashing, because speech-to-text is not byte-stable across takes — "What time is
it -- just the time!" must match "what time is it, just the time".

Text matching is against the **immediately previous** request only, not a
history. Asking the same thing again later in the window still runs: repeating
yourself an hour apart is a real question, repeating within one press is not.

A `flock` on `data/.webhook.lock` serializes turns, so a retry that arrives
mid-flight waits and then hits that cache rather than racing.

Every request logs a request/response line to `data/webhook.log`.

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
