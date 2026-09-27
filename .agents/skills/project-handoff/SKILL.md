---
name: project-handoff
description: Prepare a concise Stock Probability fresh-session handoff from repository rules, plans, and observed Git state. Use when asked for a handoff or session summary.
---

# Project handoff

Read `AGENTS.md`, `MVP-PLAN.md`, and `MVP-ROADMAP.md` as the authoritative rules, requirements, and evidence. Preserve historical entries. Read `HANDOFF.md` only if it exists; never restore or recreate it if deleted.

Inspect `git status --short`, the active branch, `git log --oneline -6`, and changed paths without changing Git state. Summarize the current task, completed and pending work, exact checks and artifacts, blockers, risks, and the next bounded action. Keep implementation distinct from independent verification. Label native x86_64 and emulated ARM64 separately, and retain unavailable physical ARM64, mobile, screen-reader, or zoom evidence. Report the exact documentation-gate command and result when relevant. Do not edit files, install hooks, commit, or push.
