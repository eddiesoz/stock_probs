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

Assign an ordinary `R-M##-<n>` or `R-ASTRA-<n>` only when the finding is reproducible and blocks the
boundary. `SOL HIGH` applies the smallest behavior-preserving deletion or collapse. Independent QA
then reruns the affected behavior, not merely a source-string assertion. Keep the original finding,
repair diff, failed attempts, and rerun as separate evidence.

Repeated project examples justify this workflow: duplicate deadline and key-retirement logic at
M05; duplicate browser collection, prose/provenance checks, repeated descriptions, and source-text
tests at M06; repeated comment-audit scans at `R-M06-15`; and duplicated performance/stub/CSS/static
checks at M09. None of those receipts substituted for the later correctness or release gates.
