// Milestone regressions assert API-only data, audit semantics, accessibility, and responsive layout.
const fs = require("node:fs/promises");
const { test, expect } = require("./fixtures");
const AxeBuilder = require("@axe-core/playwright").default;

const INTERNAL_COUNT_IDENTIFIERS = [
  "search_events",
  "forecast_runs",
  "forecast_inputs",
  "forecast_results",
  "outcomes",
];
const PUBLIC_COUNT_LABELS = [
  "forecast_analyses",
  "market_data_snapshots",
  "outcome_observations",
  "probability_results",
  "searches",
];
const STORAGE_IMPLEMENTATION_LEAK = /(?:\bsqlite3?\b|\bdatabase(?:_[a-z0-9_]*)?\b|\bsql\b|\btraceback\b|\bfile:\/\/|(?:^|[\s"'=])\/(?:home|tmp|var|etc|root|users|usr|opt|srv)\/|\b[a-z]:\\|\b(?:search_events|forecast_runs|forecast_inputs|forecast_results)\b)/i;
const REQUEST_ID = /^[a-f0-9]{8}-[a-f0-9]{4}-4[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$/;

function expectStorageNeutral(label, value) {
  // Public diagnostics may describe an artifact, but never the machine or storage engine behind it.
  expect(String(value), `${label} exposed storage implementation details`).not.toMatch(STORAGE_IMPLEMENTATION_LEAK);
}

function expectPublicBackupCounts(label, counts) {
  expect(counts, `${label} counts must be an object`).not.toBeNull();
  expect(Array.isArray(counts), `${label} counts must not be an array`).toBe(false);
  expect(Object.keys(counts).sort(), `${label} count labels changed`).toEqual(PUBLIC_COUNT_LABELS);
  for (const [name, count] of Object.entries(counts)) {
    expect(Number.isSafeInteger(count), `${label}.${name} must be an integer`).toBe(true);
    expect(count, `${label}.${name} must be non-negative`).toBeGreaterThanOrEqual(0);
  }
  const serialized = JSON.stringify(counts);
  for (const identifier of INTERNAL_COUNT_IDENTIFIERS) {
    expect(serialized, `${label} exposed internal table identifier ${identifier}`).not.toContain(identifier);
  }
}

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

test("managed backup network contract and error UI stay storage-neutral", async ({
  page,
  applicationRequests,
  unexpectedFailureApplication,
}, testInfo) => {
  await page.goto("/");
  await expect(page.locator("#system-label")).toContainText("backup available");

  const artifactName = `browser-${testInfo.project.name}.spbackup`;
  const exchanges = await page.evaluate(async (name) => {
    async function exchange(label, url, options = {}) {
      const response = await fetch(url, {
        ...options,
        headers: { Accept: "application/json", ...(options.headers || {}) },
      });
      const text = await response.text();
      let payload = null;
      try {
        payload = JSON.parse(text);
      } catch (_) {
        // The assertions outside the page report a useful failure for any non-JSON API response.
      }
      return { label, url: response.url, status: response.status, contentType: response.headers.get("content-type"), text, payload };
    }

    const jsonPost = (label, url, body) => exchange(label, url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    return [
      await exchange("backup status", "/api/v1/operations/backups/status"),
      await jsonPost("backup create", "/api/v1/operations/backups", { name }),
      await jsonPost("restore verification", "/api/v1/operations/restores", { name, promote: false }),
      await jsonPost("restore promotion", "/api/v1/operations/restores", { name, promote: true }),
      await jsonPost("restore rejection", "/api/v1/operations/restores", { name: "../escape.spbackup", promote: true }),
      await exchange("OpenAPI", "/api/v1/openapi.json"),
    ];
  }, artifactName);

  expect(exchanges.map(({ status }) => status)).toEqual([200, 201, 200, 200, 422, 200]);
  for (const exchange of exchanges) {
    expect(exchange.contentType, `${exchange.label} must remain JSON`).toContain("application/json");
    expect(exchange.payload, `${exchange.label} returned invalid JSON`).not.toBeNull();
    expectStorageNeutral(exchange.label, exchange.text);
  }

  const [status, created, verified, restored, rejected, contract] = exchanges.map(({ payload }) => payload);
  expect(status).toMatchObject({
    status: "available",
    managed_names_only: true,
    verification_required: true,
    promotion_default: false,
  });
  expect(status.max_artifact_bytes).toBeGreaterThan(0);
  expect(created).toMatchObject({
    created: true,
    format: "stock-probs-backup",
    checksum_algorithm: "sha256",
  });
  expect(created.content_checksum).toMatch(/^[a-f0-9]{64}$/);
  if (created.artifact_size !== undefined) expect(created.artifact_size).toBeGreaterThan(0);
  expect(verified).toMatchObject({ verified: true, promoted: false });
  expect(restored).toMatchObject({ verified: true, promoted: true });
  expectPublicBackupCounts("backup create", created.counts);
  expectPublicBackupCounts("restore verification", verified.counts);
  expectPublicBackupCounts("restore promotion", restored.counts);
  expect(verified.counts).toEqual(created.counts);
  expect(restored.counts).toEqual(created.counts);
  expect(rejected.error.code).toBe("restore_failed");
  expect(contract.paths).toHaveProperty("/api/v1/operations/backups/status");
  expect(contract.paths).toHaveProperty("/api/v1/operations/backups");
  expect(contract.paths).toHaveProperty("/api/v1/operations/restores");

  await page.getByLabel("Yahoo Finance symbol").fill("FAIL");
  await page.getByRole("button", { name: "Run forecast" }).click();
  const errorAlert = page.getByRole("alert");
  await expect(errorAlert).toContainText("Deterministic provider failure");
  expectStorageNeutral("forecast error UI", await errorAlert.innerText());

  await page.goto(unexpectedFailureApplication.url);
  const unexpected = await page.evaluate(async () => {
    const response = await fetch("/api/v1/operations/backups", {
      method: "POST",
      headers: { Accept: "application/json", "Content-Type": "application/json" },
      body: JSON.stringify({ name: "injected-failure.spbackup" }),
    });
    const text = await response.text();
    return {
      status: response.status,
      contentType: response.headers.get("content-type"),
      text,
      payload: JSON.parse(text),
    };
  });
  expect(unexpected.status).toBe(500);
  expect(unexpected.contentType).toContain("application/json");
  expect(unexpected.payload.error).toMatchObject({
    code: "internal_error",
    message: "The local service could not complete the request.",
  });
  expect(unexpected.payload.error.request_id).toMatch(REQUEST_ID);
  expectStorageNeutral("unexpected failure response", unexpected.text);

  expect(applicationRequests.length).toBeGreaterThanOrEqual(exchanges.length);
  expect(applicationRequests.every((url) => new URL(url).pathname.startsWith("/api/v1"))).toBe(true);
});

test("persisted repeated run relation survives an application restart", async ({ page, restartableApplication }) => {
  // Each project receives an isolated runtime, so the canonical fixture symbol is deterministic.
  const symbol = "ACDC";
  await page.goto(restartableApplication.url);
  for (let request = 0; request < 2; request += 1) {
    const responseStatus = await page.evaluate(async (submittedSymbol) => {
      const response = await fetch("/api/v1/forecasts", {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify({ symbol: submittedSymbol, asset_type: "stock" }),
      });
      return response.status;
    }, symbol);
    expect(responseStatus).toBe(201);
  }
  await page.reload();
  const repeatedBeforeRestart = page.locator("#history-content tbody tr").filter({ hasText: "repeated" });
  await expect(repeatedBeforeRestart).toContainText(/Reused immutable run #\d+/);

  await restartableApplication.restart();
  await page.goto(restartableApplication.url);
  await page.getByLabel("Find symbol").fill(symbol);
  await page.getByLabel("Status", { exact: true }).selectOption("repeated");
  await page.getByRole("button", { name: "Filter ledger" }).click();
  const persistedRepeat = page.locator("#history-content tbody tr").first();
  await expect(persistedRepeat).toContainText("repeated");
  await expect(persistedRepeat).toContainText(/Reused immutable run #\d+/);
  await expect(persistedRepeat).not.toContainText("New immutable run");

  await page.getByLabel("Status", { exact: true }).selectOption("successful");
  await page.getByRole("button", { name: "Filter ledger" }).click();
  await expect(page.locator("#history-content tbody tr").first()).toContainText(/New immutable run #\d+/);
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

test("history filters and immutable saved reopen remain usable", async ({ page }, testInfo) => {
  await page.goto("/");
  const symbol = testInfo.project.name.startsWith("desktop") ? "SPY-D" : "SPY-M";
  await page.getByLabel("Yahoo Finance symbol").fill(symbol);
  await page.getByLabel("ETF").check();
  await page.getByRole("button", { name: "Run forecast" }).click();
  await expect(page.locator(".forecast-meta").getByText(symbol, { exact: true })).toBeVisible();
  await expect(page.getByText("ETF / ETF", { exact: true })).toBeVisible();

  await page.getByLabel("Find symbol").fill(symbol);
  await page.getByRole("button", { name: "Filter ledger" }).click();
  await page.getByRole("button", { name: "Reopen saved forecast" }).first().click();
  await expect(page.getByText(/Immutable recorded result · audit event/)).toBeVisible();
  await expect(page.locator(".forecast-meta").getByText(symbol, { exact: true })).toBeVisible();
  await expect(page.getByText("ETF / ETF", { exact: true })).toBeVisible();
});

test("saved results, append-only corrections, and fresh cutoff analysis stay distinct", async ({ page, applicationRequests }, testInfo) => {
  const symbol = testInfo.project.name.startsWith("desktop") ? "ACDC-D" : "ACDC-M";
  const createdResponse = await page.request.post("/api/v1/forecasts", {
    data: { symbol, asset_type: "stock" },
  });
  expect(createdResponse.ok()).toBe(true);
  const created = await createdResponse.json();
  const resultId = created.results[0].id;
  for (const outcome of [
    { observed_close: 24.75, state: "observed", note: "official close" },
    { observed_close: 24.8, state: "corrected", note: "vendor correction" },
  ]) {
    const response = await page.request.post(`/api/v1/forecasts/${resultId}/outcomes`, {
      data: { ...outcome, observed_at: "2025-01-13T16:00:00-05:00" },
    });
    expect(response.ok()).toBe(true);
  }

  await page.goto("/");
  await page.getByLabel("Find symbol").fill(symbol);
  await page.getByRole("button", { name: "Filter ledger" }).click();
  const historyRow = page.locator("#history-content tbody tr").first();
  await expect(historyRow).toContainText("New request");
  const expectedRunLabel = created.reused ? "Reused immutable run" : "New immutable run";
  await expect(historyRow).toContainText(`${expectedRunLabel} #${created.event.run_id}`);
  await historyRow.getByRole("button", { name: "Reopen saved forecast" }).click();
  await expect(page.getByText(/Immutable recorded result · audit event/)).toBeVisible();
  await expect(page.getByRole("heading", { name: "Append-only outcome ledger" }).first()).toBeVisible();
  await expect(page.locator(".outcome-list").first()).toContainText("official close");
  await expect(page.locator(".outcome-list").first()).toContainText("vendor correction");
  const savedText = await page.locator("#result-content").innerText();

  await historyRow.getByRole("button", { name: "Run fresh cutoff analysis" }).click();
  await expect(page.getByRole("heading", { name: "Fresh historical-cutoff analysis" })).toBeVisible();
  await expect(page.locator("#fresh-analysis-content")).toContainText("This is a new calculation");
  await expect(page.locator("#fresh-analysis-content")).toContainText("Historical cutoff");
  expect(await page.locator("#result-content").innerText()).toBe(savedText);
  await page.getByLabel("Analysis type").selectOption("fresh_historical_reconstruction");
  const filter = page.getByRole("button", { name: "Filter ledger" });
  await filter.focus();
  await filter.press("Enter");
  await expect(page.locator("#history-content tbody tr").first()).toContainText("Fresh cutoff analysis");
  expect(applicationRequests.every((url) => new URL(url).pathname.startsWith("/api/v1"))).toBe(true);
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
});

test("filtered CSV and JSON downloads are bounded and parseable", async ({ page }, testInfo) => {
  const symbol = testInfo.project.name.startsWith("desktop") ? "ACDC-D" : "ACDC-M";
  await page.request.post("/api/v1/forecasts", { data: { symbol, asset_type: "stock" } });
  await page.goto("/");
  await page.getByLabel("Find symbol").fill(symbol);
  await page.getByRole("button", { name: "Filter ledger" }).click();

  const [csvDownload] = await Promise.all([
    page.waitForEvent("download"),
    page.getByRole("link", { name: "Download CSV" }).click(),
  ]);
  expect(csvDownload.suggestedFilename()).toMatch(/\.csv$/);
  const csv = await fs.readFile(await csvDownload.path(), "utf8");
  expect(csv).toMatch(/^record_type,event_id,run_id,input_id,result_id,request_id,/);
  expect(csv).toContain(symbol);

  const [jsonDownload] = await Promise.all([
    page.waitForEvent("download"),
    page.getByRole("link", { name: "Download JSON" }).click(),
  ]);
  expect(jsonDownload.suggestedFilename()).toMatch(/\.json$/);
  const json = JSON.parse(await fs.readFile(await jsonDownload.path(), "utf8"));
  expect(json.format).toBe("stock-probs-history");
  expect(json.exported_events).toBeLessThanOrEqual(100);
  expect(json.truncated).toEqual(expect.any(Boolean));
  expect(json.records.some(
    (item) => item.record_type === "event" && item.data.normalized_symbol === symbol,
  )).toBe(true);
});

test("history pagination sends only bounded API filters", async ({ page, applicationRequests }) => {
  for (let index = 0; index < 11; index += 1) {
    await page.request.post("/api/v1/forecasts", {
      data: { symbol: "FAIL", asset_type: "stock" },
    });
  }
  await page.goto("/");
  await page.getByLabel("Status", { exact: true }).selectOption("failed");
  await page.getByLabel("Rows per page").selectOption("10");
  await page.getByRole("button", { name: "Filter ledger" }).click();
  await expect(page.locator("#history-page")).toContainText(/Page 1 of [2-9]/);
  await page.getByRole("button", { name: "Next" }).click();
  await expect(page.locator("#history-page")).toContainText("Page 2");

  const historyURLs = applicationRequests
    .filter((url) => new URL(url).pathname === "/api/v1/history")
    .map((url) => new URL(url));
  expect(historyURLs.length).toBeGreaterThan(0);
  expect(historyURLs.every((url) => Number(url.searchParams.get("page_size")) <= 50)).toBe(true);
  expect(historyURLs.every((url) => Number(url.searchParams.get("page")) <= 10_000)).toBe(true);
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
