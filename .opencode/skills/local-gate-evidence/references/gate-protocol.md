# Local-gate protocol

## Before execution

- Use the repository environment and one exact profile: `m01`, `m02`, `m03`, `m04`, `m06`, `m09`,
  `check`, or `release`. There are no `m05`, `m07`, or `m08` script profiles. Do not substitute a
  hosted pipeline or a narrower command.
- Record `git rev-parse HEAD` and `git status --short` without changing the index or worktree.
- Invoke `TASK_ID=<M00-M09-or-R-M##-n> ./scripts/local-gate.sh <profile>`. For `m06`, `m09`, and
  `release`, also set `PERFORMANCE_REVIEWER='<independent reviewer>'`; the Make wrappers do not fill
  it in. The script validates task and profile independently, so the reviewer must verify the
  requested pairing rather than infer it from acceptance.
- Use a fresh loopback port and temporary runtime. A retained runtime must identify its purpose.

## Exact profile composition

| Profile | Checks run in order |
| --- | --- |
| `check` | Python lint/type/compile/shell/comment/non-live coverage/security/backup checks |
| `m01` | package, then `check` |
| `m02` | `m01`, browser regressions, MCP smoke |
| `m03` | `m02`, ARM64 functional/package/runtime smoke |
| `m04` | native package, `check`, responsive browser/visual/accessibility, MCP, ARM64 smoke |
| `m06` | reviewer and Ponytail-interface preconditions, then the `m04` stack and native x86 performance |
| `m09` | reviewer and Ponytail-interface preconditions, native package, `check`, theme/news browser, MCP, ARM64 smoke, M09 native x86 performance |
| `release` | reviewer, clean tree, Ponytail-interface preconditions, package, `check`, browser, MCP, migrate/backup CLI, M09 native x86 performance rows; no ARM64 smoke |

The Ponytail precondition checks only interface availability and does not perform the required
boundary review. Only `release` rejects a dirty tree in the script. Other profiles record dirtiness
and continue; an external clean-revision acceptance requirement still remains unsatisfied by a dirty
pass.

## During execution

- Keep deterministic fixture checks separate from opt-in live Yahoo checks.
- Inspect each child for its own deadline and cleanup behavior. Browser configuration, MCP smoke,
  performance subprocesses, provider calls, and much of ARM64 execution have local bounds, but
  `scripts/local-gate.sh` has no outer timeout and bootstrap, package/Python checks, `npm ci`, and
  some Docker setup/cleanup calls are not all wrapped by one.
- Preserve raw samples and exclude declared warmups from measured statistics.
- Treat an unexpected HTTP response, browser request, console error, page error, missing artifact,
  early subprocess exit, timeout, or cleanup failure as a gate failure.

## Failure and rerun discipline

Keep the first failure and assign a repair ID when it is reproducible and blocking. A corrected run
gets a new receipt and UTC window; it does not overwrite the failed history. Record harness or
environment failures separately from product failures. Do not convert a skipped or unavailable
check into a pass because another lane succeeded.

## Architecture labels

- `native x86_64` means the current process ran on native x86-64 hardware.
- `native ARM64` requires local ARM64 hardware.
- QEMU/OCI aarch64 execution is `emulated ARM64` and may support functional, package, runtime,
  build, or tool claims only.
- `m03`, `m04`, `m06`, and `m09` invoke `arm64-smoke.sh`; `release` does not. Missing Docker/Compose,
  QEMU acquisition failure, lock contention, or cleanup failure exits nonzero and fails an invoking
  local gate rather than silently passing an `Unavailable` child.
- Native ARM64 uses package smoke and explicitly does not measure performance. Emulated ARM64 uses
  Docker/Compose plus user-local QEMU for functional/package/runtime evidence only. Performance
  artifacts retain the zero-sample ARM64 row as `Unavailable`; emulation never satisfies it.
