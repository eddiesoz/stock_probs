---
title: "Local configuration"
description: "Supported Stock Probability environment variables for local storage, providers, backup scheduling, timeouts, listener settings, and fixtures."
---

# Local configuration

The application reads a small environment-only configuration. Keep machine-local values out
of tracked files and shell history when they could expose private locations.

| Variable | Default | Constraint and effect |
| --- | --- | --- |
| `STOCK_PROBS_DATA_DIR` | `data` | Runtime root. The server places `stock_probs.sqlite3`, `backups/`, and `.backup-auth.key` beneath it and hardens sensitive paths. |
| `STOCK_PROBS_PROVIDER` | `yahoo` | Either `yahoo` for live provider requests or `fixture` for packaged deterministic data. |
| `STOCK_PROBS_PROVIDER_TIMEOUT` | `8` | Finite provider timeout from 1 through 20 seconds. News applies an absolute end-to-end deadline of `min(this value, 10 seconds)`. |
| `STOCK_PROBS_BACKUP_INTERVAL_SECONDS` | `86400` | Due-backup interval checked at `serve` startup; finite seconds from 60 through 2678400. |
| `STOCK_PROBS_HOST` | `127.0.0.1` | Environment values are restricted to `127.0.0.1`, `localhost`, or `::1`. |
| `STOCK_PROBS_PORT` | `8000` | Integer from 1 through 65535. |
| `STOCK_PROBS_FIXTURE_NOW` | unset | Timezone-aware ISO-8601 clock used with fixture-driven runs. |

For a reproducible local dashboard:

```bash
STOCK_PROBS_DATA_DIR=/tmp/stock-probs-doc-example \
STOCK_PROBS_PROVIDER=fixture \
STOCK_PROBS_FIXTURE_NOW=2025-01-10T17:03:00+00:00 \
  .dev-venv/bin/python -m stock_probs.cli serve
```

The CLI's `--host` and `--port` override listener values for that invocation. A non-loopback
CLI host is unsupported and requires the explicit `--allow-non-loopback` acknowledgement;
prefer the loopback default. Provider credentials are not part of this application's tracked
configuration.

News safety and cache bounds are fixed rather than additional settings: request limits are 1
through 10 (default 5), one retrieval may run at a time, and the raw provider body is capped at
256 KiB. The in-memory cache keeps at most 32 symbols, 32 KiB per entry, and 1 MiB total. A
non-empty entry is fresh for five minutes and stale-eligible for at most 30 minutes; an empty
entry lasts 60 seconds, and a failed provider attempt is suppressed for 30 seconds. The absolute
deadline covers receipt and parsing, uses the configured timeout when it is below 10 seconds,
and is never extended by an automatic provider retry. The browser also stops waiting after a
fixed 10 seconds; a user may explicitly retry a failed request. Neither bound is separately
configurable.

Every CLI command may initialize persistence and apply pending migrations: `migrate`, `serve`,
`backup`, `restore`, `backup-key rotate`, and `backup-key retire`. The repaired protection creates
and verifies a pre-migration backup before any of those paths upgrades an existing older schema;
fresh and current databases need none.

After migration, `serve` authenticates every managed artifact before newest selection for its due
check. A corrupt or wrong-key artifact blocks the check and startup. The newest artifact is then
verified with `require_active_schema=false`, so a recent pre-migration artifact can suppress a
current-schema due backup. Creation is rejected at 32 existing artifacts or when the candidate
would make total managed storage exceed 256 MiB; exactly 256 MiB is allowed. These limits do not
expire active query history. See [backup and restore](../operations/backup-restore.md) for the
trust-key lifecycle, restore behavior, and exact managed-name constraint.

Continue with [getting started](../operations/getting-started.md).
