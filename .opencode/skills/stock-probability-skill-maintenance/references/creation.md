---
title: "Approved skill creation"
impact: HIGH
impactDescription: "Keeps each admitted project skill discoverable, bounded, and represented once in the catalog."
tags: [skills, creation, frontmatter, metadata]
---

## Approved skill creation

After explicit approval, choose one lowercase-hyphenated name and create a direct child of
`.opencode/skills/` containing:

```text
<name>/
  SKILL.md
  metadata.json
  references/
```

`SKILL.md` starts with only quoted `name` and `description` scalars. The name exactly matches the
directory; the description states actions and invocation triggers. Keep the file at 500 lines or
fewer and move detailed procedures into the smallest useful set of linked reference files.

As `SOL HIGH build`, add one explicit definition to `APPROVED_SKILL_CATALOG` in
`scripts/validate_docs.py`, including the canonical description, ordered tags, and exact reference
filenames. Mirror the name and description in `metadata.json`, retain `alwaysApply: false`, and add
exact table and numbered-list entries to the project skill index at `.opencode/SKILL-INDEX.md`.
Update `.opencode/skills/learnings.md` only with evidence established by the task. A docs owner
reports these changes instead of making them.

Do not add agent grants, application configuration, services, dependencies, or authored
documentation unless a separate owner and requirement explicitly include them. Do not stage files
in the Git index, commit, push, or export; those remain coordinator-owned gates.
