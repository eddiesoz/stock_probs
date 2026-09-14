---
title: "Documentation"
description: "Repository rules for authored pages, authoritative root records, generated exports, taxonomy links, and deterministic audits."
---

# Documentation

Authored guides live under `docs/` in task-oriented categories. Every page has `title` and
`description` frontmatter, one primary topic, a lowercase hyphenated filename, and relative
links. Category `index.md` pages provide navigation rather than duplicating topic prose.

## Source boundaries

- [`MVP-PLAN.md`](../../MVP-PLAN.md) is the authoritative contract and evidence ledger.
- [`MVP-ROADMAP.md`](../../MVP-ROADMAP.md) is the authoritative dependency/status summary.
- [`AGENTS.md`](../../AGENTS.md) controls repository ownership and evidence discipline.
- [`README.md`](../../README.md) is the root landing page and concise quick start.
- [`SESSION-EXPORT.md`](../../SESSION-EXPORT.md) is generated and overwritten only by export
  gates. Never move it into `docs/` or edit it as authored prose.

Guides should explain stable behavior and link to root records for volatile milestone facts.
Do not copy evidence bundles, fabricate a future revision, or convert implementation presence
into acceptance. A code example must use placeholders or deterministic public fixture values,
not credentials, private paths, or copied runtime output.

## Audit workflow

1. Identify the single category and topic before adding a page.
2. Check source code for behavior and root ledgers for contract/status claims.
3. Add the page to its category index and ensure the root documentation index reaches it.
4. Run `.dev-venv/bin/python scripts/validate_docs.py`.
5. Review the changed paths and record the actual pre-change and post-change checkpoint states.

The project `documentation` skill contains the agent-facing version of this workflow. Skill
or configuration-time changes require an OpenCode restart before discovery can be validated;
the editing session itself is not proof that the restarted process loaded them.

`R-ASTRA-70` is **Completed** for its declared documentation-only portable-link repair: eight
ignored-artifact links were changed to inline code. The current `R-ASTRA-71` documentation
reconciliation records the named initial ASTRA failure, the `R-ASTRA-66`–`R-ASTRA-69` repair
progression, the clean final `R-ASTRA-69` Ponytail boundary, independent repair QA, and the
accepted final ASTRA scope. The earlier `R-ASTRA-64` reconciliation remains historical. The
current final ASTRA session is `ses_f622707a4ffeAE3Zx8Lt2zYiC1`, reviewer `ASTRA`, model
`openai/gpt-6-astra`, on native x86_64 with official MCP/headless Chromium `153.0.8010.12`,
reviewing `/` and `/api/v1/docs` at `320x844` and `1280x1000` in Light and Dark; its scope is
accepted with no blockers. Physical mobile, actual screen-reader, true-zoom, fresh ASTRA
axe/screenshots, and native/physical ARM64-performance evidence remain unavailable. Local and
ignored artifact paths in documentation remain inline code, never Markdown links.

`R-ASTRA-72` records the validated rename to exact `Orchestrator` and the required parent-process
restart. Independent post-restart QA passed the declared rename/restart-validation scope; full
evidence and limitations are recorded in [`docs/evidence/astra-final-report.md`](../evidence/astra-final-report.md).
No release, export, commit, push, or remote result is implied.

The existing `development-conventions` skill is explicitly admitted as the eighth opt-in project
skill, and fresh discovery is recorded as **Pass**. Skill/profile activation still requires a
parent OpenCode restart and independent post-restart discovery; implementation presence does not
create that gate effect.

The validator checks heading anchors, high-confidence credential patterns, duplicate taxonomy
links, exact description parity between the skill frontmatter, project catalog metadata, and
skill index, and the active skill's 500-line limit. Prose duplication is a manual review rather
than a validator heuristic. The catalog keeps the skill opt-in; OpenCode discovery uses the
`SKILL.md` frontmatter rather than catalog metadata.
