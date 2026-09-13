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
- **Completed for declared scope:** `M05` is closed by the fully passing independent `R-M05-55` receipt: rows `(a)`–`(i)` passed in session `ses_f6bbd6b46ffes2BM2zVjBC5uLg` at `2026-09-12T06:25:04Z`–`2026-09-12T06:44:37Z`, including the `R-M05-12` independent `4/4` behavior-test rerun, and row `(j)` passed in session `ses_f6aa32b01ffexjSm9OhpprFwq4` at `2026-09-12T11:26:29Z`–`2026-09-12T11:28:26Z` with `276` non-live tests/`4` live deselected/`89.51%` coverage, documentation validation of `8` categories/`11` topics/`1` skill, `22` documentation tests, a `77`-file comment audit, Ruff, and mypy. `EXP-M05` is **Completed** at commit `9be15a3ae60b16e7cc7a5b95653f914b578e1a61`; its exact export audit receipt is recorded below. Earlier failures and pending states remain historical evidence.
- **`R-M05-55` receipt metadata:** `LUNA MAX QA` reviewed the native x86_64/`.dev-venv` Python `3.11.15` receipt. Rows `(a)`–`(i)` record round trip/checksum (`06:42:38Z`–`06:42:39Z`), the six-path pre-migration forced-failure matrix (`06:32:09Z`–`06:32:10Z`), due-check `60`/`2678400` accepted and `59`/`2678401`/`nan` rejected, retention of `32` artifacts/`256 MiB` with history preserved (`06:43:54Z`), `13/13` fail-closed negatives (`06:35:29Z`–`06:35:32Z`), key lifecycle with rollback (`06:44:37Z`), `7/7` watchdog probes (`06:35:01Z`–`06:35:02Z`), both-direction **emulated ARM64** cross-architecture restore (`06:25:04Z`–`06:28:44Z`, artifact `test-results/arm64/M05-20260912T034933Z/evidence.json`), and the `R-M05-12` rerun (`06:38:47Z`–`06:38:49Z`). Packaged-CLI end-to-end verification is session `ses_f6a96daceffegfAqyKQL2lf3bS` on native x86_64/Python `3.11.15`, with artifact `/tmp/opencode/stock-probs-m05-cli-20260912T114105Z/M05-packaged-cli-receipt.json` and reviewer `LUNA MAX QA` (fresh-venv wheel install, migration pre-backup, named backup, verify, `restore --promote`, wrong-key/tampered rejection, backup-key rotate/retire, and isolated-port serve readiness). Commands and commits were not supplied and are not inferred.
- **Completed for declared scope:** `M06` closes through final clean-target `R-M06-55` on commit `a69df40e15b3136886f26789c27861184c3bbd77`, run `2026-09-12T14:40:23Z`–`2026-09-12T14:49:48Z`, exit `0`, with `278` tests/`4` live deselected/`89.51%` coverage, browser `32` passed/`2` skipped, official MCP, labelled emulated-ARM64 package/runtime evidence, and `12/13` performance rows **Pass**; ARM64 performance is **Unavailable**. The tree stayed clean before and after; reviewer `LUNA MAX QA`. Earlier dirty receipts remain historical, and actual screen-reader evidence remains **Unavailable**.
- **Completed export:** `EXP-M06` is **Completed** at the same commit. The export audit reports `253` messages, `1,500` parts, `473` tool parts, `212` task outputs, `1,202,095` bytes, `35,447` lines, SHA-256 `f882941a1bac55b9e12b57d7a640256aad5cd1b71fe920f125134147edf516fc`, and `3,334` redaction markers; zero canonical secret-pattern matches; parent `9be15a3`; commit time `2026-09-12T10:39:42-04:00`; message `Record dark mode and news contract`; exact remote-main match; reviewer `LUNA MAX QA`. Export session ID and command were not supplied and are not inferred.
- **Current M09 acceptance:** task `M09`, receipt `M09-E18`, passed
  `TASK_ID=M09 PERFORMANCE_REVIEWER='LUNA MAX QA' ./scripts/local-gate.sh m09` on commit
  `a69df40e15b3136886f26789c27861184c3bbd77` at
  `2026-09-12T17:22:52Z`–`2026-09-12T17:33:03Z`. It recorded `339` tests passed, `4`
  live deselected, `89.62%` coverage, browser `40` passed/`2` expected performance skips,
  official MCP, explicitly labelled emulated ARM64 functional/package/runtime evidence
  via QEMU `7.2.0` on `aarch64` (not native), and `17` executable performance rows
  **Pass** with ARM64 performance **Unavailable**. Artifacts are under
  `test-results/local-gates/M09-20260912T172252Z/`; theme p95 `57.3 ms`, news endpoint
  p95 `1.436 ms`, ten-item render p95 `21.0 ms`, news response `701` bytes, provider
  deadline capped at `10 s`, static `98,068`/`98,304` bytes, and `7` requests. `M09` is
  **Completed for its declared scope**; `R-M09-2` and `R-M09-3` are completed for their
  repaired scopes, with earlier failures retained below. `EXP-M09` is **Pending** for the
  export, secret review, commit, push, and exact remote verification. `M07` is now
  **Completed for its declared scope** by the `M07-E18` receipt below; `EXP-M07` is also
  **Completed** at `779aa749d2f85849427212d890ee6918987492b7`, and M08 was the next walkthrough
  gate at that checkpoint. The current M08, ASTRA-FINAL, and `EXP-M08` records are above.
- **Current M07 integrated release acceptance:** task `M07`, evidence `M07-E18`, ran
  `TASK_ID=M07 PERFORMANCE_REVIEWER='LUNA MAX QA' ./scripts/local-gate.sh release` and
  passed on clean commit `131aabc0fc0528b1e70ba26e09e2c78565ee8d56` at
  `2026-09-12T18:14:08Z`–`2026-09-12T18:21:06Z` on native x86_64 Linux: `396` tests
  passed, `4` live deselected, `89.62%` coverage, browser `40` passed/`2` expected
  performance skips, official MCP, migration with verified pre-migration backup schema v1
  to v4, backup CLI `17` passed, Ponytail interface precondition **Pass**, and `17`
  executable performance rows **Pass** with ARM64 performance **Unavailable**. Artifacts
  are under `test-results/local-gates/M07-20260912T181408Z/`; reviewer `LUNA MAX QA`.
  The two earlier failed release runs and `R-M09-4`/`R-M09-5` repair records remain
  visible as history; `EXP-M07` is now **Completed** at commit
  `779aa749d2f85849427212d890ee6918987492b7`, with its export audit recorded below. M08 is
  next after that checkpoint.
- **Current `EXP-M07` export receipt:** the sanitized export audit reports `281` messages,
  `1,676` parts, `1,341,738` bytes, `39,520` lines, SHA-256
  `fddc25e5dbd0bbea4cd70cf3f124476157bb80e4f2cf9fa2ab969e69f7ace487`, and `3,793`
  redaction markers; secret review found zero canonical secret-pattern matches. Parent:
  `131aabc0fc0528b1e70ba26e09e2c78565ee8d56`; message: `Record integrated acceptance`;
  exact remote `main` match; reviewer: `LUNA MAX QA`. The earlier M07 receipt verification
  also passed with independently recomputed performance rows; its separate command, session,
  environment, UTC, artifact, and reviewer metadata were not supplied.
- **Earlier supplied M08 walkthrough-extension evidence:** `M08` is **In progress** with `20` steps,
  `40` annotated PNGs (`20` desktop at `1280x1000` and `20` mobile at `390x844`), manifest
  SHA-256 `806722ad4321fa3ca25a794192649eb55ad9c55cbba4abf6ec51886ba556df5d`, five companion
  news states represented as evidence rows, `5,683,157` bytes against the `20 MiB` budget,
  and zero undeclared requests or page errors. Independent verification and `EXP-M08` remain
  pending; the later ASTRA findings/repair program is recorded below. Exact generation command,
  session, environment, UTC, commit, artifact path, and named reviewer were not supplied and
  are not inferred.
- **Historical pre-acceptance `ASTRA-FINAL` state (retained):** **In progress**, not
  **Accepted**. Four ASTRA evaluation lanes
  reviewed all `211` matrix rows and produced findings across assets/controls/charts, UI
  states/persistence, theme/news/docs, and the walkthrough. SOL applied 14 repair groups:
  `R-ASTRA-1`–`R-ASTRA-5` CSS/theme defects including the mobile theme selector,
  dark/forced-colors/print contrast, mobile navigation, API-docs label, and chart typography;
  `R-ASTRA-6`–`R-ASTRA-10` app behavior including news terminal states/retry/abort, history
  race and pagination guards, fresh-analysis context, saved-replay truthfulness, validation
  recovery, stale-reason placement, ledger evidence, and chart focus; `R-ASTRA-11` export
  sort-before-cap; `R-ASTRA-12` `theme.js` package verification; `R-ASTRA-13` walkthrough
  quality and the tracked [`docs/walkthrough/`](docs/walkthrough/index.md) artifact (7.19 MiB,
  52 PNGs, instructional transcript, simulation labels, and manifest revision binding); and
  `R-ASTRA-14` news/theme documentation. The static shell was repaired from `102,607` to
  `98,242` bytes, `62` bytes below the `98,304`-byte limit. Independent QA of all 14 repairs
  and ASTRA re-evaluation were **In progress** at that historical point. Exact ASTRA/repair
  commands, sessions, environments, UTC windows, commits, and named reviewers were not
  supplied for that record; `EXP-M08` was then pending.
- **Current `ASTRA-FINAL`:** **Accepted for its declared scope** at clean commit
  `261825838d6788afeb9640db8fbbf3f94af3a82b`, session
  `ses_f679f906cffexS9H5k8Vwk4d16`. The bound receipts cover a `214`-row matrix, record no
  remaining blocking defect and no regression, and explicitly record actual screen-reader,
  physical-mobile, and native/physical ARM64 performance evidence as **Unavailable**. These
  limitations remain visible and are not converted to passes.
- **Completed `EXP-M08`:** commit `7cf1ca8395b94c2e14e5b02ddf160f3f938091d`; export audit
  `303` messages/`1,812` parts, `1,466,585` bytes/`43,137` lines, SHA-256
  `f846722f1c02aefbeb2f784141a022353c91dbf7c9bebde9c68b7a3dc79498d1`, and `4,288`
  redaction markers; zero canonical secret-pattern matches; parent
  `261825838d6788afeb9640db8fbbf3f94af3a82b`; message `Checkpoint instructional walkthrough`;
  exact remote `main` match; reviewer `LUNA MAX QA`. Export command, session, environment,
  and exact export UTC were not supplied and are not inferred.
- **Final release gate:** source evidence `EV-8` records the final `M07` gate on clean commit
  `f511ae3629de679b12c006db5d122b3ed0a22f2c` as **Pass**: `401` tests, `89.61%` coverage,
  browser `48` passed/`2` expected performance skips, and `17` executable performance rows
  passed; ARM64 performance is **Unavailable**. The tracked walkthrough observation is
  `7,660,518` bytes, under the `20 MiB` budget, with artifacts under
  `test-results/local-gates/M07-20260913T005729Z/`.
- **Final learning synthesis:** via `skill-maintenance`, **In progress**. `EXP-FINAL` remains
  **Pending** for synthesis completion and its separate export, secret review, commit, push,
  and exact remote verification.
- **M05 implementation/preparation evidence only:** migration pre-backup, serve due-check with `STOCK_PROBS_BACKUP_INTERVAL_SECONDS` default `86400` and bounds `60`–`2678400`, backup-key rotation/retirement, `32`-artifact/`256 MiB` retention, and non-expiring query history are implemented. `docs/operations/backup-restore.md` and `docs/configure/local-configuration.md` were updated for accuracy by `SOL HIGH`. The earlier M08 capture harness supplied `20` annotated screenshots and manifest SHA-256 `f9fef2b2db0a806cc47ff1db82e1e895f4dd4803425c0cf74426f5fa5a12dd5d`, but that remains preparation evidence only; the current extension is recorded above and in the M08 gate section.
- The following M09 status and boundary bullets retain the pre-consolidated-gate state as
  history; the current declared-scope result and `EXP-M09` pending state are recorded above.
- **Historical pre-acceptance aggregate:** M09 implementation is **Completed for its declared implementation scope**, but `M09` was **In progress** pending the boundary `/ponytail-review`, the consolidated M09 gate, docs finalization, and `EXP-M09`. The supplied scoped QA summary reports `130` news-contract tests plus live ACDC/SPY checks, browser `40` passed/`2` skipped with axe `0/0`, and passing M09 performance rows; its missing session/command/environment/UTC/commit/artifact/reviewer fields are not inferred. `R-M09-1` is the Ponytail-review/local-gate M09 regex repair in flight. M07 was in flight with `R-M07-1` fifth-agent configuration/profile-count test repair in flight, `R-M07-2` Ponytail-review availability pending with findings-only evidence in retained report `test-results/ponytail-m06-m07-boundary.txt` and closure pending, `R-M07-3` completed for supplied repair/test evidence, and `R-M07-4` completed for supplied Ponytail repair evidence; no integrated acceptance or `EXP-M07` was claimed at that earlier state. `M08`, `ASTRA-FINAL`, and `EXP-FINAL` were **Pending** then. `EXP-M01` through `EXP-M06` were completed; later exports were pending at that time.
- The preceding aggregate M07 in-progress wording is retained as immutable pre-acceptance
  history. Current `M07-E18` supersedes it for the declared scope; `R-M07-1`–`R-M07-4`
  and the two earlier failed release runs remain visible below.
- **M09 boundary receipt:** The retained [`test-results/ponytail-m09-boundary.txt`](test-results/ponytail-m09-boundary.txt) report records four overengineering findings and net `-119` possible lines. `SOL HIGH` applied minimal `R-M09-1` repairs: theme/news p95 sampling moved into `tools/browser/tests/performance.spec.js` (net `-25`; supplied `338` tests pass), provider curl stubs were consolidated to one helper (net `-25`; supplied `337` tests pass), CSS aliases were collapsed to one canonical name per role (net `-10`; `dashboard.spec.js` contrast assertions remain in flight), and the redundant static-row re-assertion was deleted. Independent verification of the harness/stub repairs is in flight; the consolidated M09 gate and `EXP-M09` remain **Pending**. Review/repair environment, UTC, commit, independent reviewer, and verification artifact metadata were not supplied and are not inferred.
- **M09 consolidated gate receipt:** The first `TASK_ID=M09 PERFORMANCE_REVIEWER='LUNA MAX QA' ./scripts/local-gate.sh m09` run **Failed** with the intermittent `test_success_repeat_failure_and_searchable_history` result (expected total `2`, observed `3`; known random request-ID/search-collision flake) and reproducible `R-M09-2`: local-gate invoked `scripts/arm64-smoke.sh`, which rejected `TASK_ID=M09` and exited `2` before ARM evidence. The clean rerun reported `338 passed/4 deselected/89.62%`. Independent continuation passed the native package (wheel `121,501` bytes including `theme.js` and `news.json`), browser `40` passed/`2` skipped, official MCP, Ponytail interface, and the M09 performance harness `18/18` rows; ARM64 performance is **Unavailable**. A separate functional/package/runtime smoke passed as **emulated ARM64**. `R-M09-2` and `R-M09-3` (flaky-test determinism) repairs are **In progress**; the consolidated rerun and `EXP-M09` remain **Pending**. Session, environment, UTC, commit, and artifact metadata were not supplied and are not inferred.
- **Current M06 limitations:** The final declared-scope gate does not close actual screen-reader evidence, which remains **Unavailable**, or native/physical ARM64 performance, which remains **Unavailable**. The earlier dirty `R-M06-55` performance artifacts and all earlier failures/skips remain visible as historical evidence; no final release claim is inferred.
- **Supplied Git receipt:** remote `main` was historically reported at `2a7a3bf66c3665552a46d0bd523544a01f894b3f`; it is not a current checkpoint. The old hosted Actions receipt is obsolete x64-only context and not a current gate or release proof. No hosted or external pipeline is an acceptance path; later selective Ingenium agent-pipeline adoption is an operational follow-up only.
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
- **Current documentation refinement:** The ASTRA-based M09 theme/news contract, exact lane manifest, conditional package gate, quality/byte budgets, ten news states, and acceptance rows were added. This remains documentation content only; no implementation, configuration, skill, export, or Git-history change was made.
- **Evidence ledger:**

  | Evidence ID | Requirement/check | Environment, UTC time, commit | Result, artifact, reviewer, limitation |
  | --- | --- | --- | --- |
  | `R-M00-2-E1` | `git status`/`git diff` scope review of the four documentation paths | Current native x86_64 Linux; exact UTC time and commit unavailable; `?? .vscode/` untouched | **Pass** for documentation scope; artifact: current worktree; reviewer: `LUNA MAX docs`; no implementation QA. |
   | `R-M00-2-E2` | Self-review of local-only, ARM64, M08, sequence, vocabulary, and M05 policy changes | Current docs; exact UTC time and commit unavailable | **Pass** as documentation content; artifact: four docs; reviewer: `LUNA MAX docs`; no behavior inferred. |
   | `R-M00-2-E3` | Workflow removal, local gate execution, M08 artifact/browser QA, and retrospective | Not run by this docs-only task | **Unavailable** to `R-M00-2`; current `EXP-M01` separately records the later workflow check, while the remaining M06/M07/M08/Astra evidence is future evidence. |
   | `R-M00-2-E4` | R-M00-1 identity/history and collision aliases retained | Current docs; exact UTC time and commit unavailable | **Pass** as documentation content; reviewer: `LUNA MAX docs`; no repair retest implied. |
   | `R-M00-2-E5` | `git diff --check -- README.md AGENTS.md MVP-PLAN.md MVP-ROADMAP.md` | Current native x86_64 Linux; dirty `HEAD` `9be15a3ae60b16e7cc7a5b95653f914b578e1a61`; UTC was not captured by the command tool | **Pass**; no whitespace errors; artifact: current worktree; reviewer: `LUNA MAX docs`; docs-boundary check only. |
    | `R-M00-2-E6` | `.dev-venv/bin/python scripts/validate_docs.py` | Current native x86_64 Linux; dirty `HEAD` `9be15a3ae60b16e7cc7a5b95653f914b578e1a61`; UTC was not captured; execution was denied by the tool permission boundary | **Unavailable**; no validator result is inferred; artifact: none; reviewer: `LUNA MAX docs`; rerun is required when command execution is available. |
    | `R-M00-2-E7` | Documentation scope review with `git status --short` and `git diff --name-only -- README.md AGENTS.md MVP-PLAN.md MVP-ROADMAP.md` | Current native x86_64 Linux; dirty `HEAD` above; UTC was not captured | **Pass** for this task's four-path diff; pre-existing dirty `.opencode/` and `tests/` paths were observed and untouched; reviewer: `LUNA MAX docs`. |
    | `R-M00-2-E8` | M09 root-documentation self-review: ASTRA rejected scope, the exact ten news UI states, and HTTP status semantics retained across the four owned root documents | Current native x86_64 Linux; dirty `HEAD` `9be15a3ae60b16e7cc7a5b95653f914b578e1a61`; UTC timestamp unavailable from the command tool | **Pass** as documentation content; artifact: `README.md`, `AGENTS.md`, `MVP-PLAN.md`, and `MVP-ROADMAP.md`; reviewer: `LUNA MAX docs`; no M09 implementation or QA acceptance inferred. |
     | `R-M00-2-E9` | `.dev-venv/bin/python scripts/validate_docs.py` after the M09 root-documentation update | Current native x86_64 Linux; dirty `HEAD` `9be15a3ae60b16e7cc7a5b95653f914b578e1a61`; UTC timestamp unavailable from the command tool | **Unavailable**; the command execution was denied by the tool permission boundary, so no validator result is inferred; artifact: none; reviewer: `LUNA MAX docs`; rerun remains required when execution is available. |
     | `R-M00-2-E10` | `git diff --check -- README.md AGENTS.md MVP-PLAN.md MVP-ROADMAP.md` after the M09 root-documentation update | Current native x86_64 Linux; dirty `HEAD` `9be15a3ae60b16e7cc7a5b95653f914b578e1a61`; UTC timestamp unavailable from the command tool | **Pass**; no whitespace errors; artifact: current four-document worktree diff; reviewer: `LUNA MAX docs`; no Git mutation performed. |
     | `R-M00-2-E11` | `.dev-venv/bin/python scripts/validate_docs.py` after the current M09/adoption root-documentation update | Current command attempt; execution was denied by the tool permission boundary; UTC and commit were not captured | **Unavailable**; no current validator pass is inferred; artifact: none; reviewer: `LUNA MAX docs`; rerun remains required when execution is available. |
     | `R-M00-2-E12` | `git diff --check -- README.md AGENTS.md MVP-PLAN.md MVP-ROADMAP.md` after the current M09/adoption root-documentation update | Current dirty worktree; UTC and commit were not captured by the command tool | **Pass**; no whitespace errors; artifact: current four-document worktree diff; reviewer: `LUNA MAX docs`; no Git mutation performed. |
      | `R-M00-2-E13` | `.dev-venv/bin/python scripts/validate_docs.py` after this M09 boundary-receipt root-documentation update | Current native x86_64 Linux; dirty `HEAD` `a69df40e15b3136886f26789c27861184c3bbd77`; UTC was not captured; execution was denied by the tool permission boundary | **Unavailable**; no current validator pass is inferred; artifact: none; reviewer: `LUNA MAX docs`; rerun remains required when execution is available. |
      | `R-M00-2-E14` | `git diff --check -- README.md AGENTS.md MVP-PLAN.md MVP-ROADMAP.md` after this M09 boundary-receipt root-documentation update | Current native x86_64 Linux; dirty `HEAD` `a69df40e15b3136886f26789c27861184c3bbd77`; UTC was not captured by the command tool | **Pass**; no whitespace errors; artifact: current four-document worktree diff; reviewer: `LUNA MAX docs`; no Git mutation performed. |
       | `R-M00-2-E15` | `.dev-venv/bin/python scripts/validate_docs.py` after this consolidated M09 gate-state root-documentation update | Current native x86_64 Linux; dirty `HEAD` `a69df40e15b3136886f26789c27861184c3bbd77`; UTC was not captured; execution was denied by the tool permission boundary | **Unavailable**; no current validator pass is inferred; artifact: none; reviewer: `LUNA MAX docs`; rerun remains required when execution is available. |
       | `R-M00-2-E16` | `git diff --check -- README.md AGENTS.md MVP-PLAN.md MVP-ROADMAP.md` after this consolidated M09 gate-state root-documentation update | Current native x86_64 Linux; dirty `HEAD` `a69df40e15b3136886f26789c27861184c3bbd77`; UTC was not captured by the command tool | **Pass**; no whitespace errors; artifact: current four-document worktree diff; reviewer: `LUNA MAX docs`; no Git mutation performed. |
        | `R-M00-2-E17` | `.dev-venv/bin/python scripts/validate_docs.py` after this M09 acceptance root-documentation update | Current native x86_64 Linux; dirty `HEAD` `a69df40e15b3136886f26789c27861184c3bbd77`; UTC was not captured; execution was denied by the tool permission boundary | **Unavailable**; no current validator pass is inferred; artifact: none; reviewer: `LUNA MAX docs`; no implementation or M09 acceptance is inferred from this unavailable check. |
        | `R-M00-2-E18` | `git diff --check -- README.md AGENTS.md MVP-PLAN.md MVP-ROADMAP.md` after this M09 acceptance root-documentation update | Current native x86_64 Linux; dirty `HEAD` `a69df40e15b3136886f26789c27861184c3bbd77`; UTC was not captured by the command tool | **Pass**; no whitespace errors; artifact: current four-document worktree diff; reviewer: `LUNA MAX docs`; no Git mutation performed. |
        | `R-M00-2-E19` | `.dev-venv/bin/python scripts/validate_docs.py` after this M07 integrated-acceptance root-documentation update | Current native x86_64 Linux; dirty `HEAD` `131aabc0fc0528b1e70ba26e09e2c78565ee8d56`; UTC was not captured; the tool permission boundary denied execution | **Unavailable**; no validator pass is inferred; artifact: none; reviewer: `LUNA MAX docs`; no implementation or Git acceptance inferred. |
         | `R-M00-2-E20` | `git diff --check -- README.md AGENTS.md MVP-PLAN.md MVP-ROADMAP.md` after this M07 integrated-acceptance root-documentation update | Current native x86_64 Linux; dirty `HEAD` `131aabc0fc0528b1e70ba26e09e2c78565ee8d56`; UTC was not captured by the command tool | **Pass**; no whitespace errors; artifact: current four-document worktree diff; reviewer: `LUNA MAX docs`; no Git mutation performed. |
         | `R-M00-2-E21` | `.dev-venv/bin/python scripts/validate_docs.py` after this M07-export/M08-extension root-documentation update | Current native x86_64 Linux; dirty `HEAD` `779aa749d2f85849427212d890ee6918987492b7`; UTC was not captured; execution was denied by the tool permission boundary | **Unavailable**; no current validator pass is inferred; artifact: none; reviewer: `LUNA MAX docs`; rerun remains required when execution is available. |
         | `R-M00-2-E22` | `git diff --check -- README.md AGENTS.md MVP-PLAN.md MVP-ROADMAP.md` after this M07-export/M08-extension root-documentation update | Current native x86_64 Linux; dirty `HEAD` `779aa749d2f85849427212d890ee6918987492b7`; UTC was not captured by the command tool | **Pass**; no whitespace errors; artifact: current four-document worktree diff; reviewer: `LUNA MAX docs`; no Git mutation performed. |
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
| `M05` | Backup, restore, and secure loopback operations | M02, M04 | Completed for declared scope | `R-M05-55` is fully **Pass** for rows `(a)`–`(j)`, including the `R-M05-12` `4/4` behavior rerun inside `(i)` and the `(j)` aggregate recorded in the M05 evidence section. `EXP-M05` is **Completed** at `9be15a3ae60b16e7cc7a5b95653f914b578e1a61`; see its export audit receipt below. |
| `M06` | Local QA, MCP, browser regressions, and fail-closed gates | M01, M02, M03, M04, M05 | Completed for declared scope | Final clean-target `R-M06-55` passed on `a69df40e15b3136886f26789c27861184c3bbd77` with `278` tests/`4` live deselected/`89.51%`, browser `32` passed/`2` skipped, official MCP, labelled emulated-ARM64 package/runtime, and `12/13` performance rows Pass with ARM64 performance Unavailable; tree clean before/after, reviewer `LUNA MAX QA`. Actual screen-reader evidence remains Unavailable; earlier dirty evidence is retained. `EXP-M06` is Completed at the same checkpoint; see the receipts below. |
| `M09` | Dark Mode And News | M06, `EXP-M06` | Completed for declared scope | `M09-E18` consolidated gate passed on `a69df40e15b3136886f26789c27861184c3bbd77`; `R-M09-2` and `R-M09-3` are completed for their repaired scopes, with the earlier flake and ARM-smoke task-ID failure retained below. `EXP-M09` remains Pending for export, secret review, commit, push, and exact remote verification. The M07 integrated receipt is recorded below. |
| `M07` | Integrated MVP acceptance | M06, `EXP-M06`, M09, `EXP-M09` | **Completed for declared scope** | `M07-E18` release gate passed on clean commit `131aabc0fc0528b1e70ba26e09e2c78565ee8d56` with `396` tests, browser `40`/`2` expected performance skips, migration/pre-backup schema v1→v4, backup CLI `17` passed, Ponytail interface precondition Pass, and `17` executable performance rows Pass; ARM64 performance is Unavailable. `EXP-M07` is **Completed** at `779aa749d2f85849427212d890ee6918987492b7`; its export audit is recorded below. Earlier failed release runs and `R-M09-4`/`R-M09-5` remain historical; the separate `EXP-M09` pending state is retained in its own record. |
| `M08` | Instructional Walkthrough | M07, `EXP-M07` | **Completed for declared scope** | The earlier `20`-step/`40`-PNG extension report and later ASTRA repair records remain historical evidence. The bound final release observation is `7,660,518` bytes under the `20 MiB` budget; `ASTRA-FINAL` is accepted for its declared scope and `EXP-M08` is **Completed** at `7cf1ca8395b94c2e14e5b02ddf160f3f938091d3`. The final learning synthesis remains **In progress** and `EXP-FINAL` remains **Pending**. |

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
`EXP-M05` is completed in the separate checkpoint recorded below.

| Task ID | Status | Evidence and current result | Limitation/next gate |
| --- | --- | --- | --- |
| `R-M05-5` | **Completed** | Malicious-backup closure evidence covers unsafe archive/member, transferred/wrong-key, lost-key, and retention/storage cases in `tests/test_backup_cli.py`; the later `R-M05-55 (a)`–`(i)` receipt closes the declared scope. | **Pass** in the fully passing `R-M05-55` scope. Exact receipt sessions, windows, native environment, and reviewer are recorded below; command and commit were not supplied. |
| `R-M05-6` | **Completed** | Chunked-request falsification is represented by `tests/test_m05_request_limits.py`. Supplied `test-results/arm64/M05-20260912T034933Z/evidence.json` reports both x86-64 -> emulated ARM64 and emulated ARM64 -> x86-64 restore directions; the later `R-M05-55 (a)`–`(i)` receipt closes the declared scope. | **Pass** in the fully passing `R-M05-55` scope; the emulated artifact remains functional evidence only, not native ARM64 or performance evidence. Exact receipt sessions, windows, native environment, and reviewer are recorded below; command and commit were not supplied. |
| `R-M05-7` | **Completed** | The supplied finding records an insufficient due-check watchdog. Initial result: **Fail**; closure is carried by `R-M05-8`/`R-M05-11` and the later `R-M05-55 (a)`–`(i)` receipt. | **Pass** for the declared M05 scope; the initial failure remains visible. Exact receipt sessions, windows, native environment, and reviewer are recorded below; command and commit were not supplied. |
| `R-M05-8` / `R-M05-11` | **Completed** | The supplied repair statement covers due-check, creation, internal verification, pre-migration, serve startup, and public verify/restore; the later `R-M05-55 (a)`–`(i)` receipt closes the declared scope. | **Pass** in the fully passing `R-M05-55` scope. Exact receipt sessions, windows, native environment, and reviewer are recorded below; command and commit were not supplied. |
| `R-M05-9` | **Completed** | Walkthrough comment repair is retained; row `(j)` of `R-M05-55` includes the independent `77`-file comment audit. | **Pass** in the fully passing `R-M05-55` scope. Exact receipt sessions, windows, native environment, and reviewer are recorded below; command and commit were not supplied. |
| `R-M05-10` | **Completed** | All migrating CLI commands route through the protected pre-migration path in the supplied evidence; the later `R-M05-55 (a)`–`(i)` receipt closes the declared scope. | **Pass** in the fully passing `R-M05-55` scope. Exact receipt sessions, windows, native environment, and reviewer are recorded below; command and commit were not supplied. |
| `R-M05-12` | **Completed** | Ponytail repair record: [`docs/evidence/ponytail-m05-boundary.txt`](docs/evidence/ponytail-m05-boundary.txt) records the two findings and repair. `R-M05-55 (i)` independently reran the affected behavior tests: `4/4` **Pass**. | **Pass** for the independent rerun inside `R-M05-55 (i)`; the receipt retained at `docs/evidence/ponytail-m05-boundary.txt` is overengineering-only. Exact rerun session, window, native environment, and reviewer are recorded below; command and commit were not supplied. |
| `R-M05-55` | **Completed** | Fully passing consolidated M05 QA: rows `(a)`–`(i)` passed earlier and row `(j)` passed on rerun. | **Pass** for the declared M05 scope; exact sessions, windows, native environments, artifacts, and reviewer are recorded below. `EXP-M05` is completed in the separate checkpoint below; commands and commits for this scoped receipt were not supplied. |

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
`docs/configure/local-configuration.md` were updated for accuracy by `SOL HIGH`. At that
historical M05 documentation boundary the `LUNA MAX docs` profile could not edit `docs/**`,
so `SOL HIGH` performed those authored-docs repairs; that earlier profile gap remains visible
and is not independent QA or M05 verification. The later supplied adoption state grants
`luna-docs` `docs/**` permission, but it is not gate-active until restart and independent
validation.

`EXP-M05` is **Completed** at the exact checkpoint recorded below. The export audit,
secret review, commit, push, and exact remote-main match are separate from the completed
`R-M05-55` behavior scope; earlier failures and pending states remain visible.

### `EXP-M05` completed export checkpoint

- **Status:** Completed.
- **Owner/phase:** coordinator export/checkpoint gate; reviewer `LUNA MAX QA`.
- **Dependencies verified:** M05 declared scope and independent `R-M05-55` closure; earlier failures and pending states remain historical evidence.
- **Change summary:** The sanitized full-session `SESSION-EXPORT.md` received the supplied export audit, secret review, commit, push, and exact remote-main verification. This roadmap reconciliation did not edit the export or implementation/configuration/skill/test paths.

| Evidence ID | Requirement/check | Environment, UTC time, commit | Result, artifact, reviewer, limitation |
| --- | --- | --- | --- |
| `EXP-M05-E1` | Parse/inventory: `233` messages, `1,387` parts, `432` tool parts, `185` task outputs, `1,116,276` bytes, `32,915` lines, SHA-256 `ce5f025d41c4757dcf95a336555ce0fdd46ddcf22d1e9bce68d2d8fb5328c181`, and `3,090` redaction markers | Supplied export audit receipt; commit `9be15a3ae60b16e7cc7a5b95653f914b578e1a61`, parent `59534faf1cdce493bc51a11d4adbea5e5b2d6892`, commit UTC `2026-09-12T12:41:32Z` | **Pass**; artifact: sanitized `SESSION-EXPORT.md`; reviewer `LUNA MAX QA`; export session ID and command were not supplied. |
| `EXP-M05-E2` | Full secret review across all canonical secret patterns | Same supplied receipt and checkpoint commit | **Pass**; zero matches; artifact: export audit; reviewer `LUNA MAX QA`. |
| `EXP-M05-E3` | Commit message, parent, push, and exact remote `main` match | Commit `9be15a3ae60b16e7cc7a5b95653f914b578e1a61`; parent `59534faf1cdce493bc51a11d4adbea5e5b2d6892`; commit UTC `2026-09-12T12:41:32Z`; message `Add verified backup operations` | **Pass**; exact `origin/main` match; artifact: Git checkpoint receipt; reviewer `LUNA MAX QA`. |

- **Repair/history:** The completed export checkpoint does not erase earlier M05 failures or pending states; `R-M05-55` remains the independent behavior/operations closure receipt and `EXP-M05` is the separate export gate.
- **Limitations:** The supplied receipt does not provide an export session ID, command, separate export-audit UTC window, or additional check; none is inferred. No external/hosted pipeline result is claimed.
- **Export/Git:** exact checkpoint `9be15a3ae60b16e7cc7a5b95653f914b578e1a61`, parent `59534faf1cdce493bc51a11d4adbea5e5b2d6892`, message `Add verified backup operations`, commit UTC `2026-09-12T12:41:32Z`, and exact `origin/main` match; reviewer `LUNA MAX QA`.

### Historical M08 preparation (not acceptance)

At that earlier preparation point, the supplied capture-harness receipt reported `20` annotated screenshots and manifest SHA-256
`f9fef2b2db0a806cc47ff1db82e1e895f4dd4803425c0cf74426f5fa5a12dd5d`. `M08`, walkthrough
QA, the retrospective, `ASTRA-FINAL`, and `EXP-M08` remained open; no M08 acceptance was claimed.
The generated capture output is not present in this worktree for a local hash recheck, and the
receipt's exact UTC, commit, command, and named reviewer were not supplied.

The current walkthrough-extension evidence is recorded in the M08 gate section below; it does
not replace this historical preparation record.

## Mandatory Delivery Workflow

The maximum is six concurrent agents overall. The orchestrator proactively fills up to six slots only when genuinely independent todos exist; every active agent owns a distinct todo, path, and evidence lane, with no duplicate work. Launch independent work in parallel, keep dependent steps sequential, and wait for all active lanes before integration and before independent QA. Do not invent busywork merely to fill slots. QA/docs waves may use one to six agents according to genuinely independent scopes. A build wave uses up to six concurrent `SOL HIGH build` instances and never more than six concurrent builders; A/B/C are the base roles and any additional lanes require declared disjoint ownership. The coordinator does not implement shared files, test, review, or write roadmap prose; it owns mechanical integration, status, and git only. `LUNA MAX QA` is verification-only and denies repair/delegation conceptually; it does not repair implementation/configuration or hand acceptance to a builder. The coordinator routes only reproducible blocking findings with an exact task ID to `SOL HIGH`; speculative or non-blocking preferences are not repair work. Future agent-profile and local-gate changes belong to `SOL HIGH` and require parent-process restart plus independent post-restart validation before affecting a gate.

The stock Playwright MCP entry in `opencode.json` is a hard orchestration/product
invariant: retain `./scripts/playwright-mcp.sh` with `--headless`, `--isolated`, and
loopback host/origin allowlists. Selective Ingenium pipeline adoption must never replace
that entry with Ingenium browser automation. The no-plugin subagent-count control, if
adopted, uses the valid `agent.options` field on the orchestrator profile; the orchestrator
reads it, the schema has no native concurrency cap, and `subagent_depth` controls nesting
only.

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

The canonical sequence is `R-M00-1` -> `EXP-M00` (**Completed**) -> `M01` (**Completed**) -> `EXP-M01` (**Completed**) -> `M02` (**Completed**) -> `EXP-M02` (**Completed**) -> `M03` (**Completed**) -> `EXP-M03` (**Completed**, exact checkpoint `777451643b5ec1a04a37c013a9caf59f0bd58122`) -> `M04` (**Completed** for exercised scope) -> `EXP-M04` (**Completed**, exact checkpoint recorded above) -> `M05`/`EXP-M05` -> `M06`/`EXP-M06` -> `M09` QA/docs -> `EXP-M09` -> `M07` QA/docs -> `EXP-M07` -> `M08` walkthrough QA/docs -> `ASTRA-FINAL` dedicated visual/mobile/responsive/accessibility review -> `R-ASTRA-<n>` SOL repairs/retests and Astra reevaluation until the result is `Accepted` -> `EXP-M08` -> final learning synthesis -> `EXP-FINAL` -> optional `NOTIFY-FINAL` last. The Astra design/repair/final-checkpoint and learning-synthesis sequence is one second-last operational loop, not a new milestone. No later task may be used to backfill a missing earlier export gate.

## Versioned Export, Commit, Push, And Remote Gates

Before the next milestone starts, complete the preceding milestone's exact export task: `EXP-M00`, `EXP-M01`, `EXP-M02`, `EXP-M03`, `EXP-M04`, `EXP-M05`, `EXP-M06`, `EXP-M09`, or `EXP-M07`. `EXP-M08` is the post-Astra checkpoint for the final walkthrough and its retrospective.

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
| `M09` | Dark mode is user-selectable and accessible across the dashboard, charts, tables, controls, focus states, and required states/viewports; selected-instrument news is clearly labelled, served through `/api/v1`, preserves identity and source/as-of provenance, and exposes honest loading, empty, stale, and failure states. Both features receive independent QA/docs evidence before `EXP-M09`. |
| `M07` | The integrated matrix covers every row above, including M09 dark mode/news, both architecture paths, both backup directions and trust-key lifecycle, all five viewports and states, actual assistive technology, the complete local user journey, local fail-closed gates, honest ARM64 limitations, and honest out-of-scope classification. Options/public hosting are out of scope. |
| `M08` | A deterministic-fixture, real-local-app walkthrough under `docs/walkthrough/` (annotated screenshots or accessible GIF plus Markdown/transcript) covers setup through shutdown, all required states/features including M09 dark mode/news, actual controls, desktop/mobile accessibility, bounded size, reproducible generation, no secrets/paths, and the prompt/approved-plan retrospective. Retrospective gaps receive `R-M08-<n>` repairs before Astra. |

The M01 and M02 behavior rows above have current independent scoped pass evidence and completed `EXP-M01`/`EXP-M02` checkpoints; M02's checkpoint was completed only by the late `EXP-M02-REPAIR-1` receipt. M03 and `EXP-M03` are completed at exact SHA `777451643b5ec1a04a37c013a9caf59f0bd58122`; M04 and `EXP-M04` are completed for their recorded scopes. M05 and `EXP-M05` are completed for their recorded scopes; `R-M04-30` remains pending for unavailable screen-reader evidence, and all later rows remain open. Neither `R-M00-1` nor `R-M00-2` accepted implementation behavior.

## Current M06 Evidence Record

`M06` is **Completed for its declared scope**, not final release. The row-level statuses
below retain their historical detail, while the final clean-target `R-M06-55` receipt and
the separate `EXP-M06` checkpoint close the declared M06 scope. Actual screen-reader
evidence and native/physical ARM64 performance remain **Unavailable**.

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
| `R-M06-55` | **Completed** | **Pass** — earlier dirty-worktree local `m06` gate; final clean-target closure is recorded below | Dirty native x86_64 Linux WSL2/Python `3.11.15`, revision `59534faf1cdce493bc51a11d4adbea5e5b2d6892`, `2026-09-12T04:52:33Z`–`2026-09-12T05:03:44Z`, command `./scripts/local-gate.sh m06`; `264` tests, `89.38%` coverage, browser 32 Pass/2 performance-profile Skipped, official MCP, 4/4 live Yahoo, and labelled emulated-ARM64 package/runtime. Artifact `test-results/local-gates/R-M06-55-20260912T045233Z/evidence.json`; reviewer `LUNA MAX QA`. This historical dirty receipt is retained and does not replace the clean-target receipt. |

#### `R-M06-55` final clean-target closure receipt

- **Status:** `Completed` for the declared M06 scope; **Pass**.
- **Owner/phase:** independent `LUNA MAX QA` final M06 gate; this roadmap records the
  supplied receipt and does not rerun implementation checks.
- **Dependencies verified:** the independently passed M06 scoped rows above, the retained
  earlier dirty receipt, and the M06 performance limitation row.
- **Evidence:** final clean-target gate on commit
  `a69df40e15b3136886f26789c27861184c3bbd77`, native x86_64 Linux, exit `0`,
  `2026-09-12T14:40:23Z`–`2026-09-12T14:49:48Z`; `278` tests, `4` live deselected,
  `89.51%` coverage, browser `32` passed/`2` skipped, official MCP, and explicitly
  labelled emulated-ARM64 package/runtime evidence. The structured performance receipt
  has `12/13` rows **Pass** and ARM64 performance **Unavailable**. The tree was clean
  before and after. The command and artifact path were not supplied; no value is inferred.

#### `EXP-M06` completed export checkpoint

- **Status:** `Completed`.
- **Owner/phase:** coordinator export/checkpoint gate; reviewer `LUNA MAX QA`.
- **Dependencies verified:** final declared-scope `R-M06-55` closure and its recorded
  limitations; earlier dirty receipts remain historical.
- **Evidence ledger:**

  | Evidence ID | Requirement/check | Environment, UTC time, commit | Result, artifact, reviewer, limitation |
  | --- | --- | --- | --- |
  | `EXP-M06-E1` | Sanitized full-session export audit: `253` messages, `1,500` parts, `473` tool parts, `212` task outputs, `1,202,095` bytes, `35,447` lines, SHA-256 `f882941a1bac55b9e12b57d7a640256aad5cd1b71fe920f125134147edf516fc`, and `3,334` redaction markers | Commit `a69df40e15b3136886f26789c27861184c3bbd77`; commit time `2026-09-12T10:39:42-04:00`; parent `9be15a3` | **Pass**; artifact: sanitized `SESSION-EXPORT.md`; reviewer `LUNA MAX QA`; export session ID and command were not supplied. |
  | `EXP-M06-E2` | Full canonical secret review | Same checkpoint | **Pass**; zero canonical secret-pattern matches; reviewer `LUNA MAX QA`. |
  | `EXP-M06-E3` | Commit message, push, and exact remote `main` match | Commit `a69df40e15b3136886f26789c27861184c3bbd77`; message `Record dark mode and news contract`; exact `origin/main` match | **Pass**; reviewer `LUNA MAX QA`. |

- **Repair/history:** No earlier M06 failure, skip, unavailable hardware/provider result,
  screen-reader limitation, or dirty receipt is erased by this clean-target closure.
- **Limitations:** actual screen-reader evidence remains **Unavailable**; ARM64
  performance remains **Unavailable** because no native/physical ARM64 result is claimed.
  No external/hosted pipeline result is claimed.
- **Export/Git:** exact local/remote checkpoint
  `a69df40e15b3136886f26789c27861184c3bbd77`; parent `9be15a3`; exact remote-main match;
  export session ID and command were not supplied and are not inferred.

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

M06 documentation-boundary checks do not accept implementation behavior; the separate
`R-M06-55` and `EXP-M06` receipts above close the declared scope/checkpoint.
`git diff --check -- README.md AGENTS.md MVP-PLAN.md MVP-ROADMAP.md`
returned **Pass** on the dirty local native-x86 revision
`59534faf1cdce493bc51a11d4adbea5e5b2d6892` (UTC was not captured; reviewer
`LUNA MAX docs`). The earlier `.dev-venv/bin/python scripts/validate_docs.py` receipt
returned **Pass** for `8` categories and `11` topics at `2026-09-12T12:13:23Z`; the
current reconciliation rerun was **Unavailable** because the tool permission boundary
denied execution, so no current validator pass is inferred.

## M06 Mandatory Deterministic Native-x86 Performance And UI Rows

`M06` is **Completed for its declared scope**. This section retains the historical dirty
worktree performance receipt and its row-level evidence; the clean-target closure and
export checkpoint are recorded above.
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

These are three additional acceptance rows inside the completed declared M06 scope, not
new milestones or new repair identifiers. Their row-level results remain distinct from the
milestone result. The documentation-skill row has a listed validation pass, while the
Ingenium onboarding row remains blocked on its explicitly listed checks.

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
| Source-versus-live evidence separation | Keep historical research/source reports separate from live acceptance. | The earlier dirty `R-M06-55` receipt names its native-x86 environment, UTC window, artifacts, and reviewer; it does not by itself close M06 or `EXP-M06`, which are closed by the clean-target receipts above. |
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

## M09 Dark Mode And News

`M09` is **Completed for its declared scope** through the consolidated `M09-E18` receipt.
`EXP-M06` is complete, and the frozen ASTRA/interface decisions, feasibility proof, earlier
scoped QA summary, failed first gate, and current gate are recorded here and in the plan.
`EXP-M09` remains **Pending** for the export, secret review, commit, push, and exact remote
verification. The integrated `M07-E18` receipt is recorded below; it does not close
`EXP-M09` or invent its missing export evidence.

- **Dependencies:** completed declared-scope `M06` and completed `EXP-M06`; the recorded
  M07 release receipt consumes the declared M09 scope, while `EXP-M09` remains a separate
  pending export state.
- **Scope:** Add a user-selectable accessible dark mode across the dashboard and `/api/v1/docs`,
  plus a clearly labelled selected-instrument news view. News uses FastAPI `/api/v1`, preserves
  instrument identity and source/as-of provenance, and exposes the ten documented UI states.
  The final UI, M08 walkthrough, and `ASTRA-FINAL` matrix must include both features.
- **Explicitly rejected scope (ASTRA plan):** Settings database, news archive, article
  scraper/proxy, sentiment engine, forecast/model/probability changes, Redis or external
  cache, background scheduler, service worker, separate service, notification feed, full-text
  search, watchlist, personalized ranking, and any additional market-data provider remain
  out of scope unless a new evidenced requirement is approved. No current M09 task
  authorizes or accepts one of these additions.
- **Planning limitation:** The separate ASTRA research first pass remains **Blocked** by the
  external-directory permission boundary; this planning state is not a research receipt or
  `ASTRA-FINAL` acceptance.
- **QA/docs gate:** The earlier scoped QA summary reports `130` news-contract tests plus
  live ACDC/SPY checks, browser `40` passed/`2` skipped with axe `0/0`, and earlier
  performance rows; its missing metadata remains unavailable. The current `M09-E18`
  consolidated gate supplies the exact command, commit, UTC window, native/emulated
  environment labels, artifact directory, reviewer, browser/MCP result, and performance
  rows for the declared scope. `EXP-M09` remains the separate pending export gate.

#### M09 scoped implementation and QA receipt

Task ID `M09` implementation is **Completed** for the declared scope. This retained earlier
receipt does not provide a separate session ID, command, environment, UTC window, commit,
artifact, or named reviewer, so those fields remain unavailable. It is superseded for the
current consolidated gate by `M09-E18`; it does not close `EXP-M09`.

| Evidence ID | Supplied implementation/QA result | Status/limitation |
| --- | --- | --- |
| `M09-E1` | `GET /api/v1/news` has four closed schemas and `200`/`422`/`502`/`503` semantics; empty is not `404`. | **Completed** for supplied scope; gate remains open. |
| `M09-E2` | Direct query2 retrieval through pinned `curl-cffi` uses the deadline and `256 KiB` cap; the fixture `_comment` is filtered by the loader. | **Completed** for supplied scope; exact receipt metadata unavailable. |
| `M09-E3` | Ephemeral cache has the frozen 5-minute fresh, 30-minute stale, 60-second empty, 30-second failure-suppression, 32-symbol, 32 KiB entry, 1 MiB aggregate, and one-active-retrieval limits. | **Completed** for supplied scope; exact deterministic artifact unavailable. |
| `M09-E4` | `theme.js` dark mode is on both pages with no-flash, contrast, forced-colors, and print behavior; disclosure covers all ten news states and saved reopen is provider-free. | **Completed** for supplied scope; separate state transcript/AT receipt unavailable. |
| `M09-E5` | Seven requests include `theme.js`; final static shell is `98,168`/`98,304` bytes with `136` bytes headroom. | **Completed** for supplied static measurement; command/artifact unavailable. |
| `M09-E6` | News-contract QA reports `130` tests passing plus live ACDC/SPY checks. | **Pass as supplied QA summary**; execution metadata unavailable. |
| `M09-E7` | Browser QA reports `40` passed/`2` skipped with axe `0/0`. | **Pass** for supplied automated/browser scope; skip reasons and actual screen-reader receipt unavailable. |
| `M09-E8` | Performance rows report theme p95 `32.4 ms`, news endpoint p95 `1.564 ms`, ten-item render p95 `30.3 ms`, response maximum `701` bytes, and deadline `10 s`. | **Pass** as supplied M09 performance summary; ARM64 performance **Unavailable**. |
| `M09-E9` | The declared lane handoff and implementation scope are complete. | **Completed** for implementation scope; boundary repair/independent verification, consolidated gate, docs finalization, and `EXP-M09` remain open. |

`R-M09-1` (Ponytail-review/local-gate M09 regex repair) remains a retained
overengineering-only boundary record. The earlier `R-M09-2` (ARM-smoke task-ID invocation
blocker) and `R-M09-3` (flaky-test determinism) states were **In progress** in the historical
record; `M09-E18` below closes their repaired scopes. `R-M07-1` (fifth-agent
configuration/profile-count test repair) remains **In progress**. The boundary review and
first gate remain visible below; the current consolidated pass is recorded separately.

#### M09 boundary Ponytail receipt and `R-M09-1`

The read-only `/ponytail-review` at boundary `M09` is retained as the pre-acceptance
overengineering record at
[`test-results/ponytail-m09-boundary.txt`](test-results/ponytail-m09-boundary.txt). It records
four overengineering findings and net `-119` possible lines. The review is overengineering
evidence only and does not substitute for correctness, security, accessibility, performance,
or the consolidated M09 gate.

| Evidence ID | Finding and minimal SOL HIGH repair | Current result and limitation |
| --- | --- | --- |
| `R-M09-1-E1` | Read-only `/ponytail-review` at boundary `M09`; report paths are `scripts/performance_harness.py:L1056-1200`, `tests/test_provider.py:L402-599`, `scripts/performance_harness.py:L1414-1436`, and `src/stock_probs/static/app.css:L20-33`. | **Fail** for the overengineering-only review because four findings were recorded; artifact: [`test-results/ponytail-m09-boundary.txt`](test-results/ponytail-m09-boundary.txt). Environment, UTC, commit, and reviewer were not supplied; no acceptance result is inferred. |
| `R-M09-1-E2` | `scripts/performance_harness.py:L1056-1200`: move theme/news p95 sampling from the harness-generated Node script and second Chromium launch into `tools/browser/tests/performance.spec.js`. | **Pass** for supplied repair evidence: net `-25` lines and `338` tests pass. Independent harness verification is **In progress**; command, session, environment, UTC, commit, artifact, and reviewer were not supplied. |
| `R-M09-1-E3` | `tests/test_provider.py:L402-599`: consolidate repeated curl stubs to one `fake_curl_session(handler)` helper. | **Pass** for supplied repair evidence: net `-25` lines and `337` tests pass. Independent stub verification is **In progress**; command, session, environment, UTC, commit, artifact, and reviewer were not supplied. |
| `R-M09-1-E4` | `src/stock_probs/static/app.css:L20-33`: collapse CSS aliases to one canonical name per role. | **Unavailable** for independent verification; net `-10` lines were supplied, and `dashboard.spec.js` contrast assertions are being updated. No pass is inferred. |
| `R-M09-1-E5` | `scripts/performance_harness.py:L1414-1436`: delete the redundant `_write_static_row` request/theme re-assertion. | **Unavailable** for independent verification; deletion was reported, but no command, test count, environment, UTC, commit, artifact, or reviewer was supplied. No pass is inferred. |

`R-M09-1` remains a retained overengineering-only record. Independent verification of the
harness/stub repairs and CSS assertions was not supplied in this boundary record; the later
`M09-E18` receipt closes the declared M09 gate, but does not invent a new Ponytail result.
The review/repair environment, UTC, commit, independent reviewer, and independent artifacts
were not supplied and are not inferred. `EXP-M09` remains **Pending**.

#### M09 consolidated gate attempt and continuation

- **Historical pre-acceptance status:** `M09`, `R-M09-2`, and `R-M09-3` were **In progress**
  in this retained attempt; the consolidated gate rerun then and `EXP-M09` were **Pending**.
  The later `M09-E18` receipt is the current declared-scope result; `EXP-M09` remains
  **Pending**.
- **Owner/phase:** independent `LUNA MAX QA` gate result and repair routing, consumed by
  `LUNA MAX docs`. This roadmap records the supplied results and does not rerun the
  implementation gate.
- **Dependencies verified:** declared M09 implementation scope, completed `M06` and
  `EXP-M06`, and the retained `R-M09-1` boundary/repair record.
- **Change summary:** the first consolidated attempt exposed a known intermittent test
  flake and the reproducible ARM64-smoke task-ID mismatch. No implementation,
  configuration, skill, test, export, or Git path was changed by this update.

| Evidence ID / task | Requirement/check | Environment, UTC time, commit | Result, artifact, reviewer, limitation |
| --- | --- | --- | --- |
| `M09-E15` / `M09` | First exact command `TASK_ID=M09 PERFORMANCE_REVIEWER='LUNA MAX QA' ./scripts/local-gate.sh m09`; `test_success_repeat_failure_and_searchable_history` expected total `2`, observed `3`, the known random request-ID/search-collision flake; local-gate invoked `scripts/arm64-smoke.sh`, which rejected `TASK_ID=M09` and exited `2` before ARM evidence. | Supplied gate report; session, environment, UTC, commit, and artifact were not supplied. | **Fail**; reviewer `LUNA MAX QA` from the supplied command environment. The test failure routes to `R-M09-3`; the reproducible invocation blocker routes to `R-M09-2`. |
| `R-M09-3-E1` / `R-M09-3` | Clean rerun after the intermittent failure: `338` passed / `4` deselected / `89.62%`. | Supplied continuation report; session, environment, UTC, commit, and artifact were not supplied. | **Pass** for this rerun only; flaky-test determinism repair remains **In progress**, so no `R-M09-3` closure is inferred. Reviewer: `LUNA MAX QA`. |
| `R-M09-2-E1` / `R-M09-2` | Reproducible local-gate invocation failure: local-gate invokes `scripts/arm64-smoke.sh`, which rejects `TASK_ID=M09` and exits `2` before ARM evidence. | Supplied first-gate report; session, environment, UTC, commit, and artifact were not supplied. | **Fail**; repair remains **In progress**. The failure is an invocation/task-ID blocker, not ARM performance evidence; reviewer: `LUNA MAX QA`. |
| `M09-E16` / `M09` | Independent continuation: native package validation, including a `121,501`-byte wheel containing `theme.js` and `news.json`; browser `40` passed / `2` skipped; official MCP; Ponytail interface. | Supplied continuation report; session, environment, UTC, commit, and artifact were not supplied. | **Pass** for the supplied continuation scope; browser skip reasons and receipt metadata remain unavailable. Reviewer: `LUNA MAX QA`. |
| `M09-E17` / `M09` | M09 performance harness: `18/18` rows **Pass**. | Supplied continuation report; session, environment, UTC, commit, and artifact were not supplied. | **Pass** for the supplied harness rows; ARM64 performance is **Unavailable** and no emulated result satisfies a performance row. Reviewer: `LUNA MAX QA`. |
| `R-M09-2-E2` / `R-M09-2` | Separate functional/package/runtime smoke on ARM64. | Supplied continuation report; session, environment, UTC, commit, and artifact were not supplied. | **Pass** as explicitly **emulated ARM64** smoke evidence; it does not close the `TASK_ID=M09` invocation blocker or provide ARM64 performance evidence. Reviewer: `LUNA MAX QA`. |

- **Repair/history:** `R-M09-2` covers the reproducible `arm64-smoke.sh` task-ID
  rejection; `R-M09-3` covers deterministic handling of the random request-ID/search
  collision. Both repairs were **In progress** in this historical record; `M09-E18` below
  closes their repaired scopes. The clean rerun and continuation passes above remain
  historical evidence and do not erase the initial failure.
- **Limitations:** the supplied gate/continuation report has no session ID, full
  environment, UTC window, commit, artifact path, or independent receipt beyond the
  named `LUNA MAX QA` reviewer; those fields remain unavailable. ARM64 performance is
  **Unavailable**. The separate smoke is emulated only.
- **Export/Git:** no export, secret review, commit, push, or remote-revision check was
  performed by this documentation update; the consolidated rerun and `EXP-M09` remain
  **Pending**.

#### M09 consolidated gate closure receipt (`M09-E18`)

- **Status:** `Completed` for the declared M09 scope; **Pass**.
- **Owner/phase:** independent `LUNA MAX QA` consolidated gate, recorded by `LUNA MAX docs`;
  this documentation update records the supplied receipt and does not rerun the gate.
- **Dependencies verified:** completed declared M09 implementation scope, completed `M06`
  and `EXP-M06`, and the retained first-gate failure plus repair records.
- **Change summary:** The consolidated gate passed after the intermittent search-collision
  failure and the `R-M09-2` ARM-smoke task-ID rejection. No implementation, configuration,
  skill, test, export, or Git path was changed by this update.

| Evidence ID / task | Requirement/check | Environment, UTC time, commit | Result, artifact, reviewer, limitation |
| --- | --- | --- | --- |
| `M09-E18` / `M09` | Exact command `TASK_ID=M09 PERFORMANCE_REVIEWER='LUNA MAX QA' ./scripts/local-gate.sh m09`; `339` tests passed, `4` live deselected, `89.62%` coverage; browser `40` passed/`2` expected performance skips; official MCP; explicitly labelled emulated ARM64 functional/package/runtime evidence; `17` executable performance rows **Pass** with ARM64 performance **Unavailable**; theme p95 `57.3 ms`, news endpoint p95 `1.436 ms`, ten-item render p95 `21.0 ms`, news response `701` bytes, provider deadline capped at `10 s`, static `98,068`/`98,304` bytes, and `7` requests. | Native x86_64 Linux; emulated ARM64 via QEMU `7.2.0`, `aarch64`, explicitly not native; `2026-09-12T17:22:52Z`–`2026-09-12T17:33:03Z`; commit `a69df40e15b3136886f26789c27861184c3bbd77` | **Pass**; artifacts under `test-results/local-gates/M09-20260912T172252Z/`; reviewer `LUNA MAX QA`. ARM64 performance remains **Unavailable**. |
| `R-M09-2-E3` / `R-M09-2` | The consolidated rerun includes the ARM64 smoke path that previously rejected `TASK_ID=M09`. | Same native/emulated environment, UTC window, commit, and artifact directory as `M09-E18` | **Pass** for the repaired invocation scope; reviewer `LUNA MAX QA`. Earlier `R-M09-2-E1` failure remains visible. |
| `R-M09-3-E2` / `R-M09-3` | The consolidated rerun completes the request-ID/search-collision path that previously observed total `3` instead of `2`. | Same native/emulated environment, UTC window, commit, and artifact directory as `M09-E18` | **Pass** for the repaired determinism scope; reviewer `LUNA MAX QA`. Earlier `R-M09-3-E1` rerun and initial failure remain visible. |

- **Repair/history:** `R-M09-2` and `R-M09-3` are **Completed** for their repaired scopes
  by this receipt; their earlier failure and interim rerun records remain immutable history.
  The retained `R-M09-1` boundary report remains overengineering-only evidence, and this
  receipt does not invent a separate Ponytail result.
- **Limitations:** no native/physical ARM64 performance result is claimed; ARM64 performance
  is **Unavailable**. The two expected performance skips remain skips, not passes. Earlier
  supplied reports retain their own missing metadata and are not backfilled here.
- **Export/Git:** `EXP-M09` remains **Pending**; no export, secret review, local commit,
  push, or exact remote revision verification is supplied by this receipt.

#### `EXP-M09` pending export checkpoint

- **Status:** `Pending`.
- **Owner/phase:** coordinator export/checkpoint gate; independent export reviewer not yet
  supplied; `LUNA MAX docs` records the pending state.
- **Dependencies verified:** completed declared-scope `M09-E18`; `EXP-M06` is complete.
- **Change summary:** no `SESSION-EXPORT.md` export, secret review, commit, push, or exact
  remote verification was performed by this documentation update.

| Evidence ID | Requirement/check | Environment, UTC time, commit | Result, artifact, reviewer, limitation |
| --- | --- | --- | --- |
| `EXP-M09-E1` | Full-session `SESSION-EXPORT.md` export and parse | Not run by this documentation update; UTC and commit not captured | **Unavailable**; artifact none; export remains pending; reviewer not supplied. |
| `EXP-M09-E2` | Full secret review of the reviewed export | Not run; no export artifact exists for this checkpoint | **Unavailable**; artifact none; no secret-review pass inferred; reviewer not supplied. |
| `EXP-M09-E3` | Local commit, push, and exact remote revision verification | Not run; no M09 export checkpoint commit supplied | **Unavailable**; artifact none; no Git checkpoint or remote match inferred; reviewer not supplied. |

### M09 contract detail

The theme is an external parser-blocking `theme.js` initializer in the document head before
CSS, on both the dashboard and `/api/v1/docs`. It reads the localStorage key
`stock-probs.theme` for a light/dark preference, falls back to the system preference, and
removes the override for reset-to-system. First paint must be no-flash. Semantic color roles
are required instead of whole-page inversion. Text must be `>=4.5:1`; large text, controls,
and chart marks `>=3:1`; focus `>=3:1`. Forced-colors, reduced-motion, print, and unchanged
strict CSP are separate rows; no inline script/style, `unsafe-eval`, or new origin is permitted.

News is exactly `GET /api/v1/news?symbol=<normalized>&limit=5`, with `limit` `1`–`10`,
four frozen closed schemas, a separate provider `fetch_news`, and source/as-of plus
instrument identity. The pinned `yfinance==1.7.0` feasibility proof passed: its
`Ticker.get_news`/`Search` wrappers are unusable because of an indefinite LRU cache, no
end-to-end timeout, and singleton mutation, while a direct single GET to
`https://query2.finance.yahoo.com/v1/finance/search` through already-pinned
`curl-cffi==0.16.3` is feasible. Live ACDC/SPY probes returned `5` items each with
`uuid`, `title`, `publisher`, `providerPublishTime`, and `link`; `relatedTickers` was
present in `3/5` and absent in `2/5`. The frozen adapter uses no retries, redirects, cookie
preflight, or crumb, caps the raw body at `256 KiB`, and uses the absolute deadline
`min(provider_timeout,10s)`. The query2 host is frozen with no fallback. The declared
implementation scope and supplied QA summary are recorded in the scoped receipt above. No
unpinned provider replacement is accepted. Its frozen in-memory cache policy has a 5-minute
fresh TTL,
30-minute stale ceiling, 60-second empty cache, 30-second failure suppression,
32-symbol/32 KiB-entry/1 MiB-aggregate bounds, and one active retrieval. The provider
deadline is `<=10 s`, and `cache_state` is `miss`, `hit`, or `stale_fallback`.

HTTP semantics are explicit: `200` means fresh, empty, or stale fallback; `422` means
invalid input; `502` means provider failure; and `503` means capacity busy. An empty news
response is valid and never returns `404`. Partial metadata is rendered honestly from known
fields without fabricated values. Local service unreachable is a browser transport failure
without an HTTP response, and instrument changed/request superseded must not render a result
under the wrong instrument.

News changes no storage, backup, model, fingerprint, or ledger data. Saved reopen is
provider-free; current headlines is a separately labelled action. Links are safe HTTPS links,
and browser data traffic is local-only. The ten required news UI states are: **not requested**,
**loading**, **fresh**, **empty**, **partial metadata**, **stale cached with refresh failure**,
**provider unavailable without cache**, **local service unreachable**, **capacity busy**, and
**instrument changed/request superseded**. Fresh, empty, and stale fallback use `200`; invalid
input uses `422`; provider failure uses `502`; capacity busy uses `503`; and an empty response
never uses `404`. Cache `hit` remains a cache-behavior check, while saved reopen/provider-free
and the separately labelled current-headlines action remain separate interaction checks rather
than additional UI states.

The M09 implementation lanes are disjoint, shared interfaces were handed off, and the
declared implementation scope is complete:

| Lane | Exact paths | Boundary |
| --- | --- | --- |
| `SOL HIGH-A` transport/API | `src/stock_probs/api.py`, `src/stock_probs/schemas.py`, `src/stock_probs/config.py`, `tests/test_api.py` | Route, four closed schemas, validation/error envelope, and cache/deadline configuration. |
| `SOL HIGH-B` provider/domain/service | `src/stock_probs/provider.py`, `src/stock_probs/domain.py`, `src/stock_probs/service.py`, `tests/test_provider.py`, `tests/test_domain.py`, conditional `pyproject.toml`, `requirements.lock` | `fetch_news`, identity/provenance, cache/persistence exclusion, and pinned feasibility/package gate. |
| `SOL HIGH-C` presentation/static | `src/stock_probs/static/theme.js`, `src/stock_probs/static/index.html`, `src/stock_probs/static/api-docs.html`, `src/stock_probs/static/app.js`, `src/stock_probs/static/app.css` | No-flash theme, localStorage key, semantic roles, and ten news states. |
| `SOL HIGH-D` browser/tooling | `tools/browser/playwright.config.js`, `tools/browser/tests/dashboard.spec.js` | Responsive/accessibility journeys, local traffic, official MCP, and browser budgets. |

The conditional package/launch gate covers `pyproject.toml` and `requirements.lock` under
`SOL HIGH-B`: they change only if the pinned feasibility proof shows a pinned package change
is required. If the current pin is sufficient they remain unchanged. The gate includes clean
install, package-resource/static-asset, loopback, and local native or labelled emulated-ARM64
functional/build/tool checks; emulation never satisfies performance. `SOL HIGH-D` retains the
stock Playwright entry `./scripts/playwright-mcp.sh` with `--headless`, `--isolated`, and
loopback host/origin allowlists.

The historical M09 baseline is a raw shell of `90,240 B` against the `96 KiB` (`98,304` bytes)
target, leaving `8,064 B` of headroom. The earlier supplied M09 measurement was `98,168 B`
of `98,304` bytes with `7` requests and `32.4`/`1.564`/`30.3 ms` performance rows. The
current `M09-E18` receipt is `98,068`/`98,304` bytes with `7` requests, theme p95 `57.3 ms`,
news endpoint p95 `1.436 ms`, ten-item render p95 `21.0 ms`, response `701` bytes, and
provider deadline capped at `10 s`; it records `17` executable performance rows **Pass**
and ARM64 performance **Unavailable**. Missing metadata from the earlier summary is not
inferred.

| Evidence ID / task | M09 acceptance row | Current result |
| --- | --- | --- |
| `M09-E1` / `M09` | Theme initializer ordering, localStorage key `stock-probs.theme`/system/reset behavior, and no-flash first paint on dashboard and `/api/v1/docs`. | **Completed** for the declared scope; exact earlier trace metadata remains unavailable. |
| `M09-E2` / `M09` | Semantic roles, no inversion, text/large-text-control-chart/focus contrast targets, forced-colors, reduced-motion, and print. | **Completed** for the declared automated scope; no separate reduced-motion sub-receipt is inferred. |
| `M09-E3` / `M09` | Strict CSP unchanged, local-only browser traffic, official headless MCP, and actual-control responsive/accessibility checks. | **Completed** for the declared automated/browser scope by `M09-E18`; no actual screen-reader pass is inferred from axe/MCP. |
| `M09-E4` / `M09` | Exact news route, normalized symbol, `1`–`10` limit, four closed schemas, identity, provenance, safe HTTPS links, and HTTP `200` fresh/empty/stale-fallback, `422` invalid, `502` provider failure, `503` capacity, with no `404` from an empty response. | **Completed** for the declared scope; the earlier `130`-test/live ACDC/SPY evidence remains historical. |
| `M09-E5` / `M09` | Separate `fetch_news`, pinned `yfinance==1.7.0` feasibility proof, bounded `<=10 s` provider deadline, and conditional package gate. | **Completed** for supplied direct-provider/feasibility scope; exact package receipt unavailable. |
| `M09-E6` / `M09` | Frozen in-memory cache TTLs, ceilings, size/concurrency bounds, and `miss`/`hit`/`stale_fallback` behavior. | **Completed** for supplied all-limits scope; deterministic artifact metadata unavailable. |
| `M09-E7` / `M09` | No persistence/backup/model/fingerprint/ledger change; provider-free saved reopen and labelled current-headlines action. | **Completed** for supplied disclosure/reopen scope; exact persistence/network artifact unavailable. |
| `M09-E8` / `M09` | Ten documented news UI states: not requested; loading; fresh; empty; partial metadata; stale cached with refresh failure; provider unavailable without cache; local service unreachable; capacity busy; instrument changed/request superseded, with accessible text/transcript and actual controls. | **Completed** for supplied disclosure/browser scope; browser `40` passed/`2` skipped and axe `0/0`; skip reasons/transcript unavailable. |
| `M09-E9` / `M09` | Theme switch/news fixture/ten-item render/response/static-shell performance budgets, including the frozen baseline/headroom and request budget. | **Pass** in `M09-E18`: `57.3 ms`, `1.436 ms`, `21.0 ms`, `701` bytes, `10 s`, static `98,068`/`98,304` bytes, `7` requests, and `17` executable rows; ARM64 performance **Unavailable**. |
| `M09-E10` / `M09` | Native x86-64 and explicitly labelled ARM64 functional/build/tool evidence, exact paths, handoffs, and M07/M08/Astra reconciliation. | **Completed** for the declared scope by `M09-E18`; ARM64 functional/package/runtime is explicitly emulated QEMU `7.2.0`/`aarch64`, not native. |
| `M09-E13` / `M09` | ASTRA rejected scope remains excluded: settings database, news archive, article scraper/proxy, sentiment engine, forecast/model/probability changes, Redis or external cache, background scheduler, service worker, separate service, notification feed, full-text search, watchlist, personalized ranking, and any additional market-data provider unless a new evidenced requirement is approved. | **Pending**; no new absence-review receipt or `EXP-M09` result is supplied. |
| `M09-E14` / `M09` | Boundary `/ponytail-review` and minimal repair of its four overengineering findings. | **In progress**; report retained with four findings/net `-119`, `R-M09-1` repair evidence supplied, independent harness/stub verification in flight, and the consolidated gate/`EXP-M09` still pending. |

Every row receipt records task ID, check/command, environment, UTC, commit, result,
artifact/link, reviewer, limitations, repair history, and export/revision state. The earlier
scoped receipt lacks several of those fields, which remain unavailable; the current
`M09-E18` receipt supplies them for the declared consolidated gate. `EXP-M09` remains
pending and is not inferred from implementation presence or the historical M06 measurement.
- **Export gate:** `EXP-M09` must record the full-session export, secret review, local
  commit/push, and exact Git remote revision verification. Its pending evidence is recorded
  above; the supplied `M07-E18` receipt does not backfill this export checkpoint.

## Current M07 Integrated Acceptance Record

`M07` is **Completed for its declared integrated release scope** by `M07-E18`. `EXP-M07` is
**Completed** at commit `779aa749d2f85849427212d890ee6918987492b7` for the separate
export/checkpoint gate. M06 is **Completed for its
declared scope** with `EXP-M06` complete, and the M09 declared scope is recorded above;
the separate `EXP-M09` pending state is not silently closed by this receipt. The earlier
M07 rows below are retained as pre-acceptance history:

| Task ID | Status | Requirement/check | Evidence and current result | Limitation/next gate |
| --- | --- | --- | --- | --- |
| `R-M07-1` | **In progress** | Fifth-agent configuration/profile-count test | Repair is in flight; command, session, environment, UTC, commit, artifact, and reviewer were not supplied. | No pass is inferred; independent retest remains required. |
| `R-M07-2` | **Pending** | Ponytail review availability | Retained report `test-results/ponytail-m06-m07-boundary.txt` records findings only; closure is pending. Availability evidence, command, environment, UTC, commit, artifact, and reviewer were not supplied. | **Unavailable**; findings-only evidence does not close the affected pre-QA boundary and cannot be substituted by implementation claims. |
| `R-M07-3` | **Completed** | Repair stale three-profile assertions in `tests/test_ponytail_tooling.py` | `R-M07-3-E1`: assertions were updated from three profiles to four profiles; supplied test evidence reports `278` non-live tests pass. Exact command, session, environment, UTC, commit, artifact, and reviewer were not supplied. | **Pass as supplied repair/test evidence**; independent receipt metadata and broader M07 acceptance are not claimed. |
| `R-M07-4` | **Completed** | Apply two retained Ponytail findings in `tests/test_config_quality.py` | `R-M07-4-E1`: both retained findings were applied; supplied diff evidence reports a net `-1` line. Exact command, session, environment, UTC, commit, artifact, and reviewer were not supplied. | **Completed for the supplied repair scope**; this is Ponytail/repair evidence only, with no independent correctness or M07 acceptance pass inferred. |

#### Historical failed release runs and `R-M09-4`/`R-M09-5`

The two earlier failed release runs remain immutable history. Their separate command
output, session IDs, full environments, UTC windows, commits, artifacts, and named
reviewers were not supplied in this reconciliation and are not inferred. The repair IDs
remain visible even though the current M07 release receipt is now passing:

| Evidence/task | Historical requirement/check | Environment, UTC time, commit | Result, artifact, reviewer, limitation |
| --- | --- | --- | --- |
| `R-M09-4-E1` / `R-M09-4` | First earlier M07 release run and its repair record | Failure receipt metadata was not supplied | **Fail** as the retained historical release result; artifact and reviewer unavailable. The current `M07-E18` receipt is the later integrated rerun, not a row-only `R-M09-4` receipt. |
| `R-M09-5-E1` / `R-M09-5` | Second earlier M07 release run and its repair record | Failure receipt metadata was not supplied | **Fail** as the retained historical release result; artifact and reviewer unavailable. The current `M07-E18` receipt is the later integrated rerun, not a row-only `R-M09-5` receipt. |

#### M07 integrated release closure receipt (`M07-E18`)

- **Status:** `Completed` for the declared M07 scope; **Pass**.
- **Owner/phase:** independent `LUNA MAX QA` release gate, recorded by `LUNA MAX docs`;
  this documentation update records the supplied receipt and does not rerun the release
  gate.
- **Dependencies verified:** the recorded M06/M09 declared scopes, `EXP-M06`, and the
  retained M07 pre-acceptance repair/failure history. `EXP-M07` is recorded below as the
  completed checkpoint; `EXP-M09` remains separately recorded as pending and is not silently
  closed.
- **Change summary:** no implementation, configuration, skill, test, export, or Git path
  was changed by this documentation update.

| Evidence ID / task | Requirement/check | Environment, UTC time, commit | Result, artifact, reviewer, limitation |
| --- | --- | --- | --- |
| `M07-E18` / `M07` | Exact command `TASK_ID=M07 PERFORMANCE_REVIEWER='LUNA MAX QA' ./scripts/local-gate.sh release`; `396` tests passed, `4` live deselected, `89.62%` coverage; browser `40` passed/`2` expected performance skips; official MCP; migration with verified pre-migration backup schema v1 to v4; backup CLI `17` passed; Ponytail interface precondition **Pass**; and `17` executable performance rows **Pass** with ARM64 performance **Unavailable**. | Native x86_64 Linux; `2026-09-12T18:14:08Z`–`2026-09-12T18:21:06Z`; clean commit `131aabc0fc0528b1e70ba26e09e2c78565ee8d56` | **Pass**; artifacts under `test-results/local-gates/M07-20260912T181408Z/`; reviewer `LUNA MAX QA`. ARM64 performance remains **Unavailable**; no native/physical ARM64 performance result is claimed. |
| `M07-E19` / `M07` | Earlier M07 receipt verification with independently recomputed performance rows. | Supplied earlier verification; exact command, session, environment, UTC, commit, artifact, and named reviewer were not supplied. | **Pass as supplied verification evidence**; it supplements `M07-E18` and does not replace the independent release receipt. |

- **Repair/history:** the two earlier failed release runs and `R-M09-4`/`R-M09-5` remain
  visible above. The passing receipt closes the declared integrated M07 release scope but
  does not rewrite those failures or create separate row-only repair metadata.
- **Limitations:** the two expected browser performance skips remain skips, not passes;
  ARM64 performance is **Unavailable**; actual screen-reader evidence remains separately
  unavailable and is not substituted by browser/MCP evidence; no final product release is
  claimed from this declared-scope milestone alone.
- **Export/Git:** `EXP-M07` is **Completed** at commit
  `779aa749d2f85849427212d890ee6918987492b7`; its export, secret-review, push, and exact
  remote-main evidence is recorded below.

#### `EXP-M07` completed export checkpoint

- **Status:** `Completed`.
- **Owner/phase:** coordinator export/checkpoint gate; reviewer `LUNA MAX QA`.
- **Dependencies verified:** `M07-E18` and the earlier M07 receipt verification with independently
  recomputed performance rows; the separate `EXP-M09` state remains pending and is not closed by
  this checkpoint.
- **Change summary:** The supplied sanitized full-session export audit, secret review, commit,
  push, and exact remote-main match are recorded here. This roadmap update did not edit
  `SESSION-EXPORT.md`, implementation, configuration, skill, test, or Git paths.

| Evidence ID | Requirement/check | Environment, UTC time, commit | Result, artifact, reviewer, limitation |
| --- | --- | --- | --- |
| `EXP-M07-E1` | Sanitized export inventory: `281` messages, `1,676` parts, `1,341,738` bytes, `39,520` lines, SHA-256 `fddc25e5dbd0bbea4cd70cf3f124476157bb80e4f2cf9fa2ab969e69f7ace487`, and `3,793` redaction markers. | Supplied export audit receipt; checkpoint `779aa749d2f85849427212d890ee6918987492b7`, parent `131aabc0fc0528b1e70ba26e09e2c78565ee8d56`; export command, session, environment, and exact export UTC were not supplied. | **Pass**; artifact: sanitized `SESSION-EXPORT.md`; reviewer `LUNA MAX QA`. |
| `EXP-M07-E2` | Full secret review across the canonical secret patterns. | Same supplied export audit and checkpoint; exact scan command and UTC were not supplied. | **Pass**; zero canonical secret-pattern matches; artifact: export audit; reviewer `LUNA MAX QA`. |
| `EXP-M07-E3` | Commit message, parent, push, and exact remote `main` match. | Commit `779aa749d2f85849427212d890ee6918987492b7`; parent `131aabc0fc0528b1e70ba26e09e2c78565ee8d56`; message `Record integrated acceptance`; exact commit time was not supplied. | **Pass**; exact remote `main` match; artifact: Git checkpoint receipt; reviewer `LUNA MAX QA`. |

- **Repair/history:** The export checkpoint does not erase the two earlier failed M07 release
  runs, `R-M09-4`/`R-M09-5`, or their separate missing metadata; `M07-E18` and `M07-E19` remain
  distinct evidence.
- **Limitations:** Export command, session, environment, and exact export UTC were not supplied;
  no values are inferred. The earlier M07 verification's metadata limitations remain visible.
- **Export/Git:** exact checkpoint `779aa749d2f85849427212d890ee6918987492b7`, parent
  `131aabc0fc0528b1e70ba26e09e2c78565ee8d56`, message `Record integrated acceptance`, exact
  remote `main` match, and reviewer `LUNA MAX QA`.

## M08 Walkthrough Gate

`M08` is the final roadmap milestone before `ASTRA-FINAL`. It is **Completed for its declared
scope**: `M07` and `EXP-M07` are complete, `ASTRA-FINAL` is accepted for its declared scope,
and `EXP-M08` is completed at `7cf1ca8395b94c2e14e5b02ddf160f3f938091d3`. The artifact must
be generated locally from deterministic fixture data while
the real local app is running, using official browser tooling against actual controls. The
preferred form is a compiled sequence of annotated screenshots when that is more accessible,
readable, or lightweight than a GIF; the alternative is an accessible animated GIF with
companion Markdown/transcript.

The historical supplied walkthrough-extension evidence reports `20` steps and `40` annotated PNGs (`20`
desktop at `1280x1000`, `20` mobile at `390x844`), manifest SHA-256
`806722ad4321fa3ca25a794192649eb55ad9c55cbba4abf6ec51886ba556df5d`, five companion news
states represented as evidence rows, `5,683,157` bytes against the `20 MiB` budget, and zero
undeclared requests or page errors. The exact artifact path, generation command, session,
environment, UTC, commit, and named reviewer were not supplied and are not inferred.

The latest supplied ASTRA repair artifact is tracked under [`docs/walkthrough/`](docs/walkthrough/index.md)
and is reported at `7.19 MiB` with `52` PNGs, an instructional transcript, simulation labels,
and manifest revision binding. Its index records `./scripts/capture-walkthrough.sh`, generation
UTC `2026-09-12T22:54:55.320Z`, and revision `cf099754a5c3e4a05f0e785c0d65ff06f96c4d63`
with a dirty working tree. This was supplied walkthrough/repair evidence at the pre-acceptance
boundary; the current final release observation is recorded above and below.

#### M08 walkthrough-extension evidence (implementation report, not independent acceptance)

| Evidence ID | Requirement/check | Environment, UTC time, commit | Result, artifact, reviewer, limitation |
| --- | --- | --- | --- |
| `M08-E1` | Twenty numbered steps and forty annotated PNGs: twenty desktop `1280x1000` and twenty mobile `390x844`. | Supplied implementation/artifact report; command, session, environment, UTC, commit, artifact path, and reviewer were not supplied. | **Pass as supplied implementation/artifact evidence**; independent M08 verification remains pending. |
| `M08-E2` | Manifest SHA-256 `806722ad4321fa3ca25a794192649eb55ad9c55cbba4abf6ec51886ba556df5d` and `5,683,157` bytes against the `20 MiB` budget. | Same supplied report; exact hash command, environment, UTC, commit, and reviewer were not supplied. | **Pass as supplied artifact evidence**; no independent budget/hash recheck is inferred. |
| `M08-E3` | Companion news state 1 evidence row; state name was not supplied. | Same supplied report; exact row artifact and metadata were not supplied. | **Pass as supplied implementation/artifact evidence**; independent verification remains pending. |
| `M08-E4` | Companion news state 2 evidence row; state name was not supplied. | Same supplied report; exact row artifact and metadata were not supplied. | **Pass as supplied implementation/artifact evidence**; independent verification remains pending. |
| `M08-E5` | Companion news state 3 evidence row; state name was not supplied. | Same supplied report; exact row artifact and metadata were not supplied. | **Pass as supplied implementation/artifact evidence**; independent verification remains pending. |
| `M08-E6` | Companion news state 4 evidence row; state name was not supplied. | Same supplied report; exact row artifact and metadata were not supplied. | **Pass as supplied implementation/artifact evidence**; independent verification remains pending. |
| `M08-E7` | Companion news state 5 evidence row; state name was not supplied. | Same supplied report; exact row artifact and metadata were not supplied. | **Pass as supplied implementation/artifact evidence**; independent verification remains pending. |
| `M08-E8` | No undeclared requests or page errors in the supplied extension evidence. | Same supplied report; exact request/page-error artifact and metadata were not supplied. | **Pass as supplied implementation/artifact evidence**; independent verification remains pending. |
| `M08-E9` | Latest ASTRA repair walkthrough artifact: `7.19 MiB`, `52` PNGs, instructional transcript, simulation labels, and manifest revision binding. | Tracked `docs/walkthrough/index.md`; its own index records `./scripts/capture-walkthrough.sh`, `2026-09-12T22:54:55.320Z`, and revision `cf099754a5c3e4a05f0e785c0d65ff06f96c4d63` with a dirty working tree. Exact independent QA command, environment, commit, and reviewer were not supplied. | **Pass as supplied artifact evidence**; independent M08/repair QA and ASTRA re-evaluation remain in flight; reviewer not supplied. |

The tracked artifact under `docs/walkthrough/` (or an explicitly recorded equivalent) must be lightweight and bounded to 20 MiB, reproducible with `make walkthrough` or a checked-in local generation script, and free of secrets and local filesystem paths. It must include numbered steps, captions, useful alt text, a transcript/instructions, desktop and mobile views, and the generation command, fixture identity, app revision, browser-tool context, size, and limitations. Actual-control browser QA must cover:

- setup/startup, readiness, normal shutdown, and troubleshooting;
- symbol/company selection, stock and ETF selection, identity confirmation, and submission;
- both forecasts and their completed-bar/session semantics;
- direction, probability, threshold, conditional gain/loss, return/price interval, provenance, stale, and provider-limitation reading;
- stale, failure, validation, insufficient-data, and repeated states;
- history filters, saved immutable reopen, fresh historical reconstruction, CSV/JSON export, and append-only outcomes;
- dark-mode selection plus selected-instrument news, including the ten states **not requested**, **loading**, **fresh**, **empty**, **partial metadata**, **stale cached with refresh failure**, **provider unavailable without cache**, **local service unreachable**, **capacity busy**, and **instrument changed/request superseded**, with the required `200`/`422`/`502`/`503` semantics and no empty-response `404`;
- backup/restore/status where exposed in the UI, otherwise an explicit `Not exposed in UI` label;
- accessibility names/focus, keyboard, reduced motion, responsive desktop/mobile use, and actual controls.

After the artifact exists, M08 must compare the shipped app with the original prompt and original approved plan recovered from `SESSION-EXPORT.md`. The retrospective enumerates missing or materially altered features and assesses whether the UI is beautiful, well designed, and usable using the screenshots/GIF, transcript, browser, accessibility, and responsive evidence. Any incomplete recovered source is recorded as `Unavailable`, never inferred. Each gap creates `R-M08-<n>` and is repaired and retested before Astra; no gap is hidden by presentation quality. `R-M00-2` did not create this artifact or perform this QA. The supplied extension report does not close these independent requirements.

## Final Independent Astra Gate

### Historical `ASTRA-FINAL` findings and repair program (pre-acceptance)

- **Status at that historical point:** `In progress`; four ASTRA evaluation lanes reviewed all `211` matrix rows,
  SOL applied 14 repair groups, and independent QA of all repairs plus ASTRA re-evaluation are
  in flight. **Accepted** was not claimed at that point.
- **Owner/phase:** independent ASTRA visual/mobile/responsive/accessibility review; `SOL HIGH`
  repair wave; independent `LUNA MAX QA` repair verification; and ASTRA re-evaluation.
- **Dependencies verified:** supplied M08 walkthrough evidence and the tracked
  [`docs/walkthrough/`](docs/walkthrough/index.md) artifact are available as source evidence.
  Exact independent M08 QA and ASTRA lane metadata were not supplied; `EXP-M08` remains
  pending at that historical point.
- **Findings:** the four lanes reported findings across assets/controls/charts, UI
  states/persistence, theme/news/docs, and the walkthrough.

| Repair task ID | Status | Applied SOL scope | Current evidence state |
| --- | --- | --- | --- |
| `R-ASTRA-1`–`R-ASTRA-5` | **In progress** | CSS/theme defects: mobile theme selector, dark/forced-colors/print contrast, mobile navigation, API-docs label, and chart typography. | Applied per supplied report; independent QA and ASTRA re-evaluation pending. Exact per-ID mapping and execution metadata were not supplied. |
| `R-ASTRA-6`–`R-ASTRA-10` | **In progress** | App behavior: news terminal states/retry/abort, history race and pagination guards, fresh-analysis context, saved-replay truthfulness, validation recovery, stale-reason placement, ledger evidence, and chart focus. | Applied per supplied report; independent QA and ASTRA re-evaluation pending. Exact per-ID mapping and execution metadata were not supplied. |
| `R-ASTRA-11` | **In progress** | Export sort-before-cap. | Applied per supplied report; independent QA and ASTRA re-evaluation pending. Exact execution metadata were not supplied. |
| `R-ASTRA-12` | **In progress** | `theme.js` package verification. | Applied per supplied report; independent QA and ASTRA re-evaluation pending. Exact execution metadata were not supplied. |
| `R-ASTRA-13` | **In progress** | Walkthrough quality and tracked artifact: `7.19 MiB`, `52` PNGs, instructional transcript, simulation labels, and manifest revision binding. | Artifact: [`docs/walkthrough/index.md`](docs/walkthrough/index.md). Independent QA and ASTRA re-evaluation pending; exact repair metadata were not supplied. |
| `R-ASTRA-14` | **In progress** | News/theme documentation. | Applied per supplied report; independent QA and ASTRA re-evaluation pending. Exact execution metadata were not supplied. |

The static-shell repair is separately recorded as supplied ASTRA evidence: `102,607` to
`98,242` bytes, leaving `62` bytes under the `98,304`-byte limit. It is not a new repair ID.
The supplied walkthrough index records capture command `./scripts/capture-walkthrough.sh`,
generation UTC `2026-09-12T22:54:55.320Z`, and revision
`cf099754a5c3e4a05f0e785c0d65ff06f96c4d63` with a dirty working tree; this does not replace
independent QA or the ASTRA re-evaluation.

| Evidence ID | Requirement/check | Environment, UTC time, commit | Result, artifact, reviewer, limitation |
| --- | --- | --- | --- |
| `ASTRA-FINAL-E2` | Four lanes reviewed all `211` rows and produced the listed finding classes. | Supplied ASTRA report; exact command, sessions, environment, UTC, and commit were not supplied. | **Pass as supplied review evidence**; 211-row matrix artifact path/revision and reviewer were not supplied; re-evaluation in flight. |
| `ASTRA-FINAL-E3` | SOL applied `R-ASTRA-1`–`R-ASTRA-14`. | Supplied SOL repair report; exact commands, environment, UTC, and commit were not supplied. | **Pass as supplied repair evidence**; independent QA of every repair remains in flight; reviewer not supplied. |
| `ASTRA-FINAL-E4` | Static shell is `98,242` bytes, `62` below `98,304`. | Supplied measurement; exact command, environment, UTC, commit, artifact, and reviewer were not supplied. | **Pass as supplied measurement**; no new export/Git checkpoint; independent QA remains in flight. |
| `ASTRA-FINAL-E5` | Tracked walkthrough artifact has `7.19 MiB`, `52` PNGs, transcript, simulation labels, and revision binding. | [`docs/walkthrough/index.md`](docs/walkthrough/index.md) supplies capture metadata; exact ASTRA command/environment/reviewer were not supplied. | **Pass as supplied artifact evidence**; independent QA and re-evaluation remain in flight. |
| `ASTRA-FINAL-E6` | Independent QA of all 14 repairs and ASTRA re-evaluation. | Not complete; exact command, environment, UTC, commit, artifact, and reviewer were not supplied. | **Unavailable** as a completed acceptance result; no `Accepted`, `EXP-M08`, export, commit, push, or remote verification is inferred. |

- **Repair/history:** all findings and 14 repair IDs are now recorded without erasing earlier
  M08/M09 failures, skips, unavailable checks, screen-reader limits, ARM64-performance limits,
  or the historical ASTRA preparation record.
- **Export/Git/reviewer:** `EXP-M08` remains pending. This documentation update performed no
  export, commit, push, or Git-history mutation; ASTRA, repair-QA, and re-evaluation reviewer
  names were not supplied.

### Historical `ASTRA-FINAL` preparation record

The earlier preparation record assembled the matrix skeleton at
`test-results/astra/astra-final-matrix.md` and claimed no independent ASTRA execution,
per-row evaluation, acceptance, or `R-ASTRA-<n>` result. Its separate command, environment,
UTC, commit, and reviewer metadata were not supplied. That historical limitation remains
visible; the current findings and repair program above supersede its status.

After `M08` walkthrough QA/docs evidence, including M09 dark-mode/news coverage, is complete, independent GPT-6 Astra executes or re-evaluates `ASTRA-FINAL`. Astra must include a dedicated final visual-design, mobile, responsiveness, and accessibility quality evaluation of the completed UI and walkthrough, and must confirm working behavior by execution and evidence, not by reading implementation claims. Its matrix must include a separate row for every shipped item—not merely one row per feature—and every row is evaluated against requirements, aesthetics, mobile behavior, responsive behavior, accessibility, and measured performance:

- product feature and acceptance requirement;
- API endpoint, including health/readiness, company-name/instrument lookup, forecast, history/reconstruction/prices, selected-instrument news, CSV and JSON export, immutable-result, outcome, backup, restore, documentation, and static-asset surfaces discovered in the final route inventory;
- UI click/control and every UI state, including skip navigation, symbol entry/validation, stock/ETF selection, forecast submit, history filters, reconstruction, pagination, export, dark-mode selection, and the M09 news states **not requested**, **loading**, **fresh**, **empty**, **partial metadata**, **stale cached with refresh failure**, **provider unavailable without cache**, **local service unreachable**, **capacity busy**, and **instrument changed/request superseded**, plus reduced-motion and error states;
- desktop/mobile browser journey at 360/390/768/1280/1440, including empty, loading, success, repeated, failed, stale, validation, saved reopen, fresh historical reconstruction, chart/table, export, reduced-motion, accessible keyboard/actual screen-reader, API-only, and security-console journeys;
- persistence effect, including successful/failed/repeated search events, immutable input/results, append-only outcomes/corrections, bounded non-expiring history, restart, automatic/due/pre-migration backup, retention/disk limits, trust-key lifecycle, verification, both-direction cross-architecture restore, and restore promotion.
- every asset, including images, icons, fonts, charts, tables, media item, documentation visual, static shell, stylesheet, script, and other static asset;
- M08 walkthrough artifact, every numbered instruction, screenshot/frame, GIF segment, alt text/caption/transcript, deterministic generation command, artifact-size/no-secret/path review, actual-control browser evidence, desktop/mobile usability, M09 dark-mode/news coverage, and the retrospective comparing the shipped app with the original prompt and approved plan recovered from `SESSION-EXPORT.md`, including the beautiful/well-designed/usable assessment and every `R-M08-<n>` repair.

Each row records task ID `ASTRA-FINAL`, check/command, environment, UTC timestamp, commit, result, artifact/link, limitation, and reviewer, with explicit evidence for all five evaluation dimensions. Any gap or non-pass creates `R-ASTRA-<n>`. Astra evaluates and suggests only; only `SOL HIGH` build agents implement `R-ASTRA-<n>` UI changes. The repair receives the normal up-to-six-lane build handoff, the mandatory pre-QA Ponytail review, and independent QA/docs gates, then Astra re-evaluates the failed row and affected matrix. If execution evidence shows a tooling, skill, or MCP gap caused poor output, a narrowly scoped `R-ASTRA-<n>` may repair and validate that gap before acceptance; it may not expand scope without a new evidenced requirement. Repeat until the independent record explicitly says **Accepted**. Only then does `EXP-M08` checkpoint the reviewed walkthrough. After all roadmap and Astra repairs, a final pre-`EXP-FINAL` deep learning synthesis must analyze sanitized chat/run evidence, use `skill-maintenance` only for justified reusable Stock Probability development skills, validate and index those skills, and log observations. Only after that record is complete may `EXP-FINAL` sanitize the full chat/export, complete secret review, commit, push, and verify the exact remote revision. `EXP-M08` and `EXP-FINAL` cannot be green before the stated prerequisites; `EXP-M07` is the earlier M07 checkpoint. The current findings are recorded above, but ASTRA acceptance, repair QA, re-evaluation completion, and learning-synthesis completion are not claimed.

### Current `ASTRA-FINAL` acceptance and `EXP-M08` checkpoint

- **`ASTRA-FINAL` status:** `Completed`; verdict **Accepted for its declared scope** at clean
  commit `261825838d6788afeb9640db8fbbf3f94af3a82b`, session
  `ses_f679f906cffexS9H5k8Vwk4d16`.
- **Dependencies and evidence:** the bound receipts cover a corrected `214`-row matrix
  ([matrix](docs/evidence/astra-final-matrix.md) and [report](docs/evidence/astra-final-report.md)),
  record no remaining blocking defect and no regression, and resolve the affected repair scope.
  Exact ASTRA command, environment, UTC, separate artifact path, and named reviewer were not
  supplied for this concluding session and are not inferred.
- **Explicit limitations:** actual screen-reader evidence, physical-mobile evidence, and
  native/physical ARM64 performance evidence are **Unavailable**. Emulated mobile and ARM64
  functional/package/runtime observations do not turn those fields into passes.
- **Final release gate evidence:** source receipt `EV-8` records the final `M07` release gate
  on clean commit `f511ae3629de679b12c006db5d122b3ed0a22f2c` as **Pass**: `401` tests,
  `89.61%` coverage, browser `48` passed/`2` expected performance skips, and `17` executable
  performance rows passed; ARM64 performance is **Unavailable**. The tracked walkthrough
  observation is `7,660,518` bytes under the `20 MiB` budget; artifacts are under
  `test-results/local-gates/M07-20260913T005729Z/`; reviewer `LUNA MAX QA`.

#### `EXP-M08` completed export checkpoint

- **Status:** `Completed`.
- **Owner/phase:** coordinator export/checkpoint gate; reviewer `LUNA MAX QA`.
- **Dependencies verified:** accepted `ASTRA-FINAL` at
  `261825838d6788afeb9640db8fbbf3f94af3a82b`; the final walkthrough release observation above.
- **Export evidence:** commit `7cf1ca8395b94c2e14e5b02ddf160f3f938091d`, parent
  `261825838d6788afeb9640db8fbbf3f94af3a82b`, message `Checkpoint instructional walkthrough`;
  sanitized export inventory `303` messages, `1,812` parts, `1,466,585` bytes, `43,137` lines,
  SHA-256 `f846722f1c02aefbeb2f784141a022353c91dbf7c9bebde9c68b7a3dc79498d1`, and `4,288`
  redaction markers. **Pass**; artifact: sanitized `SESSION-EXPORT.md`.
- **Secret/Git evidence:** zero canonical secret-pattern matches and exact remote `main` match.
  **Pass**; export command, export session, environment, and exact export UTC were not supplied
  and are not inferred. No code, configuration, skill, test, or Git-history mutation was made by
  this documentation update.

- **Final learning synthesis:** via `skill-maintenance`, **In progress**. `EXP-FINAL` remains
  **Pending** for synthesis completion and its separate full-session export, secret review,
  commit, push, and exact remote verification. The completed `EXP-M08` checkpoint does not close
  `EXP-FINAL` or convert the unavailable physical-evidence fields into passes.

## Final operational item: selective Ingenium pipeline adoption

- **Status:** `In progress`; the implementation/adoption state is reported implemented and
  committed, but it is not gate-active until restart and validation. This is the ASTRA-plan operational
  follow-up, not a new milestone or acceptance ID.
- **Commit evidence:** the committed adoption/profile change set is in ancestor commit
  `8084a134ab4950f36446de3af622349cd23423ae` (`Build dark mode and news`), including the
  ASTRA profile's `variant: max`; the current checkpoint is its descendant
  `779aa749d2f85849427212d890ee6918987492b7`. This does not replace the required parent
  restart or independent post-restart validation.
- **Implemented adoption state (not gate-active):** `stock-orchestrator` is the inline
  primary with the six-agent count option and `subagent_depth: 1`; `luna-docs` has the
  `docs/**` permission; the recorded `.gitignore` additions are present; and the two-skill
  validator catalog contains `documentation` plus the new `skill-maintenance` skill.
- **Plan/controls:** Retain six-agent orchestration, independent QA/docs order, the read-only
  Ponytail boundary, commit/export gates, and the stock Playwright MCP entry with its
  loopback allowlists. A parent-process restart plus independent post-restart validation is
  required before any profile/catalog/ignore change affects a gate. This documentation
  reconciliation did not edit `opencode.json`, `.gitignore`, profiles, local gates, or
  skills, and claims no restart or post-restart validation pass.
- **ASTRA profile:** The ASTRA agent profile now uses `variant: max`; parent-process
  restart and independent post-restart validation are **Pending**, so no gate effect or
  validation pass is claimed.
 - **Historical ASTRA-FINAL preparation:** The matrix skeleton was being assembled at
  `test-results/astra/astra-final-matrix.md` before the supplied four-lane review. That
  preparation record did not claim an ASTRA-FINAL review, matrix acceptance, or
  `R-ASTRA-<n>` result; the current findings and repair program are recorded above. The
  skeleton's separate command, environment, UTC, commit, and reviewer metadata were not
  supplied.
- **ASTRA research state:** The first pass is **Blocked** by the external-directory
  permission boundary. The gitignored snapshot at `test-results/ingenium-snapshot` enables
  the re-run; no re-run result is claimed.
- This follow-up does not alter the canonical `ASTRA-FINAL` -> `EXP-M08` -> final learning
  synthesis -> `EXP-FINAL` order, and optional `NOTIFY-FINAL` remains separate and last.

## Roadmap Completion Record

Every milestone, repair, export, and final review uses these exact fields:

- **Task ID:** exact `M00`–`M09`, `R-M##-<n>`, `EXP-M00`–`EXP-M09`, `ASTRA-FINAL`, `R-ASTRA-<n>`, or `EXP-FINAL`.
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

- `M00` through `M09` have explicit evidence-backed statuses, and no implementation milestone is completed by assertion alone.
- A user-selected Yahoo Finance stock and ETF each demonstrate company-name/instrument identity and both forecast horizons with completed-bar/session semantics, explicit direction/threshold and conditional gain/loss probabilities, 50/80/95 return/price intervals, evaluation evidence, provenance, and honest stale/error/archive limitations.
- SQLite retains successful, failed, and repeated searches; immutable forecast inputs/results; and append-only outcomes, with searchable history through FastAPI `/api/v1` and no browser database access.
- Saved reopen and fresh historical reconstruction are distinct; charts have text equivalents; CSV/JSON export, due/pre-migration backup, retention/disk rules, non-expiring query history, trust-key lifecycle, and both-direction cross-architecture restore have independent evidence.
- M09's dark mode is user-selectable and accessible across the dashboard and required states/viewports, and selected-instrument news is clearly labelled, API-served, provenance-bearing, and honest about loading, empty, stale, and failure states.
- Responsive Signal Ledger UI at 360/390/768/1280/1440 has no overlap/overflow, tabular numeric hierarchy, all states, charts/tables, reduced motion, WCAG AA, keyboard/actual screen-reader evidence; secure loopback behavior, bounded local x86-64/ARM64 operation with honest emulation labels, official headless `@playwright/mcp`, browser regressions, useful code comments, and fail-closed local Make/scripts have independent evidence. M06 also has independent structured native-x86 evidence for every performance/UI row, with existing thresholds separated from proposed budgets.
- `README.md` and `AGENTS.md` are reconciled with the final supported scope and evidence; they are roadmap deliverables, not optional commentary.
- M08 has a tracked, lightweight, accessible walkthrough generated from deterministic fixtures against the real local app, with actual-control browser evidence, desktop/mobile instructions, a bounded artifact, and a completed prompt/approved-plan retrospective. Any gap is repaired before Astra.
- `ASTRA-FINAL` is independently **Accepted** after every requirement, feature, endpoint, control, UI state, asset, documentation visual, walkthrough frame/segment, media item, static asset, journey, and persistence row has passed requirements, aesthetics, mobile/responsive, accessibility, and measured-performance evaluation, plus every `R-ASTRA-<n>` retest.
- `EXP-M00` through `EXP-M09` and `EXP-FINAL` contain reviewed, secret-free full-session `SESSION-EXPORT.md` revisions with commit, push, exact Git remote revision verification, and no hidden failed, skipped, unavailable, or blocked field; the final learning synthesis is complete and recorded before `EXP-FINAL`.
- The final deep chat/run learning synthesis is complete before `EXP-FINAL`; only justified reusable Stock Probability skills are created or changed, and they are validated and indexed. The authored documentation taxonomy, project documentation skill, and two-skill validator catalog (`documentation` plus `skill-maintenance`) are implemented. The earlier post-restart validation receipt is session `ses_f6aa32d33ffeAvmiFK8K7Cd8EI` at `2026-09-12T11:35:58Z`–`2026-09-12T11:36:02Z`, native x86_64/OpenCode `1.18.30`, dirty commit `59534faf1cdce493bc51a11d4adbea5e5b2d6892`, with its listed checks passed; the newly implemented adoption state still requires a parent restart and independent post-restart validation before gate effect. `.dev-venv/bin/python scripts/validate_docs.py` passed `8` categories and `11` topics at `2026-09-12T12:13:23Z` in the earlier receipt. No M06 acceptance is claimed from this receipt or implementation presence.
- Dark mode and selected-instrument news are contract requirements owned by M09; options trading and public hosting are out of scope for this local app.

### `R-M00-2-E23` and `R-M00-2-E24` current documentation checks

| Evidence ID | Requirement/check | Environment, UTC time, commit | Result, artifact, reviewer, limitation |
| --- | --- | --- | --- |
| `R-M00-2-E23` | Exact `.dev-venv/bin/python scripts/validate_docs.py` execution after the `ASTRA-FINAL` findings/repair update. | Native x86_64 Linux; dirty `HEAD` `cf099754a5c3e4a05f0e785c0d65ff06f96c4d63`; UTC was not captured; execution was denied by the tool permission boundary. | **Unavailable**; no validator pass is inferred; artifact: none; reviewer `LUNA MAX docs`; rerun remains required when execution is available. |
| `R-M00-2-E24` | Exact `git diff --check -- README.md AGENTS.md MVP-PLAN.md MVP-ROADMAP.md` execution after the same update. | Native x86_64 Linux; dirty `HEAD` `cf099754a5c3e4a05f0e785c0d65ff06f96c4d63`; UTC was not captured. | **Pass**; artifact: current four-document diff; reviewer `LUNA MAX docs`; no code/configuration/skill/export/commit/push/Git-history mutation was performed. |
| `R-M00-2-E25` | Exact `.dev-venv/bin/python scripts/validate_docs.py` execution after the accepted `ASTRA-FINAL`/completed `EXP-M08` update. | Native x86_64 Linux; dirty `HEAD` `7cf1ca8395b94c2e14e5b02ddf160f3f938091d`; UTC was not captured; execution was denied by the tool permission boundary. | **Unavailable**; no current validator pass is inferred; artifact: none; reviewer `LUNA MAX docs`; rerun remains required when execution is available. |
| `R-M00-2-E26` | Exact `git diff --check -- README.md AGENTS.md MVP-PLAN.md MVP-ROADMAP.md` execution after the accepted `ASTRA-FINAL`/completed `EXP-M08` update. | Native x86_64 Linux; dirty `HEAD` `7cf1ca8395b94c2e14e5b02ddf160f3f938091d`; UTC was not captured. | **Pass**; artifact: current four-document diff; reviewer `LUNA MAX docs`; no code/configuration/skill/export/commit/push/Git-history mutation was performed by this documentation update. |
