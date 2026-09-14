# Receipt audit

## Aggregate receipt

Confirm `evidence.json` has the exact task, revision, start-of-run dirty state, native architecture
and execution label, start/end UTC, command, profile, completed-check labels, result, exit code, and
artifact path inventory. A check label is appended only after its command returns successfully, but
it is not a substitute for auditing the child artifact.

The aggregate JSON does **not** contain the independent reviewer, full environment, stdout/stderr
logs, artifact hashes/sizes, or a final clean-tree check. Reviewer identity is present in required
performance rows and must also be carried by the external acceptance receipt. The artifact array is
a path listing made on exit, not a completeness or integrity proof.

## Structured performance rows

For `performance/summary.json`, compare `required_rows` with the artifact map and files on disk.
Require empty `missing_rows`, `nonpassing_rows`, `acceptance_errors`, and `validation_errors` before
accepting `Pass`. Then inspect each row rather than trusting the summary alone. A measured row
contains:

- schema version, task ID, row name, fixture identity, environment, revision, UTC, and command;
- isolation host/port/runtime/process and bounded cleanup evidence;
- excluded warmups, raw measured samples, units, statistics, threshold, result, and reviewer; and
- a precise limitation when the result is `Skipped` or `Unavailable`.

Recompute the claimed percentile or bound from raw samples when reviewing performance evidence.
Verify that sample counts meet the protocol and that fixture/cache conditions match the named
workload.

## Other child artifacts

- Package: wheel identity and size, non-editable install, resource inventory, migrations, and
  loopback launch.
- Python: parse JUnit counts and require zero errors/failures; do not rely on console prose alone.
- Browser: retain the HTML/report artifacts, project and viewport identity, expected skip reasons,
  expected failure/abort accounting, and the actual scope of request accounting.
- Migration/backup: prove the source schema, pre-migration verified backup, target schema, and
  restore/key behavior required by the profile.

Historical or dirty artifacts may be useful context but cannot replace the receipt bound to the
reviewed revision.

## Bounded-operation limitations

Do not infer an overall deadline or complete cleanup proof from a `Pass`. Audit the child source and
artifacts for the claimed bound: the gate itself has no outer timeout, some setup/check/Docker calls
have no local wrapper, and not every child retains a command log. Record absent process, port,
runtime, timeout, cleanup, or raw-sample evidence as `Unavailable` for that claim rather than filling
it from console prose or a neighboring run.
