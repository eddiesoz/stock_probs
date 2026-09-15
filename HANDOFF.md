# Stock Probability UI Redesign Handoff

> Temporary continuation handoff for a transport-only SOL lane. This file is intended for repository-root location and is not final product documentation.

## Purpose and ownership

- This handoff records the uncommitted Next.js dashboard redesign on `feature/nextjs-ui-redesign`.
- The handoff author owns only this file. Do not edit other documentation, implementation, configuration, tests, `SESSION-EXPORT.md`, the Git index, branches, tags, remotes, or history.
- Do not commit, push, perform QA, or infer acceptance from implementation claims or incomplete checks.
- Repository policy and evidence rules are in [`AGENTS.md`](AGENTS.md).
- Loaded skills: [`documentation`](.opencode/skills/documentation/SKILL.md) and [`development-conventions`](.opencode/skills/development-conventions/SKILL.md).
- Relevant future skills: [`browser-qa`](.opencode/skills/browser-qa/SKILL.md), [`local-gate-evidence`](.opencode/skills/local-gate-evidence/SKILL.md), [`security-audit`](.opencode/skills/security-audit/SKILL.md), and [`ponytail-boundary-review`](.opencode/skills/ponytail-boundary-review/SKILL.md).

## Repository baseline and transfer

- Repository: [`github.com/eddiesoz/stock_probs`](https://github.com/eddiesoz/stock_probs).
- Supplied remotes: `git@github.com:eddiesoz/stock_probs.git` and `https://github.com/eddiesoz/stock_probs.git`.
- Branch: `feature/nextjs-ui-redesign`; local only, uncommitted, and unpushed.
- Baseline/main/HEAD: `0f02f5f0a0dcbf0f1ee42d6c3d930f9bd2fe0ed4`, `Build Next.js dashboard foundation`.
- `origin/main`, `origin/HEAD`, and local `main` were verified at the supplied baseline before this handoff.
- Create a portable source patch with:
  `git diff --binary 0f02f5f0a0dcbf0f1ee42d6c3d930f9bd2fe0ed4 > stock-probs-ui-redesign.patch`
- Copy this `HANDOFF.md` separately because it is untracked and is not included in the patch.
- Copy ignored evidence separately as needed. `test-results/**` and `/tmp/opencode/**` are local evidence, not release-portable source.
- In the target clone, fetch the exact baseline, create the feature branch from that SHA, run `git apply --check stock-probs-ui-redesign.patch`, then apply it.
- Do not overwrite unrelated work.
- Do not touch `burry_env/` or `data/stock_probs.sqlite3` (73,461,760 bytes). Use isolated temporary data.

## Product and design contract

- The product is a local, low-resource Precision Research Terminal for close-to-close and latest-completed-5-minute-bar-to-close probabilities for Yahoo Finance stocks and ETFs.
- The redesign target is a modern research terminal with cool ivory/graphite surfaces, restrained teal/amber, dense hierarchy, immediate composer/CTA, comparable horizon cards, compact outcome ledger, and useful API documentation.
- Do not add generic gradients, glass effects, remote fonts, a design system, or a chart dependency.
- Next.js 16 App Router/React 19 is a static export. FastAPI remains the sole production server and serves `/`, `/api/v1/docs`, and the application API below `/api/v1`.
- Browser data is local-only through FastAPI. The browser never opens SQLite, issues SQL, receives a database path, or calls Yahoo Finance directly.
- Strict CSP remains intact. Parser-blocking `/assets/theme.js` must run before CSS on the dashboard and API docs, use `stock-probs.theme`, support Light/Dark/System, and preserve no-flash first paint.
- Preserve stable IDs and selectors used by browser tests and accessibility checks.
- Native Settings Popover behavior and focus restoration are contract requirements.
- Saved forecasts reopen as immutable recorded results. Historical-cutoff reconstruction is separately labelled fresh analysis.
- News is the selected-instrument API-served requirement with honest loading, empty, partial, stale, provider-failure, local-unreachable, busy, and superseded states.
- Required news states are: not requested, loading, fresh, empty, partial metadata, stale cached with refresh failure, provider unavailable without cache, local service unreachable, capacity busy, and instrument changed/request superseded.
- Support native x86_64/amd64 and ARM64/aarch64. QEMU/OCI results are emulated packaging/runtime/functional evidence only; they never prove native/physical ARM64 performance.

## Orchestration and gates

- Active profile: `Orchestrator`.
- Use at most six subagents and use six only when six genuinely independent todos exist, with disjoint ownership.
- Run read-only `/ponytail-review` at every implementation boundary before independent QA.
- Ponytail is overengineering-only and cannot replace correctness, security, accessibility, or performance evidence.
- Independent QA runs before documentation reconciliation.
- ASTRA evaluates and suggests only. SOL implements authorized repairs only.
- Required later sequence: repair, new Ponytail boundary, independent QA, supported consolidated M09/release regression, docs reconciliation, named ASTRA review, QA/docs/ASTRA rerun, sanitized export and secret review, checkpoint commit, push, and exact remote verification.
- No OpenCode profile/config change is needed. Any future profile or local-gate change requires parent restart and independent post-restart validation before it affects a gate.
- Before future source/test edits, read the applicable development-conventions testing and useful-comments references.

## Current dirty worktree

The inspected diff contains exactly 19 modified tracked files, with 1,430 insertions and 492 deletions. No implementation changes were made by the handoff author.

### UI

- [`frontend/app/api-docs/page.tsx`](frontend/app/api-docs/page.tsx)
- [`frontend/app/page.tsx`](frontend/app/page.tsx)
- [`frontend/app/settings.tsx`](frontend/app/settings.tsx)
- [`src/stock_probs/static/app.css`](src/stock_probs/static/app.css)
- [`src/stock_probs/static/app.js`](src/stock_probs/static/app.js)

### Routing and package behavior

- [`src/stock_probs/api.py`](src/stock_probs/api.py)
- [`scripts/build-frontend.sh`](scripts/build-frontend.sh)
- [`scripts/package_smoke.py`](scripts/package_smoke.py)
- [`tools/browser/playwright.config.js`](tools/browser/playwright.config.js)

### ARM and gate tooling

- [`scripts/arm64-smoke.sh`](scripts/arm64-smoke.sh)
- [`scripts/compose.arm64.yml`](scripts/compose.arm64.yml)
- [`scripts/local-gate.sh`](scripts/local-gate.sh)
- [`scripts/ponytail-review.sh`](scripts/ponytail-review.sh)

### Tests

- [`tests/test_api.py`](tests/test_api.py)
- [`tests/test_container_contract.py`](tests/test_container_contract.py)
- [`tests/test_performance_harness.py`](tests/test_performance_harness.py)
- [`tests/test_ponytail_tooling.py`](tests/test_ponytail_tooling.py)
- [`tests/test_resource.py`](tests/test_resource.py)
- [`tools/browser/tests/dashboard.spec.js`](tools/browser/tests/dashboard.spec.js)

## Work completed so far

- Added the modern dashboard shell, API docs surface, responsive chart/layout repairs, dynamic forecast/history markup, chart focus behavior, package/static-resource checks, and external Playwright mode.
- Repaired the `/assets/next/**` allowlist while preserving strict CSP.
- Made frontend build ordering and package resource traversal explicit.
- Expanded ARM production-smoke coverage.
- Updated the OpenCode launcher pin to `1.18.31`.
- Added API, container, performance, Ponytail, resource, and dashboard regressions.
- Build sessions:
  - A: `ses_f5e0d4609ffekE3iCaCIGSswby`
  - B: `ses_f5e0d4549ffepR8czDdhEhdOIc`
  - C: `ses_f5e0d4522ffeQFWsMuSLOqBN79`
  - D: `ses_f5e0d44d4ffeobj2K6sgRaLPm4`
  - E: `ses_f5e0d44b7ffeC2mYD7Wvsr2LuM`
  - F: `ses_f5e0d448bffet2QT7PNMvVOD29`
- Integration session: `ses_f5dfe21baffexFitH6364oRsxc`.
- Repair sequence: `R-ASTRA-74` through `R-ASTRA-88`.
- Retained Ponytail reports:
  `test-results/ponytail-r-astra-76-redesign.txt`,
  `test-results/ponytail-r-astra-77-redesign.txt`,
  `test-results/ponytail-r-astra-78-redesign.txt`,
  `test-results/ponytail-r-astra-80-redesign.txt`,
  `test-results/ponytail-r-astra-81-redesign.txt`,
  `test-results/ponytail-r-astra-82-redesign.txt`,
  `test-results/ponytail-r-astra-84-redesign.txt`,
  `test-results/ponytail-r-astra-85-redesign.txt`,
  `test-results/ponytail-r-astra-87-redesign.txt`,
  `test-results/ponytail-r-astra-88-redesign.txt`.
- The first `R-ASTRA-85` reviewer attempt was unavailable/malformed; its identical retry retained findings rather than a pass.
- The final `R-ASTRA-88` report contains `Lean already. Ship.`
- The Ponytail result is overengineering-only, predates the two current QA defects, and does not accept the redesign.
- No `R-ASTRA-89` or `R-ASTRA-90` implementation was made; both launches were cancelled before execution.

## Supplied QA and evidence receipts

These are supplied receipts, not checks run by the handoff author. They must remain scoped and must not be collapsed into an overall pass.

- Preflight `ses_f5da58584ffevzdJmJkcncErHN`: canonical build receipt reports Node `22.19.0`, npm `10.9.3`, Python `3.11.15`, `BUILD_ID=stock-probs`, fresh ignored output, and UTC `2026-09-14T23:58:06Z–23:59:17Z`.
- QA A `ses_f5da0f9deffeM3OHBHcJulWLEx`: `171` passed, `1` scoped deselected, Ruff and mypy reported passing. The `#fff` shorthand Ponytail note was rejected as nonblocking because shorthand is demonstrably used and the official `R-ASTRA-88` boundary was clean.
- QA B `ses_f5da0f9c1ffeXiN6F0b3pNOQ1Z`: `215` passed; routing/CSP/package/container budgets reported passing; authored bytes `134,772/143,360`; static bytes `707,861/753,664`; wheel bytes `309,390/335,872`; amd64 digest `sha256:84f6f3bc73bff5ea5380e697bdf7809495e5b5d9db8278687cc9c9ad1cdc62b0`. The reviewer marked the lane **Fail** because default wheel hashes differed by dist-info ZIP timestamps. Identical `SOURCE_DATE_EPOCH=1757894400` produced recorded hash prefix `df427bdd...`. Retain this nonblocking reproducibility limitation unless timestamp-free identity becomes an explicit gate.
- QA C `ses_f5da0f9acffe2L2Qgf66fM5FoD`: desktop `14` passed; artifact `test-results/r-astra-88-qa-desktop/`; exact 1280 evidence and actual paint timing unavailable.
- QA D `ses_f5da0f998ffecHsvR2fzM5YZxM`: `36` passed, `1` failed; screenshots in `test-results/r-astra-88-qa-mobile/`; blocker is duplicate `horizon scan` landmarks.
- QA E `ses_f5da0f987ffeGj9J9T7lyJtPH6`: `34` passed, `2` failed for the same duplicate landmark; 17 executable performance rows reported passing and ARM performance unavailable. Values: render `153.004 ms`, interaction `21.882 ms`, theme `36.5 ms`, news render `39.0 ms`, news endpoint `1.957 ms`, static bytes `707,861`, wheel bytes `309,390`. Retained artifact: `test-results/r-astra-88-qa-states/`.
- QA F `ses_f5da0f975ffeozzOrdGF7gGSoU`: ARM **Fail**. Artifacts: `test-results/arm64/R-M09-88-20260915T000322Z/` and `test-results/arm64/R-M09-89-20260915T003535Z/`.
- QA F verified ARM image builds, Node arm64, Python aarch64/QEMU `7.2`, non-root user `10001`, wheel/package, static-member identity, and supplemental runtime. Supplemental runtime: `/tmp/opencode/r-m09-90-arm64/runtime-after-restart.json`. Host surface: `/tmp/opencode/r-m09-91-arm64/host-browser-surface/`, reporting 10/10.
- Unavailable evidence remains explicit: native/physical ARM64 performance, ARM-native browser, physical mobile, actual screen-reader use, and true zoom. No emulated or axe/MCP result substitutes for those limitations.

## Blocking repairs

### `R-ASTRA-89` — duplicate landmark name

- Status: **Pending**.
- Location: [`src/stock_probs/static/app.js`](src/stock_probs/static/app.js), with the existing dashboard browser spec changed only if a scoped test adjustment is genuinely required.
- Defect: simultaneous saved-results and fresh-cutoff comparison regions both expose accessible name `horizon scan`, producing Axe `landmark-unique` failures.
- Minimal repair: give the fresh visible heading the text `Fresh horizon scan`; preserve normal labels, IDs, selectors, and data behavior.
- Required rerun: exact desktop/mobile saved-results and fresh-cutoff browser test, followed by independent QA.
- Do not broaden this into a landmark redesign.

### `R-ASTRA-90` — ARM smoke orchestration

- Status: **Pending**.
- [`scripts/arm64-smoke.sh`](scripts/arm64-smoke.sh) must accept `R-ASTRA-<n>` task IDs rather than rejecting the repair lane.
- Emulated readiness must remain bounded at approximately 180 seconds for the observed approximately 109-second startup; do not weaken native readiness limits.
- The smoke must assert `news["query"]["symbol"]`.
- Override health timeout only in [`scripts/compose.arm64.yml`](scripts/compose.arm64.yml) for ARM.
- Use an explicit primary 10-test host-x86 browser subset rather than all 36 browser tests under QEMU.
- Preserve the no-performance-claim rule, bounded cleanup, and bounded logs.
- Required rerun: canonical ARM smoke with the exact accepted task ID, plus independent QA.
- Do not relabel an unsupported task ID or infer a gate from a partial smoke.

## Required continuation sequence

1. Implement only the minimal `R-ASTRA-89` and `R-ASTRA-90` repairs, with disjoint ownership if concurrent agents are used. No speculative abstractions or unrelated cleanup.
2. At the repair boundary run:
   `./scripts/ponytail-review.sh R-ASTRA-90 test-results/ponytail-r-astra-90-redesign.txt`
3. Record exact Ponytail environment, UTC, commit, result, artifact, reviewer, and findings. A finding remains overengineering-only unless independently reproducible and blocking.
4. Independently rerun the affected landmark browser tests and canonical ARM smoke.
5. Keep native x86 performance separate from emulated ARM functional/package/runtime evidence.
6. Run the supported consolidated M09/release regression only after inspecting the current task-ID contract. Record failures, skips, unavailable hardware, and artifacts exactly; do not relabel unsupported IDs.
7. After independent QA passes, reconcile documentation with the named QA receipt. Do not erase earlier failures or limitations.
8. Run dedicated ASTRA review at 1440, 1280, 768, 390, 360, and 320 widths in Light and Dark using official Playwright/MCP.
9. ASTRA evaluates only; SOL repairs only. Repeat independent QA, docs, and ASTRA review for affected rows.
10. Only after all acceptance rows pass, perform sanitized session export, strict secret review, feature-branch checkpoint commit, push, and exact remote verification.
11. Never claim release, export, notification, or remote success before the corresponding receipt exists.

## Quick-start checks and safety

- Inspect without mutation:
  `git status --short --branch`
  `git diff 0f02f5f0a0dcbf0f1ee42d6c3d930f9bd2fe0ed4 --name-status`
  `git diff 0f02f5f0a0dcbf0f1ee42d6c3d930f9bd2fe0ed4 --stat`
- Verify Node, Python, Docker, and QEMU before any gate.
- Canonical frontend build: `./scripts/build-frontend.sh`.
- Use isolated ports, temporary directories, and temporary database state.
- Do not use or modify the tracked SQLite database.
- Do not run `git reset`, `git clean`, destructive checkout, `git add`, commit, push, branch deletion, tag mutation, remote mutation, or history rewriting during this continuation unless a later gate explicitly authorizes the exact operation.
- Do not edit [`README.md`](README.md), [`AGENTS.md`](AGENTS.md), [`MVP-PLAN.md`](MVP-PLAN.md), [`MVP-ROADMAP.md`](MVP-ROADMAP.md), implementation/configuration outside the authorized repair scope, or [`SESSION-EXPORT.md`](SESSION-EXPORT.md) during the handoff task.
- `SESSION-EXPORT.md` remains export-owned and historical until the final export gate.

## Relevant links

- Dashboard: [`frontend/app/page.tsx`](frontend/app/page.tsx), [`frontend/app/api-docs/page.tsx`](frontend/app/api-docs/page.tsx), [`frontend/app/settings.tsx`](frontend/app/settings.tsx), [`src/stock_probs/static/app.js`](src/stock_probs/static/app.js), [`src/stock_probs/static/app.css`](src/stock_probs/static/app.css), [`src/stock_probs/static/theme.js`](src/stock_probs/static/theme.js).
- API/package/build: [`src/stock_probs/api.py`](src/stock_probs/api.py), [`scripts/build-frontend.sh`](scripts/build-frontend.sh), [`scripts/package_smoke.py`](scripts/package_smoke.py), [`frontend/tests/export-contract.test.mjs`](frontend/tests/export-contract.test.mjs).
- ARM/gates: [`scripts/arm64-smoke.sh`](scripts/arm64-smoke.sh), [`scripts/compose.arm64.yml`](scripts/compose.arm64.yml), [`scripts/local-gate.sh`](scripts/local-gate.sh), [`scripts/ponytail-review.sh`](scripts/ponytail-review.sh).
- Browser: [`tools/browser/playwright.config.js`](tools/browser/playwright.config.js), [`tools/browser/tests/dashboard.spec.js`](tools/browser/tests/dashboard.spec.js).
- Tests: [`tests/test_api.py`](tests/test_api.py), [`tests/test_container_contract.py`](tests/test_container_contract.py), [`tests/test_performance_harness.py`](tests/test_performance_harness.py), [`tests/test_ponytail_tooling.py`](tests/test_ponytail_tooling.py), [`tests/test_resource.py`](tests/test_resource.py).
- Evidence index: [`docs/evidence/astra-final-report.md`](docs/evidence/astra-final-report.md).
- Ignored/local evidence is intentionally referenced as inline code, never as Markdown links.

## Handoff validation

- Intended artifact path: `/home/brajam/repos/stock_probs/HANDOFF.md`.
- After transport writes this file, run:
  `git diff --check -- HANDOFF.md`
  `git diff --no-index --check /dev/null HANDOFF.md`
  `wc -l -- HANDOFF.md`
- Because the file is intentionally untracked, the no-index command may return status `1` for the expected content difference from `/dev/null`; its output must contain no whitespace errors.
- Do not use `git add --intent-to-add` to make the check inspect the file.
- Run `.dev-venv/bin/python scripts/validate_docs.py` only if it is safe for this temporary handoff and does not edit files. If unavailable or denied, record **Unavailable**; do not infer a validator pass.
- The final transport report must return the exact path, line count, command results, and portability warnings.
- No other file or Git state may be mutated by the transport-only lane.
