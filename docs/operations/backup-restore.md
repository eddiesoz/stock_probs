---
title: "Backup and restore"
description: "Create, verify, and optionally promote authenticated managed SQLite backups without bypassing the application boundary."
---

# Backup and restore

Backups are managed `.spbackup` files beneath `STOCK_PROBS_DATA_DIR/backups`. The first backup
attempt made with no managed artifacts creates a separate installation trust key at
`STOCK_PROBS_DATA_DIR/.backup-auth.key`, before the artifact is verified and published; a failed
first attempt can therefore leave the key in place. Preserve that key with the installation.
Restore never regenerates a missing key because a replacement could not authenticate earlier
artifacts.

Backups contain the managed SQLite snapshot and its authenticated manifest. They exclude the
origin-scoped browser theme preference and the process-memory headline cache. Restoring or moving
a backup therefore does not change a browser's light/dark/system choice, restore earlier
headlines, or trigger a headline request; current headlines must be requested separately after
the service is running.

Create a timestamped backup:

```bash
.dev-venv/bin/python -m stock_probs.cli backup
```

Or supply a managed name: one leading ASCII alphanumeric character, followed by at most 63 ASCII
alphanumeric, `_`, `.`, or `-` characters, and then the `.spbackup` suffix. In regex form, the
constraint is `^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\.spbackup$`.

```bash
.dev-venv/bin/python -m stock_probs.cli backup --name before-upgrade.spbackup
```

## Automatic backups

Every CLI command that initializes persistence may apply pending migrations: `migrate`, `serve`,
`backup`, `restore`, `backup-key rotate`, and `backup-key retire`. Each command routes migration
through the repaired protection, which creates and verifies one pre-migration backup immediately
before upgrading an existing older schema. A fresh database or already-current schema creates no
pre-migration artifact.

After its protected migration step, `serve` performs the due check. Before selecting the newest
artifact, the check authenticates every managed artifact; one corrupt artifact or one that does
not match the installation key blocks the check and startup. It then fully verifies the newest
artifact with `require_active_schema=false`. Consequently, a valid pre-migration artifact can be
newest and suppress a current-schema due backup until it reaches
`STOCK_PROBS_BACKUP_INTERVAL_SECONDS`. Otherwise the check creates a backup when none exists or
when the newest artifact is at least that interval old. The default is `86400` seconds; supported
values are `60` through `2678400`. Any automatic-backup failure aborts startup.

Restore defaults to non-destructive verification:

```bash
.dev-venv/bin/python -m stock_probs.cli restore before-upgrade.spbackup
```

Only after verification succeeds, explicitly promote it:

```bash
.dev-venv/bin/python -m stock_probs.cli restore before-upgrade.spbackup --promote
```

Creation uses SQLite's online snapshot API and records database/schema checksums, schema version,
byte size, representative row counts, and an authenticated manifest. Restore accepts only the two
expected archive members, enforces a 64 MiB artifact bound, authenticates before database
inspection, and checks SQLite integrity, foreign keys, migrations, schema, and counts. With
`--promote`, it also verifies the staged candidate, atomically swaps it into place, and rechecks
the active database's integrity and representative counts before reporting success; a failed
post-swap check restores the verified rollback copy.

An existing `.pre-restore.sqlite3` rollback file blocks promotion only; verification without
`--promote` still works. After a successful promotion, failure to remove the retained rollback is
reported as `"rollback_cleanup_required": true`; resolve that file before another promotion.

For a managed `BackupError` from `migrate`, `backup`, `restore`, or `backup-key`, stderr contains
JSON shaped as `{"error":"<safe diagnostic>"}` and the process exits with status 2. An automatic
`serve` `BackupError` writes `{"error":"<safe diagnostic>","trigger":"automatic_backup"}` to
stderr and aborts ASGI startup.

## Trust-key lifecycle and retention

Rotate the installation trust key and re-sign every managed artifact together:

```bash
.dev-venv/bin/python -m stock_probs.cli backup-key rotate
```

Retire a key only after every managed artifact has been explicitly transferred or removed:

```bash
.dev-venv/bin/python -m stock_probs.cli backup-key retire
```

Rotation verifies every artifact before replacing the signatures and key. Retirement fails while
any managed artifact remains. When transferring backups to another installation, stop the service
and copy `.backup-auth.key` together with all intended `.spbackup` files through an out-of-band
protected channel. Preserve mode `0600`, place the files beneath the destination data directory,
verify there before deleting the source copies, and transfer the newly signed set again after any
rotation. Never generate a replacement key for existing artifacts.

Creation is rejected when 32 managed artifacts already exist. The storage check rejects creation
only when existing artifacts plus the candidate would exceed 256 MiB; exactly 256 MiB is allowed.
The application does not silently prune backups, and these limits never expire or delete query
history in the active database.

Never unpack an artifact over the database manually. Keep the service stopped while moving a
data directory between machines, copy the trust key through an out-of-band protected channel,
retain private file permissions, and run verification before promotion. A missing/wrong key,
unexpected archive member, checksum mismatch, schema mismatch, promotion-blocking rollback file,
or bounded-lock failure must be resolved rather than bypassed.

The HTTP operations in the [API reference](../reference/api.md) accept managed names and expose
storage-neutral results/status; neither CLI nor browser receives an arbitrary restore destination.
