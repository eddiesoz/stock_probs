const AxeBuilder = require("@axe-core/playwright").default;
const { test, expect } = require("./fixtures");

// The selected instrument travels between local pages only as these URL parameters, so every
// route assertion must confirm the full identity round-trips rather than just the symbol.
const IDENTITY = "symbol=ACDC&asset_type=stock&exchange=NMS&provider=yahoo&display_name=ProFrac%20Holding%20Corp.";
const FIXTURE_CLOCK_START = "2025-01-10T17:03:00.000Z";

// Match method, path, and parameters so unrelated same-origin traffic cannot satisfy the wait.
function waitForApiResponse(page, method, path, parameters = {}) {
  return page.waitForResponse((response) => {
    const url = new URL(response.url());
    return response.request().method() === method
      && url.pathname === path
      && Object.entries(parameters).every(([name, value]) => url.searchParams.get(name) === value);
  });
}

function observeRequests(page) {
  const requests = [];
  page.on("request", (request) => requests.push(request.url()));
  return requests;
}

// Playwright's clock is installed before navigation so React timers and the 30-second quote
// interval share one controlled timeline. The pinned Playwright version supports this API; fail
// clearly rather than replacing a timer assertion with an unbounded real-time sleep.
async function installControlledClock(page) {
  expect(page.clock, "this acceptance requires Playwright clock emulation").toBeTruthy();
  expect(typeof page.clock.install, "this acceptance requires page.clock.install").toBe("function");
  expect(typeof page.clock.runFor, "this acceptance requires page.clock.runFor").toBe("function");
  await page.clock.install({ time: FIXTURE_CLOCK_START });
}

async function advanceControlledClock(page, milliseconds) {
  expect(typeof page.clock.runFor, "this acceptance requires page.clock.runFor").toBe("function");
  await page.clock.runFor(milliseconds);
}

// `incomplete` must be empty too: an inconclusive axe rule would hide an accessibility
// failure behind a state that merely looks settled.
async function expectAxeClean(page) {
  const results = await new AxeBuilder({ page }).analyze();
  expect(results.violations).toEqual([]);
  expect(results.incomplete, "axe must fully analyze each settled workspace state").toEqual([]);
}

async function expectResponsive(page, label) {
  const overflow = await page.evaluate(() => ({
    viewport: document.documentElement.clientWidth,
    content: document.documentElement.scrollWidth,
  }));
  expect(overflow.content, `${label} must not overflow horizontally`).toBeLessThanOrEqual(overflow.viewport + 1);
}

// 44px is the contract minimum for touch targets, asserted here for nav and controls.
async function expectMinimumTarget(locator, label) {
  const box = await locator.boundingBox();
  expect(box, `${label} must be rendered`).not.toBeNull();
  expect(box.width, `${label} must be at least 44px wide`).toBeGreaterThanOrEqual(44);
  expect(box.height, `${label} must be at least 44px high`).toBeGreaterThanOrEqual(44);
}

// No-order boundary: research and tools routes must never expose buy/sell/order controls.
async function expectNoOrderEntry(page) {
  for (const role of ["button", "link"]) {
    await expect(page.getByRole(role, {
      name: /^(?:buy|sell|place order|preview order|submit order)$/i,
    }), "research routes must not expose order-entry controls").toHaveCount(0);
  }
}

async function expectIdentity(page) {
  const url = new URL(page.url());
  expect(Object.fromEntries([...url.searchParams].filter(([name]) => (
    ["symbol", "asset_type", "exchange", "provider", "display_name"].includes(name)
  ))), `${url.pathname} must retain instrument identity`).toEqual({
    symbol: "ACDC",
    asset_type: "stock",
    exchange: "NMS",
    provider: "yahoo",
    display_name: "ProFrac Holding Corp.",
  });
}

async function clearSyntheticListsForIsolatedQuoteTest(page) {
  const api = page.context().request;
  const removed = { portfolio: [], watchlist: [] };
  for (const kind of Object.keys(removed)) {
    const initial = await api.get(`/api/v1/lists?kind=${kind}`, { headers: { "cache-control": "no-store" } });
    if (!initial.ok()) throw new Error(`${kind} isolation lookup failed with HTTP ${initial.status()}.`);
    const payload = await initial.json();
    for (const item of payload.items ?? []) {
      const query = new URLSearchParams({ kind, symbol: item.symbol });
      const response = await api.delete(`/api/v1/lists?${query}`);
      if (response.status() !== 204) throw new Error(`${kind} isolation delete failed with HTTP ${response.status()}.`);
      removed[kind].push(item.symbol);
    }
    const verified = await api.get(`/api/v1/lists?kind=${kind}`, { headers: { "cache-control": "no-store" } });
    if (!verified.ok()) throw new Error(`${kind} isolation verification failed with HTTP ${verified.status()}.`);
    const remaining = await verified.json();
    expect(remaining.items ?? [], `the quote-strip journey must start with an empty ${kind}`).toEqual([]);
  }
  return removed;
}

// Documents, assets, and data must stay same-origin below /api/v1; the browser never calls
// Yahoo Finance or any third party directly.
function expectLocalOnly(page, requests, applicationRequests) {
  const origin = new URL(page.url()).origin;
  expect(requests.length, "journey must load the local application").toBeGreaterThan(0);
  expect(requests.filter((url) => new URL(url).origin !== origin),
    "documents, assets, and data requests must remain local").toEqual([]);
  expect(applicationRequests.length, "journey must use the local application API").toBeGreaterThan(0);
  expect(applicationRequests.filter((url) => {
    const request = new URL(url);
    return request.origin !== origin || !request.pathname.startsWith("/api/v1");
  }), "fetch/XHR traffic must stay same-origin below /api/v1").toEqual([]);
}

function primaryNavigation(page) {
  return page.getByRole("navigation", { name: "Primary navigation" });
}

function toolsNavigation(page) {
  return page.getByRole("navigation", { name: "Tools" });
}

async function openWithKeyboard(locator) {
  await locator.focus();
  await locator.press("Enter");
}

test("saved rolling forecasts retain every selected interval label", async ({ page }) => {
  test.setTimeout(60_000);
  const cases = [
    ["5min", "five_min_forward", "Completed 5m → next 5m", "5-minute target"],
    ["daily", "daily_1", "Close → next close", "1-session target"],
    ["weekly", "weekly_5", "Close → 5-session close", "5-session target"],
    ["monthly", "monthly_21", "Close → 21-session close", "21-session target"],
    ["quarterly", "quarterly_63", "Close → 63-session close", "63-session target"],
  ];
  const savedCases = [];
  for (const [interval, horizon, heading, target] of cases) {
    const response = await page.request.post("/api/v1/forecasts", {
      data: { symbol: "SPY", asset_type: "etf", interval },
    });
    expect(response.status()).toBe(201);
    const saved = await response.json();
    expect(saved.results[0].horizon).toBe(horizon);
    savedCases.push({ eventId: saved.event.id, heading, target });
  }
  await page.goto("/");
  for (const { eventId, heading, target } of savedCases) {
    const row = page.locator("#history-content tbody tr").filter({
      hasText: new RegExp(`New request #${eventId}(?!\\d)`),
    });
    await expect(row).toBeVisible();
    await row.getByRole("button", { name: "Reopen saved forecast" }).click();
    await expect(page.locator("#result-content")).toContainText(`audit event #${eventId}`);
    await expect(page.getByRole("heading", { name: heading })).toBeVisible();
    await expect(page.getByText(target, { exact: true })).toBeVisible();
    if (target !== "5-minute target") {
      await expect(page.getByText("Intraday horizon", { exact: true })).toHaveCount(0);
      await expect(page.getByRole("heading", { name: "Completed 5m → close" })).toHaveCount(0);
    }
  }
});

test("accessible workspace navigation preserves identity and forecast submission is explicit", async ({
  page,
  applicationRequests,
}, testInfo) => {
  const requests = observeRequests(page);
  const portfolioResponse = waitForApiResponse(page, "GET", "/api/v1/lists", { kind: "portfolio" });
  await page.goto(`/overview?${IDENTITY}`);
  expect((await portfolioResponse).status()).toBe(200);
  await expect(page.getByRole("heading", { name: "Portfolio overview" })).toBeVisible();
  await expect(page.getByRole("region", { name: "Manual portfolio holdings" })).not.toHaveAttribute("aria-busy", "true");

  const primary = primaryNavigation(page);
  for (const name of ["Overview", "Research", "Tools"]) {
    const link = primary.getByRole("link", { name, exact: true });
    await expect(link).toBeVisible();
    await expectMinimumTarget(link, `${testInfo.project.name} ${name} navigation`);
  }
  await expect(primary.getByRole("link", { name: "Overview", exact: true })).toHaveAttribute("aria-current", "page");
  await expect(page.getByText(/No brokerage connection|No trades can be submitted/i)).toBeVisible();
  await expectNoOrderEntry(page);
  await expectResponsive(page, `${testInfo.project.name} overview`);

  await openWithKeyboard(primary.getByRole("link", { name: "Research", exact: true }));
  await expect(page.getByRole("heading", { name: "Recorded research" })).toBeVisible();
  await expectIdentity(page);
  await expect(primaryNavigation(page).getByRole("link", { name: "Research", exact: true })).toHaveAttribute("aria-current", "page");
  await expectNoOrderEntry(page);
  await expectResponsive(page, `${testInfo.project.name} research`);

  await primaryNavigation(page).getByRole("link", { name: "Tools", exact: true }).click();
  await expect(page).toHaveTitle("Tools | Signal Ledger");
  await expect(page.getByRole("heading", { name: "Research tools" })).toBeVisible();
  await expect(page.getByRole("region", { name: "Tools navigation" })).toBeVisible();
  await expectIdentity(page);
  for (const name of ["Forecast", "Live Trading", "Markets"]) {
    await expect(toolsNavigation(page).getByRole("link", { name, exact: true })).toBeVisible();
  }

  const forecastRequests = () => applicationRequests.filter((url) => new URL(url).pathname === "/api/v1/forecasts");
  const initialForecastCount = forecastRequests().length;
  await openWithKeyboard(toolsNavigation(page).getByRole("link", { name: "Forecast", exact: true }));
  await expect(page.getByRole("heading", { name: "Probability forecast" })).toBeVisible();
  await expectIdentity(page);
  await expect(page.getByText("Research only", { exact: true })).toBeVisible();
  await expect(toolsNavigation(page).getByRole("link", { name: "Forecast", exact: true })).toHaveAttribute("aria-current", "page");
  expect(forecastRequests()).toHaveLength(initialForecastCount);

  const interval = page.getByRole("combobox", { name: "Forecast horizon" });
  await expect(interval.locator("option")).toHaveText(["5 minutes", "1 session", "5 sessions", "21 sessions", "63 sessions"]);
  await interval.selectOption("quarterly");
  await expect(page.getByRole("definition").filter({ hasText: "Close after 63 scheduled sessions" })).toBeVisible();
  expect(forecastRequests()).toHaveLength(initialForecastCount);
  await expectMinimumTarget(interval, `${testInfo.project.name} forecast interval`);
  const submit = page.getByRole("button", { name: "Run forecast" });
  await expectMinimumTarget(submit, `${testInfo.project.name} forecast submit`);
  const forecastResponse = waitForApiResponse(page, "POST", "/api/v1/forecasts");
  await submit.click();
  expect((await forecastResponse).status()).toBe(201);
  await expect(page.getByText("Current result", { exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Threshold probabilities" })).toBeVisible();
  const forecastDisclosure = page.getByText(/Historical\/probability data\s+—\s+not a live quote/i);
  await expect(forecastDisclosure).toBeVisible();
  await expect(forecastDisclosure).toContainText(/Provenance:/i);
  await expect(forecastDisclosure).toContainText(/Delay:/i);
  expect(forecastRequests()).toHaveLength(initialForecastCount + 1);
  await interval.selectOption("monthly");
  await expect(page.getByRole("heading", { name: "No forecast submitted" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Selected horizon unavailable" })).toHaveCount(0);
  expect(forecastRequests(), "changing an interval must not submit or reuse the old result").toHaveLength(initialForecastCount + 1);
  await expectNoOrderEntry(page);
  await expectResponsive(page, `${testInfo.project.name} forecast`);
  await expectAxeClean(page);
  expectLocalOnly(page, requests, applicationRequests);
});

test("live and markets tools disclose unavailable data without trading or external traffic", async ({
  page,
  applicationRequests,
  browserDiagnostics,
}, testInfo) => {
  const clearedSymbols = await clearSyntheticListsForIsolatedQuoteTest(page);
  await installControlledClock(page);
  const requests = observeRequests(page);
  const quoteAborts = [];
  page.on("requestfailed", (request) => {
    if (new URL(request.url()).pathname === "/api/v1/quotes") {
      quoteAborts.push({ method: request.method(), error: request.failure()?.errorText });
    }
  });
  const portfolioResponse = waitForApiResponse(page, "GET", "/api/v1/lists", { kind: "portfolio" });
  const quoteResponse = waitForApiResponse(page, "GET", "/api/v1/quotes", { symbols: "ACDC" });
  await page.goto(`/tools/live-trading?${IDENTITY}`);
  expect(Object.values(clearedSymbols).flat().every((symbol) => /^[A-Z0-9.-]{1,15}$/.test(symbol))).toBe(true);
  expect((await portfolioResponse).status()).toBe(200);
  expect((await quoteResponse).status()).toBe(200);
  await expect(page.getByRole("heading", { name: "Live Trading", exact: true })).toBeVisible();
  await expectIdentity(page);
  await expect(page.getByText("No order entry", { exact: true })).toBeVisible();
  await expect(page.getByText(/Manual quantities for research only/i)).toBeVisible();
  await expect(page.getByText(/Server portfolio (?:loaded|is empty)/i)).toBeVisible();
  await expect(page.getByRole("group", { name: "Workspace view controls" })).toBeVisible();

  const quoteStrip = page.getByRole("region", { name: "Portfolio quote strip" });
  await expect(quoteStrip).not.toHaveAttribute("aria-busy", "true");
  await expect(quoteStrip).toContainText(/\d+ (?:quote snapshots|quotes)/);
  const pause = quoteStrip.getByRole("button", { name: /^(?:pause|resume) visual strip$/i });
  // Navigation may finish the live quote request before superseding it. If it is still in
  // flight, the one allowed abort is checked against the exact request below.
  await expectMinimumTarget(pause, `${testInfo.project.name} quote strip pause`);
  const initiallyPaused = await pause.getAttribute("aria-pressed") === "true";
  if (!initiallyPaused) await pause.click();
  await expect(pause).toHaveAttribute("aria-pressed", "true");
  await expect(pause).toHaveAccessibleName("Resume visual strip");
  // Exercise both accessible names, then leave the visual strip paused for the refresh check.
  await pause.click();
  await expect(pause).toHaveAttribute("aria-pressed", "false");
  await expect(pause).toHaveAccessibleName("Pause visual strip");
  await pause.click();
  await expect(pause).toHaveAttribute("aria-pressed", "true");
  await expect(pause).toHaveAccessibleName("Resume visual strip");

  // The second ticker set is visible presentation content, but it must not create a second
  // accessible symbol control. This checks the contract without depending on CSS class names.
  const visibleTickerSymbols = quoteStrip.getByText("ACDC", { exact: true });
  await expect(visibleTickerSymbols).toHaveCount(2);
  for (let index = 0; index < 2; index += 1) await expect(visibleTickerSymbols.nth(index)).toBeVisible();
  await expect(quoteStrip.getByRole("button", { name: /ACDC/ })).toHaveCount(1);

  const quoteRequests = () => applicationRequests.filter((url) => {
    const request = new URL(url);
    return request.pathname === "/api/v1/quotes" && request.searchParams.get("symbols") === "ACDC";
  });
  const initialQuoteRequestCount = quoteRequests().length;
  expect(initialQuoteRequestCount).toBeGreaterThanOrEqual(1);
  const automaticRefresh = waitForApiResponse(page, "GET", "/api/v1/quotes", { symbols: "ACDC" });
  await advanceControlledClock(page, 30_000);
  expect((await automaticRefresh).status()).toBe(200);
  expect(quoteRequests().length, "30-second refresh must issue another quote request while paused").toBeGreaterThan(initialQuoteRequestCount);
  await expect(quoteStrip.getByText(/^\d+ quote snapshots$/)).toBeVisible();
  await expect(quoteStrip.getByRole("button", { name: /ACDC/ })).toHaveCount(1);

  const quote = page.getByRole("region", { name: /ACDC/ });
  await expect(quote).toContainText("Provider: deterministic fixture");
  await expect(quote).toContainText(/As of:/i);
  await expect(quote).toContainText(/not live market data/i);
  const quoteTerms = await quote.locator("dt").allTextContents();
  expect(quoteTerms).toContain("Last");
  expect(quoteTerms).toContain("Previous close");
  expect(quoteTerms).not.toContain("Close");
  await expect(quote.locator("dt").filter({ hasText: /^Close$/ })).toHaveCount(0);

  const depth = page.getByRole("region", { name: "Market depth" });
  await expect(depth).toContainText("State: unavailable");
  await expect(depth).toContainText("Provider: Free data");
  await expect(depth).toContainText(/free data has no Nasdaq TotalView or exchange-depth entitlement/i);
  await expect(depth).toContainText(/no rows are fabricated/i);
  await expect(depth.locator("tbody tr")).toHaveCount(0);
  expect(applicationRequests.filter((url) => new URL(url).pathname === "/api/v1/market-depth")).toEqual([]);

  const holdings = page.getByLabel("Symbols and quantities");
  await page.getByText("Bulk edit holdings").click();
  await expect(page.getByText("SYMBOL: quantity", { exact: true })).toBeVisible();
  await expect(holdings).toHaveAttribute("placeholder", /ACDC: 10/);
  const updateHoldings = page.getByRole("button", { name: "Update holdings", exact: true });
  const saveResponse = waitForApiResponse(page, "POST", "/api/v1/lists");
  const savedPortfolio = waitForApiResponse(page, "GET", "/api/v1/lists", { kind: "portfolio" });
  const portfolioQuoteRefresh = waitForApiResponse(page, "GET", "/api/v1/quotes", { symbols: "ACDC" });
  await holdings.fill("ACDC: 12.5");
  await updateHoldings.click();
  const saved = await saveResponse;
  expect(saved.status()).toBe(201);
  expect(saved.request().postDataJSON()).toEqual({
    kind: "portfolio",
    item: { symbol: "ACDC", asset_type: "stock", quantity: 12.5 },
  });
  expect((await savedPortfolio).status()).toBe(200);
  const refreshedQuote = await portfolioQuoteRefresh;
  expect(refreshedQuote.status()).toBe(200);
  await refreshedQuote.finished();
  await expect(page.getByRole("status").filter({ hasText: "Server portfolio updated." })).toBeVisible();
  await expect(holdings).toHaveValue("ACDC: 12.5");
  await expect(page.getByText(/Manual quantities for research only/i)).toBeVisible();
  await expect(quoteStrip.getByText(/^\d+ quote snapshots$/)).toBeVisible();

  // Reload through the real page/API boundary to prove the quantity is persisted as portfolio
  // context rather than being converted into an order or only echoed from React state.
  const reloadedPortfolio = waitForApiResponse(page, "GET", "/api/v1/lists", { kind: "portfolio" });
  const reloadedQuotes = waitForApiResponse(page, "GET", "/api/v1/quotes", { symbols: "ACDC" });
  await page.reload();
  expect((await reloadedPortfolio).status()).toBe(200);
  const reloadedQuote = await reloadedQuotes;
  expect(reloadedQuote.status()).toBe(200);
  await reloadedQuote.finished();
  await expect(page.getByRole("heading", { name: "Live Trading", exact: true })).toBeVisible();
  await expect(page.getByLabel("Symbols and quantities")).toHaveValue("ACDC: 12.5");
  await expect(page.getByRole("status").filter({ hasText: "Server portfolio loaded." })).toBeVisible();
  await expect(page.getByRole("region", { name: "Portfolio quote strip" }).getByText(/^\d+ quote snapshots$/)).toBeVisible();
  await expectNoOrderEntry(page);
  await expectResponsive(page, `${testInfo.project.name} live trading`);

  const watchlistResponse = waitForApiResponse(page, "GET", "/api/v1/lists", { kind: "watchlist" });
  const marketQuoteResponse = waitForApiResponse(page, "GET", "/api/v1/quotes", { symbols: "ACDC" });
  const chartResponse = waitForApiResponse(page, "GET", "/api/v1/bars", {
    symbol: "ACDC",
    asset_type: "stock",
    range: "1mo",
    interval: "1d",
  });
  await openWithKeyboard(toolsNavigation(page).getByRole("link", { name: "Markets", exact: true }));
  expect((await watchlistResponse).status()).toBe(200);
  expect((await marketQuoteResponse).status()).toBe(200);
  expect((await chartResponse).status()).toBe(200);
  await expect(page.getByRole("heading", { name: "Markets", exact: true })).toBeVisible();
  await expectIdentity(page);
  await page.getByRole("region", { name: "Add or update an instrument" }).getByRole("textbox", { name: "Symbol" }).fill("ACDC");
  await page.getByRole("button", { name: "Add or update", exact: true }).click();
  await expect(page.getByRole("region", { name: "Watchlist quotes" }).getByRole("table")).toBeVisible();
  await expect(toolsNavigation(page).getByRole("link", { name: "Markets", exact: true })).toHaveAttribute("aria-current", "page");
  await expect(page.getByRole("heading", { name: "Loading watchlist quote snapshots" })).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "Loading chart bars" })).toHaveCount(0);
  const detail = page.getByRole("region", { name: /ACDC/ }).last();
  await expect(detail.getByText("Quote snapshot / provider / as of / delay", { exact: true })).toBeVisible();
  await expect(detail).toContainText("deterministic fixture");
  const marketTerms = await detail.locator("dt").allTextContents();
  expect(marketTerms).toContain("Last");
  expect(marketTerms).toContain("Previous close");
  expect(marketTerms).not.toContain("Close");
  await expect(detail.locator("dt").filter({ hasText: /^Close$/ })).toHaveCount(0);

  const chartRange = page.getByRole("combobox", { name: "Chart range" });
  await expect(chartRange).toHaveValue("1mo");
  await expect(page.getByRole("img", { name: /ACDC closing-price chart for 1mo at 1d/i })).toBeVisible();
  await expect(page.getByText("ACDC · 1mo · 1d bars", { exact: true })).toBeVisible();
  await expect(detail).toContainText(/Bars snapshot:.*deterministic fixture/i);
  await expect(detail).toContainText(/not live market data/i);

  const fiveDayBars = waitForApiResponse(page, "GET", "/api/v1/bars", {
    symbol: "ACDC",
    asset_type: "stock",
    range: "5d",
    interval: "1d",
  });
  await chartRange.selectOption("5d");
  const fiveDayResponse = await fiveDayBars;
  expect(fiveDayResponse.status()).toBe(200);
  await fiveDayResponse.finished();
  await expect(chartRange).toHaveValue("5d");
  await expect(page.getByRole("img", { name: /ACDC closing-price chart for 5d at 1d/i })).toBeVisible();
  await expect(page.getByText("ACDC · 5d · 1d bars", { exact: true })).toBeVisible();
  await expect(detail).toContainText(/Bars snapshot:.*deterministic fixture/i);
  await expect(detail).toContainText(/not live market data/i);
  await page.getByText("More quote filters").click();
  await page.getByLabel("Minimum price").fill("999999");
  await expect(page.getByText("No instruments match these filters")).toBeVisible();
  await expect(page.getByText("More quote filters · 1 active")).toBeVisible();
  await page.getByRole("button", { name: "Reset filters" }).first().click();
  await expect(page.getByText("No instruments match these filters")).toHaveCount(0);
  await expectNoOrderEntry(page);
  await expectResponsive(page, `${testInfo.project.name} markets`);
  await expectAxeClean(page);
  expectLocalOnly(page, requests, applicationRequests);
  expect(quoteAborts.length, "at most one live quote request may be superseded").toBeLessThanOrEqual(1);
  if (quoteAborts.length === 1) {
    expect(quoteAborts[0]).toEqual({ method: "GET", error: "net::ERR_ABORTED" });
    browserDiagnostics.expectRequestAborts({ method: "GET", path: "/api/v1/quotes" });
  }
});

test("holdings editor stays reachable after saving a populated quote strip", async ({
  page,
  restartableApplication,
}, testInfo) => {
  const viewportWidth = testInfo.project.name === "mobile-chromium" ? 360 : 860;
  await page.setViewportSize({ width: viewportWidth, height: 900 });
  const initial = [
    ["ACDC", "stock"],
    ["SPY", "etf"],
  ];
  for (const [symbol, asset_type] of initial) {
    const response = await page.request.post(`${restartableApplication.url}/api/v1/lists`, {
      data: { kind: "portfolio", item: { symbol, asset_type, quantity: 10 } },
    });
    expect(response.status(), `${symbol} fixture holding must be accepted`).toBe(201);
  }

  await page.goto(`${restartableApplication.url}/tools/live-trading?${IDENTITY}`);
  const holdings = page.getByLabel("Symbols and quantities");
  await page.getByText("Bulk edit holdings").click();
  await expect(holdings).toHaveValue(/SPY: 10/);
  await expect(page.getByRole("region", { name: "Portfolio quote strip" })).not.toHaveAttribute("aria-busy", "true");
  const updatedDraft = `${await holdings.inputValue()}\nSHOP.TO: 2`;
  await holdings.fill(updatedDraft);
  await page.getByRole("button", { name: "Update holdings", exact: true }).click();
  await expect(page.getByRole("status").filter({ hasText: "Server portfolio updated." })).toBeVisible();
  await expect(holdings).toHaveValue(/SHOP\.TO: 2/);
  await expectResponsive(page, "populated live trading workspace");
  await expect(page.getByRole("region", { name: "Portfolio quote strip" })).toContainText("3 quote snapshots");
  await page.emulateMedia({ media: "print" });
  await expectResponsive(page, "printed populated live trading workspace");
  await page.emulateMedia({ media: "screen" });
  const bounds = await holdings.boundingBox();
  expect(bounds, "holdings editor must remain rendered after save").not.toBeNull();
  expect(bounds.x + bounds.width, "holdings editor must stay within the viewport").toBeLessThanOrEqual(viewportWidth + 1);
  await holdings.fill(`${await holdings.inputValue()}\nPNG.V: 1`);
  await page.getByRole("button", { name: "Update holdings", exact: true }).click();
  await expect(page.getByRole("status").filter({ hasText: "Server portfolio updated." })).toBeVisible();
  await expect(holdings).toHaveValue(/PNG\.V: 1/);
  await expectResponsive(page, "twice-updated live trading workspace");
  const secondBounds = await holdings.boundingBox();
  expect(secondBounds, "holdings editor must remain rendered after a second save").not.toBeNull();
  expect(secondBounds.x + secondBounds.width).toBeLessThanOrEqual(viewportWidth + 1);
});
