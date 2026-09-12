---
title: "Skill maintenance validation"
impact: HIGH
impactDescription: "Verifies catalog admission, metadata, references, links, discovery, and repository hygiene without self-acceptance."
tags: [skills, validation, discovery, checks]
---

## Skill maintenance validation

From the repository root, run the narrow checks first and preserve the first failure:

```bash
.dev-venv/bin/python scripts/validate_docs.py
.dev-venv/bin/python -m pytest tests/test_docs_validation.py
opencode debug skill
.dev-venv/bin/python scripts/comment_audit.py
.dev-venv/bin/python -m ruff check scripts/validate_docs.py tests/test_docs_validation.py
git diff --check
```

Use a fresh isolated OpenCode process for discovery after changing a skill. Confirm both admitted
names and canonical descriptions are present; unrelated built-in or configured extension skills
do not become project-catalog entries. A parent-process restart and independent post-restart check
remain required before discovery can satisfy a gate.

The documentation validator must continue to fail closed for the fixed authored-documentation
taxonomy, canonical skill descriptions, catalog membership, quoted frontmatter, name/directory
parity, metadata, exact references, the 500-line limit, relative links and anchors, stale status
wording, and high-confidence secret patterns. Its mutation tests must include an unexpected skill,
a missing admitted skill, and a frontmatter name mismatch.

Report exact commands, environment, UTC, revision, pass/fail/unavailable result, and residual
limitations. Validation is implementation evidence only: do not mutate Git or claim independent
QA, export completion, remote verification, or acceptance.
