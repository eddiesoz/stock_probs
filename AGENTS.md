# Agent Rules

## Repository truth

- The contract is a local Linux app for x86-64/amd64 and ARM64/aarch64, designed for low-resource operation. The current host is native x86_64; no native ARM64 or physical ARM64 performance result is claimed.
- ARM64 verification first uses local native ARM64 hardware if available. Otherwise local QEMU/OCI multi-arch execution may verify packaging, runtime, functional, build, and tool behavior, but every result is labelled emulated; it is not native/physical ARM64 or original-laptop resource evidence.
- The supplied Git remote revision `2a7a3bf66c3665552a46d0bd523544a01f894b3f` and the old GitHub Actions run are obsolete historical context only, not current gates or release proof. No external pipeline is in scope.
- `burry_env/` is tracked legacy dependency noise; do not treat it as source, add to it, repair it, or remove it. `.venv/` and other local environments are not dependency declarations or release evidence.
- `M01` is **In progress**, not completed: `R-M01-3` through `R-M01-15` have independent scoped pass records, but `EXP-M01` checkpoint evidence is pending. `M02` through `M08` remain non-completed until their exact records contain independent QA, verification, reviewer, repair history, and required local/export evidence. `R-M00-2` is documentation-only and does not accept implementation.

## Product invariants

- Forecast close-to-close and latest-completed-5-minute-bar-to-close horizons for selected Yahoo Finance stocks and ETFs expose explicit direction/threshold probabilities and return/price intervals.
- Company-name lookup preserves instrument identity. Saved forecasts reopen as immutable recorded results; historical-cutoff reconstruction is separately labelled fresh analysis.
- Frontend data uses FastAPI `/api/v1`; the browser never opens SQLite, issues SQL, receives a database path, or calls Yahoo Finance directly. SQLite retains successful, failed, and repeated searches, immutable inputs/results, and append-only outcomes.
- Searchable history, CSV/JSON export, verified backup/restore, accessible responsive UI, secure loopback, bounded operation, official headless `@playwright/mcp`, browser regressions, and local fail-closed Make/scripts are release requirements. No GitHub workflow or external pipeline may satisfy one.
- Non-obvious implementation behavior and documentation snippets need useful intent or constraint comments.

## Orchestration and ownership

- A build wave uses exactly three concurrent `SOL HIGH build` instances: A owns transport/application and package/launch; B owns domain/provider/persistence/migrations/backup; C owns presentation/browser/operations/local gate tooling. Any unlisted implementation/config/test path is assigned before work starts. M01/M06 remove `.github/workflows/ci.yml` if present; local Make/scripts replace that former role.
- `README.md`, `AGENTS.md`, `MVP-PLAN.md`, and `MVP-ROADMAP.md` belong only to `LUNA MAX docs`; `SESSION-EXPORT.md` belongs only to its export gate. The coordinator owns integration, status, and git only; it does not implement, perform QA, or write roadmap prose.
- Builders report exact task ID, paths, checks, failures, and assumptions. Only after all three reports arrive do independent `LUNA MAX QA` and `LUNA MAX docs` gates run; docs finalizes only after consuming the completed QA record.
- Use exact `M00`–`M08`, `R-M##-<n>`, `EXP-M00`–`EXP-M08`, `ASTRA-FINAL`, `R-ASTRA-<n>`, or `EXP-FINAL` IDs. Reconcile README and AGENTS after each milestone and at final acceptance.

## Gates and sequence

- Canonical sequence: `R-M00-1` -> `EXP-M00` (**Completed**) -> `M01` (**In progress**) -> `EXP-M01` (**next gate**) -> ... -> `M06`/`EXP-M06` -> `M07` QA/docs -> `EXP-M07` -> `M08` walkthrough QA/docs -> `ASTRA-FINAL` -> repairs/retests until the result is `Accepted` -> `EXP-M08` -> `EXP-FINAL`.
- Each export overwrites the tracked full-session `SESSION-EXPORT.md`. Secret review, local commit, push to the Git remote, and remote revision verification are separate evidence fields; failed, skipped, unavailable, or connectivity-blocked fields remain visible and block that checkpoint. There is no external-pipeline or hosted-runner field.
- Commit/push the reviewed export as checkpoint SHA X and verify that exact SHA on the Git remote; preserve the receipt in the next checkpoint. Never claim a future result for SHA X. `ASTRA-FINAL` must matrix M08 as well as every feature, endpoint, control, journey, and persistence effect before `EXP-FINAL`.

## Evidence discipline

- Every record has exact task ID, status only `Pending`, `In progress`, `Blocked`, or `Completed`, owner/phase, verified dependencies, change summary, one evidence item per requirement, check/command, environment, UTC timestamp, commit, result (`Pass`, `Fail`, `Skipped`, or `Unavailable`), artifact/link, repairs, limitations, export/revision, Git checkpoint/remote result, and named reviewer.
- Record failures, skips, unavailable providers or hardware, stale data, accessibility findings, restore/key failures, secret-review failures, and connectivity loss with a unique repair ID and rerun result. Never infer completion from implementation claims or hide a missing check.
- The recovered pre-checkpoint export is valid parsed JSON (`5,065,391` bytes, `11,093` physical lines, `80` top-level messages, `384` parts) but contains parent calls and summarized handoffs; its historical `EXP-M00` command remains `running` and exact secret-review/export-revision evidence is absent. The current `EXP-M00` checkpoint is **Completed**: session `ses_f71ec0499ffeokWj4h6tVwyYk1`, `1,413,943` bytes, `4,268` lines, `23` messages, `153` parts, `44` tool parts, `10` task outputs, two masked credential-like candidates, no private-key/AWS/GitHub/Bearer patterns, exact pushed/remote SHA `18da1af0b6bc31020d3587e472b8197146795bf1`, and reviewer/coordinator `OpenCode gpt-5.6-sol`; no remote CI was used.
- M01's current worktree includes the local deletion of `.github/workflows/ci.yml`, but remote removal remains pending until `EXP-M01` commits/pushes and verifies it. The unrelated `?? .vscode/` remains untouched. Native x86_64 and emulated ARM64 functional/tool evidence is recorded; native/physical ARM64 performance remains unavailable.
- `R-M00-1` and its collision aliases remain immutable historical records. `R-M00-2` records this docs-only policy repair; no implementation QA, walkthrough artifact, export, commit, or push is performed here.
