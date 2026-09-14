---
title: "Ponytail reviews"
description: "Summary of retained Ponytail boundary findings, repairs, verification, and scope limits."
---

# Ponytail reviews

Ponytail reviews only overengineering. These receipts do not verify correctness, security,
accessibility, or performance and do not accept M05, M06, or `EXP-M06`.

## Retained boundaries

- [`R-M06-1`](ponytail-r-m06-1.txt) recorded six findings: duplicate browser collection,
  bespoke prose and provenance checks, repeated skill-description data, and two redundant
  source-text test groups. The row-only mappings below retain the finding locators and
  independent verification sessions.
- [`R-M06-15`](ponytail-r-m06-15.txt) recorded three redundant comment-audit operations.
  They were repaired as `R-M06-19`, with an independent **Pass** reviewed by `LUNA MAX QA`.
- [`M05`](ponytail-m05-boundary.txt) recorded a duplicate deadline check and an unnecessary
  key-retirement loop. Both were repaired as completed repair record `R-M05-12`: the duplicate
  deadline was removed and `retire_key` was simplified, with behavior unchanged. The independent
  rerun inside `R-M05-55 (i)` passed `4/4` behavior rerun tests in session
  `ses_f6bbd6b46ffes2BM2zVjBC5uLg`.

| Row-only locator | Retained finding receipt | Independent verification session |
| --- | --- | --- |
| <a id="r-m06-16"></a>`R-M06-16` | Browser collector and its redundant source-text test: [`ponytail-r-m06-1.txt#L4`](ponytail-r-m06-1.txt#L4), [`ponytail-r-m06-1.txt#L8`](ponytail-r-m06-1.txt#L8) | `ses_f6c4979a2ffej8KzuxwZn8ZB3O` |
| <a id="r-m06-17"></a>`R-M06-17` | Bespoke prose check and repeated skill description: [`ponytail-r-m06-1.txt#L5`](ponytail-r-m06-1.txt#L5), [`ponytail-r-m06-1.txt#L7`](ponytail-r-m06-1.txt#L7) | `ses_f6c4979a2ffej8KzuxwZn8ZB3O` |
| <a id="r-m06-18"></a>`R-M06-18` | Redundant provenance and launcher source-text checks: [`ponytail-r-m06-1.txt#L6`](ponytail-r-m06-1.txt#L6), [`ponytail-r-m06-1.txt#L9`](ponytail-r-m06-1.txt#L9) | `ses_f6c4979a2ffej8KzuxwZn8ZB3O` |
| <a id="r-m06-19"></a>`R-M06-19` | Three redundant comment-audit operations: [`ponytail-r-m06-15.txt#L4-L6`](ponytail-r-m06-15.txt#L4-L6) | `ses_f6c0aa8f5ffesfhZ7G512sYB2k` |
| <a id="r-m06-20"></a>`R-M06-20` | Retained cross-link for the six `R-M06-1` findings: [`ponytail-r-m06-1.txt#L4-L9`](ponytail-r-m06-1.txt#L4-L9) | `ses_f6bf91353ffeX56ZCVldBG5YY0` |

These row-only receipts remain limited to overengineering review and scoped independent
verification; they do not verify correctness, security, accessibility, or performance.

The aggregate `R-M06-55` verification ran on native x86_64 Linux WSL2 with Python `3.11.15`
from `2026-09-12T04:52:33Z` to `2026-09-12T05:03:44Z` at commit
`59534faf1cdce493bc51a11d4adbea5e5b2d6892`, reviewed by `LUNA MAX QA`; no session ID was
supplied. It is regression context, not a Ponytail or release acceptance result.

## Earlier post-final Next.js and Settings boundaries (`R-ASTRA-64`)

The following retained reports belong to the post-final `R-ASTRA-64` reconciliation. They are
read-only overengineering observations; they do not replace the independent QA, the accepted
earlier `ASTRA-FINAL`, or the accepted `EXP-FINAL` checkpoint.

| Boundary | Retained report | Finding or clean result |
| --- | --- | --- |
| `R-ASTRA-43` | `test-results/ponytail-r-astra-43-next-qa-recheck.txt` | Findings: the static dashboard did not need a Next/React/TypeScript runtime dependency; the CSP inline-script parser existed only for Next output; and Ponytail's `net` summary branches were redundant. |
| `R-ASTRA-46` | `test-results/ponytail-r-astra-46-next-qa-repair.txt` | **Clean:** `Lean already. Ship.` This is the latest valid clean recheck in the supplied pair. |
| `R-ASTRA-47` | `test-results/ponytail-r-astra-47-next-qa-repair.txt` | Findings: duplicate browser helpers and a source-text test that asserted default Python exception propagation. |
| `R-ASTRA-49` | `test-results/ponytail-r-astra-49-next-qa-repair.txt` | Findings: one-call static inventory and Next-chunk helpers were unnecessary wrappers. |
| `R-ASTRA-50` | `test-results/ponytail-r-astra-50-next-qa-repair.txt` | Findings: speculative chunk-name regex, verbose staging copy, and a variadic CSP helper; net `-4` possible lines. |
| `R-ASTRA-53` | `test-results/ponytail-r-astra-53-next-qa-repair.txt` | Findings: static Next output/toolchain duplication, redundant symlink guards, CSP parser complexity, and source-shape tests; net `-230` possible lines. This review's suggestion to discard the Next static build is not a current product requirement or acceptance result. |
| `R-ASTRA-54` | `test-results/ponytail-r-astra-54-next-qa-repair.txt` | Finding: a path-traversal guard protected a report-only path string; net `-4` possible lines. |
| `R-ASTRA-55` | `test-results/ponytail-r-astra-55-next-qa-repair.txt` | Finding: the CSP parser duplicated a test-only regex extraction; net approximately `-20` possible lines. |
| `R-ASTRA-56` | `test-results/ponytail-r-astra-56-next-qa-repair.txt` | Finding: two explicit static-render directives were redundant under `output: export`; net approximately `-2` possible lines. |
| `R-ASTRA-57` | `test-results/ponytail-r-astra-57-next-qa.txt` and `...-repair.txt` | The retained sequence includes a clean `Lean already. Ship.` result and findings about pruning unrelated/server-only convention references from the validator catalog. |
| `R-ASTRA-58` | `test-results/ponytail-r-astra-58-profile-repair.txt` | Finding: the 23-line CSP HTML parser could be shortened by reusing the test-proven script-tag extraction. |
| `R-ASTRA-59` | `test-results/ponytail-r-astra-59-settings-repair.txt` | Boundary finding: a manual recursive directory walk could use Node 22's recursive `readdir`. Separately, the implementation/QA record for this repair corrected the native Settings popover open-state anchor. |
| `R-ASTRA-60` | `test-results/ponytail-r-astra-60-next-repair.txt` | Finding: five source-shape assertions duplicated behavioral coverage for the performance static-row inventory. |
| `R-ASTRA-61` | `test-results/ponytail-r-astra-61-next-repair.txt` | Finding: unused settings geometry fields and helpers inflated the serialized attachment; net `-5` possible lines. |
| `R-ASTRA-62` | `test-results/ponytail-r-astra-62-next-repair.txt` | Findings: prompt em-dash normalization and a redundant sensitive-line check; net `-3` possible lines. |
| `R-ASTRA-63` | `test-results/ponytail-r-astra-63-next-repair.txt` | Finding: replace the 23-line CSP parser with a regex; the suggestion is retained but **rejected** because production CSP parsing is a security boundary. No correctness or security pass is inferred from rejecting it. |
| `R-ASTRA-65` | Latest supplied Ponytail findings-only observation; exact artifact path and execution metadata were not supplied. | Finding-only CSP-regex simplification suggestion; **rejected and nonblocking**, not clean, because production CSP parsing is a security boundary. This is separate from the supplied `R-ASTRA-65` implementation repair history: the first supported M09 run exposed a `test_backup_automation` timing race, the irrelevant completion assertion was removed, and the final rerun passed. |

The implementation/QA evidence supplied for the earlier `R-ASTRA-64` reconciliation reports the
static Next build, native Settings popover, and `8/8` focus geometry checks. It does not make any
of these overengineering-only reports a correctness, accessibility, or performance acceptance
receipt.

## Historical ASTRA repair observations and current boundary

The current supplied `ASTRA-FINAL` review is session `ses_f622707a4ffeAE3Zx8Lt2zYiC1`, reviewer
`ASTRA`, model `openai/gpt-6-astra`, on native x86_64 with official MCP and headless Chromium
`153.0.8010.12` at dirty `HEAD`
`5633f87f8cff04b5b33640f6633ff31c667c0435`, from `2026-09-14T02:57:56Z` to
`2026-09-14T03:16:35Z`. It reviewed `/` and `/api/v1/docs` at `320x844` and `1280x1000` in Light
and Dark and is **Accepted** for that supplied scope with no blockers. The independent repair-QA
receipt is reviewed by `LUNA MAX QA` at `/tmp/opencode/r-astra-69-20260914T025542940Z.json`,
from `2026-09-14T02:55:42.940Z` to `2026-09-14T02:55:54.436Z`; its full browser artifact is
`test-results/r-astra-69-browser-20260914T0248Z/` with `64` passed and `2` expected performance
skips (`33` desktop and `33` mobile). Physical mobile, actual screen-reader, true-zoom, fresh ASTRA
axe/screenshots, and native/physical ARM64-performance evidence remain unavailable.

| Boundary | Retained report | Finding or repair state |
| --- | --- | --- |
| `R-ASTRA-67` | `test-results/ponytail-r-astra-67.txt` | Historical, findings-only: reuse the proven inline-script hash extraction instead of the 23-line stateful parser, and remove an unnecessary em-dash normalization; net `-22` possible lines. |
| `R-ASTRA-69` | `test-results/ponytail-r-astra-69-boundary.txt` | Historical/unrelated, findings-only observation: reuse one inline-script hash parser across both files instead of outer hash accumulation. It does not override the clean final boundary below. |
| `R-ASTRA-69` final boundary | None supplied | **CLEAN**; `/ponytail-review` returned exactly `Lean already. Ship.` at `2026-09-14T02:41:58Z` on native x86_64, dirty `HEAD` `5633f87f8cff04b5b33640f6633ff31c667c0435`; reviewer `OpenCode gpt-5.6-sol`. |
| `R-ASTRA-72` | `test-results/ponytail-r-astra-72-boundary.txt` | **CLEAN:** `Lean already. Ship.` for the Orchestrator rename boundary; overengineering-only evidence. |

The final `R-ASTRA-69` boundary remains historical; separate findings-only artifacts are
historical/unrelated and cannot override the clean `R-ASTRA-72` boundary. Ponytail does not accept
correctness, security, accessibility, or performance. The exact final ASTRA shell command and a
separate ASTRA artifact were not supplied, but the named ASTRA session, reviewer, model, and
revision are supplied and are not unavailable.
