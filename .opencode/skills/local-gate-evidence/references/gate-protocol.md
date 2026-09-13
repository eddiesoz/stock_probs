# Local-gate protocol

## Before execution

- Use the repository environment and the exact requested gate profile; do not substitute a hosted
  pipeline or a narrower command.
- Record `git rev-parse HEAD` and `git status --short` without changing the index or worktree.
- Set the exact task ID and named performance reviewer when the gate requires them.
- Use a fresh loopback port and temporary runtime. A retained runtime must identify its purpose.

## During execution

- Keep deterministic fixture checks separate from opt-in live Yahoo checks.
- Bound startup, provider calls, browser runs, subprocess shutdown, and cleanup.
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
- With no native ARM64 run, retain an explicit zero-sample ARM64 performance row whose result is
  `Unavailable` and whose limitation says that emulation was not used as performance evidence.
