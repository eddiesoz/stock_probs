# Stock Probability

Local, auditable stock-probability research for selected Yahoo Finance stocks and ETFs. The product is a loopback-first Linux app, not a public hosted service or trading system.

## Evidence-Backed Status

As of 2026-09-10, this repository is an implementation-shaped local Linux stock-probability app under evidence-controlled delivery. The support contract is Linux x86-64/amd64 and ARM64/aarch64. The current host is native x86_64; no native ARM64 or physical ARM64 performance result is claimed. Source presence and generated local artifacts are not proof that behavior works.

- `R-M00-1` is **Completed** as immutable historical documentation recovery; it accepts no implementation behavior.
- `R-M00-2` is **Completed** for this documentation-only policy repair. It does not accept implementation, perform QA, create the walkthrough, export, commit, or push.
- `M00` is **Completed**, documentation baseline only.
- `M02` and `M03` are **In progress**, not completed: partial historical checks exist, but complete acceptance records and local release checkpoints are absent.
- `M01`, `M04`, `M05`, and `M06` are **Blocked**, not completed: the recovered record includes failed findings, a cancelled retest, collision aliases, or missing evidence.
- `M07`, `M08`, `ASTRA-FINAL`, `EXP-M00` through `EXP-M08`, and `EXP-FINAL` are **Pending**.
- This task does not run implementation QA, remove implementation files, create a walkthrough artifact, export `SESSION-EXPORT.md`, commit, push, or verify a new Git revision. No unavailable check is represented as passed.

The exploratory scripts and local environments remain development material. Do not present a test file, browser report, `.coverage`, database, `.venv/`, `.dev-venv/`, or `burry_env/` as release evidence.

## Local-Only Architecture And Gate Policy

- All testing and verification is local. Native x86-64/amd64 is the current Linux environment.
- ARM64/aarch64 verification first uses local native ARM64 hardware if it becomes available. Otherwise local QEMU or OCI multi-arch execution may verify package/build/runtime portability and functional/tool behavior. Every such result must say **emulated ARM64**; it is not native or physical ARM64 evidence and cannot prove performance on the original low-resource laptop.
- ARM64 functional, build, browser, and tool checks may therefore use local emulation under the no-host constraint. Physical low-resource ARM64 performance remains `Unavailable` until native ARM64 hardware is measured and must be disclosed, never inferred.
- No GitHub Actions, hosted runner, or external pipeline is an acceptance mechanism. If `.github/workflows/ci.yml` exists, M01/M06 must remove it; local fail-closed Make/scripts are the only replacement for that former role.
- Git versioning is still required: each export checkpoint is locally reviewed, committed, pushed to the configured Git remote, and verified at the exact pushed revision. A missing or failed export, secret review, commit, push, or Git remote revision verification remains visible and blocks that checkpoint.

## Observed Repository Shape

These are implementation observations for the next evidence pass, not completion claims:

- `src/stock_probs/` contains the FastAPI boundary, domain/provider/service layers, SQLite repository and migration, backup manager, CLI, fixtures, and static dashboard.
- `tests/` contains deterministic API, domain, provider, persistence/backup, configuration, resource, and opt-in live checks.
- `tools/browser/` contains serial desktop/mobile Playwright scenarios, accessibility checks, MCP smoke support, and bounded runtime configuration.
- `opencode.json`, `.opencode/`, `scripts/`, and `Makefile` describe local operation and tooling. Any legacy workflow path is subject to the M01/M06 removal requirement above.

No implementation milestone may be marked `Completed` from these observations.

## Recovered Evidence, Not Release Acceptance

The root `SESSION-EXPORT.md` is recorded as valid parsed JSON: `5,065,391` bytes, `11,093` physical lines, `80` top-level messages, and `384` parts. It contains parent task calls and summarized handoffs, not complete child transcripts. Its historical records use session `ses_f73b976e8ffekNCE6SNIanpXFb`, `/home/eddie/stock_probs`, historical `HEAD cb7c1b1`, and an uncommitted working tree:

- `M01`–`M04` QA task `ses_f72f4e2f0ffe6hMpBTmXUnWybW` found `R-M03-1`, `R-M03-2`, `R-M01-1`, and `R-M01-2` blockers.
- `M04`/`M06` QA task `ses_f72f4e261ffeLWQEjyJI4k3hea` reported passing exercised browser/MCP/API checks, but did not accept the milestones.
- `M05`/`M06` QA task `ses_f72f4e163ffehgqJPXwbY7ujrX` reported `Blocked` with `R-M05-1` through `R-M05-4` and `R-M06-1`.
- Repair `ses_f72c4f276ffeJm9WRj0aBXCM1X` and independent retest `ses_f72ab5097ffexdJCun6m6thzDi` passed the named `R-M03-1`, `R-M03-2`, and `R-M05-3` checks.
- Correct repair-builder IDs are `ses_f72c4f20effeDoLPC0FuHaaGjZ` and `ses_f72c4f1baffeECZSQ37ujzSmCJ`. The independent retest `ses_f72ab5027ffeR0shgnOsYGX47N` for the first builder's named repairs was cancelled; no builder claim substitutes for that retest.
- Late backup retest `ses_f72ab4fc9ffepKCTOlUxIWlRrt` reported `make check` **Pass**, 83 tests, and 89.23% coverage, plus named backup/restore checks. The earlier concurrent aggregate-check limitation is historical context, not a current unresolved failure.
- `EXP-M00` ends with `opencode export ses_f73b976e8ffekNCE6SNIanpXFb > SESSION-EXPORT.md` recorded as `running`; exact full secret-review/export-revision evidence is absent. Commit/push and Git revision evidence for that export are unavailable.
- The old GitHub Actions run [34549899644](https://github.com/eddiesoz/stock_probs/actions/runs/34549899644), recorded by the earlier documentation, is obsolete x64-only historical context. It is not a current gate, release proof, ARM64 evidence, or substitute for local checks.

### Historical collision aliases

Historical labels are immutable. `R-M00-1` allocates these fresh, unique pending records for unresolved obligations:

| Historical collision | Fresh repair ID | Obligation |
| --- | --- | --- |
| `R-M01-1` in QA `ses_f72f4e2f0ffe6hMpBTmXUnWybW` vs builder `ses_f72c4f20effeDoLPC0FuHaaGjZ` | `R-M01-3`, `R-M01-4` | Router error/OpenAPI retest; startup-harness retest |
| `R-M05-1` in QA `ses_f72f4e163ffehgqJPXwbY7ujrX` vs builder `ses_f72c4f1baffeECZSQ37ujzSmCJ` | `R-M05-5`, `R-M05-6` | Malicious-artifact retest; chunked-request/resource retest |
| `R-M06-1` in QA `ses_f72f4e163ffehgqJPXwbY7ujrX` vs builder `ses_f72c4f20effeDoLPC0FuHaaGjZ` | `R-M06-2`, `R-M06-3`, `R-M06-4` | Port-collision, CSP, and CSV-safety retests |
| `R-M04-1` in browser/accessibility `ses_f72f4e261ffeLWQEjyJI4k3hea` vs builder `ses_f72c4f20effeDoLPC0FuHaaGjZ` | `R-M04-2`, `R-M04-3` | Separate actual assistive-technology evidence; mobile-focus retest |

All fresh aliases remain `Pending`; the screen-reader/assistive-technology evidence is separately unavailable. The full source-qualified register and task fields are in `MVP-PLAN.md` and `MVP-ROADMAP.md`.

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

The canonical sequence is `R-M00-1` -> `EXP-M00` -> `M01`/`EXP-M01` -> ... -> `M06`/`EXP-M06` -> `M07` QA/docs -> `EXP-M07` -> `M08` walkthrough QA/docs -> `ASTRA-FINAL` -> repairs/retests until the result is `Accepted` -> `EXP-M08` -> `EXP-FINAL`. M08 is the final roadmap milestone before Astra. Astra must review the walkthrough artifact, its actual-control browser evidence, and the retrospective before final acceptance.

Each `EXP-M00` through `EXP-M08` overwrites the one tracked full-session `SESSION-EXPORT.md`, receives a complete secret review, and records the export revision, local commit, pushed branch, exact Git remote revision verification, artifact/link, UTC timestamp, environment, and named reviewer. A failed, skipped, unavailable, or connectivity-blocked export/review/commit/push/revision check remains visible and blocks that checkpoint. No external pipeline or hosted runner may fill any field.

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
- **Evidence:** `R-M00-2-E1` — final `git status`/`git diff` four-file scope review, **Pass** for documentation scope; `?? .vscode/` remains untouched. `R-M00-2-E2` — document self-review against the requested local-only, ARM64, M08, sequence, vocabulary, and M05 requirements, **Pass** as documentation content; no implementation QA was run. `R-M00-2-E3` — actual workflow removal, local gate execution, M08 artifact generation, browser QA, and retrospective are **Unavailable** in this docs-only task and remain future evidence. `R-M00-2-E4` — R-M00-1 identity/history and collision aliases retained, **Pass** as documentation content.
- **Limitations:** no implementation behavior, local test result, native ARM64 result, emulated ARM64 run, walkthrough artifact, browser-control check, retrospective, export, commit, push, or new Git remote verification was performed here.
- **Export/Git/reviewer:** `EXP-M00` through `EXP-M08` and `EXP-FINAL` remain `Pending` or unavailable as individually recorded; no export, commit, or push was performed. Reviewer: `LUNA MAX docs` self-review; independent implementation QA was not performed.

`R-M00-1` remains immutable historical context; its old external-pipeline wording is superseded by this `R-M00-2` policy and cannot be used as current acceptance evidence. The detailed contract, milestone rows, collision register, and Astra matrix are in `MVP-PLAN.md` and `MVP-ROADMAP.md`; compact operating rules are in `AGENTS.md`.

## Local Development Guidance

The `Makefile` and pinned manifests are candidate operational paths until their exact local task evidence exists. Local fail-closed commands must identify task and commit context, stop on a failing check, and never depend on `burry_env/` or `.venv/`. Local artifacts are not release evidence until their task record names the command, environment, timestamp, result, artifact, limitation, and reviewer.
