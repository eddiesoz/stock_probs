---
title: "Git Ignore Conventions — Patterns, Structure, and Rules"
impact: MEDIUM
impactDescription: "Prevents accidental commits of secrets, build artifacts, and dependencies"
tags: [gitignore, git, patterns, security]
---

## Git Ignore Conventions

## 🔴 HARD RULE — `.gitignore` Must Be Present and Complete

Every project MUST have a `.gitignore` at the root. After scaffolding, after adding new tooling, after changing build outputs — check `.gitignore` is up to date.

### Structure

```
# ── OS Files ──────────────────────────────────────────
.DS_Store
Thumbs.db

# ── Editor / IDE ──────────────────────────────────────
.idea/

# ── Dependencies ──────────────────────────────────────
node_modules/
vendor/

# ── Build Output ──────────────────────────────────────
dist/
build/
*.tsbuildinfo

# ── Environment / Secrets ─────────────────────────────
.env
.env.*
!.env.example

# ── Runtime / Cache ───────────────────────────────────
*.log
.cache/
.tmp/

# ── Generated ─────────────────────────────────────────
*.generated.*
```

- Group by category with section headers
- One pattern per line, directory patterns end with `/`

### What Must Be Ignored

| Category | Examples | Why |
|----------|----------|-----|
| **Secrets** | `.env`, `*.pem`, `credentials.json` | Never commit credentials |
| **Dependencies** | `node_modules/`, `__pycache__/` | Reproducible from lockfiles |
| **Build output** | `dist/`, `build/`, `out/` | Generated, not source |
| **Runtime artifacts** | `*.log`, `.cache/`, `coverage/` | Ephemeral |

### What Should NOT Be Ignored

| Category | Examples | Why |
|----------|----------|-----|
| **Lockfiles** | `package-lock.json`, `Cargo.lock`, `go.sum` | Reproducible builds |
| **Example configs** | `.env.example` | Documents needed vars without exposing secrets |
| **Dockerfiles** | `Dockerfile`, `docker-compose.yml` | Infrastructure as code |

### Language-Specific

- **Node.js/TypeScript**: `node_modules/`, `dist/`, `.env`, `*.tsbuildinfo`, `coverage/`
- **Python**: `__pycache__/`, `*.pyc`, `.venv/`, `dist/`, `*.egg-info/`, `.env`
- **Go**: `*.exe`, `*.test`, `*.out`
- **Rust**: `target/`, `.env`
- **Next.js**: `.next/`, `out/`, `.env*.local`

### After Editing

1. Run `git status` — verify no unintended files are tracked
2. Run `git ls-files --ignored --exclude-standard` — verify intended files are ignored
3. If secrets were accidentally committed, rotate them immediately
