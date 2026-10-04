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
| Deployment MCP command injection or supply-chain substitution | The local stdio MCP exposes six typed tools: `inspect`, `plan_deploy`, `deploy`, `status`, `rollback`, and `refresh_operator_access(operator_ipv4_cidr)`. The fixed SSH helper accepts a reviewed `main` revision, a release archive SHA-256, and a full image ID; it rejects arbitrary commands, paths, URLs, Compose edits, registry names, tags, and Docker-socket access. The access-refresh operation accepts only a canonical IPv4 `/32` and the fixed operator SSH firewall rule. GHCR is an explicit compatibility transport, not the default. |
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
