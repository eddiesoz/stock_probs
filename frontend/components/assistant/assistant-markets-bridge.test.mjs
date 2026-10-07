import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import { readAssistantMarketsAction } from "./assistant-contract.ts";

const selection = { symbol: "SPY", asset_type: "etf", provider: "Yahoo Finance", exchange: "ARCA" };
const context = { route: "/tools/markets", selected: selection, exchanges: ["ARCA", "NASDAQ"] };
const filters = {
  query: "ACDC", exchange: "NASDAQ", asset_type: "etf", sort: "symbol:asc",
  min_price: "", max_price: "", min_change: "", max_change: "", min_volume: "",
  quote_field: "", quote_min: "", quote_max: "",
};

test("Markets bridge accepts confirmed controls with explicit local acknowledgements", () => {
  const filtered = readAssistantMarketsAction({
    type: "market.filters.apply", payload: filters, destination: { kind: "current-page", route: "/tools/markets" },
  }, context);
  assert.equal(filtered.ok, true);
  assert.equal(filtered.message, "Confirmed Markets filters applied for this page.");
  assert.deepEqual(filtered.action, { type: "market.filters.apply", payload: filters });

  const chart = readAssistantMarketsAction({
    type: "market.chart_range.set",
    payload: { ...selection, range: "3mo" },
  }, context);
  assert.equal(chart.ok, true);
  assert.equal(chart.message, "Confirmed 3mo chart range applied to SPY.");

  const columns = readAssistantMarketsAction({ type: "market.columns.set", payload: { show_all_columns: false } }, context);
  assert.equal(columns.ok, true);
  assert.equal(columns.message, "Summary quote columns are shown for this page.");

  for (const [kind, message] of [
    ["quotes", "Quote refresh requested for the current watchlist."],
    ["watchlist", "Saved watchlist reload requested."],
    ["chart", "Chart refresh requested for the current instrument."],
  ]) {
    const result = readAssistantMarketsAction({ type: "market.refresh", payload: { kind } }, context);
    assert.equal(result.ok, true);
    assert.equal(result.message, message);
  }
});

test("Markets bridge rejects wrong routes, stale instruments, unavailable exchanges, and forged events", () => {
  assert.equal(readAssistantMarketsAction({ type: "market.filters.apply", payload: filters }, { ...context, route: "/" }).ok, false);
  assert.equal(readAssistantMarketsAction({
    type: "market.filters.apply", payload: filters, destination: { kind: "current-page", route: "/" },
  }, context).ok, false);
  assert.equal(readAssistantMarketsAction({ type: "market.filters.apply", payload: { ...filters, exchange: "NASDAQ" } }, { ...context, exchanges: ["ARCA"] }).ok, false);
  assert.equal(readAssistantMarketsAction({
    type: "market.chart_range.set", payload: { ...selection, range: "1y" },
  }, { ...context, selected: { ...selection, symbol: "QQQ" } }).ok, false);
  assert.equal(readAssistantMarketsAction({ type: "market.filters.apply", payload: { ...filters, override: true } }, context).ok, false);
  assert.equal(readAssistantMarketsAction({ type: "market.refresh", payload: { kind: "quotes", force: true } }, context).ok, false);
  assert.equal(readAssistantMarketsAction({ type: "market.refresh", payload: { kind: "chart" } }, { ...context, selected: null }).ok, false);
  assert.equal(readAssistantMarketsAction(null, context).ok, false);
});

test("Markets filters keep native labeled controls and route-local client state", async () => {
  const workspace = await readFile(new URL("../../app/tools/markets/workspace.tsx", import.meta.url), "utf8");
  const panel = await readFile(new URL("./assistant-panel.tsx", import.meta.url), "utf8");
  const css = await readFile(new URL("../../app/tools/markets/workspace.module.css", import.meta.url), "utf8");
  assert.ok(workspace.includes('<form className={styles.filters} role="search"'));
  assert.ok(workspace.includes('from "../../../components/assistant/assistant-contract"'));
  assert.doesNotMatch(workspace, /assistant-contract\.ts/);
  for (const control of [
    "Symbol or name<input type=\"search\"",
    "Market / exchange<select",
    "Asset type<select",
    "Sort<select",
    "Minimum price<input type=\"number\"",
    "Minimum % change<input type=\"number\"",
    "Minimum volume<input type=\"number\"",
    "Additional quote metric<select",
    "Metric minimum<input type=\"number\"",
    "Metric maximum<input type=\"number\"",
    "Chart range<select",
  ]) assert.ok(workspace.includes(control), control);
  assert.ok(workspace.includes("aria-pressed={showAllColumns}"));
  assert.ok(workspace.includes('role="status" aria-live="polite"'));
  assert.ok(workspace.includes('signal-ledger:assistant-watchlist-updated'));
  assert.doesNotMatch(workspace, /localStorage|sessionStorage/);
  assert.ok(css.includes("@media (max-width:440px){.editor,.marketList,.detail{padding:.75rem}.editor form,.filters,.advancedGrid,.detailQuote{grid-template-columns:1fr}"));
  assert.ok(panel.includes('outcome: "handoff_rejected_locally"'));
  assert.ok(panel.includes("The confirmed change could not be applied in this browser:"));
  assert.ok(panel.includes("setLiveStatus(`The confirmed change could not be applied in this browser: ${detail}`)"));
  assert.ok(panel.includes("Downloading the approved filtered CSV history export."));
  assert.ok(panel.includes("Downloading the approved filtered JSON history export."));
  assert.ok(panel.includes("else if (result.browser_action !== undefined)"));
  assert.ok(panel.includes("signal-ledger:assistant-watchlist-updated"));
});
