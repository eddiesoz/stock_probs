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
| `GET` | `/api/v1/auth/status` | Return the configured sign-in mode and public origin. |
| `GET` | `/api/v1/auth/session` | Return the current session state, role, and CSRF token when signed in. |
| `POST` | `/api/v1/auth/local/login` | Sign in with local credentials when local authentication is enabled. |
| `GET` | `/api/v1/auth/github/start?invite=<code>` | Start the browser-bound GitHub authorization flow and redirect to GitHub. The `invite` query is optional. |
| `GET` | `/api/v1/auth/github/callback` | Complete the OAuth exchange and issue a provisional session for authenticator enrollment or verification. |
| `POST` | `/api/v1/auth/logout` | Revoke the current session and clear its cookies. Returns `204`. |
| `POST` | `/api/v1/auth/invites` | Create a single-use, expiring invitation for a numeric GitHub ID; returns a code for private sharing. Requires an administrator. |
| `GET` | `/api/v1/auth/invites` | List bounded invitation metadata and report whether email invitations are configured. Requires an administrator. |
| `POST` | `/api/v1/auth/invites/email` | Create an email-targeted invitation and submit its code to configured SMTP. Accepts an email without a GitHub ID or login; optional explicit identity fields are supported. Requires an administrator; SMTP acceptance is not mailbox delivery. |
| `POST` | `/api/v1/auth/invites/redeem` | Validate an invitation and return the browser-bound GitHub authorization URL. No signed-in session is required. |
| `GET` | `/api/v1/auth/sessions` | List safe metadata for the current user's active sessions. |
| `DELETE` | `/api/v1/auth/sessions/{session_id}` | Revoke one session owned by the current user. Returns `204`. |
| `GET` | `/api/v1/auth/totp/status` | Report authenticator enrollment and recovery-code state without returning secrets. |
| `POST` | `/api/v1/auth/totp/enroll/start` | Start a short-lived authenticator enrollment transaction. |
| `POST` | `/api/v1/auth/totp/enroll/finish` | Confirm the six-digit code, activate TOTP, and return one-time recovery codes. |
| `POST` | `/api/v1/auth/totp/verify` | Verify the authenticator code after GitHub OAuth and issue a workspace session. |
| `POST` | `/api/v1/auth/totp/step-up` | Record fresh TOTP proof for an administrator operation. |
| `POST` | `/api/v1/auth/totp/recover` | Consume one recovery code and issue a factor-replacement-only session. |
| `POST` | `/api/v1/auth/totp/recovery-codes/rotate` | Replace recovery codes after a fresh TOTP verification. |

Authenticated state-changing requests require the session's CSRF token in `X-CSRF-Token`. The
OAuth start/callback and anonymous invitation-redemption routes use their browser-bound transaction
flow. Invitation creation, listing, and email submission require an administrator; session listing
and revocation are limited to the signed-in user's own sessions. The HTTP API has no invitation
revocation route; invitations expire and can be redeemed once.

## R-ASTRA-120 assistant candidate API

These routes are present in the R-ASTRA-120 candidate source and are not part of the currently
deployed schema-12 production release. User routes use the existing authenticated, CSRF-protected
application boundary; mutations require CSRF, and conversation, turn, event, and preview access
checks active-session ownership. Provider administration routes use administrator checks, with
fresh TOTP for sensitive operations. Candidate route presence is not runtime or release acceptance.

| Method and route family | Purpose |
| --- | --- |
| `GET /api/v1/assistant/status`, `GET /api/v1/assistant/models`, `GET /api/v1/assistant/context` | Report candidate readiness and retrieve user-authorized model/workspace context. |
| `POST /api/v1/assistant/conversations`; `GET /api/v1/assistant/conversations`; `GET/PATCH/DELETE /api/v1/assistant/conversations/{conversation_id}` | Create, list, read, update, and delete user-owned conversations. |
| `POST /api/v1/assistant/conversations/{conversation_id}/turns`; `GET /api/v1/assistant/conversations/{conversation_id}/turns/{turn_id}/events`; `POST /api/v1/assistant/conversations/{conversation_id}/turns/{turn_id}/cancel` | Submit turns, read that user's turn events, or request cancellation. |
| `POST /api/v1/assistant/conversations/{conversation_id}/actions/{action_id}/confirm` | Confirm or decline a versioned, user-visible action preview. |
| `GET /api/v1/assistant/conversations/{conversation_id}/turns/{turn_id}/search-previews/{preview_id}`; `POST .../{preview_id}/confirm` | Review and confirm native websearch previews. |
| `GET /api/v1/assistant/conversations/{conversation_id}/turns/{turn_id}/webfetch-previews/{preview_id}`; `POST .../{preview_id}/confirm` | Review and confirm bounded native webfetch previews. |
| `/api/v1/assistant/providers/**` | Candidate provider/model policy, consent, validation, and OAuth administration routes. |
| `/api/v1/assistant/internal/**` | Private loopback-only provider/MCP bridge endpoints for a live execution; these are not browser APIs. |

The candidate application MCP catalog is typed and owner-scoped. Private reads derive ownership from
the authenticated user's live execution lease and are bounded to the turn. Each turn starts with a
browser-reviewed page-context preview; this is separate from tool execution and does not approve
external requests. `assistant.propose_action` creates a user-visible card but never applies it. The
same authenticated browser session must confirm the current action version and page context with its
single-use confirmation phrase. Sensitive administrator actions also require fresh TOTP step-up.

OpenCode V2 supplies native `websearch` and `webfetch`; the application does not replace them with a
custom search adapter or external search service. Every native search pauses for approval of its
exact query in the authenticated browser. When the WebFetch guard is ready, each fetch pauses for
approval of its exact public HTTPS URL. A redirect destination is blocked before contact; following
a safe redirect requires a new WebFetch request and a separate approval for that exact URL. Further
redirects need further approvals, within the five-hop, eight-tool, and 120-second turn bounds. When
the guard is unavailable, WebFetch is denied. Chat text does not approve a search, fetch, or action.

R-ASTRA-120 remains **In progress**, and the assistant candidate is disabled in production.
Native/runtime, accessibility, actual combined 1 GB resource, PR-bound rollback, and release
acceptance remain open. See the
[authoritative R-ASTRA-120 ledger](../../MVP-PLAN.md#r-astra-120-signal-ledger-assistant-design-first-follow-on)
for current receipts and detailed statuses.

### Assistant feature coverage matrix

This matrix maps the candidate source contracts to the existing application. It is a coverage
inventory for verification, not evidence that each workflow has passed. Application MCP reads
require a live owner-scoped execution. Each turn requires acknowledgement of the visible page-context
preview; subsequent private reads use that turn's live owner/session lease and bounded tool-call
counter. This is not a separate approval for each private read. External search and fetch requests
have separate exact previews. `assistant.propose_action` creates a card and cannot approve it. Every proposed change
or handoff needs the authenticated browser's exact, current, single-use confirmation.

| Route or feature | Read or explanation path | Change or navigation path |
| --- | --- | --- |
| `/`, `/overview`: research totals, portfolio and watchlist | `workspace.summary`, `workspace.instrument_lists`; server-derived owner counts | Portfolio/watchlist proposals below; existing overview controls remain available. |
| Signal Ledger dashboard (`/`): searchable, paginated history | `history.search`; bounded typed filters and summaries | Confirmed filter handoffs open the dashboard history form; the typed filter handoff is available only on `/`. Confirmed CSV/JSON export handoffs open owner-authorized downloads from any supported page. Source implementation is present; full feature coverage and QA remain pending. |
| `/research`: recent research and saved-forecast comparison | `history.search`; owner-scoped bounded history and saved-forecast records | Shows five recent records from the newest 100 events and compares saved forecasts. The assistant can search owner-scoped history here. To apply filters, use the dashboard history form (`/`), where the typed filter handoff is available. Confirmed CSV/JSON export handoffs are route-independent and open owner-authorized downloads. Source implementation is present; full feature coverage and QA remain pending. |
| Saved forecasts and input series | `history.saved_forecast`; immutable result and bounded daily/intraday series | `forecast.reopen` opens the saved result; it does not rerun a provider or alter the record. |
| `/tools`: tool landing page | Route-specific harness help describes the available workspaces | Use the existing Forecast, Live Trading and Markets navigation; opening a page does not run research. |
| `/tools/forecast`: new forecasts | `market.instrument_search`; selected instrument and saved-result references | `forecast.create` proposes a new run; `reconstruction.run` proposes separately labelled fresh historical analysis. |
| Forecast outcomes | `history.outcomes`; owner-checked result and bounded observations | `outcome.record` appends an observation after confirmation; recorded forecasts remain immutable. |
| `/tools/live-trading`: holdings | `workspace.instrument_lists`, public quote reads | `portfolio.add`, `portfolio.set_quantity`, `portfolio.remove`; quantities are research records, not brokerage positions. |
| Watchlists | `workspace.instrument_lists`, public instrument lookup | `watchlist.add`, `watchlist.remove`; ownership derives from the active session. |
| `/tools/markets`: quotes, bars and comparison | `market.quote`, `market.bars`, `market.compare`; exact provider/exchange identity | `market.open` navigates to the matching instrument workspace. Typed local filter, chart-range, visible-column, and quote/watchlist/chart refresh controls are implemented in source on the Markets page. Full feature coverage and independent QA remain pending. |
| Selected-instrument news | `market.news`; bounded public headlines with source/as-of | Public article links retain the existing safe-link behavior; no hidden browser automation. |
| Live Trading notes and alerts | Existing local UI; these are not silently uploaded as server-owned records | `notes.set`, `notes.clear`, and `alerts.remove` hand off to the matching local control; `alerts.add` uses a typed, active-page/session-scoped browser action. |
| Light/Dark/System settings | Current UI and route context; stored presentation choice remains local | `theme.set` uses the typed browser bridge after confirmation. |
| `/api-docs` | Route-specific help points to the app's reference; the harness has no local-document/file access | Read the existing documentation UI; the assistant does not rewrite API contracts. |
| `/account`: sessions and authenticator recovery | Route-specific help; credentials, TOTP and recovery codes stay outside chat | `account.sessions.manage` hands off to secure account controls. |
| `/admin`: invitations | Administrator-only route help | `invitation.create` requires a current administrator and fresh TOTP, then hands off to the protected invitation form; identity/email and delivery fields are collected there. |
| `/admin`: backup and restore | Administrator-only route help | `backup.create`, `restore.promote` hand off to secure controls; fresh TOTP and existing restore safeguards remain required. |
| `/admin`: providers, models, credentials and consent policy | Approved-model discovery; masked provider status in secure admin UI | `provider.settings` requires a current administrator and fresh TOTP, then hands off to admin forms; keys and provider OAuth never enter chat. |
| Sign-in, invitation redemption, authenticator enrollment and retired `/passkey` route | Existing secure authentication UI; assistant launcher is unavailable before workspace authentication | Complete the secure form or redirect; no chat-based authentication or code collection. |
| Public web research | OpenCode V2 native search and guarded fetch; exact query or public HTTPS destination preview, with source metadata when returned | Each request needs its own browser approval; redirects need fresh approval before contact. No TinyFish, custom search service, account signup, paid fallback or arbitrary fetch tool. |
| Conversation history, model choice and assistant controls | Owner-authenticated conversation/model interfaces and provider-free saved answers | Browser CRUD, cancellation, reconnect, expand/minimize/close and versioned privacy consent; the model cannot manage its own approvals. |

The source contracts are in `assistant/tools.py`, `assistant/service.py`, `assistant/runtime.py`
and the frontend assistant/browser bridge. Verify the matrix with populated, repeated and
unavailable-data states. Synthetic browser tests, native disposable probes and production checks
must keep their evidence scopes separate.

For Live Trading, `notes.set`, `notes.clear`, and `alerts.remove` are secure local-control handoffs:
they do not change a note or remove an alert until the user completes the corresponding workspace
control. On mobile the handoff closes the full-screen assistant and focuses that control. The
assistant's action receipt remains in the conversation; reopen assistant history and the same
conversation to review it. `alerts.add` instead uses the typed browser bridge after confirmation and
is limited to the active Live Trading page/session; it is not a server-owned or cross-session alert.
These are candidate behaviors, not production availability or release acceptance.

`R-ASTRA-111` applies admission bounds to GitHub OAuth start: 8 starts per effective caller
and 64 per app process in a rolling minute, plus 8 outstanding transactions per caller and 128
overall. The minute counters are process-local; outstanding transaction records are database-backed.
Per-caller overflow returns `429` with `Retry-After`; global start or outstanding capacity can return
`503`. The caller key is a keyed hash of the socket peer IP. A peer configured in
`STOCK_PROBS_TRUSTED_PROXY_HOSTS` may supply `CF-Connecting-IP`; other forwarded-IP headers are not
used. Shared NAT or proxy egress addresses share the per-caller limit. Production Compose ingress
attribution is installed through the reviewed host-Compose update path. These limits are deployed
with R-ASTRA-111 on schema 11; in-progress OAuth transactions were cleared during migration and
must be restarted. The independent local Docker bridge regression and bounded public boundary
probes passed. See the [R-ASTRA-111 evidence](../../MVP-PLAN.md).

`POST /api/v1/auth/invites/email` returns `submission_status: "smtp_accepted"` when the configured
SMTP server accepts the submission. That response does not prove mailbox delivery or reading.
Production email invitations are currently enabled under R-ASTRA-112. Its operator test confirmed
delivery to Gmail, but the message landed in Spam, so inbox placement was not achieved for this
test; the operator called the service functions used by this endpoint rather than exercising the authenticated HTTP route. See the
[R-ASTRA-112 evidence](../../MVP-PLAN.md).

## Email invitation contract

`POST /api/v1/auth/invites/email` accepts an administrator-authenticated request with an email
address. `github_id` is optional; an email-only invitation does not require the administrator to
look up an account ID. Without `github_id`, the email supplies the identity binding for redemption.
If a positive `github_id` is explicitly provided, the invitation stays bound to that numeric ID
and the email is only the delivery destination; `github_login` may accompany that ID as an optional
display hint. JSON accepts `github_id` only when omitted, null, or a positive integer; booleans,
strings, floats, zero, negative values, and overflow are rejected. `github_login` requires an
explicit ID.

```json
{"email":"invitee@example.com"}
```

For an email-only invitation, the address is the delivery destination and redemption match, not
identity proof by itself. After the invitee signs in through GitHub, the app checks the
authenticated account's email records and requires an exact match marked `verified`. GitHub's
authenticated email-list endpoint returns verification status and requires the `user:email` OAuth
scope for OAuth app tokens. If the address is absent or unverified, or the GitHub lookup fails, the
email-only invitation is rejected. A public profile email or a matching GitHub username is not a
substitute. An invitation created with an explicit `github_id` instead checks that numeric account
ID at redemption; its delivery address is not an additional identity factor.

Address comparison uses ASCII case-folding only. The app does not fold Gmail dots or plus tags, so
provider-specific aliases do not create an invitation match. After a verified email-only match,
the app binds the invitation to that OAuth account's numeric GitHub ID. The invitation remains
single-use and expiring; ordinary TOTP enrollment or verification and the existing per-user
ownership checks still apply. The generated code is sent by email and is never returned in this
endpoint's response.
The response's `submission_status: "smtp_accepted"` means only that SMTP accepted the message for
processing; it is not proof of mailbox delivery or reading. The separate
`POST /api/v1/auth/invites` endpoint continues to create a numeric-ID-bound code for private
sharing.

R-ASTRA-113 is **In progress** overall. Its reviewed release is deployed at schema 12 on pushed
revision `4cc5c8502ec93c57947958ee07f891b45e98d870`, following the local gate (`796` Python tests)
and schema-12 package smoke. Three invitations were sent by invoking the production service
functions over operator SSH; Resend reported all three delivered. Three personal-Gmail messages
are recorded in the same invitation thread: the original notice and two later support replies.
These operations did not exercise the
authenticated HTTP/browser invitation route.
One recipient mailbox classified its invitation as Spam; placement/read status for the other
mailboxes is unavailable. Recipient feedback and sanitized logs support one invitee's OAuth
redemption, TOTP enrollment, and private API activity, but not browser-rendered UI. Another
invitation was rejected while still valid; verified-email mismatch is inferred, not confirmed.
See the [MVP plan](../../MVP-PLAN.md) for deployment and send evidence.
For the corresponding operator workflow, see [getting started](../operations/getting-started.md#invitation-email-and-host-compose-update).
GitHub's [authenticated email-list endpoint](https://docs.github.com/en/rest/users/emails#list-email-addresses-for-the-authenticated-user)
documents the `user:email` requirement and the returned `verified` flag.

### R-ASTRA-118 mismatch recovery

For an active, unused, unexpired email-bound invitation, R-ASTRA-118 adds the distinct
`invitation_email_mismatch` result when the authenticated GitHub account's verified-email hashes
do not contain the invitation's exact email hash. This preserves the repository's existing atomic
behavior: the invitation remains unused, and the failed attempt creates no user or session.
Numeric-ID invitations and used/expired invitation errors retain their existing generic responses.

GitHub callback errors redirect with `303` only when the request positively accepts `text/html`.
`invitation_email_mismatch` and `invitation_rejected` map to fixed
`/invite?error=invitation_email_mismatch` and `/invite?error=invitation_rejected` destinations;
`oauth_rejected` and `authentication_unavailable` map to
`/sign-in?error=oauth_rejected` and `/sign-in?error=authentication_unavailable`. Only the OAuth
transaction cookie is cleared; active sessions are preserved. JSON callers retain their existing
error status and response shape; malformed callback query requests from JSON clients remain `422`.
The required code/state fields and their OpenAPI length constraints are unchanged.

The UI shows only whitelisted error codes. For a mismatch, it links to the exact
[GitHub email settings](https://github.com/settings/emails), lets the user enter the original
invitation code again, and tells a user who just changed GitHub's verified email to retry in the
same browser instead of refreshing the OAuth callback. Existing members can use normal sign-in.
Focused independent backend/browser QA and the full local gate passed. The production release is
deployed at schema 12 on revision `da2764e8477698fa7d686be93a4711e35478e802`. Public probes and a
dummy-callback browser check confirmed the recovery-page behavior, not a real invitee's OAuth
identity or sign-in. See the [MVP plan](../../MVP-PLAN.md) for receipts and limitations.

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
transaction. By default, an unexpired transaction is reused only when the session, factor generation,
and origin match, preserving its original expiry. A different origin cannot silently replace it. Send
`{"replace": true}` only when an explicit rotation is intended; that invalidates the previous pending
QR/setup key and returns new setup material. The response includes an `otpauth_uri` value for the
page to render a local QR code; the UI also offers manual-key entry and no generic URI-handler link.
Submit the authenticator's current code to `/api/v1/auth/totp/enroll/finish`; the response returns
recovery codes exactly once. Recovery codes are single-use and must be kept offline. `/recover`
accepts one unused code and
returns a restricted session that can replace the factor; it does not grant a normal workspace
session. `/step-up` records fresh proof for administrator backup and HTTP restore operations.
Production GitHub-auth mode rejects WebAuthn registration; the one-time passkey migration route from
an earlier release is historical and is not part of the current flow.

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
