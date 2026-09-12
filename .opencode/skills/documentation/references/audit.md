---
title: "Documentation audit workflow"
impact: HIGH
impactDescription: "Makes taxonomy, frontmatter, links, skill metadata, and credential checks deterministic while retaining manual accuracy review."
tags: [audit, validation, links, metadata, secrets]
---

## Documentation audit workflow

Run the repository validator from the project root:

```bash
.dev-venv/bin/python scripts/validate_docs.py
```

It fails nonzero for missing/extra taxonomy paths, invalid `title`/`description` frontmatter,
non-lowercase topic names, stale root-state wording, missing or duplicate index links, unresolved
files or heading anchors, root-absolute local links, skill name/path/reference drift, frontmatter
and catalog-metadata mismatch, active `SKILL.md` files over 500 lines, or high-confidence
credential material.

The project catalog metadata is an audited mirror, not a second discovery mechanism. OpenCode's
stock skill loader discovers `SKILL.md` frontmatter; `alwaysApply` remains `false` because this
skill is selected for documentation work, and the ordered tags are catalog search terms.

Then manually check what syntax cannot prove:

1. Compare behavioral claims with the current source and developer tests.
2. Confirm root status edits do not change unrelated evidence or claim independent acceptance.
3. Review topic prose for unnecessary repetition that syntax cannot identify reliably.
4. Review examples for safe placeholders, bounded commands, and no private machine paths.
5. Inspect `git diff --check`, `git diff --stat`, and intended changed paths.
6. Record the actual pre-change revision and leave the post-change checkpoint pending until the
   coordinator creates and verifies it.

If the skill itself changed, regenerate `.opencode/SKILL-INDEX.md`, update
`.opencode/skills/learnings.md`, and search agent profiles for stale skill references. Do not
call an unavailable MCP service or fabricate an observation receipt. Because skills load at
process start, require a parent restart and independent post-restart discovery check before
claiming the live OpenCode process uses the new skill.
