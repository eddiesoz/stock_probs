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

This Compose path is local development and validation. The invite-only GitHub OAuth/passkey
deployment, local GitHub Release publication (with GHCR as an explicit compatibility transport),
Terraform-managed Linode host, and closed-until-canary Cloudflare Tunnel use the production
procedure below. Do not copy development bootstrap credentials into a production environment.

## Invite-only production deployment

Production is one FastAPI app with SQLite on a persistent Linode volume, published only through a
Cloudflare Tunnel. Docker binds the app to `127.0.0.1:8000`; there is no public application port,
order routing, brokerage session, real-time claim, or fabricated market depth. Production uses
GitHub's authorization-code flow with state and PKCE, the numeric GitHub account ID as the stable
identity, and a required user-verifying passkey after an administrator-issued, expiring, single-use
invitation.

Terraform's Linode configuration keeps the requested low-resource shape: Ubuntu 24.04,
`g6-nanode-1` (1 GB RAM/25 GB disk), `us-east`, VM Backups, disk encryption, and the existing
firewall imported as `177236117`. Its inbound policy is default-deny with only operator SSH from
the configured `/32`; application ports are not opened, and the Linode and firewall have
`prevent_destroy`. The fixed external source gate runs during plan and again during apply and
requires a clean checkout, exact `origin/main`, the reviewed revision, and checksums for the
bootstrap files. Terraform apply remains pending.

Cloudflare Terraform defaults to `exposure_mode=closed`: the managed tunnel has a terminal 404
ingress and no DNS record. Canary mode adds only `ledger.jtmb.cc`, routes to `http://127.0.0.1:8000`,
keeps a single owner email behind Cloudflare Access, and installs a cache-settings rule that
bypasses shared and browser caching for the exact hostname. Provider token/UI creation and the
actual apply remain pending.

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
Remote Linode pull/deploy remains pending. The Linode helper derives the fixed GitHub URL from the
reviewed revision and accepts only the verified archive hash and full image ID. It does not accept
mutable tags, arbitrary image names, remote builds, shell commands, paths, URLs, Compose edits, or
Docker-socket operations.

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
a disabled `signal-ledger-cloudflared.service`. The later configuration helper writes each file
atomically under its own lock; the app environment and tunnel token are separate writes, so the
operation is not an all-or-nothing pair. Luna ops QA passed 17 focused local tests plus Bash
syntax, Ruff, ShellCheck, and diff checks, with local fixtures for full `deploy.lock` contention,
failed verify/retry, no-clobber, and strict SSH. A real host was unavailable, so remote execution
remains pending. When the provider steps are complete, install the remotely managed tunnel token at
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
schema. Luna's ops QA covered the local fixture paths; a real host was unavailable, so remote
transfer and migration remain pending. The reserved legacy owner claim remains the owner of legacy
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
records the failure for operator recovery. Luna's ops QA passed the focused local fixture sequence;
a real host was unavailable, so actual remote promotion is still pending before treating the
sequence as deployment acceptance.

### Tunnel canary and recovery

After the provider token/UI setup and closed Terraform apply, move Cloudflare to `exposure_mode=canary`
only for the owner. The exact hostname is `ledger.jtmb.cc`; the tunnel routes to
`http://127.0.0.1:8000`, Cloudflare Access allows one owner email, and the cache-settings rule
bypasses shared/browser caching. Keep the connector disabled until the private checks pass, then run
an owner-only canary: GitHub state/PKCE and callback checks, passkey enrollment, invitation
redemption, session revocation, two-user ownership isolation, and administrator fresh-passkey
backup/restore. Confirm spoofed Host/Origin/proxy headers fail closed before any public route is
considered. The canary and public route remain pending.

Application backups remain signed and verified. Enable Linode VM Backups and rehearse recovery
before exposure. This release has no independent encrypted off-server backup; Linode's configured
VM Backup retention is the external recovery boundary and must be recorded as a limitation.

Current local evidence includes schema-8 readiness, authentication status `200`, private history
`401` without a session, frontend `27` tests, focused API/auth `151` tests, and helper/MCP `31`
tests. The local-to-GitHub image transport is recorded as Pass for the reviewed revision; remote
Linode image pull/deploy remains pending. Astra's final source review reported no remaining source
launch blocker after the lock,
upload, staged-database, source-gate, and cache-ordering fixes. Luna ops QA reported 17 focused
tests passed plus Bash syntax/Ruff/ShellCheck/diff checks and local deployment fixtures; real-host
evidence remains unavailable. The latest local `R-ASTRA-101` gate then passed; coordinator stdout
reported Python `644` and `4` live deselected at `85.36%` coverage plus frontend `27` tests. The
earlier `13:39` startup-timeout failure remains historical. Provider token/UI creation, Terraform apply, remote image
deployment, GitHub OAuth credentials, owner canary, VM Backup rehearsal, and retirement of
legacy Linode `97934478` remain pending; the old VM and current local application are untouched.
