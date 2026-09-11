# Stock Probability MVP Plan

## Status And Scope

This is the implementation contract for the planned local Linux stock probability web app. The supported target is Linux x86-64/amd64 and ARM64/aarch64, with low-resource operation as a release constraint. The current host is native x86_64; no native ARM64 or physical ARM64 performance result is claimed. ARM64 verification first uses local native ARM64 hardware if available, otherwise local QEMU/OCI multi-arch execution may verify packaging, runtime, functional, build, and tool behavior only when every result is labelled **emulated ARM64**. Emulation is not native/physical ARM64 or original-laptop resource evidence. Repository presence is an observation, not acceptance evidence.

- `M00` is **Completed** for the documentation-only contract: `MVP-PLAN.md`, `MVP-ROADMAP.md`, `AGENTS.md`, and `README.md`.
- `EXP-M00` is **Completed** as the M00 coordinator checkpoint; its exact export, secret-review, commit, push, and remote-revision evidence is recorded below.
- `M01` and `EXP-M01` are **Completed**: all three independent QA retests passed their assigned behavior scopes, `R-M01-3` through `R-M01-15` are completed for those scoped repairs, and the exact checkpoint is SHA `5424fa3e22d9229d038d376512e59b3f35c97e78`.
- `M02` is **In progress** only because `EXP-M02` secret review, export, commit, push, and exact remote-revision evidence remain pending. Its scoped `R-M02-1`–`R-M02-5`, `R-M02-10`–`R-M02-20`, `R-M02-30`–`R-M02-32`, `R-M02-41`–`R-M02-42`, and `R-M02-55` records have independent pass evidence. `M03` is **In progress** with its own complete milestone record still open.
- `M04` is **Blocked** pending its own later evidence. `M05` and `M06` are **Blocked** by recorded QA findings, incomplete repair/retest records, and missing release gates; M02's scoped behavior pass does not release those later milestones.
- `M07`, `M08`, and `ASTRA-FINAL` are **Pending**. `EXP-M00` and `EXP-M01` are completed; `EXP-M02` through `EXP-M08` and final `EXP-FINAL` remain pending.
- A task may move to **Completed** only after every acceptance item, independent QA verification, repair history, reviewer, export, secret review, local commit, push, and Git remote revision verification is recorded. Implementation claims alone never change status. A physical ARM64 performance result is never inferred from emulation.

The supplied Git remote receipt is historical context only: remote `main` was reported at `2a7a3bf66c3665552a46d0bd523544a01f894b3f`. The current completed `EXP-M00` checkpoint instead pushed and verified exact SHA `18da1af0b6bc31020d3587e472b8197146795bf1`. The old hosted Actions receipt recorded by `R-M00-1` is obsolete x64-only context, not a current gate, release proof, or ARM64 evidence. No external pipeline is in scope.

### `R-M00-1` - Documentation recovery repair

The fields in this immutable historical record preserve the state observed during the original recovery. Its then-pending `EXP-M00` is superseded for current chronology only by the separately recorded completed `EXP-M00` checkpoint below; the historical record itself is not rewritten.

- **Status:** Completed for this documentation repair only; no implementation or release acceptance is claimed.
- **Owner/phase:** `LUNA MAX docs`, M00 recovery/documentation gate.
- **Dependencies verified:** The four documentation paths exist; `EXP-M00` status is `Pending` and its evidence is unavailable as recorded below.
- **Change summary:** Reconciled support architectures, current remote/CI evidence, recovered-export limitations, exact historical task IDs, collision aliases, restored contract requirements, dual-architecture gates, visual/accessibility gates, orchestration, and export receipt protocol. No application/config/test path and no `SESSION-EXPORT.md` path was edited.
- **Evidence:** `R-M00-1-E1` — final `git status`/`git diff` scope review: **Pass** for the four intended docs only; status also shows an untracked `?? .vscode/`, which this task did not edit or claim. Current host is x86_64 Linux; exact UTC time and commit were not captured by this docs-only task; reviewer: `LUNA MAX docs` self-review, independent implementation QA not performed. `R-M00-1-E2` — recovered export inventory: **Pass as supplied historical evidence** for valid parsed JSON, `5,065,391` bytes, `11,093` physical lines, `80` top-level messages, and `384` parts; exact command/time/reviewer unavailable and the export is not a complete child transcript. `R-M00-1-E3` — current remote receipt: **Pass for the named x64 deterministic/browser jobs** at the SHA and historical link in its ledger; timestamp and independent release reviewer unavailable. `R-M00-1-E4` — collision/alias register and restored acceptance matrix below: **Pass as documentation content**; no repair retest is implied.
- **Evidence ledger:**

  | Evidence ID | Requirement/check | Environment, UTC time, commit | Result, artifact, reviewer, limitation |
  | --- | --- | --- | --- |
  | `R-M00-1-E1` | `git status`/`git diff` scope review; only four docs changed by this task | Current x86_64 Linux; exact UTC time and commit not captured | **Pass** for intended docs; `?? .vscode/` remained untouched. Artifact: current worktree; reviewer: `LUNA MAX docs` self-review; no implementation QA. |
  | `R-M00-1-E2` | Recovered JSON/size/line/message/part inventory | Historical `SESSION-EXPORT.md`; exact UTC time, command, and commit not captured | **Pass as supplied historical evidence**; artifact: `SESSION-EXPORT.md`; reviewer unavailable; parent/summarized transcript only. |
  | `R-M00-1-E3` | Remote `main` SHA and linked deterministic/browser Actions jobs | Remote SHA `2a7a3bf66c3665552a46d0bd523544a01f894b3f`, ubuntu-24.04 x64; timestamp/reviewer not supplied | **Pass for named jobs only**; artifact: [run 34549899644](https://github.com/eddiesoz/stock_probs/actions/runs/34549899644); not dual-arch/full acceptance or `EXP-M00`. |
  | `R-M00-1-E4` | Exact historical repair IDs and late backup `make check` receipt | Historical ARM64/Python 3.11.2/Node 22.19.0, uncommitted revision; exact late-retest UTC time/commit not supplied | **Pass for recorded named checks**; artifact: recovered export; reviewer: historical independent retest where named; no milestone acceptance. |
  | `R-M00-1-E5` | Collision register and fresh aliases | Current docs; exact UTC time/commit not captured | **Pass as documentation content**; artifact: register below; reviewer: `LUNA MAX docs`; every fresh repair remains pending retest. |
  | `R-M00-1-E6` | Restored product and milestone acceptance rows | Current docs; exact UTC time/commit not captured | **Pass as documentation content**; artifact: restored map/task rows below; reviewer: `LUNA MAX docs`; no implementation acceptance. |
  | `R-M00-1-E7` | Required native x64/native ARM64 build, clean-install, browser, MCP, resource, and cross-arch-key gates | Current host x86_64 only; no dual-arch run in this task | **Unavailable**; future `M06`/`M07` QA required; no hosted-runner substitution claimed. |
  | `R-M00-1-E8` | Required Signal Ledger visual/accessibility and actual assistive-technology gate | No visual or assistive-technology run permitted | **Unavailable** for implementation; future `M04`/`M06`/`M07` evidence required; axe/keyboard are not substitutes. |
  | `R-M00-1-E9` | Canonical sequence and checkpoint export receipt protocol | Current docs; no export/commit/push performed | **Pass as documentation content**; `EXP-M00` status is `Pending` and its evidence is unavailable; reviewer: `LUNA MAX docs`. |
  | `R-M00-1-E10` | Three-lane ownership, QA wait, docs consumption, and eventual README/operator structure | Current docs; no implementation wave run | **Pass as documentation content**; artifact: four docs; reviewer: `LUNA MAX docs`; coordinator remains non-implementing. |
- **Limitations and repair history:** The historical ARM64 checks ran against an uncommitted historical revision; the cancelled independent retest, unavailable assistive-technology evidence, missing exact secret-review/export-revision evidence, and all fresh alias repairs remain open. The late backup retest's `make check` result is recorded as 83 tests/89.23% below; an earlier concurrent aggregate-check limitation is historical context, not a current unresolved failure.
- **Export/remote/reviewer:** `EXP-M00` status is `Pending`; its export/review/commit/push/checkpoint evidence is unavailable. No export, secret review, commit, push, or checkpoint receipt was created here. `LUNA MAX docs` is the named documentation reviewer, not an independent implementation acceptance reviewer.

> `R-M00-1` and its collision aliases are immutable historical records. Its old remote/CI fields describe the earlier recovery only; `R-M00-2` is the current policy and no external pipeline is a current gate.

### `R-M00-2` - Local-only and walkthrough policy repair

- **Status:** `Completed`.
- **Scope note:** This is documentation reconciliation only; no implementation acceptance.
- **Owner/phase:** `LUNA MAX docs`, M00 documentation repair.
- **Dependencies verified:** Immutable historical `R-M00-1`; no implementation dependency was accepted.
- **Change summary:** Removed external-pipeline acceptance language; made all checks local; defined native-x64 and local-native-or-emulated-ARM64 completion semantics; required removal of `.github/workflows/ci.yml` during M01/M06 and local fail-closed Make/scripts; added M08/`EXP-M08`, the instructional walkthrough, retrospective, Astra ordering, and exact vocabulary; corrected stale M05 aggregate wording. No implementation/config/test path and no `SESSION-EXPORT.md` path was edited.
- **Evidence ledger:**

  | Evidence ID | Requirement/check | Environment, UTC time, commit | Result, artifact, reviewer, limitation |
  | --- | --- | --- | --- |
  | `R-M00-2-E1` | `git status`/`git diff` scope review; only the four documentation paths are intended | Current native x86_64 Linux; exact UTC time and commit unavailable; `.vscode/` remains untracked and untouched | **Pass** for documentation scope; artifact: current worktree; reviewer: `LUNA MAX docs`; no implementation QA. |
  | `R-M00-2-E2` | Local-only policy, ARM64 strategy, M01/M06 local gate replacement, M08, sequence, vocabulary, and M05 wording self-review | Current docs; exact UTC time and commit unavailable | **Pass** as documentation content; artifact: four docs; reviewer: `LUNA MAX docs`; no behavior inferred. |
  | `R-M00-2-E3` | Workflow removal, local gate execution, M08 artifact generation, actual-control browser QA, and retrospective | Not run by this docs-only task; exact UTC time/commit unavailable | **Unavailable** to `R-M00-2`; current `EXP-M01` separately records the later workflow check, while the remaining implementation/M06/M07/M08/Astra evidence is future evidence. |
  | `R-M00-2-E4` | R-M00-1 identity/history, collision aliases, and repair labels retained | Current docs; exact UTC time and commit unavailable | **Pass** as documentation content; reviewer: `LUNA MAX docs`; no repair retest implied. |
- **Limitations and repair history:** No implementation QA, native ARM64 run, emulated ARM64 run, walkthrough artifact, browser-control check, retrospective, export, commit, push, or new Git remote verification was performed. `R-M00-2` does not accept any implementation milestone.
- **Export/Git/reviewer:** At the time of `R-M00-2`, no export/commit/push was performed by that documentation-only repair. The later coordinator records `EXP-M00` and `EXP-M01` are **Completed** at the exact checkpoint SHAs recorded below; `EXP-M02` through `EXP-M08` and `EXP-FINAL` remain pending. Reviewer for `R-M00-2`: `LUNA MAX docs` self-review; independent implementation QA was not performed by that historical docs repair.

### `EXP-M00` - Completed checkpoint

- **Status:** Completed.
- **Owner/phase:** coordinator export gate; reviewer/coordinator `OpenCode gpt-5.6-sol`.
- **Dependencies verified:** `R-M00-1` and `R-M00-2`; the M00 documentation baseline was complete before this checkpoint.
- **Change summary:** The active full-session export was parsed and reviewed, then committed and pushed. This record does not include the later uncommitted M01 implementation changes.
- **Evidence ledger:**

  | Evidence ID | Requirement/check | Environment, UTC time, commit | Result, artifact, reviewer, limitation |
  | --- | --- | --- | --- |
  | `EXP-M00-E1` | Active export parsed as JSON with `1,413,943` bytes, `4,268` physical lines, `23` messages, `153` parts, `44` tool parts, and `10` task outputs | Current local export; exact UTC completion timestamp was not supplied in the consumed handoff; checkpoint SHA `18da1af0b6bc31020d3587e472b8197146795bf1` | **Pass**; artifact: active session `ses_f71ec0499ffeokWj4h6tVwyYk1`; reviewer: `OpenCode gpt-5.6-sol`; timestamp limitation remains visible. |
  | `EXP-M00-E2` | Full regex secret review; two credential-like candidates were found and both were masked; no private-key, AWS, GitHub, or Bearer patterns | Same checkpoint; exact UTC time not supplied; SHA `18da1af0b6bc31020d3587e472b8197146795bf1` | **Pass**; artifact: reviewed active export; reviewer: `OpenCode gpt-5.6-sol`. |
  | `EXP-M00-E3` | Git diff/check review, local commit and push, and `git ls-remote origin refs/heads/main` exact-SHA match | Git remote `origin`, branch `main`; exact SHA `18da1af0b6bc31020d3587e472b8197146795bf1`; exact UTC time not supplied | **Pass**; artifact: exact pushed/remote SHA; reviewer: coordinator `OpenCode gpt-5.6-sol`; no remote CI was used. |
  | `EXP-M00-E4` | Scope and secret limitation review | Current worktree; exact UTC time not supplied; same checkpoint SHA | **Pass** for the recorded scope; unrelated `?? .vscode/` remained untouched. |

- **Repair history:** None reported for this completed checkpoint. The recovered pre-checkpoint export remains a separate historical record whose command ended `running`; its missing historical secret-review/export-revision evidence is not silently converted to a pass.
- **Limitations:** Exact UTC completion timestamp was not supplied; no remote CI was used; physical ARM64 performance remains unavailable.
- **Next gate at that historical checkpoint:** `M01`, followed by `EXP-M01`; the current records below supersede that forward-looking status.

## Recovered Historical QA And Gate Record

A bounded review of the recovered pre-checkpoint `SESSION-EXPORT.md` recorded the records below. The recovery inventory reports valid parsed JSON of `5,065,391` bytes, `11,093` physical lines, `80` top-level messages, and `384` parts. It contains parent task calls and summarized task handoffs, not complete child transcripts. These are historical OpenCode records from `/home/eddie/stock_probs`, generally against uncommitted working-tree material at historical `HEAD cb7c1b179aa7b33c269e1e8ff41776328d7dccae`; they are not a new QA run in the current repository and do not authorize completion. The export session is `ses_f73b976e8ffekNCE6SNIanpXFb`. The named independent reviewer in the QA rows is `LUNA MAX QA`; `SOL HIGH build` rows are implementation handoffs, not acceptance reviews.

| Task/evidence record | Check, environment, and UTC evidence | Result | Repair, limitation, and artifact |
| --- | --- | --- | --- |
| `M01`–`M04`, QA task `ses_f72f4e2f0ffe6hMpBTmXUnWybW` | ARM64 Linux, Python 3.11.2; missing daily/intraday bars at `2026-09-10T21:27:45Z`; router errors and OpenAPI mismatch at `2026-09-10T21:27:57Z`. | **Fail** | `R-M03-1`, `R-M03-2`, `R-M01-1`, and `R-M01-2` recorded; affected milestones remain blocked and unaccepted. Artifact: this export. |
 | `M04`/`M06`, QA task `ses_f72f4e261ffeLWQEjyJI4k3hea` | Node 22.19.0; eight desktop/mobile Playwright checks, official MCP smoke, 51 API checks, axe checks, controls, and `/api/v1` network checks reported passing. | **Pass for exercised checks; milestone not accepted** | Historical snapshot was uncommitted and no export/commit/push/Git revision checkpoint was present. Artifact: this export. |
| `M05`/`M06`, QA task `ses_f72f4e163ffehgqJPXwbY7ujrX` | ARM64 Linux, Python 3.11.2; adversarial backup, provider-timeout, permissions, and CSV checks. | **Blocked** | Findings recorded as `R-M05-1`, `R-M05-2`, `R-M05-3`, `R-M05-4`, and `R-M06-1`; no release acceptance. Artifact: this export. |
| `R-M03-1`, `R-M03-2`, `R-M05-3`, repair `ses_f72c4f276ffeJm9WRj0aBXCM1X` and retest `ses_f72ab5097ffexdJCun6m6thzDi` | Repair suite/full deterministic checks; retest focused checks `2026-09-10T22:10:19Z`–`22:10:22Z`, full suite 83 passed, 89.23% coverage, and live ACDC/SPY checks passed. | **Pass for the named repair checks** | No commit or push; unscheduled exchange closures remain outside the modeled calendar. Artifact: this export. |
| `R-M01-1`, `R-M01-2`, `R-M04-1`, `R-M06-1`, repair `ses_f72c4f20effeDoLPC0FuHaaGjZ` and retest `ses_f72ab5027ffeR0shgnOsYGX47N` | Repair handoff reported 22 focused, 83 full non-live, and eight browser checks passing at `2026-09-10T21:57:32Z`. | **Skipped** | The independent retest task was cancelled; no acceptance result may be inferred from the builder report. Artifact: this export. |
 | `R-M05-1`, `R-M05-2`, `R-M05-4`, repair `ses_f72c4f1baffeECZSQ37ujzSmCJ` and retest `ses_f72ab4fc9ffepKCTOlUxIWlRrt` | Independent late retest reported `make check` **Pass**, 83 tests, and 89.23% coverage, plus `make restore-test`, `make release-check`, `make mcp-smoke`, `make live-smoke`, and adversarial HMAC/ZIP/permission checks; environment was historical ARM64/Python 3.11.2/Node 22.19.0. | **Pass for the named checks** | This evidence is from the historical uncommitted revision and is not full milestone acceptance. An earlier concurrent builder aggregate-check limitation is historical context, not a current unresolved result. Export/secret-review/push/Git-revision fields for the milestone remain open. Artifact: this export. |
| Recovered historical `EXP-M00` | The export command `opencode export ses_f73b976e8ffekNCE6SNIanpXFb > SESSION-EXPORT.md` appears with status `running` at the end of the recovered transcript; no completed exit/result is recorded. | **Unavailable** | Historical record only: no exact full secret-review or export-revision evidence was captured for that attempt, and its commit/push/Git-revision receipt is unavailable. It is superseded for current chronology by the completed `EXP-M00` record above and must not be treated as current acceptance. Artifact: recovered `SESSION-EXPORT.md`. |
| Current `EXP-M00` | Active export session `ses_f71ec0499ffeokWj4h6tVwyYk1`: `1,413,943` bytes, `4,268` lines, `23` messages, `153` parts, `44` tool parts, `10` task outputs; full regex secret review masked two credential-like candidates and found no private-key/AWS/GitHub/Bearer patterns; exact pushed/remote SHA matched. | **Pass** | **Completed**; see the full `EXP-M00-E1`–`E4` ledger above. Exact UTC completion timestamp was not supplied; no remote CI was used. Reviewer/coordinator: `OpenCode gpt-5.6-sol`. Artifact: active export/checkpoint SHA `18da1af0b6bc31020d3587e472b8197146795bf1`. |

The historical transcript reuses `R-M01-1`, `R-M05-1`, `R-M06-1`, and `R-M04-1` for different integration and later QA defects. The fresh source-qualified aliases allocated by `R-M00-1` are listed next; historical labels are not changed. A check-level `Pass` above never overrides a cancelled retest, missing reviewer/gate field, failed check, or unavailable release evidence.

## Historical Collision And Alias Register

The following IDs are fresh and unique in this plan. They were pending when allocated; current M01 scoped repair results are recorded below, while later obligations remain pending until their exact independent rerun and normal export plus Git checkpoint evidence. The old labels remain immutable historical references.

| Historical source-qualified label | Defect obligation carried forward | Fresh repair ID | Status and evidence state |
| --- | --- | --- | --- |
| `R-M01-1` in QA task `ses_f72f4e2f0ffe6hMpBTmXUnWybW` | Router error envelope/OpenAPI behavior | `R-M01-3` | **Completed** for the current scoped retest; see M01 QA ledger. |
| `R-M01-1` in repair-builder handoff `ses_f72c4f20effeDoLPC0FuHaaGjZ` | Startup harness/launch behavior | `R-M01-4` | **Completed** for the current scoped retest; see M01 QA ledger. |
| `R-M05-1` in QA task `ses_f72f4e163ffehgqJPXwbY7ujrX` | Malicious backup artifact handling | `R-M05-5` | **Pending**; historical finding, no fresh retest |
| `R-M05-1` in the later backup/operations handoff `ses_f72c4f1baffeECZSQ37ujzSmCJ` | Chunked-request/resource handling | `R-M05-6` | **Pending**; source-qualified obligation, no fresh retest |
| `R-M06-1` in QA/operations task `ses_f72f4e163ffehgqJPXwbY7ujrX` | Port-collision behavior | `R-M06-2` | **Pending**; no independent retest |
| `R-M06-1` in repair-builder handoff `ses_f72c4f20effeDoLPC0FuHaaGjZ` | Documentation CSP policy | `R-M06-3` | **Pending**; cancelled independent API/UI retest |
| `R-M06-1` in repair-builder handoff `ses_f72c4f20effeDoLPC0FuHaaGjZ` | CSV formula-injection/export behavior | `R-M06-4` | **Pending**; cancelled independent API/UI retest |
| `R-M04-1` in browser/accessibility task `ses_f72f4e261ffeLWQEjyJI4k3hea` | Actual assistive-technology evidence unavailable | `R-M04-2` | **Pending**; evidence unavailable and screen-reader/assistive run still required separately |
| `R-M04-1` in repair-builder handoff `ses_f72c4f20effeDoLPC0FuHaaGjZ` | Mobile error focus behavior | `R-M04-3` | **Pending**; cancelled independent API/UI retest |

The source task IDs above are evidence locators, not acceptance reviewers. `R-M01-3` and `R-M01-4` now have current independent scoped pass records; the other listed aliases remain pending, and no later repair may reuse one of these fresh IDs for a different defect. `R-M01-5` through `R-M01-15` are current coordinator-assigned M01 records in the M01 register, not additional collision aliases.

## Mandatory Delivery Workflow

The coordinator applies this workflow to every milestone and repair. It is a sequencing rule, not permission to infer that an existing source file works.

### Safe build-wave ownership

Use exactly three concurrent `SOL HIGH build` instances in each implementation or repair wave, never more than three. The coordinator records this lane manifest against the exact milestone or repair ID before work starts; the lanes cover every implementation, configuration, and test path:

| Lane | Sole build ownership | Handoff boundary |
| --- | --- | --- |
| `SOL HIGH-A` | Transport/application: FastAPI routes, schemas, configuration, CLI, package/launch assumptions, and transport-facing tests | Versioned API contract and launch assumptions |
| `SOL HIGH-B` | Domain/provider/persistence: forecast semantics, Yahoo/fixture adapters, service, SQLite migrations/repositories, backup/restore, and domain/storage tests | Domain and storage contracts, fixtures, and migration assumptions |
| `SOL HIGH-C` | Presentation/browser/operations: static UI, browser harness, operational scripts, Make/local-gate tooling, dependency/runtime tooling, and presentation/operations tests | UI states, browser journeys, resource limits, and operational assumptions |

No two builders edit the same path or silently cross a lane boundary. `README.md`, `AGENTS.md`, `MVP-PLAN.md`, and `MVP-ROADMAP.md` are documentation-owned; `SESSION-EXPORT.md` is export-owned. Any implementation/config/test path not named in the lane manifest is assigned to A, B, or C before work starts. Builders report the exact task ID, changed paths, checks attempted, failures, and unresolved assumptions. If a dependency requires a shared edit, builders stop and hand it to the coordinator for mechanical integration; the coordinator does not author shared implementation/config/test content. The build wave is complete only after all three builder reports arrive.

### Ordered gates

1. Assign the exact `M##` or repair ID and record verified dependencies, lane ownership, and acceptance rows.
2. Run the three-lane `SOL HIGH build` wave concurrently, with no more than three subagents.
3. Wait for all builder reports and changed paths; do not integrate or declare a result while a report is missing.
4. Run independent `LUNA MAX QA` and `LUNA MAX docs` gates only after that wait. They may prepare concurrently when their scopes are independent, but docs finalizes only after consuming the completed QA record and must not fill a missing QA result with an implementation claim.
5. The coordinator alone integrates changes, updates status/evidence, and performs git operations. It does not implement, perform QA, or write roadmap prose.
6. On any failure, skip, unavailable provider, stale-data condition, accessibility finding, restore failure, secret-review failure, connectivity loss, or missing artifact, keep the task `Pending`, `In progress`, or `Blocked`; create `R-M##-<n>`, repair the root cause, and rerun the failed and affected checks.
7. Follow the canonical sequence exactly: `R-M00-1` -> `EXP-M00` (**Completed**) -> `M01` (**Completed**) -> `EXP-M01` (**Completed**) -> `M02` (**In progress**) -> `EXP-M02` (**next gate**) -> ... -> `M06`/`EXP-M06` -> `M07` QA/docs -> `EXP-M07` -> `M08` walkthrough QA/docs -> `ASTRA-FINAL` -> repairs/retests until the result is `Accepted` -> `EXP-M08` -> `EXP-FINAL`. The final gate is allowed only after Astra acceptance and all repair retests.

### Versioned session-export gates

Every milestone has a separately recorded export task ID: `EXP-M00`, `EXP-M01`, `EXP-M02`, `EXP-M03`, `EXP-M04`, `EXP-M05`, `EXP-M06`, `EXP-M07`, or `EXP-M08`. The coordinator uses OpenCode `/export`, or a verified CLI equivalent, to overwrite exactly one tracked root artifact, `SESSION-EXPORT.md`. The export must be a full-session record containing tool calls and subagent outputs; a summary, partial transcript, or untracked local file does not satisfy the gate.

Before commit, the export receives a documented full secret review. Commit and push the reviewed export as checkpoint SHA X, then verify that exact SHA on the configured Git remote. The record names the export revision/commit, pushed branch, Git remote revision result, artifact/link, UTC time, environment, and reviewer. Any failed, skipped, unavailable, or connectivity-blocked export, secret review, commit, push, or Git revision check is recorded with its result and blocks that checkpoint. Git history supplies the version for the stable overwritten path; the export task ID supplies milestone identity. No hosted runner or external pipeline is recorded. `R-M00-1` intentionally did not create, review, commit, or push the export.

### Independent final Astra gate

After `M08` walkthrough QA/docs evidence is complete, an independent GPT-6 Astra reviewer executes task `ASTRA-FINAL`. Astra must use an evidence matrix—not implementation claims—to confirm every shipped feature, every API and UI endpoint, every visible click/control, every browser journey on the supported viewports, every persistence effect, the complete walkthrough artifact, actual-control browser evidence, and the M08 retrospective. The matrix must name the check, environment, UTC timestamp, commit, result, artifact/link, limitation, and reviewer for each row.

Any missing, failing, skipped, unavailable, or unconfirmed row creates `R-ASTRA-<n>`. The repair goes through the same three-lane build handoff, independent QA/docs gates, and Astra retest. Repeat until the `ASTRA-FINAL` record explicitly says `Accepted`; no final release or `EXP-FINAL` may precede that wording.

## Product Goal

Build a small, auditable, local web application where a user selects a Yahoo Finance stock or ETF, confirms its company name and instrument identity, and receives two forecast views:

1. **Close-to-close:** a forecast from a clearly identified completed market-session close to the applicable next close.
2. **Latest-completed-5-minute-bar-to-close:** a forecast from the latest completed five-minute bar available at request time to the applicable close. An in-progress bar must never be used as completed input.

Each view must expose probabilities and magnitude intervals, not just a point estimate. The probability contract includes up/down/unchanged direction, `+/-1%`, `+/-3%`, `+/-5%`, and `+/-10%` return thresholds, conditional gain/loss probabilities, and 50%, 80%, and 95% return and price intervals. Every displayed result must identify its company name, symbol, asset type, instrument identity, input timestamps, provider/as-of time, forecast horizon, model/version, interval level and units, stale-data state, and any limitation or failure.

This is a research and auditability tool, not a trading system or a promise of predictive accuracy. Optional dark mode and news features are not part of the contract; options trading and public hosting are out of scope.

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
- Yahoo Finance five-minute history has an approximate 60-day availability limitation. The provider and UI must state that archive limitation and the applicable archive/session semantics; an unavailable or stale interval is evidence to record, not a reason to fabricate a result.

### Persistence and auditability

- Every submitted search is an append-only audit event, including successful, failed, and repeated submissions. A repeated search may reuse a valid prior result, but the new submission event must still be stored.
- A successful forecast stores an immutable input snapshot: normalized symbol and asset type, request and source timestamps, selected bars, session/calendar interpretation, data-quality flags, model and algorithm version, parameters, thresholds, and provider metadata or content fingerprint.
- The immutable result stores probabilities, magnitude intervals, interval levels and units, calculation timestamps, and the input-record reference.
- An observed outcome is appended after the forecast horizon with the actual close/return, observation timestamp, comparison rule, and outcome state. It must not rewrite the original forecast input or result.
- Corrections require a new versioned record or audit event. No update-in-place behavior may erase what was originally submitted or displayed.
- History queries must be bounded, searchable, and served through `/api/v1`; the UI must not scan the database file.
- Reopening a saved forecast must display the immutable recorded inputs/results and must not silently recalculate. A historical cutoff reconstruction is a separately labelled fresh analysis using the data available at that cutoff, with its own as-of time, model/version, and provenance.

### User experience

- The dashboard must work at desktop and mobile widths without hiding essential status or controls.
- Every search control needs a visible label, keyboard path, focus state, validation message, loading state, empty state, success state, and failure state.
- Charts, colors, and interval bands must have text or table equivalents; color alone cannot communicate direction, confidence, stale data, or failure.
- Historical price and return-distribution charts must have equivalent tables/text and remain understandable in every state. The distinctive Signal Ledger direction is intentional: polished tabular numeric hierarchy, clear status evidence, and restrained visual encoding rather than a generic trading dashboard.
- History must support practical search/filtering and expose enough context to distinguish a repeated request from a new forecast.
- Accessible names, semantic structure, WCAG AA contrast, keyboard operation, reduced-motion behavior, and actual assistive-technology/screen-reader announcements are acceptance concerns, not polish. Axe and keyboard checks do not substitute for an actual screen-reader run.

### Deployment and resources

- The default service must bind to loopback only. The deployment must make any broader bind an explicit, documented, security-reviewed choice.
- Validate symbols, request sizes, date ranges, page sizes, backup paths, and provider timeouts at the API boundary.
- Do not expose provider credentials or local file paths to the browser or logs. Avoid unsafe CORS and unbounded concurrent provider calls.
- Keep the default process, query, cache, and browser-test footprint suitable for low-resource Linux x86-64 and ARM64. Measure rather than assuming that desktop-scale defaults are safe; the target is below 500 MiB normal server memory, a cached forecast under 1 second, an indexed 100,000-history query under 250 ms, and negligible idle CPU. Native x86-64 measurements are native evidence; ARM64 performance is measured only on local native ARM64 hardware. Emulation can verify packaging/runtime portability and functional/build/tool behavior, but cannot prove physical ARM64 performance.
- All code must have useful comments for non-obvious model, time-window, persistence, security, and resource decisions.

## Planned Architecture

The intended flow is browser dashboard -> frontend API client -> FastAPI `/api/v1` -> domain services -> Yahoo Finance adapter and server-owned SQLite repositories. The browser has no alternate path to storage or to Yahoo Finance.

The API/application layers should remain separable:

- **Transport:** FastAPI routes, request/response schemas, validation, safe error mapping, and API versioning.
- **Domain:** symbol selection, session/bar semantics, forecast calculation, interval formatting, stale-data policy, and outcome comparison.
- **Adapters:** Yahoo Finance retrieval, SQLite repositories/migrations, backup artifact handling, and clock/calendar boundaries.
- **Presentation:** responsive accessible dashboard, loading/error/empty states, results, and searchable history.
- **Quality:** unit, API, persistence, accessibility, security, performance, restore, dual-architecture, and browser regression checks.

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

The evaluation record must use chronological walk-forward splits with no future leakage, compare against a documented baseline, and report Brier score, reliability/calibration, and interval coverage. Rare-event estimates must expose sample counts and uncertainty rather than implying precision from sparse observations. Historical price and return-distribution views must use the same recorded provenance and provide text/table equivalents. A saved result remains a recorded result; a historical-cutoff reconstruction is explicitly a fresh analysis.

The current hard-coded and dummy calculations are not acceptance evidence for this contract. M03 must replace or explicitly isolate them behind tested, versioned domain behavior and must not present mock backtests as validated forecasts.

## Restored Acceptance Contract Map

These requirements were omitted from a condensed milestone plan and are restored here as milestone acceptance rows. They are requirements only; none is currently accepted by this documentation repair.

| Contract requirement | Milestone acceptance row |
| --- | --- |
| Company-name lookup preserves symbol, exchange, asset type, and other instrument identity; stocks and ETFs follow one explicit identity contract. | `M01` API/schema row and `M03` provider/selection row; `M04` must display the identity without ambiguity. |
| Saved forecast reopen is immutable recorded output; historical cutoff reconstruction is labelled fresh analysis with separate provenance. | `M02` immutable-record row, `M03` horizon/provenance row, and `M04` saved/reconstruction journey row. |
| Chronological walk-forward evaluation, baseline comparison, Brier/reliability, interval coverage, and rare-event uncertainty are recorded without leakage. | `M03` forecast-engine/evaluation row and `M07`/`ASTRA-FINAL` evidence matrix rows. |
| Historical price and return-distribution charts have text/table equivalents and preserve the Signal Ledger visual direction. | `M04` chart/state/accessibility row and `M07`/`M08` visual rows. |
| Direction is explicit up/down/unchanged; thresholds are `+/-1%`, `+/-3%`, `+/-5%`, `+/-10%`; conditional gain/loss and 50/80/95 return and price intervals are defined. | `M03` numerical contract row and `M04` result presentation row. |
| Yahoo approximate 60-day five-minute limitation and archive/session semantics are visible and auditable. | `M03` provider limitation row and `M07` limitation/release row. |
| Automatic due and pre-migration backups, retention/disk limits, and no automatic query-history expiry are verified. | `M05` operations/persistence row and `M07` restore/retention row. |
| Both CSV and JSON export are available, safe, and traceable to immutable records. | `M04` user export row and `M06` security/regression row. |
| Measured targets: below 500 MiB normal server memory, cached forecast under 1 s, indexed 100,000-history query under 250 ms, negligible idle CPU. | `M06` resource row on native x86 and, if available, native ARM64; `M07` records any physical ARM64 limitation explicitly. |
| Linux x86-64/amd64 and ARM64/aarch64 gates cover clean install/package build, `make check`, loopback, Node/Chromium, official MCP interaction, desktop/mobile tests, and cross-architecture backup/key behavior. ARM64 functional/build/tool checks may be local native or labelled emulated; physical low-resource ARM64 performance is never inferred. | `M06` local dual-architecture row and `M07` release row. No external pipeline or hosted runner substitutes for local evidence. |
| Viewports 360/390/768/1280/1440 have polished no-overlap/no-overflow layouts, tabular numeric hierarchy, all states, charts/tables, reduced motion, WCAG AA, keyboard, and actual assistive-technology evidence. | `M04` visual/accessibility row, `M06` browser gate, `M07` final visual/AT row, and `M08` walkthrough row; axe/keyboard are not screen-reader substitutes. |
| The final walkthrough is a bounded, accessible, reproducible artifact using deterministic fixtures, the real local app, official browser tooling, actual controls, desktop/mobile steps, and a prompt/plan retrospective with repaired gaps. | `M08` walkthrough and retrospective rows, then `ASTRA-FINAL`. |

Optional dark mode/news are explicitly non-contract; options and public hosting are out of scope.

## Task Register

The coordinator assigns the exact task ID. Each implementation or repair wave runs exactly three concurrent build lanes and never more than three builders, waits for handoff, then runs the independent QA/docs gates; docs finalizes only after consuming the completed QA record. The listed acceptance evidence is required before status can become **Completed**, and the matching export gate is required before the milestone is released onward. M08 is the explicit ordering exception: its artifact/QA/docs result is reviewed by Astra first, then `EXP-M08` checkpoints that final walkthrough.

### M00 - Documentation Baseline

- **Status:** Completed.
- **Scope note:** Documentation baseline only; no implementation acceptance.
- **Dependencies:** None.
- **Agents:** `LUNA MAX docs`; immutable recovery `R-M00-1` and policy repair `R-M00-2` are documentation-only and do not accept implementation behavior.
- **Scope:** Create the plan, roadmap, compact agent rules, and honest repository README.
- **Acceptance evidence:** [x] `MVP-PLAN.md`, `MVP-ROADMAP.md`, `AGENTS.md`, and `README.md` exist; [x] current prototype is distinguished from planned implementation; [x] no implementation milestone is presented as completed without its evidence.
- **Verification:** [x] documentation-only diff reviewed for `R-M00-1`; [x] required product invariants, restored acceptance map, dual-architecture/visual gates, orchestration, evidence fields, repair loop, and final definition of done are present. This is not implementation QA.
- **Repair record:** `R-M00-1` **Completed** for documentation recovery only; its exact evidence, limitations, and unavailable release fields are recorded above.
- **Post-milestone gate:** `EXP-M00` was required to overwrite and review `SESSION-EXPORT.md`, then record the local commit, push, and exact Git remote revision verification. The recovered historical attempt remains incomplete, but the current coordinator checkpoint is completed above at exact SHA `18da1af0b6bc31020d3587e472b8197146795bf1`.

### M01 - API And Application Shell

- **Status:** Completed.
- **Dependencies:** `M00` and completed `EXP-M00` checkpoint `18da1af0b6bc31020d3587e472b8197146795bf1` verified. The subsequent M01 changes are included in the completed `EXP-M01` checkpoint at SHA `5424fa3e22d9229d038d376512e59b3f35c97e78`.
- **Evidence state:** All three builder handoffs and all three independent QA retests were received. No QA lane found a remaining M01 product defect. Independent behavior evidence passes in scope, `R-M01-3` through `R-M01-15` are completed for their exact assigned repair behavior, and the export/Git/workflow checkpoint is completed below.
- **Build wave:** `SOL HIGH-A` transport/application; `SOL HIGH-B` domain/storage interface assumptions; `SOL HIGH-C` presentation/browser/operations integration. Paths must be disjoint and reports must arrive before QA/docs.
- **Gates:** `LUNA MAX QA` and `LUNA MAX docs` only after the builder wait; export `EXP-M01` after every acceptance row passes.
- **Scope:** Establish the Linux x86-64/ARM64-friendly application layout, FastAPI service, versioned `/api/v1` boundary, structured errors, health/readiness behavior, company-name/instrument-identity lookup contract, frontend shell, documented local loopback launch path, and removal of any obsolete `.github/workflows/ci.yml` workflow path.
- **Change summary:** The current implementation wave includes the deleted workflow, package/bootstrap and local-gate paths, company/instrument lookup and API/UI identity handling, the service boundary, strict schemas/errors/startup behavior, and associated tests. This summary records changed paths, not a completion claim.
- **Builder handoff record:**
  - `SOL HIGH-A` task `ses_f718d04e0ffeqdv2i56c6k72Pg`, repair handoff `ses_f71674730ffeERY2M1p9htV2Or`: `pyproject.toml`, `requirements.lock`, transport/application files under `src/stock_probs/` (`api.py`, `cli.py`, `config.py`, `schemas.py`, `service.py`), and `tests/test_api.py`/`tests/test_config_quality.py`; package metadata, startup/configuration, schemas/errors, and application-shell behavior were changed, with executable Python support metadata `>=3.11,<3.12`.
  - `SOL HIGH-B` task `ses_f718d04a2ffexmhN4OlHuJlTwt`, repair handoff `ses_f716746fbffe9qOSoMniDzfbNi`: `src/stock_probs/domain.py`, `provider.py`, `repository.py`, `fixtures/acdc.json`, `fixtures/spy.json`, and `tests/test_domain.py`/`test_provider.py`/`test_repository_backup.py`; domain/provider identity and server-side persistence interfaces were changed.
  - `SOL HIGH-C` task `ses_f718d0469ffeVig2Xix5cE5N1V`, repair handoff `ses_f716746e8ffeEjA0BRqajZ0ycH`: deleted `.github/workflows/ci.yml` and `scripts/install-node-arm64.sh`; changed `.opencode/agent/sol-build.md`, `Makefile`, `src/stock_probs/static/app.css`, `app.js`, `index.html`, `tests/test_live.py`, `tests/test_resource.py`, `tools/browser/package-lock.json`, `tools/browser/playwright.config.js`, and `tools/browser/tests/dashboard.spec.js`; added the ARM64/bootstrap/local-gate scripts listed in the current worktree (`scripts/arm64-smoke.sh`, `bootstrap.sh`, `compose.arm64.yml`, `install-node.sh`, `local-gate.sh`, `package_smoke.py`, and `run-arm64-container.sh`).
  - Builder reports are implementation handoffs only; their tests are not independent acceptance evidence.
- **Acceptance evidence:** [x] independent API/schema, negative-validation, startup, and package checks passed in scope; [x] executable Python support metadata is `>=3.11,<3.12` and native x86 bootstrap used Python `3.11.15`; [x] company-name lookup preserved symbol, exchange, stock/ETF asset type, and instrument identity; [x] browser network inspection recorded 53 fetch/XHR requests all under `/api/v1` with no forbidden access or leaks; [x] native x86-64 bootstrap/loopback and clean non-edit wheel install/migration passed; [x] explicitly emulated ARM64 OCI/QEMU `7.2.0` package/install/migration/loopback passed; [x] useful comments and compile/shell checks passed; [x] `.github/workflows/ci.yml` is absent on the verified remote revision; [x] `EXP-M01` export, secret review, commit, push, and exact remote-revision verification passed.
- **Independent QA verification:**

  | Evidence ID/task | Check and environment/time | Result, artifact, reviewer, limitation |
  | --- | --- | --- |
  | `M01-QA1` / `ses_f71521f9dffeWxILBgUaEBhf0O` | Native x86_64; completed `2026-09-11T04:27:31Z`. `R-M01-3`–`R-M01-7`, `167/167` harness, `100` non-live passed/`4` deselected/`89.17%`, Ruff+S, strict mypy for all 12 production files, 51 comments, compile, and shell checks. | **Pass**; `/tmp/opencode/stock_probs-m01-qa`; reviewer `LUNA MAX QA`. Live/browser/ARM/export were skipped in this lane only. |
  | `M01-QA2` / `ses_f71521f5effeKu8HF2uh3fxJT1` | Native x86 Python `3.11.15`; direct no-`make` local gate; clean non-edit x86 wheel install/migration/loopback; deliberate safe failure exited nonzero and recorded `Fail`; Node x64/arm64 checksum; OpenCode schema/config/MCP; emulated ARM64 OCI/QEMU `7.2.0` package/install/migration/loopback; cleanup. | **Pass** for coordinator-authoritative `R-M01-8`–`R-M01-13`; artifacts `test-results/local-gates` and `test-results/arm64`; reviewer `LUNA MAX QA`. Completion UTC was not supplied. No native/physical ARM64 or performance evidence. Stale labels `R-M01-16`–`R-M01-19` were not created; their checks are assigned here to `R-M01-8`–`R-M01-13`. |
  | `M01-QA3` / `ses_f71521efbffeEdTmM7GL4wYmW2` | Native x86_64; latest artifact timestamp `2026-09-11T04:35:01.820Z`. `R-M01-14`/`R-M01-15`, browser `R-M01-3`/`R-M01-4`, checked-in 6 desktop + 6 mobile scenarios, required viewport overflow checks, identity checks, 53 API-only fetch/XHR requests, structured errors/docs/OpenAPI/console, and official MCP actual interaction. | **Pass**; artifacts `/tmp/opencode/m01qa-*`; reviewer `LUNA MAX QA`. No product defects; screen-reader/later polish remain M04/M06. |
- **Repair register:**

  | Repair ID | Exact scoped behavior and independent evidence | Status |
  | --- | --- | --- |
  | `R-M01-3` | Router error/OpenAPI scoped retest; `M01-QA1` and `M01-QA3` pass evidence. | Completed |
  | `R-M01-4` | Startup/launch-harness scoped retest; `M01-QA1` and `M01-QA3` pass evidence. | Completed |
  | `R-M01-5`–`R-M01-7` | Coordinator-assigned M01 repair rows; `M01-QA1` passed all three in scope. | Completed |
  | `R-M01-8`–`R-M01-13` | Coordinator-assigned package/bootstrap, direct local-gate, clean-install/migration/loopback, checksum, OpenCode/MCP, and emulated-ARM64 rows; `M01-QA2` pass evidence. | Completed |
  | `R-M01-14`–`R-M01-15` | Coordinator-assigned QA3 M01 repair rows; `M01-QA3` passed its recorded browser/API/identity/error/docs/OpenAPI/console/MCP scopes. | Completed |

  The range assignments above are authoritative. No `R-M01-16`, `R-M01-17`, `R-M01-18`, or `R-M01-19` repair records were created from stale export labels.
- **Limitations:** The current host lacks system `make`; the direct executable local-gate path passed and `Makefile` is a convenience wrapper. Physical/native ARM64 performance is `Unavailable`; emulated ARM64 evidence is explicitly functional/tool evidence only. M01 live checks skipped in QA1 are not represented as global passes. The unrelated `?? .vscode/` remained untouched, and no remote CI was used.
- **Post-milestone gate:** `EXP-M01` is **Completed** at SHA `5424fa3e22d9229d038d376512e59b3f35c97e78`; `M02` is the current in-progress milestone and `EXP-M02` is the next gate.

### EXP-M01 - Completed export checkpoint

- **Status:** Completed.
- **Owner/phase:** coordinator export gate. The consumed handoff did not supply a separate named export reviewer or exact UTC completion timestamp; those fields remain visibly unavailable rather than inferred.
- **Dependencies verified:** M01 independent QA records and completed `R-M01-3` through `R-M01-15` scoped repairs.
- **Change summary:** The active full-session export was parsed and reviewed, the M01 changes were committed and pushed, and the exact remote revision and workflow-path removal were verified. No implementation or test path was changed by this documentation update.
- **Evidence ledger:**

  | Evidence ID | Requirement/check | Environment, UTC time, commit | Result, artifact, reviewer, limitation |
  | --- | --- | --- | --- |
  | `EXP-M01-E1` | Parse the full export as JSON and inventory `8,791,084` bytes, `6,904` lines, `34` messages, `241` parts, `70` tools, and `23` task outputs | Current local full-session export; exact completion UTC not supplied; checkpoint SHA `5424fa3e22d9229d038d376512e59b3f35c97e78` | **Pass**; artifact: session `ses_f71ec0499ffeokWj4h6tVwyYk1`; separate export reviewer not supplied in the consumed handoff. |
  | `EXP-M01-E2` | Full secret review: four credential-like candidates masked; no private-key, AWS, GitHub, Bearer, or credential-URL pattern | Same checkpoint; exact UTC not supplied; SHA `5424fa3e22d9229d038d376512e59b3f35c97e78` | **Pass**; artifact: reviewed export; separate export reviewer not supplied in the consumed handoff. |
  | `EXP-M01-E3` | Local commit/push, exact remote revision, and remote `.github/workflows/ci.yml` absence | Configured Git remote and verified branch; exact SHA `5424fa3e22d9229d038d376512e59b3f35c97e78`; exact UTC not supplied | **Pass**; artifact: exact pushed/remote SHA and remote path check; no pipeline run or use. |
  | `EXP-M01-E4` | Scope and architecture limitation review | Native x86_64 plus explicitly emulated ARM64 functional/tool evidence; `?? .vscode/` untouched | **Pass** for recorded scope; no physical/native ARM64 performance result, no remote CI, and no unrelated path claim. |

- **Repair history:** None reported for the export gate. The M01 behavior repairs and independent retests are recorded above; builder handoffs are not substituted for those QA results.
- **Limitations:** Native x86_64 and emulated ARM64 functional/tool evidence are recorded; physical/native ARM64 and physical low-resource performance remain unavailable. The missing exact export timestamp and separate reviewer name remain visible.
- **Export/Git:** `EXP-M01` itself is the reviewed `SESSION-EXPORT.md` checkpoint at pushed/remote SHA `5424fa3e22d9229d038d376512e59b3f35c97e78`; no external pipeline was used.

### M02 - SQLite Audit And Immutable Records

- **Status:** In progress.
- **Dependencies:** Completed M01 and completed `EXP-M01` checkpoint SHA `5424fa3e22d9229d038d376512e59b3f35c97e78`.
- **Owner/phase:** three `SOL HIGH build` handoffs, independent `LUNA MAX QA`, and this `LUNA MAX docs` gate. Builder checks are implementation handoffs, not acceptance evidence.
- **Evidence state:** All recorded M02 behavior scopes have independent pass evidence. M02 remains **In progress only** because `EXP-M02` secret review, export, local commit, push, and exact remote-revision evidence are pending.
- **Build wave:** `SOL HIGH-A` transport/history contract; `SOL HIGH-B` migrations/repository/immutability; `SOL HIGH-C` history presentation and browser operation. No shared paths during the wave.
- **Gates:** `LUNA MAX QA` and `LUNA MAX docs` only after all three handoffs; export `EXP-M02` after every acceptance row passes.
- **Scope:** Define migrations and repositories for search events, successful/failed/repeated status, immutable forecast inputs, immutable results, append-only outcomes, provenance, and bounded searchable history.
- **Change summary:** The wave added additive migration `002`, searchable audit/history behavior, immutable saved-result reopen versus separately labelled fresh historical-cutoff reconstruction, append-only outcomes, CSV/JSON export, and the local M02 gate. Later repair work added migration `003`'s restore/immutability guard coverage and its package-resource assertion without rewriting prior migrations.
- **Acceptance evidence:** [x] migrations are reproducible on a clean database and package resources; [x] every trusted in-app submission persists one auditable event on success, failure, or repetition; [x] input, result, and outcome records cannot be silently overwritten; [x] saved reopen returns immutable recorded input/result without recalculation; [x] history filters and pagination use `/api/v1`; [x] restart preserves records; [x] query history has no automatic expiry, with retention/disk policy kept separate from silent deletion.
- **Verification:** [x] repository/migration and checksum/package checks; [x] success/failure/repeat matrix; [x] immutability and concurrent-write checks; [x] saved-reopen versus fresh-reconstruction distinction; [x] API-only/browser-boundary check; [x] retention/disk-limit and restart evidence; [x] CSV/JSON and local-gate checks; [x] official MCP/browser checks in the final QA scope.

#### M02 builder handoffs

| Lane/task | Reported implementation scope | Acceptance meaning |
| --- | --- | --- |
| `SOL HIGH-A`, `ses_f712f4d58ffePmzI8fAR3Oa7hx` | Transport/history contract, saved and fresh reconstruction, outcomes, and API-facing audit records. | Implementation handoff only; not independent acceptance. |
| `SOL HIGH-B`, `ses_f712f4cf0ffeixu54tZg1FfjNF` | Additive migration `002`, SQLite history/immutability/repository behavior, outcomes, and persistence safeguards. | Implementation handoff only; not independent acceptance. |
| `SOL HIGH-C`, `ses_f712f4be6ffeAetzWX712LvaDP` | History presentation, CSV/JSON surfaces, browser operation, and the local M02 gate. | Implementation handoff only; not independent acceptance. |

#### M02 initial QA and repair history

The initial failures are retained as failures in the history; later passes do not erase them. The `R-M02-6`–`R-M02-9` IDs were unused. The `21`–`29` labels in QA pass evidence were evidence labels, not new defect records, so no repair records are created from them.

| Evidence/task | Requirement/check and exact result | Environment/artifact/reviewer | Repair or limitation |
| --- | --- | --- | --- |
| Initial QA lane 1, `ses_f711eb2c2ffe6fXPkurhibBu4h` | Found `R-M02-1`–`R-M02-5`; **Fail** for the initial findings. | Parent-session QA report; exact environment/time/artifact not supplied in the consumed handoff; reviewer `LUNA MAX QA`. | First repair wave and `ses_f70e7f1edffewINIkuCL0X1fx7` later passed those scopes with 145 tests. |
| Initial QA lane 2, `ses_f711eb2abffeURm1Z1rnq6IbEV` | `R-M02-10`–`R-M02-18`: **Pass**. `R-M02-19`: **Fail**. | Parent-session QA report; exact environment/time/artifact not supplied in the consumed handoff; reviewer `LUNA MAX QA`. | The initial `R-M02-19` failure remains visible; affected later repair/regression evidence passed. |
| Initial QA lane 3, `ses_f711eb297ffeIQIk61tFgYxNzg` | Found `R-M02-20`; **Fail** for the initial finding. | Parent-session QA report; exact environment/time/artifact not supplied in the consumed handoff; reviewer `LUNA MAX QA`. | The later browser report passed 22/22 and `R-M02-20`; its exact task-ID suffix was unavailable and is not guessed. |
| First repair builders | A `ses_f70f38bb7ffemfzOJYloLsE7E5`; B `ses_f70f38aebffeweicQ3chgjhqlZ`; C `ses_f70f38aa8ffe6KzqqT2WRXU2tP`. | Implementation handoffs; no independent acceptance. | Repair history only. |
| First repair retest lane 1, `ses_f70e7f1edffewINIkuCL0X1fx7` | `R-M02-1`–`R-M02-5`: **Pass**; 145 tests. | Parent-session independent retest; reviewer `LUNA MAX QA`. | Scoped result completed. |
| First repair retest lane 2, `ses_f70e7f1d2ffe8yAJlKBozlUrfM` | Found `R-M02-30`–`R-M02-32`; **Fail** for those affected checks. | Parent-session independent retest; reviewer `LUNA MAX QA`. | Later public repair/regression sequence closed the scopes. |
| First repair browser retest | Reported 22/22 browser checks and `R-M02-20`: **Pass**. | Exact task ID was not present in the consumed parent report; reviewer `LUNA MAX QA`. | ID remains unavailable; no suffix is invented. |
| Public repair builders | A `ses_f70d720ceffeGC4hiOT8E0FdOY`; B `ses_f70d720b0ffe0AAxTzi3XR0bhc`; C `ses_f70d7209affeTJuYN3nHckLJ62`. | Implementation handoffs; no independent acceptance. | Repair history only. |
| Public API retest, `ses_f70ce409cffe8eCWi2miLmvk7a` | Found `R-M02-41`/`R-M02-42`; **Fail** for those affected checks. | Parent-session independent retest; reviewer `LUNA MAX QA`. | Later final public repair/regression sequence closed the scopes. |
| Public internal retest, `ses_f70ce4085ffeE0EHbDVJOiDjCn` | Scoped checks: **Pass**. | Parent-session independent retest; reviewer `LUNA MAX QA`. | No additional defect ID inferred. |
| Public browser retest, `ses_f70ce406effeuaq2z4gcpIzqRw` | Scoped browser checks: **Pass**. | Parent-session independent retest; reviewer `LUNA MAX QA`. | No additional defect ID inferred. |
| Final public repair builders | A `ses_f70b8b17effebJj2D5Rvc1JWvu`; C `ses_f70b8b08fffeUR0kriamGTF22l`. The B suffix was absent from the consumed evidence and is omitted. | Implementation handoffs; no independent acceptance. | No guessed task ID. |
| Cumulative QA finding | Found `R-M02-55` after the public behavior scopes passed; **Fail** because package smoke's explicit expected-resource assertion omitted migration `003` even though the wheel contained it. | Exact cumulative-QA task ID was not present in the consumed evidence; the finding artifact is retained by the final-QA record below. | No guessed task ID; repaired in the `R-M02-55` wave. |
| `R-M02-55` repair builders | A `ses_f709e8a91ffeOiE2puIHZT7DT4` and B `ses_f709e8a75ffenSblHiLG1fbcVi`: no change/pass handoffs. C `ses_f709e8a51ffekA1umC3iAm3y69`: fix handoff. | Implementation handoffs; no independent acceptance. | Final QA below is authoritative for the scoped gate. |

#### M02 final independent QA

| Evidence ID/task | Check, environment, and UTC evidence | Result, artifact, reviewer, limitation |
| --- | --- | --- |
| `R-M02-55` / `ses_f709ae6ddffe1NyppNASrAKnLQ` | Direct gate at `2026-09-11T07:37:47Z`–`07:38:46Z`, native x86_64, Python `3.11.15`; 154 tests, 4 live deselected, `89.04%`; 22 browser checks; official MCP pass; exact migration, checksum, clean-install, and readiness-schema-3 checks. | **Pass**; artifact `/tmp/opencode/m02-final-qa-20260911T071347Z`; reviewer `LUNA MAX QA`; technical acceptance recommended. |

The scoped repair register is:

| Exact record(s) | Final scoped state and independent evidence |
| --- | --- |
| `R-M02-1`–`R-M02-5` | **Completed** by `ses_f70e7f1edffewINIkuCL0X1fx7` (145 tests), with final-gate regression. |
| `R-M02-10`–`R-M02-18` | **Completed** by the initial pass in `ses_f711eb2abffeURm1Z1rnq6IbEV`, with final-gate regression. |
| `R-M02-19` | **Completed** after the initial **Fail** in `ses_f711eb2abffeURm1Z1rnq6IbEV`; the failure remains visible above. |
| `R-M02-20` | **Completed** after its initial finding; the browser retest reported 22/22 pass, but its exact task ID was unavailable and is not invented. |
| `R-M02-30`–`R-M02-32` | **Completed** after the first repair retest finding and subsequent public repair/regression evidence. |
| `R-M02-41`–`R-M02-42` | **Completed** after the public API retest finding and subsequent repair/regression evidence. |
| `R-M02-55` | **Completed** by the direct final QA gate above. |

The M02 boundary and safety distinctions are part of the evidence contract: trusted in-app malformed submissions audit once; hostile pre-routing traffic does not write; the wire parser is outside the app. Raw `REPLACE` is guarded with recursive triggers off. Restore uses a process-wide lock per canonical database and has no expiry. Public backup data is safe and domain-neutral. Request IDs remain traceable. Saved reopen returns the immutable recorded result; fresh reconstruction is separately labelled, recalculated from its historical cutoff, and recorded as a new analysis.

- **Limitations:** The current QA environment is native x86_64. No physical/native ARM64 result is claimed. Screen-reader evidence remains a later requirement and is not an M02 blocker. No remote CI was run or used. The exact first-repair browser task ID, final-public-repair B task ID, and cumulative-QA task ID were unavailable in the consumed reports and are not guessed.
- **Repair record:** Initial `R-M02-1`–`R-M02-5`, `R-M02-19`, `R-M02-20`, `R-M02-30`–`R-M02-32`, `R-M02-41`–`R-M02-42`, and `R-M02-55` findings remain visible above; their scoped final states are completed only where the named retest/final gate supplies pass evidence.
- **Post-milestone gate:** `EXP-M02` and its secret-review, commit, push, and exact Git remote revision evidence are required before M03 can start. This docs gate did not perform those operations.

### M03 - Yahoo Finance Data And Forecast Engine

- **Status:** In progress.
- **Dependencies:** M01 and M02.
- **Evidence state:** Historical independent retest passed `R-M03-1`, `R-M03-2`, and `R-M05-3` checks, including deterministic and live ACDC/SPY checks; the complete M03 acceptance/export/Git-checkpoint record is still absent, so M03 remains in progress and not completed.
- **Build wave:** `SOL HIGH-A` forecast request/response boundary; `SOL HIGH-B` provider, calendar, calculation, and immutable writes; `SOL HIGH-C` result presentation and browser instrumentation. No shared paths during the wave.
- **Gates:** `LUNA MAX QA` and `LUNA MAX docs` only after the builder wait; export `EXP-M03` after every acceptance row passes. Live Yahoo checks remain separately identified as `Pass`, `Fail`, `Skipped`, or `Unavailable`.
- **Scope:** Implement the provider adapter, company-name/symbol/asset/instrument-identity validation, completed-bar selection, close-to-close and latest-completed-5-minute-bar-to-close horizons, probability calculations, magnitude intervals, provenance, stale/missing-data handling, chronological evaluation, and immutable forecast writes.
- **Acceptance evidence:** [ ] stock and ETF selections follow one tested identity contract; [ ] an in-progress five-minute bar is excluded; [ ] both horizons identify their origin and target timestamps; [ ] probabilities explicitly cover up/down/unchanged, `+/-1%`, `+/-3%`, `+/-5%`, `+/-10%`, and conditional gain/loss; [ ] 50%, 80%, and 95% return and price intervals include definitions, levels, units, and model/version; [ ] saved output and historical-cutoff reconstruction are distinct and separately labelled; [ ] chronological walk-forward evaluation has a baseline comparison, Brier score, reliability/calibration, interval coverage, and rare-event sample uncertainty; [ ] the approximate 60-day Yahoo five-minute archive limitation and session semantics are shown; [ ] provider failures and insufficient data create auditable failed searches without fabricated results; [ ] deterministic fixtures reproduce recorded outputs.
- **Verification:** [ ] provider adapter tests with fixtures; [ ] timezone/session and boundary-time tests; [ ] incomplete-bar, missing-bar, stale-data, and out-of-session tests; [ ] numerical invariants and repeatability checks; [ ] walk-forward/no-leakage and baseline metrics; [ ] interval coverage and rare-event uncertainty checks; [ ] native x86-64 resource smoke test; [ ] local native ARM64 or explicitly emulated ARM64 functional/build/tool smoke test, with physical ARM64 performance kept `Unavailable` without hardware.
- **Repair record:** Record each failed check as `R-M03-<n>` with failing evidence and rerun result.
- **Post-milestone gate:** `EXP-M03` must include the exact provider limitation/staleness record and successful local export/Git-checkpoint verification; unavailable Yahoo access cannot be summarized as green.

### M04 - Dashboard And Searchable History

- **Status:** Blocked.
- **Dependencies:** M01, M02, and M03.
- **Evidence state:** Historical browser QA reported passing exercised journeys, but `R-M04-1` was not independently retested because its retest task was cancelled. M04 remains blocked and not completed.
- **Build wave:** `SOL HIGH-A` API/UI contract integration; `SOL HIGH-B` reconstruction/data-shape integration; `SOL HIGH-C` static presentation and browser operations. Paths must remain disjoint.
- **Gates:** `LUNA MAX QA` and `LUNA MAX docs` only after all builder reports; export `EXP-M04` after every journey and acceptance row passes.
- **Scope:** Build the distinctive Signal Ledger dashboard for company-name/instrument lookup, forecast submission, result comparison, source/as-of/stale/error context, saved-result reopening, explicitly fresh historical-cutoff reconstruction, searchable history, charts, tables, and export.
- **Acceptance evidence:** [ ] polished desktop/mobile layouts at 360, 390, 768, 1280, and 1440 CSS pixels have no overlap or overflow and retain essential content; [ ] tabular numeric hierarchy makes direction, thresholds, conditional gain/loss, and 50/80/95 return/price intervals legible; [ ] historical price and return-distribution charts have text/table equivalents; [ ] loading, empty, failed, repeated, stale, validation, and successful states are understandable without color; [ ] reduced-motion behavior, WCAG AA contrast/structure, keyboard flows, and actual assistive-technology/screen-reader flows cover search, results, errors, history, saved reopen, and reconstruction; [ ] axe and keyboard results are recorded separately and do not substitute for screen-reader evidence; [ ] result views show both forecast modes and instrument identity; [ ] CSV and JSON exports are available and traceable; [ ] all data requests use `/api/v1`.
- **Verification:** [ ] component and API integration tests; [ ] visual checks at every required viewport for no overlap/overflow; [ ] accessibility audit, keyboard pass, and separate actual assistive-technology run; [ ] checked-in browser regression scenarios; [ ] browser network assertion for the API-only boundary; [ ] saved-versus-fresh reconstruction journey; [ ] low-resource render smoke test.
- **Repair record:** Record each failed check as `R-M04-<n>` with failing evidence and rerun result.
- **Post-milestone gate:** `EXP-M04` must preserve browser tool calls and outputs in `SESSION-EXPORT.md`; a generated browser report alone is not the full-session export.

### M05 - Backup, Restore, And Secure Loopback Operations

- **Status:** Blocked.
- **Dependencies:** M02 and M04.
- **Evidence state:** Historical QA initially blocked M05 with `R-M05-1` through `R-M05-4`; the late independent backup retest reported `make check` passing 83 tests at 89.23% and passed its named HMAC/ZIP/permission checks. The repair-ID collisions and local export/Git-checkpoint fields remain unresolved; an earlier concurrent aggregate-check limitation is historical context, not a current unresolved failure. M05 is blocked and not completed.
- **Build wave:** `SOL HIGH-A` operations API/CLI contract; `SOL HIGH-B` backup, restore, filesystem, and SQLite integrity; `SOL HIGH-C` operational UI/scripts and bounded-run integration. No shared paths during the wave.
- **Gates:** `LUNA MAX QA` and `LUNA MAX docs` only after the builder wait; export `EXP-M05` after every acceptance row passes.
- **Scope:** Add verified backup and restore workflow, integrity/manifest checks, safe restore staging, automatic due and pre-migration backups, retention/disk limits without automatic query-history expiry, loopback deployment defaults, trust-key lifecycle, input/path validation, timeout limits, and operational documentation.
- **Acceptance evidence:** [ ] a backup includes the required SQLite data and verifiable metadata/checksum; [ ] automatic due and pre-migration backup triggers are observable; [ ] retention and disk limits are enforced without silently expiring query history; [ ] restore to a clean or staging location validates schema, integrity, trust/key state, and representative counts before promotion; [ ] a tampered, truncated, incompatible, unsafe-path, missing-key, or wrong-key artifact is rejected fail-closed; [ ] active data is not silently destroyed; [ ] trust keys can be transferred and rotated/retired through a documented lifecycle; [ ] default bind is loopback and security behavior is documented.
- **Verification:** [ ] backup/restore round trip; [ ] negative artifact, key, and path tests; [ ] restart and recovery test; [ ] loopback exposure check; [ ] due/pre-migration trigger and retention/disk checks; [ ] cross-architecture restore x86-64 -> ARM64 and ARM64 -> x86-64 using local native ARM64 when available or labelled emulated ARM64 otherwise; [ ] native x86-64 resource and timeout checks; [ ] native ARM64 resource checks only when hardware is available, otherwise record physical performance as `Unavailable`.
- **Repair record:** Record each failed check as `R-M05-<n>` with failing evidence and rerun result.
- **Post-milestone gate:** `EXP-M05` must include artifact/checksum evidence plus secret-review and local commit/push/Git-revision results; local backup files are not release evidence by themselves.

### M06 - Local QA, Playwright MCP, Browser Regressions, And Fail-Closed Gates

- **Status:** Blocked.
- **Dependencies:** M01, M02, M03, M04, and M05.
- **Evidence state:** Historical QA reported MCP/browser/operations checks, but `R-M06-1`'s independent retest was cancelled and the mandatory export/Git-checkpoint records are absent. M06 remains blocked and not completed.
- **Build wave:** `SOL HIGH-A` local API gate integration; `SOL HIGH-B` deterministic fixtures/resource/restore gate integration; `SOL HIGH-C` Playwright MCP/browser/operations and local-gate integration. No shared paths during the wave.
- **Gates:** wait for all builder reports, then independent `LUNA MAX QA` and `LUNA MAX docs`; export `EXP-M06` only after required gates pass or every limitation is explicitly recorded.
- **Scope:** Configure the official `@playwright/mcp` headless tool for local agent QA, check in automated browser regressions, remove any remaining `.github/workflows/ci.yml`, and establish fail-closed local Make/scripts for static checks where adopted, unit/API tests, accessibility, security/export safety, resource limits, migration, and backup/restore.
- **Acceptance evidence:** [ ] the official MCP configuration is discoverable, runs headless locally, and completes an application interaction; [ ] a clean package installation and `make check` pass on native x86-64 and on local native or labelled emulated ARM64; [ ] loopback startup, Node/Chromium, desktop/mobile browser tests, and functional/tool evidence run locally on both target architectures; [ ] browser regressions are checked in and run against a deterministic local app; [ ] a deliberate local failure proves the Make/scripts gate exits nonzero and stops; [ ] `.github/workflows/ci.yml` is absent; [ ] CSV and JSON exports are tested for safe content; [ ] cross-architecture backups and trust-key missing/wrong-key fail-closed cases pass; [ ] test artifacts identify task and commit context; [ ] no test depends on tracked `burry_env/` or local `.venv/`; [ ] physical ARM64 low-resource performance is marked `Unavailable` unless local native ARM64 hardware exists.
- **Verification:** [ ] clean-environment package build/install and `make check` on current native x86-64; [ ] local native ARM64 run if hardware becomes available, otherwise local QEMU/OCI multi-arch run explicitly labelled emulated; [ ] intentional-failure local-gate test; [ ] headless official MCP application interaction; [ ] loopback check; [ ] Node/Chromium browser regression on 360/390/768/1280/1440 desktop/mobile viewports; [ ] separate actual assistive-technology run; [ ] native x86 memory/latency/idle-CPU evidence and, only when hardware exists, native ARM64 performance evidence; [ ] cross-architecture backup/key lifecycle run.
- **Repair record:** Record each failed check as `R-M06-<n>` with failing evidence and rerun result.
- **Post-milestone gate:** `EXP-M06` must include local command/output evidence, browser/MCP artifacts, secret-review result, pushed revision, Git remote branch/revision verification, and every unavailable ARM64 performance field; no external pipeline is recorded.

### M07 - Integrated MVP Acceptance

- **Status:** Pending.
- **Dependencies:** M06.
- **Agents/sequence:** `LUNA MAX QA` and `LUNA MAX docs` perform the integrated gates after the build handoff. `EXP-M07` follows accepted M07 evidence; `ASTRA-FINAL` is later, after M08. Repairs use `R-M07-<n>` or `R-ASTRA-<n>` as applicable.
- **Evidence state:** No integrated acceptance or Astra evidence is recorded; M07 remains pending.
- **Scope:** Run the complete user journey and release review locally on native x86-64 plus local native or labelled emulated ARM64, reconcile all task evidence, and publish the supported local operation and limitations. No physical ARM64 performance claim is permitted without hardware.
- **Acceptance evidence:** [ ] a user looks up a company name and confirms stock/ETF instrument identity, then receives both forecast horizons; [ ] direction/threshold probabilities, conditional gain/loss, 50/80/95 return and price intervals, evaluation metrics, archive limitations, and provenance are traceable to immutable inputs/results; [ ] saved forecasts reopen unchanged while historical cutoffs are labelled fresh analyses; [ ] historical price/return charts have text/table equivalents; [ ] successful, failed, and repeated searches appear in searchable history with no automatic query-history expiry; [ ] outcomes can be appended without changing forecasts; [ ] CSV and JSON export is verified; [ ] due/pre-migration backup, retention/disk limits, cross-architecture restore, trust-key transfer/lifecycle, and missing/wrong-key fail-closed behavior are verified; [ ] responsive/accessibility visual gates pass at 360/390/768/1280/1440 with Signal Ledger direction, no overlap/overflow, reduced motion, WCAG AA, keyboard, and actual assistive-technology evidence; [ ] local loopback security, MCP/browser, comments, resource targets, and local fail-closed Make/scripts all pass; [ ] README and roadmap state the shipped scope honestly; [ ] ARM64 functional/build/tool checks identify native or emulated environment; [ ] physical ARM64 low-resource performance is either measured on local native hardware or recorded `Unavailable`, which prevents a full low-resource ARM64 claim; [ ] optional dark mode/news remain out of contract and options/public hosting remain out of scope.
- **Verification:** [ ] local clean package install, `make check`, loopback, Node/Chromium, official MCP application interaction, and desktop/mobile end-to-end journey on native x86-64; [ ] the same functional/build/tool journey on local native ARM64 or labelled QEMU/OCI emulation; [ ] restore artifacts in both directions with architecture labels; [ ] security and separate keyboard/actual assistive-technology sign-off; [ ] native x86 memory/latency/idle-CPU evidence and explicit ARM64 physical-performance limitation when hardware is unavailable; [ ] coordinator review of every dependency and evidence field.
- **Repair record:** Record each failed release check as `R-M07-<n>` and keep M07 pending until repaired and rerun.
- **Post-milestone gate:** `EXP-M07` follows accepted M07 evidence and records its local Git checkpoint. M08 is the final roadmap milestone before `ASTRA-FINAL`; `EXP-FINAL` is a separate final export/commit/push/Git-revision gate after Astra repairs.

### M08 - Instructional Walkthrough

- **Status:** Pending.
- **Dependencies:** `M07` must be `Completed` as an integrated implementation/QA/docs result, and `EXP-M07` must have its reviewed local Git checkpoint. M08 is the final roadmap milestone before `ASTRA-FINAL`.
- **Agents/sequence:** `SOL HIGH-C` owns the checked-in generation command/script and browser capture integration; A/B provide only disjoint route/data or fixture interfaces; `LUNA MAX QA` and `LUNA MAX docs` review after all builder reports. No claim is made until the artifact and its evidence exist.
- **Scope:** Use deterministic fixture data, the real local app, and official browser tooling to produce a tracked lightweight artifact under `docs/walkthrough/` (or an explicitly recorded equivalent). Prefer a compiled sequence of annotated screenshots when a GIF is less accessible, too large, or less readable; otherwise provide an accessible animated GIF plus companion Markdown/transcript.
- **Artifact contract:** The artifact is step-numbered and includes captions, useful alt text, and a complete Markdown transcript/instruction set. It covers desktop and mobile, including at least representative 1280px desktop and 390px mobile views, and contains no secrets, credentials, tokens, hostnames, or local filesystem paths. A reproducible local `make walkthrough` command (or a checked-in local script named in the record) must regenerate it from fixtures. The tracked walkthrough directory has a total size budget of 20 MiB; any different bounded budget requires an explicit evidence row and reviewer.
- **Acceptance evidence:**
  - [ ] setup and local startup, service readiness, normal shutdown, and troubleshooting are demonstrated;
  - [ ] symbol/company lookup, stock selection, ETF selection, instrument identity, and forecast submission use the real controls;
  - [ ] both forecast horizons are shown, including completed-bar/session semantics;
  - [ ] direction, threshold probabilities, conditional gain/loss, return/price intervals, provenance, stale data, and provider limitations are explained without treating probabilities as guarantees;
  - [ ] stale, provider failure, validation failure, insufficient-data, and repeated-search states are shown honestly;
  - [ ] history filters show successful, failed, and repeated searches; saved reopen is contrasted with separately labelled fresh historical reconstruction;
  - [ ] CSV and JSON export, append-only outcomes, and backup/restore/status controls are demonstrated when those controls are exposed in the UI; an unexposed feature is labelled `Not exposed in UI`, not fabricated;
  - [ ] accessibility names/focus, keyboard operation, reduced-motion behavior, mobile layout, and desktop/mobile responsive use are demonstrated against actual controls;
  - [ ] every frame/image has alt text or a transcript/caption, every instruction has a step number, and no secret or local path appears;
  - [ ] the generation command, fixture identity, app revision, browser-tool version/context, artifact size, and limitations are recorded;
  - [ ] the end-of-project retrospective compares the shipped application with the original prompt and the original approved plan recovered from `SESSION-EXPORT.md`, enumerates every missing or materially altered feature, and assesses whether the UI is beautiful, well designed, and usable using the walkthrough, browser, accessibility, and responsive artifacts; any incomplete recovered source is recorded as `Unavailable`, never inferred;
  - [ ] every retrospective gap creates `R-M08-<n>`, receives repair and affected-check reruns, and is closed or remains explicitly blocking before `ASTRA-FINAL`.
- **Verification:** [ ] run the exact local generation command against deterministic fixtures; [ ] inspect the complete artifact for secrets and local paths; [ ] verify the 20 MiB budget; [ ] use official `@playwright/mcp` and browser regression tooling against the real local app and actual controls at desktop/mobile viewports; [ ] record accessibility/keyboard findings separately from visual and functional findings; [ ] independently review the prompt/plan comparison and UI design/usability assessment; [ ] record every missing, skipped, unavailable, stale, or failed check with its repair ID and rerun result.
- **Repair record:** Record each failed, inaccessible, oversized, nondeterministic, incomplete, or materially altered walkthrough requirement as `R-M08-<n>`; no retrospective gap is silently accepted.
- **Astra input:** `ASTRA-FINAL` must independently inspect the tracked artifact, transcript/alt text, generation evidence, actual-control browser evidence, and retrospective, then matrix them alongside every other feature, endpoint, control, journey, and persistence effect.
- **Post-milestone gate:** Do not create a green `EXP-M08` from the artifact alone. After M08 QA/docs and Astra review, repair and retest all gaps until the Astra result is `Accepted`; then `EXP-M08` records the reviewed walkthrough/export revision and local Git checkpoint before `EXP-FINAL`.

## Evidence Record Format

Every implementation task must maintain these fields in its task record or linked review:

- **Task ID:** the exact `M00`–`M08`, `R-M##-<n>`, `EXP-M00`–`EXP-M08`, `ASTRA-FINAL`, `R-ASTRA-<n>`, or `EXP-FINAL` identifier; do not replace it with a generic phase name.
- **Status:** exactly `Pending`, `In progress`, `Blocked`, or `Completed`.
- **Owner/phase:** builder lane, QA gate, docs gate, Astra review, export, or Git remote verification owner.
- **Dependencies verified:** completed task IDs plus the evidence references that prove each dependency.
- **Change summary:** what changed and what did not change.
- **Acceptance evidence:** one row per acceptance requirement, each with an evidence ID, command/check, environment, UTC timestamp, commit, result (`Pass`, `Fail`, `Skipped`, or `Unavailable`), artifact/link, and named reviewer.
- **Verification result:** independent check name and exact result; a test file, source inspection, generated report, or implementation claim is not a pass by itself.
- **Repair history:** every failure, skip, unavailable provider, stale-data condition, accessibility finding, restore failure, secret-review failure, or connectivity loss; include repair ID, root cause, fix, and rerun result. Use `None` only when no repair was needed.
- **Limitations:** provider, environment, resource, data freshness, coverage, or artifact limitations that remain.
- **Export/Git record:** export task ID, stable `SESSION-EXPORT.md` revision, full-session artifact, secret-review result, checkpoint commit, pushed branch, exact Git remote revision verification, and the next-checkpoint receipt that preserves that result. There is no external-pipeline field.
- **Reviewer:** the named independent verifying agent, and for final release the independent GPT-6 Astra reviewer.

Evidence is not a prose promise. A skipped or unavailable check must be recorded as such and cannot satisfy a required acceptance field.

## Verification And Repair Loop

1. The coordinator selects the next pending task only after its dependencies have completed with evidence and assigns the exact task ID.
2. Exactly three non-overlapping `SOL HIGH build` lanes work concurrently, then all builders report before integration or verification begins.
3. `LUNA MAX QA` and `LUNA MAX docs` run their independent gates after the build wait; neither masks a missing result.
4. The coordinator alone integrates, updates status/evidence, and performs git operations. If any check fails, the task remains pending, in progress, or blocked; create `R-M##-<n>` and repair the root cause rather than weakening the check.
5. QA reruns the failed check and affected regression set. Documentation records the new evidence, limitation, exact timestamp/commit, and any skipped or unavailable result.
6. The coordinator marks a milestone completed only when every acceptance field, independent QA/docs review, reviewer field, matching `EXP-M00`–`EXP-M08` export, secret review, push, and exact Git remote revision verification pass. The supplied x64 SHA context is not dual-architecture or `EXP-M00` proof.
7. After M08, `ASTRA-FINAL` must review the complete feature/API/UI/control/journey/persistence matrix plus the walkthrough and retrospective. Any gap creates `R-ASTRA-<n>` and requires repair, QA rerun, Astra retest, and explicit `Accepted` before `EXP-M08` and `EXP-FINAL`.

## Final Definition Of Done

The MVP is done only when all of the following are true:

- M00 through M08 have explicit statuses and evidence, with no implementation milestone marked complete by assertion alone.
- A user can identify a company and instrument, select Yahoo Finance stocks and ETFs, and receive close-to-close and latest-completed-5-minute-bar-to-close forecasts with clear session/bar semantics.
- Results contain explicit up/down/unchanged and threshold probabilities, conditional gain/loss, 50/80/95 return and price intervals, walk-forward/baseline/calibration/coverage/rare-event evidence, and source/as-of/stale/error/model/version/input/output provenance.
- Every submitted successful, failed, and repeated search is retained, history is searchable through `/api/v1`, and forecast inputs/results/outcomes are immutable or append-only as specified.
- Saved results reopen immutably; historical cutoffs are separately labelled fresh analyses; price/return charts have text equivalents; CSV and JSON export are verified; Yahoo archive limitations are visible.
- Backup artifacts and restores are verified through integrity, compatibility, representative-data, non-destructive promotion, due/pre-migration, retention/disk, trust-key lifecycle, and both-direction cross-architecture checks; missing/wrong keys fail closed and query history is not silently expired.
- The frontend uses FastAPI `/api/v1` for all application data and has no direct SQLite access.
- The dashboard preserves Signal Ledger direction at 360/390/768/1280/1440 without overlap/overflow, with tabular numeric hierarchy, charts/tables, reduced motion, WCAG AA, keyboard, actual assistive technology, and loading/empty/stale/repeated/failure behavior.
- The default deployment is secure loopback and bounded for low-resource Linux x86-64 and ARM64. Native x86 resource targets are measured locally; ARM64 physical low-resource performance is claimed only when local native ARM64 hardware supplies evidence, never from emulation or an original-laptop assumption.
- The official headless `@playwright/mcp` supports local agent QA, automated browser regressions are checked in, and local Make/scripts fail closed on required regressions.
- Code comments explain non-obvious behavior, the supported local workflow is documented, and `README.md` and `AGENTS.md` are reconciled with the evidence actually shipped.
- M08 produces a tracked, bounded, accessible instructional walkthrough from deterministic fixtures and the real local app, with actual-control browser evidence, desktop/mobile instructions, and a completed prompt/approved-plan retrospective. Any gap is repaired before Astra.
- `ASTRA-FINAL` is independently recorded as `Accepted` after its complete evidence matrix and every `R-ASTRA-<n>` retest.
- `EXP-M00` through `EXP-M08` and `EXP-FINAL` each have a reviewed full-session `SESSION-EXPORT.md`, recorded export revision, secret review, commit, push, exact Git remote revision verification, and no hidden unavailable or failed field.
- Optional dark mode/news are not release requirements, and options/public hosting are outside this local-app contract.
