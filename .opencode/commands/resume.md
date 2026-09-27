---
description: Resume the authoritative project task with todo tracking.
agent: build
subagent: false
---

Resume the project task from its authoritative repository state.

1. Read `AGENTS.md`, `MVP-PLAN.md`, and `MVP-ROADMAP.md` in full before acting;
   they are authoritative for rules, requirements, status, evidence, and the
   next gate. Preserve historical entries rather than replacing or backdating them.
   Read `HANDOFF.md` in full only when it exists. If it was deleted or is absent,
   never restore, checkout, or recreate it; use the three authoritative files and
   live repository state instead.
2. Inspect the active branch, `git log --oneline -6`, `git status --short`, and
   changed paths read-only. Preserve unrelated dirty work and user files. Do not
   treat generated artifacts, implementation presence, or a builder report as
   independent acceptance evidence.
3. Before taking any action, create or refresh the todo list with the native todo
   tool. Keep exactly one item `in_progress`; mark an item completed only after its
   exact verification passes. Record blockers as `pending`, not as passes.
4. Continue only the unambiguous pending task, using the smallest bounded change
   and the applicable project skill. If the task is complete or ambiguous, report
   the state and ask what should happen next rather than guessing.
5. Report each check as exactly one of `Pass`, `Fail`, `Skipped`, or `Unavailable`,
   with the exact command, revision, environment/architecture, UTC window, result,
   artifact path, and limitation. Native x86_64, emulated ARM64, and physical
   hardware evidence are distinct; emulation never proves native or physical
   ARM64 performance.
