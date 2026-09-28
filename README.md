<p align="center">
  <img src="src/stock_probs/static/favicon.svg" alt="Signal Ledger mark" width="72" height="72">
</p>

<h1 align="center">Signal Ledger</h1>

<p align="center">
  <strong>Auditable stock-probability research in a calm, local workspace.</strong>
</p>

<p align="center">
  <a href="docs/operations/getting-started.md">Get started</a>
  ·
  <a href="docs/usage/dashboard.md">User guide</a>
  ·
  <a href="docs/reference/api.md">API reference</a>
  ·
  <a href="MVP-PLAN.md">Product plan</a>
</p>

Signal Ledger is the product name for **Stock Probability**, a local Linux application for
exploring selected Yahoo Finance stocks and ETFs. It turns bounded provider data into explicit
forecast probabilities, intervals, provenance, and an immutable research history that you can
reopen and inspect later.

The app runs on your machine, stores its state locally in SQLite, and serves browser data through
one loopback FastAPI boundary. It is designed for research and auditability. It does not place
orders, connect to a brokerage, promise real-time delivery, or fabricate market depth.

## Screenshots

The interface keeps the overview and research surfaces quiet, then makes probabilities and
provider context easy to scan in the forecast and market tools. These screenshots use the
deterministic fixture provider so the states are repeatable; they are representative views of the
eight current routes.

<p align="center">
  <a href="docs/images/readme/forecast-result-desktop.png"><img src="docs/images/readme/forecast-result-desktop.png" alt="Signal Ledger populated forecast result on desktop" width="900"></a>
</p>

<p align="center"><em>A populated forecast result keeps probabilities, intervals, provenance, and quality context together.</em></p>

### Desktop

<table>
  <tr>
    <th>Dashboard</th>
    <th>Overview</th>
    <th>Research</th>
    <th>Tools</th>
  </tr>
  <tr>
    <td><a href="docs/images/readme/dashboard-desktop.png"><img src="docs/images/readme/dashboard-desktop.png" alt="Signal Ledger dashboard on desktop" width="260"></a></td>
    <td><a href="docs/images/readme/overview-desktop.png"><img src="docs/images/readme/overview-desktop.png" alt="Signal Ledger overview on desktop" width="260"></a></td>
    <td><a href="docs/images/readme/research-desktop.png"><img src="docs/images/readme/research-desktop.png" alt="Signal Ledger research ledger on desktop" width="260"></a></td>
    <td><a href="docs/images/readme/tools-desktop.png"><img src="docs/images/readme/tools-desktop.png" alt="Signal Ledger tools landing page on desktop" width="260"></a></td>
  </tr>
  <tr>
    <th>Forecast</th>
    <th>Live Trading</th>
    <th>Markets</th>
    <th>API Docs</th>
  </tr>
  <tr>
    <td><a href="docs/images/readme/forecast-desktop.png"><img src="docs/images/readme/forecast-desktop.png" alt="Signal Ledger forecast workspace on desktop" width="260"></a></td>
    <td><a href="docs/images/readme/live-trading-desktop.png"><img src="docs/images/readme/live-trading-desktop.png" alt="Signal Ledger live research workspace on desktop" width="260"></a></td>
    <td><a href="docs/images/readme/markets-desktop.png"><img src="docs/images/readme/markets-desktop.png" alt="Signal Ledger markets workspace on desktop" width="260"></a></td>
    <td><a href="docs/images/readme/api-docs-desktop.png"><img src="docs/images/readme/api-docs-desktop.png" alt="Signal Ledger API documentation on desktop" width="260"></a></td>
  </tr>
</table>

### Mobile

<table>
  <tr>
    <th>Dashboard</th>
    <th>Overview</th>
    <th>Research</th>
    <th>Tools</th>
  </tr>
  <tr>
    <td><a href="docs/images/readme/dashboard-mobile.png"><img src="docs/images/readme/dashboard-mobile.png" alt="Signal Ledger dashboard on mobile" width="180"></a></td>
    <td><a href="docs/images/readme/overview-mobile.png"><img src="docs/images/readme/overview-mobile.png" alt="Signal Ledger overview on mobile" width="180"></a></td>
    <td><a href="docs/images/readme/research-mobile.png"><img src="docs/images/readme/research-mobile.png" alt="Signal Ledger research ledger on mobile" width="180"></a></td>
    <td><a href="docs/images/readme/tools-mobile.png"><img src="docs/images/readme/tools-mobile.png" alt="Signal Ledger tools landing page on mobile" width="180"></a></td>
  </tr>
  <tr>
    <th>Forecast</th>
    <th>Live Trading</th>
    <th>Markets</th>
    <th>API Docs</th>
  </tr>
  <tr>
    <td><a href="docs/images/readme/forecast-mobile.png"><img src="docs/images/readme/forecast-mobile.png" alt="Signal Ledger forecast workspace on mobile" width="180"></a></td>
    <td><a href="docs/images/readme/live-trading-mobile.png"><img src="docs/images/readme/live-trading-mobile.png" alt="Signal Ledger live research workspace on mobile" width="180"></a></td>
    <td><a href="docs/images/readme/markets-mobile.png"><img src="docs/images/readme/markets-mobile.png" alt="Signal Ledger markets workspace on mobile" width="180"></a></td>
    <td><a href="docs/images/readme/api-docs-mobile.png"><img src="docs/images/readme/api-docs-mobile.png" alt="Signal Ledger API documentation on mobile" width="180"></a></td>
  </tr>
</table>

## What you can do

- **Run explicit forecasts.** Search by company or symbol, confirm the full instrument identity,
  and choose a rolling horizon from five-minute forward through quarterly.
- **Read the evidence with the result.** Direction probabilities, threshold probabilities,
  empirical return and price intervals, samples, quality, model version, provider as-of time,
  and target boundaries stay together.
- **Keep an immutable ledger.** Reopen a saved forecast without another provider call, inspect
  later outcomes as append-only records, or run a separately labelled historical-cutoff analysis.
- **Add research context.** Maintain a small local portfolio and watchlist, inspect provider-
  labelled quote snapshots, and compare bounded daily charts.
- **Keep current headlines separate.** Headlines are an explicitly requested, ephemeral context
  panel. They do not change forecast inputs or enter the saved ledger.
- **Work comfortably across themes and sizes.** Light, Dark, and System themes, keyboard focus,
  reduced motion, print styling, and responsive layouts are part of the application surface.

## Quick start

The supported development path uses Python 3.11.15 and creates the isolated `.dev-venv/`
environment. From a checkout of this repository:

```bash
./scripts/bootstrap.sh
./scripts/build-frontend.sh
.dev-venv/bin/python -m stock_probs.cli migrate
.dev-venv/bin/python -m stock_probs.cli serve
```

Open [http://127.0.0.1:8000/](http://127.0.0.1:8000/) in a browser. The readiness endpoint is
available at [http://127.0.0.1:8000/api/v1/readiness](http://127.0.0.1:8000/api/v1/readiness),
and the local interactive API documentation is at
[http://127.0.0.1:8000/api/v1/docs](http://127.0.0.1:8000/api/v1/docs).

The default provider is Yahoo Finance and needs network access. For deterministic local work,
use the fixture configuration described in [local configuration](docs/configure/local-configuration.md).
The full startup, Compose, migration, and shutdown procedure is in
[Getting started](docs/operations/getting-started.md).

## Explore the workspace

| Route | Purpose |
| --- | --- |
| [`/`](docs/usage/dashboard.md) | Search instruments, run the original forecast comparison, and browse the ledger. |
| [`/overview`](docs/usage/dashboard.md) | Keep manually entered portfolio context visible. |
| [`/research`](docs/usage/dashboard.md) | Review recent recorded forecasts and compare saved results. |
| [`/tools`](docs/usage/dashboard.md) | Choose a research tool without submitting a request. |
| [`/tools/forecast`](docs/usage/dashboard.md) | Run one selected rolling-horizon forecast. |
| [`/tools/live-trading`](docs/usage/dashboard.md) | Inspect manual holdings and provider-labelled quote context. |
| [`/tools/markets`](docs/usage/dashboard.md) | Maintain a bounded watchlist, filter quotes, and inspect daily bars. |
| [`/api-docs`](docs/reference/api.md) | Open the browser's local API documentation page. |

The [dashboard guide](docs/usage/dashboard.md) explains instrument selection, forecast
semantics, saved replay, portfolio and watchlist context, headlines, themes, and ledger filters.
The `/api-docs` page points at the generated FastAPI contract at `/api/v1/docs`.

## Research boundaries

> Signal Ledger is a research application. Forecasts are informational outputs, not investment
> advice or a guarantee of future results.

Provider data is labelled with its source, as-of time, delay state, and any available quality
reason. Quote and chart surfaces use bounded snapshots and daily bars. The Live Trading page is
named for its compact research workspace; it has no order entry, execution, brokerage session,
or exchange-depth capability. News is fetched through the local API, held in a bounded in-memory
cache, and kept out of forecast inputs and persistence.

The browser talks to `/api/v1`; it never opens SQLite, receives a database path, or calls Yahoo
Finance directly. See [Architecture](docs/concepts/architecture.md) and the
[threat model](docs/security/threat-model.md) for the complete boundary description.

## Configuration

Most users can start with the defaults. The supported environment variables are documented in
[Local configuration](docs/configure/local-configuration.md), including:

- `STOCK_PROBS_PROVIDER=yahoo` for provider-backed requests, or `fixture` for deterministic local
  data.
- `STOCK_PROBS_DATA_DIR` for the local SQLite, backup, and trust-key directory.
- `STOCK_PROBS_HOST` and `STOCK_PROBS_PORT` for the loopback listener.
- `STOCK_PROBS_PROVIDER_TIMEOUT` for the bounded provider timeout.

For a local production-style container, use the root `compose.yaml` as described in
[Getting started](docs/operations/getting-started.md). It publishes the service on loopback and
keeps application data in a named volume.

## Private production deployment

The production path is invite-only GitHub OAuth plus a required passkey, with each user's
holdings, watchlists, forecasts, exports, outcomes, and reconstructions scoped to that account.
The app runs on one Linode with SQLite on a persistent private volume and is published only
through a Cloudflare Tunnel. The application port stays on `127.0.0.1`; the deployment helper
does not expose a public Docker port.

Build and publish the reviewed image locally:

```bash
./scripts/publish-production-image.sh
```

The default transport builds a Linux `amd64` image locally, scans the bounded archive for
credential material, and publishes a revision-named GitHub Release asset from the exact reviewed
`main` revision. The script treats that revision-named asset as immutable during its workflow,
then re-downloads it and verifies its archive SHA-256, image ID, revision, and platform before
returning the receipt; GitHub does not enforce asset immutability. Set
`SIGNAL_LEDGER_IMAGE_PUBLISH_MODE=ghcr` only when using the explicit GHCR compatibility transport;
GHCR is not the default. The Linode pulls the reviewed release asset through the local stdio
deployment MCP; the VM does not build source. The five deployment operations are `inspect`,
`plan_deploy`, `deploy`, `status`, and `rollback`. See
[Getting started](docs/operations/getting-started.md) for the Terraform host setup, owner data
migration, tunnel canary, and recovery procedure.

Terraform keeps the Linode firewall and application ports closed to the public, and Cloudflare
starts in a terminal-404 closed mode before the owner-only canary. E58 records the later
provider-refreshed `public_invited` boundary: the owner-canary Access app was deleted and the
exposure guard updated, while the tunnel, DNS, and cache bypass remained managed. The reviewed
image stays on the loopback-only replacement host, and direct port `8000` remains unreachable.
The live boundary returned `303` to local sign-in for `/overview`, `401` for `/api/v1/history`, and
`200` for `/api/v1/auth/status`; each was `no-store`/`DYNAMIC`. The live IAB showed the
unauthenticated sign-in page but no owner UI session. The prior private image was reviewed commit
`39bd185150cd3df70395e6c000f568dfd20831ac`, with release archive SHA-256
`930d6d5b5d054908a25825c980584b620817bfa7ab212a62abd63f65c72f6f3f` and image ID
`sha256:23ef16e4e5ee28db378c76bbcd9182345584bbffda55bd5313141fd0847fe31b`; publisher
re-download verification passed, and the typed MCP plan/deploy reached a healthy schema-8
loopback-only Linode with a pre-deploy backup. The auth UI repair passed frontend build/typecheck,
`28` tests, pinned Playwright desktop/mobile `2/2`, and independent Luna auth/passkey-cancellation
checks; Astra reported no remaining P1/P2 after its `409` guidance repair. GitHub OAuth application
authorization and the Access one-time-code flow completed, and the owner-only canary served the
new passkey text with Cloudflare unauthenticated traffic returning `302`. The earlier tab 13 showed
signed in as `jtmb` before this deployment, but may be stale; the new in-app-browser auth result was
not verified. Owner passkey enrollment and owner saved-data verification remain pending because the
browser requested a nearby phone/Bluetooth credential and no completed credential was observed. The
prior origin-navigation repair was reviewed at commit
`11faaf702129d0c1485a8683711d88340f623a71`; its release publisher SHA-256 is
`fad471b19db6ff4f9b4dc154055f0d2437128e49878e72a286b697f17e8a3f48` and image ID is
`sha256:26df706f6a2b4e76ee51bb014f94d39eb66bc7644a2c7a56eb3d012f41684d60`. MCP plan
`530c1c65a7b4563e9c7f1cdbf5a47a3d` deployed the ready schema-8 loopback-only image with a
pre-deploy backup; an external link from localhost:8765 to the canary passkey path loaded HTML
instead of the prior `origin_rejected` JSON. This verifies navigation only; it does not establish
current authentication, passkey enrollment, or saved-data access. A subsequent source fix at
commit `a1d868287a729c75d9b8628f612a856db132374a` handles stale/expired provisional sessions that
returned `authenticated:false` and left the passkey page at `Checking your session`; build/typecheck,
`28` frontend tests, and browser `4/4` passed. It is source-reviewed and locally tested and is
included in the final clean-main image below. The final private clean-main deployment uses revision
`2de5e9f199cd145707f95e81d389c40b2ab3c32a`, archive SHA-256
`b856795831b6fb46e94e330370e003843b266ad85f22e8d95ef7624536b2ac48`, and image ID
`sha256:ae7991f35a2093b145245f8037a3227981b09051805467870f759c0752bbfc3d`. The first MCP plan
failed transiently with `remote_operation_failed` while the canary remained healthy; retry plan
`2d8b0fe91ed01b55f1625c27edcc620b` passed, and MCP deploy returned deployed/readiness schema `8`.
Status reported the current revision, `failed: null`, `loopback_only: true`, and pre-deploy backup
`pre-deploy-2de5e9f199cd1457-751c7459.spbackup`. A live in-app-browser reload with an expired
session showed `Sign in first` and `Open sign in` and hid `Create passkey`; opening sign-in and
continuing with GitHub returned to `/passkey?mode=enroll&next=/overview`, showed `Signed in as jtmb`,
and showed `Create passkey`. No ceremony was completed in this browser tab. A read-only operator
SQLite check on `2026-09-28` (exact query UTC not captured) found `quick_check` `ok`, zero foreign-
key violations, owner id `1` claimed to the configured GitHub account as active admin, one
nonrevoked passkey, one current passkey-verified session, and owner mappings of 13 events, 13 runs,
20 results, 0 outcomes, 6 holdings, and 3 watchlist items. This proves enrollment, a completed
passkey verification on another computer, and persisted owner mappings; it does not prove
authenticated browser-rendered UI retrieval. A fresh production tab hit Cloudflare Access login with
no transferable browser session. E55's later read-only Docker access logs observed authenticated owner API
retrieval and saved-forecast access after the passkey session; `/overview`, portfolio, watchlist,
history, and saved-forecast requests returned `200`. Browser-rendered content remains **Unavailable**.
E56 independently passes the four two-client isolation scenarios locally, including cross-watchlist
deletion, member `promote=true` restore denial, nested outcome export, and two-account invitation
reuse/identity binding. E57's rerun of the full local gate also passed after its initial comment-audit
failure. E58 makes the public-invited infrastructure boundary live. E59 retires the legacy Linode
and confirms the replacement is running. E60 records the historical current-machine browser passkey
and sign-out limitation; E61 records the locally accepted logout and mode-aware passkey repair with
independent QA, and E62 records the passing full local gate. The remote image still needs the repair.
Remote two-user behavior, browser-rendered owner content, and functional invited-user acceptance
remain **Unavailable**. Astra final gate review remains pending, so this is not a full production
acceptance claim. Server-observed owner verification and saved API retrieval remain recorded in E52/E55.
See
[Getting started](docs/operations/getting-started.md)
for the current Terraform, recovery, and canary boundaries.

## Development

Read [developer testing](docs/develop/testing.md) for the deterministic Python, frontend,
browser, package, backup, and local-gate checks. The common local commands are:

```bash
./scripts/bootstrap.sh
./scripts/build-frontend.sh
make check
make browser-test
```

Changes to authored documentation should follow the [documentation workflow](docs/develop/documentation.md).
The [architecture guide](docs/concepts/architecture.md), [forecast model](docs/concepts/forecast-model.md),
and [API reference](docs/reference/api.md) are the best places to understand the system before
changing it. Please keep examples local and deterministic, preserve provider and provenance
labels, and do not add credentials or private machine paths to tracked files.

## Project records

The landing page stays deliberately short. The authoritative contract, dependency order, and
evidence history live in the root records:

- [MVP plan](MVP-PLAN.md) — product contract, task register, and evidence ledger.
- [MVP roadmap](MVP-ROADMAP.md) — milestone ordering and status summary.
- [AGENTS.md](AGENTS.md) — repository ownership, evidence, and local-workflow rules.
- [Documentation index](docs/index.md) — authored guides by topic.

## License

No root `LICENSE` file or open-source license has been declared yet. Until a license is added,
the repository should not be treated as granting permission to reuse, modify, or redistribute the
code.
