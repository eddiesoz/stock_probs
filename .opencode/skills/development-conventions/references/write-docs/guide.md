---
title: "Writing Documentation — READMEs, API Docs, Project Docs"
impact: HIGH
impactDescription: "Ensures docs stay current, complete, and follow project conventions"
tags: [documentation, readme, api-docs, getting-started]
---

## Writing Documentation

This repository's authored documentation lives under `docs/` and follows the existing category
indexes. Before writing, use the current project sources rather than inventing a parallel guide:

- Setup and local operation: `docs/operations/getting-started.md`.
- Environment variables and local configuration: `docs/configure/local-configuration.md`.
- Documentation ownership, taxonomy, and audit workflow: `AGENTS.md` and
  `docs/develop/documentation.md`.
- Test, QA, and local-gate workflow: `docs/develop/testing.md`.
- Runtime boundaries and source ownership: `docs/concepts/architecture.md`.

## 🔴 HARD RULES

- Keep the environment-variable table and runnable configuration examples in
  `docs/configure/local-configuration.md`; do not create a second variables reference.
- Keep setup, verification, and troubleshooting in the existing getting-started page. Add a
  feature page only when the documentation taxonomy and category index have a corresponding
  topic.
- Every new or moved page must be linked from its category index and reached from `docs/index.md`.

### README.md

A good README answers these questions in order:
```markdown
# Project Name
One-line description.

## Quick Start
Fastest path to working setup. Goal: under 5 minutes.

## Usage
Common workflows with copy-pasteable examples.

## Configuration
Environment variables, config files, feature flags.

## Development
How to set up dev environment, run tests, contribute.

## Architecture
High-level overview — link to docs/concepts/architecture.md.
```

- Write for someone who just found your repo — they have 30 seconds
- Copy-pasteable examples: every code block should be runnable as-is
- Keep it current: outdated Quick Start is worse than no Quick Start

### API Documentation

For every endpoint:
```markdown
### GET /api/v1/users/:id
**Path Parameters** | **Query Parameters** | **Response (200)** | **Errors**
```

- Every endpoint, every status code, every field documented
- Request and response examples for each status code
- Authentication requirements clearly stated

For API behavior, update the existing `docs/reference/api.md` and verify the implementation and
tests on the same revision. Keep system-boundary decisions in `docs/concepts/architecture.md`
unless the project taxonomy explicitly adds another topic.

### Incremental Updates

When a specific change is made, update only the affected existing docs. Use this project map as the
first review set:

| Change | Docs to update |
|--------|---------------|
| Added, removed, or modified a project skill or OpenCode workflow | `AGENTS.md`, `docs/develop/documentation.md`, `docs/develop/testing.md`, `docs/concepts/architecture.md` when a boundary changes |
| Changed environment variables or local configuration | `docs/configure/local-configuration.md`, and `docs/concepts/architecture.md` when a runtime boundary changes |
| Changed tests, QA, local gates, or verification commands | `docs/develop/testing.md`, `docs/develop/documentation.md`, and `AGENTS.md` when policy changes |
| Changed application boundaries or packaged assets | `docs/concepts/architecture.md` and the affected topic page |
| Changed a documented API | `docs/reference/api.md` and the affected usage or operations page |

### Documentation-map gate

`documentation-map.json` is a fail-closed gate for mapped workflow and configuration changes.
When a changed path matches that map, update the listed documentation and run the read-only
checks from the repository root:

```bash
python3 scripts/check-doc-coverage.py --root . --map documentation-map.json
python3 scripts/check-doc-coverage-self-test.py
```

Run `.dev-venv/bin/python scripts/validate_docs.py` for the complete documentation validator as
well. Do not treat a missing checker, an unavailable check, or a generated artifact as coverage.
