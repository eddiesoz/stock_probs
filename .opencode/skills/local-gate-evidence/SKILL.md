---
name: "local-gate-evidence"
description: "Run and audit Stock Probability local gates with fail-closed receipts, structured performance rows, honest architecture labels, and separate export checkpoints. Use when executing, repairing, or reviewing local-gate, performance, ARM64, package, release, or checkpoint evidence."
---

# Stock Probability local-gate evidence

Use this project skill to preserve the evidence contract around `scripts/local-gate.sh`. A passing
command is not enough: the retained receipt must identify what ran, where it ran, and what remained
unavailable.

## Workflow

1. Capture the exact task ID/profile pairing, revision, dirty state, native architecture, command,
   external reviewer identity, and UTC window before interpreting a result.
2. Invoke the script directly, run only the requested profile, and preserve its first failure. Follow
   [`references/gate-protocol.md`](references/gate-protocol.md) for exact composition, isolation, and
   reruns.
3. Audit `evidence.json`, package/browser/Python artifacts, and every required performance row with
   [`references/receipt-audit.md`](references/receipt-audit.md).
4. Label QEMU/OCI work as emulated functional, package, runtime, build, or tool evidence. Leave
   native/physical ARM64 performance `Unavailable` when native hardware was not used.
5. Keep gate acceptance separate from export, secret review, commit, push, and exact-remote
   verification by following
   [`references/checkpoint-boundary.md`](references/checkpoint-boundary.md).

## Hard boundaries

- Fail closed at review time on a missing required row, artifact, reviewer, command, revision,
  timestamp, or cleanup proof; do not claim that the aggregate JSON stores fields it omits.
- Never replace a failed, skipped, dirty, historical, or unavailable result with a later summary.
- Never infer screen-reader, physical-mobile, native ARM64, live-provider, export, or remote evidence
  from a neighboring automated check.
- Do not stage, commit, push, mutate Git, or claim independent QA while running or auditing a gate.
- Do not call the whole gate bounded: it has no outer deadline and not every child command emits a
  command log or bounded-cleanup artifact.

## Reference files

| File | Purpose |
| --- | --- |
| [`references/gate-protocol.md`](references/gate-protocol.md) | Deterministic execution, isolation, and failure handling. |
| [`references/receipt-audit.md`](references/receipt-audit.md) | Aggregate and per-row receipt checks. |
| [`references/checkpoint-boundary.md`](references/checkpoint-boundary.md) | Separation of gates from export and revision checkpoints. |
