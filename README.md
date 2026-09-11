# Stock Probability

## Evidence-Backed Status

As of 2026-09-10, this repository is an implementation-shaped local ARM64 stock-probability app under evidence-controlled delivery. The working tree contains FastAPI/API, domain/provider, SQLite, static dashboard, backup/restore, browser/MCP, scripts, tests, and CI material. Source presence and generated local artifacts are not proof that those behaviors work.

- `M00` is **Completed**, documentation baseline only.
- `M01` through `M06` are **In progress**, not completed: implementation material is observed, but the independent QA evidence, exact verification records, reviewers, export gates, remote checks, and CI results required by the plan are not recorded here.
- `M07`, `ASTRA-FINAL`, `EXP-M00` through `EXP-M07`, and `EXP-FINAL` are **Pending**.
- This documentation task deliberately does not run implementation QA, create/review `SESSION-EXPORT.md`, commit, push, or verify remote/CI. None of those gates is claimed as passed.

The exploratory scripts and local environments remain historical/development material. Do not present a passing-looking test file, browser report, `.coverage`, database, `.venv/`, `.dev-venv/`, or `burry_env/` as release evidence.

## Observed Repository Shape

The following are implementation observations to guide the next evidence pass, not completion claims:

- `src/stock_probs/` contains the FastAPI boundary, domain/provider/service layers, SQLite repository and migration, backup manager, CLI, fixtures, and static dashboard.
- `tests/` contains deterministic API, domain, provider, persistence/backup, configuration, resource, and opt-in live checks.
- `tools/browser/` contains serial desktop/mobile Playwright scenarios, accessibility checks, MCP smoke support, and bounded runtime configuration.
- `opencode.json`, `.opencode/`, `scripts/`, `Makefile`, and `.github/workflows/ci.yml` describe headless MCP, local operation, comments, and CI gates.

The next status change requires the exact task record in `MVP-PLAN.md`, independent `LUNA MAX QA` evidence, the docs reconciliation, and the matching export/remote/CI record. No implementation milestone may be marked `Completed` from these observations.

## Planned MVP Contract

The target is a local, loopback-only web app for selecting Yahoo Finance stocks and ETFs and reviewing auditable probability forecasts. It must demonstrate:

- A close-to-close forecast based on a clearly recorded completed-session close and applicable next close.
- A latest-completed-5-minute-bar-to-close forecast that excludes an in-progress bar and states its session rule.
- Direction/threshold probabilities and explicit magnitude intervals with definitions, levels, units, as-of time, model/version, and data-quality state.
- Source, market-session, stale-data, error, limitation, and immutable input/result provenance.
- Searchable history containing every submitted successful, failed, and repeated search.
- Append-only observed outcomes that never rewrite the original forecast.
- Verified, non-destructive backup/restore and secure loopback defaults suitable for a low-resource ARM64 laptop.

The boundary is strict: browser application data must use FastAPI `/api/v1`; the browser must not open SQLite, issue SQL, receive a database path, or call Yahoo Finance directly. The dashboard must be responsive and accessible, with text equivalents for visual data and understandable empty, loading, success, repeated, stale, validation, and failure states.

These are acceptance requirements, not a promise that the current working tree satisfies them. Forecasts are informational research outputs, not investment advice or a guarantee of future prices.

## Required Future Workflow

All future work maximizes safe parallelism with no more than three concurrent subagents. Each build wave uses three `SOL HIGH build` instances on non-overlapping lanes: transport/application, domain/provider/persistence, and presentation/browser/operations. Builders declare paths and exact task IDs, finish, and report before integration.

Only after all builder reports arrive do the independent `LUNA MAX QA` and `LUNA MAX docs` gates run. The coordinator owns integration, status, and git only; it does not implement, perform QA, or write roadmap prose. Failures, skips, unavailable providers, stale data, accessibility findings, restore failures, secret-review failures, and connectivity loss remain visible and create `R-M##-<n>` repairs with rerun evidence.

`README.md` and `AGENTS.md` are roadmap deliverables. Reconcile both after each milestone and again during final acceptance; neither may claim more than the evidence supports.

## Export And Release Gates

After every roadmap milestone, complete its exact export task: `EXP-M00` through `EXP-M07`. OpenCode `/export` (or a verified CLI equivalent) must overwrite the one tracked root artifact `SESSION-EXPORT.md` with the full session, including tool calls and subagent outputs. Review the entire export for secrets before commit; never commit an unreviewed export.

Record the export revision, secret-review result, commit, pushed branch, remote verification, CI result, artifact/link, UTC timestamp, environment, and named reviewer. A failed, skipped, unavailable, or connectivity-blocked export, review, push, remote check, or CI check blocks acceptance and must not be summarized as green. Git commit/revision versions the stable overwritten export path and provides a recoverable checkpoint so work can resume after connectivity loss.

After M07, independent GPT-6 Astra executes `ASTRA-FINAL`. Astra must confirm every feature, API/UI endpoint, click/control, browser journey, and persistence effect in an evidence matrix. Any gap creates `R-ASTRA-<n>`; repair, QA, and Astra retest repeat until the independent record says `Accepted`. Only then may `EXP-FINAL` complete the final export/commit/push/remote/CI gate.

## Evidence Record Minimum

Every record uses an exact task ID (`M##`, `R-M##-<n>`, `EXP-M##`, `ASTRA-FINAL`, `R-ASTRA-<n>`, or `EXP-FINAL`) and includes:

- status: `Pending`, `In progress`, `Blocked`, or `Completed`;
- owner/phase, verified dependency IDs, and change summary;
- one evidence row per acceptance requirement with check/command, environment, UTC timestamp, commit, result (`Pass`, `Fail`, `Skipped`, or `Unavailable`), artifact/link, and reviewer;
- repair history, limitations, export ID/revision, secret review, commit/push, remote/CI result, and named reviewer.

Missing evidence is not a pass. The detailed acceptance contract and task register are in `MVP-PLAN.md`; dependency order, gate status, Astra matrix, and export rules are in `MVP-ROADMAP.md`; compact operating rules are in `AGENTS.md`.

## Local Development Guidance

The `Makefile` and pinned manifests describe setup, deterministic checks, browser checks, MCP smoke, backup, restore, and release-check entry points. Treat them as candidate operational paths until the corresponding task and environment evidence is recorded. Do not use `burry_env/` as a source of truth; it is tracked legacy dependency noise. `.venv/` and other local environments are local state, not dependency declarations or release evidence.
