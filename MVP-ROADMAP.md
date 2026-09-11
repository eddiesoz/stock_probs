# Stock Probability MVP Roadmap

## Status Snapshot

This roadmap tracks delivery of the local Linux stock-probability web app. The supported target is Linux x86-64/amd64 and ARM64/aarch64, designed for low-resource operation. The current host is native x86_64; no native ARM64 or physical ARM64 performance result is claimed. ARM64 verification first uses local native hardware if available, otherwise local QEMU/OCI multi-arch execution may verify packaging/runtime portability and functional/build/tool behavior only when explicitly labelled **emulated ARM64**. This is not native/physical ARM64 or original-laptop resource evidence. Repository shape is not acceptance evidence.

- **Completed:** `M00`, documentation baseline only. The four roadmap deliverables are `MVP-PLAN.md`, `MVP-ROADMAP.md`, `AGENTS.md`, and `README.md`.
- **Documentation repair:** `R-M00-2` is **Completed** only for the four-file policy reconciliation; it does not accept implementation.
- **Completed checkpoint:** `EXP-M00` is **Completed** with the current coordinator export, full regex secret review, exact pushed SHA `18da1af0b6bc31020d3587e472b8197146795bf1`, and matching `git ls-remote` result; its evidence is recorded below.
- **In progress, not completed:** `M01`, `M02`, and `M03`. M01 behavior and independent repair rows pass in scope, but `EXP-M01` release evidence is absent; M02/M03 retain only partial historical checks.
- **Blocked, not completed:** `M04`, `M05`, and `M06`; their records retain failed findings, cancelled retests, duplicate repair IDs, or missing mandatory release gates.
- **Pending:** `M07`, `M08`, `EXP-M01` through `EXP-M08`, `ASTRA-FINAL`, and `EXP-FINAL`.
- **Supplied Git receipt:** remote `main` was historically reported at `2a7a3bf66c3665552a46d0bd523544a01f894b3f`; it is not a current checkpoint. The old hosted Actions receipt is obsolete x64-only context and not a current gate or release proof. No external pipeline is in scope.
- **Current-task limitation:** `R-M00-1` is immutable historical documentation recovery. `R-M00-2` is a documentation-only policy repair; it does not run implementation QA, remove implementation files, create a walkthrough, export, commit, push, or verify a new Git revision. No unavailable field is turned green.
- **Rule:** no milestone advances to `Completed` from implementation claims, a test file, a generated artifact, or a narrative summary. The exact evidence record in `MVP-PLAN.md` is authoritative. M01's local workflow deletion is not remote removal until its commit/push and exact remote revision are verified.

### `R-M00-1` documentation recovery record

This immutable record preserves the state observed during the original recovery. Its then-missing `EXP-M00` acceptance is superseded for current chronology only by the separately recorded completed checkpoint; the historical record is not rewritten.

- **Status:** Completed for documentation reconciliation only; no implementation acceptance.
- **Owner/phase:** `LUNA MAX docs`, M00 recovery/documentation gate.
- **Change/evidence:** The four documentation files were reconciled for architecture support, current remote receipt, recovered export facts, collision aliases, restored contract rows, dual-architecture and visual gates, orchestration, and checkpoint receipt protocol. The evidence is a final four-file `git status`/`git diff` scope review plus the historical/current receipts recorded here and in `MVP-PLAN.md`; exact UTC time, commit, and independent implementation reviewer are unavailable for this docs-only task.
- **Limitations:** Historical ARM64 checks are from an uncommitted historical revision; no current dual-arch, full release, screen-reader, fresh alias-repair, secret-review, or `EXP-M00` acceptance is claimed. Old external-pipeline wording is superseded by `R-M00-2` and is not a current gate.

### `R-M00-2` documentation-only policy repair

- **Status:** `Completed`.
- **Scope note:** This is a four-document reconciliation only; no implementation acceptance.
- **Owner/phase:** `LUNA MAX docs`, M00 documentation repair.
- **Dependencies verified:** immutable `R-M00-1`; no implementation dependency was accepted.
- **Change summary:** external pipeline requirements were removed; local testing and Git checkpoint semantics were made explicit; ARM64 native/emulated limits were defined; M01/M06 workflow removal and local fail-closed Make/scripts were required; M08/`EXP-M08`, walkthrough, retrospective, and Astra order were added; stale M05 wording was corrected. No implementation/config/test path or `SESSION-EXPORT.md` path was edited.
- **Evidence ledger:**

  | Evidence ID | Requirement/check | Environment, UTC time, commit | Result, artifact, reviewer, limitation |
  | --- | --- | --- | --- |
  | `R-M00-2-E1` | `git status`/`git diff` scope review of the four documentation paths | Current native x86_64 Linux; exact UTC time and commit unavailable; `?? .vscode/` untouched | **Pass** for documentation scope; artifact: current worktree; reviewer: `LUNA MAX docs`; no implementation QA. |
  | `R-M00-2-E2` | Self-review of local-only, ARM64, M08, sequence, vocabulary, and M05 policy changes | Current docs; exact UTC time and commit unavailable | **Pass** as documentation content; artifact: four docs; reviewer: `LUNA MAX docs`; no behavior inferred. |
  | `R-M00-2-E3` | Workflow removal, local gate execution, M08 artifact/browser QA, and retrospective | Not run by this docs-only task | **Unavailable**; future M01/M06/M07/M08/Astra evidence is required and visible. |
  | `R-M00-2-E4` | R-M00-1 identity/history and collision aliases retained | Current docs; exact UTC time and commit unavailable | **Pass** as documentation content; reviewer: `LUNA MAX docs`; no repair retest implied. |
- **Limitations and export/Git:** No implementation QA, ARM64 native/emulated run, walkthrough artifact, browser-control check, retrospective, export, commit, push, or new Git revision verification was performed by `R-M00-2`. The later coordinator record `EXP-M00` is completed; `EXP-M01` through `EXP-M08` and `EXP-FINAL` remain pending/unavailable in their exact records.

### `EXP-M00` current checkpoint record

- **Status:** `Completed`.
- **Owner/phase:** coordinator export gate; reviewer/coordinator `OpenCode gpt-5.6-sol`.
- **Dependencies verified:** `R-M00-1` and `R-M00-2`; M00 documentation baseline.
- **Export evidence:** active session `ses_f71ec0499ffeokWj4h6tVwyYk1` parsed as JSON with `1,413,943` bytes, `4,268` physical lines, `23` messages, `153` parts, `44` tool parts, and `10` task outputs.
- **Secret evidence:** full regex review found two credential-like candidates and both were masked; no private-key, AWS, GitHub, or Bearer patterns were found. **Pass**.
- **Git evidence:** diff/check review passed; exact pushed SHA `18da1af0b6bc31020d3587e472b8197146795bf1` matched `git ls-remote origin refs/heads/main`. No remote CI was used. The unrelated `?? .vscode/` stayed untouched.
- **Timestamp limitation:** the consumed handoff did not supply an exact UTC completion timestamp; it is recorded as unavailable, not inferred.
- **Next gate:** `M01` is **In progress**; `EXP-M01` is the next gate.

## Dependency-Ordered Milestones

| ID | Milestone | Dependencies | Status | Evidence state and next gate |
| --- | --- | --- | --- | --- |
| `M00` | Documentation baseline | None | Completed | `R-M00-1` is immutable historical recovery and `R-M00-2` reconciles the current local-only contract; this is docs-only. `EXP-M00` is now the completed exported revision at SHA `18da1af0b6bc31020d3587e472b8197146795bf1`. |
| `M01` | API and application shell | M00, `EXP-M00` | In progress | All three independent QA retests pass their assigned behavior scopes; `R-M01-3`–`R-M01-15` are completed for exact scoped repairs. Local workflow deletion is present, but remote removal and the `EXP-M01` export/secret-review/commit/push/exact-revision gate remain pending. |
| `M02` | SQLite audit and immutable records | M01 | In progress | Migration/repository material observed; failure/repeat, immutability, saved-reopen, retention, restart, and boundary evidence remain open. Then `EXP-M02`. |
| `M03` | Yahoo Finance data and forecast engine | M01, M02 | In progress | `R-M03-1`, `R-M03-2`, and `R-M05-3` repair checks were independently passed, but the complete identity/evaluation/limitation/milestone/export/Git-checkpoint record remains open. Then `EXP-M03`. |
| `M04` | Dashboard and searchable history | M01, M02, M03 | Blocked | Browser checks passed for exercised journeys, but `R-M04-1` independent retest was cancelled; fresh aliases `R-M04-2`/`R-M04-3` carry assistive/mobile obligations. Then `EXP-M04`. |
| `M05` | Backup, restore, and secure loopback operations | M02, M04 | Blocked | Late backup retest reported `make check` Pass, 83 tests/89.23%, and named adversarial checks; repair-ID collisions and release gates remain. Fresh aliases `R-M05-5`/`R-M05-6` carry the unresolved obligations. Then `EXP-M05`. |
| `M06` | Local QA, MCP, browser regressions, and fail-closed gates | M01, M02, M03, M04, M05 | Blocked | `R-M06-1` independent retest was cancelled; fresh aliases `R-M06-2`/`R-M06-3`/`R-M06-4`, dual-arch, resource, local-gate, and release evidence remain open. Then `EXP-M06`. |
| `M07` | Integrated MVP acceptance | M06 | Pending | Full local user journey, persistence, restore, dual-architecture semantics, visual/AT, release reconciliation, and sign-off remain open. Then `EXP-M07`. |
| `M08` | Instructional Walkthrough | M07, `EXP-M07` | Pending | Deterministic fixture walkthrough, real local app, official browser tooling, actual-control evidence, accessibility/transcript artifact, and prompt/approved-plan retrospective remain open. Then `ASTRA-FINAL`, `EXP-M08`, and `EXP-FINAL`. |

### Current `M01` implementation and independent QA record

- **Status:** `In progress`.
- **Owner/phase:** three `SOL HIGH build` handoffs followed by three independent `LUNA MAX QA` retests; docs consumes the completed QA record. Builder checks are not acceptance evidence.
- **Dependencies verified:** `M00` and completed `EXP-M00` at SHA `18da1af0b6bc31020d3587e472b8197146795bf1`.
- **Builder tasks and repairs:** A `ses_f718d04e0ffeqdv2i56c6k72Pg`, repair `ses_f71674730ffeERY2M1p9htV2Or`, changed `pyproject.toml`, `requirements.lock`, transport/application `src/stock_probs/` files (`api.py`, `cli.py`, `config.py`, `schemas.py`, `service.py`), and API/config tests. B `ses_f718d04a2ffexmhN4OlHuJlTwt`, repair `ses_f716746fbffe9qOSoMniDzfbNi`, changed domain/provider/repository/fixture files and domain/provider/repository tests. C `ses_f718d0469ffeVig2Xix5cE5N1V`, repair `ses_f716746e8ffeEjA0BRqajZ0ycH`, deleted `.github/workflows/ci.yml` and `scripts/install-node-arm64.sh`, changed `.opencode/agent/sol-build.md`, `Makefile`, static UI, browser tooling, and operations tests, and added the ARM64/bootstrap/local-gate scripts. The exact path inventory and summaries are authoritative in `MVP-PLAN.md`.
- **QA evidence:**
  - `M01-QA1`, task `ses_f71521f9dffeWxILBgUaEBhf0O`, native x86_64, completed `2026-09-11T04:27:31Z`: `R-M01-3`–`R-M01-7`, `167/167` harness, `100` non-live passed/`4` deselected/`89.17%`, Ruff+S, strict mypy across 12 production files, 51 comments, compile, and shell checks passed. Artifact `/tmp/opencode/stock_probs-m01-qa`; live/browser/ARM/export skipped in this lane only.
  - `M01-QA2`, task `ses_f71521f5effeKu8HF2uh3fxJT1`, native x86 Python `3.11.15` plus explicitly **emulated ARM64** OCI/QEMU `7.2.0`: executable support metadata `>=3.11,<3.12`, direct no-`make` local gate, clean non-edit wheel install/migration/loopback, safe induced failure nonzero/recorded `Fail`, Node x64/arm64 checksum, OpenCode schema/config/MCP, emulated package/install/migration/loopback, and cleanup passed. Artifacts `test-results/local-gates` and `test-results/arm64`; completion UTC was not supplied. No native/physical ARM64 or performance result.
  - `M01-QA3`, task `ses_f71521efbffeEdTmM7GL4wYmW2`, native x86_64, latest artifact `2026-09-11T04:35:01.820Z`: no product defects; `R-M01-14`/`R-M01-15` and browser `R-M01-3`/`R-M01-4` passed; checked-in 6 desktop + 6 mobile scenarios, no overflow at 360/390/768/1280/1440, stock/ETF identity checks, 53 `/api/v1` fetch/XHR requests with no forbidden/leaked access, structured errors/docs/OpenAPI/console, and official MCP actual interaction passed. Artifacts `/tmp/opencode/m01qa-*`; screen-reader/later polish remain M04/M06.
- **Repair status:** `R-M01-3` and `R-M01-4` completed for router/OpenAPI and startup-harness scoped behavior; `R-M01-5`–`R-M01-7` completed for their coordinator-assigned QA1 scopes; `R-M01-8`–`R-M01-13` completed for their coordinator-assigned package/bootstrap/local-gate/architecture/tool scopes; `R-M01-14`–`R-M01-15` completed for their coordinator-assigned QA3 scopes, with the recorded browser/API/identity/error/docs/OpenAPI/console/MCP evidence. No `R-M01-16`–`R-M01-19` records were created from stale labels.
- **Checkpoint limitation:** local `.github/workflows/ci.yml` deletion is evidenced in the worktree, but remote removal remains pending until M01 is committed, pushed, and verified by exact remote revision. The host lacks system `make`; the direct executable gate passed and `Makefile` is a convenience wrapper. Physical ARM64 performance is `Unavailable`. `EXP-M01` is **Pending** and is the next gate.

## Recovered Evidence Register

The recovered pre-checkpoint export is recorded as valid parsed JSON of `5,065,391` bytes, `11,093` physical lines, `80` top-level messages, and `384` parts. It contains parent task calls and summarized handoffs, not complete child transcripts. Its historical records use session `ses_f73b976e8ffekNCE6SNIanpXFb`, reference `/home/eddie/stock_probs` and historical `HEAD cb7c1b1`, and concern uncommitted implementation files, so they are recorded as evidence with limitations rather than treated as current acceptance. It is not the current completed checkpoint.

- `M01`–`M04`, QA task `ses_f72f4e2f0ffe6hMpBTmXUnWybW`: **Fail** at `2026-09-10T21:27:45Z`–`21:27:57Z`; affected milestones remain blocked, and missing-bar quality, router error-envelope, and OpenAPI findings created `R-M03-1`, `R-M03-2`, `R-M01-1`, and `R-M01-2`.
- `M04`/`M06`, QA task `ses_f72f4e261ffeLWQEjyJI4k3hea`: **Pass** for eight desktop/mobile browser checks, official MCP smoke, 51 API checks, axe, controls, and API-only network checks; milestone acceptance remained open.
- `M05`/`M06`, QA task `ses_f72f4e163ffehgqJPXwbY7ujrX`: **Blocked** with `R-M05-1`, `R-M05-2`, `R-M05-3`, `R-M05-4`, and `R-M06-1`.
- Repair task `ses_f72c4f276ffeJm9WRj0aBXCM1X` and independent retest `ses_f72ab5097ffexdJCun6m6thzDi`: `R-M03-1`, `R-M03-2`, and `R-M05-3` **Pass**; 83 deterministic tests, 89.23% coverage, and live ACDC/SPY checks were recorded; no commit/push.
- Repair task `ses_f72c4f20effeDoLPC0FuHaaGjZ`: builder checks reported **Pass** for `R-M01-1`, `R-M01-2`, `R-M04-1`, and `R-M06-1`; independent retest `ses_f72ab5027ffeR0shgnOsYGX47N` was **Cancelled**, so those repairs remain unaccepted.
- Repair task `ses_f72c4f1baffeECZSQ37ujzSmCJ` and retest `ses_f72ab4fc9ffepKCTOlUxIWlRrt`: the late independent retest reported `make check` **Pass**, 83 tests, 89.23% coverage, plus named HMAC/ZIP/permission/restore checks. The earlier concurrent builder aggregate limitation is not a current unresolved failure; the historical uncommitted revision and export/secret-review/push/Git-revision limitations remain.
- Recovered historical `EXP-M00`: the transcript ends with `opencode export ses_f73b976e8ffekNCE6SNIanpXFb > SESSION-EXPORT.md` in `running` state. Its export/review/commit/push/Git-revision evidence is **Unavailable** for that historical attempt; it is not the current checkpoint.
- Current `EXP-M00`: **Completed**. Active session `ses_f71ec0499ffeokWj4h6tVwyYk1` parsed as `1,413,943` bytes/`4,268` lines/`23` messages/`153` parts/`44` tool parts/`10` task outputs; two credential-like candidates were masked, no private-key/AWS/GitHub/Bearer patterns were found, and exact pushed/remote SHA `18da1af0b6bc31020d3587e472b8197146795bf1` matched. Reviewer/coordinator `OpenCode gpt-5.6-sol`; no remote CI. Exact UTC completion timestamp was not supplied.

The historical transcript reuses `R-M01-1`, `R-M05-1`, `R-M06-1`, and `R-M04-1` for different defects. `R-M00-1` allocates fresh aliases in the register below; historical labels are not altered. Check-level passes do not override cancelled retests or unavailable release gates.

### Historical collision/alias register

| Historical source-qualified label | Unresolved obligation | Fresh unique repair ID | Status |
| --- | --- | --- | --- |
| `R-M01-1` / QA `ses_f72f4e2f0ffe6hMpBTmXUnWybW` | Router errors/OpenAPI behavior | `R-M01-3` | Completed for current scoped retest; see M01 record |
| `R-M01-1` / builder `ses_f72c4f20effeDoLPC0FuHaaGjZ` | Startup harness | `R-M01-4` | Completed for current scoped retest; see M01 record |
| `R-M05-1` / QA `ses_f72f4e163ffehgqJPXwbY7ujrX` | Malicious backup | `R-M05-5` | Pending |
| `R-M05-1` / backup builder `ses_f72c4f1baffeECZSQ37ujzSmCJ` | Chunked request | `R-M05-6` | Pending |
| `R-M06-1` / QA/operations `ses_f72f4e163ffehgqJPXwbY7ujrX` | Port collision | `R-M06-2` | Pending |
| `R-M06-1` / repair builder `ses_f72c4f20effeDoLPC0FuHaaGjZ` | Documentation CSP | `R-M06-3` | Pending |
| `R-M06-1` / repair builder `ses_f72c4f20effeDoLPC0FuHaaGjZ` | CSV formula issue | `R-M06-4` | Pending |
| `R-M04-1` / browser/accessibility `ses_f72f4e261ffeLWQEjyJI4k3hea` | Actual assistive-technology evidence unavailable | `R-M04-2` | Pending; evidence unavailable |
| `R-M04-1` / repair builder `ses_f72c4f20effeDoLPC0FuHaaGjZ` | Mobile error focus | `R-M04-3` | Pending |

The source task IDs are evidence locators, not independent acceptance reviews. `R-M01-5` through `R-M01-15` are current coordinator-assigned M01 records in the M01 record below. The screen-reader/assistive-technology gap is separately unavailable; axe and keyboard results cannot close it. Mobile focus, CSP, and CSV still require the cancelled independent API/UI retest. Stale labels `R-M01-16` through `R-M01-19` were not created.

## Mandatory Delivery Workflow

All future work uses exactly three concurrent `SOL HIGH build` instances in a build wave and never more than three concurrent builders. The coordinator does not implement shared files, test, review, or write roadmap prose; it owns mechanical integration, status, and git only.

### Build wave

Every implementation or repair wave uses three `SOL HIGH build` instances with non-overlapping ownership, declared against the exact `M##` or `R-M##-<n>` ID before work begins:

| Builder | Non-overlapping ownership lane |
| --- | --- |
| `SOL HIGH-A` | Transport/application: FastAPI routes, schemas, settings, CLI, package/launch configuration, and transport-facing implementation tests |
| `SOL HIGH-B` | Domain/provider/persistence: forecast rules, Yahoo/fixture adapters, services, migrations, SQLite, backup/restore, and domain/storage tests |
| `SOL HIGH-C` | Presentation/browser/operations: static UI, browser harness, scripts, Make/local-gate tooling, dependency/runtime tooling, and presentation-facing implementation tests |

Each builder reports its exact task ID, changed paths, checks, failures, assumptions, and handoff. No two builders edit the same path. Every implementation/config/test path is assigned to A, B, or C before work starts; the four roadmap docs belong only to `LUNA MAX docs`, and `SESSION-EXPORT.md` belongs only to its export gate. A shared interface is handed to the coordinator for mechanical integration rather than edited concurrently; the coordinator does not author implementation/config/test content.

### Wait and verification gates

1. Record the task ID, dependencies, lane manifest, change summary, and one acceptance row per requirement.
2. Run all three non-overlapping `SOL HIGH build` lanes concurrently.
3. Wait for all three builder reports before integration or acceptance review.
4. Only after that wait, run independent `LUNA MAX QA` and `LUNA MAX docs` gates. They may prepare concurrently when their scopes are independent; docs finalizes only after consuming the completed QA record and cannot convert missing QA into a pass.
5. Record every pass, fail, skipped, unavailable, stale, accessibility, restore, secret-review, and connectivity result. A failed or unavailable required gate blocks acceptance.
6. For a failure, create `R-M##-<n>`, repair the root cause, repeat the builder handoff, QA/docs gates, and affected regression checks. Never weaken the acceptance requirement.

The canonical sequence is `R-M00-1` -> `EXP-M00` (**Completed**) -> `M01` (**In progress**) -> `EXP-M01` (**next gate**) -> `M02`/`EXP-M02` -> `M03`/`EXP-M03` -> `M04`/`EXP-M04` -> `M05`/`EXP-M05` -> `M06`/`EXP-M06` -> `M07` QA/docs -> `EXP-M07` -> `M08` walkthrough QA/docs -> `ASTRA-FINAL` -> repairs/retests until the result is `Accepted` -> `EXP-M08` -> `EXP-FINAL`. No later task may be used to backfill a missing earlier export gate.

## Versioned Export, Commit, Push, And Remote Gates

After each roadmap milestone through M07, before the next milestone starts, complete its exact export task: `EXP-M00`, `EXP-M01`, `EXP-M02`, `EXP-M03`, `EXP-M04`, `EXP-M05`, `EXP-M06`, or `EXP-M07`. `EXP-M08` is the post-Astra checkpoint for the final walkthrough and its retrospective.

1. Use OpenCode `/export`, or a verified CLI equivalent, to overwrite the one tracked root artifact `SESSION-EXPORT.md`.
2. Confirm that the artifact is a full-session export containing tool calls and subagent outputs, not a summary or partial log.
3. Review the complete export for secrets before commit. A skipped, failed, unavailable, or connectivity-blocked secret review blocks the gate.
4. Record the export task ID, export revision, secret-review result, checkpoint commit, pushed branch, exact Git remote revision verification, artifact/link, UTC timestamp, environment, and named reviewer.
5. The coordinator performs the commit/push and verifies the exact Git remote revision. A failed, skipped, unavailable, or connectivity-blocked push or revision check remains exactly that and blocks the checkpoint.

The stable export path is intentionally overwritten; the recorded Git commit/revision versions each export and provide a recoverable checkpoint so work can resume after connectivity loss. Commit/push the reviewed export as checkpoint SHA X, verify that exact SHA on the Git remote, and preserve that receipt in the next checkpoint. The recovered transcript shows an incomplete historical `EXP-M00` attempt, but the current coordinator record completed `EXP-M00` at SHA `18da1af0b6bc31020d3587e472b8197146795bf1` with the exact evidence above. Its handoff did not supply an exact UTC completion timestamp; that limitation remains visible. No GitHub workflow, hosted runner, or external pipeline is used.

## Restored Milestone Acceptance Rows

The condensed plan had omitted the following contract rows. They are restored here and remain open until exact evidence exists; implementation-shaped files do not satisfy them. M01's scoped current evidence is recorded above, but its checkpoint-dependent fields remain open.

| Milestone | Required acceptance rows |
| --- | --- |
| `M01` | Company-name lookup must preserve symbol, exchange, stock/ETF asset type, and instrument identity through the API; clean package install, `/api/v1` boundary, and loopback behavior are verified on native x86-64 and local native or explicitly emulated ARM64. Any `.github/workflows/ci.yml` path is removed during M01/M06. |
| `M02` | Saved forecast reopen returns immutable recorded inputs/results; successful, failed, and repeated searches remain auditable; bounded history has no automatic query-history expiry and explicit retention/disk limits are tested. |
| `M03` | Both horizons exclude an in-progress bar and expose origin/target/session semantics; up/down/unchanged, `+/-1%`, `+/-3%`, `+/-5%`, `+/-10%`, conditional gain/loss, and 50/80/95 return/price intervals are defined; company identity, Yahoo approximate 60-day five-minute archive limitation, chronological walk-forward evaluation, baseline comparison, Brier/reliability, interval coverage, and rare-event uncertainty are evidenced. |
| `M04` | Saved reopen is distinct from labelled fresh historical-cutoff reconstruction; historical price and return-distribution charts have text/table equivalents; CSV and JSON exports work; Signal Ledger visual direction is polished at 360/390/768/1280/1440 with no overlap/overflow, tabular numeric hierarchy, all states, reduced motion, WCAG AA, keyboard, and actual assistive-technology evidence. Axe and keyboard do not substitute for screen-reader evidence. |
| `M05` | Automatic due and pre-migration backups, retention/disk limits, non-expiring query history, safe staging/promotion, trust-key transfer/lifecycle, and fail-closed missing/wrong-key behavior are verified. Cross-architecture backup/restore runs x86-64 -> ARM64 and ARM64 -> x86-64 using local native ARM64 when available or labelled emulation otherwise. |
| `M06` | Local native x86-64 and local native ARM64 when available, otherwise explicitly labelled QEMU/OCI emulated ARM64, receive actual package build/clean install, `make check`, loopback, Node/Chromium, official headless MCP application interaction, desktop/mobile tests, accessibility/security/export-safety tests, and functional/tool evidence. Native x86 resource targets are measured locally; physical ARM64 low-resource performance is `Unavailable` without local native ARM64 hardware and is never inferred from emulation. |
| `M07` | The integrated matrix covers every row above, both architecture paths, both backup directions and trust-key lifecycle, all five viewports and states, actual assistive technology, the complete local user journey, local fail-closed gates, honest ARM64 limitations, and honest out-of-scope classification. Optional dark mode/news are not contract; options/public hosting are out of scope. |
| `M08` | A deterministic-fixture, real-local-app walkthrough under `docs/walkthrough/` (annotated screenshots or accessible GIF plus Markdown/transcript) covers setup through shutdown, all required states/features, actual controls, desktop/mobile accessibility, bounded size, reproducible generation, no secrets/paths, and the prompt/approved-plan retrospective. Retrospective gaps receive `R-M08-<n>` repairs before Astra. |

The M01 behavior rows above have current independent scoped pass evidence in the M01 record; the M01 milestone and its checkpoint-dependent workflow/export/Git fields are not accepted by that evidence alone. All later rows remain open, and neither `R-M00-1` nor `R-M00-2` accepted implementation behavior.

## M08 Walkthrough Gate

`M08` is the final roadmap milestone before `ASTRA-FINAL`. It is `Pending` until accepted `M07` implementation evidence and `EXP-M07` are present. The artifact must be generated locally from deterministic fixture data while the real local app is running, using official browser tooling against actual controls. The preferred form is a compiled sequence of annotated screenshots when that is more accessible, readable, or lightweight than a GIF; the alternative is an accessible animated GIF with companion Markdown/transcript.

The tracked artifact under `docs/walkthrough/` (or an explicitly recorded equivalent) must be lightweight and bounded to 20 MiB, reproducible with `make walkthrough` or a checked-in local generation script, and free of secrets and local filesystem paths. It must include numbered steps, captions, useful alt text, a transcript/instructions, desktop and mobile views, and the generation command, fixture identity, app revision, browser-tool context, size, and limitations. Actual-control browser QA must cover:

- setup/startup, readiness, normal shutdown, and troubleshooting;
- symbol/company selection, stock and ETF selection, identity confirmation, and submission;
- both forecasts and their completed-bar/session semantics;
- direction, probability, threshold, conditional gain/loss, return/price interval, provenance, stale, and provider-limitation reading;
- stale, failure, validation, insufficient-data, and repeated states;
- history filters, saved immutable reopen, fresh historical reconstruction, CSV/JSON export, and append-only outcomes;
- backup/restore/status where exposed in the UI, otherwise an explicit `Not exposed in UI` label;
- accessibility names/focus, keyboard, reduced motion, responsive desktop/mobile use, and actual controls.

After the artifact exists, M08 must compare the shipped app with the original prompt and original approved plan recovered from `SESSION-EXPORT.md`. The retrospective enumerates missing or materially altered features and assesses whether the UI is beautiful, well designed, and usable using the screenshots/GIF, transcript, browser, accessibility, and responsive evidence. Any incomplete recovered source is recorded as `Unavailable`, never inferred. Each gap creates `R-M08-<n>` and is repaired and retested before Astra; no gap is hidden by presentation quality. `R-M00-2` did not create this artifact or perform this QA.

## Final Independent Astra Gate

After `M08` walkthrough QA/docs evidence is complete, independent GPT-6 Astra executes `ASTRA-FINAL`. Astra must confirm working behavior by execution and evidence, not by reading implementation claims. Its matrix must include a separate row for every:

- product feature and acceptance requirement;
- API endpoint, including health/readiness, company-name/instrument lookup, forecast, history/reconstruction/prices, CSV and JSON export, immutable-result, outcome, backup, restore, documentation, and static-asset surfaces discovered in the final route inventory;
- UI click/control, including skip navigation, symbol entry/validation, stock/ETF selection, forecast submit, history filters, reconstruction, pagination, and export;
- desktop/mobile browser journey at 360/390/768/1280/1440, including empty, loading, success, repeated, failed, stale, validation, saved reopen, fresh historical reconstruction, chart/table, export, reduced-motion, accessible keyboard/actual screen-reader, API-only, and security-console journeys;
- persistence effect, including successful/failed/repeated search events, immutable input/results, append-only outcomes/corrections, bounded non-expiring history, restart, automatic/due/pre-migration backup, retention/disk limits, trust-key lifecycle, verification, both-direction cross-architecture restore, and restore promotion.
- M08 walkthrough artifact, every numbered instruction/frame or GIF segment, alt text/caption/transcript, deterministic generation command, artifact-size/no-secret/path review, actual-control browser evidence, desktop/mobile usability, and the retrospective comparing the shipped app with the original prompt and approved plan recovered from `SESSION-EXPORT.md`, including the beautiful/well-designed/usable assessment and every `R-M08-<n>` repair.

Each row records task ID `ASTRA-FINAL`, check/command, environment, UTC timestamp, commit, result, artifact/link, limitation, and reviewer. Any gap or non-pass creates `R-ASTRA-<n>`. The repair receives the normal three-builder handoff and QA/docs gates, then Astra retests the failed row and affected matrix. Repeat until the independent record explicitly says **Accepted**. `EXP-M08` and `EXP-FINAL` cannot be green before that acceptance; `EXP-M07` is the earlier M07 checkpoint.

## Roadmap Completion Record

Every milestone, repair, export, and final review uses these exact fields:

- **Task ID:** exact `M00`–`M08`, `R-M##-<n>`, `EXP-M00`–`EXP-M08`, `ASTRA-FINAL`, `R-ASTRA-<n>`, or `EXP-FINAL`.
- **Status:** `Pending`, `In progress`, `Blocked`, or `Completed`.
- **Owner/phase:** builder lane, QA, docs, Astra, export, or Git remote verification.
- **Dependencies verified:** task IDs and evidence links.
- **Change summary:** what changed and what did not change.
- **Acceptance evidence:** one item per requirement with evidence ID, check/command, environment, UTC timestamp, commit, result (`Pass`, `Fail`, `Skipped`, or `Unavailable`), artifact/link, and reviewer.
- **Repair history:** failure or limitation, repair ID, root cause, fix, and rerun result; do not omit skips or unavailable providers.
- **Limitations:** stale data, provider coverage, ARM64/resource, accessibility, restore, connectivity, or artifact limits.
- **Export/Git result:** export ID and revision, full-session artifact, secret review, checkpoint commit, push, exact Git remote branch/revision verification, and the next-checkpoint receipt preserving that result. No external-pipeline field exists.
- **Named reviewer:** independent QA/docs verifier, and independent GPT-6 Astra for final acceptance.

## Release Definition Of Done

The roadmap is complete only when:

- `M00` through `M08` have explicit evidence-backed statuses, and no implementation milestone is completed by assertion alone.
- A user-selected Yahoo Finance stock and ETF each demonstrate company-name/instrument identity and both forecast horizons with completed-bar/session semantics, explicit direction/threshold and conditional gain/loss probabilities, 50/80/95 return/price intervals, evaluation evidence, provenance, and honest stale/error/archive limitations.
- SQLite retains successful, failed, and repeated searches; immutable forecast inputs/results; and append-only outcomes, with searchable history through FastAPI `/api/v1` and no browser database access.
- Saved reopen and fresh historical reconstruction are distinct; charts have text equivalents; CSV/JSON export, due/pre-migration backup, retention/disk rules, non-expiring query history, trust-key lifecycle, and both-direction cross-architecture restore have independent evidence.
- Responsive Signal Ledger UI at 360/390/768/1280/1440 has no overlap/overflow, tabular numeric hierarchy, all states, charts/tables, reduced motion, WCAG AA, keyboard/actual screen-reader evidence; secure loopback behavior, bounded local x86-64/ARM64 operation with honest emulation labels, official headless `@playwright/mcp`, browser regressions, useful code comments, and fail-closed local Make/scripts have independent evidence.
- `README.md` and `AGENTS.md` are reconciled with the final supported scope and evidence; they are roadmap deliverables, not optional commentary.
- M08 has a tracked, lightweight, accessible walkthrough generated from deterministic fixtures against the real local app, with actual-control browser evidence, desktop/mobile instructions, a bounded artifact, and a completed prompt/approved-plan retrospective. Any gap is repaired before Astra.
- `ASTRA-FINAL` is independently **Accepted** after every feature/API/UI/control/journey/persistence row and every `R-ASTRA-<n>` retest.
- `EXP-M00` through `EXP-M08` and `EXP-FINAL` contain reviewed, secret-free full-session `SESSION-EXPORT.md` revisions with commit, push, exact Git remote revision verification, and no hidden failed, skipped, unavailable, or blocked field.
- Optional dark mode/news are not contract requirements; options and public hosting are out of scope for this local app.
