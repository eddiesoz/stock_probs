# Stock Probability MVP Plan

## Status And Scope

This is the implementation contract for the planned local Linux stock probability web app. The supported target is Linux x86-64/amd64 and ARM64/aarch64, with low-resource operation as a release constraint. The current host is native x86_64; no native ARM64 or physical ARM64 performance result is claimed. ARM64 verification first uses local native ARM64 hardware if available, otherwise local QEMU/OCI multi-arch execution may verify packaging, runtime, functional, build, and tool behavior only when every result is labelled **emulated ARM64**. Emulation is not native/physical ARM64 or original-laptop resource evidence. Repository presence is an observation, not acceptance evidence.

- `M00` is **Completed** for the documentation-only contract: `MVP-PLAN.md`, `MVP-ROADMAP.md`, `AGENTS.md`, and `README.md`.
- `EXP-M00` is **Completed** as the M00 coordinator checkpoint; its exact export, secret-review, commit, push, and remote-revision evidence is recorded below.
- `M01` and `EXP-M01` are **Completed**: all three independent QA retests passed their assigned behavior scopes, `R-M01-3` through `R-M01-15` are completed for those scoped repairs, and the exact checkpoint is SHA `5424fa3e22d9229d038d376512e59b3f35c97e78`.
- `M02` and `EXP-M02` are **Completed** only through the late independent repair receipt `EXP-M02-REPAIR-1`, session `ses_f6eacd1cdffeZxtRNqfzkXOuqJ`, reviewed by `LUNA MAX QA` at `2026-09-11T17:10:31Z`. Its scoped `R-M02-1`–`R-M02-5`, `R-M02-10`–`R-M02-20`, `R-M02-30`–`R-M02-32`, `R-M02-41`–`R-M02-42`, and `R-M02-55` records have independent pass evidence. The earlier missing review/timing is preserved as history, no repair is backdated, and no remote CI was run or used. `M03` and `EXP-M03` are **Completed** at exact local/remote SHA `777451643b5ec1a04a37c013a9caf59f0bd58122`.
- `M04` and `EXP-M04` are **Completed** for their recorded scopes. `R-M04-30` remains **Pending** because actual screen-reader evidence is unavailable and deferred to M06; it blocks final accessibility/release acceptance, not the exercised M04 scope. The `EXP-M04` receipt is recorded below.
- `M05` is **Completed for its declared scope** through the independent `R-M05-55` Pass receipt. `EXP-M05` is **Completed** at commit `9be15a3ae60b16e7cc7a5b95653f914b578e1a61` with the exact export audit receipt recorded below. `M06` is **In progress**, with measured native-x86 evidence and independent scoped rows, not an M06 pass; a clean target-commit gate run remains pending. `R-M06-11` has two independent QA passes, each with three hash-stable native runs and exact recomputation; this scoped result does not close M06. `M09` is **Pending** with its ASTRA research-based contract recorded and `SOL HIGH` implementation still future. `M07` is **In progress** with `R-M07-1` profile-count repair in flight, `R-M07-2` Ponytail-review availability pending with findings-only evidence in retained report `test-results/ponytail-m06-m07-boundary.txt` and closure pending, `R-M07-3` completed for supplied repair/test evidence, and `R-M07-4` completed for supplied Ponytail repair evidence. `M08`, `ASTRA-FINAL`, and `EXP-FINAL` are **Pending**. `EXP-M00` through `EXP-M05` are completed; `EXP-M06`, `EXP-M09`, `EXP-M07`, `EXP-M08`, and `EXP-FINAL` remain pending.
- M05's current `R-M05-55` closure is fully **Pass** for its declared scope, reviewed by `LUNA MAX QA` on native x86_64 with `.dev-venv` Python `3.11.15`: rows `(a)`–`(i)` are session `ses_f6bbd6b46ffes2BM2zVjBC5uLg`, `2026-09-12T06:25:04Z`–`2026-09-12T06:44:37Z` (round trip/checksum `06:42:38Z`–`06:42:39Z`; six-path pre-migration forced-failure matrix `06:32:09Z`–`06:32:10Z`; due-check `60`/`2678400` accepted and `59`/`2678401`/`nan` rejected; retention of `32` artifacts/`256 MiB` with history preserved at `06:43:54Z`; `13/13` fail-closed negatives `06:35:29Z`–`06:35:32Z`; key lifecycle with rollback at `06:44:37Z`; `7/7` watchdog probes `06:35:01Z`–`06:35:02Z`; both-direction **emulated ARM64** cross-architecture restore `06:25:04Z`–`06:28:44Z`, artifact `test-results/arm64/M05-20260912T034933Z/evidence.json`; and the `R-M05-12` rerun `06:38:47Z`–`06:38:49Z`), and row `(j)` is session `ses_f6aa32b01ffexjSm9OhpprFwq4`, `2026-09-12T11:26:29Z`–`2026-09-12T11:28:26Z` (`276` non-live tests/`4` live deselected/`89.51%` coverage, documentation validation of `8` categories/`11` topics/`1` skill, `22` documentation tests, a `77`-file comment audit, Ruff, and mypy). Packaged-CLI end-to-end verification is session `ses_f6a96daceffegfAqyKQL2lf3bS` on native x86_64/Python `3.11.15`, with artifact `/tmp/opencode/stock-probs-m05-cli-20260912T114105Z/M05-packaged-cli-receipt.json` and reviewer `LUNA MAX QA` (fresh-venv wheel install, migration pre-backup, named backup, verify, `restore --promote`, wrong-key/tampered rejection, backup-key rotate/retire, and isolated-port serve readiness). Commands and commit were not supplied; no values are inferred. Earlier failures and pending states remain historical evidence; they are not erased by the later closure receipt.
- M05 automation is implementation evidence only: migrate pre-backup, serve due-check with `STOCK_PROBS_BACKUP_INTERVAL_SECONDS` default `86400` and bounds `60`–`2678400`, backup-key rotation/retirement, `32` artifact/`256 MiB` retention limits, and no automatic query-history expiry. `docs/operations/backup-restore.md` and `docs/configure/local-configuration.md` were updated for accuracy by `SOL HIGH`. The M08 capture harness supplied `20` annotated screenshots and manifest SHA-256 `f9fef2b2db0a806cc47ff1db82e1e895f4dd4803425c0cf74426f5fa5a12dd5d`; this is preparation evidence only, not M08 acceptance.
- The current `LUNA MAX docs` profile cannot edit `docs/**`; `SOL HIGH` performed the authored documentation repairs. This profile gap remains visible, and implementation presence does not close the independent documentation-skill/M06 verification.
- A task may move to **Completed** for its declared acceptance scope only after every acceptance item in that scope, independent QA verification, repair history, and reviewer are recorded. `R-M05-12` is now independently rerun inside `R-M05-55 (i)` with `4/4` behavior tests **Pass**; its earlier repair-only state remains historical evidence. A milestone's full release checkpoint additionally requires its export, secret review, local commit, push, and exact Git remote revision verification. A milestone explicitly marked **Completed for declared scope** may retain a separately recorded deferred/unavailable later-release row and a **Pending** export gate; neither is counted as a pass, and both can block final release acceptance. Implementation claims alone never change status. `EXP-M02` moved to **Completed** only through the later named repair receipt, not at the earlier missing-review/missing-timing point. A physical ARM64 performance result is never inferred from emulation.

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
- **Current documentation refinement:** Added the ASTRA-based M09 theme/news contract, exact lane manifest, conditional package gate, performance/byte budgets, ten news states, and M09 acceptance rows. This remains documentation content only; no implementation, configuration, skill, export, or Git-history change was made.
- **Evidence ledger:**

  | Evidence ID | Requirement/check | Environment, UTC time, commit | Result, artifact, reviewer, limitation |
  | --- | --- | --- | --- |
  | `R-M00-2-E1` | `git status`/`git diff` scope review; only the four documentation paths are intended | Current native x86_64 Linux; exact UTC time and commit unavailable; `.vscode/` remains untracked and untouched | **Pass** for documentation scope; artifact: current worktree; reviewer: `LUNA MAX docs`; no implementation QA. |
   | `R-M00-2-E2` | Local-only policy, ARM64 strategy, M01/M06 local gate replacement, M08, sequence, vocabulary, and M05 wording self-review | Current docs; exact UTC time and commit unavailable | **Pass** as documentation content; artifact: four docs; reviewer: `LUNA MAX docs`; no behavior inferred. |
   | `R-M00-2-E3` | Workflow removal, local gate execution, M08 artifact generation, actual-control browser QA, and retrospective | Not run by this docs-only task; exact UTC time/commit unavailable | **Unavailable** to `R-M00-2`; current `EXP-M01` separately records the later workflow check, while the remaining implementation/M06/M07/M08/Astra evidence is future evidence. |
   | `R-M00-2-E4` | R-M00-1 identity/history, collision aliases, and repair labels retained | Current docs; exact UTC time and commit unavailable | **Pass** as documentation content; reviewer: `LUNA MAX docs`; no repair retest implied. |
   | `R-M00-2-E5` | `git diff --check -- README.md AGENTS.md MVP-PLAN.md MVP-ROADMAP.md` | Current native x86_64 Linux; dirty `HEAD` `9be15a3ae60b16e7cc7a5b95653f914b578e1a61`; UTC was not captured by the command tool | **Pass**; no whitespace errors; artifact: current worktree; reviewer: `LUNA MAX docs`; this is a docs-boundary check only. |
    | `R-M00-2-E6` | `.dev-venv/bin/python scripts/validate_docs.py` | Current native x86_64 Linux; dirty `HEAD` `9be15a3ae60b16e7cc7a5b95653f914b578e1a61`; UTC was not captured; execution was denied by the tool permission boundary | **Unavailable**; no validator result is inferred; artifact: none; reviewer: `LUNA MAX docs`; rerun is required when command execution is available. |
    | `R-M00-2-E7` | Documentation scope review with `git status --short` and `git diff --name-only -- README.md AGENTS.md MVP-PLAN.md MVP-ROADMAP.md` | Current native x86_64 Linux; dirty `HEAD` above; UTC was not captured | **Pass** for this task's four-path diff; pre-existing dirty `.opencode/` and `tests/` paths were observed and untouched; reviewer: `LUNA MAX docs`. |
    | `R-M00-2-E8` | M09 root-documentation self-review: ASTRA rejected scope, the exact ten news UI states, and HTTP status semantics retained across the four owned root documents | Current native x86_64 Linux; dirty `HEAD` `9be15a3ae60b16e7cc7a5b95653f914b578e1a61`; UTC timestamp unavailable from the command tool | **Pass** as documentation content; artifact: `README.md`, `AGENTS.md`, `MVP-PLAN.md`, and `MVP-ROADMAP.md`; reviewer: `LUNA MAX docs`; no M09 implementation or QA acceptance inferred. |
    | `R-M00-2-E9` | `.dev-venv/bin/python scripts/validate_docs.py` after the M09 root-documentation update | Current native x86_64 Linux; dirty `HEAD` `9be15a3ae60b16e7cc7a5b95653f914b578e1a61`; UTC timestamp unavailable from the command tool | **Unavailable**; the command execution was denied by the tool permission boundary, so no validator result is inferred; artifact: none; reviewer: `LUNA MAX docs`; rerun remains required when execution is available. |
    | `R-M00-2-E10` | `git diff --check -- README.md AGENTS.md MVP-PLAN.md MVP-ROADMAP.md` after the M09 root-documentation update | Current native x86_64 Linux; dirty `HEAD` `9be15a3ae60b16e7cc7a5b95653f914b578e1a61`; UTC timestamp unavailable from the command tool | **Pass**; no whitespace errors; artifact: current four-document worktree diff; reviewer: `LUNA MAX docs`; no Git mutation performed. |
- **Limitations and repair history:** No implementation QA, native ARM64 run, emulated ARM64 run, walkthrough artifact, browser-control check, retrospective, export, commit, push, or new Git remote verification was performed. `R-M00-2` does not accept any implementation milestone.
- **Export/Git/reviewer:** At the time of `R-M00-2`, no export/commit/push was performed by that documentation-only repair and `EXP-M02` had not yet been completed. The later coordinator records `EXP-M00` through `EXP-M04` are **Completed** at the exact checkpoint receipts recorded below; those later results do not rewrite the historical timing. Later exports remain pending. Reviewer for `R-M00-2`: `LUNA MAX docs` self-review; independent implementation QA was not performed by that historical docs repair.

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
| `R-M05-1` in QA task `ses_f72f4e163ffehgqJPXwbY7ujrX` | Malicious backup artifact handling | `R-M05-5` | **Completed** for the declared M05 scope through the later independent `R-M05-55` Pass receipt; the historical source-qualified label remains unchanged |
| `R-M05-1` in the later backup/operations handoff `ses_f72c4f1baffeECZSQ37ujzSmCJ` | Chunked-request/resource handling and cross-architecture restore harness | `R-M05-6` | **Completed** for the declared M05 scope through the later independent `R-M05-55` Pass receipt; the historical emulated-evidence limitations remain visible |
| `R-M05-2` in QA task `ses_f72f4e163ffehgqJPXwbY7ujrX` | Historical source-qualified label; the recovered record does not supply enough source-specific detail to infer a distinct obligation | No fresh alias allocated | **Completed** for current declared M05 coverage through the later independent `R-M05-55` Pass receipt; the historical label is retained and is not reused |
| `R-M05-4` in QA task `ses_f72f4e163ffehgqJPXwbY7ujrX` | Historical source-qualified label; the recovered record does not supply enough source-specific detail to infer a distinct obligation | No fresh alias allocated | **Completed** for current declared M05 coverage through the later independent `R-M05-55` Pass receipt; the historical label is retained and is not reused |
| `R-M06-1` in QA/operations task `ses_f72f4e163ffehgqJPXwbY7ujrX` | Port-collision behavior | `R-M06-2` | **Completed**; independent retest **Pass** for occupied-port fail-closed behavior; the historical cancelled retest remains visible |
| `R-M06-1` in repair-builder handoff `ses_f72c4f20effeDoLPC0FuHaaGjZ` | Documentation CSP policy | `R-M06-3` | **Completed**; independent retest **Pass** for CSP/host/origin enforcement; the historical cancelled retest remains visible |
| `R-M06-1` in repair-builder handoff `ses_f72c4f20effeDoLPC0FuHaaGjZ` | CSV formula-injection/export behavior | `R-M06-4` | **Completed**; independent retest **Pass** for CSV formula safety; the historical cancelled retest remains visible |
| `R-M04-1` in browser/accessibility task `ses_f72f4e261ffeLWQEjyJI4k3hea` | Actual assistive-technology evidence unavailable | `R-M04-2` | **Pending**; evidence unavailable and screen-reader/assistive run still required separately |
| `R-M04-1` in repair-builder handoff `ses_f72c4f20effeDoLPC0FuHaaGjZ` | Mobile error focus behavior | `R-M04-3` | **Pending**; cancelled independent API/UI retest |

The source task IDs above are evidence locators, not acceptance reviewers. `R-M01-3` and `R-M01-4` now have current independent scoped pass records; `R-M06-2`, `R-M06-3`, and `R-M06-4` have their later independent scoped pass records; the other listed aliases remain pending, and no later repair may reuse one of these fresh IDs for a different defect. `R-M01-5` through `R-M01-15` are current coordinator-assigned M01 records in the M01 register, not additional collision aliases. The `R-M04-2`/`R-M04-3` values here are source-qualified historical aliases from `R-M00-1`; they are retained without being merged into the later source-qualified M04 QA labels carrying the same text. The current M04 screen-reader obligation is `R-M04-30`.

## Mandatory Delivery Workflow

The coordinator applies this workflow to every milestone and repair. It is a sequencing rule, not permission to infer that an existing source file works.

### Global orchestrator concurrency

The maximum is six concurrent agents overall. The orchestrator proactively fills up to six slots only when genuinely independent todos exist; every active agent owns a distinct todo, path, and evidence lane, with no duplicate work. Launch independent work in parallel, keep dependent steps sequential, and wait for all active lanes before integration and before independent QA. Do not invent busywork merely to fill slots. QA/docs waves may use one to six agents based on their genuinely independent scopes; they are not required to use six.

### Safe build-wave ownership

Use up to six concurrent `SOL HIGH build` instances in each implementation or repair wave, never more than six. The coordinator records this lane manifest against the exact milestone or repair ID before work starts; A/B/C are the base roles and any additional lanes must have declared, disjoint implementation/configuration/test ownership:

| Lane | Sole build ownership | Handoff boundary |
| --- | --- | --- |
| `SOL HIGH-A` | Transport/application: FastAPI routes, schemas, configuration, CLI, package/launch assumptions, and transport-facing tests | Versioned API contract and launch assumptions |
| `SOL HIGH-B` | Domain/provider/persistence: forecast semantics, Yahoo/fixture adapters, service, SQLite migrations/repositories, backup/restore, and domain/storage tests | Domain and storage contracts, fixtures, and migration assumptions |
| `SOL HIGH-C` | Presentation/browser/operations: static UI, browser harness, operational scripts, Make/local-gate tooling, dependency/runtime tooling, and presentation/operations tests | UI states, browser journeys, resource limits, and operational assumptions |
| `SOL HIGH-D`–`SOL HIGH-F` | Only a separately declared, disjoint implementation/configuration/test scope | Exact task ID, paths, checks, and handoff boundary recorded before work starts |

No two builders edit the same path or silently cross a lane boundary. `README.md`, `AGENTS.md`, `MVP-PLAN.md`, and `MVP-ROADMAP.md` are documentation-owned; `SESSION-EXPORT.md` is export-owned. Any implementation/config/test path not named in the lane manifest is assigned to A, B, C, D, E, or F before work starts. Builders report the exact task ID, changed paths, checks attempted, failures, and unresolved assumptions. If a dependency requires a shared edit, builders stop and hand it to the coordinator for mechanical integration; the coordinator does not author shared implementation/config/test content. The build wave is complete only after all active builder reports arrive.

After every implementation boundary—each builder handoff, repair handoff, integration, profile/local-gate change, or other configuration boundary—and before independent QA, the coordinator must obtain a read-only `/ponytail-review`. The review is restricted to overengineering. A clean record is exactly `Ponytail result | boundary: <exact task ID> | finding: none | scope: overengineering only | command: /ponytail-review | environment | UTC | commit | result | artifact | reviewer`. A finding is exactly `Ponytail finding | boundary: <exact task ID> | path:line | overengineering claim | evidence | minimal SOL HIGH repair | QA rerun | environment | UTC | commit | result | artifact | reviewer`. Only a reproducible blocking finding receives an ordinary `R-M##-<n>` repair; only `SOL HIGH` implements it, and independent QA reruns it. Ponytail cannot accept or substitute for correctness, security, accessibility, or performance evidence. A missing or unavailable review blocks the affected pre-QA boundary.

### Ordered gates

1. Assign the exact `M##` or repair ID and record verified dependencies, lane ownership, and acceptance rows.
2. Run the declared `SOL HIGH` build wave concurrently, using up to six non-overlapping lanes and no more than six subagents.
3. Wait for all active builder reports and changed paths; do not integrate or declare a result while a report is missing.
4. Run the mandatory read-only `/ponytail-review` for every implementation boundary, before independent QA, using the exact clean/finding format above. A missing or unavailable review blocks the boundary.
5. Run the independent `LUNA MAX QA` and `LUNA MAX docs` waves only after that wait and review. Use one to six agents according to genuinely independent scopes, launch independent QA/docs work in parallel, and keep dependent work sequential. QA is verification-only: it denies repair and delegation conceptually; it does not repair implementation/configuration or hand acceptance to a builder. Docs finalizes only after consuming the completed QA record and must not fill a missing QA result with an implementation claim.
6. The coordinator alone integrates changes, updates status/evidence, and performs git operations. It does not implement, perform QA, route speculative/non-blocking findings, or write roadmap prose. It routes only reproducible blocking findings with an exact task ID to `SOL HIGH`.
7. Agent-profile and local-gate changes are `SOL HIGH` work; each requires a parent-process restart and independent post-restart validation before it can affect a gate. A profile edit, local script, or generated artifact is never self-validating.
8. On any failure, skip, unavailable provider, stale-data condition, accessibility finding, restore failure, secret-review failure, connectivity loss, or missing artifact, keep the task `Pending`, `In progress`, or `Blocked`; create `R-M##-<n>`, repair the root cause, and rerun the failed and affected checks.
9. Follow the canonical sequence exactly: `R-M00-1` -> `EXP-M00` (**Completed**) -> `M01` (**Completed**) -> `EXP-M01` (**Completed**) -> `M02` (**Completed**) -> `EXP-M02` (**Completed**) -> `M03` (**Completed**) -> `EXP-M03` (**Completed**, exact checkpoint `777451643b5ec1a04a37c013a9caf59f0bd58122`) -> `M04` (**Completed** for exercised scope) -> `EXP-M04` (**Completed**, exact checkpoint recorded below) -> `M05`/`EXP-M05` -> `M06`/`EXP-M06` -> `M09` QA/docs -> `EXP-M09` -> `M07` QA/docs -> `EXP-M07` -> `M08` walkthrough QA/docs -> `ASTRA-FINAL` dedicated visual/mobile/responsive/accessibility review -> `R-ASTRA-<n>` SOL repairs/retests and Astra reevaluation until the result is `Accepted` -> `EXP-M08` -> final learning synthesis -> `EXP-FINAL` -> optional `NOTIFY-FINAL` last. The Astra design/repair/final-checkpoint and learning-synthesis sequence is one second-last operational loop, not a new milestone; the final gate is allowed only after Astra acceptance, all repair retests, and the completed learning synthesis.

### Versioned session-export gates

Every milestone has a separately recorded export task ID: `EXP-M00`, `EXP-M01`, `EXP-M02`, `EXP-M03`, `EXP-M04`, `EXP-M05`, `EXP-M06`, `EXP-M09`, `EXP-M07`, or `EXP-M08`. The coordinator uses OpenCode `/export`, or a verified CLI equivalent, to overwrite exactly one tracked root artifact, `SESSION-EXPORT.md`. The export must be a full-session record containing tool calls and subagent outputs; a summary, partial transcript, or untracked local file does not satisfy the gate.

Before commit, the export receives a documented full secret review. Commit and push the reviewed export as checkpoint SHA X, then verify that exact SHA on the configured Git remote. The record names the export revision/commit, pushed branch, Git remote revision result, artifact/link, UTC time, environment, and reviewer. Any failed, skipped, unavailable, or connectivity-blocked export, secret review, commit, push, or Git revision check is recorded with its result and blocks that checkpoint. Git history supplies the version for the stable overwritten path; the export task ID supplies milestone identity. No hosted runner or external pipeline is recorded. `R-M00-1` intentionally did not create, review, commit, or push the export.

After `EXP-FINAL` is independently accepted, an optional operational notification may be referred to as `NOTIFY-FINAL`. This is not a milestone or acceptance task ID and cannot satisfy a missing gate. It may use only a webhook supplied out-of-band by the user and may send only a minimal non-secret receipt, such as the accepted result and checkpoint SHA. The endpoint, token, headers, and credential-bearing payload must be supplied without being persisted or printed in the repository, export, artifacts, screenshots, or logs; the request must be bounded and transport errors redacted. Record bounded success, failure, or unavailable delivery separately without changing the accepted `EXP-FINAL` result. No notification is attempted by this documentation gate.

### Independent final Astra gate

After `M08` walkthrough QA/docs evidence, including the accepted M09 dark-mode/news features, is complete, an independent GPT-6 Astra reviewer executes task `ASTRA-FINAL`. `ASTRA-FINAL` must include a dedicated final visual-design, mobile, responsiveness, and accessibility quality evaluation of the completed UI and walkthrough, as well as an evidence matrix—not implementation claims. The matrix must have a separate row for every product requirement, feature, API endpoint, visible click/control, UI state, persistence effect, asset, documentation visual, walkthrough frame/segment, media item, and static asset. Every row is evaluated against requirements, aesthetics, mobile behavior, responsive behavior, accessibility, and measured performance, and names the check, command, environment, UTC timestamp, commit, result, artifact/link, limitation, and reviewer.

Any missing, failing, skipped, unavailable, or unconfirmed row creates `R-ASTRA-<n>`. Astra evaluates and suggests only; only `SOL HIGH` build agents implement `R-ASTRA-<n>` UI repairs. The repair goes through the same up-to-six-lane build handoff, the mandatory pre-QA Ponytail review, independent QA/docs gates, and Astra re-evaluation of the failed and affected rows. If execution evidence shows that a tooling, skill, or MCP gap caused poor output, a narrowly scoped `R-ASTRA-<n>` may repair and validate that gap before acceptance; it may not expand the product scope without a new evidenced requirement. Repeat until the `ASTRA-FINAL` record explicitly says `Accepted`; only then does `EXP-M08` checkpoint the reviewed walkthrough. After all roadmap and Astra repairs, a final pre-`EXP-FINAL` learning synthesis must deeply analyze sanitized chat/run evidence, use `skill-maintenance` only for justified reusable Stock Probability development skills, validate and index those skills, and log observations. Only after that record is complete may `EXP-FINAL` sanitize the full chat/export, complete secret review, commit, push, and verify the exact remote revision. No final release or `EXP-FINAL` may precede those prerequisites, and no Astra or learning-synthesis run is claimed by this record.

## Product Goal

Build a small, auditable, local web application where a user selects a Yahoo Finance stock or ETF, confirms its company name and instrument identity, and receives two forecast views:

1. **Close-to-close:** a forecast from a clearly identified completed market-session close to the applicable next close.
2. **Latest-completed-5-minute-bar-to-close:** a forecast from the latest completed five-minute bar available at request time to the applicable close. An in-progress bar must never be used as completed input.

Each view must expose probabilities and magnitude intervals, not just a point estimate. The probability contract includes up/down/unchanged direction, `+/-1%`, `+/-3%`, `+/-5%`, and `+/-10%` return thresholds, conditional gain/loss probabilities, and 50%, 80%, and 95% return and price intervals. Every displayed result must identify its company name, symbol, asset type, instrument identity, input timestamps, provider/as-of time, forecast horizon, model/version, interval level and units, stale-data state, and any limitation or failure.

This is a research and auditability tool, not a trading system or a promise of predictive accuracy. Dark mode and selected-instrument news are contract requirements owned by M09; options trading and public hosting are out of scope.

## Non-Negotiable Boundaries

### API boundary

- All frontend application data must pass through FastAPI `/api/v1`.
- The browser must not import a SQLite client, issue SQL, open a database path, or infer storage details from the API.
- The API owns validation, provider calls, forecast calculation, persistence, history queries, and backup/restore operations.
- API errors must be structured, safe to display, and specific enough to distinguish invalid input, unavailable market data, stale data, calculation failure, persistence failure, and restore failure.

### Browser MCP and orchestration invariant

- The stock Playwright MCP entry in `opencode.json` is a hard constraint: retain
  `./scripts/playwright-mcp.sh` with `--headless`, `--isolated`, and loopback host/origin
  allowlists. Any selective Ingenium agent-pipeline adoption must never replace this
  entry with Ingenium browser automation.
- The local acceptance path remains six-agent orchestration with independent QA/docs order,
  the read-only Ponytail boundary, and commit/export gates. A future no-plugin subagent
  count is controlled through the valid `agent.options` field on the orchestrator profile,
  which the orchestrator reads; the schema has no native concurrency cap and
  `subagent_depth` controls nesting only.

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
- Dark mode must be user-selectable and accessible across the dashboard, charts, tables, controls, focus states, and loading/empty/success/stale/failure states at the required viewports; color alone cannot carry meaning.
- News for the selected stock or ETF must be clearly labelled, served through FastAPI `/api/v1`, preserve instrument identity and source/as-of provenance, and expose honest loading, empty, stale, and failure states.
- History must support practical search/filtering and expose enough context to distinguish a repeated request from a new forecast.
- Accessible names, semantic structure, WCAG AA contrast, keyboard operation, reduced-motion behavior, and actual assistive-technology/screen-reader announcements are acceptance concerns, not polish. Axe and keyboard checks do not substitute for an actual screen-reader run.

### Deployment and resources

- The default service must bind to loopback only. The deployment must make any broader bind an explicit, documented, security-reviewed choice.
- Validate symbols, request sizes, date ranges, page sizes, backup paths, and provider timeouts at the API boundary.
- Do not expose provider credentials or local file paths to the browser or logs. Avoid unsafe CORS and unbounded concurrent provider calls.
- Keep the default process, query, cache, and browser-test footprint suitable for low-resource Linux x86-64 and ARM64. Measure rather than assuming that desktop-scale defaults are safe. The existing contract thresholds are process RSS `<500 MiB`, a defined fixture/cache-hit forecast p95 `<1 s`, and an indexed 100,000-history query p95 `<250 ms`; the existing idle-CPU requirement is qualitative (`negligible`). M06's additional executable budgets are explicitly proposed below and are not current results. Native x86-64 measurements are native evidence; ARM64 performance is measured only on local native ARM64 hardware. Emulation can verify packaging/runtime portability and functional/build/tool behavior, but cannot prove physical ARM64 performance.
- All code must have useful comments for non-obvious model, time-window, persistence, security, and resource decisions.
- Do not add auth, MFA, a gateway, a multi-service split, dual-database restore, direct-route SQL, or replica rate limiting without a demonstrated contract requirement. A read-only integrity diagnostic is optional and must not become a new acceptance surface.

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
| Automatic due and pre-migration backups, retention/disk limits, no automatic query-history expiry, bounded chunked-request rejection, watchdog coverage, and protected migration routing are verified. | `M05` operations/persistence row and `M07` restore/retention row. |
| Dark mode is user-selectable and accessible across the dashboard, charts, tables, controls, focus states, and loading/empty/success/stale/failure states at all required viewports without color-only meaning. | `M09` dark-mode implementation/QA/docs rows, `M07` integrated row, `M08` walkthrough row, and `ASTRA-FINAL` matrix rows. |
| Selected-instrument news is clearly labelled, served through FastAPI `/api/v1`, preserves instrument identity and source/as-of provenance, and exposes honest loading, empty, stale, and failure states. | `M09` news/API/UI QA/docs rows, `M07` integrated row, `M08` walkthrough row, and `ASTRA-FINAL` matrix rows. |
| M09 theme initializer is external/parser-blocking before CSS on the dashboard and `/api/v1/docs`, uses localStorage/system/reset-to-system without first-paint flash, semantic roles, numeric contrast, forced-colors, reduced-motion, print, and unchanged strict CSP. | `M09-E1`–`M09-E3`, then `M07`/`M08`/`ASTRA-FINAL` per-asset and per-state rows. |
| M09 news route, closed schemas, separate `fetch_news`, pinned `yfinance==1.7.0` feasibility proof, bounded ephemeral cache, `cache_state`, HTTP `200`/`422`/`502`/`503` semantics with no empty-response `404`, persistence exclusion, provider-free reopen/current-headlines action, safe HTTPS, local-only traffic, and ten UI states are verified. | `M09-E4`–`M09-E8`, then `M07`/`M08`/`ASTRA-FINAL` integrated rows. |
| M09's ASTRA rejected scope remains out of scope unless a new evidenced requirement is approved. | `M09-E13`, then M07/M08/`ASTRA-FINAL` scope-reconciliation rows. |
| M09 quality budgets include static-shell/headroom and justified eighth `theme.js` request, theme switch p95 `<=100 ms`, news fixture p95 `<=100 ms`, ten-item render p95 `<=250 ms`, response `<=32 KiB`, and provider deadline `<=10 s` subject to feasibility. | `M09-E9`–`M09-E12`; native x86 performance only, with ARM64 performance remaining subject to the existing limitation. |
| Both CSV and JSON export are available, safe, and traceable to immutable records. | `M04` user export row and `M06` security/regression row. |
| Existing measured targets: process RSS `<500 MiB`, defined fixture/cache-hit forecast p95 `<1 s`, indexed 100,000-history query p95 `<250 ms`, and qualitative negligible idle CPU. | `M06` mandatory deterministic native-x86 performance rows below; `M07` records any physical ARM64 limitation explicitly. Proposed numeric additions are not current results. |
| Linux x86-64/amd64 and ARM64/aarch64 gates cover clean install/package build, `make check`, loopback, Node/Chromium, official MCP interaction, desktop/mobile tests, and cross-architecture backup/key behavior. ARM64 functional/build/tool checks may be local native or labelled emulated; physical low-resource ARM64 performance is never inferred. | `M06` local dual-architecture row and `M07` release row. No external pipeline or hosted runner substitutes for local evidence. |
| Viewports 360/390/768/1280/1440 have polished no-overlap/no-overflow layouts, tabular numeric hierarchy, all states, charts/tables, reduced motion, WCAG AA, keyboard, and actual assistive-technology evidence. | `M04` visual/accessibility row, `M06` browser gate, `M07` final visual/AT row, and `M08` walkthrough row; axe/keyboard are not screen-reader substitutes. |
| The final walkthrough is a bounded, accessible, reproducible artifact using deterministic fixtures, the real local app, official browser tooling, actual controls, desktop/mobile steps, and a prompt/plan retrospective with repaired gaps. | `M08` walkthrough and retrospective rows, then `ASTRA-FINAL`. |

Dark mode and selected-instrument news are contract requirements owned by M09; options and public hosting are out of scope.

## Task Register

The coordinator assigns the exact task ID. Each implementation or repair build wave runs up to six concurrent, disjoint build lanes and never more than six builders, waits for all active handoffs, then runs the independent QA/docs gates; a QA/docs wave may use one to six agents according to genuinely independent scopes, and docs finalizes only after consuming the completed QA record. The listed acceptance evidence is required before status can become **Completed**, and the matching export gate is required before the milestone is released onward. M08 is the explicit ordering exception: its artifact/QA/docs result is reviewed by Astra first, then `EXP-M08` checkpoints that final walkthrough.

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
- **Post-milestone gate:** `EXP-M01` is **Completed** at SHA `5424fa3e22d9229d038d376512e59b3f35c97e78`; M02 and `EXP-M02` are subsequently completed through the late repair receipt, and the later `M03`/`EXP-M03` completion is recorded at exact SHA `777451643b5ec1a04a37c013a9caf59f0bd58122`.

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

- **Status:** Completed; the behavior records and canonical `EXP-M02` checkpoint are closed only through the explicit late independent repair receipt `EXP-M02-REPAIR-1`.
- **Dependencies:** Completed M01 and completed `EXP-M01` checkpoint SHA `5424fa3e22d9229d038d376512e59b3f35c97e78`.
- **Owner/phase:** three `SOL HIGH build` handoffs, independent `LUNA MAX QA`, and this `LUNA MAX docs` gate. Builder checks are implementation handoffs, not acceptance evidence.
- **Evidence state:** All recorded M02 behavior scopes have independent pass evidence. `EXP-M02` is completed only through the late receipt below; the earlier missing review/timing is preserved and not backdated.
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

#### `EXP-M02` late repair receipt and completed checkpoint

- **Status:** `Completed` only through `EXP-M02-REPAIR-1`; this is later evidence and is not claimed to have occurred at the earlier export/commit time.
- **Owner/phase:** independent export-repair QA; OpenCode session `ses_f6eacd1cdffeZxtRNqfzkXOuqJ`; reviewer `LUNA MAX QA`.
- **Dependencies verified:** all M02 scoped records above, including `R-M02-55`; the prior missing independent review and exact timing remain visible as historical limitations.
- **Change summary:** no implementation or documentation path is accepted by this receipt; it verifies the immutable changed export and its checkpoint evidence.
- **Evidence ledger:**

  | Evidence ID | Requirement/check | Environment, UTC time, commit | Result, artifact, reviewer, limitation |
  | --- | --- | --- | --- |
  | `EXP-M02-REPAIR-1-E1` | jq/Python parse and inventory of the immutable export: `17,183,159` bytes, `10,029` lines, `50` messages, `350` parts, `106` tool parts, `50` task outputs | Local Linux; `2026-09-11T17:10:31Z`; committed revision `ae740b79f8d8da5e1996d4ba38caa3a98cb2cce5` | **Pass**; artifact `SESSION-EXPORT.md`; reviewer `LUNA MAX QA`. |
  | `EXP-M02-REPAIR-1-E2` | Full secret scan after distinguishing false positives | Same receipt and timestamp; revision above | **Pass**; artifact: immutable export scan; reviewer `LUNA MAX QA`; false positives were not treated as secrets or hidden. |
  | `EXP-M02-REPAIR-1-E3` | Commit contained the changed export and current remote `main` matched the exact revision | Remote `main`; `2026-09-11T17:10:31Z`; `ae740b79f8d8da5e1996d4ba38caa3a98cb2cce5` | **Pass**; artifact: commit/remote verification; reviewer `LUNA MAX QA`; supplied export SHA-256 `d64d…` has only the shown prefix, so no suffix is invented. |
  | `EXP-M02-REPAIR-1-E4` | Remote CI use | Same receipt | **Skipped**; no remote CI was run or used, and it is not an acceptance mechanism. Reviewer: `LUNA MAX QA`. |

- **Repair/history:** The earlier `EXP-M02` record's missing review/timing is immutable historical context. This receipt closes the canonical `EXP-M02` later and must not be described as if the repair occurred at the earlier commit time.

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

- **Limitations:** The current QA environment is native x86_64. No physical/native ARM64 result is claimed. Screen-reader evidence remains a later requirement and is not an M02 blocker. No remote CI was run or used. The exact first-repair browser task ID, final-public-repair B task ID, and cumulative-QA task ID were unavailable in the consumed reports and are not guessed. The original export review/timing gap remains visible; the late receipt supplies the current checkpoint evidence.
- **Repair record:** Initial `R-M02-1`–`R-M02-5`, `R-M02-19`, `R-M02-20`, `R-M02-30`–`R-M02-32`, `R-M02-41`–`R-M02-42`, and `R-M02-55` findings remain visible above; their scoped final states are completed only where the named retest/final gate supplies pass evidence.
- **Post-milestone gate:** `EXP-M02` is **Completed** through `EXP-M02-REPAIR-1`; the later `M03` and `EXP-M03` completion is recorded at exact SHA `777451643b5ec1a04a37c013a9caf59f0bd58122`. This docs gate did not perform a new export, commit, push, or remote verification.

### M03 - Yahoo Finance Data And Forecast Engine

- **Status:** Completed.
- **Dependencies:** M01, `EXP-M01`, M02, and `EXP-M02` are verified. `EXP-M02` was completed only through `EXP-M02-REPAIR-1`; no earlier missing review/timing is backdated.
- **Owner/phase:** three `SOL HIGH build` handoffs, independent `LUNA MAX QA`, then this `LUNA MAX docs` reconciliation. Builder/local-gate output is not acceptance by itself, and the consumed local-gate reports do not name a separate export reviewer.
- **Evidence state:** The historical independent retest passed `R-M03-1`, `R-M03-2`, and `R-M05-3`. The exact M03 receipts below cover provider, session, numerical, evaluation, browser/MCP, packaging, loopback, live, and explicitly emulated-ARM64 scopes. `R-M03-3`–`R-M03-22` are **Completed** after their recorded failures/skips and named repairs/retests; `R-M03-23` remains **Pending** because actual screen-reader evidence is unavailable and deferred to M04/M06. M03 is completed for its provider/model scope, and `EXP-M03` is completed by the supplied export receipt below.
- **Build wave:** `SOL HIGH-A` forecast request/response boundary; `SOL HIGH-B` provider, calendar, calculation, and immutable writes; `SOL HIGH-C` result presentation and browser instrumentation. No shared paths during the wave.
- **Gates:** `LUNA MAX QA` and `LUNA MAX docs` only after the builder wait; export `EXP-M03` after every acceptance row in the declared M03 provider/model scope passes. The separately deferred `R-M03-23` accessibility row remains visible and is not substituted or counted as a pass. Live Yahoo checks remain separately identified as `Pass`, `Fail`, `Skipped`, or `Unavailable`.
- **Scope:** Implement the provider adapter, company-name/symbol/asset/instrument-identity validation, completed-bar selection, close-to-close and latest-completed-5-minute-bar-to-close horizons, probability calculations, magnitude intervals, provenance, stale/missing-data handling, chronological evaluation, and immutable forecast writes.
- **Change summary:** The implementation wave added versioned provider/query provenance, stock/ETF identity handling, explicit completed-bar/session rules, empirical/EWMA forecast distributions, direction/threshold/conditional magnitude fields, 50/80/95 intervals, bounded chronological evaluation with baseline/Brier/reliability/coverage fields, stale/missing-data reasons, the M03 browser contracts, and local package/loopback/ARM64 smoke paths. These are changed-path observations supported by the evidence below, not a release claim.
- **Acceptance evidence:** [x] scoped stock/ETF identity, provider bounds, historical-cutoff, interval-rejection, session, numerical, and repeatability checks passed; [x] the normal fixture/browser paths exclude an in-progress bar and expose both forecast origins/targets; [x] direction, unchanged, thresholds, conditional magnitudes, and 50/80/95 intervals are represented and checked; [x] corrected evaluation probes and the deterministic suite cover chronological/no-leakage behavior, baseline metrics, Brier, reliability, interval coverage, and rare-event uncertainty; [x] Yahoo archive/session limitations and stale/missing reasons are explicit; [x] exact independent receipts map and complete `R-M03-3`–`R-M03-22`, including repair/retest closure of `R-M03-7`, `R-M03-14`, `R-M03-21`, and the skipped-live `R-M03-22`; [ ] `R-M03-23` actual screen-reader evidence remains unavailable and deferred to M04/M06; [x] supplied `EXP-M03` export, secret review, commit, push, and exact remote-revision verification are complete.
- **Verification:** [x] provider, session/boundary, numerical, edge-contract, mutation-quality, and corrected evaluation probes supplied results; [x] the lane-1 non-live run passed 171 tests with 4 live tests deselected and 88.95% coverage; [x] Ruff, security Ruff, mypy, compile/shell, and comment audit passed; [x] R-M03-20/R-M03-21/R-M03-55 each recorded 26 browser checks and official MCP smoke; [x] R-M03-21 and R-M03-55 recorded native x86-64 plus explicitly emulated ARM64 package/install/migration/loopback checks; [x] R-M03-14 malformed matrix/concurrency and 175-test retest passed; [x] the exact original R-M03-7 mutation closure passed; [x] four live checks passed after the preserved R-M03-22 skip; [x] supplied `EXP-M03` parse/secret/push/remote checks passed; [ ] physical/native ARM64 performance and actual screen-reader evidence remain unavailable.

#### M03 independent evidence ledger

The following ledger records the supplied evidence without promoting a generated artifact or a builder claim to milestone acceptance. The local reports ran against revision `ae740b79f8d8da5e1996d4ba38caa3a98cb2cce5` with `dirty=true`; the separate supplied `EXP-M03` checkpoint below is the only M03 export/commit/push/remote-revision evidence.

The supplied initial-lane receipts provide exact OpenCode session IDs and record mappings, but do not provide separate UTC completion windows or filesystem artifact links; those fields are recorded as unavailable rather than inferred. The named independent reviewer is `LUNA MAX QA`; no separate OpenCode reviewer is inferred where the receipt does not name one.

| Evidence ID/task | Requirement/check and exact result | Environment, UTC time, commit | Result, artifact, reviewer, limitation |
| --- | --- | --- | --- |
| `M03-QA1-E0`, lane manifest | The wrong host Python `3.14.4` import failed; the project `.dev-venv` Python `3.11.15` rerun proceeded. | Linux WSL2 x86_64; revision `ae740b79f8d8da5e1996d4ba38caa3a98cb2cce5`; supplied lane receipt; reviewer `LUNA MAX QA` | **Fail** for the wrong-environment invocation; not a product failure and not hidden. |
| `M03-QA1-E1`–`E3` / `R-M03-3`–`R-M03-6`, `R-M03-8`, `R-M03-9` | Exact lane-1 session `ses_f6f774aaaffeTm7gAU0bGmAugP` passed provider/identity, session/horizon, numerical/edge, stale-data, and evaluation scopes. | Native x86_64/Python `3.11.15`; dirty revision above; exact UTC window unavailable in supplied receipt; OpenCode session is the evidence locator | **Pass**; reviewer `LUNA MAX QA`. |
| `M03-QA1-E4` / `R-M03-7` | Removing the original ACDC internal bar at `2025-01-07T11:20:00-05:00` produced the incorrect `quality=current` result. | Native x86_64/Python `3.11.15`; initial lane session `ses_f6f774aaaffeTm7gAU0bGmAugP` | **Fail** initially; repair B `ses_f6f4e64bbffeMBNd12DmLUXxND` and exact closure retest `ses_f6e8b8cd7ffeyHZZEr5fpj6Boc` passed at `2026-09-11T17:18:07Z`; artifact `/tmp/opencode/r-m03-7-closure-retest.json`; reviewer `LUNA MAX QA`. |
| `M03-QA1-E5`–`E6` | Corrected evaluation/split probes and full non-live checks: 171 passed, 4 live deselected, 88.95%; Ruff/security Ruff/mypy/compile/shell/comment audit passed. | Native x86_64/Python `3.11.15`; supplied lane evidence; reviewer `LUNA MAX QA` | **Pass** for corrected checks; scratch `SyntaxError`/`NameError` and wrong-host-Python import failure remain visible. |
| `M03-QA2` / `R-M03-10`–`R-M03-19` | Exact lane-2 session `ses_f6f774a94ffeTeR7hqQOGwyEO4` passed `R-M03-10`–`R-M03-13` and `R-M03-15`–`R-M03-19`; `R-M03-14` initially failed. | Native x86_64/Python `3.11.15`; dirty revision above; exact UTC window unavailable in supplied receipt | **Pass** for the listed initial records; **Fail** retained for `R-M03-14`; reviewer `LUNA MAX QA`. Repair A `ses_f6f4e64e4ffe4pU2k7hLMSVxtp`; retest `ses_f6f42aaa4ffe0xr1uX2mtv3tPH` passed at `2026-09-11T14:00:50Z`–`14:02:31Z` with malformed matrix/concurrency and 175 tests. |
| `M03-QA3` / `R-M03-20`–`R-M03-23` | Exact lane-3 session `ses_f6f774a7fffeewwU6GC340kNkx` passed `R-M03-20`, initially failed `R-M03-21`, skipped `R-M03-22`, and recorded `R-M03-23` unavailable/deferred. | Native x86_64/Python `3.11.15`; dirty revision above; exact UTC window unavailable in supplied receipt | **Pass** for `R-M03-20`; initial **Fail** for `R-M03-21`; **Skipped** for `R-M03-22`; **Unavailable** for `R-M03-23`; reviewer `LUNA MAX QA`. |
| `R-M03-21` retest | Repair C `ses_f6f4e6464ffeT0G1nJ1DYSGfiB`; independent session `ses_f6f42aa8dffeSLySK2qeivnie0`: 175/89.02%, 26 browser, real MCP, exactly one expected 502, and QEMU-emulated ARM64. | Native x86_64 plus QEMU-emulated ARM64; dirty revision above; exact UTC window unavailable in supplied receipt | **Pass**; reviewer `LUNA MAX QA`; scoped gate evidence, not an export checkpoint. |
| `R-M03-22` rerun | Lane-3 skip is preserved; exact live passes came from `R-M03-8`, `R-M03-19`, and final `R-M03-55`; four live checks passed at `2026-09-11T14:37:18Z`–`14:37:21Z`. | Native x86_64; live receipt sessions above | **Pass** after initial **Skipped** attempt; stale ACDC/SPY reasons remain recorded; reviewer `LUNA MAX QA`. |
| `R-M03-23` | Actual screen-reader/assistive-technology run. | Native x86_64 host; no supplied run | **Unavailable**; record status **Pending**, deferred to M04/M06; axe/keyboard/MCP do not substitute; reviewer for the unavailable finding: `LUNA MAX QA`. |
| `R-M03-55` | Final receipt session `ses_f6f2d798fffeERazFPTac2nAar`: wheel/resources/migration/loopback, 175 passed/4 live deselected/89.02%, 26 browser, real MCP, and QEMU-emulated ARM64 package/install/migration/loopback. | Native x86_64 plus QEMU-emulated ARM64; artifact `test-results/local-gates/R-M03-55-20260911T141605Z/{evidence.json,arm64/evidence.json}`; dirty revision above | **Pass**; reviewer `LUNA MAX QA`; not `EXP-M03` and no physical ARM64 performance evidence. |

#### M03 scoped record register

The exact rows below preserve the supplied task labels. `Completed` means the named behavior or gate is complete in scope; it does not by itself complete M03 or its export, which require the separate receipts above. Initial failures remain in the ledger and are not erased by later regression passes.

| Exact record | Status | Scoped result and evidence | Repair/limitation |
| --- | --- | --- | --- |
| `R-M03-3`–`R-M03-6` | Completed | **Pass** in exact lane-1 session `ses_f6f774aaaffeTm7gAU0bGmAugP`. | Reviewer `LUNA MAX QA`; scoped behavior only. |
| `R-M03-7` | Completed | Initial **Fail** for the exact `2025-01-07T11:20:00-05:00` mutation; repair B `ses_f6f4e64bbffeMBNd12DmLUXxND`; exact closure retest `ses_f6e8b8cd7ffeyHZZEr5fpj6Boc` passed at `2026-09-11T17:18:07Z`. | Artifact `/tmp/opencode/r-m03-7-closure-retest.json`; reviewer `LUNA MAX QA`; initial failure remains visible. |
| `R-M03-8`–`R-M03-9` | Completed | **Pass** in exact lane-1 session `ses_f6f774aaaffeTm7gAU0bGmAugP`; `R-M03-8` also supplies an exact live pass. | Reviewer `LUNA MAX QA`; corrected probes count, not scratch harness failures. |
| `R-M03-10`–`R-M03-13` | Completed | **Pass** in exact lane-2 session `ses_f6f774a94ffeTeR7hqQOGwyEO4`. | Reviewer `LUNA MAX QA`; exact record mapping is supplied. |
| `R-M03-14` | Completed | Initial **Fail** in lane 2; repair A `ses_f6f4e64e4ffe4pU2k7hLMSVxtp`; independent retest `ses_f6f42aaa4ffe0xr1uX2mtv3tPH` passed at `2026-09-11T14:00:50Z`–`14:02:31Z` with malformed matrix/concurrency and 175 tests. | Reviewer `LUNA MAX QA`; initial failure remains visible. |
| `R-M03-15`–`R-M03-19` | Completed | **Pass** in exact lane-2 session `ses_f6f774a94ffeTeR7hqQOGwyEO4`; `R-M03-19` also supplies an exact live pass. | Reviewer `LUNA MAX QA`. |
| `R-M03-20` | Completed | **Pass** in exact lane-3 session `ses_f6f774a7fffeewwU6GC340kNkx`; final-gate regression. | Reviewer `LUNA MAX QA`; dirty revision and scoped evidence do not equal `EXP-M03`. |
| `R-M03-21` | Completed | Initial **Fail** in lane 3; repair C `ses_f6f4e6464ffeT0G1nJ1DYSGfiB`; independent retest `ses_f6f42aa8dffeSLySK2qeivnie0` passed with 175/89.02%, 26 browser, real MCP, one expected 502, and QEMU-emulated ARM64. | Reviewer `LUNA MAX QA`; initial failure remains visible. |
| `R-M03-22` | Completed | Lane-3 attempt was **Skipped**; exact live rerun passed through `R-M03-8`, `R-M03-19`, and final `R-M03-55`, four passes at `2026-09-11T14:37:18Z`–`14:37:21Z`. | Reviewer `LUNA MAX QA`; stale provider reasons remain recorded. |
| `R-M03-23` | Pending | Actual screen-reader evidence **Unavailable**. | Deferred to M04/M06; axe/keyboard/MCP do not substitute and this is not a blocker to the M03 provider/model scope. |
| `R-M03-55` | Completed | **Pass** in session `ses_f6f2d798fffeERazFPTac2nAar`: 175 passed/4 live deselected/89.02%, 26 browser, real MCP, QEMU-emulated ARM64. | Reviewer `LUNA MAX QA`; not `EXP-M03`, no physical ARM64 performance evidence. |

- **Limitations and repair history:** The host is native x86_64 Linux WSL2; no native/physical ARM64 hardware or performance result exists. Initial `R-M03-7`, `R-M03-14`, and `R-M03-21` failures and the skipped lane for `R-M03-22` remain visible, with named independent retests closing those records. Live samples retained stale reasons as recorded above. Actual screen-reader evidence for `R-M03-23` is unavailable and deferred to M04/M06; it is not substituted by axe/MCP and is not a blocker to the M03 provider/model scope. Harness/environment failures are retained and separated from corrected product probes. The local-gate reports ran with a dirty worktree and do not establish a release commit.
- **Export/Git/reviewer:** `EXP-M03` is **Completed** by the supplied direct export receipt below, reviewed by `OpenCode gpt-5.6-sol` as coordinator. `R-M03-23` remains a later accessibility limitation rather than a blocker to the M03 provider/model scope.
- **Post-milestone gate:** the supplied `EXP-M03` receipt parsed and secret-reviewed the sanitized full-session export, recorded commit UTC `2026-09-11T17:46:42Z`, pushed exact SHA `777451643b5ec1a04a37c013a9caf59f0bd58122`, and verified exact remote `main`. Built-in streaming truncation failures remain visible if present in that export; the final direct export pass is recorded below.

#### `EXP-M03` completed export checkpoint

- **Status:** Completed.
- **Owner/phase:** coordinator export gate; reviewer/coordinator `OpenCode gpt-5.6-sol`.
- **Dependencies verified:** M03 provider/model scope and `R-M03-3`–`R-M03-22` completed records; `R-M03-23` remains Pending and is not substituted by axe/MCP.
- **Change summary:** The supplied sanitized full-session export was parsed and reviewed, then the auditable forecast-engine checkpoint was committed and pushed. This documentation gate records the receipt only; it does not edit `SESSION-EXPORT.md` or perform another Git operation.
- **Evidence ledger:**

  | Evidence ID | Requirement/check | Environment, UTC time, commit | Result, artifact, reviewer, limitation |
  | --- | --- | --- | --- |
  | `EXP-M03-E1` | Parse the sanitized full-session export and inventory `94` messages, `602` parts, `67` task outputs, `176` tool parts, `479,795` bytes, `14,128` physical lines, and `1,298` redaction markers; SHA-256 `964f4f71b8f0d56b1417afc23ff1ea65a69f50ea7a1c3067f91ba8a30c974892` | Supplied sanitized `SESSION-EXPORT.md`; commit UTC `2026-09-11T17:46:42Z`; exact local/remote SHA `777451643b5ec1a04a37c013a9caf59f0bd58122` | **Pass**; artifact: supplied full-session export; reviewer `OpenCode gpt-5.6-sol`. |
  | `EXP-M03-E2` | Full secret review: zero webhook, private-key, AWS, GitHub, Bearer, or embedded-credential patterns | Same sanitized export/checkpoint; `2026-09-11T17:46:42Z`; SHA above | **Pass**; no endpoint, token, or credential was persisted or printed; reviewer `OpenCode gpt-5.6-sol`. |
  | `EXP-M03-E3` | Commit message, push, and exact remote `main` match | `2026-09-11T17:46:42Z`; message `Build auditable forecast engine`; exact local/remote SHA `777451643b5ec1a04a37c013a9caf59f0bd58122` | **Pass**; artifact: pushed commit and exact remote-main receipt; reviewer `OpenCode gpt-5.6-sol`. |
  | `EXP-M03-E4` | CI and export-stream limitations | Same checkpoint; no external pipeline | **Skipped** for CI because no CI was run or used; built-in streaming truncation failures remain visible where present, while the final direct export parse passed; reviewer `OpenCode gpt-5.6-sol`. |

- **Repair/history:** The export record preserves the supplied streaming-truncation failures and does not promote them to passes; the final direct parse, secret review, push, and exact remote-main match passed.
- **Limitations:** No CI, native/physical ARM64 performance, or actual screen-reader evidence is claimed. `R-M03-23` remains Pending and deferred to later accessibility work.
- **Export/Git:** exact local and remote `main` SHA `777451643b5ec1a04a37c013a9caf59f0bd58122`; commit UTC `2026-09-11T17:46:42Z`; message `Build auditable forecast engine`; no new export/commit/push is performed by this docs gate.

### M04 - Dashboard And Searchable History

- **Status:** Completed for the exercised functional scope, and `EXP-M04` is **Completed**.
- **Dependencies:** M01, `EXP-M01`, M02, `EXP-M02`, M03, and completed `EXP-M03` at exact SHA `777451643b5ec1a04a37c013a9caf59f0bd58122`.
- **Owner/phase:** three `SOL HIGH build` handoffs, independent `LUNA MAX QA`, then `LUNA MAX docs`; builder reports and local-gate output are not acceptance by themselves.
- **Evidence state:** named independent repairs and closure QA completed the exercised dashboard/history functional records. `R-M04-30` remains **Pending** because actual screen-reader evidence is **Unavailable** and deferred to M06; it blocks final accessibility/release acceptance, not the exercised M04 feature scope. The old recovered M04 collision history remains visible and is not silently rewritten.
- **Build wave:** `SOL HIGH-A` API/UI contract integration; `SOL HIGH-B` reconstruction/data-shape integration; `SOL HIGH-C` static presentation and browser operations. Paths must remain disjoint.
- **Gates:** `LUNA MAX QA` and `LUNA MAX docs` only after all builder reports; export `EXP-M04` after every applicable exercised-scope journey and acceptance row passes, with deferred or unavailable later-release rows explicitly retained rather than counted as passes.
- **Scope:** Build the distinctive Signal Ledger dashboard for company-name/instrument lookup, forecast submission, result comparison, source/as-of/stale/error context, saved-result reopening, explicitly fresh historical-cutoff reconstruction, searchable history, charts, tables, and export.
- **Change summary:** the supplied wave covered API aliases/noninteger handling, history export query/parity/read bounds, migration timestamp precision, saved/repeated/fresh semantics, dashboard states, chart/table equivalents, responsive Signal Ledger presentation, contrast/axe/MCP checks, and package/migration/runtime tooling. These are evidence-backed scoped changes, not a claim that the dirty worktree is an M04 export checkpoint.
- **Builder handoff record:** A `ses_f6e6a711fffeyuef4zb62H0giu`; B `ses_f6e6a70e1ffe26uoiMUKL6tJYQ`; C `ses_f6e6a70c9ffeHInuhUf0xcS4Sf`. First repairs A/B/C: `ses_f6e23032effeXHemmIiJw24mvc`, `ses_f6e2301f1ffe9tJOQ0zBihTVOF`, `ses_f6e23016bffe6FKOJLQHWssAks`. Second repairs A/B/C: `ses_f6ded9fabffe74Yzkxn9HP3moM`, `ses_f6ded9f30ffe98yoClIySjeVHN`, `ses_f6ded9f04ffeztNVxscerfMIh`; A/B integration: `ses_f6dd70c15ffev9zBudOh8W5hog`. Final C repair/retest is supplied as combined/collision session `ses_f6d97dd26ffesyTKZixyryG1ob`; it is not split into invented sessions.
- **Acceptance evidence:** [x] API-only `/api/v1` dashboard/history behavior, identity, saved/fresh reconstruction, CSV/JSON, chart/table, explicit states, and exercised browser journeys passed in the named final scope; [x] responsive checks passed after repairs at the recorded supported widths, including the initial 1024 overlap and 360 loading-overflow retests; [x] migration/schema-4/package/checksum/runtime and 100,000-row query target passed in closure QA; [x] raw axe completed with `0` violations/`0` incomplete results in the final C/final-gate scope; [x] official headless MCP interaction passed; [x] explicit emulated ARM64 functional/package evidence passed; [ ] actual screen-reader evidence remains unavailable as `R-M04-30`; [x] `EXP-M04` export, secret review, commit, push, and exact remote-revision verification are recorded in the completed checkpoint below.
- **Verification:** [x] final receipt `R-M04-55` / `ses_f6d85b2a2ffeUizsObfcDoBzsZ` passed `198` tests/`89.29%`, `32` browser checks, `4` live checks, `55` backup checks, raw axe `0/0`, package/migration/schema-4, actual MCP, and emulated ARM64 package/runtime checks; [x] closure A `ses_f6dd32543ffeubeFL5TuTKpJIh` passed alias/noninteger safe-404/OpenAPI, event pre-cap/parity, exactly-five-read, and `198 + 4` test checks; [x] closure B `ses_f6dd32520ffe2WEUzDbuouU5iB` passed `R-M04-11`–`R-M04-18`, schema-4/checksum/package, `100,000` rows in `<=48.792 ms`, and five reads; [x] final C `ses_f6d97dd26ffesyTKZixyryG1ob` passed raw axe/contrast/32-browser/MCP scope; [ ] actual screen-reader run is **Unavailable** and deferred to M06; [ ] no native/physical ARM64 or CI result.

#### M04 independent evidence ledger

The supplied QA/retest evidence ran on dirty native x86_64 Linux WSL2/Python `3.11.15`, revision `777451643b5ec1a04a37c013a9caf59f0bd58122`, unless a row says otherwise. Exact UTC windows were not supplied for the parent builder/QA sessions; they remain unavailable rather than inferred. Reviewer for the independent records: `LUNA MAX QA`.

| Evidence/task | Requirement/check and exact result | Environment, UTC evidence, commit | Result, artifact, reviewer, limitation |
| --- | --- | --- | --- |
| Initial QA A `ses_f6e477c95ffewj86nzBDav0XDr` | `R-M04-2`–`R-M04-10` passed; supplied `F-M04-1` undocumented-alias check failed. | Dirty native x86_64 WSL2/Python `3.11.15`; exact UTC window unavailable; revision `777451643b5ec1a04a37c013a9caf59f0bd58122` | **Pass** for the listed R records; **Fail** retained for `F-M04-1`; reviewer `LUNA MAX QA`. |
| Initial QA B `ses_f6e477c73ffeTGeXUo9LjYAyzB` | `R-M04-11`, `R-M04-12`, `R-M04-14`, `R-M04-15`, `R-M04-17`, `R-M04-18` passed; `R-M04-13` failed migration microseconds; `R-M04-16` failed HTTP N+1/export behavior. | Same dirty native x86_64/Python `3.11.15`; exact UTC window unavailable; revision above | **Pass** for listed passes; **Fail** retained for `R-M04-13`/`R-M04-16`; reviewer `LUNA MAX QA`. |
| Initial QA C `ses_f6e477c5cffeCcKYsNq7FiB` | 30 browser/gate checks passed; 1024px overlap and 360px loading overflow were found; actual screen-reader evidence was unavailable as `R-M04-30`. | Same dirty native x86_64/Python `3.11.15`; exact UTC window unavailable; revision above | **Pass** for exercised checks; responsive failures and `R-M04-30` **Unavailable/Pending** retained; reviewer `LUNA MAX QA`. |
| First retest A `ses_f6e0b6f9cffepJAxXGpRAr0yDI` | Other parity/five-read checks passed, but `F-M04-1` retained `422` and `R-M04-16` retained post-cap/event-filter failures. | Same dirty revision; exact UTC window unavailable | **Fail** for affected checks; no builder claim substituted; reviewer `LUNA MAX QA`. |
| First retest B `ses_f6e0b6f7fffeektwB8iMbo1viu` | Migration microseconds repair for `R-M04-13` closed. | Same dirty revision; exact UTC window unavailable | **Pass** for `R-M04-13`; reviewer `LUNA MAX QA`. |
| First retest C `ses_f6e0b6f6effeA4v` | Responsive checks passed; `R-M04-35` retained raw-axe incomplete/manual-contrast failure. The supplied handoff included `Ends?` after this ID; no suffix is inferred. | Same dirty revision; exact UTC window unavailable | **Pass** for responsive scope; **Fail/Pending** retained for `R-M04-35`; reviewer `LUNA MAX QA`. |
| Closure QA A `ses_f6dd32543ffeubeFL5TuTKpJIh` | Alias/noninteger safe `404` and absent OpenAPI; exact event pre-cap/parity; exactly five reads; `198` non-live + `4` live passed. | Native x86_64 Linux WSL2/Python `3.11.15`; exact UTC window unavailable; revision above | **Pass** for A closure; reviewer `LUNA MAX QA`. |
| Closure QA B `ses_f6dd32520ffe2WEUzDbuouU5iB` | `R-M04-11`–`R-M04-18`; schema-4/checksum/package; `100,000`-row query `<=48.792 ms`; five reads. | Native x86_64 Linux WSL2/Python `3.11.15`; exact UTC window unavailable; revision above | **Pass** for B closure; reviewer `LUNA MAX QA`. |
| Closure QA C `ses_f6dd32500ffeYPyuvir4MqUwj8` | Responsive scope passed; raw axe remained incomplete and contrast remained blocked for manual review. | Native x86_64 Linux WSL2/Python `3.11.15`; exact UTC window unavailable; revision above | **Fail/Pending** for unresolved `R-M04-35` scope; reviewer `LUNA MAX QA`. |
| Final C repair/retest `ses_f6d97dd26ffesyTKZixyryG1ob` | Supplied collision/combined handoff: raw axe `0/0`, contrast passes, `32` browser/MCP checks; screen-reader still unavailable. | Native x86_64; exact UTC window unavailable; revision above | **Pass** for repaired visual/MCP scope; `R-M04-30` remains **Unavailable/Pending**; reviewer `LUNA MAX QA`. |
| `R-M04-55` / `ses_f6d85b2a2ffeUizsObfcDoBzsZ` | Final local gate: `198` tests/`89.29%`, `32` browser, `4` live, `55` backup, raw axe `0/0`, schema-4/package/migration, actual MCP, and emulated ARM64 functional/package evidence. | Native x86_64 Linux WSL2/Python `3.11.15`; artifact timestamp `2026-09-11T22:27:04Z`–`2026-09-11T22:34:52Z`; dirty revision `777451643b5ec1a04a37c013a9caf59f0bd58122` | **Pass**; artifact `test-results/local-gates/R-M04-55-20260911T222704Z`; reviewer `LUNA MAX QA`; no native/physical ARM64 or CI. |

#### M04 scoped record register

| Exact record(s) | Status | Scoped result, repair history, and limitation |
| --- | --- | --- |
| `R-M04-2`–`R-M04-10` | **Completed** | Initial A pass in `ses_f6e477c95ffewj86nzBDav0XDr`, final-gate regression; reviewer `LUNA MAX QA`. |
| `R-M04-11`, `R-M04-12`, `R-M04-14`, `R-M04-15`, `R-M04-17`, `R-M04-18` | **Completed** | Initial B pass and closure B `ses_f6dd32520ffe2WEUzDbuouU5iB`; final regression; reviewer `LUNA MAX QA`. |
| `R-M04-13` | **Completed** after initial **Fail** | Migration-microseconds failure retained; first B retest `ses_f6e0b6f7fffeektwB8iMbo1viu` and closure B pass; reviewer `LUNA MAX QA`. |
| `R-M04-16` | **Completed** after initial **Fail** | HTTP N+1, post-cap/event-filter, parity, and formula-safety failures retained; repair sequence, closure A `ses_f6dd32543ffeubeFL5TuTKpJIh`, exactly-five-read/pre-cap/parity pass, and final regression; reviewer `LUNA MAX QA`. |
| `R-M04-21`, `R-M04-22` | **Completed** after initial responsive findings | 1024px overlap and 360px loading overflow retained; responsive retests and final `R-M04-55` pass; reviewer `LUNA MAX QA`. |
| `R-M04-35` | **Completed** after initial **Fail** | Axe-incomplete/manual-contrast finding retained; final C repair/retest `ses_f6d97dd26ffesyTKZixyryG1ob` and `R-M04-55` raw axe `0/0`/contrast pass; reviewer `LUNA MAX QA`. |
| `R-M04-30` | **Pending** | Actual screen-reader evidence **Unavailable**, deferred to M06. It blocks final accessibility/release acceptance, not the exercised M04 functional scope; axe/keyboard/MCP do not substitute. |
| `R-M04-55` | **Completed** | Final receipt above; initial random request-ID/search-collision gate **Fail** and clean rerun **Pass** are both retained; reviewer `LUNA MAX QA`. |

The supplied `F-M04-1` label is preserved as a failure alias/finding rather than silently assigned a new canonical repair ID: its initial undocumented-alias result was `422`, while closure A passed safe noninteger `404` behavior and absence from OpenAPI. No missing task suffix, repair ID, timestamp, native ARM64 result, or CI result is inferred.

- **Repair history:** the initial M04 failures, first-retest residuals, raw-axe/manual-contrast block, responsive findings, screen-reader unavailability, and random request-ID/search-collision gate failure remain visible. Named repair/retest receipts close the completed functional records; `R-M04-30` remains open for M06.
- **Limitations:** QA ran on dirty native x86_64; ARM64 evidence is explicitly emulated functional/package evidence only; physical/native ARM64 performance and screen-reader evidence are unavailable; no CI was run or used.
- **Export/Git/reviewer:** `EXP-M04` is **Completed** at commit `59534faf1cdce493bc51a11d4adbea5e5b2d6892`, with commit UTC `2026-09-11T20:25:10-04:00`, pushed exact `origin/main` match, and no CI run or use. The named export reviewer is not supplied in this reconciliation; that missing field is retained rather than invented.
- **Post-milestone gate:** `M04` exercised scope and `EXP-M04` are **Completed** for their recorded scopes; `R-M04-30` still blocks final accessibility/release acceptance and is deferred to M06.

#### `EXP-M04` completed export checkpoint

- **Status:** Completed.
- **Owner/phase:** coordinator export gate; the supplied receipt is recorded by `LUNA MAX docs` without re-running export or Git operations.
- **Dependencies verified:** M04 exercised functional scope and `R-M04-55` are complete; `R-M04-30` remains Pending because actual screen-reader evidence is Unavailable and deferred to M06.
- **Change summary:** the sanitized full-session `SESSION-EXPORT.md` was overwritten, parsed, secret-reviewed, committed, pushed, and checked against remote `main`; no CI was run or used.
- **Evidence ledger:**

  | Evidence ID | Requirement/check | Environment, UTC time, commit | Result, artifact, reviewer, limitation |
  | --- | --- | --- | --- |
  | `EXP-M04-E1` | Sanitized full-session `SESSION-EXPORT.md` overwritten, parsed as JSON, and inventoried as `140` messages, `844` parts, `101` task outputs, `241` tool parts, `672,190` bytes, `19,855` physical lines, and `1,817` redaction markers; SHA-256 `5eebab2ce302e9f8b5a08aec5e4773c8bf7e4a99c920fa059c462dd71cecb837` | Supplied `SESSION-EXPORT.md`; commit `59534faf1cdce493bc51a11d4adbea5e5b2d6892`; commit UTC `2026-09-11T20:25:10-04:00` | **Pass as supplied export receipt**; named reviewer not supplied in this reconciliation. |
  | `EXP-M04-E2` | Full secret review: zero webhook, private-key, AWS, GitHub, Bearer, or embedded-credential matches | Same sanitized export/checkpoint | **Pass as supplied secret-review receipt**; no credential match was found; named reviewer not supplied. |
  | `EXP-M04-E3` | Commit message, push, and exact remote `main` match | Commit `59534faf1cdce493bc51a11d4adbea5e5b2d6892`; message `Build responsive forecast dashboard`; remote `origin/main` | **Pass as supplied Git receipt**; exact remote match verified; named reviewer not supplied. |
  | `EXP-M04-E4` | CI limitation | Same checkpoint | **Skipped**; no CI was run or used. |

- **Repairs/history:** `R-M04-30` remains open for M06; the initial functional failures, repairs, retests, and final `R-M04-55` receipt remain in the M04 ledger above. The export receipt does not substitute for the unavailable screen-reader run.
- **Limitations:** no native/physical ARM64 performance or actual screen-reader result is claimed; the named export reviewer was not supplied in this reconciliation. The exact export, secret, commit, push, and remote-match facts above are the supplied checkpoint evidence.

### M05 - Backup, Restore, And Secure Loopback Operations

- **Status:** Completed for the declared M05 scope.
- **Dependencies:** M02 and M04 are satisfied; the M05 behavior/repair acceptance scope is closed by `R-M05-55`, and the separate `EXP-M05` checkpoint is **Completed** at `9be15a3ae60b16e7cc7a5b95653f914b578e1a61`.
- **Evidence state:** Historical QA initially blocked M05 with `R-M05-1` through `R-M05-4`; the late independent backup retest and its limitations remain visible. The later independent `R-M05-55` receipt is fully **Pass** for rows `(a)`–`(i)` and `(j)`: row `(i)` includes the `R-M05-12` independent rerun with `4/4` behavior tests, and row `(j)` records `276` non-live tests passed/`4` live deselected/`89.51%` coverage, documentation validation of `8` categories/`11` topics/`1` skill, `22` documentation tests, a `77`-file comment audit, Ruff, and mypy. No failure or earlier pending state is erased by this later closure.
- **Build wave:** `SOL HIGH-A` operations API/CLI contract; `SOL HIGH-B` backup, restore, filesystem, and SQLite integrity; `SOL HIGH-C` operational UI/scripts and bounded-run integration. No shared paths during the wave.
- **Gates:** `LUNA MAX QA` and `LUNA MAX docs` only after the builder wait; export `EXP-M05` after every acceptance row passes.
- **Scope:** Add verified backup and restore workflow, integrity/manifest checks, safe restore staging, automatic due and pre-migration backups, retention/disk limits without automatic query-history expiry, loopback deployment defaults, trust-key lifecycle, input/path validation, timeout limits, and operational documentation.
- **Acceptance evidence:** [x] a backup includes the required SQLite data and verifiable metadata/checksum; [x] automatic due and pre-migration backup triggers are observable; [x] retention and disk limits are enforced without silently expiring query history; [x] restore to a clean or staging location validates schema, integrity, trust/key state, and representative counts before promotion; [x] a tampered, truncated, incompatible, unsafe-path, missing-key, or wrong-key artifact is rejected fail-closed; [x] active data is not silently destroyed; [x] trust keys can be transferred and rotated/retired through a documented lifecycle; [x] unknown-length/chunked request input is rejected before body consumption; [x] every migrating CLI command is protected by the pre-migration path; [x] watchdog bounds due-check, creation, internal verification, pre-migration, serve startup, and public verify/restore; [x] default bind is loopback and security behavior is documented. These acceptance items are covered by the fully passing `R-M05-55` rows `(a)`–`(j)` and the exact row mapping recorded below.
- **Verification:** [x] backup/restore round trip; [x] negative artifact, key, and path tests; [x] restart and recovery test; [x] loopback exposure check; [x] due/pre-migration trigger and retention/disk checks; [x] chunked-request falsification; [x] watchdog timeout checks for each named operation; [x] every-command migration-protection check; [x] cross-architecture restore x86-64 -> **emulated ARM64** and **emulated ARM64** -> x86-64; [x] native x86-64 resource and timeout checks. The receipt metadata below records the exact sessions, windows, probe times, cross-architecture artifact, packaged-CLI artifact, native x86_64 environments, and reviewer `LUNA MAX QA`; commands and commits were not supplied and are not inferred. No native ARM64 resource or performance result is inferred.
- **Repair record:** Record each failed check as `R-M05-<n>` with failing evidence and rerun result.
- **Post-milestone gate:** `EXP-M05` must include artifact/checksum evidence plus secret-review and local commit/push/Git-revision results; local backup files are not release evidence by themselves.

#### M05 repair-wave ledger

This ledger retains the initial repair history and records the later independent closure.
The current worktree is dirty native x86_64 Linux at HEAD
`59534faf1cdce493bc51a11d4adbea5e5b2d6892`. The supplied `R-M05-55` receipt records
session `ses_f6bbd6b46ffes2BM2zVjBC5uLg` for rows `(a)`–`(i)` at
`2026-09-12T06:25:04Z`–`2026-09-12T06:44:37Z` and session
`ses_f6aa32b01ffexjSm9OhpprFwq4` for row `(j)` at
`2026-09-12T11:26:29Z`–`2026-09-12T11:28:26Z`, on native x86_64 with `.dev-venv`
Python `3.11.15`, reviewed by `LUNA MAX QA`. The packaged-CLI session is
`ses_f6a96daceffegfAqyKQL2lf3bS` on native x86_64/Python `3.11.15`, with artifact
`/tmp/opencode/stock-probs-m05-cli-20260912T114105Z/M05-packaged-cli-receipt.json` and
reviewer `LUNA MAX QA`. Commands and commits were not supplied and are not inferred.
`R-M05-55` closes the declared M05 scope; it does not create `EXP-M05`.

| Task ID | Status | Owner/phase and requirement | Supplied evidence and exact result | Artifact, reviewer, and limitation |
| --- | --- | --- | --- | --- |
| `R-M05-5` | **Completed** | `SOL HIGH` malicious-backup repair; `LUNA MAX QA` closure gate. Close unsafe/tampered/truncated artifacts and missing/wrong-key paths without damaging active data. | `R-M05-5-E1` retains the repair surface in `tests/test_backup_cli.py`; the later `R-M05-55 (a)`–`(i)` receipt closes the declared scope. | **Pass** in the fully passing `R-M05-55` consolidated scope; exact receipt sessions, windows, environment, and reviewer are recorded below; command and commit were not supplied. |
| `R-M05-6` | **Completed** | `SOL HIGH` request-boundary and cross-architecture repair; `LUNA MAX QA` closure gate. Falsify unbounded chunked request handling and preserve verified backup data in both directions. | `R-M05-6-E1` retains the no-body-consumption check; `R-M05-6-E2` retains supplied x86-64 -> emulated ARM64 and reverse-direction evidence at `test-results/arm64/M05-20260912T034933Z/evidence.json` and reference `d70220a0…`. The later `R-M05-55 (a)`–`(i)` receipt closes the declared scope. | **Pass** in the fully passing `R-M05-55` consolidated scope; the referenced emulated artifact remains functional evidence only, not native ARM64 or performance evidence. Exact receipt sessions, windows, environment, and reviewer are recorded below; command and commit were not supplied. |
| `R-M05-7` | **Completed** | `SOL HIGH` repair routing. This remains a finding record, not a replacement for the later closure receipt. | `R-M05-7-E1` retains the initial **Fail** for insufficient watchdog coverage; `R-M05-8`/`R-M05-11` and the later `R-M05-55 (a)`–`(i)` receipt close the declared scope. | **Pass** for the declared M05 scope; the initial failure remains visible. Exact receipt sessions, windows, environment, and reviewer are recorded below; command and commit were not supplied. |
| `R-M05-8` | **Completed** | `SOL HIGH` watchdog repair; `LUNA MAX QA` independent retest. | `R-M05-8-E1` retains the repair coverage statement; the later `R-M05-55 (a)`–`(i)` receipt closes the declared scope. | **Pass** in the fully passing `R-M05-55` consolidated scope; exact receipt sessions, windows, environment, and reviewer are recorded below; command and commit were not supplied. |
| `R-M05-11` | **Completed** | `SOL HIGH` follow-up watchdog repair; `LUNA MAX QA` independent retest. | `R-M05-11-E1` retains coverage of due-check, creation, internal verification, pre-migration, serve startup, and public verify/restore; the later `R-M05-55 (a)`–`(i)` receipt closes the declared scope. | **Pass** in the fully passing `R-M05-55` consolidated scope; exact receipt sessions, windows, environment, and reviewer are recorded below; command and commit were not supplied. |
| `R-M05-9` | **Completed** | `SOL HIGH` walkthrough/comment repair; independent comment/walkthrough verification. | `R-M05-9-E1` retains the implementation-wave repair surface; row `(j)` of `R-M05-55` records the independent comment audit. | **Pass** in the fully passing `R-M05-55` scope, including the `77`-file comment audit; exact receipt sessions, windows, environment, and reviewer are recorded below; command and commit were not supplied. |
| `R-M05-10` | **Completed** | `SOL HIGH` CLI migration-protection repair; `LUNA MAX QA` retest. | `R-M05-10-E1` retains the all-command routing statement; the later `R-M05-55 (a)`–`(i)` receipt closes the declared scope. | **Pass** in the fully passing `R-M05-55` consolidated scope; exact receipt sessions, windows, environment, and reviewer are recorded below; command and commit were not supplied. |
| `R-M05-12` | **Completed** | `SOL HIGH` Ponytail repair record and independent behavior rerun. | `R-M05-12-E1`: [`docs/evidence/ponytail-m05-boundary.txt`](docs/evidence/ponytail-m05-boundary.txt) records the two overengineering findings and repair. `R-M05-55 (i)` independently reran the affected behavior tests: `4/4` **Pass**. | **Pass** for the independent rerun inside `R-M05-55 (i)`; the receipt retained at `docs/evidence/ponytail-m05-boundary.txt` is overengineering-only. Exact rerun session, window, environment, and reviewer are recorded below; command and commit were not supplied. |
  | `R-M05-55` | **Completed** | `LUNA MAX QA` consolidated M05 verification for the declared repair/acceptance scope. | The fully passing consolidated receipt is detailed below: rows `(a)`–`(i)` passed earlier and row `(j)` passed on rerun. | **Pass** for the declared M05 scope; exact receipt sessions, windows, native environments, artifacts, and reviewer are recorded below. `EXP-M05` is completed in the separate checkpoint below; commands and commits for this scoped receipt were not supplied. |

#### `R-M05-55` consolidated closure receipt

- **Status:** Completed for the declared M05 scope; **Pass**.
- **Owner/phase:** independent `LUNA MAX QA` consolidated M05 QA receipt; this documentation reconciliation records the supplied result and does not rerun implementation checks.
- **Dependencies verified:** M05 repair rows and the receipt retained at [`docs/evidence/ponytail-m05-boundary.txt`](docs/evidence/ponytail-m05-boundary.txt); the independent `R-M05-12` behavior rerun is recorded in row `(i)` below.
- **Change summary:** rows `(a)`–`(i)` were previously passed; row `(j)` was independently rerun and passed. No implementation, configuration, skill, or test path was changed by this documentation update.

| Evidence ID | Requirement/check | Environment, UTC time, commit | Result, artifact, reviewer, limitation |
| --- | --- | --- | --- |
| `R-M05-55 (a)`–`(i)` | Round trip/checksum (`06:42:38Z`–`06:42:39Z`); six-path pre-migration forced-failure matrix (`06:32:09Z`–`06:32:10Z`); due-check `60`/`2678400` accepted and `59`/`2678401`/`nan` rejected; retention of `32` artifacts/`256 MiB` with history preserved (`06:43:54Z`); `13/13` fail-closed negatives (`06:35:29Z`–`06:35:32Z`); key lifecycle with rollback (`06:44:37Z`); `7/7` watchdog probes (`06:35:01Z`–`06:35:02Z`); both-direction **emulated ARM64** cross-architecture restore (`06:25:04Z`–`06:28:44Z`, artifact `test-results/arm64/M05-20260912T034933Z/evidence.json`); and the `R-M05-12` rerun (`06:38:47Z`–`06:38:49Z`). | Session `ses_f6bbd6b46ffes2BM2zVjBC5uLg`; native x86_64 with `.dev-venv` Python `3.11.15`; overall UTC window `2026-09-12T06:25:04Z`–`2026-09-12T06:44:37Z`; command and commit were not supplied. | **Pass**; reviewer `LUNA MAX QA`. Row `(i)` includes the `R-M05-12` `4/4` behavior-test rerun. The receipt retained at [`docs/evidence/ponytail-m05-boundary.txt`](docs/evidence/ponytail-m05-boundary.txt) remains overengineering-only. No native ARM64 or performance result is inferred. |
| `R-M05-55 (j)` | Independent consolidated rerun: `276` non-live tests, `4` live tests deselected, `89.51%` coverage, documentation validation of `8` categories/`11` topics/`1` skill, `22` documentation tests, a `77`-file comment audit, Ruff, and mypy. | Session `ses_f6aa32b01ffexjSm9OhpprFwq4`; native x86_64 with `.dev-venv` Python `3.11.15`; UTC window `2026-09-12T11:26:29Z`–`2026-09-12T11:28:26Z`; command and commit were not supplied. | **Pass**; reviewer `LUNA MAX QA`. This is scoped M05 evidence, not the `EXP-M05` checkpoint. |
| `R-M05-55` packaged-CLI verification | Wheel install in a fresh venv; migrate pre-migration backup; named backup; verify; `restore --promote`; wrong-key and tampered rejection; backup-key rotate/retire; serve readiness on an isolated port. | Session `ses_f6a96daceffegfAqyKQL2lf3bS`; native x86_64/Python `3.11.15`; artifact `/tmp/opencode/stock-probs-m05-cli-20260912T114105Z/M05-packaged-cli-receipt.json`; command, UTC window, and commit were not supplied. | **Pass as supplied packaged-CLI verification evidence**; reviewer `LUNA MAX QA`; it supplements the independent `R-M05-55` receipt and does not create `EXP-M05`. |

The earlier failures and pending states in the historical repair narrative remain visible;
this later receipt closes the declared M05 scope without backdating or erasing that history.

The M05 automation inventory is implementation evidence, not acceptance: `migrate` creates
and verifies a pre-migration backup; `serve` performs a fail-closed due check using
`STOCK_PROBS_BACKUP_INTERVAL_SECONDS` with default `86400` and bounds `60`–`2678400`;
`backup-key rotate` and `backup-key retire` are present; retention is bounded at `32`
artifacts and `256 MiB`; and query history is never automatically expired. The authored
pages `docs/operations/backup-restore.md` and `docs/configure/local-configuration.md`
were updated for accuracy by `SOL HIGH`. The current `LUNA MAX docs` profile cannot edit
`docs/**`, so those repairs were performed by `SOL HIGH`; this profile gap remains visible
and does not supply independent documentation or M05 verification.

#### `EXP-M05` completed export checkpoint

- **Status:** Completed.
- **Owner/phase:** coordinator export/checkpoint gate; reviewer `LUNA MAX QA`.
- **Dependencies verified:** M05 declared scope and independent `R-M05-55` closure; earlier failures and pending states remain historical evidence.
- **Change summary:** The sanitized full-session `SESSION-EXPORT.md` received the supplied export audit, secret review, commit, push, and exact remote-main verification. This documentation reconciliation did not edit the export or implementation/configuration/skill/test paths.
- **Evidence ledger:**

  | Evidence ID | Requirement/check | Environment, UTC time, commit | Result, artifact, reviewer, limitation |
  | --- | --- | --- | --- |
  | `EXP-M05-E1` | Parse/inventory the sanitized full-session export: `233` messages, `1,387` parts, `432` tool parts, `185` task outputs, `1,116,276` bytes, `32,915` lines, SHA-256 `ce5f025d41c4757dcf95a336555ce0fdd46ddcf22d1e9bce68d2d8fb5328c181`, and `3,090` redaction markers | Supplied export audit receipt; commit `9be15a3ae60b16e7cc7a5b95653f914b578e1a61`, parent `59534faf1cdce493bc51a11d4adbea5e5b2d6892`, commit UTC `2026-09-12T12:41:32Z` | **Pass**; artifact: sanitized `SESSION-EXPORT.md`; reviewer `LUNA MAX QA`; export session ID and command were not supplied. |
  | `EXP-M05-E2` | Full secret review across all canonical secret patterns | Same supplied receipt and checkpoint commit | **Pass**; zero matches; artifact: export audit; reviewer `LUNA MAX QA`. |
  | `EXP-M05-E3` | Commit message, parent, push, and exact remote `main` match | Commit `9be15a3ae60b16e7cc7a5b95653f914b578e1a61`; parent `59534faf1cdce493bc51a11d4adbea5e5b2d6892`; commit UTC `2026-09-12T12:41:32Z`; message `Add verified backup operations` | **Pass**; exact `origin/main` match; artifact: Git checkpoint receipt; reviewer `LUNA MAX QA`. |

- **Repair/history:** The completed export checkpoint does not erase earlier M05 failures or pending states; `R-M05-55` remains the independent behavior/operations closure receipt and `EXP-M05` is the separate export gate.
- **Limitations:** The supplied receipt does not provide an export session ID, command, separate export-audit UTC window, or additional check; none is inferred. No external/hosted pipeline result is claimed.
- **Export/Git:** exact checkpoint `9be15a3ae60b16e7cc7a5b95653f914b578e1a61`, parent `59534faf1cdce493bc51a11d4adbea5e5b2d6892`, message `Add verified backup operations`, commit UTC `2026-09-12T12:41:32Z`, and exact `origin/main` match; reviewer `LUNA MAX QA`.

#### M08 preparation evidence (not M08 acceptance)

`M08` remains **Pending**. The supplied capture-harness receipt reports `20` annotated
screenshots and manifest SHA-256
`f9fef2b2db0a806cc47ff1db82e1e895f4dd4803425c0cf74426f5fa5a12dd5d`. This is reusable
preparation evidence only: no M08 QA, retrospective, Astra review, `EXP-M08`, or final
walkthrough acceptance is claimed. The generated capture output is not present in this
worktree for a local hash recheck; the supplied receipt's exact UTC, commit, command, and
named reviewer were not provided.

### M06 - Local QA, Playwright MCP, Browser Regressions, And Fail-Closed Gates

- **Status:** In progress.
- **Dependencies:** M01, M02, M03, M04, and M05.
- **Evidence state:** The historical `R-M06-1` independent retest was cancelled and remains visible. Current independent scoped results are **Pass** for `R-M06-2`, `R-M06-3`, `R-M06-4`, `R-M06-16`–`R-M06-20`, and `R-M06-11`, which passed twice, each with three hash-stable native runs and exact recomputation. The documentation-skill post-restart receipt also passed its listed checks. The scoped `R-M06-55` gate passed. M06 itself remains **In progress** pending a clean target-commit gate run, the final consolidated gate rerun, docs/release reconciliation, and `EXP-M06`; the dirty gate receipt is not a clean release checkpoint.
- **Build wave:** `SOL HIGH-A` local API gate integration; `SOL HIGH-B` deterministic fixtures/resource/restore gate integration; `SOL HIGH-C` Playwright MCP/browser/operations and local-gate integration. No shared paths during the wave.
- **Gates:** wait for all builder reports, then independent `LUNA MAX QA` and `LUNA MAX docs`; export `EXP-M06` only after required gates pass or every limitation is explicitly recorded.
- **Scope:** Configure the official `@playwright/mcp` headless tool for local agent QA, check in automated browser regressions, remove any remaining `.github/workflows/ci.yml`, and establish fail-closed local Make/scripts for static checks where adopted, unit/API tests, accessibility, security/export safety, resource limits, migration, and backup/restore. The scope also includes the three additional Ingenium configuration/documentation rows recorded below.
- **Acceptance evidence:** [x] `R-M06-55` records the official MCP application interaction, native package/runtime checks, browser regression gate, and explicitly labelled emulated-ARM64 package/runtime run; [x] `R-M06-4` independently retests CSV formula safety; [x] the required native-x86 performance/UI rows have structured results below; [x] physical/native ARM64 performance is explicitly `Unavailable`; [x] the documentation-skill post-restart receipt records canonical-description discovery, six registered Ponytail commands, three loaded profiles, valid configuration, and no credentials; [ ] actual screen-reader/assistive-technology evidence remains `Unavailable`; [ ] final consolidated QA/docs and `EXP-M06` remain open. Cross-architecture backup/key lifecycle closure, any deliberate-failure sub-receipt not named in the current M06 evidence, Ponytail closure, and Ingenium onboarding are not promoted beyond their row-level states below.
- **Verification:** `R-M06-55` ran `./scripts/local-gate.sh m06` on native x86_64 Linux and retained the package, browser, MCP, emulated-ARM64, Python, and performance artifacts. The independent scoped rows and their limitations are recorded in the register below. The post-restart receipt is session `ses_f6aa32d33ffeAvmiFK8K7Cd8EI`, `2026-09-12T11:35:58Z`–`2026-09-12T11:36:02Z`, native x86_64/OpenCode `1.18.30`, dirty commit `59534faf1cdce493bc51a11d4adbea5e5b2d6892`; it passed canonical-description discovery, six registered Ponytail commands, three loaded profiles, valid configuration, and no credentials. `.dev-venv/bin/python scripts/validate_docs.py` **Pass** for `8` categories and `11` topics at `2026-09-12T12:13:23Z`. Command/artifact/reviewer fields not supplied for the post-restart receipt remain unavailable; a missing workspace credential, screen-reader run, or physical ARM64 performance result remains unavailable rather than inferred.
- **Repair record:** Record each failed check as `R-M06-<n>` with failing evidence and rerun result.
- **Post-milestone gate:** `EXP-M06` must include local command/output evidence, browser/MCP artifacts, secret-review result, pushed revision, Git remote branch/revision verification, and every unavailable ARM64 performance field; no external pipeline is recorded.

#### M06 independent scoped retests and gate receipt

The following rows are current evidence, not a milestone-release claim. The exact
independent row receipts for `R-M06-2`, `R-M06-3`, `R-M06-4`, `R-M06-11`, and
`R-M06-16`–`R-M06-20` were supplied as the M06 reconciliation. The latter rows now
carry row-only line locators and cross-links to the receipts retained at `docs/evidence`;
the shared locators do not invent a separate execution session or artifact.

| Task ID | Status | Requirement/check | Exact evidence and environment | Result, artifact, reviewer, limitation |
| --- | --- | --- | --- | --- |
| `R-M06-2` | **Completed** | Occupied-port fail-closed behavior | Independent retest supplied for this exact row; the later M06 receipt ran on dirty native x86_64 Linux, revision `59534faf1cdce493bc51a11d4adbea5e5b2d6892` | **Pass**; final gate artifact set `test-results/local-gates/R-M06-55-20260912T045233Z/`; reviewer `LUNA MAX QA`; separate row-only session/UTC/artifact was not supplied. |
| `R-M06-3` | **Completed** | CSP/host/origin enforcement | Independent retest supplied for this exact row; same dirty native x86_64 M06 receipt and revision as `R-M06-55` | **Pass**; final gate artifact set `test-results/local-gates/R-M06-55-20260912T045233Z/`; reviewer `LUNA MAX QA`; separate row-only session/UTC/artifact was not supplied. |
| `R-M06-4` | **Completed** | CSV formula safety | Independent retest supplied for this exact row; same dirty native x86_64 M06 receipt and revision as `R-M06-55` | **Pass**; final gate artifact set `test-results/local-gates/R-M06-55-20260912T045233Z/`; reviewer `LUNA MAX QA`; separate row-only session/UTC/artifact was not supplied. |
| `R-M06-11` | **Completed** | Exact idle-CPU recomputation | Two independent QA passes each used three hash-stable native runs and independently verified the exact recomputation | **Pass**; the supplied reconciliation did not provide the row-only hash bundle, session ID, or UTC window, so no hash value or locator is invented; named M06 gate reviewer: `LUNA MAX QA`. |
| <a id="r-m06-16"></a>`R-M06-16` | **Completed** | M06 scoped row as named by the supplied independent receipt | Row-only locator: [`ponytail-reviews.md#L13-L17`](docs/evidence/ponytail-reviews.md#L13-L17); source receipt: [`ponytail-r-m06-1.txt#L4-L6`](docs/evidence/ponytail-r-m06-1.txt#L4-L6). The retained summary maps this receipt to an independent pass but does not name a finer behavior. | **Pass** for the supplied scope only; the shared final-gate artifact set is `test-results/local-gates/R-M06-55-20260912T045233Z/`; reviewer `LUNA MAX QA`; no finer behavior claim is made. |
| <a id="r-m06-17"></a>`R-M06-17` | **Completed** | M06 scoped row as named by the supplied independent receipt | Row-only locator: [`ponytail-reviews.md#L13-L17`](docs/evidence/ponytail-reviews.md#L13-L17); source receipt: [`ponytail-r-m06-1.txt#L4-L6`](docs/evidence/ponytail-r-m06-1.txt#L4-L6). The retained summary maps this receipt to an independent pass but does not name a finer behavior. | **Pass** for the supplied scope only; the shared final-gate artifact set is `test-results/local-gates/R-M06-55-20260912T045233Z/`; reviewer `LUNA MAX QA`; no finer behavior claim is made. |
| <a id="r-m06-18"></a>`R-M06-18` | **Completed** | M06 scoped row as named by the supplied independent receipt | Row-only locator: [`ponytail-reviews.md#L13-L17`](docs/evidence/ponytail-reviews.md#L13-L17); source receipt: [`ponytail-r-m06-1.txt#L4-L6`](docs/evidence/ponytail-r-m06-1.txt#L4-L6). The retained summary maps this receipt to an independent pass but does not name a finer behavior. | **Pass** for the supplied scope only; the shared final-gate artifact set is `test-results/local-gates/R-M06-55-20260912T045233Z/`; reviewer `LUNA MAX QA`; no finer behavior claim is made. |
| <a id="r-m06-19"></a>`R-M06-19` | **Completed** | Closure of the three findings from the `R-M06-15` Ponytail boundary | Row-only locator: [`ponytail-reviews.md#L18-L20`](docs/evidence/ponytail-reviews.md#L18-L20); source receipt: [`ponytail-r-m06-15.txt#L4-L6`](docs/evidence/ponytail-r-m06-15.txt#L4-L6). | **Pass** for the scoped repair; the receipt retained at `docs/evidence/ponytail-r-m06-15.txt` and shared final-gate result remain overengineering-only; reviewer `LUNA MAX QA`. |
| <a id="r-m06-20"></a>`R-M06-20` | **Completed** | M06 scoped row as named by the supplied independent receipt | Row-only locator: [`ponytail-reviews.md#L13-L17`](docs/evidence/ponytail-reviews.md#L13-L17); the retained summary explicitly records a supplied scoped pass but no finding mapping. | **Pass** for the supplied scope only; the shared final-gate artifact set is `test-results/local-gates/R-M06-55-20260912T045233Z/`; reviewer `LUNA MAX QA`; no finer behavior claim is made. |
| `R-M06-55` | **Completed** | Consolidated local `m06` gate for its declared scope | Dirty native x86_64 Linux WSL2, Python `3.11.15`, revision `59534faf1cdce493bc51a11d4adbea5e5b2d6892`; `2026-09-12T04:52:33Z`–`2026-09-12T05:03:44Z`; command `./scripts/local-gate.sh m06` | **Pass**; `264` tests, `89.38%` coverage, 32 browser passes/2 performance-profile skips, official MCP, 4/4 live Yahoo checks, and labelled emulated-ARM64 package/runtime evidence. Artifact `test-results/local-gates/R-M06-55-20260912T045233Z/evidence.json`; reviewer `LUNA MAX QA`. Dirty worktree means this is not the `EXP-M06` checkpoint. |

`R-M06-55`'s performance summary is
`test-results/local-gates/R-M06-55-20260912T045233Z/performance/summary.json`:
all 13 required row artifacts are present, `12/13` rows are **Pass**, the sole
architecture row is **Unavailable**, and the summary reviewer is `LUNA MAX QA`.
The emulated package/runtime receipt is
`test-results/local-gates/R-M06-55-20260912T045233Z/arm64/evidence.json`; it is
explicitly emulated ARM64 via QEMU/OCI and cannot provide ARM64 performance evidence.

#### M06 retained Ponytail boundary records

These records are evidence of the overengineering-only review and repair history;
they do not substitute for correctness, security, accessibility, performance, or
the M06 export gate.

| Boundary | Retained artifact | Exact finding/repair state | Verification state |
| --- | --- | --- | --- |
| `R-M06-1` | [`docs/evidence/ponytail-r-m06-1.txt`](docs/evidence/ponytail-r-m06-1.txt) | Six Ponytail findings were recorded and repaired. | The receipt retained at `docs/evidence/ponytail-r-m06-1.txt` is overengineering-only; its mapped scoped rows `R-M06-16`–`R-M06-18` are independently **Pass** above. |
| `R-M06-15` | [`docs/evidence/ponytail-r-m06-15.txt`](docs/evidence/ponytail-r-m06-15.txt) | Three findings were recorded and repaired as `R-M06-19`. | `R-M06-19` is independently **Pass** above; the receipt retained at `docs/evidence/ponytail-r-m06-15.txt` remains overengineering-only. |
| `M05` | [`docs/evidence/ponytail-m05-boundary.txt`](docs/evidence/ponytail-m05-boundary.txt) | Two findings were recorded and repaired as completed repair record `R-M05-12`. | The independent `4/4` behavior rerun is **Pass** inside `R-M05-55 (i)`; the receipt retained at `docs/evidence/ponytail-m05-boundary.txt` remains overengineering-only. |

#### M06 consolidated gate limitations and additional rows

| Row | Status | Exact evidence and current verification state |
| --- | --- | --- |
| Actual screen-reader/assistive-technology evidence (`R-M04-30`) | **Pending** | **Unavailable**. No actual screen-reader run is supplied; axe, keyboard, MCP, and browser results do not substitute. This remains a final accessibility/release limitation. |
| Documentation taxonomy and project documentation skill | **Completed** for the listed validation scope | The skill was created under `.opencode/skills/documentation`. Fresh isolated discovery passed the validator, 20 tests, description parity, the 500-line limit, and all required references. The post-restart receipt is session `ses_f6aa32d33ffeAvmiFK8K7Cd8EI`, `2026-09-12T11:35:58Z`–`2026-09-12T11:36:02Z`, native x86_64/OpenCode `1.18.30`, dirty commit `59534faf1cdce493bc51a11d4adbea5e5b2d6892`; canonical-description discovery, six registered Ponytail commands, three loaded profiles, valid configuration, and no credentials all passed. `.dev-venv/bin/python scripts/validate_docs.py` **Pass** for `8` categories and `11` topics at `2026-09-12T12:13:23Z`. |
| Ingenium MCP onboarding | **Blocked** | The restart precondition is satisfied by the receipt above. Remaining blockers only: authorized workspace credentials, project registration, repository-sync dry-run/apply/no-drift, and credential-free evidence. No credential, endpoint, or token is recorded; none of those onboarding checks is claimed. |
| Native/physical ARM64 performance | **Unavailable** | `R-M06-55`'s `performance/arm64-performance-limitation.json` records native ARM64 unavailable, zero performance samples, and no inference from emulation. |

`EXP-M06` is **Pending**. This documentation reconciliation did not export,
secret-review, commit, push, or verify a remote revision. `R-M06-55` is a dirty
worktree gate receipt, not an export checkpoint; final consolidated QA/docs must
consume the row-level states above before `EXP-M06` can be recorded.

#### M06 mandatory deterministic native-x86 app/UI performance evidence

These are acceptance rows inside `M06`; `R-M06-55` independently verified the
structured native-x86 receipt, while `M06` remains **In progress** pending final
consolidated QA/docs and `EXP-M06`. The run used native x86_64 Linux, a fresh isolated deterministic fixture
runtime, an exact commit, an isolated port and temporary directory, and a process that was
not warmed by an earlier check. The fixture identity, cache state, process tree, port,
temporary artifacts, start/end UTC, command, and cleanup result are part of every row. A
dirty or reused runtime is not silently treated as fresh evidence.

The existing contract thresholds are deliberately separated from proposed executable
budgets:

| Threshold class | Existing contract or future distinction |
| --- | --- |
| Existing numeric thresholds | Process RSS `<500 MiB`; defined fixture/cache-hit forecast p95 `<1 s`; indexed 100,000-history query p95 `<250 ms`. |
| Existing qualitative threshold | Idle CPU must be `negligible`; the contract does not currently contain a numeric idle-CPU bound. |
| Proposed M06 protocol/budgets | Five warmups plus at least 30 measured requests; 60 seconds idle CPU at `<=1 core-percent`; readiness within `20 s`; package/build and backup/restore baselines and bounds; static shell/assets `<96 KiB`; a designated response `<8 KiB`; and pinned browser render/interaction/layout/request budgets. These are proposed executable additions, not current passes. |

Each row below has task ID `M06`. The final structured artifacts are under
`test-results/local-gates/R-M06-55-20260912T045233Z/performance/` from `R-M06-55`,
native x86_64 Linux WSL2/Python `3.11.15`, dirty revision
`59534faf1cdce493bc51a11d4adbea5e5b2d6892`, command `./scripts/local-gate.sh m06`,
`2026-09-12T04:52:33Z`–`2026-09-12T05:03:44Z`. Every row names `LUNA MAX QA` as
reviewer in its JSON artifact. The 12 native-x86 rows are **Pass**; the ARM64
performance limitation row is **Unavailable**.

The final measured receipt reports process RSS p95 `139,685,888` bytes, fixture/cache-hit
forecast p95 `121.225 ms`, indexed 100,000-history p95 `3.233 ms`, readiness
`2,433.622 ms`, idle CPU mean `0.1332848089 core-percent`, static total `91,708` raw
bytes, designated response `58` raw bytes, browser render p95 `138.681 ms`, and browser
interaction p95 `21.842 ms`. These values are row evidence, not a release checkpoint.

| Task ID | Threshold class | Mandatory future acceptance/evidence row | Required protocol and structured artifact | Current result |
| --- | --- | --- | --- | --- |
| `M06` | Proposed protocol | Fresh isolated fixture runtime | Start a new app process with the deterministic fixture, isolated port and temp directory; record fixture/cache identity, process tree, CPU architecture, Python/runtime, commit, and cleanup. | **Pass**; `runtime-isolation.json`; reviewer `LUNA MAX QA`. |
| `M06` | Proposed protocol | Five warmups plus `>=30` measured requests | Exclude at least five warmups, then record at least 30 raw measured requests for each designated workload and declared concurrency level. | **Pass**; `sample-protocol.json`; 5 warmups/30 samples per designated workload; reviewer `LUNA MAX QA`. |
| `M06` | Existing numeric threshold | Process RSS `<500 MiB` | Measure peak isolated app/runtime RSS and retain raw samples, units, method, and scope. | **Pass**; `process-rss.json`; p95 `139,685,888` bytes; reviewer `LUNA MAX QA`. |
| `M06` | Existing numeric threshold | Defined fixture/cache-hit forecast p95 `<1 s` | Report route, fixture, cache state, raw elapsed times, p50/p95/max, and errors. | **Pass**; `fixture-cache-hit-forecast.json`; p50/p95/max `73.753/121.225/131.923 ms`; reviewer `LUNA MAX QA`. |
| `M06` | Existing numeric threshold | Indexed 100,000-history query p95 `<250 ms` with `>=10` repetitions and an index plan | Record exact fixture, index/query plan, repetitions, raw timings, and p50/p95/max. | **Pass**; `indexed-100k-history-query.json`; p50/p95/max `2.671/3.233/3.567 ms`; reviewer `LUNA MAX QA`. |
| `M06` | Proposed numeric threshold | 60-second idle CPU `<=1 core-percent` | Record 60 seconds of raw CPU samples, interval, process scope, normalization, and max; proposed bound applies to mean normalized CPU. | **Pass**; `idle-cpu.json`; mean/p95/max `0.1332848089/0.9996194349/0.9998222786 core-percent`; reviewer `LUNA MAX QA`. |
| `M06` | Proposed protocol/bound | Concurrency elapsed | Record declared concurrency levels, warmups, measured batches, p50/p95/max, errors, and peak RSS. | **Pass**; `concurrency-elapsed.json`; p50/p95/max `284.565/1003.099/1238.757 ms`; reviewer `LUNA MAX QA`. |
| `M06` | Proposed numeric threshold | Readiness within `20 s` | Record fresh process start, readiness command/timestamp, retries, and elapsed time. | **Pass**; `readiness.json`; `2,433.622 ms`; raw connection-refused attempts remain in the artifact; reviewer `LUNA MAX QA`. |
| `M06` | Proposed baseline/bound | Package size and clean build time | Record package bytes, clean isolated build time, tool/runtime, and baseline/bound. | **Pass**; `package-size-build-time.json`; `112,983` bytes/`944.726 ms`; reviewer `LUNA MAX QA`. |
| `M06` | Proposed baseline/bound | Backup and restore duration and bounds | Record representative fixture bytes, backup/restore time, RSS, verification, and bounds. | **Pass**; `backup-restore-duration.json`; p50/p95/max `1975.554/2545.148/2545.148 ms`; reviewer `LUNA MAX QA`. |
| `M06` | Proposed numeric thresholds | Static shell/assets `<96 KiB` and designated response `<8 KiB` | Record raw byte semantics, every file/response, compression, and strict bounds. | **Pass**; `static-and-response-bytes.json`; `91,708` static bytes/`58` response bytes; reviewer `LUNA MAX QA`. |
| `M06` | Proposed browser budgets | Render, interaction, layout, and request budgets | Record pinned manifest, raw traces, timings, requests, viewport, and console result. | **Pass**; `browser-budgets.json`; render p95 `138.681 ms`, interaction p95 `21.842 ms`; reviewer `LUNA MAX QA`. |
| `M06` | Evidence rule | One structured artifact per check | Each artifact records task/row, fixture/isolation, native environment, revision, UTC, command, samples, raw data, classification, result, limitation, path, and reviewer. | **Pass**; `performance/summary.json` has all 13 rows, no missing/nonpassing rows, and reviewer `LUNA MAX QA`; 12 rows Pass/1 Unavailable. |
| `M06` | Architecture limitation | ARM64 performance field | Native/physical ARM64 performance only; emulation cannot satisfy this row. | **Unavailable**; `arm64-performance-limitation.json` records no native ARM64 and zero performance samples; no ARM64 resource result is inferred. |

The performance gate fails closed: missing warmups, measured samples, clean fixture,
index plan, baseline, bound, raw data, artifact, exact commit/time, or named independent
reviewer is not a pass. The M06 performance artifacts are not an aggregate dashboard
claim; `LUNA MAX QA` must independently review every row after the required pre-QA
`/ponytail-review` boundary gate. No emulated ARM64 result can satisfy any performance
row.

#### M06 additional Ingenium configuration/documentation rows

These rows remain within `M06`; they do not allocate new milestone, repair, or export
IDs. `M06` remains **In progress**, and the rows below are not current completion claims.

| Task ID | Row status | Owner/phase | Preconditions and required check | Current evidence result and limitation |
| --- | --- | --- | --- | --- |
| `M06` | **In progress** | `LUNA MAX docs` records the row; `SOL HIGH` owns any repair; `LUNA MAX QA` independently retests | The pinned Ingenium Ponytail closure is vendored at `tools/ponytail` from upstream `16f29800fd2681bdf24f3eb4ccffe38be3baec6b`, configured in `opencode.json`, and the retained reports are [`docs/evidence/ponytail-r-m06-1.txt`](docs/evidence/ponytail-r-m06-1.txt) (six findings repaired), [`docs/evidence/ponytail-r-m06-15.txt`](docs/evidence/ponytail-r-m06-15.txt) (three findings repaired as `R-M06-19`), and [`docs/evidence/ponytail-m05-boundary.txt`](docs/evidence/ponytail-m05-boundary.txt) (two findings repaired as completed repair record `R-M05-12`, independently rerun `4/4` inside `R-M05-55 (i)`). | **Unavailable** for full M06 acceptance: `R-M06-19` is independently **Pass**, but Ponytail remains overengineering-only and its overall closure/launcher-reliability state is not a correctness, security, accessibility, or performance pass. |
| `M06` | **Completed** for the listed validation scope | `LUNA MAX docs` plus post-restart validation | The authored documentation taxonomy and project documentation skill are implemented under `docs/**` and `.opencode/skills/documentation`. Fresh isolated discovery passed the validator, 20 tests, description parity, the 500-line limit, and all required references. Receipt: session `ses_f6aa32d33ffeAvmiFK8K7Cd8EI`, `2026-09-12T11:35:58Z`–`2026-09-12T11:36:02Z`, native x86_64/OpenCode `1.18.30`, dirty commit `59534faf1cdce493bc51a11d4adbea5e5b2d6892`; canonical description, six registered Ponytail commands, three loaded profiles, valid configuration, and no credentials all passed. `.dev-venv/bin/python scripts/validate_docs.py` **Pass** for `8` categories and `11` topics at `2026-09-12T12:13:23Z`. |
| `M06` | **Blocked** | `LUNA MAX docs` records credential-free onboarding; independent QA verifies it | Restart precondition is satisfied. Remaining required checks are authorized workspace credentials, project registration, repository-sync dry-run/apply/no-drift, and credential-free evidence. | **Blocked** only on those remaining onboarding checks; no credential, endpoint, or token value is recorded, and no onboarding pass is claimed. |

The exact environment, UTC timestamp, commit, command, result, artifact/link, repair
history, limitation, export/revision, and named reviewer remain required when these
rows are actually run. The restart precondition is evidenced in the validation row;
any remaining missing precondition stays visible and cannot be replaced by an
implementation claim.

#### M06 Ingenium research evidence (not acceptance)

Three completed read-only Ingenium studies informed the documentation architecture and
the rows above. Their session IDs are research locators only and do not substitute for
M06 acceptance, QA, a restart, authorized workspace access, or an export checkpoint:

- `ses_f6d4726a7ffeW18Cuf8Hl86PNs`
- `ses_f6d47256cffert6bjT4wan4xvZ`
- `ses_f6d4724b1ffeC2gGE0kc5AgPo2`

The supplied deep read-only Ingenium research sessions
`ses_f6d219e22ffeQuT1z7fdC3e4MA`, `ses_f6d219dddffeyB2ZTOmnUMJU3Z`, and
`ses_f6d219d92ffewot26Lkx216Lqw` are also design evidence only. Their useful conventions
are recorded as policy below; implementation behavior still requires the independent M06
rows and no session is a pass, restart receipt, skill validation, or export checkpoint.

| Ingenium convention | Documentation disposition | Independent implementation/evidence state |
| --- | --- | --- |
| Deny-by-default least privilege | Adopted in ownership, credential, and permission policy. | M06 credential-file binding and onboarding remain **Blocked** only on authorized workspace credentials, project registration, repository-sync dry-run/apply/no-drift, and credential-free evidence. |
| Source-versus-live evidence separation | Adopted in every ledger: historical/source reports never become current live acceptance. | `R-M06-55` names the live native-x86 environment, dirty commit, UTC window, artifacts, and reviewer; its scoped result does not close M06 or `EXP-M06`. |
| Structured sanitized errors | Adopted as the API/product contract and export-safety rule. | QA must independently exercise safe error shapes and secret review; no new pass is inferred here. |
| Deterministic browser containment with no hidden retries | Adopted for fixture/browser gates, readiness, and failure recording. | M06/M07 must record the declared fixture, requests, retries, and failures; hidden retry success is not evidence. |
| Bounded process, port, and temporary artifacts | Adopted as the isolation and cleanup requirement for performance and local gates. | `R-M06-55` records process/port/temp bounds and cleanup per structured performance artifact; ARM64 performance remains **Unavailable**. |
| Migration, package, and resource checks | Adopted as explicit local-gate acceptance rows, including package/build/resource artifacts. | M06 independent QA must verify each row; generated files or builder claims do not pass it. |
| Optional read-only integrity diagnostic | Permitted only as a read-only diagnostic and never as a new acceptance surface. | No diagnostic result is claimed or required by this reconciliation. |

The research does not authorize overengineering. Absent a demonstrated requirement, the
contract still rejects added auth, MFA, gateway, multi-service split, dual-database restore,
direct-route SQL, and replica rate limiting. The authored documentation taxonomy and project
documentation skill are implemented under `docs/**` and `.opencode/skills/documentation`;
fresh isolated discovery passed the validator, 20 tests, description parity, 500-line limit,
and required references. The post-restart receipt is session
`ses_f6aa32d33ffeAvmiFK8K7Cd8EI` at `2026-09-12T11:35:58Z`–
`2026-09-12T11:36:02Z`, native x86_64/OpenCode `1.18.30`, dirty commit
`59534faf1cdce493bc51a11d4adbea5e5b2d6892`; it passed canonical-description discovery,
six Ponytail commands, three profiles, valid configuration, and no-credential checks.
`.dev-venv/bin/python scripts/validate_docs.py` **Pass** for `8` categories and
`11` topics at `2026-09-12T12:13:23Z`.

### M09 - Dark Mode And News

- **Status:** Pending.
- **Dependencies:** `M06` and its required `EXP-M06` checkpoint, which is currently pending. `M07` cannot begin its integrated acceptance until M09 and `EXP-M09` are complete.
- **Owner/phase:** The ASTRA research-based plan is recorded here; `SOL HIGH` implements the documented scope after the dependency gate, then `LUNA MAX QA` and `LUNA MAX docs` independently verify it. `EXP-M09` is the separate export/checkpoint gate. No M09 implementation, QA/docs, or export pass is claimed here.
- **Scope:** Add the contract-bound dashboard/API-docs dark mode and a clearly labelled selected-instrument news view. News must use the FastAPI `/api/v1` boundary, preserve instrument identity and source/as-of provenance, and represent all ten documented UI states honestly. The final UI, M08 walkthrough, and `ASTRA-FINAL` matrix must include both features.
- **Explicitly rejected scope (ASTRA plan):** Settings database, news archive, article scraper/proxy, sentiment engine, forecast/model/probability changes, Redis or external cache, background scheduler, service worker, separate service, notification feed, full-text search, watchlist, personalized ranking, and any additional market-data provider remain out of scope unless a new evidenced requirement is approved. No current M09 task authorizes or accepts one of these additions.
- **Planning limitation:** The separate ASTRA research first pass remains **Blocked** by the external-directory permission boundary; this M09 planning state is not a research receipt or `ASTRA-FINAL` acceptance. No implementation result is inferred.
- **Acceptance evidence:** [ ] every row in the M09 ledger below has an independent `LUNA MAX QA`/`LUNA MAX docs` receipt; [ ] native x86-64 evidence and any local ARM64 functional/build/tool evidence are labelled native or emulated; [ ] the shipped behavior and limitations are reconciled into README, AGENTS, M07, M08, and the Astra handoff. A test file, source inspection, generated artifact, or builder claim alone is not acceptance.
- **Repair record:** Record each M09 implementation, accessibility, stale-data, API-boundary, responsive, or documentation failure as `R-M09-<n>`; no missing evidence is silently accepted.

#### M09 dark-mode contract

The theme initializer is an external static asset, not inline JavaScript. A parser-blocking
`theme.js` script must run in the document head before CSS is applied on both the dashboard
and `/api/v1/docs`. It reads a localStorage light/dark preference, falls back to the system
`prefers-color-scheme` value when no override exists, and reset-to-system removes the stored
override. The first styled paint must already use the selected/system theme; a flash of the
other theme is a failure.

Theme CSS uses semantic roles for surfaces, text, borders, focus, status, and chart marks;
whole-page inversion is not acceptable. Independent checks must establish text contrast of
`>=4.5:1`, large text/controls/chart marks of `>=3:1`, and focus indication of `>=3:1`.
Forced-colors behavior, reduced-motion behavior, and print output are separate acceptance
rows. Strict CSP is unchanged: no inline script/style, `unsafe-eval`, or newly permitted
origin is introduced. Both the dashboard and `/api/v1/docs` must receive the same preference,
no-flash, semantic-role, contrast, and fallback/reset treatment.

#### M09 news contract

The route is exactly `GET /api/v1/news?symbol=<normalized>&limit=5`. `limit` defaults to
`5` and accepts only `1`–`10`; symbols are normalized before lookup. The response and item
schemas are closed (unknown fields are rejected), with only the documented identity,
headline, source, as-of/publication, URL, and `cache_state` data. The browser calls only
this local API; it never imports SQLite or calls Yahoo Finance.

HTTP semantics are explicit: `200` means fresh, empty, or stale fallback; `422` means
invalid input; `502` means provider failure; and `503` means capacity busy. An empty news
response is valid and must never return `404`. Partial metadata is rendered honestly from
the known fields without fabricated values. A local service unreachable condition has no
HTTP response, and an instrument changed/request superseded condition must not render a
response under the wrong instrument.

News retrieval is a separate provider operation named `fetch_news`, not a forecast/provider
side effect. A pinned `yfinance==1.7.0` feasibility proof is required before the news
package/launch gate can pass. The proof must cover the pinned install and provider API shape,
bounded retrieval, response mapping, and safe HTTPS links; a package declaration is not the
proof. If the proof fails or is unavailable, M09 remains blocked, `R-M09-1` records the
root cause and rerun, and no unpinned replacement is accepted.

The cache is ephemeral and in memory only: a non-empty successful result is fresh for
5 minutes and may be served as stale fallback for no more than 30 minutes; empty results
are cached for 60 seconds; failures suppress another provider attempt for 30 seconds; no
more than 32 symbols, 32 KiB per entry, or 1 MiB aggregate may be retained; and only one
provider retrieval may be active at a time. The provider deadline is `<=10 s`, subject to
the pinned feasibility proof. API responses expose only `cache_state` `miss`, `hit`, or
`stale_fallback` as applicable.

News must not change storage, backups, model inputs/results, content fingerprints, or the
search/outcome ledger. Saved forecast reopen is provider-free and shows the immutable
recorded result; a separately labelled current-headlines action is the only saved-result
path that requests current news. Every displayed link must be safe HTTPS, and all browser
application data traffic remains local-only (only the server-owned provider fetch may leave
the app for the declared Yahoo source).

The ten required news UI states are: (1) **not requested**, (2) **loading**, (3) **fresh**,
(4) **empty**, (5) **partial metadata**, (6) **stale cached with refresh failure**, (7)
**provider unavailable without cache**, (8) **local service unreachable**, (9) **capacity
busy**, and (10) **instrument changed/request superseded**. The first, second, third,
fourth, and sixth states must preserve the HTTP semantics above: fresh, empty, and stale
fallback are `200`; invalid input is `422`; provider failure is `502`; capacity busy is
`503`; and empty is never `404`. These are distinct walkthrough/browser rows even when
one control leads to several of them. Cache `hit` remains a cache-behavior check under
`M09-E6`, while saved forecast reopen/provider-free and the separately labelled
current-headlines action remain separate interaction checks, not additional states.

#### M09 lane manifest and conditional package gate

The three implementation lanes are disjoint; shared interfaces are handed off rather than
co-edited. The paths below are the exact M09 ownership boundary and are not changed by this
documentation update:

| Lane | Exact M09 paths | Handoff/acceptance boundary |
| --- | --- | --- |
| `SOL HIGH-A` transport/API | `src/stock_probs/api.py`, `src/stock_probs/schemas.py`, `src/stock_probs/config.py`, `tests/test_api.py` | Normalized route, closed schemas, validation/error envelope, cache/deadline configuration contract. |
| `SOL HIGH-B` provider/domain/service | `src/stock_probs/provider.py`, `src/stock_probs/domain.py`, `src/stock_probs/service.py`, `tests/test_provider.py`, `tests/test_domain.py` | `fetch_news`, identity/provenance, cache policy, persistence exclusion, and the pinned-package feasibility proof. |
| `SOL HIGH-C` presentation/browser | `src/stock_probs/static/theme.js`, `src/stock_probs/static/index.html`, `src/stock_probs/static/api-docs.html`, `src/stock_probs/static/app.js`, `src/stock_probs/static/app.css`, `tools/browser/playwright.config.js`, `tools/browser/tests/dashboard.spec.js` | No-flash theme/UI states, responsive/accessibility journeys, local-only network checks, and browser budgets. |

`pyproject.toml` and `requirements.lock` are conditional `SOL HIGH-B` package paths: they
may change only if the `yfinance==1.7.0` feasibility proof shows a pinned package change is
actually required. If the current pin is sufficient, they stay unchanged. A passing
conditional gate then includes clean install, package-resource/static-asset, loopback
launch, and local native or explicitly emulated ARM64 functional/build/tool checks; no
emulated ARM64 performance claim is allowed. The stock Playwright MCP entry remains hard:
retain `./scripts/playwright-mcp.sh` with `--headless`, `--isolated`, and loopback
host/origin allowlists.

#### M09 acceptance and quality rows

Each row has task ID `M09`; the `M09-E*` value is its evidence ID. Every future receipt must
also record the exact command, environment, UTC time, commit, result, artifact/link,
limitation, repair history, export/revision state, and named reviewer. All rows are currently
**Pending**; this documentation update performed no implementation or M09 QA.

| Evidence ID | Acceptance row | Required independent evidence | Current result |
| --- | --- | --- | --- |
| `M09-E1` | Parser-blocking theme bootstrap and no-flash first paint on dashboard and `/api/v1/docs`; localStorage light/dark, system fallback, and reset-to-system. | Browser trace at stored light/dark, system light/dark, missing/invalid preference, and reset; actual first-paint ordering. | **Pending**; not run. |
| `M09-E2` | Semantic theme roles and numeric contrast: text `>=4.5:1`, large text/controls/chart marks `>=3:1`, focus `>=3:1`; no whole-page inversion. | Computed-style/contrast checks and visual/browser evidence for dashboard and API docs. | **Pending**; not run. |
| `M09-E3` | Forced-colors, reduced-motion, print, strict CSP unchanged, and local-only browser traffic. | Forced-colors/reduced-motion/print checks, CSP/security inspection, console/network capture, and retained official MCP interaction. | **Pending**; not run. |
| `M09-E4` | `GET /api/v1/news?symbol=<normalized>&limit=5`, normalized identity, `1`–`10` limit validation, closed schemas, and HTTP semantics: `200` fresh/empty/stale fallback, `422` invalid input, `502` provider failure, `503` capacity busy, and no `404` for an empty response. | API positive/negative matrix, unknown-field rejection, safe structured errors, explicit fresh/empty/stale/provider/capacity responses, and OpenAPI/route inspection. | **Pending**; not run. |
| `M09-E5` | Separate `fetch_news` provider and pinned `yfinance==1.7.0` feasibility proof with `<=10 s` deadline. | Clean pinned install/package proof, fixture/provider mapping, bounded timeout, safe HTTPS URL checks, and no direct browser/provider path. | **Pending**; proof not supplied. |
| `M09-E6` | Ephemeral cache: 5-minute fresh TTL, 30-minute stale ceiling, 60-second empty cache, 30-second failure suppression, 32 symbols, 32 KiB entry, 1 MiB aggregate, one active retrieval, and `miss`/`hit`/`stale_fallback`. | Deterministic clock/concurrency/eviction/size/failure matrix with raw timings and response bytes. | **Pending**; not run. |
| `M09-E7` | No storage/backup/model/fingerprint/ledger changes; provider-free saved reopen; labelled current-headlines action; safe HTTPS links. | Persistence/backup/fingerprint/ledger diff checks, saved-reopen network trace, current-action trace, and URL allowlist tests. | **Pending**; not run. |
| `M09-E8` | Ten documented news UI states: not requested; loading; fresh; empty; partial metadata; stale cached with refresh failure; provider unavailable without cache; local service unreachable; capacity busy; instrument changed/request superseded. | Actual-control browser journeys with fixture data, accessible text/transcript for every state, and the required `200`/`422`/`502`/`503`/no-`404` semantics. | **Pending**; not run. |
| `M09-E9` | Responsive/accessibility quality across 360/390/768/1280/1440, keyboard/focus, actual assistive technology, and text equivalents. | Official headless MCP plus browser checks, separate actual screen-reader evidence, and no axe/keyboard substitution. | **Pending**; not run. |
| `M09-E10` | Proposed M09 budgets: theme switch p95 `<=100 ms`, news fixture p95 `<=100 ms`, ten-item render p95 `<=250 ms`, news response `<=32 KiB`, provider deadline `<=10 s` subject to proof. | Fresh isolated fixture runtime, warmups/measured samples, raw traces/bytes, p50/p95/max, and one structured artifact per check; native x86 performance only. | **Pending**; not run. |
| `M09-E11` | Static shell `<96 KiB` after M09 and justified eighth navigation request for external `theme.js`. | Re-measure every raw static asset and request on the target commit; compare with the existing `91,708`-byte baseline and retain any failure. | **Pending**; no M09 target-commit measurement. |
| `M09-E12` | Conditional package/launch and architecture scope, exact lane ownership, Playwright retention, and M07/M08/Astra documentation handoff. | Clean package/launch/local gate, native or labelled emulated ARM64 functional/build/tool receipt, path-scope review, and reconciled root docs. | **Pending**; no M09 build or QA receipt. |
| `M09-E13` | ASTRA rejected scope remains excluded: settings database, news archive, article scraper/proxy, sentiment engine, forecast/model/probability changes, Redis or external cache, background scheduler, service worker, separate service, notification feed, full-text search, watchlist, personalized ranking, and any additional market-data provider. | Final route/dependency/path inventory and independent absence review; any expansion must cite a newly approved evidenced requirement and task row. | **Pending**; no M09 implementation or scope audit has run. |

The existing M06 measurement is a baseline only: `91,708` raw static bytes against
`96 KiB = 98,304` bytes leaves `6,596` bytes (about `6.44 KiB`, approximately `6.6 KiB`)
of headroom before M09. The external parser-blocking `theme.js` intentionally adds a
justified eighth navigation request for no-flash behavior under strict CSP; both its bytes
and request must be counted. The proposed M09 budgets are additions to, not replacements
for, the existing M06 thresholds, and no M09 result is inferred from the dirty M06 receipt.

- **Verification:** `LUNA MAX QA` independently exercises the actual theme control, both document contexts, the API boundary, all ten news states, HTTP status semantics, cache/persistence exclusions, rejected-scope absence, responsive/accessibility behavior, and quality budgets; `LUNA MAX docs` consumes that completed record and reconciles the four root documents. Every failed, skipped, unavailable, stale, or unconfirmed row receives a unique `R-M09-<n>` repair and affected-check rerun.
- **Post-milestone gate:** After independent M09 QA/docs acceptance, `EXP-M09` must overwrite and review the full-session `SESSION-EXPORT.md`, complete secret review, commit and push the reviewed export, and verify the exact remote revision before M07 starts. No `EXP-M09` evidence is supplied by this documentation update.

### M07 - Integrated MVP Acceptance

- **Status:** In progress.
- **Dependencies:** M06, M09, and their required `EXP-M06`/`EXP-M09` checkpoints, currently pending.
- **Agents/sequence:** `LUNA MAX QA` and `LUNA MAX docs` perform the integrated gates after the build handoff. `EXP-M07` follows accepted M07 evidence; `ASTRA-FINAL` is later, after M08. Repairs use `R-M07-<n>` or `R-ASTRA-<n>` as applicable.
- **Evidence state:** M07 integration is in progress, not accepted or released. `R-M07-1` is the profile-count test with repair in flight. `R-M07-2` records Ponytail review availability; the retained report `test-results/ponytail-m06-m07-boundary.txt` records findings only and closure is pending, so its result is **Unavailable** and the row remains **Pending**. `R-M07-3` and `R-M07-4` have supplied repair evidence recorded below; no integrated acceptance or Astra evidence is recorded.
- **Scope:** Run the complete user journey and release review locally on native x86-64 plus local native or labelled emulated ARM64, reconcile all task evidence, and publish the supported local operation and limitations. No physical ARM64 performance claim is permitted without hardware.
- **Current M07 repair/availability register:**

  | Task ID | Status | Requirement/check | Evidence and current result | Limitation/next gate |
  | --- | --- | --- | --- | --- |
  | `R-M07-1` | **In progress** | Profile-count test | Repair is in flight; command, session, environment, UTC, commit, artifact, and reviewer were not supplied. | No pass is inferred; independent retest remains required. |
  | `R-M07-2` | **Pending** | Ponytail review availability | Retained report `test-results/ponytail-m06-m07-boundary.txt` records findings only; closure is pending. Availability evidence, command, environment, UTC, commit, artifact, and reviewer were not supplied. | **Unavailable**; findings-only evidence does not close the affected pre-QA boundary and cannot be substituted by implementation claims. |
  | `R-M07-3` | **Completed** | Repair stale three-profile assertions in `tests/test_ponytail_tooling.py` | `R-M07-3-E1`: assertions were updated from three profiles to four profiles; supplied test evidence reports `278` non-live tests pass. Exact command, session, environment, UTC, commit, artifact, and reviewer were not supplied. | **Pass as supplied repair/test evidence**; independent receipt metadata and broader M07 acceptance are not claimed. |
  | `R-M07-4` | **Completed** | Apply two retained Ponytail findings in `tests/test_config_quality.py` | `R-M07-4-E1`: both retained findings were applied; supplied diff evidence reports a net `-1` line. Exact command, session, environment, UTC, commit, artifact, and reviewer were not supplied. | **Completed for the supplied repair scope**; this is Ponytail/repair evidence only, with no independent correctness or M07 acceptance pass inferred. |
- **Acceptance evidence:** [ ] a user looks up a company name and confirms stock/ETF instrument identity, then receives both forecast horizons; [ ] direction/threshold probabilities, conditional gain/loss, 50/80/95 return and price intervals, evaluation metrics, archive limitations, and provenance are traceable to immutable inputs/results; [ ] saved forecasts reopen unchanged while historical cutoffs are labelled fresh analyses; [ ] historical price/return charts have text/table equivalents; [ ] successful, failed, and repeated searches appear in searchable history with no automatic query-history expiry; [ ] outcomes can be appended without changing forecasts; [ ] CSV and JSON export is verified; [ ] due/pre-migration backup, retention/disk limits, cross-architecture restore, trust-key transfer/lifecycle, and missing/wrong-key fail-closed behavior are verified; [ ] responsive/accessibility visual gates pass at 360/390/768/1280/1440 with Signal Ledger direction, no overlap/overflow, reduced motion, WCAG AA, keyboard, and actual assistive-technology evidence; [ ] every M06 native-x86 performance/UI row has its own independently reviewed structured artifact; [ ] local loopback security, MCP/browser, comments, resource targets, and local fail-closed Make/scripts all pass; [ ] README and roadmap state the shipped scope honestly; [ ] ARM64 functional/build/tool checks identify native or emulated environment; [ ] physical ARM64 low-resource performance is either measured on local native hardware or recorded `Unavailable`, which prevents a full low-resource ARM64 claim; [ ] M09 dark mode is user-selectable, accessible, responsive, and included in the integrated UI; [ ] M09 selected-instrument news is clearly labelled, API-served, provenance-bearing, and includes honest loading/empty/stale/failure states; [ ] options trading and public hosting remain out of scope.
- **Verification:** [ ] local clean package install, `make check`, loopback, Node/Chromium, official MCP application interaction, and desktop/mobile end-to-end journey on native x86-64; [ ] the same functional/build/tool journey on local native ARM64 or labelled QEMU/OCI emulation; [ ] restore artifacts in both directions with architecture labels; [ ] security and separate keyboard/actual assistive-technology sign-off; [ ] independent review of every M06 performance/UI artifact and its existing-versus-proposed threshold classification; [ ] native x86 memory/latency/idle-CPU evidence and explicit ARM64 physical-performance limitation when hardware is unavailable; [ ] coordinator review of every dependency and evidence field.
- **Repair record:** Record each failed release check as `R-M07-<n>` and keep M07 pending until repaired and rerun.
- **Post-milestone gate:** `EXP-M07` follows accepted M07 evidence and records its local Git checkpoint. M08 is the final roadmap milestone before `ASTRA-FINAL`; `EXP-FINAL` is a separate final export/commit/push/Git-revision gate after Astra repairs and the required final learning synthesis.

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
  - [ ] CSV and JSON export, append-only outcomes, backup/restore/status controls, M09 dark mode, and the ten selected-instrument news states—**not requested**, **loading**, **fresh**, **empty**, **partial metadata**, **stale cached with refresh failure**, **provider unavailable without cache**, **local service unreachable**, **capacity busy**, and **instrument changed/request superseded**—are demonstrated when those controls/features are exposed in the UI; an unexposed feature is labelled `Not exposed in UI`, not fabricated;
  - [ ] accessibility names/focus, keyboard operation, reduced-motion behavior, mobile layout, and desktop/mobile responsive use are demonstrated against actual controls;
  - [ ] every frame/image has alt text or a transcript/caption, every instruction has a step number, and no secret or local path appears;
  - [ ] the generation command, fixture identity, app revision, browser-tool version/context, artifact size, and limitations are recorded;
  - [ ] the end-of-project retrospective compares the shipped application with the original prompt and the original approved plan recovered from `SESSION-EXPORT.md`, enumerates every missing or materially altered feature, and assesses whether the UI is beautiful, well designed, and usable using the walkthrough, browser, accessibility, and responsive artifacts; any incomplete recovered source is recorded as `Unavailable`, never inferred;
  - [ ] every retrospective gap creates `R-M08-<n>`, receives repair and affected-check reruns, and is closed or remains explicitly blocking before `ASTRA-FINAL`.
- **Verification:** [ ] run the exact local generation command against deterministic fixtures; [ ] inspect the complete artifact for secrets and local paths; [ ] verify the 20 MiB budget; [ ] use official `@playwright/mcp` and browser regression tooling against the real local app and actual controls at desktop/mobile viewports; [ ] record accessibility/keyboard findings separately from visual and functional findings; [ ] independently review the prompt/plan comparison and UI design/usability assessment; [ ] record every missing, skipped, unavailable, stale, or failed check with its repair ID and rerun result.
- **Repair record:** Record each failed, inaccessible, oversized, nondeterministic, incomplete, or materially altered walkthrough requirement as `R-M08-<n>`; no retrospective gap is silently accepted.
- **Astra input:** `ASTRA-FINAL` must independently inspect the tracked artifact, transcript/alt text, generation evidence, actual-control browser evidence, and retrospective, then create separate rows for every feature, endpoint, control, UI state, asset, documentation visual, walkthrough frame/segment, media item, static asset, journey, and persistence effect. Every row must be evaluated for requirements, aesthetics, mobile/responsive behavior, accessibility, and measured performance.
- **Post-milestone gate:** Do not create a green `EXP-M08` from the artifact alone. After M08 QA/docs and Astra review, repair and retest all gaps until the Astra result is `Accepted`; then `EXP-M08` records the reviewed walkthrough/export revision and local Git checkpoint. After all roadmap and Astra repairs, complete the final learning synthesis before `EXP-FINAL`.

## Final operational item: selective Ingenium pipeline adoption

- **Status:** `Pending`; this is the ASTRA-plan operational follow-up, not a new
  milestone or acceptance ID, and no adoption result is claimed.
- **Plan:** Adopt Ingenium's agent-pipeline patterns selectively while retaining the
  six-agent orchestration, independent QA/docs order, the read-only Ponytail boundary,
  and commit/export gates. Add the simplest no-plugin subagent-count control through the
  valid `agent.options` field on the orchestrator profile, which the orchestrator reads;
  the schema has no native concurrency cap, and `subagent_depth` controls nesting only.
- **Required controls:** Audit `.gitignore`, align `AGENTS.md` principles, retain the
  stock Playwright MCP entry and its loopback allowlists, and require a parent-process
  restart plus independent post-restart validation before any profile control affects a
  gate. This documentation-only reconciliation did not edit `opencode.json`, `.gitignore`,
  profiles, local gates, or skills, and claims no audit or restart pass.
- **ASTRA profile:** The ASTRA agent profile now uses `variant: max`; parent-process
  restart and independent post-restart validation are **Pending**, so no gate effect or
  validation pass is claimed.
- **ASTRA research state:** The first pass is **Blocked** by the external-directory
  permission boundary. The gitignored snapshot at `test-results/ingenium-snapshot` enables
  the re-run; no re-run result is claimed.
- This follow-up does not alter the canonical `ASTRA-FINAL` -> `EXP-M08` -> final learning
  synthesis -> `EXP-FINAL` order, and optional `NOTIFY-FINAL` remains separate and last.

## Evidence Record Format

Every implementation task must maintain these fields in its task record or linked review:

- **Task ID:** the exact `M00`–`M09`, `R-M##-<n>`, `EXP-M00`–`EXP-M09`, `ASTRA-FINAL`, `R-ASTRA-<n>`, or `EXP-FINAL` identifier; do not replace it with a generic phase name.
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

For every implementation boundary, the pre-QA record also contains the read-only
`/ponytail-review` command, exact clean/finding form, environment, UTC, commit, result,
artifact, and reviewer. Its scope is overengineering only; it has no authority to accept
correctness, security, accessibility, or performance. A missing review is `Unavailable` and
blocks the boundary. Future profile or local-gate changes remain `SOL HIGH` work and require
parent restart plus independent validation before use.

## Verification And Repair Loop

1. The coordinator selects the next pending task only after its dependencies have completed with evidence and assigns the exact task ID.
2. Up to six non-overlapping `SOL HIGH build` lanes work concurrently, then all active builders report before integration or verification begins.
3. Run the mandatory read-only `/ponytail-review` after the boundary and before independent QA, using the exact clean/finding form; missing or unavailable review blocks the boundary.
4. `LUNA MAX QA` and `LUNA MAX docs` run their independent gates after the build wait and Ponytail review; QA denies repair/delegation conceptually and neither gate masks a missing result.
5. The coordinator alone integrates, updates status/evidence, and performs git operations. It routes only reproducible blocking findings with an exact task ID to `SOL HIGH`; if any check fails, the task remains pending, in progress, or blocked, and the root cause is repaired rather than the check weakened.
6. QA reruns the failed check and affected regression set. Documentation records the new evidence, limitation, exact timestamp/commit, and any skipped or unavailable result.
7. The coordinator marks a milestone completed for its declared scope only when every acceptance field in that scope, independent QA/docs review, and reviewer field pass. Full milestone/checkpoint acceptance additionally requires the matching `EXP-M00`–`EXP-M09` export, secret review, push, and exact Git remote revision verification. An explicitly deferred or unavailable later-release field, or an `In progress` export gate for a milestone marked **Completed for exercised scope**, remains visible, is not counted as a pass, and blocks final acceptance. The supplied x64 SHA context is not dual-architecture or `EXP-M00` proof.
8. After M08, `ASTRA-FINAL` must review the complete feature/API/UI/control/state/asset/journey/persistence matrix plus the walkthrough, media, static assets, documentation visuals, and retrospective. Any gap creates `R-ASTRA-<n>` and requires SOL repair, QA rerun, Astra retest, and explicit `Accepted` before `EXP-M08`; the final deep chat/run skill synthesis must then complete before `EXP-FINAL`.

## Final Definition Of Done

The MVP is done only when all of the following are true:

- M00 through M09 have explicit statuses and evidence, with no implementation milestone marked complete by assertion alone.
- A user can identify a company and instrument, select Yahoo Finance stocks and ETFs, and receive close-to-close and latest-completed-5-minute-bar-to-close forecasts with clear session/bar semantics.
- Results contain explicit up/down/unchanged and threshold probabilities, conditional gain/loss, 50/80/95 return and price intervals, walk-forward/baseline/calibration/coverage/rare-event evidence, and source/as-of/stale/error/model/version/input/output provenance.
- Every submitted successful, failed, and repeated search is retained, history is searchable through `/api/v1`, and forecast inputs/results/outcomes are immutable or append-only as specified.
- Saved results reopen immutably; historical cutoffs are separately labelled fresh analyses; price/return charts have text equivalents; CSV and JSON export are verified; Yahoo archive limitations are visible.
- Backup artifacts and restores are verified through integrity, compatibility, representative-data, non-destructive promotion, due/pre-migration, retention/disk, trust-key lifecycle, and both-direction cross-architecture checks; missing/wrong keys fail closed and query history is not silently expired.
- The frontend uses FastAPI `/api/v1` for all application data and has no direct SQLite access.
- The dashboard preserves Signal Ledger direction at 360/390/768/1280/1440 without overlap/overflow, with tabular numeric hierarchy, charts/tables, reduced motion, WCAG AA, keyboard, actual assistive technology, and loading/empty/stale/repeated/failure behavior.
- Dark mode is user-selectable and accessible across the dashboard, charts, tables, controls, focus states, and all required loading/empty/success/stale/failure states; selected-instrument news is clearly labelled, API-served, provenance-bearing, and honest about loading, empty, stale, and failure states.
- The default deployment is secure loopback and bounded for low-resource Linux x86-64 and ARM64. M06 independently passes every structured native-x86 performance/UI row: fresh isolated fixture runtime, five warmups plus at least 30 samples, process RSS `<500 MiB`, fixture/cache-hit forecast p95 `<1 s`, 100,000-history p95 `<250 ms` with at least 10 repetitions and index plan, proposed 60-second idle CPU `<=1 core-percent`, concurrency elapsed, readiness `20 s`, package/build baseline, backup/restore bounds, static shell/assets `<96 KiB`, designated response `<8 KiB`, and browser budgets. Native x86 resource targets are measured locally; ARM64 physical low-resource performance is claimed only when local native ARM64 hardware supplies evidence, never from emulation or an original-laptop assumption. Any missing field remains unavailable or blocking.
- The official headless `@playwright/mcp` supports local agent QA, automated browser regressions are checked in, and local Make/scripts fail closed on required regressions.
- Every implementation boundary has a read-only `/ponytail-review` record in the exact required format before QA; it is overengineering-only and never substitutes for correctness, security, accessibility, or performance evidence. Profile/local-gate changes have parent-restart and independent-validation receipts.
- Code comments explain non-obvious behavior, the supported local workflow is documented, and `README.md` and `AGENTS.md` are reconciled with the evidence actually shipped.
- M08 produces a tracked, bounded, accessible instructional walkthrough from deterministic fixtures and the real local app, with actual-control browser evidence, desktop/mobile instructions, and a completed prompt/approved-plan retrospective. Any gap is repaired before Astra.
- `ASTRA-FINAL` is independently recorded as `Accepted` after separate rows for every requirement, feature, endpoint, control, UI state, asset, documentation visual, walkthrough frame/segment, media item, static asset, journey, and persistence effect have passed requirements, aesthetics, mobile/responsive, accessibility, and measured-performance evaluation, including every `R-ASTRA-<n>` retest. Astra suggests only; SOL implements and QA retests.
- `EXP-M00` through `EXP-M09` and `EXP-FINAL` each have a reviewed full-session `SESSION-EXPORT.md`, recorded export revision, secret review, commit, push, exact Git remote revision verification, and no hidden unavailable or failed field; the final learning synthesis is recorded before `EXP-FINAL`.
- The final learning synthesis deeply analyzes sanitized chat/run evidence, creates or changes only justified reusable Stock Probability skills through validated/indexed `skill-maintenance` work, and records observations before `EXP-FINAL`; the authored documentation taxonomy and project documentation skill are implemented, and the post-restart validation receipt is session `ses_f6aa32d33ffeAvmiFK8K7Cd8EI` at `2026-09-12T11:35:58Z`–`2026-09-12T11:36:02Z`, native x86_64/OpenCode `1.18.30`, dirty commit `59534faf1cdce493bc51a11d4adbea5e5b2d6892`, with its listed checks passed. `.dev-venv/bin/python scripts/validate_docs.py` passed `8` categories and `11` topics at `2026-09-12T12:13:23Z`. This receipt does not close M06 or any export gate.
- Dark mode and selected-instrument news are release requirements owned by M09; options trading and public hosting are outside this local-app contract.
