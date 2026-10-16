// Synthetic report rows are bounded route fixtures; notifications use the disposable app's real
// local-auth API. This spec does not establish multi-owner isolation or a live-provider baseline.
const AxeBuilder = require("@axe-core/playwright").default;
const { test, expect } = require("./fixtures");

const FIXTURE_NOW = "2025-01-10T22:03:00.000Z";

function featurePayload(overrides = {}) {
  return {
    enabled: true,
    can_arm: true,
    email_available: false,
    reported_at: FIXTURE_NOW,
    ...overrides,
  };
}

function emptyPage() {
  return { items: [], next_cursor: null };
}

function emptyReport(page = 1) {
  return {
    as_of: FIXTURE_NOW,
    counts: { scored: 0, pending: 0, unavailable: 0, disputed: 0, incomparable: 0 },
    groups: [],
    items: [],
    label: "Recorded owner outcomes only.",
    sample_limit: "Metrics use comparable saved outcomes only.",
    direction_boundaries: { down: "below -0.5%", unchanged: "-0.5% through 0.5%", up: "above 0.5%" },
    page,
    page_size: 100,
    total: 0,
    has_next: false,
    denominator_scope: "current_page",
    denominator_count: 0,
  };
}

function scoredRow({
  id,
  symbol,
  target,
  direction = "up",
  correct = true,
  covered = true,
  reason,
  horizon = "weekly_5",
  model = "fixture-model-1",
  fiveMinute = false,
  sourceMethod = "provider_bar",
  observedReturn = 0.02,
}) {
  const origin = 100;
  return {
    result_id: id,
    symbol,
    horizon,
    model_version: model,
    five_minute: fiveMinute,
    target_timestamp: `${target}T15:00:00.000Z`,
    state: "scored",
    reason: reason || `fixture row ${String(id).padStart(2, "0")}`,
    predicted_class: direction,
    observed_class: direction,
    direction_correct: correct,
    interval_80_covered: covered,
    observed_return: observedReturn,
    interval_80_price: { low: origin * 0.97, high: origin * 1.05 },
    outcome: { observed_close: origin * (1 + observedReturn) },
    source: { method: sourceMethod },
  };
}

function unscoredRow({ id, symbol, target, state, reason, horizon = "weekly_5", model = "fixture-model-1", fiveMinute = false }) {
  return {
    result_id: id,
    symbol,
    horizon,
    model_version: model,
    five_minute: fiveMinute,
    target_timestamp: `${target}T15:00:00.000Z`,
    state,
    reason,
    predicted_class: null,
    observed_class: null,
    direction_correct: null,
    interval_80_covered: null,
    observed_return: null,
    interval_80_price: null,
    outcome: null,
    source: null,
  };
}

function populatedReport() {
  const weekly = [
    scoredRow({ id: 1, symbol: "SPY", target: "2025-01-09", reason: "Primary SPY outcome" }),
    scoredRow({ id: 2, symbol: "ACDC", target: "2025-01-08", direction: "down", covered: false, observedReturn: -0.02, reason: "Primary ACDC outcome" }),
    { ...scoredRow({ id: 3, symbol: "SPY", target: "2025-01-07", direction: "up", correct: null, reason: "Tied forecast; no unique direction" }), predicted_class: null },
    unscoredRow({ id: 4, symbol: "ACDC", target: "2025-01-09", state: "pending", reason: "Awaiting target-session evidence" }),
    unscoredRow({ id: 5, symbol: "SPY", target: "2025-01-10", state: "unavailable", reason: "Target evidence unavailable" }),
    unscoredRow({ id: 6, symbol: "ACDC", target: "2025-01-09", state: "disputed", reason: "Outcome under review" }),
    unscoredRow({ id: 7, symbol: "SPY", target: "2025-01-09", state: "incomparable", reason: "Outcome is incomparable" }),
  ];
  for (let index = 1; index <= 18; index += 1) {
    weekly.push(scoredRow({
      id: 10 + index,
      symbol: "SPY",
      target: `2024-12-${String(index).padStart(2, "0")}`,
      reason: `fixture row ${String(index).padStart(2, "0")}`,
    }));
  }
  const fiveMinute = scoredRow({
    id: 100,
    symbol: "SPY",
    target: "2025-01-09",
    horizon: "five_min_forward",
    model: "fixture-model-2",
    fiveMinute: true,
    sourceMethod: "manual_review",
    reason: "Fixture five-minute manual review",
    observedReturn: 0.024,
  });
  // Duplicate identities are intentionally malformed: both copies must leave metrics and rows.
  const rawItems = [...weekly, fiveMinute, { ...weekly[7] }, null];
  return {
    ...emptyReport(),
    counts: { scored: 22, pending: 1, unavailable: 1, disputed: 1, incomparable: 1 },
    groups: [],
    items: rawItems,
    page: 1,
    total: 128,
    has_next: true,
    denominator_scope: "current_page",
    denominator_count: rawItems.length,
  };
}

async function attachAxeCapture(page, testInfo, name, { screenshot = false } = {}) {
  const result = await new AxeBuilder({ page }).analyze();
  // Keep every axe result array intact so later review can distinguish violations and incompletes.
  await testInfo.attach(`${name}-axe-raw.json`, {
    body: Buffer.from(JSON.stringify(result)),
    contentType: "application/json",
  });
  expect(result.violations, `${name} raw axe violations`).toEqual([]);
  expect(result.incomplete, `${name} raw axe incomplete results`).toEqual([]);
  const width = page.viewportSize().width;
  const targets = await page.locator("main button:visible, main select:visible, main input:not([type=checkbox]):visible, main summary:visible").evaluateAll((nodes) => nodes.map((node) => {
    const rect = node.getBoundingClientRect();
    return { tag: node.tagName.toLowerCase(), label: node.getAttribute("aria-label") || node.textContent?.trim().slice(0, 80) || "", width: rect.width, height: rect.height };
  }));
  await testInfo.attach(`${name}-geometry.json`, {
    body: Buffer.from(JSON.stringify({ width, targets })),
    contentType: "application/json",
  });
  expect(targets.filter((target) => target.width < 44 || target.height < 44), `${name} primary target geometry`).toEqual([]);
  const smallChoiceLabels = await page.locator('main label:has(input[type="checkbox"]):visible, main label:has(input[type="radio"]):visible').evaluateAll((nodes) => nodes.map((node) => {
    const rect = node.getBoundingClientRect();
    return { label: node.textContent?.trim() || "", width: rect.width, height: rect.height };
  }));
  expect(smallChoiceLabels.filter((target) => target.width < 44 || target.height < 44), `${name} choice-label target geometry`).toEqual([]);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), `${name} horizontal page overflow`).toBe(true);
  if (screenshot) {
    await testInfo.attach(`${name}.png`, {
      body: await page.screenshot({ fullPage: true, animations: "disabled", scale: "css" }),
      contentType: "image/png",
    });
  }
  return result;
}

function reportRoute(page, response) {
  return page.route("**/api/v1/report-cards?*", async (route) => {
    if (route.request().method() !== "GET") return route.continue();
    await route.fulfill({ status: response.status || 200, contentType: "application/json", body: JSON.stringify(response.body) });
  });
}

test.beforeEach(async ({ page }) => {
  // Match the synthetic disabled-assistant response in auth-flow.spec.js before local sign-in.
  await page.route("**/api/v1/assistant/status", (route) => route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify({
      enabled: false,
      available: false,
      worker: { status: "disabled", reason: null },
      authorization: { role: "admin", admitted: false },
      limits: { active_per_user: 1, active_global: 2, tools_per_turn: 8, turn_seconds: 120 },
      storage: null,
    }),
  }));
});

for (const theme of ["light", "dark"]) {
  test(`notifications lost-response replay is idempotent and simulated baselines stay unavailable in ${theme}`, async ({ page, browserDiagnostics, monitoringApplication }, testInfo) => {
    browserDiagnostics.expectRequestAborts({ method: "POST", path: "/api/v1/alerts" });
    await page.addInitScript((value) => localStorage.setItem("stock-probs.theme", value), theme);
    await monitoringApplication.signIn(page);
    await page.goto(`${monitoringApplication.url}/notifications`);
    await expect(page.locator("html")).toHaveAttribute("data-theme", theme);
    await expect(page.locator("main").getByRole("heading", { level: 2, name: "Notifications", exact: true })).toBeVisible();
    await expect(page.getByText(/15-minute cadence/)).toBeVisible();
    await expect(page.getByText(/cross and return between checks, so a brief crossing may be missed/)).toBeVisible();
    await expect(page.getByText("No alert rules are recorded", { exact: true })).toBeVisible();
    await expect(page.getByText("No threshold notices yet", { exact: true })).toBeVisible();
    const initialAudit = await (await page.request.get(`${monitoringApplication.url}/__qa/monitoring-provider-audit`)).json();
    expect(initialAudit.items, "navigation and safe saved-state reads must not call the fixture provider").toEqual([]);

    const submissions = [];
    const postStatuses = [];
    let firstCreate = true;
    page.on("response", (response) => {
      if (new URL(response.url()).pathname === "/api/v1/alerts" && response.request().method() === "POST") postStatuses.push(response.status());
    });
    await page.route("**/api/v1/alerts", async (route) => {
      if (route.request().method() !== "POST") return route.continue();
      const submission = {
        body: JSON.parse(route.request().postData() || "{}"),
        key: route.request().headers()["idempotency-key"],
      };
      submissions.push(submission);
      if (firstCreate) {
        firstCreate = false;
        const committed = await route.fetch();
        expect(committed.status(), "the fixture server must commit the first create before its response is dropped").toBe(201);
        await route.abort("aborted");
        return;
      }
      await route.continue();
    });

    await page.getByLabel("Symbol", { exact: true }).fill("ACDC");
    await page.getByLabel("Currency", { exact: true }).fill("USD");
    await page.getByLabel("Threshold price", { exact: true }).fill("250");
    const emailChoice = page.locator('main input[type="checkbox"]').nth(1);
    await expect(emailChoice).toBeDisabled();
    await expect(page.getByText("Email alerts are not configured per rule. Account-wide email preferences do not enable delivery for this alert.", { exact: true })).toBeVisible();
    const save = page.getByRole("button", { name: "Save alert request", exact: true });
    await save.focus();
    await page.keyboard.press("Enter");
    await expect(page.getByRole("status").filter({ hasText: "could not be confirmed" })).toBeVisible();
    expect(submissions).toHaveLength(1);

    await page.getByRole("button", { name: "Refresh inbox", exact: true }).click();
    await expect(page.getByText("ACDC", { exact: true })).toBeVisible();
    await expect.poll(async () => {
      const response = await page.request.get(`${monitoringApplication.url}/api/v1/alerts?limit=100`);
      return (await response.json()).items?.[0]?.state;
    }).toBe("unavailable");
    const afterExplicitCreateAudit = await (await page.request.get(`${monitoringApplication.url}/__qa/monitoring-provider-audit`)).json();
    expect(afterExplicitCreateAudit.items).toEqual([{ kind: "lookup" }]);
    await page.getByRole("button", { name: "Refresh inbox", exact: true }).click();
    await expect(page.getByText("Monitoring unavailable", { exact: true })).toBeVisible();
    await expect(page.getByText(/not active until that observation is saved/)).toBeVisible();
    expect(await page.getByRole("button", { name: "Pause alert", exact: true }).count()).toBe(1);
    await expect(page.getByText("Last check", { exact: true })).toBeVisible();

    const main = page.locator("main");
    await page.getByLabel("Symbol", { exact: true }).focus();
    await page.keyboard.press("Tab");
    const keyboardState = await page.evaluate(() => {
      const active = document.activeElement;
      return active ? {
        focused: active.tagName.toLowerCase(),
        label: active.closest("label")?.textContent?.trim() || "",
        outline: getComputedStyle(active).outlineStyle,
      } : null;
    });
    expect(keyboardState?.focused).toBe("input");
    expect(keyboardState?.label).toContain("Currency");
    expect(keyboardState?.outline).not.toBe("none");
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
    await attachAxeCapture(page, testInfo, `notifications-${testInfo.project.name}-${theme}`, { screenshot: true });

    // Refresh leaves the submitted draft and its idempotency key in place for an explicit replay.
    const createAgain = page.getByRole("button", { name: "Save alert request", exact: true });
    await createAgain.focus();
    await page.keyboard.press("Enter");
    await expect(page.getByRole("status").filter({ hasText: "request was submitted" })).toBeVisible();
    await expect(page.locator("main article").filter({ hasText: "ACDC" })).toHaveCount(1);
    expect(submissions).toHaveLength(2);
    expect(submissions[1]).toEqual(submissions[0]);
    expect(postStatuses.slice(-1)).toEqual([200]);
    const saved = await (await page.request.get(`${monitoringApplication.url}/api/v1/alerts?limit=100`)).json();
    expect(saved.items).toHaveLength(1);
    expect(saved.items[0]).toMatchObject({ state: "unavailable", baseline_ready: false, last_observation: null });
    expect(submissions[0].body).toEqual({ symbol: "ACDC", currency: "USD", threshold: "250", direction: "above", repeating: false });
    expect(submissions[0].key).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/);
    expect(submissions[1].key).toBe(submissions[0].key);
    await expect(main).toBeVisible();
  });

  test(`notifications use explicit global-busy and revision-CAS actions in ${theme}`, async ({ page, browserDiagnostics, monitoringApplication }, testInfo) => {
    browserDiagnostics.expectHttpFailures({ method: "POST", path: "/api/v1/alerts/00000000-0000-4000-8000-000000000002/pause", status: 409 });
    await page.addInitScript((value) => localStorage.setItem("stock-probs.theme", value), theme);
    await monitoringApplication.signIn(page);
    await page.goto(`${monitoringApplication.url}/notifications`);
    await expect(page.getByText("No alert rules are recorded", { exact: true })).toBeVisible();

    async function createAlert(symbol) {
      await page.getByLabel("Symbol", { exact: true }).fill(symbol);
      await page.getByLabel("Currency", { exact: true }).fill("USD");
      await page.getByLabel("Threshold price", { exact: true }).fill(symbol === "ACDC" ? "250" : "400");
      await page.getByRole("button", { name: "Save alert request", exact: true }).click();
      await expect(page.getByRole("status").filter({ hasText: "request was submitted" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Save alert request", exact: true })).toBeEnabled();
    }

    await createAlert("ACDC");
    await createAlert("SPY");
    const alerts = await (await page.request.get(`${monitoringApplication.url}/api/v1/alerts?limit=100`)).json();
    expect(alerts.items).toHaveLength(2);
    await page.getByRole("button", { name: "Refresh inbox", exact: true }).click();
    await expect(page.locator("main article").filter({ hasText: "ACDC" })).toBeVisible();
    await expect(page.locator("main article").filter({ hasText: "SPY" })).toBeVisible();

    const bySymbol = new Map(alerts.items.map((item) => [item.config.symbol, item]));
    const firstAlert = bySymbol.get("ACDC");
    const secondAlert = bySymbol.get("SPY");
    expect(firstAlert).toBeDefined();
    expect(secondAlert).toBeDefined();
    const firstPath = `**/api/v1/alerts/${firstAlert.id}/pause`;
    let release;
    let entered;
    const held = new Promise((resolve) => { release = resolve; });
    const requestEntered = new Promise((resolve) => { entered = resolve; });
    const pauseRequests = [];
    await page.route(firstPath, async (route) => {
      if (route.request().method() !== "POST") return route.continue();
      pauseRequests.push(JSON.parse(route.request().postData() || "{}"));
      entered();
      await held;
      await route.continue();
    });
    const firstArticle = page.locator("main article").filter({ hasText: "ACDC" });
    const secondArticle = page.locator("main article").filter({ hasText: "SPY" });
    const pause = firstArticle.getByRole("button", { name: "Pause alert", exact: true });
    await pause.focus();
    await page.keyboard.press("Enter");
    await requestEntered;
    await expect(pause).toBeDisabled();
    await expect(secondArticle.getByRole("button", { name: "Pause alert", exact: true })).toBeDisabled();
    await expect(page.getByRole("button", { name: "Save alert request", exact: true })).toBeDisabled();
    await expect(page.getByLabel("Symbol", { exact: true })).toBeDisabled();
    expect(pauseRequests).toEqual([{ expected_revision: firstAlert.revision }]);
    release();
    await expect(page.getByText("Paused", { exact: true }).first()).toBeVisible();

    // A second client commits the pause after this page loaded its revision. The visible stale
    // button must send its old revision and receive the real API's 409 instead of overwriting it.
    const csrf = (await (await page.request.get(`${monitoringApplication.url}/api/v1/auth/session`)).json()).csrf_token;
    const externalPause = await page.request.post(`${monitoringApplication.url}/api/v1/alerts/${secondAlert.id}/pause`, {
      headers: { "x-csrf-token": csrf },
      data: { expected_revision: secondAlert.revision },
    });
    expect(externalPause.status()).toBe(200);
    await secondArticle.getByRole("button", { name: "Pause alert", exact: true }).click();
    await expect(page.getByRole("status").filter({ hasText: "could not be confirmed" })).toBeVisible();
    await page.getByRole("button", { name: "Refresh inbox", exact: true }).click();
    await expect(page.locator("main article").filter({ hasText: "SPY" }).getByText("Paused", { exact: true })).toBeVisible();
    await expect(page.locator("main article").filter({ hasText: "SPY" }).getByRole("button", { name: "Resume alert", exact: true })).toBeVisible();
    const pausedRows = await (await page.request.get(`${monitoringApplication.url}/api/v1/alerts?limit=100`)).json();
    const pausedAlert = pausedRows.items.find((item) => item.id === secondAlert.id);
    expect(pausedAlert.state).toBe("paused");
    await page.locator("main article").filter({ hasText: "SPY" }).getByRole("button", { name: "Resume alert", exact: true }).click();
    await expect(page.getByRole("status").filter({ hasText: "fresh verified baseline is required" })).toBeVisible();
    const resumedRows = await (await page.request.get(`${monitoringApplication.url}/api/v1/alerts?limit=100`)).json();
    const resumedAlert = resumedRows.items.find((item) => item.id === secondAlert.id);
    expect(resumedAlert.baseline_ready).toBe(false);
    expect(resumedAlert.arm_generation).toBeGreaterThan(pausedAlert.arm_generation);
    const providerAudit = await (await page.request.get(`${monitoringApplication.url}/__qa/monitoring-provider-audit`)).json();
    expect(providerAudit.items.every((item) => item.kind === "lookup")).toBe(true);
    await attachAxeCapture(page, testInfo, `notifications-cas-${testInfo.project.name}-${theme}`, { screenshot: true });
  });

  test(`notifications loading, empty, malformed-error, and feature-unavailable states in ${theme}`, async ({ page, browserDiagnostics, monitoringApplication }, testInfo) => {
    browserDiagnostics.expectHttpFailures({ method: "GET", path: "/api/v1/notifications", status: 500 });
    await page.addInitScript((value) => localStorage.setItem("stock-probs.theme", value), theme);
    await monitoringApplication.signIn(page);
    let mode = "loading";
    let releaseFeatures;
    const featureGate = new Promise((resolve) => { releaseFeatures = resolve; });
    await page.route("**/api/v1/monitoring/features", async (route) => {
      if (mode === "loading") await featureGate;
      if (mode === "unavailable") {
        return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(featurePayload({ enabled: false, can_arm: false })) });
      }
      return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(featurePayload({ can_arm: false })) });
    });
    await page.route("**/api/v1/notifications?*", async (route) => {
      if (mode === "error") return route.fulfill({ status: 500, contentType: "application/json", body: JSON.stringify({ error: { code: "fixture_error", message: "The inbox fixture is unavailable." } }) });
      return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(emptyPage()) });
    });
    await page.route("**/api/v1/alerts?*", (route) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(emptyPage()) }));
    await page.route("**/api/v1/notification-preferences", (route) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ revision: 0, alert_email: false, digest_email: false, digest_time: "09:00", digest_timezone: "UTC", address_configured: false, updated_at: null }) }));

    await page.goto(`${monitoringApplication.url}/notifications`);
    await expect(page.getByText("Loading saved notifications and alert rules…", { exact: true })).toBeVisible();
    await expect(page.getByRole("button", { name: "Save alert request", exact: true })).toBeDisabled();
    await attachAxeCapture(page, testInfo, `notifications-loading-${testInfo.project.name}-${theme}`);
    mode = "empty";
    releaseFeatures();
    await expect(page.getByText("No threshold notices yet", { exact: true })).toBeVisible();
    await expect(page.getByText("No alert rules are recorded", { exact: true })).toBeVisible();
    await expect(page.getByText("Opted out", { exact: true })).toBeVisible();
    await attachAxeCapture(page, testInfo, `notifications-empty-${testInfo.project.name}-${theme}`, { screenshot: true });

    mode = "error";
    await page.reload();
    await expect(page.locator("main").getByRole("alert")).toContainText("inbox fixture is unavailable");
    await attachAxeCapture(page, testInfo, `notifications-error-${testInfo.project.name}-${theme}`);

    mode = "unavailable";
    await page.reload();
    await expect(page.getByRole("status").filter({ hasText: "Monitoring is unavailable" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Save alert request", exact: true })).toBeDisabled();
    await attachAxeCapture(page, testInfo, `notifications-unavailable-${testInfo.project.name}-${theme}`, { screenshot: true });
  });

  test(`notification read state requires an explicit revision-checked action in ${theme}`, async ({ page, monitoringApplication }, testInfo) => {
    await page.addInitScript((value) => localStorage.setItem("stock-probs.theme", value), theme);
    await monitoringApplication.signIn(page);
    // The inbox projection is deliberately synthetic because this fixture refuses to attest a
    // simulated provider observation as trusted monitoring evidence.
    const notice = {
      id: "00000000-0000-4000-8000-000000000101",
      kind: "price_alert",
      payload: {
        alert_id: "00000000-0000-4000-8000-000000000102",
        generation: 1,
        symbol: "ACDC",
        currency: "USD",
        threshold: "250",
        direction: "above",
        price: "251.25",
        provider: "fixture projection",
        observed_at: FIXTURE_NOW,
      },
      is_read: false,
      revision: 1,
      created_at: FIXTURE_NOW,
    };
    let isRead = false;
    let revision = 1;
    const updates = [];
    await page.route("**/api/v1/notifications?*", (route) => route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ items: [{ ...notice, is_read: isRead, revision }], next_cursor: null }),
    }));
    await page.route("**/api/v1/notifications/00000000-0000-4000-8000-000000000101/read", async (route) => {
      if (route.request().method() !== "PUT") return route.continue();
      const body = JSON.parse(route.request().postData() || "{}");
      updates.push(body);
      expect(body.expected_revision).toBe(revision);
      isRead = body.is_read === true;
      revision += 1;
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ ...notice, is_read: isRead, revision }),
      });
    });
    await page.goto(`${monitoringApplication.url}/notifications`);
    const card = page.locator("main article").filter({ hasText: "ACDC" });
    await expect(card.getByText("Unread", { exact: true })).toBeVisible();
    const markRead = card.getByRole("button", { name: "Mark read", exact: true });
    await markRead.focus();
    await page.keyboard.press("Enter");
    await expect(card.getByText("Read", { exact: true })).toBeVisible();
    await expect(card.getByRole("button", { name: "Mark unread", exact: true })).toBeVisible();
    expect(updates).toEqual([{ expected_revision: 1, is_read: true }]);
    const audit = await (await page.request.get(`${monitoringApplication.url}/__qa/monitoring-provider-audit`)).json();
    expect(audit.items, "reading a saved notice is explicit UI state, not a provider operation").toEqual([]);
    await attachAxeCapture(page, testInfo, `notification-read-${testInfo.project.name}-${theme}`, { screenshot: true });
  });

  test(`report card recomputes bounded page denominators, ties, filters, and five-minute provenance in ${theme}`, async ({ page, monitoringApplication }, testInfo) => {
    await page.addInitScript((value) => localStorage.setItem("stock-probs.theme", value), theme);
    await monitoringApplication.signIn(page);
    const report = populatedReport();
    await reportRoute(page, { body: report });
    await page.goto(`${monitoringApplication.url}/research/report-card`);
    const initialAudit = await (await page.request.get(`${monitoringApplication.url}/__qa/monitoring-provider-audit`)).json();
    expect(initialAudit.items, "opening the report page must not start a provider operation").toEqual([]);
    await expect(page.locator("html")).toHaveAttribute("data-theme", theme);
    await expect(page.getByRole("heading", { name: "Report card", exact: true })).toBeVisible();
    await expect(page.getByText("Metrics and filters describe the 28 saved forecasts on page 1, out of 128 matching records. Other pages are excluded from these denominators.", { exact: true })).toBeVisible();
    await expect(page.getByText("Recorded outcomes · not a backtest", { exact: true })).toBeVisible();
    await expect(page.getByText(/Daily-or-longer outcomes can be scored automatically/)).toBeVisible();
    await expect(page.getByText(/Five-minute rows require supported saved evidence/)).toBeVisible();
    await expect(page.getByText("3 malformed or duplicate result rows were omitted before calculating filters, charts, and denominators.", { exact: true })).toBeVisible();
    await expect(page.getByText("24", { exact: true }).first()).toBeVisible();
    const metrics = page.locator('[aria-label="Selected report metrics"]');
    await expect(metrics).toContainText("Forecasts in scope");
    await expect(metrics).toContainText("24");
    await expect(metrics).toContainText("19 correct / 19 scored direction comparisons");
    await expect(metrics.locator("article").nth(2).locator("strong")).toHaveText("100.0%");
    await expect(metrics).toContainText("19 covered / 20 scored comparable intervals");
    await expect(page.locator('[aria-label="Outcome states in selected scope"]')).toContainText("Pending");
    await expect(page.locator('[aria-label="Outcome states in selected scope"]')).toContainText("Unavailable");
    await expect(page.getByText("No unique direction prediction", { exact: true })).toBeVisible();
    await expect(page.getByRole("img", { name: /Predicted interval and observed return plot/ })).toBeVisible();
    const outcomes = page.getByRole("table", { name: /Metric denominators are recomputed/ });
    await expect(outcomes.locator("tbody tr")).toHaveCount(20);
    await page.getByRole("navigation", { name: "Outcome pages" }).getByRole("button", { name: "Next", exact: true }).click();
    await expect(outcomes.locator("tbody tr")).toHaveCount(4);
    await expect(page.getByRole("navigation", { name: "Outcome pages" })).toContainText("Page 2 of 2");
    const pageTwoReasons = await outcomes.locator("tbody tr td:nth-child(3) small").allTextContents();
    await page.getByRole("navigation", { name: "Outcome pages" }).getByRole("button", { name: "Previous", exact: true }).click();
    const pageOneReasons = await outcomes.locator("tbody tr td:nth-child(3) small").allTextContents();
    const allReasons = [...pageOneReasons, ...pageTwoReasons];
    expect(allReasons).toHaveLength(24);
    expect(new Set(allReasons).size).toBe(24);
    await page.getByText("Read plotted values as text", { exact: true }).click();
    await expect(page.locator("figure ol li")).toHaveCount(20);
    await attachAxeCapture(page, testInfo, `report-card-${testInfo.project.name}-${theme}`, { screenshot: true });

    const modelHorizon = page.getByLabel("Model and horizon", { exact: true });
    await modelHorizon.selectOption({ label: "fixture-model-2 · 5-minute forward" });
    await expect(metrics).toContainText("1 scored / 1 rows in this scope");
    await expect(page.getByText("0 provider-bar rows · 1 manual reviews", { exact: true })).toBeVisible();
    await expect(page.getByText("Fixture five-minute manual review", { exact: true })).toBeVisible();

    await modelHorizon.selectOption({ label: "fixture-model-1 · Weekly · 5 sessions" });
    await page.getByLabel("Symbol", { exact: true }).selectOption("SPY");
    await page.getByLabel("Period", { exact: true }).selectOption("7");
    await page.getByLabel("Target from (UTC)", { exact: true }).fill("2025-01-09");
    await page.getByLabel("Target through (UTC)", { exact: true }).fill("2025-01-09");
    await expect(metrics.locator("article").first()).toContainText("2");
    await expect(metrics).toContainText("1 correct / 1 scored direction comparisons");
    await expect(metrics).toContainText("1 covered / 1 scored comparable intervals");
    await expect(page.getByText("No rows match the selected model, horizon, symbol, and target-date filters.", { exact: true })).toHaveCount(0);
    const focusedFilter = page.getByLabel("Symbol", { exact: true });
    await focusedFilter.focus();
    await page.keyboard.press("ArrowDown");
    const focusEvidence = await focusedFilter.evaluate((node) => ({ active: document.activeElement === node, outline: getComputedStyle(node).outlineStyle }));
    expect(focusEvidence.active).toBe(true);
    expect(focusEvidence.outline).not.toBe("none");
    await attachAxeCapture(page, testInfo, `report-card-filtered-${testInfo.project.name}-${theme}`);
  });

  test(`report card loading, empty, error, malformed, and unavailable states in ${theme}`, async ({ page, browserDiagnostics, monitoringApplication }, testInfo) => {
    browserDiagnostics.expectHttpFailures({ method: "GET", path: "/api/v1/report-cards", status: 500 });
    await page.addInitScript((value) => localStorage.setItem("stock-probs.theme", value), theme);
    await monitoringApplication.signIn(page);
    let mode = "loading";
    let release;
    const gate = new Promise((resolve) => { release = resolve; });
    await page.route("**/api/v1/report-cards?*", async (route) => {
      if (mode === "loading") await gate;
      if (mode === "error") return route.fulfill({ status: 500, contentType: "application/json", body: JSON.stringify({ error: { code: "fixture_report_error", message: "The report fixture is unavailable." } }) });
      if (mode === "malformed") return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ ...emptyReport(), items: null }) });
      return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(emptyReport()) });
    });
    await page.goto(`${monitoringApplication.url}/research/report-card`);
    await expect(page.getByText("Loading report data…", { exact: true })).toBeVisible();
    await attachAxeCapture(page, testInfo, `report-loading-${testInfo.project.name}-${theme}`);
    mode = "empty";
    release();
    await expect(page.getByText("No recorded outcomes to score", { exact: true })).toBeVisible();
    await expect(page.getByText("Metrics appear only after an owner-scoped forecast has a published, comparable outcome.", { exact: true })).toBeVisible();
    await attachAxeCapture(page, testInfo, `report-empty-${testInfo.project.name}-${theme}`, { screenshot: true });

    mode = "error";
    await page.getByRole("button", { name: "Refresh report", exact: true }).click();
    await expect(page.locator("main").getByRole("alert")).toContainText("report fixture is unavailable");
    await expect(page.getByRole("button", { name: "Retry report", exact: true })).toBeVisible();
    await attachAxeCapture(page, testInfo, `report-error-${testInfo.project.name}-${theme}`);

    mode = "empty";
    await page.getByRole("button", { name: "Retry report", exact: true }).click();
    await expect(page.getByText("No recorded outcomes to score", { exact: true })).toBeVisible();
    mode = "malformed";
    await page.reload();
    await expect(page.locator("main").getByRole("alert")).toContainText("bounded report response is unavailable");
    await expect(page.getByText("Report data is unavailable. No performance values are being inferred.", { exact: true })).toBeVisible();
    await expect(page.getByText("No recorded outcomes to score", { exact: true })).toHaveCount(0);
    await attachAxeCapture(page, testInfo, `report-malformed-${testInfo.project.name}-${theme}`);

    await page.route("**/api/v1/monitoring/features", (route) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(featurePayload({ enabled: false, can_arm: false })) }));
    await page.reload();
    await expect(page.getByText("The outcome service is unavailable. Previously loaded values may be stale.", { exact: true })).toBeVisible();
    await expect(page.getByText("Report data is unavailable. No performance values are being inferred.", { exact: true })).toBeVisible();
    await attachAxeCapture(page, testInfo, `report-unavailable-${testInfo.project.name}-${theme}`, { screenshot: true });
  });
}
