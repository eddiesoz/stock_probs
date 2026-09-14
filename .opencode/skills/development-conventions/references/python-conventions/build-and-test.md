---
title: "Build and Test Commands — Default Fallback Commands for Python Projects"
impact: HIGH
impactDescription: "Ensures consistent lint/format/type-check/test workflow across any Python project"
tags: [python, build, test, commands, workflow]
---

## Build & Test Commands

Ask for the project's build commands if not obvious. Default fallbacks:

- **Lint:** `ruff check .`
- **Format:** `ruff format .` (run after linting)
- **Type check:** `mypy src/` (or `mypy .` in simpler projects)
- **Test:** `pytest` (or `python -m pytest`)
- **Full check (in order):** `ruff check . && ruff format --check . && mypy src/ && pytest`
