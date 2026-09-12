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

This repair uses declared `SOL HIGH` documentation scope because the `LUNA MAX docs` profile
currently lacks `docs/**` edit permission. The profile and configuration are unchanged, and
independent documentation closure/restart verification remains pending.

The validator checks heading anchors, high-confidence credential patterns, duplicate taxonomy
links, exact description parity between the skill frontmatter, project catalog metadata, and
skill index, and the active skill's 500-line limit. Prose duplication is a manual review rather
than a validator heuristic. The catalog keeps the skill opt-in; OpenCode discovery uses the
`SKILL.md` frontmatter rather than catalog metadata.
