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

As of 2026-09-12:

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
  inferred. `EXP-M05` remains **Pending** for its separate export, secret-review,
  local commit, push, and exact remote-verification checkpoint.
- M05 automation is implemented as builder evidence only: migrate creates a verified
  pre-migration backup; serve performs a fail-closed due check using
  `STOCK_PROBS_BACKUP_INTERVAL_SECONDS` (default `86400`, bounds `60`–`2678400`);
  `backup-key rotate` and `backup-key retire` are present; retention is `32` artifacts/
  `256 MiB`, and query history never expires automatically. The authored operation and
  configuration pages were updated for accuracy by `SOL HIGH`; this is not independent
  QA or M05 acceptance.
- The M08 capture harness is prepared only: it supplied `20` annotated screenshots and
  manifest SHA-256 `f9fef2b2db0a806cc47ff1db82e1e895f4dd4803425c0cf74426f5fa5a12dd5d`.
  This is no M08 acceptance, walkthrough QA, Astra result, or `EXP-M08` checkpoint.
- `M06` is **In progress**, not released: `R-M06-2`, `R-M06-3`, `R-M06-4`,
  `R-M06-11`, and `R-M06-16`–`R-M06-20` have supplied independent **Pass** results;
  `R-M06-11` passed twice, each with three hash-stable native runs and exact recomputation.
  `R-M06-55` also passed the scoped M06 gate, but the final consolidated gate rerun,
  docs/release reconciliation, and `EXP-M06` checkpoint remain pending. Actual
  screen-reader evidence is **Unavailable**; `M07`, `M08`, `ASTRA-FINAL`, and
  `EXP-FINAL` remain **Pending**.
- `R-M06-55` ran on dirty native x86_64 Linux at revision
  `59534faf1cdce493bc51a11d4adbea5e5b2d6892` from `2026-09-12T04:52:33Z` to
  `2026-09-12T05:03:44Z`: `264` tests, `89.38%` coverage, 32 browser passes plus
  2 performance-profile skips, official MCP, 4/4 live Yahoo checks, and labelled
  emulated-ARM64 package/runtime evidence. Its structured performance receipt has
  `12/13` rows **Pass**; native/physical ARM64 performance is **Unavailable**.
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
- Provide searchable history, CSV/JSON export, verified backup/restore, responsive
  accessible UI, secure loopback defaults, bounded operation, and local fail-closed gates.
- Keep the smallest contract that evidence requires: absent a demonstrated need, do not
  add auth, MFA, a gateway, a multi-service split, dual-database restore, direct-route SQL,
  or replica rate limiting. A read-only integrity diagnostic is optional.

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

There is no hosted pipeline acceptance path. A failed, skipped, unavailable, stale, or
connectivity-blocked check remains visible and requires a uniquely recorded repair and
rerun. The exact task vocabulary is `M00`–`M08`, `R-M##-<n>`, `EXP-M00`–`EXP-M08`,
`ASTRA-FINAL`, `R-ASTRA-<n>`, and `EXP-FINAL`.

Orchestration allows at most six concurrent agents. Build waves use up to six declared,
disjoint lanes with A/B/C as the base roles; additional lanes require explicit ownership.

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
→ M04 → EXP-M04 → M05/EXP-M05 → M06/EXP-M06 → M07/EXP-M07
→ M08 → ASTRA-FINAL → R-ASTRA-<n> SOL repairs and Astra reevaluation
→ EXP-M08 → final learning synthesis → EXP-FINAL → optional NOTIFY-FINAL
```

`ASTRA-FINAL`, its `R-ASTRA-<n>` repairs/retests, `EXP-M08`, the final learning
synthesis, and `EXP-FINAL` form one combined second-last operational loop, not a new
milestone. Astra must explicitly be **Accepted** before `EXP-M08`; the learning
synthesis must complete after all roadmap and Astra repairs and before `EXP-FINAL`.
`ASTRA-FINAL` must separately matrix every asset, control, UI state, documentation visual,
walkthrough frame/segment, media item, and static asset against requirements, aesthetics,
mobile/responsive behavior, accessibility, and measured performance. Astra evaluates and
suggests only; `SOL HIGH` implements `R-ASTRA-<n>`, QA retests, and Astra reevaluates.
A demonstrated tooling, skill, or MCP gap may receive a narrowly scoped SOL repair and
validation before acceptance, but it cannot expand scope without a new evidenced need.
The final learning synthesis deeply analyzes sanitized chat/run evidence and uses
`skill-maintenance` only for justified reusable Stock Probability skills, validates and
indexes any such skill, and logs observations; no such run is claimed now.
Optional notification is last and cannot repair a missing gate.

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
optional read-only integrity diagnostic. Implementation verification remains a future M06
gate. The authored documentation taxonomy is implemented under [`docs/`](docs/index.md),
and the project documentation skill is implemented at
`.opencode/skills/documentation/SKILL.md`. Its post-restart validation receipt is session
`ses_f6aa32d33ffeAvmiFK8K7Cd8EI` at
`2026-09-12T11:35:58Z`–`2026-09-12T11:36:02Z`, native x86_64/OpenCode `1.18.30`,
dirty commit `59534faf1cdce493bc51a11d4adbea5e5b2d6892`, and is **Pass** for the
canonical-description, six Ponytail-command, three-profile, configuration, and
credential checks. `.dev-venv/bin/python scripts/validate_docs.py` is also **Pass** for
`8` categories and `11` topics at `2026-09-12T12:13:23Z`. No M06 acceptance or
`EXP-M06` checkpoint is claimed by this reconciliation.

The current `LUNA MAX docs` profile cannot edit `docs/**`; `SOL HIGH` performed the
authored documentation repairs there. This profile gap remains recorded and does not
create independent documentation-skill or M06 verification.
