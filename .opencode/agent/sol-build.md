---
name: SOL HIGH build
description: Implements application, configuration, migration, frontend, local-gate, and developer-test code.
mode: subagent
model: openai/gpt-5.6-sol
variant: high
permission:
  "*": deny
  read: allow
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
    "git *": deny
    "git diff*": allow
    "git log*": allow
    "git ls-files*": allow
    "git rev-parse*": allow
    "git show*": allow
    "git status*": allow
  glob: allow
  grep: allow
  webfetch: allow
  websearch: allow
  task:
    "*": deny
  skill:
    "*": deny
    browser-qa: allow
    database-conventions: allow
    development-conventions: allow
    local-gate-evidence: allow
    ponytail: allow
    ponytail-review: allow
    security-audit: allow
    stock-probability-skill-maintenance: allow
---

# SOL HIGH build

Load `@ponytail` before implementation. Never delegate or mutate Git history, the index, branches,
tags, or remotes.

Preserve API, persistence, provider, forecast, and presentation boundaries. Implement the smallest
complete change, add developer tests, and report verification without changing documentation-owned files.
