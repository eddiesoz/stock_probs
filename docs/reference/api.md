---
title: "API reference"
description: "Versioned FastAPI endpoint inventory for workspace instruments, quotes, charts, lists, forecasts, current news, immutable history, outcomes, exports, backups, restores, and local documentation."
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
| `GET` | `/api/v1/quotes` | Provider-labelled quote snapshots for one comma-separated batch of up to 20 normalized symbols. |
| `GET` | `/api/v1/bars` | One symbol's bounded daily chart for `range=5d`, `1mo`, `3mo`, `6mo`, or `1y`; the response interval is fixed at `1d`. |
| `GET` | `/api/v1/lists` | Read the bounded local `watchlist`, `portfolio`, or `all` instrument list. |
| `POST` | `/api/v1/lists` | Add or update one local list item; manual `quantity` is allowed only for `portfolio`. Returns `201` and `Location`. |
| `DELETE` | `/api/v1/lists` | Remove one local list item by `kind` and normalized `symbol`. Returns `204`. |
| `GET` | `/api/v1/news?symbol=<normalized>&limit=5` | Read ephemeral current headlines for a normalized symbol; `limit` defaults to 5 and is bounded from 1 through 10. No persistence effect. |
| `POST` | `/api/v1/forecasts` | Submit `{symbol, asset_type, interval?}` and create an audited forecast. Without `interval` it returns the legacy two-horizon pair; with one of `5min`, `daily`, `weekly`, `monthly`, or `quarterly` it returns the selected rolling horizon. Returns `201`, `Location`, and `X-Request-ID`. |
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
| `GET` | `/api/v1/auth/totp/status` | Report authenticator enrollment and recovery-code state without returning secrets. |
| `POST` | `/api/v1/auth/totp/enroll/start` | Start a short-lived authenticator enrollment transaction. |
| `POST` | `/api/v1/auth/totp/enroll/finish` | Confirm the six-digit code, activate TOTP, and return one-time recovery codes. |
| `POST` | `/api/v1/auth/totp/verify` | Verify the authenticator code after GitHub OAuth and issue a workspace session. |
| `POST` | `/api/v1/auth/totp/step-up` | Record fresh TOTP proof for an administrator operation. |
| `POST` | `/api/v1/auth/totp/recover` | Consume one recovery code and issue a factor-replacement-only session. |
| `POST` | `/api/v1/auth/totp/recovery-codes/rotate` | Replace recovery codes after a fresh TOTP verification. |

There is no `/api/v1/market-depth` endpoint and no `MarketDepthResponse` schema. The Live Trading
workspace may disclose that free data has no exchange-depth entitlement, but it does not fabricate
bid/ask rows or claim Nasdaq TotalView, exchange depth, order execution, brokerage connectivity, or
real-time delivery.

## Authentication contract

Production uses GitHub's authorization-code flow with state and PKCE to establish the stable
numeric GitHub identity. An invitation is resolved, expiring, and single-use. After OAuth, a user
must enroll or verify a six-digit TOTP code from an authenticator app before private workspace
routes are available. This TOTP code is the sole ongoing application second factor; ordinary sign-in
does not require Bluetooth, a nearby phone, or browser passkey support.

`/api/v1/auth/totp/enroll/start` returns setup material only for the short-lived enrollment
transaction. Add the secret to an authenticator app using the manual key or the `otpauth://` link,
then submit the current code to `/enroll/finish`. The response returns recovery codes exactly once.
Recovery codes are single-use and must be kept offline. `/recover` accepts one unused code and
returns a restricted session that can replace the factor; it does not grant a normal workspace
session. `/step-up` records fresh proof for an administrator backup or restore. Passkey routes are
legacy migration endpoints only and do not create new production passkeys.

## Research-workspace contracts

`GET /api/v1/instruments` returns at most five identity-complete matches. Each match keeps the
canonical symbol with display/company name, exchange, currency, timezone, quote type, asset type,
provider, and provider as-of time; callers must not detach a company name from its identity.

`GET /api/v1/quotes?symbols=ACDC,SPY` accepts one `symbols` parameter containing one through 20
comma-separated symbols. Each returned item includes `last`, optional OHLC/volume/trade fields,
`source`, UTC `as_of`, `state` (`provider_reported`, `delayed`, or `simulated`), `delayed`, an
optional positive `delay_minutes`, and a disclosure `label`. A missing delay does not become a
real-time claim.

`GET /api/v1/bars` accepts `symbol`, optional matching `asset_type`, and the bounded `range` query
parameter. It returns `range`, `interval: "1d"`, an adjustment-basis statement, source/as-of and
delay disclosure, plus captured bars with timestamp, end, close, and duration. The endpoint is a
daily chart surface; it does not expose market depth or an unbounded intraday stream.

`GET /api/v1/lists?kind=watchlist|portfolio` reads local records. A `POST` body is:

```json
{"kind":"portfolio","item":{"symbol":"SPY","asset_type":"etf","quantity":2}}
```

`quantity` is optional and must be finite and non-negative, but it is rejected for a watchlist.
The server resolves the submitted symbol to a provider identity before persisting it. Duplicate or
bounded-list conflicts return `409`; `DELETE` requires `kind` and `symbol` and returns `404` when
the item is absent.

The forecast interval mapping is:

| Request interval | Horizon | Boundary |
| --- | --- | --- |
| `5min` | `five_min_forward` | Latest completed five-minute bar to the next completed five-minute bar. |
| `daily` | `daily_1` | Latest completed daily close to the next scheduled session close. |
| `weekly` | `weekly_5` | Latest completed daily close to the fifth subsequent session close. |
| `monthly` | `monthly_21` | Latest completed daily close to the 21st subsequent session close. |
| `quarterly` | `quarterly_63` | Latest completed daily close to the 63rd subsequent session close. |

Each selected interval returns one result and preserves its interval, target boundary, availability,
sample accounting, empirical intervals, provider snapshot, and provenance. Insufficient history is
an explicit unavailable result, not a substituted horizon. See [forecast model](../concepts/forecast-model.md)
for calculation semantics.

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
