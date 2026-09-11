// M04/M06 regressions assert API-only data, accessibility, all states, and responsive layout.
const { test, expect } = require("./fixtures");
const AxeBuilder = require("@axe-core/playwright").default;

test("forecast journey exposes complete text equivalents and audit states", async ({ page, applicationRequests }, testInfo) => {
  const securityConsoleErrors = [];
  page.on("console", (message) => {
    // A deliberate 502 logs as a browser error; only CSP/style violations fail this gate.
    if (message.type() === "error" && /content security policy|refused to/i.test(message.text())) {
      securityConsoleErrors.push(message.text());
    }
  });

  await page.goto("/");
  await expect(page.getByText("No forecast loaded")).toBeVisible();
  if (testInfo.project.name.startsWith("desktop")) {
    await expect(page.getByText("No audit events match these filters.")).toBeVisible();
  }
  const symbol = testInfo.project.name.startsWith("desktop") ? "ACDC-D" : "ACDC-M";
  await page.getByLabel("Yahoo Finance symbol").fill(symbol);
  await page.getByRole("button", { name: "Run forecast" }).click();

  await expect(page.getByRole("heading", { name: "Close → next close" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Completed 5m → close" })).toBeVisible();
  await expect(page.getByText("50% magnitude interval")).toHaveCount(2);
  await expect(page.getByText(/scheduled US equity sessions \/ us-equities-rules-v1/)).toBeVisible();
  await expect(page.locator("#history-content tbody tr").first()).toContainText("successful");
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);

  await page.getByRole("button", { name: "Run forecast" }).click();
  await expect(page.getByText(/Repeated \/ current/)).toBeVisible();
  await expect(page.locator("#history-content tbody tr").first()).toContainText("repeated");

  await page.getByLabel("Yahoo Finance symbol").fill("FAIL");
  await page.getByRole("button", { name: "Run forecast" }).click();
  await expect(page.getByRole("alert")).toContainText("Deterministic provider failure");
  await expect(page.locator("#history-content tbody tr").first()).toContainText("failed");
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);

  expect(applicationRequests.length).toBeGreaterThan(0);
  expect(applicationRequests.every((url) => new URL(url).pathname.startsWith("/api/v1"))).toBe(true);
  expect(securityConsoleErrors).toEqual([]);
});

test("dashboard is keyboard-operable, responsive, and axe-clean", async ({ page }) => {
  await page.goto("/");
  await page.keyboard.press("Tab");
  await expect(page.getByRole("link", { name: "Skip to forecasts" })).toBeFocused();
  await page.getByRole("link", { name: "Skip to forecasts" }).press("Enter");
  await expect(page.locator("#main")).toBeFocused();

  const viewportWidth = await page.evaluate(() => document.documentElement.clientWidth);
  const bodyWidth = await page.evaluate(() => document.body.scrollWidth);
  expect(bodyWidth).toBeLessThanOrEqual(viewportWidth);

  const results = await new AxeBuilder({ page }).analyze();
  expect(results.violations).toEqual([]);
});

test("company lookup is bounded, race-safe, keyboard-selectable, and confirms identity", async ({ page, applicationRequests }) => {
  await page.goto("/");
  const symbol = page.getByLabel("Company name or Yahoo Finance symbol");
  await symbol.fill("ProFrac");
  await expect(page.getByRole("option", { name: /ProFrac Holding Corp/ })).toBeVisible();
  await symbol.press("ArrowDown");
  await symbol.press("Enter");

  const confirmation = page.locator("#identity-confirmation");
  await expect(confirmation).toContainText("Confirmed identity: ACDC / NMS / USD / America/New_York / STOCK");
  await page.getByRole("button", { name: "Run forecast" }).click();
  const metadata = page.locator(".forecast-meta");
  await expect(metadata).toContainText("Display nameProFrac Holding Corp");
  await expect(metadata).toContainText("Company nameProFrac Holding Corp");
  await expect(metadata).toContainText("Canonical symbolACDC");
  await expect(metadata).toContainText("Instrument typeSTOCK / EQUITY");
  await expect(metadata).toContainText("ExchangeNMS");
  await expect(metadata).toContainText("CurrencyUSD");
  await expect(metadata).toContainText("Exchange timezoneAmerica/New_York");

  const lookupURLs = applicationRequests.filter((url) => new URL(url).pathname === "/api/v1/instruments");
  expect(lookupURLs.length).toBeGreaterThan(0);
  expect(lookupURLs.every((url) => new URL(url).searchParams.get("limit") === "5")).toBe(true);
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
});

test("a stale lookup response cannot replace newer company choices", async ({ page }) => {
  await page.route("**/api/v1/instruments?*", async (route) => {
    const query = new URL(route.request().url()).searchParams.get("query");
    if (query === "ProFrac") await new Promise((resolve) => setTimeout(resolve, 500));
    await route.continue();
  });
  await page.goto("/");
  const symbol = page.getByLabel("Company name or Yahoo Finance symbol");
  await symbol.fill("ProFrac");
  await expect(page.getByText("Looking up “ProFrac”…")).toBeVisible();
  await symbol.fill("SPDR");
  await expect(page.getByRole("option", { name: /SPDR S&P 500 ETF Trust/ })).toBeVisible();
  await expect(page.locator("#instrument-options")).not.toContainText("ProFrac Holding Corp");
});

test("history filters and reconstruction remain usable", async ({ page }, testInfo) => {
  await page.goto("/");
  const symbol = testInfo.project.name.startsWith("desktop") ? "SPY-D" : "SPY-M";
  await page.getByLabel("Yahoo Finance symbol").fill(symbol);
  await page.getByLabel("ETF").check();
  await page.getByRole("button", { name: "Run forecast" }).click();
  await expect(page.locator(".forecast-meta").getByText(symbol, { exact: true })).toBeVisible();
  await expect(page.getByText("ETF / ETF", { exact: true })).toBeVisible();

  await page.getByLabel("Find symbol").fill(symbol);
  await page.getByRole("button", { name: "Filter ledger" }).click();
  await page.getByRole("button", { name: "Reconstruct" }).first().click();
  await expect(page.getByText(/Historical reconstruction \d+ loaded/)).toBeAttached();
  await expect(page.locator(".forecast-meta").getByText(symbol, { exact: true })).toBeVisible();
  await expect(page.getByText("ETF / ETF", { exact: true })).toBeVisible();
});

test("validation, loading, and stale states remain explicit", async ({ page }) => {
  await page.goto("/");
  const symbol = page.getByLabel("Yahoo Finance symbol");
  await symbol.fill("bad symbol");
  await page.getByRole("button", { name: "Run forecast" }).click();
  await expect(page.getByText(/Enter a 1-15 character symbol|Choose a matching instrument/)).toBeVisible();
  await expect(symbol).toBeFocused();
  await expect(symbol).toHaveAttribute("aria-invalid", "true");

  await page.route("**/api/v1/forecasts", async (route) => {
    await new Promise((resolve) => setTimeout(resolve, 250));
    await route.continue();
  });
  await symbol.fill("STALE");
  await page.getByRole("button", { name: "Run forecast" }).click();
  await expect(page.getByText("Retrieving completed bars for STALE…")).toBeVisible();
  await expect(page.locator("#quality-badge")).toContainText("stale");
  await expect(page.getByText(/intraday origin.*applicable close elapsed/)).toBeVisible();
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
});
