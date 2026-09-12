# Stock Probability MVP Roadmap

## Status Snapshot

This roadmap tracks delivery of the local Linux stock-probability web app. The supported target is Linux x86-64/amd64 and ARM64/aarch64, designed for low-resource operation. The current host is native x86_64; no native ARM64 or physical ARM64 performance result is claimed. ARM64 verification first uses local native hardware if available, otherwise local QEMU/OCI multi-arch execution may verify packaging/runtime portability and functional/build/tool behavior only when explicitly labelled **emulated ARM64**. This is not native/physical ARM64 or original-laptop resource evidence. Repository shape is not acceptance evidence.

- **Completed:** `M00`, documentation baseline only. The four roadmap deliverables are `MVP-PLAN.md`, `MVP-ROADMAP.md`, `AGENTS.md`, and `README.md`.
- **Documentation repair:** `R-M00-2` is **Completed** only for the four-file policy reconciliation; it does not accept implementation.
- **Completed checkpoint:** `EXP-M00` is **Completed** as the M00 coordinator export, with full regex secret review, exact pushed SHA `18da1af0b6bc31020d3587e472b8197146795bf1`, and matching `git ls-remote` result; its evidence is recorded below.
- **Completed:** `M01` and `EXP-M01`; M01 scoped repair rows pass independently and the exact export/Git/workflow checkpoint is SHA `5424fa3e22d9229d038d376512e59b3f35c97e78`.
- **Completed through explicit late repair:** `M02` and `EXP-M02`. The independent receipt `EXP-M02-REPAIR-1`, session `ses_f6eacd1cdffeZxtRNqfzkXOuqJ`, was reviewed by `LUNA MAX QA` at `2026-09-11T17:10:31Z`; the earlier missing review/timing remains historical and no remote CI was run or used. `M03` and `EXP-M03` are **Completed** at exact local/remote SHA `777451643b5ec1a04a37c013a9caf59f0bd58122`, with supplied export commit UTC `2026-09-11T17:46:42Z`.
- **Completed functional and export scope:** `M04` and `EXP-M04` are **Completed** for their recorded scopes. `R-M04-30` remains **Pending** because actual screen-reader evidence is **Unavailable** and deferred to M06; it blocks final accessibility/release acceptance, not the exercised M04 feature scope.
- **`EXP-M04` receipt:** the sanitized full-session `SESSION-EXPORT.md` was overwritten and parsed as JSON with `140` messages, `844` parts, `101` task outputs, `241` tool parts, `672,190` bytes, `19,855` lines, SHA-256 `5eebab2ce302e9f8b5a08aec5e4773c8bf7e4a99c920fa059c462dd71cecb837`, and `1,817` redaction markers. Secret review found zero webhook/private-key/AWS/GitHub/Bearer/embedded-credential matches. Commit `59534faf1cdce493bc51a11d4adbea5e5b2d6892` (`Build responsive forecast dashboard`, commit UTC `2026-09-11T20:25:10-04:00`) was pushed and exact `origin/main` match verified; no CI was run. Named export reviewer was not supplied in this reconciliation.
- **Completed for declared scope:** `M05` is closed by the fully passing independent `R-M05-55` receipt: rows `(a)`–`(i)` passed in session `ses_f6bbd6b46ffes2BM2zVjBC5uLg` at `2026-09-12T06:25:04Z`–`2026-09-12T06:44:37Z`, including the `R-M05-12` independent `4/4` behavior-test rerun, and row `(j)` passed in session `ses_f6aa32b01ffexjSm9OhpprFwq4` at `2026-09-12T11:26:29Z`–`2026-09-12T11:28:26Z` with `276` non-live tests/`4` live deselected/`89.51%` coverage, documentation validation of `8` categories/`11` topics/`1` skill, `22` documentation tests, a `77`-file comment audit, Ruff, and mypy. `EXP-M05` remains **Pending** for its separate export/secret-review/commit/push/exact-remote-verification checkpoint. Earlier failures and pending states remain historical evidence.
- **`R-M05-55` receipt metadata:** `LUNA MAX QA` reviewed the native x86_64/`.dev-venv` Python `3.11.15` receipt. Rows `(a)`–`(i)` record round trip/checksum (`06:42:38Z`–`06:42:39Z`), the six-path pre-migration forced-failure matrix (`06:32:09Z`–`06:32:10Z`), due-check `60`/`2678400` accepted and `59`/`2678401`/`nan` rejected, retention of `32` artifacts/`256 MiB` with history preserved (`06:43:54Z`), `13/13` fail-closed negatives (`06:35:29Z`–`06:35:32Z`), key lifecycle with rollback (`06:44:37Z`), `7/7` watchdog probes (`06:35:01Z`–`06:35:02Z`), both-direction **emulated ARM64** cross-architecture restore (`06:25:04Z`–`06:28:44Z`, artifact `test-results/arm64/M05-20260912T034933Z/evidence.json`), and the `R-M05-12` rerun (`06:38:47Z`–`06:38:49Z`). Packaged-CLI end-to-end verification is session `ses_f6a96daceffegfAqyKQL2lf3bS` on native x86_64/Python `3.11.15`, with artifact `/tmp/opencode/stock-probs-m05-cli-20260912T114105Z/M05-packaged-cli-receipt.json` and reviewer `LUNA MAX QA` (fresh-venv wheel install, migration pre-backup, named backup, verify, `restore --promote`, wrong-key/tampered rejection, backup-key rotate/retire, and isolated-port serve readiness). Commands and commits were not supplied and are not inferred.
- **In progress, not completed:** `M06` has independent scoped passes for `R-M06-2`, `R-M06-3`, `R-M06-4`, `R-M06-16`–`R-M06-20`, and `R-M06-11`; `R-M06-11` passed twice, each with three hash-stable native runs and exact recomputation. `R-M06-55` passed the scoped gate, and the documentation-skill post-restart receipt passed its listed checks. Final consolidated gate rerun, docs/release reconciliation, screen-reader evidence, and `EXP-M06` remain pending.
- **M05 implementation/preparation evidence only:** migration pre-backup, serve due-check with `STOCK_PROBS_BACKUP_INTERVAL_SECONDS` default `86400` and bounds `60`–`2678400`, backup-key rotation/retirement, `32`-artifact/`256 MiB` retention, and non-expiring query history are implemented. `docs/operations/backup-restore.md` and `docs/configure/local-configuration.md` were updated for accuracy by `SOL HIGH`. The M08 capture harness supplied `20` annotated screenshots and manifest SHA-256 `f9fef2b2db0a806cc47ff1db82e1e895f4dd4803425c0cf74426f5fa5a12dd5d`, but M08 acceptance is not claimed.
- **Pending:** `M07`, `M08`, `ASTRA-FINAL`, and `EXP-FINAL`. `EXP-M01` through `EXP-M04` are completed; later exports remain pending.
- **Current M06 limitation:** `R-M06-11` passed twice in independent QA, with three hash-stable native runs and exact recomputation. `R-M06-55` is a dirty native-x86 gate receipt, not the export checkpoint; actual screen-reader evidence and native/physical ARM64 performance are **Unavailable**, and final consolidated QA/docs plus `EXP-M06` remain open.
- **Supplied Git receipt:** remote `main` was historically reported at `2a7a3bf66c3665552a46d0bd523544a01f894b3f`; it is not a current checkpoint. The old hosted Actions receipt is obsolete x64-only context and not a current gate or release proof. No external pipeline is in scope.
- **Current-task limitation:** `R-M00-1` is immutable historical documentation recovery. `R-M00-2` is a documentation-only policy repair; it does not run implementation QA, remove implementation files, create a walkthrough, export, commit, push, or verify a new Git revision. No unavailable field is turned green.
- **Rule:** no milestone advances to `Completed` from implementation claims, a test file, a generated artifact, or a narrative summary. The exact evidence record in `MVP-PLAN.md` is authoritative. `EXP-M01` verified the workflow deletion on its exact pushed/remote revision; `EXP-M02` is completed only by its later independent repair receipt; `EXP-M03` is completed by its supplied direct export receipt; M04's functional scope and `EXP-M04` are completed for their recorded scopes, with the exact export checkpoint recorded above.
- **Scope discipline:** absent a demonstrated requirement, no auth, MFA, gateway, multi-service split, dual-database restore, direct-route SQL, or replica rate limiting is added. A read-only integrity diagnostic is optional and is not a new acceptance surface.

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
- **Limitations and export/Git:** At the time of `R-M00-2`, no implementation QA, ARM64 native/emulated run, walkthrough artifact, browser-control check, retrospective, export, commit, push, or new Git revision verification was performed by that docs-only repair; `EXP-M02` was not yet completed then. The later `EXP-M02-REPAIR-1` receipt now completes `EXP-M02` without rewriting that historical timing; `EXP-M03` and `EXP-M04` are completed at their exact receipts below, and later exports remain pending in their exact records.

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
| `M03` | Yahoo Finance data and forecast engine | M01, M02, `EXP-M02` | Completed | `R-M03-3`–`R-M03-22` are completed after their recorded failures/skips and repairs; `R-M03-23` remains pending for unavailable screen-reader evidence deferred to M04/M06. `EXP-M03` is completed at exact local/remote SHA `777451643b5ec1a04a37c013a9caf59f0bd58122`; see its export receipt below. |
| `M04` | Dashboard and searchable history | M01, M02, M03, `EXP-M03` | Completed | Exercised scope and `EXP-M04` are completed for their recorded scopes; `R-M04-30` remains Pending because actual screen-reader evidence is Unavailable and deferred to M06, blocking final accessibility/release acceptance but not the exercised M04 scope. |
| `M05` | Backup, restore, and secure loopback operations | M02, M04 | Completed for declared scope | `R-M05-55` is fully **Pass** for rows `(a)`–`(j)`, including the `R-M05-12` `4/4` behavior rerun inside `(i)` and the `(j)` aggregate recorded in the M05 evidence section. `EXP-M05` is **Pending** and is the next export/secret-review/commit/push/exact-remote-verification gate. |
| `M06` | Local QA, MCP, browser regressions, and fail-closed gates | M01, M02, M03, M04, M05 | In progress | `R-M06-2`, `R-M06-3`, `R-M06-4`, and `R-M06-16`–`R-M06-20` independently pass; `R-M06-11` passed twice, each with three hash-stable native runs and exact recomputation; `R-M06-55` passed its dirty native-x86 scoped gate; and the documentation-skill post-restart receipt passed its listed checks. Final consolidated gate rerun, docs/release reconciliation, actual screen-reader evidence, and `EXP-M06` remain open. Then `EXP-M06`. |
| `M07` | Integrated MVP acceptance | M06 | Pending | Full local user journey, persistence, restore, dual-architecture semantics, visual/AT, release reconciliation, and sign-off remain open. Then `EXP-M07`. |
| `M08` | Instructional Walkthrough | M07, `EXP-M07` | Pending | Deterministic fixture walkthrough, real local app, official browser tooling, actual-control evidence, accessibility/transcript artifact, and prompt/approved-plan retrospective remain open. Then `ASTRA-FINAL`, `EXP-M08`, final learning synthesis, and `EXP-FINAL`. |

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
- **Checkpoint limitation:** the host lacks system `make`; the direct executable gate passed and `Makefile` is a convenience wrapper. Physical/native ARM64 performance is `Unavailable`; the ARM64 result is explicitly emulated functional/tool evidence only. `EXP-M01` verified `.github/workflows/ci.yml` absent on the exact remote checkpoint; the unrelated `?? .vscode/` remained untouched and no remote CI was used. `EXP-M02` is completed through its late repair receipt; `EXP-M03` is completed at exact SHA `777451643b5ec1a04a37c013a9caf59f0bd58122`, and `EXP-M04` is completed at the receipt recorded above.

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
- **Next gate at that historical checkpoint:** `M03`/`EXP-M03`; this docs gate did not perform the export, commit, push, or remote verification. The current records below supersede that forward-looking status; `EXP-M03` and `EXP-M04` are now completed at their separately recorded receipts.

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
| `R-M05-1` / QA `ses_f72f4e163ffehgqJPXwbY7ujrX` | Malicious backup audit/repair | `R-M05-5` | Completed for the declared M05 scope through the later independent `R-M05-55` Pass receipt; the historical source-qualified label remains unchanged |
| `R-M05-1` / backup builder `ses_f72c4f1baffeECZSQ37ujzSmCJ` | Chunked request and cross-architecture restore harness | `R-M05-6` | Completed for the declared M05 scope through the later independent `R-M05-55` Pass receipt; historical emulated-evidence limitations remain visible |
| `R-M05-2` / QA `ses_f72f4e163ffehgqJPXwbY7ujrX` | Historical source-qualified label; the recovered record does not supply enough source-specific detail to infer a distinct obligation | No fresh alias allocated | Completed for current declared M05 coverage through the later independent `R-M05-55` Pass receipt; the historical label is retained and is not reused |
| `R-M05-4` / QA `ses_f72f4e163ffehgqJPXwbY7ujrX` | Historical source-qualified label; the recovered record does not supply enough source-specific detail to infer a distinct obligation | No fresh alias allocated | Completed for current declared M05 coverage through the later independent `R-M05-55` Pass receipt; the historical label is retained and is not reused |
| `R-M06-1` / QA/operations `ses_f72f4e163ffehgqJPXwbY7ujrX` | Port collision | `R-M06-2` | **Completed**; independent retest **Pass** for occupied-port fail-closed behavior |
| `R-M06-1` / repair builder `ses_f72c4f20effeDoLPC0FuHaaGjZ` | Documentation CSP | `R-M06-3` | **Completed**; independent retest **Pass** for CSP/host/origin enforcement |
| `R-M06-1` / repair builder `ses_f72c4f20effeDoLPC0FuHaaGjZ` | CSV formula issue | `R-M06-4` | **Completed**; independent retest **Pass** for CSV formula safety |
| `R-M04-1` / browser/accessibility `ses_f72f4e261ffeLWQEjyJI4k3hea` | Actual assistive-technology evidence unavailable | `R-M04-2` | Pending; evidence unavailable |
| `R-M04-1` / repair builder `ses_f72c4f20effeDoLPC0FuHaaGjZ` | Mobile error focus | `R-M04-3` | Pending |

The source task IDs are evidence locators, not independent acceptance reviews. `R-M01-5` through `R-M01-15` are current coordinator-assigned M01 records in the M01 record below. The `R-M04-2`/`R-M04-3` values above are source-qualified historical aliases from `R-M00-1`; they remain visible and are not merged into the later source-qualified current M04 QA labels carrying the same text. The current M04 screen-reader obligation is `R-M04-30`. The screen-reader/assistive-technology gap is separately unavailable; axe and keyboard results cannot close it. Mobile focus, CSP, and CSV still require the cancelled independent API/UI retest. Stale labels `R-M01-16` through `R-M01-19` were not created.

## Current M03 Evidence Record

`M03` and `EXP-M03` are **Completed**. M01, `EXP-M01`, M02, and `EXP-M02` are verified; the M03 behavior records below are complete in scope, while `R-M03-23` remains pending for unavailable screen-reader evidence deferred to M04/M06. The supplied M03 behavior evidence ran on native x86_64 Linux WSL2, Python `3.11.15`, at dirty revision `ae740b79f8d8da5e1996d4ba38caa3a98cb2cce5`; the separate export receipt below closes `EXP-M03`.

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
- **Post-milestone gate:** `EXP-M03` is **Completed** by the supplied direct export receipt below, reviewed by `OpenCode gpt-5.6-sol`; `R-M03-23` remains a later accessibility limitation rather than a blocker to the M03 provider/model scope. The receipt parsed and secret-reviewed the sanitized full-session export, committed at `2026-09-11T17:46:42Z`, pushed exact SHA `777451643b5ec1a04a37c013a9caf59f0bd58122`, and verified exact remote `main`.

### `EXP-M03` completed checkpoint

- **Status:** Completed.
- **Owner/phase:** coordinator export gate; reviewer/coordinator `OpenCode gpt-5.6-sol`.
- **Dependencies verified:** completed M03 scoped records `R-M03-3`–`R-M03-22`; `R-M03-23` remains Pending and was not substituted by axe/MCP.
- **Export evidence:** supplied sanitized full-session `SESSION-EXPORT.md` parsed as `94` messages, `602` parts, `67` task outputs, `176` tool parts, `479,795` bytes, `14,128` physical lines, and `1,298` redaction markers; SHA-256 `964f4f71b8f0d56b1417afc23ff1ea65a69f50ea7a1c3067f91ba8a30c974892`. **Pass**.
- **Secret evidence:** zero webhook, private-key, AWS, GitHub, Bearer, or embedded-credential patterns. **Pass**; no webhook endpoint/token/credential is persisted or printed.
- **Git evidence:** commit UTC `2026-09-11T17:46:42Z`, message `Build auditable forecast engine`, exact local and remote `main` SHA `777451643b5ec1a04a37c013a9caf59f0bd58122`; push and exact remote match **Pass**. No CI was run or used.
- **Limitations:** supplied built-in streaming truncation failures remain visible where present, while the final direct export parse passed. This docs gate does not edit/export/commit/push or perform a new remote check.

## Current M04 Evidence Record

`M04` and `EXP-M04` are **Completed** for their recorded scopes. `R-M04-30` remains **Pending** because actual screen-reader evidence is **Unavailable** and deferred to M06; it blocks final accessibility/release acceptance, not the exercised M04 feature scope. The supplied M04 QA/retest evidence ran on dirty native x86_64 Linux WSL2/Python `3.11.15`, revision `777451643b5ec1a04a37c013a9caf59f0bd58122`; this is functional evidence context, not the `EXP-M04` export checkpoint.

- **Builder handoffs:** A `ses_f6e6a711fffeyuef4zb62H0giu`, B `ses_f6e6a70e1ffe26uoiMUKL6tJYQ`, C `ses_f6e6a70c9ffeHInuhUf0xcS4Sf`; implementation handoffs only.
- **Initial QA:** A `ses_f6e477c95ffewj86nzBDav0XDr` passed `R-M04-2`–`R-M04-10` but failed the supplied `F-M04-1` alias finding. B `ses_f6e477c73ffeTGeXUo9LjYAyzB` passed `R-M04-11`, `R-M04-12`, `R-M04-14`, `R-M04-15`, `R-M04-17`, and `R-M04-18`, and failed `R-M04-13` (migration microseconds) and `R-M04-16` (HTTP N+1/export behavior). C `ses_f6e477c5cffeCcKYsNq7FiB` reported 30 browser/gate passes but found 1024px overlap, 360px loading overflow, and unavailable actual screen-reader evidence `R-M04-30`. Reviewer: `LUNA MAX QA`.
- **Repair waves:** first A/B/C `ses_f6e23032effeXHemmIiJw24mvc`, `ses_f6e2301f1ffe9tJOQ0zBihTVOF`, `ses_f6e23016bffe6FKOJLQHWssAks`; second A/B/C `ses_f6ded9fabffe74Yzkxn9HP3moM`, `ses_f6ded9f30ffe98yoClIySjeVHN`, `ses_f6ded9f04ffeztNVxscerfMIh`; A/B integration `ses_f6dd70c15ffev9zBudOh8W5hog`. Final C repair/retest is the supplied combined/collision handoff `ses_f6d97dd26ffesyTKZixyryG1ob`; it is not split into invented sessions.
- **Independent retests:** A `ses_f6e0b6f9cffepJAxXGpRAr0yDI` retained `F-M04-1` `422` and R-M04-16 post-cap/event-filter failures while other parity/five-read checks passed; B `ses_f6e0b6f7fffeektwB8iMbo1viu` closed R-M04-13; C `ses_f6e0b6f6effeA4v` retained responsive passes but recorded R-M04-35 axe-incomplete/manual-contrast failure. The supplied C handoff includes `Ends?` after that ID; no suffix is inferred.
- **Closure QA:** A `ses_f6dd32543ffeubeFL5TuTKpJIh` passed aliases/noninteger safe `404` and absent OpenAPI, exact event pre-cap/parity, exactly five reads, and `198` non-live + `4` live. B `ses_f6dd32520ffe2WEUzDbuouU5iB` passed R-M04-11–18, schema-4/checksum/package, `100,000` rows in `<=48.792 ms`, and five reads. C `ses_f6dd32500ffeYPyuvir4MqUwj8` passed responsive checks but retained raw-axe-incomplete/contrast block. Final C `ses_f6d97dd26ffesyTKZixyryG1ob` reported raw axe `0/0`, contrast passes, `32` browser/MCP, and screen-reader unavailable.
- **Final receipt:** `R-M04-55`, session `ses_f6d85b2a2ffeUizsObfcDoBzsZ`, reviewed by `LUNA MAX QA`, passed `198` tests/`89.29%`, `32` browser, `4` live, `55` backup, raw axe `0/0`, schema-4/package/migration, actual MCP, and explicitly emulated ARM64 functional/package evidence. Artifact `test-results/local-gates/R-M04-55-20260911T222704Z`; the initial random request-ID/search-collision gate **Fail** and clean rerun **Pass** remain visible.

### M04 scoped records

| Exact record(s) | Status | Evidence and limitation |
| --- | --- | --- |
| `R-M04-2`–`R-M04-10` | **Completed** | Initial A pass `ses_f6e477c95ffewj86nzBDav0XDr`, final regression; reviewer `LUNA MAX QA`. |
| `R-M04-11`, `R-M04-12`, `R-M04-14`, `R-M04-15`, `R-M04-17`, `R-M04-18` | **Completed** | Initial B passes plus closure B `ses_f6dd32520ffe2WEUzDbuouU5iB`; reviewer `LUNA MAX QA`. |
| `R-M04-13` | **Completed** after initial **Fail** | Migration-microseconds repair/retest `ses_f6e0b6f7fffeektwB8iMbo1viu` and closure B pass; reviewer `LUNA MAX QA`. |
| `R-M04-16` | **Completed** after initial **Fail** | HTTP N+1/post-cap/event-filter/parity/formula-safety failures retained; closure A `ses_f6dd32543ffeubeFL5TuTKpJIh`, exactly-five-read/pre-cap/parity pass; reviewer `LUNA MAX QA`. |
| `R-M04-21`, `R-M04-22` | **Completed** after initial responsive findings | 1024px overlap and 360px loading overflow retained; responsive retests and final receipt pass; reviewer `LUNA MAX QA`. |
| `R-M04-35` | **Completed** after initial **Fail** | Raw axe/manual contrast finding retained; final C repair/retest and final receipt reported raw axe `0/0` and contrast pass; reviewer `LUNA MAX QA`. |
| `R-M04-30` | **Pending** | Actual screen-reader evidence **Unavailable**, deferred to M06; blocks final accessibility/release, not exercised M04 scope; axe/keyboard/MCP do not substitute. |
| `R-M04-55` | **Completed** | Final functional receipt above; initial collision failure and clean rerun pass retained; reviewer `LUNA MAX QA`. |

The supplied `F-M04-1` label remains visible as a failure alias/finding rather than an invented canonical repair ID: initial alias behavior returned `422`; closure A passed safe noninteger `404` behavior and absence from OpenAPI. No missing task suffix, repair ID, timestamp, native ARM64 result, or CI result is inferred.

- **Limitations/export:** native x86_64 only for the functional QA; ARM64 evidence explicitly emulated for functional/package behavior; physical/native ARM64 performance and actual screen-reader evidence are unavailable; no CI was run. The separate `EXP-M04` receipt below supplies its export, secret, commit, push, and exact remote-main facts; it does not close `R-M04-30`.

### `EXP-M04` completed export checkpoint

- **Status:** Completed.
- **Owner/phase:** coordinator export gate; this roadmap records the supplied receipt and does not re-run export or Git operations. Named export reviewer was not supplied in this reconciliation.
- **Dependencies verified:** completed M04 exercised functional scope and `R-M04-55`; `R-M04-30` remains Pending because actual screen-reader evidence is Unavailable and deferred to M06.
- **Evidence ledger:**

  | Evidence ID | Requirement/check | Environment, UTC time, commit | Result, artifact, reviewer, limitation |
  | --- | --- | --- | --- |
  | `EXP-M04-E1` | Sanitized full-session `SESSION-EXPORT.md` overwritten and parsed as JSON: `140` messages, `844` parts, `101` task outputs, `241` tool parts, `672,190` bytes, `19,855` lines, `1,817` redaction markers; SHA-256 `5eebab2ce302e9f8b5a08aec5e4773c8bf7e4a99c920fa059c462dd71cecb837` | Supplied export; commit `59534faf1cdce493bc51a11d4adbea5e5b2d6892`; commit UTC `2026-09-11T20:25:10-04:00` | **Pass as supplied export receipt**; named reviewer not supplied. |
  | `EXP-M04-E2` | Full secret review: zero webhook, private-key, AWS, GitHub, Bearer, or embedded-credential matches | Same sanitized export/checkpoint | **Pass as supplied secret-review receipt**; named reviewer not supplied. |
  | `EXP-M04-E3` | Commit, push, and exact remote `main` match | Commit message `Build responsive forecast dashboard`; exact `origin/main` match at `59534faf1cdce493bc51a11d4adbea5e5b2d6892` | **Pass as supplied Git receipt**; named reviewer not supplied. |
  | `EXP-M04-E4` | CI limitation | Same checkpoint | **Skipped**; no CI was run or used. |

- **Limitations:** `R-M04-30` remains Pending/Unavailable and deferred to M06; no physical/native ARM64 performance or CI result is claimed. The export receipt is complete for `EXP-M04`, but its named reviewer field was not supplied here.

## Current M05 Evidence Record

`M05` is **Completed for the declared scope**. This record retains the repair-wave history
and consumes the later independent `R-M05-55` closure receipt without converting
implementation presence into acceptance. The current worktree is dirty native x86_64 Linux
at HEAD `59534faf1cdce493bc51a11d4adbea5e5b2d6892`. The supplied receipt records session
`ses_f6bbd6b46ffes2BM2zVjBC5uLg` for rows `(a)`–`(i)` at
`2026-09-12T06:25:04Z`–`2026-09-12T06:44:37Z` and session
`ses_f6aa32b01ffexjSm9OhpprFwq4` for row `(j)` at
`2026-09-12T11:26:29Z`–`2026-09-12T11:28:26Z`, on native x86_64 with `.dev-venv` Python
`3.11.15`, reviewed by `LUNA MAX QA`. The packaged-CLI session is
`ses_f6a96daceffegfAqyKQL2lf3bS` on native x86_64/Python `3.11.15`, with artifact
`/tmp/opencode/stock-probs-m05-cli-20260912T114105Z/M05-packaged-cli-receipt.json` and
reviewer `LUNA MAX QA`. Commands and commits were not supplied and are not inferred.
`EXP-M05` remains the next separate checkpoint.

| Task ID | Status | Evidence and current result | Limitation/next gate |
| --- | --- | --- | --- |
| `R-M05-5` | **Completed** | Malicious-backup closure evidence covers unsafe archive/member, transferred/wrong-key, lost-key, and retention/storage cases in `tests/test_backup_cli.py`; the later `R-M05-55 (a)`–`(i)` receipt closes the declared scope. | **Pass** in the fully passing `R-M05-55` scope. Exact receipt sessions, windows, native environment, and reviewer are recorded below; command and commit were not supplied. |
| `R-M05-6` | **Completed** | Chunked-request falsification is represented by `tests/test_m05_request_limits.py`. Supplied `test-results/arm64/M05-20260912T034933Z/evidence.json` reports both x86-64 -> emulated ARM64 and emulated ARM64 -> x86-64 restore directions; the later `R-M05-55 (a)`–`(i)` receipt closes the declared scope. | **Pass** in the fully passing `R-M05-55` scope; the emulated artifact remains functional evidence only, not native ARM64 or performance evidence. Exact receipt sessions, windows, native environment, and reviewer are recorded below; command and commit were not supplied. |
| `R-M05-7` | **Completed** | The supplied finding records an insufficient due-check watchdog. Initial result: **Fail**; closure is carried by `R-M05-8`/`R-M05-11` and the later `R-M05-55 (a)`–`(i)` receipt. | **Pass** for the declared M05 scope; the initial failure remains visible. Exact receipt sessions, windows, native environment, and reviewer are recorded below; command and commit were not supplied. |
| `R-M05-8` / `R-M05-11` | **Completed** | The supplied repair statement covers due-check, creation, internal verification, pre-migration, serve startup, and public verify/restore; the later `R-M05-55 (a)`–`(i)` receipt closes the declared scope. | **Pass** in the fully passing `R-M05-55` scope. Exact receipt sessions, windows, native environment, and reviewer are recorded below; command and commit were not supplied. |
| `R-M05-9` | **Completed** | Walkthrough comment repair is retained; row `(j)` of `R-M05-55` includes the independent `77`-file comment audit. | **Pass** in the fully passing `R-M05-55` scope. Exact receipt sessions, windows, native environment, and reviewer are recorded below; command and commit were not supplied. |
| `R-M05-10` | **Completed** | All migrating CLI commands route through the protected pre-migration path in the supplied evidence; the later `R-M05-55 (a)`–`(i)` receipt closes the declared scope. | **Pass** in the fully passing `R-M05-55` scope. Exact receipt sessions, windows, native environment, and reviewer are recorded below; command and commit were not supplied. |
| `R-M05-12` | **Completed** | Ponytail repair record: [`docs/evidence/ponytail-m05-boundary.txt`](docs/evidence/ponytail-m05-boundary.txt) records the two findings and repair. `R-M05-55 (i)` independently reran the affected behavior tests: `4/4` **Pass**. | **Pass** for the independent rerun inside `R-M05-55 (i)`; the receipt retained at `docs/evidence/ponytail-m05-boundary.txt` is overengineering-only. Exact rerun session, window, native environment, and reviewer are recorded below; command and commit were not supplied. |
| `R-M05-55` | **Completed** | Fully passing consolidated M05 QA: rows `(a)`–`(i)` passed earlier and row `(j)` passed on rerun. | **Pass** for the declared M05 scope; exact sessions, windows, native environments, artifacts, and reviewer are recorded below. `EXP-M05` remains pending; commands and commits were not supplied. |

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

Earlier failures and pending states remain visible in the historical repair narrative; this
later receipt closes the declared M05 scope without backdating or erasing that history.

### M05 implementation evidence (not acceptance)

The implemented automation includes migrate pre-backup; a fail-closed serve due check using
`STOCK_PROBS_BACKUP_INTERVAL_SECONDS` with default `86400` and bounds `60`–`2678400`;
`backup-key rotate` and `backup-key retire`; retention limits of `32` artifacts and
`256 MiB`; and no automatic query-history expiry. `docs/operations/backup-restore.md` and
`docs/configure/local-configuration.md` were updated for accuracy by `SOL HIGH`. The current
`LUNA MAX docs` profile cannot edit `docs/**`, so `SOL HIGH` performed those authored-docs
repairs; this profile gap remains visible and is not independent QA or M05 verification.

`EXP-M05` is **Pending** and is the next checkpoint. No M05 export, full-session secret
review, local commit, push, or exact remote-revision verification was performed by this
reconciliation; no new checkpoint exists. Those checkpoint fields remain pending and do not
become passes from the completed `R-M05-55` scope receipt.

### M08 preparation (not acceptance)

The supplied capture-harness receipt reports `20` annotated screenshots and manifest SHA-256
`f9fef2b2db0a806cc47ff1db82e1e895f4dd4803425c0cf74426f5fa5a12dd5d`. `M08`, walkthrough
QA, the retrospective, `ASTRA-FINAL`, and `EXP-M08` remain open; no M08 acceptance is claimed.
The generated capture output is not present in this worktree for a local hash recheck, and the
receipt's exact UTC, commit, command, and named reviewer were not supplied.

## Mandatory Delivery Workflow

The maximum is six concurrent agents overall. The orchestrator proactively fills up to six slots only when genuinely independent todos exist; every active agent owns a distinct todo, path, and evidence lane, with no duplicate work. Launch independent work in parallel, keep dependent steps sequential, and wait for all active lanes before integration and before independent QA. Do not invent busywork merely to fill slots. QA/docs waves may use one to six agents according to genuinely independent scopes. A build wave uses up to six concurrent `SOL HIGH build` instances and never more than six concurrent builders; A/B/C are the base roles and any additional lanes require declared disjoint ownership. The coordinator does not implement shared files, test, review, or write roadmap prose; it owns mechanical integration, status, and git only. `LUNA MAX QA` is verification-only and denies repair/delegation conceptually; it does not repair implementation/configuration or hand acceptance to a builder. The coordinator routes only reproducible blocking findings with an exact task ID to `SOL HIGH`; speculative or non-blocking preferences are not repair work. Future agent-profile and local-gate changes belong to `SOL HIGH` and require parent-process restart plus independent post-restart validation before affecting a gate.

### Build wave

Every implementation or repair wave uses up to six `SOL HIGH build` instances with non-overlapping ownership, declared against the exact `M##` or `R-M##-<n>` ID before work begins. A/B/C are the base roles; D/E/F exist only when their scopes are separately declared:

| Builder | Non-overlapping ownership lane |
| --- | --- |
| `SOL HIGH-A` | Transport/application: FastAPI routes, schemas, settings, CLI, package/launch configuration, and transport-facing implementation tests |
| `SOL HIGH-B` | Domain/provider/persistence: forecast rules, Yahoo/fixture adapters, services, migrations, SQLite, backup/restore, and domain/storage tests |
| `SOL HIGH-C` | Presentation/browser/operations: static UI, browser harness, scripts, Make/local-gate tooling, dependency/runtime tooling, and presentation-facing implementation tests |
| `SOL HIGH-D`–`SOL HIGH-F` | Only a separately declared, disjoint implementation/configuration/test scope |

Each builder reports its exact task ID, changed paths, checks, failures, assumptions, and handoff. No two builders edit the same path. Every implementation/config/test path is assigned to A, B, C, D, E, or F before work starts; the four roadmap docs belong only to `LUNA MAX docs`, and `SESSION-EXPORT.md` belongs only to its export gate. A shared interface is handed to the coordinator for mechanical integration rather than edited concurrently; the coordinator does not author implementation/config/test content.

After every implementation boundary—builder or repair handoff, integration, profile/local-gate change, or other configuration boundary—and before independent QA, run the read-only `/ponytail-review`. Its scope is overengineering only. A clean record is exactly `Ponytail result | boundary: <exact task ID> | finding: none | scope: overengineering only | command: /ponytail-review | environment | UTC | commit | result | artifact | reviewer`; a finding is exactly `Ponytail finding | boundary: <exact task ID> | path:line | overengineering claim | evidence | minimal SOL HIGH repair | QA rerun | environment | UTC | commit | result | artifact | reviewer`. Use an ordinary `R-M##-<n>` only for a reproducible blocking finding. Only `SOL HIGH` repairs it, independent QA retests it, and a missing/unavailable review blocks the boundary. Ponytail never substitutes for correctness, security, accessibility, or performance evidence.

### Wait and verification gates

1. Record the task ID, dependencies, lane manifest, change summary, and one acceptance row per requirement.
2. Run all declared non-overlapping `SOL HIGH build` lanes concurrently, using no more than six.
3. Wait for all active builder reports before integration or acceptance review.
4. Run the mandatory read-only `/ponytail-review` after the boundary and before independent QA, using the exact clean/finding record; a missing or unavailable review blocks the boundary.
5. Only after that wait and review, run independent `LUNA MAX QA` and `LUNA MAX docs` waves. Use one to six agents according to genuinely independent scopes; launch independent work in parallel and keep dependent work sequential. Docs finalizes only after consuming the completed QA record and cannot convert missing QA into a pass.
6. Record every pass, fail, skipped, unavailable, stale, accessibility, restore, secret-review, and connectivity result. A failed or unavailable required gate blocks acceptance.
7. For a failure, create `R-M##-<n>`, route only the reproducible blocking finding to `SOL HIGH`, repair the root cause, repeat the builder handoff, Ponytail review, QA/docs gates, and affected regression checks. Never weaken the acceptance requirement.

The canonical sequence is `R-M00-1` -> `EXP-M00` (**Completed**) -> `M01` (**Completed**) -> `EXP-M01` (**Completed**) -> `M02` (**Completed**) -> `EXP-M02` (**Completed**) -> `M03` (**Completed**) -> `EXP-M03` (**Completed**, exact checkpoint `777451643b5ec1a04a37c013a9caf59f0bd58122`) -> `M04` (**Completed** for exercised scope) -> `EXP-M04` (**Completed**, exact checkpoint recorded above) -> `M05`/`EXP-M05` -> `M06`/`EXP-M06` -> `M07` QA/docs -> `EXP-M07` -> `M08` walkthrough QA/docs -> `ASTRA-FINAL` dedicated visual/mobile/responsive/accessibility review -> `R-ASTRA-<n>` SOL repairs/retests and Astra reevaluation until the result is `Accepted` -> `EXP-M08` -> final learning synthesis -> `EXP-FINAL` -> optional `NOTIFY-FINAL` last. The Astra design/repair/final-checkpoint and learning-synthesis sequence is one second-last operational loop, not a new milestone. No later task may be used to backfill a missing earlier export gate.

## Versioned Export, Commit, Push, And Remote Gates

After each roadmap milestone through M07, before the next milestone starts, complete its exact export task: `EXP-M00`, `EXP-M01`, `EXP-M02`, `EXP-M03`, `EXP-M04`, `EXP-M05`, `EXP-M06`, or `EXP-M07`. `EXP-M08` is the post-Astra checkpoint for the final walkthrough and its retrospective.

1. Use OpenCode `/export`, or a verified CLI equivalent, to overwrite the one tracked root artifact `SESSION-EXPORT.md`.
2. Confirm that the artifact is a full-session export containing tool calls and subagent outputs, not a summary or partial log.
3. Review the complete export for secrets before commit. A skipped, failed, unavailable, or connectivity-blocked secret review blocks the gate.
4. Record the export task ID, export revision, secret-review result, checkpoint commit, pushed branch, exact Git remote revision verification, artifact/link, UTC timestamp, environment, and named reviewer.
5. The coordinator performs the commit/push and verifies the exact Git remote revision. A failed, skipped, unavailable, or connectivity-blocked push or revision check remains exactly that and blocks the checkpoint.

The stable export path is intentionally overwritten; the recorded Git commit/revision versions each export and provide a recoverable checkpoint so work can resume after connectivity loss. Commit/push the reviewed export as checkpoint SHA X, verify that exact SHA on the Git remote, and preserve that receipt in the next checkpoint. The recovered transcript shows an incomplete historical `EXP-M00` attempt, but the current coordinator record completed `EXP-M00` at SHA `18da1af0b6bc31020d3587e472b8197146795bf1` with the exact evidence above. Its handoff did not supply an exact UTC completion timestamp; that limitation remains visible. No GitHub workflow, hosted runner, or external pipeline is used.

After an independently accepted `EXP-FINAL`, an optional operational notification may be referred to as `NOTIFY-FINAL`. It is not a milestone or acceptance task ID and cannot satisfy a missing gate. It may use only a webhook supplied out-of-band by the user and send only a minimal non-secret receipt, such as the accepted result and checkpoint SHA. The endpoint, token, headers, and credential-bearing payload must never be persisted or printed in the repository, `SESSION-EXPORT.md`, artifacts, screenshots, or logs; use a bounded request and redact transport errors. Record bounded success, failure, or unavailable delivery separately without changing the accepted `EXP-FINAL` result. This documentation task performs no notification; `NOTIFY-FINAL` remains the last optional operational item.

## Restored Milestone Acceptance Rows

The condensed plan had omitted the following contract rows. They are restored here and remain open until exact evidence exists; implementation-shaped files do not satisfy them. M01, M02, and M03's scoped behavior records and checkpoints are recorded above. M04 is closed only for its exercised functional scope; its screen-reader row remains pending as `R-M04-30`, and later rows remain open at their own gates.

| Milestone | Required acceptance rows |
| --- | --- |
| `M01` | Company-name lookup must preserve symbol, exchange, stock/ETF asset type, and instrument identity through the API; clean package install, `/api/v1` boundary, and loopback behavior are verified on native x86-64 and local native or explicitly emulated ARM64. Any `.github/workflows/ci.yml` path is removed during M01/M06. |
| `M02` | Saved forecast reopen returns immutable recorded inputs/results; successful, failed, and repeated searches remain auditable; bounded history has no automatic query-history expiry and explicit retention/disk limits are tested. |
| `M03` | Both horizons exclude an in-progress bar and expose origin/target/session semantics; up/down/unchanged, `+/-1%`, `+/-3%`, `+/-5%`, `+/-10%`, conditional gain/loss, and 50/80/95 return/price intervals are defined; company identity, Yahoo approximate 60-day five-minute archive limitation, chronological walk-forward evaluation, baseline comparison, Brier/reliability, interval coverage, and rare-event uncertainty are evidenced. |
| `M04` | Saved reopen is distinct from labelled fresh historical-cutoff reconstruction; historical price and return-distribution charts have text/table equivalents; CSV and JSON exports work; Signal Ledger visual direction is polished at 360/390/768/1280/1440 with no overlap/overflow, tabular numeric hierarchy, all states, reduced motion, WCAG AA, keyboard, and actual assistive-technology evidence. Axe and keyboard do not substitute for screen-reader evidence. |
| `M05` | Automatic due and pre-migration backups, retention/disk limits, non-expiring query history, safe staging/promotion, trust-key transfer/lifecycle, fail-closed missing/wrong-key behavior, bounded chunked-request rejection, watchdog coverage, and protected migration routing are verified. Cross-architecture backup/restore runs x86-64 -> ARM64 and ARM64 -> x86-64 using local native ARM64 when available or labelled emulation otherwise. |
| `M06` | Local native x86-64 receives mandatory deterministic app/UI performance QA in a fresh isolated fixture runtime: five warmups plus at least 30 measured requests, existing RSS/forecast/history thresholds, proposed CPU/readiness/package/backup/restore/static-byte/browser budgets, concurrency elapsed, and one structured artifact per check. Local native ARM64 is used when available; otherwise QEMU/OCI is explicitly emulated for packaging/runtime/functional/build/tool evidence only. Physical ARM64 low-resource performance is `Unavailable` without local native ARM64 hardware and is never inferred from emulation. |
| `M07` | The integrated matrix covers every row above, both architecture paths, both backup directions and trust-key lifecycle, all five viewports and states, actual assistive technology, the complete local user journey, local fail-closed gates, honest ARM64 limitations, and honest out-of-scope classification. Optional dark mode/news are not contract; options/public hosting are out of scope. |
| `M08` | A deterministic-fixture, real-local-app walkthrough under `docs/walkthrough/` (annotated screenshots or accessible GIF plus Markdown/transcript) covers setup through shutdown, all required states/features, actual controls, desktop/mobile accessibility, bounded size, reproducible generation, no secrets/paths, and the prompt/approved-plan retrospective. Retrospective gaps receive `R-M08-<n>` repairs before Astra. |

The M01 and M02 behavior rows above have current independent scoped pass evidence and completed `EXP-M01`/`EXP-M02` checkpoints; M02's checkpoint was completed only by the late `EXP-M02-REPAIR-1` receipt. M03 and `EXP-M03` are completed at exact SHA `777451643b5ec1a04a37c013a9caf59f0bd58122`; M04 and `EXP-M04` are completed for their recorded scopes. M05 is now completed for its declared scope through `R-M05-55`, while `EXP-M05` remains pending; `R-M04-30` remains pending for unavailable screen-reader evidence, and all later rows remain open. Neither `R-M00-1` nor `R-M00-2` accepted implementation behavior.

## Current M06 Evidence Record

`M06` is **In progress**, not released. The row-level statuses below are distinct from
the milestone and export status. `R-M06-55` is the supplied dirty-worktree gate receipt;
the documentation-skill post-restart receipt passed its listed checks, and `EXP-M06`
remains **Pending**.

| Task ID | Status | Exact scoped result | Evidence and limitation |
| --- | --- | --- | --- |
| `R-M06-2` | **Completed** | **Pass** — occupied-port fail-closed | Independent retest supplied; separate row-only session/artifact was not supplied. Final artifact set: `test-results/local-gates/R-M06-55-20260912T045233Z/`; reviewer `LUNA MAX QA`. |
| `R-M06-3` | **Completed** | **Pass** — CSP/host/origin enforcement | Independent retest supplied; separate row-only session/artifact was not supplied. Final artifact set above; reviewer `LUNA MAX QA`. |
| `R-M06-4` | **Completed** | **Pass** — CSV formula safety | Independent retest supplied; separate row-only session/artifact was not supplied. Final artifact set above; reviewer `LUNA MAX QA`. |
| `R-M06-11` | **Completed** | **Pass** — two independent QA passes, each with exact recomputation across three hash-stable native runs | Hash values, row-only session, and UTC window were not supplied; none is invented. Named M06 gate reviewer: `LUNA MAX QA`. |
| [`R-M06-16`](MVP-PLAN.md#r-m06-16) | **Completed** | **Pass** for the supplied independent scope | Row-only locator: [`ponytail-reviews.md#L13-L17`](docs/evidence/ponytail-reviews.md#L13-L17); source receipt: [`ponytail-r-m06-1.txt#L4-L6`](docs/evidence/ponytail-r-m06-1.txt#L4-L6). The retained summary does not name a finer behavior. Final artifact set above; reviewer `LUNA MAX QA`. |
| [`R-M06-17`](MVP-PLAN.md#r-m06-17) | **Completed** | **Pass** for the supplied independent scope | Row-only locator: [`ponytail-reviews.md#L13-L17`](docs/evidence/ponytail-reviews.md#L13-L17); source receipt: [`ponytail-r-m06-1.txt#L4-L6`](docs/evidence/ponytail-r-m06-1.txt#L4-L6). The retained summary does not name a finer behavior. Final artifact set above; reviewer `LUNA MAX QA`. |
| [`R-M06-18`](MVP-PLAN.md#r-m06-18) | **Completed** | **Pass** for the supplied independent scope | Row-only locator: [`ponytail-reviews.md#L13-L17`](docs/evidence/ponytail-reviews.md#L13-L17); source receipt: [`ponytail-r-m06-1.txt#L4-L6`](docs/evidence/ponytail-r-m06-1.txt#L4-L6). The retained summary does not name a finer behavior. Final artifact set above; reviewer `LUNA MAX QA`. |
| [`R-M06-19`](MVP-PLAN.md#r-m06-19) | **Completed** | **Pass** — three `R-M06-15` Ponytail findings repaired | Row-only locator: [`ponytail-reviews.md#L18-L20`](docs/evidence/ponytail-reviews.md#L18-L20); source receipt: [`ponytail-r-m06-15.txt#L4-L6`](docs/evidence/ponytail-r-m06-15.txt#L4-L6). Ponytail remains overengineering-only; reviewer `LUNA MAX QA`. |
| [`R-M06-20`](MVP-PLAN.md#r-m06-20) | **Completed** | **Pass** for the supplied independent scope | Row-only locator: [`ponytail-reviews.md#L13-L17`](docs/evidence/ponytail-reviews.md#L13-L17). The retained summary explicitly records a supplied scoped pass but no finding mapping; final artifact set above; reviewer `LUNA MAX QA`. |
| `R-M06-55` | **Completed** | **Pass** — local `m06` gate | Dirty native x86_64 Linux WSL2/Python `3.11.15`, revision `59534faf1cdce493bc51a11d4adbea5e5b2d6892`, `2026-09-12T04:52:33Z`–`2026-09-12T05:03:44Z`, command `./scripts/local-gate.sh m06`; `264` tests, `89.38%` coverage, browser 32 Pass/2 performance-profile Skipped, official MCP, 4/4 live Yahoo, and labelled emulated-ARM64 package/runtime. Artifact `test-results/local-gates/R-M06-55-20260912T045233Z/evidence.json`; reviewer `LUNA MAX QA`. |

The `R-M06-55` performance summary reports all 13 structured rows present, `12/13`
**Pass**, and ARM64 performance **Unavailable**. The retained Ponytail artifacts are
[`docs/evidence/ponytail-r-m06-1.txt`](docs/evidence/ponytail-r-m06-1.txt) (six findings repaired),
[`docs/evidence/ponytail-r-m06-15.txt`](docs/evidence/ponytail-r-m06-15.txt) (three repaired as `R-M06-19`), and
[`docs/evidence/ponytail-m05-boundary.txt`](docs/evidence/ponytail-m05-boundary.txt) (two repaired as completed repair record
`R-M05-12`; its independent `4/4` behavior rerun is **Pass** inside `R-M05-55 (i)`). Fresh isolated
documentation-skill discovery passed the validator, 20 tests, description parity,
500-line limit, and references. The post-restart receipt is session
`ses_f6aa32d33ffeAvmiFK8K7Cd8EI` at `2026-09-12T11:35:58Z`–
`2026-09-12T11:36:02Z`, native x86_64/OpenCode `1.18.30`, dirty commit
`59534faf1cdce493bc51a11d4adbea5e5b2d6892`; it passed canonical-description discovery,
six Ponytail commands, three profiles, valid configuration, and no-credential checks.
Ingenium onboarding is **Blocked** only on authorized workspace credentials, project
registration, repository-sync dry-run/apply/no-drift, and credential-free evidence.
Actual screen-reader evidence and native/physical ARM64 performance are **Unavailable**.

M06 documentation-boundary checks do not accept implementation behavior or close
`EXP-M06`. `git diff --check -- README.md AGENTS.md MVP-PLAN.md MVP-ROADMAP.md`
returned **Pass** on the dirty local native-x86 revision
`59534faf1cdce493bc51a11d4adbea5e5b2d6892` (UTC was not captured; reviewer
`LUNA MAX docs`). `.dev-venv/bin/python scripts/validate_docs.py` returned **Pass** for
`8` categories and `11` topics at `2026-09-12T12:13:23Z`; the supplied receipt has no
unavailable validator result.

## M06 Mandatory Deterministic Native-x86 Performance And UI Rows

`M06` remains **In progress**. `R-M06-55` independently verified the final scoped
native-x86 receipt, but the dirty worktree receipt is not an M06 export checkpoint.
The rows below require native x86_64 Linux, a fresh isolated deterministic fixture
runtime, an exact commit, isolated process/port/temp resources, and independent
`LUNA MAX QA` review. Reused or dirty runtime state is not silently called fresh.

The existing contract is process RSS `<500 MiB`, defined fixture/cache-hit forecast p95
`<1 s`, indexed 100,000-history query p95 `<250 ms`, and qualitative `negligible` idle
CPU. The final structured artifacts are under
`test-results/local-gates/R-M06-55-20260912T045233Z/performance/` from `R-M06-55`,
native x86_64 Linux WSL2/Python `3.11.15`, dirty revision
`59534faf1cdce493bc51a11d4adbea5e5b2d6892`, command `./scripts/local-gate.sh m06`,
`2026-09-12T04:52:33Z`–`2026-09-12T05:03:44Z`. `R-M06-11` passed twice in
independent QA, with three hash-stable native runs and exact recomputation. Native/physical ARM64
performance is **Unavailable**.

The final measured receipt reports process RSS p95 `139,685,888` bytes, fixture/cache-hit
forecast p95 `121.225 ms`, indexed 100,000-history p95 `3.233 ms`, readiness
`2,433.622 ms`, idle CPU mean `0.1332848089 core-percent`, static total `91,708` raw
bytes, designated response `58` raw bytes, browser render p95 `138.681 ms`, and browser
interaction p95 `21.842 ms`. The performance summary has 13 required rows: `12/13`
are **Pass**, and the ARM64 performance row is **Unavailable**.

| Task ID | Threshold class | Exact future M06 acceptance/evidence row | Required evidence and fail-closed rule | Current result |
| --- | --- | --- | --- | --- |
| `M06` | Proposed protocol | Fresh isolated fixture runtime | New process, deterministic fixture, isolated port/temp directory, exact commit, process tree, cache state, start/end UTC, and cleanup are recorded. | **Pass**; `performance/runtime-isolation.json`; reviewer `LUNA MAX QA`. |
| `M06` | Proposed protocol | Five warmups plus `>=30` measured requests | At least five warmups are excluded and at least 30 raw measured requests are recorded for each designated workload. | **Pass**; `performance/sample-protocol.json`; 5 warmups/30 samples per workload; reviewer `LUNA MAX QA`. |
| `M06` | Existing numeric threshold | Process RSS `<500 MiB` | Peak app/runtime RSS, raw samples, units, measurement method, and process scope are recorded. | **Pass**; `performance/process-rss.json`; p95 `139,685,888` bytes; reviewer `LUNA MAX QA`. |
| `M06` | Existing numeric threshold | Fixture/cache-hit forecast p95 `<1 s` | Forecast route, fixture/input, cache-hit condition, raw samples, errors, and p50/p95/max are recorded. | **Pass**; `performance/fixture-cache-hit-forecast.json`; p95 `121.225 ms`; reviewer `LUNA MAX QA`. |
| `M06` | Existing numeric threshold | Indexed 100,000-history query p95 `<250 ms` and `>=10` repetitions | Exact fixture, schema/index/query plan, repetitions, raw timings, and p50/p95/max are recorded. | **Pass**; `performance/indexed-100k-history-query.json`; p95 `3.233 ms`; reviewer `LUNA MAX QA`. |
| `M06` | Proposed numeric threshold | 60-second idle CPU `<=1 core-percent` | Raw 60-second CPU samples, interval, process scope, normalization, and max are recorded. | **Pass**; `performance/idle-cpu.json`; mean `0.1332848089 core-percent`; reviewer `LUNA MAX QA`. |
| `M06` | Proposed protocol/bound | Concurrency elapsed | Declared levels, warmups, measured batches, p50/p95/max, errors, and peak RSS are recorded. | **Pass**; `performance/concurrency-elapsed.json`; p95 `1003.099 ms`; reviewer `LUNA MAX QA`. |
| `M06` | Proposed numeric threshold | Readiness within `20 s` | Fresh start, command, timestamp, attempts, and elapsed time are recorded. | **Pass**; `performance/readiness.json`; `2,433.622 ms`; raw refused attempts remain visible; reviewer `LUNA MAX QA`. |
| `M06` | Proposed baseline/bound | Package size and clean build time | Package bytes, clean build time, tool/runtime, and bound are recorded. | **Pass**; `performance/package-size-build-time.json`; `112,983` bytes/`944.726 ms`; reviewer `LUNA MAX QA`. |
| `M06` | Proposed baseline/bound | Backup/restore duration and bounds | Fixture/artifact bytes, backup/restore time, RSS, verification, and bounds are recorded. | **Pass**; `performance/backup-restore-duration.json`; p95 `2545.148 ms`; reviewer `LUNA MAX QA`. |
| `M06` | Proposed numeric threshold | Static shell/assets `<96 KiB` and designated response `<8 KiB` | Raw byte semantics, every file/response, compression, and strict bounds are recorded. | **Pass**; `performance/static-and-response-bytes.json`; `91,708` static bytes/`58` response bytes; reviewer `LUNA MAX QA`. |
| `M06` | Proposed browser budgets | Render, interaction, layout, and request budgets | Browser manifest, raw traces, timings, requests, viewport, and console result are recorded. | **Pass**; `performance/browser-budgets.json`; render p95 `138.681 ms`, interaction p95 `21.842 ms`; reviewer `LUNA MAX QA`. |
| `M06` | Evidence rule | Per-check structured artifacts | Every row has a structured artifact with task/row, fixture/isolation, native environment, revision, UTC, command, samples, raw data, classification, result, limitation, path, and reviewer. | **Pass**; `performance/summary.json` reports all 13 rows present and 12 Pass/1 Unavailable; reviewer `LUNA MAX QA`. |
| `M06` | Architecture limitation | Native/physical ARM64 performance | Only qualifying local native ARM64 hardware can produce this result; emulation cannot. | **Unavailable**; `performance/arm64-performance-limitation.json` records no native ARM64 and zero performance samples. |

This gate fails closed. Missing samples, clean fixture, index plan, baseline, bound, raw
data, exact command/commit/time, structured artifact, or named reviewer is not a pass.
No aggregate result may hide a failed, skipped, or unavailable row, and no emulated ARM64
result satisfies a performance row.

## M06 Additional Ingenium Gates

These are three additional acceptance rows inside `M06`, not new milestones or new
repair identifiers. `M06` remains **In progress**; their row-level results remain
distinct from the milestone result. The documentation-skill row has a listed validation
pass, while the Ingenium onboarding row remains blocked on its explicitly listed checks.

| Task ID | Row status | Owner/phase | Verified dependencies and preconditions | Required check and current evidence result |
| --- | --- | --- | --- | --- |
| `M06` | **In progress** | `LUNA MAX docs` records the row; `SOL HIGH` owns any repair; `LUNA MAX QA` independently retests | Pinned Ponytail is vendored/configured. Retained reports: [`docs/evidence/ponytail-r-m06-1.txt`](docs/evidence/ponytail-r-m06-1.txt) (six findings repaired), [`docs/evidence/ponytail-r-m06-15.txt`](docs/evidence/ponytail-r-m06-15.txt) (three repaired as `R-M06-19`), and [`docs/evidence/ponytail-m05-boundary.txt`](docs/evidence/ponytail-m05-boundary.txt) (two repaired as completed repair record `R-M05-12`, independently rerun `4/4` inside `R-M05-55 (i)`). | **Unavailable** for full M06 acceptance: `R-M06-19` is independently **Pass**, but Ponytail remains overengineering-only and does not replace correctness, security, accessibility, or performance evidence. |
| `M06` | **Completed** for the listed validation scope | `LUNA MAX docs` plus post-restart validation | The authored documentation taxonomy and project documentation skill are implemented under `docs/**` and `.opencode/skills/documentation`; fresh isolated discovery passed the validator, 20 tests, description parity, the 500-line limit, and required references. Receipt: session `ses_f6aa32d33ffeAvmiFK8K7Cd8EI`, `2026-09-12T11:35:58Z`–`2026-09-12T11:36:02Z`, native x86_64/OpenCode `1.18.30`, dirty commit `59534faf1cdce493bc51a11d4adbea5e5b2d6892`; canonical description, six registered Ponytail commands, three loaded profiles, valid configuration, and no credentials all passed. `.dev-venv/bin/python scripts/validate_docs.py` **Pass** for `8` categories and `11` topics at `2026-09-12T12:13:23Z`. |
| `M06` | **Blocked** | `LUNA MAX docs` records credential-free onboarding; independent QA verifies the run | The restart precondition is satisfied. Remaining required checks are authorized workspace credentials, project registration, repository-sync dry-run/apply/no-drift, and credential-free evidence. | **Blocked** only on those remaining onboarding checks; no credential, endpoint, or token value is recorded, and no onboarding pass is claimed. |

The rows require exact environment, UTC timestamp, commit, command result, artifact/link,
repair history, limitations, and named independent reviewer when performed. The restart
precondition is evidenced above; any missing credential, workspace, artifact, or reviewer
remains **Unavailable** or **Blocked** and is never promoted from an implementation claim.
No endpoint or token value is recorded here.

### M06 research evidence (not acceptance)

The following three completed read-only Ingenium studies informed this documentation
taxonomy and the additional rows above. Their session IDs are evidence locators only;
they do not substitute for M06 acceptance, QA, a restart, authorized workspace access,
or an export checkpoint.

| Research session | Use | Acceptance meaning |
| --- | --- | --- |
| `ses_f6d4726a7ffeW18Cuf8Hl86PNs` | Read-only Ingenium design research | Research input only; no M06 result |
| `ses_f6d47256cffert6bjT4wan4xvZ` | Read-only Ingenium design research | Research input only; no M06 result |
| `ses_f6d4724b1ffeC2gGE0kc5AgPo2` | Read-only Ingenium design research | Research input only; no M06 result |

The supplied deep read-only research sessions
`ses_f6d219e22ffeQuT1z7fdC3e4MA`, `ses_f6d219dddffeyB2ZTOmnUMJU3Z`, and
`ses_f6d219d92ffewot26Lkx216Lqw` are additional design evidence only. The documentation
records their useful conventions as policy; the authored taxonomy and project skill are
implemented, and the post-restart validation receipt is **Pass** for its listed checks. The
`.dev-venv/bin/python scripts/validate_docs.py` receipt is also **Pass** for `8` categories
and `11` topics at `2026-09-12T12:13:23Z`; Ingenium onboarding remains
blocked on its separately listed checks:

| Convention | Roadmap disposition | Evidence state |
| --- | --- | --- |
| Deny-by-default least privilege | Adopt in permissions, ownership, and credential-file policy. | M06 onboarding remains **Blocked** only on authorized workspace credentials, project registration, repository-sync dry-run/apply/no-drift, and credential-free evidence; the restart precondition is satisfied. |
| Source-versus-live evidence separation | Keep historical research/source reports separate from live acceptance. | `R-M06-55` names the live native-x86 environment, dirty commit, UTC window, artifacts, and reviewer; its scoped result does not close M06 or `EXP-M06`. |
| Structured sanitized errors | Retain as an API and export-safety contract. | Independent QA remains required; this docs reconciliation claims no new behavior pass. |
| Deterministic browser containment with no hidden retries | Use deterministic fixtures, declared requests, and visible failures. | M06/M07 browser/readiness evidence remains future and fail-closed. |
| Bounded process/port/temp artifacts | Make isolation, bounds, and cleanup part of performance artifacts. | `R-M06-55` records process/port/temp bounds and cleanup per structured performance artifact; ARM64 performance remains **Unavailable**. |
| Migration/package/resource checks | Keep these as named local acceptance rows. | Builder/generated output cannot replace independent checks. |
| Optional read-only integrity diagnostic | Permit only as a diagnostic, never as a new gate. | No result is claimed. |

The authored documentation taxonomy and project documentation skill are implemented under
`docs/**` and `.opencode/skills/documentation`; fresh isolated discovery passed the validator,
20 tests, description parity, 500-line limit, and required references. The post-restart receipt
is session `ses_f6aa32d33ffeAvmiFK8K7Cd8EI` at `2026-09-12T11:35:58Z`–
`2026-09-12T11:36:02Z`, native x86_64/OpenCode `1.18.30`, dirty commit
`59534faf1cdce493bc51a11d4adbea5e5b2d6892`; it passed canonical-description discovery,
six Ponytail commands, three profiles, valid configuration, and no-credential checks. The
`.dev-venv/bin/python scripts/validate_docs.py` receipt is **Pass** for `8` categories and
`11` topics at `2026-09-12T12:13:23Z`. The research does not justify auth, MFA, a gateway, a multi-service split,
dual-database restore, direct-route SQL, or replica rate limiting absent a demonstrated
requirement.

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

After `M08` walkthrough QA/docs evidence is complete, independent GPT-6 Astra executes `ASTRA-FINAL`. Astra must include a dedicated final visual-design, mobile, responsiveness, and accessibility quality evaluation of the completed UI and walkthrough, and must confirm working behavior by execution and evidence, not by reading implementation claims. Its matrix must include a separate row for every shipped item—not merely one row per feature—and every row is evaluated against requirements, aesthetics, mobile behavior, responsive behavior, accessibility, and measured performance:

- product feature and acceptance requirement;
- API endpoint, including health/readiness, company-name/instrument lookup, forecast, history/reconstruction/prices, CSV and JSON export, immutable-result, outcome, backup, restore, documentation, and static-asset surfaces discovered in the final route inventory;
- UI click/control and every UI state, including skip navigation, symbol entry/validation, stock/ETF selection, forecast submit, history filters, reconstruction, pagination, export, empty, loading, success, repeated, failed, stale, validation, reduced-motion, and error states;
- desktop/mobile browser journey at 360/390/768/1280/1440, including empty, loading, success, repeated, failed, stale, validation, saved reopen, fresh historical reconstruction, chart/table, export, reduced-motion, accessible keyboard/actual screen-reader, API-only, and security-console journeys;
- persistence effect, including successful/failed/repeated search events, immutable input/results, append-only outcomes/corrections, bounded non-expiring history, restart, automatic/due/pre-migration backup, retention/disk limits, trust-key lifecycle, verification, both-direction cross-architecture restore, and restore promotion.
- every asset, including images, icons, fonts, charts, tables, media item, documentation visual, static shell, stylesheet, script, and other static asset;
- M08 walkthrough artifact, every numbered instruction, screenshot/frame, GIF segment, alt text/caption/transcript, deterministic generation command, artifact-size/no-secret/path review, actual-control browser evidence, desktop/mobile usability, and the retrospective comparing the shipped app with the original prompt and approved plan recovered from `SESSION-EXPORT.md`, including the beautiful/well-designed/usable assessment and every `R-M08-<n>` repair.

Each row records task ID `ASTRA-FINAL`, check/command, environment, UTC timestamp, commit, result, artifact/link, limitation, and reviewer, with explicit evidence for all five evaluation dimensions. Any gap or non-pass creates `R-ASTRA-<n>`. Astra evaluates and suggests only; only `SOL HIGH` build agents implement `R-ASTRA-<n>` UI changes. The repair receives the normal up-to-six-lane build handoff, the mandatory pre-QA Ponytail review, and independent QA/docs gates, then Astra re-evaluates the failed row and affected matrix. If execution evidence shows a tooling, skill, or MCP gap caused poor output, a narrowly scoped `R-ASTRA-<n>` may repair and validate that gap before acceptance; it may not expand scope without a new evidenced requirement. Repeat until the independent record explicitly says **Accepted**. Only then does `EXP-M08` checkpoint the reviewed walkthrough. After all roadmap and Astra repairs, a final pre-`EXP-FINAL` deep learning synthesis must analyze sanitized chat/run evidence, use `skill-maintenance` only for justified reusable Stock Probability development skills, validate and index those skills, and log observations. Only after that record is complete may `EXP-FINAL` sanitize the full chat/export, complete secret review, commit, push, and verify the exact remote revision. `EXP-M08` and `EXP-FINAL` cannot be green before the stated prerequisites; `EXP-M07` is the earlier M07 checkpoint. No Astra or learning-synthesis run is claimed now.

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

The M06 performance rows require one structured artifact per check, with exact task ID,
fixture/process/port/temp identity, native x86_64 environment, commit, UTC start/end,
command, warmups/measured samples, raw resource/request/byte/timing data, p50/p95/max,
threshold class, result, limitation, artifact path, and named independent reviewer. A
missing sample, baseline, index plan, bound, artifact, or reviewer is `Fail` or
`Unavailable`, never an inferred pass. The pre-QA Ponytail record uses the exact clean or
finding format, overengineering-only scope, and cannot replace any correctness, security,
accessibility, or performance check.

## Release Definition Of Done

The roadmap is complete only when:

- `M00` through `M08` have explicit evidence-backed statuses, and no implementation milestone is completed by assertion alone.
- A user-selected Yahoo Finance stock and ETF each demonstrate company-name/instrument identity and both forecast horizons with completed-bar/session semantics, explicit direction/threshold and conditional gain/loss probabilities, 50/80/95 return/price intervals, evaluation evidence, provenance, and honest stale/error/archive limitations.
- SQLite retains successful, failed, and repeated searches; immutable forecast inputs/results; and append-only outcomes, with searchable history through FastAPI `/api/v1` and no browser database access.
- Saved reopen and fresh historical reconstruction are distinct; charts have text equivalents; CSV/JSON export, due/pre-migration backup, retention/disk rules, non-expiring query history, trust-key lifecycle, and both-direction cross-architecture restore have independent evidence.
- Responsive Signal Ledger UI at 360/390/768/1280/1440 has no overlap/overflow, tabular numeric hierarchy, all states, charts/tables, reduced motion, WCAG AA, keyboard/actual screen-reader evidence; secure loopback behavior, bounded local x86-64/ARM64 operation with honest emulation labels, official headless `@playwright/mcp`, browser regressions, useful code comments, and fail-closed local Make/scripts have independent evidence. M06 also has independent structured native-x86 evidence for every performance/UI row, with existing thresholds separated from proposed budgets.
- `README.md` and `AGENTS.md` are reconciled with the final supported scope and evidence; they are roadmap deliverables, not optional commentary.
- M08 has a tracked, lightweight, accessible walkthrough generated from deterministic fixtures against the real local app, with actual-control browser evidence, desktop/mobile instructions, a bounded artifact, and a completed prompt/approved-plan retrospective. Any gap is repaired before Astra.
- `ASTRA-FINAL` is independently **Accepted** after every requirement, feature, endpoint, control, UI state, asset, documentation visual, walkthrough frame/segment, media item, static asset, journey, and persistence row has passed requirements, aesthetics, mobile/responsive, accessibility, and measured-performance evaluation, plus every `R-ASTRA-<n>` retest.
- `EXP-M00` through `EXP-M08` and `EXP-FINAL` contain reviewed, secret-free full-session `SESSION-EXPORT.md` revisions with commit, push, exact Git remote revision verification, and no hidden failed, skipped, unavailable, or blocked field; the final learning synthesis is complete and recorded before `EXP-FINAL`.
- The final deep chat/run learning synthesis is complete before `EXP-FINAL`; only justified reusable Stock Probability skills are created or changed, and they are validated and indexed. The authored documentation taxonomy and project documentation skill are implemented, and the post-restart validation receipt is session `ses_f6aa32d33ffeAvmiFK8K7Cd8EI` at `2026-09-12T11:35:58Z`–`2026-09-12T11:36:02Z`, native x86_64/OpenCode `1.18.30`, dirty commit `59534faf1cdce493bc51a11d4adbea5e5b2d6892`, with its listed checks passed. `.dev-venv/bin/python scripts/validate_docs.py` passed `8` categories and `11` topics at `2026-09-12T12:13:23Z`. No M06 acceptance is claimed from this receipt or implementation presence.
- Optional dark mode/news are not contract requirements; options and public hosting are out of scope for this local app.
