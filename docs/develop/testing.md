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
./scripts/build-frontend.sh
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

The frontend build check is intentionally static: `./scripts/build-frontend.sh` runs the pinned
Next.js `16.3.5` / React `19.3` App Router export, typecheck, and frontend tests, then stages
the served tree for FastAPI. It does not start a Next server. The generated `out/` and staged
trees are ignored, while the 12 staged served files are packaged into the Python wheel. The
production container keeps Node in a build-only stage.

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

The latest post-ASTRA M09 gate artifact is `test-results/local-gates/M09-20260914T032442Z/`:
**Pass**, exit `0`, dirty `HEAD`
`5633f87f8cff04b5b33640f6633ff31c667c0435`, native x86_64, `2026-09-14T03:24:42Z`–
`03:37:22Z`, command `./scripts/local-gate.sh m09`. Its completed checks include the frontend
npm CI/typecheck/test/build stage, native package, Python checks, responsive browser
visual/accessibility/theme/news, official MCP, explicit ARM64 package/runtime, and mandatory
native M09 performance. The Ponytail interface was available but not invoked; that is not a
clean Ponytail result.

The artifact's Python JUnit reports `444` tests with zero errors and zero failures, with
`89.73%` coverage. Browser artifacts/logs report `64` passed and `2` expected performance
skips; the official MCP check is included in the gate receipt. The native performance summary
has `18` rows: `17` executable rows **Pass** and ARM64 performance **Unavailable**. Current row
values include theme p95 `35.0 ms`, browser render p95 `151.958 ms`, interaction p95
`24.027 ms`, ten-item news render p95 `35.0 ms`, news cache-hit p95 `1.809 ms`, news response
`701` bytes, provider deadline capped at `10 s`, static assets `697,667` bytes below `753,664`,
readiness p95 `2,633.207 ms`, process RSS p95 `144,457,728` bytes, and wheel `307,483` bytes
below `335,872`. The earlier `test-results/local-gates/M09-20260914T002732Z/` receipt and its
values remain historical. The failed rerun at `test-results/local-gates/M09-20260914T031828Z/`
also remains visible; it recorded `46` documentation-link setup errors and is not replaced by the
later pass. QEMU/OCI ARM64 evidence passed for package/runtime/functional scope only; QEMU
`7.2.0` is not ARM64 performance evidence. Physical mobile, actual screen-reader, and true-zoom
evidence remain unavailable.

The existing deterministic build/container receipt remains separate evidence: `26` files /
`703,175` bytes, staged `12` files / `608,713` bytes, an approximately `306,559`-byte wheel,
and amd64 image digest
`sha256:0d68e3d9a78d626a61a1a82c455ea1734ddaa753f562d74022b94986c477bb12` at
`170,062,564` bytes. These values do not replace the current gate's exact `306,553`-byte wheel
receipt.

The unsupported `TASK_ID=R-ASTRA-64` attempt exited `2` with no artifact. The first supported
M09 attempt failed in `test_backup_automation` because of a timing race; supplied `R-ASTRA-65`
repair history records removal of the irrelevant completion assertion and a passing final rerun.
The `R-ASTRA-65` Ponytail observation is historical findings-only: its CSP-regex suggestion is
rejected and nonblocking because production CSP parsing is a security boundary. The final
`R-ASTRA-69` `/ponytail-review` boundary is separately **CLEAN**, returning exactly
`Lean already. Ship.` at `2026-09-14T02:41:58Z`; see the [ASTRA report](../evidence/astra-final-report.md)
for the full reconciliation and limitations.

ARM64 checks must identify whether execution is native or QEMU/OCI-emulated. Emulation can
exercise package, runtime, functional, build, and tool behavior; it cannot prove native
resource performance. See the [MVP plan](../../MVP-PLAN.md) for current gate requirements.
