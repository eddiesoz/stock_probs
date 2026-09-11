# Stock Probability MVP Roadmap

## Status Snapshot

This roadmap tracks delivery of the local ARM64 stock-probability web app. As of 2026-09-10, the working tree contains implementation-shaped FastAPI, domain/provider, SQLite, static-dashboard, backup/restore, browser, MCP, and CI material. That observation is not acceptance evidence.

- **Completed:** `M00`, documentation baseline only. The four roadmap deliverables are `MVP-PLAN.md`, `MVP-ROADMAP.md`, `AGENTS.md`, and `README.md`.
- **In progress, not completed:** `M01` through `M06`; source/config/test material is present, but independent QA evidence, exact verification records, reviewers, and release gates are not recorded here.
- **Pending:** `M07`, `ASTRA-FINAL`, `EXP-M00` through `EXP-M07`, and `EXP-FINAL`.
- **Current-task limitation:** this docs task does not run implementation QA, create or review `SESSION-EXPORT.md`, commit, push, or verify remote/CI. Those checks remain open and are not represented as green.
- **Rule:** no milestone advances to `Completed` from implementation claims, a test file, a generated artifact, or a narrative summary. The exact evidence record in `MVP-PLAN.md` is authoritative.

## Dependency-Ordered Milestones

| ID | Milestone | Dependencies | Status | Evidence state and next gate |
| --- | --- | --- | --- | --- |
| `M00` | Documentation baseline | None | Completed, docs only | Four docs and the contract exist. Complete `EXP-M00` before treating the baseline as an exported revision. |
| `M01` | API and application shell | M00 | In progress | Implementation-shaped API/shell material observed; QA contract, API-only browser, loopback, and resource evidence remain open. Then `EXP-M01`. |
| `M02` | SQLite audit and immutable records | M01 | In progress | Migration/repository material observed; failure/repeat, immutability, restart, and boundary evidence remain open. Then `EXP-M02`. |
| `M03` | Yahoo Finance data and forecast engine | M01, M02 | In progress | Provider/domain/fixture material observed; live/fixture, completed-bar, stale, numerical, and ARM64 evidence remain open. Then `EXP-M03`. |
| `M04` | Dashboard and searchable history | M01, M02, M03 | In progress | Static UI and browser scenarios observed; responsive, keyboard, accessibility, state, and network evidence remain open. Then `EXP-M04`. |
| `M05` | Backup, restore, and secure loopback operations | M02, M04 | In progress | Backup/restore and loopback material observed; integrity, tamper, promotion, security, timeout, and ARM64 evidence remain open. Then `EXP-M05`. |
| `M06` | QA, MCP, browser regressions, and CI | M01, M02, M03, M04, M05 | In progress | MCP/config/browser/CI material observed; independent clean-run, browser/a11y/security/restore/resource and CI evidence remains open. Then `EXP-M06`. |
| `M07` | Integrated MVP acceptance | M06 | Pending | Full user journey, persistence, restore, release reconciliation, and sign-off remain open. Then `ASTRA-FINAL`, `EXP-M07`, and `EXP-FINAL` in the required order. |

## Mandatory Delivery Workflow

All future work maximizes safe parallelism with no more than three concurrent subagents. The coordinator does not implement, test, review, or write roadmap prose; it owns integration, status, and git only.

### Build wave

Every implementation or repair wave uses three `SOL HIGH build` instances with non-overlapping ownership, declared against the exact `M##` or `R-M##-<n>` ID before work begins:

| Builder | Non-overlapping ownership lane |
| --- | --- |
| `SOL HIGH-A` | Transport/application: FastAPI routes, schemas, settings, CLI, and transport-facing implementation tests |
| `SOL HIGH-B` | Domain/provider/persistence: forecast rules, Yahoo/fixture adapters, services, migrations, SQLite, backup/restore, and domain/storage tests |
| `SOL HIGH-C` | Presentation/browser/operations: static UI, browser harness, scripts, Make/CI/tool configuration, and presentation-facing implementation tests |

Each builder reports its exact task ID, changed paths, checks, failures, assumptions, and handoff. No two builders edit the same path. A shared interface is handed to the coordinator for integration rather than edited concurrently.

### Wait and verification gates

1. Record the task ID, dependencies, lane manifest, change summary, and one acceptance row per requirement.
2. Run all three non-overlapping `SOL HIGH build` lanes concurrently.
3. Wait for all three builder reports before integration or acceptance review.
4. Only after that wait, run independent `LUNA MAX QA` and `LUNA MAX docs` gates. They may run concurrently when their scopes are independent; docs cannot convert missing QA into a pass.
5. Record every pass, fail, skipped, unavailable, stale, accessibility, restore, secret-review, and connectivity result. A failed or unavailable required gate blocks acceptance.
6. For a failure, create `R-M##-<n>`, repair the root cause, repeat the builder handoff, QA/docs gates, and affected regression checks. Never weaken the acceptance requirement.

## Versioned Export, Commit, Push, And Remote Gates

After **each** roadmap milestone, before the next milestone starts, complete its exact export task: `EXP-M00`, `EXP-M01`, `EXP-M02`, `EXP-M03`, `EXP-M04`, `EXP-M05`, `EXP-M06`, or `EXP-M07`.

1. Use OpenCode `/export`, or a verified CLI equivalent, to overwrite the one tracked root artifact `SESSION-EXPORT.md`.
2. Confirm that the artifact is a full-session export containing tool calls and subagent outputs, not a summary or partial log.
3. Review the complete export for secrets before commit. A skipped, failed, unavailable, or connectivity-blocked secret review blocks the gate.
4. Record the export task ID, export revision, secret-review result, commit, pushed branch, remote verification, CI result, artifact/link, UTC timestamp, environment, and named reviewer.
5. The coordinator performs the commit/push and verifies the remote branch and CI. A failed, skipped, unavailable, or connectivity-blocked push, remote check, or CI result remains exactly that and blocks acceptance.

The stable export path is intentionally overwritten; the recorded Git commit/revision versions each export and provide a recoverable checkpoint so work can resume after connectivity loss. This task has not run any `EXP-*` gate and does not claim a commit or push.

## Final Independent Astra Gate

After `M07` QA/docs evidence is complete, independent GPT-6 Astra executes `ASTRA-FINAL`. Astra must confirm working behavior by execution and evidence, not by reading implementation claims. Its matrix must include a separate row for every:

- product feature and acceptance requirement;
- API endpoint, including health/readiness, forecast, history/reconstruction/prices, CSV export, immutable-result, outcome, backup, restore, documentation, and static-asset surfaces discovered in the final route inventory;
- UI click/control, including skip navigation, symbol entry/validation, stock/ETF selection, forecast submit, history filters, reconstruction, pagination, and export;
- desktop/mobile browser journey, including empty, loading, success, repeated, failed, stale, validation, accessible keyboard/screen-reader, API-only, and security-console journeys;
- persistence effect, including successful/failed/repeated search events, immutable input/results, append-only outcomes/corrections, bounded history, restart, backup, verification, and restore promotion.

Each row records task ID `ASTRA-FINAL`, check/command, environment, UTC timestamp, commit, result, artifact/link, limitation, and reviewer. Any gap or non-pass creates `R-ASTRA-<n>`. The repair receives the normal three-builder handoff and QA/docs gates, then Astra retests the failed row and affected matrix. Repeat until the independent record explicitly says **Accepted**. `EXP-M07` and `EXP-FINAL` cannot be green before that acceptance.

## Roadmap Completion Record

Every milestone, repair, export, and final review uses these exact fields:

- **Task ID:** exact `M##`, `R-M##-<n>`, `EXP-M##`, `ASTRA-FINAL`, `R-ASTRA-<n>`, or `EXP-FINAL`.
- **Status:** `Pending`, `In progress`, `Blocked`, or `Completed`.
- **Owner/phase:** builder lane, QA, docs, Astra, export, or remote verification.
- **Dependencies verified:** task IDs and evidence links.
- **Change summary:** what changed and what did not change.
- **Acceptance evidence:** one item per requirement with evidence ID, check/command, environment, UTC timestamp, commit, result (`Pass`, `Fail`, `Skipped`, or `Unavailable`), artifact/link, and reviewer.
- **Repair history:** failure or limitation, repair ID, root cause, fix, and rerun result; do not omit skips or unavailable providers.
- **Limitations:** stale data, provider coverage, ARM64/resource, accessibility, restore, connectivity, or artifact limits.
- **Export/remote result:** export ID and revision, full-session artifact, secret review, commit, push, remote branch/check, and CI result.
- **Named reviewer:** independent QA/docs verifier, and independent GPT-6 Astra for final acceptance.

## Release Definition Of Done

The roadmap is complete only when:

- `M00` through `M07` have explicit evidence-backed statuses, and no implementation milestone is completed by assertion alone.
- A user-selected Yahoo Finance stock and ETF each demonstrate both forecast horizons with completed-bar/session semantics, probabilities, magnitude intervals, provenance, and honest stale/error limitations.
- SQLite retains successful, failed, and repeated searches; immutable forecast inputs/results; and append-only outcomes, with searchable history through FastAPI `/api/v1` and no browser database access.
- Responsive accessible UI, keyboard/screen-reader states, secure loopback behavior, bounded ARM64 operation, verified backup/restore, official headless `@playwright/mcp`, browser regressions, useful code comments, and fail-closed Git/CI gates have independent evidence.
- `README.md` and `AGENTS.md` are reconciled with the final supported scope and evidence; they are roadmap deliverables, not optional commentary.
- `ASTRA-FINAL` is independently **Accepted** after every feature/API/UI/control/journey/persistence row and every `R-ASTRA-<n>` retest.
- `EXP-M00` through `EXP-M07` and `EXP-FINAL` contain reviewed, secret-free full-session `SESSION-EXPORT.md` revisions with commit, push, remote verification, and CI results. No failed, skipped, unavailable, or blocked gate is hidden.
