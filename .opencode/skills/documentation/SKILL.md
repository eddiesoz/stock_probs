---
name: "documentation"
description: "Author and audit Stock Probability documentation while preserving authoritative sources, generated exports, taxonomy, links, metadata, and evidence-backed status. Use when writing or reorganizing guides, documenting application behavior, validating documentation, or reconciling evidence-supported wording."
---

# Stock Probability documentation

Use this project skill for authored documentation and documentation audits. It uses a split
structure: this file holds the non-negotiable source boundaries and workflow; detailed checks
live in `references/`.

## When to use

- Add or revise a page beneath `docs/`.
- Update documentation navigation or the authored taxonomy.
- Document application architecture, forecast semantics, configuration, development,
  operations, API behavior, security, or dashboard usage.
- Reconcile root documentation with facts already established by an evidence record.
- Audit frontmatter, index coverage, relative links, skill metadata, or credential-like content.

## Hard rules

### Preserve authoritative and generated boundaries

- `MVP-PLAN.md` owns the product contract and detailed evidence ledger.
- `MVP-ROADMAP.md` owns dependency ordering and milestone status summaries.
- `AGENTS.md` owns repository rules; `README.md` is the concise root landing page.
- `docs/` explains stable behavior and links to root records instead of copying their ledgers.
- Root `SESSION-EXPORT.md` is generated and export-gate-owned. Never move it beneath `docs/`,
  edit it as prose, or cite its mere presence as acceptance.

### Keep one topic per page

Every authored `docs/**/*.md` file has quoted `title` and `description` frontmatter. Category
folders and topic filenames are lowercase and hyphenated; each category has an `index.md`.
Indexes navigate. Topic pages explain. Do not add empty sections for visual symmetry.

### Report status from evidence only

Never advance a milestone, invent a task result, guess a commit hash, or turn generated files,
implementation presence, self-validation, an emulated architecture, or a research session into
independent acceptance. Keep `Fail`, `Skipped`, `Unavailable`, `Blocked`, and `Pending` visible.

### Keep examples safe and local

Use relative Markdown links and deterministic fixture values or explicit placeholders. Do not
write credentials, private machine paths, endpoint secrets, raw provider failures, or database
paths into browser-facing examples. The browser's application data boundary remains `/api/v1`.

## Workflow

1. Read [`references/repository-sources.md`](references/repository-sources.md) to choose the
   authoritative source for each statement.
2. Read [`references/authoring.md`](references/authoring.md) before creating or moving a page.
3. Verify behavior in the current source; do not infer it from a stale guide.
4. Make the smallest complete documentation change and update the relevant indexes.
5. Run the process in [`references/audit.md`](references/audit.md).
6. Report changed paths, exact commands/results, the actual current revision, and limitations.
   A skill/configuration-time change requires a parent OpenCode restart and independent
   post-restart validation before discovery can count toward a gate.

## Reference files

| File | Purpose |
| --- | --- |
| [`references/repository-sources.md`](references/repository-sources.md) | Authoritative root, source-code, and generated-export boundaries. |
| [`references/authoring.md`](references/authoring.md) | Page placement, frontmatter, linking, and concise content rules. |
| [`references/audit.md`](references/audit.md) | Deterministic validation, manual review, and honest handoff workflow. |

## Project entry points

- [`../../../docs/index.md`](../../../docs/index.md) — authored documentation index.
- [`../../../README.md`](../../../README.md) — repository landing page.
- [`../../../MVP-PLAN.md`](../../../MVP-PLAN.md) — authoritative contract/evidence ledger.
- [`../../../MVP-ROADMAP.md`](../../../MVP-ROADMAP.md) — authoritative roadmap/status view.
