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
starts in a terminal-404 closed mode before the owner-only canary. The replacement host and
reviewed image are deployed privately, and the canary hostname is routed through the active
tunnel behind the configured owner Access policy with cache bypass. Direct port `8000` remains
unreachable. GitHub OAuth application authorization and the Access one-time-code flow completed,
but callback-code handoff, owner passkey enrollment, and owner saved-data verification remain
pending. The privacy review P2 has been repaired with a private owner-email file, `14` canary
fixture tests, and a successful live canary rerun; final scoped QA passed and Astra's final P1/P2
review reported no remaining finding for that boundary. The invited-user route and retirement of
the legacy Linode remain pending, so this is not a production release claim. See
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
