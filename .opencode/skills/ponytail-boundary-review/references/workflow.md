# Read-only boundary workflow

## Invocation

From the repository root, use one canonical boundary ID: `M00`–`M09`, `EXP-M00`–`EXP-M09`,
`R-M##-<n>`, `ASTRA-FINAL`, `R-ASTRA-<n>`, or `EXP-FINAL`. Do not invent a milestone or use
`NOTIFY-FINAL`; the launcher's permissive optional suffix syntax does not make a suffixed label a
canonical evidence ID.

Supply a coordinator-approved report path whose existing non-symlink parent is inside the
repository. The path must not exist or be a symlink:

```bash
./scripts/ponytail-review.sh <task-boundary> <new-report-path>
```

The launcher requires `opencode` exactly 1.18.30 plus `timeout`, `install`, `jq`, `stat`, and the
core Git/path/file utilities it invokes. It also requires the current user's non-symlink regular
OpenCode `auth.json` at the resolved data-home path, owned by that user with mode 600 or 400. It
copies only that file into its mode-700 temporary data home and removes the sandbox on exit.

It starts a fresh process with an inline agent named `LUNA MAX QA`, source reads except denied
environment/credential/secret paths, glob/grep, read-only Git status/diff/revision commands, and
`wc -l`. Edit/write/delegation and all other shell commands are denied; only `ponytail-review` may be
loaded. The 300-second provider run and captured files are bounded. Provider diagnostics remain in
the private sandbox, and the requested report is created only after JSON parsing, allowlisting, raw
diff/credential rejection, and the 64 KiB sanitized-output limit pass.

The retained file contains the boundary/scope/command header and allowlisted clean/finding lines; it
does not itself add environment, UTC, commit, result, or reviewer fields. Record those separately in
the boundary receipt. Because the launcher writes a new report, describe the **reviewer** as
source-read-only rather than claiming the entire launcher has no filesystem effect.

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
