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
  { state: "primary paper text", foreground: "--text", background: "--canvas", minimum: 4.5, recorded: 13.85 },
  { state: "secondary paper text", foreground: "--soft", background: "--canvas", minimum: 4.5, recorded: 9.65 },
  { state: "muted paper text", foreground: "--muted", background: "--canvas", minimum: 4.5, recorded: 5.13 },
  { state: "section number on paper", foreground: "--signal", background: "--canvas", minimum: 4.5, recorded: 5.89 },
  { state: "large signal headline on paper", foreground: "--focus", background: "--canvas", minimum: 3, recorded: 3.85 },
  { state: "light text on terminal", foreground: "#ffffff", background: "--text", minimum: 4.5, recorded: 16.07 },
  { state: "mint text on terminal", foreground: "--mint", background: "--text", minimum: 4.5, recorded: 10.94 },
  { state: "field index on terminal", foreground: "#92a69e", background: "--text", minimum: 4.5, recorded: 6.25 },
  { state: "hint text on terminal", foreground: "#b9c6c1", background: "--text", minimum: 4.5, recorded: 9.12 },
  { state: "field error on terminal", foreground: "#ffb5a3", background: "--text", minimum: 4.5, recorded: 9.48 },
  { state: "primary sheet text", foreground: "--text", background: "--panel", minimum: 4.5, recorded: 15.8 },
  { state: "muted sheet and option text", foreground: "--muted", background: "--panel", minimum: 4.5, recorded: 5.86 },
  { state: "identity confirmation text", foreground: "#cad8d2", background: "#203b33", minimum: 4.5, recorded: 8.22 },
  { state: "identity confirmation emphasis", foreground: "#ffffff", background: "#203b33", minimum: 4.5, recorded: 12.11 },
  { state: "primary button text", foreground: "--text", background: "--lime", minimum: 4.5, recorded: 12.22 },
  { state: "successful status on paper", foreground: "--good", background: "--canvas", minimum: 4.5, recorded: 6.02 },
  { state: "repeated status on paper", foreground: "--warn", background: "--canvas", minimum: 4.5, recorded: 5.87 },
  { state: "failed status on paper", foreground: "--bad", background: "--canvas", minimum: 4.5, recorded: 6.27 },
  { state: "comparison description", foreground: "#b9c9c3", background: "--text", minimum: 4.5, recorded: 9.34 },
  { state: "comparison secondary labels", foreground: "#aebeb8", background: "--text", minimum: 4.5, recorded: 8.31 },
  { state: "comparison down value", foreground: "#ffad9b", background: "--text", minimum: 4.5, recorded: 8.96 },
  { state: "chart label", foreground: "--muted", background: "#f6f4eb", minimum: 4.5, recorded: 5.41 },
  { state: "provenance copy", foreground: "#45564f", background: "#e5e5d8", minimum: 4.5, recorded: 6.13 },
  { state: "provenance heading", foreground: "--text", background: "#e5e5d8", minimum: 4.5, recorded: 12.65 },
  { state: "error label", foreground: "--bad", background: "#f4ded9", minimum: 4.5, recorded: 5.65 },
  { state: "error copy", foreground: "--text", background: "#f4ded9", minimum: 4.5, recorded: 12.47 },
  { state: "navigation hover", foreground: "--strong", background: "--lime", minimum: 4.5, recorded: 12.22 },
  { state: "history action on sheet", foreground: "--signal", background: "--panel", minimum: 4.5, recorded: 6.72 },
  { state: "focus and loss-chart signal", foreground: "--focus", background: "--panel", minimum: 3, recorded: 4.4 },
  { state: "control boundary", foreground: "--edge", background: "--panel", minimum: 3, recorded: 3.49 },
  { state: "loading and empty boundary", foreground: "--edge", background: "--canvas", minimum: 3, recorded: 3.05 },
];
const THEME_ROLE_CONTRAST = [
  ["text", "--text", "--canvas", 4.5],
  ["muted text", "--muted", "--canvas", 4.5],
  ["control border", "--edge", "--panel", 3],
  ["focus", "--focus", "--canvas", 3],
  ["success", "--good", "--canvas", 4.5],
  ["warning", "--warn", "--canvas", 4.5],
  ["error", "--bad", "--canvas", 4.5],
  ["loss chart", "--loss", "--plot", 3],
  ["gain chart", "--gain", "--plot", 3],
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
    const resolve = (name) => {
      const value = styles.getPropertyValue(name).trim();
      return value.startsWith("var(") ? resolve(value.slice(4, -1)) : value;
    };
    return Object.fromEntries(names.map((name) => [name, resolve(name)]));
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

async function verifyThemeRoleContrast(page) {
  const tokens = await page.evaluate((names) => {
    const styles = getComputedStyle(document.documentElement);
    return Object.fromEntries(names.map((name) => [name, styles.getPropertyValue(name).trim()]));
  }, [...new Set(THEME_ROLE_CONTRAST.flatMap(([, foreground, background]) => [foreground, background]))]);
  return THEME_ROLE_CONTRAST.map(([state, foreground, background, minimum]) => {
    const calculated = contrastRatio(tokens[foreground], tokens[background]);
    expect(calculated, `${state} theme contrast`).toBeGreaterThanOrEqual(minimum);
    return { state, foreground: tokens[foreground], background: tokens[background], minimum, calculated: Number(calculated.toFixed(2)) };
  });
}

async function renderedContrast(page, selector, pseudo = null) {
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
  expect(ratio, `${selector}${pseudo || ""} rendered contrast`).toBeGreaterThanOrEqual(4.5);
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

function newsPayload(symbol, count) {
  return {
    query: { symbol, limit: count > 5 ? 10 : 5 },
    provider: "Yahoo Finance",
    as_of: "2025-01-10T17:03:00Z",
    cache_state: "miss",
    coverage: { returned_count: count, partial_metadata: false, refresh_failed: false },
    items: Array.from({ length: count }, (_, index) => ({
      id: `fixture-${index + 1}`,
      title: `Current headline ${index + 1}`,
      publisher: "Fixture News",
      published_at: `2025-01-10T${String(16 - Math.floor(index / 6)).padStart(2, "0")}:${String((index * 7) % 60).padStart(2, "0")}:00Z`,
      url: `https://example.com/news/${index + 1}`,
      related_symbols: [symbol],
    })),
  };
}

// Dashboard helpers use test-runner expect, optional status, keyboard opening, and literal source assertions.
function themeRadio(page, name) {
  return page.locator(".theme-control").getByRole("radio", { name, exact: true });
}

async function waitForImperativeApp(page) {
  const status = page.locator("#system-label");
  if (await status.count()) await expect(status).not.toHaveText("Checking local service");
}

async function gotoSurface(page, url) {
  const response = await page.goto(url);
  await waitForImperativeApp(page);
  return response;
}

async function reloadSurface(page) {
  const response = await page.reload();
  await waitForImperativeApp(page);
  return response;
}

function expectApiOnlyDataRequests(urls) {
  expect(
    urls.filter((url) => !new URL(url).pathname.startsWith("/api/v1")),
    "fetch/XHR traffic, including Next RSC .txt requests, must stay below /api/v1",
  ).toEqual([]);
}

function literalThemeOrdering(html) {
  const theme = '<script src="/assets/theme.js"></script>';
  const css = '<link rel="stylesheet" href="/assets/app.css"';
  return {
    count: html.split(theme).length - 1,
    beforeCss: html.indexOf(theme) >= 0 && html.indexOf(theme) < html.indexOf(css),
  };
}

async function openSettings(page, keyboard = false) {
  const trigger = page.locator('.settings-trigger[popovertarget="settings-menu"]');
  const menu = page.locator("#settings-menu.settings-menu[popover]");
  if (await menu.isHidden()) {
    if (keyboard) {
      await trigger.focus();
      await trigger.press("Enter");
    } else {
      await trigger.click();
    }
  }
  await expect(menu).toBeVisible();
  expect(await menu.evaluate((element) => element.matches(":popover-open"))).toBe(true);
  return menu;
}

async function attachScreenshot(testInfo, name, locator) {
  await testInfo.attach(name, {
    body: await locator.screenshot({ animations: "disabled" }),
    contentType: "image/png",
  });
}

async function settingsGeometry(page) {
  return page.evaluate(() => {
    const rectangle = (element) => {
      const box = element.getBoundingClientRect();
      return { left: box.left, right: box.right, top: box.top, bottom: box.bottom };
    };
    const trigger = rectangle(document.querySelector(".settings-trigger"));
    const menuElement = document.querySelector("#settings-menu.settings-menu");
    const menu = rectangle(menuElement);
    const focusedElement = document.activeElement;
    const focused = rectangle(focusedElement);
    return {
      scrollY,
      viewport: { width: innerWidth, height: innerHeight, documentHeight: document.documentElement.scrollHeight },
      positionAnchor: getComputedStyle(menuElement).positionAnchor,
      trigger,
      menu,
      focused: {
        ...focused,
        inSettings: Boolean(focusedElement.closest("#settings-menu")),
        overlappedByMenu: menu.left < focused.right && menu.right > focused.left
          && menu.top < focused.bottom && menu.bottom > focused.top,
      },
    };
  });
}

async function expectVisibleThemeControl(page, width) {
  await openSettings(page);
  const control = page.locator(".theme-control");
  await expect(control).toBeVisible();
  await expect(control.locator("select")).toHaveCount(0);
  for (const name of ["Light", "Dark", "System"]) {
    const radio = themeRadio(page, name);
    await expect(radio).toBeVisible();
    const target = await radio.evaluate((input) => {
      const box = (input.closest("label") || input).getBoundingClientRect();
      return { width: box.width, height: box.height };
    });
    expect(target.width, `${width}px ${name} theme target was too narrow`).toBeGreaterThanOrEqual(44);
    expect(target.height, `${width}px ${name} theme target was too short`).toBeGreaterThanOrEqual(44);
  }

  const boxes = await page.locator(
    ".masthead .brand-lockup, .masthead .section-nav a, .masthead .settings-trigger, .masthead-primary > div:first-child",
  ).evaluateAll((elements) => elements.filter((element) => {
    const style = getComputedStyle(element);
    return style.display !== "none" && style.visibility !== "hidden";
  }).map((element) => {
    const box = element.getBoundingClientRect();
    return { label: element.textContent.trim(), left: box.left, right: box.right, top: box.top, bottom: box.bottom };
  }));
  for (let first = 0; first < boxes.length; first += 1) {
    for (let second = first + 1; second < boxes.length; second += 1) {
      const a = boxes[first];
      const b = boxes[second];
      expect(
        a.right <= b.left || b.right <= a.left || a.bottom <= b.top || b.bottom <= a.top,
        `${width}px masthead controls overlapped: ${a.label} / ${b.label}`,
      ).toBe(true);
    }
  }
  expect(await page.evaluate(() => getComputedStyle(document.body, "::before").backgroundImage)).toBe("none");
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
  await expect(result.getByRole("heading", { name: "Conditional gain / loss magnitudes", includeHidden: true })).toHaveCount(2);
  for (const level of ["50%", "80%", "95%"]) {
    await expect(result.getByText(`${level} magnitude interval (return and price)`)).toHaveCount(2);
  }
  await expect(result.getByText("Historical sample count")).toHaveCount(2);
  await expect(result.getByRole("heading", { name: "Sample uncertainty", includeHidden: true })).toHaveCount(2);
  await expect(result.getByRole("heading", { name: "Chronological walk-forward evaluation", includeHidden: true })).toHaveCount(2);
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

  await gotoSurface(page, "/");
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
  const providerDetails = page.locator("details.provider-provenance");
  await expect(providerDetails).toHaveJSProperty("open", false);
  await providerDetails.locator("summary").click();
  await expect(page.getByText(/scheduled US equity sessions \/ us-equities-rules-v1/)).toBeVisible();
  await expect(page.locator("#history-content tbody tr").first()).toContainText(/successful|repeated/);
  await expectAxeClean(page);

  await page.getByRole("button", { name: "Run forecast" }).click();
  await expect(page.getByText(/Repeated \/ current/)).toBeVisible();
  await expect(page.locator("#history-content tbody tr").first()).toContainText("repeated");

  await page.getByLabel("Yahoo Finance symbol").fill("FAIL");
  await expect(page.locator("#lookup-status")).toContainText("Identity lookup unavailable");
  await page.getByRole("button", { name: "Run forecast" }).click();
  await expect(page.locator("#result-content .error-panel[role=alert]")).toContainText("Deterministic provider failure");
  await expect(page.locator("#history-content tbody tr").first()).toContainText("failed");
  await expectAxeClean(page);

  expect(applicationRequests.length).toBeGreaterThan(0);
  expectApiOnlyDataRequests(applicationRequests);
});

test("M03 stock and ETF contracts remain complete, textual, and API-only", async ({
  page,
  applicationRequests,
}) => {
  for (const instrument of [
    { symbol: "ACDC-D", assetType: "stock", company: "ProFrac Holding Corp." },
    { symbol: "SPY-D", assetType: "etf", company: "SPDR S&P 500 ETF Trust" },
  ]) {
    await gotoSurface(page, "/");
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
  expectApiOnlyDataRequests(applicationRequests);
  await expectAxeClean(page);
});

test("result summaries keep complete values in native disclosures and semantic surfaces", async ({
  page,
}, testInfo) => {
  await gotoSurface(page, "/");
  const payload = await submitUiForecast(page, testInfo.project.name.startsWith("desktop") ? "ACDC-D" : "ACDC-M");
  const result = page.locator("#result-content");
  const disclosures = result.locator(".forecast-card details");
  expect(await disclosures.count()).toBeGreaterThan(0);
  expect(await disclosures.evaluateAll((items) => items.every((item) => !item.open))).toBe(true);
  await expect(result.locator(".forecast-card meter")).toHaveCount(6);
  for (const label of [
    "Origin price", "Origin timestamp", "Reference timestamp", "Target close", "Session at request",
    "Down probability", "Unchanged probability", "Up probability", "Historical sample count",
    "Forecast fingerprint",
  ]) {
    await expect(result.getByText(label, { exact: true })).toHaveCount(2);
  }
  for (const forecast of payload.results) {
    const card = result.locator(`[data-horizon="${forecast.horizon}"]`);
    await expect(card.getByRole("heading", { level: 3 })).toBeVisible();
    await expect(card).toContainText(forecast.model_fingerprint || payload.input.model_fingerprint);
    await expect(card).toContainText(forecast.forecast_fingerprint);
    await expect(card).toContainText(String(forecast.sample_size));
  }

  const firstDisclosure = disclosures.first();
  await firstDisclosure.locator("summary").click();
  await expect(firstDisclosure).toHaveJSProperty("open", true);

  const palettes = {};
  await openSettings(page);
  for (const theme of ["Light", "Dark"]) {
    await themeRadio(page, theme).click();
    palettes[theme.toLowerCase()] = await page.evaluate(() => {
      const probe = document.createElement("i");
      document.body.append(probe);
      const token = (name) => {
        probe.style.color = `var(${name})`;
        return getComputedStyle(probe).color;
      };
      const background = (selector) => getComputedStyle(document.querySelector(selector)).backgroundColor;
      const meters = Object.fromEntries(["down", "flat", "up"].map((direction) => [
        direction,
        getComputedStyle(document.querySelector(`.probability-bar.${direction} meter`)).accentColor,
      ]));
      const values = {
        roles: {
          canvas: token("--canvas"), panel: token("--panel"), strongPanel: token("--strong"),
          chart: token("--plot"), bad: token("--bad"), flat: token("--muted"), good: token("--good"),
        },
        surfaces: {
          body: background("body"), search: background(".search-panel"), card: background(".forecast-card"),
          probability: background(".probability-chart"), chart: background(".tail-figure"),
        },
        meters,
      };
      probe.remove();
      return values;
    });
    expect(palettes[theme.toLowerCase()].surfaces).toEqual({
      body: palettes[theme.toLowerCase()].roles.canvas,
      search: palettes[theme.toLowerCase()].roles.strongPanel,
      card: palettes[theme.toLowerCase()].roles.panel,
      probability: palettes[theme.toLowerCase()].roles.panel,
      chart: palettes[theme.toLowerCase()].roles.chart,
    });
    expect(palettes[theme.toLowerCase()].meters).toEqual({
      down: palettes[theme.toLowerCase()].roles.bad,
      flat: palettes[theme.toLowerCase()].roles.flat,
      up: palettes[theme.toLowerCase()].roles.good,
    });
  }
  expect(palettes.light.roles).not.toEqual(palettes.dark.roles);
  await attachScreenshot(testInfo, "forecast-summary-and-disclosure.png", page.locator("#result-section"));
});

test("M03 stale, missing, out-of-session, and failed states are explicit", async ({
  page,
  outOfSessionApplication,
  browserDiagnostics,
}) => {
  browserDiagnostics.expectHttpFailures({ method: "POST", path: "/api/v1/forecasts", status: 502 });
  browserDiagnostics.expectHttpFailures({ method: "GET", path: "/api/v1/instruments", status: 502 });
  await gotoSurface(page, "/");
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
  await gotoSurface(page, "/");
  await submitUiForecast(page, "SPY-M", "etf");
  await expect(page.locator("#quality-badge")).toContainText("stale");
  await expect(page.locator(".missing-details")).toContainText("Missing intraday intervals");
  await expect(page.locator(".missing-details")).toContainText("2");
  await expect(page.locator(".provenance")).toContainText("provider data contains 2 missing intraday bars");
  await page.unroute("**/api/v1/forecasts");

  await gotoSurface(page, outOfSessionApplication.url);
  const outOfSession = await submitUiForecast(page, "ACDC-D");
  expect(outOfSession.input.session_state_at_request).toBe("post_session");
  await expect(page.locator('[data-horizon="completed_5m_to_close"]')).toContainText("Post session");
  await expect(page.locator('[data-horizon="completed_5m_to_close"]')).toContainText(
    "next scheduled session close",
  );

  await gotoSurface(page, "/");
  await page.getByLabel("Yahoo Finance symbol").fill("FAIL");
  await expect(page.locator("#lookup-status")).toContainText("Identity lookup unavailable");
  await page.getByRole("button", { name: "Run forecast" }).click();
  const failure = page.locator("#result-content .error-panel[role=alert]");
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
  await gotoSurface(page, "/");
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
  const errorAlert = page.locator("#result-content .error-panel[role=alert]");
  await expect(errorAlert).toContainText("Deterministic provider failure");
  expectStorageNeutral("forecast error UI", await errorAlert.innerText());

  await gotoSurface(page, unexpectedFailureApplication.url);
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
  expectApiOnlyDataRequests(applicationRequests);
});

test("persisted repeated run relation survives an application restart", async ({ page, restartableApplication }) => {
  // Each project receives an isolated runtime, so the canonical fixture symbol is deterministic.
  const symbol = "ACDC";
  await gotoSurface(page, restartableApplication.url);
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
  await reloadSurface(page);
  const repeatedBeforeRestart = page.locator("#history-content tbody tr").filter({ hasText: "repeated" });
  await expect(repeatedBeforeRestart).toContainText(/Reused immutable run #\d+/);

  await restartableApplication.restart();
  await gotoSurface(page, restartableApplication.url);
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
  await gotoSurface(page, "/");
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

test("Next framework assets stay same-origin while fetch and XHR stay API-only", async ({
  page,
  applicationRequests,
}) => {
  const requests = [];
  page.on("request", (request) => requests.push(request.url()));
  await gotoSurface(page, "/");
  const origin = new URL(page.url()).origin;
  await gotoSurface(page, "/api/v1/docs");

  const framework = requests.filter((url) => new URL(url).pathname.startsWith("/_next/"));
  expect(framework.length).toBeGreaterThan(0);
  expect(framework.every((url) => (
    new URL(url).origin === origin && new URL(url).pathname.startsWith("/_next/static/")
  ))).toBe(true);
  expect(requests.filter((url) => new URL(url).pathname.endsWith(".txt"))).toEqual([]);
  expectApiOnlyDataRequests(applicationRequests);
});

test("company lookup is bounded, race-safe, keyboard-selectable, and confirms identity", async ({ page, applicationRequests }) => {
  await gotoSurface(page, "/");
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
  await gotoSurface(page, "/");
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
  await gotoSurface(page, "/");
  const symbol = testInfo.project.name.startsWith("desktop") ? "SPY-D" : "SPY-M";
  await page.getByLabel("Yahoo Finance symbol").fill(symbol);
  await page.getByLabel("ETF").check();
  await page.getByRole("button", { name: "Run forecast" }).click();
  await expect(page.locator(".forecast-meta").getByText(symbol, { exact: true })).toBeVisible();
  await expect(page.getByText("ETF / ETF", { exact: true })).toBeVisible();
  await expect(page.locator('#history-content td[data-label="Model / evidence"] .run-label').first()).toContainText(/2 horizons|Horizon evidence unavailable/);

  await page.getByLabel("Find symbol").fill(symbol);
  await page.getByRole("button", { name: "Filter ledger" }).click();
  await page.getByRole("button", { name: "Reopen saved forecast" }).first().click();
  await expect(page.getByText(/Immutable recorded result · audit event/)).toBeVisible();
  await expect(page.locator(".forecast-meta").getByText(symbol, { exact: true })).toBeVisible();
  await expect(page.getByText("ETF / ETF", { exact: true })).toBeVisible();
});

test("failed event reopen shows the recorded request identity", async ({
  page,
  browserDiagnostics,
}) => {
  browserDiagnostics.expectHttpFailures({ method: "POST", path: "/api/v1/forecasts", status: 502 });
  await gotoSurface(page, "/");
  await expect(page.locator("#history-content")).toHaveAttribute("aria-busy", "false");
  await page.getByLabel("Yahoo Finance symbol").fill("FAIL");
  const refreshedHistory = page.waitForResponse((response) => (
    new URL(response.url()).pathname === "/api/v1/history" && response.status() === 200
  ));
  await page.getByRole("button", { name: "Run forecast" }).click();
  await refreshedHistory;
  const failedRow = page.locator("#history-content tbody tr").filter({ hasText: "FAIL" }).first();
  await expect(failedRow).toContainText("failed");
  const eventId = (await failedRow.getByText(/New request #\d+/).textContent()).match(/\d+/)[0];
  await failedRow.getByRole("button", { name: "View failed request" }).click();
  const recordedFailure = page.locator("#result-content");
  await expect(recordedFailure.getByRole("alert")).toContainText("Deterministic provider failure");
  await expect(recordedFailure).toContainText("Recorded failed request");
  await expect(recordedFailure).toContainText(`#${eventId}`);
  await expect(recordedFailure).toContainText("FAIL");
  await expect(recordedFailure).toContainText(/STOCK/i);
});

test("only the latest saved reopen may replace its explicit loading state", async ({
  page,
}, testInfo) => {
  const older = await (await page.request.post("/api/v1/forecasts", {
    data: { symbol: "ACDC-D", asset_type: "stock" },
  })).json();
  const newer = await (await page.request.post("/api/v1/forecasts", {
    data: { symbol: "SPY-D", asset_type: "etf" },
  })).json();
  let releaseOlder;
  let markOlderStarted;
  let markOlderSettled;
  const olderRelease = new Promise((resolve) => { releaseOlder = resolve; });
  const olderStarted = new Promise((resolve) => { markOlderStarted = resolve; });
  const olderSettled = new Promise((resolve) => { markOlderSettled = resolve; });
  await page.route("**/api/v1/saved-forecasts/*", async (route) => {
    if (!new URL(route.request().url()).pathname.endsWith(`/${older.event.id}`)) return route.continue();
    markOlderStarted();
    await olderRelease;
    try {
      const response = await route.fetch();
      await route.fulfill({ response });
    } finally {
      markOlderSettled();
    }
  });
  await gotoSurface(page, "/");
  const history = page.locator("#history-content tbody");
  await history.locator("tr").filter({ hasText: `New request #${older.event.id}` }).getByRole("button", { name: "Reopen saved forecast" }).click();
  await olderStarted;
  await expect(page.locator("#result-content")).toHaveAttribute("aria-busy", "true");
  await history.locator("tr").filter({ hasText: `New request #${newer.event.id}` }).getByRole("button", { name: "Reopen saved forecast" }).click();
  await expect(page.locator(".forecast-meta").getByText("SPY-D", { exact: true })).toBeVisible();
  releaseOlder();
  await olderSettled;
  await page.evaluate(() => new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve))));
  await expect(page.locator(".forecast-meta").getByText("SPY-D", { exact: true })).toBeVisible();
  await expect(page.locator("#result-content")).not.toContainText("ACDC-D");
  await attachScreenshot(testInfo, "latest-saved-reopen.png", page.locator("#result-section"));
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

  await gotoSurface(page, "/");
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
  await expect(page.locator("#quality-badge")).toContainText("Recorded quality:");
  await expect(page.locator("#result-content")).not.toContainText("records a new immutable forecast run");
  await expect(page.getByRole("heading", { name: "Append-only outcome ledger" }).first()).toBeVisible();
  await expect(page.locator(".outcome-list").first()).toContainText("official close");
  await expect(page.locator(".outcome-list").first()).toContainText("vendor correction");
  const stableResultText = () => page.locator("#result-content").evaluate((content) => {
    const copy = content.cloneNode(true);
    copy.querySelectorAll(".chart-tooltip").forEach((tooltip) => tooltip.remove());
    return copy.textContent;
  });
  const savedText = await stableResultText();

  let releaseFresh;
  const freshRelease = new Promise((resolve) => { releaseFresh = resolve; });
  let reconstructionRequests = 0;
  await page.route("**/api/v1/history/*/reconstructions", async (route) => {
    reconstructionRequests += 1;
    await freshRelease;
    const response = await route.fetch();
    const payload = await response.json();
    payload.input.quality = "stale";
    payload.input.quality_reasons = ["reconstruction provider data is stale"];
    payload.input.stale_state = { state: "stale", reasons: payload.input.quality_reasons };
    payload.input.limitations = ["Fresh reconstruction limitation."];
    payload.input.provider_metadata.intraday_archive_limit.statement = "Archive coverage is limited.";
    await route.fulfill({ response, json: payload });
  });
  const freshAction = historyRow.getByRole("button", { name: "Run fresh cutoff analysis" });
  await freshAction.click();
  const formattedCutoff = await page.evaluate((value) => new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium", timeStyle: "short",
  }).format(new Date(value)), created.input.request_cutoff);
  await expect(page.locator("#fresh-analysis-content")).toContainText(`source audit event #${created.event.id}`);
  await expect(page.locator("#fresh-analysis-content")).toContainText(`historical cutoff ${formattedCutoff}`);
  await expect(freshAction).toBeDisabled();
  await freshAction.evaluate((button) => button.click());
  await expect.poll(() => reconstructionRequests).toBe(1);
  releaseFresh();
  await expect(page.getByRole("heading", { name: "Fresh historical-cutoff analysis" })).toBeVisible();
  await expect(page.locator("#fresh-analysis-section").getByText("New calculation", { exact: true })).toBeVisible();
  await expect(page.locator("#fresh-analysis-section")).toContainText("Not the saved forecast");
  await expect(page.locator("#fresh-analysis-content")).toContainText("This is a new calculation");
  await expect(page.locator("#fresh-analysis-content")).toContainText("Historical cutoff");
  await expect(page.locator("#fresh-analysis-content")).toContainText(`Source audit event#${created.event.id}`);
  await expect(page.locator("#fresh-analysis-content")).toContainText(`Instrument${created.input.canonical_symbol}`);
  await expect(page.locator("#fresh-analysis-content")).toContainText(`Provider${created.input.provider}`);
  await expect(page.locator("#fresh-analysis-content .fresh-warning")).toContainText("reconstruction provider data is stale");
  await expect(page.locator("#fresh-analysis-content")).toContainText("Input qualitystale");
  await expect(page.locator("#fresh-analysis-content")).toContainText("Quality reasonsreconstruction provider data is stale");
  await expect(page.locator("#fresh-analysis-content")).toContainText("Provider / archive limitationsFresh reconstruction limitation. Archive coverage is limited.");
  expect(await stableResultText()).toBe(savedText);
  await page.locator(".advanced-filters summary").click();
  await page.getByLabel("Analysis type").selectOption("fresh_historical_reconstruction");
  const filter = page.getByRole("button", { name: "Filter ledger" });
  await filter.focus();
  await filter.press("Enter");
  await expect(page.locator("#history-content tbody tr").first()).toContainText("Fresh cutoff analysis");
  expectApiOnlyDataRequests(applicationRequests);
  await expectAxeClean(page);
});

test("fresh-analysis failure keeps source context and refreshes the ledger", async ({
  page,
  browserDiagnostics,
}) => {
  const createdResponse = await page.request.post("/api/v1/forecasts", {
    data: { symbol: "ACDC-D", asset_type: "stock" },
  });
  const created = await createdResponse.json();
  let historyRequests = 0;
  page.on("request", (request) => {
    if (new URL(request.url()).pathname === "/api/v1/history") historyRequests += 1;
  });
  await page.route("**/api/v1/history/*/reconstructions", (route) => route.fulfill({
    status: 502,
    contentType: "application/json",
    json: { error: { code: "provider_unavailable", message: "Fresh provider unavailable", request_id: "12345678-1234-4123-8123-123456789abc" } },
  }));
  browserDiagnostics.expectHttpFailures({
    method: "POST", path: `/api/v1/history/${created.event.id}/reconstructions`, status: 502,
  });
  await gotoSurface(page, "/");
  await expect(page.locator("#history-content")).toHaveAttribute("aria-busy", "false");
  const beforeFailure = historyRequests;
  await page.getByRole("button", { name: "Run fresh cutoff analysis" }).first().click();
  const failure = page.locator("#fresh-analysis-content").getByRole("alert");
  await expect(failure).toContainText(`Source audit event #${created.event.id}`);
  await expect(failure).toContainText("historical cutoff");
  await expect(failure).toContainText("Error code: provider_unavailable");
  await expect(failure).toContainText("Audit request: 12345678-1234-4123-8123-123456789abc");
  await expect.poll(() => historyRequests).toBeGreaterThan(beforeFailure);
});

test("390px result metadata keeps long values intact without horizontal overflow", async ({
  page,
}, testInfo) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const longValues = {
    display_name: "International Consolidated Renewable Energy Holdings",
    company_name: "International Consolidated Renewable Energy Holdings Incorporated",
    exchange: "Global Select Market",
    exchange_timezone: "America/Argentina/Buenos_Aires",
  };
  await page.route("**/api/v1/forecasts", async (route) => {
    const response = await route.fetch();
    const payload = await response.json();
    Object.assign(payload.input, longValues);
    await route.fulfill({ response, json: payload });
  });
  await gotoSurface(page, "/");
  await submitUiForecast(page, "ACDC-M");
  await page.locator(".instrument-details summary").click();
  for (const value of Object.values(longValues)) {
    const cell = page.locator(".calculation-details > div").filter({ hasText: value }).first();
    await expect(cell).toContainText(value);
    const layout = await cell.evaluate((element) => {
      const box = element.getBoundingClientRect();
      const style = getComputedStyle(element);
      return { left: box.left, right: box.right, wordBreak: style.wordBreak };
    });
    expect(layout.left).toBeGreaterThanOrEqual(0);
    expect(layout.right).toBeLessThanOrEqual(390);
    expect(layout.wordBreak).not.toBe("break-all");
  }
  const dimensions = await page.evaluate(() => ({
    document: document.documentElement.scrollWidth,
    viewport: document.documentElement.clientWidth,
  }));
  expect(dimensions.document).toBeLessThanOrEqual(dimensions.viewport);
  await attachScreenshot(testInfo, "forecast-long-metadata-390.png", page.locator("#result-section"));
});

test("mobile threshold labels remain separate at 360px and 390px", async ({ page }) => {
  await gotoSurface(page, "/");
  await submitUiForecast(page, "ACDC-D");
  for (const width of [360, 390]) {
    await page.setViewportSize({ width, height: 844 });
    const figures = page.locator(".tail-figure");
    await expect(figures).toHaveCount(2);
    for (const figure of await figures.all()) {
      const ticks = figure.locator(".chart-x-tick");
      await expect(ticks).toHaveText(["-10%", "-5%", "-3%", "-1%", "+1%", "+3%", "+5%", "+10%"]);
      const boxes = await ticks.evaluateAll((labels) => labels.map((label) => {
        const { left, right, top, bottom } = label.getBoundingClientRect();
        return { left, right, top, bottom };
      }));
      for (let first = 0; first < boxes.length; first += 1) {
        for (let second = first + 1; second < boxes.length; second += 1) {
          const a = boxes[first];
          const b = boxes[second];
          expect(a.right <= b.left || b.right <= a.left || a.bottom <= b.top || b.bottom <= a.top,
            `${width}px threshold labels ${first + 1} and ${second + 1} overlap`).toBe(true);
        }
      }
    }
  }
});

test("mobile advanced ledger filters retain every value and history actions align", async ({
  page,
}, testInfo) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.request.post("/api/v1/forecasts", { data: { symbol: "ACDC-M", asset_type: "stock" } });
  await gotoSurface(page, "/");
  const advanced = page.locator("#history-form details");
  await expect(advanced).toHaveJSProperty("open", false);
  const advancedSummary = advanced.locator("summary");
  await advancedSummary.click();
  await expect(advanced).toHaveJSProperty("open", true);
  await advancedSummary.click();
  await expect(advanced).toHaveJSProperty("open", false);
  await advancedSummary.click();

  const values = [
    ["Find symbol or company", "ACDC-M"],
    ["Status", "successful"],
    ["Asset type", "stock"],
    ["Analysis type", "submitted_forecast"],
    ["Submitted from", "2025-01-10"],
    ["Submitted through", "2025-01-10"],
    ["Model name or version", "empirical"],
    ["Forecast horizon", "close_to_close"],
    ["Sort ledger", "symbol:asc"],
    ["Rows per page", "20"],
  ];
  for (const [label, value] of values) {
    const control = page.getByLabel(label, { exact: true });
    if (await control.evaluate((element) => element.tagName === "SELECT")) await control.selectOption(value);
    else await control.fill(value);
  }
  const filtered = page.waitForResponse((response) => {
    const url = new URL(response.url());
    return url.pathname === "/api/v1/history" && url.searchParams.get("q") === "ACDC-M";
  });
  await page.getByRole("button", { name: "Filter ledger" }).click();
  const filteredUrl = new URL((await filtered).url());
  expect(Object.fromEntries(filteredUrl.searchParams)).toMatchObject({
    q: "ACDC-M",
    status: "successful",
    asset_type: "stock",
    analysis_kind: "submitted_forecast",
    submitted_from: "2025-01-10T00:00:00Z",
    submitted_to: "2025-01-10T23:59:59.999Z",
    model: "empirical",
    horizon: "close_to_close",
    sort_by: "symbol",
    sort_order: "asc",
    page_size: "20",
  });
  await expect(page.locator("#history-content tbody tr").first()).toContainText("ACDC-M");
  await advancedSummary.click();
  await expect(advanced).toHaveJSProperty("open", false);
  await advancedSummary.click();
  for (const [label, value] of values) await expect(page.getByLabel(label, { exact: true })).toHaveValue(value);

  const alignment = await page.locator("#history-content tbody tr").first().evaluate((row) => ({
    secondary: [...row.querySelectorAll("td")].filter((cell) => (
      cell.querySelector(".request-label") && cell.querySelector(".run-label")
    )).map((cell) => {
      const primary = cell.querySelector(".request-label").getBoundingClientRect();
      const secondary = cell.querySelector(".run-label").getBoundingClientRect();
      return Math.abs(primary.left - secondary.left);
    }),
    actions: [...row.querySelectorAll(".history-actions button")].map((button) => button.getBoundingClientRect().left),
  }));
  expect(alignment.secondary.length).toBeGreaterThan(0);
  expect(alignment.secondary.every((difference) => difference <= 1)).toBe(true);
  expect(new Set(alignment.actions.map(Math.round)).size).toBe(1);
  await attachScreenshot(testInfo, "ledger-filters-and-row-390.png", page.locator(".ledger"));
});

test("768px ledger cards expose every label and action in light and dark", async ({ page }) => {
  await page.setViewportSize({ width: 768, height: 1024 });
  await page.request.post("/api/v1/forecasts", { data: { symbol: "ACDC-D", asset_type: "stock" } });
  await gotoSurface(page, "/");
  await expect(page.locator("#history-content")).toHaveAttribute("aria-busy", "false");

  const advanced = page.locator(".advanced-filters");
  await expect(advanced).toHaveJSProperty("open", false);
  expect(await advanced.locator(".advanced-filter-grid, .advanced-filter-grid *").evaluateAll((elements) => (
    elements.every((element) => {
      const box = element.getBoundingClientRect();
      return box.width === 0 && box.height === 0;
    })
  ))).toBe(true);

  const expectedLabels = [
    "Request / run", "Instrument", "Type / venue", "Analysis",
    "Status", "Model / evidence", "Submitted", "Actions",
  ];
  await openSettings(page);
  for (const theme of ["Light", "Dark"]) {
    await themeRadio(page, theme).click();
    const layout = await page.locator("#history-content tbody tr").first().evaluate((row) => ({
      documentWidth: document.documentElement.scrollWidth,
      viewportWidth: document.documentElement.clientWidth,
      historyWidth: row.closest(".history-content").scrollWidth,
      historyViewport: row.closest(".history-content").clientWidth,
      labels: [...row.cells].map((cell) => ({
        label: cell.dataset.label,
        rendered: getComputedStyle(cell, "::before").content.replaceAll('"', ""),
        left: cell.getBoundingClientRect().left,
        right: cell.getBoundingClientRect().right,
      })),
      actions: [...row.querySelectorAll(".history-actions button")].map((button) => {
        const box = button.getBoundingClientRect();
        return { left: box.left, right: box.right, height: box.height };
      }),
    }));
    expect(layout.documentWidth, `${theme} document overflow`).toBeLessThanOrEqual(layout.viewportWidth);
    expect(layout.historyWidth, `${theme} ledger required horizontal scrolling`).toBeLessThanOrEqual(layout.historyViewport);
    expect(layout.labels.map(({ label }) => label)).toEqual(expectedLabels);
    expect(layout.labels.every(({ label, rendered, left, right }) => (
      rendered === label && left >= 0 && right <= layout.viewportWidth
    ))).toBe(true);
    expect(layout.actions.length).toBeGreaterThan(0);
    expect(layout.actions.every(({ left, right, height }) => (
      left >= 0 && right <= layout.viewportWidth && height >= 44
    ))).toBe(true);
  }
});

test("filtered CSV and JSON downloads are bounded and parseable", async ({ page }, testInfo) => {
  const symbol = testInfo.project.name.startsWith("desktop") ? "ACDC-D" : "ACDC-M";
  await page.request.post("/api/v1/forecasts", { data: { symbol, asset_type: "stock" } });
  await gotoSurface(page, "/");
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
  await gotoSurface(page, "/");
  await page.getByLabel("Status", { exact: true }).selectOption("failed");
  await page.locator(".advanced-filters summary").click();
  await page.getByLabel("Rows per page").selectOption("10");
  await page.getByRole("button", { name: "Filter ledger" }).click();
  await expect(page.locator("#history-page")).toContainText(/Page 1 of [2-9]/);
  await expect(page.getByRole("button", { name: "Previous" })).toBeDisabled();
  await page.getByRole("button", { name: "Previous" }).evaluate((button) => {
    button.disabled = false;
    button.click();
    button.disabled = true;
  });
  let releasePage;
  const pageRelease = new Promise((resolve) => { releasePage = resolve; });
  await page.route("**/api/v1/history?*", async (route) => {
    if (new URL(route.request().url()).searchParams.get("page") === "2") await pageRelease;
    await route.continue();
  });
  await page.getByRole("button", { name: "Next" }).click();
  await expect(page.locator("#history-content")).toHaveAttribute("aria-busy", "true");
  await expect(page.getByRole("button", { name: "Previous" })).toBeDisabled();
  await expect(page.getByRole("button", { name: "Next" })).toBeDisabled();
  releasePage();
  await expect(page.locator("#history-page")).toContainText("Page 2");
  while (!(await page.getByRole("button", { name: "Next" }).isDisabled())) {
    await page.getByRole("button", { name: "Next" }).click();
    await expect(page.locator("#history-content")).toHaveAttribute("aria-busy", "false");
  }
  await expect(page.getByRole("button", { name: "Next" })).toBeDisabled();
  await page.getByRole("button", { name: "Next" }).evaluate((button) => {
    button.disabled = false;
    button.click();
    button.disabled = true;
  });

  const historyURLs = applicationRequests
    .filter((url) => new URL(url).pathname === "/api/v1/history")
    .map((url) => new URL(url));
  expect(historyURLs.length).toBeGreaterThan(0);
  expect(historyURLs.every((url) => Number(url.searchParams.get("page_size")) <= 50)).toBe(true);
  expect(historyURLs.every((url) => Number(url.searchParams.get("page")) <= 10_000)).toBe(true);
  const lastPage = Number((await page.locator("#history-page").textContent()).match(/of (\d+)/)[1]);
  expect(historyURLs.every((url) => Number(url.searchParams.get("page")) >= 1)).toBe(true);
  expect(historyURLs.every((url) => Number(url.searchParams.get("page")) <= lastPage)).toBe(true);
});

test("latest ledger filters win when delayed responses finish in reverse order", async ({ page }) => {
  await page.request.post("/api/v1/forecasts", { data: { symbol: "ACDC-D", asset_type: "stock" } });
  await page.request.post("/api/v1/forecasts", { data: { symbol: "SPY-D", asset_type: "etf" } });
  let releaseOlder;
  let markOlder;
  let markOlderSettled;
  const olderRelease = new Promise((resolve) => { releaseOlder = resolve; });
  const olderStarted = new Promise((resolve) => { markOlder = resolve; });
  const olderSettled = new Promise((resolve) => { markOlderSettled = resolve; });
  await page.route("**/api/v1/history?*", async (route) => {
    const query = new URL(route.request().url()).searchParams.get("q");
    if (query !== "ACDC-D") return route.continue();
    const response = await route.fetch();
    markOlder();
    await olderRelease;
    await route.fulfill({ response });
    markOlderSettled();
  });
  await gotoSurface(page, "/");
  await page.getByLabel("Find symbol").fill("ACDC-D");
  await page.getByRole("button", { name: "Filter ledger" }).click();
  await olderStarted;
  await page.getByLabel("Find symbol").fill("SPY-D");
  await page.getByRole("button", { name: "Filter ledger" }).click();
  const currentRow = page.locator("#history-content tbody tr").first();
  await expect(currentRow).toContainText("SPY-D");
  releaseOlder();
  await olderSettled;
  await page.evaluate(() => new Promise((resolve) => requestAnimationFrame(resolve)));
  await expect(currentRow).toContainText("SPY-D");
  await expect(currentRow).not.toContainText("ACDC-D");
  expect(new URL(await page.locator("#export-json").getAttribute("href"), page.url()).searchParams.get("q")).toBe("SPY-D");
});

test("validation, loading, and stale states remain explicit", async ({ page }) => {
  await gotoSurface(page, "/");
  const symbol = page.getByLabel("Yahoo Finance symbol");
  await symbol.fill("bad symbol");
  await page.getByRole("button", { name: "Run forecast" }).click();
  await expect(page.getByText(/Enter a 1-15 character symbol|Choose a matching instrument/)).toBeVisible();
  await expect(symbol).toBeFocused();
  await expect(symbol).toHaveAttribute("aria-invalid", "true");
  await symbol.fill("ProFrac");
  await expect(page.getByRole("option", { name: /ProFrac Holding Corp/ })).toBeVisible();
  await symbol.press("ArrowDown");
  await symbol.press("Enter");
  await expect(symbol).not.toHaveAttribute("aria-invalid");
  await expect(page.locator("#symbol-error")).toBeEmpty();

  await page.route("**/api/v1/forecasts", async (route) => {
    await new Promise((resolve) => setTimeout(resolve, 250));
    await route.continue();
  });
  await symbol.fill("STALE");
  await page.getByRole("button", { name: "Run forecast" }).click();
  await expect(page.getByText("Retrieving completed bars for STALE…")).toBeVisible();
  await expect(page.locator("#quality-badge")).toContainText("stale");
  const qualitySummary = page.locator(".quality-summary");
  await expect(qualitySummary).toContainText(/Stale-data reason:.*intraday origin.*applicable close elapsed/);
  const provenanceLink = qualitySummary.getByRole("link", { name: "Review detailed provenance" });
  await expect(provenanceLink).toHaveAttribute("href", "#forecast-provenance");
  const provenance = page.locator("details.provider-provenance");
  await expect(provenance).toHaveJSProperty("open", false);
  await provenanceLink.click();
  await expect(provenance).toHaveJSProperty("open", true);
  expect(await qualitySummary.evaluate((summary) => Boolean(summary.compareDocumentPosition(
    document.querySelector(".forecast-grid"),
  ) & Node.DOCUMENT_POSITION_FOLLOWING))).toBe(true);
  await expectAxeClean(page);
});

test("native settings popover is hidden, responsive, persistent, keyboard-operable, and axe-clean", async ({ page }, testInfo) => {
  const widths = testInfo.project.name.startsWith("desktop") ? [820] : [390, 320];
  const geometry = [];
  for (const path of ["/", "/api/v1/docs"]) {
    for (const width of widths) {
      await page.setViewportSize({ width, height: 844 });
      await gotoSurface(page, path);
      const trigger = page.locator(".settings-trigger");
      const menu = page.locator("#settings-menu.settings-menu");
      await expect(trigger).toHaveAttribute("popovertarget", "settings-menu");
      await expect(menu).toHaveAttribute("popover", "");
      await expect(menu).toBeHidden();
      await expect(page.locator(".theme-control")).toBeHidden();
      for (const name of ["Light", "Dark", "System"]) await expect(themeRadio(page, name)).toBeHidden();
      await expect(page.locator(".theme-control select")).toHaveCount(0);
      if (path === "/" && width === 320) {
        await trigger.evaluate((element) => {
          const scrollIntoView = element.scrollIntoView.bind(element);
          element.scrollIntoView = (options) => {
            element.dataset.scrollCalls = String(Number(element.dataset.scrollCalls || 0) + 1);
            scrollIntoView(options);
          };
        });
      }
      const triggerBox = await trigger.boundingBox();
      expect(triggerBox.width, `${path} ${width}px Settings target was too narrow`).toBeGreaterThanOrEqual(44);
      expect(triggerBox.height, `${path} ${width}px Settings target was too short`).toBeGreaterThanOrEqual(44);

      await openSettings(page, true);
      await expectVisibleThemeControl(page, width);
      const dimensions = await menu.evaluate((element) => {
        const box = element.getBoundingClientRect();
        return {
          left: box.left, right: box.right, top: box.top, bottom: box.bottom,
          document: document.documentElement.scrollWidth,
          viewport: document.documentElement.clientWidth,
          viewportHeight: window.innerHeight,
        };
      });
      expect(dimensions.left, `${path} settings escaped the left edge at ${width}px`).toBeGreaterThanOrEqual(0);
      expect(dimensions.top, `${path} settings escaped the top edge at ${width}px`).toBeGreaterThanOrEqual(0);
      expect(dimensions.right, `${path} settings escaped the right edge at ${width}px`).toBeLessThanOrEqual(dimensions.viewport);
      expect(dimensions.bottom, `${path} settings escaped the bottom edge at ${width}px`).toBeLessThanOrEqual(dimensions.viewportHeight);
      expect(dimensions.document, `${path} overflowed at ${width}px`).toBeLessThanOrEqual(dimensions.viewport);
      await expectAxeClean(page);

      let focusedThemeRadio = await page.locator(":focus").evaluate((element) => Boolean(element.closest(".theme-control")));
      for (let tabs = 0; !focusedThemeRadio && tabs < 2; tabs += 1) {
        await page.keyboard.press("Tab");
        focusedThemeRadio = await page.locator(":focus").evaluate((element) => Boolean(element.closest(".theme-control")));
      }
      expect(focusedThemeRadio, `${path} keyboard entry skipped the theme radios at ${width}px`).toBe(true);
      if (path === "/" && width === 320) {
        const entryScrollCalls = await trigger.getAttribute("data-scroll-calls");
        await page.keyboard.press("ArrowRight");
        await expect(page.locator(".theme-control").getByRole("radio", { checked: true })).toBeFocused();
        expect(await trigger.getAttribute("data-scroll-calls"), "radio-to-radio focus scrolled the anchor")
          .toBe(entryScrollCalls);
      }
      await page.keyboard.press("Tab");
      expect(await page.locator(":focus").evaluate((element) => Boolean(element.closest("#settings-menu")))).toBe(false);
      await expect(menu).toBeVisible();
      const beforeScroll = await settingsGeometry(page);
      expect(beforeScroll.positionAnchor, `${path} open settings used its fixed fallback at ${width}px`).toBe("--settings-trigger");
      expect(beforeScroll.focused.overlappedByMenu, `${path} settings covered the next focused control at ${width}px`).toBe(false);
      await testInfo.attach(`${path === "/" ? "dashboard" : "api-docs"}-settings-${width}-before-scroll.png`, {
        body: await page.screenshot({ animations: "disabled" }), contentType: "image/png",
      });
      await page.evaluate(({ exactMobileSequence }) => window.scrollBy(
        0,
        exactMobileSequence ? 200 : Math.min(240, document.documentElement.scrollHeight - innerHeight - scrollY),
      ), { exactMobileSequence: path === "/" && width === 320 });
      const afterScroll = await settingsGeometry(page);
      const triggerMovement = afterScroll.trigger.top - beforeScroll.trigger.top;
      const menuMovement = afterScroll.menu.top - beforeScroll.menu.top;
      expect(afterScroll.positionAnchor, `${path} settings detached after scrolling at ${width}px`).toBe("--settings-trigger");
      if (afterScroll.scrollY > beforeScroll.scrollY) {
        expect(menuMovement, `${path} settings stayed at its fixed fallback after scrolling at ${width}px`).toBeCloseTo(triggerMovement, 0);
      } else {
        expect(beforeScroll.viewport.documentHeight, `${path} unexpectedly had no scroll range at ${width}px`)
          .toBeLessThanOrEqual(beforeScroll.viewport.height);
        expect({ triggerMovement, menuMovement }).toEqual({ triggerMovement: 0, menuMovement: 0 });
      }
      expect(afterScroll.focused.inSettings, `${path} focus returned to settings at ${width}px`).toBe(false);
      expect(afterScroll.focused.overlappedByMenu, `${path} scrolled settings covered the focused control at ${width}px`).toBe(false);
      geometry.push({ path, width, beforeScroll, afterScroll });
      await testInfo.attach(`${path === "/" ? "dashboard" : "api-docs"}-settings-${width}-after-scroll.png`, {
        body: await page.screenshot({ animations: "disabled" }), contentType: "image/png",
      });

      if (path === "/" && width === 320) {
        expect(afterScroll.scrollY - beforeScroll.scrollY, "dashboard did not scroll meaningfully after Tab")
          .toBeGreaterThanOrEqual(100);
        await expect(page.getByLabel("Company name or Yahoo Finance symbol")).toBeFocused();
        await page.keyboard.press("Shift+Tab");
        await expect(page.locator(".theme-control").getByRole("radio", { checked: true })).toBeFocused();
        await expect(page.locator(":focus")).toBeInViewport({ ratio: 1 });
        await page.evaluate(() => window.scrollTo(0, 200));
      }
      await page.keyboard.press("Escape");
      await expect(menu).toBeHidden();
      expect(await page.locator(":focus").evaluate((element) => Boolean(element.closest("#settings-menu")))).toBe(false);
      if (path === "/" && width === 320) {
        await expect(trigger).toBeFocused();
        const restoredTrigger = await trigger.evaluate((element) => {
          const box = element.getBoundingClientRect();
          return { top: box.top, bottom: box.bottom, viewportHeight: innerHeight };
        });
        expect(restoredTrigger.top, "restored Settings trigger was above the viewport").toBeGreaterThanOrEqual(0);
        expect(restoredTrigger.bottom, "restored Settings trigger was below the viewport")
          .toBeLessThanOrEqual(restoredTrigger.viewportHeight);
      }

      await page.evaluate(() => window.scrollTo(0, 0));
      await openSettings(page, true);
      await themeRadio(page, "Dark").click();
      await page.keyboard.press("Escape");
      await expect(menu).toBeHidden();
      await expect(trigger).toBeFocused();

      await reloadSurface(page);
      await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
      await expect(page.locator(".theme-control")).toBeHidden();
      await openSettings(page, true);
      await expect(themeRadio(page, "Dark")).toBeChecked();
      const dismissPoint = await menu.evaluate((element) => {
        const box = element.getBoundingClientRect();
        return [[1, 1], [innerWidth - 1, 1], [1, innerHeight - 1], [innerWidth - 1, innerHeight - 1]]
          .find(([x, y]) => x < box.left || x > box.right || y < box.top || y > box.bottom);
      });
      expect(dismissPoint, `${path} settings left no light-dismiss target at ${width}px`).toBeDefined();
      await page.mouse.click(...dismissPoint);
      await expect(menu).toBeHidden();
      await page.keyboard.press("Tab");
      const restoredFocus = page.locator(":focus");
      await expect(restoredFocus).toBeVisible();
      expect(await restoredFocus.evaluate((element) => element.closest("#settings-menu") === null)).toBe(true);
      const persistedDimensions = await page.evaluate(() => ({
        document: document.documentElement.scrollWidth,
        viewport: document.documentElement.clientWidth,
      }));
      expect(persistedDimensions.document, `${path} overflowed after dismissal at ${width}px`).toBeLessThanOrEqual(persistedDimensions.viewport);
      if (width === 390) {
        await openSettings(page);
        await attachScreenshot(testInfo, `${path === "/" ? "dashboard" : "api-docs"}-theme-390.png`, page.locator(".masthead"));
      }
    }
  }
  await testInfo.attach("settings-anchor-geometry.json", {
    body: Buffer.from(JSON.stringify(geometry, null, 2)), contentType: "application/json",
  });
});

test("theme initializes before CSS and persists light dark and system choices on both pages", async ({
  page,
  applicationRequests,
}, testInfo) => {
  await page.emulateMedia({ colorScheme: "dark", reducedMotion: "reduce" });
  await gotoSurface(page, "/");
  await page.evaluate(() => localStorage.setItem("stock-probs.theme", "light"));
  const dashboardResponse = await gotoSurface(page, "/");
  const dashboardHtml = await dashboardResponse.text();
  const csp = (await dashboardResponse.headers())["content-security-policy"];
  expect(csp).toMatch(/^default-src 'self'; script-src 'self'(?: 'sha256-[A-Za-z0-9+/]+=*')+; style-src 'self'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'$/);
  expect(csp).not.toMatch(/'unsafe-(?:eval|inline)'/);
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  const ordering = {
    ...await page.evaluate(() => {
      const theme = document.querySelector('script[src="/assets/theme.js"]');
      return {
        async: theme.async,
        defer: theme.defer,
        type: theme.type,
        firstPaintTheme: document.documentElement.dataset.theme,
      };
    }),
    beforeCss: literalThemeOrdering(dashboardHtml).beforeCss,
  };
  expect(literalThemeOrdering(dashboardHtml).count).toBe(1);
  expect(ordering).toEqual({ beforeCss: true, async: false, defer: false, type: "", firstPaintTheme: "light" });
  await openSettings(page);
  const darkTheme = themeRadio(page, "Dark");
  await darkTheme.click();
  await expect(darkTheme).toBeChecked();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  expect(await page.evaluate(() => getComputedStyle(document.documentElement).colorScheme)).toBe("dark");
  expect(await page.evaluate(() => localStorage.getItem("stock-probs.theme"))).toBe("dark");
  await reloadSurface(page);
  await openSettings(page);
  await expect(darkTheme).toBeChecked();
  await darkTheme.press("ArrowLeft");
  await expect(themeRadio(page, "Light")).toBeChecked();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  await reloadSurface(page);
  await openSettings(page);
  await expect(themeRadio(page, "Light")).toBeChecked();
  await themeRadio(page, "Light").press("ArrowRight");
  await expect(darkTheme).toBeChecked();
  const darkRatios = await verifyThemeRoleContrast(page);
  const hoveredLink = page.locator(".section-nav a").first();
  await hoveredLink.hover();
  const darkHoverRatios = [
    await renderedContrast(page, ".section-nav a:first-child"),
    await renderedContrast(page, ".section-nav a:first-child span"),
  ];
  await darkTheme.press("ArrowRight");
  await expect(themeRadio(page, "System")).toBeChecked();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  expect(await page.evaluate(() => localStorage.getItem("stock-probs.theme"))).toBeNull();
  await reloadSurface(page);
  await openSettings(page);
  await expect(themeRadio(page, "System")).toBeChecked();
  const dashboardAxe = await expectAxeClean(page);

  const docsResponse = await gotoSurface(page, "/api/v1/docs");
  const docsHtml = await docsResponse.text();
  expect(literalThemeOrdering(docsHtml)).toEqual({ count: 1, beforeCss: true });
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await openSettings(page);
  await themeRadio(page, "Light").click();
  await expect(themeRadio(page, "Light")).toBeChecked();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  const lightRatios = await verifyThemeRoleContrast(page);
  const docsAxe = await expectAxeClean(page);
  expect(await page.locator(".search-panel").evaluate((panel) => getComputedStyle(panel, "::before").content)).toBe("none");
  expect((await page.locator('script[src="/assets/theme.js"]').getAttribute("defer"))).toBeNull();
  await page.evaluate(() => localStorage.setItem("stock-probs.theme", "invalid"));
  await reloadSurface(page);
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  expect(await page.evaluate(() => localStorage.getItem("stock-probs.theme"))).toBeNull();
  const darkDocsAxe = await expectAxeClean(page);
  await page.emulateMedia({ media: "print", colorScheme: "dark", forcedColors: "none" });
  expect(await page.evaluate(() => getComputedStyle(document.documentElement).colorScheme)).toBe("light");
  await expect(page.locator(".theme-control")).toBeHidden();
  expect(applicationRequests.some((url) => new URL(url).pathname === "/api/v1/news")).toBe(false);
  await testInfo.attach("m09-theme-axe-contrast.json", {
    body: Buffer.from(JSON.stringify({ ordering, lightRatios, darkRatios, darkHoverRatios, axe: { dashboard: dashboardAxe, docs: docsAxe, darkDocs: darkDocsAxe } }, null, 2)),
    contentType: "application/json",
  });
});

test("theme falls back to the system when storage is invalid or unavailable", async ({ page }) => {
  await page.emulateMedia({ colorScheme: "dark" });
  await page.addInitScript(() => {
    Object.defineProperties(Storage.prototype, {
      getItem: { value: () => { throw new DOMException("disabled"); } },
      setItem: { value: () => { throw new DOMException("disabled"); } },
      removeItem: { value: () => { throw new DOMException("disabled"); } },
    });
  });
  await gotoSurface(page, "/");
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await openSettings(page);
  await themeRadio(page, "Light").click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  await expectAxeClean(page);
});

test("news disclosure is lazy bounded safe and separate from immutable evidence", async ({
  page,
  applicationRequests,
}, testInfo) => {
  const requestedLimits = [];
  await page.route("**/api/v1/news?*", async (route) => {
    const url = new URL(route.request().url());
    const limit = Number(url.searchParams.get("limit"));
    requestedLimits.push(limit);
    const payload = newsPayload(url.searchParams.get("symbol"), limit);
    if (limit === 5) payload.items[0].url = "http://unsafe.example/news";
    await route.fulfill({ status: 200, contentType: "application/json", json: payload });
  });
  await gotoSurface(page, "/");
  await page.getByLabel("Company name or Yahoo Finance symbol").fill("ProFrac");
  await expect(page.getByRole("option", { name: /ProFrac Holding Corp/ })).toBeVisible();
  expect(requestedLimits).toEqual([]);
  await openSettings(page);
  await themeRadio(page, "Dark").click();
  expect(requestedLimits).toEqual([]);
  await page.getByLabel("Company name or Yahoo Finance symbol").fill("ACDC-D");
  await page.getByRole("button", { name: "Run forecast" }).click();
  const panel = page.locator(".news-panel");
  const disclosure = panel.locator("summary");
  await expect(disclosure).toHaveText("Current headlines for this symbol");
  await expect(disclosure).toBeVisible();
  await expect(panel).toHaveJSProperty("open", false);
  await expect(page.locator(".news-content")).toHaveAttribute("data-state", "not-requested");
  expect(requestedLimits).toEqual([]);
  await disclosure.click();
  await expect(page.locator(".news-content")).toHaveAttribute("data-state", "fresh");
  await expect(disclosure).toBeFocused();
  await expect(page.locator(".news-content")).toHaveAttribute("aria-busy", "false");
  await expect(page.locator(".news-list li")).toHaveCount(5);
  await expect(page.locator(".news-content")).toContainText("Source: Yahoo Finance · As of:");
  await expect(page.locator(".news-list li").first()).toContainText("Link unavailable");
  const links = page.locator(".news-link");
  await expect(links).toHaveCount(4);
  for (const link of await links.all()) {
    expect(await link.getAttribute("href")).toMatch(/^https:\/\//);
    expect((await link.getAttribute("rel")).split(/\s+/).sort()).toEqual(["noopener", "noreferrer"]);
  }
  await panel.getByRole("button", { name: "Show up to 10 headlines" }).click();
  await expect(page.locator(".news-list li")).toHaveCount(10);
  await expect(page.locator(".news-content")).toHaveAttribute("aria-busy", "false");
  expect(await panel.evaluate((element) => element.contains(document.activeElement))).toBe(true);
  expect(requestedLimits).toEqual([5, 10]);
  await expect(page.locator("#history-content tbody tr").first()).not.toContainText("Current headline");
  await page.getByRole("button", { name: "Reopen saved forecast" }).first().click();
  await expect(page.getByText("Load current headlines for this symbol", { exact: true })).toBeVisible();
  expect(requestedLimits).toEqual([5, 10]);
  expectApiOnlyDataRequests(applicationRequests);
  const axe = await expectAxeClean(page);
  await testInfo.attach("m09-news-axe.json", {
    body: Buffer.from(JSON.stringify(axe, null, 2)), contentType: "application/json",
  });
});

test("news renders empty partial stale failure busy unreachable and superseded states", async ({
  page,
  browserDiagnostics,
}) => {
  let mode = "empty";
  await page.route("**/api/v1/news?*", async (route) => {
    const symbol = new URL(route.request().url()).searchParams.get("symbol");
    if (mode === "provider") return route.fulfill({ status: 502, contentType: "application/json", json: { error: { code: "provider_unavailable", message: "Provider unavailable" } } });
    if (mode === "busy") return route.fulfill({ status: 503, contentType: "application/json", json: { error: { code: "capacity_busy", message: "Busy" } } });
    const payload = newsPayload(symbol, mode === "empty" ? 0 : 1);
    if (mode === "partial") {
      payload.items[0] = { id: "partial", title: "Headline with partial metadata", publisher: null, published_at: null, url: "https://example.com/partial", related_symbols: null };
      payload.coverage.partial_metadata = true;
    }
    if (mode === "stale") {
      payload.cache_state = "stale_fallback";
      payload.coverage.refresh_failed = true;
    }
    return route.fulfill({ status: 200, contentType: "application/json", json: payload });
  });
  browserDiagnostics.expectHttpFailures(
    { method: "GET", path: "/api/v1/news", status: 502 },
    { method: "GET", path: "/api/v1/news", status: 503 },
  );
  await gotoSurface(page, "/");
  const run = async (state) => {
    mode = state;
    await page.getByLabel("Company name or Yahoo Finance symbol").fill("ACDC-D");
    await page.getByRole("button", { name: "Run forecast" }).click();
    await page.getByText("Current headlines for this symbol", { exact: true }).click();
    return page.locator(".news-content");
  };
  await expect(await run("empty")).toHaveAttribute("data-state", "empty");
  await expect(page.locator(".news-content")).toHaveAttribute("aria-busy", "false");
  await expect(page.locator(".news-content")).toContainText("Source: Yahoo Finance · As of:");
  for (const state of ["partial", "stale"]) {
    await expect(await run(state)).toHaveAttribute("data-state", state);
    await expect(page.locator(".news-content")).toHaveAttribute("aria-busy", "false");
  }
  const provider = await run("provider");
  await expect(provider).toHaveAttribute("data-state", "unavailable");
  await expect(provider.getByRole("button", { name: "Retry headlines" })).toHaveCount(1);
  mode = "partial";
  await provider.getByRole("button", { name: "Retry headlines" }).click();
  await expect(provider).toHaveAttribute("data-state", "partial");
  expect(await provider.evaluate((content) => content.closest("details").contains(document.activeElement))).toBe(true);
  const busy = await run("busy");
  await expect(busy).toHaveAttribute("data-state", "busy");
  await expect(busy.getByRole("button", { name: "Retry headlines" })).toHaveCount(1);

  await page.getByLabel("Company name or Yahoo Finance symbol").fill("ACDC-D");
  await page.getByRole("button", { name: "Run forecast" }).click();
  await page.evaluate(() => {
    window.__realFetch = window.fetch;
    window.fetch = (url, options) => String(url).includes("/api/v1/news")
      ? Promise.reject(new TypeError("Local service unreachable")) : window.__realFetch(url, options);
  });
  await page.getByText("Current headlines for this symbol", { exact: true }).click();
  await expect(page.locator(".news-content")).toHaveAttribute("data-state", "unreachable");
  await page.evaluate(() => { window.fetch = window.__realFetch; });
  mode = "empty";
  await page.getByRole("button", { name: "Retry headlines" }).click();
  await expect(page.locator(".news-content")).toHaveAttribute("data-state", "empty");

  await page.evaluate(() => {
    window.__realFetch = window.fetch;
    window.fetch = async (url, options) => {
      if (!String(url).includes("/api/v1/news")) return window.__realFetch(url, options);
      return {
        ok: true,
        status: 200,
        json: () => new Promise((resolve, reject) => (
          options.signal.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError")))
        )),
      };
    };
  });
  await page.getByLabel("Company name or Yahoo Finance symbol").fill("ACDC-D");
  await page.getByRole("button", { name: "Run forecast" }).click();
  await page.getByText("Current headlines for this symbol", { exact: true }).click();
  await expect(page.locator(".news-content")).toHaveAttribute("data-state", "loading");
  await page.getByLabel("Company name or Yahoo Finance symbol").fill("SPY-D");
  await expect(page.locator(".news-content")).toHaveAttribute("data-state", "superseded");
  await expect(page.locator(".news-list")).toHaveCount(0);
  await page.evaluate(() => { window.fetch = window.__realFetch; });
  await expectAxeClean(page);
});

test("a stalled headline request has one finite timeout and manual retry", async ({ page }) => {
  await gotoSurface(page, "/");
  await page.getByLabel("Yahoo Finance symbol").fill("ACDC-D");
  await page.getByRole("button", { name: "Run forecast" }).click();
  await page.evaluate(() => {
    window.__realFetch = window.fetch;
    window.__realSetTimeout = window.setTimeout;
    window.setTimeout = (callback, delay, ...args) => window.__realSetTimeout(callback, delay === 10_000 ? 10 : delay, ...args);
    window.fetch = (url, options) => String(url).includes("/api/v1/news")
      ? new Promise((resolve, reject) => options.signal.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError"))))
      : window.__realFetch(url, options);
  });
  await page.getByText("Current headlines for this symbol", { exact: true }).click();
  const news = page.locator(".news-content");
  await expect(news).toHaveAttribute("data-state", "unreachable");
  await expect(news).toHaveAttribute("aria-busy", "false");
  await expect(news.getByRole("button", { name: "Retry headlines" })).toHaveCount(1);
  await page.evaluate(() => {
    window.fetch = window.__realFetch;
    window.setTimeout = window.__realSetTimeout;
  });
});

test("M04 editorial dashboard and horizon visualization match reviewed compositions", async ({
  page,
  applicationRequests,
}, testInfo) => {
  await gotoSurface(page, "/");
  await expect(page.locator("#system-label")).toContainText("Local service ready");
  await attachScreenshot(testInfo, "forecast-workbench.png", page.locator(".hero"));

  const symbol = testInfo.project.name.startsWith("desktop") ? "ACDC-D" : "ACDC-M";
  const payload = await submitUiForecast(page, symbol);
  const comparison = page.locator(".horizon-comparison");
  await expect(comparison).toContainText("Daily close origin");
  await expect(comparison).toContainText("Five-minute origin");
  await attachScreenshot(testInfo, "horizon-comparison.png", comparison);

  const figures = page.locator(".tail-figure");
  await expect(figures).toHaveCount(2);
  const axisText = (await figures.first().locator(".chart-axis-label").allTextContents()).join(" ");
  for (const label of ["0%", "50%", "100%", "-10%", "+10%", "RETURN THRESHOLD", "PROBABILITY"]) {
    expect(axisText).toContain(label);
  }
  await expect(figures.first()).toContainText("Loss tail · at or below · solid circles");
  await expect(figures.first()).toContainText("Gain tail · at or above · dashed diamonds");
  await figures.first().scrollIntoViewIfNeeded();
  const chartTypography = await figures.first().evaluate((figure) => ({
    axis: parseFloat(getComputedStyle(figure.querySelector(".chart-axis-label")).fontSize),
    legend: parseFloat(getComputedStyle(figure.querySelector(".chart-legend")).fontSize),
    hitStroke: parseFloat(getComputedStyle(figure.querySelector(".chart-point")).strokeWidth),
    hitTarget: (() => {
      const point = figure.querySelector("circle.chart-point");
      const probe = new DOMPoint(Number(point.getAttribute("cx")) + 10, Number(point.getAttribute("cy")))
        .matrixTransform(point.getScreenCTM());
      return document.elementFromPoint(probe.x, probe.y) === point;
    })(),
  }));
  expect(chartTypography.axis).toBeGreaterThanOrEqual(testInfo.project.name.startsWith("mobile") ? 12 : 11);
  expect(chartTypography.legend).toBeGreaterThanOrEqual(12);
  expect(chartTypography.hitStroke).toBeGreaterThanOrEqual(26);
  expect(chartTypography.hitTarget).toBe(true);
  await page.mouse.move(0, 0);
  const point = figures.first().locator(".chart-point").first();
  await point.focus();
  await expect(figures.first().locator(".chart-tooltip")).toContainText(/probability of return at or below/);
  const controlledRow = page.locator(`#${await point.getAttribute("aria-controls")}`);
  await expect(controlledRow).toContainText("Return at or below -10%");
  const controlledDisclosure = page.locator(".forecast-card details").filter({ has: controlledRow });
  await expect(controlledDisclosure).toHaveJSProperty("open", false);
  await point.press("Enter");
  await expect(controlledDisclosure).toHaveJSProperty("open", true);
  await expect(controlledRow).toBeVisible();
  await expect(controlledRow).toBeFocused();
  const gainPoint = figures.first().locator(".chart-point.gain").first();
  await gainPoint.focus();
  await expect(figures.first().locator(".chart-tooltip")).toContainText(/probability of return at or above/);
  await expect(page.locator(`#${await gainPoint.getAttribute("aria-controls")}`)).toContainText("Return at or above +1%");
  if (testInfo.project.name.startsWith("mobile")) {
    await page.setViewportSize({ width: 390, height: 844 });
    await point.click();
  }
  await expect(page.locator(".interval-table").first()).toContainText("50% magnitude interval (return and price)");
  await expect(page.locator(".interval-table").first()).toContainText("95% magnitude interval (return and price)");
  await page.locator(".advanced-filters summary").click();
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
  expectApiOnlyDataRequests(applicationRequests);
  await expectAxeClean(page);
});

test("R-M04-21/22 exact 1024 query heading and 360 loading state remain separated and bounded", async ({
  page,
}, testInfo) => {
  if (testInfo.project.name.startsWith("desktop")) {
    await page.setViewportSize({ width: 1024, height: 900 });
    await gotoSurface(page, "/");
    await expect(page.locator("#system-label")).toContainText("Local service ready");
    const label = page.locator(".symbol-field label");
    const index = page.locator(".symbol-field .field-index");
    const [labelBox, indexBox] = await Promise.all([label.boundingBox(), index.boundingBox()]);
    expect(labelBox).not.toBeNull();
    expect(indexBox).not.toBeNull();
    expect(labelBox.x + labelBox.width, "1024px query label overlapped QUERY / 01").toBeLessThanOrEqual(indexBox.x);
    await attachScreenshot(testInfo, "query-panel-1024.png", page.locator(".search-panel"));
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
  await gotoSurface(page, "/");
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
  await attachScreenshot(testInfo, "forecast-loading-360.png", page.locator("#result-section"));
  await expectAxeClean(page);
  releaseForecast();
  await expect(page.locator("#result-content")).not.toHaveClass(/loading/);
});

test("M04 360–1440 layouts, touch targets, reduced motion, and high contrast stay usable", async ({
  page,
}, testInfo) => {
  for (const width of [360, 768, 1024, 1440]) {
    await page.setViewportSize({ width, height: width === 360 ? 800 : 900 });
    await gotoSurface(page, "/");
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
    await expectVisibleThemeControl(page, width);
    if (width <= 820) {
      await expect(page.locator(".section-nav")).toBeVisible();
      await expect(page.locator(".section-nav a")).toHaveCount(3);
    }
  }

  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.getByLabel("Company name or Yahoo Finance symbol").fill("ACDC");
  await page.getByRole("button", { name: "Run forecast" }).click();
  await expect(page.locator("#result-content")).not.toHaveClass(/loading/);
  const authoredRatios = await verifyAuthoredContrastStates(page);
  await expectAxeClean(page);
  await openSettings(page);
  await themeRadio(page, "Dark").click();
  await page.keyboard.press("Escape");
  await page.emulateMedia({ forcedColors: "active", reducedMotion: "reduce" });
  await page.getByRole("button", { name: "Filter ledger" }).focus();
  await expect(page.getByRole("button", { name: "Filter ledger" })).toBeFocused();
  const forcedColorRatios = [];
  for (const [selector, pseudo] of [
    ["#forecast-heading", null],
    [".search-panel", null],
    [".search-panel", "::before"],
    ["#forecast-form label", null],
    ["#symbol", null],
    [".primary", null],
    [".text-link", null],
    [".history-filters label", null],
    [".history-table th", null],
    ["#quality-badge", null],
    [".horizon-comparison", null],
    [".comparison-title p", null],
    [".comparison-stat.down strong", null],
  ]) {
    forcedColorRatios.push(await renderedContrast(page, selector, pseudo));
  }
  const forcedChart = await page.locator(".tail-figure").first().evaluate((figure) => {
    const loss = getComputedStyle(figure.querySelector(".chart-line.loss"));
    const gain = getComputedStyle(figure.querySelector(".chart-line.gain"));
    return { loss: loss.stroke, gain: gain.stroke, gainDash: gain.strokeDasharray };
  });
  expect(forcedChart.loss).toBe(forcedChart.gain);
  expect(forcedChart.gainDash).not.toBe("none");
  await expectAxeClean(page);
  const printSurfaces = {};
  for (const theme of ["light", "dark"]) {
    await page.emulateMedia({ media: "screen", forcedColors: "none", reducedMotion: "reduce" });
    await page.evaluate(() => window.scrollTo(0, 0));
    await openSettings(page);
    await themeRadio(page, theme === "light" ? "Light" : "Dark").click();
    await page.keyboard.press("Escape");
    await page.emulateMedia({ media: "print", forcedColors: "none", reducedMotion: "reduce" });
    printSurfaces[theme] = await page.evaluate(() => Object.fromEntries([
      ".search-panel", ".horizon-comparison", ".tail-figure", ".history-table th",
    ].map((selector) => {
      const style = getComputedStyle(document.querySelector(selector));
      return [selector, { color: style.color, background: style.backgroundColor }];
    })));
  }
  expect(printSurfaces.light).toEqual(printSurfaces.dark);
  expect(new Set(Object.values(printSurfaces.dark).map(({ background }) => background))).toEqual(new Set(["rgb(255, 255, 255)"]));
  await testInfo.attach("wcag-contrast-ratios.json", {
    body: Buffer.from(JSON.stringify({ authoredRatios, forcedColorRatios, forcedChart, printSurfaces }, null, 2)),
    contentType: "application/json",
  });
});
