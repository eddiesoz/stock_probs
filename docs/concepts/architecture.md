---
title: "Architecture"
description: "The single-process application architecture and its API, service, provider, persistence, forecast, and presentation boundaries."
---

# Architecture

Stock Probability is a self-hosted Linux application built as one bounded Python process. FastAPI
remains the sole production server: it serves `/`, `/api/v1/docs`, and the workspace routes
`/overview`, `/research`, `/tools`, `/tools/forecast`, `/tools/live-trading`, and
`/tools/markets`, plus the application API below `/api/v1`. The default listener is loopback;
production deployment runs on an operator-managed host. Node is not a production server, and the
application does not split into multiple runtime services.

The presentation source is a Next.js `16.3.8` / React `19.3` App Router project, but it is a
static build-time input rather than another runtime. Run `./scripts/build-frontend.sh` to create
the static export and stage it for the Python package. The export has the stable build ID
`stock-probs`; generated `frontend/.next/`, `frontend/out/`, and
`src/stock_probs/static/next/` trees are ignored. The Python package includes the staged App Router
pages and assets from `src/stock_probs/static/next/`. The container uses Node only in its build
stage; the runtime image contains the Python server and packaged static files.

The optional root `compose.yaml` wraps that same process as one local `app` service. Its
loopback-only publication, `/data` volume, resource/log bounds, non-root image user, and image
healthcheck are operational containment. Native development remains the `.dev-venv/` plus local CLI path in
[getting started](../operations/getting-started.md).

## Authentication boundary

Production keeps GitHub OAuth as the first factor and uses a six-digit TOTP code from an
authenticator app as the sole ongoing application second factor. Invitations are resolved to a
numeric GitHub account ID, expire, and can be redeemed once. The enrollment API returns the manual
secret and an `otpauth://` URI only during the short setup transaction; the authenticator page uses
that URI to render a local QR code and does not expose a generic URI-handler link. The encrypted
secret is never returned after activation. Recovery codes are displayed once, stored as hashes,
and each is consumed at most once. A lost authenticator enters a factor-replacement-only session
until a new authenticator is confirmed.

The deployed schema-10 migration revokes stored passkeys and old passkey sessions, and production
GitHub-auth mode rejects WebAuthn registration. The one-time passkey migration screen belonged to
an earlier release and is not current authentication guidance. Ordinary sign-in on another device
does not require Bluetooth or a nearby phone. In production GitHub-auth mode, backup creation and
every HTTP restore request require an administrator session and TOTP proof no older than five
minutes. Local-auth mode can satisfy the same fresh step-up window with its local-passkey proof.
Backup status is administrator-only without step-up. All private research queries derive ownership
from the authenticated session.

```text
Browser presentation
        │ local workspace HTML/assets and HTTP /api/v1
        ▼
FastAPI (`/`, `/api/v1/docs`, `/api/v1`) ── application service ── forecast domain
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
  identities, quote snapshots, daily/five-minute bars, and daily chart series. Its separate
  `fetch_news` operation returns bounded current headlines to an ephemeral service cache; headlines
  never enter the repository. It has no market-depth capability.
- **Forecast domain** owns session completion, historical samples, model calculations,
  evaluation, quality labels, and immutable provenance payloads.
- **Persistence** applies checksum-pinned additive migrations and stores each submission plus
  bounded local watchlist and portfolio records. Forecast inputs/results are immutable; outcomes
  and corrections are append-only; manual quantities are research context, not broker positions.
- **Presentation** uses the static Next export for the workspace pages and calls only `/api/v1`
  for application data. It does not open SQLite, receive database paths, or call Yahoo Finance
  directly. User-activated external article navigation is not an alternate browser data-provider
  path, and no presentation control places an order.

The color theme is presentation state only. A parser-blocking `theme.js` runs before the
stylesheet, and the server's strict CSP authorizes local scripts plus the exact hashes of the
inline export snippets. An origin-scoped browser preference selects light, dark, or the
operating-system setting; it does not create server configuration, SQLite state, or backup
content. The native Settings popover exposes Light, Dark, and System; the `R-ASTRA-59`
open-state anchor repair keeps the opened control aligned. News is likewise separate from
forecast and persistence paths, but it is fetched server-side and held only in bounded process
memory.

Exact repeated provider content may reuse one immutable forecast run, but every submitted
request still receives its own search event. Reopening a saved forecast reads captured data;
a historical-cutoff reconstruction is a separate provider call and newly audited analysis.

See [API reference](../reference/api.md), [threat model](../security/threat-model.md), and
[forecast model](forecast-model.md).
