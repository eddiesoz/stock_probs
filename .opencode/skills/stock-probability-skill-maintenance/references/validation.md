---
title: "Skill maintenance validation"
impact: HIGH
impactDescription: "Verifies project skill governance, metadata, references, links, and repository hygiene without self-acceptance."
tags: [skills, validation, governance, checks]
---

## Skill maintenance validation

From the repository root, run the narrow checks first and preserve the first failure:

```bash
.dev-venv/bin/python scripts/validate_docs.py
.dev-venv/bin/python -m pytest tests/test_docs_validation.py
.dev-venv/bin/python scripts/comment_audit.py
.dev-venv/bin/python -m ruff check scripts/validate_docs.py tests/test_docs_validation.py
git diff --check
```

The commands above are deterministic static catalog, metadata, link, comment, and hygiene checks.
Static repository validation only: the project catalog, metadata, `SKILL-INDEX.md`, and archived
ledger are explicit repository-governance contracts. They are not runtime evidence and do not prove
that native V2 has discovered or loaded a skill. Do not report runtime discovery from static files,
generated indexes, configuration parsing, or agent inspection.

The documentation validator must continue to fail closed for the fixed authored-documentation
taxonomy, canonical skill descriptions, catalog membership, quoted frontmatter, name/directory
parity, metadata, exact references, the 500-line limit, relative links and anchors, stale status
wording, and high-confidence secret patterns. Its mutation tests must include an unexpected skill,
a missing admitted skill, and a frontmatter name mismatch.

Report exact commands, environment, UTC, revision, pass/fail/unavailable result, and residual
limitations. Validation is implementation evidence only: do not mutate Git or claim independent
QA, export completion, remote verification, or acceptance.
