# Receipt and repair discipline

## Clean record

Record:

```text
Ponytail result | boundary: <exact task ID> | finding: none | scope: overengineering only | command: /ponytail-review | environment | UTC | commit | result | artifact | reviewer
```

## Finding record

For each finding, record:

```text
Ponytail finding | boundary: <exact task ID> | path:line | overengineering claim | evidence | minimal SOL HIGH repair | QA rerun | environment | UTC | commit | result | artifact | reviewer
```

Retain the sanitized launcher artifact, net deletion estimate when supplied, and any missing fields
as `Unavailable`. Findings-only evidence is not closure.

## Repair and closure

Assign a canonical `R-M##-<n>` or `R-ASTRA-<n>` only when the finding is reproducible and blocks the
boundary. A `SOL HIGH build` lane applies the smallest behavior-preserving deletion or collapse;
the receipt retains the canonical `minimal SOL HIGH repair` field name shown above. Independent QA
then reruns the affected behavior, not merely a source-string assertion. Keep the original finding,
repair diff, failed attempts, and rerun as separate evidence.

Use the tracked receipts as project evidence rather than copying examples that can drift:

- [`ponytail-m05-boundary.txt`](../../../../docs/evidence/ponytail-m05-boundary.txt)
- [`ponytail-r-m06-1.txt`](../../../../docs/evidence/ponytail-r-m06-1.txt)
- [`ponytail-r-m06-15.txt`](../../../../docs/evidence/ponytail-r-m06-15.txt)

They are overengineering-only artifacts and do not substitute for correctness or release gates.
