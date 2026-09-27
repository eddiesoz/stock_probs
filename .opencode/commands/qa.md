---
description: Independently verify changed paths and report bounded QA evidence.
agent: luna-qa
subagent: true
---

Perform independent, verification-only QA for the current project change.

1. Read `AGENTS.md`, `MVP-PLAN.md`, and `MVP-ROADMAP.md` in full. Inspect the
   active branch, revision, and changed paths using `origin/main...HEAD`, falling
   back to `HEAD~1`; if neither exists, use the current working-tree diff. Never
   restore a deleted `HANDOFF.md`, rewrite historical entries, mutate Git history,
   or edit implementation/configuration files.
2. Select only the scoped commands required by the changed paths, and run those
   checks independently before any aggregate gate. Use the smallest applicable
   commands: `src/**`, `tests/**`, and Python configuration changes use the
   relevant `.dev-venv/bin/python` tests and static checks; `frontend/**` or
   `tools/browser/**` changes use the frontend/browser checks; migration or
   package changes use the applicable migration/package checks; and
   documentation-map, documentation-gate, hook, or `.opencode/commands/**`
   changes use `py_compile`, `bash -n`, the isolated documentation self-test,
   and the completeness checker. Do not claim an unrelated check from repository
   shape, and do not run a full profile merely because an unrelated path changed.
3. When the changed scope requires application-wide confidence, run the existing
   local aggregate gate only after the scoped checks. Do not replace independent
   verification with the aggregate gate, and do not run a repair or delegate work.
4. Use only these result labels: `Pass` means the exact command exited successfully
   with evidence; `Fail` means it ran and found a failure; `Skipped` means it was
   deliberately out of scope or conditional; `Unavailable` means it could not run
   because of a tool, permission, environment, or hardware limitation. Never turn
   `Skipped` or `Unavailable` into `Pass`.
5. For every row report the exact command, revision, native/emulated/physical
   environment, UTC start/end, result, artifact path (or `none`), and limitation.
   Label QEMU/OCI as emulated ARM64 and do not infer physical mobile, actual
   screen-reader, true-zoom, native/physical ARM64, or ARM64-performance evidence
   from a substitute.
6. Do not repair findings, add tests to hide them, delegate them, or broaden scope.
