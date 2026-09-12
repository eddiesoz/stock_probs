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
.dev-venv/bin/python -m stock_probs.cli migrate
.dev-venv/bin/python -m stock_probs.cli serve
```

Open `http://127.0.0.1:8000/`. Readiness is available at
`http://127.0.0.1:8000/api/v1/readiness`, and the local API pointer is at
`http://127.0.0.1:8000/api/v1/docs`.

The default provider is Yahoo Finance and requires network availability. For a repeatable
offline-oriented development run, use the fixture settings in
[local configuration](../configure/local-configuration.md). Startup creates the private data
directory, applies packaged migrations, and marks readiness only after initialization.

Stop the foreground server with `Ctrl-C` and wait for normal process exit. Do not delete the
data directory to clear a port conflict; choose another loopback port. Before migration,
upgrade, or destructive filesystem maintenance, create and verify a managed backup as
described in [backup and restore](backup-restore.md).
