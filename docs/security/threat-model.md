---
title: "Threat model"
description: "Threats and controls for loopback HTTP, untrusted requests, Yahoo market/news data, SQLite state, exports, and managed backup artifacts."
---

# Threat model

Signal Ledger has two supported security modes. Development may use a local bootstrap account on
loopback; production is an invite-only multi-user deployment behind a Cloudflare Tunnel. The
production image binds the app to the host loopback interface, uses GitHub's authorization-code
flow plus a passkey, and keeps SQLite on a private persistent volume. The recovery rehearsal has
passed for its declared scope, and the restricted owner-only canary is active behind Cloudflare
Access; authenticated owner API and saved-forecast retrieval are now evidenced by read-only server
logs, while browser-rendered owner content remains **Unavailable**. E56 passes the four two-client
isolation scenarios locally, but remote two-user behavior and browser UI remain **Unavailable**.
Invited-user exposure remains closed until Astra's final gate review and the remaining security gates
are complete. The final private
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
passing full local gate after its initial comment-audit failure. Astra final gate review remains
pending.

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
| Invitation theft or account takeover | Invitations resolve a GitHub account, expire, are single-use, and are redeemed before passkey enrollment. Production rejects development bootstrap credentials. Every invited account must complete a user-verifying passkey ceremony. |
| Session theft, fixation, or replay | Sessions are opaque server-side records addressed by hashed tokens, with idle and absolute expiry, revocation, host-only `Secure`/`HttpOnly` cookies, CSRF tokens for mutations, and no browser storage for credentials. Passkey step-up markers are short-lived and process-local. |
| Cross-user IDOR or legacy-data disclosure | Forecasts, events, results, outcomes, reconstructions, exports, holdings, watchlists, and account operations derive the owner from the session. Legacy rows attach to one reserved owner claim; a new user cannot claim or query them by changing an ID. |
| Privileged backup or restore abuse | Backup status and creation require an administrator. Restore promotion requires an administrator, a fresh passkey check, a verified pre-restore backup, matching account-security state, maintenance-mode serialization, and revocation of all sessions. |
| Deployment MCP command injection or supply-chain substitution | The local stdio MCP exposes only `inspect`, `plan_deploy`, `deploy`, `status`, and `rollback`. The fixed SSH helper accepts a reviewed `main` revision, a release archive SHA-256, and a full image ID; it rejects arbitrary commands, paths, URLs, Compose edits, registry names, tags, and Docker-socket access. GHCR is an explicit compatibility transport, not the default. |
| Mutable image or remote-build drift | The local publisher builds a Linux `amd64` image, scans and publishes a revision-named GitHub Release asset derived from the reviewed revision, treats that asset as immutable during its workflow, and verifies the downloaded archive SHA-256, image ID, platform, and revision. GitHub does not enforce asset immutability. The Linode loads only that verified asset and never builds source on the VM; optional GHCR plans remain digest-pinned. |
| Terraform source or infrastructure drift | The Linode plan and apply both use a fixed external source gate that requires a clean checkout, exact `origin/main`, the reviewed revision, fixed repository, and checksums for the host files. The imported firewall has `prevent_destroy`; no application port is opened by Terraform. |
| Public-ingress or cache bypass | The app port is published only on `127.0.0.1`; Cloudflare starts closed with a terminal `404`, then routes only the exact owner-canary hostname behind Access. The managed cache-settings ruleset bypasses shared and browser caching for that host. The connector is active for the restricted canary, while the invited-user route remains closed; proxy trust is local-only. |
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
