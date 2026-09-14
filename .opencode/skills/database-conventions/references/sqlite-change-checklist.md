# SQLite change checklist

## Before editing

1. Trace every affected repository caller and transaction.
2. Read all packaged migrations in order and identify clean-create and upgrade behavior.
3. Confirm whether the change can remain in `repository.py` without a schema change.

## Migration and query checks

- Name a schema change `<next-version>_<purpose>.sql`; keep prior files byte-for-byte unchanged.
- Update `SCHEMA_VERSION` and `MIGRATION_SHA256` only for the new migration.
- Keep migration history contiguous and apply each pending migration under `BEGIN IMMEDIATE`.
- Use `?` parameters for values. Dynamic table, column, sort, or clause text must come only from a
  fixed code-owned allowlist.
- Add constraints or triggers that preserve append-only records on raw SQLite connections, including
  `INSERT OR REPLACE` conflict paths.

## Minimum verification

Run the focused persistence suite:

```bash
.dev-venv/bin/python -m pytest tests/test_repository_backup.py -q
```

For a migration, retain checks that clean creation is idempotent, upgrade schema matches clean
schema, previous rows survive, checksum drift fails before database work, and unknown or gapped
history fails closed. For backup integration, also run:

```bash
.dev-venv/bin/python -m pytest tests/test_backup_automation.py tests/test_backup_cli.py -q
```

Verify a failed pre-migration backup leaves the old schema intact and a restore is checked before
promotion. Report the exact command and result; do not treat file presence as acceptance.
