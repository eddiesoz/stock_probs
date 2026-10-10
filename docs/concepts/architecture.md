---
title: "Architecture"
description: "The production single-process architecture and the deployed R-ASTRA-120 owner-canary boundary."
---

# Architecture

The deployed Stock Probability baseline is a self-hosted Linux application served by one bounded
FastAPI process. It serves `/`, `/api/v1/docs`, and the workspace routes
`/overview`, `/research`, `/tools`, `/tools/forecast`, `/tools/live-trading`, and
`/tools/markets`, plus the application API below `/api/v1`. The default listener is loopback;
production deployment runs on an operator-managed host. Node is not a production server. The
deployed R-ASTRA-120 release adds one supervised OpenCode worker process inside the same image and
container; it does not add a companion service or image.

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

## R-ASTRA-120 assistant boundary

The R-ASTRA-120 release runs a supervised OpenCode V2.0.7 worker inside the same FastAPI image.
The browser uses same-origin `/api/v1/assistant` routes; the worker and its internal provider/MCP
callbacks stay on private loopback. The worker has a separate UID and bounded writable runtime
state. Application session checks bind each tool call and stream to its owner. The typed application
MCP catalog exposes workspace/research operations; OpenCode's native websearch and webfetch are
separate runtime tools with approval checks. The release does not add a companion container,
arbitrary shell/filesystem access, or background job scheduler.

Production Compose still defaults assistant enablement to `0` and rollout to `disabled`, but that
is not the deployed setting. E849 deployed the tested PR #2 image
`sha256:78746f600815cac1941a9060f91bba41aca08f363714db466200c2d77e8ad7b1` at schema 13, ready
and loopback-only, then the rollout control passed with `owner_canary` on that same image. The
deployment verified pre-deploy and pre-migration backups and registered recovery image
`sha256:a9b5147cff0016e443589e8c7b72e83764ca4bac45866ef3ad9bbcd3b308c13f`. The actual owner
UI/model/action canary remains pending; the owner's current authenticator-code field was empty.
Invited-user rollout and the announcement remain held.

E847 passed its declared canonical and 590-check security scopes. Its input-bound browser/axe reuse
passed for 193/196 browser cases with three expected skips and 68 cases/72 scans with zero
violations or incompletes. Earlier input-bound current-product native wire/kill scopes also passed.
E848 passed the exact-5ad actual-host pair/resource/recovery, combined 1 GB and PR-bound rollback
scopes. These results do not establish full WCAG AA or owner UI/model/action acceptance. Physical
mobile, actual screen reader, true zoom and PDF/UA evidence remain unavailable. The E848
`backup_unverified` deployment failure and successful failure-path rollback are historical, not
the current E849 result.

The source distinguishes rollout paths: `disabled` persists the disabled marker and invokes the
fixed in-place assistant-kill client, while `owner_canary` and `invited` transitions force-recreate
the app service (E53). An earlier input-bound current-product active-search kill scope passed for
its image; this does not establish actual owner interaction. See the
[R-ASTRA-120 evidence ledger](../../MVP-PLAN.md#r-astra-120-signal-ledger-assistant-design-first-follow-on).

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
