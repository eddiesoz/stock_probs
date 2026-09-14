---
name: "stock-probability-skill-maintenance"
description: "Maintain the approved Stock Probability skill catalog by detecting justified gaps, creating or retiring project skills, regenerating the project skill index, and validating discovery and repository boundaries. Use when a project skill is added, changed, audited, indexed, or removed."
---

# Stock Probability skill maintenance

Use this project skill for bounded maintenance of the explicitly approved skill catalog. It
selectively adopts Ingenium's detection, creation, retirement, indexing, and validation workflow;
the detailed checklists live in `references/`.

## When to use

- Audit an admitted project skill after its behavior, paths, or trigger description changes.
- Evaluate a demonstrated recurring workflow as a possible project skill.
- Add, rename, or retire a skill after the repository contract explicitly approves that change.
- Regenerate the project skill index at `.opencode/SKILL-INDEX.md` and verify OpenCode discovery.

## Hard boundaries

- The catalog in `scripts/validate_docs.py` is allow-listed and fail-closed. Do not admit a skill
  from directory presence alone, and do not copy Ingenium's other skills wholesale.
- Detection produces a proposal, not an autonomous edit. Create or retire only within explicit
  task ownership and preserve the fixed nine-category authored-documentation taxonomy.
- Project skill trees, the validator catalog, `.opencode/SKILL-INDEX.md`, and
  `.opencode/skills/learnings.md` are `SOL HIGH build` changes. `LUNA MAX docs` reports findings
  in them to that owner rather than editing them.
- Never stage files in the Git index, commit, amend, push, export a session, or alter Git history,
  branches, tags, or remotes. The project skill index is a normal build-owned file; the Git index
  and coordinator-owned `EXP-*` commit/export gates remain separate and authoritative.
- Do not call or add Ingenium infrastructure, workspace mutation, observation, persistence,
  background synthesis, or state services. Repository files and local checks are sufficient.
- Keep each `SKILL.md` at 500 lines or fewer, use quoted `name` and `description` frontmatter,
  match the lowercase-hyphenated directory exactly, and place detail in linked references.
- A changed skill is not live-process evidence. Require a fresh parent OpenCode process and an
  independent discovery check before it can affect a gate.

## Workflow

1. Use [`references/detection.md`](references/detection.md) to establish a non-speculative need.
2. Follow [`references/creation.md`](references/creation.md) for an approved addition or update.
3. Follow [`references/retirement.md`](references/retirement.md) for an approved removal.
4. Rebuild the exact catalog view with
   [`references/index-regeneration.md`](references/index-regeneration.md).
5. Run every applicable check in [`references/validation.md`](references/validation.md) and
   report failures or unavailable evidence without inferring acceptance. End with a coordinator
   handoff; this workflow never requires or performs its own commit.

## Reference files

| File | Purpose |
| --- | --- |
| [`references/detection.md`](references/detection.md) | Evidence threshold for proposing skill work. |
| [`references/creation.md`](references/creation.md) | Minimal approved skill structure and catalog registration. |
| [`references/retirement.md`](references/retirement.md) | Reference-safe removal without Git or export mutations. |
| [`references/index-regeneration.md`](references/index-regeneration.md) | Exact catalog-to-index parity procedure. |
| [`references/validation.md`](references/validation.md) | Deterministic validator, discovery, and quality checks. |

## Related project skill

- [`../documentation/SKILL.md`](../documentation/SKILL.md) owns authored documentation and its
  fixed taxonomy.
