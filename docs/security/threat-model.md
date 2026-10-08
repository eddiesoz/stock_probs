---
title: "Threat model"
description: "Threats and controls for loopback HTTP, untrusted requests, Yahoo market/news data, SQLite state, exports, and managed backup artifacts."
---

# Threat model

Signal Ledger has two supported security modes. Development may use a local bootstrap account on
loopback; production is an invite-only multi-user deployment behind a Cloudflare Tunnel. The
production image binds the app to the host loopback interface, uses GitHub's authorization-code
flow plus a six-digit TOTP authenticator app, and keeps SQLite on a private persistent volume. The
authenticator code is the sole application second factor. The deployed schema-10 migration revokes
stored passkeys and old passkey sessions; the application does not create or accept WebAuthn
credentials. The recovery rehearsal has
passed for its declared scope, and E58 has applied the provider-refreshed `public_invited` boundary
through the Cloudflare Tunnel after deleting the owner-canary Access app and updating the exposure
guard. Authenticated owner API and saved-forecast retrieval are evidenced by read-only server logs,
while browser-rendered owner content remains **Unavailable**. E56 passes the four two-client
isolation scenarios locally, but remote two-user behavior and browser UI remain **Unavailable**.
The live IAB showed the unauthenticated sign-in page but no owner UI session. E59 retired the
legacy host; functional owner/invited-user acceptance remains pending. E60 records the historical
current-machine browser passkey/sign-out limitation; E61 records the locally accepted logout and
mode-aware passkey repair with independent QA, and E62 records the passing full local gate. E63
records its then-current schema-8 image deployment and public probes; E64 records Astra's no-P1/P2 live read-only
review. R-ASTRA-103 established the deployed schema-10 authenticator-only baseline. R-ASTRA-110 at
pushed revision `566baab14c298fb52b5edb3138d64cd3e9123311`, schema 10, is the historical deployment
preceding R-ASTRA-111; it includes the R-ASTRA-107 key-reuse repair. The R-ASTRA-111 schema-11
baseline was at pushed revision `82f2dfed76f6aee2a1ef9c3decd675ed72d89fed`, before the later
R-ASTRA-113 deployment. The user
later reported successful Firefox sign-in,
and production database inspection confirms one enrolled TOTP factor. The report is attributed;
authenticated owner-browser code verification and workspace retrieval remain **Unavailable** in
agent-observed evidence.
`R-ASTRA-111` advances the deployed schema to 11 and clears OAuth transaction rows before adding a
caller-key hash; it preserves user, session, and research records. The deployment verified a
schema-10 pre-migration backup and installed production Compose ingress attribution through the
existing reviewed host-Compose updater. The local gate, scoped Sol security review,
independent Luna Docker bridge regression, deployment, and bounded public boundary probes passed
for their declared scopes; the initial local-gate failure on four stale schema-10 expectations
remains historical. OAuth transactions already in progress had to be restarted after migration.
SMTP was absent during the R-ASTRA-111 deployment checks; that point-in-time state was superseded
by R-ASTRA-112, which enabled production SMTP and verified delivery of an owner-bound invitation
to Gmail's Spam folder; inbox placement was not achieved for this test. Authenticated
email-endpoint/browser acceptance and new-user onboarding remain unverified. See the
[R-ASTRA-112 evidence](../../MVP-PLAN.md).

`R-ASTRA-113` is **In progress** overall for email-only invitation identity binding. In the local
implementation, the recipient email is a delivery destination. For email-only invitations, it
also supplies the redemption match: a public profile email or username is not proof of identity.
During redemption, query the
authenticated GitHub account's email list with the `user:email` scope and require an exact address
marked verified. Compare using ASCII case-folding only, without provider-specific dot or plus-tag
folding. Reject unverified or mismatched addresses and fail closed when GitHub's email lookup is
unavailable. After a match, bind the invitation to the OAuth account's numeric GitHub ID. If an
administrator explicitly supplies a positive `github_id`, the invitation stays ID-bound and email
is only the delivery destination; `github_login` is an optional display hint for that ID-bound
case. In both cases, preserve the existing TOTP and per-user ownership checks. The single-use code
goes in the email and must not appear in the API response; the existing numeric-ID code-invitation
flow remains available. See the
[email invitation contract](../reference/api.md#email-invitation-contract) and the official
[GitHub authenticated email-list endpoint](https://docs.github.com/en/rest/users/emails#list-email-addresses-for-the-authenticated-user).
The implementation and declared local QA scope passed, including schema-12 package smoke and the
final local gate (`796` Python tests). The reviewed release is deployed at schema 12 on pushed
revision `4cc5c8502ec93c57947958ee07f891b45e98d870`. Three invitations were submitted by direct
production service-function calls over operator SSH, and Resend showed all three delivered; two
follow-up messages were sent from the user's Gmail in the same invitation thread. No authenticated
HTTP/browser send was exercised. One
recipient mailbox classified its invitation as Spam; other mailbox placement/read status is
unavailable. For one invitee, recipient feedback and sanitized logs support OAuth redemption, TOTP
enrollment, and private API activity, but not browser-rendered UI. Another valid invitation was
rejected; verified-email mismatch remains an inference because the authenticated GitHub email list
was not observed. The earlier R-ASTRA-112 Gmail Spam delivery remains a separate historical check.

`R-ASTRA-118` is deployed at schema 12 on revision `da2764e8477698fa7d686be93a4711e35478e802`.
It adds a distinct mismatch result for an active, unused, unexpired email-bound
invitation while preserving the repository's existing atomic no-consume behavior. No user/session
is created for that mismatch; numeric-ID, used, and expired cases keep generic errors. HTML callback
redirects require positive `text/html` acceptance and use fixed local destinations. JSON status/body
behavior remains unchanged, including `422` for malformed callback query requests from JSON clients.
Only the OAuth transaction cookie is cleared; active sessions are preserved. The UI exposes only
whitelisted error codes and provides a verified-email retry route. Focused independent QA and the
full local gate passed; production probes and a dummy-callback browser check confirmed the recovery
guidance. They do not verify a real invitee's authenticated GitHub email or sign-in. A reported
rejection while an invitation remained valid is consistent with a verified-email mismatch, but the
account's authenticated GitHub email list was not observed; the cause remains an inference. See the
[MVP plan](../../MVP-PLAN.md) for the bounded deployment and mail receipts.

The earlier private
clean-main image is revision
`2de5e9f199cd145707f95e81d389c40b2ab3c32a`, archive SHA-256
`b856795831b6fb46e94e330370e003843b266ad85f22e8d95ef7624536b2ac48`, and image ID
`sha256:ae7991f35a2093b145245f8037a3227981b09051805467870f759c0752bbfc3d`; a fixed typed-MCP
retry plan `2d8b0fe91ed01b55f1625c27edcc620b` passed after the first plan failed transiently with
`remote_operation_failed`. Deploy returned deployed/readiness schema `8`; status reported the
current revision, `failed: null`, `loopback_only: true`, and pre-deploy backup
`pre-deploy-2de5e9f199cd1457-751c7459.spbackup`. A later
privacy review found a P2 caused by the configured owner email reaching an embedded process
argument. The private-file repair is complete, scoped QA passed, and Astra's final source review
reported no P1/P2 after its `409` guidance finding was repaired. An earlier tab 13 showed signed in
as `jtmb` before the prior deployment, but that observation is historical. The final live
in-app-browser reload with an expired session showed `Sign in first` and `Open sign in` and hid
`Create passkey`; opening sign-in and continuing with GitHub returned to
`/passkey?mode=enroll&next=/overview`, showed `Signed in as jtmb`, and showed `Create passkey`.
No ceremony was completed in this browser tab. Operator read-only SQLite evidence on `2026-09-28`
(exact query UTC not captured) found `quick_check` `ok`, zero foreign-key violations, owner id `1`
claimed to the configured GitHub account as active admin, one nonrevoked passkey, one current
passkey-verified session, and mappings of 13 events, 13 runs, 20 results, 0 outcomes, 6 holdings,
and 3 watchlist items. This proves enrollment, a completed passkey verification on another computer,
and persisted owner mappings, but not browser-rendered UI retrieval. A fresh production tab hit
Cloudflare Access login with no transferable session. Later read-only Docker access logs observed
authenticated owner API retrieval and saved-forecast access after the passkey session; `/overview`,
portfolio, watchlist, history, and saved-forecast requests returned `200`. The prior origin-navigation repair loaded the
canary HTML page instead of the prior `origin_rejected` JSON response; that E49 result does not
establish current authentication or saved-data access. A subsequent source-reviewed fix at
commit `a1d868287a729c75d9b8628f612a856db132374a` handles stale/expired provisional sessions that
returned `authenticated:false` and left the passkey page at `Checking your session`; local
build/typecheck, `28` frontend tests, and browser `4/4` passed, and the fix is included in the final
image. Owner enrollment is operator-verified and authenticated owner API/saved-forecast retrieval is
confirmed by E55. Browser-rendered content remains **Unavailable**. E56 passes the four local
two-client isolation scenarios; remote two-user behavior remains **Unavailable**, and E57 records the
passing full local gate after its initial comment-audit failure. E58 records the live public boundary
and unauthenticated sign-in probes; E59 records legacy-host retirement, E60 records the current-
machine browser passkey limitation, E61-E62 record the locally accepted repair and gate, E63 records
the then-current schema-8 deployment, and E64 records Astra's no-P1/P2 live read-only review. Functional
invited-user acceptance remains pending; Terraform/image, IPv6, old-VM, browser owner-workspace,
live second-user, and independently completed passkey checks remain **Unavailable**.

At the time of E63, its image was main revision `27e0d2f5916d4297e10d259aa4776055a78faeaa`, archive SHA-256
`78f2e44ecfbe2021a61a0ecd71414065024c246eb46ca9506b33c20f13b07ad1`, and image ID
`sha256:ecd41e1b65eb76b424cff830a6150db2282d326cfb18b3b6eaa37b07f83c4bc0`; the typed-MCP retry
plan passed, status is schema `8`, `failed: null`, loopback-only, and the pre-deploy backup is
`pre-deploy-27e0d2f5916d4297-39376b8d.spbackup`. Public health/auth/sign-in probes returned
`200`/`200`/`401`/`303` with `no-store`/`DYNAMIC`. A post-deploy read-only SQLite check reported
`quick_check=ok`, zero foreign-key violations, 13 search events, 13 forecast runs, 20 forecast
results, 6 holdings, 3 watchlist items, 1 passkey, and 1 user. The IAB passkey remained unavailable;
corrected sign-out returned `/sign-in` with no account controls twice.

## R-ASTRA-103 boundary status

The authenticator-only implementation advances the additive auth schema to schema 10 and retires
passkeys. The deployed migration revokes stored passkeys and old passkey sessions, and the
application does not create or accept WebAuthn credentials. After fresh GitHub OAuth, an account without a TOTP factor
goes directly to `/authenticator?mode=enroll`; `/passkey` redirects to that flow. Existing TOTP
accounts remain protected by their current TOTP or recovery-code replacement flow. Enrollment is
short-lived and origin-bound, recovery codes are hashed and single-use, and backup/restore promotion
requires fresh TOTP proof, a verified backup, matching account-security state, maintenance
serialization, and session revocation.

Independent QA passed `64` authentication/repository/list checks, `123` API checks, `61` backup/CLI
checks, `10` desktop/mobile-emulated auth-flow cases, `27` frontend checks, Ruff, and diff checks.
Fresh schema-10 creation and schema-9-to-10 migration checks passed; the `61` backup/CLI check set
passed. No schema-10 backup/restore rehearsal is claimed. The owner API flow
returned `303` to `/authenticator?mode=enroll`, required TOTP for protected access, denied private
history without a session, and returned `403` for WebAuthn. Existing TOTP factor replacement remained
guarded. Astra's independent medium source security review reported no P1/P2 finding.

The current local `R-ASTRA-103` gate **Passed** for its declared scope. Receipt
`test-results/local-gates/R-ASTRA-103-20260928T235350Z/evidence.json` reports `707` Python tests
passed, `4` live tests deselected, `85.25%` coverage, frontend build/typecheck and `27` frontend
tests, and documentation coverage. The older schema-9 backup remains an offline recovery artifact
only. Owner TOTP enrollment, authenticated workspace retrieval, physical mobile, and second-user
acceptance remain **Unavailable**.

The exact remote `main` revision `9cc0751da459e911d285b14e0d57a29320a9f366` matched before
publication. GitHub Release `signal-ledger-9cc0751da459e911d285b14e0d57a29320a9f366` has archive
SHA-256 `d60da545be26a050e305e13d2e8db219a253a0668b32f13f532148069bde188e`; publisher re-download
passed. The Linux/amd64 image is `103143811` bytes with ID
`sha256:3e5f242573044114797b66447e3a8139ed35ca7decc387e6f1ab3ef62db486ff`. Restricted MCP plan
`16c6655376c3b80569694ce400a2381c` passed; deploy returned readiness schema `10`, and status
reported backup `pre-deploy-9cc0751da459e911-20833573.spbackup`,
`deployed_at=2026-09-29T00:21:06.828904+00:00`, `failed: null`, and `loopback_only: true`.
Live HTTPS at `2026-09-29T00:22:18Z`–`00:22:19Z` returned health `200`, anonymous history `401`,
overview `303` to sign-in, and `no-store`/`DYNAMIC` responses. `/passkey?mode=verify` returned
`303` to `/authenticator?mode=enroll&next=%2Foverview`. The IAB showed `Sign in first` for the
revoked old session; fresh GitHub sign-in as `jtmb` rendered the authenticator setup page without
a WebAuthn prompt. Owner TOTP enrollment and workspace content remain **Unavailable**.

## R-ASTRA-107 enrollment-key lifecycle (deployed through R-ASTRA-110)

The current repair keeps an unexpired pending enrollment bound to the same session, factor generation,
and origin. A repeated default start returns that pending setup with its original expiry; it does not
silently mint a new QR. `{"replace": true}` is the explicit rotation path and invalidates the previous
pending setup. A different origin cannot overwrite the row, and concurrent starts leave at most one
origin-bound pending row. The UI displays the expiry, disables expired QR/code use, and offers an
explicit replacement action after a cross-session conflict.

Production observation at `2026-10-01T15:03:02Z` and `15:04:39Z` returned `200` for starts and `403`
at `15:05:51Z` and `15:06:10Z` for finishes; a pending row from the second start remained and server
NTP was synced. These pre-deployment observations do not establish enrollment or code acceptance.
If a QR or setup key appears in a photo,
treat it as exposed and rotate after deployment by generating a fresh key and replacing the old Signal
Ledger entry in Passwords. Physical iOS verification remains **Unavailable**.

### Historical R-ASTRA-102 deployment evidence

The following deployment details are historical R-ASTRA-102 evidence and are not current deployment
or auth acceptance. They describe the then-deployed schema-9 release; R-ASTRA-110 is the current
schema-10 deployment. Post-deploy evidence records revision
`403cd79b08f90b49603cec3152b4f1e07b91d730` pushed with exact `origin/main` matching, release archive
SHA-256 `811229e8355679f08d1a0857426cbec3526cee492417e50a5f9fe760e98894f4`, verified publisher
re-download, and Linux/amd64 image ID
`sha256:76283822fb01ba19ead18037d3396b81db5c804e41d0203dfbaae04c3c3abb8f` (`103146866` bytes).
Restricted MCP plan `5b757cb6e2cb2b8d97b85613a4b5504b` deployed it; inspect/status reported schema
`9`, `ready`, `loopback_only: true`, verified pre-deploy backup
`pre-deploy-403cd79b08f90b49-3055603f.spbackup`, and no failed release was reported after the successful deploy. Before that successful
retry, the first official MCP `plan_deploy` call for the same revision/archive/image returned
bounded `remote_operation_failed`; the remote remained on its prior healthy schema-8 image. The
cause was not established. Fixed structured-helper plan `5b757cb6e2cb2b8d97b85613a4b5504b` then
succeeded and the subsequent official MCP deploy passed. Live Cloudflare HTTP at
`20:29:04Z` returned health `200`, auth status `200`, `/authenticator` `200`, `/overview` `303`,
and `/api/v1/history` `401`, all `no-store`/`DYNAMIC`. The IAB reached the one-time legacy-passkey
migration route for owner `jtmb`; the button remained `Waiting for passkey…`, reloading cancelled
it, and sign-out returned to `/sign-in`. Owner TOTP enrollment, live mobile sign-in, authenticated-
browser saved-data access, and physical authenticator-device verification remain **Unavailable**.
The existing schema-8 passkey deployment evidence above is historical and must not be used as TOTP
acceptance evidence.

The model protects account identity, owner-scoped research history, forecast provenance, local
filesystem locations, backup authenticity, and process availability from accidental corruption and
untrusted browser, provider, request, and deployment input. A Cloudflare Tunnel supplies ingress;
it does not make the application a brokerage, order router, real-time feed, or market-depth
service.

## Trust boundaries and controls

| Boundary or threat | Control |
| --- | --- |
| Remote access or browser cross-origin traffic | Loopback-only environment configuration, explicit warning flag for unsupported broader CLI binds, host/origin checks, strict response headers, and no permissive cross-origin API policy. |
| Forged Host, forwarded-host, or path authority | Production requires one exact HTTPS public origin. Host parsing rejects URL syntax, duplicate or non-ASCII authorities, and unexpected ports; forwarded headers are accepted only from the local trusted proxy. Path decisions use the ASGI scope rather than an attacker-controlled URL reconstruction. |
| OAuth callback substitution or login CSRF | GitHub numeric account IDs are the stable identity; the authorization-code flow uses a short-lived server-side state value and PKCE, checks the exact callback/origin, and never accepts a client-supplied identity. |
| Invitation theft or account takeover | Invitations resolve a GitHub account, expire, are single-use, and are redeemed before authenticator enrollment. Production rejects development bootstrap credentials. Every invited account must confirm a six-digit TOTP code from an authenticator app. The deployed schema-10 migration revokes passkeys; they cannot authorize enrollment or sign-in after that migration. |
| Authenticator theft, replay, or brute force | TOTP secrets are encrypted at rest, enrollment is short-lived and origin-bound, accepted time steps are monotonic, attempts are reserved under the SQLite write lock before verification, and failed attempts are throttled. Recovery codes are high-entropy, hashed, single-use, and reveal no replacement session beyond factor replacement. |
| Pending setup overwrite or exposed enrollment QR | Pending setup material is encrypted at rest, expires after the bounded enrollment window, and is bound to the current factor generation and originating session. Default starts reuse the same-origin pending row and expiry; explicit replacement rotates it, while a different origin fails closed. The UI shows expiry and removes expired QR/code actions. A QR or setup key visible in a photo must be treated as exposed and replaced after deployment. |
| Session theft, fixation, or replay | Sessions are opaque server-side records addressed by hashed tokens, with idle and absolute expiry, revocation, host-only `Secure`/`HttpOnly` cookies, CSRF tokens for mutations, and no browser storage for credentials. TOTP verification is bound to the active factor generation and fresh step-up markers are short-lived. |
| Cross-user IDOR or legacy-data disclosure | Forecasts, events, results, outcomes, reconstructions, exports, holdings, watchlists, and account operations derive the owner from the session. Legacy rows attach to one reserved owner claim; a new user cannot claim or query them by changing an ID. |
| Privileged backup or restore abuse | Backup status requires an administrator. Backup creation and every HTTP restore request, including verify-only, require an administrator and TOTP proof no older than 300 seconds. Restore promotion also requires a verified pre-restore backup, matching account-security state, maintenance-mode serialization, and revocation of all sessions. |
| Redirect consent changing the approved destination | The user-facing contract requires fresh approval for the exact redirect URL. E199 found a selected native source path that followed a changed public redirect without renewed exact-destination approval. E203 independently **Failed** its ordering scope; parent review corrected the mock's omission of the shared atomic eight-tool counter but did not close the hop/repeat race. E209 later **Passed** selected runtime/helper/MockTransport and guard checks for serialized message snapshots and exact-URL approval; the retained circular mock timeout is diagnostic-only and native integration remains unavailable. Parent source-pin review passed. No live external request, native integration, or private-network SSRF bypass is established. |
| Provider egress after session, role, consent, or lease revocation | E204's independent synthetic real-manager/API-stream-wrapper check **Failed** five paths: the upstream stub received a prompt and, for four API-key routes, a synthetic credential after authorization became false. E205's separate actual-ASGI body-chunk tests **Passed** two synthetic cases because middleware buffers before route dispatch; revoked sessions returned 404 and the fake manager was not called. E206–E208 record synthetic transport callback checks, fixture adaptation, and parent source review; E210 independently **Passed** selected synthetic manager/provider, DNS/TLS, authorization, and context-isolation batches, including zero request writes after mocked revocation during DNS/TLS. These later scoped passes preserve rather than erase E204. No live provider/network, customer-data incident, native runtime, or production exploitability is established; complete transport/runtime acceptance remains open. |
| Deployment MCP command injection or supply-chain substitution | The R-ASTRA-120 deployment MCP candidate exposes eight typed operations: `inspect`, `plan_deploy`, `deploy`, `status`, `rollback`, `refresh_operator_access(operator_ipv4_cidr)`, `rehearse_pr_pair`, and `set_assistant_rollout`. The current task advertised all eight names; read-only `inspect` and `status` passed against the unchanged production baseline (E329). Metadata does not prove all operations executed, and no mutating invocation is inferred. The earlier six-tool snapshot remains historical. The fixed SSH helper accepts reviewed release identities and rejects arbitrary commands, paths, URLs, Compose edits, registry names, tags, and Docker-socket access. GHCR is an explicit compatibility transport, not the default. |
| Mutable image or remote-build drift | The local publisher builds a Linux `amd64` image, scans and publishes a revision-named GitHub Release asset derived from the reviewed revision, treats that asset as immutable during its workflow, and verifies the downloaded archive SHA-256, image ID, platform, and revision. GitHub does not enforce asset immutability. The Linode loads only that verified asset and never builds source on the VM; optional GHCR plans remain digest-pinned. |
| Terraform source or infrastructure drift | The Linode plan and apply both use a fixed external source gate that requires a clean checkout, exact `origin/main`, the reviewed revision, fixed repository, and checksums for the host files. The operator-access refresh also uses fixed private external state and rejects any plan outside the imported firewall's `ssh-operator` TCP port-22 CIDR change. The imported firewall has `prevent_destroy`; no application port is opened by Terraform. |
| Public-ingress or cache bypass | The app port is published only on `127.0.0.1`; Cloudflare starts closed with a terminal `404`, then E58 applies the `public_invited` boundary for the exact hostname after deleting the owner-canary Access app and updating the exposure guard. The managed cache-settings ruleset bypasses shared and browser caching. `/overview` returned `303` to local sign-in, `/api/v1/history` returned `401`, and `/api/v1/auth/status` returned `200`; each was `no-store`/`DYNAMIC`, and direct port `8000` was unreachable. The live IAB showed sign-in with no owner UI session; proxy trust is local-only. |
| Host compromise or lost recovery channel | Use a restricted deployment account with a forced command, public-key-only SSH, no forwarding or TTY, least-privilege sudo, private state directories, and an operator-managed tunnel token. Linode VM Backups are enabled and the repaired disposable recovery rehearsal passed its declared scope; this release has no independent encrypted off-server backup. |
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

## R-ASTRA-120 assistant candidate boundary

The assistant source is a candidate on the shared R-ASTRA-120 branch. E256's read-only production
inspect recorded revision `da2764e8477698fa7d686be93a4711e35478e802`, image
`sha256:d3e21ae9de800f0151c1eba74fb3d16423e1171985c33ea03057acbfe2278ec1`, schema 12 ready,
`failed=null`, and loopback-only. E301 later reconfirmed those facts; E329's current-task read-only
inspect/status pair reconfirmed them again. Neither E301 nor E329 returned assistant rollout mode
or user/browser access. Earlier rollout-disabled evidence is historical, and current rollout mode
remains **Unavailable**.
The source boundary uses same-origin authenticated
application routes, session-owned tool calls, typed tools, bounded request/storage limits, private
loopback callbacks, and a worker UID separate from the FastAPI process. These are source/design
observations, not independent security acceptance.

Earlier candidate-image disposable native checks passed their local functional and shutdown scopes
(E167/E168), with independent terminal, source-binding and exact-cleanup review (E171). Two owners
received matching model/MCP results; native search and guarded public fetch completed; cross-owner
and forged MCP access returned 404; deleting conversations erased their worker cache markers. An
active-search shutdown left its pending query unapproved and unexecuted, cancelled the turn,
preserved app readiness and saved records, and disabled six assistant endpoints. Observed process
separation, read-only root and no-new-privileges checks belong to these local runs. They do not
verify production Docker security options or the combined 1 GB Linode resource gate. Worker
readiness samples included starting and unavailable states; uninterrupted availability is not
claimed.

The later corrected-catalog image failed its two-owner native completion check (E520): one owner
encountered worker unavailability before a model event, and the other completed summary, search
and an approved public fetch but timed out without an answer. App readiness and exact fixture
cleanup passed; the cause remains unproven. That image does not establish current runtime or
resource acceptance. A subsequent WebFetch confirmation repair now binds affirmative approval
to refreshed, canonical current page context on both client and server (E522/E523). Independent
backend checks and focused desktop/emulated-mobile checks passed that scoped repair (E531).
The incremental worker-cache purge repair passed selected independent checks, followed by its
explicit socket-cleanup assertion (E526/E529). Open-panel worker/policy recovery remains in progress
(E528); these results do not establish current full-application acceptance.
Current-image shutdown, strict accessibility, combined 1 GB resources and PR-bound rollback remain
open; no production promotion is authorized by these source or local-test results.

The current task advertised eight deployment MCP operations. E329 is the latest receipt-backed
read-only production `inspect`/`status` pair; both returned `status=ok`, the revision and image above, schema 12,
`failed=null`, and loopback-only, while inspect returned `ready`. The receipt does not expose
rollout, RAM, billing, or user/browser access, so it is not rollout or authenticated UI verification.
No promotion or production mutation occurred in that check. E330's bounded pinned-V2/current-upstream
public-source audit did not reveal the eligibility clause behind E322's HTTP 403; its cause remains
unproven, and no live provider request was made. Current helper source
requires no-new-privileges and a pinned migration/hash pair; their source and selected tests do not
replace a PR-bound live recovery rehearsal. The existing 1 GB server and backups remain under the
US$15 monthly total cap, including tax; the proposed resize was not applied.

The maintained model catalog supplies the known-model confidentiality exclusions. E195's
independent local source/regression/lint scope **Passed**: direct Zen parsing and native
Console/manager plus compatible custom routes bind an exclusion to the upstream native model
identity and exact Zen route before registration or use. Administrator review and user consent
cannot override an excluded model. An ambiguous route on the exact Zen host fails closed; a
similarly named unrelated host is not globally banned. The independent review found no remaining
reachable bypass in the inspected paths. This synthetic/local scope did not run live upstream
discovery, native Console, external network/data flow, browser, Docker, or production checks. E192's
initial P2 finding remains preserved in the evidence ledger; E195 is not a full security review.

E199's independent native WebFetch/search source review **Failed** for its selected scope with P2
SG-01. After the user approves the exact displayed URL, the native guard follows a validated public
redirect to a changed exact URL without renewed approval; the application accounts for approval on
the original URL and does not require the final URL to match it, although the confirmation card
promises approval applies only to the exact URL shown. Static checks for per-hop DNS resolution,
public-address filtering, pinned addresses, allowed schemes/ports, HTTPS downgrade rejection, and
bounded redirects **Passed** in the inspected paths. No private-network SSRF bypass is claimed.
E202 was partial builder validation; E203's independent review **Failed** on a permission/message
ordering race, a 48/49 guard-fixture result, and 57 versus 40 static test inventory. Parent review
confirmed the mock omitted the shared atomic eight-tool counter; that correction did not close the
hop/repeat finding. E209 later **Passed** 43 runtime tests, 23 build-helper tests, 49 mocked Bun guard
cases, and exact 49+8=57 inventory for its selected local scope. The old circular delayed-message
mock timed out as a diagnostic-only fixture failure; native integration remains **Unavailable**
because the upstream checkout was absent. Parent source review matched all seven pins and removed
only the temporary Bun. No native permission-store, browser, live network, production, or release
acceptance is inferred.

E204's independent synthetic provider-egress review **Failed** five real-manager/stream-wrapper
paths after authorization became false: the stubbed upstream received a synthetic prompt and, for
the four API-key paths, a synthetic key. E205 separately passed two actual FastAPI middleware
body-chunk revocation cases because middleware buffers before route dispatch. E206–E208 record a
builder transport follow-up, a frozen-runtime fixture-only 99-test pass, and parent review of the
async callback contract. E210's independent serial synthetic batches passed 9 transport, 17 manager
authorization, 12 network, 80 transport-boundary, 147 provider, 88 protocol, 11 catalog, five API-
auth, and one permission-reply rollback tests; a concurrent task-local context diagnostic and
Ruff/format also passed. The mocked DNS/TLS cases verify the selected callback/write boundary only.
E205/E206–E210 do not erase the original E204 failure or establish real provider contact behavior.
No real provider/network, customer-data incident, or production exploitability is inferred.

The E211 Linux/amd64 image build **Passed** for its declared build and source/stage binding scope
(147 inputs, 52 served files); its generated native-integration/OAuth fields are builder output, with
raw subprocess summaries suppressed. E212's network-none verifier returned `valid=false` because
the supervisor's fixed guard and manifest hashes did not match that image's receipt. It correctly
rejected worker acceptance; the app and worker were not started, and owned-container/config cleanup
passed. E213's builder-only pin repair passed 14 focused tests plus lint/format. E216 independently
passed the selected supervisor source/test/lint/security/format scope with 42 stable bindings. E215
built a fresh image from 147 inputs with all 52 served files matching. E218's one-shot receipt
verifier passed on that exact image under network-none, read-only root, zero capabilities,
no-new-privileges, and UID/GID 10001; neither the app nor worker was started. Parent review matched
the allowlisted result facts, log digest and 42 pins, but did not verify exact owned-container cleanup
beyond the `--rm` terminal result. E219 parent review passed the image build/source bindings. E220's
separate synthetic wire attempt **Failed** before container start when the runner expected four
`.Mounts` entries and Docker reported two read-only binds with tmpfs separately in `HostConfig.Tmpfs`;
the tmpfs settings matched and exact cleanup passed. This is a setup failure, not native behavior;
E221's ignored runner mount-guard repair passed six Docker-free metadata tests plus selected
lint/security/format checks. E222's first same-image wire recheck **Failed** its aggregate despite a
zero-exit child because protocol facts were rejected; E223 showed all ten required assertions true,
11 authenticated listed tools, and a null `/mcp` readiness count. E226's ignored parser repair passed
22 Docker-free tests and selected checks, but E227's second aggregate **Failed**. E231 isolated two
false generic Google body assertions; the parent diagnosis identifies a likely protocol-shape
mismatch for Google's model-in-path and `streamGenerateContent?alt=sse` form. Raw request-body
contents were not captured. E235's ignored-runner-only repair passed independent Docker-free
tests, but the native aggregate still failed on its schema-row projection. No tracked probe edit
or wire/provider acceptance is claimed.

E224's current-image native functional attempt **Failed** at the seed command before model calls and
initial cleanup failed; E225 later passed exact owned cleanup. E228's ignored driver-guard repair
passed 14 Docker-free tests and selected lint/format, but E230's later native functional run
**Failed** after the output projection rejected malformed worker status. App UID 10001 and worker
UID 10002 were observed, source/stage bindings matched, and exact cleanup passed; the underlying
worker failure remains **Unproven**. Native functional and kill acceptance remain open. E229's
iframe prototype invocation **Failed** at setup because the preserved old spec was discovered; its
new tests were skipped and no raw axe ran. E232's later iframe prototype failed its desktop-Light
contrast/parity criteria. E233's failure-only worker-status projection repair leaves success
requirements intact. E234's same-image two-owner run failed after owner 1 received native search
sources but timed out before fetch approval or an answer; resource or provider causation remains
unproven. Exact cleanup passed. E236's unfiltered desktop/mobile diagnostic did not clear all
raw-axe states, so no UI repair or accessibility acceptance is inferred. E212's old-image rejection
remains preserved. E217 is a parent
source/receipt/log consistency review of E210, without test rerun. E214's checksum-pinned
compile-source review confirmed `--smol`, minification, and bytecode, but ran no compile/runtime and
provides no memory measurement. E237–E239 subsequently establish a narrow schema correction,
independent synthetic native wire pass, and parent current-source/cleanup review. The actual pinned
binary exercised the three provider protocol fixtures and MCP continuation under network-none,
read-only root, dropped capabilities, UID/GID 10001, and no-new-privileges. This is a local 1.5 GiB
fixture result; it does not establish live-provider reliability, resource acceptance on the 1 GB
Linode, or release readiness. E234's timeout and strict accessibility failure remain open.

The later E248 two-owner current-image run **Failed**: owner 0 answered; owner 1 timed out before
search or fetch. E249 independently confirmed that result and the pinned source/stage bindings and
owned cleanup. Its failure-only readiness and resource samples did not establish DNS, model,
provider, restart, or memory causation; the outer shell exit remains **Unavailable**. A separate
read-only runtime diagnosis found no safe existing attached bootstrap-stream timing seam, with no
source/test changes or real-provider call; exact task, artifact and time were not supplied. E250's
fixture-only UI diagnostic leaves strict mobile raw axe **Fail**. E251's builder-only frontend
checks do not establish source acceptance: E252 found the CSS-module disclaimer padding selector
was unbound, and E253 found a readiness styling/mobile font mismatch against the tested candidate.
E254's builder repair binds the disclaimer selector and passes scoped frontend/stage checks. E257's
readiness CSS follow-up and E258's parent source/stage review are recorded in the ledger; E258
passed only the source and served/export binding scope. E263's selected browser review passed its UI
test, served/export and cleanup checks, but strict raw axe remains **Fail** with one incomplete
contrast item in each of four snapshots. Enabled-Send keyboard traversal, numeric mobile target
geometry and rendered code-fence fidelity were not exercised. A private volatile anonymous
per-execution timing observer is authorized. E259's candidate review **Failed** because production
INFO logging was disabled and the extractor dropped stderr. E260's logging/capture repair passed
builder checks and parent source review; E261 independent QA **Failed** on invalid late-callback
coverage and owner validation order. E262 repaired those cases and passed focused tests plus
independent and parent reviews. E264 built a current Linux/amd64 image from 147 inputs with all 52
served/export files matched. E265's test-header repair passed builder test/comment audit/Ruff checks
and parent header-only review, but current canonical and fresh independent test checks remain
pending. E267 then ran the image in a native two-owner trial and **Failed**; E268 independently
verified its result and recorded cleanup. E271's host-only warning-parser tests and Ruff checks
**Passed** for that narrow scope: the parser avoids retaining raw warning lines, IDs, URLs, or
secrets, but this is not runtime acceptance and its files are excluded from the image. E272's later
run on the same image also **Failed**: owner 0 answered, while owner 1 reached search and an approved
IANA fetch but timed out without an answer. E273 independently passed result-integrity review only;
it did not rerun the trial or recheck cleanup. Anonymous rows A/B report workspace-summary,
first-sanitized-chunk, and end times for corresponding second provider requests; they have no owner
mapping, and later activity is unknown. No stall, provider HTTP success, or cause is established.
The empty captured warning list is limited to the parser's closed categories.
The 768 MiB sample is failure-diagnostic only and does not establish actual 1 GB acceptance. E269's
corrected static header/body inspection **Passed** after an initial stage/header-comparison failure;
no independent test rerun occurred (**Skipped/not run**) and remains pending. E274's initial UI
fixture attempt **Failed at setup** with no UI records; corrected rerun remains pending. Neither
preflight ran the candidate. The observer cannot expose identifiers, a public endpoint, raw data, or
altered deadlines. At that diagnostic checkpoint the current-tree canonical run was pending; E288
later passed the canonical local check profile, but its opt-in native OpenCode checks remained
skipped. Live provider, current-image shutdown, complete security, actual 1 GB resources, PR-bound
recovery, deployment and release acceptance remain open.

E275's independent host-only CPU receipt-boundary review **Passed** after preserving the initial
review failure for boolean-baseline acceptance and clamping a decreased usage counter to zero. The
repair uses checked baseline/monotonic counters and fixed aggregate projections; the review found no
raw CPU samples, paths, IDs, log lines, secrets, or environment values in those projections. This is
host-only evidence and does not establish live counter availability. E279's current-image two-owner
functional run **Failed** while recording CPU throttling; those local diagnostic values do not
establish the timeout cause or actual 1 GB resource acceptance.

E283 independently passed 34 focused progressive SSE/framing tests, including strict 1–16
ASCII-hex framing and truncation-prefix coverage. That scoped result does not establish native
provider-latency causation; the E279 image is stale for the source repair. E284's canonical local
gate **Failed** on two confirmation-flow cookie-helper `StopIteration` failures after HTTP 200.
E286 later independently passed the two selected flow tests and reproduced the expired-cookie
TestClient jar effect when the host clock was later than the fixture expiry. This supports a test
harness clock mismatch, not an application authentication defect, and does not rewrite E284's
aggregate. E285 applied only a candidate lockfile update to sharp 0.35.5 while leaving
`package.json` unchanged; E287 independently passed its Sharp/Next compatibility, 55 frontend
contracts, zero-finding audit, and 52-file served/export parity scope. This is not image/runtime
acceptance. The [GitHub advisory GHSA-wq5f-xc86-pv6w](https://github.com/advisories/GHSA-wq5f-xc86-pv6w)
reports sharp `<0.35.5` affected and `0.35.5` patched for its librsvg issue.

E288 is the latest complete canonical local check-profile **Pass**: native x86_64, 2,300 Python
passes, 3 opt-in skips, 4 deselected, 90 warnings, 85.230871% coverage, and 55 frontend checks;
documentation, frontend, and Python checks completed. The 1,048 bound files and 52 served/export
bindings were unchanged. Opt-in native OpenCode boundary/provider-wire checks remain separate
required gates. E289 passed ignored wrapper-preparation/static review only at that checkpoint; E292 later records the separate image build and E293 the failed native functional run. E290's read-only source review found current exact-source raw axe
**Unavailable** because the retained snapshots use a different source binding. The historical strict
raw axe result remains **Fail**; static token contrast calculations are not fresh rendered results,
and no speculative CSS/DOM repair or accessibility acceptance is inferred. No production change,
resize, or release is claimed. E291 records a current-image build attempt **Failed** on `ENOSPC`; its
build receipt and log were zero bytes, so no image build/runtime result is accepted. The exact plan
was restored and bounded task-owned disk cleanup **Passed** only; the retry was pending at that
checkpoint. E292 later passed image build identity and source/stage binding for 147 source inputs
and 52 served/export files, without runtime acceptance. E293 **Failed** its two-owner native
functional run after both turns timed out before an answer or tool activity; observed CPU throttling
does not establish cause, and the 768 MiB sample is not actual 1 GB evidence. Exact cleanup and
binding checks passed; no current-image kill ran. E294 failed synthetic geometry setup assertions;
E295 passed the corrected synthetic geometry scope but retained axe incompletes and does not
establish app accessibility or a source repair. Strict app axe remains **Fail**; E300 later recorded a targeted exact-current-stage strict raw axe
**Fail**, superseding E290's earlier source-binding **Unavailable** result for that narrow scope.
E296/E297 passed structure and visual review of the exact 13-page draft PDF only; PDF/UA and final
PR-bound guide acceptance are open. E298's independent timing source review **Failed** due missing
explicit nested proxy close, and the builder reported a pre-repair close-regression failure without
a saved receipt/hash/selector. E299's independent recheck and parent review **Passed** the repaired
source/cleanup scope only; anonymous bounded timings establish no latency cause or native provider
acceptance. E300's selected browser cases passed 4/4 while strict axe failed; mobile was emulated,
physical mobile and screen-reader acceptance are unavailable. E302 **Passed** a local Linux/amd64 image build and source/stage binding for image `sha256:9628a3cfddb86809efd44e3cd93829362db190702665eda488e69790f34b0bbc` (context `823777afc3ec3df12e0aa904463d17c9ed3dd6c57efd56cf0820735771e04bf6`): 147 source inputs and all 52 served/export files matched; owned cleanup passed. Parent binding review passed. This is build-only; E304 later records the native functional result for this image. E303 **Passed** manual contrast/visibility review of all 8 retained axe-incomplete nodes only: ratios were 6.4185–15.4826:1, full text was visible, each target had two unclipped in-viewport line rectangles and six sampled topmost-target hits, and no foreground obstruction was observed. Strict raw axe remains **Fail**; no cause, waiver, or full accessibility acceptance follows. See the plan for exact receipts. E304 independent native functional acceptance on the E302 image **Failed**: owner 0 completed in 63.632 seconds with a 779-byte answer, but conversation deletion failed (exact status/error unavailable); owner 1 approved search and fetch, received nine search sources and one fetch source, then timed out after 120.756 seconds without an answer. Cause remains unproven. The 768 MiB sample is not actual 1 GB acceptance, and CPU throttling is not causal proof; exact cleanup and source/stage bindings passed. No retry or kill ran. E306 independently passed selected deletion-diagnostic tests and source review only; historical baseline bytes and a deletion cause remain unavailable. E307 passed Linux/amd64 build and source/stage binding for a new image (147 inputs, 52 served files). E308 then **Failed** native functional acceptance on that image: both turns returned `provider_unavailable` after the model-session event without an answer, workspace summary, or search/fetch activity; both conversation deletes returned HTTP 200. The timing projection is invalid and model identity was not retained, so no provider cause or LongCat availability is inferred. Cleanup and bindings passed; no retry or kill ran. E309 independently **Passed** warning-projection QA for its selected source/test scope (209 tests, two deprecation warnings, Ruff check/format, and three unchanged source/test pins); it did not run native/provider work. Its first parent AST-helper lookup failed on a literal-only `OUTPUT_LIMIT` match, then the corrected source review completed (review SHA-256 `020288c1388434fbcf0656da8edbe9d8e87c03027626b21e03ee832e54d0f114`). E310 then **Failed** the one native functional attempt on E307’s image: both turns returned `provider_unavailable` after model-session, without answers, workspace summaries, or search/fetch. Exact selected model identity was unavailable. Two anonymous timing rows show eight `safe_protocol_error` attempts per turn, zero sanitized chunks/bytes, and the same `native_error_unknown` terminal warning; this supports pre-chunk failures only, with provider cause and upstream status unproven. Owner 0 conversation deletion returned HTTP 503 `assistant_cache_clear_pending`; owner 1 returned HTTP 200 `none`. The 768 MiB failure sample peaked at 542,703,616/805,306,368 bytes with zero high/max/OOM deltas; CPU throttling was observed, not causal evidence or actual 1 GB acceptance. Exact cleanup and 147-input/52-file bindings passed. A parent prefix-guard helper setup failure was corrected and was not a product failure. No retry or kill ran. E311 independently passed selected cache-clear/runtime (9), supervisor (4), HTTP-boundary (8), and API-delete (2) tests, plus a synthetic child `/api/info` supervisor purge/restart probe. The original QA pin set omitted imported `tests/native_assistant_probe.py`, so its before/after binding is **Unavailable**; its optional integrated HTTP delete harness failed during startup with `diagnostic_unknown`, cause unproven, and no retry. E312 passed a separately pinned 9-test runtime-only rerun with 54 unchanged inputs, resolving only that runtime test binding gap; it does not replace E311’s missing original pin or unavailable integrated HTTP result. E313 independently passed selected closed-stage provider-diagnostic source review, 413 tests and Ruff checks; this is not native/provider acceptance, and the eight registered observer ordinals are not an HTTP retry limit. E314 passed `./scripts/build-frontend.sh` with 55 frontend checks, 82 unchanged build inputs, and all 52 served/export files byte-matched; no browser, axe, image, or runtime result follows. E315’s independent current-source axe-stack diagnostic passed execution 4/4 with zero errors, retries, or skips across desktop Chromium (1440×1000) and emulated Pixel 7 (360×800), Light and Dark. Strict raw axe still **Fails** its zero-incomplete criterion: there were zero violations and one incomplete contrast rule in each state. Six incomplete targets mapped exactly to 12 text rectangles; ordered-stack differences appeared only below the opaque panel, supporting underlay variation only. Cause, repair, foreground obstruction, and accessibility acceptance remain unproven. Source/scaffold bindings, all 52 served/export files, and exact owned cleanup passed. Earlier closure/setup and preliminary verifier failures are preserved as separate audit history; the corrected final audit did not retry the browser run or edit source. Physical mobile, actual screen-reader, and true-zoom results remain **Unavailable**. E316 passed one local Linux/amd64 image build for build and source/stage binding only (image `sha256:9ef936567f2e270f9caac07a7f002ccc52438580a3a9be8d5ad3b6c1f31df27a`, context `bbc8bd55746f92dd39a08e56d564e898cbf09f5532ac67ff5f9573c8f1739880`): all 147 input files remained bound, all 52 served files matched the export, and the owned workspace was removed. Docker `Config.Env` was not inspected; no credentials were read and no native/provider run on this image, publish, or production action occurred. E317 then records a builder-run native functional **Fail** on E316’s image; independent QA remains pending after reviewer launch was rejected by the tool registry thread limit. Both owners returned `provider_unavailable` after model-session, without an answer, workspace summary, search, or WebFetch. Model-selection predicates matched, but exact model identity was not recorded. Two timing rows show eight `safe_protocol_error` attempts each, zero sanitized chunks/bytes and zero provider-stream-failure marker rows, with two `native_error_unknown` terminal warnings; provider/upstream cause is unproven. Both conversation DELETE calls returned HTTP 200, which does not establish that E310’s earlier 503 cause was fixed. The 147 source-input and 52 served/export bindings and exact cleanup passed. The 768 MiB failure sample peaked at 546,971,648 bytes with zero high/max/OOM deltas; throttling proves neither cause nor actual 1 GB acceptance. No retry, kill, provider fallback, or production/release action occurred; at the E317 checkpoint, no further native run or repair was authorized. E318 records builder source-preparation **Pass** for focused pytest exit 0 and Ruff, but the final test count is **Unavailable**; the earlier 14-failure, 1-failure, and terminal-metadata-unavailable attempts remain historical, and parent review was static only. E319 records read-only QA by a Luna build worker (not a formal luna-qa-profile run): the named timing/probe files exited 0 with counts **Unavailable**, the selected API JUnit passed 18/18, and six source/test pins matched. E320 records an eight-case builder scroll/layout diagnostic execution **Pass**, while 12 of 16 baseline/candidate axe analyses retained incompletes and the scrolling candidate did not improve contrast; strict raw axe remains **Fail**. The 21 source pins and 52 served/export bindings matched. Mobile was emulated, screenshots were absent, and no app-accessibility acceptance follows. E292/E293 concern the pre-repair image, and canonical E288 predates the timing cleanup. No production, resize, or release action occurred.

E198 remains a historical complete canonical local-gate **Pass** for its frozen dirty native-x86_64
tree: 2,108 Python passes, three skips, four deselected, 90 warnings, and 85.25%
coverage; the ordered documentation, frontend, and Python checks completed, with 54 frontend checks.
It predates E199/E203/E204 findings and later source changes; it does not exercise the redirect or
provider-egress invariants. E288 is the later complete canonical pass for its declared local scope,
with native OpenCode boundary/provider-wire gates still skipped. E191's earlier complete canonical run remains preserved as **Failed** with 2,052
Python passes, two failed tests, three skips, four deselected, and 85.24% coverage. Strict raw axe
remains Fail. Complete integrated security, provider terms/connection coverage,
full-feature/mobile/accessibility, combined host-resource, backup/recovery and rollout gates remain
open. Parent source observations are explicitly incomplete (E172), not security acceptance.
Earlier failed model/search runs, DNS diagnostics, guide renders and helper checks remain in the
[R-ASTRA-120 ledger](../../MVP-PLAN.md#r-astra-120-signal-ledger-assistant-design-first-follow-on);
the earlier DNS failure's cause remains unproven. No release or email acceptance is inferred.

## Operator responsibilities

For development, keep the listener on loopback, use only generated local bootstrap credentials,
and never copy them into production. For production, keep the app port loopback-only, protect the
data directory, trust key, app environment, tunnel token, and deployment key, and review exports
before sharing. Re-take the online SQLite snapshot at cutover, stop public ingress while moving
active storage, and verify signed backups before migration or restore. Treat Yahoo content,
imported artifacts, OAuth profile data, and browser input as untrusted. Review an article
destination before following it; the destination receives an ordinary browser navigation even
though application data traffic remains local. Do not disable verification to recover an artifact.

The deployment is intentionally one app process, one SQLite volume, and one connector service;
that shape does not substitute for the account, ownership, session, backup, or recovery controls
above. Signal Ledger remains research software; security controls do not make forecasts investment
advice.

See [getting started](../operations/getting-started.md),
[backup and restore](../operations/backup-restore.md), and
[architecture](../concepts/architecture.md).


## Current R-ASTRA-120 security and release checkpoint

E672 is the latest read-only production observation: revision `da2764e8477698fa7d686be93a4711e35478e802`, image `sha256:d3e21ae9de800f0151c1eba74fb3d16423e1171985c33ea03057acbfe2278ec1`, schema 12 ready, `failed=null` and loopback-only; rollout, RAM, billing and browser state were not returned. E662's canonical local check **Failed** on two test-fixture AF_UNIX paths exceeding the Linux socket limit before child spawn; the selected short-path rerun does not change the aggregate. E666's repaired OAuth egress callback passed its independent selected 14-test and source-review scope, with parent source review also passing; this is not live-provider or full security acceptance, and a fresh canonical gate remains pending. The native HTTP 403 cause and any provider policy remain unproven. E667 confirms strict raw app axe **Fail**; manual measurements do not waive the incomplete results, and E668 found no maintained upstream fix. E669 found no supported safe provider remedy. E670's initial independent test review **Failed** on a P2 assertion-boundary gap, and its first repair-run exit was **Unavailable**. E673 then passed the exact repaired Node command at exit 0 with 17/17 tests; maintained guide rendering remains pending. Current-image kill, actual combined 1 GB, complete security, strict accessibility, PR-bound rollback, final guide and release gates remain open. Production mutation and release acceptance are not claimed; the existing 1 GB/backups and US$15 monthly total cap remain unchanged. See the [R-ASTRA-120 evidence ledger](../../MVP-PLAN.md) for exact receipts.
