---
title: "Testing"
description: "Local developer checks for Python, API, persistence, theme/news presentation, package, backup, provider, and architecture behavior."
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

Theme and news checks stay deterministic by reusing existing fixtures. The fixture provider
loads synthetic Yahoo-shaped entries from `src/stock_probs/fixtures/news.json`; API and service
tests inject providers and monotonic clocks to exercise closed schemas, cache boundaries,
failure suppression, stale fallback, size limits, persistence exclusion, and the single
retrieval slot. Provider tests stub the direct `curl-cffi` session to pin one bounded request,
the absolute deadline, malformed-data rejection, and safe links without contacting Yahoo.

The Playwright journeys emulate system color preference and storage failure, switch among
light/dark/system on both local pages, and exercise print, reduced-motion, forced-colors, CSP,
and contrast behavior. News routes are fixture-fulfilled for not-requested, loading, fresh,
empty, partial, stale, provider-failure, local-unreachable, capacity-busy, and superseded
states. The mixed-feature journey changes theme, runs a forecast, expands from five to ten
headlines, checks local-only application requests and ledger exclusion, then reopens the saved
forecast without an automatic news request.

The M09 local performance profile records theme action, news cache-hit endpoint, ten-item render,
response-byte, and provider-deadline evidence alongside the forecast concurrency and process
resource rows. This is aggregate mixed-load evidence; do not describe the forecast-concurrency
row as simultaneous news traffic unless a future artifact actually drives both. The pinned
provider feasibility evidence and opt-in ACDC/SPY live news probes remain separate from the
deterministic suite: record their command, environment, UTC, revision, result, and provider
availability, and never convert an unavailable live run into a pass.

ARM64 checks must identify whether execution is native or QEMU/OCI-emulated. Emulation can
exercise package, runtime, functional, build, and tool behavior; it cannot prove native
resource performance. See the [MVP plan](../../MVP-PLAN.md) for current gate requirements.
