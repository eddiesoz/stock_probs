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
