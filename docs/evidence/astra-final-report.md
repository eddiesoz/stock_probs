---
title: "ASTRA-FINAL evaluation report"
description: "Four-lane ASTRA-FINAL re-evaluation, repair, row-level evidence, and limitation record."
---

# ASTRA-FINAL evaluation report

## Result

The supplied final re-evaluation resolved the previously reported product, presentation, and
walkthrough findings, then found two traceability defects: three existing controls were absent
from the matrix, and rows were not individually bound to aesthetic, mobile, responsive,
accessibility, and measured-performance evidence. `R-ASTRA-21` repairs both documentation gaps.
The revision-bound independent repair-QA receipt now verifies the affected `R-ASTRA-17`–
`R-ASTRA-20` scope against the corrected 214-row matrix, and the concluding ASTRA receipt records
that reviewed scope as resolved.
The [matrix](astra-final-matrix.md) now contains **214 unique rows**: the original 211 IDs plus
`C035`–`C037`.

This is **Completed** for the revision-bound `ASTRA-FINAL` review and the `R-ASTRA-17`–
`R-ASTRA-21` traceability scope. It is not a claim that unavailable actual screen-reader,
native/physical ARM64-performance, or physical-mobile evidence was obtained. No `EXP-M08`,
export, push, or remote verification is supplied by these receipts. Missing session-specific
commands, UTC windows, environments, and named reviewers remain explicitly unavailable rather
than inferred.

## Reopened visual repair and final disposition

The earlier accepted `ASTRA-FINAL`/`EXP-M08`/`EXP-FINAL` receipts remain immutable history. The
visual-quality requirement was subsequently reopened as `R-ASTRA-22`; the supplied repair and
independent QA then closed the declared visual scope. The scoped repairs are recorded explicitly
below rather than being folded into the earlier receipt:

| Task ID | Requirement | Disposition |
| --- | --- | --- |
| `R-ASTRA-22` | Reopened visual repair program covering theme parity, surfaces/background, density, controls, and mobile metadata. | **Completed** for the declared scope; independent QA passed and the post-repair `ASTRA-FINAL` receipt accepted the reviewed result. |
| `R-ASTRA-24` | SPY lookup classification. | **Pass**; the lookup flow classified SPY as an ETF. This is lookup/identity evidence, not proof of exact-symbol provider news availability or headline relevance. |
| `R-ASTRA-25` | Heading order across the repaired desktop/mobile news and forecast surfaces. | **Pass**; the supplied heading-order evidence had no axe violations. |
| `R-ASTRA-26` | Desktop action target sizing. | **Pass**; desktop actions met the supplied `44px` minimum observation. |
| `R-ASTRA-27` | Theme-selector alignment and related repaired visual/news evidence. | **Pass** on the successful reruns; the initial render attempt failed and remains recorded below. |

The independent QA receipt was run against dirty `HEAD`
`91ba52eca35fcfc13bd0d9996beb947d65d69d09` on native x86_64 Linux. It reports `425` passed,
`4` deselected, and `89.65%` coverage; provider `32` passed; browser `62` passed with `2`
expected performance skips plus `31` checks at `1280px`; `17` executable performance rows
passed with ARM64 performance **Unavailable**; static assets measured `97,893` of `98,304`
bytes; persistence rows `55 + 35 + 4` passed; and two container contract tests passed. The
container receipt reports final amd64 image digest
`sha256:0dcb3f5ec77d31a5e8f57ef6e5d57b7144b973c3acb73ac360ffe01494735da`, size
`169,699,932` bytes, and real ACDC/SPY flows. Those flows do not establish that returned ACDC
news is relevant or that exact-symbol provider news is available.

The live browser artifact records event `143`/run `141` and fresh event `145`, `21`
localhost-only requests, and axe `0/0` for desktop and `390px`; it does not provide physical
mobile, actual screen-reader, or true browser-zoom evidence. The retained artifacts are
`test-results/astra-final-live/` and `test-results/astra-final-repair/`. The accepted concluding
ASTRA session is `ses_f6683138affe6t8S6Z0G66YJDc`; its disposition is **Accepted** with no
reproducible blockers. The exact QA command, QA UTC, and named QA session were not supplied and
are not inferred.

The mandatory overengineering-only boundary result was supplied as:
`Ponytail result | boundary: R-ASTRA-22 | finding: none | scope: overengineering only | command:
/ponytail-review | result: "Lean already. Ship."`. Its exact execution UTC, environment metadata,
and separate reviewer were not supplied. This result cannot substitute for the correctness,
accessibility, provider, or performance rows above.

The current post-repair evidence is not a new clean release checkpoint. No new export, secret
review, commit, push, exact remote verification, or notification is claimed; the earlier accepted
`EXP-FINAL` checkpoint and the earlier `NOTIFY-FINAL` operational receipt remain unchanged.

## Earlier post-final Next.js 16 and Settings reconciliation (`R-ASTRA-64`)

`R-ASTRA-64` records the earlier post-final documentation scope after the supplied implementation
and independent QA evidence. It is **Completed for its declared documentation scope** after the
checks recorded below. It does not rewrite the earlier accepted `ASTRA-FINAL`, `EXP-M08`, or
`EXP-FINAL` records, and it is not a new milestone or clean release checkpoint.

FastAPI remains the sole production server and the sole application API boundary below
`/api/v1`; it serves `/` and `/api/v1/docs`. The current frontend is a Next.js `16.3.5` /
React `19.3` static App Router export built by `./scripts/build-frontend.sh` with stable build
ID `stock-probs`. `frontend/.next/`, `frontend/out/`, and the staged
`src/stock_probs/static/next/` tree are generated and ignored. The staged tree contains 12
served files packaged into the wheel. Node is used only by the build-only container stage, not
as a production server. Both routes retain parser-blocking `theme.js`; strict CSP authorizes
local scripts and the exact inline-script hashes emitted by the export. The native Settings
popover exposes Light, Dark, and System; `R-ASTRA-59` repaired its open-state anchor.

The supplied post-final QA values below remain visible as historical evidence. The then-current
M09 gate receipt is recorded by `R-ASTRA-64-E10`–`R-ASTRA-64-E15` and the
`R-ASTRA-65` history rows; none is a new release receipt:

| Evidence ID | Requirement/check | Environment, UTC time, commit | Result, artifact, reviewer, limitation |
| --- | --- | --- | --- |
| `R-ASTRA-64-E1` | Independent Python `444` pass / `4` deselected / `89.73%` coverage and `52` documentation checks. | Supplied post-final QA record; exact command, session, UTC, QA revision, artifact, and named reviewer were not supplied. | **Pass as supplied evidence**; no current implementation rerun is claimed by this docs task. |
| `R-ASTRA-64-E2` | Browser `64` pass / `2` expected performance skips, axe `0/0`, `8/8` focus geometry, and no external or `.txt` traffic. | Supplied post-final browser record; exact command, session, UTC, revision, artifact, and reviewer were not supplied. | **Pass as supplied automated-browser evidence**; physical mobile, actual screen-reader, and true zoom remain **Unavailable**. |
| `R-ASTRA-64-E3` | Deterministic build inventory: `26` files / `703,175` bytes; staged inventory: `12` files / `608,713` bytes; stable Next build ID `stock-probs`. | Supplied build record; exact command, session, UTC, revision, artifact, and reviewer were not supplied. | **Pass as supplied build evidence**; generated trees remain ignored and are not source or release evidence. |
| `R-ASTRA-64-E4` | Package and container outputs: wheel approximately `306,559` bytes; native M09 wheel row `306,553` bytes; amd64 image digest `sha256:0d68e3d9a78d626a61a1a82c455ea1734ddaa753f562d74022b94986c477bb12`, size `170,062,564` bytes. | Supplied package/container record; exact command, UTC, revision, artifact path, and reviewer were not supplied. | **Pass as supplied package/container evidence**; no clean release, commit, push, or remote result is inferred. |
| `R-ASTRA-64-E5` | Native M09 profile: `18` rows; theme p95 `32.7 ms`; ten-item render p95 `168.649 ms`; static `696,727` bytes `<753,664`; navigation `13` / `574,661` bytes; wheel `306,553` bytes `<335,872`. | Supplied native x86 performance record; exact command, session, UTC, revision, artifact, and named reviewer were not supplied. | **Pass for supplied native-x86 rows**; ARM64 performance is **Unavailable**. |
| `R-ASTRA-64-E6` | Emulated ARM64 functional/package/runtime verification. | Supplied emulated ARM64 record; exact command, UTC, revision, artifact, and reviewer were not supplied. | **Pass for functional/package/runtime scope only**; it is not native/physical ARM64 performance evidence. |
| `R-ASTRA-64-E7` | Retained pre-repair theme samples of `120.2 ms` and `120.8 ms`. | Supplied earlier performance record; exact command, session, UTC, revision, artifact, and reviewer were not supplied. | **Fail** as historical pre-repair evidence; it remains visible and is not rewritten by the earlier supplied `32.7 ms` result or the current final-gate `34.9 ms` result. No separate repair ID was supplied for those samples. |
| `R-ASTRA-64-E8` | `development-conventions` is explicitly admitted as the eighth opt-in project skill; fresh discovery passed. | Supplied skill-discovery record; exact command, session, UTC, revision, artifact, and reviewer were not supplied. | **Pass** for fresh discovery; profile activation remains **Pending** a parent restart and independent post-restart discovery. |
| `R-ASTRA-64-E9` | Latest valid Ponytail boundary history: `R-ASTRA-43` findings, `R-ASTRA-46` clean recheck, and subsequent `R-ASTRA-47`, `R-ASTRA-49`, `R-ASTRA-50`, `R-ASTRA-53`–`R-ASTRA-63` records, followed by the findings-only `R-ASTRA-65` observation. | Retained reports under `test-results/ponytail-r-astra-*.txt` plus the supplied latest observation; exact execution metadata was not supplied. | **Pass as evidence-preservation/documentation scope**; Ponytail is overengineering-only and cannot accept correctness, security, accessibility, or performance. The `R-ASTRA-65` CSP-regex suggestion is rejected and nonblocking because production CSP parsing is a security boundary; it is not clean. |
| `R-M00-2-E46` | Documentation taxonomy, references, authored metadata, and project-skill discovery validation. | Native x86_64 Linux; dirty `HEAD` `5633f87f8cff04b5b33640f6633ff31c667c0435`; UTC was not captured by the command tool. | **Pass**: `.dev-venv/bin/python scripts/validate_docs.py` reported `9` categories, `13` topics, and `8` project skills; artifact: none; reviewer: `LUNA MAX docs`. |
| `R-M00-2-E47` | Final documentation whitespace and path-scope check. | Native x86_64 Linux; dirty `HEAD` `5633f87f8cff04b5b33640f6633ff31c667c0435`; UTC was not captured by the command tool. | **Pass**: `git diff --check -- README.md AGENTS.md MVP-PLAN.md MVP-ROADMAP.md docs`; artifact: current 11-file documentation diff; reviewer: `LUNA MAX docs`; no Git mutation. |
| `R-ASTRA-64-E10` | Then-current M09 local gate: frontend npm CI/typecheck/test/build stage; Ponytail interface availability; native package; Python checks; responsive browser visual/accessibility/theme/news; official MCP; explicit ARM64 package/runtime; and mandatory native M09 performance. | Native x86_64 Linux; dirty `HEAD` `5633f87f8cff04b5b33640f6633ff31c667c0435`; `2026-09-14T00:27:32Z`–`2026-09-14T00:40:00Z`; command `./scripts/local-gate.sh m09`; artifact `test-results/local-gates/M09-20260914T002732Z/evidence.json`. | **Pass**, exit `0`; reviewer `LUNA MAX QA` from the performance receipt. The check records `ponytail-review-interface-available-not-invoked`; it is not a clean Ponytail result and does not establish named ASTRA live acceptance. No clean release, commit, export, push, or remote result is claimed. |
| `R-ASTRA-64-E11` | Python JUnit and coverage: `444` tests, zero errors, zero failures, `89.73%` coverage; browser report/log counts: `64` passed and `2` expected performance skips; official MCP completed. | Same native x86_64 dirty revision and gate window; artifacts `python/junit.xml`, `browser/report/`, `browser/test-artifacts/.last-run.json`, and the gate `playwright-mcp` completed-check entry. | **Pass** for the M09 gate evidence; the browser result is not a named ASTRA live acceptance. Reviewer `LUNA MAX QA`; no physical mobile, actual screen-reader, or true-zoom evidence is supplied. |
| `R-ASTRA-64-E12` | Native performance summary: `18` rows, `17` executable rows **Pass**, ARM64 performance **Unavailable**; current rows include theme p95 `34.9 ms`, browser render p95 `152.881 ms`, interaction p95 `26.515 ms`, ten-item news render p95 `35.4 ms`, news cache-hit p95 `1.621 ms`, news response `701` bytes, provider deadline capped at `10 s`, and static `696,727` bytes `<753,664`. | Native x86_64 Python `3.11.15`; dirty revision above; row artifacts under `performance/`; performance summary reports no missing or nonpassing rows and reviewer `LUNA MAX QA`. | **Pass** for the `17` executable native-x86 rows; ARM64 performance remains **Unavailable**, not emulated into a pass. |
| `R-ASTRA-64-E13` | Emulated ARM64 package/runtime/functional check. | Host x86_64, target `aarch64`, explicit user-local QEMU/OCI, QEMU `7.2.0`; `2026-09-14T00:34:24Z`–`00:38:19Z`; dirty revision above; artifact `arm64/evidence.json`. | **Pass** for emulated package/runtime/functional scope only; not native or physical ARM64 performance evidence. |
| `R-ASTRA-64-E14` | Native wheel build/content/package receipt: `306,553` bytes. | Native x86_64 dirty revision above; artifact `package/manifest.json` and `performance/package-size-build-time.json`; gate window above. | **Pass**; wheel is below the `335,872`-byte threshold. No release/export/Git checkpoint is inferred. |
| `R-ASTRA-64-E15` | Unsupported task-ID attempt using `TASK_ID=R-ASTRA-64`. | The supplied history records exit `2` and no artifact; exact command, UTC, environment, revision, and reviewer were not supplied. | **Fail**; retained as an unavailable/unsupported invocation, not converted to a gate result. |
| `R-ASTRA-65-E1` | First supported M09 rerun failed in `test_backup_automation` because of a timing race. | Supplied repair history; exact command, session, UTC, environment, revision, artifact, and reviewer were not supplied. | **Fail**; retained as historical failure. |
| `R-ASTRA-65-E2` | Repair removed the irrelevant completion assertion; the supported final rerun passed. | Supplied repair history; exact command, session, UTC, environment, revision, artifact, and reviewer were not supplied. | **Pass** for the supplied repaired rerun; this does not create a new release/export/Git checkpoint. |
| `R-ASTRA-65-E3` | Latest Ponytail observation was findings-only: a CSP-regex simplification suggestion. | Supplied latest Ponytail history; exact command, path/line, UTC, environment, revision, artifact, and reviewer were not supplied. | **Rejected/nonblocking**, not clean: production CSP parsing is a security boundary. Ponytail remains overengineering-only and cannot accept correctness or security. |
| `R-M00-2-E48` | Final documentation taxonomy/reference/skill validation after consuming the current gate artifact. | Native x86_64 Linux; dirty `HEAD` `5633f87f8cff04b5b33640f6633ff31c667c0435`; UTC was not captured by the command tool. | **Pass**: `.dev-venv/bin/python scripts/validate_docs.py` reported `9` categories, `13` topics, and `8` project skills; artifact: none; reviewer `LUNA MAX docs`. |
| `R-M00-2-E49` | Final documentation whitespace and scope check after consuming the current gate artifact. | Native x86_64 Linux; dirty `HEAD` `5633f87f8cff04b5b33640f6633ff31c667c0435`; UTC was not captured by the command tool. | **Pass**: `git diff --check -- README.md AGENTS.md MVP-PLAN.md MVP-ROADMAP.md docs`; artifact: current 11-file documentation diff; reviewer `LUNA MAX docs`; no Git mutation. |
| `ASTRA-FINAL-POST-MIGRATION-E1` | New post-migration ASTRA review with named live-browser evidence. | Current parent task lacks the officially granted `playwright_*` tools; fresh delegated attempts timed out; exact commands, sessions, UTC, revision, artifacts, and reviewer were not supplied. | **Blocked**; named live-browser evidence is **Unavailable**. No remaining reproducible app blocker was reported, but no new ASTRA acceptance is inferred. |

The new ASTRA limitation is independent of the accepted earlier ASTRA result: the current profile
grants only official `playwright_*` tools, while this parent task lacks those tools. The timed-out
delegated attempts do not become browser evidence. The full Ponytail repair history is retained in
[Ponytail reviews](ponytail-reviews.md), and the authoritative task ledger remains in
[`MVP-PLAN.md`](../../MVP-PLAN.md).

### Post-repair evidence details

| Evidence ID | Requirement/check | Environment, UTC time, commit | Result, artifact, reviewer, limitation |
| --- | --- | --- | --- |
| `R-ASTRA-22-E1` | Independent QA totals: `425` passed/`4` deselected/`89.65%`; provider `32` passed; browser `62` passed/`2` expected performance skips plus `31` at `1280px`; static `97,893`/`98,304` bytes; persistence `55 + 35 + 4` passed. | Native x86_64 Linux; dirty `HEAD` `91ba52eca35fcfc13bd0d9996beb947d65d69d09`; exact command and UTC not supplied. | **Pass** as supplied independent QA evidence; artifacts `test-results/astra-final-live/` and `test-results/astra-final-repair/`; reviewer `LUNA MAX QA` as supplied scope owner. |
| `R-ASTRA-22-E2` | `17` executable performance rows passed; ARM64 performance remained unavailable. | Native x86_64 Linux; dirty `HEAD` above; exact command and UTC not supplied. | **Pass** for executable native-x86 rows; ARM64 performance **Unavailable**, not emulated into a pass; artifacts `test-results/astra-final-repair/`; reviewer `LUNA MAX QA`. |
| `R-ASTRA-22-E3` | Two container contract tests, amd64 image digest/size, and real ACDC/SPY flows. | Native x86_64 QA context; dirty `HEAD` above; exact container command and UTC not supplied. | **Pass** for the supplied container contract/flow scope; artifact `test-results/astra-final-repair/` plus the supplied image receipt; exact artifact filename and reviewer metadata were not supplied. Exact-symbol news availability and ACDC news relevance remain unproven. |
| `R-ASTRA-24-E1` | SPY lookup classification is ETF. | Native x86_64 browser/QA context; dirty `HEAD` above; exact command and UTC not supplied. | **Pass** for lookup classification; no exact-symbol provider/news claim; artifact `test-results/astra-final-live/`; reviewer metadata not separately supplied. |
| `R-ASTRA-25-E1` | Heading order and heading-order axe checks. | Native x86_64, pinned Playwright Chromium; `2026-09-13T06:57:42Z`–`06:58:01Z` successful rerun, dirty `HEAD` above. | **Pass**; artifact `test-results/astra-final-repair/r-astra-27-news-evidence-rerun.json`; first `R-ASTRA-27` render attempt failed at `2026-09-13T06:55:15Z`–`06:55:52Z` with exit `1`, and its failure reason was not supplied. Reviewer metadata not separately supplied. |
| `R-ASTRA-26-E1` | Desktop actions met the supplied `44px` minimum observation. | Native x86_64 browser/QA context; dirty `HEAD` above; exact command and UTC not supplied. | **Pass** for the supplied desktop observation; artifact `test-results/astra-final-live/manifest.json`; physical mobile and true zoom remain unavailable. Reviewer metadata not separately supplied. |
| `R-ASTRA-27-E1` | Selector alignment, static-size budget, actual isolated fixture news, axe and heading-order checks. | Native x86_64, pinned Playwright Chromium; successful actual run `2026-09-13T07:00:18Z`–`07:00:36Z`; `git diff --check` `2026-09-13T06:56:36Z`; dirty `HEAD` above. | **Pass**; static `97,893`/`98,304` bytes; artifacts `test-results/astra-final-repair/static-size.json`, `r-astra-27-news-evidence-actual.json`, and `diff-check-metadata.txt`; exact reviewer metadata not supplied. |
| `ASTRA-FINAL-POST-E1` | Final post-repair ASTRA disposition. | Session `ses_f6683138affe6t8S6Z0G66YJDc`; dirty `HEAD` above; exact command, UTC, environment, and separate ASTRA artifact were not supplied. | **Accepted** with no reproducible blockers; scope is the supplied post-repair review, not a new clean release/export/push checkpoint. Reviewer identity was not separately supplied. |

The initial `R-ASTRA-27` render failure is retained rather than hidden: its successful
deterministic rerun and successful actual isolated-fixture run are the closure evidence. The
supplied ASTRA disposition does not convert physical-mobile, actual screen-reader, native/physical
ARM64-performance, or true-zoom gaps into passes.

## Four evaluation lanes and re-evaluation verdicts

| Lane | Inventory | Re-evaluation verdict | Resolved finding / remaining action |
| --- | --- | --- | --- |
| Assets, controls, and charts | `A001`–`A035`, `C001`–`C037`, `H001`–`H008` | Resolved and receipt-bound for the affected rows | CSS/theme, navigation, API-docs, chart, control, export, and package findings were reported resolved. `R-ASTRA-21` adds the three omitted controls without renumbering existing rows; `EV-9` binds the affected keys. |
| UI states and persistence | `S001`–`S021`, `P001`–`P013` | Resolved and receipt-bound for the affected rows | News terminal handling, history races/paging, fresh/saved context, validation, stale reasons, ledger evidence, and sort-before-cap were reported resolved. `EV-9` verifies the affected state/control observations against the 214-row matrix. |
| Theme, news, and documentation | `T001`–`T012`, `N001`–`N010` | Resolved and receipt-bound for the affected rows | Theme/news behavior and authored guidance were reported resolved. The capture selector/abort assertions and the 214-row matrix are independently verified in `EV-9`. |
| Walkthrough and media | `V001`–`V052`, `M001`–`M006`, `W001`–`W020` | Resolved and receipt-bound for the affected rows | The repair-QA receipt verifies the 214-row artifact scope and a 7,660,518-byte walkthrough observation. Physical-mobile execution remains unavailable. |

## Repair program

The early source grouped some IDs rather than supplying a one-to-one mapping. This report keeps
those groups and does not invent missing command or receipt metadata.

| Task ID | Repair scope | Re-evaluation disposition |
| --- | --- | --- |
| `R-ASTRA-1`, `R-ASTRA-2`, `R-ASTRA-3`, `R-ASTRA-4`, `R-ASTRA-5` | Mobile theme selector; dark, forced-colors, and print contrast; mobile navigation; API-docs label; chart typography | Resolved in supplied re-evaluation |
| `R-ASTRA-6`, `R-ASTRA-7`, `R-ASTRA-8`, `R-ASTRA-9`, `R-ASTRA-10` | News terminal states/retry/abort; history race/pagination; fresh-analysis and saved-replay context; validation recovery; stale reason; ledger evidence; chart focus | Resolved in supplied re-evaluation |
| `R-ASTRA-11` | Export sort-before-cap | Resolved in supplied re-evaluation |
| `R-ASTRA-12` | Package verification for parser-blocking `theme.js` | Resolved in supplied re-evaluation |
| `R-ASTRA-13` | Walkthrough quality, transcript, simulation labels, and revision-bound manifest | Resolved for tracked artifact |
| `R-ASTRA-14` | News and theme authored documentation | Resolved in supplied re-evaluation |
| `R-ASTRA-15` | Measured browser, layout, request, static-shell, theme, and ten-item-render budgets | **Pass** in the revision-bound final release receipt `EV-8`; the earlier local `EV-2` remains historical |
| `R-ASTRA-16` | Included in the supplied repaired/re-evaluated program; separate scope and receipt metadata were not supplied | Resolved as supplied; detail remains unavailable |
| `R-ASTRA-17` | Included in the supplied repaired/re-evaluated program | **Pass** in independent repair-QA receipt `EV-9`; affected row keys are resolved below |
| `R-ASTRA-18` | Included in the supplied repaired/re-evaluated program | **Pass** in independent repair-QA receipt `EV-9`; affected row keys are resolved below |
| `R-ASTRA-19` | Publish and verify the corrected 214-row matrix and taxonomy checks | **Pass** in `EV-9`; the matrix contains 214 rows and the documentation validator reports 9 categories, 13 topics, and 2 skills |
| `R-ASTRA-20` | Included in the supplied repaired/re-evaluated program | **Pass** in independent repair-QA receipt `EV-9`; affected row keys are resolved below |
| `R-ASTRA-21` | Add three omitted controls, 214-row assertion, per-row five-dimension keys, this report, taxonomy links, and mutation coverage | Completed for the owned documentation scope; the concluding ASTRA receipt now records the reviewed traceability scope as resolved |

## Completed portable-link repair (`R-ASTRA-70`)

`R-ASTRA-70` is **Completed** for its declared documentation-only scope; owner/phase is `LUNA
MAX docs`. It changed eight links to ignored artifacts into inline code, preserving portable
documentation and the evidence boundary. It does not accept implementation, create a milestone,
or create a release, export, commit, push, remote, CI, or notification result. All local and
ignored artifact paths in this report remain inline code rather than Markdown links.

| Evidence ID | Requirement/check | Environment, UTC time, commit | Result, artifact, reviewer, limitation |
| --- | --- | --- | --- |
| `R-ASTRA-70-E1` | Change eight ignored-artifact links to inline code and keep local/ignored artifact paths portable. | Documentation-only worktree on native x86_64 Linux; dirty `HEAD` `5633f87f8cff04b5b33640f6633ff31c667c0435`; exact repair UTC was not captured. | **Pass** for the declared documentation-only link repair; artifact: current owned-document diff; reviewer `LUNA MAX docs`. No implementation or release result is inferred. |

## Current final documentation reconciliation (`R-ASTRA-71`)

`R-ASTRA-71` is **Completed** for its declared documentation scope; owner/phase is `LUNA MAX
docs`. It consumes the supplied ASTRA repair/review records, the independent repair-QA receipt,
the final M09 gate, and `R-ASTRA-70`. It preserves the initial failure and all repair limitations;
it does not create a new milestone, implementation acceptance, clean release, export, commit, push,
remote verification, CI result, or notification. Full rows follow so unavailable fields are not
collapsed into passes.

| Evidence ID | Requirement/check | Environment, UTC time, commit | Result, artifact, reviewer, limitation |
| --- | --- | --- | --- |
| `R-ASTRA-71-E1` | Preserve the initial post-restart ASTRA failure, including official MCP exposure, focus disposition, and the unavailable fixture evaluation. | Session `ses_f6276e3a8ffeR3awDDSYKonmLk`; reviewer `ASTRA`; model `openai/gpt-6-astra`; native x86_64 with headless Chromium `153.0.8010.12`; dirty `HEAD` `5633f87f8cff04b5b33640f6633ff31c667c0435`; `2026-09-14T01:30:13Z`–`2026-09-14T01:47:02Z`. | **Blocked**: official MCP exposure **Pass**, but at `320x844` reverse-Tab followed by Escape restored focus off-screen. Forecast/chart/news evaluation was **Unavailable** because the first isolated server used the wrong 2026 fixture clock and correctly returned `stale_data`; this does not imply a production defect. Artifact: none supplied. |
| `R-ASTRA-71-E2` | Preserve the repair progression from the incomplete first repair through the final 320px/mobile repair. | Supplied repair history for `R-ASTRA-66`–`R-ASTRA-69`; exact repair commands, UTC windows, environment, commit, artifacts, and independent reviewer metadata were not supplied. | **Pass** for chronology/evidence preservation: `R-ASTRA-66` first repair was incomplete; `R-ASTRA-67` simplified the path, followed by independent-QA failures for bubbling internal focus and off-screen Escape; `R-ASTRA-68` guarded external entry and added trigger-focus restoration; `R-ASTRA-69` restored 320px to Pixel/mobile. No repair is backdated or independently accepted by this history row. |
| `R-ASTRA-71-E3` | Run the final overengineering-only boundary review for `R-ASTRA-69`. | Boundary `R-ASTRA-69`; command `/ponytail-review`; native x86_64; dirty `HEAD` `5633f87f8cff04b5b33640f6633ff31c667c0435`; `2026-09-14T02:41:58Z`; reviewer `OpenCode gpt-5.6-sol`. | **Pass; CLEAN**. Exact result: `Lean already. Ship.` Artifact: none supplied. Separate findings-only artifacts are historical/unrelated and do not override this clean boundary; Ponytail remains overengineering-only and cannot accept correctness, security, accessibility, or performance. |
| `R-ASTRA-71-E4` | Independently verify the repaired live focus, forecast, chart, news, traffic, and error scope. | Live receipt `/tmp/opencode/r-astra-69-20260914T025542940Z.json`; supplied window `2026-09-14T02:55:42.940Z`–`2026-09-14T02:55:54.436Z`; reviewer `LUNA MAX QA`; exact environment and commit were not separately supplied. | **Pass**: `66/66` checks; axe `0/0`; Light/Dark focus; successful HTTP `201` forecast with charts/text; HTTP `200` partial news with 2 items; local-only traffic; no current errors. |
| `R-ASTRA-71-E5` | Verify the complete browser artifact and desktop/mobile split for the independent repair-QA run. | Full browser artifact `test-results/r-astra-69-browser-20260914T0248Z/`; supplied QA window `2026-09-14T02:55:42.940Z`–`2026-09-14T02:55:54.436Z`; reviewer `LUNA MAX QA`; exact environment and commit were not separately supplied. | **Pass**: `64` passed and `2` expected performance skips, split `33` desktop / `33` mobile. Physical mobile, screen-reader, true-zoom, and native/physical ARM64-performance evidence remain unavailable. |
| `R-ASTRA-71-E6` | Record the named final ASTRA review, routes, viewports, themes, browser, MCP, and bounded disposition. | Session `ses_f622707a4ffeAE3Zx8Lt2zYiC1`; reviewer `ASTRA`; model `openai/gpt-6-astra`; native x86_64; official MCP with headless Chromium `153.0.8010.12`; dirty `HEAD` `5633f87f8cff04b5b33640f6633ff31c667c0435`; `2026-09-14T02:57:56Z`–`2026-09-14T03:16:35Z`; routes `/` and `/api/v1/docs`; `320x844` and `1280x1000`; Light and Dark. | **Accepted** for the affected post-repair scope, with no blockers. Exact shell command and separate ASTRA artifact were not supplied; the named session, reviewer, model, and revision are supplied and are not unavailable. Physical mobile, screen-reader, true-zoom, fresh ASTRA axe/screenshots, and native/physical ARM64-performance evidence remain **Unavailable**. |
| `R-ASTRA-71-E7` | Preserve the key final live observations and bounded traffic result. | Same named final ASTRA session and dirty native x86_64 revision as `R-ASTRA-71-E6`; exact live command and separate ASTRA artifact were not supplied. | **Pass** for the supplied review scope: prior focus and fixture-evaluation blockers were resolved; the popover had an `8px` gap and containment; no overlap/overflow; controls were `44px`; focus/dismissal, sampled contrast, first paint/System/CSP/media emulation passed; ACDC-M event `#6`/run `#2` succeeded with charts/text, partial news (2 items), and OpenAPI; `103` requests/`18` data requests had no off-origin, non-API, `.txt`, or current errors. The `.data-label` note is optional/nonblocking; no repair is authorized for it. |
| `R-ASTRA-71-E8` | Preserve evidence unavailable at final review. | Native x86_64 final-review context; exact commands and separate ASTRA artifact were not supplied. | **Unavailable**: physical mobile, actual screen reader, true zoom, fresh ASTRA axe/screenshots, and native/physical ARM64 performance. These limitations are not passes. |
| `R-ASTRA-71-E9` | Preserve the failed post-ASTRA M09 rerun and its documentation-link setup failures. | Artifact `test-results/local-gates/M09-20260914T031828Z/`; exact command, session, environment, UTC, commit, and reviewer were not separately supplied. | **Fail**, retained as historical evidence: the run recorded `46` documentation-link setup errors. It is not replaced by the later M09 pass. |
| `R-ASTRA-71-E10` | Preserve the final post-ASTRA M09 consolidated gate and its native performance rows. | Task `M09`; command `./scripts/local-gate.sh m09`; artifact `test-results/local-gates/M09-20260914T032442Z/evidence.json`; native x86_64; dirty `HEAD` `5633f87f8cff04b5b33640f6633ff31c667c0435`; `2026-09-14T03:24:42Z`–`2026-09-14T03:37:22Z`; reviewer `LUNA MAX QA`. | **Pass**, exit `0`: `444` Python tests, `89.73%` coverage, browser `64` passed/`2` expected skips, official MCP, `17` executable native-x86 performance rows passed, and QEMU `7.2.0` ARM64 package/runtime/functional evidence only; ARM64 performance **Unavailable**. Current rows: theme p95 `35.0 ms`, browser render p95 `151.958 ms`, interaction p95 `24.027 ms`, ten-item news render p95 `35.0 ms`, news cache-hit p95 `1.809 ms`, news response `701` bytes, provider deadline `10 s`, static `697,667`/`753,664` bytes, readiness `2,633.207 ms`, process RSS `144,457,728` bytes, and wheel `307,483`/`335,872` bytes. |
| `R-ASTRA-71-E11` | Preserve the remaining M09 export and release boundary. | Current worktree is dirty at `HEAD` `5633f87f8cff04b5b33640f6633ff31c667c0435`; no export artifact or Git checkpoint is supplied for this reconciliation. | **Pending**: `EXP-M09` still requires export, secret review, commit, push, and exact remote verification. No clean release, export, commit, push, remote, CI, or notification result is claimed here. |
| `R-M00-2-E56` | Final documentation validator for `R-ASTRA-71`. | Native x86_64 Linux; dirty `HEAD` `5633f87f8cff04b5b33640f6633ff31c667c0435`; UTC was not captured by the command tool. | **Pass**: `.dev-venv/bin/python scripts/validate_docs.py` reported `9` categories, `13` topics, and `8` project skills; artifact none; reviewer `LUNA MAX docs`. |
| `R-M00-2-E57` | Final documentation-test attempt for `R-ASTRA-71`. | Native x86_64 Linux; dirty `HEAD` `5633f87f8cff04b5b33640f6633ff31c667c0435`; UTC was not captured; execution was denied by the tool permission boundary. | **Unavailable**: `.dev-venv/bin/python -m pytest tests/test_docs_validation.py` did not run; no documentation-test pass is inferred; artifact none; reviewer `LUNA MAX docs`. |
| `R-M00-2-E58` | Final scoped documentation whitespace/path check for `R-ASTRA-71`. | Native x86_64 Linux; dirty `HEAD` `5633f87f8cff04b5b33640f6633ff31c667c0435`; UTC was not captured by the command tool. | **Pass**: `git diff --check -- README.md AGENTS.md MVP-PLAN.md MVP-ROADMAP.md docs`; artifact current owned-document diff; reviewer `LUNA MAX docs`; no Git mutation. |
| `R-M00-2-E59` | Final validator rerun after the last documentation wording correction for `R-ASTRA-71`. | Native x86_64 Linux; dirty `HEAD` `5633f87f8cff04b5b33640f6633ff31c667c0435`; UTC was not captured by the command tool. | **Pass**: `.dev-venv/bin/python scripts/validate_docs.py` reported `9` categories, `13` topics, and `8` project skills; artifact none; reviewer `LUNA MAX docs`. |
| `R-M00-2-E60` | Final scoped documentation whitespace/path check after the last wording correction for `R-ASTRA-71`. | Native x86_64 Linux; dirty `HEAD` `5633f87f8cff04b5b33640f6633ff31c667c0435`; UTC was not captured by the command tool. | **Pass**: `git diff --check -- README.md AGENTS.md MVP-PLAN.md MVP-ROADMAP.md docs`; artifact current owned-document diff; reviewer `LUNA MAX docs`; no Git mutation. |

## Current Orchestrator rename reconciliation (`R-ASTRA-72`)

`R-ASTRA-72` is **Completed** for its declared rename/restart-validation scope; owner/phase is
`LUNA MAX docs` for this documentation reconciliation. Historical note: `R-ASTRA-72` performed
the rename to exact `Orchestrator` and required parent-process restart validation. This section
consumes the independent post-restart QA receipt reviewed by `LUNA MAX QA`; it does not create a
new milestone, implementation scope, clean release, export, commit, push, remote verification,
CI result, or notification.

| Evidence ID | Requirement/check | Environment, UTC time, commit | Result, artifact, reviewer, limitation |
| --- | --- | --- | --- |
| `R-ASTRA-72-E1` | Verify the renamed primary agent and its six-agent/depth settings with `opencode debug agent Orchestrator`. | Independent post-restart QA; native x86_64 WSL2; OpenCode `1.18.30`; Python `3.11.15`; dirty `HEAD` `5633f87f8cff04b5b33640f6633ff31c667c0435`; live config `2026-09-14T14:33:39.924Z`–`14:33:43.328Z`. | **Pass**: primary `openai/gpt-5.6-sol`, `medium`, depth `1`, and `options.stock_probs_max_active_subagents: 6`; artifact none supplied; reviewer `LUNA MAX QA`. |
| `R-ASTRA-72-E2` | Verify the retired profile identifier no longer resolves and that no alias, default, or plugin changes were introduced. | Same independent post-restart QA context and live-config window as `R-ASTRA-72-E1`; exact auxiliary check command and artifact were not supplied. | **Pass** as supplied QA evidence; no alias/default/plugin changes; reviewer `LUNA MAX QA`. |
| `R-ASTRA-72-E3` | Verify debug configuration and JSON, `9` tooling tests, the targeted test, and the supplied diff check. | Native x86_64 WSL2; OpenCode `1.18.30`; Python `3.11.15`; dirty `HEAD` `5633f87f8cff04b5b33640f6633ff31c667c0435`; tests `2026-09-14T14:34:44.774Z`–`14:34:56.110Z`; exact auxiliary commands and separate artifacts were not supplied. | **Pass** as supplied QA evidence; reviewer `LUNA MAX QA`. |
| `R-ASTRA-72-E4` | Run the required overengineering-only boundary review after the rename. | Command `/ponytail-review`; native x86_64 WSL2; OpenCode `1.18.30`; Python `3.11.15`; dirty `HEAD` `5633f87f8cff04b5b33640f6633ff31c667c0435`; Ponytail UTC was not supplied; artifact `test-results/ponytail-r-astra-72-boundary.txt`; SHA-256 `2f4aecfa4db3ff428eb3cbe347fb3caab84cf47977358780f4320f71d14507f`. | **Pass; CLEAN**: exact result `Lean already. Ship.`; scope is overengineering only and cannot replace correctness, security, accessibility, or performance evidence; reviewer `LUNA MAX QA`. |
| `R-M00-2-E61` | Final documentation taxonomy/reference/skill validation after consuming `R-ASTRA-72`. | Native x86_64 Linux; dirty `HEAD` `5633f87f8cff04b5b33640f6633ff31c667c0435`; UTC was not captured by the command tool. | **Pass**: `.dev-venv/bin/python scripts/validate_docs.py` reported `9` categories, `13` topics, and `8` project skills; artifact none; reviewer `LUNA MAX docs`. |
| `R-M00-2-E62` | Final documentation-test attempt after consuming `R-ASTRA-72`. | Native x86_64 Linux; dirty `HEAD` `5633f87f8cff04b5b33640f6633ff31c667c0435`; UTC was not captured; execution was denied by the tool permission boundary. | **Unavailable**: `.dev-venv/bin/python -m pytest tests/test_docs_validation.py` did not run; no documentation-test pass is inferred; artifact none; reviewer `LUNA MAX docs`. |
| `R-M00-2-E63` | Final scoped documentation whitespace/path check after consuming `R-ASTRA-72`. | Native x86_64 Linux; dirty `HEAD` `5633f87f8cff04b5b33640f6633ff31c667c0435`; UTC was not captured by the command tool. | **Pass**: `git diff --check -- README.md AGENTS.md MVP-PLAN.md MVP-ROADMAP.md docs`; artifact current owned-document diff; reviewer `LUNA MAX docs`; no Git mutation. |

- **Repair/history:** `R-ASTRA-72` performed the rename and required the parent restart before
  the independent discovery check. No additional repair is supplied or inferred.
- **Limitations:** Exact commands for the auxiliary debug/config/JSON, tooling-test, targeted-test,
  and supplied diff checks, separate QA artifacts, and the Ponytail UTC were not supplied. The
  dirty revision is an observation, not a clean checkpoint.
- **Export/Git/reviewer:** No new release, export, commit, push, exact remote result, CI result,
  or notification is claimed. Reviewer: `LUNA MAX QA`.

`R-ASTRA-70` changed eight ignored-artifact links to inline code. Local and ignored artifact paths
in the current records are intentionally inline code, never Markdown links. The M09 interface-
available-but-not-invoked check is not a clean Ponytail result; the clean `R-ASTRA-69` boundary is
recorded by `R-ASTRA-71-E3`.

## Evidence receipts

| Evidence | Scope and exact available result |
| --- | --- |
| `EV-1` | Supplied ASTRA final re-evaluation: four lanes; prior findings resolved; two documentation traceability gaps found. Exact execution metadata and named reviewer unavailable. |
| `EV-2` | Local receipt `test-results/r-astra-15-browser-budgets.json`: native x86_64, dirty revision `cf099754a5c3e4a05f0e785c0d65ff06f96c4d63`, `2026-09-13T00:04:15.966Z`–`00:04:27.344Z`, 30 measured samples after 5 warmups, render p95 `125.363 ms`, interaction p95 `18.907 ms`, maximum CLS `0.001423881474247685`, zero overlap/overflow, at most 7 requests and 96,900 response bytes, static shell 98,276 bytes, theme p95 `73.9 ms`, ten-item render p95 `41.9 ms`, **Pass**; reviewer `SOL HIGH build`. The receipt is local evidence, not a tracked release artifact. |
| `EV-3` | [`M09-E18` gate ledger](../../MVP-PLAN.md): 339 tests, browser 40 passed/2 expected performance skips, theme/news/accessibility checks and 17 executable performance rows passed; ARM64 performance unavailable. |
| `EV-4` | [`M07-E18` gate ledger](../../MVP-PLAN.md): 396 tests, browser 40 passed/2 expected performance skips, official MCP, migration/backup checks, and 17 executable performance rows passed; ARM64 performance unavailable. |
| `EV-5` | [`R-M05-55` gate ledger](../../MVP-PLAN.md): independent backup, restore, retention, key-lifecycle, and explicitly emulated ARM64 functional evidence. |
| `EV-6` | [Walkthrough](../walkthrough/index.md) and [manifest](../walkthrough/manifest.json): desktop 1280×1000 and emulated mobile 390×844, 20 steps, 52 PNGs, 7,639,804 bytes under 20 MiB, zero blocked/undeclared requests and zero page errors in both journeys. |
| `EV-7` | `R-ASTRA-21` developer checks listed in the verification section below. |
| `EV-8` | Final `M07` release gate on clean commit `f511ae3629de679b12c006db5d122b3ed0a22f2c`, reviewed by `LUNA MAX QA`, `2026-09-13T00:57:29Z`–`2026-09-13T01:05:32Z`: 401 tests passed, 4 live deselected, 89.61% coverage; browser 48 passed and 2 expected performance skips; official MCP; migration schema v1→v4 with verified pre-migration backup; backup CLI 17 passed; 17 executable performance rows passed; ARM64 performance unavailable; static shell 97,952 bytes. Artifacts: `test-results/local-gates/M07-20260913T005729Z/` (`evidence.json`, browser report, `python/junit.xml`, `performance/summary.json`). |
| `EV-9` | Independent repair-QA session `ses_f67cb9073ffeFOZqQ5adQIbevD`, revision-bound to clean commit `f511ae3629de679b12c006db5d122b3ed0a22f2c`: browser 48 passed/2 skipped; capture selector/abort assertions passed; the matrix contains 214 rows; documentation validation reports 9 categories, 13 topics, and 2 skills; static shell 97,952 bytes; walkthrough observation 7,660,518 bytes. Session UTC, command, environment, separate artifact path, and named reviewer were not supplied. |
| `EV-10` | `ASTRA-FINAL` evaluation session `ses_f67ead899ffeSSEXGOfubQOadq`: the initial ASTRA verdict identified the affected evidence-binding/traceability work for the repaired scope. Exact command, UTC, environment, artifact, and named reviewer were not supplied. |
| `EV-11` | `ASTRA-FINAL` re-evaluation session `ses_f67ead42dffeZCheaK8TUpSun6`: the re-evaluation verdict resolved the repaired affected rows against the 214-row matrix and the revision-bound QA observations. Exact command, UTC, environment, artifact, and named reviewer were not supplied. |
| `EV-12` | Concluding `ASTRA-FINAL` session `ses_f67bb48cbffengjIN2uX2MqvIc`: the concluding verdict records the reviewed traceability scope as resolved. It preserves the unavailable actual screen-reader, native/physical ARM64-performance, and physical-mobile evidence limitations; no unavailable field is treated as a pass. Exact command, UTC, environment, artifact, and named reviewer were not supplied. |

## Per-row five-dimension evidence map

For matrix row `<ID>`, use `<ID>-AE` for aesthetic, `<ID>-MO` for mobile, `<ID>-RE` for
responsive, `<ID>-AX` for accessibility, and `<ID>-PE` for measured performance. The row's own
**Evidence reference** narrows the mapped receipts to that item. Thus `C035-AX`, for example,
means the `C035` source/reference plus the control accessibility evidence below; it is not a
category-only verdict.

| Prefix | Aesthetic (`-AE`) | Mobile (`-MO`) | Responsive (`-RE`) | Accessibility (`-AX`) | Measured performance (`-PE`) |
| --- | --- | --- | --- | --- | --- |
| `A` | `EV-1`, rendered route frames in `EV-6`; affected keys also use `EV-11`/`EV-12` | `EV-6`; API-only assets explicitly have no independent physical surface | `EV-8`/`EV-9` for the revision-bound release and browser observations | `EV-9`/`EV-11`/`EV-12`; actual screen reader unavailable | `EV-8`: 17 executable rows pass; ARM64 performance unavailable |
| `C` | `EV-1`, control compositions in `EV-6`; affected keys use `EV-9`/`EV-12` | 390×844 emulation in `EV-9`; physical mobile unavailable | `EV-8`: browser 48 pass/2 expected skips and static shell 97,952 bytes | Official MCP/browser and ASTRA observations in `EV-9`/`EV-12`; actual screen reader unavailable | `EV-8`: 17 executable rows pass; ARM64 performance unavailable |
| `S` | `EV-1`, state frames in `EV-6`; affected keys use `EV-9`/`EV-12` | Paired emulated-mobile state observations in `EV-9`; physical mobile unavailable | `EV-8` browser result and `EV-9` capture assertions | `EV-9`/`EV-11`/`EV-12`; actual screen reader unavailable | `EV-8`: 17 executable rows pass; ARM64 performance unavailable |
| `H` | `EV-1`, chart/table frames in `EV-6`; affected chart keys use `EV-9`/`EV-12` | Paired 390×844 chart/table observations in `EV-9`; physical mobile unavailable | `EV-8` browser result, official MCP, and 97,952-byte shell | `EV-9`/`EV-11`/`EV-12`; actual screen reader unavailable | `EV-8`: 17 executable rows pass; ARM64 performance unavailable |
| `T` | `EV-1`, light/dark/API-docs frames in `EV-6` | Paired theme frames in `EV-6`; physical mobile unavailable | `EV-8`/`EV-9` | Contrast, forced-colors, print, focus, and browser observations in `EV-9`/`EV-12`; actual screen reader unavailable | `EV-8`: 17 executable rows pass; ARM64 performance unavailable |
| `N` | `EV-1`, ten news-state frames in `EV-6`; affected news keys use `EV-9`/`EV-12` | Paired news observations in `EV-9`; physical mobile unavailable | `EV-8` browser result and `EV-9` selector/abort assertions | `EV-9`/`EV-11`/`EV-12`; actual screen reader unavailable | `EV-8`: 17 executable rows pass; ARM64 performance unavailable |
| `V` | Row-specific annotated PNG and caption in `EV-6`; affected frames use `EV-9`/`EV-12` | `EV-9` paired emulated-mobile observation; physical mobile unavailable | `EV-9` desktop/mobile capture pairing | Row-specific alt text/caption and ASTRA review in `EV-9`/`EV-12`; actual screen reader unavailable | `EV-9`: walkthrough observation 7,660,518 bytes; ARM64 performance unavailable |
| `M` | Row-specific manifest/transcript/download presentation in `EV-6`; affected manifest key uses `EV-9`/`EV-12` | `EV-9` mobile manifest/artifact observation; physical mobile unavailable | `EV-9` desktop/mobile artifact pairing | Transcript, alt-text policy, and text downloads in `EV-9`/`EV-12`; actual screen reader unavailable | `EV-9`: walkthrough observation 7,660,518 bytes; ARM64 performance unavailable |
| `W` | Row-specific desktop/mobile instructional sequence in `EV-6`; affected segments use `EV-9`/`EV-12` | `EV-9` paired emulated-mobile step; physical mobile unavailable | `EV-9` desktop/mobile capture pairing | Do/expect text, caption, alt text, keyboard steps, and ASTRA review in `EV-9`/`EV-12`; actual screen reader unavailable | `EV-8` release performance plus `EV-9` 7,660,518-byte walkthrough observation; ARM64 performance unavailable |
| `P` | No independent rendered aesthetic surface; related visible state is identified by the row reference | No independent mobile persistence implementation; related UI evidence uses `EV-6` | No viewport-dependent persistence behavior; API/UI boundaries checked by `EV-4`/`EV-5` | No direct assistive-technology surface; related controls use `EV-3`/`EV-4`; actual screen reader unavailable | Persistence, backup, restore, and bounded-query checks in `EV-4`/`EV-5`; native ARM64 performance unavailable |

## Revision-bound affected-row resolution

The matrix's affected-row table resolves each five-dimension key to the observations below. The
ASTRA verdict is `EV-12`; the independent repair-QA observations are `EV-9`; and the clean
release-gate observations are `EV-8`. These are scoped evidence bindings, not a replacement for
the explicit physical-evidence limitations that follow.

| Row | Exact observation | Revision-bound receipt | Remaining limitation |
| --- | --- | --- | --- |
| `H004` | Return-tail SVG chart legibility/typography was resolved by the ASTRA re-evaluation and conclusion. | `EV-9` browser 48 passed/2 skipped; `EV-8` static shell 97,952 bytes and 17 executable performance rows passed; `EV-11`/`EV-12` verdict. | Actual screen reader and native/physical ARM64 performance unavailable; mobile is emulated. |
| `H005` | Chart axes, tick labels, and legend legibility was resolved by the ASTRA re-evaluation and conclusion. | `EV-9` browser 48 passed/2 skipped; `EV-8` official MCP and release measurements; `EV-11`/`EV-12` verdict. | Actual screen reader and native/physical ARM64 performance unavailable; mobile is emulated. |
| `V005` | Desktop chart/table capture remained present and was included in the repaired walkthrough observation. | `EV-9` capture QA and 7,660,518-byte walkthrough observation; `EV-12` verdict. | Physical mobile and actual screen reader unavailable; no separate export checkpoint is supplied. |
| `V031` | Mobile chart/table capture was present in the paired 390×844 emulation observation. | `EV-9` capture QA and 7,660,518-byte walkthrough observation; `EV-12` verdict. | The 390×844 result is emulated, not physical mobile; actual screen reader unavailable. |
| `S021` | Fresh historical-cutoff analysis remained distinct from the saved forecast and was resolved in the ASTRA re-evaluation. | `EV-9` browser/capture receipt; `EV-11`/`EV-12` verdict; `EV-8` release gate. | Actual screen reader and native/physical ARM64 performance unavailable. |
| `A020` | The fresh historical-cutoff reconstruction endpoint remained separately labelled and was resolved in the ASTRA re-evaluation. | `EV-9` browser/capture receipt; `EV-11`/`EV-12` verdict; `EV-8` release gate. | API-only row has no independent physical-mobile surface; actual screen reader and native/physical ARM64 performance unavailable. |
| `W009` | Step 09 continued to distinguish a new cutoff analysis from saved evidence. | `EV-9` walkthrough/capture observation at 7,660,518 bytes; `EV-12` verdict. | Physical mobile and actual screen reader unavailable; no separate export checkpoint is supplied. |
| `V009` | Desktop fresh-reconstruction frame was included in the repaired walkthrough observation. | `EV-9` capture QA and 7,660,518-byte walkthrough observation; `EV-12` verdict. | Physical mobile and actual screen reader unavailable; no separate export checkpoint is supplied. |
| `V035` | Mobile fresh-reconstruction frame was included in the paired 390×844 emulation observation. | `EV-9` capture QA and 7,660,518-byte walkthrough observation; `EV-12` verdict. | Physical mobile is unavailable; actual screen reader unavailable. |
| `W020` | Saved evidence remained separate from current news; the capture/abort assertions covered the changed-request path without treating current news as saved evidence. | `EV-9` capture selector/abort assertions; `EV-11`/`EV-12` verdict; `EV-8` browser/MCP gate. | News is deterministic simulated evidence; physical mobile, actual screen reader, and native/physical ARM64 performance unavailable. |
| `N010` | Instrument-changed/request-superseded handling aborted the old request and did not render stale-symbol headlines. | `EV-9` capture selector/abort assertions; `EV-11`/`EV-12` verdict; `EV-8` browser gate. | News is deterministic simulated evidence; physical mobile and actual screen reader unavailable. |
| `V026` | Desktop superseded-news capture represented the aborted stale request. | `EV-9` capture selector/abort assertions and walkthrough observation; `EV-12` verdict. | News is deterministic simulated evidence; physical mobile and actual screen reader unavailable. |
| `V052` | Mobile superseded-news capture represented the aborted stale request in 390×844 emulation. | `EV-9` capture selector/abort assertions and walkthrough observation; `EV-12` verdict. | News is deterministic simulated evidence; physical mobile and actual screen reader unavailable. |
| `M001` | The manifest/artifact evidence was checked with the corrected 214-row matrix and the 7,660,518-byte walkthrough observation. | `EV-9` matrix count, documentation validation, and walkthrough observation; `EV-12` verdict. | Physical mobile and actual screen reader unavailable; no separate export checkpoint is supplied. |
| `C035` | The bounded “show up to 10 headlines” control was included in the passing browser/control receipt. | `EV-9` browser 48 passed/2 skipped; `EV-8` official MCP release gate; `EV-12` verdict. | News is deterministic simulated evidence; physical mobile and actual screen reader unavailable. |
| `C036` | The detailed-provenance link from the stale-data reason was included in the passing browser/control receipt. | `EV-9` browser 48 passed/2 skipped; `EV-8` official MCP release gate; `EV-12` verdict. | Physical mobile and actual screen reader unavailable. |
| `C037` | The failed-request control opened immutable audit detail in the passing browser/control receipt. | `EV-9` browser 48 passed/2 skipped; `EV-8` official MCP release gate; `EV-12` verdict. | Actual screen reader and native/physical ARM64 performance unavailable; mobile is emulated. |

## Explicitly unavailable evidence

- **Actual screen reader:** unavailable. Axe, keyboard, semantic, contrast, and browser checks do
  not substitute for an assistive-technology session.
- **Native/physical ARM64 performance:** unavailable. QEMU/aarch64 results are labelled emulated
  functional/package/runtime evidence and do not satisfy a performance row.
- **Physical mobile:** unavailable. Mobile evidence is Chromium touch/viewport emulation at
  390×844, not execution on a phone or tablet.
- **Post-`R-ASTRA-21` ASTRA verdict:** the concluding receipt `EV-12` records the reviewed
  traceability scope as resolved. This does not convert the three unavailable physical-evidence
  categories above into passes, and no `EXP-M08` or export checkpoint is inferred.

## `R-ASTRA-21` verification

The exact requested commands are:

```text
.dev-venv/bin/python scripts/validate_docs.py
.dev-venv/bin/python -m pytest tests/test_docs_validation.py
.dev-venv/bin/python scripts/comment_audit.py
git diff --check
```

The current attempts were made on native x86_64 Linux with dirty `HEAD`
`f511ae3629de679b12c006db5d122b3ed0a22f2c`. The tool permission boundary denied execution of
`.dev-venv/bin/python scripts/validate_docs.py`,
`.dev-venv/bin/python -m pytest tests/test_docs_validation.py`, and
`.dev-venv/bin/python scripts/comment_audit.py`; their results are **Unavailable**, with no pass
inferred and no UTC captured. `git diff --check` returned **Pass**; UTC was not captured and the
artifact is the current two-file documentation diff; reviewer `LUNA MAX docs`. No Git history,
index, branch, tag, or remote was mutated. The earlier
29-test, 88-file comment-audit, and 9-category/13-topic/2-skill receipt remains historical and
is not substituted for the unavailable current runs.

[Back to evidence](index.md)
