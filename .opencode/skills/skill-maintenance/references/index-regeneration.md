---
title: "Skill index regeneration"
impact: HIGH
impactDescription: "Keeps the human-readable skill index in exact parity with the approved fail-closed catalog."
tags: [skills, index, catalog, parity]
---

## Skill index regeneration

Treat `APPROVED_SKILL_CATALOG` in `scripts/validate_docs.py` as the admission list. Skill
directories are checked against it; they do not expand it automatically.

For each catalog entry, copy the exact name, path, and canonical description into one table row in
`.opencode/SKILL-INDEX.md`. Add one numbered directory-list entry in catalog order. Set the header
count to the number of admitted entries. Each `skills/<name>/SKILL.md` link therefore appears
exactly twice.

Run `scripts/validate_docs.py` rather than maintaining a generator or adding a dependency. The
validator rejects missing or unexpected skill directories, stale counts, non-canonical rows,
missing listings, and extra skill links. Index regeneration changes repository files only; it
does not update remote services, commit, push, or export the result.
