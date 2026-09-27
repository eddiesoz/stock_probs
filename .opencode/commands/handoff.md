---
description: Prepare a concise project handoff without restoring HANDOFF.md.
agent: build
subagent: false
---

Prepare a fresh-session handoff for this project without changing repository history.

1. Read `AGENTS.md`, `MVP-PLAN.md`, and `MVP-ROADMAP.md` in full first. Treat those
   three files as authoritative for repository rules, requirements, status, and
   evidence. Preserve their historical entries; do not rewrite history to make a
   current state look cleaner.
2. Inspect `git status --short`, the active branch, `git log --oneline -6`, and the
   changed paths. Read `HANDOFF.md` only if it exists. If it is deleted or absent,
   never restore, checkout, or recreate `HANDOFF.md`; report that fact instead.
3. Produce a concise response containing the current task, completed work, pending
   work, exact checks and artifacts, blockers, risks, and the next bounded action.
   Separate implementation claims from independent evidence and retain every
   supplied limitation. State native x86_64 versus emulated ARM64 explicitly;
   never infer physical/native ARM64, physical-mobile, screen-reader, or true-zoom
   evidence from an unavailable or emulated check.
4. If a documentation gate is relevant, report its exact command and result. Do not
   edit documentation owned by another agent, commit, push, or install hooks.
