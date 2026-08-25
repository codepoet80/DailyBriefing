---
name: index01-webhook
description: Setup reference for the Index.01 ring voice webhook — the ring's multipart fields, endpoint configuration steps, and the config.json webhook block. Load when configuring, testing, or debugging web/webhook.php.
---

# Index.01 webhook setup reference

Behavioural rules, security gotchas, and design rationale stay in the root
`CLAUDE.md` under "Index.01 Webhook" — this file is the setup reference only.

### What the ring sends

`POST` `multipart/form-data`, plus any custom headers configured in the app:

| Field | Notes |
|---|---|
| `transcription` | plain text; present when *text transmission* is enabled |
| `audio` | `audio/mp4` (M4A); present when *audio transmission* is enabled |
| `recordedAt` | ms since epoch; always sent |
| `client` | always `ring` |

Set the app's **Send** option to transcription (or both). **Audio-only is
rejected with a 400** — there is no speech-to-text on this end, and silently
accepting it would look like the ring was being ignored.

### Setup

1. `config.webhook.token` — a long random string. The endpoint **refuses to run
   with an empty token** (unlike the chat box, whose reachability is the page's
   own; this URL is meant to face the internet).
2. In the Index app: URL `https://your-host/webhook.php`, custom header
   `Authorization: Bearer <that token>`, Send = transcription, pick a trigger.
   `Bearer <t>`, `Token <t>`, a bare token, and `X-Webhook-Token` are all accepted.
3. The ring requires **HTTPS**, so the endpoint needs a real certificate — a LAN
   self-signed cert will not do. The briefing itself stays on the LAN; only the
   webhook is published, via reverse proxy (below).

### Config (`config.json` → `webhook`)

```json
{
  "enabled": true,
  "token": "long-random-string",   // required; no token = 500, never wide open
  "session_id": "index01-ring",    // fixed id → follow-ups work across taps
  "reply_via_pushover": true,
  "pushover_title": "Index",
  "pushover_priority": 0,
  "max_reply_chars": 900,          // Pushover truncates past ~1024
  "dedupe_seconds": 600,
  "save_audio": false,             // write M4As to data/webhook_audio/ for debugging
  "system_prompt_extra": ""        // appended to the ring's client context
}
```

