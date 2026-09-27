import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import { instrumentFromSearch, instrumentHref } from "../../components/workspace-context-url.ts";
import { manualHoldingErrors, portfolioFromPayload, portfolioMutation } from "./portfolio-data.ts";

test("instrument identity round-trips through workspace URLs", () => {
  const instrument = instrumentFromSearch("?symbol=spy&asset_type=etf&exchange=arca&provider=fixture&display_name=SPDR%20S%26P%20500");
  assert.deepEqual(instrument, {
    provider: "fixture",
    canonicalSymbol: "SPY",
    assetType: "etf",
    exchange: "ARCA",
    displayName: "SPDR S&P 500",
  });
  assert.equal(
    instrumentHref("/tools/markets?panel=quote#details", instrument),
    "/tools/markets?panel=quote&symbol=SPY&asset_type=etf&exchange=ARCA&provider=fixture&display_name=SPDR+S%26P+500#details",
  );
  assert.equal(instrumentFromSearch("?symbol=SPY&asset_type=etf"), null);
  assert.throws(() => instrumentHref("https://example.com", instrument), /must be local/);
});

test("manual portfolio input rejects invalid holdings and parses bounded local records", () => {
  assert.deepEqual(manualHoldingErrors("?", "0"), {
    symbol: "Enter 1–15 letters, numbers, periods, hyphens, or ^.",
    quantity: "Shares must be greater than zero.",
  });
  assert.deepEqual(manualHoldingErrors("brk.b", "1.5"), { symbol: "", quantity: "" });
  assert.deepEqual(portfolioFromPayload({ kind: "portfolio", items: [{
    symbol: "SPY",
    display_name: "SPDR S&P 500",
    provider: "fixture",
    asset_type: "etf",
    exchange: "ARCA",
    quantity: 2,
  }, {
    symbol: "ACDC",
    display_name: "ProFrac Holding Corp.",
    provider: "fixture",
    asset_type: "stock",
    exchange: "NASDAQ",
    quantity: 3,
  }] }), [{
    symbol: "SPY",
    displayName: "SPDR S&P 500",
    provider: "fixture",
    assetType: "etf",
    exchange: "ARCA",
    quantity: 2,
  }, {
    symbol: "ACDC",
    displayName: "ProFrac Holding Corp.",
    provider: "fixture",
    assetType: "stock",
    exchange: "NASDAQ",
    quantity: 3,
  }]);
  assert.equal(portfolioFromPayload({ kind: "portfolio", items: [{ symbol: "SPY" }] }), null);
  assert.equal(portfolioFromPayload({ lists: [] }), null);
});

test("portfolio mutation sends only the fixed-list request contract", () => {
  assert.deepEqual(portfolioMutation(" spy ", "etf", "2.5"), {
    kind: "portfolio",
    item: { symbol: "SPY", asset_type: "etf", quantity: 2.5 },
  });
});

test("overview uses only the final local lists contract", async () => {
  const source = await readFile(new URL("portfolio-workspace.tsx", import.meta.url), "utf8");
  assert.match(source, /fetch\("\/api\/v1\/lists\?kind=portfolio"/);
  assert.match(source, /fetch\("\/api\/v1\/lists"/);
  assert.doesNotMatch(source, /\/portfolios|localStorage/);
});

test("expansion chrome leaves the root dashboard and static navigation outside the client boundary", async () => {
  const [rootLayout, rootPage, navigation, link, overviewLayout, researchLayout, toolsLayout, toolPage, toolNav] = await Promise.all([
    readFile(new URL("../layout.tsx", import.meta.url), "utf8"),
    readFile(new URL("../page.tsx", import.meta.url), "utf8"),
    readFile(new URL("../../components/workspace-nav.tsx", import.meta.url), "utf8"),
    readFile(new URL("../../components/workspace-link.tsx", import.meta.url), "utf8"),
    readFile(new URL("layout.tsx", import.meta.url), "utf8"),
    readFile(new URL("../research/layout.tsx", import.meta.url), "utf8"),
    readFile(new URL("../tools/layout.tsx", import.meta.url), "utf8"),
    readFile(new URL("../tools/tool-page.tsx", import.meta.url), "utf8"),
    readFile(new URL("../../components/workspace-nav.tsx", import.meta.url), "utf8"),
  ]);

  assert.doesNotMatch(rootLayout, /WorkspaceProvider|WorkspaceNav/);
  assert.equal((rootPage.match(/aria-label="Primary navigation"/g) ?? []).length, 1);
  for (const path of ["overview", "research", "tools"]) assert.match(rootPage, new RegExp(`path="/${path}"`));
  assert.doesNotMatch(rootPage, /aria-label="Dashboard sections"/);
  assert.doesNotMatch(navigation, /["']use client["']/);
  assert.match(link, /^"use client";/);
  assert.match(link, /instrumentHref\(path, instrumentFromSearch\(window\.location\.search\)\)/);
  assert.match(link, /instrumentChangeEvent/);
  assert.match(link, /window\.location\.pathname === path/);
  assert.match(overviewLayout, /<WorkspaceNav current="overview"/);
  assert.match(researchLayout, /<WorkspaceNav current="research"/);
  assert.match(toolsLayout, /<WorkspaceNav current="tools"/);
  assert.match(toolPage, /<ToolsNav current=\{tool\}/);
  assert.match(toolNav, /current\?: "forecast" \| "live-trading" \| "markets"/);
  assert.match(toolNav, /current=\{current \? path === `\/tools\/\$\{current\}` : undefined\}/);
});

test("owned static routes expose workspace navigation and honest initial states", async () => {
  const output = new URL("../../out/", import.meta.url);
  const overview = await readFile(new URL("overview.html", output), "utf8");
  const research = await readFile(new URL("research.html", output), "utf8");
  const tools = await readFile(new URL("tools.html", output), "utf8");

  for (const html of [overview, research, tools]) {
    assert.match(html, /aria-label="Primary navigation"/);
    for (const label of ["Overview", "Research", "Tools"]) assert.match(html, new RegExp(`>${label}<`));
  }
  assert.match(overview, /Loading portfolio records/);
  assert.match(overview, /Manual portfolio holdings/);
  assert.match(overview, /No brokerage connection, order routing, or assumed real-time valuation/);
  assert.match(research, /Open search ledger/);
  assert.match(research, /Not a trading platform/);
  for (const label of ["Forecast", "Live Trading", "Markets"]) assert.match(tools, new RegExp(`>${label}<`));
  assert.doesNotMatch(tools, /buy|sell|place order/i);
});
