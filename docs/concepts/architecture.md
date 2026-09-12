---
title: "Architecture"
description: "The single-process application architecture and its API, service, provider, persistence, forecast, and presentation boundaries."
---

# Architecture

Stock Probability is a local Linux application built as one bounded Python process. FastAPI
serves both the browser shell and the `/api/v1` interface. The default listener is loopback;
there is no hosted service or multi-service control plane.

```text
Browser presentation
        │ HTTP /api/v1 only
        ▼
FastAPI transport ── application service ── forecast domain
                            │                    ▲
                            ├── provider adapter ┘
                            │   Yahoo or deterministic fixture
                            └── repository ── SQLite
                                  │
                                  └── backup manager ── managed .spbackup artifacts
```

## Boundary responsibilities

- **Transport** validates HTTP shapes, applies local security policy, maps safe errors, and
  never embeds SQL or provider-specific objects.
- **Application service** coordinates provider capacity, forecast calculation, and exactly
  classified audit writes.
- **Provider** turns bounded Yahoo Finance responses or packaged fixtures into normalized
  identities and daily/five-minute bars.
- **Forecast domain** owns session completion, historical samples, model calculations,
  evaluation, quality labels, and immutable provenance payloads.
- **Persistence** applies checksum-pinned additive migrations and stores each submission.
  Forecast inputs/results are immutable; outcomes and corrections are append-only.
- **Presentation** calls only `/api/v1`. It does not open SQLite, receive database paths, or
  call Yahoo Finance directly.

Exact repeated provider content may reuse one immutable forecast run, but every submitted
request still receives its own search event. Reopening a saved forecast reads captured data;
a historical-cutoff reconstruction is a separate provider call and newly audited analysis.

See [API reference](../reference/api.md), [threat model](../security/threat-model.md), and
[forecast model](forecast-model.md).
