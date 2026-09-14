---
name: mail-app-ui-conventions
description: "Mail app UI/UX standards for sync operations — automatic job-based syncing, visible progress indicators, explicit interface."
---

# Mail App UI Conventions

## 🔴 HARD RULEs
- Sync must run automatically as separate jobs without manual triggers (user preference)
- UI must show progress during sync, never appear unavailable (importance: 6)
- Progress display must be visually appealing and explicit, not hidden or ambiguous (importance: 6)
- Interface must be explicit — no guessing required (importance: 6)

## 🔴 HARD RULEs
- email_suggestions cache: folder must pass through unchanged from email.folder (no defaulting)
- noreply senders matching /no[-_.]?reply|do[-_.]?not[-_.]?reply patterns must be handled correctly
- mail_smart_replies_enabled checkbox setting must be documented and applied
- Parse RFC 2822/MIME headers with `mailparser.simpleParser`, never handwritten address regexes.
- Smart replies use an 8192-token budget for reasoning models and never expose or fall back to `reasoning_content`; empty or failed responses return the established safe sentinel without crashing the sync loop.
