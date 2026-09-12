---
title: "Dashboard"
description: "How to use the Signal Ledger dashboard to select an instrument, run and interpret forecasts, and search immutable history."
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
