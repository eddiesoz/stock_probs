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
deployment, local GHCR publication, restricted Linode host, and disabled-until-canary Cloudflare
Tunnel use the production procedure below. Do not copy development bootstrap credentials into a
production environment.

## Invite-only production deployment

Production is one FastAPI app with SQLite on a persistent Linode volume, published only through a
Cloudflare Tunnel. Docker binds the app to `127.0.0.1:8000`; there is no public application port,
order routing, brokerage session, real-time claim, or fabricated market depth. Production uses
GitHub's authorization-code flow with state and PKCE, the numeric GitHub account ID as the stable
identity, and a required user-verifying passkey after an administrator-issued, expiring, single-use
invitation.

### Build and publish locally

The VM never builds source. A reviewed clean checkout whose `origin/main` matches the exact `HEAD`
builds and publishes the fixed package `ghcr.io/jtmb/signal-ledger`:

```bash
./scripts/publish-production-image.sh
```

The script labels the image with the reviewed revision, pushes it, and verifies the returned
immutable manifest digest. The Linode helper pulls only
`ghcr.io/jtmb/signal-ledger@sha256:<digest>` and verifies the registry digest, revision label,
and schema. It does not accept mutable tags, arbitrary image names, remote builds, shell commands,
paths, URLs, Compose edits, or Docker-socket operations.

### Prepare the host

Create the replacement Ubuntu 24.04 Linode with the planned low-resource size, encrypted disk,
Signal Ledger firewall, VM Backups, and no public application port. Keep inbound SSH restricted to
the operator route and default-deny unsolicited inbound traffic. Do not remove the existing VM or
change the current local app during preparation.

Install Docker, Git, Python 3, `curl`, and the official `cloudflared` binary. Run the reviewed host
setup as root with one operator-supplied public SSH key; the private key stays with the operator:

```bash
SIGNAL_LEDGER_DEPLOY_PUBLIC_KEY_FILE=/path/to/operator-deploy-key.pub \
  ./scripts/setup-production-host.sh
```

The setup creates a forced-command `signal-ledger-deploy` account, least-privilege helper, private
state/audit directories, and a disabled `signal-ledger-cloudflared.service`. Install the remotely
managed tunnel token at `/etc/cloudflared/tunnel.token` with mode `0600`. Store production values
in `/etc/signal-ledger/app.env` with mode `0600`: `STOCK_PROBS_ENV=production`,
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

The deployment helper reads the existing schema, verifies a pre-deploy backup, creates and verifies
the pre-migration backup when the imported database advances schema, runs the checksum-pinned
migrations, verifies a current-schema backup, and requires readiness with the image's schema. The
reserved legacy owner claim remains the owner of legacy events/results; every new request derives
ownership from the session, so changing an ID cannot expose another user's history, exports,
holdings, watchlists, outcomes, or reconstructions.

The local rehearsal used the verified read-only `pre-production-20260927.spbackup` schema-6
database hash `2533d3bf96db79610b4616531e047df434ed54b1b2e1243c8a65b4e8401adcfd`. A separate
mode-`0600` online snapshot matched it and passed `PRAGMA integrity_check=ok`; it contained 13
events, 13 runs, 20 results, 6 portfolio holdings, and 3 watchlist items. Disposable schema-6→8
migration verified pre/post backups, and a simulated claim to GitHub ID `86915618` preserved all
records. This is local evidence; take the live snapshot again if data changes before cutover.

### Use the deployment MCP

Run `./scripts/deploy-mcp.sh` locally. Its separate stdio server exposes exactly five typed tools:
`inspect`, `plan_deploy`, `deploy`, `status`, and `rollback`. The controller uses the restricted
SSH helper and records only revisions, digests, schema versions, backups, and safe result codes.
The normal sequence is:

```text
inspect → plan_deploy(main revision, GHCR digest) → deploy(plan) → status
```

Each promotion is serialized under a lock, starts with a verified application backup, runs
readiness checks, and attempts code-only rollback only when the database schema remains compatible.
If a migration has advanced the schema and the candidate fails, the helper stops the service and
records the failure for operator recovery.

### Tunnel canary and recovery

Create a remotely managed Cloudflare Tunnel for the exact HTTPS hostname and route it to
`http://127.0.0.1:8000`. Keep the connector disabled until the private checks pass, then run an
owner-only canary: GitHub state/PKCE and callback checks, passkey enrollment, invitation redemption,
session revocation, two-user ownership isolation, and administrator fresh-passkey backup/restore.
Confirm spoofed Host/Origin/proxy headers fail closed and HTML/authenticated API responses bypass
shared caching before widening access beyond the owner.

Application backups remain signed and verified. Enable Linode VM Backups and rehearse recovery
before exposure. This release has no independent encrypted off-server backup; Linode's configured
VM Backup retention is the external recovery boundary and must be recorded as a limitation.

Current local evidence includes schema-8 readiness, authentication status `200`, private history
`401` without a session, frontend `27` tests, focused API/auth `151` tests, and helper/MCP `31`
tests. The remote GHCR push, replacement Linode, GitHub OAuth credentials, Tunnel canary, and VM
Backup rehearsal remain pending; the old VM and current local application are untouched.
