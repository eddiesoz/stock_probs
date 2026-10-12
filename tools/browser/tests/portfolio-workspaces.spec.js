// Every journey owns a fresh native fixture app and an isolated browser context.
const AxeBuilder = require("@axe-core/playwright").default;
const { test, expect } = require("./fixtures");

test.use({ locale: "en-CA" });

async function capture(page, testInfo, name) {
  const result = await new AxeBuilder({ page }).analyze();
  await testInfo.attach(`${name}-axe`, { body: JSON.stringify(result), contentType: "application/json" });
  expect(result.violations).toEqual([]);
  expect(result.incomplete).toEqual([]);
  const viewport = page.viewportSize();
  expect(await page.evaluate(width => document.documentElement.scrollWidth <= width + 1, viewport.width)).toBe(true);
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
  await page.screenshot({ path: testInfo.outputPath(`${name}.png`), fullPage: true, scale: "css" });
}

async function createAccount(page, origin, title) {
  await page.goto(`${origin}/overview/transactions`);
  await page.getByRole("textbox", { name: "Account label", exact: true }).first().fill(title);
  const response = page.waitForResponse(row => new URL(row.url()).pathname === "/api/v1/portfolio/accounts" && row.request().method() === "POST");
  await page.getByRole("button", { name: "Create account", exact: true }).click();
  const created = await response;
  expect(created.status()).toBe(201);
  return (await created.json()).id;
}

async function record(page, accountId, kind, fields) {
  const form = page.locator("form").filter({ has: page.locator("#transaction-kind") });
  await form.getByRole("combobox", { name: "Account", exact: true }).selectOption(accountId);
  await form.getByRole("combobox", { name: "Type", exact: true }).selectOption(kind);
  await form.getByLabel("Original date", { exact: true }).fill("2025-01-09");
  for (const [label, value] of Object.entries(fields)) {
    const control = ["Instrument type", "Currency received"].includes(label) ? form.getByRole("combobox", { name: label, exact: true }) : form.getByLabel(label, { exact: true });
    if (await control.evaluate(node => node.tagName === "SELECT")) await control.selectOption(value);
    else await control.fill(value);
  }
  await form.getByRole("button", { name: "Preview balances", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Review before committing" })).toBeFocused();
  await page.getByRole("button", { name: "Commit reviewed transactions", exact: true }).click();
  await expect(page.locator("main").getByRole("status")).toContainText("Reviewed transactions committed");
  await expect(page.getByRole("button", { name: "Preview balances", exact: true })).toBeFocused();
}

for (const theme of ["light", "dark"]) {
  test(`portfolio native cash, positions and preview in ${theme}`, async ({ page, outOfSessionApplication }, testInfo) => {
    await page.addInitScript(value => localStorage.setItem("stock-probs.theme", value), theme);
    const origin = outOfSessionApplication.url;
    const requests = [];
    page.on("request", request => requests.push(new URL(request.url()).pathname));
    const accountId = await createAccount(page, origin, "My TFSA");
    const form = page.locator("form").filter({ has: page.locator("#transaction-kind") });
    await form.getByLabel("Original date", { exact: true }).fill("2025-01-09");
    await form.getByLabel("Amount", { exact: true }).fill("1000");
    await form.getByRole("button", { name: "Preview balances", exact: true }).click();
    await expect(page.getByRole("heading", { name: "Review before committing" })).toBeFocused();
    const before = await page.request.get(`${origin}/api/v1/portfolio/balances`);
    expect((await before.json()).book.cash).toEqual([]);
    await page.getByRole("button", { name: "Commit reviewed transactions", exact: true }).click();
    await expect(page.locator("main").getByRole("status")).toContainText("Reviewed transactions committed");
    await record(page, accountId, "exchange", { "Amount": "100", "Currency received": "USD", "Actual amount received": "75" });
    await record(page, accountId, "buy", { "Original currency": "USD", "Instrument": "SPY", "Instrument type": "etf", "Units": "0.1", "Price per unit": "500", "Fee in original currency": "1" });
    const balances = await (await page.request.get(`${origin}/api/v1/portfolio/balances`)).json();
    expect(balances.book.cash.map(row => [row.currency, row.amount])).toEqual([["CAD", "900"], ["USD", "24.0"]]);
    expect(balances.book.positions[0]).toMatchObject({ symbol: "SPY", quantity: "0.1", book_cost: "51.0", currency: "USD" });
    await capture(page, testInfo, `transactions-${theme}`);
    await page.goto(`${origin}/overview`);
    await page.getByRole("button", { name: "Refresh values", exact: true }).click();
    await expect(page.getByText("Valuation inputs available", { exact: true })).toBeVisible();
    await expect(page.getByText(/Deterministic simulated FX indicative CAD per USD/)).toBeVisible();
    await expect(page.getByRole("table", { name: "Manual positions. Prices are observations with their provider timestamps." })).toContainText("SPY");
    expect(requests).not.toContain("/api/v1/forecasts");
    await capture(page, testInfo, `portfolio-${theme}`);
    const controls = await page.locator("main button:visible, main select:visible, main input:not([type=checkbox]):visible, main summary:visible").evaluateAll(nodes => nodes.map(node => { const r = node.getBoundingClientRect(); return { name: node.textContent || node.getAttribute("aria-label"), width: r.width, height: r.height }; }));
    expect(controls.filter(row => row.height < 44 || row.width < 44)).toEqual([]);
  });

  test(`what-if frozen reopening and deterministic allocation in ${theme}`, async ({ page, outOfSessionApplication }, testInfo) => {
    await page.addInitScript(value => localStorage.setItem("stock-probs.theme", value), theme);
    const origin = outOfSessionApplication.url;
    const accountId = await createAccount(page, origin, "Scenario TFSA");
    await record(page, accountId, "deposit", { "Amount": "1000" });
    await page.goto(`${origin}/tools/what-if`);
    await page.getByRole("combobox", { name: "Accounts", exact: true }).selectOption(accountId);
    await page.getByLabel("Additional instrument for reallocation (optional)", { exact: true }).fill("SPY");
    await page.getByRole("combobox", { name: "Additional instrument type", exact: true }).selectOption("etf");
    const baselineResponse = page.waitForResponse(row => new URL(row.url()).pathname === "/api/v1/portfolio/snapshots" && row.request().method() === "POST");
    await page.getByRole("button", { name: "Freeze portfolio baseline", exact: true }).click();
    const baseline = await (await baselineResponse).json();
    await page.getByRole("textbox", { name: /^SPY price change/ }).fill("-20");
    await page.getByRole("textbox", { name: /^USD\/CAD change/ }).fill("10");
    await page.getByRole("combobox", { name: "Funding cash", exact: true }).selectOption(`${accountId}/CAD`);
    await page.getByRole("combobox", { name: "Instrument", exact: true }).selectOption("SPY/etf");
    await page.getByLabel("Amount in funding currency", { exact: true }).fill("100");
    await page.getByRole("button", { name: "Add hypothetical allocation", exact: true }).click();
    await page.getByRole("button", { name: "Calculate simulation", exact: true }).click();
    await expect(page.getByText("CAD -12.00", { exact: true })).toBeVisible();
    await page.getByLabel("Scenario name", { exact: true }).fill("Cash-funded stress test");
    const scenarioResponse = page.waitForResponse(row => new URL(row.url()).pathname === "/api/v1/scenarios" && row.request().method() === "POST");
    await page.getByRole("button", { name: "Save scenario", exact: true }).click();
    const saved = await (await scenarioResponse).json();
    await expect(page.getByText("Saved scenario: Cash-funded stress test", { exact: true })).toBeVisible();
    const actual = await (await page.request.get(`${origin}/api/v1/portfolio/balances`)).json();
    expect(actual.book.cash[0].amount).toBe("1000");
    expect(actual.book.positions).toEqual([]);
    const snapshots = [];
    page.on("request", request => { if (request.method() === "POST" && new URL(request.url()).pathname === "/api/v1/portfolio/snapshots") snapshots.push(request.url()); });
    await page.goto(`${origin}/tools/what-if?scenario_id=${saved.id}`);
    await expect(page.getByText("Saved scenario: Cash-funded stress test", { exact: true })).toBeVisible();
    expect(snapshots).toEqual([]);
    expect(await (await page.request.get(`${origin}/api/v1/portfolio/snapshots/${baseline.id}`)).json()).toEqual(baseline);
    await capture(page, testInfo, `what-if-${theme}`);
  });

  test(`portfolio empty loading error and unavailable states in ${theme}`, async ({ page, outOfSessionApplication, browserDiagnostics }, testInfo) => {
    await page.addInitScript(value => localStorage.setItem("stock-probs.theme", value), theme);
    const origin = outOfSessionApplication.url;
    let release; const loading = new Promise(resolve => { release = resolve; }); let mode = "loading";
    await page.route("**/api/v1/portfolio/balances", async route => {
      if (mode === "loading") await loading;
      if (mode === "error") await route.fulfill({ status: 503, contentType: "application/json", body: JSON.stringify({ error: { code: "portfolio_unavailable", message: "The ledger is temporarily unavailable." } }) });
      else await route.continue();
    });
    await page.goto(`${origin}/overview`);
    await expect(page.locator("main").getByRole("status")).toContainText("Loading accounts and ledger");
    await capture(page, testInfo, `portfolio-loading-${theme}`);
    mode = "empty"; release();
    await expect(page.getByText(/No positions recorded/)).toBeVisible();
    await expect(page.locator("main").getByRole("status")).not.toContainText("Loading accounts");
    await capture(page, testInfo, `portfolio-empty-${theme}`);
    browserDiagnostics.expectHttpFailures({ method: "GET", path: "/api/v1/portfolio/balances", status: 503 });
    mode = "error";
    await page.goto(`${origin}/overview`);
    await expect(page.locator("main").getByRole("alert")).toContainText("The ledger is temporarily unavailable");
    await capture(page, testInfo, `portfolio-error-${theme}`);
    await page.route("**/api/v1/portfolio/features", route => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ enabled: false }) }));
    await page.goto(`${origin}/overview/transactions`);
    await expect(page.getByText("The transaction ledger is not enabled for this account yet.")).toBeVisible();
    await capture(page, testInfo, `transactions-unavailable-${theme}`);
    await page.goto(`${origin}/tools/what-if`);
    await expect(page.getByRole("heading", { name: "What-if unavailable" })).toBeVisible();
    await capture(page, testInfo, `what-if-unavailable-${theme}`);
  });
}

// Replacements must remove response-only metadata before submitting the reviewed draft.
test("correct a saved transaction through its workspace action", async ({ page, outOfSessionApplication }) => {
  const origin = outOfSessionApplication.url;
  const accountId = await createAccount(page, origin, "Correction TFSA");
  await record(page, accountId, "deposit", { "Amount": "1000" });
  await page.getByRole("button", { name: "Correct", exact: true }).click();
  const form = page.locator("form").filter({ has: page.locator("#transaction-kind") });
  await form.getByLabel("Amount", { exact: true }).fill("1200");
  const response = page.waitForResponse(row => new URL(row.url()).pathname === "/api/v1/portfolio/transactions/preview" && row.request().method() === "POST");
  await form.getByRole("button", { name: "Preview balances", exact: true }).click();
  expect((await response).status()).toBe(200);
  await expect(page.getByRole("heading", { name: "Review before committing" })).toBeFocused();
  await page.getByRole("button", { name: "Discard preview", exact: true }).click();
  await expect(form.getByRole("button", { name: "Preview balances", exact: true })).toBeFocused();
  await form.getByRole("button", { name: "Preview balances", exact: true }).click();
  await page.getByRole("button", { name: "Commit reviewed transactions", exact: true }).click();
  await expect(form.getByRole("button", { name: "Preview balances", exact: true })).toBeFocused();
  const book = await (await page.request.get(`${origin}/api/v1/portfolio/balances`)).json();
  expect(book.book.cash[0].amount).toBe("1200");
  const history = await (await page.request.get(`${origin}/api/v1/portfolio/transactions`)).json();
  expect(history.items).toHaveLength(2);
  expect(history.items.filter(row => row.superseded)).toHaveLength(1);
});

// Page advances must include every original transaction without gaps.
test("overview five-row pagination retains every imported original amount", async ({ page, outOfSessionApplication }) => {
  const origin = outOfSessionApplication.url;
  await createAccount(page, origin, "Pagination TFSA");
  const csv = "date,type,currency,amount\n" + Array.from({ length: 13 }, (_, i) => `2025-01-09,deposit,CAD,${i + 1}`).join("\n");
  await page.getByLabel("CSV file", { exact: true }).setInputFiles({ name: "original-records.csv", mimeType: "text/csv", buffer: Buffer.from(csv) });
  await page.getByRole("button", { name: "Validate and preview import", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Review before committing" })).toBeFocused();
  await page.getByRole("button", { name: "Commit reviewed transactions", exact: true }).click();
  await expect(page.getByRole("button", { name: "Preview balances", exact: true })).toBeFocused();
  await page.goto(`${origin}/overview`);
  await expect(page.getByRole("heading", { name: "Recent transactions", exact: true })).toBeVisible();
  await expect(page.getByRole("link", { name: "View all transactions", exact: true })).toBeVisible();
  const seen = [];
  for (let number = 1; number <= 3; number++) {
    await expect(page.getByText(`Page ${number} · 13 records`, { exact: true })).toBeVisible();
    const rows = page.getByRole("table").locator("tbody tr");
    await expect(rows).toHaveCount(number === 3 ? 3 : 5);
    seen.push(...await rows.locator("td:nth-child(3)").evaluateAll(nodes => nodes.map(node => Array.from(node.childNodes).filter(child => child.nodeType === Node.TEXT_NODE).map(child => child.textContent).join(""))));
    if (number < 3) await page.getByRole("button", { name: "Next", exact: true }).click();
  }
  expect(seen).toEqual(Array.from({ length: 13 }, (_, i) => `CAD ${13 - i}`));
});
