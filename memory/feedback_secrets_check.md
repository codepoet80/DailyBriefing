---
name: Check example/template files for secrets before commit
description: Always scan example and template config files for real credentials, not just live config files
type: feedback
---

When asked to verify no secrets are present before a git commit, check ALL files being staged — including `*.example`, `*.sample`, `*.template`, and any other non-live config variants. Example files can contain real credentials if they were copy-pasted from a live config.

**Why:** In this project, I checked `config/config.json` but missed `config/config.json.example`, which had the user's real ownCloud password in it. It was pushed to GitHub and cost the user an hour of credential rotation across all devices.

**How to apply:** Before confirming any commit is secret-free, grep staged files for patterns like passwords, tokens, API keys, and URLs with credentials — across every file in the diff, regardless of filename.
