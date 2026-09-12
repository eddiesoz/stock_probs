---
title: "Approved skill retirement"
impact: HIGH
impactDescription: "Removes obsolete guidance without leaving stale discovery, links, or catalog entries."
tags: [skills, retirement, references, boundaries]
---

## Approved skill retirement

Retire a skill only when an explicit requirement approves removal and repository evidence shows
that its workflow is obsolete or fully covered elsewhere.

1. Search the catalog, index, project skills, agent profiles, commands, and authored documentation
   for the exact name and path.
2. Identify any current instruction that must move to an already admitted skill; do not create a
   replacement merely for symmetry.
3. Remove the skill directory, its `APPROVED_SKILL_CATALOG` entry, and both exact index entries in
   the same owned change.
4. Run the complete validation workflow and report references outside the task boundary to their
   owner instead of editing them opportunistically.

Never rewrite historical evidence to erase a retired skill. Never stage, commit, push, export, or
use an external state service as part of retirement; the normal `EXP-*` gate handles the reviewed
repository checkpoint.
