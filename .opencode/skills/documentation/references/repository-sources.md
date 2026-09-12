---
title: "Repository documentation sources"
impact: HIGH
impactDescription: "Prevents authored guides from replacing contracts, evidence ledgers, generated exports, or current implementation truth."
tags: [documentation, sources, evidence, export]
---

## Repository documentation sources

Choose the source by claim type before writing.

| Claim | First authority | Supporting source |
| --- | --- | --- |
| Product requirement or acceptance row | `MVP-PLAN.md` | `AGENTS.md` invariants |
| Milestone order or status summary | `MVP-ROADMAP.md` | exact plan ledger |
| Ownership or evidence protocol | `AGENTS.md` | plan workflow |
| Current route/schema behavior | `src/stock_probs/api.py` and `schemas.py` | API tests and live OpenAPI from the same revision |
| Forecast calculation | `src/stock_probs/domain.py` | domain tests |
| Provider behavior and archive bounds | `src/stock_probs/provider.py` | provider tests |
| Persistence and migration behavior | `repository.py` plus packaged migrations | repository/migration tests |
| Backup and restore behavior | `backup.py` and `cli.py` | backup/CLI tests |
| Dashboard controls and states | static HTML/JS/CSS | checked-in browser tests |
| User/developer explanation | relevant `docs/` topic | link back to authority when status-sensitive |

`SESSION-EXPORT.md` is a generated full-session checkpoint artifact. It may be linked as an
artifact only where the exact evidence record authorizes that link. Do not normalize it into
authored taxonomy, extract unverified claims from it, or edit it during documentation work.

Research sessions, builder summaries, screenshots, test-result directories, and package
artifacts are source observations until the required independent review records them. Preserve
that distinction in wording such as “implemented”, “self-validation passed”, “independently
verified”, and “checkpoint completed”. These terms are not interchangeable.
