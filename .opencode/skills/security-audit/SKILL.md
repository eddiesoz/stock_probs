---
name: "security-audit"
description: "Audit Stock Probability local security boundaries for loopback HTTP, provider links, SQLite and backups, exports, and dependencies. Use when changing LocalSecurityMiddleware, provider URL handling, storage or backup trust, export handling, or security-relevant dependencies."
---

# Stock Probability security audit

Start with `docs/security/threat-model.md` and review only the changed trust boundaries.

## Required boundaries

- `LocalSecurityMiddleware` keeps browser traffic on an allowed loopback Host and same origin,
  rejects cross-site requests, bounds request framing, returns safe errors, and applies the strict
  CSP and isolation headers to success and error responses. Do not add permissive CORS.
- Provider headline text remains bounded text, never HTML. Operable article URLs must be public
  HTTPS destinations without credentials, local/private hosts, or non-HTTPS ports.
- SQLite files remain private and no-follow hardened; values remain parameter-bound; migrations are
  checksum-pinned; recorded data remains immutable or append-only.
- Backup artifacts remain bounded, authenticated by the installation trust key, checksum-verified,
  allowlisted, staged, and verified before promotion. Do not expose storage paths or trust material.
- Exports remain bounded, neutralize spreadsheet formulas, omit local paths, and undergo checkpoint
  redaction and secret-pattern review before sharing.
- Dependency review is limited to relevant `pyproject.toml` and `requirements.lock` changes and the
  locked package path. Ignore `burry_env/` legacy noise.

Use [`references/audit-checklist.md`](references/audit-checklist.md) for focused checks and reporting.

## Deliberate non-goals

This is a single-operator loopback application. Do not recommend authentication, MFA, an API
gateway, public hosting, a multi-service split, or replicas without a new demonstrated requirement.
