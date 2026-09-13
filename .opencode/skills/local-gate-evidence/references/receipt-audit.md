# Receipt audit

## Aggregate receipt

Confirm `evidence.json` has the exact task, revision, dirty state, native architecture and execution
label, start/end UTC, command, profile, completed checks, result, exit code, and artifact inventory.
The aggregate result must fail when a mandatory child check is absent or nonpassing.

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
  expected failure/abort accounting, and local-only requests.
- Migration/backup: prove the source schema, pre-migration verified backup, target schema, and
  restore/key behavior required by the profile.

Historical or dirty artifacts may be useful context but cannot replace the receipt bound to the
reviewed revision.
