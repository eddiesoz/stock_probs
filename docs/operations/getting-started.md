---
title: "Getting started"
description: "Install and run Stock Probability locally with the pinned Python environment, migrations, readiness check, and safe shutdown."
---

# Getting started

Stock Probability supports Linux on x86-64/amd64 and ARM64/aarch64 with Python 3.11. The
bootstrap selects exactly Python 3.11.15 and creates `.dev-venv/`; tracked `burry_env/` is
legacy noise and must not be used as the environment or dependency declaration.

```bash
./scripts/bootstrap.sh
./scripts/build-frontend.sh
.dev-venv/bin/python -m stock_probs.cli migrate
.dev-venv/bin/python -m stock_probs.cli serve
```

Open `http://127.0.0.1:8000/`. Readiness is available at
`http://127.0.0.1:8000/api/v1/readiness`, and the local API pointer is at
`http://127.0.0.1:8000/api/v1/docs`.

`./scripts/build-frontend.sh` runs the pinned Next.js `16.3.5` / React `19.3` static App
Router export, typecheck, and frontend tests, then stages the result for the Python package.
Its stable build ID is `stock-probs`. `frontend/.next/`, `frontend/out/`, and
`src/stock_probs/static/next/` are generated and ignored; do not treat their presence as source
or release evidence. FastAPI remains the only production server and `/api/v1` remains the only
application-data boundary. The Docker path uses Node in a build-only stage and copies the staged
static files into the Python wheel; Node is not part of the runtime image.

The default provider is Yahoo Finance and requires network availability. For a repeatable
offline-oriented development run, use the fixture settings in
[local configuration](../configure/local-configuration.md). Startup creates the private data
directory, applies packaged migrations, and marks readiness only after initialization.

Stop the foreground server with `Ctrl-C` and wait for normal process exit. Do not delete the
data directory to clear a port conflict; choose another loopback port. Before migration,
upgrade, or destructive filesystem maintenance, create and verify a managed backup as
described in [backup and restore](backup-restore.md).

## Optional local production Compose path

The root `compose.yaml` provides one minimal local production-style
service; it is not a hosted deployment or a replacement for native development. Build and start
it from the repository root:

```bash
docker compose up --build -d
docker compose ps
```

Open `http://127.0.0.1:8000/`. Compose publishes only
`127.0.0.1:${STOCK_PROBS_PORT:-8000}` and keeps the database, SQLite WAL sidecars, trust key, and
managed backups in the named `stock-probs-data` volume mounted at `/data`. The image healthcheck
requests `/api/v1/health`; the runtime image uses UID/GID `10001`, a read-only root filesystem
with a bounded `/tmp`, dropped capabilities, `no-new-privileges`, `128` PIDs, `768m` memory,
`1.0` CPU, and three `10m` JSON log files. Compose defaults `STOCK_PROBS_PROVIDER` to `yahoo`;
set it explicitly only when a deliberate local fixture run is required.

Stop the service without deleting its named volume:

```bash
docker compose down
```

The native path above remains the development path: it uses `.dev-venv/`, the local CLI, and
directly selected `STOCK_PROBS_DATA_DIR`/provider settings. The Compose path builds the pinned
wheel image and does not claim native ARM64 performance, physical-mobile behavior, screen-reader
coverage, or true browser-zoom evidence. Physical mobile, actual screen-reader, and true-zoom
evidence are unavailable in the current post-final QA record; emulated ARM64 covers functional,
package, and runtime behavior only, not ARM64 performance.

This Compose path is local development and validation. The invite-only GitHub OAuth/authenticator-app
deployment, local GitHub Release publication (with GHCR as an explicit compatibility transport),
Terraform-managed Linode host, and closed-until-canary Cloudflare Tunnel use the production
procedure below. Do not copy development bootstrap credentials into a production environment.

## Invite-only production deployment

Production is one FastAPI app with SQLite on a persistent Linode volume, published only through a
Cloudflare Tunnel. Docker binds the app to `127.0.0.1:8000`; there is no public application port,
order routing, brokerage session, real-time claim, or fabricated market depth. Production uses
GitHub's authorization-code flow with state and PKCE, the numeric GitHub account ID as the stable
identity, and a six-digit TOTP authenticator-app code after an administrator-issued, expiring,
single-use invitation. The authenticator code is the sole ongoing application second factor. New
passkeys are not enrolled; a legacy passkey is accepted only once to migrate an existing account
to TOTP.

### Authenticator enrollment and recovery

After GitHub sign-in and invitation validation, open `/authenticator?mode=enroll`. Add the displayed
secret to an authenticator app using the manual key or the `otpauth://` link, then enter the current
six-digit code. The server activates the factor only after the code is verified and returns recovery
codes once. Store each recovery code offline; each can be consumed only once.

If an authenticator is lost, use one unused recovery code at `/authenticator?mode=recover`. That
session is limited to replacing the factor. Enroll the replacement app and save the newly issued
recovery codes before returning to the workspace. A normal sign-in from another device uses only
GitHub plus the six-digit authenticator code; it does not require Bluetooth, a nearby phone, or
browser passkey support. Legacy accounts may use `/passkey?mode=verify` exactly once as a migration
step, after which the authenticator page completes the transition.

Terraform's Linode configuration keeps the requested low-resource shape: Ubuntu 24.04,
`g6-nanode-1` (1 GB RAM/25 GB disk), `us-east`, VM Backups, disk encryption, and the existing
firewall imported as `177236117`. Its inbound policy is default-deny with only operator SSH from
the configured `/32`; application ports are not opened, and the Linode and firewall have
`prevent_destroy`. The fixed external source gate runs during plan and again during apply and
requires a clean checkout, exact `origin/main`, the reviewed revision, and checksums for the
bootstrap files. This has been applied to replacement Linode `106817202`; E59 retired legacy Linode
`97934478` after validation-only checks and a guarded execute run. The old instance was labeled
`cardventory` with backups disabled; the replacement is labeled `signal-ledger` with backups enabled
and the same shape/location. The retirement workflow used the local Signal Ledger app as its data
source; no Cardventory-data preservation claim is made. The firewall is attached only to the
replacement host, and the application remains loopback-only.

Cloudflare Terraform defaults to `exposure_mode=closed`: the managed tunnel has a terminal 404
ingress and no DNS record. E58 records the provider-refreshed `public_invited` apply for
`ledger.jtmb.cc`: the owner-canary Access app was deleted and the exposure guard updated, while
the tunnel, DNS record, and cache-settings rule remain managed. The route still targets
`http://127.0.0.1:8000`, the connector is active, and direct port `8000` remains unreachable.
The live boundary returned `303` to local sign-in for `/overview`, `401` for `/api/v1/history`, and
`200` for `/api/v1/auth/status`; each response was `no-store`/`DYNAMIC`. The live IAB showed the
unauthenticated sign-in page but no owner UI session. E59's post-delete probes returned health and
auth `200`, history `401`, and overview `303` to sign-in, with `no-store`/`DYNAMIC`. Functional
owner/invited-user acceptance remains pending.
The earlier provider verification reported Cloudflare HTTP `401` despite functional API/Terraform
operations, so that discrepancy remains an open limitation.

### Build and publish locally

The VM never builds source. A reviewed clean checkout whose `origin/main` matches the exact `HEAD`
builds and publishes the default GitHub Release transport:

```bash
./scripts/publish-production-image.sh
```

The script builds a Linux `amd64` image, creates the revision-named local tag
`signal-ledger-<reviewed-sha>` and release asset `signal-ledger-image-<reviewed-sha>.tar.gz`, scans
the archive for credential-like material, publishes through `gh release create`, then downloads
the asset again and verifies its archive SHA-256, Docker image ID, revision label, platform, and
size. The script treats the revision-named asset as immutable during this workflow, but GitHub
does not enforce asset immutability. Set `SIGNAL_LEDGER_IMAGE_PUBLISH_MODE=ghcr` only for the
explicit compatibility transport; GHCR is not the default. Local-to-GitHub publication is
completed for reviewed revision `3bc85ed6c6b8b56386da32e532e4a79c5f74b6dd`; the verified asset is
`103,116,996` bytes with SHA-256
`586ef74929dd3542930f37f46f9081f56a2c3bdf7a43b5aec32450be69d9ecce` at
`https://github.com/eddiesoz/stock_probs/releases/tag/signal-ledger-3bc85ed6c6b8b56386da32e532e4a79c5f74b6dd`.
That transport receipt remains historical. The current private deployment uses reviewed revision
`f329a4c99bf75d9ff2d365473051580f8eda7f58`, archive SHA-256
`79f4ac15491ccb7d70ab28b0ed44f441f18f0212c54c3a1487dde6a3a267f9a1`, and image ID
`sha256:b324a8f288307ff864b26d4792c54271cfee963cf077d31b16c1fac951f87eca`; remote readiness is
schema `8`. The Linode helper derives the fixed GitHub URL from the reviewed revision and accepts
only the verified archive hash and full image ID. It does not accept mutable tags, arbitrary image
names, remote builds, shell commands, paths, URLs, Compose edits, or Docker-socket operations.

### Prepare the host

From a clean reviewed checkout, run the static validation and plan the two Terraform roots. Supply
the operator IPv4 `/32`, separate operator/deployment public-key paths, and reviewed commit SHA as
variables; the private keys and provider credentials stay outside the repository. The plan must
show the existing firewall import and the requested `g6-nanode-1` replacement without opening
application ports. Do not remove the existing VM or change the current local app during
preparation. Run Terraform from an operator-owned private working directory with mode `0700`, and
set `umask 077` before creating `.terraform`, local state, saved plans, or backups:

```bash
umask 077
chmod 700 /path/to/private-deployment-workdir
cd /path/to/private-deployment-workdir
```

Before using any existing state, backup, or saved-plan file, verify that it is operator-owned and
mode `0600`; correct each retained file with `chmod 600 /path/to/file` before continuing. This
procedure does not claim that existing state or credential permissions have been checked. Do not
store Terraform state, saved plans, backups, provider credentials, or private keys in a shared or
world-readable directory.

```bash
./infra/linode/validate.sh
terraform -chdir=infra/linode init -backend=false
terraform -chdir=infra/linode plan \
  -var='operator_ipv4_cidr=OPERATOR_IPV4/32' \
  -var='reviewed_revision=REVIEWED_MAIN_SHA'
terraform -chdir=infra/cloudflare init -backend=false
terraform -chdir=infra/cloudflare plan -var='exposure_mode=closed'
```

The first-boot bootstrap installs Docker, Compose, `cloudflared`, the restricted host boundary, and
a disabled `signal-ledger-cloudflared.service`. The service command and host-unit update path are
code-managed, and the fresh bootstrap remains source-gated. The later configuration helper writes
each file atomically under its own lock; the app environment and tunnel token are separate writes,
so the operation is not an all-or-nothing pair. The private replacement host has completed the
scoped bootstrap, configure, seed, and image deployment checks; the recovery rehearsal is recorded
separately below. When the provider steps are complete, install the remotely managed tunnel token at
`/etc/cloudflared/tunnel.token` with mode `0600`. Store production values in
`/etc/signal-ledger/app.env` with mode `0600`: `STOCK_PROBS_ENV=production`,
`STOCK_PROBS_AUTH_MODE=github`, exact `STOCK_PROBS_PUBLIC_ORIGIN`, unique
`STOCK_PROBS_AUTH_SESSION_SECRET`, `STOCK_PROBS_GITHUB_CLIENT_ID`,
`STOCK_PROBS_GITHUB_CLIENT_SECRET`, `STOCK_PROBS_GITHUB_REDIRECT_URI`, and
`STOCK_PROBS_OWNER_GITHUB_ID`. Keep `STOCK_PROBS_AUTH_COOKIE_SECURE=1`, leave the cookie domain
unset for a host-only cookie, and trust proxy headers only from `127.0.0.1`.

### Preserve and migrate existing data

At cutover, take a fresh online SQLite snapshot while the source app is running, verify the signed
`.spbackup` and installation trust key, then transfer the snapshot through the protected operator
SSH route into the private target volume. Preserve mode `0600`; do not copy a live WAL pair by hand,
edit tables, or generate a replacement trust key. Keep the public Tunnel disabled while loading and
verifying the private volume.

The deployment helper is designed to read the existing schema, verify a pre-deploy backup, create
and verify the pre-migration backup when the imported database advances schema, run the
checksum-pinned migrations, verify a current-schema backup, and require readiness with the image's
schema. The R-ASTRA-102 candidate advances the additive auth schema to schema 9. Luna's ops QA
covered the local fixture paths; the prior private host run verified schema-8 readiness and
preserved the migrated counts. The reviewed schema-9 image is now deployed and live-verified at the
Cloudflare boundary, while owner TOTP enrollment and authenticated-browser data access remain
unavailable. The
repaired recovery rehearsal passed its declared
scope after restoring a disposable clone, checking the app, database, firewall, SSH, loopback, and
tunnel-disabled boundaries, then deleting the clone and confirming that its API lookup returned
`404`.
reserved legacy owner claim remains the owner of legacy
events/results; every new request derives ownership from the session, so
changing an ID cannot expose another user's history, exports, holdings, watchlists, outcomes, or
reconstructions.

The local rehearsal used the verified read-only `pre-production-20260927.spbackup` schema-6
database hash `2533d3bf96db79610b4616531e047df434ed54b1b2e1243c8a65b4e8401adcfd`. A separate
mode-`0600` online snapshot matched it and passed `PRAGMA integrity_check=ok`; it contained 13
events, 13 runs, 20 results, 6 portfolio holdings, and 3 watchlist items. Disposable schema-6→8
migration verified pre/post backups, and a simulated claim to GitHub ID `86915618` preserved all
records. This is local evidence; take the live snapshot again if data changes before cutover.

### Use the deployment MCP

Run `./scripts/deploy-mcp.sh` locally. Its separate stdio server exposes exactly five typed tools:
`inspect`, `plan_deploy`, `deploy`, `status`, and `rollback`. The default release transport carries
the reviewed revision, archive SHA-256, and full Docker image ID; the optional GHCR compatibility
shape carries its immutable digest. The controller uses the restricted SSH helper and records only
revisions, image identities, schema versions, backups, and safe result codes.
The normal sequence is:

```text
inspect → plan_deploy(main revision, release archive SHA, image ID) → deploy(plan) → status
```

Each promotion is serialized under a lock, starts with a verified application backup, runs
readiness checks, and attempts code-only rollback only when the database schema remains compatible.
If a migration has advanced the schema and the candidate fails, the helper stops the service and
records the failure for operator recovery. The fixed helper completed a private deployment plan
(`65d8355aef719983cb989a2dd8056522`) and the remote app is healthy. The prior private image was
reviewed commit `39bd185150cd3df70395e6c000f568dfd20831ac`, with release archive SHA-256
`930d6d5b5d054908a25825c980584b620817bfa7ab212a62abd63f65c72f6f3f` and image ID
`sha256:23ef16e4e5ee28db378c76bbcd9182345584bbffda55bd5313141fd0847fe31b`; publisher
re-download verification passed. The prior origin-navigation image was reviewed commit
`11faaf702129d0c1485a8683711d88340f623a71`, with publisher SHA-256
`fad471b19db6ff4f9b4dc154055f0d2437128e49878e72a286b697f17e8a3f48`, image ID
`sha256:26df706f6a2b4e76ee51bb014f94d39eb66bc7644a2c7a56eb3d012f41684d60`, and MCP plan
`530c1c65a7b4563e9c7f1cdbf5a47a3d`; deploy reported ready schema `8`, no failure, and loopback-only
with pre-deploy backup `pre-deploy-11faaf702129d0c1-d1c03381.spbackup`. The earlier final clean-main image
uses revision `2de5e9f199cd145707f95e81d389c40b2ab3c32a`, archive SHA-256
`b856795831b6fb46e94e330370e003843b266ad85f22e8d95ef7624536b2ac48`, and image ID
`sha256:ae7991f35a2093b145245f8037a3227981b09051805467870f759c0752bbfc3d`. Its first MCP plan
failed transiently with `remote_operation_failed`; retry plan
`2d8b0fe91ed01b55f1625c27edcc620b` passed, and deploy returned deployed/readiness schema `8` with
status reporting the current revision, `failed: null`, `loopback_only: true`, and pre-deploy backup
`pre-deploy-2de5e9f199cd1457-751c7459.spbackup`. The official Python SDK MCP plan
`a07bb7ba2716899bef956269495f0a47`
and deploy passed to the replacement Linode; status is healthy, schema `8`, loopback-only, and a
pre-deploy backup was present. Static MCP discovery passed in a fresh CLI task. The earlier
read-only stdio smoke listed exactly the five typed tools and completed `inspect` successfully
without printing credential bytes. A separate fresh Codex client invocation remains unavailable
under host approval policy `never`; rollback is not accepted by the read-only smoke. E63 is the current
deployment: main revision `27e0d2f5916d4297e10d259aa4776055a78faeaa`, Linux/amd64 image ID
`sha256:ecd41e1b65eb76b424cff830a6150db2282d326cfb18b3b6eaa37b07f83c4bc0`, archive SHA-256
`78f2e44ecfbe2021a61a0ecd71414065024c246eb46ca9506b33c20f13b07ad1`, retry plan
`21ca962a39d261282610568bc1e21219`, schema `8`, `failed: null`, loopback-only, and pre-deploy
backup `pre-deploy-27e0d2f5916d4297-39376b8d.spbackup`. The publisher exited `0`; public
health/auth/sign-in probes returned `200`/`200`/`401`/`303` with `no-store`/`DYNAMIC`.

### Historical schema-8 passkey canary and recovery receipt

The recovery rehearsal passed before the restricted canary. Cloudflare is now in
`exposure_mode=public_invited` after E58's provider-refreshed plan and apply. The exact hostname is
`ledger.jtmb.cc`; the tunnel routes to `http://127.0.0.1:8000`, and the cache-settings rule bypasses
shared/browser caching. The owner-canary Access app was deleted as part of the apply. The GitHub OAuth application authorization and
Cloudflare one-time-code flow completed successfully in the earlier browser session. The final live
in-app-browser reload with an expired session showed `Sign in first` and `Open sign in` and hid
`Create passkey`; opening sign-in and continuing with GitHub returned to
`/passkey?mode=enroll&next=/overview`, showed `Signed in as jtmb`, and showed `Create passkey`.
No ceremony was completed in this browser tab. A read-only operator SQLite check on `2026-09-28`
(exact query UTC not captured) found `quick_check` `ok`, zero foreign-key violations, owner id `1`
claimed to the configured GitHub account as active admin, one nonrevoked passkey, one current
passkey-verified session, and owner mappings of 13 events, 13 runs, 20 results, 0 outcomes, 6
holdings, and 3 watchlist items. This proves enrollment, a completed passkey verification on another
computer, and persisted owner mappings, but not browser-rendered UI retrieval. A fresh production
tab hit Cloudflare Access login with no transferable session. Later read-only Docker access logs
observed authenticated owner API retrieval and saved-forecast access after the passkey session;
`/overview`, portfolio, watchlist, history, and saved-forecast requests returned `200`. The earlier
callback-blocked observation is retained as historical evidence in E38, and E49 remains the prior
origin-navigation record. Browser-rendered owner content remains **Unavailable**. E56 independently
passes the four two-client isolation scenarios locally—cross-watchlist deletion, member `promote=true`
restore denial, nested outcome export, and two-account invitation reuse/identity binding—while remote
two-user behavior and browser UI remain **Unavailable**. E58 makes the public-invited infrastructure
boundary live, but the live IAB had no owner UI session. E59 records legacy-host retirement. E60
records the historical current-machine GitHub OAuth provisional session at `/passkey?mode=verify`,
the browser error `The browser could not create a passkey` after Verify with passkey, a `403`/denied
sign-out response, and the generic verify-mode error using `create`. E61 records the locally accepted
logout and mode-aware passkey repair with independent QA, and E62 records the passing full local gate.
E63 records the current deployment and a post-deploy read-only SQLite check with `quick_check=ok`,
zero foreign-key violations, 13 search events, 13 forecast runs, 20 forecast results, 6 holdings,
3 watchlist items, 1 passkey, and 1 user. The server-observed owner-verified session on another computer and saved API retrieval
in E52/E55 remain valid. Administrator
fresh-passkey backup/restore, rendered owner workspace, live second-user onboarding, and functional
invited-user acceptance remain pending or **Unavailable**. E64's Astra live read-only review found no
P1/P2; its Terraform/image, IPv6, and old-VM rechecks remain **Unavailable**.

### R-ASTRA-102 authenticator release status

The current follow-on replaces the ongoing passkey requirement with the authenticator flow
described above. Scoped independent QA passed 19 authentication checks, 8 repository checks, 6 API
checks, 65 backup/container checks, 10 desktop/mobile-emulated browser cases, 28 frontend checks,
4 account/admin smoke checks, two-user ownership isolation, and a disposable schema-9 backup/restore
rehearsal. Packaging and security lint also passed. Astra's independent security re-review reported
no P1/P2 finding after the generation, replay, and throttle repairs.

The current local `R-ASTRA-102` gate **Passed** for its declared scope. Receipt
`test-results/local-gates/R-ASTRA-102-20260928T201109Z/evidence.json` reports `704` Python tests
passed, `4` live tests deselected, `85.10%` coverage, frontend typecheck/build and `28` frontend
tests, and documentation coverage. The earlier aggregate failure remains visible as historical
evidence: four legacy schema expectation tests still expected versions 1 through 8 and coverage was
84.88%. Post-deploy evidence records reviewed revision
`403cd79b08f90b49603cec3152b4f1e07b91d730` pushed with exact `origin/main` matching, release archive
SHA-256 `811229e8355679f08d1a0857426cbec3526cee492417e50a5f9fe760e98894f4`, and a verified publisher
re-download. The Linux/amd64 image is `103146866` bytes with ID
`sha256:76283822fb01ba19ead18037d3396b81db5c804e41d0203dfbaae04c3c3abb8f`. Restricted MCP plan
`5b757cb6e2cb2b8d97b85613a4b5504b` deployed it; inspect/status reported schema `9`, `ready`,
`loopback_only: true`, verified pre-deploy backup
`pre-deploy-403cd79b08f90b49-3055603f.spbackup`, deployment
`2026-09-28T20:28:26.839271+00:00`, and no failed release. Live Cloudflare HTTP at `20:29:04Z`
returned health `200`, auth status `200`, `/authenticator` `200`, `/overview` `303`, and
`/api/v1/history` `401`, all `no-store`/`DYNAMIC`. The IAB reached the one-time legacy-passkey
migration route for owner `jtmb`; the button remained `Waiting for passkey…`, reloading cancelled
it, and sign-out returned to `/sign-in`. Owner TOTP enrollment, live mobile sign-in, and
authenticated-browser saved-data access remain **Unavailable**. Keep the route under the existing
invite-only boundary until those owner checks are directly observed.

Application backups remain signed and verified. Linode VM Backups are enabled, and successful
snapshot `385239936` is available. The first disposable restore attempt **Failed**: clone
`106821372` reached offline boot, but a concurrent in-place Bash edit corrupted the running process
and it exited `127` before verification; that guarded clone was deleted and its API lookup returned
`404`. The repaired rehearsal then **Passed**: clone `106825234` was restored, verified against the
declared boundaries, deleted, and confirmed `404`. The failed attempt and the repair findings stay
visible in the root evidence ledger. This release has no independent encrypted off-server backup;
Linode's configured VM Backup retention is the external recovery boundary and remains a limitation.

Current local evidence includes schema-8 readiness, authentication status `200`, private history
`401` without a session, frontend build/typecheck with `28` tests, pinned Playwright desktop/mobile
`2/2`, Luna auth contract `9/9`, click `2/2`, and simulated passkey-cancellation checks on desktop
and mobile. Astra's source review reported no P1/P2 after its `409` guidance finding was repaired.
Focused API/auth `151` tests, helper/MCP `31` tests, and a private remote deployment with migrated
data counts are also recorded. An earlier Astra source review reported no remaining P1/P2 finding
for the deployment-hardening boundary; a later privacy review
found a P2 because the configured owner email reached an embedded Python process argv. The private
owner-email-file repair is complete, the tracked tree has no literal personal email, `14` canary
fixture tests passed, and the live canary script reran exit `0` with the tunnel active. Luna's final
scoped QA passed the focused checks and Astra's final P1/P2 re-review reported no remaining finding
for this boundary. The earlier owner callback observation is historical; E51 records the final live
sign-in recovery. E52 records operator-side owner enrollment, passkey verification, and persisted
mappings, but does not complete authenticated app retrieval or the invited-user release gate.
A subsequent source fix at
commit `a1d868287a729c75d9b8628f612a856db132374a` handles a stale/expired provisional session that
returned `authenticated:false` and left the passkey page at `Checking your session`; build/typecheck,
`28` frontend tests, and browser `4/4` passed locally. The fix is source-reviewed and included in
the final clean-main image.
Independent Luna QA passed Terraform format/validate, `31` scoped infrastructure tests, and
`git diff --check` at the dirty reviewed revision. The earlier review recorded an import-order
finding in the Terraform test; final scoped QA passed all four Ruff checks, so that finding is
historical. The full Linode validator exits `2` on a deliberately dirty worktree. The earlier
Cloudflare token verification `401` and documentation-coverage **Fail** remain historical evidence.
The OAuth authorization and Access code steps completed in the earlier browser session. The final
live session returned to the signed-in passkey-enrollment page, but no ceremony completed in that
browser tab; owner passkey enrollment is operator-verified. E55 records server-observed
authenticated owner API and saved-forecast retrieval, while browser-rendered content remains
**Unavailable**. E56 passes the local four-scenario two-client QA, and E57 records the passing full
local gate after its initial comment-audit failure. E58 records the public-invited boundary and its
live unauthenticated probes. E59 records retirement of legacy Linode `97934478`; E60 records the
current-machine browser limitation; E61-E62 record the locally accepted repair and gate; E63 records
the current deployment; and E64 records Astra's no-P1/P2 live read-only review. Remote two-user/browser
verification, rendered owner workspace, and functional invited-user acceptance remain pending or
**Unavailable**; the current local application is untouched.
