---
description: Implements application and test changes without touching documentation, generated outputs, environments, or Git history.
mode: subagent
model: openai/gpt-5.6-luna#max
permissions:
  - action: "*"
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
    resource: "*"
    effect: allow
  - action: edit
    resource: "AGENTS.md"
    effect: deny
  - action: edit
    resource: "README.md"
    effect: deny
  - action: edit
    resource: "MVP-PLAN.md"
    effect: deny
  - action: edit
    resource: "MVP-ROADMAP.md"
    effect: deny
  - action: edit
    resource: "*.md"
    effect: deny
  - action: edit
    resource: "**/*.md"
    effect: deny
  - action: edit
    resource: "*.mdx"
    effect: deny
  - action: edit
    resource: "**/*.mdx"
    effect: deny
  - action: edit
    resource: "docs/**"
    effect: deny
  - action: edit
    resource: ".git/**"
    effect: deny
  - action: edit
    resource: "**/.git/**"
    effect: deny
  - action: edit
    resource: "*.env"
    effect: deny
  - action: edit
    resource: "*.env.*"
    effect: deny
  - action: edit
    resource: "**/*.env"
    effect: deny
  - action: edit
    resource: "**/*.env.*"
    effect: deny
  - action: edit
    resource: ".venv/**"
    effect: deny
  - action: edit
    resource: ".dev-venv/**"
    effect: deny
  - action: edit
    resource: "burry_env/**"
    effect: deny
  - action: edit
    resource: "**/.venv/**"
    effect: deny
  - action: edit
    resource: "**/.dev-venv/**"
    effect: deny
  - action: edit
    resource: "**/burry_env/**"
    effect: deny
  - action: edit
    resource: "node_modules/**"
    effect: deny
  - action: edit
    resource: "**/node_modules/**"
    effect: deny
  - action: edit
    resource: "vendor/**"
    effect: deny
  - action: edit
    resource: "**/vendor/**"
    effect: deny
  - action: edit
    resource: "generated/**"
    effect: deny
  - action: edit
    resource: "**/generated/**"
    effect: deny
  - action: edit
    resource: "dist/**"
    effect: deny
  - action: edit
    resource: "**/dist/**"
    effect: deny
  - action: edit
    resource: "build/**"
    effect: deny
  - action: edit
    resource: "**/build/**"
    effect: deny
  - action: edit
    resource: "out/**"
    effect: deny
  - action: edit
    resource: "**/out/**"
    effect: deny
  - action: edit
    resource: ".next/**"
    effect: deny
  - action: edit
    resource: "**/.next/**"
    effect: deny
  - action: edit
    resource: "coverage/**"
    effect: deny
  - action: edit
    resource: "**/coverage/**"
    effect: deny
  - action: edit
    resource: "test-results/**"
    effect: deny
  - action: edit
    resource: "**/test-results/**"
    effect: deny
  - action: edit
    resource: "playwright-report/**"
    effect: deny
  - action: edit
    resource: "**/playwright-report/**"
    effect: deny
  - action: edit
    resource: "*.generated.*"
    effect: deny
  - action: edit
    resource: "**/*.generated.*"
    effect: deny
  - action: shell
    resource: "*"
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
  - action: execute
    resource: "*"
    effect: allow
  - action: playwright_*
    resource: "*"
    effect: allow
  - action: subagent
    resource: "*"
    effect: deny
  - action: skill
    resource: "*"
    effect: deny
  - action: skill
    resource: browser-qa
    effect: allow
  - action: skill
    resource: database-conventions
    effect: allow
  - action: skill
    resource: development-conventions
    effect: allow
  - action: skill
    resource: local-gate-evidence
    effect: allow
  - action: skill
    resource: security-audit
    effect: allow
  - action: skill
    resource: stock-probability-skill-maintenance
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

# Luna build

Implement the assigned change and its developer tests. You may edit application and test source broadly,
but never edit documentation, environment directories or files, vendor trees, generated outputs, or Git
metadata. Do not launch nested subagents or mutate Git history, the index, branches, tags, or remotes.
Run the narrowest useful checks and report exact commands, paths, failures, and residual risks.
