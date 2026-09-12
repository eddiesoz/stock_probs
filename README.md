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

As of 2026-09-11:

- `M00`, `EXP-M00`, `M01`, `EXP-M01`, `M02`, `EXP-M02`, `M03`, and `EXP-M03` are
  **Completed** for their recorded scopes. `EXP-M03` is verified at exact local and
  remote SHA `777451643b5ec1a04a37c013a9caf59f0bd58122`.
- `M04` is **Completed** for its exercised dashboard/history functional scope. Only
  `EXP-M04` is **In progress**.
- `R-M04-30` remains **Pending** because actual screen-reader evidence is
  **Unavailable** and deferred to M06. Axe, keyboard, and MCP evidence do not replace it.
- `M05` and `M06` are **Blocked**. `M07`, `M08`, `ASTRA-FINAL`, and `EXP-FINAL` are
  **Pending**. No native/physical ARM64 performance result or external CI result is claimed.
- M06's deterministic native-x86 app/UI performance gate is future work, not a current
  result. Existing thresholds are process RSS `<500 MiB`, fixture/cache-hit forecast p95
  `<1 s`, and indexed 100,000-history query p95 `<250 ms`; `negligible` idle CPU remains
  qualitative. Proposed M06 rows add five warmups plus at least 30 measured requests,
  60-second idle CPU `<=1 core-percent`, readiness within `20 s`, package/build and
  backup/restore baselines/bounds, static shell/assets `<96 KiB`, a designated response
  `<8 KiB`, and pinned browser render/interaction/layout/request budgets. Each check needs
  a structured artifact and named independent reviewer; emulated ARM64 never supplies
  performance evidence.

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
gate. Authored-docs taxonomy implementation remains **Pending** after the future clean
pre-skill `EXP-M04` checkpoint; no skill, code/configuration, export, or new documentation
file or Git checkpoint is created by this reconciliation.
