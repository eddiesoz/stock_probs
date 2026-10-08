---
title: "Testing"
description: "Local developer checks for Python, API, persistence, theme/news presentation, package, backup, provider, and architecture behavior."
---

# Testing

## Reviewing incomplete contrast results

Keep raw axe violations and incomplete results in the evidence. An incomplete result needs
manual review; axe has not definitively classified it as a violation or a pass. See the
[axe results contract](https://github.com/dequelabs/axe-core/blob/develop/doc/API.md#results-object).
Map every exact raw node to the measured direct text, verify its foreground against the nearest
opaque semantic background, and check all line rectangles, clipping and sampled foreground
occlusion. Require independent QA and parent inspection of the bound screenshots. Unknown,
unmapped or unresolved nodes fail the contrast gate; do not suppress the rule or alter the
approved layout solely to clear a resolved classifier result.

The current assistant contrast review and strict raw-axe status are in the
[R-ASTRA-120 ledger](../../MVP-PLAN.md#r-astra-120-signal-ledger-assistant-design-first-follow-on).
A manual resolution for measured nodes does not change the strict raw-axe zero-incomplete
requirement.

## Reproducible image-build and source-recovery evidence

Before source edits, save the exact bytes and SHA-256 of each owned baseline file in a task-owned
recovery directory. Require at least 4 GiB free on the build filesystem before starting a Docker
image build; stop the owned build if free space falls below 1 GiB and hold source edits until the
low-disk build has terminated. If the repository filesystem fills, retain terminal evidence under
`/tmp`. Remove only exact fixed-ID cache objects proven task-owned and unused. Never force-remove,
globally prune, or remove protected release images or application data. This procedure does not
authorize a resize above the US$15 monthly total cap including backups and tax. The root
[agent policy](../../AGENTS.md) is authoritative.

## Unix-socket test fixtures

Supervisor tests create AF_UNIX sockets. Use a unique, caller-owned short temporary root for
their pytest base directory; evidence-directory names must not determine socket paths. Check
the complete encoded socket-path length before binding. Linux limits pathname sockets to the
length of `sockaddr_un.sun_path`, including its terminator. Preserve a path-length setup failure
separately from product assertions, and rerun only after correcting that fixture boundary.
For live supervisor cases, verify the serving thread exits and its control socket is unlinked;
remove only that run's owned temporary directory after all children have exited.

## Current OpenCode V2 QA contract

Use native OpenCode V2 `build`/`plan` entry points and the Luna profiles: `luna-build` may
implement, `luna-qa` verifies read-only, and `luna-docs` records only the owned documentation.
QA result labels are exactly **Pass**, **Fail**, **Skipped**, and **Unavailable**. A builder
report, implementation presence, generated artifact, skipped check, provider error, or missing
hardware is not acceptance. Native x86_64, emulated ARM64, and physical ARM64/mobile/
screen-reader/true-zoom evidence must remain separately labelled.

After changing project configuration, profiles, commands, plugins, or `.opencode` dependencies,
restart the parent before discovery or runtime acceptance. With `OPENCODE_DISABLE_PROJECT_CONFIG=1`,
project-profile discovery is **Pending**/**Unavailable**. The real V2 provider probe emitted an
error event without a report and is therefore **Unavailable**, not a provider acceptance result.

Native V2 automatically discovers project skills from directory-based
`.opencode/skills/<id>/SKILL.md` definitions; the `skills` configuration array is for additional
later-precedence sources, so an explicit `.opencode/skills` entry is not expected in
`opencode.json`. The eight approved definitions, `metadata.json`, `alwaysApply: false`,
`.opencode/SKILL-INDEX.md`, the
validator allow-list, and `.opencode/skill-history/learnings.md` are static governance/history
artifacts, not native loader proof. Runtime skill discovery is **Unavailable** here because
`OPENCODE_DISABLE_PROJECT_CONFIG=1`; no runtime loader result is inferred. The active history path
is `.opencode/skill-history/learnings.md`; the former flat
`.opencode/skills/learnings.md` path is retired.

The coordinator's exact CLI rerun returned `opencode v2.0.7` from both `opencode --version` and
`/home/james/.local/opt/opencode-v2/opencode --version`; `/home/james/.local/opt/opencode-v2/opencode debug --help`
listed only `agents`, `config`, and `paths`; and
`printenv OPENCODE_DISABLE_PROJECT_CONFIG` returned `1`. These version/help facts do not establish
skill discovery.

Loader-boundary evidence is separated. Supplied builder static evidence recorded config/docs tests
`73/73`, comment tests `5/5`, validator `9` categories/`13` topics/`7` governance entries,
documentation self-test `26/26`, completeness `111` mapped files, and dirty-tree coverage `154`
inputs/`0` violations, with Ruff/security/comment audit `203` files plus JSON/frontmatter,
shell-syntax, and diff checks **Pass**. Independent Luna QA passed the static loader-boundary
scope on native x86_64 at dirty revision `09ba8b8dd285bd64c34241069051936c82c6390b`: exactly seven
directory `SKILL.md` files, no flat skill files, history-path migration, no explicit skills config,
retired Ponytail absence, and docs/map semantics **Pass**. This is independent static QA, not
native runtime discovery, provider runtime, release, or clean-scope acceptance; clean-scope proof
remains **Unavailable** because of the broad pre-existing dirty worktree, and no provider runtime
or service restart was invoked.

Ponytail is retired from the current tree and workflow. No package, plugin, dependency pin,
command, boundary review, or smoke check is current. The retained Ponytail reports are historical
overengineering-only evidence and cannot substitute for correctness, security, accessibility,
performance, or release evidence.

The documentation gate is separate and fail-closed. Run the validator, completeness checker,
change-aware checker, isolated self-test, and scoped `git diff --check` as applicable; do not
install hooks or treat the hook's presence as a check result.

The approved project governance set has eight directory-based definitions and no Ponytail skill.
This static count is not native loader/discovery acceptance. The provider/model runtime probe
remains **Unavailable** when it reports `provider.quota`, `Insufficient Balance`, and HTTP `402`;
no runtime, loader, or provider acceptance is claimed from that failure.

## Current research-workspace QA (`R-ASTRA-98`)

The post-reconciliation aggregate command was
`TMPDIR=/home/james/.cache/stock-probs-gate-tmp TASK_ID=R-ASTRA-98 ./scripts/local-gate.sh check`.
Its native-x86_64 receipt at dirty revision `09ba8b8dd285bd64c34241069051936c82c6390b` ran
`2026-09-18T15:47:01Z`–`2026-09-18T15:53:58Z`, **Passed** with exit `0`, and recorded `545`
Python tests passed, `4` deselected, no skipped test reported, and `90.38%` coverage. Frontend
checks passed `17/17`, including typecheck and the Next production build; static routes include
`/`, `/api-docs`, `/overview`, `/research`, `/tools`, `/tools/forecast`, `/tools/live-trading`,
and `/tools/markets`. Completed checks were `documentation-completeness`,
`frontend-npm-ci-typecheck-build-test-stage`, and `python-checks`. The tracked receipt is
`test-results/local-gates/R-ASTRA-98-20260918T154701Z/evidence.json`.

Separate supplied backend QA passed `240` tests. Browser QA passed `4/4` desktop/mobile-emulated
cases with axe `0/0`; live Yahoo checks covered `ACDC`, `SPY`, `SHOP.TO`, `VFV.TO`, and `PNG.V`.
The browser artifact is temporary: `/tmp/opencode/r-astra-98-browser-final-pass`. Native ARM64,
physical mobile, true browser zoom, and actual screen-reader acceptance remain **Unavailable**.
The recorded aggregate is scoped dirty-worktree evidence; it does not itself establish
release/export/commit/push acceptance.

## Run local checks

Bootstrap the pinned development environment:

```bash
./scripts/bootstrap.sh
```

Run the focused checks appropriate to the changed feature:

```bash
.dev-venv/bin/python -m pytest -m "not live"
.dev-venv/bin/python -m ruff check src tests scripts
.dev-venv/bin/python -m mypy src/stock_probs/backup.py src/stock_probs/cli.py
.dev-venv/bin/python scripts/validate_docs.py
./scripts/build-frontend.sh
```

Python tests use temporary databases and injected fixtures. Tests marked `live` contact Yahoo
Finance and are excluded from deterministic gates; a skipped or unavailable provider is not a
pass. Run checked-in isolated browser regressions with `make browser-test`, and the official
headless MCP interaction with `make mcp-smoke`. `scripts/local-gate.sh` provides the fail-closed
aggregate and records revision, architecture and results; a builder run is not independent QA.

The frontend build exports the pinned Next App Router UI and stages it for FastAPI; it does not
start a Next server. The served candidate contains 48 generated files and four authored assets.
Node remains build-only in the container, while the candidate OpenCode/Bun assistant worker runs
privately in that same application container. Keep native runtime checks separate from static
frontend and synthetic fixture checks.

## Assistant verification (`R-ASTRA-120`)

Use focused checks to isolate their boundaries. `tests/test_assistant_delete_session_boundary.py`
checks live-session revalidation around conversation deletion. `tests/test_assistant_native_harness_lifecycle_flows.py`
uses synthetic OpenCode HTTP responses; it does not run the native runtime. The provider-admin
API-flow tests use manager stubs, while `tests/test_assistant_provider_real_manager_http_flows.py`
uses the real `AssistantProviderManager`, a disposable encrypted vault, and public HTTP routes with
synthetic or mocked vendor, native-runtime, and model-catalog inputs. Assistant-help capture,
render, and finalization tests exercise those helpers; they do not establish app accessibility or
final PR-bound guide acceptance. A focused test or synthetic run establishes only its declared
scope, not live provider, native OpenCode, production, or release acceptance.

The supervised native probe retains only normalized diagnostics. Model-discovery warnings use
closed outcome names and bounded numeric counters for catalog reads and the activation barrier;
raw log text, request URLs and owner identifiers are excluded. The existing limits remain four
distinct warning rows and 512 occurrences, with counter and elapsed-time bounds. These rows can
identify the failing stage; they do not establish a timeout cause, correlate an anonymous row to
an owner, or waive the 120-second turn deadline and shared eight-call limit. Host-probe changes
need fresh hash bindings and independent checks, separately from the application image.

The candidate timing schema v5 adds nullable `pre_session_phase` and
`pre_session_failure_code` fields to the existing anonymous terminal row. Values come from closed
allow-lists and are held in the private execution/owner context until that row is emitted. A
pre-session failure cannot coexist with provider request rows, a completed workspace summary, or
a completed terminal status. The host parser preserves older timing schemas and rejects missing,
forged, or contradictory v5 fields. These classifications distinguish the failed boundary; they
do not prove its cause or establish native execution acceptance. No credentials, prompts, native
identifiers, or owner identifiers belong in the retained projection.

R-ASTRA-120 remains in progress, and its assistant candidate is disabled in production. E662's
latest canonical check **Failed** on two supervisor-test AF_UNIX socket paths that exceeded the
Linux path limit before child spawn (2,672 tests, 2 failures, 4 skips, 0 errors). E663's selected
short-`TMPDIR` reproduction passed 2/2 only; it does not replace the failed aggregate. The later
OAuth callback repair passed its selected independent 14-test/source-review scope, but the full
canonical gate has not been rerun on those modified files. The tracked guide renderer's source
review passed. Its initial test review **Failed** on a P2 finding because the test flattened PDF
structure leaves without asserting per-block boundaries or order. The test-only correction then
passed independent source/test review and TAP reported 17/17, but the numeric command exit is
**Unavailable** in that first repair attempt. E673 independently reran the exact command with exit 0
and 17/17; it supersedes only that missing-exit result. E665's private PDF artifact passed
exact-structure review, but that does not accept current maintained output; fresh rendering remains
pending. Native runtime/provider, strict app
accessibility, actual combined 1 GB resources, complete security, PR-bound rollback, final guide,
and release acceptance remain open. Use the
[authoritative R-ASTRA-120 ledger](../../MVP-PLAN.md#r-astra-120-signal-ledger-assistant-design-first-follow-on)
for current receipts and preserved result statuses.

### Binding browser evidence to the served frontend

Before browser QA or screenshot/capture evidence is claimed for the current frontend, run the full
approved `./scripts/build-frontend.sh` build-and-stage path and verify that every file FastAPI serves
matches the current `frontend/out` export byte for byte: compare all 48 generated Next files and all
four authored `/assets` files (52 served files total) against their matching export paths. An
npm/Next build alone does not prove which bundle the app serves. If any file differs, label results
as stale-stage evidence, rebuild and stage, then rerun the affected browser checks and captures.
The build/stage evidence is recorded in the R-ASTRA-120 ledger. A successful build/stage check alone
is not browser acceptance.

The Playwright journeys emulate system color preference and storage failure, switch among
light/dark/system on both local pages, and exercise print, reduced-motion, forced-colors, CSP, and
contrast behavior. News routes are fixture-fulfilled for not-requested, loading, fresh, empty,
partial, stale, provider-failure, local-unreachable, capacity-busy, and superseded states. The
mixed-feature journey changes theme, runs a forecast, expands from five to ten headlines, checks
local-only application requests and ledger exclusion, then reopens the saved forecast without an
automatic news request.

The M09 local performance profile records theme action, news cache-hit endpoint, ten-item render,
response-byte, and provider-deadline evidence alongside forecast concurrency and process-resource
rows. This is aggregate mixed-load evidence; do not describe the forecast-concurrency row as
simultaneous news traffic unless an artifact actually drives both. Pinned provider-feasibility
evidence and opt-in ACDC/SPY live-news probes remain separate from the deterministic suite; record
their command, environment, UTC, revision, result, and provider availability, and never convert an
unavailable live run into a pass.

## Historical application gate receipt (preserved)

Any Ponytail wording in this receipt is historical and does not describe a current check.

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
