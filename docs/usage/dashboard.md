---
title: "Dashboard"
description: "How to use the Signal Ledger dashboard, its theme and current-headline controls, forecasts, and immutable history."
---

# Dashboard

Start the local app, open its loopback URL, and wait for the system status to report readiness.
The local workspace keeps portfolio context, recorded research, and bounded market tools separate;
it is not a brokerage or order-entry system.

## Navigate the research workspace

The shared navigation exposes these routes:

| Route | Purpose |
| --- | --- |
| `/overview` | Maintain manually entered portfolio holdings as research context. |
| `/research` | Open the recorded forecast ledger, Forecast tool, or Markets tool. |
| `/tools` | Choose Forecast, Live Trading, or Markets without submitting a request. |
| `/tools/forecast` | Submit one explicit rolling-horizon forecast. |
| `/tools/live-trading` | Inspect provider-labelled quote context for manual holdings; no orders. |
| `/tools/markets` | Maintain a watchlist, filter quote snapshots, and inspect a daily chart. |

The root `/` remains the original forecast-and-ledger surface: it provides instrument lookup,
the legacy two-horizon comparison, immutable history, current-headline disclosure, and saved or
fresh-analysis actions. Opening a workspace route with a selected symbol only restores context;
it never submits a forecast or saves a holding automatically.

## Maintain portfolio and watchlist context

On **Overview**, add one stock or ETF with a manually entered quantity. The value is stored in the
local portfolio list and is not a broker position, valuation, order, or real-time balance. On
**Markets**, add or remove watchlist instruments, then filter by symbol/name, exchange, asset type,
price, percentage change, volume, or an additional quote metric. Watchlist and portfolio records
are local bounded lists; quote snapshots are refreshed by the browser while symbols exist and
always disclose provider, as-of time, state, and any delay.

On **Live Trading**, the page can edit a bounded `SYMBOL: quantity` portfolio draft, select a
returned quote, save browser-local notes, and create active-page-only price thresholds. Notes are
not sent to the server; alerts have no scheduler or delivery path. The page has no order controls,
brokerage connection, execution endpoint, or live-trading guarantee. Market depth is explicitly
unavailable: no `/api/v1/market-depth` endpoint exists, no bid/ask rows are fabricated, and Nasdaq
TotalView or exchange-depth entitlement is not claimed.

On **Markets**, choose `5d`, `1mo`, `3mo`, `6mo`, or `1y` for the selected chart. The chart response
uses daily bars (`interval=1d`); it is bounded provider context, not an intraday or real-time feed.

## Run a forecast

1. Enter a company name or Yahoo Finance symbol on `/` or `/tools/forecast`.
2. When lookup suggestions appear, choose the identity whose symbol, name, exchange, and
   stock/ETF classification match your intent. Keyboard users can navigate the listbox and
   confirm a choice without a pointer.
3. If entering a symbol directly, select Stock or ETF explicitly. On the Forecast tool, also
   select `5min`, `daily`, `weekly`, `monthly`, or `quarterly`; the form shows the exact origin
   and target boundary before submission.
4. Activate **Run forecast**. Loading and failures are announced in the page; a failed
   submitted search is retained in the ledger with its request ID.

The root result compares close-to-close with completed-five-minute-bar-to-close. A selected
Forecast-tool interval returns one rolling horizon: five-minute forward, one session, five
sessions, 21 sessions, or 63 sessions. Read direction probabilities, tail thresholds, conditional
magnitude, central return/price intervals, origin and target times, sample counts, evaluation,
provider as-of time, model/version, and quality reasons together. An unavailable horizon is shown
with its explicit reason rather than being filled with a different horizon. A stale badge is a
warning with explicit reasons, not permission to silently treat old data as current. See
[forecast model](../concepts/forecast-model.md) for definitions.

## Use Settings and choose a color theme

Open the native **Settings** popover and select **Light**, **Dark**, or **System**. The
`R-ASTRA-59` repair corrected the popover's open-state anchor; the current supplied QA reports
all `8/8` focus-geometry checks passing. Light and Dark are saved under
`stock-probs.theme` in browser local storage. Selecting System removes that override and follows
the operating-system preference, including later system changes while no explicit choice exists.
The preference is scoped to the browser origin, so another browser profile, host name, or port
can have a different choice; the dashboard and `/api/v1/docs` share it when opened on the same
origin. If storage is unavailable, the control still works for the current page but cannot
persist the override.

Printing uses the light print palette and hides the theme control. It does not reset or replace
the saved screen preference.

## Read current headlines

Each displayed forecast has a closed **Current headlines for this symbol** disclosure. Opening
it makes a local `/api/v1/news` request for five items; use **Show up to 10 headlines** when five
are returned. The disclosure communicates each possible state explicitly:

- **Not requested:** the disclosure has not been opened, so no news request was made.
- **Loading:** the bounded request is in progress; a browser-side timeout prevents indefinite
  waiting.
- **Fresh:** current items include provider/as-of information and available publication details.
- **Empty:** the provider successfully returned no current items; this is not a missing page,
  and source/as-of information remains visible.
- **Partial metadata:** items are shown without inventing omitted publisher, time, or related data.
- **Stale cached with refresh failure:** cached items and their original as-of time remain visible
  with a warning that refresh failed.
- **Provider unavailable without cache**, **local service unreachable**, and **capacity busy** are
  distinct failures rather than empty results. Use **Retry headlines** for a new manual attempt;
  retries do not rerun the forecast or happen automatically.
- **Instrument changed/request superseded:** the old request is cancelled and cannot populate the
  newly selected instrument.

Headline text and links are untrusted provider content. An operable link is marked **External
site**, opens a new browser context, and leaves the local application for its public HTTPS
destination; review it before navigating. Unsafe links are shown as unavailable rather than
opened, and Stock Probability does not fetch or proxy article pages.

Headlines are current, ephemeral context, not forecast or ledger evidence. Reopening a saved
forecast remains provider-free and makes no automatic headline request; its separately labelled
**Load current headlines for this symbol** action requests current information and does not alter
the saved result. Headlines are not included in history exports or backups.

Provider search results are not a guarantee of exact-symbol news availability or semantic
relevance. Real ACDC/SPY flow evidence demonstrates the application/provider path only; it does
not make every returned headline relevant to the requested symbol.

## Use the ledger

Filter by symbol/company, status, asset type, analysis type, date, model, or horizon; choose a
sort and bounded page size, then activate **Filter ledger**. CSV and JSON links preserve the
active filter/sort context. The exports are bounded audit records, not a database copy.

**Reopen saved forecast** reads the immutable captured result and displays later append-only
outcomes separately. It does not call the provider or recalculate. **Run fresh cutoff analysis**
uses the saved event's historical cutoff, calls the configured provider, and creates another
audited event in the separate Fresh historical-cutoff analysis region. Never compare these two
actions as if they had the same provenance.

Use the skip link and section navigation to move between regions. Charts expose text and table
values, interactive points are keyboard focusable, status changes use live regions, and reduced
motion preferences are respected. Browser viewport emulation is not physical-mobile or true-zoom
evidence. Report an actual screen-reader gap separately; automated accessibility checks are not a
substitute for assistive-technology evidence.

For endpoint details, see the [API reference](../reference/api.md).
