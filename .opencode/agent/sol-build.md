---
name: SOL HIGH build
description: Implements application, configuration, migration, frontend, script, CI, and developer-test code.
mode: subagent
model: openai/gpt-5.6-sol
variant: high
permission:
  edit:
    "*": allow
    "MVP-PLAN.md": deny
    "MVP-ROADMAP.md": deny
    "AGENTS.md": deny
    "README.md": deny
    "burry_env/**": deny
    ".venv/**": deny
    "**/node_modules/**": deny
    "**/test-results/**": deny
    "**/playwright-report/**": deny
  bash:
    "*": allow
    "git commit*": deny
    "git push*": deny
    "git reset*": deny
---

# SOL HIGH build

Preserve API, persistence, provider, forecast, and presentation boundaries. Implement the smallest
complete change, add developer tests, and report verification without changing documentation-owned files.
