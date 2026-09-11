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

test("history filters and reconstruction remain usable", async ({ page }, testInfo) => {
  await page.goto("/");
  const symbol = testInfo.project.name.startsWith("desktop") ? "SPY-D" : "SPY-M";
  await page.getByLabel("Yahoo Finance symbol").fill(symbol);
  await page.getByLabel("ETF").check();
  await page.getByRole("button", { name: "Run forecast" }).click();
  await expect(page.getByText(`${symbol} / ETF`)).toBeVisible();

  await page.getByLabel("Find symbol").fill(symbol);
  await page.getByRole("button", { name: "Filter ledger" }).click();
  await page.getByRole("button", { name: "Reconstruct" }).first().click();
  await expect(page.getByText(/Historical reconstruction \d+ loaded/)).toBeAttached();
  await expect(page.getByText(`${symbol} / ETF`)).toBeVisible();
});

test("validation, loading, and stale states remain explicit", async ({ page }) => {
  await page.goto("/");
  const symbol = page.getByLabel("Yahoo Finance symbol");
  await symbol.fill("bad symbol");
  await page.getByRole("button", { name: "Run forecast" }).click();
  await expect(page.getByText("Enter 1-15 letters")).toBeVisible();
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
