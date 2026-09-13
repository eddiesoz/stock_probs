---
title: "ASTRA-FINAL evidence matrix"
description: "Tracked 214-row inventory of product assets, controls, states, walkthrough media, and persistence effects reviewed by ASTRA-FINAL."
---

# ASTRA-FINAL evidence matrix

This matrix was first published for `R-ASTRA-19` and corrected for `R-ASTRA-21`. The final
re-evaluation found that the earlier 211-row inventory omitted three rendered controls and did
not bind every row to all five evaluation dimensions. Existing IDs remain unchanged; `C035`–
`C037` bring the inventory to 214 rows. The separate [evaluation report](astra-final-report.md)
records the four lanes, repair program, re-evaluation verdicts, evidence scheme, and limits.

## Verdict and limitation key

The verdict and limitation columns preserve the first review so its findings remain auditable;
the [report](astra-final-report.md#four-evaluation-lanes-and-re-evaluation-verdicts) records the
supplied final re-evaluation disposition.

- **Meets** reproduces a supplied review row with no recorded finding.
- **Acceptable** identifies bounded evidence that can support re-evaluation but is not final
  acceptance.
- **Needs improvement** preserves a first-review finding; it is not the current re-evaluation
  verdict.
- **Accepted** is reserved for an independently completed ASTRA re-evaluation; no row uses it.
- **L1:** exact original ASTRA command, environment, UTC, commit, artifact revision, and reviewer
  were not supplied; the later ASTRA session IDs are recorded in the report's `EV-10`–`EV-12`.
- **L2:** the cited SOL repair was implementation evidence at first review. The affected rows are
  independently bound by `EV-9`; L2 remains historical only where it is retained on an unaffected
  first-review row.
- **L3:** news evidence is a deterministic simulated response, not live provider evidence.
- **L4:** mobile evidence is Chromium emulation at 390×844, not a physical phone.
- **L5:** a settled screenshot does not by itself prove first-paint ordering.
- **L6:** actual screen-reader and native/physical ARM64 performance evidence remain unavailable.
- **L7:** the original walkthrough publication used a dirty revision; `EV-9` supplies the
  revision-bound repair-QA observation for the affected rows, but no `EXP-M08` or export
  checkpoint is supplied here.

## Per-row five-dimension evidence keys

The **Evidence reference** in each row remains the item-specific source. For every row ID
`<ID>`, the compact keys `<ID>-AE`, `<ID>-MO`, `<ID>-RE`, `<ID>-AX`, and `<ID>-PE` respectively
mean aesthetic, mobile, responsive, accessibility, and measured-performance evidence. Resolve
the row's prefix and those five keys through the [report's evidence map](astra-final-report.md#per-row-five-dimension-evidence-map).
An unavailable or non-applicable observation is recorded there rather than inferred as a pass.

## Revision-bound keys for affected rows

The following entries resolve the five keys for every row named in the repair-QA receipt. `EV-8`
is the final `M07` release gate on clean commit `f511ae3629de679b12c006db5d122b3ed0a22f2c`,
`EV-9` is the independent repair-QA session, and `EV-11`/`EV-12` are the ASTRA re-evaluation and
concluding verdict. A cell that says **unavailable** records a limitation; it is not a pass.

| Row | Aesthetic (`-AE`) | Mobile (`-MO`) | Responsive (`-RE`) | Accessibility (`-AX`) | Measured performance (`-PE`) |
| --- | --- | --- | --- | --- | --- |
| row `H004` | `EV-11`/`EV-12`: return-tail chart legibility/typography resolved. | `EV-9`: paired 390×844 chart/table observation; physical mobile unavailable. | `EV-8`: browser 48 passed/2 expected skips; static shell 97,952 bytes. | `EV-9`/`EV-12`: browser/ASTRA review; actual screen reader unavailable. | `EV-8`: 17 executable rows passed; ARM64 performance unavailable. |
| row `H005` | `EV-11`/`EV-12`: axes, tick labels, and legend legibility resolved. | `EV-9`: paired 390×844 chart/table observation; physical mobile unavailable. | `EV-8`: official MCP/browser release observation and static shell 97,952 bytes. | `EV-9`/`EV-12`: browser/ASTRA review; actual screen reader unavailable. | `EV-8`: 17 executable rows passed; ARM64 performance unavailable. |
| row `V005` | `EV-9`/`EV-12`: desktop chart/table frame present and resolved. | `EV-9`: paired mobile evidence is emulated; physical mobile unavailable. | `EV-9`: desktop/mobile capture pairing; walkthrough observation 7,660,518 bytes. | `EV-9`/`EV-12`: caption/alt-text and ASTRA review; actual screen reader unavailable. | `EV-9`: walkthrough observation 7,660,518 bytes; native/physical ARM64 performance unavailable. |
| row `V031` | `EV-9`/`EV-12`: mobile chart/table frame present and resolved. | `EV-9`: 390×844 emulation; physical mobile unavailable. | `EV-9`: paired desktop/mobile capture observation. | `EV-9`/`EV-12`: caption/alt-text and ASTRA review; actual screen reader unavailable. | `EV-9`: walkthrough observation 7,660,518 bytes; native/physical ARM64 performance unavailable. |
| row `S021` | `EV-11`/`EV-12`: fresh cutoff analysis remained distinct from saved evidence. | `EV-9`: mobile state capture is emulated; physical mobile unavailable. | `EV-8`/`EV-9`: browser and capture receipt. | `EV-9`/`EV-12`: state/control review; actual screen reader unavailable. | `EV-8`: 17 executable rows passed; ARM64 performance unavailable. |
| row `A020` | `EV-11`/`EV-12`: fresh reconstruction endpoint remained separately labelled. | `EV-9`: API-only row has no independent physical-mobile surface. | `EV-8`/`EV-9`: browser/API boundary release observation. | `EV-9`/`EV-12`: API/UI review; actual screen reader unavailable. | `EV-8`: 17 executable rows passed; ARM64 performance unavailable. |
| row `W009` | `EV-9`/`EV-12`: step 09 distinguishes new cutoff analysis from saved evidence. | `EV-9`: paired mobile step is emulated; physical mobile unavailable. | `EV-9`: desktop/mobile capture pairing; walkthrough observation 7,660,518 bytes. | `EV-9`/`EV-12`: instructional text/caption review; actual screen reader unavailable. | `EV-9`: walkthrough observation 7,660,518 bytes; native/physical ARM64 performance unavailable. |
| row `V009` | `EV-9`/`EV-12`: desktop fresh-reconstruction frame present and resolved. | `EV-9`: paired mobile evidence is emulated; physical mobile unavailable. | `EV-9`: desktop/mobile capture pairing. | `EV-9`/`EV-12`: caption/alt-text and ASTRA review; actual screen reader unavailable. | `EV-9`: walkthrough observation 7,660,518 bytes; native/physical ARM64 performance unavailable. |
| row `V035` | `EV-9`/`EV-12`: mobile fresh-reconstruction frame present and resolved. | `EV-9`: 390×844 emulation; physical mobile unavailable. | `EV-9`: paired desktop/mobile capture observation. | `EV-9`/`EV-12`: caption/alt-text and ASTRA review; actual screen reader unavailable. | `EV-9`: walkthrough observation 7,660,518 bytes; native/physical ARM64 performance unavailable. |
| row `W020` | `EV-11`/`EV-12`: saved evidence stayed separate from current news. | `EV-9`: paired news evidence is emulated; physical mobile unavailable. | `EV-8`/`EV-9`: browser/MCP and capture observations. | `EV-9`/`EV-12`: saved/current-news and abort-path review; actual screen reader unavailable. | `EV-8`: 17 executable rows passed; ARM64 performance unavailable. |
| row `N010` | `EV-11`/`EV-12`: superseded request state resolved without stale-symbol headlines. | `EV-9`: superseded-news mobile capture is emulated; physical mobile unavailable. | `EV-9`: capture selector/abort assertions passed. | `EV-9`/`EV-12`: terminal-state review; actual screen reader unavailable. | `EV-8`: 17 executable rows passed; ARM64 performance unavailable. |
| row `V026` | `EV-9`/`EV-12`: desktop superseded-news frame represents the aborted request. | `EV-9`: paired mobile evidence is emulated; physical mobile unavailable. | `EV-9`: capture selector/abort assertions passed. | `EV-9`/`EV-12`: caption/alt-text and ASTRA review; actual screen reader unavailable. | `EV-9`: walkthrough observation 7,660,518 bytes; native/physical ARM64 performance unavailable. |
| row `V052` | `EV-9`/`EV-12`: mobile superseded-news frame represents the aborted request. | `EV-9`: 390×844 emulation; physical mobile unavailable. | `EV-9`: capture selector/abort assertions passed. | `EV-9`/`EV-12`: caption/alt-text and ASTRA review; actual screen reader unavailable. | `EV-9`: walkthrough observation 7,660,518 bytes; native/physical ARM64 performance unavailable. |
| row `M001` | `EV-9`/`EV-12`: manifest/artifact evidence reviewed with the corrected matrix. | `EV-9`: mobile manifest/artifact observation is emulated; physical mobile unavailable. | `EV-9`: desktop/mobile artifact pairing; matrix count 214. | `EV-9`/`EV-12`: manifest/transcript/alt-text review; actual screen reader unavailable. | `EV-9`: walkthrough observation 7,660,518 bytes; native/physical ARM64 performance unavailable. |
| row `C035` | `EV-9`/`EV-12`: bounded “show up to 10 headlines” control resolved. | `EV-9`: control evidence at emulated mobile; physical mobile unavailable. | `EV-8`: browser 48 passed/2 expected skips and official MCP. | `EV-9`/`EV-12`: browser/control review; actual screen reader unavailable. | `EV-8`: 17 executable rows passed; ARM64 performance unavailable. |
| row `C036` | `EV-9`/`EV-12`: detailed-provenance control from the stale reason resolved. | `EV-9`: control evidence at emulated mobile; physical mobile unavailable. | `EV-8`: browser 48 passed/2 expected skips and official MCP. | `EV-9`/`EV-12`: browser/control review; actual screen reader unavailable. | `EV-8`: 17 executable rows passed; ARM64 performance unavailable. |
| row `C037` | `EV-9`/`EV-12`: failed-request control opened immutable audit detail. | `EV-9`: control evidence at emulated mobile; physical mobile unavailable. | `EV-8`: browser 48 passed/2 expected skips and official MCP. | `EV-9`/`EV-12`: browser/control review; actual screen reader unavailable. | `EV-8`: 17 executable rows passed; ARM64 performance unavailable. |

## Inventory summary

| Inventory | IDs | Rows |
| --- | --- | ---: |
| Product, route, and static assets | `A001`–`A035` | 35 |
| Controls | `C001`–`C037` | 37 |
| General UI states | `S001`–`S021` | 21 |
| Charts and tables | `H001`–`H008` | 8 |
| Theme states | `T001`–`T012` | 12 |
| News states | `N001`–`N010` | 10 |
| Documentation visuals / walkthrough frames | `V001`–`V052` | 52 |
| Supporting media | `M001`–`M006` | 6 |
| Walkthrough segments | `W001`–`W020` | 20 |
| Persistence effects | `P001`–`P013` | 13 |
| **Total** |  | **214** |

## Product, route, and static assets

| ID | Item/source | Requirement served | Verdict | Evidence reference | Limitation |
| --- | --- | --- | --- | --- | --- |
| `A001` | Dashboard shell, `static/index.html` | Local responsive forecast UI and semantic document structure | Meets | `ASTRA-FINAL-E2`; `M09-E18` | L1, L6 |
| `A002` | API documentation shell, `static/api-docs.html` | Local inspectable API contract without remote UI dependencies | Needs improvement | `R-ASTRA-1`–`R-ASTRA-5` API-docs label repair | L1, L2 |
| `A003` | Stylesheet, `static/app.css` | Responsive visual system, contrast, forced colors, print, and motion | Needs improvement | `R-ASTRA-1`–`R-ASTRA-5` | L1, L2, L6 |
| `A004` | Theme initializer, `static/theme.js` | Parser-blocking no-flash theme selection on both pages | Acceptable | `R-ASTRA-12`; `M09-E18` package receipt | L1, L2, L5 |
| `A005` | Dashboard behavior, `static/app.js` | Accessible forecast, history, chart, and news interactions | Needs improvement | `R-ASTRA-6`–`R-ASTRA-10` | L1, L2, L6 |
| `A006` | Product icon, `static/favicon.svg` | Local branded icon with accessible SVG label | Meets | `ASTRA-FINAL-E2`; packaged static inventory | L1 |
| `A007` | `GET /` | Serve the browser dashboard over loopback | Meets | `M07-E18`; `src/stock_probs/api.py` | L1 |
| `A008` | `GET /api/v1/docs` | Serve local API guidance under strict CSP | Needs improvement | `R-ASTRA-1`–`R-ASTRA-5`; `M09-E18` | L1, L2 |
| `A009` | `GET /api/v1/openapi.json` | Machine-readable closed API contract | Meets | `M07-E18`; `docs/reference/api.md` | L1 |
| `A010` | `GET /api/v1/health` | Bounded local process health result | Meets | `M07-E18`; API route inventory | L1 |
| `A011` | `GET /api/v1/readiness` | Readiness with schema and provider identity | Meets | `M07-E18`; API route inventory | L1 |
| `A012` | `GET /api/v1/instruments` | Company-name lookup preserving instrument identity | Meets | Walkthrough steps 02–03; `M07-E18` | L1 |
| `A013` | `GET /api/v1/news` | Selected-instrument current headlines with frozen status semantics | Needs improvement | `R-ASTRA-6`–`R-ASTRA-10`; `M09-E18` | L1, L2 |
| `A014` | `POST /api/v1/forecasts` | Audited stock/ETF forecast creation | Meets | Walkthrough steps 04 and 06; `M07-E18` | L1 |
| `A015` | `GET /api/v1/history` | Searchable, bounded, stably paged event ledger | Needs improvement | `R-ASTRA-6`–`R-ASTRA-10` history guards | L1, L2 |
| `A016` | `GET /api/v1/history-export.csv` | Bounded filtered CSV export | Needs improvement | `R-ASTRA-11` sort-before-cap | L1, L2 |
| `A017` | `GET /api/v1/history-export.json` | Bounded filtered JSON export | Needs improvement | `R-ASTRA-11` sort-before-cap | L1, L2 |
| `A018` | `GET /api/v1/history/{event_id}` | Immutable reconstruction record for success or failure | Meets | `M07-E18`; API route inventory | L1 |
| `A019` | `GET /api/v1/saved-forecasts/{event_id}` | Provider-free immutable saved-result reopen | Needs improvement | `R-ASTRA-6`–`R-ASTRA-10` saved-replay truthfulness | L1, L2 |
| `A020` | `POST /api/v1/history/{event_id}/reconstructions` | Separately labelled fresh cutoff analysis | Needs improvement | `R-ASTRA-17`–`R-ASTRA-20`; `EV-9`; keys `A020-AE`–`A020-PE` below | L1 |
| `A021` | `GET /api/v1/history/{event_id}/prices` | Bounded captured prices without a browser/provider query | Meets | `M07-E18`; API route inventory | L1 |
| `A022` | `GET /api/v1/forecasts/{result_id}` | Original immutable forecast result | Meets | `M07-E18`; API route inventory | L1 |
| `A023` | `POST /api/v1/forecasts/{result_id}/outcomes` | Append-only observed outcome | Meets | `M07-E18`; API route inventory | L1 |
| `A024` | `POST /api/v1/forecasts/{result_id}/corrections` | Append-only correction instead of mutation | Meets | `M07-E18`; API route inventory | L1 |
| `A025` | `POST /api/v1/operations/backups` | Named verified backup creation | Meets | `R-M05-55`; API route inventory | L1 |
| `A026` | `GET /api/v1/operations/backups/status` | Honest managed-backup capability status | Meets | Walkthrough step 01; `R-M05-55` | L1 |
| `A027` | `POST /api/v1/operations/restores` | Verified restore with explicit promotion | Meets | `R-M05-55`; API route inventory | L1 |
| `A028` | Loopback/API-only browser boundary | Browser data remains on FastAPI `/api/v1` and never opens SQLite/Yahoo | Meets | Walkthrough manifest request inventory; `M07-E18` | L1 |
| `A029` | Instrument identity surface | Company, canonical symbol, exchange, currency, timezone, and type stay joined | Meets | Walkthrough step 03 | L1, L4 |
| `A030` | Stock analysis path | Selected Yahoo stock forecasting | Meets | Walkthrough step 04 | L1, L4 |
| `A031` | ETF analysis path | Selected Yahoo ETF forecasting | Meets | Walkthrough step 06 | L1, L4 |
| `A032` | Close → next close forecast | Explicit direction/threshold probabilities and intervals | Meets | Walkthrough steps 04 and 06 | L1, L4 |
| `A033` | Completed 5m → close forecast | Latest completed bar origin with explicit forecast outputs | Meets | Walkthrough steps 04 and 06 | L1, L4 |
| `A034` | Probability and interval contract | Direction, threshold, return, and price uncertainty remain explicit | Meets | `M07-E18`; result rendering inventory | L1 |
| `A035` | Strict CSP and 98,304-byte static shell budget | Local dependency containment and low-resource presentation | Acceptable | `ASTRA-FINAL-E4`: 98,242 bytes | L1, L2 |

## Controls

| ID | Item/source | Requirement served | Verdict | Evidence reference | Limitation |
| --- | --- | --- | --- | --- | --- |
| `C001` | Dashboard “Skip to forecasts” link | Keyboard bypass to main forecast content | Meets | `static/index.html`; browser regression | L1, L6 |
| `C002` | Signal Ledger home link | Named return to dashboard main content | Meets | `static/index.html` | L1 |
| `C003` | Forecast section navigation link | Reach forecast form at desktop and mobile widths | Needs improvement | `R-ASTRA-1`–`R-ASTRA-5` mobile navigation | L1, L2 |
| `C004` | Analysis section navigation link | Reach result region at desktop and mobile widths | Needs improvement | `R-ASTRA-1`–`R-ASTRA-5` mobile navigation | L1, L2 |
| `C005` | Ledger section navigation link | Reach history region at desktop and mobile widths | Needs improvement | `R-ASTRA-1`–`R-ASTRA-5` mobile navigation | L1, L2 |
| `C006` | Dashboard color-theme select | Choose light, dark, or system preference accessibly | Needs improvement | `R-ASTRA-1`–`R-ASTRA-5` mobile theme selector | L1, L2 |
| `C007` | Instrument/company combobox | Enter bounded company name or symbol | Meets | Walkthrough steps 02–03 | L1, L4 |
| `C008` | Generated instrument result option | Choose identity by keyboard or pointer | Meets | Walkthrough steps 02–03 | L1, L4, L6 |
| `C009` | Stock radio | Select stock analysis explicitly | Meets | Walkthrough step 04 | L1, L4 |
| `C010` | ETF radio | Select ETF analysis explicitly | Meets | Walkthrough step 06 | L1, L4 |
| `C011` | Run forecast button | Submit one validated forecast request | Needs improvement | `R-ASTRA-6`–`R-ASTRA-10` validation recovery | L1, L2 |
| `C012` | Download CSV link | Export current filters and sort | Needs improvement | `R-ASTRA-11`; walkthrough step 10 | L1, L2 |
| `C013` | Download JSON link | Export current filters and sort | Needs improvement | `R-ASTRA-11`; walkthrough step 10 | L1, L2 |
| `C014` | Ledger query input | Search symbol/company/audit fields | Meets | Walkthrough step 07 | L1, L4 |
| `C015` | Ledger status select | Filter successful and failed searches | Meets | Walkthrough step 07 | L1, L4 |
| `C016` | Ledger asset-type select | Filter stocks and ETFs | Meets | Walkthrough step 07 | L1, L4 |
| `C017` | Ledger analysis-kind select | Separate original, saved, and fresh analysis context | Needs improvement | `R-ASTRA-6`–`R-ASTRA-10` context repair | L1, L2 |
| `C018` | Submitted-from date input | Native lower date bound | Meets | `static/index.html`; browser regression | L1 |
| `C019` | Submitted-to date input | Native upper date bound | Meets | `static/index.html`; browser regression | L1 |
| `C020` | Model search input | Filter by model identity | Meets | `static/index.html`; browser regression | L1 |
| `C021` | Horizon select | Filter forecast horizon | Meets | `static/index.html`; browser regression | L1 |
| `C022` | Sort select | Select stable ledger field and direction | Meets | `static/index.html`; browser regression | L1 |
| `C023` | Page-size select | Select bounded ledger page size | Meets | `static/index.html`; browser regression | L1 |
| `C024` | Filter ledger button | Apply the complete filter set | Needs improvement | `R-ASTRA-6`–`R-ASTRA-10` history race guards | L1, L2 |
| `C025` | Previous-page button | Guard first page and stale responses | Needs improvement | `R-ASTRA-6`–`R-ASTRA-10` pagination guards | L1, L2 |
| `C026` | Next-page button | Guard terminal page and stale responses | Needs improvement | `R-ASTRA-6`–`R-ASTRA-10` pagination guards | L1, L2 |
| `C027` | Reopen saved forecast button | Reopen immutable evidence without recalculation | Needs improvement | `R-ASTRA-6`–`R-ASTRA-10`; walkthrough step 08 | L1, L2 |
| `C028` | Run fresh cutoff analysis button | Create distinct current computation at recorded cutoff | Needs improvement | `R-ASTRA-6`–`R-ASTRA-10`; walkthrough step 09 | L1, L2 |
| `C029` | Current-headlines disclosure | Keep mutable news separate and opt-in | Needs improvement | `R-ASTRA-6`–`R-ASTRA-10`; walkthrough step 20 | L1, L2, L3 |
| `C030` | Retry headlines button | Retry provider, busy, timeout, or local failures honestly | Needs improvement | `R-ASTRA-6`–`R-ASTRA-10` terminal-state/retry repair | L1, L2, L3 |
| `C031` | HTTPS headline article link | Open only sanitized safe external article targets | Meets | `M09-E18`; walkthrough step 15 | L1, L3 |
| `C032` | API-docs “Skip to API contract” link | Keyboard bypass on documentation page | Meets | `static/api-docs.html`; browser regression | L1, L6 |
| `C033` | API-docs color-theme select | Share light/dark/system preference with dashboard | Needs improvement | `R-ASTRA-1`–`R-ASTRA-5` API-docs/theme repair | L1, L2 |
| `C034` | Open OpenAPI JSON link | Reach the machine-readable local contract | Meets | `static/api-docs.html`; browser regression | L1 |
| `C035` | Show up to 10 headlines button, `static/app.js:450-454` | Expand a full five-item news response through a bounded `limit=10` request | Meets | `R-ASTRA-17`–`R-ASTRA-20`; `EV-9`/`EV-8`; keys `C035-AE`–`C035-PE` below | L1, L3 |
| `C036` | Review detailed provenance link, `static/app.js:831-834` | Move from a stale-data reason to the detailed forecast provenance | Meets | `R-ASTRA-17`–`R-ASTRA-20`; `EV-9`/`EV-8`; keys `C036-AE`–`C036-PE` below | L1, L4 |
| `C037` | View failed request button, `static/app.js:1243-1245` | Open the immutable audit detail for a failed search | Meets | `R-ASTRA-17`–`R-ASTRA-20`; `EV-9`/`EV-8`; keys `C037-AE`–`C037-PE` below | L1, L6 |

## General UI states

| ID | Item/source | Requirement served | Verdict | Evidence reference | Limitation |
| --- | --- | --- | --- | --- | --- |
| `S001` | Initial “Awaiting input” result | Honest empty starting state | Meets | `static/index.html`; browser regression | L1 |
| `S002` | Local service ready | Identify schema/provider/backup readiness | Meets | Walkthrough step 01 | L1, L4 |
| `S003` | Local service unavailable | Fail visibly without implying forecast readiness | Meets | Browser regression; `M07-E18` | L1 |
| `S004` | Instrument lookup loading | Announce lookup progress | Meets | Browser regression | L1, L6 |
| `S005` | Instrument lookup results | Present bounded named identities | Meets | Walkthrough step 02 | L1, L4 |
| `S006` | Instrument lookup empty | Distinguish no matches from provider failure | Meets | Browser regression | L1 |
| `S007` | Instrument lookup failure | Preserve retryable provider/service error | Meets | Browser regression | L1 |
| `S008` | Confirmed instrument identity | Require an unambiguous stock/ETF identity | Meets | Walkthrough step 03 | L1, L4 |
| `S009` | Forecast loading | Disable duplicate submit and announce calculation | Meets | Browser regression | L1, L6 |
| `S010` | Successful forecast | Render both horizons and audit identity | Meets | Walkthrough steps 04 and 06 | L1, L4 |
| `S011` | Repeated successful search | Record a separate repeat without overwriting prior evidence | Meets | `M07-E18`; persistence regression | L1 |
| `S012` | Forecast/provider failure | Preserve failed search and bounded public error | Meets | `M07-E18`; browser regression | L1 |
| `S013` | Forecast validation and recovery | Keep field error near input and allow corrected resubmission | Needs improvement | `R-ASTRA-6`–`R-ASTRA-10` validation recovery | L1, L2, L6 |
| `S014` | Insufficient-data result | Explain why no valid forecast can be produced | Meets | Browser regression; `M07-E18` | L1 |
| `S015` | Stale-data result | Place explicit stale reason with the quality state | Needs improvement | `R-ASTRA-6`–`R-ASTRA-10` stale-reason placement | L1, L2 |
| `S016` | History loading | Announce ledger retrieval and suppress stale updates | Needs improvement | `R-ASTRA-6`–`R-ASTRA-10` history race guard | L1, L2, L6 |
| `S017` | Empty history | Explain that no ledger rows match | Meets | Browser regression | L1 |
| `S018` | Populated/filtered history | Show matching evidence and active context | Needs improvement | `R-ASTRA-6`–`R-ASTRA-10` ledger evidence | L1, L2 |
| `S019` | History failure | Keep prior context while reporting retrieval failure | Needs improvement | `R-ASTRA-6`–`R-ASTRA-10` history behavior | L1, L2 |
| `S020` | Immutable saved-result replay | Label recorded result, audit event, and no provider call truthfully | Needs improvement | `R-ASTRA-6`–`R-ASTRA-10`; walkthrough step 08 | L1, L2 |
| `S021` | Fresh historical-cutoff analysis | Label new calculation “Not the saved forecast” with source context | Needs improvement | `R-ASTRA-17`–`R-ASTRA-20`; `EV-9`; keys `S021-AE`–`S021-PE` below | L1 |

## Charts and tables

| ID | Item/source | Requirement served | Verdict | Evidence reference | Limitation |
| --- | --- | --- | --- | --- | --- |
| `H001` | Close → next close result card | Summarize direction probabilities and uncertainty | Meets | Walkthrough steps 04 and 06 | L1, L4 |
| `H002` | Completed 5m → close result card | Summarize intraday-origin probabilities and uncertainty | Meets | Walkthrough steps 04 and 06 | L1, L4 |
| `H003` | Direction-probability bar chart | Non-text visual summary with accessible label | Needs improvement | `R-ASTRA-1`–`R-ASTRA-5` chart typography | L1, L2, L6 |
| `H004` | Return-tail SVG chart | Show loss/gain threshold curves without color-only meaning | Needs improvement | `R-ASTRA-17`–`R-ASTRA-20`; `EV-9`/`EV-12`; keys `H004-AE`–`H004-PE` below | L1, L6 |
| `H005` | Chart axes, tick labels, and legend | Make scale and series visually legible at all viewports | Needs improvement | `R-ASTRA-17`–`R-ASTRA-20`; `EV-9`/`EV-12`; keys `H005-AE`–`H005-PE` below | L1, L4 |
| `H006` | Keyboard-focusable chart points and tooltip | Expose exact threshold probability by keyboard | Needs improvement | `R-ASTRA-6`–`R-ASTRA-10` chart focus; walkthrough step 05 | L1, L2, L6 |
| `H007` | Horizon/direction/threshold details table | Provide a textual equivalent to chart values | Meets | Walkthrough step 05 and continuation frame | L1, L4 |
| `H008` | Interval, uncertainty, evaluation, and provenance tables | Preserve model limits and audit context in text | Meets | Result rendering inventory; `M07-E18` | L1, L4 |

## Theme states

| ID | Item/source | Requirement served | Verdict | Evidence reference | Limitation |
| --- | --- | --- | --- | --- | --- |
| `T001` | Explicit light dashboard | User-selectable semantic light palette | Needs improvement | `R-ASTRA-1`–`R-ASTRA-5` contrast repair | L1, L2 |
| `T002` | Explicit dark dashboard | User-selectable semantic dark palette | Needs improvement | `R-ASTRA-1`–`R-ASTRA-5`; walkthrough step 12 | L1, L2, L4 |
| `T003` | System preference resolving light | Follow OS preference without storing an override | Meets | `M09-E18`; walkthrough step 13 | L1, L4 |
| `T004` | System preference resolving dark | Follow OS dark preference without storing an override | Meets | `M09-E18`; walkthrough step 11 | L1, L4 |
| `T005` | Reset to system | Remove `stock-probs.theme` override | Meets | Walkthrough step 13; `M09-E18` | L1, L4 |
| `T006` | Dashboard dark first paint | Apply theme before CSS without a flash | Acceptable | Walkthrough manifest paint entries; `M09-E18` | L1, L5 |
| `T007` | API-docs dark first paint | Apply the same parser-blocking initializer before CSS | Acceptable | Walkthrough manifest paint entries; `R-ASTRA-12` | L1, L2, L5 |
| `T008` | Loaded dark API documentation | Keep contract label and controls legible | Needs improvement | `R-ASTRA-1`–`R-ASTRA-5`; walkthrough step 14 | L1, L2, L4, L5 |
| `T009` | Forced-colors mode | Preserve native contrast and visible chart semantics | Needs improvement | `R-ASTRA-1`–`R-ASTRA-5` forced-colors repair | L1, L2, L6 |
| `T010` | Reduced-motion mode | Avoid required animation and keep states understandable | Meets | Browser regression; static walkthrough policy | L1 |
| `T011` | Print mode | Produce black-on-white legible results and charts | Needs improvement | `R-ASTRA-1`–`R-ASTRA-5` print contrast repair | L1, L2 |
| `T012` | Focus and semantic color roles | Meet text/control/chart/focus contrast without whole-page inversion | Needs improvement | `R-ASTRA-1`–`R-ASTRA-5`; contrast assertions | L1, L2, L6 |

## News states

| ID | Item/source | Requirement served | Verdict | Evidence reference | Limitation |
| --- | --- | --- | --- | --- | --- |
| `N001` | Not requested | Closed disclosure makes zero news requests | Needs improvement | `R-ASTRA-6`–`R-ASTRA-10`; walkthrough step 20 | L1, L2, L3 |
| `N002` | Loading | Live region announces a pending headline request | Needs improvement | `R-ASTRA-6`–`R-ASTRA-10`; companion frame | L1, L2, L3, L6 |
| `N003` | Fresh | Show source, as-of, publisher/time, and safe links | Meets | Walkthrough step 15; `M09-E18` | L1, L3 |
| `N004` | Empty | Successful empty response is not a 404 or provider error | Meets | Walkthrough step 16; `M09-E18` | L1, L3 |
| `N005` | Partial metadata | Keep headline usable without publisher/publication time | Meets | Walkthrough step 17; `M09-E18` | L1, L3 |
| `N006` | Stale cache after refresh failure | Retain headlines and place a clear stale reason/as-of warning | Needs improvement | `R-ASTRA-6`–`R-ASTRA-10`; walkthrough step 18 | L1, L2, L3 |
| `N007` | Provider unavailable without cache | Distinguish 502 failure from an empty response and offer retry | Needs improvement | `R-ASTRA-6`–`R-ASTRA-10`; walkthrough step 19 | L1, L2, L3 |
| `N008` | Local service unreachable | Distinguish local network failure from Yahoo failure | Needs improvement | `R-ASTRA-6`–`R-ASTRA-10`; companion frame | L1, L2, L3 |
| `N009` | Capacity busy | Present retryable 503 capacity state | Needs improvement | `R-ASTRA-6`–`R-ASTRA-10`; companion frame | L1, L2, L3 |
| `N010` | Instrument changed/request superseded | Abort old request and render no stale-symbol headlines | Needs improvement | `R-ASTRA-17`–`R-ASTRA-20`; `EV-9`/`EV-12`; keys `N010-AE`–`N010-PE` below | L1, L3, L4, L6 |

## Documentation visuals and walkthrough frames

Each visual has descriptive alt text and a caption in the [walkthrough](../walkthrough/index.md).
The **Acceptable** verdict records the supplied repaired artifact, not independent ASTRA
acceptance.

| ID | Item/source | Requirement served | Verdict | Evidence reference | Limitation |
| --- | --- | --- | --- | --- | --- |
| `V001` | Desktop 01 backup status PNG | Service/provider/backup readiness visual | Acceptable | `docs/walkthrough/images/desktop-01-backup-status.png` | L1, L2, L7 |
| `V002` | Desktop 02 company lookup PNG | Named lookup results visual | Acceptable | `docs/walkthrough/images/desktop-02-company-lookup.png` | L1, L2, L7 |
| `V003` | Desktop 03 symbol identity PNG | Confirmed identity visual | Acceptable | `docs/walkthrough/images/desktop-03-symbol-identity.png` | L1, L2, L7 |
| `V004` | Desktop 04 stock horizons PNG | Stock result visual | Acceptable | `docs/walkthrough/images/desktop-04-stock-horizons.png` | L1, L2, L7 |
| `V005` | Desktop 05 chart and table PNG | Focused threshold point visual | Acceptable | `R-ASTRA-17`–`R-ASTRA-20`; `EV-9`/`EV-12`; keys `V005-AE`–`V005-PE` below | L1, L6, L7 |
| `V006` | Desktop 06 ETF horizons PNG | ETF result visual | Acceptable | `docs/walkthrough/images/desktop-06-etf-horizons.png` | L1, L2, L7 |
| `V007` | Desktop 07 history filter PNG | Filtered ledger visual | Acceptable | `docs/walkthrough/images/desktop-07-history-filter.png` | L1, L2, L7 |
| `V008` | Desktop 08 saved reopen PNG | Immutable result visual | Acceptable | `docs/walkthrough/images/desktop-08-saved-reopen.png` | L1, L2, L7 |
| `V009` | Desktop 09 fresh reconstruction PNG | Distinct fresh analysis visual | Acceptable | `R-ASTRA-17`–`R-ASTRA-20`; `EV-9`/`EV-12`; keys `V009-AE`–`V009-PE` below | L1, L6, L7 |
| `V010` | Desktop 10 history downloads PNG | Export-control visual | Acceptable | `docs/walkthrough/images/desktop-10-history-downloads.png` | L1, L2, L7 |
| `V011` | Desktop 11 system theme PNG | System-dark visual | Acceptable | `docs/walkthrough/images/desktop-11-theme-system.png` | L1, L2, L7 |
| `V012` | Desktop 12 dark theme PNG | Explicit-dark visual | Acceptable | `docs/walkthrough/images/desktop-12-theme-dark.png` | L1, L2, L7 |
| `V013` | Desktop 13 theme reset PNG | Reset-to-system-light visual | Acceptable | `docs/walkthrough/images/desktop-13-theme-reset.png` | L1, L2, L7 |
| `V014` | Desktop 14 loaded API page PNG | Settled dark API-docs visual | Acceptable | `docs/walkthrough/images/desktop-14-theme-first-paint.png` | L1, L2, L5, L7 |
| `V015` | Desktop 15 fresh news PNG | Fresh five-headline visual | Acceptable | `docs/walkthrough/images/desktop-15-news-fresh.png` | L1, L2, L3, L7 |
| `V016` | Desktop 16 empty news PNG | Honest empty visual | Acceptable | `docs/walkthrough/images/desktop-16-news-empty.png` | L1, L2, L3, L7 |
| `V017` | Desktop 17 partial news PNG | Missing metadata visual | Acceptable | `docs/walkthrough/images/desktop-17-news-partial.png` | L1, L2, L3, L7 |
| `V018` | Desktop 18 stale news PNG | Stale fallback warning visual | Acceptable | `docs/walkthrough/images/desktop-18-news-stale.png` | L1, L2, L3, L7 |
| `V019` | Desktop 19 provider failure PNG | Provider unavailable visual | Acceptable | `docs/walkthrough/images/desktop-19-news-provider-failure.png` | L1, L2, L3, L7 |
| `V020` | Desktop 20 saved/current news PNG | Provider-free saved result visual | Acceptable | `docs/walkthrough/images/desktop-20-saved-current-news.png` | L1, L2, L3, L7 |
| `V021` | Desktop chart-table continuation PNG | Exact textual chart equivalent visual | Acceptable | `docs/walkthrough/images/desktop-05-chart-and-table-table-continuation.png` | L1, L2, L7 |
| `V022` | Desktop closed-headlines disclosure PNG | Not-requested news visual | Acceptable | `docs/walkthrough/images/desktop-20-saved-current-news-closed-disclosure.png` | L1, L2, L3, L7 |
| `V023` | Desktop capacity-busy PNG | Retryable 503 visual | Acceptable | `docs/walkthrough/images/desktop-20-news-capacity-busy.png` | L1, L2, L3, L7 |
| `V024` | Desktop local-unreachable PNG | Local network failure visual | Acceptable | `docs/walkthrough/images/desktop-20-news-local-unreachable.png` | L1, L2, L3, L7 |
| `V025` | Desktop news-loading PNG | Pending live-region visual | Acceptable | `docs/walkthrough/images/desktop-20-news-loading.png` | L1, L2, L3, L7 |
| `V026` | Desktop superseded-news PNG | Aborted stale request visual | Acceptable | `R-ASTRA-17`–`R-ASTRA-20`; `EV-9`/`EV-12`; keys `V026-AE`–`V026-PE` below | L1, L3, L6, L7 |
| `V027` | Mobile 01 backup status PNG | Mobile readiness visual | Acceptable | `docs/walkthrough/images/mobile-01-backup-status.png` | L1, L2, L4, L7 |
| `V028` | Mobile 02 company lookup PNG | Mobile lookup-results visual | Acceptable | `docs/walkthrough/images/mobile-02-company-lookup.png` | L1, L2, L4, L7 |
| `V029` | Mobile 03 symbol identity PNG | Mobile identity visual | Acceptable | `docs/walkthrough/images/mobile-03-symbol-identity.png` | L1, L2, L4, L7 |
| `V030` | Mobile 04 stock horizons PNG | Mobile stock result visual | Acceptable | `docs/walkthrough/images/mobile-04-stock-horizons.png` | L1, L2, L4, L7 |
| `V031` | Mobile 05 chart and table PNG | Mobile focused chart-point visual | Acceptable | `R-ASTRA-17`–`R-ASTRA-20`; `EV-9`/`EV-12`; keys `V031-AE`–`V031-PE` below | L1, L4, L6, L7 |
| `V032` | Mobile 06 ETF horizons PNG | Mobile ETF result visual | Acceptable | `docs/walkthrough/images/mobile-06-etf-horizons.png` | L1, L2, L4, L7 |
| `V033` | Mobile 07 history filter PNG | Mobile filtered ledger visual | Acceptable | `docs/walkthrough/images/mobile-07-history-filter.png` | L1, L2, L4, L7 |
| `V034` | Mobile 08 saved reopen PNG | Mobile immutable result visual | Acceptable | `docs/walkthrough/images/mobile-08-saved-reopen.png` | L1, L2, L4, L7 |
| `V035` | Mobile 09 fresh reconstruction PNG | Mobile fresh-analysis visual | Acceptable | `R-ASTRA-17`–`R-ASTRA-20`; `EV-9`/`EV-12`; keys `V035-AE`–`V035-PE` below | L1, L4, L6, L7 |
| `V036` | Mobile 10 history downloads PNG | Mobile export-control visual | Acceptable | `docs/walkthrough/images/mobile-10-history-downloads.png` | L1, L2, L4, L7 |
| `V037` | Mobile 11 system theme PNG | Mobile system-dark visual | Acceptable | `docs/walkthrough/images/mobile-11-theme-system.png` | L1, L2, L4, L7 |
| `V038` | Mobile 12 dark theme PNG | Mobile explicit-dark visual | Acceptable | `docs/walkthrough/images/mobile-12-theme-dark.png` | L1, L2, L4, L7 |
| `V039` | Mobile 13 theme reset PNG | Mobile reset-to-system visual | Acceptable | `docs/walkthrough/images/mobile-13-theme-reset.png` | L1, L2, L4, L7 |
| `V040` | Mobile 14 loaded API page PNG | Mobile settled dark API-docs visual | Acceptable | `docs/walkthrough/images/mobile-14-theme-first-paint.png` | L1, L2, L4, L5, L7 |
| `V041` | Mobile 15 fresh news PNG | Mobile fresh-headline visual | Acceptable | `docs/walkthrough/images/mobile-15-news-fresh.png` | L1, L2, L3, L4, L7 |
| `V042` | Mobile 16 empty news PNG | Mobile empty-news visual | Acceptable | `docs/walkthrough/images/mobile-16-news-empty.png` | L1, L2, L3, L4, L7 |
| `V043` | Mobile 17 partial news PNG | Mobile partial-metadata visual | Acceptable | `docs/walkthrough/images/mobile-17-news-partial.png` | L1, L2, L3, L4, L7 |
| `V044` | Mobile 18 stale news PNG | Mobile stale-fallback visual | Acceptable | `docs/walkthrough/images/mobile-18-news-stale.png` | L1, L2, L3, L4, L7 |
| `V045` | Mobile 19 provider failure PNG | Mobile provider-unavailable visual | Acceptable | `docs/walkthrough/images/mobile-19-news-provider-failure.png` | L1, L2, L3, L4, L7 |
| `V046` | Mobile 20 saved/current news PNG | Mobile provider-free saved-result visual | Acceptable | `docs/walkthrough/images/mobile-20-saved-current-news.png` | L1, L2, L3, L4, L7 |
| `V047` | Mobile chart-table continuation PNG | Mobile textual chart-equivalent visual | Acceptable | `docs/walkthrough/images/mobile-05-chart-and-table-table-continuation.png` | L1, L2, L4, L7 |
| `V048` | Mobile closed-headlines disclosure PNG | Mobile not-requested visual | Acceptable | `docs/walkthrough/images/mobile-20-saved-current-news-closed-disclosure.png` | L1, L2, L3, L4, L7 |
| `V049` | Mobile capacity-busy PNG | Mobile retryable 503 visual | Acceptable | `docs/walkthrough/images/mobile-20-news-capacity-busy.png` | L1, L2, L3, L4, L7 |
| `V050` | Mobile local-unreachable PNG | Mobile local network failure visual | Acceptable | `docs/walkthrough/images/mobile-20-news-local-unreachable.png` | L1, L2, L3, L4, L7 |
| `V051` | Mobile news-loading PNG | Mobile pending live-region visual | Acceptable | `docs/walkthrough/images/mobile-20-news-loading.png` | L1, L2, L3, L4, L7 |
| `V052` | Mobile superseded-news PNG | Mobile aborted stale-request visual | Acceptable | `R-ASTRA-17`–`R-ASTRA-20`; `EV-9`/`EV-12`; keys `V052-AE`–`V052-PE` below | L1, L3, L4, L6, L7 |

## Supporting media

| ID | Item/source | Requirement served | Verdict | Evidence reference | Limitation |
| --- | --- | --- | --- | --- | --- |
| `M001` | Walkthrough manifest JSON | Bind fixture, generation, requests, viewports, states, and media | Acceptable | `R-ASTRA-17`–`R-ASTRA-20`; `EV-9`/`EV-12`; keys `M001-AE`–`M001-PE` below | L1, L4, L6, L7 |
| `M002` | Walkthrough instructional transcript/index | Pair every frame with action, expectation, alt text, and caption | Acceptable | `docs/walkthrough/index.md`; `R-ASTRA-13` | L1, L2, L7 |
| `M003` | Desktop filtered-history CSV | Downloaded SPY/successful/ETF CSV example | Acceptable | `docs/walkthrough/downloads/desktop/history.csv` | L1, L2, L7 |
| `M004` | Desktop filtered-history JSON | Downloaded SPY/successful/ETF JSON example | Acceptable | `docs/walkthrough/downloads/desktop/history.json` | L1, L2, L7 |
| `M005` | Mobile filtered-history CSV | Mobile-journey CSV example | Acceptable | `docs/walkthrough/downloads/mobile/history.csv` | L1, L2, L4, L7 |
| `M006` | Mobile filtered-history JSON | Mobile-journey JSON example | Acceptable | `docs/walkthrough/downloads/mobile/history.json` | L1, L2, L4, L7 |

## Walkthrough segments

Each segment is separately inventoried from its frames so the instruction and expected outcome
remain independently reviewable.

| ID | Item/source | Requirement served | Verdict | Evidence reference | Limitation |
| --- | --- | --- | --- | --- | --- |
| `W001` | Step 01: confirm service and backup status | Begin from an honest ready local service | Acceptable | `docs/walkthrough/index.md`, step 01 | L1, L2, L4, L7 |
| `W002` | Step 02: use company-name lookup | Exercise named search with actual controls | Acceptable | `docs/walkthrough/index.md`, step 02 | L1, L2, L4, L7 |
| `W003` | Step 03: confirm selected identity | Preserve canonical instrument identity | Acceptable | `docs/walkthrough/index.md`, step 03 | L1, L2, L4, L7 |
| `W004` | Step 04: run stock forecast | Exercise both ACDC forecast origins | Acceptable | `docs/walkthrough/index.md`, step 04 | L1, L2, L4, L7 |
| `W005` | Step 05: read chart and table | Prove keyboard point and textual equivalent | Acceptable | `docs/walkthrough/index.md`, step 05 | L1, L2, L4, L6, L7 |
| `W006` | Step 06: run ETF forecast | Exercise both SPY forecast origins | Acceptable | `docs/walkthrough/index.md`, step 06 | L1, L2, L4, L7 |
| `W007` | Step 07: filter ledger | Exercise symbol/status/type history filters | Acceptable | `docs/walkthrough/index.md`, step 07 | L1, L2, L4, L7 |
| `W008` | Step 08: reopen saved forecast | Demonstrate immutable provider-free replay | Acceptable | `docs/walkthrough/index.md`, step 08 | L1, L2, L4, L7 |
| `W009` | Step 09: run fresh reconstruction | Distinguish a new cutoff analysis from saved evidence | Acceptable | `R-ASTRA-17`–`R-ASTRA-20`; `EV-9`/`EV-12`; keys `W009-AE`–`W009-PE` below | L1, L4, L6, L7 |
| `W010` | Step 10: download CSV and JSON | Exercise both filtered exports | Acceptable | `docs/walkthrough/index.md`, step 10 | L1, L2, L4, L7 |
| `W011` | Step 11: follow system theme | Exercise system-dark preference | Acceptable | `docs/walkthrough/index.md`, step 11 | L1, L2, L4, L7 |
| `W012` | Step 12: choose dark mode | Exercise explicit dark preference | Acceptable | `docs/walkthrough/index.md`, step 12 | L1, L2, L4, L7 |
| `W013` | Step 13: reset theme | Exercise override removal/system-light | Acceptable | `docs/walkthrough/index.md`, step 13 | L1, L2, L4, L7 |
| `W014` | Step 14: open loaded dark API page | Inspect shared theme on API docs | Acceptable | `docs/walkthrough/index.md`, step 14 | L1, L2, L4, L5, L7 |
| `W015` | Step 15: load fresh headlines | Exercise source/as-of and safe-link presentation | Acceptable | `docs/walkthrough/index.md`, step 15 | L1, L2, L3, L4, L7 |
| `W016` | Step 16: show empty news | Distinguish successful empty from failure | Acceptable | `docs/walkthrough/index.md`, step 16 | L1, L2, L3, L4, L7 |
| `W017` | Step 17: label partial metadata | Preserve useful headline with missing optional fields | Acceptable | `docs/walkthrough/index.md`, step 17 | L1, L2, L3, L4, L7 |
| `W018` | Step 18: explain stale headlines | Show cached content and refresh-failure reason | Acceptable | `docs/walkthrough/index.md`, step 18 | L1, L2, L3, L4, L7 |
| `W019` | Step 19: report provider failure | Distinguish no-cache upstream failure | Acceptable | `docs/walkthrough/index.md`, step 19 | L1, L2, L3, L4, L7 |
| `W020` | Step 20: separate saved evidence/current news | Prove optional disclosure and zero request delta | Acceptable | `R-ASTRA-17`–`R-ASTRA-20`; `EV-9`/`EV-12`; keys `W020-AE`–`W020-PE` below | L1, L3, L4, L6, L7 |

## Persistence effects

| ID | Item/source | Requirement served | Verdict | Evidence reference | Limitation |
| --- | --- | --- | --- | --- | --- |
| `P001` | Successful search event append | Keep every successful request auditable | Meets | `M07-E18`; repository matrix tests | L1 |
| `P002` | Failed search event append | Retain failures without fake forecast records | Meets | `M07-E18`; repository matrix tests | L1 |
| `P003` | Repeated search event append | Preserve each repeat as a distinct event | Meets | `M07-E18`; repository matrix tests | L1 |
| `P004` | Immutable inputs and results | Prevent saved forecast mutation during reopen/outcomes | Needs improvement | `R-ASTRA-6`–`R-ASTRA-10` saved-replay truthfulness | L1, L2 |
| `P005` | Append-only outcomes | Add observations without changing original result | Meets | `M07-E18`; outcome tests | L1 |
| `P006` | Append-only corrections | Correct through a new row, never an update | Meets | `M07-E18`; correction tests | L1 |
| `P007` | Bounded non-expiring searchable history across restart | Retain audit history while bounding queries/pages | Needs improvement | `R-ASTRA-6`–`R-ASTRA-10` history/pagination guards | L1, L2 |
| `P008` | Manual named backup | Create and verify a bounded managed artifact | Meets | `R-M05-55` | L1 |
| `P009` | Automatic/due backup | Enforce configured interval and startup watchdog behavior | Meets | `R-M05-55` | L1 |
| `P010` | Pre-migration backup | Preserve recoverable schema state before migration | Meets | `M07-E18`; `R-M05-55` | L1 |
| `P011` | Backup retention and disk limits | Keep at most 32 artifacts/256 MiB without history expiry | Meets | `R-M05-55` | L1 |
| `P012` | Verification and trust-key lifecycle | Reject tampering/wrong keys and support rotate/retire rollback | Meets | `R-M05-55` | L1 |
| `P013` | Cross-architecture restore and promotion | Verify both directions and require explicit promotion | Acceptable | `R-M05-55` emulated ARM64 receipt | L1, L6 |

## `R-ASTRA-19` publication record

- **Status:** Completed for the documentation repair scope; this does not complete
  `ASTRA-FINAL`.
- **Change:** restored one tracked 211-row matrix, added it to the evidence taxonomy, updated
  the expected topic count, and added a missing-index-link mutation test.
- **Acceptance limit at publication:** all `Needs improvement` rows then required independent
  repair QA and re-evaluation. The later disposition is retained in the evaluation report.

## `R-ASTRA-21` traceability repair

- **Status:** Completed for the owned documentation and developer-test scope; the concluding
  `ASTRA-FINAL` receipt `EV-12` records the reviewed traceability scope as resolved.
- **Change:** retained all 211 existing IDs, added `C035`–`C037`, corrected the total to 214,
  bound every row to five dimension keys, and published the tracked evaluation report.
- **Finding closure:** the control-inventory and per-row evidence-record gaps found by the final
  re-evaluation are resolved in these artifacts and bound to `EV-9`, `EV-11`, and `EV-12`. Actual
  screen-reader evidence, native/physical ARM64 performance, and physical-mobile evidence remain
  explicitly unavailable; no `EXP-M08` or export checkpoint is inferred.

[Back to evidence](index.md)
