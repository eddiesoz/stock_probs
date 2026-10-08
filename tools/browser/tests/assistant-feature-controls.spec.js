const { readFileSync } = require("node:fs");
const path = require("node:path");
const { test, expect } = require("./fixtures");

const catalog = JSON.parse(readFileSync(path.resolve(__dirname, "../../../src/stock_probs/assistant/assistant_catalog.json"), "utf8"));
const zenPolicy = catalog.zen;
const eligibleZenModel = Object.entries(zenPolicy.reviewed_models)
  .filter(([, candidate]) => candidate.available === true
    && candidate.free === true
    && candidate.training === false
    && candidate.data_collection_allowed === false
    && candidate.data_collection_default === false
    && candidate.route === "openai-compatible")
  .sort(([left], [right]) => left.localeCompare(right))[0];
if (!eligibleZenModel) throw new Error("The maintained catalog has no eligible synthetic browser model.");
const [zenModelKey, zenFreeModel] = eligibleZenModel;
const zenModelId = `${zenPolicy.provider_id}/${zenModelKey}`;
const zenPrivacyPolicyVersion = zenFreeModel.privacy_policy_version ?? zenPolicy.privacy_policy_version;
const zenBillingPolicyVersion = zenFreeModel.billing_policy_version ?? zenPolicy.billing_policy_version;
const contextVersion = "assistant-feature-controls-context-v1";
let nextFeatureActionId = 0;
const instrument = {
  symbol: "ACDC",
  asset_type: "stock",
  provider: "fixture",
  exchange: "NMS",
  display_name: "Acme Industries",
};
const assistantStatus = {
  available: true,
  enabled: true,
  worker: { status: "ready" },
  limits: { active_per_user: 1, active_global: 2, tools_per_turn: 8, turn_seconds: 120 },
  storage: { user_bytes: 0, user_limit: 2_097_152, global_bytes: 0, global_limit: 25_165_824, database_bytes: 0, database_limit: 50_331_648 },
};
const assistantModel = {
  id: zenModelId,
  model_id: zenModelId,
  provider: zenPolicy.provider_id,
  provider_id: zenPolicy.provider_id,
  native_provider_id: zenPolicy.provider_id,
  name: `Synthetic feature QA / ${zenFreeModel.display_name}`,
  availability: "available",
  available: true,
  enabled: true,
  usable: true,
  free: true,
  training: "no_training",
  training_uses_data: false,
  terms_url: zenPolicy.terms_url,
  terms_reviewed_at: zenPolicy.terms_reviewed_at,
  policy_version: zenPolicy.policy_version,
  disclosure: "Synthetic browser regression fixture; no model request leaves the local app.",
  privacy_policy_version: zenPrivacyPolicyVersion,
  privacy_disclosure: "Synthetic browser regression fixture; no model request leaves the local app.",
  billing_class: "free",
  billing_policy_version: zenBillingPolicyVersion,
  cost_disclosure: zenFreeModel.disclosure,
  revision: 1,
  availability_reason: null,
  consent: { accepted: true, data_collection_opt_in: false, accepted_at: "2025-01-01T00:00:00Z" },
};
const conversationId = "feature-controls-conversation";
const expiresAt = "2099-01-01T00:00:00Z";
const csrfToken = "browser-feature-controls-fixture-csrf";

function actionScenario({ actionType, payload, result, title = "Review the requested workspace change", summary = "Synthetic application-provided preview.", onConfirm }) {
  return {
    actionType,
    payload,
    result,
    title,
    summary,
    onConfirm,
    actionId: `feature-action-${actionType.replaceAll(".", "-")}-${++nextFeatureActionId}`,
    confirmationPhrase: `CONFIRM ${actionType.replaceAll(".", "-").toUpperCase()}`,
  };
}

function assistantContext(route) {
  return {
    route,
    instrument: ["/tools/markets", "/tools/live-trading"].includes(route) ? instrument : null,
    event_ref: null,
    result_ref: null,
    context_version: contextVersion,
  };
}

function conversationSummary() {
  return {
    id: conversationId,
    title: "Feature controls browser test",
    revision: 1,
    created_at: "2025-01-10T17:00:00Z",
    updated_at: "2025-01-10T17:00:00Z",
    last_message_preview: null,
  };
}

function proposalFor(scenario) {
  return {
    title: scenario.title,
    summary: scenario.summary,
    changes: [{ label: "Synthetic preview", after: "Review before applying" }],
    action_version: 1,
    context_version: contextVersion,
    confirmation_phrase: scenario.confirmationPhrase,
  };
}

function actionRecord(scenario, state) {
  const result = state.confirmed.get(scenario.actionId);
  return {
    action_id: scenario.actionId,
    action_type: scenario.actionType,
    status: result?.status ?? "pending",
    expires_at: expiresAt,
    availability: result ? "unavailable" : "confirmable",
    proposal: proposalFor(scenario),
    receipt: result ? {
      receipt_id: `receipt-${scenario.actionId}`,
      outcome: result.status,
      message: result.message,
      destination: result.destination ?? null,
      browser_action: result.browser_action,
    } : null,
  };
}

function conversationDetail(state) {
  const messages = state.started.map((scenario, index) => ([
    {
      id: `feature-user-${index + 1}`,
      turn_id: `turn-${index + 1}`,
      seq: 1,
      role: "user",
      text: scenario.prompt,
      created_at: "2025-01-10T17:01:00Z",
      sources: [],
    },
    {
      id: `feature-assistant-${index + 1}`,
      turn_id: `turn-${index + 1}`,
      seq: 2,
      role: "assistant",
      text: "Synthetic application preview ready.",
      created_at: "2025-01-10T17:02:00Z",
      sources: [],
    },
  ])).flat();
  return {
    conversation: { ...conversationSummary(), delete_confirmation_phrase: "DELETE feature-controls" },
    messages: { items: messages, page: 1, page_size: 50, total: messages.length },
    turns: state.started.map((scenario, index) => ({
      id: `turn-${index + 1}`,
      status: "completed",
      model_id: assistantModel.id,
      policy_version: assistantModel.policy_version,
      context_version: contextVersion,
      context: scenario.turnContext,
      created_at: "2025-01-10T17:01:00Z",
      completed_at: "2025-01-10T17:02:00Z",
      actions: [],
    })),
    actions: state.started.map((scenario) => actionRecord(scenario, state)),
    events: { items: [], page: 1, page_size: 100, total: 0 },
    action_pagination: { page: 1, page_size: 100, total: state.started.length },
  };
}

function eventStream(scenario) {
  const events = [
    [1, "meta", { model_id: assistantModel.id, policy_version: assistantModel.policy_version, context_version: contextVersion }],
    [2, "token", { text: "Synthetic application preview ready." }],
    [3, "proposed_action", {
      action_id: scenario.actionId,
      action_type: scenario.actionType,
      title: scenario.title,
      summary: scenario.summary,
      changes: [{ label: "Synthetic preview", before: "Current local state", after: "Confirmed change" }],
      version: 1,
      expires_at: expiresAt,
      confirmation_phrase: scenario.confirmationPhrase,
      context_version: contextVersion,
    }],
    [4, "complete", { status: "completed", assistant_message_id: `feature-assistant-${scenario.turnNumber}` }],
  ];
  return events.map(([id, name, data]) => `id: ${id}\nevent: ${name}\ndata: ${JSON.stringify(data)}\n\n`).join("");
}

function quote(symbol, displayName, exchange = "NMS", assetType = "stock") {
  return {
    symbol,
    display_name: displayName,
    asset_type: assetType,
    provider: "fixture",
    exchange,
    last: 10.25,
    price: 10.25,
    currency: "USD",
    change_percent: -1.5,
    volume: 500,
    open: 10.5,
    high: 11,
    low: 9,
    previous_close: 10.5,
    last_trade: 10.25,
    state: "available",
    source: "deterministic browser fixture",
    as_of: "2025-01-10T17:00:00Z",
    delayed: false,
    delay_minutes: 0,
    sparkline: [9, 9.5, 10.25],
  };
}

async function installFeatureHarness(page, { route = "/", scenarios = [], markets = false, savedForecast = null, browserDiagnostics = null } = {}) {
  const state = {
    created: false,
    started: [],
    currentScenario: null,
    confirmed: new Map(),
    confirmationRequests: [],
    assistantRequests: [],
    assistantStatus: { ...assistantStatus },
    savedForecastRequests: [],
    forecastRequests: [],
    historyRequests: [],
    exportRequests: [],
    marketRequests: { watchlist: [], quotes: [], bars: [] },
    watchlist: [instrument],
  };
  if (markets) state.watchlist.push({ ...instrument, symbol: "MSFT", display_name: "Maple Systems" });
  page.on("request", (request) => {
    const url = new URL(request.url());
    if (url.pathname === "/api/v1/forecasts" || /\/api\/v1\/history\/\d+\/reconstructions$/.test(url.pathname)) {
      state.forecastRequests.push({ method: request.method(), path: url.pathname });
    }
  });

  await page.route("**/api/v1/auth/session", (requestRoute) => requestRoute.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify({ authenticated: true, user: { id: 1, role: "admin" }, csrf_token: csrfToken }),
  }));
  await page.route("**/api/v1/readiness", (requestRoute) => requestRoute.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify({ ready: true, provider: "fixture" }),
  }));
  await page.route("**/api/v1/operations/backups/status", (requestRoute) => requestRoute.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify({ status: "ready" }),
  }));
  await page.route("**/api/v1/history**", async (requestRoute) => {
    const request = requestRoute.request();
    const url = new URL(request.url());
    if (url.pathname === "/api/v1/history-export.csv" || url.pathname === "/api/v1/history-export.json") {
      state.exportRequests.push({ path: url.pathname, query: Object.fromEntries(url.searchParams), url: `${url.pathname}${url.search}` });
      const csv = url.pathname.endsWith(".csv");
      return requestRoute.fulfill({
        status: 200,
        contentType: csv ? "text/csv; charset=utf-8" : "application/json; charset=utf-8",
        headers: { "Content-Disposition": `attachment; filename=history.${csv ? "csv" : "json"}` },
        body: csv ? "event_id,symbol\n1,ACDC\n" : JSON.stringify({ items: [{ event_id: 1, symbol: "ACDC" }] }),
      });
    }
    if (url.pathname === "/api/v1/history") {
      state.historyRequests.push(Object.fromEntries(url.searchParams));
      return requestRoute.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ items: [], page: Number(url.searchParams.get("page") || 1), page_size: Number(url.searchParams.get("page_size") || 10), total: 0 }),
      });
    }
    return requestRoute.fulfill({ status: 404, contentType: "application/json", body: JSON.stringify({ error: { code: "fixture_missing" } }) });
  });

  if (savedForecast) {
    await page.route("**/api/v1/saved-forecasts/*", async (requestRoute) => {
      const request = requestRoute.request();
      const url = new URL(request.url());
      state.savedForecastRequests.push({ method: request.method(), path: url.pathname });
      if (request.method() === "GET" && url.pathname === `/api/v1/saved-forecasts/${savedForecast.event.id}`) {
        return requestRoute.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(savedForecast) });
      }
      return requestRoute.fulfill({ status: 404, contentType: "application/json", body: JSON.stringify({ error: { code: "fixture_saved_event_missing" } }) });
    });
  }

  if (markets) {
    await page.route("**/api/v1/lists**", async (requestRoute) => {
      const request = requestRoute.request();
      const url = new URL(request.url());
      if (request.method() === "GET" && url.searchParams.get("kind") === "watchlist") {
        state.marketRequests.watchlist.push(url.search);
        return requestRoute.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ items: state.watchlist }) });
      }
      if (request.method() === "GET" && url.searchParams.get("kind") === "portfolio") {
        return requestRoute.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ items: [] }) });
      }
      return requestRoute.fulfill({ status: 405, contentType: "application/json", body: JSON.stringify({ error: { code: "fixture_method_not_supported" } }) });
    });
    await page.route("**/api/v1/quotes**", async (requestRoute) => {
      const url = new URL(requestRoute.request().url());
      state.marketRequests.quotes.push(url.searchParams.get("symbols") || "");
      const symbols = (url.searchParams.get("symbols") || "").split(",").filter(Boolean);
      const available = [...state.watchlist, instrument];
      const items = [...new Map(available.map((item) => [item.symbol, quote(item.symbol, item.display_name, item.exchange, item.asset_type)])).values()]
        .filter((item) => symbols.includes(item.symbol));
      return requestRoute.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ items }) });
    });
    await page.route("**/api/v1/bars**", async (requestRoute) => {
      const url = new URL(requestRoute.request().url());
      state.marketRequests.bars.push({ symbol: url.searchParams.get("symbol"), asset_type: url.searchParams.get("asset_type"), range: url.searchParams.get("range") });
      return requestRoute.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          bars: [
            { timestamp: "2025-01-09T00:00:00Z", close: 9.5, high: 10, low: 9 },
            { timestamp: "2025-01-10T00:00:00Z", close: 10.25, high: 11, low: 10 },
          ],
          source: "deterministic browser fixture",
          provider: "fixture",
          range: url.searchParams.get("range"),
          interval: "1d",
          as_of: "2025-01-10T17:00:00Z",
          state: "available",
          delayed: false,
          delay_minutes: 0,
        }),
      });
    });
  }

  await page.route("**/api/v1/assistant/**", async (requestRoute) => {
    const request = requestRoute.request();
    const url = new URL(request.url());
    const pathname = url.pathname;
    state.assistantRequests.push({ method: request.method(), path: pathname, body: request.postData() || "" });
    if (pathname === "/api/v1/assistant/status") {
      return requestRoute.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(state.assistantStatus) });
    }
    if (pathname === "/api/v1/assistant/models") {
      return requestRoute.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ items: [assistantModel] }) });
    }
    if (pathname === "/api/v1/assistant/context") {
      const requestedRoute = url.searchParams.get("route") || "/";
      return requestRoute.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          context: assistantContext(requestedRoute),
          preview: { summary: requestedRoute === route ? "Current fixture route" : "Current application route", fields: ["route", "selected instrument"], note: "Synthetic local browser context." },
        }),
      });
    }
    if (pathname === "/api/v1/assistant/conversations" && request.method() === "GET") {
      return requestRoute.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ items: state.created ? [conversationSummary()] : [], page: 1, page_size: 20, total: state.created ? 1 : 0 }),
      });
    }
    if (pathname === "/api/v1/assistant/conversations" && request.method() === "POST") {
      state.created = true;
      return requestRoute.fulfill({ status: 201, contentType: "application/json", body: JSON.stringify(conversationSummary()) });
    }
    if (pathname === `/api/v1/assistant/conversations/${conversationId}/turns` && request.method() === "POST") {
      const body = request.postDataJSON();
      const scenario = scenarios[state.started.length];
      if (!scenario) return requestRoute.fulfill({ status: 409, contentType: "application/json", body: JSON.stringify({ error: { code: "fixture_scenario_missing" } }) });
      scenario.prompt = body.prompt;
      scenario.turnNumber = state.started.length + 1;
      scenario.turnContext = body.context;
      state.started.push(scenario);
      state.currentScenario = scenario;
      return requestRoute.fulfill({ status: 202, contentType: "application/json", body: JSON.stringify({ turn: { id: `turn-${scenario.turnNumber}`, status: "running" } }) });
    }
    const eventMatch = pathname.match(new RegExp(`^/api/v1/assistant/conversations/${conversationId}/turns/turn-(\\d+)/events$`));
    if (eventMatch && request.method() === "GET") {
      const scenario = state.started[Number(eventMatch[1]) - 1];
      if (!scenario) return requestRoute.fulfill({ status: 404, contentType: "application/json", body: JSON.stringify({ error: { code: "fixture_turn_missing" } }) });
      browserDiagnostics?.expectCompletedAssistantEventStream({ path: pathname });
      return requestRoute.fulfill({
        status: 200,
        contentType: "text/event-stream; charset=utf-8",
        headers: { "Cache-Control": "no-store" },
        body: eventStream(scenario),
      });
    }
    const confirmMatch = pathname.match(new RegExp(`^/api/v1/assistant/conversations/${conversationId}/actions/([^/]+)/confirm$`));
    if (confirmMatch && request.method() === "POST") {
      const scenario = state.started.find((item) => item.actionId === confirmMatch[1]);
      if (!scenario) return requestRoute.fulfill({ status: 404, contentType: "application/json", body: JSON.stringify({ error: { code: "fixture_action_missing" } }) });
      const body = request.postDataJSON();
      state.confirmationRequests.push({ actionType: scenario.actionType, body });
      if (typeof scenario.onConfirm === "function") scenario.onConfirm(state);
      state.confirmed.set(scenario.actionId, scenario.result);
      return requestRoute.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ action_id: scenario.actionId, receipt_id: `receipt-${scenario.actionId}`, ...scenario.result }) });
    }
    if (pathname === `/api/v1/assistant/conversations/${conversationId}` && request.method() === "GET") {
      return requestRoute.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(conversationDetail(state)) });
    }
    return requestRoute.fulfill({ status: 404, contentType: "application/json", body: JSON.stringify({ error: { code: "fixture_missing", message: "No feature-controls assistant fixture route." } }) });
  });
  return state;
}

async function openAssistant(page, url) {
  await page.goto(url);
  const launcher = page.getByRole("button", { name: "Open Ledger assistant" });
  await expect(launcher).toBeVisible();
  await launcher.click();
  const panel = page.getByTestId("assistant-panel");
  await expect(panel).toBeVisible();
  const modelSelector = panel.getByRole("combobox", { name: "Assistant model" });
  if (await modelSelector.inputValue() !== assistantModel.id) await modelSelector.selectOption(assistantModel.id);
  await expect(panel.getByRole("textbox", { name: "Ask about this page" })).toBeVisible();
  return panel;
}

async function requestAndConfirm(page, panel, prompt, expectedOutcome, confirmationButton = "Confirm change", beforeConfirm = null) {
  await panel.getByRole("textbox", { name: "Ask about this page" }).fill(prompt);
  await panel.getByRole("button", { name: "Send question" }).click();
  const card = panel.locator('[aria-label^="Preview:"]').last();
  await expect(card).toBeVisible();
  const phrase = card.locator("input");
  await expect(phrase).toHaveValue("");
  const confirmationPhrase = await card.locator("code").textContent();
  await phrase.fill(confirmationPhrase);
  if (beforeConfirm) await beforeConfirm({ card, page, panel });
  const [confirmation] = await Promise.all([
    page.waitForResponse((response) => response.request().method() === "POST" && response.url().includes("/actions/") && response.url().endsWith("/confirm")),
    card.getByRole("button", { name: confirmationButton }).click(),
  ]);
  expect(confirmation.status()).toBe(200);
  if (expectedOutcome) {
    const receipts = panel.getByRole("region", { name: "Confirmed action receipts" });
    await expect(receipts).toBeVisible();
    await expect(receipts).toContainText(expectedOutcome);
  }
}

async function closeAssistant(panel, page) {
  await panel.getByRole("button", { name: "Close assistant" }).click();
  await expect(page.getByRole("button", { name: "Open Ledger assistant" })).toBeFocused();
  await expect(page.locator("[data-assistant-background]")).toHaveJSProperty("inert", false);
}

async function reopenAssistant(page, { resumeConversation = false } = {}) {
  await page.getByRole("button", { name: "Open Ledger assistant" }).click();
  const panel = page.getByTestId("assistant-panel");
  await expect(panel).toBeVisible();
  const modelSelector = panel.getByRole("combobox", { name: "Assistant model" });
  if (await modelSelector.inputValue() !== assistantModel.id) await modelSelector.selectOption(assistantModel.id);
  await expect(panel.getByRole("textbox", { name: "Ask about this page" })).toBeVisible();
  if (resumeConversation) {
    await panel.getByRole("button", { name: "Open conversation history" }).click();
    const conversation = panel.getByRole("button", { name: /Feature controls browser test/ });
    await expect(conversation).toBeVisible();
    await conversation.click();
    await expect(panel.getByText("Synthetic application preview ready.", { exact: true }).first()).toBeVisible();
  }
  return panel;
}

async function confirmLocalControlHandoff({ page, panel, testInfo, prompt, expectedOutcome, headingId, previewText, receiptText, desktopStatusText, beforeConfirm = null }) {
  const mobileHandoff = testInfo.project.name === "mobile-chromium";
  await requestAndConfirm(page, panel, prompt, mobileHandoff ? undefined : expectedOutcome, "Open local controls", async ({ card }) => {
    await expect(card).toContainText(previewText);
    if (beforeConfirm) await beforeConfirm({ page, card, panel });
  });
  if (mobileHandoff) {
    await expect(panel).toBeHidden();
    await expect(page.getByTestId("assistant-panel")).toHaveCount(0);
    await expect(page.locator("[data-assistant-background]")).toHaveJSProperty("inert", false);
    await expect(page.locator("[data-assistant-background]")).not.toHaveAttribute("data-assistant-mobile-modal-underlay");
    await expect(page.locator("body")).not.toHaveAttribute("data-assistant-open", "true");
    await expect(page.locator(`#${headingId}`)).toBeFocused();
    const focusAttempt = await page.evaluate((targetId) => {
      const attempts = window.__assistantHandoffFocusProbe?.focusAttempts ?? [];
      return attempts.filter((attempt) => attempt.targetId === targetId).at(-1) ?? null;
    }, headingId);
    expect(focusAttempt).toMatchObject({
      targetId: headingId,
      backgroundInert: false,
      underlay: null,
      assistantOpen: false,
      panelMounted: false,
    });
    panel = await reopenAssistant(page, { resumeConversation: true });
  } else {
    await expect(page.locator(`#${headingId}`)).toBeFocused();
    if (desktopStatusText) await expect(panel.locator('[aria-live="polite"]')).toHaveText(desktopStatusText);
  }
  await expect(panel.getByRole("region", { name: "Confirmed action receipts" })).toContainText(receiptText);
  return panel;
}

function historyDestination(payload) {
  const params = new URLSearchParams();
  if (payload.query.trim()) params.set("q", payload.query.trim());
  for (const key of ["asset_type", "status", "analysis_kind", "submitted_from", "submitted_to", "model", "horizon", "sort"]) {
    if (payload[key]) params.set(key, payload[key]);
  }
  if (payload.page_size) params.set("page_size", String(payload.page_size));
  const query = params.toString();
  return `${query ? `/?${query}` : "/"}#history-heading`;
}

function exportDestination(format) {
  const params = new URLSearchParams([
    ["q", "ACDC"],
    ["symbol", "ACDC"],
    ["status", "successful"],
    ["asset_type", "stock"],
    ["analysis_kind", "submitted_forecast"],
    ["submitted_from", "2025-01-01T00:00:00Z"],
    ["submitted_to", "2025-01-10T23:59:59.999Z"],
    ["model", "fixture-model"],
    ["horizon", "weekly_5"],
    ["sort_by", "symbol"],
    ["sort_order", "asc"],
  ]);
  return { path: `/api/v1/history-export.${format}`, url: `/api/v1/history-export.${format}?${params.toString()}` };
}

function marketDestination() {
  const params = new URLSearchParams({
    symbol: instrument.symbol,
    asset_type: instrument.asset_type,
    provider: instrument.provider,
    exchange: instrument.exchange,
  });
  return `/tools/markets?${params.toString()}`;
}

function chartRangePayload(symbol, range) {
  return {
    symbol,
    asset_type: instrument.asset_type,
    provider: instrument.provider,
    exchange: instrument.exchange,
    range,
  };
}

test("assistant history filter confirmation applies all bounded form fields and preserves independent defaults", async ({ page, applicationRequests }) => {
  const filters = {
    query: "ACDC",
    asset_type: "etf",
    status: "failed",
    analysis_kind: "fresh_historical_reconstruction",
    submitted_from: "2025-01-01",
    submitted_to: "2025-01-31",
    model: "fixture-model",
    horizon: "weekly_5",
    sort: "company:asc",
    page_size: 50,
  };
  const state = await installFeatureHarness(page, {
    route: "/",
    scenarios: [actionScenario({
      actionType: "filters.apply",
      payload: filters,
      title: "Apply the selected research filters",
      result: {
        status: "handed_off",
        message: "The approved filters are ready in the ledger form.",
        destination: historyDestination(filters),
        browser_action: { type: "filters.apply", payload: filters, destination: { kind: "current-page", route: "/" } },
      },
    })],
  });
  const panel = await openAssistant(page, "/");
  await panel.getByRole("textbox", { name: "Ask about this page" }).fill("Apply the selected ledger filters.");
  await panel.getByRole("button", { name: "Send question" }).click();
  const card = panel.locator('[aria-label^="Preview:"]').last();
  await expect(card).toBeVisible();
  const phrase = await card.locator("code").textContent();
  await card.locator("input").fill(phrase);
  const confirmationResponse = page.waitForResponse((response) => response.request().method() === "POST" && response.url().endsWith("/confirm"));
  const navigation = page.waitForURL((url) => url.pathname === "/" && url.hash === "#history-heading");
  await card.getByRole("button", { name: "Confirm change" }).click();
  const response = await confirmationResponse;
  await navigation;
  expect(response.status()).toBe(200);
  const url = new URL(page.url());
  expect(Object.fromEntries(url.searchParams)).toEqual({
    q: "ACDC",
    asset_type: "etf",
    status: "failed",
    analysis_kind: "fresh_historical_reconstruction",
    submitted_from: "2025-01-01",
    submitted_to: "2025-01-31",
    model: "fixture-model",
    horizon: "weekly_5",
    sort: "company:asc",
    page_size: "50",
  });
  await expect(page.getByLabel("Find symbol or company")).toHaveValue("ACDC");
  await expect(page.getByRole("combobox", { name: "Status", exact: true })).toHaveValue("failed");
  await page.getByText("More filters", { exact: true }).click();
  await expect(page.getByRole("combobox", { name: "Asset type", exact: true })).toHaveValue("etf");
  await expect(page.getByRole("combobox", { name: "Analysis type", exact: true })).toHaveValue("fresh_historical_reconstruction");
  await expect(page.getByLabel("Submitted from", { exact: true })).toHaveValue("2025-01-01");
  await expect(page.getByLabel("Submitted through", { exact: true })).toHaveValue("2025-01-31");
  await expect(page.getByLabel("Model name or version", { exact: true })).toHaveValue("fixture-model");
  await expect(page.getByRole("combobox", { name: "Forecast horizon", exact: true })).toHaveValue("weekly_5");
  await expect(page.getByRole("combobox", { name: "Sort ledger", exact: true })).toHaveValue("company:asc");
  await expect(page.getByRole("combobox", { name: "Rows per page", exact: true })).toHaveValue("50");
  await expect.poll(() => state.historyRequests.at(-1)).toMatchObject({
    q: "ACDC",
    asset_type: "etf",
    status: "failed",
    analysis_kind: "fresh_historical_reconstruction",
    submitted_from: "2025-01-01T00:00:00Z",
    submitted_to: "2025-01-31T23:59:59.999Z",
    model: "fixture-model",
    horizon: "weekly_5",
    sort_by: "company",
    sort_order: "asc",
    page_size: "50",
  });
  expect(state.confirmationRequests[0].body).toMatchObject({
    action_version: 1,
    allow: true,
    confirmation_phrase: "CONFIRM FILTERS-APPLY",
    context: { route: "/", instrument: null, context_version: contextVersion },
  });
  expect(applicationRequests.every((request) => new URL(request).origin === url.origin && new URL(request).pathname.startsWith("/api/v1/"))).toBe(true);
});

test("assistant filter reset handoff renders explicit default sort and page size after mobile dialog closes", async ({ page }) => {
  const filters = {
    query: "",
    asset_type: "",
    status: "",
    analysis_kind: "",
    submitted_from: "",
    submitted_to: "",
    model: "",
    horizon: "",
    sort: "event_id:desc",
    page_size: 10,
  };
  await installFeatureHarness(page, {
    route: "/",
    scenarios: [actionScenario({
      actionType: "filters.apply",
      payload: filters,
      title: "Reset the research filters",
      result: {
        status: "handed_off",
        message: "Default ledger filters are ready.",
        destination: historyDestination(filters),
        browser_action: { type: "filters.apply", payload: filters, destination: { kind: "current-page", route: "/" } },
      },
    })],
  });
  const panel = await openAssistant(page, "/");
  await panel.getByRole("textbox", { name: "Ask about this page" }).fill("Clear the research filters and use their defaults.");
  await panel.getByRole("button", { name: "Send question" }).click();
  const card = panel.locator('[aria-label^="Preview:"]').last();
  await expect(card).toBeVisible();
  await card.locator("input").fill(await card.locator("code").textContent());
  const navigation = page.waitForURL((url) => url.pathname === "/" && url.hash === "#history-heading");
  await card.getByRole("button", { name: "Confirm change" }).click();
  await navigation;
  await expect(page.getByTestId("assistant-panel")).toHaveCount(0);
  await expect(page.locator("[data-assistant-background]")).toHaveJSProperty("inert", false);
  await expect(page.getByLabel("Find symbol or company")).toHaveValue("");
  await expect(page.getByRole("combobox", { name: "Status", exact: true })).toHaveValue("");
  await page.getByText("More filters", { exact: true }).click();
  for (const label of ["Asset type", "Analysis type", "Forecast horizon"]) {
    await expect(page.getByRole("combobox", { name: label, exact: true })).toHaveValue("");
  }
  for (const label of ["Submitted from", "Submitted through", "Model name or version"]) {
    await expect(page.getByLabel(label, { exact: true })).toHaveValue("");
  }
  await expect(page.getByRole("combobox", { name: "Sort ledger", exact: true })).toHaveValue("event_id:desc");
  await expect(page.getByRole("combobox", { name: "Rows per page", exact: true })).toHaveValue("10");
  const url = new URL(page.url());
  expect(Object.fromEntries(url.searchParams)).toEqual({ sort: "event_id:desc", page_size: "10" });
});

for (const format of ["csv", "json"]) {
  test(`assistant-confirmed filtered ${format.toUpperCase()} export downloads the exact approved query`, async ({ page, applicationRequests, browserDiagnostics }) => {
    const destination = exportDestination(format);
    browserDiagnostics.expectRequestAborts({ method: "GET", path: destination.path });
    const state = await installFeatureHarness(page, {
      route: "/",
      scenarios: [actionScenario({
        actionType: `history.export.${format}`,
        title: `Download the filtered ${format.toUpperCase()} export`,
        result: {
          status: "handed_off",
          message: `The approved filtered ${format.toUpperCase()} export is ready.`,
          destination: destination.url,
        },
      })],
    });
    const panel = await openAssistant(page, "/");
    await panel.getByRole("textbox", { name: "Ask about this page" }).fill(`Prepare the filtered ${format.toUpperCase()} history export.`);
    await panel.getByRole("button", { name: "Send question" }).click();
    const card = panel.locator('[aria-label^="Preview:"]').last();
    await expect(card).toBeVisible();
    await card.locator("input").fill(await card.locator("code").textContent());
    const [download] = await Promise.all([
      page.waitForEvent("download"),
      card.getByRole("button", { name: "Confirm change" }).click(),
    ]);
    expect(download.suggestedFilename()).toBe(`history.${format}`);
    await expect.poll(() => state.exportRequests).toHaveLength(1);
    expect(state.exportRequests[0].path).toBe(destination.path);
    expect(state.exportRequests[0].url).toBe(destination.url);
    expect(state.exportRequests[0].query).toMatchObject({
      q: "ACDC",
      symbol: "ACDC",
      status: "successful",
      asset_type: "stock",
      analysis_kind: "submitted_forecast",
      submitted_from: "2025-01-01T00:00:00Z",
      submitted_to: "2025-01-10T23:59:59.999Z",
      model: "fixture-model",
      horizon: "weekly_5",
      sort_by: "symbol",
      sort_order: "asc",
    });
    const receipt = panel.getByRole("region", { name: "Confirmed action receipts" });
    await expect(receipt).toContainText(`Download ${format.toUpperCase()} history · handed off`);
    const localApiRequests = applicationRequests.map((request) => new URL(request));
    expect(localApiRequests.every((request) => request.origin === new URL(page.url()).origin && request.pathname.startsWith("/api/v1/"))).toBe(true);
  });
}

test("confirmed Markets filters, column visibility, and chart range update page controls for the exact selected instrument", async ({ page, browserDiagnostics }) => {
  const marketFilters = {
    query: "Acme",
    exchange: "NMS",
    asset_type: "stock",
    sort: "change:desc",
    min_price: "10",
    max_price: "20",
    min_change: "-5",
    max_change: "3",
    min_volume: "100",
    quote_field: "change_percent",
    quote_min: "-2.5",
    quote_max: "1",
  };
  const scenarios = [
    actionScenario({
      actionType: "market.filters.apply",
      payload: marketFilters,
      title: "Apply the Markets filters",
      result: {
        status: "handed_off",
        message: "Confirmed Markets filters applied for this page.",
        destination: marketDestination(),
        browser_action: { type: "market.filters.apply", payload: marketFilters, destination: { kind: "current-page", route: "/tools/markets" } },
      },
    }),
    actionScenario({
      actionType: "market.columns.set",
      payload: { show_all_columns: true },
      title: "Show all quote columns",
      result: {
        status: "handed_off",
        message: "All quote columns are shown for this page.",
        destination: marketDestination(),
        browser_action: { type: "market.columns.set", payload: { show_all_columns: true }, destination: { kind: "current-page", route: "/tools/markets" } },
      },
    }),
    actionScenario({
      actionType: "market.chart_range.set",
      payload: chartRangePayload(instrument.symbol, "6mo"),
      title: "Set the chart range to six months",
      result: {
        status: "handed_off",
        message: "Confirmed 6mo chart range applied to ACDC.",
        destination: marketDestination(),
        browser_action: { type: "market.chart_range.set", payload: chartRangePayload(instrument.symbol, "6mo"), destination: { kind: "current-page", route: "/tools/markets" } },
      },
    }),
  ];
  const state = await installFeatureHarness(page, { route: "/tools/markets", scenarios, markets: true, browserDiagnostics });
  const initialUrl = `/tools/markets?${new URLSearchParams({ ...instrument }).toString()}`;
  let panel = await openAssistant(page, initialUrl);
  await closeAssistant(panel, page);
  await expect(page.getByRole("heading", { name: /ACDC · Acme Industries/ })).toBeVisible();
  panel = await reopenAssistant(page);
  await requestAndConfirm(page, panel, "Apply these Markets filters.", "Apply Markets filters · handed off");
  await requestAndConfirm(page, panel, "Show every quote column.", "Change quote columns · handed off");
  await requestAndConfirm(page, panel, "Show six months of chart bars for the selected instrument.", "Change chart range · handed off");
  await closeAssistant(panel, page);
  await expect.poll(() => {
    const current = new URL(page.url());
    const expected = new URL(initialUrl, page.url());
    return current.pathname === expected.pathname && current.search === expected.search;
  }).toBe(true);
  await expect(page.getByLabel("Symbol or name")).toHaveValue("Acme");
  await expect(page.getByRole("combobox", { name: "Market / exchange", exact: true })).toHaveValue("NMS");
  await expect(page.getByRole("combobox", { name: "Asset type", exact: true }).last()).toHaveValue("stock");
  await expect(page.getByRole("combobox", { name: "Sort", exact: true })).toHaveValue("change:desc");
  await page.getByText(/More quote filters/).click();
  for (const [label, value] of [
    ["Minimum price", "10"], ["Maximum price", "20"], ["Minimum % change", "-5"],
    ["Maximum % change", "3"], ["Minimum volume", "100"],
    ["Metric minimum", "-2.5"], ["Metric maximum", "1"],
  ]) await expect(page.getByLabel(label, { exact: true })).toHaveValue(value);
  await expect(page.getByRole("combobox", { name: "Additional quote metric", exact: true })).toHaveValue("change_percent");
  await expect(page.getByRole("button", { name: "Summary columns" })).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByRole("combobox", { name: "Chart range", exact: true })).toHaveValue("6mo");
  await expect(page.getByRole("img", { name: "ACDC closing-price chart for 6mo at 1d" })).toBeVisible();
  expect(state.confirmationRequests.map(({ body }) => body.context.instrument)).toEqual([instrument, instrument, instrument]);
  expect(state.marketRequests.bars.at(-1)).toEqual({ symbol: "ACDC", asset_type: "stock", range: "6mo" });
});

test("confirmed Markets refresh actions re-request only their named local data and applied watchlist changes reload the list", async ({ page, browserDiagnostics }) => {
  const refreshScenarios = ["quotes", "watchlist", "chart"].map((kind) => actionScenario({
    actionType: "market.refresh",
    payload: { kind },
    title: `Refresh ${kind}`,
    result: {
      status: "handed_off",
      message: `${kind} refresh requested for the current fixture page.`,
      destination: marketDestination(),
      browser_action: { type: "market.refresh", payload: { kind }, destination: { kind: "current-page", route: "/tools/markets" } },
    },
  }));
  const appliedWatchlist = actionScenario({
    actionType: "watchlist.add",
    payload: { symbol: "TSLA", asset_type: "stock", provider: "fixture", exchange: "NMS" },
    title: "Add TSLA to the watchlist",
    result: { status: "applied", message: "The instrument was saved to the local watchlist." },
    summary: "Add the approved instrument to this account's saved watchlist.",
    onConfirm(state) {
      state.watchlist = [...state.watchlist, { symbol: "TSLA", display_name: "Tesla Fixture", asset_type: "stock", provider: "fixture", exchange: "NMS" }];
    },
  });
  const state = await installFeatureHarness(page, { route: "/tools/markets", scenarios: [...refreshScenarios, appliedWatchlist], markets: true, browserDiagnostics });
  const panel = await openAssistant(page, `/tools/markets?${new URLSearchParams(instrument).toString()}`);
  await page.waitForLoadState("networkidle");
  for (const [kind, requestKey] of [["quotes", "quotes"], ["watchlist", "watchlist"], ["chart", "bars"]]) {
    const before = Object.fromEntries(Object.entries(state.marketRequests).map(([key, requests]) => [key, requests.length]));
    await requestAndConfirm(page, panel, `Refresh ${kind} for this Markets page.`, "Refresh Markets data · handed off");
    await page.waitForLoadState("networkidle");
    await expect.poll(() => state.marketRequests[requestKey].length).toBeGreaterThan(before[requestKey]);
    for (const key of Object.keys(state.marketRequests)) {
      const expectedDependentQuoteReload = kind === "watchlist" && key === "quotes";
      if (key === requestKey || expectedDependentQuoteReload) continue;
      expect(state.marketRequests[key]).toHaveLength(before[key]);
    }
    if (kind === "watchlist") {
      expect(state.marketRequests.quotes.length).toBeGreaterThan(before.quotes);
    }
  }
  const listReadsBeforeChange = state.marketRequests.watchlist.length;
  await requestAndConfirm(page, panel, "Add TSLA to this saved watchlist.", "Add instrument to watchlist · applied");
  await expect.poll(() => state.marketRequests.watchlist.length).toBeGreaterThan(listReadsBeforeChange);
  await closeAssistant(panel, page);
  await expect(page.getByRole("row").filter({ hasText: "TSLA" })).toBeVisible();
  expect(state.marketRequests.bars.length).toBeGreaterThan(0);
  expect(state.confirmationRequests.at(-1).body).toMatchObject({ allow: true, context: { route: "/tools/markets", instrument } });
});

test("stale or malformed confirmed browser actions leave Markets state and route unchanged without using a destination fallback", async ({ page, browserDiagnostics }) => {
  const staleChart = actionScenario({
    actionType: "market.chart_range.set",
    payload: chartRangePayload(instrument.symbol, "6mo"),
    title: "Change the chart range",
    result: {
      status: "handed_off",
      message: "A chart-range handoff was accepted.",
      destination: `/tools/markets?${new URLSearchParams({ symbol: "MSFT", asset_type: "stock", provider: "fixture", exchange: "NMS" }).toString()}`,
      browser_action: {
        type: "market.chart_range.set",
        payload: chartRangePayload("MSFT", "6mo"),
        destination: { kind: "current-page", route: "/tools/markets" },
      },
    },
  });
  const malformedColumns = actionScenario({
    actionType: "market.columns.set",
    payload: { show_all_columns: true },
    title: "Change quote columns",
    result: {
      status: "handed_off",
      message: "A malformed browser action and navigation fallback were returned.",
      destination: "/?q=FORGED#history-heading",
      browser_action: { type: "market.columns.set", payload: { show_all_columns: true }, destination: { kind: "current-page", route: "/" } },
    },
  });
  const state = await installFeatureHarness(page, { route: "/tools/markets", scenarios: [staleChart, malformedColumns], markets: true, browserDiagnostics });
  const marketUrl = `/tools/markets?${new URLSearchParams(instrument).toString()}`;
  let panel = await openAssistant(page, marketUrl);
  await closeAssistant(panel, page);
  await expect(page.getByRole("combobox", { name: "Chart range", exact: true })).toHaveValue("1mo");

  panel = await reopenAssistant(page);
  await requestAndConfirm(page, panel, "Change the selected chart range.", "Change chart range · handoff rejected locally");
  await expect.poll(() => {
    const current = new URL(page.url());
    const expected = new URL(marketUrl, page.url());
    return current.pathname === expected.pathname && current.search === expected.search;
  }).toBe(true);
  await closeAssistant(panel, page);
  await expect(page.getByRole("combobox", { name: "Chart range", exact: true })).toHaveValue("1mo");
  await expect(page.getByRole("button", { name: "All quote fields" })).toHaveAttribute("aria-pressed", "false");

  panel = await reopenAssistant(page, { resumeConversation: true });
  await requestAndConfirm(page, panel, "Show all quote columns.", "Change quote columns · handoff rejected locally");
  await expect.poll(() => {
    const current = new URL(page.url());
    const expected = new URL(marketUrl, page.url());
    return current.pathname === expected.pathname && current.search === expected.search;
  }).toBe(true);
  await closeAssistant(panel, page);
  await expect(page.getByRole("button", { name: "All quote fields" })).toHaveAttribute("aria-pressed", "false");
  await expect(page.getByRole("combobox", { name: "Chart range", exact: true })).toHaveValue("1mo");
  expect(state.confirmationRequests).toHaveLength(2);
  expect(state.confirmationRequests.every(({ body }) => body.context.instrument.symbol === "ACDC" && body.allow === true)).toBe(true);
});

test("confirmed notes and alert actions preserve browser drafts and keep thresholds session-only", async ({ page, browserDiagnostics }, testInfo) => {
  const identity = {
    symbol: instrument.symbol,
    asset_type: instrument.asset_type,
    provider: instrument.provider,
    exchange: instrument.exchange,
  };
  const liveTradingDestination = { kind: "current-page", route: "/tools/live-trading" };
  const scenarios = [
    actionScenario({
      actionType: "notes.set",
      payload: identity,
      title: "Open local note controls",
      result: {
        status: "handed_off",
        message: "The existing browser controls are open. No note or alert was changed.",
        browser_action: {
          type: "notes.set",
          payload: identity,
          destination: { ...liveTradingDestination, focus: "notes-heading" },
        },
      },
    }),
    actionScenario({
      actionType: "notes.clear",
      payload: identity,
      title: "Open local note controls",
      result: {
        status: "handed_off",
        message: "The existing browser controls are open. No note or alert was changed.",
        browser_action: {
          type: "notes.clear",
          payload: identity,
          destination: { ...liveTradingDestination, focus: "notes-heading" },
        },
      },
    }),
    actionScenario({
      actionType: "alerts.add",
      payload: { ...identity, threshold: 12.75 },
      title: "Add a session-only price threshold",
      result: {
        status: "handed_off",
        message: "The price alert was submitted to this browser's existing alert handler.",
        browser_action: {
          type: "alerts.add",
          payload: { ...identity, threshold: 12.75 },
          destination: { ...liveTradingDestination, handler: "alerts.add" },
        },
      },
    }),
    actionScenario({
      actionType: "alerts.remove",
      payload: identity,
      title: "Open current alert controls",
      result: {
        status: "handed_off",
        message: "Select and remove the existing browser alert in the Alert controls. No alert was changed here.",
        browser_action: {
          type: "alerts.remove",
          payload: identity,
          destination: { ...liveTradingDestination, focus: "alerts-heading" },
        },
      },
    }),
  ];
  const state = await installFeatureHarness(page, { route: "/tools/live-trading", scenarios, markets: true, browserDiagnostics });
  const url = `/tools/live-trading?${new URLSearchParams(instrument).toString()}`;
  await page.addInitScript(() => {
    const nativeRequestAnimationFrame = window.requestAnimationFrame.bind(window);
    const probe = { holdNextFrame: false, heldFrame: null, focusAttempts: [], nativeRequestAnimationFrame };
    window.__assistantHandoffFocusProbe = probe;
    window.requestAnimationFrame = (callback) => {
      if (probe.holdNextFrame) {
        probe.holdNextFrame = false;
        probe.heldFrame = callback;
        return -1;
      }
      return nativeRequestAnimationFrame(callback);
    };
    const nativeFocus = HTMLElement.prototype.focus;
    HTMLElement.prototype.focus = function focus(options) {
      if (this.id === "notes-heading" || this.id === "alerts-heading") {
        const background = document.querySelector("[data-assistant-background]");
        probe.focusAttempts.push({
          targetId: this.id,
          backgroundInert: background?.inert ?? null,
          underlay: background?.getAttribute("data-assistant-mobile-modal-underlay") ?? null,
          assistantOpen: document.body.dataset.assistantOpen === "true",
          panelMounted: Boolean(document.querySelector('[data-testid="assistant-panel"]')),
        });
      }
      return nativeFocus.call(this, options);
    };
  });
  await page.goto(url);
  const note = page.getByRole("textbox", { name: "Notes for ACDC (local only; not sent to the server)" });
  const noteField = page.locator("#live-notes");
  const activeThreshold = page.locator('section[aria-labelledby="alerts-heading"] li').filter({ hasText: "ACDC at 12.75" });
  const noteKey = "stock-probs.live-notes.ACDC";
  const noteDraft = "Review the next earnings date before changing this note.";
  await note.fill(noteDraft);
  await expect(note).toHaveValue(noteDraft);
  const launcher = page.getByRole("button", { name: "Open Ledger assistant" });
  await expect(launcher).toBeVisible();
  await launcher.click();
  let panel = page.getByTestId("assistant-panel");
  await expect(panel).toBeVisible();
  const modelSelector = panel.getByRole("combobox", { name: "Assistant model" });
  if (await modelSelector.inputValue() !== assistantModel.id) await modelSelector.selectOption(assistantModel.id);
  await expect(panel.getByRole("textbox", { name: "Ask about this page" })).toBeVisible();

  panel = await confirmLocalControlHandoff({
    page,
    panel,
    testInfo,
    prompt: "Open the existing note editor for this instrument.",
    expectedOutcome: "Open local note controls · handed off",
    headingId: "notes-heading",
    previewText: "Confirmation opens the local note editor. Review or change the note there; the chat will not replace or clear your browser draft.",
    receiptText: "The existing browser controls are open. No note or alert was changed.",
    desktopStatusText: "The local note controls are open. Review or edit the note there; chat did not change it.",
  });
  await expect(noteField).toHaveValue(noteDraft);
  expect(await page.evaluate((key) => localStorage.getItem(key), noteKey)).toBe(noteDraft);

  panel = await confirmLocalControlHandoff({
    page,
    panel,
    testInfo,
    prompt: "Open the existing note controls without changing my draft.",
    expectedOutcome: "Open local note controls · handed off",
    headingId: "notes-heading",
    previewText: "Confirmation opens the local note editor. Review or change the note there; the chat will not replace or clear your browser draft.",
    receiptText: "The existing browser controls are open. No note or alert was changed.",
    desktopStatusText: "The local note controls are open. Review or edit the note there; chat did not change it.",
    beforeConfirm: async ({ page: handoffPage }) => {
      if (testInfo.project.name === "mobile-chromium") {
        await handoffPage.evaluate(() => { window.__assistantHandoffFocusProbe.holdNextFrame = true; });
      }
    },
  });
  if (testInfo.project.name === "mobile-chromium") {
    const released = await page.evaluate(() => {
      const probe = window.__assistantHandoffFocusProbe;
      if (!probe?.heldFrame) return false;
      const callback = probe.heldFrame;
      probe.heldFrame = null;
      probe.nativeRequestAnimationFrame(callback);
      return true;
    });
    expect(released).toBe(true);
    await expect.poll(() => page.evaluate(() => {
      const background = document.querySelector("[data-assistant-background]");
      return document.activeElement?.closest('[data-testid="assistant-panel"]') !== null
        && background?.inert === true
        && document.body.dataset.assistantOpen === "true";
    })).toBe(true);
    const delayedAttempt = await page.evaluate(() => {
      const attempts = window.__assistantHandoffFocusProbe?.focusAttempts ?? [];
      return attempts.filter((attempt) => attempt.targetId === "notes-heading").at(-1) ?? null;
    });
    expect(delayedAttempt).toMatchObject({
      targetId: "notes-heading",
      backgroundInert: true,
      assistantOpen: true,
      panelMounted: true,
    });
  }
  await expect(noteField).toHaveValue(noteDraft);
  expect(await page.evaluate((key) => localStorage.getItem(key), noteKey)).toBe(noteDraft);

  await requestAndConfirm(page, panel, "Add a session-only alert threshold of 12.75 for this page.", "Add a session-only price threshold · handed off");
  await expect(activeThreshold).toHaveCount(1);
  await expect(activeThreshold).toContainText("ACDC at 12.75");
  if (testInfo.project.name === "desktop-chromium") await expect(activeThreshold).toBeVisible();
  await expect(panel).toContainText("The threshold was added to this open page session only. No scheduler or delivery is configured.");

  panel = await confirmLocalControlHandoff({
    page,
    panel,
    testInfo,
    prompt: "Open the current alert controls for this instrument.",
    expectedOutcome: "Open current alert controls · handed off",
    headingId: "alerts-heading",
    previewText: "Confirmation opens the current alert controls. Select and remove the existing alert there; the chat will not remove an alert.",
    receiptText: "Select and remove the existing browser alert in the Alert controls. No alert was changed here.",
    desktopStatusText: "The current alert controls are open. Select and remove the existing alert there; chat did not remove any alert.",
  });
  await expect(activeThreshold).toHaveCount(1);
  await expect(activeThreshold).toContainText("ACDC at 12.75");
  if (testInfo.project.name === "desktop-chromium") await expect(activeThreshold).toBeVisible();

  expect(state.confirmationRequests.map(({ actionType }) => actionType)).toEqual([
    "notes.set", "notes.clear", "alerts.add", "alerts.remove",
  ]);
  expect(state.confirmationRequests.every(({ body }) => body.allow === true
    && body.context.route === "/tools/live-trading"
    && body.context.instrument.symbol === "ACDC"
    && !Object.hasOwn(body, "note"))).toBe(true);
  expect(JSON.stringify(state.assistantRequests)).not.toContain(noteDraft);

  await page.reload();
  await expect(page.getByRole("textbox", { name: "Notes for ACDC (local only; not sent to the server)" })).toHaveValue(noteDraft);
  await expect(page.getByText("No active thresholds.", { exact: true })).toBeVisible();
  await expect(activeThreshold).toHaveCount(0);
  expect(await page.evaluate((key) => localStorage.getItem(key), noteKey)).toBe(noteDraft);
});

test("confirmed saved-forecast reopen displays the immutable event without a new model or forecast request", async ({ page, browserDiagnostics }) => {
  const eventId = 731;
  const timestamp = "2025-01-10T17:00:00Z";
  const savedForecast = {
    analysis_kind: "saved_recorded_forecast",
    immutable: true,
    recalculated: false,
    provider_called: false,
    event: { id: eventId, run_id: 91, status: "successful", submitted_symbol: "ACDC", asset_type: "stock", submitted_at: timestamp },
    input: {
      quality: "current",
      quality_reasons: [],
      display_name: "Acme Industries",
      company_name: "Acme Industries",
      canonical_symbol: "ACDC",
      symbol: "ACDC",
      asset_type: "stock",
      quote_type: "EQUITY",
      exchange: "NMS",
      currency: "USD",
      exchange_timezone: "America/New_York",
      provider_as_of: timestamp,
      captured_at: timestamp,
      request_cutoff: timestamp,
      provider: "fixture",
      model: { name: "Saved fixture model", version: "1" },
      model_fingerprint: "saved-model-fingerprint",
      forecast_contract_version: "fixture-contract-v1",
      content_fingerprint: "saved-content-fingerprint",
      selected_daily_bars: [],
      selected_intraday_bars: [],
      provider_metadata: { intraday_archive_limit: { statement: "Fixture data has no archived intraday bars." } },
      limitations: [],
      session_state_at_request: "regular",
      session_rule: "Fixture session rule",
      calendar: { name: "Fixture calendar", version: "1", timezone: "America/New_York" },
    },
    results: [{
      horizon: "close_to_close",
      definition: "Recorded next-close forecast",
      origin_price: 10.25,
      origin_timestamp: timestamp,
      reference_timestamp: timestamp,
      reference_state: "reported_origin",
      target_timestamp: "2025-01-13T21:00:00Z",
      target_state: "scheduled_session_close",
      target_session_rule: "Fixture target session",
      calculated_at: timestamp,
      direction_probabilities: { down: 0.25, flat: 0.5, up: 0.25 },
      magnitude_intervals: [{
        level: 0.9,
        definition: "Recorded 90 percent interval",
        percent: { low: -4, high: 4, unit: "percent" },
        price: { low: 9.84, high: 10.66, unit: "USD" },
      }],
      threshold_probabilities: [],
      sample_size: 4,
      distribution_definition: "Saved fixture distribution",
      model: { name: "Saved fixture model", version: "1" },
      forecast_contract_version: "fixture-contract-v1",
      model_fingerprint: "saved-model-fingerprint",
      forecast_fingerprint: "saved-forecast-fingerprint",
    }],
  };
  const scenario = actionScenario({
    actionType: "forecast.reopen",
    payload: { event_id: eventId, event_version: "a".repeat(64) },
    title: "Open the saved forecast",
    summary: "Reopen the owner-validated saved event exactly as recorded.",
    result: {
      status: "handed_off",
      message: "Open the owner-validated saved forecast.",
      destination: `/?event_id=${eventId}#result-section`,
    },
  });
  const state = await installFeatureHarness(page, { scenarios: [scenario], savedForecast, browserDiagnostics });
  const panel = await openAssistant(page, "/");
  await requestAndConfirm(page, panel, `Open saved forecast event ${eventId}.`, undefined, "Confirm change", async ({ page }) => {
    state.assistantStatus = {
      ...assistantStatus,
      available: false,
      enabled: true,
      worker: { status: "unavailable", reason: "The assistant worker is unavailable. Your workspace is still available." },
    };
    const statusResponse = page.waitForResponse((response) => response.request().method() === "GET"
      && response.url().endsWith("/api/v1/assistant/status"));
    const observedStatus = await page.evaluate(async () => {
      const response = await fetch("/api/v1/assistant/status", { cache: "no-store" });
      return { httpStatus: response.status, body: await response.json() };
    });
    const response = await statusResponse;
    expect(response.status()).toBe(200);
    expect(observedStatus).toMatchObject({
      httpStatus: 200,
      body: { available: false, enabled: true, worker: { status: "unavailable" } },
    });
    expect(state.assistantRequests.filter(({ method, path }) => method === "GET" && path === "/api/v1/assistant/status")).not.toHaveLength(0);
  });
  await page.waitForURL((url) => url.pathname === "/" && url.search === `?event_id=${eventId}` && url.hash === "#result-section");
  await expect(page.locator("#result-content")).toContainText(`Immutable recorded result · audit event #${eventId}`);
  await expect(page.locator("#result-content")).toContainText("Saved fixture model / 1");
  await expect(page.locator("#announcement")).toHaveText(`Immutable recorded result ${eventId} reopened without recalculation.`);

  expect(state.confirmationRequests).toHaveLength(1);
  expect(state.confirmationRequests[0].body).toMatchObject({ allow: true });
  expect(savedForecast).toMatchObject({ analysis_kind: "saved_recorded_forecast", immutable: true, recalculated: false, provider_called: false });
  expect(state.savedForecastRequests).toEqual([{ method: "GET", path: `/api/v1/saved-forecasts/${eventId}` }]);
  expect(state.forecastRequests).toEqual([]);
  expect(state.started).toHaveLength(1);
  expect(state.assistantRequests.filter(({ method, path }) => method === "POST" && /\/turns$/.test(path))).toHaveLength(1);
  expect(state.assistantStatus).toMatchObject({ available: false, enabled: true, worker: { status: "unavailable" } });
});
