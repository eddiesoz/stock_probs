---
name: "database-conventions"
description: "Apply Stock Probability SQLite repository and migration rules for schema changes, bound queries, immutable audit records, and backup-safe upgrades. Use when changing repository.py, packaged migrations, persistence SQL, or migration and restore checks."
---

# Stock Probability database conventions

Use this skill only for the SQLite persistence boundary implemented by
`src/stock_probs/repository.py` and `src/stock_probs/migrations/*.sql`.

## Rules

- Add a new contiguous numbered migration; never rewrite a shipped migration.
- Bump `SCHEMA_VERSION` and add the new file's SHA-256 to `MIGRATION_SHA256` together.
- Keep SQL structure fixed or selected from a code-owned allowlist. Bind every data value with
  SQLite placeholders.
- Preserve foreign keys, short-lived coordinated connections, explicit transactions, and rollback
  on failure.
- Keep search events, inputs, results, outcomes, facets, and migration receipts immutable or
  append-only. Do not replace, update, delete, or silently rebuild recorded audit data.
- Run the pre-migration backup hook once immediately before the first pending upgrade. A failed
  backup must prevent every pending schema change; clean database creation needs no backup.
- Prove both clean creation and upgrade parity. Restore checks must verify the restored schema and
  representative records before promotion.

Follow the smallest applicable workflow in
[`references/sqlite-change-checklist.md`](references/sqlite-change-checklist.md).

## Non-goals

Do not import PostgreSQL, FTS, external synchronization, ORM, or generic database conventions into
this local SQLite application.
