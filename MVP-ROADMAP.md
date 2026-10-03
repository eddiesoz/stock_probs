# Stock Probability MVP Roadmap

## Status Snapshot

### Current approval status

`R-ASTRA-110` is the current Microsoft Authenticator iOS setup-routing follow-on, deployed at pushed
clean `main` revision `566baab14c298fb52b5edb3138d64cd3e9123311`. `R-ASTRA-109` is the historical
pre-R110 deployed Microsoft Authenticator dropdown follow-on, extending the chooser introduced by `R-ASTRA-108` after
the deployed key-reuse repair in `R-ASTRA-107`; `R-ASTRA-103` is the deployed authenticator-only baseline.
Invite-only GitHub OAuth remains the identity boundary, while production requires a six-digit TOTP
code from an authenticator app as its second factor. The deployed schema-10 migration revokes
stored credentials and old passkey sessions; the application does not create or accept WebAuthn
credentials.
Recovery codes are
hashed and single-use. Production GitHub-auth backup/restore actions require fresh TOTP proof; local
authentication can use fresh local-passkey proof for the same step-up window.

`R-ASTRA-111` tracks source-only OAuth admission changes: schema 11 clears OAuth transaction rows
while preserving users, sessions, and research records; the supported CLI verifies a
schema-10 pre-migration backup. The scope also includes explicit production Compose ingress
attribution installed through the existing reviewed host-Compose updater. The scoped Sol security
review and independent Luna Docker bridge regression passed. The first full local gate failed on
four stale schema-10 test expectations; the corrected full gate then passed, and parent integrated
review found no blocker for the declared local scope. The deployed R-ASTRA-110 image remains schema
10; no R-ASTRA-111 deployment or release is claimed.

Scoped independent QA passed `64` authentication/repository/list checks, `123` API checks, `61`
backup/CLI checks, `10` desktop/mobile-emulated auth-flow cases, `27` frontend checks, Ruff, and
diff checks. Fresh schema-10 creation and schema-9-to-10 migration checks passed; the `61` backup/CLI
check set passed. No schema-10 backup/restore rehearsal is claimed. The
owner API flow returned `303` to `/authenticator?mode=enroll`, required TOTP for protected access,
denied private history without a session, and returned `403` for WebAuthn. Existing TOTP factor
replacement remained guarded. Astra's independent medium source security review reported no P1/P2
finding.

The deployed baseline `R-ASTRA-103` local gate **Passed** for its declared scope. Receipt:
`test-results/local-gates/R-ASTRA-103-20260928T235350Z/evidence.json`; it reports `707` Python
tests passed, `4` live tests deselected, `85.25%` coverage, frontend build/typecheck and `27`
frontend tests, and documentation coverage. The schema-9 predeploy backup remains an offline
recovery artifact only. `R-ASTRA-102` and `R-ASTRA-101` remain historical deployment records and
are not current auth guidance.

The reviewed exact remote `main` revision `9cc0751da459e911d285b14e0d57a29320a9f366` was published
as GitHub Release `signal-ledger-9cc0751da459e911d285b14e0d57a29320a9f366`; archive SHA-256
`d60da545be26a050e305e13d2e8db219a253a0668b32f13f532148069bde188e`, Linux/amd64 image ID
`sha256:3e5f242573044114797b66447e3a8139ed35ca7decc387e6f1ab3ef62db486ff`, and size
`103143811` bytes. Publisher re-download verification passed. Restricted MCP plan
`16c6655376c3b80569694ce400a2381c` passed; deploy returned readiness schema `10`, and status
reported the exact revision, backup `pre-deploy-9cc0751da459e911-20833573.spbackup`,
`deployed_at=2026-09-29T00:21:06.828904+00:00`, `failed: null`, and `loopback_only: true`.
Live HTTPS at `00:22:18Z`–`00:22:19Z` returned health `200`, anonymous history `401`, and overview
`303` to sign-in with `no-store`/`DYNAMIC`; `/passkey?mode=verify` returned `303` to
`/authenticator?mode=enroll&next=%2Foverview`. The IAB showed the revoked old session's
`Sign in first` state; fresh GitHub sign-in as `jtmb` rendered the authenticator setup page without
a WebAuthn prompt. Owner TOTP enrollment, workspace content, saved holdings, physical mobile, and
second-user acceptance remain unavailable.

`R-ASTRA-101` remains the historical schema-8 passkey deployment record; its passkey and live-host
receipts must not be used as acceptance evidence for this TOTP release.

`EXP-M09` remains the current approval-gated export item. `R-ASTRA-110` remains **In progress** for
complete owner authentication but is **Completed** for its declared UI repair, local QA, deployment,
and live-guidance scope; native Microsoft app interaction, owner enrollment, and physical iPhone code
acceptance remain **Unavailable**. `R-ASTRA-109` is the historical pre-R110 chooser record: its live
selection flow displayed guidance, but no setup key or TOTP code was generated or entered, and the
read-only database query at that checkpoint found zero owner factors and zero active pending
enrollments. The user later reported successful Firefox sign-in; this is an attributed report that
has not been independently verified and does not independently establish authenticated workspace
retrieval. `R-ASTRA-107` is deployed
through R110 but remains incomplete for owner TOTP acceptance. `R-ASTRA-100` is **Completed for its
declared UI scope** with the evidence recorded below; this does not create a broader release or
export checkpoint. `M09-E18`, `M07-E20`, and `R-ASTRA-98` remain recorded for their declared scopes.
The remaining M09 action is `EXP-M09`: full-session export, secret review, local commit, push,
and exact remote verification. Unavailable evidence categories—actual screen reader, physical
mobile, true browser zoom, native ARM64 performance, provider runtime, and project-profile/skill
runtime discovery—remain separate limitations and are not converted into passes by this follow-on.

`M09-E13` is a frozen historical constraint for the M09 contract, not a current absence-audit
task. Its original rejected M09 scope remains intact. Later `R-ASTRA-98` separately
approved/evidenced bounded watchlists, forecast/model expansion, and provider-labelled
quote/daily-bar market-data research; that later research scope does not retroactively alter
`M09-E13`, reopen M09 implementation, or invent a new task. `M09-E14` and the retained
Ponytail/`R-M09-1` boundary record are historical overengineering evidence superseded for the
declared M09 scope by `M09-E18`; no current repair or Ponytail action follows from them.
`R-M07-1` and `R-M07-2` retain historical statuses only and are superseded for M07's declared
integrated scope by `M07-E20`; no current M07 repair, Ponytail availability review, or retest is
open.

## Current native OpenCode V2 workflow

### Current V2/documentation reconciliation evidence

The approved project governance set has seven directory-based skill definitions:
`documentation`, `development-conventions`, `stock-probability-skill-maintenance`,
`local-gate-evidence`, `browser-qa`, `database-conventions`, and `security-audit`. Ponytail is
retired: no local package, plugin, dependency pin, command, boundary review, or acceptance gate
is current. This static definition/governance count is not native loader or runtime discovery
acceptance. Historical Ponytail receipts remain below for traceability only. Native V2
automatically discovers `.opencode/skills/<id>/SKILL.md`; the `skills` configuration array is an
additional later-precedence source list, so no explicit `.opencode/skills` entry is expected in
`opencode.json`.
The `metadata.json` files, `alwaysApply: false`, `.opencode/SKILL-INDEX.md`, validator allow-list,
and `.opencode/skill-history/learnings.md` remain governance contracts, not loader proof. Native
runtime skill discovery is **Unavailable** in this harness because `OPENCODE_DISABLE_PROJECT_CONFIG=1`;
no runtime loader result is inferred. The provider/model runtime probe is also
**Unavailable** when it reports `provider.quota`, `Insufficient Balance`, and HTTP `402`; no
provider or project-profile acceptance is inferred.

The coordinator's exact CLI rerun returned `opencode v2.0.7` from both `opencode --version` and
`/home/james/.local/opt/opencode-v2/opencode --version`; `/home/james/.local/opt/opencode-v2/opencode debug --help`
listed only `agents`, `config`, and `paths`; and
`printenv OPENCODE_DISABLE_PROJECT_CONFIG` returned `1`. These version/help facts do not establish
skill discovery.

Loader-boundary evidence is separated. Supplied builder static evidence recorded config/docs tests
`73/73`, comment tests `5/5`, validator `9` categories/`13` topics/`7` governance entries,
documentation self-test `26/26`, completeness `111` mapped files, and dirty-tree coverage `154`
inputs/`0` violations, with Ruff/security/comment audit `203` files plus JSON/frontmatter,
shell-syntax, and diff checks **Pass**. Independent Luna QA passed the static loader-boundary
scope on native x86_64 at dirty revision `09ba8b8dd285bd64c34241069051936c82c6390b`: exactly seven
directory `SKILL.md` files, no flat skill files, history-path migration, no explicit skills config,
retired Ponytail absence, and docs/map semantics **Pass**. This is independent static QA, not
native runtime discovery, provider runtime, release, or clean-scope acceptance; clean-scope proof
remains **Unavailable** because of the broad pre-existing dirty worktree, and no provider runtime
or service restart was invoked.

This is the current operational overlay. The status and delivery receipts below preserve their
historical V1/Astra/SOL/Orchestrator/Ponytail wording for traceability, but that wording is not
current workflow guidance. Native V2 uses the builtin `build` and `plan` entry points in
`opencode.json`.
Current Luna ownership is `.opencode/agents/luna-build.md` for implementation/tests,
`.opencode/agents/luna-qa.md` for read-only independent QA, and
`.opencode/agents/luna-docs.md` for `AGENTS.md`, `README.md`, `MVP-PLAN.md`, `MVP-ROADMAP.md`,
and authored `docs/**/*.md`.

Project configuration, profiles, commands, plugins, and `.opencode` dependencies are loaded at
parent startup; each change requires restart and independent post-restart discovery. With
`OPENCODE_DISABLE_PROJECT_CONFIG=1`, project-profile discovery and runtime acceptance are
**Pending**/**Unavailable**. The real V2 provider probe emitted an error event without a report,
which is **Unavailable** evidence, not provider/project-profile acceptance.

QA uses only **Pass**, **Fail**, **Skipped**, and **Unavailable**. Builder output, file presence,
generated artifacts, skipped checks, unavailable providers, and unavailable hardware cannot
close a gate. Native x86_64, emulated ARM64, and physical ARM64/mobile/screen-reader/true-zoom
evidence remain distinct. The documentation map plus fail-closed `.githooks/pre-push` gate
requires mapped workflow changes to update `docs/develop/documentation.md` and `AGENTS.md`.
This docs-only reconciliation does not install hooks, commit, push, or edit `SESSION-EXPORT.md`.

## Current research-workspace expansion (`R-ASTRA-98`)

`R-ASTRA-98` is the current research-workspace expansion: `/overview` holds manually entered
portfolio context, `/research` links recorded research destinations, and `/tools` exposes
`/tools/forecast`, `/tools/live-trading`, and `/tools/markets`. Forecast accepts the explicit
`5min`, `daily`, `weekly`, `monthly`, or `quarterly` interval selection; Markets provides bounded
watchlists, provider-labelled quote snapshots, and daily bars; Live Trading is research-only and
has no order execution, brokerage connection, real-time guarantee, market-depth endpoint, or
Nasdaq TotalView data.

The post-reconciliation native-x86_64 receipt supersedes the earlier R-ASTRA-98 aggregate. It ran
`TMPDIR=/home/james/.cache/stock-probs-gate-tmp TASK_ID=R-ASTRA-98 ./scripts/local-gate.sh check`
on dirty revision `09ba8b8dd285bd64c34241069051936c82c6390b` at
`2026-09-18T15:47:01Z`–`2026-09-18T15:53:58Z`, **Passed** with exit `0`: `545` Python tests
passed, `4` were deselected, no skipped test was reported, and coverage was `90.38%`. Frontend
checks passed `17/17`, including typecheck and the Next production build; static routes include
`/`, `/api-docs`, `/overview`, `/research`, `/tools`, `/tools/forecast`, `/tools/live-trading`,
and `/tools/markets`. Completed checks were `documentation-completeness`,
`frontend-npm-ci-typecheck-build-test-stage`, and `python-checks`. The receipt is
`test-results/local-gates/R-ASTRA-98-20260918T154701Z/evidence.json`. Separate supplied QA
passed `240` backend tests and `4/4` desktop/mobile-emulated browser cases with axe `0/0`; live
Yahoo checks covered `ACDC`, `SPY`, `SHOP.TO`, `VFV.TO`, and `PNG.V`. The browser artifact is
temporary: `/tmp/opencode/r-astra-98-browser-final-pass`. Native ARM64, physical mobile, true
browser zoom, and actual screen-reader acceptance remain **Unavailable**. The recorded aggregate
is scoped dirty-worktree evidence; it does not itself establish release/export/commit/push
acceptance.

## Current Signal Ledger UI refinement follow-on (`R-ASTRA-99`)

`R-ASTRA-99` is a new follow-on to the historical `ASTRA-FINAL` and completed `R-ASTRA-22`
visual records. It covers a cohesive presentation pass over `/`, `/overview`, `/research`,
`/tools`, `/tools/forecast`, `/tools/live-trading`, `/tools/markets`, and `/api/v1/docs`.
Shared Light/Dark/System typography, spacing, semantic colors, surfaces, controls, forms,
tables, charts, and status treatments support calmer Overview/Research entry points, a
probability-first Forecast flow, and denser Live Trading/Markets research surfaces. Provider,
as-of, delay, and research-only labels remain visible; existing APIs, saved data, instrument
identity, theme behavior, and research-only boundaries remain unchanged. Buy/Sell controls,
order routing, real-time claims, and fabricated market depth are outside this follow-on. The
holdings editor remains available after saving so additional holdings can be added repeatedly.

- **Status:** **Completed for its declared UI scope**.
- **Owner/phase:** implementation follow-on, independent `LUNA MAX QA` visual/browser review,
  and `LUNA MAX docs` evidence reconciliation for the completed declared scope.
- **Dependencies:** `R-ASTRA-98` supplies the current workspace and data-contract baseline;
  `ASTRA-FINAL` and `R-ASTRA-22` remain closed only for their declared scopes and are not
  reopened by this follow-on.
- **Verification state:** build, capture, scoped browser, media, isolated-container, deployment,
  current-session, and post-repair semantic accessibility evidence is recorded below. This is
  completion for the declared UI scope; no release/export/commit/push checkpoint is created.

| Evidence ID | Requirement/check | Environment, UTC time, commit | Result, artifact, reviewer, limitation |
| --- | --- | --- | --- |
| `R-ASTRA-99-E1` | Shared visual system and eight-route composition, including repeatable holdings editing and preserved research-only boundaries. | Current native x86_64 worktree; exact UTC and commit were not supplied. | **Pass as supplied implementation evidence**; source paths are the artifact; independent acceptance is not inferred. |
| `R-ASTRA-99-E2` | Frontend production build for all eight static routes and frontend test set `17/17` passed. | Commands `/home/james/repos/stock_probs/.tools/node/bin/npm --prefix frontend run build` and `/home/james/repos/stock_probs/.tools/node/bin/npm --prefix frontend test`; exact UTC and commit were not supplied. | **Pass as supplied coordinator self-validation**; build output lists 8 routes and tests report `17/17`; no release or clean-tree result is inferred. |
| `R-ASTRA-99-E3` | Before/after capture sweep: `64` screenshots before and `64` after at `390`, `768`, `1280`, and `1920` in Light/Dark; final report records `64` captures and `0` page-overflow findings. | Current fixture capture; exact UTC and commit were not supplied. | **Pass as supplied screenshot evidence**; artifact `/tmp/stock-probs-ui-final/report.json`; temporary artifact, no release checkpoint. |
| `R-ASTRA-99-E4` | Independent review of `32` representative screenshots for all eight routes in Light/Dark at mobile `390px` and desktop `1280px`, plus repeated holdings updates twice, unavailable depth, API docs, and Markets layout. | Native x86_64; `2026-09-25T15:13:32Z`–`15:16:27Z`; dirty revision `09ba8b8dd285bd64c34241069051936c82c6390b`; commands followed `UI_ORIGIN=http://127.0.0.1:18768 UI_CAPTURE_DIR=/tmp/stock-probs-ui-visual-qa-390 UI_WIDTHS=390 ... /tmp/capture-ui-refinement.cjs` and the corresponding `1280` run. | **Pass** as independent review evidence; reviewer `LUNA MAX QA`; artifacts `/tmp/stock-probs-ui-visual-qa-390/`, `/tmp/stock-probs-ui-visual-qa-1280/`, and holdings captures `/tmp/stock-probs-ui-visual-qa-holdings/live-trading-390-light.png` and `/tmp/stock-probs-ui-visual-qa-holdings/live-trading-1280-dark.png`. Independent QA sampled `390px`/`1280px`; coordinator captures cover `768px`/`1920px`. |
| `R-ASTRA-99-E5` | Post-repair scoped expansion browser flow rerun `6/6` passed, including two holdings saves and the repeated-add regression path. | Browser fixture; coordinator log `/tmp/stock-probs-ui-expansion-final.log`; exact UTC and commit were not supplied. | **Pass as coordinator self-validation**; reviewer `Codex coordinator`; no current-session deployment claim is inferred. |
| `R-ASTRA-99-E6` | Full dashboard suite bounded by a fixed `300s`: `68` completed cases passed and `6` cases were not run when the bound elapsed. | Bounded dashboard run; logs `/tmp/stock-probs-ui-dashboard-complete.log` and `/tmp/stock-probs-ui-dashboard-tail.log`; exact UTC and commit were not supplied. | **Pass** for the `68` completed cases and **Skipped** for the `6` not-run cases; reviewer `Codex coordinator`; the timed aggregate is not called a full-suite pass. |
| `R-ASTRA-99-E7` | The six remaining mobile dashboard cases were run separately after the bounded run. | Separate mobile continuation; log `/tmp/stock-probs-ui-dashboard-tail.log`; exact UTC and commit were not supplied. | **Pass**: `6/6`; reviewer `Codex coordinator`; this is the separate continuation, not a relabelling of the bounded aggregate. |
| `R-ASTRA-99-E8` | Targeted dashboard accessibility checks and the expansion browser flow. | Coordinator browser checks; logs `/tmp/stock-probs-ui-dashboard-axe.log` and `/tmp/stock-probs-ui-expansion-final.log`; exact UTC and commit were not supplied. | **Pass**: targeted dashboard axe `6/6` and expansion `6/6`; reviewer `Codex coordinator`. |
| `R-ASTRA-99-E9` | Forced-colors and print media review: `12` screenshots at `390px` and `1280px` across the dashboard, Markets, and API docs, with a populated Live Trading capture confirming the editor remains visible with four isolated-fixture holdings. | Coordinator fixture media review; artifact `/tmp/stock-probs-ui-media/report.json`; exact UTC and commit were not supplied. | **Pass as coordinator screenshot evidence**; reviewer `Codex coordinator`; `0` overflow findings; selected screenshot path and exact command were not supplied. |
| `R-ASTRA-99-E10` | Final after-capture sweep at widths `390`, `768`, `1280`, and `1920` in Light and Dark. | Current fixture capture; exact UTC and commit were not supplied. | **Pass as coordinator screenshot evidence**; reviewer `Codex coordinator`; artifact `/tmp/stock-probs-ui-final/report.json`, `64` captures, `0` page-overflow findings. |
| `R-ASTRA-99-E11` | Final Docker Compose build and isolated-container validation after the semantic accessibility repair. `docker compose build app` passed with image `sha256:5e652316ef2a70baf0aacd34dd6b06a7ca363967dd81c17bb344f032ea0c5932`; the disposable-tmpfs container on `127.0.0.1:18767` returned readiness `200`, verified `<title>Tools \| Signal Ledger`, and produced `32` route captures with `0` overflow findings before it was stopped. | Current local Docker environment; build log `/tmp/stock-probs-ui-docker-build-final.log`; exact UTC and commit were not supplied. | **Pass**; artifact `/tmp/stock-probs-ui-container-final/report.json`; reviewer `Codex coordinator`; prior image `sha256:87ef1f01ee1cb7113e80c94a9b86f449e1b7aac0f237bb326aa058730cb97c38` remains superseded historical evidence. |
| `R-ASTRA-99-E12` | Final existing-container deployment and current-session preservation. `docker compose up -d --no-build app` runs the final image SHA `sha256:5e652316ef2a70baf0aacd34dd6b06a7ca363967dd81c17bb344f032ea0c5932` with the existing `stock_probs_stock-probs-data` volume; the container is healthy/readiness `200`. API checks preserved `BBW10`, `ACDC10`, `SOC10`, `PYPL10`, `JD10`, and `ZTS10`; the restored IAB ACDC Live Trading port-`8000` URL showed all six holdings, six snapshots, the editor and Update holdings control, and honest unavailable depth. | Current local Docker/browser session; exact UTC and commit were not supplied. | **Pass** as coordinator deployment/session evidence; reviewer `Codex coordinator`; no release/export/commit/push or remote verification is inferred. |
| `R-ASTRA-99-E13` | Semantic accessibility verification after the source repair: Tools title/landmark, Live Trading workspace controls grouping, and presentational empty depth tables; fixture coverage at `390px` and `1280px` in Light/Dark was `32/32` with zero violations and zero incomplete checks. | Coordinator isolated-fixture check; artifacts `/tmp/stock-probs-ui-all-axe-semantic.log` and `/tmp/stock-probs-ui-all-axe-1280.log`; exact UTC and commit were not supplied. | **Pass** as coordinator accessibility self-validation; reviewer `Codex coordinator`; this is fixture evidence, and the separate deployed user-data axe check is recorded in `E15`. |
| `R-ASTRA-99-E14` | Final expanded browser regression with explicit Tools title/landmark and Live Trading controls-group assertions. | Coordinator browser fixture; log `/tmp/stock-probs-ui-expansion-final-semantic.log`; exact UTC and commit were not supplied. | **Pass**: `6/6`; reviewer `Codex coordinator`. |
| `R-ASTRA-99-E15` | Final deployed user-data axe check at `390px` in Light/Dark after the final container deployment. | Final deployed app; command completed with exit `0`; exact UTC and commit were not supplied. | **Pass**: all eight routes, `16/16` cases, `0` violations, and `0` incomplete checks; artifacts `/tmp/stock-probs-ui-all-axe-deployed.log` and `/tmp/stock-probs-ui-all-axe-deployed.json`; reviewer `Codex coordinator`. |
| `R-ASTRA-99-E16` | Independent Luna route/theme sweep: all eight route URLs plus `/api-docs` returned HTTP `200`; Light/Dark at `390px` and `1280px` covered `32/32` primary cases with axe `0` violations/`0` incomplete checks, no overflow, and no page or console errors. | Native x86_64 Linux; `2026-09-26T21:28:35.520Z`–`21:33:23.255Z`; dirty `HEAD` `09ba8b8dd285bd64c34241069051936c82c6390b`. | **Pass**; artifact `/tmp/luna-site-qa-final-18778/report.json`; reviewer `LUNA MAX QA`; fixture evidence, not provider or release acceptance. |
| `R-ASTRA-99-E17` | Independent Luna special-state sweep: System light/dark, forced-colors, and reduced-motion at `390px` across all eight routes covered `32/32` cases with axe `0/0`, no overflow, and no page or console errors. Populated Live Trading with three holdings kept the editor visible; print at `390px` had `scrollWidth = clientWidth = body = 390` and no offenders. | Native x86_64 Linux; `2026-09-26T21:28:35.520Z`–`21:33:23.255Z`; dirty `HEAD` `09ba8b8dd285bd64c34241069051936c82c6390b`. | **Pass**; report `/tmp/luna-site-qa-final-18778/report.json`, screenshot `/tmp/luna-site-qa-final-18778/populated-live-print-390.png`; reviewer `LUNA MAX QA`; print axe had `0` violations but `8` `color-contrast` incomplete nodes, so print contrast is not promoted to a complete check. Four transient Markets request aborts were followed by HTTP `200` responses and were treated as request supersession, not a product failure. |
| `R-ASTRA-99-E18` | Coordinator API audit exercised all `23/23` documented API operations against an isolated fixture, including list mutation, forecast/history/saved/reconstruction/prices, outcomes/corrections, and backup/restore verification; each returned its expected status. | Native x86_64 Linux; exact UTC and commit were not supplied; isolated fixture; script `/tmp/stock-probs-api-audit.py`. | **Pass** as scoped coordinator validation; artifact/script `/tmp/stock-probs-api-audit.py`; no production data mutation or release acceptance is inferred. |
| `R-ASTRA-99-E19` | Frontend typecheck, production build, and frontend tests passed; the build covers the eight static routes and reports `17/17` frontend tests. A rebuilt Docker image with digest `sha256:16079f2a0946cb27df3c29ded9359fb95553b581128a838c2572223c10669939` passed disposable-container `/api-docs` and Live Trading HTTP checks with zero seeded holdings. | Native x86_64 Linux; exact UTC and commit were not supplied; disposable isolated container. | **Pass** for the recorded build/container scope; reviewer `Codex coordinator`; no clean-tree, export, commit, push, or remote result is inferred. |
| `R-ASTRA-99-E20` | Production deployment with the existing data volume remained healthy; `/api-docs` returned `200`, and the current browser session preserved exactly `BBW: 10`, `ACDC: 10`, `SOC: 10`, `PYPL: 10`, `JD: 10`, and `ZTS: 10`, with six quote snapshots and no holdings mutation. | Native x86_64 Docker/browser session; `2026-09-26T21:42:10.803Z`–`21:43:34.347Z`; dirty `HEAD` `09ba8b8dd285bd64c34241069051936c82c6390b`. | **Pass**; artifact `/tmp/luna-site-qa-production-8000/report.json`, screenshot `/tmp/luna-site-qa-production-8000/production-live-holdings.png`; reviewer `LUNA MAX QA`; Markets quotes/bars can return provider capacity `503` with an explicit unavailable state, recorded in `/tmp/luna-site-qa-production-8000/markets-targeted.json`; no provider acceptance is claimed. |
| `R-ASTRA-99-E21` | The first unsharded `82`-case browser command exited `1` at the global timeout after `37` completed passes, one contrast assertion failure, and `44` cases not run; it is not a suite pass. Sharded runs recorded desktop part 1 `21/21`, desktop part 2 `17` passed/`3` failed/`1` skipped, mobile part 1 `20/20`, and mobile part 2 `17` passed/`2` failed/`1` skipped. Targeted reruns passed the five failed case identities (desktop/mobile theme, mobile settings, desktop news, and desktop M04) after source/test repairs; the timeout and original shard failures remain recorded. | Native x86_64 fixture browser; exact UTC and commit were not supplied; shard artifacts `/tmp/stock-probs-browser-final-shard-1`, `/tmp/stock-probs-browser-final-shard-2`, `/tmp/stock-probs-browser-final-shard-3`, `/tmp/stock-probs-browser-final-shard-4`; targeted artifacts `/tmp/stock-probs-browser-targeted`, `/tmp/stock-probs-browser-mobile-rechecks`, and `/tmp/stock-probs-browser-desktop-rechecks`. | **Fail** for the initial aggregate because it exited `1` at the global timeout; **Pass** for the listed shard and targeted rerun results where stated. Reviewer `Codex coordinator`; no single green `82`-case result is inferred, and physical mobile, actual screen reader, true zoom, and native ARM64 performance remain **Unavailable**. |
| `R-ASTRA-99-E22` | Scoped backend regression rerun covered API, market quotes, instrument lists, and forecast horizons: `151` tests collected and all `151` passed. | Native x86_64 Linux; exact UTC and commit were not supplied; command `.dev-venv/bin/python -m pytest tests/test_api.py tests/test_market_quotes.py tests/test_instrument_lists.py tests/test_forecast_horizons.py -q`. | **Pass** as coordinator scoped self-validation; reviewer `Codex coordinator`; this is not the full local gate or release acceptance. |
| `R-ASTRA-99-E23` | Packaged API audit against the disposable rebuilt Docker image and tmpfs data passed `23/23` documented operations with expected GET/POST/DELETE/status responses after health readiness. The first immediate attempt returned `RemoteDisconnected` during startup and is retained as a startup-timing failure; the health-gated rerun passed. | Native x86_64 Docker fixture at `127.0.0.1:18767`; exact UTC and commit were not supplied; artifact/script `/tmp/stock-probs-api-audit-container.py`. | **Fail** for the initial startup attempt; **Pass** for the health-gated `23/23` rerun; reviewer `Codex coordinator`; no production data mutation or provider acceptance is inferred. |

The roadmap records `R-ASTRA-99` as **Completed for its declared UI scope**. The bounded
dashboard run is preserved as `68` passed and `6` skipped/not run; the separately completed
`6/6` mobile continuation means all `74` case identities were exercised successfully, but the
timed aggregate is not relabelled as a suite pass. Physical mobile, true browser zoom, actual
screen-reader, native/physical ARM64 performance, provider runtime, and project-profile runtime
discovery remain **Unavailable** unless directly exercised. The 2026-09-26 site-wide QA follow-on
adds independent fixture and deployed-session evidence above; its timed `82`-case attempt remains
**Unavailable** and is preserved with the successful shards and targeted reruns rather than
collapsed into one aggregate result. This follow-on creates no export, commit, push, remote
verification, or broader release acceptance.

## Current Astra product follow-on (`R-ASTRA-100`)

`R-ASTRA-100` is a new implementation follow-on to `R-ASTRA-99`, based on Astra's review of
populated routes. It preserves the existing APIs, saved data, instrument identity, provider/as-of/
delay labels, theme behavior, and research-only market-data boundaries. Brokerage connections,
order routing, real-time claims, and fabricated market depth remain outside scope.

- **Status:** **Completed for its declared UI scope**; the opening unavailable rows remain
  historical, while the later implementation, independent QA, deployment, and documentation rows
  close the declared follow-on scope.
- **Owner/phase:** implementation follow-on, then independent `LUNA MAX QA` verification;
  `LUNA MAX docs` records supplied evidence only. This is not a release, export, commit, push, or
  remote-verification checkpoint.
- **Dependencies:** `R-ASTRA-99` completed its declared UI scope and `R-ASTRA-98` remains the
  workspace/data-contract baseline. `ASTRA-FINAL` and `R-ASTRA-22` remain closed only for their
  declared scopes.
- **Scope:**
  - Forecast headings and summaries reflect the actual saved-result count and selected horizon;
    readable interval values remain primary while exact values and schema units stay in provenance.
  - Overview selection exposes provider-labelled quote context and the latest saved forecast event,
    including source/as-of/delay and saved-result semantics.
  - Research exposes the five latest saved events with honest outcome status and an immutable
    same-instrument saved-forecast comparison covering horizon, target, model, provenance,
    probabilities, and intervals without inferred outcomes.
  - Markets provides compact and optional full-field watchlist views, an accessible bounded
    chart-values table, separate last-bar and retrieval times, and stock/ETF-neutral action wording.
  - Live Trading provides row-based manual quantity editing while preserving visible and repeated
    holding adds, with explicit manual semantics and compact unavailable depth.

| Evidence ID | Requirement/check | Environment, UTC time, commit | Result, artifact, reviewer, limitation |
| --- | --- | --- | --- |
| `R-ASTRA-100-E1` | Initial implementation handoff record for the five scope groups. | No source paths, command, UTC, or commit were supplied at the opening documentation update. | **Unavailable** as an opening record; later implementation evidence is recorded in `R-ASTRA-100-E4` and does not retroactively change this row. |
| `R-ASTRA-100-E2` | Initial independent browser/accessibility evidence record. | Not yet run or supplied at the opening documentation update. | **Unavailable** as an opening record; later independent evidence is recorded in `R-ASTRA-100-E9`. |
| `R-ASTRA-100-E3` | Initial build, isolated-container, and current-session/data-preservation evidence record. | Not yet run or supplied at the opening documentation update. | **Unavailable** as an opening record; later checks are recorded in `R-ASTRA-100-E5`–`E6` and `E11`. |
| `R-ASTRA-100-E4` | Source implementation across `frontend/app/page.tsx`, Overview, Research, Live Trading, Markets, and `src/stock_probs/static/app.js`; frontend build covers 8 static routes, typecheck, and `17/17` frontend unit tests. | Native x86_64 worktree; command `./scripts/build-frontend.sh`; exact UTC and commit were not supplied. | **Pass** as supplied coordinator implementation/build evidence; no clean-tree, release, export, commit, push, or remote result is inferred. |
| `R-ASTRA-100-E5` | Final `docker compose build app` for the follow-on image. | Native local Docker environment; image created `2026-09-27T00:08:28.901Z`; exact commit was not supplied. | **Pass**; image digest `sha256:65e3bf61e19241b89c4c7a4076c8b234a29dc7452257ecc8f6d7d06b3ad765d9`; artifact: final image; reviewer not separately supplied. |
| `R-ASTRA-100-E6` | Isolated disposable-fixture readiness and targeted refinement browser flow. | Isolated container; artifact `/tmp/stock-probs-final-image-qa-rerun`; exact UTC and commit were not supplied. | **Pass**: readiness and refinement `6/6` desktop/mobile; no production data mutation or provider acceptance is inferred. |
| `R-ASTRA-100-E7` | Scoped browser flows in `tools/browser/tests/dashboard.spec.js`, `expansion.spec.js`, and `refinement.spec.js` for the expansion and refinement changes. | Isolated fixture; exact UTC and commit were not supplied. | **Pass**: expansion `8/8` and refined `6/6`; artifact: supplied browser run; reviewer not separately supplied. |
| `R-ASTRA-100-E8` | Broad dashboard coverage and its timeout handling. | Native x86_64 fixture browser; the initial run reached `36/74` before the global `300s` timeout; split continuation passed `37/37` mobile and one remaining desktop case, covering `37` desktop cases total; exact UTC and commit were not supplied. | **Unavailable** for the single timed aggregate because it timed out; **Pass** for the completed split runs. All case identities were exercised across the split runs, but no single green aggregate is inferred. |
| `R-ASTRA-100-E9` | Independent Luna visual/accessibility review: refinement `6/6`, expansion `8/8`, focused dashboard `18/18`, 8-route Light desktop/Dark mobile coverage, no overflow, and no blocking visual finding. | Native x86_64; dirty `HEAD` `09ba8b8dd285bd64c34241069051936c82c6390b`; `2026-09-27T00:02:53Z`–`00:03:21Z`; screenshot artifact `test-results/r-astra-100-independent/` (ignored path, referenced inline). | **Pass**; reviewer `LUNA MAX QA`; independent evidence covers the declared UI review, while actual screen-reader, physical mobile, and true-zoom evidence remain **Unavailable**. |
| `R-ASTRA-100-E10` | Production quote observation during the final session. | Port `8000` production session; exact UTC and commit were not supplied. | **Pass as a nonblocking observation**: an initial quote batch returned transient `503` responses and recovered to `200`; this is not provider acceptance. |
| `R-ASTRA-100-E11` | Final image deployment, health, current-session preservation, and populated Live Trading behavior. | Native x86_64 Docker/browser session; container created `2026-09-27T00:11:48.923Z`, started `2026-09-27T00:11:50.833Z`, healthy at `2026-09-27T00:14:10Z`; provider `yahoo`; exact commit not supplied. | **Pass**; final image deployed to port `8000`; all six holdings remained quantity `10`, 13 ledger events and latest event `#13` remained present, and the refreshed ACDC tab showed the row editor and six quote snapshots. Reviewer not separately supplied; no release/export/commit/push/remote result is inferred. |
| `R-ASTRA-100-E12` | Documentation validator after the completed follow-on record. | Native x86_64; `2026-09-27T00:18:07.723948991Z`; dirty `HEAD` `09ba8b8dd285bd64c34241069051936c82c6390b`; command `.dev-venv/bin/python scripts/validate_docs.py`. | **Pass**; output: `Documentation validation passed: 9 categories, 13 topics, 7 project skill governance entries.` Reviewer `LUNA MAX docs`. |
| `R-ASTRA-100-E13` | Scoped documentation diff check. | Native x86_64; `2026-09-27T00:18:07.747571394Z`; dirty `HEAD` `09ba8b8dd285bd64c34241069051936c82c6390b`; command `git diff --check -- MVP-PLAN.md MVP-ROADMAP.md`. | **Pass**; artifact: scoped two-file diff; reviewer `LUNA MAX docs`; no source, test, configuration, export, commit, push, or Git metadata mutation was performed. |

`R-ASTRA-100` is **Completed for its declared UI scope**. The broad timed dashboard aggregate is
preserved as **Unavailable** because it reached the global timeout; the successful split runs and
targeted flows remain recorded above. The final deployed session preserved the six holdings and 13
ledger events, and the current ACDC tab showed the row editor and quote snapshots. The transient
quote `503` observation recovered to `200` and is not provider acceptance. Actual screen-reader,
physical-mobile, true-zoom, native/physical ARM64-performance, and project-profile runtime evidence
remain **Unavailable**. No release, export, commit, push, or remote-verification result is claimed.

No historical acceptance record is changed. Provider capacity failures, unavailable hardware, physical
mobile, true browser zoom, actual screen-reader, native/physical ARM64 performance, and
project-profile runtime discovery remain separate evidence categories.

## Current Signal Ledger email-invitation follow-on (`R-ASTRA-104`)

**Status: In progress.** Independent scoped QA passed backend invitation/mail and UI checks,
frontend build/typecheck and `27` tests, npm audit with zero advisories, package smoke, and focused
browser `6/6` desktop/emulated-mobile cases. The broader browser attempt is **Unavailable** as a
full aggregate after `44` passed, `61` unrun, and one interrupted case. Astra's medium source-only
review at `2026-09-30T22:14:20Z` on dirty `HEAD`
`010ecab30fc3180751cc74e3737e42675bf6462a` reported no P1/P2. Exact QA commands, artifact paths,
and named QA reviewer were not supplied; no separate overall gate or acceptance receipt is
claimed. Authored documentation validation, change-aware coverage, and scoped diff check passed
at `2026-09-30T22:19:59Z`–`22:20:00Z` on the same dirty revision.

Email is optional and supplements manual single-use invitations. Each invite remains bound to the
numeric GitHub account ID, while the email address is used only for delivery. SMTP acceptance does
not confirm mailbox delivery. `docs/configure/local-configuration.md` documents the six production
SMTP variables; `docs/operations/getting-started.md` documents the operator flow and code-gated
`infra/linode/update-host-compose.sh` procedure; `docs/develop/documentation.md` and `AGENTS.md`
record the documentation coverage boundary. The host updater requires a clean checkout matching
the reviewed SHA and public `origin/main`, verifies the Compose checksum, and replaces the fixed
host file without restarting services.

The initial full local gate **Failed** with `686` passed, `4` deselected, and `45` setup errors
attributed to the documentation fixture's stubbed plan page lacking the linked heading anchor; its
receipt is `test-results/local-gates/R-ASTRA-104-20260930T222152Z/`. After the docs-only link repair,
the full rerun **Passed** for its declared local scope: `731` Python tests passed, `4` deselected,
`85.48%` coverage, frontend build/typecheck and `27/27` tests, documentation coverage, and backup
follow-on checks. Receipt: `test-results/local-gates/R-ASTRA-104-20260930T223407Z/evidence.json`.
The rerun supersedes the initial failure for that scope. Live SMTP/mailbox delivery, production
Compose update/deployment, and the complete browser suite remain **Pending/Unavailable**. No
production delivery or release acceptance is inferred.

## Current deployment-access and invitation-transport follow-on (`R-ASTRA-106`)

**Status: In progress.** Reviewed `main` revision
`de9f45f2d5c562c34e004c658e7cee118af6ef58` was pushed. The private stdio deployment MCP now has
six typed tools, adding `refresh_operator_access(operator_ipv4_cidr)`. It accepts one canonical
IPv4 `/32` and constrains Terraform to the imported `linode_firewall.signal_ledger` resource (ID
`177236117`) and its `ssh-operator` TCP port-22 rule through fixed external private state and the
clean-tree, exact-`origin/main`, reviewed-revision source gate. SMTP accepts `implicit_tls` on `465`
or `2465`, or `starttls` on `587`. The operator's Linode console login uses Google SSO; SSH material
remains separate. The MCP accepts no arbitrary command, path, state, or credential argument.

Independent Luna QA passed `37` focused tests, Ruff/security/compilation, locked MCP stdio six-tool
discovery, and invalid-CIDR behavior for the declared local scope. A later local gate on revision
`411c146` reported `741` Python and `27` frontend checks passed. A separate focused repaired-guard
run on pushed revision `de9f45f2d5c562c34e004c658e7cee118af6ef58` reported `19` passes. The initial
semantic documentation audit failed on stale five-tool/port wording and is repaired by this
documentation update. Terraform stages passed in `./infra/linode/validate.sh`,
but its required dirty-tree gate exited `2`; that aggregate remains **Fail**. The later operator
refresh and deployment receipts below are separate live evidence. Resend domain/DNS preparation and
endpoint transport checks passed for their declared scopes, but API-key creation, host installation,
live SMTP sending/mailbox delivery, owner TOTP enrollment, authenticated workspace retrieval,
physical-mobile/hardware-authenticator evidence, and full production acceptance remain
**Unavailable**.

The Resend free account was created through Google SSO and `mail.jtmb.cc` was reported verified at
approximately `2026-10-01T14:04Z`. Three DNS-only records were committed and pushed in Cloudflare
Terraform at `90ad506dc7c39e145734f295f41ac2a4358b7a14`; format/validate, the exact three-record
create apply, public DNS resolution, and the post-apply no-change plan passed for the DNS scope. The
fixed controller applied operator SSH `142.198.155.54/32`, and Linode TCP plus TLS 1.3 checks to
`smtp.resend.com:2465` passed. These are domain and transport checks only.

The Resend credential installer QA was observed against local revision
`42cf0f40c98404d55585745b10311354661a5195`; those changes are included in pushed `main` checkpoint
`329fdc595483fa3b112b98c7788d808348638faa`, reported as matching `origin/main` at that checkpoint;
the tree was clean at push.
Builder self-validation reported `11` focused tests, Ruff check/format, `bash -n`, and ShellCheck
**Pass**. Initial independent QA found a P1 remote-shell quoting blocker and a P2 incomplete-read
rollback blocker; the repaired independent QA recheck passed `13` tests, including command
parse/probe and incomplete-read rollback, for its declared local scope. At that checkpoint, no API
key or host installation was observed; no live send or mailbox delivery was verified. This is
historical point-in-time evidence. A later operator observation reported
`email_invites_enabled=False` (timestamp not supplied), also as a point-in-time value. A later
read-only SSH recheck timed out before returning a value, so the current setting is unavailable; 25
local fake-SMTP tests and invitation-expiry checks pass, but live delivery remains unverified.

| Evidence ID | Requirement/check | Environment, UTC time, commit | Result, artifact, reviewer, limitation |
| --- | --- | --- | --- |
| `R-ASTRA-106-E1` | Independent focused implementation and MCP QA. | Native x86_64; dirty `HEAD` `db0372891ea00a0228f2c04f785a34519cb6c21b`; exact command, UTC, and artifact not supplied. | **Pass** for `37` focused tests, Ruff/security/compilation, locked stdio six-tool discovery, and invalid-CIDR behavior; reviewer `LUNA MAX QA`. |
| `R-ASTRA-106-E2` | Initial semantic documentation audit. | Environment, command, UTC, artifact, and reviewer metadata not supplied. | **Fail** for stale five-tool and SMTP-port wording. This authored-documentation repair follows; no runtime acceptance is inferred. |
| `R-ASTRA-106-E3` | Terraform/infrastructure validation. | Native x86_64; command `./infra/linode/validate.sh`; exact UTC, revision, and artifact not supplied. | **Fail** for the aggregate: Terraform stages passed, then the required dirty-tree gate exited `2`. No live apply or firewall refresh was observed. |
| `R-ASTRA-106-E4` | SOL source review after the firewall-ID repair. | Environment, command, UTC, artifact, and source-review revision not supplied. | **Pass** with no P1/P2 reported after repair and re-review; reviewer `SOL`. |
| `R-ASTRA-106-E5` | Final authored-documentation validator, tests, map coverage, self-test, and scoped diff check. | Native x86_64; dirty `HEAD` `db0372891ea00a0228f2c04f785a34519cb6c21b`; `2026-09-30T23:52:55Z`–`23:53:57Z`; commands `.dev-venv/bin/python scripts/validate_docs.py`, `.dev-venv/bin/python -m pytest -o addopts='' tests/test_docs_validation.py -ra`, `python3 scripts/check-doc-coverage.py --root . --map documentation-map.json`, `python3 scripts/check-doc-coverage-self-test.py`, and `git diff --check -- AGENTS.md README.md MVP-PLAN.md MVP-ROADMAP.md docs`. | **Pass**: validator reported `9` categories, `13` topics, and `7` governance entries; documentation tests passed `57` with one warning; coverage checked `133` files; self-test passed `26` cases; diff check exited `0`. Reviewer `LUNA MAX docs`; no deployment or delivery acceptance is inferred. |
| `R-ASTRA-106-E6` | Full local gate for the follow-on. | Native x86_64; revision `411c146`; command `TASK_ID=R-ASTRA-106 ./scripts/local-gate.sh check`; artifact `test-results/local-gates/R-ASTRA-106-20260930T235707Z/evidence.json`; exact UTC window and reviewer were not supplied. | **Pass** as reported: `741` Python checks and `27` frontend checks passed. This is local evidence only; no deployment or mail acceptance is inferred. |
| `R-ASTRA-106-E7` | Focused repaired operator-access guard. | Native x86_64; pushed reviewed `main` revision `de9f45f2d5c562c34e004c658e7cee118af6ef58`; exact command, UTC window, artifact, and reviewer were not supplied. | **Pass** as reported: `19` focused guard checks passed. This is local evidence only; no deployment or mail acceptance is inferred. |
| `R-ASTRA-106-E8` | Constrained operator firewall refresh. | Linode/Terraform MCP; pushed reviewed `main` revision `de9f45f2d5c562c34e004c658e7cee118af6ef58`; exact command, UTC window, artifact, and reviewer were not supplied. | **Pass**: `refresh_operator_access` returned firewall `177236117` with operator CIDR `50.21.67.178/32` applied to the fixed SSH rule. The Linode console login uses Google SSO; SSH material remains a separate operator-controlled boundary. |
| `R-ASTRA-106-E9` | Official-client deployment-plan attempts and fixed-helper fallback. | Native x86_64; pushed reviewed `main` revision `de9f45f2d5c562c34e004c658e7cee118af6ef58`; exact UTC window and artifact were not supplied. | **Fail** for two official-client plan attempts: both returned generic `remote_operation_failed`. The separate fixed host-helper direct plan **Passed** with plan ID `475203e37dd969d84e10e7a0839f1a28`; the failed official-client attempts remain a deployment limitation. |
| `R-ASTRA-106-E10` | Reviewed Compose installation, immutable release transport, schema-10 deployment, and HTTPS boundary. | Native x86_64/operator host and production Linode; pushed reviewed `main` revision `de9f45f2d5c562c34e004c658e7cee118af6ef58`; MCP deploy `2026-10-01T00:20:13Z`; refresh and HTTPS probe UTC/artifact/reviewer metadata were not supplied. | **Pass** for the declared scope: Compose checksum `35b4f09c0696a4873302f1127eeeb2d1468f77ce8c9c25d989e8f30af156f14b` was installed; the GitHub Release archive SHA-256 was `0e81c7c227ffe15094c5f7557b024e445e3fe61d72138bb57bacc6f6f99f47a0`; image ID was `sha256:bbb6a35143cda6d38883a8294710b2ee143f383077f4e27d6fad0c746ec5a6f1`; fixed helper plan ID was `475203e37dd969d84e10e7a0839f1a28`; deploy returned backup `pre-deploy-de9f45f2d5c562c3-497734d9.spbackup`, schema `10` ready, `loopback_only: true`, and `failed: null`; HTTPS health returned `200`, private history `401`, and responses carried `no-store`/`DYNAMIC`. No SMTP delivery, owner TOTP enrollment, authenticated workspace retrieval, physical-mobile evidence, or broader production acceptance is inferred. |
| `R-ASTRA-106-E11` | Final authored-documentation validator, tests, map coverage, self-test, and scoped diff check after this deployment reconciliation. | Native x86_64; dirty `HEAD` `de9f45f2d5c562c34e004c658e7cee118af6ef58`; `2026-10-01T00:33:23Z`–`00:33:52Z`; commands `.dev-venv/bin/python scripts/validate_docs.py`, `.dev-venv/bin/python -m pytest -o addopts='' tests/test_docs_validation.py -ra`, `python3 scripts/check-doc-coverage.py --root . --map documentation-map.json`, `python3 scripts/check-doc-coverage-self-test.py`, and `git diff --check -- AGENTS.md README.md MVP-PLAN.md MVP-ROADMAP.md docs`; no artifact. | **Pass**: validator reported `9` categories, `13` topics, and `7` governance entries; documentation tests passed `57` with one warning; coverage checked `133` files; self-test passed `26` cases; scoped diff check exited `0`. Reviewer `LUNA MAX docs`; no deployment or delivery acceptance is inferred. |
| `R-ASTRA-106-E12` | Resend account, sending-domain verification, and Cloudflare DNS preparation. | Resend/Cloudflare provider boundary; reported verification at approximately `2026-10-01T14:04Z`; Terraform commit `90ad506dc7c39e145734f295f41ac2a4358b7a14`; exact commands, apply UTC, artifacts, and reviewer were not supplied. | **Pass** for the declared DNS scope: three DNS-only records were committed/pushed; Terraform format/validate, exact three-record create apply, public DNS resolution, and post-apply no-change plan were reported passed. No API key or mail delivery is inferred. |
| `R-ASTRA-106-E13` | Operator SSH refresh and Resend SMTP endpoint transport checks. | Linode provider boundary; exact command, UTC, artifact, and reviewer were not supplied. | **Pass** for the declared transport scope: fixed typed controller applied `142.198.155.54/32`; from Linode, `smtp.resend.com:2465` passed TCP reachability and TLS 1.3 negotiation. This does not establish SMTP authentication, message acceptance, or mailbox delivery. |
| `R-ASTRA-106-E14` | Builder self-validation for the fixed Resend credential installer. | Native x86_64; installer QA revision `42cf0f40c98404d55585745b10311354661a5195`; included in pushed `main` checkpoint `329fdc595483fa3b112b98c7788d808348638faa`, reported as matching `origin/main` at that checkpoint with a clean tree at push; paths `infra/linode/install-resend-smtp-key.sh`, `infra/linode/smtp-credential-installer.py`, and `tests/test_linode_smtp_credentials.py`; exact commands, UTC, artifact, and reviewer were not supplied. | **Pass as builder self-validation** for `11` focused tests, Ruff check/format, `bash -n`, and ShellCheck. This is not independent installer or production acceptance. |
| `R-ASTRA-106-E15` | Initial independent QA of the Resend credential installer. | Exact QA task, command, UTC, environment, artifact, and reviewer were not supplied. | **Fail** for the declared installer scope: QA found a P1 remote Python shell quoting blocker and a P2 incomplete-read rollback blocker. The failure remains visible; the repaired rerun is recorded separately in E16. No host installation, live send, or mailbox result is inferred. |
| `R-ASTRA-106-E16` | Repaired independent QA of the Resend credential installer. | Native x86_64; installer QA revision `42cf0f40c98404d55585745b10311354661a5195`; included in pushed `main` checkpoint `329fdc595483fa3b112b98c7788d808348638faa`, reported as matching `origin/main` at that checkpoint with the tree clean at push; exact command, UTC window, artifact, and reviewer were not supplied. | **Pass** for the declared local installer scope: `13` tests passed, including command parse/probe and incomplete-read rollback. This does not establish API-key creation, host installation, live sending, mailbox delivery, or production acceptance. |
| `R-ASTRA-106-E17` | Final authored-documentation validator, tests, map coverage, self-test, and scoped diff check after the Resend reconciliation. | Native x86_64; dirty `HEAD` `42cf0f40c98404d55585745b10311354661a5195`; `2026-10-01T14:55:29Z`–`14:56:27Z`; commands `.dev-venv/bin/python scripts/validate_docs.py`, `.dev-venv/bin/python -m pytest -o addopts='' tests/test_docs_validation.py -ra`, `python3 scripts/check-doc-coverage.py --root . --map documentation-map.json`, `python3 scripts/check-doc-coverage-self-test.py`, and `git diff --check -- AGENTS.md README.md MVP-PLAN.md MVP-ROADMAP.md docs`; no artifact. | **Pass**: validator reported `9` categories, `13` topics, and `7` governance entries; documentation tests passed `57` with one warning; coverage checked `133` files; self-test passed `26` cases; scoped diff check exited `0`. Subsequent docs-only checkpoint `329fdc595483fa3b112b98c7788d808348638faa` was pushed; pre-push documentation coverage reported `133` mapped files/`10` changed passed, and `git ls-remote origin refs/heads/main` exactly matched; the tree was clean at push. Reviewer `LUNA MAX docs`; no installer, host, SMTP, mailbox, or production acceptance is inferred. |

## Current TOTP enrollment key-reuse repair (`R-ASTRA-107`)

**Status: In progress.** The repair reuses an unexpired pending setup only for the same session,
factor generation, and origin, preserving its expiry. Explicit `{"replace": true}` rotates the key;
a different origin cannot silently overwrite it. The UI shows expiry, disables expired QR/code use,
and offers an explicit replacement action after a cross-session conflict. The repaired image is
deployed; owner enrollment remains incomplete because no TOTP code was entered.

Production starts at `2026-10-01T15:03:02Z` and `15:04:39Z` returned `200`; finish attempts at
`15:05:51Z` and `15:06:10Z` returned `403`. A pending row from the second start remained and server
NTP was synced. This is historical bounded observation before the repaired deployment.

Independent QA repaired an initial P2 missing cross-session replacement button; final desktop and
emulated-mobile checks passed `3/3` each after the `2026-10-01T19:22Z` build. The earlier stale
staged-export browser attempt **Failed** and remains historical. The full local gate receipt
`test-results/local-gates/R-ASTRA-107-20261001T154012Z/` **Passed** on dirty `HEAD` `2e07a8e`
with `763` Python tests passed, `4` deselected, `85.47%` coverage, and reported frontend/build/typecheck/docs
checks passing with `28` frontend checks; it began before the final UI repair and is not a final
exact-tree gate. The final-tree gate and deployment records are below; physical iOS evidence remains
**Unavailable**.

Pushed revision `a2247cce6e9f55fc81f96da3698f424ae2a2dc20` published a Linux/amd64 release archive
with SHA-256 `85c53648c8c1810bfc37153c404d4064ee468c81ce78caaf0666e71bb5221106`, image ID
`sha256:b4249173085ef5b7b6c0df8741aa34d99e6b1d488ab9bfc829010398a422d2a1`, and size `103160002`
bytes; publisher re-download verification passed. Terraform MCP refresh applied `50.21.67.178/32`
to fixed firewall `177236117`. Two MCP `plan_deploy` attempts returned `remote_operation_failed`;
fixed typed host-helper plan `105579dd822e69b03360201df2276bc3` succeeded, followed by MCP deploy
with readiness schema `10`. Status reported revision `a2247cc`, `failed: null`, `loopback_only: true`,
backup `pre-deploy-a2247cce6e9f55fc-6ef1c2e6.spbackup`, and
`deployed_at=2026-10-01T19:58:26.230020Z`. Public HTTPS returned health `200`, auth status `200`,
anonymous history `401`, and overview `303` to sign-in, all with `no-store`/`DYNAMIC`. IAB sign-in as
`jtmb` reached setup; repeated default starts across reload returned the same pending key when compared
locally without exposing it, and expiry plus explicit rotation controls were visible. No TOTP code was
entered, so owner enrollment and workspace access remain **Unavailable**. If a QR or setup key appears
in a photo or screenshot, treat it as exposed: use **Start over with new key** to rotate it, replace
the old Signal Ledger entry in Apple Passwords with the new key before entering its code, and do not
use the captured QR or old key. This
deployment evidence does not claim complete auth acceptance.

| Evidence ID | Requirement/check | Environment, UTC time, commit | Result, artifact, reviewer, limitation |
| --- | --- | --- | --- |
| `R-ASTRA-107-E1` | Source repair for pending-key reuse, explicit rotation, same-origin binding, expiry handling, and UI conflict recovery. | Dirty `HEAD` `2e07a8e`; exact command, UTC, artifact, and reviewer were not supplied. | **Pass as supplied repair evidence**; independent QA and local-gate limitations remain below. |
| `R-ASTRA-107-E2` | Production enrollment start/finish observation and server clock state before repaired deployment. | Production HTTPS; start times `15:03:02Z` and `15:04:39Z`; finish times `15:05:51Z` and `15:06:10Z`; exact command, revision, artifact, and reviewer were not supplied. | **Pass** for the historical bounded observation: starts `200`, finishes `403`, pending row from the second start remained, and NTP was synced. It predates the repaired deployment recorded in E10-E11. |
| `R-ASTRA-107-E3` | Initial independent browser QA. | Exact task, command, environment, UTC, revision, artifact, and reviewer were not supplied. | **Fail** for the initial scope because the cross-session replacement button was missing (P2); the repair and final rerun remain separate. |
| `R-ASTRA-107-E4` | Repaired independent desktop and emulated-mobile browser QA. | Frontend build at `2026-10-01T19:22Z`; exact command, environment, revision, artifact, and reviewer were not supplied. | **Pass**: desktop `3/3` and emulated mobile `3/3`; physical iOS remains **Unavailable**. |
| `R-ASTRA-107-E5` | Earlier staged-export browser attempt. | Exact command, environment, UTC, revision, artifact, and reviewer were not supplied. | **Fail** for that stale staged-export attempt; it remains historical and is not relabelled as final QA. |
| `R-ASTRA-107-E6` | Full local gate before the final UI repair. | Native x86_64; dirty `HEAD` `2e07a8e`; artifact `test-results/local-gates/R-ASTRA-107-20261001T154012Z/`; exact command, UTC, and reviewer were not supplied. | **Pass** as reported for its declared pre-repair scope: `763` Python tests passed, `4` deselected, `85.47%` coverage, and reported frontend/build/typecheck/docs checks passed with `28` frontend checks. It is not final exact-tree acceptance. |
| `R-ASTRA-107-E7` | Production deployment preflight and operator-access follow-up, before the successful refresh and deployment. | Production HTTPS/MCP/SSH boundary; approximately `2026-10-01T19:24Z`; exact command, revision, artifact, and reviewer were not supplied. | **Unavailable** at that time: HTTPS remained reachable, MCP `inspect`/`status` returned `remote_rejected`, SSH timed out, and the observed operator address did not match the firewall CIDR. This is historical pre-deployment evidence, superseded for current deployment status by E10-E11. |
| `R-ASTRA-107-E8` | Final authored-documentation validator, docs tests, change-aware coverage, coverage self-test, and scoped diff check after the repair documentation. | Native x86_64; dirty `HEAD` `2e07a8e`; UTC was not captured by the command tool; commands `.dev-venv/bin/python scripts/validate_docs.py`, `.dev-venv/bin/python -m pytest -o addopts='' tests/test_docs_validation.py -ra`, `python3 scripts/check-doc-coverage.py --root . --map documentation-map.json`, `python3 scripts/check-doc-coverage-self-test.py`, and `git diff --check -- AGENTS.md README.md MVP-ROADMAP.md MVP-PLAN.md docs`; artifact none. | **Pass**: validator reported `9` categories, `13` topics, and `7` governance entries; docs tests passed `57` with one warning; coverage checked `133` mapped files; self-test passed `26` cases; and scoped diff check exited `0`. Reviewer `LUNA MAX docs`; no commit, push, deployment, or device result is inferred. |
| `R-ASTRA-107-E9` | Final-tree local gate after the UI repair. | Native x86_64; dirty worktree at `HEAD` `2e07a8e9e2b15d80bc154182d0392977c60db53a`; `2026-10-01T19:37:24Z`–`19:47:25Z`; receipt `test-results/local-gates/R-ASTRA-107-20261001T193724Z/evidence.json`. | **Pass**, exit `0`: `763` Python tests passed, `4` were deselected, coverage was `85.45%`, and frontend `28`, build, typecheck, and documentation checks passed. This is dirty-worktree local evidence, not a pushed revision; the later push and deployment are separately recorded in E10. |
| `R-ASTRA-107-E10` | Release publication, operator-access refresh, and production deployment. | Pushed `main` revision `a2247cce6e9f55fc81f96da3698f424ae2a2dc20`; Linux/amd64; archive SHA-256 `85c53648c8c1810bfc37153c404d4064ee468c81ce78caaf0666e71bb5221106`; image `sha256:b4249173085ef5b7b6c0df8741aa34d99e6b1d488ab9bfc829010398a422d2a1`; size `103160002` bytes; exact command/UTC/reviewer not supplied. | **Pass** for the declared deployment scope: publisher re-download passed; Terraform MCP applied `50.21.67.178/32` to firewall `177236117`; two MCP plans returned `remote_operation_failed`; fixed host-helper plan `105579dd822e69b03360201df2276bc3` succeeded; MCP deploy reached readiness schema `10`; status reported revision `a2247cc`, `failed: null`, `loopback_only: true`, backup `pre-deploy-a2247cce6e9f55fc-6ef1c2e6.spbackup`, and `deployed_at=2026-10-01T19:58:26.230020Z`. The transient plan failures remain visible. |
| `R-ASTRA-107-E11` | Public boundary and live setup/reuse check. | Production HTTPS and IAB; exact probe/browser UTC, command, artifact, and reviewer were not supplied; no QR or secret was recorded. | **Pass** for the bounded boundary/UI scope: health `200`, auth status `200`, anonymous history `401`, overview `303` to sign-in, all `no-store`/`DYNAMIC`; GitHub sign-in as `jtmb` reached setup; repeated default starts across reload returned the same pending key when compared locally without exposing it, with expiry and explicit rotation controls visible. No TOTP code was entered; owner enrollment, workspace access, and physical iPhone code validation remain **Unavailable**. |

## Microsoft Authenticator iOS setup-routing follow-on (`R-ASTRA-110`)

**Status: In progress** for complete owner authentication; **Completed** for the declared UI repair,
local QA, deployment, and live-guidance scope. The dirty working-tree source at
`416b29b23f3e70af1635806a77164392de76d64b` makes Microsoft Authenticator default to same-phone
manual key entry, keeps its QR hidden until the user selects **Another screen: scan from inside
Microsoft Authenticator**, warns against iPhone Camera or Photos, and resets the setup method to
manual when the authenticator selection changes. No documented way to force those iOS tools to open
Microsoft Authenticator is claimed.

GPT-6.1 Sol's independent read-only review reported no findings. The focused Python command
`.dev-venv/bin/python -m pytest tests/test_auth.py -q -k 'totp_enrollment or authenticator_api_enrollment or totp_replay or totp_failed_attempts'`
passed `8` tests, and `node --test tests/auth-contract.test.mjs` from the `frontend` directory
passed `9` tests at `2026-10-02T18:57:02Z`; no artifact was saved. A separate native-x86_64
disposable FastAPI `TestClient` protocol passed from
`2026-10-02T18:58:27.159923Z` to `18:58:31.766543Z`, covering matching parsed `otpauth` and manual
keys, independent standard-library SHA-1/6-digit/30-second TOTP generation, enrollment HTTP `200`,
ten recovery codes, enrolled status, and history HTTP `200`. No secret, code, or recovery value was
printed and temporary data was deleted; the protocol used `.dev-venv/bin/python - <<'PY'` and saved no
artifact.

The prior local-gate attempt at `test-results/local-gates/R-ASTRA-110-20261002T182918Z/` was
interrupted with no final `evidence.json` or process, so that aggregate is **Unavailable**. Luna focused
browser QA passed `22/22` on desktop and emulated Pixel 7, with no overflow at mobile `360px`; the
default Microsoft QR was absent until the scanner method was selected, and the scanner QR then
appeared. Native iOS and Microsoft Authenticator interaction remain **Unavailable**. Full-gate session
`81547` ended with exit `143`; its receipt
`test-results/local-gates/R-ASTRA-110-20261002T185559Z/evidence.json` embeds Pass/0 fields but lists
only documentation and frontend checks, with Python completion missing, so that aggregate remains
**Unavailable** as historical evidence. The final gate
`TASK_ID=R-ASTRA-110 ./scripts/local-gate.sh check` passed with exit `0` on native x86_64 dirty
`HEAD` `416b29b23f3e70af1635806a77164392de76d64b` from `2026-10-02T19:44:59Z` to `19:56:44Z`; receipt
`test-results/local-gates/R-ASTRA-110-20261002T194459Z/evidence.json` records documentation, frontend,
and Python checks, `763` tests with zero errors/failures/skips, `4` deselected, `85.47%` coverage,
frontend `28`, and final backup `61` passed.

The declared release and deployment scope then completed. Pushed clean `main` revision
`566baab14c298fb52b5edb3138d64cd3e9123311` was published by
`./scripts/publish-production-image.sh` with exit `0`; GitHub Release
`signal-ledger-566baab14c298fb52b5edb3138d64cd3e9123311` has archive SHA-256
`6867ddc1a78a432d5e9c0a990089f746ad3257e9f26bdf38539054160e4cad73`, Linux/amd64 image
`sha256:151c527557161917f7184f56563f29d29fadf7d1efac7d1a2051004d1e986252`, size `103163291`, and
verified re-download. The fixed operator firewall refresh succeeded; the first MCP plan returned
`remote_operation_failed`, fixed restricted helper plan `22b896023069ce3c5ac09efc5a2bd19a` succeeded,
and native MCP deploy reached schema `10` ready. Status reported exact revision, `failed: null`,
`loopback_only: true`, backup `pre-deploy-566baab14c298fb5-93cbdab4.spbackup`, and
`deployed_at=2026-10-02T20:07:20.087209Z`. Public probes at `2026-10-02T20:07:33.739529Z` returned
health `200`, auth status `200`, anonymous history `401`, and overview `303`, all `no-store`/`DYNAMIC`.
The signed-in IAB showed the new Microsoft intro, manual-key and in-app-scanner guidance, and the
explicit Camera/Photos Apple Passwords warning; temporary screenshot artifact
`/tmp/signal-ledger-r110-release/production-microsoft-guidance.png`. During the recorded agent-run
live check, no owner key was generated or code entered. Native iPhone/Microsoft Authenticator
interaction, owner enrollment, authenticated workspace retrieval, and broader authentication
acceptance remain **Unavailable** in agent-observed evidence.
See the [MVP plan](MVP-PLAN.md#microsoft-authenticator-ios-setup-routing-follow-on-r-astra-110)
for the evidence ledger.

## Historical Microsoft Authenticator dropdown follow-on (`R-ASTRA-109`)

**Status: In progress** for complete owner authentication. The deployed chooser includes Microsoft
Authenticator and shows app-specific setup guidance after selection. The implementation and
getting-started update are at pushed `main` revision
`3ec26d2826bf4acfbe0b8af8eaf2bb7b8ad54d5d`, which matched `origin/main` with a clean tree at the
checkpoint. Focused authenticator browser QA passed `14/14` on desktop Chromium and emulated Pixel
7. Microsoft Support documents **+** > **Other account** for non-Microsoft QR enrollment and
manual entry when the option is available.

The final local gate `TASK_ID=R-ASTRA-109 ./scripts/local-gate.sh check` **Passed** with exit `0` on
native x86_64 from `2026-10-02T00:30:17Z` to `00:37:23Z`; receipt
`test-results/local-gates/R-ASTRA-109-20261002T003017Z/evidence.json` records dirty base
`9f983a08bf5aeef5f1ace1bd61afee20228499d7`, `763` Python tests passed, `4` deselected, `85.47%`
coverage, and frontend `28`, build, typecheck, and documentation checks passed.

Release `signal-ledger-3ec26d2826bf4acfbe0b8af8eaf2bb7b8ad54d5d` has archive SHA-256
`82acc1fcb52da66ee0ced78e8549780cd81ba31f73a657f761cdeb41284a0068`, Linux/amd64 image ID
`sha256:91253b9384318853c36b9949f091bab747b8d9dac930e002f0dc116aef05c8e8`, and size `103157486`
bytes. The first MCP plan returned `remote_operation_failed`; fixed restricted helper plan
`5dc7eb3db7946693b2043895e8f50c4d` passed, then MCP deploy succeeded. Status reported schema `10`
ready, backup `pre-deploy-3ec26d2826bf4acf-0f9c4edb.spbackup`, `failed: null`, `loopback_only: true`,
and `deployed_at=2026-10-02T00:42:50.439878Z`.

Live HTTPS returned health/auth status `200`, anonymous history `401`, and `/overview` `303` to
sign-in, all with `no-store`/`DYNAMIC`. In the production IAB after GitHub sign-in as `jtmb`, the
Microsoft option and its guidance appeared and selecting it enabled setup-key generation. No key
was generated or code entered; the read-only database query at that checkpoint found zero owner
factors and zero active pending enrollments. Owner TOTP acceptance and authenticated workspace retrieval remain
**Unavailable**, as do actual Microsoft Authenticator interaction and physical iPhone code
acceptance. See the [MVP plan](MVP-PLAN.md#historical-microsoft-authenticator-dropdown-follow-on-r-astra-109)
for the evidence ledger.

At the time of this R-ASTRA-109 draft, a working-tree source follow-on addressed the iOS routing
report. Microsoft Authenticator defaults to same-phone manual key entry; the QR remains hidden until the user selects **Another
screen: scan from inside Microsoft Authenticator**. The page warns against iPhone Camera or Photos,
which may route the QR to Apple Passwords, and documents no way to force those iOS tools to open
Microsoft Authenticator. This draft was superseded by the deployed and independently checked
[R-ASTRA-110 follow-on](MVP-PLAN.md#microsoft-authenticator-ios-setup-routing-follow-on-r-astra-110).

## Preceding authenticator-app chooser refinement (`R-ASTRA-108`)

**Status: In progress** for complete owner authentication. The chooser refinement is deployed at
pushed `main` revision `d5d2cbf0314091977358c3d3a90bfab096286bd4`, which includes the getting-started
guide and matched `origin/main` with a clean tree at the checkpoint. The page requires app selection
before setup-key generation, retains the choice through setup and rotation, removes the generic
`otpauth://` handler link, and explains manual-key entry and use of the selected app's in-app QR
scanner. `R-ASTRA-107` remains the preceding deployed key-reuse repair and remains incomplete for
owner TOTP acceptance.

Independent Luna xhigh QA found two small issues and recorded their repairs; final source review
reported no code blocker, auth-contract checks passed `9/9`, and typecheck/docs validator/diff checks
passed. The focused `8/8` browser run predates the final copy change. After the final frontend build,
the final exact-tree desktop/emulated Pixel 7 browser run passed `14/14`. The earlier concurrent
browser attempt used a stale export and **Failed**. The initial full gate was interrupted after the
last copy change and exited `1`; it is retained as a failed invocation, not acceptance evidence.

The final command `TASK_ID=R-ASTRA-108 ./scripts/local-gate.sh check` **Passed** with exit `0` on
native x86_64 from `2026-10-01T20:52:50Z` to `21:00:17Z`; receipt
`test-results/local-gates/R-ASTRA-108-20261001T205250Z/evidence.json` records dirty base
`da2ab8e22a1efe0bc57c903cd17a4bd9c3da4013`, `763` Python tests passed, `4` deselected, `85.47%`
coverage, and frontend `28`, build, typecheck, and documentation checks passed.

GitHub Release `signal-ledger-d5d2cbf0314091977358c3d3a90bfab096286bd4` has archive SHA-256
`4c57f78084e4c27dc5a666c2fc8f080b5ef9b02c83b7a0ea33ae4ac7761c8129`, Linux/amd64 image ID
`sha256:151ba3169c65cd6cb410cb19b6102e67a61289fd58fb74384c9bc953150e1e85`, and size `103157662`
bytes. The first MCP plan returned `remote_operation_failed`; fixed restricted helper plan
`93852f0183b35d024f6bbe27b3388784` passed, then MCP deploy succeeded. Status reported schema `10`
ready, exact revision, backup `pre-deploy-d5d2cbf031409197-d1b7d25e.spbackup`, `failed: null`,
`loopback_only: true`, and `deployed_at=2026-10-01T21:06:23.524988Z`.

Public HTTPS returned health/auth status `200`, anonymous history `401`, and `/overview` `303` to
sign-in with `no-store`/`DYNAMIC` responses. In the production IAB after GitHub sign-in as `jtmb`,
key generation was disabled before a choice, selecting Google Authenticator displayed its guidance
and enabled generation, and resetting the choice disabled it again. No key was generated or code
entered. The operator's read-only database query found zero owner factors and zero active pending
enrollments. Owner code acceptance, authenticated workspace retrieval, physical iPhone, and
VoiceOver evidence remain **Unavailable**. See the [MVP plan](MVP-PLAN.md#current-authenticator-app-chooser-refinement-r-astra-108)
for the evidence ledger.

## Historical authentication and production deployment follow-on (`R-ASTRA-101`)

`R-ASTRA-101` is the next dependency-ordered item after the Signal Ledger UI follow-ons. It adds
the invite-only multi-user boundary before public exposure: GitHub authorization-code OAuth with
state and PKCE, stable numeric GitHub identity, required user-verifying passkeys, opaque hashed
sessions, exact origin/Host handling, CSRF protection, revocation, and session-derived ownership
for history, saved results, exports, outcomes, reconstructions, holdings, and watchlists. Admin
backup and restore promotion requires a fresh passkey check and verified recovery state.

The deployment is a single FastAPI app with SQLite on one persistent Linode volume. Terraform
defines the same Ubuntu 24.04 `g6-nanode-1` (1 GB/25 GB) host in `us-east`, imports firewall
`177236117`, permits only operator SSH from the configured `/32`, enables VM Backups and disk
encryption, and prevents destruction. Its fixed clean reviewed-main source gate runs during both
plan and apply. Docker binds the app only to loopback, and a host-managed Cloudflare Tunnel
starts closed with a terminal `404`; the exact `ledger.jtmb.cc` owner canary and cache bypass were
the preceding private step. E58 records the later `public_invited` boundary. The local stdio deployment MCP exposes only `inspect`, `plan_deploy`, `deploy`,
`status`, and `rollback`. The default image transport is a locally built Linux amd64 GitHub
Release archive derived from the reviewed revision; GHCR is an explicit compatibility mode. The
VM does not build source.

- **Status:** **In progress**; implementation, private infrastructure apply, the auth-UI repair,
  remote image deployment, the declared recovery rehearsal, and the restricted owner-only canary
  are recorded. E63 records the then-current schema-8 deployment at that historical checkpoint: main revision
  `27e0d2f5916d4297e10d259aa4776055a78faeaa`, verified Linux/amd64 image, schema `8`, `failed: null`,
  and loopback-only with a pre-deploy backup. Public health/auth/sign-in probes passed with
  `no-store`/`DYNAMIC`. The IAB passkey remained unavailable and corrected sign-out returned to
  sign-in twice; no independently completed browser passkey was observed.
  Operator read-only evidence confirms one nonrevoked passkey, one current passkey-verified session,
  and persisted owner mappings. Later server-observed access logs confirm authenticated owner API
  retrieval and saved-forecast access; browser-rendered content remains **Unavailable**. E56 passes
  the four two-client isolation scenarios locally, and E57's full local gate rerun passes after its
  initial comment-audit failure; remote two-user behavior and browser UI remain **Unavailable**.
  E58 records the provider-refreshed `public_invited` Terraform apply and live unauthenticated
  sign-in boundary. E59 records the legacy-host retirement pass. Functional owner/invited-user
  browser acceptance remains pending; E60 records the historical current-machine browser passkey
  failure and sign-out limitation, E61 records the locally accepted repair, E62 records the passing
  full local gate, E63 records the then-current schema-8 image publication/deployment, and E64 records Astra's
  no-P1/P2 live read-only review. Browser-rendered owner content, live second-user onboarding, and
  hardware passkey evidence remain **Unavailable**.
- **Owner/phase:** implementation/security repair, `ASTRA` medium review, independent
  `LUNA MAX QA` browser/deployment checks, and `LUNA MAX docs` reconciliation.
- **Dependencies:** `R-ASTRA-100` is complete for its declared UI scope; source schema was 8 at this
  historical checkpoint; the local app remained untouched and E59 confirmed the old VM was retired.
- **Pending external steps:** browser-rendered owner UI verification, remote two-user/browser
  verification, and functional owner/invited-user acceptance. E59 retires
  legacy Linode `97934478`; the public-invited infrastructure boundary is applied in E58, but no
  owner UI session was observed. E60 records the current-machine passkey browser limitation. E63
  records the then-current schema-8 image and public probes; E64 records Astra's no-P1/P2 live read-only
  review. The four local isolation scenarios pass in E56. The three provider access items were created privately;
  Terraform applied replacement Linode `106817202` and the imported firewall; the reviewed image
  was deployed privately with the app loopback-only; the VM Backup recovery rehearsal passed for
  its declared scope; and the restricted Cloudflare canary is active. It served the new passkey
  text and unauthenticated Cloudflare traffic returned `302`, but the browser requested a nearby
  phone/Bluetooth credential and no completed credential was observed in that earlier browser
  check. The source-reviewed
  session-recovery fix at `a1d868287a729c75d9b8628f612a856db132374a` passed local build/typecheck,
  `28` frontend tests, and browser `4/4`. E63 published and deployed the then-current schema-8 image. Earlier
  Luna evidence records Cloudflare token verification HTTP `401` and documentation-coverage **Fail**.
  E58's boundary probes returned the expected sign-in/auth responses with `no-store`/`DYNAMIC`,
  and direct port `8000` remained unreachable. E59's post-delete probes returned health/auth `200`,
  history `401`, and overview `303` to sign-in. E63's IAB passkey remained unavailable, but corrected
  sign-out returned to sign-in twice. E64 found no P1/P2 for its live read-only scope; independently
  completed passkey, rendered owner workspace, live second-user onboarding, Terraform/image/IPv6/old-VM
  rechecks remain **Unavailable**. No full production acceptance checkpoint is claimed.

| Evidence ID | Requirement/check | Environment, UTC time, commit | Result, artifact, reviewer, limitation |
| --- | --- | --- | --- |
| `R-ASTRA-101-E1` | Initial Astra medium source security review. | Native x86_64; dirty revision `893a146dcb0cf3ba03b435307dec1fb138941cd0`; exact command and UTC were not supplied. | **Fail** initially: Host authority/path poisoning and a Starlette range denial-of-service advisory were P1 launch blockers. Reviewer `ASTRA` medium; findings remain visible until the recheck. |
| `R-ASTRA-101-E2` | Recheck after Host-scope and dependency repairs. | Native x86_64; dirty revision `893a146dcb0cf3ba03b435307dec1fb138941cd0`; exact command and UTC were not supplied. | **Pass** as supplied Astra recheck: no remaining source blocker reported. This is not public-hosting acceptance. |
| `R-ASTRA-101-E3` | Fresh Python and deployment-MCP lock audits. | Native x86_64; current dirty worktree; exact commands and UTC were not supplied. | **Pass**: both recorded `pip-audit` runs reported zero advisories. |
| `R-ASTRA-101-E4` | Focused API/auth and helper/MCP regressions. | Native x86_64; current dirty worktree; exact commands and UTC were not supplied. | **Pass** as scoped evidence: API/auth `151` passed and helper/MCP `31` passed. The completed `R-ASTRA-101` local-gate rerun is recorded in E12; no remote image or public result is inferred. |
| `R-ASTRA-101-E5` | Frontend/auth test surface. | Native x86_64; current dirty worktree; exact command and UTC were not supplied. | **Pass**: frontend tests reported `27` passed. |
| `R-ASTRA-101-E6` | Isolated production-shaped browser auth and boundary checks. | Official Playwright; `127.0.0.1:8766`; Light/Dark at `1280x720` and `390x844`; exact UTC and revision were not supplied. | **Pass** for the scoped checks: protected routes redirected `303`, private history returned `401`, spoofed Host/Origin returned `400`/`403`, 104 requests remained loopback-only, no horizontal overflow was found, and focus/44px checks passed. CUA, full axe, physical mobile, screen reader, and true zoom remain **Unavailable**; reviewer `LUNA MAX QA`. |
| `R-ASTRA-101-E7` | Schema-6 online snapshot, signed backup, migration, and owner-claim rehearsal. | Native x86_64; current live schema-6 app; exact UTC and revision were not supplied. | **Pass** as local isolated evidence: verified backup and mode-`0600` online snapshot share SHA-256 `2533d3bf96db79610b4616531e047df434ed54b1b2e1243c8a65b4e8401adcfd`; integrity check was `ok`; counts were 13 events, 13 runs, 20 results, 6 holdings, and 3 watchlist items. Schema 6→8 migration verified pre/post backups, and simulated owner claim to GitHub ID `86915618` preserved the records. Re-take at cutover if data changes. |
| `R-ASTRA-101-E8` | Disposable production-shaped image readiness. | Native x86_64; local candidate image; exact image identity and UTC were not supplied. | **Pass**: schema `8` readiness, authentication status `200`, and private history `401` without a session. No GitHub Release, GHCR, or remote result is inferred. |
| `R-ASTRA-101-E9` | Broad `R-ASTRA-100` gate carried into this follow-on. | Native x86_64; exact aggregate command and UTC were not supplied. | **Unavailable** as one historical green aggregate: `603` passed, `5` failed, `4` deselected; four stale schema expectations and one timing race were targeted by a `33`-pass repair run. The current `R-ASTRA-101` local-gate rerun is recorded separately in E12; the earlier failed identities remain visible. |
| `R-ASTRA-101-E10` | Provider token/UI creation, Terraform apply for the replacement Linode and imported firewall, remote image pull/deploy, GitHub OAuth credentials, Tunnel canary, VM Backup rehearsal, and legacy Linode `97934478` retirement. | External provider consoles; no completion timestamp or remote revision supplied. | **Pending**; the local-to-GitHub image transport is recorded in E21, and this row blocks public exposure and a production release claim. |
| `R-ASTRA-101-E11` | Authored docs validation, coverage, self-test, and diff checks. | Native x86_64; current dirty worktree; exact UTC and revision were not supplied. | **Pass**: with `TMPDIR=/home/james/.cache/stock-probs-gate-tmp`, the documentation coverage self-test exited 0 with 26 cases and `tests/test_docs_validation.py -q` exited 0 with 57/57 tests (collect-only confirmed 57); docs validation reported 9 categories and 13 topics; coverage checked 133 mapped files; and scoped `git diff --check` passed. Earlier quota-limited attempts remain historical: the self-test exited 1 during fixture creation and pytest exited 1 after 40 passed tests and 13 setup errors, both with errno 122. Reviewer `LUNA MAX docs`. |
| `R-ASTRA-101-E12` | Full local security/deployment gate for the current authentication and private deployment follow-on. | Native x86_64; `2026-09-27T10:59:03Z`–`2026-09-27T11:11:45Z`; dirty `HEAD` `893a146dcb0cf3ba03b435307dec1fb138941cd0`; command `TMPDIR=/home/james/.cache/stock-probs-gate-tmp TASK_ID=R-ASTRA-101 ./scripts/local-gate.sh check`. | **Pass**, exit 0; artifact `test-results/local-gates/R-ASTRA-101-20260927T105903Z/evidence.json`. Python: 612 passed, 4 live deselected, 85.36% coverage. Frontend typecheck/build/test: 27 tests passed. Documentation coverage checked 133 files; comment audit covered 229 files. Completed checks were documentation-completeness, frontend-npm-ci-typecheck-build-test-stage, and python-checks. Reviewer was not supplied. This is local dirty-worktree evidence; it does not claim GHCR publication, an image deployed on the remote VM, a Linode deployment, public exposure, or a release checkpoint. |
| `R-ASTRA-101-E13` | Independent infrastructure design review of the Linode and Cloudflare Terraform boundaries. | Supplied independent infra QA; exact task ID, command, UTC, artifact, reviewer, and provider apply result were not supplied. | **Pass as supplied for the declared review scope**: the Linode shape remains `g6-nanode-1` (1 GB/25 GB), Ubuntu 24.04 in `us-east`, with imported firewall `177236117`, default-deny ingress, operator SSH `/32`, no app port, prevent-destroy controls, and clean reviewed-main gates for plan and apply. Cloudflare starts closed with terminal `404`, supports the exact `ledger.jtmb.cc` owner canary, and bypasses shared/browser caching for that host. This does not prove provider token/UI creation, an actual Terraform apply, a release publication, a tunnel canary, VM Backup recovery, or public exposure. |
| `R-ASTRA-101-E14` | External execution for the bootstrap, configure, seed, publish, deploy, and retirement operations. | External host/provider scope; exact task ID, command, UTC, artifact, reviewer, and remote receipts were not supplied. | **Pending**: the local ops-QA portion is superseded by E16, but provider token/UI creation, Terraform apply, remote image pull/deploy, OAuth credentials, Cloudflare canary, VM Backup recovery rehearsal, and retirement of legacy Linode `97934478` remain pending. The local-to-GitHub transport is recorded in E21. |
| `R-ASTRA-101-E15` | Astra source review after the deployment-hardening and image-boundary repairs. | Supplied Astra source review; exact task ID, command, UTC, artifact, and source revision were not supplied. | **Pass as supplied for that boundary**: no remaining source launch blocker was reported after the lock, upload, staged-database, source-gate, cache-ordering, recursive database/backup/sidecar exclusion, and per-layer publisher-path fixes; the recheck reported no P1/P2 finding for that scope. A later privacy-refactor review found a separate P2 and is recorded in E39/E42. This does not establish remote deployment or public-hosting acceptance; reviewer `ASTRA`. |
| `R-ASTRA-101-E16` | Independent Luna operations QA for bootstrap, configuration, seed, publish, deploy, and retirement helpers. | Native x86_64 local fixtures; exact task ID, command, UTC, artifact, and revision were not supplied. | **Pass as supplied for the local scope**: 17 focused tests passed, along with Bash syntax, Ruff, ShellCheck, and diff checks; fixtures covered full `deploy.lock` contention, failed verify/retry, no-clobber, and strict SSH. A real host was unavailable, so remote execution, provider actions, and production acceptance remain pending; reviewer `LUNA MAX QA`. |
| `R-ASTRA-101-E17` | Latest full local security/deployment gate after the operations and harness repairs. | Native x86_64; dirty `HEAD` `585a5c2e28aef66d3100df91063dc9ee64b81cac`; `2026-09-27T14:14:22Z`–`14:30:02Z`; command `TMPDIR=/home/james/.cache/stock-probs-gate-tmp OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 TASK_ID=R-ASTRA-101 ./scripts/local-gate.sh check`. | **Pass**, exit `0`; artifact `test-results/local-gates/R-ASTRA-101-20260927T141422Z/evidence.json`. Coordinator command stdout reported Python: `644` passed, `4` live deselected, `85.36%` coverage, and frontend: `27` passed. Completed checks: documentation-completeness, frontend-npm-ci-typecheck-build-test-stage, and python-checks. The retained receipt does not independently reconstruct the stdout-only coverage or frontend counts. This remains local dirty-tree evidence and does not claim remote success, image publication, Terraform apply, public exposure, or release; reviewer was not supplied. |
| `R-ASTRA-101-E18` | Earlier full-gate startup-timeout failure and test-only harness repair. | Native x86_64; earlier `2026-09-27T13:39` run; exact command, revision, artifact, and reviewer were not supplied. | **Fail** for the earlier aggregate: five fixed 10-second child-startup waits under 4 GB full swap reached `185` tests and exited `2`; a separate parent rerun saw one equivalent timeout. The test-only harness repair added bounded 30-second waits and cleanup. This failure remains historical and is superseded for the local gate by E17; source was unchanged. |
| `R-ASTRA-101-E19` | Independent Luna retest of the repaired operations-test harness and backup-file path. | Native x86_64 local fixtures; exact task ID, command, UTC, artifact, and revision were not supplied. | **Pass as supplied**: six targeted checks were run twice plus the full backup-file check, totaling `24` passes, with source unchanged. This does not provide real-host or remote deployment evidence; reviewer `LUNA MAX QA`. |
| `R-ASTRA-101-E20` | Initial local production-image publish attempt and expanded Docker-context/secret-boundary QA. | Native x86_64; initial attempt approximately `2026-09-27T14:34`–`14:36Z`; expanded Luna QA `2026-09-27T14:48:23Z`–`14:54:05Z`; exact commands, revision, and artifacts were not supplied. | **Pass for the final scoped QA**: Luna's real synthetic Docker QA passed `59` sentinels, including nested `src`/`frontend` database, WAL, SHM, and backup files, with expected inputs present. Publisher-guard QA then passed `38` scoped tests at `14:53:34`–`14:53:42Z`, a regex matrix with `15` nested database/backup/sidecar positive matches and `10` legitimate nonmatches at `14:53:58Z`, and `bash -n`/ShellCheck at `14:54:04`–`14:54:05Z`. No actual state, secrets, or database contents were accessed. Astra's P1 review found nested `.sqlite3`/`.spbackup` files could enter COPY/package and the release scanner lacked a database guard; recursive database/backup/sidecar exclusions and per-layer publisher-path rejection were added, and Astra's final recheck reported no P1/P2 finding. The initial attempt remains a **Fail** record: Docker sent a `353.4 MB` context including a `335 MB` `infra/.terraform` provider cache and stopped before creating a GitHub Release; root `id_rsa`, nested `id_rsa`, and nested environment/key fixture failures remain visible in the repair progression. Remote image pull/deploy remains pending; reviewer `LUNA MAX QA`. |
| `R-ASTRA-101-E21` | Local-to-GitHub image transport from the exact pushed `main` revision. | Native x86_64/local Docker and GitHub Release; pushed revision `3bc85ed6c6b8b56386da32e532e4a79c5f74b6dd`; exact publication UTC was not supplied. | **Pass**: Luna re-downloaded the `103,116,996`-byte asset with SHA-256 `586ef74929dd3542930f37f46f9081f56a2c3bdf7a43b5aec32450be69d9ecce`, verified Linux/amd64 and the exact revision label, confirmed every inner Docker archive member matched local `docker save`, and found no database, backup, or sidecar paths. Release URL: `https://github.com/eddiesoz/stock_probs/releases/tag/signal-ledger-3bc85ed6c6b8b56386da32e532e4a79c5f74b6dd`. This is local-to-GitHub transport evidence only; it does not claim remote VM deployment, public exposure, or a production release; reviewer `LUNA MAX QA`. |
| `R-ASTRA-101-E22` | Creation of the three external access items and Terraform-managed replacement infrastructure. | Provider API/browser execution; exact task ID, command, UTC, and artifact were not supplied. Linode instance `106817202`, `g6-nanode-1`, Ubuntu 24.04, `us-east`; imported firewall `177236117`; Cloudflare closed configuration; GitHub OAuth application. Credential values remain in private operator storage and are not recorded here. | **Pass** for the declared creation/apply scope: the replacement instance has 1 GB/25 GB, VM Backups, and disk encryption; only the replacement is attached to the imported firewall; the legacy instance remains untouched; Cloudflare has no public DNS route in closed mode. This does not pass the canary, recovery, or retirement gates. |
| `R-ASTRA-101-E23` | Private host bootstrap, data seed, and reviewed image deployment. | Native x86_64 coordinator plus remote Linode `106817202`; exact UTC and task ID were not supplied. Reviewed revision `f329a4c99bf75d9ff2d365473051580f8eda7f58`; archive SHA-256 `79f4ac15491ccb7d70ab28b0ed44f441f18f0212c54c3a1487dde6a3a267f9a1`; image ID `sha256:b324a8f288307ff864b26d4792c54271cfee963cf077d31b16c1fac951f87eca`; deployment plan `65d8355aef719983cb989a2dd8056522`. | **Pass** for private deployment: remote readiness reported schema `8`; `/api/v1/health` and authentication status returned `200`, unauthenticated history returned `401`, spoofed Host/Origin returned `400`/`403`, and the app port remained loopback-only. Verified migrated data preserved 13 events, 13 runs, 20 results, 6 holdings, and 3 watchlist items. No public exposure is inferred. |
| `R-ASTRA-101-E24` | Cloudflare closed-mode application and owner-canary preparation. | Cloudflare Terraform state and saved canary plan; exact UTC and task ID were not supplied. Tunnel `ad7dfd41-9b9a-4b5c-92c0-6c72ca2d1c2f`; canary hostname `ledger.jtmb.cc`. | **Pass** for closed-mode preparation: terminal `404`, no DNS record, owner-only Access policy, and exact-host shared/browser cache bypass were present before the canary. The later live canary is recorded in E36. |
| `R-ASTRA-101-E25` | Application and Linode VM backup evidence before exposure. | Native x86_64 coordinator and Linode API; exact task ID, command, and UTC were not supplied. VM snapshot `385239936` for the replacement instance. | **Pass** for the recorded backup scope: the application backup was verified, the snapshot is successful and available, VM Backups are enabled, and the snapshot was taken before canary exposure. This release has no independent encrypted off-server backup; the VM Backup retention boundary remains a limitation. |
| `R-ASTRA-101-E26` | First disposable VM Backup recovery rehearsal from snapshot `385239936`. | External Linode restore operation; temporary instance `106821372`; exact task ID, command, and UTC were not supplied. | **Fail**: the clone restored to offline boot, but a concurrent in-place Bash edit corrupted the running process; it exited `127` before application, database, firewall, loopback, or tunnel verification. Only the guarded disposable clone was deleted afterward, and its API lookup returned `404`; the source and legacy instances were not deletion targets. Astra's two P2 rehearsal-script findings remain visible as historical evidence. No recovery pass is inferred from this row. |
| `R-ASTRA-101-E32` | Repair boundary after the failed live recovery rehearsal. | Native x86_64 source repair plus external Linode rehearsal follow-up; exact task ID, command, UTC, revision, and artifact were not supplied. | **Completed** for the repair boundary: nested firewall response handling, WAL-aware logical database hashing, offline-boot resume, and source-preserving SSH host-key handling were implemented and exercised by the later live rehearsal in E35. The original failure remains in E26. |
| `R-ASTRA-101-E27` | Independent Luna live private deployment checks. | Remote private host and provider boundary; exact task ID, command, UTC, revision, and artifact were not supplied. | **Pass** for the reported private checks: the deployed app and loopback boundary were exercised without a public route. The report does not pass the owner canary, recovery rehearsal, public exposure, or release checkpoint; reviewer `LUNA MAX QA`. |
| `R-ASTRA-101-E28` | Provider token verification and documentation coverage in the latest Luna QA report. | Native x86_64/local provider and documentation checks; exact task ID, command, UTC, revision, and artifact were not supplied. | **Fail** for this mixed follow-up: Cloudflare token verification returned HTTP `401`, despite functional provider API/Terraform operations, and documentation coverage was reported **Fail**. The discrepancy and coverage failure remain open; no token health or docs gate pass is inferred. Reviewer `LUNA MAX QA`. |
| `R-ASTRA-101-E29` | Owner authentication through CUA for the restricted canary. | CUA/browser; exact task ID, command, UTC, revision, and artifact were not supplied. | **Unavailable**. No owner authentication, GitHub callback, passkey enrollment, invitation redemption, or two-user ownership result is claimed. |
| `R-ASTRA-101-E30` | Fresh-task discovery and runtime invocation of the fixed-target deployment MCP. | Fresh CLI task for static discovery; task ID, command, UTC, and artifact were not supplied. `.codex/config.toml` contains only fixed nonsecret target metadata and operator-owned key paths. | **Pass** for static discovery; the actual MCP call was blocked by the current host approval policy `never`, so runtime invocation is **Unavailable**. No MCP deployment acceptance is inferred. |
| `R-ASTRA-101-E31` | Final authored-documentation validator, coverage, self-test, and whitespace checks after this reconciliation. | Native x86_64 Linux; `2026-09-27T23:45:49Z`; dirty `HEAD` `f329a4c99bf75d9ff2d365473051580f8eda7f58`; commands `.dev-venv/bin/python scripts/validate_docs.py`, `python3 scripts/check-doc-coverage.py --root . --map documentation-map.json`, `python3 scripts/check-doc-coverage-self-test.py`, and `git diff --check -- AGENTS.md README.md MVP-PLAN.md MVP-ROADMAP.md docs`. | **Pass**: documentation validation reported 9 categories, 13 topics, and 7 project skill governance entries; coverage checked 133 mapped files; self-test passed 26 cases; and scoped diff-check exited 0. This current pass does not erase Luna's earlier coverage **Fail** in E28 or establish runtime MCP, canary, recovery, release, commit, or push acceptance; reviewer `LUNA MAX docs`. |
| `R-ASTRA-101-E33` | Documentation checks after recording the failed live recovery rehearsal and repair boundary. | Native x86_64 Linux; `2026-09-27T23:47:30Z`; dirty `HEAD` `f329a4c99bf75d9ff2d365473051580f8eda7f58`; commands `.dev-venv/bin/python scripts/validate_docs.py`, `python3 scripts/check-doc-coverage.py --root . --map documentation-map.json`, `python3 scripts/check-doc-coverage-self-test.py`, and `git diff --check -- AGENTS.md README.md MVP-PLAN.md MVP-ROADMAP.md docs`. | **Pass**: documentation validation reported 9 categories, 13 topics, and 7 project skill governance entries; coverage checked 133 mapped files; self-test passed 26 cases; and scoped diff-check exited 0. This pass is docs-only and does not close the recovery, canary, MCP, provider-token, release, commit, or push gates; reviewer `LUNA MAX docs`. |
| `R-ASTRA-101-E34` | Source and infrastructure repair review after the private deployment hardening changes. | Native x86_64; dirty reviewed revision `f329a4c99bf75d9ff2d365473051580f8eda7f58`; independent Luna QA window `2026-09-28T01:18:00Z`–`2026-09-28T01:25:00Z`; exact task ID, artifact, and command were not supplied. | **Pass** for the declared scoped review: Terraform format/validate, `31` scoped infrastructure tests, and `git diff --check` passed. The code-managed cloudflared unit, host-unit update path, source-gated fresh-bootstrap delivery, live Terraform refresh guard, and rehearsal-resume fixes were present. Ruff reported an import-order finding in `tests/test_linode_terraform.py`; the later E43 QA records its repair. ShellCheck warnings were informational, and `infra/linode/validate.sh` exited `2` because the worktree was intentionally dirty. This is not clean-release or production acceptance; reviewer `LUNA MAX QA`. |
| `R-ASTRA-101-E35` | Final disposable VM Backup recovery rehearsal from snapshot `385239936`. | External Linode restore operation; replacement host `106817202`; disposable clone `106825234`; private operator receipt retained outside the repository; exact task ID, command, and UTC were not supplied. | **Pass** for the declared recovery scope: the clone was restored, booted, checked against the firewall and restricted SSH boundary, verified for loopback app readiness, schema/data counts, backups, and disabled tunnel state, then deleted and confirmed by API lookup `404`. The earlier E26 failure remains visible. No independent encrypted off-server backup is claimed. |
| `R-ASTRA-101-E36` | Live Cloudflare owner-only canary after Terraform application. | Cloudflare provider and private Linode host; canary hostname `ledger.jtmb.cc`; exact task ID, command, UTC, and artifact were not supplied. | **Pass** for the restricted ingress scope: Terraform applied the exact hostname, owner Access policy, and cache bypass; the tunnel is healthy and active; unauthenticated browser traffic receives the Access `302` and private responses use `no-store`; direct public port `8000` timed out. This does not pass invited-user exposure, owner passkey enrollment, or saved-data verification. |
| `R-ASTRA-101-E37` | Browser authorization of the GitHub OAuth application and Cloudflare Access one-time-code flow. | In-app browser; exact task ID, command, UTC, and artifact were not supplied. Credential values are retained only in private operator storage. | **Pass** for the authorization steps completed in the browser. The browser client then blocked callback-code navigation, so this row does not establish a completed owner session or passkey ceremony. |
| `R-ASTRA-101-E38` | Owner callback completion, passkey enrollment, saved-data verification, and invited-user readiness. | In-app browser owner-only canary; exact task ID, command, UTC, and artifact were not supplied. | **Unavailable/Pending at that historical check**: callback-code handoff could not be completed by the browser client; owner passkey enrollment and the owner saved-data check were not completed. A later pre-redeploy owner session showed signed in as `jtmb`, while passkey and saved-data verification remained pending. The post-redeploy session is unverified. Public invited-user mode, two-user isolation, and legacy Linode `97934478` retirement remain pending. No production release or public invited-user route is claimed. |
| `R-ASTRA-101-E39` | Later privacy-refactor source security re-review after deployment and recovery repairs. | Supplied Astra source re-review; exact task ID, command, UTC, artifact, and source revision were not supplied. | **Fail at that review point**: Astra found a P2 because the configured owner email reached an embedded Python process argv. The later private-file repair and final re-review are recorded in E42/E43; this historical row must not be treated as current source security clearance or production acceptance; reviewer `ASTRA`. |
| `R-ASTRA-101-E40` | Final authored-documentation validator, coverage, self-test, and whitespace checks after this reconciliation. | Native x86_64 Linux; observed `2026-09-28T01:44:11Z`; dirty `HEAD` `f329a4c99bf75d9ff2d365473051580f8eda7f58`; commands `.dev-venv/bin/python scripts/validate_docs.py`, `python3 scripts/check-doc-coverage.py --root . --map documentation-map.json`, `python3 scripts/check-doc-coverage-self-test.py`, `git diff --check -- AGENTS.md README.md MVP-PLAN.md MVP-ROADMAP.md docs`, and the tracked-email literal scan. | **Pass**: documentation validation reported 9 categories, 13 topics, and 7 project skill governance entries; coverage checked 133 mapped files; self-test passed 26 cases; scoped diff-check exited 0; and the tracked docs contained no literal personal owner email. This row is docs evidence only and does not close the deployment, privacy re-review, canary, MCP, release, commit, or push gates; reviewer `LUNA MAX docs`. |
| `R-ASTRA-101-E41` | Deployment MCP protocol smoke using the official Python SDK stdio client. | Native x86_64; fixed nonsecret target environment; exact task ID, command, UTC, and artifact were not supplied. | **Pass** for the read-only protocol scope: initialization and `list_tools` exposed exactly `deploy`, `inspect`, `plan_deploy`, `rollback`, and `status`, and `inspect` returned `is_error=False` with bounded text content. Credential bytes were not printed. The separate fresh Codex client invocation remains **Unavailable** under host approval policy `never`; this read-only row does not accept deploy or rollback, which are covered by the later E45 plan/deploy row. |
| `R-ASTRA-101-E42` | Repair of the current privacy P2 and live-canary rerun. | Native x86_64; private owner-email file and validator environment; exact repair task ID, command, UTC, artifact, and revision were not supplied. | **Pass** for the repair and scoped canary checks: the owner email is no longer passed in embedded-process argv, the tracked tree has no literal personal email, `14` canary fixture tests passed, and the live canary script reran exit `0` with the tunnel active. Astra's final P1/P2 re-review is recorded as no remaining finding in E43; no production release is claimed. |
| `R-ASTRA-101-E43` | Final privacy-repair QA and Astra P1/P2 re-review. | Native x86_64; dirty `HEAD` `f329a4c99bf75d9ff2d365473051580f8eda7f58`; Luna QA `2026-09-28T01:38:08Z`–`2026-09-28T01:38:27Z`; exact commands and artifact were not supplied. | **Pass** for the declared final scope: Luna passed Ruff across all four tests, `38` focused pytest cases, Bash syntax, warning-level ShellCheck, the tracked personal-email scan, canary environment privacy, and `git diff --check`; no live mutation occurred. The live canary script reran exit `0` with the tunnel active, and Astra's final review reported no remaining P1/P2. The earlier E34 Ruff finding remains historical and is superseded by this repaired result. Owner passkey/data checks and invited-user exposure remain pending; reviewer `LUNA MAX QA` / `ASTRA`. |
| `R-ASTRA-101-E44` | Auth UI repair and independent browser/auth QA. | Native x86_64; reviewed commit `39bd185150cd3df70395e6c000f568dfd20831ac`; exact task IDs, UTC, and artifacts were not supplied. | **Pass**: frontend build/typecheck and `28` tests passed; pinned Playwright desktop/mobile checks passed `2/2`; independent Luna QA passed `9/9` auth contract checks, `2/2` click checks, and simulated passkey-cancellation checks on desktop and mobile. Astra's source review reported no P1/P2 after its `409` guidance finding was repaired. Owner passkey enrollment and saved-data verification remain pending; reviewers `LUNA MAX QA` / `ASTRA`. |
| `R-ASTRA-101-E45` | Private release publication and MCP plan/deploy of the reviewed image. | Native x86_64; reviewed commit `39bd185150cd3df70395e6c000f568dfd20831ac`; release archive SHA-256 `930d6d5b5d054908a25825c980584b620817bfa7ab212a62abd63f65c72f6f3f`; image ID `sha256:23ef16e4e5ee28db378c76bbcd9182345584bbffda55bd5313141fd0847fe31b`; MCP plan `a07bb7ba2716899bef956269495f0a47`; exact UTC and artifact were not supplied. | **Pass** for the private deployment scope: release publisher re-download verification passed; official Python SDK MCP plan and deploy passed to replacement Linode `106817202`; pre-deploy backup was present; status was healthy, schema `8`, and loopback-only. This does not pass owner passkey/data verification, public invited-user exposure, or production release acceptance. |
| `R-ASTRA-101-E46` | Owner-only Cloudflare canary browser recheck after the auth UI deployment. | In-app browser and Cloudflare canary; hostname `ledger.jtmb.cc`; exact task ID, UTC, and artifact were not supplied. | **Pass** for the restricted canary presentation: the canary served the new passkey text and unauthenticated Cloudflare traffic returned `302`. **Unavailable/Pending** for owner passkey enrollment and saved-data verification because the browser requested a nearby phone/Bluetooth credential and no completed credential was observed. Invited-user exposure remains closed. |
| `R-ASTRA-101-E47` | Final authored-documentation validation after the auth UI and private deployment reconciliation. | Native x86_64 Linux; observed `2026-09-28T04:05:13Z`; dirty `HEAD` `39bd185150cd3df70395e6c000f568dfd20831ac`; commands `.dev-venv/bin/python scripts/validate_docs.py`, `python3 scripts/check-doc-coverage.py --root . --map documentation-map.json`, `python3 scripts/check-doc-coverage-self-test.py`, `git diff --check -- AGENTS.md README.md MVP-PLAN.md MVP-ROADMAP.md docs`, and the tracked-email literal scan. | **Pass**: documentation validation reported 9 categories, 13 topics, and 7 project skill governance entries; coverage checked 133 mapped files; self-test passed 26 cases; scoped diff-check exited 0; and no tracked owner-email literal was found. This is docs evidence only and does not close owner passkey/data, public exposure, release, commit, or push gates; reviewer `LUNA MAX docs`. |
| `R-ASTRA-101-E48` | Current-status callback reconciliation and final authored-documentation checks before the later origin-navigation deployment. | Native x86_64 Linux; observed `2026-09-28T04:10:35Z`; dirty `HEAD` `39bd185150cd3df70395e6c000f568dfd20831ac`; same validator, coverage, self-test, scoped diff-check, and tracked-email scan commands as E47. | **Pass** for that documentation checkpoint: documentation validation reported 9 categories, 13 topics, and 7 project skill governance entries; coverage checked 133 mapped files; self-test passed 26 cases; scoped diff-check exited 0; and no tracked owner-email literal was found. The then-current browser session showed the owner callback and signed-in page; E38 remained historical and passkey/data checks remained pending. The later deployment supersedes that session observation; see E49. Reviewer `LUNA MAX docs`. |
| `R-ASTRA-101-E49` | Scoped origin-navigation repair, private image deployment, and fresh browser boundary check. | Native x86_64; reviewed commit `11faaf702129d0c1485a8683711d88340f623a71`; publisher SHA-256 `fad471b19db6ff4f9b4dc154055f0d2437128e49878e72a286b697f17e8a3f48`; image ID `sha256:26df706f6a2b4e76ee51bb014f94d39eb66bc7644a2c7a56eb3d012f41684d60`; MCP plan `530c1c65a7b4563e9c7f1cdbf5a47a3d`; pre-deploy backup `pre-deploy-11faaf702129d0c1-d1c03381.spbackup`; exact UTC and artifacts were not supplied. | **Pass** for the scoped repair/deployment checks: `tests/test_api.py`, `tests/test_auth.py`, focused tests, Ruff, security checks, and format checks passed; Astra reported no P1/P2; the MCP deploy reported ready schema `8`, no failure, and loopback-only. An external hyperlink from localhost:8765 to `https://ledger.jtmb.cc/passkey` loaded the HTML page instead of the prior `origin_rejected` JSON response. The new IAB tab's auth result was not verified, and tab 13's prior signed-in state may be stale; no current passkey or saved-data access is claimed. |
| `R-ASTRA-101-E50` | Stale-session passkey recovery repair in the source tree. | Native x86_64; source commit `a1d868287a729c75d9b8628f612a856db132374a`; exact UTC and artifacts were not supplied. | **Pass** for local source/UI scope: a stale or expired provisional session returned `authenticated:false` and left the passkey page at `Checking your session`; the repair presents sign-in recovery. Build/typecheck and `28` frontend tests passed, and desktop/mobile browser checks passed `4/4`. The fix is source-reviewed and locally tested but **not deployed**; no new remote auth, passkey, or saved-data result is claimed. |
| `R-ASTRA-101-E51` | Final clean-main private image deployment and live expired-session sign-in recovery. | Native x86_64; clean-main revision `2de5e9f199cd145707f95e81d389c40b2ab3c32a`; archive SHA-256 `b856795831b6fb46e94e330370e003843b266ad85f22e8d95ef7624536b2ac48`; image ID `sha256:ae7991f35a2093b145245f8037a3227981b09051805467870f759c0752bbfc3d`; retry MCP plan `2d8b0fe91ed01b55f1625c27edcc620b`; first plan failed transiently as `remote_operation_failed`; exact UTC/artifacts were not supplied. | **Pass** for private deployment and recovery navigation: retry plan passed, deploy returned deployed/readiness schema `8`, and status reported the current revision, `failed: null`, `loopback_only: true`, with pre-deploy backup `pre-deploy-2de5e9f199cd1457-751c7459.spbackup`. Live IAB reload showed `Sign in first`/`Open sign in` and hid `Create passkey`; opening sign-in and continuing with GitHub returned to `/passkey?mode=enroll&next=/overview`, showed `Signed in as jtmb`, and showed `Create passkey`. No ceremony completed in that browser tab; later operator evidence is recorded in E52. |
| `R-ASTRA-101-E52` | Operator-side owner database integrity, passkey/session evidence, persisted mappings, and fixed-target MCP inspection/status. | Native x86_64; current R-ASTRA-101 clean-main checkpoint `8be7933`; operator SQLite read-only evidence on `2026-09-28` UTC with exact query UTC not captured; fresh official Python SDK stdio inspect timestamp `2026-09-28T14:30:59.523209+00:00`; explicit fixed nonsecret target metadata. | **Pass** for the operator read-only scope: SQLite `quick_check` was `ok`, foreign-key violations were `0`, owner id `1` was claimed to the configured GitHub account as active admin, there was `1` nonrevoked passkey and `1` current passkey-verified session, and owner mappings were 13 events, 13 runs, 20 results, 0 outcomes, 6 holdings, and 3 watchlist items. This proves enrollment, a completed passkey verification on another computer, and persisted owner mappings, not authenticated UI/API retrieval. The fresh SDK client listed exactly the five typed tools and read-only inspect/status passed; inspect reported revision `2de5e9f199cd145707f95e81d389c40b2ab3c32a`, image `sha256:ae7991f35a2093b145245f8037a3227981b09051805467870f759c0752bbfc3d`, schema `8`, health `ready`, `loopback_only: true`, and `failed: null`. The in-task MCP tool returned `deploy_target_unconfigured` because its runtime lacked the target environment (**Unavailable** for that invocation). A fresh IAB production tab hit Cloudflare Access login with no transferable session. Astra reported no new P1/P2 source defect, but owner app retrieval and two-user isolation remain required before invited-user exposure or legacy-host retirement. |
| `R-ASTRA-101-E53` | Baseline Luna authentication/API regression suite and two-user gate status. | Native x86_64; current R-ASTRA-101 clean-main checkpoint `8be7933`; `2026-09-28T14:32:21Z`–`2026-09-28T14:33:44Z`; tests `tests/test_auth.py`, `tests/test_auth_repository.py`, and `tests/test_api.py`; exact command/artifact not supplied. | **Pass** for the listed baseline suite: `153` tests passed. The full two-user ownership gate remains **Unavailable/Pending** because coverage gaps remain; a builder is adding tests and independent post-build QA is pending. Reviewer `LUNA MAX QA`. |
| `R-ASTRA-101-E54` | Final authored-documentation validation after the owner-evidence reconciliation. | Native x86_64 Linux; `HEAD` `8be7933ed4d17cee31619adedf372581bf7c3a28`; UTC was not captured by the command tool; commands `./.dev-venv/bin/python scripts/validate_docs.py`, `python3 scripts/check-doc-coverage.py --root . --map documentation-map.json`, `python3 scripts/check-doc-coverage-self-test.py`, `./.dev-venv/bin/python -m pytest tests/test_docs_validation.py`, scoped `git diff --check`, and the tracked owner-email literal scan. | **Pass**: documentation validation reported 9 categories, 13 topics, and 7 governance entries; coverage checked 133 mapped files; self-test passed 26 cases; documentation tests passed `57` with one warning; scoped diff-check exited `0`; and no tracked owner-email literal was found. This is documentation evidence only and does not close authenticated owner UI/API retrieval, saved-data retrieval, two-user isolation, invited-user exposure, or legacy-host retirement. Reviewer `LUNA MAX docs`; no source, test, configuration, credential, provider, or Git-history mutation was performed. |
| `R-ASTRA-101-E55` | Authenticated owner API and saved-forecast retrieval observed after passkey verification, plus post-build security and isolation status. | Native x86_64; operator read-only Docker access logs covering since `2026-09-28T00:00Z`, observed `2026-09-28T14:50:04.643439Z`; owner passkey session `last_passkey_at 06:05:08.385559Z`; source checkpoint and exact log artifact were not supplied. | **Pass** for authenticated owner API retrieval and saved-forecast access: after the passkey session, `GET /overview` returned `200` at `06:05:08.804Z`; portfolio list returned `200` with count `3`; watchlist list returned `200` with count `2`; history list returned `200` with count `3`; and `saved-forecasts/{id}` returned `200` with count `21`. Read-only database evidence showed one active owner and zero other active users, with 6 owner holdings, 3 watchlist items, and 20 results. Source review confirmed protected API middleware requires passkey authentication and handlers derive ownership from the request. Astra judged this sufficient for authenticated owner API retrieval and saved-forecast access; browser-rendered content remains **Unavailable**. Independent Luna QA ran `.dev-venv/bin/python -m pytest tests/test_auth.py tests/test_auth_repository.py tests/test_api.py -q` from `2026-09-28T14:44:13Z`–`14:45:34Z` with `153` passed; security Ruff and diff checks passed. Comprehensive two-client isolation covers forged IDs, repeated forecasts, exports, holdings/watchlists, and member backup denial, but four gaps remain pending builder repair and independent post-build QA: cross-watchlist deletion, member `promote=true` restore denial, nested outcome export, and two-account invitation reuse/identity binding. This does not authorize invited-user exposure or legacy-host retirement; reviewer `ASTRA` / `LUNA MAX QA`. |
| `R-ASTRA-101-E56` | Independent final local two-user and invitation-boundary QA. | Native x86_64; Python `3.11.15`; dirty `HEAD` `8be7933`; `.dev-venv/bin/python -m pytest tests/test_auth.py tests/test_auth_repository.py tests/test_api.py -q -rA`; `2026-09-28T15:03:40Z`–`15:04:56Z`; exact artifact not supplied. | **Pass** for the local scope: `154` passed, `0` failed, and `0` skipped; focused two checks passed; security Ruff and diff checks passed. QA verified cross-watchlist deletion in both directions with post-state checks, member `promote=true` restore denial, nested observed/corrected outcome JSON export isolation, and two-browser GitHub callback invitation binding/reuse/mismatch using `httpx.MockTransport`, local `TestClient`, temporary migrated SQLite, and `MemoryAuthStore`. Remote two-user behavior and browser UI remain **Unavailable**; no deployment mutation occurred. Reviewer `LUNA MAX QA`. |
| `R-ASTRA-101-E57` | Final local R-ASTRA-101 gate after the new auth-flow comment-audit repair. | Native x86_64; dirty `HEAD` `8be7933`; first attempt `2026-09-28T15:08:28Z`–`15:08:52Z`; rerun `TMPDIR=/home/james/.cache/stock-probs-gate-tmp OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 TASK_ID=R-ASTRA-101 ./scripts/local-gate.sh check` at `2026-09-28T15:09:49Z`–`15:17:13Z`; receipt `test-results/local-gates/R-ASTRA-101-20260928T150949Z/evidence.json`. | **Fail** for the first attempt at the pre-existing new `auth-flow.spec.js` comment-audit check; frontend build and `28` frontend tests passed. One intent comment was added, `python3 scripts/comment_audit.py` then passed across `237` files, and diff-check passed. The rerun **Passed** with exit `0`: `683` Python tests passed, `4` live tests were deselected, coverage was `85.63%`, and frontend build/typecheck/`28` tests, documentation completeness, and comment audit passed. This local gate does not establish remote two-user/browser UI evidence or authorize invited-user exposure; Astra final gate review remains pending, as does legacy-host retirement. No deployment mutation occurred. Reviewer metadata was not supplied. |
| `R-ASTRA-101-E58` | Provider-refreshed `public_invited` Terraform apply and live public boundary. | Native x86_64; observed around `2026-09-28T15:20Z` (exact UTC and artifact were not supplied); provider-refreshed saved plan SHA-256 `6bc28c80c84da1b08e0b58bc8be941b0d117b45a90cc0db0c1349f3ea0b29f7e`; source docs/test commit `7712318`; deployed image remained revision `2de5e9f199cd145707f95e81d389c40b2ab3c32a`. | **Pass** for the declared infrastructure/boundary scope: apply exited `0` and changed only the owner-canary Access app (deleted) and the exposure guard; the refresh plan with `-detailed-exitcode` exited `0`; state showed `0` Access apps, `1` tunnel, `1` DNS record, and `1` cache ruleset. `/overview` returned `303` to local sign-in, `/api/v1/history` returned `401`, and `/api/v1/auth/status` returned `200`; each was `no-store`/`DYNAMIC`, and direct IP port `8000` was unreachable. Live IAB showed the unauthenticated sign-in page but no owner UI session. This does not prove browser-rendered owner content, remote two-user behavior, functional invited-user acceptance, Astra final gate completion, or legacy-host retirement; no image mutation was performed. Reviewer metadata was not supplied. |
| `R-ASTRA-101-E59` | Legacy Linode retirement and post-delete public boundary. | Native x86_64; observed around `2026-09-28T15:37Z` (exact UTC and artifacts were not supplied); `infra/linode/retire-legacy-linode.sh` validation-only mode passed on three distinct mode-`0600` private operator receipts; the `--execute` run exited `0`. | **Pass** for the declared retirement and boundary scope: the workflow accepted deletion of legacy Linode `97934478`; Linode API then returned `404` for the legacy ID and `200` with `running` for replacement `106817202`. The old instance was labeled `cardventory`, `g6-nanode-1`, Ubuntu 24.04, `us-east`, with backups disabled; the replacement is labeled `signal-ledger`, has the same shape and location, and has backups enabled. The data source was the local Signal Ledger app; no Cardventory-data preservation claim is made. Post-delete public probes returned `/api/v1/health` `200`, `/api/v1/auth/status` `200`, `/api/v1/history` `401`, and `/overview` `303` to sign-in, with `no-store`/`DYNAMIC`. Astra judged the evidence truthful and sufficient for this scope. Reviewer `ASTRA`; no production release claim is inferred. |
| `R-ASTRA-101-E60` | Current-machine owner passkey browser limitation after public exposure. | In-app browser on the current machine; exact UTC and artifact were not supplied; GitHub OAuth returned a provisional `jtmb` session at `/passkey?mode=verify`. | **Unavailable** for browser passkey verification: clicking Verify with passkey produced `The browser could not create a passkey`; signing out of the failed provisional session returned `403`/denied text; and verify mode exposed a generic error using `create`. No successful passkey UI result was observed. This is historical browser evidence pending the source repair; it does not invalidate the server-observed owner-verified session on another computer or saved API retrieval recorded in E52/E55. Reviewer metadata was not supplied. |
| `R-ASTRA-101-E61` | Provisional-session logout and mode-aware passkey verification repair with independent QA. | Native x86_64; source paths `src/stock_probs/api.py` and `frontend/components/auth-client.ts`; focused provisional test `2026-09-28T15:47:44Z`–`15:47:47Z`, full auth-file run `15:48:01Z`–`15:48:13Z`, `tests/test_api.py` `15:50:29Z`–`15:51:44Z`, and desktop/emulated Pixel 7 browser auth-flow `15:52:19Z`–`15:52:30Z`; exact commands, artifacts, and source revision were not supplied. | **Pass** for the local repair and QA scope: the narrow logout middleware exception permits signing out only the current user's provisional session; CSRF and origin checks remain, and private passkey gates remain. Mode-aware passkey verification wording is covered by the frontend repair. Focused provisional, full auth, API, frontend typecheck/`28` tests, browser auth-flow `4/4` desktop plus emulated Pixel 7, and security Ruff passed. Astra reported no P1/P2. Real passkey/hardware evidence is **Unavailable**, and the unenrolled provisional state was not directly combined in the independent test. No live deployment or remote image result is claimed; reviewer `LUNA MAX QA` / `ASTRA`. |
| `R-ASTRA-101-E62` | Full local R-ASTRA-101 gate after the E60 auth-flow repair. | Native x86_64; command `TMPDIR=/home/james/.cache/stock-probs-gate-tmp OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 TASK_ID=R-ASTRA-101 ./scripts/local-gate.sh check`; `2026-09-28T15:48:22Z`–`2026-09-28T15:56:15Z`; dirty revision `77123186bbb7af71d401defec0e8f99c7bb42cc0`; receipt `test-results/local-gates/R-ASTRA-101-20260928T154822Z/evidence.json`. | **Pass**, exit `0`: `683` Python tests passed, `4` live tests were deselected, coverage was `85.71%`, frontend build/typecheck/`28` tests passed, and documentation completeness plus comment audit passed. This is local dirty-tree gate evidence only; the remote image update/deploy and live owner passkey acceptance remain pending. Reviewer metadata was not supplied. |
| `R-ASTRA-101-E63` | Final main image publication, typed-MCP deployment, public boundary probes, and live sign-in/passkey repair check. | Native x86_64; pushed main revision `27e0d2f5916d4297e10d259aa4776055a78faeaa` (commit/push preceded this docs update); `./scripts/publish-production-image.sh` exit `0`; GitHub Release tag `signal-ledger-27e0d2f5916d4297e10d259aa4776055a78faeaa`; release re-download verification passed; archive SHA-256 `78f2e44ecfbe2021a61a0ecd71414065024c246eb46ca9506b33c20f13b07ad1`; Linux/amd64 image ID `sha256:ecd41e1b65eb76b424cff830a6150db2282d326cfb18b3b6eaa37b07f83c4bc0`; archive size `103119161` bytes; first MCP plan returned `remote_operation_failed`, retry plan `21ca962a39d261282610568bc1e21219` passed; exact UTC was not supplied. | **Pass** for the declared publication/deployment scope: a fresh official Python SDK stdio client listed exactly five typed tools; pre-deploy inspect reported the prior revision `2de5e9f` ready; MCP deploy returned `deployed` schema `8`; status reported revision `27e0d2f`, `failed: null`, `loopback_only: true`, and pre-deploy backup `pre-deploy-27e0d2f5916d4297-39376b8d.spbackup`. Public probes returned `/api/v1/health` `200`, `/api/v1/auth/status` `200`, `/api/v1/history` `401`, and `/overview` `303` to local sign-in, all `no-store`/`DYNAMIC`. Live IAB OAuth produced a provisional `jtmb` `/passkey?mode=verify` session; passkey remained unavailable there, the corrected error was `The browser could not verify a passkey`, and signing out returned `/sign-in` with no account controls twice. A post-deploy read-only SQLite check reported `quick_check=ok`, zero foreign-key violations, 13 search events, 13 forecast runs, 20 forecast results, 6 holdings, 3 watchlist items, 1 passkey, and 1 user, matching the preserved owner data. Owner full-session evidence remains limited to the other-computer E52/E55 record; independently completed passkey, browser-rendered owner workspace, and live second-user onboarding remain **Unavailable**. Reviewer metadata and exact UTC were not supplied. |
| `R-ASTRA-101-E64` | Astra final live read-only review of the deployed public boundary and source security controls. | Live read-only production review; `2026-09-28T16:16:44Z`–`16:16:50Z`; exact command, environment, revision, and artifact were not supplied. | **Pass** for the declared review scope with no P1/P2: sign-in/auth returned `200`, overview returned `303` to local sign-in, history/portfolio/JSON export/backup returned `401`, responses were `no-store`/`DYNAMIC`, direct IPv4 port `8000` timed out, and source retained passkey, CSRF, and own-session logout controls. Independently completed passkey, rendered owner workspace, live second-user onboarding, Terraform/image recheck by Astra, IPv6, and old-VM recheck remain **Unavailable**; no full production acceptance claim is made. Reviewer `ASTRA`. |


`R-ASTRA-101` remains **In progress**. The external steps have created the provider access items,
applied the replacement infrastructure, published and re-verified the current release archive,
deployed the reviewed image privately through the typed MCP, completed the declared recovery
rehearsal, applied the E58 `public_invited` boundary, retired the legacy Linode in E59, and deployed
the current main image in E63. The current auth-UI repair, privacy P2 repair, final scoped QA, and
Astra reviews are complete for their declared scopes. E49 and E50 remain historical scoped records; E51
records the earlier final deployment and live sign-in recovery, E52
records operator-side owner enrollment/passkey verification and persisted mappings, E53 records
the baseline test pass, E54 records the final documentation checks, E55 records authenticated
owner API/saved-forecast retrieval, E56 records the local two-user QA pass, E57 records the
passing rerun of the full local gate after its initial comment-audit failure, and E58 records the
live public boundary. Browser-rendered owner content and remote two-user behavior remain
**Unavailable**; functional owner/invited-user acceptance remains pending. E60 records the historical
current-machine browser passkey limitation; E61 records the locally accepted repair and QA, E62 records
the passing full local gate, E63 records the then-current schema-8 deployment, and E64 records Astra's no-P1/P2 live
read-only review. Server-observed owner verification and
saved API retrieval remain recorded in E52/E55. The historical
R-ASTRA-100 aggregate remains separately recorded and is not relabeled by E12. The Cloudflare
token-verification `401`, earlier documentation-coverage failure, historical callback-code/browser
limitation, fresh-IAB Access-login limitation, browser-rendered UI unavailability, remote two-user
unavailability, initial comment-audit failure, and fresh Codex-client approval-policy limitation remain
visible; the
  origin-navigation repair is recorded in E49, the source/UI repair in E50, the earlier deployment in
  E51, operator/MCP/QA/documentation/retrieval/local-gate evidence in E52-E57, the public boundary in
  E58, the legacy-host retirement in E59, the current-machine browser limitation in E60, the local
  repair/gate in E61-E62, and the deployment/review recorded in E63-E64. No secret,
token, key, owner
email, private path, or public hostname belongs in
tracked roadmap prose.

All Ponytail references in the status and receipt sections below are historical, overengineering-
only evidence. Ponytail is retired and is not a current workflow dependency, command, review, or
acceptance gate.

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
  **Completed for its declared scope** by the later `M07-E20` receipt below; `EXP-M07` is also
  **Completed** at `779aa749d2f85849427212d890ee6918987492b7`, and M08 was the next walkthrough
  gate at that checkpoint. The current M08, ASTRA-FINAL, and `EXP-M08` records are above.
- **Earlier integrated M07 release acceptance:** task `M07`, evidence `M07-E18`, ran
  `TASK_ID=M07 PERFORMANCE_REVIEWER='LUNA MAX QA' ./scripts/local-gate.sh release` and
  passed on clean commit `131aabc0fc0528b1e70ba26e09e2c78565ee8d56` at
  `2026-09-12T18:14:08Z`–`2026-09-12T18:21:06Z` on native x86_64 Linux: `396` tests
  passed, `4` live deselected, `89.62%` coverage, browser `40` passed/`2` expected
  performance skips, official MCP, migration with verified pre-migration backup schema v1
  to v4, backup CLI `17` passed, the retained receipt's Ponytail interface precondition
  **Pass**, and `17`
  executable performance rows **Pass** with ARM64 performance **Unavailable**. Artifacts
  are under `test-results/local-gates/M07-20260912T181408Z/`; reviewer `LUNA MAX QA`.
  The two earlier failed release runs and `R-M09-4`/`R-M09-5` repair records remain
  visible as history; `EXP-M07` is now **Completed** at commit
  `779aa749d2f85849427212d890ee6918987492b7`, with its export audit recorded below. M08 is
  next after that checkpoint.
- **Final clean-checkpoint M07 release receipt:** task `M07`, evidence `M07-E20`, ran
   `TASK_ID=M07 PERFORMANCE_REVIEWER='LUNA MAX QA' ./scripts/local-gate.sh release` and
   passed at clean detached commit `c55064da92dcc8da591494c1c88cf040039e2437` on
   `2026-09-13T07:31:01Z`–`2026-09-13T07:38:21Z`, native x86_64 WSL2 with Python
   `3.11.15` and Node `22.19.0`: `417` passed/`4` deselected/`89.65%` coverage, browser
   `62` passed/`2` expected performance skips, official MCP, backup CLI `17` passed,
   package `122,814` bytes, build `634.16 ms`, `17` executable performance rows **Pass**,
   static `97,893` bytes, and ARM64 performance **Unavailable**. Artifact:
   `test-results/local-gates/M07-20260913T073101Z/`; reviewer `LUNA MAX QA`. The clean state
   applies only to that detached checkpoint; no clean state is inferred for the concurrent main
   worktree. This receipt does not itself create export, push, exact remote verification, or a
   new notification.
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
- **Earlier accepted `ASTRA-FINAL`:** **Accepted for its declared scope** at clean commit
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
- **Historical pre-notification status (retained):** via `skill-maintenance`, the final learning
  synthesis was **In progress** and `EXP-FINAL` was **Pending** for synthesis completion and its
  separate export, secret review, commit, push, and exact remote verification.
- **Earlier accepted final receipt (immutable history):** the supplied receipt records accepted
  `EXP-FINAL` checkpoint `b96cb6954ecf6e03b3bcdb0ad52af38ed7eae4cb`. `NOTIFY-FINAL` is
  **Completed for its operational scope only**: the optional post-`EXP-FINAL` delivery to the
  user-supplied out-of-band webhook returned HTTP `204` with an empty response body around
  `2026-09-13T01:45Z`; no retry was needed, and the bounded success did not change the accepted
  `EXP-FINAL` result. Its retained dirty-worktree context is
  `91ba52eca35fcfc13bd0d9996beb947d65d69d09`; reviewer/coordinator:
  `OpenCode gpt-5.6-sol`.
- The payload was a minimal non-secret receipt containing the accepted result, checkpoint, and
  evidence summary. The endpoint, token, and credential-bearing payload were never written to the
  repository, export, artifacts, or logs; the sanitized export shows zero webhook-pattern
  matches. Exact delivery UTC, network environment, and a separate notification artifact were
  not supplied and are not inferred. `NOTIFY-FINAL` is not a milestone or acceptance ID.
- **Current post-repair visual result:** `R-ASTRA-22` is **Completed for its declared scope**.
  Independent QA on dirty `HEAD` `91ba52eca35fcfc13bd0d9996beb947d65d69d09` reported `425`
  passed/`4` deselected/`89.65%` coverage, provider `32` passed, browser `62` passed/`2`
  expected performance skips plus `31` at `1280px`, `17` executable performance rows passed,
  static `97,893`/`98,304` bytes, and persistence `55 + 35 + 4` passed. `R-ASTRA-24` records
  SPY lookup as ETF, `R-ASTRA-25` heading order, `R-ASTRA-26` `44px` desktop actions, and
  `R-ASTRA-27` selector alignment after a failed initial render and successful reruns. The
  supplied overengineering-only Ponytail result was `Lean already. Ship.`
 - **Earlier post-repair ASTRA disposition (retained):** session `ses_f6683138affe6t8S6Z0G66YJDc` is
  **Accepted** with no reproducible blockers. Artifacts are `test-results/astra-final-live/` and
  `test-results/astra-final-repair/`; the live browser receipt records event `143`/run `141`,
  fresh event `145`, `21` localhost-only requests, and axe `0/0` at desktop and `390px`.
  Physical mobile, actual screen-reader, true-zoom, and native/physical ARM64-performance
  evidence remain **Unavailable**. ACDC/SPY flows do not prove news relevance or exact-symbol
  provider availability. No new clean release, export, commit, push, remote verification, or
  notification is claimed.
- **Current post-repair `EXP-FINAL`:** **Completed** for the same declared final acceptance
  scope, not a new milestone or acceptance scope. The implementation checkpoint is
  `c55064da92dcc8da591494c1c88cf040039e2437`; the release-receipt documentation checkpoint is
  `830030ab5322e5c7aaaf12e6fde3f6c0ea9b2a12`; and the accepted export checkpoint is commit
  `10b5de4a1842baf43e847f21f75154966e44b9c0`, parent `830030a`, message `Checkpoint final repair
  session`. Exact `git push origin main` passed and `git ls-remote origin refs/heads/main` exactly
  matched `10b5de4a1842baf43e847f21f75154966e44b9c0`. The sanitized audit used session
  `ses_f71ec0499ffeokWj4h6tVwyYk1`: `572` messages, `3,155` parts, `952` tool parts, `350`
  completed task outputs, `2,552,320` bytes, `90,476` lines, SHA-256
  `cf1b85d07eefc9ff6436ad692ee826cb394be8f39af34caf6b1ff58f1f8517ff`, and `14,895`
  redaction markers; ordered message-ID hash
  `ecc9a2be4ebf82e92e459a979cde2ceb93517c61d2ec95708a9f370fff255568`; ordered part-ID hash
  `0061d16fa7de0a60d8cb159db0d11474f291247708925bc6cb4b65c643da33be`; exact watermark with a
  later database delta of `1` message/`5` parts, all strictly trailing; and strict allowlist
  redaction checked `38,686` strings with zero violations and zero webhook/private-key/AWS/GitHub/
  Bearer/credential-URL matches. Built-in sanitized and unsanitized OpenCode exporter attempts
  each emitted only `64KiB` of invalid/incomplete JSON; no corrupt export was accepted. The
  verified equivalent used a read-only SQLite transaction and strict allowlist redaction.
  Reviewer `LUNA MAX QA`; audit UTC `2026-09-13T12:28:44.223816Z`; native x86_64; OpenCode
   `1.18.30`. Exact export-generation UTC remains **Unavailable**. No CI, new acceptance scope,
   or new notification is claimed.
  - **Earlier post-final `R-ASTRA-64` documentation reconciliation (retained):** **Completed for its declared
   documentation scope** after the final documentation checks; owner/phase `LUNA MAX docs`. This is a documentation-only record
   after the supplied implementation and independent QA evidence, not a new milestone or clean
   release checkpoint. FastAPI remains the sole production server for `/`, `/api/v1/docs`, and
   `/api/v1`. Next.js `16.3.5` / React `19.3` is a static App Router export built by
   `./scripts/build-frontend.sh` with stable build ID `stock-probs`; generated `.next`/`out`/
   staged trees are ignored, 12 staged served files are packaged into the wheel, and Node is
   build-only in the container. Strict CSP exact inline hashes, parser-blocking `theme.js`,
   native Settings Light/Dark/System, and `R-ASTRA-59`'s open-state anchor repair are recorded
   in [`docs/evidence/astra-final-report.md`](docs/evidence/astra-final-report.md). Supplied QA
   reports Python `444` pass/`4` deselected/`89.73%`, docs `52`, browser `64` pass/`2` expected
   performance skips, axe `0/0`, focus geometry `8/8`, no external/`.txt` traffic, deterministic
   build `26`/`703,175` bytes, staged `12`/`608,713` bytes, wheel about `306,559` bytes, and
   amd64 image digest `sha256:0d68e3d9a78d626a61a1a82c455ea1734ddaa753f562d74022b94986c477bb12`
   at `170,062,564` bytes. Native M09 reports `18` rows, theme p95 `32.7 ms`, render p95
   `168.649 ms`, static `696,727`/`753,664` bytes, navigation `13`/`574,661` bytes, and
   wheel `306,553`/`335,872` bytes; ARM64 performance is **Unavailable**. Earlier `120.2`/
   `120.8 ms` theme failures remain history; emulated ARM64 is functional/package/runtime only,
   and physical mobile, screen-reader, and true-zoom evidence remain **Unavailable**.
   `development-conventions` is the eighth opt-in skill with fresh discovery **Pass**, but
   activation requires a parent restart. The post-migration ASTRA review is **Blocked** and
   named live-browser evidence is **Unavailable** because the current parent lacks official
   `playwright_*` tools and delegated attempts timed out; no remaining reproducible app blocker
   was reported. `R-ASTRA-43`/`R-ASTRA-46` and subsequent Ponytail history, including rejected
   `R-ASTRA-63` CSP-regex advice, remain visible. Exact commands, sessions, UTC, revisions,
   artifacts, and named reviewers for the supplied post-final summary were not supplied and are
   not inferred. `R-M00-2-E46` records `.dev-venv/bin/python scripts/validate_docs.py` as **Pass**
   with `9` categories, `13` topics, and `8` project skills; `R-M00-2-E47` records
   `git diff --check -- README.md AGENTS.md MVP-PLAN.md MVP-ROADMAP.md docs` as **Pass**. Both
   checks ran on native x86_64 Linux at dirty `HEAD`
   `5633f87f8cff04b5b33640f6633ff31c667c0435`; UTC was not captured by the command tool;
   reviewer `LUNA MAX docs`; no code, configuration, test, export, commit, push, or Git-history
   mutation was performed. No clean commit, export, push, or exact remote result is claimed.
 - **Current local production containerization:** `R-M07-5` is **Completed for its declared
  scope** by two passing container contract tests and the supplied amd64 image receipt (digest
  `sha256:0dcb3f5ec77d31a5e8f57ef6e5d57b7144b973c3acb73ac360ffe01494735da`, size
  `169,699,932` bytes). The path remains Compose-only, loopback-bound, non-root, healthchecked,
  persistent for SQLite/WAL/backup data, resource- and log-bounded, real-Yahoo-default, and
  compatible with retained native non-container development.
- **M05 implementation/preparation evidence only:** migration pre-backup, serve due-check with `STOCK_PROBS_BACKUP_INTERVAL_SECONDS` default `86400` and bounds `60`–`2678400`, backup-key rotation/retirement, `32`-artifact/`256 MiB` retention, and non-expiring query history are implemented. `docs/operations/backup-restore.md` and `docs/configure/local-configuration.md` were updated for accuracy by `SOL HIGH`. The earlier M08 capture harness supplied `20` annotated screenshots and manifest SHA-256 `f9fef2b2db0a806cc47ff1db82e1e895f4dd4803425c0cf74426f5fa5a12dd5d`, but that remains preparation evidence only; the current extension is recorded above and in the M08 gate section.
  - **Earlier `R-ASTRA-64` final gate receipt (retained):** The artifact
    `test-results/local-gates/M09-20260914T002732Z/`
   records task `M09`, command `./scripts/local-gate.sh m09`, **Pass**, exit `0`, dirty `HEAD`
   `5633f87f8cff04b5b33640f6633ff31c667c0435`, native x86_64, and
   `2026-09-14T00:27:32Z`–`2026-09-14T00:40:00Z`. All eight completed checks are recorded,
   including official MCP; Python JUnit reports `444` tests, zero errors/failures, coverage
   `89.73%`; browser artifacts/logs report `64` passed and `2` expected performance skips; and
   the performance summary reports `18` rows, `17` executable **Pass**, and ARM64 performance
   **Unavailable**. Current row values include theme p95 `34.9 ms`, browser render p95
   `152.881 ms`, ten-item news render p95 `35.4 ms`, news cache-hit p95 `1.621 ms`, news
   response `701` bytes, provider deadline `10 s`, static `696,727`/`753,664` bytes, and wheel
   `306,553`/`335,872` bytes. Emulated ARM64 passed package/runtime/functional checks under
   QEMU `7.2.0`, not performance. The unsupported `TASK_ID=R-ASTRA-64` attempt exited `2` with
   no artifact; the first supported M09 attempt failed the `test_backup_automation` timing race,
   and supplied `R-ASTRA-65` repair history records removal of the irrelevant completion
   assertion followed by a passing rerun. Latest Ponytail `R-ASTRA-65` is findings-only and
   nonblocking: its CSP-regex suggestion is rejected because production CSP parsing is a security
   boundary; it is not clean. No named ASTRA live acceptance or clean release/commit/export/push/
    remote result is claimed. Detailed rows are in [`docs/evidence/astra-final-report.md`](docs/evidence/astra-final-report.md).
    `R-M00-2-E48` records the final `.dev-venv/bin/python scripts/validate_docs.py` rerun as
    **Pass** (`9` categories, `13` topics, `8` project skills); `R-M00-2-E49` records the final
    `git diff --check -- README.md AGENTS.md MVP-PLAN.md MVP-ROADMAP.md docs` rerun as **Pass**.
    Both ran on native x86_64 Linux at dirty `HEAD` `5633f87f8cff04b5b33640f6633ff31c667c0435`;
     UTC was not captured by the command tool; reviewer `LUNA MAX docs`; no Git mutation.
  - **Completed docs-only portable-link repair (`R-ASTRA-70`):** owner/phase `LUNA MAX docs`;
    eight ignored-artifact links were changed to inline code. Local and ignored artifact paths
    remain inline code, never Markdown links. This creates no milestone, implementation
    acceptance, release, export, commit, push, remote, CI, or notification result.
  - **Current final documentation reconciliation (`R-ASTRA-71`):** **Completed for its declared
    documentation scope**; owner/phase `LUNA MAX docs`. The named initial ASTRA session
    `ses_f6276e3a8ffeR3awDDSYKonmLk` was **Blocked** at
    `2026-09-14T01:30:13Z`–`01:47:02Z` on native x86_64/headless Chromium `153.0.8010.12`,
    dirty `HEAD` `5633f87f8cff04b5b33640f6633ff31c667c0435`, reviewer `ASTRA`, model
    `openai/gpt-6-astra`: official MCP exposure passed, but reverse-Tab then Escape at `320x844`
    restored focus off-screen. Forecast/chart/news evaluation was **Unavailable** because the
    first isolated server used the wrong 2026 fixture clock and correctly returned `stale_data`,
    not because of a production defect. The repair progression preserves incomplete
    `R-ASTRA-66`, independent-QA failures after `R-ASTRA-67`, guarded external entry and trigger
    restoration in `R-ASTRA-68`, and 320px Pixel/mobile restoration in `R-ASTRA-69`.
  - Final `R-ASTRA-69` Ponytail is **CLEAN**: `/ponytail-review` returned exactly
    `Lean already. Ship.` at `2026-09-14T02:41:58Z`, native x86_64, dirty `HEAD` above, reviewer
    `OpenCode gpt-5.6-sol`. Independent QA (`LUNA MAX QA`) used
    `/tmp/opencode/r-astra-69-20260914T025542940Z.json` at
    `2026-09-14T02:55:42.940Z`–`02:55:54.436Z`: `66/66` passed, axe `0/0`, Light/Dark focus,
    HTTP `201` forecast with charts/text, HTTP `200` partial news with 2 items, local-only
    traffic, and no current errors. Full browser artifact:
    `test-results/r-astra-69-browser-20260914T0248Z/`, `64` passed/`2` expected skips, `33`
    desktop/`33` mobile; the shorter path is not the full artifact. Findings-only artifacts are
    historical/unrelated and do not override the clean boundary.
  - Final ASTRA session `ses_f622707a4ffeAE3Zx8Lt2zYiC1` is **Accepted** for the affected
    post-repair scope with no blockers: reviewer `ASTRA`, model `openai/gpt-6-astra`, native
    x86_64, official MCP/headless Chromium `153.0.8010.12`, dirty `HEAD` above,
    `2026-09-14T02:57:56Z`–`03:16:35Z`, routes `/` and `/api/v1/docs`, viewports `320x844` and
    `1280x1000`, Light/Dark. Exact shell command and separate ASTRA artifact were not supplied;
    the named session, reviewer, model, and revision are supplied. Prior focus/fixture blockers,
    the `8px` popover gap, containment, no overlap/overflow, `44px` controls, focus/dismissal,
    sampled contrast, first paint/System/CSP/media emulation, ACDC-M event `#6`/run `#2`,
     charts/text, partial news (2 items), OpenAPI, and `103` requests/`18` data requests; no
     off-origin, non-API, or `.txt` traffic and no current errors. `.data-label` is
     optional/nonblocking; no
    repair is authorized. Physical mobile, screen reader, true zoom, fresh ASTRA axe/screenshots,
    and native ARM64 performance remain **Unavailable**.
  - Failed M09 rerun `test-results/local-gates/M09-20260914T031828Z/` remains visible with `46`
    documentation-link setup errors. Final M09 artifact
    `test-results/local-gates/M09-20260914T032442Z/evidence.json` **Passed**, exit `0`, at
    `2026-09-14T03:24:42Z`–`03:37:22Z` on native x86_64 dirty `HEAD` above, command
    `./scripts/local-gate.sh m09`, reviewer `LUNA MAX QA`: Python `444`, `89.73%` coverage,
    browser `64` passed/`2` expected skips, official MCP, `17` executable native-x86 performance
    rows passed, and QEMU `7.2.0` ARM64 package/runtime/functional evidence only. Current rows:
    theme `35.0 ms`, browser render `151.958 ms`, interaction `24.027 ms`, ten-item news render
    `35.0 ms`, news cache-hit `1.809 ms`, news response `701` bytes, provider deadline `10 s`,
    static `697,667`/`753,664` bytes, readiness `2,633.207 ms`, process RSS `144,457,728` bytes,
    and wheel `307,483`/`335,872` bytes; ARM64 performance **Unavailable**. `EXP-M09` remains
    **Pending** for export, secret review, commit, push, and exact remote verification. No clean
    release/export/commit/push/remote/CI/notification result is claimed for this reconciliation.
     Full rows: [`docs/evidence/astra-final-report.md`](docs/evidence/astra-final-report.md).
     Prior `R-M00-2-E50`–`R-M00-2-E55` documentation-check records remain historical; new final
     checks use new IDs below.
     `R-M00-2-E56` records `.dev-venv/bin/python scripts/validate_docs.py` as **Pass** with
     `9` categories, `13` topics, and `8` project skills. `R-M00-2-E57` records the exact
     `.dev-venv/bin/python -m pytest tests/test_docs_validation.py` attempt as **Unavailable**
     because the tool permission boundary denied execution; no documentation-test pass is inferred.
      `R-M00-2-E58` records `git diff --check -- README.md AGENTS.md MVP-PLAN.md MVP-ROADMAP.md
      docs` as **Pass**. All three ran on native x86_64 Linux at dirty `HEAD`
      `5633f87f8cff04b5b33640f6633ff31c667c0435`; UTC was not captured by the command tool;
      artifacts are none for the validator/test attempt and the current owned-document diff for
      diff-check; reviewer `LUNA MAX docs`; no Git mutation occurred.
      `R-M00-2-E59` records the final `.dev-venv/bin/python scripts/validate_docs.py` rerun after
      the last wording correction as **Pass** with `9` categories, `13` topics, and `8` project
      skills. `R-M00-2-E60` records the final `git diff --check -- README.md AGENTS.md MVP-PLAN.md
      MVP-ROADMAP.md docs` rerun after the last wording correction as **Pass**. Both ran on native
      x86_64 Linux at dirty `HEAD` `5633f87f8cff04b5b33640f6633ff31c667c0435`; UTC was not captured
      by the command tool; artifacts are none for the validator and the current owned-document diff
        for diff-check; reviewer `LUNA MAX docs`; no Git mutation occurred.
       `R-M00-2-E61` records the final `.dev-venv/bin/python scripts/validate_docs.py` run for
       `R-ASTRA-72` as **Pass**: `9` categories, `13` topics, and `8` project skills. Native x86_64
       Linux; dirty `HEAD` above; UTC was not captured by the command tool; artifact none; reviewer
       `LUNA MAX docs`.
       `R-M00-2-E62` records the final `.dev-venv/bin/python -m pytest tests/test_docs_validation.py`
       attempt for `R-ASTRA-72` as **Unavailable** because the tool permission boundary denied
       execution; no documentation-test pass is inferred. Native x86_64 Linux; dirty `HEAD` above;
       UTC was not captured; artifact none; reviewer `LUNA MAX docs`.
       `R-M00-2-E63` records the final `git diff --check -- README.md AGENTS.md MVP-PLAN.md
       MVP-ROADMAP.md docs` run for `R-ASTRA-72` as **Pass**. Native x86_64 Linux; dirty `HEAD`
       above; UTC was not captured by the command tool; artifact current owned-document diff;
       reviewer `LUNA MAX docs`; no Git mutation.
   - **Current `R-ASTRA-72` Orchestrator rename validation:** **Completed for its declared
     rename/restart-validation scope** from independent post-restart QA by `LUNA MAX QA`. The
     historical `R-ASTRA-72` rename performed the change to exact `Orchestrator` and required
     restart validation. The supplied QA passed `opencode debug agent Orchestrator`, the retired
     identifier resolution check, debug config/JSON, `9` tooling tests, the targeted test, and a
     diff check on native x86_64 WSL2 at dirty `HEAD` `5633f87f8cff04b5b33640f6633ff31c667c0435`.
     Full rows are in [`docs/evidence/astra-final-report.md`](docs/evidence/astra-final-report.md).
     No new release, export, commit, push, or remote result is claimed.
    - The following M09 status and boundary bullets retain the pre-consolidated-gate state as
  history; the current declared-scope result and `EXP-M09` pending state are recorded above.
- **Historical pre-acceptance aggregate:** M09 implementation is **Completed for its declared implementation scope**, but `M09` was **In progress** pending the boundary `/ponytail-review`, the consolidated M09 gate, docs finalization, and `EXP-M09`. The supplied scoped QA summary reports `130` news-contract tests plus live ACDC/SPY checks, browser `40` passed/`2` skipped with axe `0/0`, and passing M09 performance rows; its missing session/command/environment/UTC/commit/artifact/reviewer fields are not inferred. `R-M09-1` is the Ponytail-review/local-gate M09 regex repair in flight. M07 was in flight with `R-M07-1` fifth-agent configuration/profile-count test repair in flight, `R-M07-2` Ponytail-review availability pending with findings-only evidence in retained report `test-results/ponytail-m06-m07-boundary.txt` and closure pending, `R-M07-3` completed for supplied repair/test evidence, and `R-M07-4` completed for supplied Ponytail repair evidence; no integrated acceptance or `EXP-M07` was claimed at that earlier state. `M08`, `ASTRA-FINAL`, and `EXP-FINAL` were **Pending** then. `EXP-M01` through `EXP-M06` were completed; later exports were pending at that time.
 - The preceding aggregate M07 in-progress wording is retained as immutable pre-acceptance
  history. Current `M07-E20` supersedes it for the declared scope; `R-M07-1`–`R-M07-4`
  and the two earlier failed release runs remain visible below.
 - The following M09 boundary and first-gate bullets preserve pre-consolidated-gate history
   only; `M09-E18` supersedes their open declared-scope wording, and `EXP-M09` is the only
   current approval gate.
  - **M09 boundary receipt:** The retained `test-results/ponytail-m09-boundary.txt` report records four overengineering findings and net `-119` possible lines. `SOL HIGH` applied minimal `R-M09-1` repairs: theme/news p95 sampling moved into `tools/browser/tests/performance.spec.js` (net `-25`; supplied `338` tests pass), provider curl stubs were consolidated to one helper (net `-25`; supplied `337` tests pass), CSS aliases were collapsed to one canonical name per role (net `-10`; `dashboard.spec.js` contrast assertions remain in flight), and the redundant static-row re-assertion was deleted. Independent verification of the harness/stub repairs is in flight; the consolidated M09 gate and `EXP-M09` remain **Pending**. Review/repair environment, UTC, commit, independent reviewer, and verification artifact metadata were not supplied and are not inferred.
- **Historical first consolidated M09 gate record:** The first `TASK_ID=M09 PERFORMANCE_REVIEWER='LUNA MAX QA' ./scripts/local-gate.sh m09` run **Failed** with the intermittent `test_success_repeat_failure_and_searchable_history` result (expected total `2`, observed `3`; known random request-ID/search-collision flake) and reproducible `R-M09-2`: local-gate invoked `scripts/arm64-smoke.sh`, which rejected `TASK_ID=M09` and exited `2` before ARM evidence. The clean rerun reported `338 passed/4 deselected/89.62%`. Independent continuation passed the native package (wheel `121,501` bytes including `theme.js` and `news.json`), browser `40` passed/`2` skipped, official MCP, Ponytail interface, and the M09 performance harness `18/18` rows; ARM64 performance is **Unavailable**. A separate functional/package/runtime smoke passed as **emulated ARM64**. `R-M09-2` and `R-M09-3` (flaky-test determinism) repairs were **In progress** in that historical record; the later `M09-E18` receipt supersedes that open wording, while `EXP-M09` remains the sole current approval gate. Session, environment, UTC, commit, and artifact metadata were not supplied and are not inferred.
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
| `M07` | Integrated MVP acceptance | M06, `EXP-M06`, M09, `EXP-M09` | **Completed for declared scope** | Final clean-checkpoint receipt `M07-E20` passed on detached commit `c55064da92dcc8da591494c1c88cf040039e2437` with `417` tests, browser `62`/`2` expected performance skips, official MCP, backup CLI `17` passed, package `122,814` bytes, build `634.16 ms`, `17` executable performance rows Pass, static `97,893` bytes, and ARM64 performance Unavailable. Earlier `M07-E18`/`M07-E19` and failed `R-M09-4`/`R-M09-5` remain historical; `EXP-M07` is the separate completed export checkpoint and `EXP-M09` remains pending. |
| `M08` | Instructional Walkthrough | M07, `EXP-M07` | **Completed for declared scope** | The earlier `20`-step/`40`-PNG extension report and later ASTRA repair records remain historical evidence. The bound final release observation is `7,660,518` bytes under the `20 MiB` budget; `ASTRA-FINAL` is accepted for its declared scope and `EXP-M08` is **Completed** at `7cf1ca8395b94c2e14e5b02ddf160f3f938091d3`. The current post-repair `EXP-FINAL` checkpoint is `10b5de4a1842baf43e847f21f75154966e44b9c0`; the earlier `b96cb6954ecf6e03b3bcdb0ad52af38ed7eae4cb` checkpoint and `NOTIFY-FINAL` record at dirty context `91ba52eca35fcfc13bd0d9996beb947d65d69d09` remain immutable history. No new notification is claimed. |

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

## Historical V1/V0 delivery workflow (preserved receipts; not current operational guidance)

The maximum is six concurrent agents overall. The orchestrator proactively fills up to six slots only when genuinely independent todos exist; every active agent owns a distinct todo, path, and evidence lane, with no duplicate work. Launch independent work in parallel, keep dependent steps sequential, and wait for all active lanes before integration and before independent QA. Do not invent busywork merely to fill slots. QA/docs waves may use one to six agents according to genuinely independent scopes. A build wave uses up to six concurrent `SOL HIGH build` instances and never more than six concurrent builders; A/B/C are the base roles and any additional lanes require declared disjoint ownership. The coordinator does not implement shared files, test, review, or write roadmap prose; it owns mechanical integration, status, and git only. `LUNA MAX QA` is verification-only and denies repair/delegation conceptually; it does not repair implementation/configuration or hand acceptance to a builder. The coordinator routes only reproducible blocking findings with an exact task ID to `SOL HIGH`; speculative or non-blocking preferences are not repair work. Future agent-profile and local-gate changes belong to `SOL HIGH` and require parent-process restart plus independent post-restart validation before affecting a gate.

The stock Playwright MCP entry in `opencode.json` is a hard orchestration/product
invariant: retain `./scripts/playwright-mcp.sh` with `--headless`, `--isolated`, and
loopback host/origin allowlists. Selective Ingenium pipeline adoption must never replace
  that entry with Ingenium browser automation. The no-plugin subagent-count control, if
  adopted, uses the valid `agent.options` field on the `Orchestrator` profile; `Orchestrator`
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

After an independently accepted `EXP-FINAL`, an optional operational notification may be referred to as `NOTIFY-FINAL`. It is not a milestone or acceptance task ID and cannot satisfy a missing gate. It may use only a webhook supplied out-of-band by the user and send only a minimal non-secret receipt, such as the accepted result and checkpoint SHA. The endpoint, token, headers, and credential-bearing payload must never be persisted or printed in the repository, `SESSION-EXPORT.md`, artifacts, screenshots, or logs; use a bounded request and redact transport errors. Record bounded success, failure, or unavailable delivery separately without changing the accepted `EXP-FINAL` result. The prior pre-notification documentation task performed no notification; the earlier bounded-success `NOTIFY-FINAL` receipt is immutable history, and no new notification is claimed for the current post-repair checkpoint.

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
**Pass**, and ARM64 performance **Unavailable**. The retained historical Ponytail artifacts are
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
| `M06` | **In progress** | `LUNA MAX docs` records the row; `SOL HIGH` owns any repair; `LUNA MAX QA` independently retests | **Historical receipt only:** a pinned Ponytail bundle/configuration was recorded at that checkpoint. The bundle is retired and absent from the current tree. Retained reports: [`docs/evidence/ponytail-r-m06-1.txt`](docs/evidence/ponytail-r-m06-1.txt) (six findings repaired), [`docs/evidence/ponytail-r-m06-15.txt`](docs/evidence/ponytail-r-m06-15.txt) (three repaired as `R-M06-19`), and [`docs/evidence/ponytail-m05-boundary.txt`](docs/evidence/ponytail-m05-boundary.txt) (two repaired as completed repair record `R-M05-12`, independently rerun `4/4` inside `R-M05-55 (i)`). | **Unavailable** for full M06 acceptance: `R-M06-19` is independently **Pass**, but the historical Ponytail review was overengineering-only and does not replace correctness, security, accessibility, or performance evidence. |
| `M06` | **Completed** for the listed validation scope | `LUNA MAX docs` plus post-restart validation | The authored documentation taxonomy and project documentation skill are implemented under `docs/**` and `.opencode/skills/documentation`; fresh isolated discovery passed the validator, 20 tests, description parity, the 500-line limit, and required references. Receipt: session `ses_f6aa32d33ffeAvmiFK8K7Cd8EI`, `2026-09-12T11:35:58Z`–`2026-09-12T11:36:02Z`, native x86_64/OpenCode `1.18.30`, dirty commit `59534faf1cdce493bc51a11d4adbea5e5b2d6892`; canonical description, six historical Ponytail commands, three legacy profiles, valid configuration, and no credentials all passed. This historical receipt does not describe current discovery; the current catalog has seven skills and no Ponytail package or skill. |
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
verification. The final clean-checkpoint `M07-E20` receipt is recorded below; retained
`M07-E18`/`M07-E19` records are historical and do not close `EXP-M09` or invent its missing
export evidence.

- **Dependencies:** completed declared-scope `M06` and completed `EXP-M06`; the recorded
  M07 release receipt consumes the declared M09 scope, while `EXP-M09` remains a separate
  pending export state.
- **Scope:** Add a user-selectable accessible dark mode across the dashboard and `/api/v1/docs`,
  plus a clearly labelled selected-instrument news view. News uses FastAPI `/api/v1`, preserves
  instrument identity and source/as-of provenance, and exposes the ten documented UI states.
  The final UI, M08 walkthrough, and `ASTRA-FINAL` matrix must include both features.
- **Frozen historical `M09-E13` constraint (ASTRA plan):** Settings database, news archive,
  article scraper/proxy, sentiment engine, forecast/model/probability changes, Redis or
  external cache, background scheduler, service worker, separate service, notification feed,
  full-text search, watchlist, personalized ranking, and any additional market-data provider
  were excluded from M09. The later `R-ASTRA-98` receipt separately approves/evidences bounded
  watchlists, forecast/model expansion, and provider-labelled quote/daily-bar market-data
  research; that later scope does not alter the frozen M09 row, reopen M09 implementation, or
  create a new current task.
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
| `M09-E1` | `GET /api/v1/news` has four closed schemas and `200`/`422`/`502`/`503` semantics; empty is not `404`. | **Completed** for supplied scope; `M09-E18` supersedes this historical row for the consolidated gate, and only `EXP-M09` remains pending. |
| `M09-E2` | Direct query2 retrieval through pinned `curl-cffi` uses the deadline and `256 KiB` cap; the fixture `_comment` is filtered by the loader. | **Completed** for supplied scope; exact receipt metadata unavailable. |
| `M09-E3` | Ephemeral cache has the frozen 5-minute fresh, 30-minute stale, 60-second empty, 30-second failure-suppression, 32-symbol, 32 KiB entry, 1 MiB aggregate, and one-active-retrieval limits. | **Completed** for supplied scope; exact deterministic artifact unavailable. |
| `M09-E4` | `theme.js` dark mode is on both pages with no-flash, contrast, forced-colors, and print behavior; disclosure covers all ten news states and saved reopen is provider-free. | **Completed** for supplied scope; separate state transcript/AT receipt unavailable. |
| `M09-E5` | Seven requests include `theme.js`; final static shell is `98,168`/`98,304` bytes with `136` bytes headroom. | **Completed** for supplied static measurement; command/artifact unavailable. |
| `M09-E6` | News-contract QA reports `130` tests passing plus live ACDC/SPY checks. | **Pass as supplied QA summary**; execution metadata unavailable. |
| `M09-E7` | Browser QA reports `40` passed/`2` skipped with axe `0/0`. | **Pass** for supplied automated/browser scope; skip reasons and actual screen-reader receipt unavailable. |
| `M09-E8` | Performance rows report theme p95 `32.4 ms`, news endpoint p95 `1.564 ms`, ten-item render p95 `30.3 ms`, response maximum `701` bytes, and deadline `10 s`. | **Pass** as supplied M09 performance summary; ARM64 performance **Unavailable**. |
| `M09-E9` | The declared lane handoff and implementation scope are complete. | **Completed** for implementation scope; `M09-E18` supersedes the historical boundary/gate wording, and only `EXP-M09` remains pending. |

`R-M09-1` (Ponytail-review/local-gate M09 regex repair) remains a retained
overengineering-only boundary record. The earlier `R-M09-2` (ARM-smoke task-ID invocation
blocker) and `R-M09-3` (flaky-test determinism) states were **In progress** in the historical
record; `M09-E18` below closes their repaired scopes. `R-M07-1` (fifth-agent
configuration/profile-count test repair) was **In progress** in that historical record and is
superseded for the declared M07 scope by `M07-E20`. The boundary review and first gate remain
visible below only as history; no current repair or Ponytail action is open.

#### M09 boundary Ponytail receipt and `R-M09-1`

The read-only `/ponytail-review` at boundary `M09` is retained as the pre-acceptance
overengineering record at
  `test-results/ponytail-m09-boundary.txt`. It records
four overengineering findings and net `-119` possible lines. The review is overengineering
evidence only and does not substitute for correctness, security, accessibility, performance,
or the consolidated M09 gate.

| Evidence ID | Finding and minimal SOL HIGH repair | Historical result and limitation |
| --- | --- | --- |
| `R-M09-1-E1` | Read-only `/ponytail-review` at boundary `M09`; report paths are `scripts/performance_harness.py:L1056-1200`, `tests/test_provider.py:L402-599`, `scripts/performance_harness.py:L1414-1436`, and `src/stock_probs/static/app.css:L20-33`. | **Fail** for the overengineering-only review because four findings were recorded; artifact: `test-results/ponytail-m09-boundary.txt`. Environment, UTC, commit, and reviewer were not supplied; no acceptance result is inferred. |
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
| `M09-E13` / `M09` | Frozen historical M09 rejected scope: settings database, news archive, article scraper/proxy, sentiment engine, forecast/model/probability changes, Redis or external cache, background scheduler, service worker, separate service, notification feed, full-text search, watchlist, personalized ranking, and any additional market-data provider. | **Frozen historical constraint; no current absence-audit task.** Later `R-ASTRA-98` separately approves/evidences bounded watchlists, forecast/model expansion, and provider-labelled quote/daily-bar market-data research; that later scope does not alter this M09 row. |
| `M09-E14` / `M09` | Historical boundary `/ponytail-review` and minimal repair of its four overengineering findings. | **Historical/superseded by `M09-E18`** for the declared M09 scope; report retained with four findings/net `-119` and `R-M09-1` repair evidence, but no current repair or Ponytail action is open. |

Every row receipt records task ID, check/command, environment, UTC, commit, result,
artifact/link, reviewer, limitations, repair history, and export/revision state. The earlier
scoped receipt lacks several of those fields, which remain unavailable; the current
`M09-E18` receipt supplies them for the declared consolidated gate. `EXP-M09` remains
pending and is not inferred from implementation presence or the historical M06 measurement.
- **Export gate:** `EXP-M09` must record the full-session export, secret review, local
  commit/push, and exact Git remote revision verification. Its pending evidence is recorded
  above; the supplied `M07-E18` receipt does not backfill this export checkpoint.

## M07 Integrated Acceptance Record

`M07` is **Completed for its declared integrated release scope** by the later `M07-E20` receipt;
`M07-E18`/`M07-E19` remain historical evidence. `EXP-M07` is
**Completed** at commit `779aa749d2f85849427212d890ee6918987492b7` for the separate
export/checkpoint gate. M06 is **Completed for its
declared scope** with `EXP-M06` complete, and the M09 declared scope is recorded above;
the separate `EXP-M09` pending state is not silently closed by this receipt. The earlier
M07 rows below are retained as pre-acceptance history:

| Task ID | Status | Requirement/check | Evidence and current result | Limitation/next gate |
| --- | --- | --- | --- | --- |
| `R-M07-1` | **In progress** | Historical fifth-agent configuration/profile-count test | Repair was in flight in the retained pre-acceptance record; command, session, environment, UTC, commit, artifact, and reviewer were not supplied. | Superseded by `M07-E20` for the declared integrated scope; no current retest or repair is required. |
| `R-M07-2` | **Pending** | Historical Ponytail review availability | Retained report `test-results/ponytail-m06-m07-boundary.txt` records findings only; its historical closure was pending. Availability evidence, command, environment, UTC, commit, artifact, and reviewer were not supplied. | **Unavailable in that historical record; superseded by `M07-E20` for the declared integrated scope.** No current Ponytail availability review is open. |
| `R-M07-3` | **Completed** | Repair stale three-profile assertions in `tests/test_ponytail_tooling.py` | `R-M07-3-E1`: assertions were updated from three profiles to four profiles; supplied test evidence reports `278` non-live tests pass. Exact command, session, environment, UTC, commit, artifact, and reviewer were not supplied. | **Pass as supplied repair/test evidence**; independent receipt metadata and broader M07 acceptance are not claimed. |
| `R-M07-4` | **Completed** | Apply two retained Ponytail findings in `tests/test_config_quality.py` | `R-M07-4-E1`: both retained findings were applied; supplied diff evidence reports a net `-1` line. Exact command, session, environment, UTC, commit, artifact, and reviewer were not supplied. | **Completed for the supplied repair scope**; this is Ponytail/repair evidence only, with no independent correctness or M07 acceptance pass inferred. |

#### Historical failed release runs and `R-M09-4`/`R-M09-5`

The two earlier failed release runs remain immutable history. Their separate command
output, session IDs, full environments, UTC windows, commits, artifacts, and named
reviewers were not supplied in this reconciliation and are not inferred. The repair IDs
remain visible even though the current M07 release receipt is now passing:

| Evidence/task | Historical requirement/check | Environment, UTC time, commit | Result, artifact, reviewer, limitation |
| --- | --- | --- | --- |
| `R-M09-4-E1` / `R-M09-4` | First earlier M07 release run and its repair record | Failure receipt metadata was not supplied | **Fail** as the retained historical release result; artifact and reviewer unavailable. The retained `M07-E18` receipt is the earlier integrated rerun, not a row-only `R-M09-4` receipt; current declared-scope evidence is `M07-E20`. |
| `R-M09-5-E1` / `R-M09-5` | Second earlier M07 release run and its repair record | Failure receipt metadata was not supplied | **Fail** as the retained historical release result; artifact and reviewer unavailable. The retained `M07-E18` receipt is the earlier integrated rerun, not a row-only `R-M09-5` receipt; current declared-scope evidence is `M07-E20`. |

#### M07 precondition-failure receipts (`R-M07-6`/`R-M07-7`)

These are new observations for the final clean-checkpoint attempt and do not alter the immutable
`R-M09-4`/`R-M09-5` records above.
`R-M07-6` and `R-M07-7` are **Completed for their recorded precondition-resolution scopes**;
each release attempt itself **Failed** before checks and neither is release acceptance.

| Evidence/task | Requirement/check | Environment, UTC time, commit | Result, artifact, reviewer, resolution |
| --- | --- | --- | --- |
| `R-M07-6` | Main dirty-tree release gate stopped before checks. | Concurrent main worktree; `2026-09-13T07:26:18Z`–`2026-09-13T07:26:31Z`; dirty `HEAD` `91ba52eca35fcfc13bd0d9996beb947d65d69d09`. | **Fail** before checks; artifact `test-results/local-gates/M07-20260913T072622Z/evidence.json` relative to the worktree; reviewer `LUNA MAX QA`; resolved by using an isolated clean worktree. |
| `R-M07-7` | First clean-worktree run stopped before checks because `.tools/node/bin/node` was absent. | Clean detached worktree at `c55064da92dcc8da591494c1c88cf040039e2437`; `2026-09-13T07:29:40Z`–`2026-09-13T07:29:56Z`; host/runtime metadata not separately supplied. | **Fail** before checks; artifact `test-results/local-gates/M07-20260913T072946Z/evidence.json` relative to the clean worktree; reviewer `LUNA MAX QA`; resolved by installing pinned Node `22.19.0` and rerunning unchanged as `M07-E20`. |

#### Historical M07 integrated release closure receipt (`M07-E18`)

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

#### M07 final clean-checkpoint release receipt (`M07-E20`)

- **Status:** `Completed` for the declared M07 release-gate scope; **Pass**.
- **Owner/phase:** independent `LUNA MAX QA` release gate, recorded by `LUNA MAX docs`.
- **Dependencies verified:** the new `R-M07-6`/`R-M07-7` precondition failures and resolutions
  remain visible above; `M07-E18`/`M07-E19` remain historical evidence; `EXP-M07` remains a
  separate export/checkpoint record.
- **Change summary:** this receipt records the supplied clean detached-checkpoint gate only. It
  does not change implementation, configuration, tests, export, or Git history.

| Evidence ID / task | Requirement/check | Environment, UTC time, commit | Result, artifact, reviewer, limitation |
| --- | --- | --- | --- |
| `M07-E20` / `M07` | Exact command `TASK_ID=M07 PERFORMANCE_REVIEWER='LUNA MAX QA' ./scripts/local-gate.sh release`; `417` passed, `4` deselected, `89.65%` coverage; browser `62` passed/`2` expected performance skips; official MCP; backup CLI `17` passed; package `122,814` bytes; build `634.16 ms`; `17` executable performance rows **Pass**; static `97,893` bytes; ARM64 performance **Unavailable**. | Native x86_64 WSL2; Python `3.11.15`; Node `22.19.0`; `2026-09-13T07:31:01Z`–`2026-09-13T07:38:21Z`; clean detached commit `c55064da92dcc8da591494c1c88cf040039e2437`. | **Pass**; artifact `test-results/local-gates/M07-20260913T073101Z/` relative to the clean worktree; reviewer `LUNA MAX QA`. The clean state applies only to the detached checkpoint; no clean state is inferred for the concurrent main worktree. |

- **Repair/history:** the dirty-main clean-tree failure and first clean-worktree missing-Node
  failure remain visible as `R-M07-6` and `R-M07-7`; neither is erased by `M07-E20`.
- **Limitations:** the two expected browser performance skips remain skips; ARM64 performance is
  **Unavailable**; no native/physical ARM64 performance result is claimed. This receipt does not
  itself create export, push, exact remote verification, or a new notification.
- **Export/Git:** the detached commit and relative local artifact identify this gate only. No
  export, secret review, push, exact remote-main verification, or notification result is claimed
  from `M07-E20`; the separate `EXP-M07` record remains unchanged.

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
  runs, `R-M09-4`/`R-M09-5`, or their separate missing metadata; `M07-E18`, `M07-E19`, and
  `M07-E20` remain distinct evidence.
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

## Historical final independent Astra gate (preserved application receipts)

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

Each row records task ID `ASTRA-FINAL`, check/command, environment, UTC timestamp, commit, result, artifact/link, limitation, and reviewer, with explicit evidence for all five evaluation dimensions. Any gap or non-pass creates `R-ASTRA-<n>`. Astra evaluates and suggests only; only `SOL HIGH` build agents implement `R-ASTRA-<n>` UI changes. The repair receives the normal up-to-six-lane build handoff, the mandatory pre-QA Ponytail review, and independent QA/docs gates, then Astra re-evaluates the failed row and affected matrix. If execution evidence shows a tooling, skill, or MCP gap caused poor output, a narrowly scoped `R-ASTRA-<n>` may repair and validate that gap before acceptance; it may not expand scope without a new evidenced requirement. Repeat until the independent record explicitly says **Accepted**. Only then does `EXP-M08` checkpoint the reviewed walkthrough. After all roadmap and Astra repairs, a final pre-`EXP-FINAL` deep learning synthesis must analyze sanitized chat/run evidence, use `skill-maintenance` only for justified reusable Stock Probability development skills, validate and index those skills, and log observations. Only after that record is complete may `EXP-FINAL` sanitize the full chat/export, complete secret review, commit, push, and verify the exact remote revision. `EXP-M08` and `EXP-FINAL` cannot be green before the stated prerequisites; `EXP-M07` is the earlier M07 checkpoint. This paragraph is retained pre-acceptance workflow history; the accepted `ASTRA-FINAL`, completed `EXP-M08`, current post-repair `EXP-FINAL` checkpoint, and immutable earlier `NOTIFY-FINAL` receipt are recorded below.

### Earlier accepted `ASTRA-FINAL` acceptance and `EXP-M08` checkpoint

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

- **Historical pre-notification status (retained):** via `skill-maintenance`, the final learning
  synthesis was **In progress** and `EXP-FINAL` was **Pending** for synthesis completion and its
  separate full-session export, secret review, commit, push, and exact remote verification. The
  completed `EXP-M08` checkpoint did not close `EXP-FINAL` or convert unavailable physical-evidence
  fields into passes at that earlier point.

#### Earlier accepted `EXP-FINAL` checkpoint and `NOTIFY-FINAL` operational receipt (immutable history)

- **`EXP-FINAL` status:** **Completed**; the final acceptance receipt identifies the accepted
  checkpoint as `b96cb6954ecf6e03b3bcdb0ad52af38ed7eae4cb`. This
  notification record does not change that accepted result or infer unprovided final-export
  inventory, command, session, environment, or exact remote-verification metadata.
- **`NOTIFY-FINAL` status:** **Completed for its operational scope only**; this optional item is
  not a milestone or acceptance ID and cannot satisfy or repair a missing gate.
- **Owner/phase:** optional post-`EXP-FINAL` delivery; reviewer/coordinator `OpenCode
  gpt-5.6-sol`.
- **Dependencies verified:** accepted `EXP-FINAL` checkpoint above. The delivery was sent only to
  the user-supplied out-of-band webhook; its endpoint and credentials are intentionally absent.
- **Change summary:** sent a bounded minimal non-secret receipt containing the accepted result,
  checkpoint, and evidence summary. No repository, export, artifact, log, code, configuration,
  skill, or Git-history content was changed by the delivery.

| Evidence ID | Requirement/check | Environment, UTC time, commit | Result, artifact, reviewer, limitation |
| --- | --- | --- | --- |
| `NOTIFY-FINAL-E1` | Bounded delivery to the user-supplied out-of-band webhook; HTTP `204` success with an empty response body; no retry needed. | Delivery environment was user-supplied and out-of-band; exact network environment and exact UTC were not supplied, only a window around `2026-09-13T01:45Z`; accepted checkpoint `b96cb6954ecf6e03b3bcdb0ad52af38ed7eae4cb`. | **Pass**; artifact: supplied delivery receipt, with no tracked notification artifact; reviewer/coordinator `OpenCode gpt-5.6-sol`. |
| `NOTIFY-FINAL-E2` | Minimal non-secret payload and credential handling; endpoint, token, and credential-bearing payload were not written to the repository, export, artifacts, or logs; sanitized export shows zero webhook-pattern matches. | Sanitized export evidence; exact export revision, command, environment, and scan UTC were not supplied in this notification receipt and are not inferred. | **Pass as supplied receipt evidence**; artifact: sanitized export reference, exact path/revision not supplied; reviewer/coordinator `OpenCode gpt-5.6-sol`. |
| `NOTIFY-FINAL-E3` | Notification did not change the accepted `EXP-FINAL` result. | Accepted `EXP-FINAL` checkpoint `b96cb6954ecf6e03b3bcdb0ad52af38ed7eae4cb`; delivery window around `2026-09-13T01:45Z`. | **Pass**; no repair or retry; artifact: accepted checkpoint and supplied delivery receipt; reviewer/coordinator `OpenCode gpt-5.6-sol`. |

- **Repair history:** None; no retry was needed. The notification does not create an `R-M##-<n>`
  repair and does not substitute for any failed, skipped, unavailable, or limited acceptance row.
- **Limitations:** Exact delivery UTC, network environment, endpoint identity, token, verbatim
  payload, separate notification artifact, and a new remote-verification result are unavailable
  by design or were not supplied. Existing screen-reader, physical-mobile, native/physical ARM64
  performance, provider, and other historical limitations remain unchanged.
- **Export/Git/reviewer:** `EXP-FINAL` remains the accepted checkpoint above; the notification
  did not overwrite `SESSION-EXPORT.md`, create a Git checkpoint, commit, push, or remote result.
  Reviewer/coordinator: `OpenCode gpt-5.6-sol`.

## Historical final operational item: selective Ingenium pipeline adoption (not current workflow)

- **Status:** `In progress`; the broader implementation/adoption follow-up remains open. The
  `R-ASTRA-72` rename/restart-validation scope is independently verified, but no broader gate
  effect is inferred. This is the ASTRA-plan operational follow-up, not a new milestone or
  acceptance ID.
- **Commit evidence:** the committed adoption/profile change set is in ancestor commit
  `8084a134ab4950f36446de3af622349cd23423ae` (`Build dark mode and news`), including the
  ASTRA profile's `variant: max`; the current checkpoint is its descendant
  `779aa749d2f85849427212d890ee6918987492b7`. That historical commit evidence did not replace
  the required parent restart or independent post-restart validation; `R-ASTRA-72` supplies
  that validation for the renamed `Orchestrator` entry only.
- **Adoption state (rename scope validated):** `Orchestrator` is the inline
  primary with the six-agent count option and `subagent_depth: 1`; `luna-docs` has the
  `docs/**` permission; the recorded `.gitignore` additions are present; and the two-skill
  validator catalog contains `documentation` plus the new `skill-maintenance` skill.
- **Plan/controls:** Retain six-agent orchestration, independent QA/docs order, the read-only
  Ponytail boundary, commit/export gates, and the stock Playwright MCP entry with its
  loopback allowlists. `R-ASTRA-72` supplies independent post-restart validation for the
  `Orchestrator` rename only; unvalidated profile/catalog/ignore changes still require their
  own restart validation before affecting a gate. This documentation reconciliation did not
  edit `opencode.json`, `.gitignore`, profiles, local gates, or skills.
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

## Current post-acceptance work items

These are current follow-on requirements, not retroactive edits to the historical
`ASTRA-FINAL`, `EXP-M08`, `EXP-FINAL`, or `NOTIFY-FINAL` receipts. The visual and container items
below are now closed for their declared scopes by the supplied evidence; they do not create a
new clean release/export/remote checkpoint.

### `R-ASTRA-22` visual parity and no-known-visual-bug acceptance

- **Status:** `Completed` for the declared visual-repair scope.
- **Owner/phase:** `SOL HIGH` owns the repair; `LUNA MAX QA` owns independent human-like
  Playwright QA; `ASTRA-FINAL` owns the screenshot-backed visual reevaluation; `LUNA MAX docs`
  records the roadmap state.
- **Dependencies verified:** The prior `ASTRA-FINAL` acceptance and its bound `EXP-M08`,
  `EXP-FINAL`, and `NOTIFY-FINAL` checkpoints remain historical evidence; the supplied
  independent QA and post-repair `ASTRA-FINAL` receipt close this declared visual scope.
- **Change summary:** Dark mode must reach visual-quality parity with light mode across page
  background/surfaces, typography and hierarchy, density/spacing, controls, charts, tables, and
  every reachable state. The reported theme-dropdown, background, density, and mobile-metadata
  defects invalidate the prior visual acceptance for this current requirement. Closure requires
  human-like Playwright use of every reachable control and state at `320`, `390`, `768`, `1280`,
  `1440`, and `1920` CSS-pixel widths in Light, Dark, and System modes, with keyboard operation,
  forced-colors, and reduced-motion coverage, plus screenshot-backed `ASTRA-FINAL` acceptance.
  The supplied result records no reproducible blockers. `R-ASTRA-22` is closed only for the
  supplied declared scope; implementation presence alone is not the acceptance basis.

| Evidence ID | Requirement/check | Environment, UTC time, commit | Result, artifact, reviewer, limitation |
| --- | --- | --- | --- |
| `R-ASTRA-22-E1` | Independent QA totals: `425` passed/`4` deselected/`89.65%`; provider `32` passed; browser `62` passed/`2` expected performance skips plus `31` at `1280px`; static `97,893`/`98,304` bytes; persistence `55 + 35 + 4` passed. | Native x86_64 Linux; dirty `HEAD` `91ba52eca35fcfc13bd0d9996beb947d65d69d09`; exact command and UTC not supplied. | **Pass** as supplied independent QA evidence; artifacts `test-results/astra-final-live/` and `test-results/astra-final-repair/`; reviewer `LUNA MAX QA` as supplied. |
| `R-ASTRA-22-E2` | `17` executable performance rows passed; ARM64 performance remained unavailable. | Native x86_64 Linux; dirty `HEAD` above; exact command and UTC not supplied. | **Pass** for native-x86 executable rows; ARM64 performance **Unavailable**; artifact `test-results/astra-final-repair/`; reviewer `LUNA MAX QA`. |
| `R-ASTRA-22-E3` | Two container contract tests, supplied amd64 image digest/size, and real ACDC/SPY flows. | Native x86_64 QA context; dirty `HEAD` above; exact container command and UTC not supplied. | **Pass** for supplied container/flow scope; digest `sha256:0dcb3f5ec77d31a5e8f57ef6e5d57b7144b973c3acb73ac360ffe01494735da`, size `169,699,932` bytes; exact image artifact filename not supplied. ACDC news relevance and exact-symbol provider availability remain unproven. |
| `R-ASTRA-24-E1` | SPY lookup classification. | Native x86_64 browser/QA context; dirty `HEAD` above; exact command and UTC not supplied. | **Pass**; SPY classified as ETF; artifact `test-results/astra-final-live/`; no exact-symbol provider/news claim. |
| `R-ASTRA-25-E1` | Heading order and heading-order axe checks. | Native x86_64, pinned Playwright Chromium; successful rerun `2026-09-13T06:57:42Z`–`06:58:01Z`; dirty `HEAD` above. | **Pass**; artifact `test-results/astra-final-repair/r-astra-27-news-evidence-rerun.json`; the initial render attempt failed with exit `1` and remains visible. |
| `R-ASTRA-26-E1` | Desktop action target minimum. | Native x86_64 browser/QA context; dirty `HEAD` above; exact command and UTC not supplied. | **Pass**; supplied desktop actions met `44px`; artifact `test-results/astra-final-live/manifest.json`; physical mobile and true zoom unavailable. |
| `R-ASTRA-27-E1` | Selector alignment, static-size budget, actual isolated fixture news, axe and heading-order checks. | Native x86_64, pinned Playwright Chromium; successful actual run `2026-09-13T07:00:18Z`–`07:00:36Z`; dirty `HEAD` above. | **Pass**; artifacts `test-results/astra-final-repair/static-size.json`, `r-astra-27-news-evidence-actual.json`, and `diff-check-metadata.txt`; static `97,893`/`98,304` bytes. |
| `ASTRA-FINAL-POST-E1` | Post-repair ASTRA disposition. | Session `ses_f6683138affe6t8S6Z0G66YJDc`; dirty `HEAD` above; exact command, UTC, environment, and separate artifact not supplied. | **Accepted** with no reproducible blockers; not a new clean release/export/push checkpoint; reviewer identity not separately supplied. |

- **Repair/history:** The prior ASTRA findings and repair receipts remain visible and are not
  rewritten. The initial `R-ASTRA-27` render failure is retained; the deterministic and actual
  isolated-fixture reruns are the closure evidence. The supplied Ponytail result was `Lean
  already. Ship.` and is overengineering-only.
- **Limitations:** Physical mobile, actual screen-reader, true zoom, and native/physical ARM64
  performance remain **Unavailable**. The live receipt's ACDC/SPY flows do not prove news
  relevance or exact-symbol provider availability.
- **Export/Git/reviewer:** No new export, secret review, commit, push, exact remote verification,
  or notification was performed for this item. The current worktree is dirty at `HEAD`
  `91ba52eca35fcfc13bd0d9996beb947d65d69d09`; reviewer `LUNA MAX docs` recorded the supplied
  evidence, and the exact independent QA/Astra reviewer metadata not supplied remains unavailable.

### `R-M07-5` minimal local production containerization

- **Status:** `Completed` for the declared container scope.
- **Owner/phase:** `SOL HIGH-C` owns the implementation/configuration handoff; `LUNA MAX QA`
  independently verifies the container boundary; `LUNA MAX docs` records the roadmap state.
- **Dependencies verified:** The declared M05 backup/restore scope and M06 local-operation
  requirements remain the relevant contract context. The supplied Dockerfile/Compose inspection,
  two container contract tests, image receipt, and independent QA result are recorded below.
- **Change summary:** The verified path is one Compose `app` service built from the pinned,
  multi-stage `Dockerfile`. Compose publishes `127.0.0.1:${STOCK_PROBS_PORT:-8000}:8000`, mounts
  `stock-probs-data:/data`, defaults the provider to Yahoo, and applies read-only, tmpfs,
  capability, privilege, PID, memory, CPU, log, restart, and stop-grace bounds. The image runs as
  UID/GID `10001`, carries the `/api/v1/health` healthcheck, and serves on the container listener
  required by the loopback publication. Native `.dev-venv/` development remains separate. No
  hosted pipeline, service split, or broader deployment platform is authorized by this item.

| Evidence ID | Requirement/check | Environment, UTC time, commit | Result, artifact, reviewer, limitation |
| --- | --- | --- | --- |
| `R-M07-5-E1` | Compose-only lifecycle and one-service local production path. | Native amd64 container QA context; dirty `HEAD` `91ba52eca35fcfc13bd0d9996beb947d65d69d09`; exact command and UTC not supplied. | **Pass** for two supplied container contract tests; artifact: supplied container QA receipt; reviewer `LUNA MAX QA`. |
| `R-M07-5-E2` | Published application binding is loopback-only. | Verified `compose.yaml`; dirty `HEAD` above; exact inspection command and UTC not supplied. | **Pass**; artifact: `compose.yaml`; `127.0.0.1:${STOCK_PROBS_PORT:-8000}:8000`. |
| `R-M07-5-E3` | The application process runs as a non-root user. | Verified `Dockerfile`; dirty `HEAD` above; exact inspection command and UTC not supplied. | **Pass**; artifact: `Dockerfile`; runtime `USER 10001:10001`. |
| `R-M07-5-E4` | A healthcheck verifies local service health. | Verified `Dockerfile`; dirty `HEAD` above; exact inspection command and UTC not supplied. | **Pass**; artifact: `Dockerfile`; healthcheck requests `http://127.0.0.1:8000/api/v1/health`. |
| `R-M07-5-E5` | SQLite, WAL state, trust key, and backups persist on the declared volume. | Verified `compose.yaml`; dirty `HEAD` above; exact inspection command and UTC not supplied. | **Pass** for the declared mount behavior; artifact: `compose.yaml`; `stock-probs-data:/data`. Lifecycle recheck metadata were not separately supplied. |
| `R-M07-5-E6` | CPU/memory/process and log bounds are explicit. | Verified `compose.yaml`; dirty `HEAD` above; exact inspection command and UTC not supplied. | **Pass** for declared bounds: `128` PIDs, `768m`, `1.0` CPU, and `10m` × `3` JSON logs; artifact: `compose.yaml`. |
| `R-M07-5-E7` | Yahoo is the Compose provider default; fixtures remain an explicit setting. | Verified `compose.yaml`; dirty `HEAD` above; exact inspection command and UTC not supplied. | **Pass** for the declared environment expression `${STOCK_PROBS_PROVIDER:-yahoo}`; artifact: `compose.yaml`; real ACDC/SPY flows do not prove news relevance or exact-symbol provider availability. |
| `R-M07-5-E8` | Native local development remains distinct from Compose. | Verified `Dockerfile`, `compose.yaml`, and [getting started](docs/operations/getting-started.md); dirty `HEAD` above; exact inspection command and UTC not supplied. | **Pass** for documented distinction; native `.dev-venv/` path remains; no native ARM64 performance claim. |

- **Repair/history:** The supplied independent QA closed the declared container contract scope;
  this is not a new M07 release or export checkpoint. No separate `/ponytail-review` receipt was
  supplied for this follow-on item.
- **Limitations:** The amd64 image receipt reports digest
  `sha256:0dcb3f5ec77d31a5e8f57ef6e5d57b7144b973c3acb73ac360ffe01494735da` and size
  `169,699,932` bytes. Native ARM64 performance, physical mobile, actual screen-reader, and true
  zoom evidence remain unavailable. The exact container command, UTC, artifact filename, and
  clean release metadata were not supplied.
- **Export/Git/reviewer:** No new export, secret review, commit, push, or exact remote
  verification was performed. Current roadmap reviewer: `LUNA MAX docs`; independent QA was
  supplied as `LUNA MAX QA` without a separate session/UTC receipt.

### Current post-repair `EXP-FINAL` checkpoint

- **Task ID/status:** `EXP-FINAL` — **Completed** for the same declared final acceptance scope;
  this is a post-repair export checkpoint, not a new milestone or acceptance scope.
- **Owner/phase:** final export/checkpoint gate; reviewer `LUNA MAX QA`.
- **Dependencies verified:** implementation checkpoint
  `c55064da92dcc8da591494c1c88cf040039e2437` (`M07-E20`), release-receipt documentation
  checkpoint `830030ab5322e5c7aaaf12e6fde3f6c0ea9b2a12`, and the accepted `ASTRA-FINAL`/
  `EXP-M08` records. Export commit parent supplied as `830030a`.

| Evidence ID | Requirement/check | Environment, UTC time, commit | Result, artifact, reviewer, limitation |
| --- | --- | --- | --- |
| `EXP-FINAL-E1` | Sanitized export audit: session `ses_f71ec0499ffeokWj4h6tVwyYk1`; `572` messages, `3,155` parts, `952` tool parts, `350` completed task outputs, `2,552,320` bytes, `90,476` lines, SHA-256 `cf1b85d07eefc9ff6436ad692ee826cb394be8f39af34caf6b1ff58f1f8517ff`, `14,895` redaction markers. | Native x86_64; OpenCode `1.18.30`; audit UTC `2026-09-13T12:28:44.223816Z`; commit `10b5de4a1842baf43e847f21f75154966e44b9c0`; exact export-generation UTC unavailable. | **Pass**; artifact: sanitized `SESSION-EXPORT.md` audit; reviewer `LUNA MAX QA`. |
| `EXP-FINAL-E2` | Ordered message-ID hash `ecc9a2be4ebf82e92e459a979cde2ceb93517c61d2ec95708a9f370fff255568`, ordered part-ID hash `0061d16fa7de0a60d8cb159db0d11474f291247708925bc6cb4b65c643da33be`, exact watermark, and strictly trailing later-database delta. | Same audit context; later database delta was `1` message/`5` parts, all strictly trailing. | **Pass**; artifact: export audit; reviewer `LUNA MAX QA`. |
| `EXP-FINAL-E3` | Strict allowlist redaction checked `38,686` strings with zero violations and zero webhook/private-key/AWS/GitHub/Bearer/credential-URL matches. | Same audit context; exact scan command was not supplied and is not inferred. | **Pass**; artifact: sanitized export audit; reviewer `LUNA MAX QA`. |
| `EXP-FINAL-E4` | Built-in sanitized OpenCode exporter attempt. | Native x86_64/OpenCode `1.18.30`; only `64KiB` of invalid/incomplete JSON; no corrupt output accepted. | **Fail**; invalid/incomplete output was not accepted; no separate repair ID was supplied. |
| `EXP-FINAL-E5` | Built-in unsanitized OpenCode exporter attempt. | Native x86_64/OpenCode `1.18.30`; only `64KiB` of invalid/incomplete JSON; not used as the accepted export. | **Fail**; invalid/incomplete output was not accepted; no separate repair ID was supplied. |
| `EXP-FINAL-E6` | Verified equivalent path using a read-only SQLite transaction and strict allowlist redaction. | Native x86_64; OpenCode `1.18.30`; audit UTC `2026-09-13T12:28:44.223816Z`; export-generation UTC unavailable; commit `10b5de4a1842baf43e847f21f75154966e44b9c0`. | **Pass**; artifact: sanitized export audit; reviewer `LUNA MAX QA`; supplied closure of E4/E5. |
| `EXP-FINAL-E7` | Commit message/parent, push, and exact remote revision. | Commit `10b5de4a1842baf43e847f21f75154966e44b9c0`; parent `830030a`; message `Checkpoint final repair session`; exact `git push origin main` passed; exact `git ls-remote origin refs/heads/main` matched; no CI. | **Pass**; artifact: Git checkpoint/remote receipt; reviewer `LUNA MAX QA`. |

- **Repair/history:** `EXP-FINAL-E4` and `EXP-FINAL-E5` preserve both failed exporter attempts;
  `EXP-FINAL-E6` records the verified equivalent closure. The earlier accepted checkpoint
  `b96cb6954ecf6e03b3bcdb0ad52af38ed7eae4cb` and `NOTIFY-FINAL` at dirty context
  `91ba52eca35fcfc13bd0d9996beb947d65d69d09` remain immutable history.
- **Limitations:** Exact export-generation UTC remains **Unavailable**. Existing physical-mobile,
  actual screen-reader, true-zoom, and native/physical ARM64-performance limitations remain
  unchanged. No new acceptance scope or notification is claimed.
- **Change boundary:** This documentation update did not edit `SESSION-EXPORT.md`, implementation,
  configuration, skills, tests, Git index/history, branches, tags, or remotes; concurrent
  `.opencode/**`, validator, and documentation-test changes were preserved.

## Future/post-MVP design item: scheduled forecast report email

- **Status:** Future design only; automated scheduled forecast jobs and email delivery are
  **not implemented** and **not accepted**. No current milestone, `EXP-*`, `ASTRA-FINAL`,
  `EXP-FINAL`, or `NOTIFY-FINAL` status changes. The historical M09 exclusion of a background
  scheduler and notification feed remains unchanged; this is a separately requested future
  scope item and has no current task or acceptance ID.
- **Purpose:** A local scheduled job may run a forecast for an explicitly selected set of
  symbols/assets, generate a report, and deliver that report as an email attachment. Before
  implementation, define local scheduler semantics, the authoritative timezone, daylight-saving
  behavior, missed-run policy, bounded cadence, and the maximum selected symbols/assets per run.
- **Design/acceptance considerations:**
  - Execute against the real provider path, with provider freshness, timeout, stale/failure
    handling, and unavailable-provider results shown honestly; fixtures alone cannot accept it.
  - Link every scheduled run immutably to its schedule, normalized symbol/asset selection,
    forecast inputs/results, report revision/hash, attempt history, and delivery outcome.
  - Decide and document an explicit attachment format (CSV, PDF, or another bounded format),
    including its schema, filenames, encoding, size limit, and a plain-text email alternative.
  - Keep SMTP or other mail-provider configuration and credentials outside the repository,
    logs, and exports; retain only sanitized configuration identity and delivery evidence.
  - Define bounded retries, stable run/delivery idempotency keys, duplicate suppression, and an
    honest failed-delivery state that cannot be mistaken for a successful forecast or email.
  - Preserve loopback/local security, least-privilege network behavior, bounded runtime,
    symbols, report bytes, mailbox attempts, temporary files, and resource consumption.
  - Acceptance must test timezone/scheduling and missed runs, real-provider execution, report
    generation, attachment/plain-text delivery, delivery failure, retry/idempotency,
    duplicate suppression, immutable audit linkage, and backup/restore behavior without losing
    run history or falsely marking a delivery successful.

## Roadmap Completion Record

Every milestone, repair, export, and final review uses these exact fields:

- **Task ID:** exact `M00`–`M09`, `R-M##-<n>`, `EXP-M00`–`EXP-M09`, `ASTRA-FINAL`, `R-ASTRA-<n>`, or `EXP-FINAL`; `NOTIFY-FINAL` is a separate optional operational record, not a milestone or acceptance ID.
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
- The final deep chat/run learning synthesis is complete before `EXP-FINAL`; only justified reusable
  Stock Probability skills are created or changed, and they are validated and indexed. The current
  approved governance set contains seven directory-based definitions, with no Ponytail skill or
  package pin. Documentation validation, metadata/index/frontmatter checks, and coverage checks
  are separate fail-closed static gates; none establishes native loader/discovery acceptance.
  Historical
  post-restart receipts remain evidence only and do not create current profile, provider, or
  milestone acceptance.
- Dark mode and selected-instrument news are contract requirements owned by M09; options trading and public hosting are out of scope for this local app.

### `R-M00-2-E23` and `R-M00-2-E24` current documentation checks

| Evidence ID | Requirement/check | Environment, UTC time, commit | Result, artifact, reviewer, limitation |
| --- | --- | --- | --- |
| `R-M00-2-E23` | Exact `.dev-venv/bin/python scripts/validate_docs.py` execution after the `ASTRA-FINAL` findings/repair update. | Native x86_64 Linux; dirty `HEAD` `cf099754a5c3e4a05f0e785c0d65ff06f96c4d63`; UTC was not captured; execution was denied by the tool permission boundary. | **Unavailable**; no validator pass is inferred; artifact: none; reviewer `LUNA MAX docs`; rerun remains required when execution is available. |
| `R-M00-2-E24` | Exact `git diff --check -- README.md AGENTS.md MVP-PLAN.md MVP-ROADMAP.md` execution after the same update. | Native x86_64 Linux; dirty `HEAD` `cf099754a5c3e4a05f0e785c0d65ff06f96c4d63`; UTC was not captured. | **Pass**; artifact: current four-document diff; reviewer `LUNA MAX docs`; no code/configuration/skill/export/commit/push/Git-history mutation was performed. |
| `R-M00-2-E25` | Exact `.dev-venv/bin/python scripts/validate_docs.py` execution after the accepted `ASTRA-FINAL`/completed `EXP-M08` update. | Native x86_64 Linux; dirty `HEAD` `7cf1ca8395b94c2e14e5b02ddf160f3f938091d`; UTC was not captured; execution was denied by the tool permission boundary. | **Unavailable**; no current validator pass is inferred; artifact: none; reviewer `LUNA MAX docs`; rerun remains required when execution is available. |
| `R-M00-2-E26` | Exact `git diff --check -- README.md AGENTS.md MVP-PLAN.md MVP-ROADMAP.md` execution after the accepted `ASTRA-FINAL`/completed `EXP-M08` update. | Native x86_64 Linux; dirty `HEAD` `7cf1ca8395b94c2e14e5b02ddf160f3f938091d`; UTC was not captured. | **Pass**; artifact: current four-document diff; reviewer `LUNA MAX docs`; no code/configuration/skill/export/commit/push/Git-history mutation was performed by this documentation update. |
| `R-M00-2-E27` | Exact `.dev-venv/bin/python scripts/validate_docs.py` execution after this accepted `EXP-FINAL`/`NOTIFY-FINAL` root-documentation update. | Native x86_64 Linux; dirty `HEAD` `b96cb6954ecf6e03b3bcdb0ad52af38ed7eae4cb`; UTC was not captured; execution was denied by the tool permission boundary. | **Unavailable**; no current validator pass is inferred; artifact: none; reviewer `LUNA MAX docs`; rerun remains required when execution is available. |
| `R-M00-2-E28` | Exact `git diff --check -- README.md AGENTS.md MVP-PLAN.md MVP-ROADMAP.md` execution after this accepted `EXP-FINAL`/`NOTIFY-FINAL` root-documentation update. | Native x86_64 Linux; dirty `HEAD` `b96cb6954ecf6e03b3bcdb0ad52af38ed7eae4cb`; UTC was not captured by the command tool. | **Pass**; artifact: current four-document diff; reviewer `LUNA MAX docs`; no code/configuration/skill/export/commit/push/Git-history mutation was performed by this documentation update. |
| `R-M00-2-E29` | Documentation self-review of the future/post-MVP scheduled forecast report email item: explicit non-implementation/non-acceptance, required design considerations, and preserved M09 historical exclusion. | Native x86_64 Linux; dirty `HEAD` `91ba52eca35fcfc13bd0d9996beb947d65d69d09`; UTC was not captured. | **Pass** as documentation content only; artifact: `MVP-ROADMAP.md`; reviewer `LUNA MAX docs`; no milestone, `EXP-*`, `ASTRA-FINAL`, `EXP-FINAL`, or `NOTIFY-FINAL` status changed. |
| `R-M00-2-E30` | Exact `.dev-venv/bin/python scripts/validate_docs.py` execution after this future/post-MVP roadmap update. | Native x86_64 Linux; dirty `HEAD` `91ba52eca35fcfc13bd0d9996beb947d65d69d09`; UTC was not captured; execution was denied by the tool permission boundary. | **Unavailable**; no validator pass is inferred; artifact: none; reviewer `LUNA MAX docs`; rerun remains required when execution is available. |
| `R-M00-2-E31` | Exact `git diff --check -- README.md AGENTS.md MVP-PLAN.md MVP-ROADMAP.md` execution after this future/post-MVP roadmap update. | Native x86_64 Linux; dirty `HEAD` `91ba52eca35fcfc13bd0d9996beb947d65d69d09`; UTC was not captured by the command tool. | **Pass**; artifact: current four-document diff; reviewer `LUNA MAX docs`; no code/configuration/skill/export/commit/push/Git-history mutation was performed by this documentation update. |
| `R-M00-2-E32` | Documentation self-review of current `R-ASTRA-22` visual repair requirements, `R-M07-5` containerization work, explicit non-completion, and preservation of the scheduled-email future item and historical receipts. | Native x86_64 Linux; dirty `HEAD` `91ba52eca35fcfc13bd0d9996beb947d65d69d09`; UTC was not captured. | **Pass** as documentation content only; artifact: `MVP-ROADMAP.md`; reviewer `LUNA MAX docs`; no implementation, QA, export, commit, push, or Git-history mutation was performed. |
| `R-M00-2-E33` | Exact `.dev-venv/bin/python scripts/validate_docs.py` execution after this current-work-item roadmap update. | Native x86_64 Linux; dirty `HEAD` `91ba52eca35fcfc13bd0d9996beb947d65d69d09`; UTC was not captured; execution was denied by the tool permission boundary. | **Unavailable**; no validator pass is inferred; artifact: none; reviewer `LUNA MAX docs`; rerun remains required when execution is available. |
| `R-M00-2-E34` | Exact `git diff --check -- MVP-ROADMAP.md` execution after this current-work-item roadmap update. | Native x86_64 Linux; dirty `HEAD` `91ba52eca35fcfc13bd0d9996beb947d65d69d09`; UTC was not captured by the command tool. | **Pass**; artifact: current `MVP-ROADMAP.md` diff; reviewer `LUNA MAX docs`; no code/configuration/skill/export/commit/push/Git-history mutation was performed. |
| `R-M00-2-E35` | Exact `.dev-venv/bin/python scripts/validate_docs.py` attempt after the final current-doc wording review. | Native x86_64 Linux; dirty `HEAD` `91ba52eca35fcfc13bd0d9996beb947d65d69d09`; UTC was not captured; the tool permission boundary denied execution. | **Unavailable**; no validator pass is inferred; artifact: none; reviewer `LUNA MAX docs`; rerun remains required when execution is available. |
| `R-M00-2-E36` | Exact `.dev-venv/bin/python -m pytest tests/test_docs_validation.py` attempt after the final current-doc wording review. | Native x86_64 Linux; dirty `HEAD` `91ba52eca35fcfc13bd0d9996beb947d65d69d09`; UTC was not captured; the tool permission boundary denied execution. | **Unavailable**; no documentation-test pass is inferred; artifact: none; reviewer `LUNA MAX docs`; rerun remains required when execution is available. |
| `R-M00-2-E37` | Exact `git diff --check -- README.md AGENTS.md MVP-PLAN.md MVP-ROADMAP.md docs` check after the final current-doc wording review. | Native x86_64 Linux; dirty `HEAD` `91ba52eca35fcfc13bd0d9996beb947d65d69d09`; UTC was not captured by the command tool. | **Pass**; artifact: current owned-document diff; reviewer `LUNA MAX docs`; no code/configuration/skill/export/commit/push/Git-history mutation was performed. |
| `R-M00-2-E38` | Direct coordinator rerun of `.dev-venv/bin/python -m pytest tests/test_docs_validation.py` before the link repair. | Native x86_64 Linux; dirty `HEAD` `91ba52eca35fcfc13bd0d9996beb947d65d69d09`; exact UTC and independent session were not supplied. | **Fail**; `43` setup errors and `6` tests passed because the isolated fixture omitted root `Dockerfile`/`compose.yaml` targets for the new Markdown links. Artifact: supplied coordinator test result; repair: convert both `compose.yaml` links to inline code references; reviewer `LUNA MAX docs` recording the supplied failure. |
| `R-M00-2-E39` | Exact `.dev-venv/bin/python scripts/validate_docs.py` rerun after converting root deployment-file links to inline code. | Native x86_64 Linux; dirty `HEAD` `91ba52eca35fcfc13bd0d9996beb947d65d69d09`; UTC was not captured; the tool permission boundary denied execution. | **Unavailable**; no post-repair validator pass is inferred; artifact: none; reviewer `LUNA MAX docs`; rerun remains required when execution is available. |
| `R-M00-2-E40` | Exact `.dev-venv/bin/python -m pytest tests/test_docs_validation.py` rerun after converting root deployment-file links to inline code. | Native x86_64 Linux; dirty `HEAD` `91ba52eca35fcfc13bd0d9996beb947d65d69d09`; UTC was not captured; the tool permission boundary denied execution. | **Unavailable**; no post-repair documentation-test pass is inferred; artifact: none; reviewer `LUNA MAX docs`; rerun remains required when execution is available. |
| `R-M00-2-E41` | Exact `git diff --check -- README.md AGENTS.md MVP-PLAN.md MVP-ROADMAP.md docs` rerun after the link repair. | Native x86_64 Linux; dirty `HEAD` `91ba52eca35fcfc13bd0d9996beb947d65d69d09`; UTC was not captured by the command tool. | **Pass**; artifact: current owned-document diff; reviewer `LUNA MAX docs`; no code/configuration/skill/export/commit/push/Git-history mutation was performed. |
| `R-M00-2-E42` | Final documentation self-review and scoped `git diff --name-only -- README.md AGENTS.md MVP-PLAN.md MVP-ROADMAP.md docs`; exact output: `AGENTS.md`, `MVP-PLAN.md`, `MVP-ROADMAP.md`, `README.md`. Concurrent `.opencode/**`, `scripts/validate_docs.py`, and `tests/test_docs_validation.py` changes were preserved. | Native x86_64 Linux; dirty `HEAD` `10b5de4a1842baf43e847f21f75154966e44b9c0`; UTC was not captured. | **Pass** for documentation ownership/scope; artifact: current worktree and scoped name-only diff; reviewer `LUNA MAX docs`; no concurrent implementation, configuration, validator, test, index, branch, tag, remote, or export content was edited. |
| `R-M00-2-E43` | Exact `.dev-venv/bin/python scripts/validate_docs.py`. | Native x86_64 Linux; dirty `HEAD` `10b5de4a1842baf43e847f21f75154966e44b9c0`; UTC was not captured by the command tool. | **Pass**; output: `Documentation validation passed: 9 categories, 13 topics, 7 project skills.` Artifact: validator output; reviewer `LUNA MAX docs`. |
| `R-M00-2-E44` | Exact `.dev-venv/bin/python -m pytest tests/test_docs_validation.py` attempt. | Native x86_64 Linux; dirty `HEAD` `10b5de4a1842baf43e847f21f75154966e44b9c0`; UTC was not captured; execution was denied by the tool permission boundary. | **Unavailable**; no documentation-test pass is inferred from E44; artifact: none; reviewer `LUNA MAX docs`; the fresh `R-M00-2-E46` receipt below closes the rerun. |
| `R-M00-2-E45` | Exact `git diff --check -- README.md AGENTS.md MVP-PLAN.md MVP-ROADMAP.md docs`. | Native x86_64 Linux; dirty `HEAD` `10b5de4a1842baf43e847f21f75154966e44b9c0`; UTC was not captured by the command tool. | **Pass**; artifact: current owned-document diff; reviewer `LUNA MAX docs`; no code/configuration/skill/export/commit/push/Git-history mutation was performed. |
| `R-M00-2-E46` | Subsequent exact `.dev-venv/bin/python -m pytest tests/test_docs_validation.py` rerun. | Native x86_64 Linux; dirty `HEAD` `10b5de4a1842baf43e847f21f75154966e44b9c0`; UTC was not captured. | **Pass**; `49` passed in `3.24s`; artifact: coordinator command output; reviewer `LUNA MAX docs` for the documentation receipt; no source, configuration, or test edits were made by this documentation update. |

### `R-M00-2-E64` through `R-M00-2-E65` site-wide QA documentation checks

| Evidence ID | Requirement/check | Environment, UTC time, commit | Result, artifact, reviewer, limitation |
| --- | --- | --- | --- |
| `R-M00-2-E64` | Exact `.dev-venv/bin/python scripts/validate_docs.py` after the `R-ASTRA-99` site-wide QA rows. | Native x86_64 Linux; dirty `HEAD` observed from the current worktree; UTC was not captured by the command tool. | **Pass**; output: `Documentation validation passed: 9 categories, 13 topics, 7 project skill governance entries.` Artifact: validator output; reviewer `LUNA MAX docs`; no source, test, configuration, export, commit, push, or Git-history mutation was performed. |
| `R-M00-2-E65` | Exact `git diff --check -- MVP-PLAN.md MVP-ROADMAP.md` after the `R-ASTRA-99` site-wide QA rows. | Native x86_64 Linux; dirty `HEAD` observed from the current worktree; UTC was not captured by the command tool. | **Pass**; artifact: current two-file documentation diff; reviewer `LUNA MAX docs`; no source, test, configuration, export, commit, push, or Git-history mutation was performed. |
