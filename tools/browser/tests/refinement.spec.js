const AxeBuilder = require("@axe-core/playwright").default;
const { test, expect } = require("./fixtures");

// Each test uses the fixture server's isolated data directory. This journey covers real local
// API responses and static pages without contacting the provider or the current user volume.
test("recorded research links and comparison preserve each saved target", async ({ page }) => {
  const created = [];
  for (const interval of ["monthly", "quarterly"]) {
    const response = await page.request.post("/api/v1/forecasts", { data: { symbol: "SPY", asset_type: "etf", interval } });
    expect(response.status()).toBe(201);
    created.push((await response.json()).event.id);
  }
  await page.goto("/research");
  await expect(page.getByRole("heading", { name: "Recent research" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Compare saved forecasts" })).toBeVisible();
  await expect(page.getByText(`event #${created[1]}`).first()).toBeVisible();
  await expect(page.getByText(/No outcome recorded|Targets pending/).first()).toBeVisible();
  await expect(page.getByText(/Different horizon or target/)).toBeVisible();
  await expect(page.getByRole("heading", { name: "63 trading sessions" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "21 trading sessions" })).toBeVisible();
  const axe = await new AxeBuilder({ page }).analyze();
  expect(axe.violations).toEqual([]);
  expect(axe.incomplete).toEqual([]);
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(await page.evaluate(() => document.documentElement.clientWidth + 1));

  await page.goto(`/?event_id=${created[1]}#result-section`);
  await expect(page.locator("#result-content")).toContainText(`audit event #${created[1]}`);
  await expect(page.getByRole("heading", { name: "63-session horizon", exact: true })).toBeVisible();
  await expect(page.locator("#result-summary")).toContainText("One recorded completed origin and target");
  await expect(page.locator(".interval-table")).not.toContainText("raw ");
  await expect(page.locator(".exact-intervals")).toContainText("Exact recorded interval values");
});

test("holding summary opens the latest saved forecast and market chart values", async ({ page }) => {
  const forecast = await page.request.post("/api/v1/forecasts", { data: { symbol: "SPY", asset_type: "etf", interval: "weekly" } });
  expect(forecast.status()).toBe(201);
  const eventId = (await forecast.json()).event.id;
  const holding = await page.request.post("/api/v1/lists", { data: { kind: "portfolio", item: { symbol: "SPY", asset_type: "etf", quantity: 10 } } });
  expect(holding.status()).toBe(201);
  const watch = await page.request.post("/api/v1/lists", { data: { kind: "watchlist", item: { symbol: "SPY", asset_type: "etf" } } });
  expect(watch.status()).toBe(201);

  await page.goto("/overview");
  await page.getByRole("listitem").filter({ hasText: /SPY.*SPDR/ }).getByRole("button", { name: "Research summary" }).click();
  await expect(page.getByRole("heading", { name: /SPY/ })).toBeVisible();
  await expect(page.getByText(`Event #${eventId}`)).toBeVisible();
  await expect(page.getByRole("link", { name: "Open saved forecast" })).toHaveAttribute("href", `/?event_id=${eventId}#result-section`);
  await expect(page.getByText(/Provider quote snapshot/)).toBeVisible();

  await page.goto("/tools/markets?symbol=SPY&asset_type=etf&exchange=PCX&provider=yahoo&display_name=SPDR%20S%26P%20500%20ETF%20Trust");
  await expect(page.getByRole("link", { name: "Forecast this instrument" })).toBeVisible();
  await expect(page.getByRole("button", { name: "All quote fields" })).toBeVisible();
  await expect(page.locator("table").first().locator("th", { hasText: "Volume" })).toBeHidden();
  await page.getByRole("button", { name: "All quote fields" }).click();
  await expect(page.locator("table").first().locator("th", { hasText: "Volume" })).toBeVisible();
  await expect(page.getByText(/Last bar:/)).toBeVisible();
  await page.getByText(/Read chart values/).click();
  await expect(page.getByRole("table", { name: /SPY daily closing values/ })).toBeVisible();
  expect(await page.getByRole("table", { name: /SPY daily closing values/ }).locator("tbody tr").count()).toBeGreaterThan(0);
});

test("row editor stays available for two manual holding additions", async ({ page }) => {
  await page.goto("/tools/live-trading?symbol=ACDC&asset_type=stock&exchange=NMS&provider=yahoo&display_name=ProFrac%20Holding%20Corp.");
  await expect(page.getByRole("heading", { name: "Portfolio holdings" })).toBeVisible();
  const add = page.getByRole("button", { name: "Add holding", exact: true });
  await page.getByLabel("Add holding symbol").fill("ACDC");
  await page.getByLabel("Manual quantity", { exact: true }).fill("10");
  await add.click();
  await expect(page.getByRole("status").filter({ hasText: /ACDC saved/ })).toBeVisible();
  await expect(add).toBeVisible();
  await page.getByLabel("Add holding symbol").fill("SPY");
  await page.getByLabel("Manual quantity", { exact: true }).fill("5");
  await add.click();
  await expect(page.getByRole("status").filter({ hasText: /SPY saved/ })).toBeVisible();
  await expect(page.getByRole("list", { name: "Saved manual holdings" }).locator("li")).toHaveCount(2);
  await expect(page.getByRole("region", { name: "Market depth" })).toContainText("unavailable");
  await expect(page.getByText("Inspect empty bid and ask tables")).toBeVisible();
  await expect(page.getByRole("link", { name: "Forecast this instrument" })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(await page.evaluate(() => document.documentElement.clientWidth + 1));
});
