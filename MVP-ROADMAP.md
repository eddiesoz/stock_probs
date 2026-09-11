# Stock Probability MVP Roadmap

## Status Snapshot

This roadmap tracks delivery of the local Linux stock-probability web app. The supported target is Linux x86-64/amd64 and ARM64/aarch64, designed for low-resource operation. The current host is native x86_64; no native ARM64 or physical ARM64 performance result is claimed. ARM64 verification first uses local native hardware if available, otherwise local QEMU/OCI multi-arch execution may verify packaging/runtime portability and functional/build/tool behavior only when explicitly labelled **emulated ARM64**. This is not native/physical ARM64 or original-laptop resource evidence. Repository shape is not acceptance evidence.

- **Completed:** `M00`, documentation baseline only. The four roadmap deliverables are `MVP-PLAN.md`, `MVP-ROADMAP.md`, `AGENTS.md`, and `README.md`.
- **Documentation repair:** `R-M00-2` is **Completed** only for the four-file policy reconciliation; it does not accept implementation.
- **Completed checkpoint:** `EXP-M00` is **Completed** as the M00 coordinator export, with full regex secret review, exact pushed SHA `18da1af0b6bc31020d3587e472b8197146795bf1`, and matching `git ls-remote` result; its evidence is recorded below.
- **Completed:** `M01` and `EXP-M01`; M01 scoped repair rows pass independently and the exact export/Git/workflow checkpoint is SHA `5424fa3e22d9229d038d376512e59b3f35c97e78`.
- **Completed through explicit late repair:** `M02` and `EXP-M02`. The independent receipt `EXP-M02-REPAIR-1`, session `ses_f6eacd1cdffeZxtRNqfzkXOuqJ`, was reviewed by `LUNA MAX QA` at `2026-09-11T17:10:31Z`; the earlier missing review/timing remains historical and no remote CI was run or used. **In progress, not completed:** `M03` only for `EXP-M03`.
- **Blocked, not completed:** `M04`, `M05`, and `M06`; their records retain failed findings, cancelled retests, duplicate repair IDs, or missing mandatory release gates.
- **Pending:** `M07`, `M08`, `EXP-M03` through `EXP-M08`, `ASTRA-FINAL`, and `EXP-FINAL`. `EXP-M01` and `EXP-M02` are completed.
- **Supplied Git receipt:** remote `main` was historically reported at `2a7a3bf66c3665552a46d0bd523544a01f894b3f`; it is not a current checkpoint. The old hosted Actions receipt is obsolete x64-only context and not a current gate or release proof. No external pipeline is in scope.
- **Current-task limitation:** `R-M00-1` is immutable historical documentation recovery. `R-M00-2` is a documentation-only policy repair; it does not run implementation QA, remove implementation files, create a walkthrough, export, commit, push, or verify a new Git revision. No unavailable field is turned green.
- **Rule:** no milestone advances to `Completed` from implementation claims, a test file, a generated artifact, or a narrative summary. The exact evidence record in `MVP-PLAN.md` is authoritative. `EXP-M01` verified the workflow deletion on its exact pushed/remote revision; `EXP-M02` is completed only by its later independent repair receipt, and later milestones still require their own checkpoint evidence.

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
  | `R-M00-2-E3` | Workflow removal, local gate execution, M08 artifact/browser QA, and retrospective | Not run by this docs-only task | **Unavailable** to `R-M00-2`; current `EXP-M01` separately records the later workflow check, while the remaining M06/M07/M08/Astra evidence is future evidence. |
  | `R-M00-2-E4` | R-M00-1 identity/history and collision aliases retained | Current docs; exact UTC time and commit unavailable | **Pass** as documentation content; reviewer: `LUNA MAX docs`; no repair retest implied. |
- **Limitations and export/Git:** At the time of `R-M00-2`, no implementation QA, ARM64 native/emulated run, walkthrough artifact, browser-control check, retrospective, export, commit, push, or new Git revision verification was performed by that docs-only repair; `EXP-M02` was not yet completed then. The later `EXP-M02-REPAIR-1` receipt now completes `EXP-M02` without rewriting that historical timing; `EXP-M03` through `EXP-M08` and `EXP-FINAL` remain pending in their exact records.

### `EXP-M00` completed checkpoint record

- **Status:** `Completed`.
- **Owner/phase:** coordinator export gate; reviewer/coordinator `OpenCode gpt-5.6-sol`.
- **Dependencies verified:** `R-M00-1` and `R-M00-2`; M00 documentation baseline.
- **Export evidence:** active session `ses_f71ec0499ffeokWj4h6tVwyYk1` parsed as JSON with `1,413,943` bytes, `4,268` physical lines, `23` messages, `153` parts, `44` tool parts, and `10` task outputs.
- **Secret evidence:** full regex review found two credential-like candidates and both were masked; no private-key, AWS, GitHub, or Bearer patterns were found. **Pass**.
- **Git evidence:** diff/check review passed; exact pushed SHA `18da1af0b6bc31020d3587e472b8197146795bf1` matched `git ls-remote origin refs/heads/main`. No remote CI was used. The unrelated `?? .vscode/` stayed untouched.
- **Timestamp limitation:** the consumed handoff did not supply an exact UTC completion timestamp; it is recorded as unavailable, not inferred.
- **Next gate at that historical checkpoint:** `M01`, followed by `EXP-M01`; the current records below supersede that forward-looking status.

## Dependency-Ordered Milestones

| ID | Milestone | Dependencies | Status | Evidence state and next gate |
| --- | --- | --- | --- | --- |
| `M00` | Documentation baseline | None | Completed | `R-M00-1` is immutable historical recovery and `R-M00-2` reconciles the current local-only contract; this is docs-only. `EXP-M00` is now the completed exported revision at SHA `18da1af0b6bc31020d3587e472b8197146795bf1`. |
| `M01` | API and application shell | M00, `EXP-M00` | Completed | All three independent QA retests pass their assigned behavior scopes; `R-M01-3`–`R-M01-15` are completed. `EXP-M01` completed export/secret/Git evidence and verified the remote workflow path absent at SHA `5424fa3e22d9229d038d376512e59b3f35c97e78`. |
| `M02` | SQLite audit and immutable records | M01, `EXP-M01` | Completed | All scoped records pass independently; `EXP-M02` is completed only through `EXP-M02-REPAIR-1`, session `ses_f6eacd1cdffeZxtRNqfzkXOuqJ`, with parse/secret/commit/remote-main evidence at `2026-09-11T17:10:31Z`. |
| `M03` | Yahoo Finance data and forecast engine | M01, M02, `EXP-M02` | In progress | Exact `R-M03-3`–`R-M03-22` records are completed after their recorded failures/skips and repairs; `R-M03-23` remains pending for unavailable screen-reader evidence deferred to M04/M06. Only `EXP-M03` is the current gate. |
| `M04` | Dashboard and searchable history | M01, M02, M03 | Blocked | Browser checks passed for exercised journeys, but `R-M04-1` independent retest was cancelled; fresh aliases `R-M04-2`/`R-M04-3` carry assistive/mobile obligations. Then `EXP-M04`. |
| `M05` | Backup, restore, and secure loopback operations | M02, M04 | Blocked | Late backup retest reported `make check` Pass, 83 tests/89.23%, and named adversarial checks; repair-ID collisions and release gates remain. Fresh aliases `R-M05-5`/`R-M05-6` carry the unresolved obligations. Then `EXP-M05`. |
| `M06` | Local QA, MCP, browser regressions, and fail-closed gates | M01, M02, M03, M04, M05 | Blocked | `R-M06-1` independent retest was cancelled; fresh aliases `R-M06-2`/`R-M06-3`/`R-M06-4`, dual-arch, resource, local-gate, and release evidence remain open. Then `EXP-M06`. |
| `M07` | Integrated MVP acceptance | M06 | Pending | Full local user journey, persistence, restore, dual-architecture semantics, visual/AT, release reconciliation, and sign-off remain open. Then `EXP-M07`. |
| `M08` | Instructional Walkthrough | M07, `EXP-M07` | Pending | Deterministic fixture walkthrough, real local app, official browser tooling, actual-control evidence, accessibility/transcript artifact, and prompt/approved-plan retrospective remain open. Then `ASTRA-FINAL`, `EXP-M08`, and `EXP-FINAL`. |

### Current `M01` implementation and independent QA record

- **Status:** `Completed`.
- **Owner/phase:** three `SOL HIGH build` handoffs followed by three independent `LUNA MAX QA` retests; docs consumes the completed QA record. Builder checks are not acceptance evidence.
- **Dependencies verified:** `M00` and completed `EXP-M00` at SHA `18da1af0b6bc31020d3587e472b8197146795bf1`; the M01 work is checkpointed by completed `EXP-M01` at SHA `5424fa3e22d9229d038d376512e59b3f35c97e78`.
- **Builder tasks and repairs:** A `ses_f718d04e0ffeqdv2i56c6k72Pg`, repair `ses_f71674730ffeERY2M1p9htV2Or`, changed `pyproject.toml`, `requirements.lock`, transport/application `src/stock_probs/` files (`api.py`, `cli.py`, `config.py`, `schemas.py`, `service.py`), and API/config tests. B `ses_f718d04a2ffexmhN4OlHuJlTwt`, repair `ses_f716746fbffe9qOSoMniDzfbNi`, changed domain/provider/repository/fixture files and domain/provider/repository tests. C `ses_f718d0469ffeVig2Xix5cE5N1V`, repair `ses_f716746e8ffeEjA0BRqajZ0ycH`, deleted `.github/workflows/ci.yml` and `scripts/install-node-arm64.sh`, changed `.opencode/agent/sol-build.md`, `Makefile`, static UI, browser tooling, and operations tests, and added the ARM64/bootstrap/local-gate scripts. The exact path inventory and summaries are authoritative in `MVP-PLAN.md`.
- **QA evidence:**
  - `M01-QA1`, task `ses_f71521f9dffeWxILBgUaEBhf0O`, native x86_64, completed `2026-09-11T04:27:31Z`: `R-M01-3`–`R-M01-7`, `167/167` harness, `100` non-live passed/`4` deselected/`89.17%`, Ruff+S, strict mypy across 12 production files, 51 comments, compile, and shell checks passed. Artifact `/tmp/opencode/stock_probs-m01-qa`; live/browser/ARM/export skipped in this lane only.
  - `M01-QA2`, task `ses_f71521f5effeKu8HF2uh3fxJT1`, native x86 Python `3.11.15` plus explicitly **emulated ARM64** OCI/QEMU `7.2.0`: executable support metadata `>=3.11,<3.12`, direct no-`make` local gate, clean non-edit wheel install/migration/loopback, safe induced failure nonzero/recorded `Fail`, Node x64/arm64 checksum, OpenCode schema/config/MCP, emulated package/install/migration/loopback, and cleanup passed. Artifacts `test-results/local-gates` and `test-results/arm64`; completion UTC was not supplied. No native/physical ARM64 or performance result.
  - `M01-QA3`, task `ses_f71521efbffeEdTmM7GL4wYmW2`, native x86_64, latest artifact `2026-09-11T04:35:01.820Z`: no product defects; `R-M01-14`/`R-M01-15` and browser `R-M01-3`/`R-M01-4` passed; checked-in 6 desktop + 6 mobile scenarios, no overflow at 360/390/768/1280/1440, stock/ETF identity checks, 53 `/api/v1` fetch/XHR requests with no forbidden/leaked access, structured errors/docs/OpenAPI/console, and official MCP actual interaction passed. Artifacts `/tmp/opencode/m01qa-*`; screen-reader/later polish remain M04/M06.
- **Repair status:** `R-M01-3` and `R-M01-4` completed for router/OpenAPI and startup-harness scoped behavior; `R-M01-5`–`R-M01-7` completed for their coordinator-assigned QA1 scopes; `R-M01-8`–`R-M01-13` completed for their coordinator-assigned package/bootstrap/local-gate/architecture/tool scopes; `R-M01-14`–`R-M01-15` completed for their coordinator-assigned QA3 scopes, with the recorded browser/API/identity/error/docs/OpenAPI/console/MCP evidence. No `R-M01-16`–`R-M01-19` records were created from stale labels.
- **Checkpoint limitation:** the host lacks system `make`; the direct executable gate passed and `Makefile` is a convenience wrapper. Physical/native ARM64 performance is `Unavailable`; the ARM64 result is explicitly emulated functional/tool evidence only. `EXP-M01` verified `.github/workflows/ci.yml` absent on the exact remote checkpoint; the unrelated `?? .vscode/` remained untouched and no remote CI was used. `EXP-M02` is completed through its late repair receipt; `M03` is current and `EXP-M03` is next.

### `EXP-M01` completed checkpoint

- **Status:** `Completed`.
- **Owner/phase:** coordinator export gate. The consumed handoff did not provide a separate named export reviewer or exact UTC completion timestamp; those fields remain unavailable rather than inferred.
- **Dependencies verified:** M01 independent QA and `R-M01-3` through `R-M01-15` scoped pass records.
- **Export evidence:** session `ses_f71ec0499ffeokWj4h6tVwyYk1` parsed as JSON with `8,791,084` bytes, `6,904` physical lines, `34` messages, `241` parts, `70` tools, and `23` task outputs. **Pass**.
- **Secret evidence:** four credential-like candidates were found and all four were masked; no private-key, AWS, GitHub, Bearer, or credential-URL pattern was found. **Pass**.
- **Git/workflow evidence:** commit/push and exact remote revision verified SHA `5424fa3e22d9229d038d376512e59b3f35c97e78`; `.github/workflows/ci.yml` was absent at that remote revision. **Pass**. No pipeline run was used.
- **Limitations:** native x86_64 plus explicitly emulated ARM64 functional/tool evidence only; no physical/native ARM64 result or performance claim; unrelated `?? .vscode/` untouched; exact timestamp and separate export reviewer name not supplied.

### Current `M02` implementation and independent QA record

- **Status:** `Completed`; the behavior records and canonical `EXP-M02` checkpoint are closed only through the explicit late repair receipt `EXP-M02-REPAIR-1`.
- **Owner/phase:** three `SOL HIGH build` handoffs, independent `LUNA MAX QA`, then `LUNA MAX docs`; builder reports are not acceptance evidence.
- **Dependencies verified:** completed `M01` and `EXP-M01` at SHA `5424fa3e22d9229d038d376512e59b3f35c97e78`.
- **Implementation summary:** additive migration `002`; searchable history and audit events; immutable saved reopen versus separately labelled fresh historical-cutoff reconstruction; append-only outcomes; CSV/JSON; and the local M02 gate. Later repair work added migration `003` guard/package-resource coverage without rewriting prior migrations.

#### M02 builder handoffs

| Lane/task | Reported scope | Acceptance meaning |
| --- | --- | --- |
| `SOL HIGH-A`, `ses_f712f4d58ffePmzI8fAR3Oa7hx` | Transport/history contract, saved/fresh reconstruction, outcomes, and API audit records. | Implementation handoff only. |
| `SOL HIGH-B`, `ses_f712f4cf0ffeixu54tZg1FfjNF` | Additive migration `002`, SQLite history/immutability/repository behavior, outcomes, and persistence safeguards. | Implementation handoff only. |
| `SOL HIGH-C`, `ses_f712f4be6ffeAetzWX712LvaDP` | History presentation, CSV/JSON surfaces, browser operation, and local M02 gate. | Implementation handoff only. |

#### M02 initial findings and repair sequence

| Evidence/task | Exact result | Repair/limitation |
| --- | --- | --- |
| Initial lane 1, `ses_f711eb2c2ffe6fXPkurhibBu4h` | Found `R-M02-1`–`R-M02-5`; **Fail** initially. | First repair retest `ses_f70e7f1edffewINIkuCL0X1fx7` later passed all five with 145 tests. |
| Initial lane 2, `ses_f711eb2abffeURm1Z1rnq6IbEV` | `R-M02-10`–`R-M02-18` **Pass**; `R-M02-19` **Fail**. | The failure remains visible; later affected regression evidence passed. |
| Initial lane 3, `ses_f711eb297ffeIQIk61tFgYxNzg` | Found `R-M02-20`; **Fail** initially. | Later browser report gave 22/22 **Pass**; exact browser task ID was unavailable and is not guessed. |
| First repair builders | A `ses_f70f38bb7ffemfzOJYloLsE7E5`; B `ses_f70f38aebffeweicQ3chgjhqlZ`; C `ses_f70f38aa8ffe6KzqqT2WRXU2tP`. | Handoffs only. |
| First repair lane 2, `ses_f70e7f1d2ffe8yAJlKBozlUrfM` | Found `R-M02-30`–`R-M02-32`; **Fail** for affected checks. | Later public repair/regression evidence closed the scopes. |
| Public repair builders | A `ses_f70d720ceffeGC4hiOT8E0FdOY`; B `ses_f70d720b0ffe0AAxTzi3XR0bhc`; C `ses_f70d7209affeTJuYN3nHckLJ62`. | Handoffs only. |
| Public API retest, `ses_f70ce409cffe8eCWi2miLmvk7a` | Found `R-M02-41`/`R-M02-42`; **Fail** for affected checks. | Later repair/regression evidence closed the scopes. |
| Public internal retest, `ses_f70ce4085ffeE0EHbDVJOiDjCn` | Scoped checks **Pass**. | No new defect inferred. |
| Public browser retest, `ses_f70ce406effeuaq2z4gcpIzqRw` | Scoped checks **Pass**. | No new defect inferred. |
| Final public repair builders | A `ses_f70b8b17effebJj2D5Rvc1JWvu`; C `ses_f70b8b08fffeUR0kriamGTF22l`. B suffix unavailable and omitted. | Handoffs only; no guessed ID. |
| Cumulative QA | Found `R-M02-55` after public behaviors passed; **Fail** because package smoke's explicit expected-resource assertion omitted migration `003` even though the wheel contained it. Exact cumulative task ID unavailable in the consumed report. | Finding retained and repaired; no guessed ID. |
| `R-M02-55` repair builders | A `ses_f709e8a91ffeOiE2puIHZT7DT4` and B `ses_f709e8a75ffenSblHiLG1fbcVi`: no change/pass; C `ses_f709e8a51ffekA1umC3iAm3y69`: fix. | Handoffs only; final QA is authoritative. |

#### M02 final QA and scoped register

| Evidence/task | Check and environment/time | Result, artifact, reviewer, limitation |
| --- | --- | --- |
| `R-M02-55` / `ses_f709ae6ddffe1NyppNASrAKnLQ` | Direct gate `2026-09-11T07:37:47Z`–`07:38:46Z`; native x86_64, Python `3.11.15`; 154 tests, 4 live deselected, `89.04%`; 22 browser checks; official MCP pass; exact migrations/checksum/clean install/readiness-schema-3 checks. | **Pass**; `/tmp/opencode/m02-final-qa-20260911T071347Z`; reviewer `LUNA MAX QA`; technical acceptance recommended. |

The final scoped records are `R-M02-1`–`R-M02-5`, `R-M02-10`–`R-M02-20`, `R-M02-30`–`R-M02-32`, `R-M02-41`–`R-M02-42`, and `R-M02-55`, all **Completed** for their recorded scopes. `R-M02-6`–`R-M02-9` were unused. The `21`–`29` labels in QA pass evidence were not repair defects and no records were created from them. Initial failures remain visible above and are not silently converted into passes.

#### `EXP-M02` late repair receipt and completed checkpoint

- **Status:** `Completed` only through `EXP-M02-REPAIR-1`; this receipt is later evidence and is not backdated to the earlier export/commit time.
- **Owner/phase:** independent export-repair QA; OpenCode session `ses_f6eacd1cdffeZxtRNqfzkXOuqJ`; reviewer `LUNA MAX QA`.
- **Evidence:** at `2026-09-11T17:10:31Z`, jq/Python parsing passed for the immutable export: `17,183,159` bytes, `10,029` lines, `50` messages, `350` parts, `106` tool parts, and `50` task outputs. Secret scan passed after distinguishing false positives. The commit contained the changed export and current remote `main` matched exact revision `ae740b79f8d8da5e1996d4ba38caa3a98cb2cce5`; supplied export SHA-256: `d64d…` (only this prefix was supplied, so no suffix is invented). Artifact: tracked `SESSION-EXPORT.md`. Result: **Pass** for each named check; reviewer: `LUNA MAX QA`.
- **Historical limitation:** the earlier export record's missing independent review and exact timing remain visible; this late receipt closes the canonical checkpoint without claiming that the repair happened at that earlier time. No remote CI was run or used.

The M02 safety distinctions are explicit: trusted in-app malformed submissions audit once; hostile pre-routing traffic does not write; the wire parser is outside the app; raw `REPLACE` is guarded with recursive triggers off; restore uses a process-wide per-canonical-database lock with no expiry; public backup data is safe and domain-neutral; request IDs are traceable; saved reopen is immutable while fresh reconstruction is separately labelled and newly recorded.

- **Limitations:** native x86_64 only for final QA; no physical/native ARM64 result is claimed. Screen-reader evidence remains later and is not an M02 blocker. No remote CI was run or used. The first-repair browser task ID, final-public-repair B task ID, and cumulative-QA task ID were unavailable in the consumed reports and are not guessed. The original export review/timing gap is preserved as history; the late repair receipt supplies the current checkpoint evidence.
- **Next gate:** `M03`/`EXP-M03`; this docs gate did not perform the export, commit, push, or remote verification.

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

## Current M03 Evidence Record

`M03` is **In progress** only for `EXP-M03`. M01, `EXP-M01`, M02, and `EXP-M02` are verified; the M03 behavior records below are complete in scope, but no M03 export checkpoint is inferred. The supplied M03 evidence ran on native x86_64 Linux WSL2, Python `3.11.15`, at dirty revision `ae740b79f8d8da5e1996d4ba38caa3a98cb2cce5`. No M03 export, commit, push, or exact remote-revision verification was performed.

- **Owner/phase:** three `SOL HIGH build` handoffs, independent `LUNA MAX QA`, then `LUNA MAX docs`; local-gate output remains scoped evidence, not a release checkpoint.
- **Pass evidence:** provider bounds/identity, cutoff/session semantics, completed-bar selection, numerical/interval/rare-event fields, corrected chronological evaluation, stale/missing-data handling, deterministic checks, package/migration/loopback, browser/MCP, and explicitly emulated-ARM64 functional/tool scopes passed where recorded.
- **Exact initial receipts:** lane 1 `ses_f6f774aaaffeTm7gAU0bGmAugP` passed `R-M03-3`, `R-M03-4`, `R-M03-5`, `R-M03-6`, `R-M03-8`, and `R-M03-9`, and failed `R-M03-7` for the original `2025-01-07T11:20:00-05:00` mutation; lane 2 `ses_f6f774a94ffeTeR7hqQOGwyEO4` passed `R-M03-10`–`R-M03-13` and `R-M03-15`–`R-M03-19`, and initially failed `R-M03-14`; lane 3 `ses_f6f774a7fffeewwU6GC340kNkx` passed `R-M03-20`, initially failed `R-M03-21`, skipped `R-M03-22`, and recorded `R-M03-23` unavailable/deferred. Reviewer for each: `LUNA MAX QA`.
- **Repairs and retests:** repair handoffs A/B/C were `ses_f6f4e64e4ffe4pU2k7hLMSVxtp` (`R-M03-14`), `ses_f6f4e64bbffeMBNd12DmLUXxND` (`R-M03-7`), and `ses_f6f4e6464ffeT0G1nJ1DYSGfiB` (`R-M03-21`). Independent `LUNA MAX QA` retests passed `R-M03-14` in `ses_f6f42aaa4ffe0xr1uX2mtv3tPH` at `2026-09-11T14:00:50Z`–`14:02:31Z` with malformed matrix/concurrency and 175 tests; passed `R-M03-21` in `ses_f6f42aa8dffeSLySK2qeivnie0` with 175/89.02%, 26 browser checks, real MCP, one expected 502, and QEMU-emulated ARM64; and closed the exact original `R-M03-7` mutation in `ses_f6e8b8cd7ffeyHZZEr5fpj6Boc` at `2026-09-11T17:18:07Z`, artifact `/tmp/opencode/r-m03-7-closure-retest.json`.
- **Final/live evidence:** the lane-3 `R-M03-22` skip is preserved, then superseded by exact live passes in `R-M03-8`, `R-M03-19`, and final `R-M03-55`; four live checks passed at `2026-09-11T14:37:18Z`–`14:37:21Z`. Final `R-M03-55` session `ses_f6f2d798fffeERazFPTac2nAar` passed with 175 passed/4 live deselected/89.02%, 26 browser checks, real MCP, and QEMU-emulated ARM64 package/install/migration/loopback evidence. Reviewer: `LUNA MAX QA`.
- **Limitations:** earlier selected live samples retained stale reasons (ACDC omitted one scheduled close and 12 intraday bars; SPY omitted one scheduled close). `R-M03-23` remains **Pending** because actual screen-reader evidence is **Unavailable** and deferred to M04/M06; axe, keyboard, and MCP do not substitute for it. It is a later accessibility gate, not a blocker to the M03 provider/model scope. Host-Python import and scratch-probe `SyntaxError`/`NameError` failures remain visible; corrected probes count as evidence. Physical/native ARM64 performance is unavailable and is not inferred from emulation.

### M03 scoped record register

| Exact record(s) | Status | Evidence state and limitation |
| --- | --- | --- |
| `R-M03-3`–`R-M03-6` | **Completed** | Exact lane-1 passes in `ses_f6f774aaaffeTm7gAU0bGmAugP`; reviewer `LUNA MAX QA`. |
| `R-M03-7` | **Completed** after initial **Fail** | Original `2025-01-07T11:20:00-05:00` mutation failure retained; repair B `ses_f6f4e64bbffeMBNd12DmLUXxND`, exact closure retest `ses_f6e8b8cd7ffeyHZZEr5fpj6Boc` at `2026-09-11T17:18:07Z`, artifact `/tmp/opencode/r-m03-7-closure-retest.json`; reviewer `LUNA MAX QA`. |
| `R-M03-8`–`R-M03-9` | **Completed** | Exact lane-1 passes in `ses_f6f774aaaffeTm7gAU0bGmAugP`; reviewer `LUNA MAX QA`. |
| `R-M03-10`–`R-M03-13` | **Completed** | Exact lane-2 passes in `ses_f6f774a94ffeTeR7hqQOGwyEO4`; reviewer `LUNA MAX QA`. |
| `R-M03-14` | **Completed** after initial **Fail** | Repair A `ses_f6f4e64e4ffe4pU2k7hLMSVxtp`; independent retest `ses_f6f42aaa4ffe0xr1uX2mtv3tPH`, `2026-09-11T14:00:50Z`–`14:02:31Z`, malformed matrix/concurrency and 175 tests; reviewer `LUNA MAX QA`. |
| `R-M03-15`–`R-M03-19` | **Completed** | Exact lane-2 passes in `ses_f6f774a94ffeTeR7hqQOGwyEO4`; `R-M03-19` also supplies the live rerun; reviewer `LUNA MAX QA`. |
| `R-M03-20` | **Completed** | Exact lane-3 pass in `ses_f6f774a7fffeewwU6GC340kNkx`; final-gate regression; reviewer `LUNA MAX QA`. |
| `R-M03-21` | **Completed** after initial **Fail** | Repair C `ses_f6f4e6464ffeT0G1nJ1DYSGfiB`; independent retest `ses_f6f42aa8dffeSLySK2qeivnie0`, 175/89.02%, 26 browser, real MCP, one expected 502, QEMU-emulated ARM64; reviewer `LUNA MAX QA`. |
| `R-M03-22` | **Completed** after **Skipped** lane | Lane-3 skip is retained; exact live passes via `R-M03-8`, `R-M03-19`, and `R-M03-55` at `2026-09-11T14:37:18Z`–`14:37:21Z`; reviewer `LUNA MAX QA`. |
| `R-M03-23` | **Pending** | Actual screen-reader/assistive-technology run is **Unavailable**, deferred to M04/M06; not substituted by axe/MCP and not a blocker to the M03 provider/model scope. |
| `R-M03-55` | **Completed** | Final receipt `ses_f6f2d798fffeERazFPTac2nAar`: 175 passed/4 live deselected/89.02%, 26 browser, real MCP, QEMU-emulated ARM64; reviewer `LUNA MAX QA`. |

### M03 evidence ledger

| Evidence ID/task | Check, environment, UTC evidence | Result, artifact, reviewer, limitation |
| --- | --- | --- |
| `M03-QA1-E1`–`E3` | Exact lane-1 receipt `ses_f6f774aaaffeTm7gAU0bGmAugP` passed `R-M03-3`–`R-M03-6`, `R-M03-8`, and `R-M03-9` on native x86_64/Python `3.11.15`; provider/session/numerical/edge/identity scopes. | **Pass**; OpenCode session is the supplied evidence locator; reviewer `LUNA MAX QA`. |
| `M03-QA1-E4` / `R-M03-7` | Removing ACDC `2025-01-07T11:20:00-05:00` produced the original incorrect `quality=current` result. | **Fail** initially; failure retained. Repair B `ses_f6f4e64bbffeMBNd12DmLUXxND` and closure retest `ses_f6e8b8cd7ffeyHZZEr5fpj6Boc` passed at `2026-09-11T17:18:07Z`; artifact `/tmp/opencode/r-m03-7-closure-retest.json`; reviewer `LUNA MAX QA`. |
| `M03-QA1-E5`–`E6` | Corrected evaluation/split probes and full non-live checks: 171 passed, 4 live deselected, 88.95%; Ruff/security Ruff/mypy/compile/shell/comment audit passed. | **Pass** for corrected checks; scratch `SyntaxError`/`NameError` and wrong-host-Python import failure remain visible. Artifact: supplied lane reports; reviewer `LUNA MAX QA`. |
| `M03-QA2` / `R-M03-10`–`R-M03-19` | Exact lane-2 receipt `ses_f6f774a94ffeTeR7hqQOGwyEO4` passed `R-M03-10`–`R-M03-13` and `R-M03-15`–`R-M03-19`; `R-M03-14` initially failed. | **Pass** for the listed initial records; initial **Fail** retained for `R-M03-14`; repair A `ses_f6f4e64e4ffe4pU2k7hLMSVxtp`; independent retest `ses_f6f42aaa4ffe0xr1uX2mtv3tPH` passed at `2026-09-11T14:00:50Z`–`14:02:31Z` with malformed matrix/concurrency and 175 tests; reviewer `LUNA MAX QA`. |
| `M03-QA3` / `R-M03-20`–`R-M03-23` | Exact lane-3 receipt `ses_f6f774a7fffeewwU6GC340kNkx` passed `R-M03-20`, initially failed `R-M03-21`, skipped `R-M03-22`, and recorded `R-M03-23` unavailable/deferred. | **Pass** for `R-M03-20`; initial **Fail** for `R-M03-21`; **Skipped** for `R-M03-22`; **Unavailable** for `R-M03-23`; reviewer `LUNA MAX QA`. |
| `R-M03-21` retest | Repair C `ses_f6f4e6464ffeT0G1nJ1DYSGfiB`; independent session `ses_f6f42aa8dffeSLySK2qeivnie0`: 175/89.02%, 26 browser, real MCP, exactly one expected 502, and QEMU-emulated ARM64. | **Pass**; reviewer `LUNA MAX QA`; local-gate evidence is scoped and not an export checkpoint. |
| `R-M03-22` rerun | Lane-3 skip retained; exact live passes came from `R-M03-8`, `R-M03-19`, and final `R-M03-55`; four live checks passed at `2026-09-11T14:37:18Z`–`14:37:21Z`. | **Pass** after initial **Skipped** attempt; reviewer `LUNA MAX QA`; earlier stale reasons remain recorded. |
| `R-M03-23` | Actual screen-reader/assistive-technology run. | **Unavailable**; record status **Pending**, deferred to M04/M06, not substituted by axe/MCP, and not a blocker to the M03 provider/model scope; reviewer for the unavailable finding: `LUNA MAX QA`. |
| `R-M03-55` | Final receipt `ses_f6f2d798fffeERazFPTac2nAar`: native x86_64 plus **QEMU-emulated ARM64**, 175 passed/4 live deselected/89.02%, 26 browser checks, real MCP, wheel/resources/migration/loopback. | **Pass**; artifact `test-results/local-gates/R-M03-55-20260911T141605Z/{evidence.json,arm64/evidence.json}`; reviewer `LUNA MAX QA`; not `EXP-M03`, no physical ARM64 performance result. |

- **Repair history:** the earlier `R-M03-1`/`R-M03-2` records remain independently passed for omitted daily and trailing intraday bars. All initial M03 failures, the lane-3 skip, unavailable `R-M03-23`, host-Python import failure, and scratch harness failures remain visible; named retests close the completed records without erasing their history.
- **Post-milestone gate:** `EXP-M03` is **Pending** and is the next gate. It must consume this completed QA/docs record, overwrite and secret-review the full `SESSION-EXPORT.md`, commit, push, and verify the exact remote revision. `R-M03-23` remains a later accessibility limitation rather than a blocker to the M03 provider/model scope.

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

The canonical sequence is `R-M00-1` -> `EXP-M00` (**Completed**) -> `M01` (**Completed**) -> `EXP-M01` (**Completed**) -> `M02` (**Completed**) -> `EXP-M02` (**Completed**) -> `M03` (**In progress**) -> `EXP-M03` (**next gate**) -> `M04`/`EXP-M04` -> `M05`/`EXP-M05` -> `M06`/`EXP-M06` -> `M07` QA/docs -> `EXP-M07` -> `M08` walkthrough QA/docs -> `ASTRA-FINAL` -> repairs/retests until the result is `Accepted` -> `EXP-M08` -> `EXP-FINAL`. No later task may be used to backfill a missing earlier export gate.

## Versioned Export, Commit, Push, And Remote Gates

After each roadmap milestone through M07, before the next milestone starts, complete its exact export task: `EXP-M00`, `EXP-M01`, `EXP-M02`, `EXP-M03`, `EXP-M04`, `EXP-M05`, `EXP-M06`, or `EXP-M07`. `EXP-M08` is the post-Astra checkpoint for the final walkthrough and its retrospective.

1. Use OpenCode `/export`, or a verified CLI equivalent, to overwrite the one tracked root artifact `SESSION-EXPORT.md`.
2. Confirm that the artifact is a full-session export containing tool calls and subagent outputs, not a summary or partial log.
3. Review the complete export for secrets before commit. A skipped, failed, unavailable, or connectivity-blocked secret review blocks the gate.
4. Record the export task ID, export revision, secret-review result, checkpoint commit, pushed branch, exact Git remote revision verification, artifact/link, UTC timestamp, environment, and named reviewer.
5. The coordinator performs the commit/push and verifies the exact Git remote revision. A failed, skipped, unavailable, or connectivity-blocked push or revision check remains exactly that and blocks the checkpoint.

The stable export path is intentionally overwritten; the recorded Git commit/revision versions each export and provide a recoverable checkpoint so work can resume after connectivity loss. Commit/push the reviewed export as checkpoint SHA X, verify that exact SHA on the Git remote, and preserve that receipt in the next checkpoint. The recovered transcript shows an incomplete historical `EXP-M00` attempt, but the current coordinator record completed `EXP-M00` at SHA `18da1af0b6bc31020d3587e472b8197146795bf1` with the exact evidence above. Its handoff did not supply an exact UTC completion timestamp; that limitation remains visible. No GitHub workflow, hosted runner, or external pipeline is used.

After an independently accepted `EXP-FINAL`, an optional operational notification may be referred to as `NOTIFY-FINAL`. It is not a milestone or acceptance task ID and cannot satisfy a missing gate. It may use only a webhook supplied out-of-band by the user and send only a minimal non-secret receipt, such as the accepted result and checkpoint SHA. The endpoint, token, headers, and credential-bearing payload must never be persisted or printed in the repository, `SESSION-EXPORT.md`, artifacts, screenshots, or logs; use a bounded request and redact transport errors. Record bounded success, failure, or unavailable delivery separately without changing the accepted `EXP-FINAL` result. This documentation task performs no notification.

## Restored Milestone Acceptance Rows

The condensed plan had omitted the following contract rows. They are restored here and remain open until exact evidence exists; implementation-shaped files do not satisfy them. M01 and M02's scoped behavior records and checkpoints are recorded above; M03 and later rows remain open at their own gates.

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

The M01 and M02 behavior rows above have current independent scoped pass evidence and completed `EXP-M01`/`EXP-M02` checkpoints; M02's checkpoint was completed only by the late `EXP-M02-REPAIR-1` receipt. `M03` is current with `EXP-M03` as the next checkpoint, all later rows remain open, and neither `R-M00-1` nor `R-M00-2` accepted implementation behavior.

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
