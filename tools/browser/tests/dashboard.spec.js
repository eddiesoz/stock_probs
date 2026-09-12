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

// Ratios are independently recorded from the WCAG relative-luminance formula. The entries cover
// every authored foreground/background token pairing, including hover, error, and chart states.
const CONTRAST_STATES = [
  { state: "primary paper text", foreground: "--ink", background: "--paper", minimum: 4.5, recorded: 13.85 },
  { state: "secondary paper text", foreground: "--ink-soft", background: "--paper", minimum: 4.5, recorded: 9.65 },
  { state: "muted paper text", foreground: "--muted", background: "--paper", minimum: 4.5, recorded: 5.13 },
  { state: "section number on paper", foreground: "--signal-dark", background: "--paper", minimum: 4.5, recorded: 5.89 },
  { state: "large signal headline on paper", foreground: "--signal", background: "--paper", minimum: 3, recorded: 3.85 },
  { state: "light text on terminal", foreground: "#ffffff", background: "--ink", minimum: 4.5, recorded: 16.07 },
  { state: "mint text on terminal", foreground: "--mint", background: "--ink", minimum: 4.5, recorded: 10.94 },
  { state: "field index on terminal", foreground: "#92a69e", background: "--ink", minimum: 4.5, recorded: 6.25 },
  { state: "hint text on terminal", foreground: "#b9c6c1", background: "--ink", minimum: 4.5, recorded: 9.12 },
  { state: "field error on terminal", foreground: "#ffb5a3", background: "--ink", minimum: 4.5, recorded: 9.48 },
  { state: "primary sheet text", foreground: "--ink", background: "--sheet", minimum: 4.5, recorded: 15.8 },
  { state: "muted sheet and option text", foreground: "--muted", background: "--sheet", minimum: 4.5, recorded: 5.86 },
  { state: "identity confirmation text", foreground: "#cad8d2", background: "#203b33", minimum: 4.5, recorded: 8.22 },
  { state: "identity confirmation emphasis", foreground: "#ffffff", background: "#203b33", minimum: 4.5, recorded: 12.11 },
  { state: "primary button text", foreground: "--ink", background: "--lime", minimum: 4.5, recorded: 12.22 },
  { state: "successful status on paper", foreground: "--green", background: "--paper", minimum: 4.5, recorded: 6.02 },
  { state: "repeated status on paper", foreground: "--amber", background: "--paper", minimum: 4.5, recorded: 5.87 },
  { state: "failed status on paper", foreground: "--red", background: "--paper", minimum: 4.5, recorded: 6.27 },
  { state: "comparison description", foreground: "#b9c9c3", background: "--ink", minimum: 4.5, recorded: 9.34 },
  { state: "comparison secondary labels", foreground: "#aebeb8", background: "--ink", minimum: 4.5, recorded: 8.31 },
  { state: "comparison down value", foreground: "#ffad9b", background: "--ink", minimum: 4.5, recorded: 8.96 },
  { state: "chart label", foreground: "--muted", background: "#f6f4eb", minimum: 4.5, recorded: 5.41 },
  { state: "provenance copy", foreground: "#45564f", background: "#e5e5d8", minimum: 4.5, recorded: 6.13 },
  { state: "provenance heading", foreground: "--ink", background: "#e5e5d8", minimum: 4.5, recorded: 12.65 },
  { state: "error label", foreground: "--red", background: "#f4ded9", minimum: 4.5, recorded: 5.65 },
  { state: "error copy", foreground: "--ink", background: "#f4ded9", minimum: 4.5, recorded: 12.47 },
  { state: "navigation hover", foreground: "--ink-soft", background: "--lime", minimum: 4.5, recorded: 8.52 },
  { state: "history action on sheet", foreground: "--signal-dark", background: "--sheet", minimum: 4.5, recorded: 6.72 },
  { state: "focus and loss-chart signal", foreground: "--signal", background: "--sheet", minimum: 3, recorded: 4.4 },
  { state: "control boundary", foreground: "--line-dark", background: "--sheet", minimum: 3, recorded: 3.49 },
  { state: "loading and empty boundary", foreground: "--line-dark", background: "--paper", minimum: 3, recorded: 3.05 },
];

function relativeLuminance(color) {
  const channels = color.match(/[\da-f]{2}/gi).map((channel) => parseInt(channel, 16) / 255);
  const linear = channels.map((channel) => (
    channel <= 0.04045 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4
  ));
  return (0.2126 * linear[0]) + (0.7152 * linear[1]) + (0.0722 * linear[2]);
}

function contrastRatio(foreground, background) {
  const values = [relativeLuminance(foreground), relativeLuminance(background)].sort((a, b) => b - a);
  return (values[0] + 0.05) / (values[1] + 0.05);
}

async function verifyAuthoredContrastStates(page) {
  const tokens = await page.evaluate((names) => {
    const styles = getComputedStyle(document.documentElement);
    return Object.fromEntries(names.map((name) => [name, styles.getPropertyValue(name).trim()]));
  }, [...new Set(CONTRAST_STATES.flatMap(({ foreground, background }) => (
    [foreground, background].filter((value) => value.startsWith("--"))
  )))]);
  return CONTRAST_STATES.map((entry) => {
    const foreground = entry.foreground.startsWith("--") ? tokens[entry.foreground] : entry.foreground;
    const background = entry.background.startsWith("--") ? tokens[entry.background] : entry.background;
    const ratio = contrastRatio(foreground, background);
    expect(ratio, `${entry.state} drifted from its recorded WCAG ratio`).toBeCloseTo(entry.recorded, 2);
    expect(ratio, `${entry.state} does not meet WCAG contrast`).toBeGreaterThanOrEqual(entry.minimum);
    return { ...entry, foreground, background, calculated: Number(ratio.toFixed(2)) };
  });
}

async function forcedColorContrast(page, selector, pseudo = null) {
  const colors = await page.evaluate(({ target, pseudoElement }) => {
    const element = document.querySelector(target);
    const foreground = getComputedStyle(element, pseudoElement).color;
    let background = "rgba(0, 0, 0, 0)";
    for (let current = element; current; current = current.parentElement) {
      const candidate = getComputedStyle(current).backgroundColor;
      if (!candidate.endsWith(", 0)")) {
        background = candidate;
        break;
      }
    }
    return { foreground, background };
  }, { target: selector, pseudoElement: pseudo });
  const toHex = (color) => {
    const channels = color.match(/[\d.]+/g).slice(0, 3).map(Number);
    return `#${channels.map((channel) => Math.round(channel).toString(16).padStart(2, "0")).join("")}`;
  };
  const ratio = contrastRatio(toHex(colors.foreground), toHex(colors.background));
  expect(ratio, `${selector}${pseudo || ""} forced-color contrast`).toBeGreaterThanOrEqual(4.5);
  return { selector, pseudo, ...colors, calculated: Number(ratio.toFixed(2)), minimum: 4.5 };
}

async function expectAxeClean(page) {
  const results = await new AxeBuilder({ page }).analyze();
  expect(results.violations).toEqual([]);
  // R-M04-35 is intentionally stricter than an allowlist: raw axe output must be complete.
  expect(results.incomplete, "axe must fully analyze every rendered node").toEqual([]);
  return results;
}

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

async function submitUiForecast(page, symbol, assetType = "stock") {
  await page.getByLabel("Yahoo Finance symbol").fill(symbol);
  await page.getByLabel(assetType === "etf" ? "ETF" : "Stock").check();
  const responsePromise = page.waitForResponse((response) => (
    response.request().method() === "POST"
    && new URL(response.url()).pathname === "/api/v1/forecasts"
  ));
  await page.getByRole("button", { name: "Run forecast" }).click();
  const response = await responsePromise;
  expect(response.status()).toBe(201);
  return response.json();
}

function expectM03Payload(payload, assetType) {
  expect(payload.input.asset_type).toBe(assetType);
  expect(payload.input.instrument_identity.asset_type).toBe(assetType);
  expect(payload.input.model.name).toEqual(expect.any(String));
  expect(payload.input.model.version).toEqual(expect.any(String));
  expect(payload.input.provider_metadata.intraday_archive_limit).toMatchObject({
    approximate_days: 60,
  });
  expect(payload.results.map((result) => result.horizon).sort()).toEqual([
    "close_to_close",
    "completed_5m_to_close",
  ]);
  for (const result of payload.results) {
    expect(result.reference_timestamp).toEqual(expect.any(String));
    expect(result.reference_state).toEqual(expect.any(String));
    expect(result.target_timestamp).toEqual(expect.any(String));
    expect(result.model_version).toEqual(expect.any(String));
    expect(result.direction_probabilities).toMatchObject({
      down: expect.any(Number),
      unchanged: expect.any(Number),
      up: expect.any(Number),
    });
    expect(result.threshold_probabilities.map((item) => item.threshold).sort((a, b) => a - b)).toEqual([
      -10, -5, -3, -1, 1, 3, 5, 10,
    ]);
    expect(result.threshold_probabilities.every((item) => (
      item.sample_count > 0
      && item.uncertainty.method.includes("Wilson")
      && typeof item.rare_event === "boolean"
    ))).toBe(true);
    expect(result.conditional_magnitudes).toMatchObject({
      gain: { observed_count: expect.any(Number), unit: "percent_return_magnitude" },
      loss: { observed_count: expect.any(Number), unit: "percent_return_magnitude" },
    });
    expect(result.magnitude_intervals.map((item) => item.level)).toEqual([0.5, 0.8, 0.95]);
    expect(result.sample_size).toBeGreaterThan(0);
    expect(result.sample_accounting.effective_count).toBe(result.sample_size);
    expect(result.evaluation).toMatchObject({
      method: expect.stringContaining("chronological"),
      status: "available",
      forecast_model: {
        direction_brier: expect.any(Object),
        reliability: expect.any(Object),
        interval_coverage: expect.any(Array),
      },
      baseline: {
        direction_brier: expect.any(Object),
        reliability: expect.any(Object),
        interval_coverage: expect.any(Array),
      },
    });
  }
}

async function expectM03Presentation(page, companyName, assetType) {
  const result = page.locator("#result-content");
  await expect(result).toContainText(companyName);
  await expect(result).toContainText(assetType === "etf" ? "ETF / ETF" : "STOCK / EQUITY");
  await expect(result.getByText("Origin timestamp")).toHaveCount(2);
  await expect(result.getByText("Reference timestamp")).toHaveCount(2);
  await expect(result.getByText("Target close")).toHaveCount(2);
  await expect(result.locator(".forecast-card").getByText("Session at request")).toHaveCount(2);
  await expect(result.getByText("Down probability")).toHaveCount(2);
  await expect(result.getByText("Unchanged probability")).toHaveCount(2);
  await expect(result.getByText("Up probability")).toHaveCount(2);
  for (const threshold of ["-1%", "-3%", "-5%", "-10%", "+1%", "+3%", "+5%", "+10%"]) {
    await expect(result.getByText(new RegExp(`Return .* ${threshold.replace("+", "\\+")}$`))).toHaveCount(2);
  }
  await expect(result.getByRole("heading", { name: "Conditional gain / loss magnitudes" })).toHaveCount(2);
  for (const level of ["50%", "80%", "95%"]) {
    await expect(result.getByText(`${level} magnitude interval (return and price)`)).toHaveCount(2);
  }
  await expect(result.getByText("Historical sample count")).toHaveCount(2);
  await expect(result.getByRole("heading", { name: "Sample uncertainty" })).toHaveCount(2);
  await expect(result.getByRole("heading", { name: "Chronological walk-forward evaluation" })).toHaveCount(2);
  await expect(result).toContainText("Direction Brier");
  await expect(result).toContainText("Baseline");
  await expect(result).toContainText("Reliability");
  await expect(result).toContainText("Interval coverage");
  await expect(result).toContainText("Provider:");
  await expect(result).toContainText("Response as-of:");
  await expect(result).toContainText("Stale state:");
  await expect(result).toContainText("Missing-bar evidence");
  await expect(result).toContainText("approximately 60 recent days");
  await expect(result).toContainText("Provider request and immutable provenance");
  const widths = await page.evaluate(() => ({
    content: document.body.scrollWidth,
    visual: window.visualViewport?.width || document.documentElement.clientWidth,
  }));
  expect(widths.content).toBeLessThanOrEqual(Math.ceil(widths.visual));
}

test("forecast journey exposes complete text equivalents and audit states", async ({
  page,
  applicationRequests,
  browserDiagnostics,
}, testInfo) => {
  browserDiagnostics.expectHttpFailures({ method: "POST", path: "/api/v1/forecasts", status: 502 });
  browserDiagnostics.expectHttpFailures({ method: "GET", path: "/api/v1/instruments", status: 502 });

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
  await expectAxeClean(page);

  await page.getByRole("button", { name: "Run forecast" }).click();
  await expect(page.getByText(/Repeated \/ current/)).toBeVisible();
  await expect(page.locator("#history-content tbody tr").first()).toContainText("repeated");

  await page.getByLabel("Yahoo Finance symbol").fill("FAIL");
  await expect(page.locator("#lookup-status")).toContainText("Identity lookup unavailable");
  await page.getByRole("button", { name: "Run forecast" }).click();
  await expect(page.getByRole("alert")).toContainText("Deterministic provider failure");
  await expect(page.locator("#history-content tbody tr").first()).toContainText("failed");
  await expectAxeClean(page);

  expect(applicationRequests.length).toBeGreaterThan(0);
  expect(applicationRequests.every((url) => new URL(url).pathname.startsWith("/api/v1"))).toBe(true);
});

test("M03 stock and ETF contracts remain complete, textual, and API-only", async ({
  page,
  applicationRequests,
}) => {
  for (const instrument of [
    { symbol: "ACDC-D", assetType: "stock", company: "ProFrac Holding Corp." },
    { symbol: "SPY-D", assetType: "etf", company: "SPDR S&P 500 ETF Trust" },
  ]) {
    await page.goto("/");
    const payload = await submitUiForecast(page, instrument.symbol, instrument.assetType);
    expectM03Payload(payload, instrument.assetType);
    await expectM03Presentation(page, instrument.company, instrument.assetType);

    const intraday = payload.results.find((item) => item.horizon === "completed_5m_to_close");
    const selectedEnds = payload.input.selected_intraday_bars.map((bar) => Date.parse(bar.end));
    const cutoff = Date.parse(payload.input.request_cutoff);
    expect(Math.max(...selectedEnds)).toBeLessThanOrEqual(cutoff);
    expect(Date.parse(intraday.origin_bar_end)).toBe(Math.max(...selectedEnds));
    await expect(page.locator('[data-horizon="completed_5m_to_close"]')).toContainText(
      "an active incomplete bar is excluded",
    );
  }

  expect(applicationRequests.length).toBeGreaterThan(0);
  expect(applicationRequests.every((url) => new URL(url).pathname.startsWith("/api/v1"))).toBe(true);
  await expectAxeClean(page);
});

test("M03 stale, missing, out-of-session, and failed states are explicit", async ({
  page,
  outOfSessionApplication,
  browserDiagnostics,
}) => {
  browserDiagnostics.expectHttpFailures({ method: "POST", path: "/api/v1/forecasts", status: 502 });
  browserDiagnostics.expectHttpFailures({ method: "GET", path: "/api/v1/instruments", status: 502 });
  await page.goto("/");
  await submitUiForecast(page, "STALE");
  await expect(page.locator("#quality-badge")).toContainText("stale");
  await expect(page.locator(".provenance")).toContainText(/latest completed intraday bar|applicable close elapsed/);

  await page.route("**/api/v1/forecasts", async (route) => {
    const response = await route.fetch();
    const payload = await response.json();
    payload.input.quality = "stale";
    payload.input.quality_reasons = ["provider data contains 2 missing intraday bars"];
    payload.input.stale_state = {
      state: "stale",
      reasons: payload.input.quality_reasons,
    };
    payload.input.provider_metadata.missing_intraday_intervals = 2;
    await route.fulfill({ response, json: payload });
  });
  await page.goto("/");
  await submitUiForecast(page, "SPY-M", "etf");
  await expect(page.locator("#quality-badge")).toContainText("stale");
  await expect(page.locator(".missing-details")).toContainText("Missing intraday intervals");
  await expect(page.locator(".missing-details")).toContainText("2");
  await expect(page.locator(".provenance")).toContainText("provider data contains 2 missing intraday bars");
  await page.unroute("**/api/v1/forecasts");

  await page.goto(outOfSessionApplication.url);
  const outOfSession = await submitUiForecast(page, "ACDC-D");
  expect(outOfSession.input.session_state_at_request).toBe("post_session");
  await expect(page.locator('[data-horizon="completed_5m_to_close"]')).toContainText("Post session");
  await expect(page.locator('[data-horizon="completed_5m_to_close"]')).toContainText(
    "next scheduled session close",
  );

  await page.goto("/");
  await page.getByLabel("Yahoo Finance symbol").fill("FAIL");
  await expect(page.locator("#lookup-status")).toContainText("Identity lookup unavailable");
  await page.getByRole("button", { name: "Run forecast" }).click();
  const failure = page.getByRole("alert");
  await expect(failure).toHaveCount(1);
  await expect(failure).toContainText("Deterministic provider failure");
  await expect(failure).toContainText("Error code: provider_unavailable");
  await expect(page.locator("#result-content .error-panel")).toHaveCount(1);
  await expect(page.locator("#lookup-status")).toBeEmpty();
  await expect(page.locator("#history-content tbody tr").first()).toContainText("failed");
  await expectAxeClean(page);
});

test("managed backup network contract and error UI stay storage-neutral", async ({
  page,
  applicationRequests,
  unexpectedFailureApplication,
  browserDiagnostics,
}, testInfo) => {
  browserDiagnostics.expectHttpFailures(
    { method: "POST", path: "/api/v1/operations/restores", status: 422 },
    { method: "POST", path: "/api/v1/forecasts", status: 502 },
    { method: "GET", path: "/api/v1/instruments", status: 502 },
    { method: "POST", path: "/api/v1/operations/backups", status: 500 },
  );
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
  await expect(page.locator("#lookup-status")).toContainText("Identity lookup unavailable");
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

  // Mobile Chromium can widen its layout viewport when an unbreakable result leaks outside the
  // visual viewport, so compare against the width the user can actually see.
  const viewportWidth = await page.evaluate(() => window.visualViewport?.width || document.documentElement.clientWidth);
  const bodyWidth = await page.evaluate(() => document.body.scrollWidth);
  expect(bodyWidth).toBeLessThanOrEqual(viewportWidth);

  await expectAxeClean(page);
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
  await expectAxeClean(page);
});

test("a superseded lookup is aborted once and cannot race a direct-symbol forecast", async ({
  page,
  browserDiagnostics,
}) => {
  const lookupQueries = [];
  await page.route("**/api/v1/instruments?*", async (route) => {
    const query = new URL(route.request().url()).searchParams.get("query");
    lookupQueries.push(query);
    if (["ProFrac", "ACDC-D"].includes(query)) {
      await new Promise((resolve) => setTimeout(resolve, 500));
    }
    await route.continue();
  });
  browserDiagnostics.expectRequestAborts({
    method: "GET",
    path: "/api/v1/instruments",
    count: 2,
  });
  await page.goto("/");
  const symbol = page.getByLabel("Company name or Yahoo Finance symbol");
  await symbol.fill("ProFrac");
  await expect(page.getByText("Looking up “ProFrac”…")).toBeVisible();
  await symbol.fill("SPDR");
  await expect(page.getByRole("option", { name: /SPDR S&P 500 ETF Trust/ })).toBeVisible();
  await expect(page.locator("#instrument-options")).not.toContainText("ProFrac Holding Corp");

  await symbol.fill("ACDC-D");
  await expect(page.getByText("Looking up “ACDC-D”…")).toBeVisible();
  const forecastResponse = page.waitForResponse((response) => (
    response.request().method() === "POST"
    && new URL(response.url()).pathname === "/api/v1/forecasts"
  ));
  await page.getByRole("button", { name: "Run forecast" }).click();
  expect((await forecastResponse).status()).toBe(201);
  await expect(page.getByRole("heading", { name: "Close → next close" })).toBeVisible();
  await expect(page.locator("#instrument-options")).toBeHidden();
  await expect(page.locator("#lookup-status")).toBeEmpty();
  expect(lookupQueries.filter((query) => query === "ACDC-D")).toHaveLength(1);
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
  await expect(page.locator("#result-content .state-strip")).toContainText(
    "Forecast inputs and values are reopened exactly as saved",
  );
  await expect(page.getByRole("heading", { name: "Append-only outcome ledger" }).first()).toBeVisible();
  await expect(page.locator(".outcome-list").first()).toContainText("official close");
  await expect(page.locator(".outcome-list").first()).toContainText("vendor correction");
  const savedText = await page.locator("#result-content").innerText();

  await historyRow.getByRole("button", { name: "Run fresh cutoff analysis" }).click();
  await expect(page.getByRole("heading", { name: "Fresh historical-cutoff analysis" })).toBeVisible();
  await expect(page.locator("#fresh-analysis-section").getByText("New calculation", { exact: true })).toBeVisible();
  await expect(page.locator("#fresh-analysis-section")).toContainText("Not the saved forecast");
  await expect(page.locator("#fresh-analysis-content")).toContainText("This is a new calculation");
  await expect(page.locator("#fresh-analysis-content")).toContainText("Historical cutoff");
  expect(await page.locator("#result-content").innerText()).toBe(savedText);
  await page.getByLabel("Analysis type").selectOption("fresh_historical_reconstruction");
  const filter = page.getByRole("button", { name: "Filter ledger" });
  await filter.focus();
  await filter.press("Enter");
  await expect(page.locator("#history-content tbody tr").first()).toContainText("Fresh cutoff analysis");
  expect(applicationRequests.every((url) => new URL(url).pathname.startsWith("/api/v1"))).toBe(true);
  await expectAxeClean(page);
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
  await expectAxeClean(page);
});

test("M04 editorial dashboard and horizon visualization match reviewed compositions", async ({
  page,
  applicationRequests,
}, testInfo) => {
  await page.goto("/");
  await expect(page.locator("#system-label")).toContainText("Local service ready");
  await expect(page.locator(".hero")).toHaveScreenshot("forecast-workbench.png", {
    animations: "disabled",
  });

  const symbol = testInfo.project.name.startsWith("desktop") ? "ACDC-D" : "ACDC-M";
  const payload = await submitUiForecast(page, symbol);
  const comparison = page.locator(".horizon-comparison");
  await expect(comparison).toContainText("Daily close origin");
  await expect(comparison).toContainText("Five-minute origin");
  await expect(comparison).toHaveScreenshot("horizon-comparison.png", {
    animations: "disabled",
    maxDiffPixelRatio: 0.04,
  });

  const figures = page.locator(".tail-figure");
  await expect(figures).toHaveCount(2);
  const axisText = (await figures.first().locator(".chart-axis-label").allTextContents()).join(" ");
  for (const label of ["0%", "50%", "100%", "-10%", "+10%", "RETURN THRESHOLD", "PROBABILITY"]) {
    expect(axisText).toContain(label);
  }
  await expect(figures.first()).toContainText("Loss tail · at or below · solid circles");
  await expect(figures.first()).toContainText("Gain tail · at or above · dashed diamonds");
  const point = figures.first().locator(".chart-point").first();
  await point.focus();
  await expect(figures.first().locator(".chart-tooltip")).toContainText(/probability of return at or below/);
  await expect(page.locator(".interval-table").first()).toContainText("50% magnitude interval (return and price)");
  await expect(page.locator(".interval-table").first()).toContainText("95% magnitude interval (return and price)");
  await page.locator("#history-query").fill("ProFrac");
  await page.locator("#history-from").fill("2025-01-10");
  await page.locator("#history-to").fill("2025-01-10");
  await page.locator("#history-model").fill(payload.input.model.name);
  await page.locator("#history-horizon").selectOption("completed_5m_to_close");
  await page.locator("#history-sort").selectOption("company:asc");
  const filteredResponse = page.waitForResponse((response) => (
    new URL(response.url()).pathname === "/api/v1/history"
    && new URL(response.url()).searchParams.get("sort_by") === "company"
  ));
  await page.getByRole("button", { name: "Filter ledger" }).click();
  expect((await filteredResponse).status()).toBe(200);
  const filteredRow = page.locator("#history-content tbody tr").first();
  await expect(filteredRow).toContainText("ProFrac Holding Corp.");
  await expect(filteredRow).toContainText(/2 horizons|evaluation Available/);
  expect(applicationRequests.every((url) => new URL(url).pathname.startsWith("/api/v1"))).toBe(true);
  await expectAxeClean(page);
});

test("R-M04-21/22 exact 1024 query heading and 360 loading state remain separated and bounded", async ({
  page,
}, testInfo) => {
  if (testInfo.project.name.startsWith("desktop")) {
    await page.setViewportSize({ width: 1024, height: 900 });
    await page.goto("/");
    await expect(page.locator("#system-label")).toContainText("Local service ready");
    const label = page.locator(".symbol-field label");
    const index = page.locator(".symbol-field .field-index");
    const [labelBox, indexBox] = await Promise.all([label.boundingBox(), index.boundingBox()]);
    expect(labelBox).not.toBeNull();
    expect(indexBox).not.toBeNull();
    expect(labelBox.x + labelBox.width, "1024px query label overlapped QUERY / 01").toBeLessThanOrEqual(indexBox.x);
    await expect(page.locator(".search-panel")).toHaveScreenshot("query-panel-1024.png", {
      animations: "disabled",
    });
    await expectAxeClean(page);
    return;
  }

  await page.setViewportSize({ width: 360, height: 800 });
  let releaseForecast;
  const forecastRelease = new Promise((resolve) => { releaseForecast = resolve; });
  await page.route("**/api/v1/forecasts", async (route) => {
    await forecastRelease;
    await route.continue();
  });
  await page.goto("/");
  await page.getByLabel("Company name or Yahoo Finance symbol").fill("ACDC-M");
  await page.getByRole("button", { name: "Run forecast" }).click();
  await expect(page.locator("#quality-badge")).toHaveText("Calculating");
  await expect(page.getByText("Retrieving completed bars for ACDC-M…")).toBeVisible();
  const loadingDimensions = await page.evaluate(() => ({
    document: document.documentElement.scrollWidth,
    viewport: document.documentElement.clientWidth,
  }));
  expect(loadingDimensions.document, "360px loading state widened the page").toBeLessThanOrEqual(
    loadingDimensions.viewport,
  );
  const [headingBox, badgeBox] = await Promise.all([
    page.locator("#result-heading").boundingBox(),
    page.locator("#quality-badge").boundingBox(),
  ]);
  expect(headingBox).not.toBeNull();
  expect(badgeBox).not.toBeNull();
  expect(badgeBox.y, "360px loading badge overlapped the heading").toBeGreaterThanOrEqual(
    headingBox.y + headingBox.height,
  );
  expect(badgeBox.x + badgeBox.width, "360px loading badge escaped the viewport").toBeLessThanOrEqual(360);
  await expect(page.locator("#result-section")).toHaveScreenshot("forecast-loading-360.png", {
    animations: "disabled",
  });
  await expectAxeClean(page);
  releaseForecast();
  await expect(page.locator("#result-content")).not.toHaveClass(/loading/);
});

test("M04 360–1440 layouts, touch targets, reduced motion, and high contrast stay usable", async ({
  page,
}, testInfo) => {
  for (const width of [360, 768, 1024, 1440]) {
    await page.setViewportSize({ width, height: width === 360 ? 800 : 900 });
    await page.goto("/");
    const dimensions = await page.evaluate(() => ({
      document: document.documentElement.scrollWidth,
      viewport: document.documentElement.clientWidth,
    }));
    expect(dimensions.document, `${width}px layout overflowed`).toBeLessThanOrEqual(dimensions.viewport);
    for (const control of [
      page.getByRole("button", { name: "Run forecast" }),
      page.getByRole("link", { name: "Download CSV" }),
      page.getByRole("button", { name: "Filter ledger" }),
    ]) {
      const box = await control.boundingBox();
      expect(box.height, `${width}px touch target was too short`).toBeGreaterThanOrEqual(44);
    }
  }

  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.getByLabel("Company name or Yahoo Finance symbol").fill("ACDC");
  await page.getByRole("button", { name: "Run forecast" }).click();
  await expect(page.locator("#result-content")).not.toHaveClass(/loading/);
  const authoredRatios = await verifyAuthoredContrastStates(page);
  await expectAxeClean(page);
  await page.emulateMedia({ forcedColors: "active", reducedMotion: "reduce" });
  await page.getByRole("button", { name: "Filter ledger" }).focus();
  await expect(page.getByRole("button", { name: "Filter ledger" })).toBeFocused();
  const forcedColorRatios = [];
  for (const [selector, pseudo] of [
    ["#forecast-heading", null],
    [".search-panel", null],
    [".search-panel", "::before"],
    [".primary", null],
    [".text-link", null],
    [".history-filters label", null],
    [".horizon-comparison", null],
    [".comparison-title p", null],
    [".comparison-stat.down strong", null],
  ]) {
    forcedColorRatios.push(await forcedColorContrast(page, selector, pseudo));
  }
  await expectAxeClean(page);
  await testInfo.attach("wcag-contrast-ratios.json", {
    body: Buffer.from(JSON.stringify({ authoredRatios, forcedColorRatios }, null, 2)),
    contentType: "application/json",
  });
});
