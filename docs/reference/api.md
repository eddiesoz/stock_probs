---
title: "API reference"
description: "Versioned FastAPI endpoint inventory for health, forecasts, current news, immutable history, outcomes, exports, backups, restores, and local documentation."
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
| `GET` | `/api/v1/news?symbol=<normalized>&limit=5` | Read ephemeral current headlines for a normalized symbol; `limit` defaults to 5 and is bounded from 1 through 10. No persistence effect. |
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

## News contract

The news operation has four closed schemas; unknown fields are rejected rather than retained:

| Schema | Fields and meaning |
| --- | --- |
| `NewsQuery` | `symbol` is normalized to the supported uppercase symbol form; `limit` is an integer from 1 through 10. |
| `NewsItem` | Required `id`, `title`, and public HTTPS `url`; optional `publisher`, UTC `published_at`, and `related_symbols` remain `null` when the provider omits them. |
| `NewsCoverage` | `returned_count` exactly matches `items`; `partial_metadata` is true when a returned item lacks publisher, publication time, or related symbols; `refresh_failed` is true only for a stale fallback. |
| `NewsResponse` | Echoes the normalized `query` and reports `provider`, UTC `as_of`, bounded `items`, `coverage`, and `cache_state` (`miss`, `hit`, or `stale_fallback`). |

`as_of` is the provider-request time assigned to the returned set, not an individual article's
publication time. A cache hit preserves that time, and a stale fallback preserves the cached
time so its age remains visible. `published_at` is the separate, optional article timestamp.
`cache_state=miss` means no usable cached entry satisfied the request and a provider retrieval
completed; `hit` means a positive entry younger than five minutes or an empty entry younger
than 60 seconds satisfied it without a provider call. `stale_fallback` means refresh failed and
a non-empty cached entry no older than 30 minutes was returned; in that case
`coverage.refresh_failed` is true. Provider failures are suppressed for 30 seconds, but that
suppression does not make expired or empty data eligible for stale fallback.

Status `200` covers a current/fresh result, a successful empty result, or a stale fallback.
Invalid query input returns `422`, provider failure without eligible cache returns `502`, and
the single news retrieval slot being occupied returns `503`. Empty news is a successful
response and never returns `404`.

Validation, domain, provider, persistence, and unexpected failures use sanitized JSON error
envelopes. Provider internals, SQL text, credentials, and database paths are not public API
fields. Local origin/host/content constraints are enforced before application work; do not
treat the loopback API as a general network service.

For exact request and response schemas, use the OpenAPI document from the running revision.
For user flow, see [dashboard usage](../usage/dashboard.md).
