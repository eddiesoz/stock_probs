# Read-only boundary workflow

## Invocation

From the repository root, choose an exact allowed task boundary and a report path whose existing
non-symlink parent is inside the repository. The path must not already exist:

```bash
./scripts/ponytail-review.sh <task-boundary> <new-report-path>
```

The launcher starts a fresh isolated OpenCode 1.18.30 process with the `LUNA MAX QA` profile,
read-only repository permissions, no delegation, and only the `ponytail-review` skill. It bounds
runtime and output, separates provider diagnostics from JSON events, allowlists clean/finding lines,
rejects raw diffs and credential-like content, and retains a report only after successful parsing.

## Review target

Inspect the boundary diff and its callers for code that can be deleted or collapsed without losing
required behavior:

- duplicate collectors, checks, parsing, loops, or source-text assertions;
- one-use wrappers and abstractions;
- repeated canonical data or aliases;
- bespoke work already covered by executed tests, standard tools, or existing helpers; and
- speculative flexibility with no accepted requirement.

Do not report correctness, security, accessibility, performance, style, or feature preferences.
Those belong to their own QA lanes. A clean output means only that no evidenced overengineering
finding was retained.
