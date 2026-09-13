---
title: "Architecture"
description: "The single-process application architecture and its API, service, provider, persistence, forecast, and presentation boundaries."
---

# Architecture

Stock Probability is a local Linux application built as one bounded Python process. FastAPI
serves both the browser shell and the `/api/v1` interface. The default listener is loopback;
there is no hosted service or multi-service control plane.

The optional root `compose.yaml` wraps that same process as one local
`app` service. Its loopback-only publication, `/data` volume, resource/log bounds, non-root image
user, and image healthcheck are operational containment; they do not turn the app into a hosted
or multi-service deployment. Native development remains the `.dev-venv/` plus local CLI path in
[getting started](../operations/getting-started.md).

```text
Browser presentation
        │ HTTP /api/v1 only
        ▼
FastAPI transport ── application service ── forecast domain
                            │                    ▲
                            ├── market-data provider adapter ┘
                            │   Yahoo or deterministic fixture
                            ├── news provider ── ephemeral memory cache
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
  identities and daily/five-minute bars. Its separate `fetch_news` operation returns bounded
  current headlines to an ephemeral service cache; headlines never enter the repository.
- **Forecast domain** owns session completion, historical samples, model calculations,
  evaluation, quality labels, and immutable provenance payloads.
- **Persistence** applies checksum-pinned additive migrations and stores each submission.
  Forecast inputs/results are immutable; outcomes and corrections are append-only.
- **Presentation** calls only `/api/v1`. It does not open SQLite, receive database paths, or
  call Yahoo Finance directly. User-activated external article navigation is not an alternate
  browser data-provider path.

The color theme is presentation state only. An origin-scoped browser preference selects light,
dark, or the operating-system setting; it does not create server configuration, SQLite state, or
backup content. News is likewise separate from forecast and persistence paths, but it is fetched
server-side and held only in bounded process memory.

Exact repeated provider content may reuse one immutable forecast run, but every submitted
request still receives its own search event. Reopening a saved forecast reads captured data;
a historical-cutoff reconstruction is a separate provider call and newly audited analysis.

See [API reference](../reference/api.md), [threat model](../security/threat-model.md), and
[forecast model](forecast-model.md).
