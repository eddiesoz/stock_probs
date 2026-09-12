---
title: "API reference"
description: "Versioned FastAPI endpoint inventory for health, forecasts, immutable history, outcomes, exports, backups, restores, and local documentation."
---

# API reference

Application data is served below `/api/v1`. The browser uses this boundary exclusively.
FastAPI publishes the machine-readable contract at `/api/v1/openapi.json`; the
dependency-free local pointer is `/api/v1/docs`.

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/api/v1/health` | Process health and API version. |
| `GET` | `/api/v1/readiness` | Migration-backed readiness, schema version, and selected provider. |
| `GET` | `/api/v1/instruments` | Bounded company/symbol lookup (`query`, optional `limit` up to 5) with complete selectable identity. |
| `POST` | `/api/v1/forecasts` | Submit `{symbol, asset_type}` and create an audited two-horizon forecast. Returns `201`, `Location`, and `X-Request-ID`. |
| `GET` | `/api/v1/history` | Filter, sort, and page submitted events; page size is bounded to 100. |
| `GET` | `/api/v1/history-export.csv` | Download at most 100 filtered audit events with CSV formula-safety handling. |
| `GET` | `/api/v1/history-export.json` | Download the same bounded typed audit record stream as JSON. |
| `GET` | `/api/v1/history/{event_id}` | Read immutable event detail, including a failed request when no forecast exists. |
| `GET` | `/api/v1/saved-forecasts/{event_id}` | Reopen captured forecast inputs/results without provider access or recalculation. |
| `POST` | `/api/v1/history/{event_id}/reconstructions` | Run and record a distinct fresh analysis for a timezone-aware historical `cutoff`. |
| `GET` | `/api/v1/history/{event_id}/prices` | Read bounded captured `daily` or `intraday` prices; no provider call. |
| `GET` | `/api/v1/forecasts/{result_id}` | Read one immutable original horizon result without folding in outcomes. |
| `POST` | `/api/v1/forecasts/{result_id}/outcomes` | Append an observed, unavailable, or provisional outcome. |
| `POST` | `/api/v1/forecasts/{result_id}/corrections` | Append a correction; it does not update an earlier outcome. |
| `POST` | `/api/v1/operations/backups` | Create a verified managed backup with an optional managed name. |
| `GET` | `/api/v1/operations/backups/status` | Report bounded backup capability without filesystem paths. |
| `POST` | `/api/v1/operations/restores` | Verify a managed backup, and promote only when `promote` is explicitly true. |

Validation, domain, provider, persistence, and unexpected failures use sanitized JSON error
envelopes. Provider internals, SQL text, credentials, and database paths are not public API
fields. Local origin/host/content constraints are enforced before application work; do not
treat the loopback API as a general network service.

For exact request and response schemas, use the OpenAPI document from the running revision.
For user flow, see [dashboard usage](../usage/dashboard.md).
