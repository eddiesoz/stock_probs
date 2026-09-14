---
title: "Writing Documentation — READMEs, API Docs, ADRs, Project Docs"
impact: HIGH
impactDescription: "Ensures docs stay current, complete, and follow project conventions"
tags: [documentation, readme, adr, api-docs, getting-started]
---

## Writing Documentation

## 🔴 HARD RULEs

### operations/getting-started.md Required
Every project MUST have `docs/operations/getting-started.md` covering setup from scratch: prerequisites, clone and install, build steps, editor/IDE configuration, starting the app, verification checks, troubleshooting.

### develop/variables.md Required
Every project MUST have `docs/develop/variables.md` documenting ALL environment variables. Each entry lists: variable name, default value, which files use it, brief description.

### Per-Feature Guides Required
Every project with multiple features MUST have `docs/usage/`, `docs/configure/`, and `docs/operations/` with one `.md` file per feature. Each covers: what it does, how to use, API endpoints, code location, related docs.

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

### Architecture Decision Records (ADRs)

For significant architectural decisions, create `docs/adr/NNNN-title.md`:
```markdown
# ADR-0001: Title
**Status:** proposed | accepted | deprecated | superseded
**Date:** YYYY-MM-DD
**Context:** What problem?
**Decision:** What we decided.
**Consequences:** Tradeoffs.
```

### Incremental Updates

When a specific change was made, update only the affected docs:

| Change | Docs to update |
|--------|---------------|
| Added/removed/modified a skill | `docs/concepts/architecture.md` (skill count, directory map), `docs/concepts/skill-system.md` |
| Added/removed/modified an agent | `docs/configure/agents.md` (agent table, profiles) |
| Changed config | `docs/concepts/architecture.md`, `docs/concepts/tech-stack.md` |
| Added new dependencies | `docs/concepts/tech-stack.md` |
| Modified self-learning system files | `.opencode/skills/self-learning/SKILL.md`, `docs/concepts/self-learning.md` (update reference), affected `.opencode/agents/**` profiles for role instructions |
