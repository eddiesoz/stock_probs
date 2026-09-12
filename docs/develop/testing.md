---
title: "Testing"
description: "Local developer checks for Python, API, persistence, browser, package, backup, provider, and architecture behavior."
---

# Testing

Bootstrap the pinned Python 3.11.15 environment before running checks:

```bash
./scripts/bootstrap.sh
```

Fast feedback commands are:

```bash
.dev-venv/bin/python -m pytest -m "not live"
.dev-venv/bin/python -m ruff check src tests scripts
.dev-venv/bin/python -m mypy src/stock_probs/backup.py src/stock_probs/cli.py
.dev-venv/bin/python scripts/validate_docs.py
```

`pytest` uses temporary data directories and injected fixture providers for deterministic
domain, API, migration, repository, and backup checks. Tests marked `live` contact Yahoo
Finance and are deliberately excluded from deterministic gates; a skipped or unavailable
provider run is not a deterministic pass.

Browser tests run the real local app on an isolated loopback port with packaged fixtures.
Use `make browser-test` for checked-in Playwright regressions and `make mcp-smoke` for the
official headless MCP interaction. `scripts/local-gate.sh` is the make-independent,
fail-closed aggregate runner and writes revision/architecture/result artifacts. Do not treat
a generated artifact or builder run as independent acceptance evidence.

ARM64 checks must identify whether execution is native or QEMU/OCI-emulated. Emulation can
exercise package, runtime, functional, build, and tool behavior; it cannot prove native
resource performance. See the [MVP plan](../../MVP-PLAN.md) for current gate requirements.
