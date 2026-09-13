---
title: "Dashboard"
description: "How to use the Signal Ledger dashboard, its theme and current-headline controls, forecasts, and immutable history."
---

# Dashboard

Start the local app, open its loopback URL, and wait for the system status to report readiness.
The dashboard has three primary areas: Forecast desk, Horizon analysis, and Search ledger.

## Run a forecast

1. Enter a company name or Yahoo Finance symbol.
2. When lookup suggestions appear, choose the identity whose symbol, name, exchange, and
   stock/ETF classification match your intent. Keyboard users can navigate the listbox and
   confirm a choice without a pointer.
3. If entering a symbol directly, select Stock or ETF explicitly.
4. Activate **Run forecast**. Loading and failures are announced in the page; a failed
   submitted search is retained in the ledger with its request ID.

The result compares close-to-close with completed-five-minute-bar-to-close. Read direction
probabilities, tail thresholds, conditional magnitude, central return/price intervals, origin
and target times, sample counts, evaluation, provider as-of time, model/version, and quality
reasons together. A stale badge is a warning with explicit reasons, not permission to silently
treat old data as current. See [forecast model](../concepts/forecast-model.md) for definitions.

## Choose a color theme

Use **Color theme** to select **Light**, **Dark**, or **System**. Light and Dark are saved under
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
motion preferences are respected. Report an actual screen-reader gap separately; automated
accessibility checks are not a substitute for assistive-technology evidence.

For endpoint details, see the [API reference](../reference/api.md).
