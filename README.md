# Stock Probability

Stock Probability is a local, auditable research application for selected Yahoo
Finance stocks and ETFs. It is a loopback-first Linux app, not a hosted service or a
trading system.

## Start here

- [MVP plan](MVP-PLAN.md) — authoritative product contract, task register, and evidence ledger.
- [MVP roadmap](MVP-ROADMAP.md) — dependency order, milestone status, and release gates.
- [AGENTS.md](AGENTS.md) — compact ownership, local-only verification, and evidence rules.
- [SESSION-EXPORT.md](SESSION-EXPORT.md) — generated root export, owned by its export gate.

The root MVP files are preserved compatibility paths because repository orchestration
references them directly. They are the authority; this README is a landing page and
does not duplicate their detailed ledgers.

## Current evidence-backed status

As of 2026-09-14:

- `M00`, `EXP-M00`, `M01`, `EXP-M01`, `M02`, `EXP-M02`, `M03`, and `EXP-M03` are
  **Completed** for their recorded scopes. `EXP-M03` is verified at exact local and
  remote SHA `777451643b5ec1a04a37c013a9caf59f0bd58122`.
- `M04` and `EXP-M04` are **Completed** for their recorded scopes. `R-M04-30` remains
  **Pending** because actual screen-reader evidence is **Unavailable** and deferred to
  M06; it still blocks final accessibility/release acceptance, not the exercised M04
  functional scope.
- `EXP-M04` receipt: the sanitized full-session `SESSION-EXPORT.md` was overwritten and
  parsed as JSON with `140` messages, `844` parts, `101` task outputs, `241` tool parts,
  `672,190` bytes, `19,855` physical lines, SHA-256
  `5eebab2ce302e9f8b5a08aec5e4773c8bf7e4a99c920fa059c462dd71cecb837`, and `1,817`
  redaction markers. Secret review found zero webhook, private-key, AWS, GitHub, Bearer,
  or embedded-credential matches. Commit `59534faf1cdce493bc51a11d4adbea5e5b2d6892`
  (`Build responsive forecast dashboard`, commit UTC `2026-09-11T20:25:10-04:00`) was
  pushed and the exact `origin/main` match was verified; no CI was run or used.
- `M05` is **Completed for its declared scope**. The independent `R-M05-55` receipt is
  **Pass**, reviewed by `LUNA MAX QA` on native x86_64 with `.dev-venv` Python `3.11.15`.
  Rows `(a)`–`(i)` are session `ses_f6bbd6b46ffes2BM2zVjBC5uLg`,
  `2026-09-12T06:25:04Z`–`2026-09-12T06:44:37Z`: round trip/checksum
  (`06:42:38Z`–`06:42:39Z`), six-path pre-migration forced-failure matrix
  (`06:32:09Z`–`06:32:10Z`), due-check bounds `60`/`2678400` accepted and
  `59`/`2678401`/`nan` rejected, retention of `32` artifacts/`256 MiB` with history
  preserved (`06:43:54Z`), `13/13` fail-closed negatives (`06:35:29Z`–`06:35:32Z`),
  key lifecycle with rollback (`06:44:37Z`), `7/7` watchdog probes
  (`06:35:01Z`–`06:35:02Z`), both-direction **emulated ARM64** cross-architecture
  restore (`06:25:04Z`–`06:28:44Z`, artifact
  `test-results/arm64/M05-20260912T034933Z/evidence.json`), and the `R-M05-12`
  rerun (`06:38:47Z`–`06:38:49Z`). Row `(j)` is session
  `ses_f6aa32b01ffexjSm9OhpprFwq4`, `2026-09-12T11:26:29Z`–`2026-09-12T11:28:26Z`:
  `276` non-live tests, `4` live deselected, `89.51%` coverage, documentation
  validation of `8` categories/`11` topics/`1` skill, `22` documentation tests, a
  `77`-file comment audit, Ruff, and mypy. Packaged-CLI end-to-end verification is
  session `ses_f6a96daceffegfAqyKQL2lf3bS` on native x86_64/Python `3.11.15`, with
  fresh-venv wheel install, migration pre-backup, named backup, verify,
  `restore --promote`, wrong-key/tampered rejection, backup-key rotate/retire, and
  isolated-port serve readiness; artifact
  `/tmp/opencode/stock-probs-m05-cli-20260912T114105Z/M05-packaged-cli-receipt.json`,
  reviewer `LUNA MAX QA`. Commands and commit were not supplied; no values are
  inferred.
- `EXP-M05` is **Completed** at commit
  `9be15a3ae60b16e7cc7a5b95653f914b578e1a61`. The export audit receipt reports
  `233` messages, `1,387` parts, `432` tool parts, `185` task outputs, `1,116,276`
  bytes, `32,915` lines, SHA-256
  `ce5f025d41c4757dcf95a336555ce0fdd46ddcf22d1e9bce68d2d8fb5328c181`, and
  `3,090` redaction markers. Secret review found zero matches across all canonical
  secret patterns. The commit parent is
  `59534faf1cdce493bc51a11d4adbea5e5b2d6892`, commit UTC is
  `2026-09-12T12:41:32Z`, the message is `Add verified backup operations`, and
  `origin/main` matched the exact commit; reviewer: `LUNA MAX QA`. No export session
  ID, command, or additional check is inferred.
- M05 automation is implemented as builder evidence only: migrate creates a verified
  pre-migration backup; serve performs a fail-closed due check using
  `STOCK_PROBS_BACKUP_INTERVAL_SECONDS` (default `86400`, bounds `60`–`2678400`);
  `backup-key rotate` and `backup-key retire` are present; retention is `32` artifacts/
  `256 MiB`, and query history never expires automatically. The authored operation and
  configuration pages were updated for accuracy by `SOL HIGH`; this is not independent
  QA or M05 acceptance.
- The earlier M08 capture harness was preparation only: it supplied `20` annotated screenshots and
  manifest SHA-256 `f9fef2b2db0a806cc47ff1db82e1e895f4dd4803425c0cf74426f5fa5a12dd5d`.
  This is no M08 acceptance, walkthrough QA, Astra result, or `EXP-M08` checkpoint.
  The eventual walkthrough must include the M09 dark-mode and selected-instrument news
  controls and states; no such walkthrough evidence is claimed.
- Historical pre-acceptance `M08` walkthrough-extension evidence remains **In progress**: `20` steps,
  `40` annotated PNGs (`20` desktop at `1280x1000` and `20` mobile at `390x844`), manifest
  SHA-256 `806722ad4321fa3ca25a794192649eb55ad9c55cbba4abf6ec51886ba556df5d`, five
  companion news states represented as evidence rows, `5,683,157` bytes against the `20 MiB`
  budget, and zero undeclared requests or page errors. Independent M08 verification and
  `EXP-M08` remained pending at that historical point; the later ASTRA findings, repair
  program, and accepted checkpoint are recorded below.
  The exact generation command, session, environment, UTC, commit, artifact path, and named
  reviewer for this extension evidence were not supplied and are not inferred.
- Historical pre-acceptance `ASTRA-FINAL` state (retained): it was **In progress**, not
  **Accepted**. Four ASTRA evaluation lanes reviewed all
  `211` matrix rows and produced findings across assets/controls/charts, UI states/persistence,
  theme/news/docs, and the walkthrough. SOL applied fourteen repair groups: `R-ASTRA-1`–
  `R-ASTRA-5` cover CSS/theme defects including the mobile theme selector, dark/forced-colors/
  print contrast, mobile navigation, the API-docs label, and chart typography; `R-ASTRA-6`–
  `R-ASTRA-10` cover app behavior including news terminal states/retry/abort, history race and
  pagination guards, fresh-analysis context, saved-replay truthfulness, validation recovery,
  stale-reason placement, ledger evidence, and chart focus; `R-ASTRA-11` covers export
  sort-before-cap; `R-ASTRA-12` covers `theme.js` package verification; `R-ASTRA-13` covers
  walkthrough quality and the tracked [`docs/walkthrough/`](docs/walkthrough/index.md)
  artifact (7.19 MiB, 52 PNGs, instructional transcript, simulation labels, and manifest
  revision binding); and `R-ASTRA-14` covers news/theme documentation. The static shell was
  repaired from `102,607` to `98,242` bytes, `62` bytes below the `98,304`-byte limit.
  Independent QA of all 14 repairs and ASTRA re-evaluation were **In progress** at that
  historical point; no ASTRA acceptance or `EXP-M08` checkpoint was then inferred. Exact
  ASTRA/repair commands, sessions, environments, UTC windows, commits, and named reviewers
  were not supplied for that earlier record.
- `M06` is **Completed for its declared scope** through the final clean-target
  `R-M06-55` gate on commit `a69df40e15b3136886f26789c27861184c3bbd77`, run
  `2026-09-12T14:40:23Z`–`2026-09-12T14:49:48Z` with exit `0`: `278` tests, `4` live
  deselected, `89.51%` coverage, browser `32` passed/`2` skipped, official MCP,
  explicitly labelled emulated-ARM64 package/runtime evidence, and `12/13` performance
  rows **Pass** with ARM64 performance **Unavailable**. The tree stayed clean before and
  after; reviewer: `LUNA MAX QA`. Earlier dirty-worktree M06 receipts remain historical.
  Actual screen-reader evidence remains **Unavailable**, and this declared-scope result
  does not claim final accessibility/release acceptance.
- `EXP-M06` is **Completed** at the same commit. Its export audit reports `253` messages,
  `1,500` parts, `473` tool parts, `212` task outputs, `1,202,095` bytes, `35,447` lines,
  SHA-256 `f882941a1bac55b9e12b57d7a640256aad5cd1b71fe920f125134147edf516fc`, and
  `3,334` redaction markers; secret review found zero canonical secret-pattern matches.
  Parent: `9be15a3`; commit time `2026-09-12T10:39:42-04:00`; message `Record dark mode
  and news contract`; exact `origin/main` match; reviewer: `LUNA MAX QA`. No export
  session ID or command is inferred.
- `M09` is **Completed for its declared scope** by the consolidated `M09-E18` receipt:
  `TASK_ID=M09 PERFORMANCE_REVIEWER='LUNA MAX QA' ./scripts/local-gate.sh m09` passed on
  commit `a69df40e15b3136886f26789c27861184c3bbd77` at
  `2026-09-12T17:22:52Z`–`2026-09-12T17:33:03Z` with `339` tests passed, `4` live
  deselected, and `89.62%` coverage; browser `40` passed with `2` expected performance
  skips; official MCP; and explicitly labelled emulated ARM64 functional/package/runtime
  evidence using QEMU `7.2.0` on `aarch64` (not native ARM64). The receipt has `17`
  executable performance rows **Pass** and ARM64 performance **Unavailable**. Artifacts:
  `test-results/local-gates/M09-20260912T172252Z/`. Measured rows are theme p95 `57.3 ms`,
  news endpoint p95 `1.436 ms`, ten-item render p95 `21.0 ms`, news response `701` bytes,
  provider deadline capped at `10 s`, static `98,068`/`98,304` bytes, and `7` requests.
- `R-M09-2` and `R-M09-3` are **Completed** for their repaired scopes by the consolidated
  receipt; their earlier failure, flaky search-collision observation, and repair records
  remain visible below. The retained `R-M09-1` boundary report remains overengineering-only
  history; this update does not infer a new Ponytail result. `EXP-M09` is **Pending** for
  the full-session export, secret review, local commit, push, and exact remote verification.
- Earlier integrated `M07` release acceptance is **Completed for its declared scope** by receipt
  `M07-E18`: the exact release gate
  `TASK_ID=M07 PERFORMANCE_REVIEWER='LUNA MAX QA' ./scripts/local-gate.sh release` passed on
  clean commit `131aabc0fc0528b1e70ba26e09e2c78565ee8d56` at
  `2026-09-12T18:14:08Z`–`2026-09-12T18:21:06Z`. It recorded `396` tests passed, `4` live
  deselected, `89.62%` coverage, browser `40` passed/`2` expected performance skips, official
  MCP, migration with a verified pre-migration backup from schema v1 to v4, backup CLI `17`
  passed, a Ponytail interface precondition **Pass**, and `17` executable performance rows
  **Pass** with ARM64 performance **Unavailable**. Artifacts are under
  `test-results/local-gates/M07-20260912T181408Z/`; reviewer: `LUNA MAX QA`.
- The two earlier failed release runs and their `R-M09-4`/`R-M09-5` repair records remain
  visible as immutable history below; the supplied M07 receipt is the current integrated
  release result, not a row-only repair receipt. `EXP-M07` is now **Completed** at commit
  `779aa749d2f85849427212d890ee6918987492b7`; its export audit is recorded below. M08 is
  the next walkthrough gate after that checkpoint.
- `EXP-M07` export audit is **Completed**: `281` messages, `1,676` parts, `1,341,738` bytes,
  `39,520` lines, SHA-256
  `fddc25e5dbd0bbea4cd70cf3f124476157bb80e4f2cf9fa2ab969e69f7ace487`, and `3,793`
  redaction markers. Secret review found zero canonical secret-pattern matches. Parent:
  `131aabc0fc0528b1e70ba26e09e2c78565ee8d56`; message: `Record integrated acceptance`;
  exact remote `main` matched; reviewer: `LUNA MAX QA`. The earlier M07 receipt
   verification also passed with independently recomputed performance rows; its separate
   command, session, environment, UTC, artifact, and reviewer metadata were not supplied.
- Earlier accepted `ASTRA-FINAL` is retained at clean commit
  `261825838d6788afeb9640db8fbbf3f94af3a82b`, session
  `ses_f679f906cffexS9H5k8Vwk4d16`. The bound ASTRA evidence covers a `214`-row matrix,
  records no remaining blocking defect and no regression, and preserves the explicit
  limitations that actual screen-reader, physical-mobile, and native/physical ARM64
  performance evidence are **Unavailable**. These unavailable fields are not converted to
  passes; the accepted result is for the recorded ASTRA scope.
- `EXP-M08` is **Completed** at commit
  `7cf1ca8395b94c2e14e5b02ddf160f3f938091d3`. Its export audit reports `303` messages,
  `1,812` parts, `1,466,585` bytes, `43,137` lines, SHA-256
  `f846722f1c02aefbeb2f784141a022353c91dbf7c9bebde9c68b7a3dc79498d1`, and `4,288`
  redaction markers; secret review found zero canonical secret-pattern matches. Parent:
  `261825838d6788afeb9640db8fbbf3f94af3a82b`; message: `Checkpoint instructional walkthrough`;
  exact remote `main` match; reviewer: `LUNA MAX QA`. The export command, session,
  environment, and exact export UTC were not supplied and are not inferred.
- The final `M07` release gate receipt (`EV-8` in the bound ASTRA evidence) passed on clean
  commit `f511ae3629de679b12c006db5d122b3ed0a22f2c`: `401` tests, `89.61%` coverage,
  browser `48` passed/`2` expected performance skips, and `17` executable performance rows
  passed; ARM64 performance is **Unavailable**. Its tracked walkthrough observation is
  `7,660,518` bytes, below the `20 MiB` budget. The receipt's supplied artifacts are under
  `test-results/local-gates/M07-20260913T005729Z/`; no native/physical ARM64 performance
  result is claimed.
- Historical pre-notification status (retained): the final learning synthesis via
  `skill-maintenance` was **In progress** and `EXP-FINAL` was **Pending** for the completed
  synthesis, final export/secret review, commit, push, and exact remote verification; no final
  export acceptance was inferred at that earlier point.
- The earlier supplied final acceptance receipt records `EXP-FINAL` as accepted at checkpoint
  `b96cb6954ecf6e03b3bcdb0ad52af38ed7eae4cb`. The optional `NOTIFY-FINAL` delivery is
  **Completed for its operational scope only**: the user-supplied out-of-band webhook returned
  HTTP `204` with an empty response body around `2026-09-13T01:45Z`, no retry was needed, and the
  bounded delivery did not change the accepted `EXP-FINAL` result. Its retained dirty-worktree
  context is `91ba52eca35fcfc13bd0d9996beb947d65d69d09`; the reviewer/coordinator was `OpenCode
  gpt-5.6-sol`.
- `NOTIFY-FINAL` is not a milestone or acceptance ID. Its minimal non-secret payload contained the
  accepted result, checkpoint, and evidence summary; the endpoint, token, and credential-bearing
  payload were never written to the repository, export, artifacts, or logs, and the sanitized
  export shows zero webhook-pattern matches. Exact delivery UTC, network environment, and a
  separate notification artifact were not supplied and are not inferred.
- **Current post-repair `EXP-FINAL`:** **Completed** for the same declared final acceptance scope,
  not a new milestone or acceptance scope. The implementation checkpoint is
  `c55064da92dcc8da591494c1c88cf040039e2437`; the release-receipt documentation checkpoint is
  `830030ab5322e5c7aaaf12e6fde3f6c0ea9b2a12`; and the accepted export checkpoint is commit
  `10b5de4a1842baf43e847f21f75154966e44b9c0`, parent `830030a`, message `Checkpoint final repair
  session`. Exact `git push origin main` passed and `git ls-remote origin refs/heads/main` exactly
  matched `10b5de4a1842baf43e847f21f75154966e44b9c0`. The sanitized audit used session
  `ses_f71ec0499ffeokWj4h6tVwyYk1`: `572` messages, `3,155` parts, `952` tool parts, `350`
  completed task outputs, `2,552,320` bytes, `90,476` lines, SHA-256
  `cf1b85d07eefc9ff6436ad692ee826cb394be8f39af34caf6b1ff58f1f8517ff`, and `14,895` redaction
  markers; ordered message-ID hash
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
- **Current post-repair visual result:** the visual-quality requirement was reopened as
  `R-ASTRA-22` and is **Completed for its declared scope**. Independent QA on dirty `HEAD`
  `91ba52eca35fcfc13bd0d9996beb947d65d69d09` reported `425` passed/`4` deselected/`89.65%`
  coverage, provider `32` passed, browser `62` passed/`2` expected performance skips plus `31`
  checks at `1280px`, `17` executable performance rows passed, static `97,893`/`98,304` bytes,
  and persistence `55 + 35 + 4` passed. `R-ASTRA-24` records SPY as an ETF in lookup,
  `R-ASTRA-25` records heading-order pass, `R-ASTRA-26` records `44px` desktop actions, and
  `R-ASTRA-27` records selector-alignment pass after its failed initial render attempt and
  successful reruns. The supplied Ponytail result was `Lean already. Ship.`; it is
  overengineering-only evidence.
 - **Current final documentation reconciliation (`R-ASTRA-71`):** `R-ASTRA-70` is **Completed**
   as the docs-only portable-link repair that changed eight ignored-artifact links to inline code.
   The final ASTRA session `ses_f622707a4ffeAE3Zx8Lt2zYiC1` is **Accepted** for its affected
   post-repair scope with no blockers: reviewer `ASTRA`, model `openai/gpt-6-astra`, native
   x86_64, official MCP/headless Chromium `153.0.8010.12`, dirty `HEAD`
   `5633f87f8cff04b5b33640f6633ff31c667c0435`, `2026-09-14T02:57:56Z`–`03:16:35Z`, routes `/`
   and `/api/v1/docs`, viewports `320x844` and `1280x1000`, Light/Dark. Exact shell command and
   separate ASTRA artifact were not supplied; the named session, reviewer, model, and revision
   are supplied. The initial named session `ses_f6276e3a8ffeR3awDDSYKonmLk` remains **Blocked** at
   `2026-09-14T01:30:13Z`–`01:47:02Z`, reviewer `ASTRA`, model `openai/gpt-6-astra`: official MCP
   exposure passed, but reverse-Tab then Escape at `320x844` restored focus off-screen;
   forecast/chart/news evaluation was **Unavailable** because the first isolated server used the
   wrong 2026 fixture clock and correctly returned `stale_data`, not because of a production defect.
   The repair history preserves incomplete `R-ASTRA-66`, independent-QA failures after `R-ASTRA-67`,
   guarded external entry/trigger-focus restoration in `R-ASTRA-68`, and 320px Pixel/mobile
   restoration in `R-ASTRA-69`. Final `R-ASTRA-69` Ponytail is **CLEAN** (`Lean already. Ship.` at
   `2026-09-14T02:41:58Z`, native x86_64, dirty `HEAD` above, reviewer `OpenCode gpt-5.6-sol`).
   Separate findings-only artifacts are historical/unrelated and do not override this clean boundary.
   Independent QA (`LUNA MAX QA`) used `/tmp/opencode/r-astra-69-20260914T025542940Z.json` at
   `2026-09-14T02:55:42.940Z`–`02:55:54.436Z`: `66/66`, axe `0/0`, Light/Dark focus,
   HTTP `201` forecast with charts/text, HTTP `200` partial news/2 items, local-only traffic, and
   no current errors. The final review also passed prior focus/fixture blockers, the `8px` popover
   gap and containment, no overlap/overflow, `44px` controls, focus/dismissal, sampled contrast,
   first paint/System/CSP/media emulation, ACDC-M event `#6`/run `#2`, charts/text, partial news
   (2 items), OpenAPI, and `103` requests/`18` data requests with no off-origin, non-API, `.txt`,
    or current errors; `.data-label` is optional/nonblocking and no repair is authorized. Full artifact:
    `test-results/r-astra-69-browser-20260914T0248Z/` (`64`
    passed/`2` expected skips; `33` desktop/`33` mobile). Physical mobile, actual screen-reader,
    true-zoom, fresh ASTRA axe/screenshots, and native/physical ARM64-performance evidence remain
    **Unavailable**. Full rows: `docs/evidence/astra-final-report.md`.
 - **Current Orchestrator rename validation (`R-ASTRA-72`):** **Completed for its declared
   rename/restart-validation scope** from independent post-restart QA by `LUNA MAX QA`. The
   historical `R-ASTRA-72` rename performed the change to exact `Orchestrator` and required
   restart validation. Full QA, Ponytail, and limitation rows are in
   `docs/evidence/astra-final-report.md`; no new release, export, commit, push, or remote result
   is claimed.
 - **Current local container follow-on:** `R-M07-5` is **Completed for its declared scope** by
  two passing container contract tests and the supplied amd64 image receipt (digest
  `sha256:0dcb3f5ec77d31a5e8f57ef6e5d57b7144b973c3acb73ac360ffe01494735da`,
  `169,699,932` bytes). The optional Compose path and native-development distinction are
  documented in [getting started](docs/operations/getting-started.md). This dirty-worktree
  evidence is not a new clean release, export, commit, push, remote verification, or
  notification.
  - **Earlier post-final frontend/documentation reconciliation (`R-ASTRA-64`, retained):**
   **Completed for
   its declared documentation scope** after the supplied implementation and independent QA
  evidence; this is a docs-only record, not a new
  milestone or release checkpoint. FastAPI remains the sole production server and `/api/v1`
  remains the sole application-data API; it serves `/` and `/api/v1/docs`. Next.js `16.3.5` /
  React `19.3` builds a static App Router export through `./scripts/build-frontend.sh` with
  stable build ID `stock-probs`. Generated `frontend/.next/`, `frontend/out/`, and staged
  `src/stock_probs/static/next/` trees are ignored; 12 staged served files are packaged into
  the wheel. Node is build-only in the container. The routes retain strict CSP with exact
  inline hashes and parser-blocking `theme.js`; native Settings offers Light/Dark/System, and
  `R-ASTRA-59` repaired its open-state anchor.
  The supplied QA summary reports Python `444` pass/`4` deselected/`89.73%`, docs `52`,
  browser `64` pass/`2` expected performance skips, axe `0/0`, focus geometry `8/8`, and no
  external or `.txt` traffic. Deterministic builds are `26` files/`703,175` bytes and staged
  `12`/`608,713` bytes; the wheel is approximately `306,559` bytes. The supplied amd64 image
  is digest `sha256:0d68e3d9a78d626a61a1a82c455ea1734ddaa753f562d74022b94986c477bb12`,
  `170,062,564` bytes. Native M09 reports `18` rows, theme p95 `32.7 ms`, render p95
  `168.649 ms`, static `696,727`/`753,664` bytes, navigation `13`/`574,661` bytes, and
  wheel `306,553`/`335,872` bytes; ARM64 performance is **Unavailable**. Earlier theme
  failures at `120.2`/`120.8 ms` remain history. Emulated ARM64 is functional/package/runtime
  only; physical mobile, screen-reader, and true zoom remain **Unavailable**.
  `development-conventions` is explicitly admitted as the eighth opt-in skill and fresh
   discovery passed, but profile activation requires a parent restart. At that earlier
   checkpoint, the post-migration ASTRA review was **Blocked**/**Unavailable** for named
   live-browser evidence because the current parent lacked the official `playwright_*` tools and
   fresh delegated attempts timed out; no remaining reproducible app blocker was reported. The
   `R-ASTRA-43`/`R-ASTRA-46` Ponytail
   history (including the clean `R-ASTRA-46` recheck), subsequent repair records, and rejected
   `R-ASTRA-63` CSP-regex suggestion
   are retained in [the evidence report](docs/evidence/astra-final-report.md). No clean
   release, commit, export, push, or remote result is claimed here.
  - **Earlier final gate artifact consumed by `R-ASTRA-64` (retained):**
   `test-results/local-gates/M09-20260914T002732Z/` was **Pass**, exit `0`, dirty `HEAD`
   `5633f87f8cff04b5b33640f6633ff31c667c0435`, native x86_64, at
   `2026-09-14T00:27:32Z`–`2026-09-14T00:40:00Z`, with command `./scripts/local-gate.sh m09`.
   It recorded the eight checks, `444` Python tests with zero errors/failures and `89.73%`
   coverage, browser `64` passed/`2` expected performance skips, `18` performance rows with
   `17` executable **Pass**, and ARM64 performance **Unavailable**. Its `306,553`-byte wheel,
   `34.9 ms` theme p95, `152.881 ms` browser-render p95, and other row values remain historical.
   The unsupported `TASK_ID=R-ASTRA-64` attempt, the first supported M09 timing-race failure,
   `R-ASTRA-65` repair, and findings-only CSP observation remain visible; no clean release or
   Git/export result was claimed for that reconciliation.
  - **Current post-ASTRA M09 gate rerun:** task `M09` ran `./scripts/local-gate.sh m09` and
   **Passed** with exit `0` in artifact directory `test-results/local-gates/M09-20260914T032442Z/`.
   The native x86_64 run used dirty `HEAD` `5633f87f8cff04b5b33640f6633ff31c667c0435` from
   `2026-09-14T03:24:42Z` to `2026-09-14T03:37:22Z`; all eight completed checks, official MCP,
   Python `444`/`0` errors/`0` failures/`89.73%`, browser `64` passed/`2` expected skips, and
    `18` performance rows (`17` executable **Pass**, ARM64 performance **Unavailable**) are
   recorded. Current measured rows include theme p95 `35.0 ms`, browser render p95 `151.958 ms`,
   interaction p95 `24.027 ms`, ten-item news render p95 `35.0 ms`, news cache-hit p95 `1.809 ms`,
   news response `701` bytes, provider deadline `10 s`, static assets `697,667` bytes below
   `753,664`, readiness `2,633.207 ms`, process RSS `144,457,728` bytes, and wheel `307,483`
    bytes below `335,872`. The ARM64 receipt is explicitly emulated QEMU `7.2.0` package/runtime/
    functional evidence, not native or physical ARM64 performance evidence. The earlier failed
    rerun at `test-results/local-gates/M09-20260914T031828Z/` remains visible with `46`
    documentation-link setup errors; `EXP-M09` is still **Pending** for export, secret review,
    commit, push, and exact remote verification. No clean release/export/commit/push/remote/CI/
    notification result is claimed for this current reconciliation.
- `R-M09-4` and `R-M09-5` each retain an earlier failed release result; their separate
  failure output, session, environment, UTC, commit, artifact, and reviewer metadata were
  not supplied here. The current `M07-E18` receipt does not rewrite either historical
  failure or invent a row-only repair receipt.
- The earlier supplied scoped M09 QA summary remains historical: it reported `130`
  news-contract tests plus live ACDC/SPY checks, browser `40` passed/`2` skipped with
  axe `0/0`, and performance rows of `32.4 ms`, `1.564 ms`, `30.3 ms`, `701` bytes, and
  `10 s`; its missing receipt metadata was not inferred.
- The first consolidated M09 gate command
  `TASK_ID=M09 PERFORMANCE_REVIEWER='LUNA MAX QA' ./scripts/local-gate.sh m09`
  **Failed** with one intermittent `test_success_repeat_failure_and_searchable_history`
  failure (expected total `2`, observed `3`; the known random request-ID/search-collision
  flake) and one reproducible blocker, `R-M09-2`: when local-gate invokes
  `scripts/arm64-smoke.sh`, it rejects `TASK_ID=M09` and exits `2` before ARM evidence.
  Its clean rerun reported `338
  passed/4 deselected/89.62%`. Independent continuation passed the native package
  (wheel `121,501` bytes including `theme.js` and `news.json`), browser `40` passed/
  `2` skipped, official MCP, Ponytail interface, and the M09 performance harness
  `18/18` rows; ARM64 performance is **Unavailable**. A separate functional/package/
  runtime smoke passed as **emulated ARM64**. This earlier report supplied no session,
  environment, UTC, commit, or artifact metadata; no value is inferred. The later
  `M09-E18` receipt above is the current declared-scope acceptance and does not erase this
  failed attempt.
- The retained `R-M09-1` boundary report records the earlier pre-acceptance state; the
  current M09 declared-scope result is complete, while the separate `EXP-M09` checkpoint
  remains pending. The earlier M07 pre-acceptance wording is retained as history:
  `R-M07-1` was the fifth-agent configuration/profile-count test with repair in flight,
  `R-M07-2` was the pending Ponytail-review availability row, and `R-M07-3`/`R-M07-4`
  retain their supplied repair evidence. The current `M07-E18` receipt above supersedes
  that wording for the declared integrated scope; it does not erase the earlier unavailable
  boundary evidence. At that earlier state it did not create an `EXP-M07` checkpoint; the
  later `EXP-M07` receipt above is the separate completed export checkpoint.
- The retained M09 boundary report
   `test-results/ponytail-m09-boundary.txt` records
  four overengineering findings and net `-119` possible lines. `SOL HIGH` applied minimal
  `R-M09-1` repairs: theme/news p95 sampling moved from the harness-generated Node script
  into `tools/browser/tests/performance.spec.js` (net `-25`; supplied `338` tests pass),
  provider curl stubs were consolidated to one helper (net `-25`; supplied `337` tests
  pass), CSS aliases were collapsed to one canonical name per role (net `-10`; the
  `dashboard.spec.js` contrast assertions are being updated), and the redundant static-row
  re-assertion was deleted. Independent verification of the harness/stub repairs is in
  flight at that historical boundary. This is overengineering-only repair evidence; the
  current M09 gate is recorded above and `EXP-M09` remains **Pending**.
- The earlier pre-acceptance M07 record is retained as history: `R-M07-1` was the
  fifth-agent configuration/profile-count test repair, `R-M07-2` was the findings-only
  Ponytail-review availability row, `R-M07-3` recorded the stale three-profile assertion
  repair, and `R-M07-4` recorded two retained Ponytail findings. The current `M07-E18`
  receipt above supersedes that pending state for the declared integrated scope; it does
  not erase the earlier unavailable boundary evidence. At that earlier state it did not create
  an `EXP-M07` checkpoint; the later export receipt above is the completed checkpoint.
- Historical pre-ASTRA status: `M08` remained **In progress** for the supplied walkthrough-
  extension implementation evidence; independent verification, Astra review, and `EXP-M08`
  were pending, and `ASTRA-FINAL`/`EXP-FINAL` were **Pending** at that earlier point. The
  current accepted `ASTRA-FINAL` and completed `EXP-M08` records are now above; `EXP-FINAL`
  remains **Pending** while the final learning synthesis is in flight.
- An earlier `R-M06-55` receipt ran on dirty native x86_64 Linux at revision
  `59534faf1cdce493bc51a11d4adbea5e5b2d6892` from `2026-09-12T04:52:33Z` to
  `2026-09-12T05:03:44Z`: `264` tests, `89.38%` coverage, 32 browser passes plus
  2 performance-profile skips, official MCP, 4/4 live Yahoo checks, and labelled
  emulated-ARM64 package/runtime evidence. Its structured performance receipt has
  `12/13` rows **Pass**; native/physical ARM64 performance is **Unavailable**. This
  historical dirty receipt is retained separately from the final clean-target receipt.
- The retained Ponytail receipts are
  [`ponytail-r-m06-1.txt`](docs/evidence/ponytail-r-m06-1.txt) (six findings repaired),
  [`ponytail-r-m06-15.txt`](docs/evidence/ponytail-r-m06-15.txt) (three findings repaired
  as `R-M06-19`), and
  [`ponytail-m05-boundary.txt`](docs/evidence/ponytail-m05-boundary.txt) (two findings
  repaired as completed repair record `R-M05-12`, whose independent rerun passed 4/4
  behavior tests inside `R-M05-55 (i)`). The documentation skill's fresh isolated
  discovery passed its validator, 20 tests, description-parity, 500-line-limit, and
  reference checks. The post-restart receipt is session
  `ses_f6aa32d33ffeAvmiFK8K7Cd8EI`, `2026-09-12T11:35:58Z`–`2026-09-12T11:36:02Z`,
  native x86_64/OpenCode `1.18.30`, dirty commit
  `59534faf1cdce493bc51a11d4adbea5e5b2d6892`; it passed discovery with the canonical
  description, six registered Ponytail commands, three loaded profiles, valid config,
  and no credentials. Ingenium onboarding is **Blocked** only on authorized workspace
  credentials, project registration, repository-sync dry-run/apply/no-drift, and
  credential-free evidence; no credential is recorded.

Implementation presence, generated artifacts, and builder reports do not change these
statuses. The detailed records, including failures, skips, unavailable checks, repairs,
reviewers, and checkpoint limitations, remain in the root plan and roadmap.

## Product contract

- Look up a company while preserving symbol, exchange, stock/ETF type, and instrument identity.
- Forecast close-to-close and latest-completed-five-minute-bar-to-close horizons; an
  in-progress bar is never treated as completed.
- Show explicit up/down/unchanged and `+/-1%`, `+/-3%`, `+/-5%`, and `+/-10%`
  threshold probabilities, conditional gain/loss, and 50/80/95 return and price intervals.
- Preserve source/as-of time, session and bar semantics, model/version, data quality,
  provider limitations, and immutable input/result provenance.
- Retain successful, failed, and repeated searches; reopen saved results immutably;
  label historical-cutoff reconstruction as a new analysis; append outcomes and corrections.
- Serve browser data through FastAPI `/api/v1`; the browser never opens SQLite, issues
  SQL, receives a database path, or calls Yahoo Finance directly.
- Retain the stock Playwright MCP entry in `opencode.json`: it invokes
  `./scripts/playwright-mcp.sh` with `--headless`, `--isolated`, and loopback host/origin
  allowlists. Selective Ingenium pipeline adoption must never replace this browser
  automation with Ingenium browser automation.
- Provide a user-selectable accessible dark mode and clearly labelled selected-instrument
  news through FastAPI `/api/v1`, including source/as-of information and honest loading,
  empty, stale, and failure states. M09 owns their implementation and QA/docs. The ten
  news UI states are **not requested**, **loading**, **fresh**, **empty**, **partial metadata**,
  **stale cached with refresh failure**, **provider unavailable without cache**, **local
  service unreachable**, **capacity busy**, and **instrument changed/request superseded**.
  The route returns `200` for fresh, empty, or stale fallback, `422` for invalid input,
  `502` for provider failure, and `503` for capacity busy; an empty news response is never
  `404`.
- Provide searchable history, CSV/JSON export, verified backup/restore, responsive
  accessible UI, secure loopback defaults, bounded operation, and local fail-closed gates.
- Keep the smallest contract that evidence requires: absent a demonstrated need, do not
  add auth, MFA, a gateway, a multi-service split, dual-database restore, direct-route SQL,
  or replica rate limiting. A read-only integrity diagnostic is optional.

### M09 ASTRA contract summary (Completed for declared scope; `EXP-M09` Pending)

`EXP-M06` is complete. M09 is complete for its declared implementation and consolidated
QA scope through the `M09-E18` receipt above. `EXP-M09` remains pending its full-session
export, secret review, local commit, push, and exact remote verification; it is not closed
by the separately recorded `M07-E18` integrated gate. The detailed rows in
[MVP-PLAN.md](MVP-PLAN.md) are authoritative; the earlier supplied QA summary and failed
gate remain historical evidence, not the M09 export checkpoint.

- **Theme:** an external parser-blocking `theme.js` initializer is loaded before CSS on
  the dashboard and `/api/v1/docs`. It reads the localStorage key `stock-probs.theme` for
  a light/dark preference, falls back to the system preference, and supports reset-to-
  system by removing the override.
  The first paint must not flash the wrong theme. Semantic color roles replace whole-page
  inversion. Text contrast is `>=4.5:1`; large text, controls, and chart marks are
  `>=3:1`; focus indicators are `>=3:1`. Forced-colors, reduced-motion, print, and
  strict-CSP behavior are separately tested; CSP is not loosened with inline script/style
  or new origins.
- **News:** `GET /api/v1/news?symbol=<normalized>&limit=5`, with `limit` from `1` to
  `10`. Four closed schemas are frozen; unknown fields are not accepted. A separate
  server-side provider `fetch_news` uses the pinned `yfinance==1.7.0` feasibility result:
  its `Ticker.get_news`/`Search` wrappers are unusable because of an indefinite LRU cache,
  no end-to-end timeout, and singleton mutation, while a direct single GET to
  `https://query2.finance.yahoo.com/v1/finance/search` through already-pinned
  `curl-cffi==0.16.3` is feasible. Live ACDC/SPY probes returned `5` items each with
  `uuid`, `title`, `publisher`, `providerPublishTime`, and `link`; `relatedTickers` was
  present in `3/5` and absent in `2/5`. The frozen adapter uses no retries, redirects,
  cookie preflight, or crumb; it caps the raw body at `256 KiB` and uses the absolute
  deadline `min(provider_timeout, 10s)`. Its frozen in-memory cache policy has a 5-minute
  fresh TTL, 30-minute stale ceiling, 60-second empty cache, 30-second failure suppression,
  at most 32 symbols, 32 KiB per entry, 1 MiB aggregate, and one active retrieval.
  Responses expose `cache_state` `miss`, `hit`, or `stale_fallback`; `200` means fresh,
  empty, or stale fallback, `422` means invalid input, `502` means provider failure, and
  `503` means capacity busy; an empty response never produces `404`. No storage, backup,
  model, fingerprint, or ledger changes are allowed.
  Saved forecasts reopen provider-free; a separately labelled current-headlines action
  fetches current data. Links are safe HTTPS links and browser traffic remains local-only.
- **Ten required news states:** **not requested**, **loading**, **fresh**, **empty**, **partial
  metadata**, **stale cached with refresh failure**, **provider unavailable without cache**,
  **local service unreachable**, **capacity busy**, and **instrument changed/request
  superseded**. Cache `hit` remains a cache-behavior check, while saved-reopen/provider-free
  and the separately labelled current-headlines action remain separate interaction checks;
  neither adds a UI state. The walkthrough and final Astra matrix must cover each state.
- **Explicitly rejected scope:** settings database, news archive, article scraper/proxy,
  sentiment engine, forecast/model/probability changes, Redis or external cache, background
  scheduler, service worker, separate service, notification feed, full-text search,
  watchlist, personalized ranking, and any additional market-data provider remain out of
  scope unless a new evidenced requirement is approved.
- **Measured scope and ownership:** the historical raw shell baseline was `90,240 B` with
  `8,064 B` headroom; the earlier supplied M09 shell was `98,168 B` of `98,304` bytes,
  leaving `136` bytes. The current `M09-E18` receipt is `98,068`/`98,304` bytes, with
  `7` requests and `theme.js` request `7`; theme p95 is `57.3 ms`, news endpoint p95
  `1.436 ms`, ten-item render p95 `21.0 ms`, news response `701` bytes, and provider
  deadline `10 s`. It records `17` executable performance rows **Pass** and ARM64
  performance **Unavailable**. `SOL HIGH-A` owns transport/API paths, `SOL HIGH-B` owns
  provider/domain/service paths and the conditional pinned-package proof, `SOL HIGH-C`
  owns presentation/static paths, and `SOL HIGH-D` owns browser/tooling paths. Exact paths,
  frozen interfaces, and the package/launch gate are in the plan; the retained Playwright
  MCP entry remains mandatory. QA receipt metadata not supplied above is not inferred.

Forecasts are informational research outputs, not investment advice or a guarantee.

## Local quick start

The supported development environment is Python `3.11.15` within the project range
`>=3.11,<3.12`. The bootstrap script uses the pinned lock file and creates the local
`.dev-venv/`; it does not use `burry_env/` as a dependency declaration.

```bash
./scripts/bootstrap.sh
./.dev-venv/bin/python -m stock_probs.cli migrate
./.dev-venv/bin/python -m stock_probs.cli serve
```

The default listener is loopback on port `8000`. For a deterministic first run:

```bash
STOCK_PROBS_PROVIDER=fixture \
STOCK_PROBS_FIXTURE_NOW=2025-01-10T17:03:00+00:00 \
  .dev-venv/bin/python -m stock_probs.cli serve
```

Use the [MVP plan](MVP-PLAN.md) and [MVP-ROADMAP.md](MVP-ROADMAP.md)
for the full contract. Keep provider credentials and machine-local values outside
tracked Markdown, configuration, command arguments, logs, and exports.

## Local verification policy

All acceptance checks are local. The current host is native x86-64. ARM64 checks use
local native hardware when available; otherwise they may use local QEMU/OCI and must be
labelled **emulated ARM64**. Emulation can verify packaging, runtime, functional, build,
and tool behavior, but cannot prove physical ARM64 performance.

There is no hosted or external pipeline acceptance path. A failed, skipped, unavailable, stale, or
connectivity-blocked check remains visible and requires a uniquely recorded repair and
rerun. The exact task vocabulary is `M00`–`M09`, `R-M##-<n>`, `EXP-M00`–`EXP-M09`,
`ASTRA-FINAL`, `R-ASTRA-<n>`, and `EXP-FINAL`; `NOTIFY-FINAL` is a separate optional
operational record, not a milestone or acceptance ID.

Orchestration allows at most six concurrent agents. Build waves use up to six declared,
disjoint lanes with A/B/C as the base roles; additional lanes require explicit ownership.
Any future selective Ingenium pipeline adoption is an operational follow-up only: it keeps
the six-agent orchestration and commit/export gates, uses the stock Playwright MCP entry,
and cannot create a hosted acceptance path.

Every implementation boundary is followed, before independent QA, by a read-only
`/ponytail-review`. It examines overengineering only. Record either
`Ponytail result | boundary: <exact task ID> | finding: none | scope: overengineering only |
command: /ponytail-review | environment | UTC | commit | result | artifact | reviewer` or
the exact finding form
`Ponytail finding | boundary: <exact task ID> | path:line | overengineering claim | evidence |
minimal SOL HIGH repair | QA rerun | environment | UTC | commit | result | artifact | reviewer`.
Only a reproducible blocking finding may receive an `R-M##-<n>` repair; only `SOL HIGH`
repairs it, and independent QA retests it. Ponytail cannot replace correctness, security,
accessibility, or performance evidence, and an unavailable review blocks that boundary.

## Final delivery order

The canonical order is:

```text
R-M00-1 → EXP-M00 → M01 → EXP-M01 → M02 → EXP-M02 → M03 → EXP-M03
→ M04 → EXP-M04 → M05/EXP-M05 → M06/EXP-M06 → M09/EXP-M09
→ M07/EXP-M07
→ M08 → ASTRA-FINAL → R-ASTRA-<n> SOL repairs and Astra reevaluation
→ EXP-M08 → final learning synthesis → EXP-FINAL → optional NOTIFY-FINAL
```

M09's dark-mode and selected-instrument news requirements therefore flow into the
integrated UI, walkthrough, and `ASTRA-FINAL` review. The declared implementation scope
and consolidated QA receipt are recorded above; `EXP-M09` remains open for the export,
secret review, commit, push, and exact remote verification. The integrated `M07` acceptance
receipt and completed `EXP-M07` checkpoint are recorded above; M08 follows that
checkpoint.

`ASTRA-FINAL`, its `R-ASTRA-<n>` repairs/retests, `EXP-M08`, the final learning
synthesis, and `EXP-FINAL` form one combined second-last operational loop, not a new
milestone. `ASTRA-FINAL` is now explicitly **Accepted for its declared scope** at
`261825838d6788afeb9640db8fbbf3f94af3a82b`, and `EXP-M08` is **Completed** at
`7cf1ca8395b94c2e14e5b02ddf160f3f938091d3`. The current post-repair receipt records accepted
`EXP-FINAL` checkpoint `10b5de4a1842baf43e847f21f75154966e44b9c0`. The earlier accepted
checkpoint `b96cb6954ecf6e03b3bcdb0ad52af38ed7eae4cb` and its `NOTIFY-FINAL` record at dirty
context `91ba52eca35fcfc13bd0d9996beb947d65d69d09` remain immutable history; no new
notification is claimed.
`ASTRA-FINAL` must separately matrix every asset, control, UI state, documentation visual,
walkthrough frame/segment, media item, and static asset against requirements, aesthetics,
mobile/responsive behavior, accessibility, and measured performance. Astra evaluates and
suggests only; `SOL HIGH` implements `R-ASTRA-<n>`, QA retests, and Astra reevaluates.
A demonstrated tooling, skill, or MCP gap may receive a narrowly scoped SOL repair and
validation before acceptance, but it cannot expand scope without a new evidenced need.
The final learning synthesis deeply analyzes sanitized chat/run evidence and uses
`skill-maintenance` only for justified reusable Stock Probability skills, validates and
indexes any such skill, and logs observations. The accepted post-repair `EXP-FINAL` checkpoint is
`10b5de4a1842baf43e847f21f75154966e44b9c0`. The earlier `b96cb6954ecf6e03b3bcdb0ad52af38ed7eae4cb`
checkpoint and its optional `NOTIFY-FINAL` record remain immutable history; no new notification is
claimed.

## Final operational item: selective Ingenium pipeline adoption

- **Status:** `In progress`; the broader implementation/adoption follow-up remains open. The
  `R-ASTRA-72` rename/restart-validation scope is independently verified, but no broader gate
  effect is inferred.
- **Commit evidence:** the committed adoption/profile change set is in ancestor commit
  `8084a134ab4950f36446de3af622349cd23423ae` (`Build dark mode and news`), including the
  ASTRA profile's `variant: max`; the current checkpoint is its descendant
  `779aa749d2f85849427212d890ee6918987492b7`. This commit history does not replace the
  required restart or independent post-restart validation.
- **Adoption state (rename scope validated):** `Orchestrator` is the inline
  primary with the six-agent count option and `subagent_depth: 1`; `luna-docs` has the
  `docs/**` permission; `.gitignore` additions are present; and the two-skill validator
  catalog contains `documentation` plus the new `skill-maintenance` skill.
- **Required controls:** retain the six-agent orchestration, independent QA/docs order,
  Ponytail boundary, and commit/export gates; retain the stock Playwright MCP command and
  loopback allowlists. `R-ASTRA-72` supplies independent post-restart validation for the
  `Orchestrator` rename only; unvalidated profile/catalog/ignore changes still require their
  own restart validation before affecting a gate. This docs reconciliation edits neither
  `opencode.json`, `.gitignore`, profiles, local gates, nor skills.
- **ASTRA profile:** the ASTRA agent profile now uses `variant: max`; parent-process
  restart and independent post-restart validation are **Pending**, so no gate effect or
  validation pass is claimed.
- **Historical ASTRA-FINAL preparation:** the matrix skeleton was being assembled at
  `test-results/astra/astra-final-matrix.md` before the supplied four-lane review. That
  preparation record did not claim a review, matrix acceptance, or `R-ASTRA-<n>` result; the
  current findings and repair program are recorded above and in the plan/roadmap. The
  preparation skeleton's separate command, environment, UTC, commit, and reviewer metadata
  were not supplied.
- **ASTRA research state:** the first pass is **Blocked** by the external-directory
  permission boundary. The gitignored snapshot at `test-results/ingenium-snapshot` enables
  a re-run; no re-run result is claimed.
- This follow-up does not alter the canonical `ASTRA-FINAL` → `EXP-M08` → final learning
  synthesis → `EXP-FINAL` order, and optional `NOTIFY-FINAL` remains separate and last.

## Documentation boundary

Authored documentation must remain concise, link to the root ledgers rather than copy
them, and keep the generated `SESSION-EXPORT.md` at the root. No current documentation
statement substitutes for independent QA, an export checkpoint, a restart, authorized
workspace access, or an unavailable hardware/provider result.

The supplied deep read-only Ingenium research sessions
`ses_f6d219e22ffeQuT1z7fdC3e4MA`, `ses_f6d219dddffeyB2ZTOmnUMJU3Z`, and
`ses_f6d219d92ffewot26Lkx216Lqw` are design input only. Their useful conventions are
recorded in the ledgers: deny-by-default least privilege, source-versus-live evidence
separation, structured sanitized errors, deterministic browser containment with no hidden
retries, bounded process/port/temp artifacts, migration/package/resource checks, and an
optional read-only integrity diagnostic. Implementation verification remains separate from
the completed M06 declared scope. The authored documentation taxonomy is implemented under
[`docs/`](docs/index.md),
and the project documentation skill is implemented at
`.opencode/skills/documentation/SKILL.md`. Its post-restart validation receipt is session
`ses_f6aa32d33ffeAvmiFK8K7Cd8EI` at
`2026-09-12T11:35:58Z`–`2026-09-12T11:36:02Z`, native x86_64/OpenCode `1.18.30`,
dirty commit `59534faf1cdce493bc51a11d4adbea5e5b2d6892`, and is **Pass** for the
canonical-description, six Ponytail-command, three-profile, configuration, and
credential checks. `.dev-venv/bin/python scripts/validate_docs.py` is also **Pass** for
`8` categories and `11` topics at `2026-09-12T12:13:23Z`. The later clean-target
`R-M06-55` and `EXP-M06` receipts above are the current M06 acceptance/checkpoint records;
this documentation boundary does not replace them.

The earlier `LUNA MAX docs` profile gap is retained as historical evidence: `SOL HIGH`
performed those authored documentation repairs. The supplied adoption state now grants
`luna-docs` `docs/**` permission, but it is not gate-active until the required parent restart
and independent post-restart validation; no new documentation-skill or M06 verification is
inferred here.

For an earlier four-document reconciliation, `.dev-venv/bin/python scripts/validate_docs.py`
was attempted but execution was **Unavailable** because the tool permission boundary denied
it; no current validator pass is inferred. `git diff --check -- README.md AGENTS.md
MVP-PLAN.md MVP-ROADMAP.md` returned **Pass**. UTC, commit, and artifact metadata were not
captured for these command attempts.

For the earlier M09 boundary-receipt update, the same validator command was attempted and remained
**Unavailable** because the tool permission boundary denied execution; no validator pass is
inferred. `git diff --check -- README.md AGENTS.md MVP-PLAN.md MVP-ROADMAP.md` returned
**Pass** on dirty `HEAD` `a69df40e15b3136886f26789c27861184c3bbd77`. UTC was not captured;
no artifact, commit mutation, or Git checkpoint was created.

For the earlier consolidated M09 gate-state root-documentation update, `.dev-venv/bin/python
scripts/validate_docs.py` was attempted and was **Unavailable** because the tool permission
boundary denied execution; no current validator pass is inferred (`R-M00-2-E15`). `git
diff --check -- README.md AGENTS.md MVP-PLAN.md MVP-ROADMAP.md` returned **Pass** on dirty
`HEAD` `a69df40e15b3136886f26789c27861184c3bbd77` (`R-M00-2-E16`). UTC was not captured;
no artifact, commit mutation, or Git checkpoint was created.

For the earlier M09 acceptance root-documentation update, the same validator command was attempted
and was **Unavailable** because the tool permission boundary denied execution; no current
validator pass is inferred (`R-M00-2-E17`). `git diff --check -- README.md AGENTS.md
MVP-PLAN.md MVP-ROADMAP.md` returned **Pass** (`R-M00-2-E18`) on dirty `HEAD`
`a69df40e15b3136886f26789c27861184c3bbd77`. UTC was not captured; no artifact, commit
mutation, or Git checkpoint was created.

For this M07 integrated-acceptance root-documentation update, `R-M00-2-E19` records the
exact `.dev-venv/bin/python scripts/validate_docs.py` attempt as **Unavailable** because
the tool permission boundary denied execution; no validator pass is inferred. `R-M00-2-E20`
records `git diff --check -- README.md AGENTS.md MVP-PLAN.md MVP-ROADMAP.md` as **Pass**;
UTC was not captured by the command tool, and the dirty `HEAD` was
  `131aabc0fc0528b1e70ba26e09e2c78565ee8d56`. No code, configuration, skill, export, commit,
  push, or Git-history mutation is part of this update.

For this M07 export/M08 walkthrough-extension root-documentation update, `R-M00-2-E21`
records `.dev-venv/bin/python scripts/validate_docs.py` as **Unavailable** because the tool
permission boundary denied execution; no validator pass is inferred. `R-M00-2-E22` records
`git diff --check -- README.md AGENTS.md MVP-PLAN.md MVP-ROADMAP.md` as **Pass** on dirty
`HEAD` `779aa749d2f85849427212d890ee6918987492b7`; UTC was not captured by the command tool.
No code, configuration, skill, export, commit, push, or Git-history mutation is part of this
update.

For this `ASTRA-FINAL` findings/repair root-documentation update, `R-M00-2-E23` records the
exact `.dev-venv/bin/python scripts/validate_docs.py` attempt as **Unavailable** because the
tool permission boundary denied execution; no current validator pass is inferred. Environment:
native x86_64 Linux; dirty `HEAD` `cf099754a5c3e4a05f0e785c0d65ff06f96c4d63`; UTC was not
captured; artifact: none; reviewer: `LUNA MAX docs`. `R-M00-2-E24` records the exact
`git diff --check -- README.md AGENTS.md MVP-PLAN.md MVP-ROADMAP.md` check as **Pass** on the
same dirty `HEAD`; UTC was not captured; artifact: current four-document diff; reviewer:
`LUNA MAX docs`. No code, configuration, skill, export, commit, push, or Git-history mutation
was performed.

For this accepted `ASTRA-FINAL`/completed `EXP-M08` root-documentation update,
`R-M00-2-E25` records the exact `.dev-venv/bin/python scripts/validate_docs.py` attempt as
**Unavailable** because the tool permission boundary denied execution; no current validator
pass is inferred. Environment: native x86_64 Linux; dirty `HEAD`
`7cf1ca8395b94c2e14e5b02ddf160f3f938091d`; UTC was not captured; artifact: none; reviewer:
`LUNA MAX docs`. `R-M00-2-E26` records the exact `git diff --check -- README.md AGENTS.md
MVP-PLAN.md MVP-ROADMAP.md` check as **Pass** on the same dirty `HEAD`; UTC was not captured;
artifact: current four-document diff; reviewer: `LUNA MAX docs`. No code, configuration,
skill, export, commit, push, or Git-history mutation was performed by this documentation update.

For this accepted `EXP-FINAL`/`NOTIFY-FINAL` root-documentation update, `R-M00-2-E27` records
the exact `.dev-venv/bin/python scripts/validate_docs.py` attempt as **Unavailable** because
the tool permission boundary denied execution; no current validator pass is inferred. Environment:
native x86_64 Linux; dirty `HEAD` `b96cb6954ecf6e03b3bcdb0ad52af38ed7eae4cb`; UTC was not
captured; artifact: none; reviewer: `LUNA MAX docs`. `R-M00-2-E28` records the exact
`git diff --check -- README.md AGENTS.md MVP-PLAN.md MVP-ROADMAP.md` check as **Pass** on the
same dirty `HEAD`; UTC was not captured; artifact: current four-document diff; reviewer:
`LUNA MAX docs`. No code, configuration, skill, export, commit, push, or Git-history mutation
was performed by this documentation update.

For this current post-repair `EXP-FINAL` documentation receipt, `R-M00-2-E42` records the
scoped name-only diff as exactly `AGENTS.md`, `MVP-PLAN.md`, `MVP-ROADMAP.md`, and `README.md`;
concurrent `.opencode/**`, `scripts/validate_docs.py`, and `tests/test_docs_validation.py`
changes were preserved. Environment: native x86_64 Linux; dirty `HEAD`
`10b5de4a1842baf43e847f21f75154966e44b9c0`; UTC was not captured; reviewer `LUNA MAX docs`.
`R-M00-2-E43` records `.dev-venv/bin/python scripts/validate_docs.py` as **Pass** with
`9` categories, `13` topics, and `7` project skills. `R-M00-2-E44` records the exact
`.dev-venv/bin/python -m pytest tests/test_docs_validation.py` attempt as **Unavailable** because
the tool permission boundary denied execution; no documentation-test pass is inferred.
`R-M00-2-E45` records `git diff --check -- README.md AGENTS.md MVP-PLAN.md MVP-ROADMAP.md docs`
as **Pass**. UTC was not captured for these checks; artifacts are the validator output and
current owned-document diff; reviewer `LUNA MAX docs`.

For the prior `R-ASTRA-70` documentation reconciliation, `R-M00-2-E50` records the exact
`.dev-venv/bin/python scripts/validate_docs.py` run as **Pass** with `9` categories, `13` topics,
and `8` project skills. `R-M00-2-E51` records the exact
`.dev-venv/bin/python -m pytest tests/test_docs_validation.py` attempt as **Unavailable** because
the tool permission boundary denied execution; `R-M00-2-E52` records the exact
`.dev-venv/bin/python scripts/comment_audit.py` attempt as **Unavailable** for the same reason.
`R-M00-2-E53` records `git diff --check -- README.md AGENTS.md MVP-PLAN.md MVP-ROADMAP.md docs`
as **Pass**. These checks ran on native x86_64 Linux at dirty `HEAD`
`5633f87f8cff04b5b33640f6633ff31c667c0435`; UTC was not captured; artifact: none for the Python
checks and the current documentation diff for `git diff --check`; reviewer `LUNA MAX docs`; no
Git mutation was performed.
`R-M00-2-E54` records the final `.dev-venv/bin/python scripts/validate_docs.py` rerun as **Pass**
with `9` categories, `13` topics, and `8` project skills. `R-M00-2-E55` records the final
`git diff --check -- README.md AGENTS.md MVP-PLAN.md MVP-ROADMAP.md docs` rerun as **Pass**.
Both ran on native x86_64 Linux at dirty `HEAD` `5633f87f8cff04b5b33640f6633ff31c667c0435`;
UTC was not captured by the command tool; artifacts are none for the validator and the current
documentation diff for `git diff --check`; reviewer `LUNA MAX docs`; no Git mutation occurred.
For current `R-ASTRA-71`, `R-M00-2-E56` records `.dev-venv/bin/python scripts/validate_docs.py`
as **Pass** with `9` categories, `13` topics, and `8` project skills. `R-M00-2-E57` records the
exact `.dev-venv/bin/python -m pytest tests/test_docs_validation.py` attempt as **Unavailable**
because the tool permission boundary denied execution; no documentation-test pass is inferred.
`R-M00-2-E58` records `git diff --check -- README.md AGENTS.md MVP-PLAN.md MVP-ROADMAP.md docs`
as **Pass**. All three checks ran on native x86_64 Linux at dirty `HEAD`
`5633f87f8cff04b5b33640f6633ff31c667c0435`; UTC was not captured by the command tool; artifacts
are none for the validator/test attempt and the current owned-document diff for diff-check;
reviewer `LUNA MAX docs`; no Git mutation occurred.
`R-M00-2-E59` records the final `.dev-venv/bin/python scripts/validate_docs.py` rerun after the
last wording correction as **Pass** with `9` categories, `13` topics, and `8` project skills.
`R-M00-2-E60` records the final `git diff --check -- README.md AGENTS.md MVP-PLAN.md MVP-ROADMAP.md
docs` rerun after the last wording correction as **Pass**. Both ran on native x86_64 Linux at
dirty `HEAD` `5633f87f8cff04b5b33640f6633ff31c667c0435`; UTC was not captured by the command tool;
artifacts are none for the validator and the current owned-document diff for diff-check; reviewer
`LUNA MAX docs`; no Git mutation occurred.
For current `R-ASTRA-72`, `R-M00-2-E61` records `.dev-venv/bin/python scripts/validate_docs.py`
as **Pass** with `9` categories, `13` topics, and `8` project skills. `R-M00-2-E62` records the
exact `.dev-venv/bin/python -m pytest tests/test_docs_validation.py` attempt as **Unavailable**
because the tool permission boundary denied execution; no documentation-test pass is inferred.
`R-M00-2-E63` records `git diff --check -- README.md AGENTS.md MVP-PLAN.md MVP-ROADMAP.md docs` as **Pass**.
All three ran on native x86_64 Linux at dirty `HEAD` `5633f87f8cff04b5b33640f6633ff31c667c0435`;
UTC was not captured by the command tool; artifacts are none for the validator/test attempt and
the current owned-document diff for diff-check; reviewer `LUNA MAX docs`; no Git mutation occurred.
