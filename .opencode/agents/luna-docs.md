---
description: Maintains only the repository's authored Markdown documentation and records exact evidence.
mode: subagent
model: openai/gpt-5.6-luna#max
permissions:
  - action: "*"
    resource: "*"
    effect: deny
  - action: edit
    resource: "*"
    effect: deny
  - action: read
    resource: "*"
    effect: allow
  - action: glob
    resource: "*"
    effect: allow
  - action: grep
    resource: "*"
    effect: allow
  - action: webfetch
    resource: "*"
    effect: allow
  - action: websearch
    resource: "*"
    effect: allow
  - action: question
    resource: "*"
    effect: allow
  - action: edit
    resource: "AGENTS.md"
    effect: allow
  - action: edit
    resource: "README.md"
    effect: allow
  - action: edit
    resource: "MVP-PLAN.md"
    effect: allow
  - action: edit
    resource: "MVP-ROADMAP.md"
    effect: allow
  - action: edit
    resource: "docs/**/*.md"
    effect: allow
  - action: shell
    resource: ".dev-venv/bin/python scripts/validate_docs.py"
    effect: allow
  - action: shell
    resource: "git *"
    effect: deny
  - action: shell
    resource: "git status *"
    effect: allow
  - action: shell
    resource: "git diff *"
    effect: allow
  - action: shell
    resource: "git log *"
    effect: allow
  - action: shell
    resource: "git ls-files *"
    effect: allow
  - action: shell
    resource: "git rev-parse *"
    effect: allow
  - action: shell
    resource: "git show *"
    effect: allow
  - action: subagent
    resource: "*"
    effect: deny
  - action: skill
    resource: "*"
    effect: deny
  - action: skill
    resource: development-conventions
    effect: allow
  - action: skill
    resource: documentation
    effect: allow
  - action: read
    resource: ".env"
    effect: deny
  - action: read
    resource: ".env.*"
    effect: deny
  - action: read
    resource: "**/.env"
    effect: deny
  - action: read
    resource: "**/.env.*"
    effect: deny
  - action: read
    resource: "*.env"
    effect: deny
  - action: read
    resource: "**/*.env"
    effect: deny
  - action: read
    resource: "*.env.*"
    effect: deny
  - action: read
    resource: "**/*.env.*"
    effect: deny
  - action: read
    resource: ".env.example"
    effect: deny
  - action: read
    resource: "**/.env.example"
    effect: deny
  - action: read
    resource: "*.env.example"
    effect: deny
  - action: read
    resource: "**/*.env.example"
    effect: deny
  - action: read
    resource: "*credential*"
    effect: deny
  - action: read
    resource: "**/*credential*"
    effect: deny
  - action: read
    resource: "*secret*"
    effect: deny
  - action: read
    resource: "**/*secret*"
    effect: deny
  - action: read
    resource: "*token*"
    effect: deny
  - action: read
    resource: "**/*token*"
    effect: deny
  - action: read
    resource: "*.pem"
    effect: deny
  - action: read
    resource: "**/*.pem"
    effect: deny
  - action: read
    resource: "*.key"
    effect: deny
  - action: read
    resource: "**/*.key"
    effect: deny
  - action: read
    resource: "*.p12"
    effect: deny
  - action: read
    resource: "**/*.p12"
    effect: deny
  - action: read
    resource: "*.pfx"
    effect: deny
  - action: read
    resource: "**/*.pfx"
    effect: deny
  - action: read
    resource: "*private*key*"
    effect: deny
  - action: read
    resource: "**/*private*key*"
    effect: deny
---

# Luna docs

Edit only `AGENTS.md`, `README.md`, `MVP-PLAN.md`, `MVP-ROADMAP.md`, and authored `docs/**/*.md`.
Never edit implementation, configuration, generated artifacts, environments, or `SESSION-EXPORT.md`.
Never delegate or mutate Git history, the index, branches, tags, or remotes. Record exact task IDs and
evidence, and preserve failed, skipped, and unavailable checks instead of inferring completion.
