# Agent Rules

## Repository truth

- The target is a local ARM64 stock-probability web app; the working tree contains an exploratory prototype plus implementation-shaped source, tests, and operations files. Presence of code is not acceptance evidence.
- `burry_env/` is tracked legacy dependency noise. Do not treat it as source, add to it, repair it, or remove it.
- `.venv/` and other local environments are not dependency declarations or release evidence.
- `M01` through `M07` stay non-completed until the exact task record contains QA evidence, verification, reviewer, repairs, and the required export/remote checks.

## Product invariants

- Forecast close-to-close and latest-completed-5-minute-bar-to-close horizons for user-selected Yahoo Finance stocks and ETFs, with probabilities and explicit magnitude intervals.
- All frontend application data goes through FastAPI `/api/v1`; the browser never opens SQLite, issues SQL, receives a database path, or calls Yahoo Finance directly.
- SQLite retains successful, failed, and repeated searches plus immutable forecast inputs/results and append-only later outcomes.
- Searchable history, verified backup/restore, accessible responsive UI, secure loopback deployment, bounded ARM64 operation, headless official `@playwright/mcp`, browser regressions, and Git/CI gates are release requirements.
- Non-obvious implementation behavior must have a useful intent or constraint comment. Any code/config snippet added to documentation must also contain a useful comment.

## Orchestration

- Maximize safe parallelism with no more than three concurrent subagents. Each build wave uses three `SOL HIGH build` instances only on declared, non-overlapping ownership lanes: transport/application, domain/provider/persistence, and presentation/browser/operations.
- Builders must finish and report before integration. After the wait, run the independent `LUNA MAX QA` and `LUNA MAX docs` gates; they may run concurrently only after the build handoff and neither may hide a missing check.
- The coordinator owns integration, status, and git only. It does not implement, perform QA, or write roadmap prose.
- `SOL HIGH build` owns scoped implementation and engineering fixes; `LUNA MAX QA` owns tests, browser, accessibility, security, resource, migration, restore, and verification; `LUNA MAX docs` owns these four documentation files and honest evidence/status wording.
- Every assignment names an exact task ID from `MVP-PLAN.md`/`MVP-ROADMAP.md`; use `R-M##-<n>` for repairs, `EXP-M##` for milestone exports, `ASTRA-FINAL` for the final review, `R-ASTRA-<n>` for its repairs, and `EXP-FINAL` for the last export.
- `README.md` and `AGENTS.md` are roadmap deliverables: reconcile both after each milestone and again during final acceptance.

## Mandatory gates

- After every roadmap milestone (`M00` through `M07`), complete its `EXP-M##` gate. OpenCode `/export` (or a verified CLI equivalent) must overwrite the one tracked `SESSION-EXPORT.md` full-session export, including tool calls and subagent outputs. Review the export for secrets before commit; never commit an unreviewed export.
- The coordinator then records the export revision/commit, pushes it, and verifies the remote branch and CI result. A failed, skipped, unavailable, or connectivity-blocked export, secret review, push, remote check, or CI check is recorded and blocks acceptance; it is never summarized as green.
- After `M07`, an independent GPT-6 Astra review with task ID `ASTRA-FINAL` must execute an evidence matrix covering every feature, API/UI endpoint, click/control, browser journey, and persistence effect. Any gap creates `R-ASTRA-<n>`; repair, QA, and Astra retest repeat until Astra records `Accepted`.
- Complete `EXP-FINAL` only after Astra acceptance and all repair retests. The final export/commit/push/remote/CI result is part of the release record.

## Evidence discipline

- Each record includes: exact task ID; status (`Pending`, `In progress`, `Blocked`, or `Completed`); owner/phase; verified dependency IDs; change summary; one evidence item per acceptance requirement; command/check, environment, UTC timestamp, commit, result (`Pass`, `Fail`, `Skipped`, or `Unavailable`), artifact/link; repair history; limitations; export ID and revision; remote/CI result; and named reviewer.
- Record failures, skips, unavailable providers, stale data, accessibility findings, restore failures, secret-review failures, and connectivity loss with their repair ID and rerun result. Never infer completion from implementation claims or omit a failed check.
