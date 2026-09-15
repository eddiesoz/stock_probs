---
description: Commit all changes and push with generated message
---

Commit all current changes and push them.

Context:
Branch/status:
!`git status --short --branch`
Staged/unstaged summary:
!`git diff --stat HEAD`
Recent commits for style:
!`git log --oneline -5`

User hint: $ARGUMENTS

Do:
1. Run `git add -A`, then re-check `git status --short`.
2. If nothing to commit, stop and say so.
3. Otherwise write one concise commit message from the actual diff (imperative, <72 chars subject; body only if needed). If a user hint was given above, use it as the basis.
4. Run `git commit -m "<message>"`, then `git push`.
5. Verify with `git status --short --branch` and `git log --oneline -3` and report the commit + push result.
