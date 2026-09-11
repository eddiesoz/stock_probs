# Stock Probability

Local, auditable stock-probability research for selected Yahoo Finance stocks and ETFs. The product is a loopback-first Linux app, not a public hosted service or trading system.

## Evidence-Backed Status

As of 2026-09-11, this repository is an implementation-shaped local Linux stock-probability app under evidence-controlled delivery. The support contract is Linux x86-64/amd64 and ARM64/aarch64. The current host is native x86_64; no native ARM64 or physical ARM64 performance result is claimed. Source presence and generated local artifacts are not proof that behavior works.

- `R-M00-1` is **Completed** as immutable historical documentation recovery; it accepts no implementation behavior.
- `R-M00-2` is **Completed** for this documentation-only policy repair. It does not accept implementation, perform QA, create the walkthrough, export, commit, or push.
- `M00` is **Completed**, documentation baseline only.
- `EXP-M00` is **Completed** as the M00 coordinator export checkpoint. Its exact parsed-export, secret-review, commit, push, and remote-revision evidence is recorded below.
- `M01` and `EXP-M01` are **Completed**: `R-M01-3` through `R-M01-15` have independent scoped pass records and the checkpoint is verified at exact SHA `5424fa3e22d9229d038d376512e59b3f35c97e78`.
- `M02` is **In progress**, not completed: all recorded M02 behavior scopes have independent pass evidence, but `EXP-M02` secret review, export, commit, push, and exact remote-revision evidence are still pending. `M03` remains **In progress** with its own later acceptance record still open.
- `M04`, `M05`, and `M06` are **Blocked**, not completed: their recovered records retain failed findings, cancelled retests, collision aliases, or missing evidence.
- `M07`, `M08`, `EXP-M02` through `EXP-M08`, `ASTRA-FINAL`, and `EXP-FINAL` are **Pending**; `EXP-M01` is completed as recorded below.
- This documentation gate does not rerun implementation QA/builds, edit implementation files, create a walkthrough artifact, export `SESSION-EXPORT.md`, commit, push, or verify a new Git revision. It records the supplied parent-session M02 evidence; no unavailable check is represented as passed.

The exploratory scripts and local environments remain development material. Do not present a test file, browser report, `.coverage`, database, `.venv/`, `.dev-venv/`, or `burry_env/` as release evidence.

## Local-Only Architecture And Gate Policy

- All testing and verification is local. Native x86-64/amd64 is the current Linux environment.
- ARM64/aarch64 verification first uses local native ARM64 hardware if it becomes available. Otherwise local QEMU or OCI multi-arch execution may verify package/build/runtime portability and functional/tool behavior. Every such result must say **emulated ARM64**; it is not native or physical ARM64 evidence and cannot prove performance on the original low-resource laptop.
- ARM64 functional, build, browser, and tool checks may therefore use local emulation under the no-host constraint. Physical low-resource ARM64 performance remains `Unavailable` until native ARM64 hardware is measured and must be disclosed, never inferred.
- No GitHub Actions, hosted runner, or external pipeline is an acceptance mechanism. `EXP-M01` verified `.github/workflows/ci.yml` absent on the remote revision at SHA `5424fa3e22d9229d038d376512e59b3f35c97e78`; local fail-closed Make/scripts are the replacement for that former role.
- Git versioning is still required: each export checkpoint is locally reviewed, committed, pushed to the configured Git remote, and verified at the exact pushed revision. A missing or failed export, secret review, commit, push, or Git remote revision verification remains visible and blocks that checkpoint.

## Observed Repository Shape

These are implementation observations for the next evidence pass, not completion claims:

- `src/stock_probs/` contains the FastAPI boundary, domain/provider/service layers, SQLite repository and migration, backup manager, CLI, fixtures, and static dashboard.
- `tests/` contains deterministic API, domain, provider, persistence/backup, configuration, resource, and opt-in live checks.
- `tools/browser/` contains serial desktop/mobile Playwright scenarios, accessibility checks, MCP smoke support, and bounded runtime configuration.
- `opencode.json`, `.opencode/`, `scripts/`, and `Makefile` describe local operation and tooling. Any legacy workflow path is subject to the M01/M06 removal requirement above.

No implementation milestone may be marked `Completed` from these observations.

## M00 Chronology, Recovered Evidence, And Current Checkpoint

`R-M00-1` recovered an earlier incomplete export; it remains immutable historical context. The coordinator subsequently completed the current `EXP-M00` checkpoint before the M01 build wave. The current checkpoint is not inferred from the older export or from implementation claims.

### `EXP-M00` completed checkpoint

- **Status:** `Completed`.
- **Owner/phase:** coordinator export gate; reviewer/coordinator `OpenCode gpt-5.6-sol`.
- **Dependencies verified:** `R-M00-1` and `R-M00-2`; the M00 documentation baseline was in place before this export.
- **Export evidence:** active session `ses_f71ec0499ffeokWj4h6tVwyYk1` parsed as JSON: `1,413,943` bytes, `4,268` physical lines, `23` messages, `153` parts, `44` tool parts, and `10` task outputs.
- **Secret review:** full regex review found two credential-like candidates; both were masked. No private-key, AWS, GitHub-token, or Bearer-credential patterns were found. Result: **Pass**.
- **Git evidence:** diff/check review passed; the reviewed export was committed and pushed at exact SHA `18da1af0b6bc31020d3587e472b8197146795bf1`; `git ls-remote origin refs/heads/main` matched that SHA. No remote CI was used.
- **Limitations:** the handoff does not supply an exact UTC completion timestamp; that missing field remains visible rather than invented. The unrelated `?? .vscode/` stayed untouched.
- **Next gate:** `M01`, followed by `EXP-M01`; M01 changes are not included in the `EXP-M00` checkpoint.

The recovered pre-checkpoint export is recorded as valid parsed JSON: `5,065,391` bytes, `11,093` physical lines, `80` top-level messages, and `384` parts. It contains parent task calls and summarized handoffs, not complete child transcripts. Its historical records use session `ses_f73b976e8ffekNCE6SNIanpXFb`, `/home/eddie/stock_probs`, historical `HEAD cb7c1b1`, and an uncommitted working tree. It is not the current completed checkpoint:

- `M01`–`M04` QA task `ses_f72f4e2f0ffe6hMpBTmXUnWybW` found `R-M03-1`, `R-M03-2`, `R-M01-1`, and `R-M01-2` blockers.
- `M04`/`M06` QA task `ses_f72f4e261ffeLWQEjyJI4k3hea` reported passing exercised browser/MCP/API checks, but did not accept the milestones.
- `M05`/`M06` QA task `ses_f72f4e163ffehgqJPXwbY7ujrX` reported `Blocked` with `R-M05-1` through `R-M05-4` and `R-M06-1`.
- Repair `ses_f72c4f276ffeJm9WRj0aBXCM1X` and independent retest `ses_f72ab5097ffexdJCun6m6thzDi` passed the named `R-M03-1`, `R-M03-2`, and `R-M05-3` checks.
- Correct repair-builder IDs are `ses_f72c4f20effeDoLPC0FuHaaGjZ` and `ses_f72c4f1baffeECZSQ37ujzSmCJ`. The independent retest `ses_f72ab5027ffeR0shgnOsYGX47N` for the first builder's named repairs was cancelled; no builder claim substitutes for that retest.
- Late backup retest `ses_f72ab4fc9ffepKCTOlUxIWlRrt` reported `make check` **Pass**, 83 tests, and 89.23% coverage, plus named backup/restore checks. The earlier concurrent aggregate-check limitation is historical context, not a current unresolved failure.
- The recovered pre-checkpoint `EXP-M00` attempt ends with `opencode export ses_f73b976e8ffekNCE6SNIanpXFb > SESSION-EXPORT.md` recorded as `running`; its exact full secret-review/export-revision evidence is absent. That historical record is superseded for current M00 chronology by the completed checkpoint above; its old commit/push fields remain unavailable.
- The old GitHub Actions run [34549899644](https://github.com/eddiesoz/stock_probs/actions/runs/34549899644), recorded by the earlier documentation, is obsolete x64-only historical context. It is not a current gate, release proof, ARM64 evidence, or substitute for local checks.

### Historical collision aliases

Historical labels are immutable. `R-M00-1` allocated fresh, unique records. The M01 records `R-M01-3` and `R-M01-4` have since received independent scoped pass evidence; the later M04/M05/M06 obligations remain pending:

| Historical collision | Fresh repair ID | Obligation | Current state |
| --- | --- | --- | --- |
| `R-M01-1` in QA `ses_f72f4e2f0ffe6hMpBTmXUnWybW` vs builder `ses_f72c4f20effeDoLPC0FuHaaGjZ` | `R-M01-3`, `R-M01-4` | Router error/OpenAPI retest; startup-harness retest | **Completed** in scoped M01 retests; `EXP-M01` checkpoint completed |
| `R-M05-1` in QA `ses_f72f4e163ffehgqJPXwbY7ujrX` vs builder `ses_f72c4f1baffeECZSQ37ujzSmCJ` | `R-M05-5`, `R-M05-6` | Malicious-artifact retest; chunked-request/resource retest | **Pending** |
| `R-M06-1` in QA `ses_f72f4e163ffehgqJPXwbY7ujrX` vs builder `ses_f72c4f20effeDoLPC0FuHaaGjZ` | `R-M06-2`, `R-M06-3`, `R-M06-4` | Port-collision, CSP, and CSV-safety retests | **Pending** |
| `R-M04-1` in browser/accessibility `ses_f72f4e261ffeLWQEjyJI4k3hea` vs builder `ses_f72c4f20effeDoLPC0FuHaaGjZ` | `R-M04-2`, `R-M04-3` | Separate actual assistive-technology evidence; mobile-focus retest | **Pending** |

The screen-reader/assistive-technology evidence remains separately unavailable for later M04/M06 work. The full source-qualified register and current M01 task fields are in `MVP-PLAN.md` and `MVP-ROADMAP.md`.

## Current M01 Evidence Record

`M01` is **Completed**. The three builder reports and all three independent QA retests were received, but builder checks remain implementation handoffs rather than independent acceptance. The M01 changes after the completed `EXP-M00` checkpoint were committed and pushed through `EXP-M01`; the exact remote checkpoint is SHA `5424fa3e22d9229d038d376512e59b3f35c97e78`.

### Builder handoffs

| Lane/task | Repair handoff | Recorded implementation paths and change summary | Acceptance meaning |
| --- | --- | --- | --- |
| `SOL HIGH-A`, `ses_f718d04e0ffeqdv2i56c6k72Pg` | `ses_f71674730ffeERY2M1p9htV2Or` | `pyproject.toml`, `requirements.lock`; `src/stock_probs/api.py`, `cli.py`, `config.py`, `schemas.py`, `service.py`; `tests/test_api.py`, `tests/test_config_quality.py`. Transport/application schemas, errors, startup/configuration, package metadata, and application-shell tests were changed; executable Python support metadata is `>=3.11,<3.12`. | Handoff received; builder checks are not independent acceptance. |
| `SOL HIGH-B`, `ses_f718d04a2ffexmhN4OlHuJlTwt` | `ses_f716746fbffe9qOSoMniDzfbNi` | `src/stock_probs/domain.py`, `provider.py`, `repository.py`, `fixtures/acdc.json`, `fixtures/spy.json`; `tests/test_domain.py`, `test_provider.py`, `test_repository_backup.py`. Domain/provider identity and server-side persistence interfaces were changed. | Handoff received; builder checks are not independent acceptance. |
| `SOL HIGH-C`, `ses_f718d0469ffeVig2Xix5cE5N1V` | `ses_f716746e8ffeEjA0BRqajZ0ycH` | Deleted `.github/workflows/ci.yml` and `scripts/install-node-arm64.sh`; changed `.opencode/agent/sol-build.md`, `Makefile`, `src/stock_probs/static/app.css`, `app.js`, `index.html`, `tests/test_live.py`, `test_resource.py`, `tools/browser/package-lock.json`, `playwright.config.js`, `tests/dashboard.spec.js`; added `scripts/arm64-smoke.sh`, `bootstrap.sh`, `compose.arm64.yml`, `install-node.sh`, `local-gate.sh`, `package_smoke.py`, and `run-arm64-container.sh`. Local gates, package/bootstrap paths, presentation, browser tooling, and operations were changed. | Handoff received; builder checks are not independent acceptance. |

### Independent QA retests

| Evidence/task | Exact check result | Environment/time/artifact | Result and limitation |
| --- | --- | --- | --- |
| `M01-QA1`, `ses_f71521f9dffeWxILBgUaEBhf0O` | `R-M01-3` through `R-M01-7` passed in scope; `167/167` harness checks; `100` non-live passed, `4` deselected, `89.17%`; Ruff+S, strict mypy for all 12 production files, 51 comments, compile, and shell checks passed. | Native x86_64; completed `2026-09-11T04:27:31Z`; `/tmp/opencode/stock_probs-m01-qa`. | **Pass** for this lane. Live, browser, ARM, and export checks were skipped in this lane only; the skips are not hidden or promoted to passes. |
| `M01-QA2`, `ses_f71521f5effeKu8HF2uh3fxJT1` | Native x86 bootstrap with Python `3.11.15`; direct no-`make` local gate; clean non-edit x86 wheel install, migration, and loopback; deliberate safe failure exited nonzero and recorded `Fail`; Node x64/arm64 checksums; OpenCode schema/config/MCP connection; emulated ARM64 OCI/QEMU `7.2.0` package/install/migration/loopback; cleanup passed. | Native x86_64 plus explicitly **emulated ARM64**; completion UTC not supplied in the consumed record; artifacts under `test-results/local-gates` and `test-results/arm64`. | **Pass** for assigned `R-M01-8` through `R-M01-13` evidence. No native/physical ARM64 or performance result. The stale-export labels `R-M01-16` through `R-M01-19` were not authoritative and were not created; their evidence is recorded under `R-M01-8` through `R-M01-13`. |
| `M01-QA3`, `ses_f71521efbffeEdTmM7GL4wYmW2` | No product defects; `R-M01-14`/`R-M01-15` and browser `R-M01-3`/`R-M01-4` passed; checked-in browser `6` desktop + `6` mobile scenarios; 360/390/768/1280/1440 had no overflow; company lookup and stock/ETF identities were correct; 53 fetch/XHR requests used `/api/v1` with no forbidden access or leaks; structured errors/docs/OpenAPI/console and official MCP actual interaction passed. | Native x86_64; latest artifact timestamp `2026-09-11T04:35:01.820Z`; artifacts under `/tmp/opencode/m01qa-*`. | **Pass** for this lane. Screen-reader and later visual/accessibility polish remain M04/M06 requirements. |

### M01 repair and checkpoint register

| Repair/task ID | Independent evidence and scoped state |
| --- | --- |
| `R-M01-3` | Router error/OpenAPI scoped retest; passed in `M01-QA1` and browser/API checks in `M01-QA3`. **Completed** for this behavior. |
| `R-M01-4` | Startup/launch-harness scoped retest; passed in `M01-QA1` and `M01-QA3`. **Completed** for this behavior. |
| `R-M01-5`–`R-M01-7` | Coordinator-assigned M01 repair rows; `M01-QA1` passed all three in scope. **Completed** for the assigned behaviors; no new IDs inferred. |
| `R-M01-8`–`R-M01-13` | Coordinator-authoritative package/bootstrap, direct local-gate, clean-install/migration/loopback, checksum, OpenCode/MCP, and emulated-ARM64 checks; `M01-QA2` passed. **Completed** for the assigned behaviors. |
| `R-M01-14`–`R-M01-15` | Coordinator-assigned QA3 M01 repair rows; `M01-QA3` passed its recorded browser/API/identity/error/docs/OpenAPI/console/MCP scopes. **Completed** for the assigned behaviors. |
| `EXP-M01` | Full export, secret review, local commit/push, exact remote revision, and remote `.github/workflows/ci.yml` absence are evidenced below. **Completed**. |

The host has no system `make`; the direct executable local-gate path passed and the `Makefile` remains a convenience wrapper. `EXP-M01` verified the workflow path absent on the remote checkpoint. M01 evidence is native x86_64 plus explicitly emulated ARM64 functional/tool evidence only; no physical/native ARM64 result or performance claim is made. The unrelated `?? .vscode/` remained untouched.

### `EXP-M01` completed checkpoint

- **Status:** `Completed`.
- **Owner/phase:** coordinator export gate; the consumed handoff did not provide a separate named export reviewer or exact UTC completion timestamp, so neither is invented here.
- **Dependencies verified:** M01's independent QA records and `R-M01-3` through `R-M01-15` scoped pass records.
- **Export evidence:** active session `ses_f71ec0499ffeokWj4h6tVwyYk1` parsed as JSON: `8,791,084` bytes, `6,904` physical lines, `34` messages, `241` parts, `70` tools, and `23` task outputs. Result: **Pass**.
- **Secret review:** four credential-like candidates were found and all four were masked. No private-key, AWS, GitHub, Bearer, or credential-URL pattern was found. Result: **Pass**.
- **Git and workflow evidence:** the reviewed export was committed and pushed; exact SHA `5424fa3e22d9229d038d376512e59b3f35c97e78` matched the verified remote revision, and `.github/workflows/ci.yml` was absent there. Result: **Pass**.
- **Scope and limitations:** the unrelated `?? .vscode/` remained untouched; no pipeline run was used. M01's ARM64 evidence is explicitly emulated functional/tool evidence, not native/physical ARM64 or physical low-resource performance evidence.

## Current M02 Evidence Record

`M02` is **In progress** only because its next checkpoint, `EXP-M02`, still needs secret review, export, local commit, push, and exact remote-revision verification. The scoped implementation and independent QA records below are complete; this status does not infer completion from source presence or builder claims.

- **Owner/phase:** three `SOL HIGH build` handoffs, independent `LUNA MAX QA`, then this `LUNA MAX docs` reconciliation.
- **Dependencies verified:** completed M01 and `EXP-M01` at SHA `5424fa3e22d9229d038d376512e59b3f35c97e78`.
- **Implementation summary:** the wave added additive migration `002`, searchable audit/history behavior, immutable saved-result reopen versus separately labelled fresh historical-cutoff reconstruction, append-only outcomes, CSV/JSON export, and the local M02 gate. Later repair work added the migration `003` package-resource assertion/guard coverage without rewriting prior migrations.

### M02 builder handoffs

| Lane/task | Reported scope | Acceptance meaning |
| --- | --- | --- |
| `SOL HIGH-A`, `ses_f712f4d58ffePmzI8fAR3Oa7hx` | Transport/history contract, saved and fresh reconstruction behavior, outcomes, and API-facing audit records. | Implementation handoff only; not independent acceptance. |
| `SOL HIGH-B`, `ses_f712f4cf0ffeixu54tZg1FfjNF` | Additive migration `002`, SQLite history/immutability/repository behavior, outcomes, and persistence safeguards. | Implementation handoff only; not independent acceptance. |
| `SOL HIGH-C`, `ses_f712f4be6ffeAetzWX712LvaDP` | History presentation, CSV/JSON surfaces, browser coverage, and the local M02 gate. | Implementation handoff only; not independent acceptance. |

### M02 QA, repairs, and final verification

The initial failures remain visible even though the affected scoped checks later passed. A QA label is not promoted to a repair record unless it was allocated as one; no `R-M02-6`–`R-M02-9` records were created, and the `21`–`29` labels in QA pass evidence were not defect records.

| Evidence/task | Exact scoped evidence | Result and follow-up |
| --- | --- | --- |
| Initial QA lane 1, `ses_f711eb2c2ffe6fXPkurhibBu4h` | Found `R-M02-1`–`R-M02-5`. | **Fail** for the initial findings; the failure is retained in the repair history. |
| Initial QA lane 2, `ses_f711eb2abffeURm1Z1rnq6IbEV` | `R-M02-10`–`R-M02-18` passed; `R-M02-19` failed. | **Pass** for `R-M02-10`–`R-M02-18`; **Fail** for `R-M02-19` initially, later closed by affected retests. |
| Initial QA lane 3, `ses_f711eb297ffeIQIk61tFgYxNzg` | Found `R-M02-20`. | **Fail** initially; later browser evidence passed. |
| First repair handoffs | A `ses_f70f38bb7ffemfzOJYloLsE7E5`; B `ses_f70f38aebffeweicQ3chgjhqlZ`; C `ses_f70f38aa8ffe6KzqqT2WRXU2tP`. | Builder reports only; no acceptance inferred. |
| First repair retest lane 1, `ses_f70e7f1edffewINIkuCL0X1fx7` | `R-M02-1`–`R-M02-5` passed with 145 tests. | **Pass** for that scoped retest. |
| First repair retest lane 2, `ses_f70e7f1d2ffe8yAJlKBozlUrfM` | Found `R-M02-30`–`R-M02-32`. | **Fail** for those affected checks; later repair evidence closed them. |
| First repair browser retest | The consumed parent report gives 22/22 browser checks and `R-M02-20` **Pass**, but does not expose the exact task-ID suffix. | **Pass** for the reported scope; the unavailable ID is not guessed. |
| Public repair handoffs | A `ses_f70d720ceffeGC4hiOT8E0FdOY`; B `ses_f70d720b0ffe0AAxTzi3XR0bhc`; C `ses_f70d7209affeTJuYN3nHckLJ62`. | Builder reports only; no acceptance inferred. |
| Public retest API, `ses_f70ce409cffe8eCWi2miLmvk7a` | Found `R-M02-41`/`R-M02-42`. | **Fail** for those affected checks; later repair evidence closed them. |
| Public retest internal, `ses_f70ce4085ffeE0EHbDVJOiDjCn` | Reported its scoped checks passing. | **Pass**. |
| Public retest browser, `ses_f70ce406effeuaq2z4gcpIzqRw` | Reported its scoped browser checks passing. | **Pass**. |
| Final public repair handoffs | A `ses_f70b8b17effebJj2D5Rvc1JWvu`; C `ses_f70b8b08fffeUR0kriamGTF22l`. The B suffix was not present in the consumed evidence and is intentionally omitted. | Builder reports only; no guessed ID or acceptance inferred. |
| Cumulative QA finding | The consumed report identified `R-M02-55` after the public behavior scopes passed: package smoke's explicit expected-resource assertion omitted migration `003` even though the wheel contained it; its exact task-ID suffix was not present in the consumed evidence. | **Fail** retained and repaired; no task ID is guessed. |
| `R-M02-55` repair handoffs | A `ses_f709e8a91ffeOiE2puIHZT7DT4` and B `ses_f709e8a75ffenSblHiLG1fbcVi` made no change; C `ses_f709e8a51ffekA1umC3iAm3y69` fixed the package migration assertion. | Builder reports only; final QA below is the acceptance evidence. |
| Independent final QA, `ses_f709ae6ddffe1NyppNASrAKnLQ` | Direct gate `R-M02-55`, `2026-09-11T07:37:47Z`–`07:38:46Z`, native x86 Python `3.11.15`; 154 tests, 4 live deselected, `89.04%`; 22 browser checks; official MCP pass; exact migrations/checksum/clean install/readiness-schema-3 checks. | **Pass**; technical acceptance recommended. Artifact: `/tmp/opencode/m02-final-qa-20260911T071347Z`; reviewer: `LUNA MAX QA`. |

### M02 scoped record and safety register

| Exact record(s) | Scoped final state | Independent evidence |
| --- | --- | --- |
| `R-M02-1`–`R-M02-5` | **Completed**. | `ses_f70e7f1edffewINIkuCL0X1fx7`, 145-test retest; final gate regression. |
| `R-M02-10`–`R-M02-18` | **Completed**. | `ses_f711eb2abffeURm1Z1rnq6IbEV` initial pass evidence; final gate regression. |
| `R-M02-19` | **Completed** after its initial **Fail**. | Initial `ses_f711eb2abffeURm1Z1rnq6IbEV` failure remains recorded; affected repair/retest sequence and final gate pass. |
| `R-M02-20` | **Completed** after its initial finding. | Browser retest reported 22/22 and pass; exact browser task ID was unavailable in the consumed handoff and is not invented. |
| `R-M02-30`–`R-M02-32` | **Completed** after the first repair retest found the affected checks. | Later public repair/retest sequence and final gate regression. |
| `R-M02-41`–`R-M02-42` | **Completed** after the public API retest finding. | `ses_f70ce409cffe8eCWi2miLmvk7a` finding, later public repairs, and final gate regression. |
| `R-M02-55` | **Completed**. | `ses_f709ae6ddffe1NyppNASrAKnLQ` direct gate pass. |

The acceptance distinctions are explicit: trusted in-app malformed submissions audit once; hostile pre-routing traffic does not write; the wire parser is outside the app. Raw `REPLACE` is guarded with recursive triggers off, restore uses a process-wide lock per canonical database with no expiry, public backup data is safe and domain-neutral, request IDs remain traceable, and saved reopen never silently recalculates while fresh reconstruction is separately labelled and newly recorded. Physical/native ARM64 and screen-reader evidence are later requirements, not M02 blockers; no remote CI was run or used.

- **Post-milestone gate:** `EXP-M02` is the next gate. It must record the full-session export, secret review, local commit, push, and exact Git remote revision; this documentation update performs none of those operations.

## Planned MVP Contract

The target is a local, loopback-only app for selecting Yahoo Finance stocks and ETFs and reviewing auditable probability forecasts. It must demonstrate:

- Company-name lookup preserving symbol, exchange, stock/ETF asset type, and instrument identity.
- Close-to-close and latest-completed-5-minute-bar-to-close forecasts; an in-progress bar is never treated as completed.
- Explicit up/down/unchanged direction, `+/-1%`, `+/-3%`, `+/-5%`, and `+/-10%` thresholds, conditional gain/loss, and 50/80/95 return and price intervals with definitions, levels, units, as-of time, model/version, and data-quality state.
- Chronological walk-forward evaluation without leakage, baseline comparison, Brier score, reliability/calibration, interval coverage, and rare-event uncertainty.
- Source, session, stale-data, error, limitation, immutable input/result provenance, and Yahoo's approximate 60-day five-minute archive/session limitation.
- Immutable saved-result reopen versus separately labelled fresh historical-cutoff reconstruction.
- Searchable history for successful, failed, and repeated searches; append-only outcomes; no automatic query-history expiry.
- CSV and JSON export; verified non-destructive backup/restore; automatic due/pre-migration backups; retention/disk limits; and secure loopback defaults.

The browser uses FastAPI `/api/v1` for all application data and never opens SQLite, issues SQL, receives a database path, or calls Yahoo Finance directly. The dashboard preserves Signal Ledger direction and tabular numeric hierarchy at 360/390/768/1280/1440 without overlap or overflow; charts have text/table equivalents; all empty/loading/success/repeated/stale/validation/failure states are understandable; reduced motion, WCAG AA, keyboard, and actual assistive-technology evidence are required. Axe and keyboard checks do not substitute for a screen-reader run.

These are acceptance requirements, not claims about the current working tree. Optional dark mode/news are not contract requirements; options trading and public hosting are out of scope. Forecasts are informational research outputs, not investment advice or a guarantee.

## Eventual User And Operator Guide

1. Start the app locally, open its loopback address, and confirm readiness, source/as-of, and data-quality state.
2. Search by symbol or company name; confirm exchange, asset type, and instrument identity before submitting.
3. Review both forecast horizons and why an in-progress five-minute bar was excluded.
4. Read direction, threshold probabilities, conditional gain/loss, 50/80/95 return/price intervals, model/version, units, stale state, provider limitation, and provenance; a probability is not a guarantee.
5. Reopen a saved forecast as an immutable recorded result. Use historical-cutoff reconstruction only as a separately labelled fresh analysis.
6. Filter history for successful, failed, and repeated searches; review chart/table equivalents; append outcomes without changing forecasts.
7. Export selected records as CSV or JSON. Use exposed backup/restore/status controls only after reading their integrity, key, and promotion state.
8. Shut down through the documented local command. For trouble, check readiness, stale/provider state, loopback binding, bounded-resource messages, and the documented restore/key path; do not expose secrets or local paths.

Use pinned manifests and the repository `Makefile`/launch documentation for clean local setup. Never use `burry_env/`, `.venv/`, or another local environment as a dependency declaration or release artifact. Trust keys require documented transfer, rotation, retirement, and backup handling; missing or incorrect keys fail closed.

## Visual, Accessibility, And Walkthrough Direction

The interface keeps the **Signal Ledger** direction: calm high-signal status treatment, polished tabular numeric hierarchy, charts paired with tables/text, and clear provenance rather than decorative trading noise. Every required viewport and state must remain usable with visible focus and reduced motion.

The final `M08` **Instructional Walkthrough** is a required tracked artifact under `docs/walkthrough/` (or an explicitly recorded equivalent). It uses deterministic fixtures, the real local app, and official browser tooling. Prefer a compiled sequence of annotated screenshots when a GIF would be less accessible, too large, or less readable; otherwise provide an accessible animated GIF plus companion Markdown/transcript. It must have numbered steps, captions/alt text/transcript, desktop and mobile coverage, no secrets or local paths, a reproducible local generation command/script (the planned entry point is `make walkthrough`), and a total artifact budget of 20 MiB. Browser QA must exercise actual controls, not a mock narrative.

M08 must cover setup/startup, readiness, symbol/company selection, stock and ETF selection, both forecasts, probability/threshold/interval reading, stale/failure/repeated states, history filters, saved reopen versus fresh reconstruction, CSV and JSON export, outcomes, backup/restore/status when exposed in the UI, accessibility/keyboard/mobile use, and shutdown/troubleshooting. After the artifact exists, its retrospective must compare the shipped app with the original prompt and original approved plan recovered from `SESSION-EXPORT.md`, enumerate missing or materially altered features, assess whether the UI is beautiful, well designed, and usable using evidence/artifacts, and create and close `R-M08-<n>` repairs before Astra when gaps exist.

## Required Future Workflow And Checkpoints

All future work uses exactly three concurrent `SOL HIGH build` instances: A transport/application/package, B domain/provider/persistence/backup, and C presentation/browser/operations/local tooling. Any unlisted implementation/config/test path is assigned before work starts. The four docs belong to `LUNA MAX docs`; `SESSION-EXPORT.md` belongs to its export gate. Builders report exact task ID, paths, checks, failures, and assumptions before independent `LUNA MAX QA` and `LUNA MAX docs` gates run.

The canonical sequence is `R-M00-1` -> `EXP-M00` (**Completed**, checkpoint `18da1af0b6bc31020d3587e472b8197146795bf1`) -> `M01` (**Completed**) -> `EXP-M01` (**Completed**, checkpoint `5424fa3e22d9229d038d376512e59b3f35c97e78`) -> `M02` (**In progress**) -> `EXP-M02` (**next gate**) -> ... -> `M06`/`EXP-M06` -> `M07` QA/docs -> `EXP-M07` -> `M08` walkthrough QA/docs -> `ASTRA-FINAL` -> repairs/retests until the result is `Accepted` -> `EXP-M08` -> `EXP-FINAL`. M08 is the final roadmap milestone before Astra. Astra must review the walkthrough artifact, its actual-control browser evidence, and the retrospective before final acceptance.

Each `EXP-M00` through `EXP-M08` overwrites the one tracked full-session `SESSION-EXPORT.md`, receives a complete secret review, and records the export revision, local commit, pushed branch, exact Git remote revision verification, artifact/link, UTC timestamp, environment, and named reviewer. `EXP-M00` has the completed evidence above; its handoff did not supply an exact UTC completion timestamp, which remains a visible limitation. A failed, skipped, unavailable, or connectivity-blocked export/review/commit/push/revision check remains visible and blocks that checkpoint. No external pipeline or hosted runner may fill any field.

## Evidence Record Minimum

Every record uses an exact task ID (`M00`–`M08`, `R-M##-<n>`, `EXP-M00`–`EXP-M08`, `ASTRA-FINAL`, `R-ASTRA-<n>`, or `EXP-FINAL`) and includes:

- status exactly `Pending`, `In progress`, `Blocked`, or `Completed`;
- owner/phase, verified dependencies, and change summary;
- one evidence row per requirement with evidence ID, check/command, environment, UTC timestamp, commit, result (`Pass`, `Fail`, `Skipped`, or `Unavailable`), artifact/link, and reviewer;
- repair history, limitations, export/revision, secret review, local commit/push, Git remote revision result, and named reviewer.

### `R-M00-2` documentation-only record

- **Status:** `Completed` for this four-document policy reconciliation only; no implementation acceptance.
- **Owner/phase:** `LUNA MAX docs`, M00 documentation repair.
- **Dependencies verified:** immutable historical `R-M00-1`; no implementation dependency was accepted.
- **Change summary:** removed external-pipeline acceptance language; defined local-only testing and honest ARM64 emulation semantics; required M01/M06 workflow removal and local fail-closed Make/scripts; added M08/`EXP-M08`, walkthrough, retrospective, and Astra ordering; corrected stale M05 wording; expanded exact task vocabulary. No implementation/config/test path and no `SESSION-EXPORT.md` path was edited.
- **Evidence:** `R-M00-2-E1` — final `git status`/`git diff` four-file scope review, **Pass** for documentation scope; `?? .vscode/` remains untouched. `R-M00-2-E2` — document self-review against the requested local-only, ARM64, M08, sequence, vocabulary, and M05 requirements, **Pass** as documentation content; no implementation QA was run. `R-M00-2-E3` — actual workflow removal, local gate execution, M08 artifact generation, browser QA, and retrospective were **Unavailable** to that docs-only task; current `EXP-M01` separately records the later workflow check, while the other items remain future evidence. `R-M00-2-E4` — R-M00-1 identity/history and collision aliases retained, **Pass** as documentation content.
- **Limitations:** no implementation behavior, local test result, native ARM64 result, emulated ARM64 run, walkthrough artifact, browser-control check, retrospective, export, commit, push, or new Git remote verification was performed here.
- **Export/Git/reviewer:** At the time of `R-M00-2`, no export, commit, or push was performed by that documentation-only repair. The later coordinator records `EXP-M00` and `EXP-M01` are now **Completed** at the exact checkpoint SHAs recorded above; `EXP-M02` through `EXP-M08` and `EXP-FINAL` remain pending. Reviewer for `R-M00-2`: `LUNA MAX docs` self-review; independent implementation QA was not performed by that historical docs repair.

`R-M00-1` remains immutable historical context; its old external-pipeline wording is superseded by this `R-M00-2` policy and cannot be used as current acceptance evidence. The detailed contract, milestone rows, collision register, and Astra matrix are in `MVP-PLAN.md` and `MVP-ROADMAP.md`; compact operating rules are in `AGENTS.md`.

## Local Development Guidance

The `Makefile` and pinned manifests are candidate operational paths until their exact local task evidence exists. The current host lacks system `make`; M01's direct executable local-gate path passed, while the `Makefile` remains a convenience wrapper and is not silently represented as executed. Local fail-closed commands must identify task and commit context, stop on a failing check, and never depend on `burry_env/` or `.venv/`. Local artifacts are not release evidence until their task record names the command, environment, timestamp, result, artifact, limitation, and reviewer.
