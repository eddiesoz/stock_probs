---
name: project-qa
description: Independently verify a Stock Probability change with scoped checks and exact evidence. Use when asked for independent QA or invoked explicitly as $project-qa.
---

# Project QA

Delegate the independent verification to the project `luna-qa` agent when available. The verifier reads `AGENTS.md`, `MVP-PLAN.md`, and `MVP-ROADMAP.md` in full. Inspect the active branch and revision. Identify changed paths from `origin/main...HEAD`, falling back to `HEAD~1`; if neither comparison exists, use the current working-tree diff. Include uncommitted and untracked paths in the verification scope. Preserve unrelated dirty work and any deleted `HANDOFF.md`.

Select the smallest checks that cover the changed paths. Changes under `src/**`, `tests/**`, or Python configuration call for relevant `.dev-venv/bin/python` tests and static checks. Changes under `frontend/**` or `tools/browser/**` call for frontend or browser checks. Migration or package changes call for their corresponding checks. Changes to the documentation map, documentation gate, hooks, `.opencode/commands/**`, `.codex/**`, or `.agents/skills/**` call for relevant configuration and skill validation plus `py_compile`, `bash -n`, the isolated documentation self-test, and the completeness checker. Run an aggregate local gate only when the scope calls for application-wide confidence, after focused checks. Do not repair findings, edit source, or delegate further.

Use Codex's native todo tool when available to track multiple QA steps. Keep one item in progress and mark a check complete only after its exact command finishes. Report each check as **Pass**, **Fail**, **Skipped**, or **Unavailable**, with the exact command, revision, environment and native/emulated/physical architecture, UTC start/end, artifact path (or `none`), and limitation. A **Pass** requires a successful exact command; **Skipped** means deliberately out of scope, and **Unavailable** means the check could not run. Keep an unavailable provider, actual screen-reader, physical mobile, true browser zoom, or native ARM64 result unavailable. A builder report or aggregate receipt alone is not independent QA.
