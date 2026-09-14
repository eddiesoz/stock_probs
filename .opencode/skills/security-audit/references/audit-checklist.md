# Security audit checklist

## Scope the review

Map each changed path to the threat-model row it can affect. Review the implementation, its direct
callers, and focused tests. Report unsupported hardening ideas as out of scope rather than expanding
the local application contract.

## Inspect

1. **HTTP:** Host parsing, same-origin checks, loopback allowlists, body bounds, safe error envelopes,
   CSP, and isolation headers on every response path.
2. **Provider:** bounded text and public HTTPS URL validation, including userinfo, private address,
   local suffix, and port rejection.
3. **SQLite and backups:** private/no-follow paths, bound SQL values, immutable migrations and audit
   rows, archive member and size limits, installation-key authentication, checksums, staged restore,
   rollback, and sanitized API responses.
4. **Exports:** bounded output, spreadsheet-prefix neutralization, no local paths, and canonical
   secret-pattern redaction before a checkpoint leaves the machine.
5. **Dependencies:** explain each changed direct dependency and lock delta; use the pinned lock and
   package smoke rather than an untracked environment or an unpinned substitute.

## Focused verification

Run the checks applicable to the changed boundary:

```bash
.dev-venv/bin/python -m ruff check --select S --ignore S101 src tests scripts
.dev-venv/bin/python -m pytest tests/test_api.py -q
.dev-venv/bin/python -m pytest tests/test_repository_backup.py tests/test_backup_cli.py -q
.dev-venv/bin/python scripts/package_smoke.py
```

The full API file covers Host/origin/CSP, safe errors, provider-facing contracts, export output, and
backup response leakage. The backup files cover trust-key, tamper, traversal, bounds, staging, and
rollback behavior. Run package smoke when dependencies or packaging changed.

Report exact commands and results, changed boundaries, findings, and unavailable checks. Never print
or persist a discovered secret; never treat redaction as a substitute for rotating an exposed key.
