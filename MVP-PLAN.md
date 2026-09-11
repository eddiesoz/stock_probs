# Stock Probability MVP Plan

## Status And Scope

This is the implementation contract for the planned local ARM64 stock probability web app. As of 2026-09-10, the working tree contains exploratory scripts plus implementation-shaped application, test, browser, operations, and CI material. That presence is an observation, not acceptance evidence.

- `M00` is **Completed** for the documentation-only contract: `MVP-PLAN.md`, `MVP-ROADMAP.md`, `AGENTS.md`, and `README.md`.
- `M01` through `M06` are **In progress** only in the sense that corresponding source/config/test material is present; their acceptance and independent QA evidence are not recorded here, so none is completed.
- `M07` and `ASTRA-FINAL` are **Pending**. The milestone export gates `EXP-M00` through `EXP-M07` and final `EXP-FINAL` are also not evidenced by this documentation task.
- A task may move to **Completed** only after every acceptance item, independent QA verification, repair history, reviewer, export, secret review, push, remote check, and CI result is recorded. Implementation claims alone never change status.

## Mandatory Delivery Workflow

The coordinator applies this workflow to every milestone and repair. It is a sequencing rule, not permission to infer that an existing source file works.

### Safe build-wave ownership

Use no more than three concurrent subagents. A build wave uses three `SOL HIGH build` instances with these declared, non-overlapping lanes; the coordinator records the lane manifest against the exact milestone or repair ID before work starts:

| Lane | Sole build ownership | Handoff boundary |
| --- | --- | --- |
| `SOL HIGH-A` | Transport/application: FastAPI routes, schemas, configuration, CLI, and their implementation-facing tests | Versioned API contract and launch assumptions |
| `SOL HIGH-B` | Domain/provider/persistence: forecast semantics, Yahoo/fixture adapters, service, SQLite migrations/repositories, backup/restore, and their implementation-facing tests | Domain and storage contracts, fixtures, and migration assumptions |
| `SOL HIGH-C` | Presentation/browser/operations: static UI, browser harness, operational scripts, Make/CI/tool configuration, and their implementation-facing tests | UI states, browser journeys, resource limits, and operational assumptions |

No two builders edit the same path or silently cross a lane boundary. Builders report the exact task ID, changed paths, checks attempted, failures, and unresolved assumptions. If a dependency requires a shared edit, builders stop and hand it to the coordinator for integration rather than overlapping. The build wave is complete only after all three builder reports arrive.

### Ordered gates

1. Assign the exact `M##` or repair ID and record verified dependencies, lane ownership, and acceptance rows.
2. Run the three-lane `SOL HIGH build` wave concurrently, with no more than three subagents.
3. Wait for all builder reports and changed paths; do not integrate or declare a result while a report is missing.
4. Run independent `LUNA MAX QA` and `LUNA MAX docs` gates only after that wait. They may run concurrently when their scopes are independent, but docs must not fill a missing QA result with an implementation claim.
5. The coordinator alone integrates changes, updates status/evidence, and performs git operations. It does not implement, perform QA, or write roadmap prose.
6. On any failure, skip, unavailable provider, stale-data condition, accessibility finding, restore failure, secret-review failure, connectivity loss, or missing artifact, keep the task `Pending`, `In progress`, or `Blocked`; create `R-M##-<n>`, repair the root cause, and rerun the failed and affected checks.
7. After each accepted roadmap milestone, complete its export gate (`EXP-M00` through `EXP-M07`) before starting the next milestone. The final gate is `EXP-FINAL` and is allowed only after `ASTRA-FINAL` is `Accepted` and all Astra repairs have passed retest.

### Versioned session-export gates

Every milestone has a separately recorded export task ID: `EXP-M00`, `EXP-M01`, `EXP-M02`, `EXP-M03`, `EXP-M04`, `EXP-M05`, `EXP-M06`, or `EXP-M07`. The coordinator uses OpenCode `/export`, or a verified CLI equivalent, to overwrite exactly one tracked root artifact, `SESSION-EXPORT.md`. The export must be a full-session record containing tool calls and subagent outputs; a summary, partial transcript, or untracked local file does not satisfy the gate.

Before commit, the export receives a documented secret review. The record then names the export revision/commit, commit, pushed branch, remote verification, and CI result. Any failed, skipped, unavailable, or connectivity-blocked export, secret review, push, remote check, or CI check is recorded with its result and blocks acceptance. Git history supplies the version for the stable overwritten path; the export task ID supplies milestone identity. This task intentionally does not create the export, commit, or push it.

### Independent final Astra gate

After `M07` dependencies and its QA/docs evidence are complete, an independent GPT-6 Astra reviewer executes task `ASTRA-FINAL`. Astra must use an evidence matrix—not implementation claims—to confirm every shipped feature, every API and UI endpoint, every visible click/control, every browser journey on the supported viewports, and every persistence effect. The matrix must name the check, environment, UTC timestamp, commit, result, artifact/link, limitation, and reviewer for each row.

Any missing, failing, skipped, unavailable, or unconfirmed row creates `R-ASTRA-<n>`. The repair goes through the same three-lane build handoff, independent QA/docs gates, and Astra retest. Repeat until the `ASTRA-FINAL` record explicitly says `Accepted`; no final release or `EXP-FINAL` may precede that wording.

## Product Goal

Build a small, auditable, local web application where a user selects a Yahoo Finance stock or ETF and receives two forecast views:

1. **Close-to-close:** a forecast from a clearly identified completed market-session close to the applicable next close.
2. **Latest-completed-5-minute-bar-to-close:** a forecast from the latest completed five-minute bar available at request time to the applicable close. An in-progress bar must never be used as completed input.

Each view must expose probabilities and magnitude intervals, not just a point estimate. Every displayed result must identify its symbol, asset type, input timestamps, provider/as-of time, forecast horizon, model/version, interval level and units, stale-data state, and any limitation or failure.

This is a research and auditability tool, not a trading system or a promise of predictive accuracy.

## Non-Negotiable Boundaries

### API boundary

- All frontend application data must pass through FastAPI `/api/v1`.
- The browser must not import a SQLite client, issue SQL, open a database path, or infer storage details from the API.
- The API owns validation, provider calls, forecast calculation, persistence, history queries, and backup/restore operations.
- API errors must be structured, safe to display, and specific enough to distinguish invalid input, unavailable market data, stale data, calculation failure, persistence failure, and restore failure.

### Data source and time semantics

- Yahoo Finance is the planned market-data source for user-selected stocks and ETFs.
- The provider adapter must record the exact query, requested interval, returned coverage, timezone/session interpretation, response as-of time, and any missing or stale bars.
- The forecast service must reject or clearly label insufficient, stale, out-of-session, or ambiguous data. It must not silently substitute a different interval or session.
- Close-to-close and five-minute-bar-to-close calculations must have separate, testable horizon semantics. A request made outside market hours must follow a documented session rule rather than an implicit guess.

### Persistence and auditability

- Every submitted search is an append-only audit event, including successful, failed, and repeated submissions. A repeated search may reuse a valid prior result, but the new submission event must still be stored.
- A successful forecast stores an immutable input snapshot: normalized symbol and asset type, request and source timestamps, selected bars, session/calendar interpretation, data-quality flags, model and algorithm version, parameters, thresholds, and provider metadata or content fingerprint.
- The immutable result stores probabilities, magnitude intervals, interval levels and units, calculation timestamps, and the input-record reference.
- An observed outcome is appended after the forecast horizon with the actual close/return, observation timestamp, comparison rule, and outcome state. It must not rewrite the original forecast input or result.
- Corrections require a new versioned record or audit event. No update-in-place behavior may erase what was originally submitted or displayed.
- History queries must be bounded, searchable, and served through `/api/v1`; the UI must not scan the database file.

### User experience

- The dashboard must work at desktop and mobile widths without hiding essential status or controls.
- Every search control needs a visible label, keyboard path, focus state, validation message, loading state, empty state, success state, and failure state.
- Charts, colors, and interval bands must have text or table equivalents; color alone cannot communicate direction, confidence, stale data, or failure.
- History must support practical search/filtering and expose enough context to distinguish a repeated request from a new forecast.
- Accessible names, semantic structure, contrast, keyboard operation, reduced-motion behavior, and screen-reader announcements are acceptance concerns, not polish.

### Deployment and resources

- The default service must bind to loopback only. The deployment must make any broader bind an explicit, documented, security-reviewed choice.
- Validate symbols, request sizes, date ranges, page sizes, backup paths, and provider timeouts at the API boundary.
- Do not expose provider credentials or local file paths to the browser or logs. Avoid unsafe CORS and unbounded concurrent provider calls.
- Keep the default process, query, cache, and browser-test footprint suitable for a low-resource ARM64 laptop. Measure rather than assuming that desktop-scale defaults are safe.
- All code must have useful comments for non-obvious model, time-window, persistence, security, and resource decisions.

## Planned Architecture

The intended flow is browser dashboard -> frontend API client -> FastAPI `/api/v1` -> domain services -> Yahoo Finance adapter and server-owned SQLite repositories. The browser has no alternate path to storage or to Yahoo Finance.

The API/application layers should remain separable:

- **Transport:** FastAPI routes, request/response schemas, validation, safe error mapping, and API versioning.
- **Domain:** symbol selection, session/bar semantics, forecast calculation, interval formatting, stale-data policy, and outcome comparison.
- **Adapters:** Yahoo Finance retrieval, SQLite repositories/migrations, backup artifact handling, and clock/calendar boundaries.
- **Presentation:** responsive accessible dashboard, loading/error/empty states, results, and searchable history.
- **Quality:** unit, API, persistence, accessibility, security, performance, restore, and browser regression checks.

The exact module names and endpoint names are implementation decisions for M01. The invariants above are not optional.

## Forecast Contract

The forecast engine must make assumptions visible and reproducible. At minimum, a stored forecast must answer:

- Which user-selected symbol and asset type were requested?
- Which completed close or five-minute bar was the origin, and which close was the target?
- What market timezone, trading-session rule, and provider response were used?
- What historical window, features, parameters, thresholds, and model/version produced the output?
- What probability definitions were used, such as direction or return threshold?
- What do the magnitude intervals mean, what confidence/coverage level do they represent, and are they expressed as percent return, price, or both?
- What data was missing, stale, unavailable, or outside the supported market session?

The current hard-coded and dummy calculations are not acceptance evidence for this contract. M03 must replace or explicitly isolate them behind tested, versioned domain behavior and must not present mock backtests as validated forecasts.

## Task Register

The coordinator assigns the exact task ID and no more than three subagents concurrently. Each implementation milestone runs the three-lane build wave, waits for handoff, then runs the independent QA/docs gates. The listed acceptance evidence is required before status can become **Completed**, and the matching `EXP-M##` gate is required before the milestone is released onward.

### M00 - Documentation Baseline

- **Status:** Completed, docs only.
- **Dependencies:** None.
- **Agents:** `LUNA MAX docs`.
- **Scope:** Create the plan, roadmap, compact agent rules, and honest repository README.
- **Acceptance evidence:** [x] `MVP-PLAN.md`, `MVP-ROADMAP.md`, `AGENTS.md`, and `README.md` exist; [x] current prototype is distinguished from planned implementation; [x] no implementation milestone is presented as completed without its evidence.
- **Verification:** [x] documentation-only diff reviewed; [x] required product invariants, orchestration, evidence fields, repair loop, and final definition of done are present.
- **Repair record:** None at baseline creation.
- **Post-milestone gate:** `EXP-M00` must overwrite and review `SESSION-EXPORT.md`, then record commit/push/remote/CI evidence. No such export or release operation is claimed by this task.

### M01 - API And Application Shell

- **Status:** In progress.
- **Dependencies:** M00.
- **Evidence state:** Implementation-shaped API, configuration, CLI, and static shell material is present; independent QA evidence is not recorded, so M01 is not completed.
- **Build wave:** `SOL HIGH-A` transport/application; `SOL HIGH-B` domain/storage interface assumptions; `SOL HIGH-C` presentation/browser/operations integration. Paths must be disjoint and reports must arrive before QA/docs.
- **Gates:** `LUNA MAX QA` and `LUNA MAX docs` only after the builder wait; export `EXP-M01` after every acceptance row passes.
- **Scope:** Establish the ARM64-friendly application layout, FastAPI service, versioned `/api/v1` boundary, structured errors, health/readiness behavior, frontend shell, and documented local loopback launch path.
- **Acceptance evidence:** [ ] API contract and schema tests pass; [ ] a browser can obtain application data only through `/api/v1`; [ ] no frontend source imports a database driver or opens a SQLite path; [ ] loopback smoke test passes on the target ARM64 environment; [ ] non-obvious code decisions have useful comments.
- **Verification:** [ ] unit and API tests; [ ] negative validation tests; [ ] browser network inspection; [ ] local ARM64 startup and bounded-resource smoke test.
- **Repair record:** Record each failed check as `R-M01-<n>` with failing evidence and rerun result.
- **Post-milestone gate:** `EXP-M01` and its remote/CI record are mandatory; a source inspection or passing-looking artifact cannot substitute for them.

### M02 - SQLite Audit And Immutable Records

- **Status:** In progress.
- **Dependencies:** M01.
- **Evidence state:** Migration, repository, and audit-shaped material is present; independent success/failure/repeat, immutability, restart, and API-boundary evidence is not recorded, so M02 is not completed.
- **Build wave:** `SOL HIGH-A` transport/history contract; `SOL HIGH-B` migrations/repository/immutability; `SOL HIGH-C` history presentation and browser operation. No shared paths during the wave.
- **Gates:** `LUNA MAX QA` and `LUNA MAX docs` only after all three handoffs; export `EXP-M02` after every acceptance row passes.
- **Scope:** Define migrations and repositories for search events, successful/failed/repeated status, immutable forecast inputs, immutable results, append-only outcomes, provenance, and bounded searchable history.
- **Acceptance evidence:** [ ] migration is reproducible on a clean database; [ ] every submission persists exactly one auditable event even on failure or repetition; [ ] input, result, and outcome records cannot be silently overwritten; [ ] history filters and pagination work through `/api/v1`; [ ] restart preserves records.
- **Verification:** [ ] repository and migration tests; [ ] success/failure/repeat matrix; [ ] immutability and concurrent-write tests; [ ] API authorization/boundary test showing no direct browser database access.
- **Repair record:** Record each failed check as `R-M02-<n>` with failing evidence and rerun result.
- **Post-milestone gate:** `EXP-M02` and its secret-review, commit, push, remote, and CI evidence are required before M03 can start.

### M03 - Yahoo Finance Data And Forecast Engine

- **Status:** In progress.
- **Dependencies:** M01 and M02.
- **Evidence state:** Provider/domain/fixture material is present; provider, time-boundary, deterministic-output, stale-data, and ARM64 QA evidence is not recorded, so M03 is not completed.
- **Build wave:** `SOL HIGH-A` forecast request/response boundary; `SOL HIGH-B` provider, calendar, calculation, and immutable writes; `SOL HIGH-C` result presentation and browser instrumentation. No shared paths during the wave.
- **Gates:** `LUNA MAX QA` and `LUNA MAX docs` only after the builder wait; export `EXP-M03` after every acceptance row passes. Live Yahoo checks remain separately identified as `Pass`, `Fail`, `Skipped`, or `Unavailable`.
- **Scope:** Implement the provider adapter, symbol/asset validation, completed-bar selection, close-to-close and latest-completed-5-minute-bar-to-close horizons, probability calculations, magnitude intervals, provenance, stale/missing-data handling, and immutable forecast writes.
- **Acceptance evidence:** [ ] stock and ETF selections follow one tested contract; [ ] an in-progress five-minute bar is excluded; [ ] both horizons identify their origin and target timestamps; [ ] probabilities and magnitude intervals include definitions, levels, units, and model/version; [ ] provider failures and insufficient data create auditable failed searches without fabricated results; [ ] deterministic fixtures reproduce recorded outputs.
- **Verification:** [ ] provider adapter tests with fixtures; [ ] timezone/session and boundary-time tests; [ ] incomplete-bar, missing-bar, stale-data, and out-of-session tests; [ ] numerical invariants and repeatability checks; [ ] ARM64 resource smoke test.
- **Repair record:** Record each failed check as `R-M03-<n>` with failing evidence and rerun result.
- **Post-milestone gate:** `EXP-M03` must include the exact provider limitation/staleness record and successful remote/CI verification; unavailable Yahoo access cannot be summarized as green.

### M04 - Dashboard And Searchable History

- **Status:** In progress.
- **Dependencies:** M01, M02, and M03.
- **Evidence state:** Static dashboard and checked-in browser scenarios are present; independent responsive, keyboard, accessibility, state, and network-boundary evidence is not recorded, so M04 is not completed.
- **Build wave:** `SOL HIGH-A` API/UI contract integration; `SOL HIGH-B` reconstruction/data-shape integration; `SOL HIGH-C` static presentation and browser operations. Paths must remain disjoint.
- **Gates:** `LUNA MAX QA` and `LUNA MAX docs` only after all builder reports; export `EXP-M04` after every journey and acceptance row passes.
- **Scope:** Build the responsive accessible dashboard for symbol selection, forecast submission, result comparison, source/as-of/stale/error context, and searchable history.
- **Acceptance evidence:** [ ] desktop and mobile layouts retain all essential content; [ ] keyboard and screen-reader flows cover search, results, errors, and history; [ ] loading, empty, failed, repeated, stale, and successful states are understandable without color; [ ] result views show both forecast modes, probabilities, and magnitude intervals; [ ] all data requests use `/api/v1`.
- **Verification:** [ ] component and API integration tests; [ ] accessibility audit and keyboard pass; [ ] checked-in browser regression scenarios; [ ] browser network assertion for the API-only boundary; [ ] low-resource render smoke test.
- **Repair record:** Record each failed check as `R-M04-<n>` with failing evidence and rerun result.
- **Post-milestone gate:** `EXP-M04` must preserve browser tool calls and outputs in `SESSION-EXPORT.md`; a generated browser report alone is not the full-session export.

### M05 - Backup, Restore, And Secure Loopback Operations

- **Status:** In progress.
- **Dependencies:** M02 and M04.
- **Evidence state:** Backup/restore and loopback-shaped material is present; round-trip, tamper, non-destructive promotion, security, timeout, and ARM64 QA evidence is not recorded, so M05 is not completed.
- **Build wave:** `SOL HIGH-A` operations API/CLI contract; `SOL HIGH-B` backup, restore, filesystem, and SQLite integrity; `SOL HIGH-C` operational UI/scripts and bounded-run integration. No shared paths during the wave.
- **Gates:** `LUNA MAX QA` and `LUNA MAX docs` only after the builder wait; export `EXP-M05` after every acceptance row passes.
- **Scope:** Add verified backup and restore workflow, integrity/manifest checks, safe restore staging, loopback deployment defaults, input/path validation, timeout limits, and operational documentation.
- **Acceptance evidence:** [ ] a backup includes the required SQLite data and verifiable metadata/checksum; [ ] restore to a clean or staging location validates schema, integrity, and representative counts before promotion; [ ] a tampered, truncated, incompatible, or unsafe-path artifact is rejected; [ ] active data is not silently destroyed; [ ] default bind is loopback and security behavior is documented.
- **Verification:** [ ] backup/restore round trip; [ ] negative artifact and path tests; [ ] restart and recovery test; [ ] loopback exposure check; [ ] resource and timeout checks on ARM64.
- **Repair record:** Record each failed check as `R-M05-<n>` with failing evidence and rerun result.
- **Post-milestone gate:** `EXP-M05` must include artifact/checksum evidence plus secret-review and remote/CI results; local backup files are not release evidence by themselves.

### M06 - QA, Playwright MCP, Browser Regressions, And CI

- **Status:** In progress.
- **Dependencies:** M01, M02, M03, M04, and M05.
- **Evidence state:** Official MCP configuration, checked-in browser scenarios, and CI definitions are present; independent clean-environment, MCP, browser, accessibility, security, restore, and CI results are not recorded, so M06 is not completed.
- **Build wave:** `SOL HIGH-A` CI/API gate integration; `SOL HIGH-B` deterministic fixtures/resource/restore gate integration; `SOL HIGH-C` Playwright MCP/browser/operations integration. No shared paths during the wave.
- **Gates:** wait for all builder reports, then independent `LUNA MAX QA` and `LUNA MAX docs`; export `EXP-M06` only after required gates pass or every limitation is explicitly recorded.
- **Scope:** Configure the official `@playwright/mcp` headless for agent QA, check in automated browser regressions, and establish Git/CI gates for linting, typing or static checks where adopted, unit/API tests, accessibility, security, resource limits, migration, and backup/restore.
- **Acceptance evidence:** [ ] the official MCP configuration is discoverable and runs headless; [ ] browser regressions are checked in and run against a deterministic local app; [ ] CI blocks a failing unit/API/browser/accessibility/security/restore gate; [ ] test artifacts identify task and commit context; [ ] no test depends on the tracked `burry_env/` or local `.venv/`.
- **Verification:** [ ] clean-environment CI run; [ ] intentional-failure gate test; [ ] headless MCP smoke run; [ ] browser regression run on desktop and mobile viewports; [ ] ARM64 or documented equivalent resource run.
- **Repair record:** Record each failed check as `R-M06-<n>` with failing evidence and rerun result.
- **Post-milestone gate:** `EXP-M06` must include the exact CI run/link, browser/MCP artifacts, secret-review result, pushed revision, remote branch, and CI result.

### M07 - Integrated MVP Acceptance

- **Status:** Pending.
- **Dependencies:** M06.
- **Agents/sequence:** `LUNA MAX QA` and `LUNA MAX docs` perform the integrated gates after the build handoff; then independent GPT-6 Astra performs `ASTRA-FINAL`. Repairs use `R-M07-<n>` or `R-ASTRA-<n>` as applicable.
- **Evidence state:** No integrated acceptance or Astra evidence is recorded; M07 remains pending.
- **Scope:** Run the complete user journey and release review on a low-resource ARM64 laptop, reconcile all task evidence, and publish the supported local operation and limitations.
- **Acceptance evidence:** [ ] a user selects a stock and an ETF and receives both forecast horizons; [ ] probabilities and magnitude intervals are traceable to immutable inputs/results; [ ] successful, failed, and repeated searches appear in searchable history; [ ] outcomes can be appended without changing forecasts; [ ] backup/restore is verified; [ ] responsive/accessibility, loopback security, MCP/browser, comments, and Git/CI gates all pass; [ ] README and roadmap state the shipped scope honestly.
- **Verification:** [ ] full CI; [ ] end-to-end browser journey; [ ] restore from the produced artifact; [ ] security and accessibility sign-off; [ ] performance/resource evidence; [ ] coordinator review of every dependency and evidence field.
- **Repair record:** Record each failed release check as `R-M07-<n>` and keep M07 pending until repaired and rerun.
- **Final review gate:** `ASTRA-FINAL` must independently confirm every feature, API/UI endpoint, click/control, browser journey, and persistence effect in an evidence matrix and record `Accepted`. Any gap requires `R-ASTRA-<n>` and QA/Astra retest.
- **Post-milestone gate:** `EXP-M07` follows accepted M07 evidence and Astra acceptance; `EXP-FINAL` is a separate final export/commit/push/remote/CI gate after all Astra repairs.

## Evidence Record Format

Every implementation task must maintain these fields in its task record or linked review:

- **Task ID:** the exact `M##`, `R-M##-<n>`, `EXP-M##`, `ASTRA-FINAL`, `R-ASTRA-<n>`, or `EXP-FINAL` identifier; do not replace it with a generic phase name.
- **Status:** exactly `Pending`, `In progress`, `Blocked`, or `Completed`.
- **Owner/phase:** builder lane, QA gate, docs gate, Astra review, export, or remote verification owner.
- **Dependencies verified:** completed task IDs plus the evidence references that prove each dependency.
- **Change summary:** what changed and what did not change.
- **Acceptance evidence:** one row per acceptance requirement, each with an evidence ID, command/check, environment, UTC timestamp, commit, result (`Pass`, `Fail`, `Skipped`, or `Unavailable`), artifact/link, and named reviewer.
- **Verification result:** independent check name and exact result; a test file, source inspection, generated report, or implementation claim is not a pass by itself.
- **Repair history:** every failure, skip, unavailable provider, stale-data condition, accessibility finding, restore failure, secret-review failure, or connectivity loss; include repair ID, root cause, fix, and rerun result. Use `None` only when no repair was needed.
- **Limitations:** provider, environment, resource, data freshness, coverage, or artifact limitations that remain.
- **Export/remote record:** export task ID, stable `SESSION-EXPORT.md` revision, secret-review result, commit, pushed branch, remote verification, and CI result.
- **Reviewer:** the named independent verifying agent, and for final release the independent GPT-6 Astra reviewer.

Evidence is not a prose promise. A skipped or unavailable check must be recorded as such and cannot satisfy a required acceptance field.

## Verification And Repair Loop

1. The coordinator selects the next pending task only after its dependencies have completed with evidence and assigns the exact task ID.
2. Three non-overlapping `SOL HIGH build` lanes work concurrently, then all builders report before integration or verification begins.
3. `LUNA MAX QA` and `LUNA MAX docs` run their independent gates after the build wait; neither masks a missing result.
4. The coordinator alone integrates, updates status/evidence, and performs git operations. If any check fails, the task remains pending, in progress, or blocked; create `R-M##-<n>` and repair the root cause rather than weakening the check.
5. QA reruns the failed check and affected regression set. Documentation records the new evidence, limitation, exact timestamp/commit, and any skipped or unavailable result.
6. The coordinator marks a milestone completed only when every acceptance field, independent QA/docs review, reviewer field, `EXP-M##` export, secret review, push, remote check, and CI result pass.
7. After M07, `ASTRA-FINAL` must review the complete feature/API/UI/control/journey/persistence matrix. Any gap creates `R-ASTRA-<n>` and requires repair, QA rerun, Astra retest, and explicit `Accepted` before `EXP-FINAL`.

## Final Definition Of Done

The MVP is done only when all of the following are true:

- M00 through M07 have explicit statuses and evidence, with no implementation milestone marked complete by assertion alone.
- A user can select Yahoo Finance stocks and ETFs and receive close-to-close and latest-completed-5-minute-bar-to-close forecasts with clear session/bar semantics.
- Results contain probabilities and defined magnitude intervals with source, as-of, stale/error, model/version, input, and output provenance.
- Every submitted successful, failed, and repeated search is retained, history is searchable through `/api/v1`, and forecast inputs/results/outcomes are immutable or append-only as specified.
- Backup artifacts and restores are verified through integrity, compatibility, representative-data, and non-destructive promotion checks.
- The frontend uses FastAPI `/api/v1` for all application data and has no direct SQLite access.
- The dashboard is responsive and accessible, including keyboard, screen-reader, text-equivalent, loading, empty, stale, repeated, and failure behavior.
- The default deployment is secure loopback, bounded for a low-resource ARM64 laptop, and documented with its limitations.
- The official headless `@playwright/mcp` supports agent QA, automated browser regressions are checked in, and Git/CI gates fail closed on required regressions.
- Code comments explain non-obvious behavior, the supported local workflow is documented, and `README.md` and `AGENTS.md` are reconciled with the evidence actually shipped.
- `ASTRA-FINAL` is independently recorded as `Accepted` after its complete evidence matrix and every `R-ASTRA-<n>` retest.
- `EXP-M00` through `EXP-M07` and `EXP-FINAL` each have a reviewed full-session `SESSION-EXPORT.md`, recorded export revision, secret review, commit, push, remote verification, and CI result; no unavailable or failed gate is hidden.
