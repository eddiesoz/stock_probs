---
title: "Threat model"
description: "Threats and controls for loopback HTTP, untrusted requests, Yahoo market/news data, SQLite state, exports, and managed backup artifacts."
---

# Threat model

Stock Probability assumes one local operator on a Linux machine. It protects audit history,
forecast provenance, local filesystem locations, backup authenticity, and process availability
from accidental corruption and untrusted browser/provider/request input. It is not designed as
a publicly exposed multi-user service.

## Trust boundaries and controls

| Boundary or threat | Control |
| --- | --- |
| Remote access or browser cross-origin traffic | Loopback-only environment configuration, explicit warning flag for unsupported broader CLI binds, host/origin checks, strict response headers, and no permissive cross-origin API policy. |
| Oversized, malformed, or slow request bodies | Bounded framing/body checks, bounded server concurrency/backlog/keep-alive, typed validation, and sanitized error envelopes. |
| Provider delay or malformed Yahoo market data | Explicit 1–20 second configured timeout, bounded lookup/history calls, provider concurrency of two, normalized identity/bar contracts, and no provider objects exposed by transport. |
| Untrusted headline text or article destinations | Headline fields reject controls and enforce length/type bounds; presentation inserts them as text, not HTML. Links must be public HTTPS destinations without credentials, local/private hosts, or non-HTTPS ports; invalid links are not made operable. |
| Oversized, slow, or repeatedly failing news responses | One direct request has an absolute `min(configured timeout, 10 seconds)` deadline and a 256 KiB raw-body cap, with no retries or redirects. One retrieval may run at a time. Failure suppression lasts 30 seconds. |
| Unbounded or persistent news retention | The process-memory cache is limited to 32 symbols, 32 KiB per entry, and 1 MiB total, with five-minute fresh, 60-second empty, and 30-minute stale bounds. It makes no SQLite, ledger, backup, model, or fingerprint writes. |
| Browser bypass of server ownership | Presentation fetches `/api/v1` only; database paths, SQL, and direct Yahoo requests are absent from browser data flow. |
| External article navigation | Each operable link is disclosed as an external site and opens only after user activation with `noopener noreferrer`. That navigation leaves the loopback application and contacts the destination directly; it is not an application data request or an article proxy. |
| SQLite mutation or migration drift | Private storage permissions, no-follow path hardening, foreign keys, checksum-pinned additive migrations, immutable/append-only triggers, short-lived connections, and bounded per-database coordination. |
| Forged, oversized, or path-traversing backup | Managed filenames, exact archive-member allowlist, size/metadata bounds, installation-key manifest authentication, checksums, compatibility/integrity/count checks, staged promotion, and rollback. |
| Export formula execution or data leakage | Bounded exports, typed shared record construction, dangerous spreadsheet-cell prefixes neutralized, and no server filesystem paths in responses. |
| Diagnostic leakage | Public failures use stable safe categories and request IDs; logs classify operation and exception type without request bodies, local paths, or raw exception text. |

## Operator responsibilities

Keep the listener on loopback, restrict access to the operating-system account, protect the
data directory and backup trust key, review exports before sharing, and stop the process before
moving active storage. Treat Yahoo content and imported artifacts as untrusted even on a local
machine. Review an article destination before following it; the destination receives an ordinary
browser navigation even though application data traffic remains local. Do not disable
verification to recover an artifact.

Authentication, MFA, an API gateway, a multi-service split, replicas, and public hosting are
deliberate non-goals absent a new demonstrated requirement. The application is research
software; security controls do not make forecasts investment advice.

See [backup and restore](../operations/backup-restore.md) and
[architecture](../concepts/architecture.md).
