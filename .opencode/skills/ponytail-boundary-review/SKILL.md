---
name: "ponytail-boundary-review"
description: "Run the read-only Stock Probability Ponytail boundary workflow and preserve overengineering-only findings through minimal repair and independent retest. Use after an implementation or configuration boundary and before independent QA, or when auditing a retained Ponytail receipt."
---

# Stock Probability Ponytail boundary review

Use this project skill after each implementation, repair, integration, profile, local-gate, or other
configuration boundary and before independent QA. The isolated reviewer gets read-only source and
Git-inspection permissions and hunts only removable complexity; the launcher may create the one
requested sanitized report after successful parsing.

## Workflow

1. Identify one canonical project task boundary and a new in-repository report path with an existing
   non-symlink parent.
2. Run the isolated launcher and preserve its result with
   [`references/workflow.md`](references/workflow.md).
3. Record either the exact clean result or each path/line finding using
   [`references/receipt-and-repair.md`](references/receipt-and-repair.md).
4. Route only reproducible blocking findings to a `SOL HIGH build` lane for the smallest
   behavior-preserving repair, then require an independent behavior retest before closure.

## Hard boundaries

- The reviewer is source-read-only and overengineering-only. It cannot verify correctness, security,
  accessibility, performance, release acceptance, or an export checkpoint. Report creation by the
  launcher is not permission to edit source or other evidence.
- A missing, unavailable, malformed, provider-failed, or findings-only review blocks its pre-QA
  boundary; do not infer a clean result.
- Never overwrite a retained receipt or erase failed and historical findings.
- Never stage, commit, push, export, mutate Git, or let the reviewer repair implementation.

## Reference files

| File | Purpose |
| --- | --- |
| [`references/workflow.md`](references/workflow.md) | Isolated launcher use and review scope. |
| [`references/receipt-and-repair.md`](references/receipt-and-repair.md) | Exact receipt fields, repair routing, and closure. |
