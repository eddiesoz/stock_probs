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
