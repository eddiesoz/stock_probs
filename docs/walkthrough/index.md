---
title: "Stock Probability walkthrough"
description: "An annotated desktop and mobile walkthrough of forecasts, history, themes, and current-headline states."
---

# Stock Probability walkthrough

Follow these steps in order on the local dashboard. The desktop and mobile figures are annotated Chromium captures; mobile figures use emulation, not a physical phone.

Generation revision: `cf099754a5c3e4a05f0e785c0d65ff06f96c4d63` (dirty working tree)  
Generated UTC: `2026-09-13T00:32:43.223Z`  
Command: `./scripts/capture-walkthrough.sh`

> Forecasts and news use deterministic walkthrough fixtures. Every news figure is a simulated production UI response at the fixture clock (10 Jan 2025, 17:03 UTC), not live Yahoo Finance evidence.

## 01. Confirm the local service and backup status

**Do:** Open the dashboard and confirm that the status line says ready, fixture provider, and backup available.

**Expect:** The ready status identifies deterministic fixture data and says managed backups are available; backup and restore are not exposed in the UI.

![Dashboard masthead with ready, fixture provider, and backup available status labels.](images/desktop-01-backup-status.png)

*Desktop: The ready status identifies deterministic fixture data and says managed backups are available; backup and restore are not exposed in the UI.*

![Dashboard masthead with ready, fixture provider, and backup available status labels.](images/mobile-01-backup-status.png)

*Mobile: The ready status identifies deterministic fixture data and says managed backups are available; backup and restore are not exposed in the UI.*

## 02. Use company-name lookup

**Do:** Type ProFrac in the instrument field, then choose ProFrac Holding Corp. from the result list.

**Expect:** The ProFrac query returns one selectable ACDC stock result.

![Instrument search containing ProFrac with a ProFrac Holding Corp., ACDC result card.](images/desktop-02-company-lookup.png)

*Desktop: The ProFrac query returns one selectable ACDC stock result.*

![Instrument search containing ProFrac with a ProFrac Holding Corp., ACDC result card.](images/mobile-02-company-lookup.png)

*Mobile: The ProFrac query returns one selectable ACDC stock result.*

## 03. Confirm the selected symbol identity

**Do:** Press Arrow Down and Enter, or tap the result, then check the confirmed ACDC identity before continuing.

**Expect:** The confirmation shows ACDC, NMS, USD, America/New_York, and Stock.

![Confirmed identity panel for ProFrac Holding Corp. showing symbol ACDC and stock metadata.](images/desktop-03-symbol-identity.png)

*Desktop: The confirmation shows ACDC, NMS, USD, America/New_York, and Stock.*

![Confirmed identity panel for ProFrac Holding Corp. showing symbol ACDC and stock metadata.](images/mobile-03-symbol-identity.png)

*Mobile: The confirmation shows ACDC, NMS, USD, America/New_York, and Stock.*

## 04. Run the stock forecast

**Do:** Select Stock, run the ACDC forecast, and compare the Close → next close and Completed 5m → close cards.

**Expect:** The ACDC result presents direction probabilities for both forecast origins.

![ACDC forecast comparison with close-to-close and completed-five-minute-to-close result cards.](images/desktop-04-stock-horizons.png)

*Desktop: The ACDC result presents direction probabilities for both forecast origins.*

![ACDC forecast comparison with close-to-close and completed-five-minute-to-close result cards.](images/mobile-04-stock-horizons.png)

*Mobile: The ACDC result presents direction probabilities for both forecast origins.*

## 05. Read a chart point and its table equivalent

**Do:** Focus the −10% chart point, read its 0.6% probability, then continue to the matching Return at or below −10% table row.

**Expect:** The focused −10% point and the continuation table row both report 0.6%.

![Focused minus-ten-percent chart point with a tooltip reporting 0.6 percent at or below minus ten percent.](images/desktop-05-chart-and-table.png)

*Desktop: The focused −10% point and the continuation table row both report 0.6%.*

![Details table row for return at or below minus ten percent showing 0.6 percent.](images/desktop-05-chart-and-table-table-continuation.png)

*Continuation: The matching table row reports 0.6%, the same value as the focused −10% chart point.*

![Focused minus-ten-percent chart point with a tooltip reporting 0.6 percent at or below minus ten percent.](images/mobile-05-chart-and-table.png)

*Mobile: The focused −10% point and the continuation table row both report 0.6%.*

![Details table row for return at or below minus ten percent showing 0.6 percent.](images/mobile-05-chart-and-table-table-continuation.png)

*Continuation: The matching table row reports 0.6%, the same value as the focused −10% chart point.*

## 06. Run the ETF forecast

**Do:** Enter SPY, select ETF, run the forecast, and compare the same two forecast horizons.

**Expect:** The SPY ETF result uses the close-to-close and completed-five-minute-to-close origins.

![SPY ETF forecast with two horizon cards and direction probabilities.](images/desktop-06-etf-horizons.png)

*Desktop: The SPY ETF result uses the close-to-close and completed-five-minute-to-close origins.*

![SPY ETF forecast with two horizon cards and direction probabilities.](images/mobile-06-etf-horizons.png)

*Mobile: The SPY ETF result uses the close-to-close and completed-five-minute-to-close origins.*

## 07. Search and filter the ledger

**Do:** Set symbol to SPY, status to Successful, and asset type to ETF; select Filter ledger and inspect the matching result.

**Expect:** The active filters narrow the ledger to the successful SPY ETF event.

![History ledger filtered to a single successful SPY ETF result.](images/desktop-07-history-filter.png)

*Desktop: The active filters narrow the ledger to the successful SPY ETF event.*

![History ledger filtered to a single successful SPY ETF result.](images/mobile-07-history-filter.png)

*Mobile: The active filters narrow the ledger to the successful SPY ETF event.*

## 08. Reopen the immutable saved forecast

**Do:** Select Reopen saved forecast on the SPY event and confirm the immutable recorded-result label.

**Expect:** Saved event 2 reopens as an immutable recorded SPY result.

![Reopened SPY forecast headed Immutable recorded result and audit event 2.](images/desktop-08-saved-reopen.png)

*Desktop: Saved event 2 reopens as an immutable recorded SPY result.*

![Reopened SPY forecast headed Immutable recorded result and audit event 2.](images/mobile-08-saved-reopen.png)

*Mobile: Saved event 2 reopens as an immutable recorded SPY result.*

## 09. Run a fresh historical-cutoff analysis

**Do:** Select Run fresh cutoff analysis and verify that the new calculation is labelled Not the saved forecast.

**Expect:** Fresh event 3 appears separately with its historical cutoff and leaves the saved result unchanged.

![Fresh analysis panel labelled Not the saved forecast with a new event and historical cutoff.](images/desktop-09-fresh-reconstruction.png)

*Desktop: Fresh event 3 appears separately with its historical cutoff and leaves the saved result unchanged.*

![Fresh analysis panel labelled Not the saved forecast with a new event and historical cutoff.](images/mobile-09-fresh-reconstruction.png)

*Mobile: Fresh event 3 appears separately with its historical cutoff and leaves the saved result unchanged.*

## 10. Download the filtered CSV and JSON

**Do:** Keep the SPY, Successful, and ETF filters active; select Download CSV and Download JSON to save history.csv and history.json.

**Expect:** The two download controls export the currently filtered SPY history in CSV and JSON formats.

![Filtered history controls with Download CSV and Download JSON links visible.](images/desktop-10-history-downloads.png)

*Desktop: The two download controls export the currently filtered SPY history in CSV and JSON formats.*

![Filtered history controls with Download CSV and Download JSON links visible.](images/mobile-10-history-downloads.png)

*Mobile: The two download controls export the currently filtered SPY history in CSV and JSON formats.*

Generated examples: [desktop CSV](downloads/desktop/history.csv), [desktop JSON](downloads/desktop/history.json), [mobile CSV](downloads/mobile/history.csv), and [mobile JSON](downloads/mobile/history.json). Each export contains the active SPY / Successful / ETF filter context.

## 11. Follow the system theme

**Do:** Choose System in the theme control and confirm that the dashboard follows the current dark system preference.

**Expect:** System is selected while the dashboard follows a dark operating-system preference.

![Dark dashboard masthead with System selected in the color theme control.](images/desktop-11-theme-system.png)

*Desktop: System is selected while the dashboard follows a dark operating-system preference.*

![Dark dashboard masthead with System selected in the color theme control.](images/mobile-11-theme-system.png)

*Mobile: System is selected while the dashboard follows a dark operating-system preference.*

## 12. Choose explicit dark mode

**Do:** Choose Dark in the theme control and confirm that the dashboard changes to the explicit dark theme.

**Expect:** Dark is selected as an explicit preference rather than inherited from the system.

![Dashboard in dark colors with Dark selected in the theme control.](images/desktop-12-theme-dark.png)

*Desktop: Dark is selected as an explicit preference rather than inherited from the system.*

![Dashboard in dark colors with Dark selected in the theme control.](images/mobile-12-theme-dark.png)

*Mobile: Dark is selected as an explicit preference rather than inherited from the system.*

## 13. Reset the theme to system

**Do:** Choose System again to remove the explicit theme choice and return to the current light system preference.

**Expect:** System is selected and the dashboard has returned to the light system theme.

![Light dashboard masthead after the color theme control is reset to System.](images/desktop-13-theme-reset.png)

*Desktop: System is selected and the dashboard has returned to the light system theme.*

![Light dashboard masthead after the color theme control is reset to System.](images/mobile-13-theme-reset.png)

*Mobile: System is selected and the dashboard has returned to the light system theme.*

## 14. Open the loaded dark API page

**Do:** Choose Dark, open the local API documentation, and inspect the fully loaded dark page; first paint timing is recorded separately.

**Expect:** This image shows the settled dark API page, not the earlier paint transition.

![Loaded local API documentation page using the dark theme.](images/desktop-14-theme-first-paint.png)

*Desktop: This image shows the settled dark API page, not the earlier paint transition.*

![Loaded local API documentation page using the dark theme.](images/mobile-14-theme-first-paint.png)

*Mobile: This image shows the settled dark API page, not the earlier paint transition.*

## 15. Load fresh current headlines

**Do:** Open current headlines and inspect all five items. Simulated response — fixture clock 10 Jan 2025, 17:03 UTC.

**Expect:** The simulated fresh response shows five SPY headlines, source, as-of time, publication metadata, and safe links.

![SPY news panel with five simulated fresh headlines at the 10 January 2025 fixture clock.](images/desktop-15-news-fresh.png)

*Desktop: The simulated fresh response shows five SPY headlines, source, as-of time, publication metadata, and safe links.*

![SPY news panel with five simulated fresh headlines at the 10 January 2025 fixture clock.](images/mobile-15-news-fresh.png)

*Mobile: The simulated fresh response shows five SPY headlines, source, as-of time, publication metadata, and safe links.*

## 16. Show an honest empty news result

**Do:** Open current headlines and confirm the successful empty message. Simulated response — fixture clock 10 Jan 2025, 17:03 UTC.

**Expect:** The simulated empty response says no current headlines were returned and does not present a provider error.

![SPY news panel showing a simulated successful empty state at the fixture clock.](images/desktop-16-news-empty.png)

*Desktop: The simulated empty response says no current headlines were returned and does not present a provider error.*

![SPY news panel showing a simulated successful empty state at the fixture clock.](images/mobile-16-news-empty.png)

*Mobile: The simulated empty response says no current headlines were returned and does not present a provider error.*

## 17. Label partial headline metadata

**Do:** Inspect item 1 and confirm it remains usable without publisher or publication time. Simulated response — fixture clock 10 Jan 2025, 17:03 UTC.

**Expect:** In the simulated partial response, item 1 lacks publisher and time while the remaining headline data stays available.

![Simulated partial SPY headline list whose first item has no publisher or publication time.](images/desktop-17-news-partial.png)

*Desktop: In the simulated partial response, item 1 lacks publisher and time while the remaining headline data stays available.*

![Simulated partial SPY headline list whose first item has no publisher or publication time.](images/mobile-17-news-partial.png)

*Mobile: In the simulated partial response, item 1 lacks publisher and time while the remaining headline data stays available.*

## 18. Explain stale cached headlines

**Do:** Inspect the retained cached headlines and their warning. Simulated stale fallback — fixture clock 10 Jan 2025, 17:03 UTC.

**Expect:** The simulated stale fallback keeps cached headlines visible and labels the displayed as-of time as cached after refresh failure.

![Simulated stale SPY news panel with cached headlines and a refresh-failed warning.](images/desktop-18-news-stale.png)

*Desktop: The simulated stale fallback keeps cached headlines visible and labels the displayed as-of time as cached after refresh failure.*

![Simulated stale SPY news panel with cached headlines and a refresh-failed warning.](images/mobile-18-news-stale.png)

*Mobile: The simulated stale fallback keeps cached headlines visible and labels the displayed as-of time as cached after refresh failure.*

## 19. Report provider failure without cache

**Do:** Open current headlines and read the unavailable message. Simulated provider failure with no cache — fixture clock 10 Jan 2025, 17:03 UTC.

**Expect:** The simulated provider failure reports that no cached headlines can be shown and remains distinct from an empty result.

![SPY news panel showing a simulated provider-unavailable state with no cached headlines.](images/desktop-19-news-provider-failure.png)

*Desktop: The simulated provider failure reports that no cached headlines can be shown and remains distinct from an empty result.*

![SPY news panel showing a simulated provider-unavailable state with no cached headlines.](images/mobile-19-news-provider-failure.png)

*Mobile: The simulated provider failure reports that no cached headlines can be shown and remains distinct from an empty result.*

## 20. Keep saved evidence separate from current headlines

**Do:** Reopen the saved SPY forecast and leave Load current headlines for this symbol closed; use it only when current information is wanted.

**Expect:** The closed disclosure keeps current headlines separate; the recorded request-count delta for saved reopen is zero.

![Immutable saved SPY forecast with the Load current headlines disclosure closed.](images/desktop-20-saved-current-news.png)

*Desktop: The closed disclosure keeps current headlines separate; the recorded request-count delta for saved reopen is zero.*

![Closed Load current headlines disclosure beneath the immutable saved SPY forecast.](images/desktop-20-saved-current-news-closed-disclosure.png)

*Continuation: The closed disclosure is a separate optional action; saved reopen produced a zero news-request delta.*

![Immutable saved SPY forecast with the Load current headlines disclosure closed.](images/mobile-20-saved-current-news.png)

*Mobile: The closed disclosure keeps current headlines separate; the recorded request-count delta for saved reopen is zero.*

![Closed Load current headlines disclosure beneath the immutable saved SPY forecast.](images/mobile-20-saved-current-news-closed-disclosure.png)

*Continuation: The closed disclosure is a separate optional action; saved reopen produced a zero news-request delta.*

## Companion news states

These states remain attached to step 20 rather than extending the 20-step journey.

### Desktop

**Headlines not requested.** Reopen the saved result and leave the current-headlines disclosure closed.

![Closed Load current headlines disclosure beneath the immutable saved SPY forecast.](images/desktop-20-saved-current-news-closed-disclosure.png)

*The closed saved-result disclosure is shown and the measured news-request delta is zero.*

**Headline capacity busy.** Read the busy message and retry later; this is a simulated 503 at the fixture clock.

![Current-headlines panel showing a simulated capacity-busy message.](images/desktop-20-news-capacity-busy.png)

*A simulated 503 response is presented as a retryable capacity state.*

**Local service unreachable.** Check the local service when this message appears; the walkthrough simulates the fetch rejection.

![Current-headlines panel showing a simulated local service unreachable message.](images/desktop-20-news-local-unreachable.png)

*A simulated local network failure is distinct from an upstream provider failure.*

**Headlines loading.** Wait while the live region reports loading; this walkthrough response remains deliberately pending.

![Current-headlines panel displaying a simulated loading message.](images/desktop-20-news-loading.png)

*The simulated pending response exposes its in-progress state.*

**Instrument changed and request superseded.** Change the instrument while loading and confirm the superseded message replaces the old request.

![Current-headlines panel showing that a simulated request was superseded after the instrument changed.](images/desktop-20-news-superseded.png)

*The capture observed the pending stub's abort event and asserted that no headline items remained.*

### Mobile

**Headlines not requested.** Reopen the saved result and leave the current-headlines disclosure closed.

![Closed Load current headlines disclosure beneath the immutable saved SPY forecast.](images/mobile-20-saved-current-news-closed-disclosure.png)

*The closed saved-result disclosure is shown and the measured news-request delta is zero.*

**Headline capacity busy.** Read the busy message and retry later; this is a simulated 503 at the fixture clock.

![Current-headlines panel showing a simulated capacity-busy message.](images/mobile-20-news-capacity-busy.png)

*A simulated 503 response is presented as a retryable capacity state.*

**Local service unreachable.** Check the local service when this message appears; the walkthrough simulates the fetch rejection.

![Current-headlines panel showing a simulated local service unreachable message.](images/mobile-20-news-local-unreachable.png)

*A simulated local network failure is distinct from an upstream provider failure.*

**Headlines loading.** Wait while the live region reports loading; this walkthrough response remains deliberately pending.

![Current-headlines panel displaying a simulated loading message.](images/mobile-20-news-loading.png)

*The simulated pending response exposes its in-progress state.*

**Instrument changed and request superseded.** Change the instrument while loading and confirm the superseded message replaces the old request.

![Current-headlines panel showing that a simulated request was superseded after the instrument changed.](images/mobile-20-news-superseded.png)

*The capture observed the pending stub's abort event and asserted that no headline items remained.*

## Evidence boundaries

- The main set contains 20 desktop and 20 mobile figures. Continuation figures show the −10% table row, closed current-headlines disclosure, and simulated busy, unreachable, loading, and superseded states.
- The capture context bypasses CSP only to add annotations. Separate first-paint observations run without CSP bypass; screenshots show settled pages and do not prove a transition by themselves.
- Saved-result reopen records and asserts a zero browser news-request delta. Backend provider-free behavior remains separate QA evidence.
- Backup and restore are not exposed in the UI. Use the documented local CLI for those operations.
- Static PNGs are authoritative. No GIF encoder or animation dependency is required.

