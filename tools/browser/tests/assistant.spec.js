const { test, expect } = require("./fixtures");
const { readFileSync } = require("node:fs");
const path = require("node:path");
const AxeBuilder = require("@axe-core/playwright").default;
const { captureAssistantAxeIncompleteSnapshot, evaluateAssistantContrastAudit } = require("./assistant-contrast-audit");

const assistantCatalog = JSON.parse(readFileSync(path.resolve(__dirname, "../../../src/stock_probs/assistant/assistant_catalog.json"), "utf8"));
const zenPolicy = assistantCatalog.zen;
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

const answer = [
  "## Forecast summary",
  "The **up probability** is 65% in the saved result.",
  "- Down: 20%",
  "- Unchanged: 15%",
  "- Up: 65%",
  "Horizon: Close to next close",
  "As of: 2025-01-10",
  "| Outcome | Probability |",
  "| --- | ---: |",
  "| Down | 20% |",
  "| Up | 65% |",
  "<img src=x onerror=alert(1)> https://example.invalid/private",
].join("\n");

const context = {
  route: "/",
  instrument: null,
  event_ref: null,
  result_ref: null,
  context_version: "context-v1",
};

async function installAssistantClock(page) {
  await page.clock.install({ time: "2025-01-10T17:03:00.000Z" });
}

const status = {
  available: true,
  enabled: true,
  worker: { status: "ready" },
  limits: { active_per_user: 1, active_global: 2, tools_per_turn: 8, turn_seconds: 120 },
  storage: { user_bytes: 1024, user_limit: 2097152, global_bytes: 4096, global_limit: 25165824, database_bytes: 8192, database_limit: 50331648, backup_retention_note: "Existing backup retention applies." },
};

const model = {
  id: zenModelId,
  model_id: zenModelId,
  provider: zenPolicy.provider_id,
  provider_id: zenPolicy.provider_id,
  native_provider_id: zenPolicy.provider_id,
  name: `Synthetic QA / ${zenFreeModel.display_name}`,
  availability: "available",
  available: true,
  enabled: true,
  usable: true,
  free: true,
  training: zenFreeModel.training ? "training_may_use_data" : "no_training",
  training_uses_data: false,
  terms_url: zenPolicy.terms_url,
  terms_reviewed_at: zenPolicy.terms_reviewed_at,
  policy_version: zenPolicy.policy_version,
  disclosure: "Synthetic browser QA model; no external model is called.",
  privacy_policy_version: zenPrivacyPolicyVersion,
  privacy_disclosure: "Synthetic browser QA model; no external model is called.",
  billing_class: "free",
  billing_policy_version: zenBillingPolicyVersion,
  cost_disclosure: zenFreeModel.disclosure,
  revision: 1,
  availability_reason: null,
  consent: { accepted: true, data_collection_opt_in: false, accepted_at: "2025-01-01T00:00:00Z" },
};

async function expectAssistantAxeClean(page, testInfo, scan) {
  await expect(page.locator('[data-testid="assistant-panel"] [aria-label="Conversation"]')).toHaveAttribute("tabindex", "0");
  const results = await new AxeBuilder({ page }).include('[data-testid="assistant-panel"]').analyze();
  const counts = {
    project: testInfo.project.name,
    scan,
    violations: Array.isArray(results.violations) ? results.violations.length : null,
    incomplete: Array.isArray(results.incomplete) ? results.incomplete.length : null,
    passes: Array.isArray(results.passes) ? results.passes.length : null,
    inapplicable: Array.isArray(results.inapplicable) ? results.inapplicable.length : null,
  };
  await testInfo.attach(`assistant-axe-counts-${scan}.json`, {
    body: Buffer.from(JSON.stringify(counts, null, 2)),
    contentType: "application/json",
  });
  if (Array.isArray(results.incomplete) && results.incomplete.length > 0) {
    const incompleteNodes = results.incomplete.flatMap((rule) => (rule.nodes || []).map((node) => ({
      rule: rule.id,
      targets: node.target,
    })));
    const layouts = await page.evaluate((nodes) => {
      const describe = (element) => ({
        tag: element.tagName.toLowerCase(),
        id: element.id || null,
        classes: Array.from(element.classList).slice(0, 6),
        testId: element.getAttribute("data-testid"),
      });
      const styleSummary = (element) => {
        const style = getComputedStyle(element);
        return {
          position: style.position,
          zIndex: style.zIndex,
          opacity: style.opacity,
          color: style.color,
          backgroundColor: style.backgroundColor,
          backgroundImage: style.backgroundImage,
          transform: style.transform,
          pointerEvents: style.pointerEvents,
        };
      };
      const bounds = (rect) => ({
        x: Number(rect.x.toFixed(2)),
        y: Number(rect.y.toFixed(2)),
        width: Number(rect.width.toFixed(2)),
        height: Number(rect.height.toFixed(2)),
      });
      return nodes.map(({ rule, targets }) => ({
        rule,
        targets: targets.map((selector) => {
          const elements = Array.from(document.querySelectorAll(selector));
          return {
            selector,
            elementCount: elements.length,
            elements: elements.map((element) => {
              const textRange = document.createRange();
              textRange.selectNodeContents(element);
              const textRects = Array.from(textRange.getClientRects());
              const intersections = Array.from(document.querySelectorAll("*"))
                .filter((candidate) => candidate !== element && !element.contains(candidate) && !candidate.contains(element))
                .filter((candidate) => {
                  const style = getComputedStyle(candidate);
                  return style.display !== "none" && style.visibility !== "hidden" && Number(style.opacity) > 0
                    && candidate.getClientRects().length > 0;
                })
                .map((candidate) => {
                  const rect = candidate.getBoundingClientRect();
                  const lines = textRects.flatMap((textRect, line) => {
                    const width = Math.min(rect.right, textRect.right) - Math.max(rect.left, textRect.left);
                    const height = Math.min(rect.bottom, textRect.bottom) - Math.max(rect.top, textRect.top);
                    return width > 0.5 && height > 0.5 ? [{ line, width, height }] : [];
                  });
                  return lines.length ? { candidate, rect, lines } : null;
                })
                .filter(Boolean);
              const hitTests = textRects.flatMap((rect) => [0.25, 0.5, 0.75].map((fraction) => {
                const x = rect.left + rect.width * fraction;
                const y = rect.top + rect.height / 2;
                const hit = document.elementFromPoint(x, y);
                return {
                  x: Number(x.toFixed(2)),
                  y: Number(y.toFixed(2)),
                  targetOrChild: hit === element || element.contains(hit),
                  hit: hit ? describe(hit) : null,
                };
              }));
              const siblings = Array.from(element.parentElement?.children || [])
                .filter((sibling) => sibling !== element)
                .map((sibling) => ({
                  element: describe(sibling),
                  rect: bounds(sibling.getBoundingClientRect()),
                  style: styleSummary(sibling),
                }));
              const ancestors = [];
              for (let current = element; current && ancestors.length < 8; current = current.parentElement) {
                ancestors.push({
                  element: describe(current),
                  rect: bounds(current.getBoundingClientRect()),
                  style: styleSummary(current),
                });
                if (current.matches('[data-testid="assistant-panel"]')) break;
              }
              return {
                element: describe(element),
                rect: bounds(element.getBoundingClientRect()),
                style: styleSummary(element),
                textRects: textRects.map(bounds),
                intersectingElementCount: intersections.length,
                intersections: intersections.slice(0, 20).map(({ candidate, rect, lines }) => ({
                  element: describe(candidate),
                  rect: bounds(rect),
                  style: styleSummary(candidate),
                  textLines: lines.map(({ line, width, height }) => ({
                    line,
                    overlapWidth: Number(width.toFixed(2)),
                    overlapHeight: Number(height.toFixed(2)),
                  })),
                })),
                siblings,
                ancestors,
                hitTests,
              };
            }),
          };
        }),
      }));
    }, incompleteNodes);
    await testInfo.attach(`assistant-axe-layout-${scan}.json`, {
      body: Buffer.from(JSON.stringify({ viewport: await page.evaluate(() => ({ width: innerWidth, height: innerHeight })), layouts }, null, 2)),
      contentType: "application/json",
    });
  }
  expect(results.violations).toEqual([]);
  if (Array.isArray(results.incomplete) && results.incomplete.length > 0) {
    const snapshot = await captureAssistantAxeIncompleteSnapshot(page, results);
    const audit = evaluateAssistantContrastAudit(snapshot);
    await testInfo.attach(`assistant-axe-resolution-counts-${scan}.json`, {
      body: Buffer.from(JSON.stringify({
        project: testInfo.project.name,
        scan,
        rawAxeCounts: snapshot.rawAxe.counts,
        rawNodeMappingCount: snapshot.rawNodeMappings.length,
        measuredTextTargetCount: snapshot.targets.length,
        measuredRoles: snapshot.requiredRoles,
        issueCount: audit.issues.length,
        passed: audit.passed,
        roleCounts: audit.roleCounts,
      }, null, 2)),
      contentType: "application/json",
    });
    await testInfo.attach(`assistant-axe-resolution-measurements-${scan}.json`, {
      body: Buffer.from(JSON.stringify({
        rawNodeMappings: snapshot.rawNodeMappings,
        targets: snapshot.targets,
        audit,
      }, null, 2)),
      contentType: "application/json",
    });
    expect(audit.issues, "measured resolution for exact raw axe incomplete targets").toEqual([]);
  } else {
    expect(results.incomplete, "axe must return an incomplete-results array").toEqual([]);
  }
}

async function expectAssistantLiveStatus(panel, message) {
  const visibleStatus = panel.locator("p").filter({ hasText: message });
  const announcer = panel.locator('span.sr-only[aria-live="polite"]');
  await expect(visibleStatus).toHaveCount(1);
  await expect(visibleStatus).toBeVisible();
  await expect(visibleStatus).toHaveText(message);
  await expect(visibleStatus).not.toHaveAttribute("role", "status");
  await expect(panel.locator('[aria-live="polite"]')).toHaveCount(1);
  await expect(announcer).toHaveCount(1);
  await expect(announcer).toHaveText(message);
}

async function expectAssistantLiveStatusAbsent(panel, message) {
  await expect(panel.locator("p").filter({ hasText: message })).toHaveCount(0);
  const announcer = panel.locator('span.sr-only[aria-live="polite"]');
  await expect(panel.locator('[aria-live="polite"]')).toHaveCount(1);
  await expect(announcer).toHaveCount(1);
  await expect(announcer).not.toHaveText(message);
}

async function chooseFixtureModel(panel) {
  const selector = panel.getByRole("combobox", { name: "Assistant model" });
  if (await selector.inputValue() !== model.id) await selector.selectOption(model.id);
}

async function openRealAssistant(page, origin) {
  await page.context().addCookies([
    { name: "signal_ledger_session", value: "browser-assistant-fixture-session-not-a-production-credential", url: origin, httpOnly: true, sameSite: "Lax" },
    { name: "signal_ledger_csrf", value: "browser-assistant-fixture-csrf-token-not-a-production-credential", url: origin, sameSite: "Lax" },
  ]);
  await page.goto(`${origin}/overview`);
  await page.getByRole("button", { name: "Open Ledger assistant" }).click();
  const panel = page.getByTestId("assistant-panel");
  await expect(panel).toBeVisible();
  await chooseFixtureModel(panel);
  const consent = panel.getByRole("checkbox", { name: /I accept this model's privacy terms/ });
  if (await consent.count()) {
    await consent.check();
    await panel.getByRole("button", { name: "Save privacy choice" }).click();
    await expectAssistantLiveStatus(panel, "Model privacy consent saved for this policy version.");
  }
  return panel;
}

function conversationDetail() {
  return {
    conversation: {
      id: "conversation-1",
      title: "Saved forecast question",
      revision: 2,
      created_at: "2025-01-10T17:00:00Z",
      updated_at: "2025-01-10T17:01:00Z",
      delete_confirmation_phrase: "DELETE tion-1",
    },
    messages: {
      items: [{
        id: "assistant-message-1",
        turn_id: "turn-1",
        seq: 2,
        role: "assistant",
        text: answer,
        created_at: "2025-01-10T17:01:00Z",
        sources: [
          { source_id: "source-1", title: "Saved result source", url: "https://source.example.org/research", source_type: "saved result", retrieved_at: "2025-01-10T17:00:00Z", as_of: "2025-01-10T17:00:00Z" },
          { source_id: "source-private", title: "Loopback source", url: "https://127.0.0.1/private", source_type: "saved result", retrieved_at: "2025-01-10T17:00:00Z" },
        ],
      }],
      page: 1,
      page_size: 50,
      total: 1,
    },
    turns: [{ id: "turn-1", status: "completed", model_id: model.id, policy_version: model.policy_version, context_version: context.context_version, context, created_at: "2025-01-10T17:00:00Z", completed_at: "2025-01-10T17:01:00Z", actions: [] }],
    actions: [],
  };
}

test("assistant desktop/mobile widget keeps a structured saved answer readable and applies only a confirmed typed theme action", async ({ page }, testInfo) => {
  const originalViewport = page.viewportSize();
  if (!originalViewport) throw new Error("The browser project must provide a viewport for this regression.");
  let confirmedBody = null;
  let turnStarted = false;
  const contextRoutes = [];
  await page.route("**/api/v1/auth/session", (route) => route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify({ authenticated: true, user: { id: 1, role: "admin" }, csrf_token: "fixture-csrf" }),
  }));
  await page.route("**/api/v1/assistant/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;
    if (path === "/api/v1/assistant/status") return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(status) });
    if (path === "/api/v1/assistant/models") return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ items: [model] }) });
    if (path === "/api/v1/assistant/context") {
      const routeName = url.searchParams.get("route") || "/";
      contextRoutes.push(routeName);
      return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ context: { ...context, route: routeName, context_version: routeName === "/" ? context.context_version : `context-v1-${routeName}` }, preview: { summary: routeName === "/overview" ? "Overview" : "Forecast workspace", fields: ["page route only"], note: "Only the route is attached." } }) });
    }
    if (path === "/api/v1/assistant/conversations" && request.method() === "GET") return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ items: [{ id: "conversation-1", title: "Saved forecast question", revision: 2, created_at: "2025-01-10T17:00:00Z", updated_at: "2025-01-10T17:01:00Z", last_message_preview: "Compare the recorded probabilities" }], page: 1, page_size: 20, total: 1 }) });
    if (path === "/api/v1/assistant/conversations/conversation-1" && request.method() === "GET") {
      const detail = conversationDetail();
      if (turnStarted) {
        detail.messages.items = [...detail.messages.items, {
          id: "assistant-message-2",
          turn_id: "turn-2",
          seq: 2,
          role: "assistant",
          text: "Theme preview ready.",
          created_at: "2025-01-10T17:02:00Z",
          sources: [],
        }];
        detail.messages.total = 2;
        detail.turns.push({ id: "turn-2", status: "completed", model_id: model.id, policy_version: model.policy_version, context_version: context.context_version, context, created_at: "2025-01-10T17:01:30Z", completed_at: "2025-01-10T17:02:00Z", actions: [] });
        detail.actions = [{
          action_id: "action-12345678",
          action_type: "theme.set",
          status: "pending",
          expires_at: "2099-01-01T00:00:00Z",
          availability: "confirmable",
          proposal: {
            title: "Set dark theme",
            summary: "Use dark appearance for this browser.",
            changes: [{ label: "Theme", after: "Dark" }],
            action_version: 1,
            context_version: context.context_version,
            confirmation_phrase: "CONFIRM 12345678",
          },
          receipt: null,
        }];
        detail.events = {
          items: [{
            turn_id: "turn-2",
            sequence: 3,
            type: "tool",
            data: {
              name: "signal-ledger_workspace_summary",
              call_id: "fixture-call-1",
              receipt_id: "fixture-receipt-1",
              status: "complete",
              result_bytes: 96,
            },
            created_at: "2025-01-10T17:00:30Z",
          }],
          page: 1,
          page_size: 100,
          total: 1,
        };
      }
      return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(detail) });
    }
    if (path === "/api/v1/assistant/conversations/conversation-1/turns" && request.method() === "POST") {
      turnStarted = true;
      return route.fulfill({ status: 202, contentType: "application/json", body: JSON.stringify({ turn: { id: "turn-2", status: "running" } }) });
    }
    if (path === "/api/v1/assistant/conversations/conversation-1/turns/turn-2/events") {
      const events = [
        [1, "meta", { model_id: model.id, policy_version: model.policy_version, context_version: context.context_version }],
        [2, "token", { text: "Theme preview ready." }],
        [3, "proposed_action", { action_id: "action-12345678", action_type: "theme.set", title: "Set dark theme", summary: "Use dark appearance for this browser.", changes: [{ label: "Theme", before: "System", after: "Dark" }], version: 1, context_version: context.context_version, expires_at: "2099-01-01T00:00:00Z", confirmation_phrase: "CONFIRM 12345678" }],
        [4, "complete", { status: "completed", assistant_message_id: "assistant-message-2" }],
      ];
      const body = events.map(([id, name, data]) => `id: ${id}\nevent: ${name}\ndata: ${JSON.stringify(data)}\n\n`).join("");
      return route.fulfill({ status: 200, contentType: "text/event-stream", headers: { "Cache-Control": "no-store" }, body });
    }
    if (path === "/api/v1/assistant/conversations/conversation-1/actions/action-12345678/confirm" && request.method() === "POST") {
      confirmedBody = request.postDataJSON();
      return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({
        action_id: "action-12345678",
        status: "handed_off",
        message: "Theme preference passed to the browser setting.",
        receipt_id: "receipt-1",
        browser_action: { type: "theme.set", payload: { theme: "dark" } },
      }) });
    }
    return route.fulfill({ status: 404, contentType: "application/json", body: JSON.stringify({ error: { code: "fixture_missing", message: "No assistant fixture route." } }) });
  });

  await page.goto("/");
  await expect(page.getByRole("button", { name: "Open Ledger assistant" })).toBeVisible();
  await expect(page.getByTestId("assistant-panel")).toHaveCount(0);
  await page.getByRole("button", { name: "Open Ledger assistant" }).click();
  const panel = page.getByTestId("assistant-panel");
  await expect(panel).toBeVisible();
  if (test.info().project.name === "mobile-chromium") {
    await expect(panel).toHaveAttribute("aria-modal", "true");
    await expect(panel.getByRole("button", { name: "Minimize assistant" })).toHaveCount(0);
    await expect(page.locator("[data-assistant-background]")).toHaveJSProperty("inert", true);
    await expect(panel.getByRole("heading", { name: "Ledger assistant" })).toBeFocused();
    const focusCycle = await panel.evaluate((node) => {
      const controls = [...node.querySelectorAll('a[href],button:not([disabled]),input:not([disabled]),select:not([disabled]),textarea:not([disabled]),[tabindex]:not([tabindex="-1"])')]
        .filter((element) => element.getAttribute("aria-hidden") !== "true" && element.getClientRects().length > 0);
      controls[0]?.focus();
      return { hasControls: controls.length > 1, firstFocused: document.activeElement === controls[0] };
    });
    expect(focusCycle).toEqual({ hasControls: true, firstFocused: true });
    await page.keyboard.press("Shift+Tab");
    const wrappedToLastControl = await panel.evaluate((node) => {
      const controls = [...node.querySelectorAll('a[href],button:not([disabled]),input:not([disabled]),select:not([disabled]),textarea:not([disabled]),[tabindex]:not([tabindex="-1"])')]
        .filter((element) => element.getAttribute("aria-hidden") !== "true" && element.getClientRects().length > 0);
      return controls.length > 1 && document.activeElement === controls.at(-1);
    });
    expect(wrappedToLastControl).toBe(true);
    const focusWasBlockedByInertBackground = await page.evaluate(() => {
      const background = document.querySelector("[data-assistant-background]");
      const target = document.createElement("button");
      target.type = "button";
      target.textContent = "Background focus probe";
      background?.append(target);
      target.focus();
      const blocked = document.activeElement !== target;
      target.remove();
      return blocked;
    });
    expect(focusWasBlockedByInertBackground).toBe(true);
  } else {
    await expect(panel).not.toHaveAttribute("aria-modal", "true");
    await expect(page.locator("[data-assistant-background]")).toHaveJSProperty("inert", false);
    await panel.getByRole("button", { name: "Minimize assistant" }).click();
    const resumeButton = panel.getByRole("button", { name: "Resume assistant" });
    await expect(resumeButton).toBeVisible();
    await expect(resumeButton).toBeFocused();
    await resumeButton.click();
    await expect(panel).toBeFocused();
    await expect(panel.getByRole("textbox", { name: "Ask about this page" })).toBeVisible();
  }

  await page.setViewportSize({ width: 1280, height: 900 });
  await expect(panel).toHaveAttribute("data-mobile", "false");
  await expect(page.locator("[data-assistant-background]")).toHaveJSProperty("inert", false);
  await panel.getByRole("button", { name: "Minimize assistant" }).click();
  const resumeButton = panel.getByRole("button", { name: "Resume assistant" });
  await expect(resumeButton).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(panel).toBeFocused();
  await expect(panel.getByRole("textbox", { name: "Ask about this page" })).toBeVisible();
  await expect(panel.getByRole("region", { name: "Workspace context" })).toBeVisible();

  await panel.getByRole("button", { name: "Minimize assistant" }).click();
  await expect(panel.getByRole("button", { name: "Resume assistant" })).toBeFocused();
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(panel).toHaveAttribute("data-mobile", "true");
  await expect(panel).toHaveAttribute("aria-modal", "true");
  await expect(panel.getByRole("button", { name: "Resume assistant" })).toHaveCount(0);
  await expect(panel.getByRole("textbox", { name: "Ask about this page" })).toBeVisible();
  await expect(panel.getByRole("heading", { name: "Ledger assistant" })).toBeFocused();
  await expect(page.locator("[data-assistant-background]")).toHaveJSProperty("inert", true);

  await page.setViewportSize(originalViewport);
  const originalMobileMode = originalViewport.width <= 699;
  await expect(panel).toHaveAttribute("data-mobile", originalMobileMode ? "true" : "false");
  await expect(page.locator("[data-assistant-background]")).toHaveJSProperty("inert", originalMobileMode);
  if (originalMobileMode) {
    await expect(panel).toHaveAttribute("aria-modal", "true");
  } else {
    await expect(panel).not.toHaveAttribute("aria-modal", "true");
  }

  await expect(panel.getByText("Conversation storage")).toBeVisible();
  await expect(panel.getByText("Forecast workspace", { exact: true }).first()).toBeVisible();

  await panel.getByRole("button", { name: "Open conversation history" }).click();
  await panel.getByRole("button", { name: /Saved forecast question/ }).click();
  await expect(panel.getByRole("heading", { name: "Forecast summary" })).toBeVisible();
  await expect(panel.getByRole("list").getByText("Up: 65%")).toBeVisible();
  await expect(panel.getByRole("table").getByText("Probability")).toBeVisible();
  await expect(panel.getByText("<img src=x onerror=alert(1)> https://example.invalid/private", { exact: true })).toBeVisible();
  await expect(panel.locator("img[src='x']")).toHaveCount(0);
  await expect(panel.getByRole("link", { name: /Saved result source/ })).toHaveAttribute("href", "https://source.example.org/research");
  await expect(panel.getByRole("link", { name: /Loopback source/ })).toHaveCount(0);
  await expect(panel.getByText(/Loopback source.*Link unavailable/)).toBeVisible();
  await expect(panel.getByRole("link", { name: /example.invalid/ })).toHaveCount(0);

  const shortViewport = page.context().browser()?.browserType().name() === "chromium" && test.info().project.name === "mobile-chromium";
  if (shortViewport) await page.setViewportSize({ width: 320, height: 568 });
  const geometry = await panel.evaluate((node) => {
    const header = node.querySelector("header").getBoundingClientRect();
    const composer = node.querySelector("#assistant-prompt").getBoundingClientRect();
    const content = node.querySelector("[class*='body']");
    return {
      panel: node.getBoundingClientRect().toJSON(),
      header: header.toJSON(),
      composer: composer.toJSON(),
      bodyScrollHeight: content?.scrollHeight ?? 0,
      bodyClientHeight: content?.clientHeight ?? 0,
      transcriptClientHeight: node.querySelector("[aria-label='Conversation']")?.clientHeight ?? 0,
      composerFontSize: getComputedStyle(node.querySelector("#assistant-prompt")).fontSize,
      composerFontFamily: getComputedStyle(node.querySelector("#assistant-prompt")).fontFamily,
      pageFontFamily: getComputedStyle(document.body).fontFamily,
    };
  });
  expect(geometry.composerFontFamily).toBe(geometry.pageFontFamily);
  expect(geometry.composer.bottom).toBeLessThanOrEqual(geometry.panel.bottom + 1);
  if (shortViewport) {
    expect(geometry.panel.height).toBeLessThanOrEqual(569);
    expect(Number.parseFloat(geometry.composerFontSize)).toBeGreaterThanOrEqual(16);
    expect(geometry.bodyScrollHeight).toBeGreaterThan(geometry.bodyClientHeight);
    expect(geometry.transcriptClientHeight).toBeGreaterThanOrEqual(192);
  }

  if (testInfo.project.name === "mobile-chromium") {
    for (const viewport of [{ width: 390, height: 844 }, { width: 360, height: 740 }, { width: 390, height: 520 }]) {
      await page.setViewportSize(viewport);
      const contentGeometry = await panel.evaluate((node) => {
        const bounds = node.getBoundingClientRect();
        const contextCard = node.querySelector('[aria-label="Workspace context"]');
        const transcript = node.querySelector('[aria-label="Conversation"]');
        const composer = node.querySelector("#assistant-prompt");
        return {
          panel: { left: bounds.left, right: bounds.right, top: bounds.top, bottom: bounds.bottom },
          viewport: { width: window.innerWidth, height: window.innerHeight },
          documentWidth: document.documentElement.scrollWidth,
          contextHeight: contextCard?.getBoundingClientRect().height ?? 0,
          transcriptHeight: transcript?.clientHeight ?? 0,
          transcriptScrollHeight: transcript?.scrollHeight ?? 0,
          composerBottom: composer?.getBoundingClientRect().bottom ?? 0,
        };
      });
      expect(contentGeometry.panel.left).toBeGreaterThanOrEqual(-1);
      expect(contentGeometry.panel.right).toBeLessThanOrEqual(contentGeometry.viewport.width + 1);
      expect(contentGeometry.panel.bottom).toBeLessThanOrEqual(contentGeometry.viewport.height + 1);
      expect(contentGeometry.documentWidth).toBeLessThanOrEqual(contentGeometry.viewport.width + 1);
      expect(contentGeometry.contextHeight).toBeLessThanOrEqual(120);
      expect(contentGeometry.transcriptHeight).toBeGreaterThanOrEqual(192);
      expect(contentGeometry.transcriptScrollHeight).toBeGreaterThan(contentGeometry.transcriptHeight);
      expect(contentGeometry.composerBottom).toBeLessThanOrEqual(contentGeometry.panel.bottom + 1);
      await expect(panel.getByRole("heading", { name: "Forecast summary" })).toBeVisible();
      await expect(panel.getByRole("textbox", { name: "Ask about this page" })).toBeVisible();
    }
  }

  await chooseFixtureModel(panel);
  await panel.getByRole("textbox", { name: "Ask about this page" }).fill("Set the dark theme");
  await panel.getByRole("button", { name: "Send question" }).click();
  const phrase = panel.getByRole("textbox", { name: "Type CONFIRM 12345678 to confirm" });
  await expect(phrase).toBeVisible();
  await expectAssistantLiveStatus(panel, "Assistant response complete.");
  await phrase.fill("CONFIRM 12345678");
  await panel.getByRole("button", { name: "Confirm change" }).click();
  await expect.poll(async () => page.locator("html").getAttribute("data-theme")).toBe("dark");
  expect(confirmedBody).toMatchObject({
    action_version: 1,
    allow: true,
    context: { route: "/", context_version: "context-v1", instrument: null },
    confirmation_phrase: "CONFIRM 12345678",
  });
  await page.evaluate(() => {
    window.history.pushState({}, "", "/overview");
    window.dispatchEvent(new PopStateEvent("popstate"));
  });
  await expect(panel).toBeVisible();
  await expect(panel.getByRole("heading", { name: "Forecast summary" })).toBeVisible();
  await expect(panel.getByText("Overview", { exact: true }).first()).toBeVisible();
  expect(contextRoutes).toContain("/overview");
  await panel.getByRole("button", { name: "Close assistant" }).click();
  await expect(page.getByRole("button", { name: "Open Ledger assistant" })).toBeFocused();
  await expect(page.locator("[data-assistant-background]")).toHaveJSProperty("inert", false);
  if (test.info().project.name === "mobile-chromium") {
    const backgroundRestored = await page.evaluate(() => {
      const background = document.querySelector("[data-assistant-background]");
      const target = document.createElement("button");
      target.type = "button";
      target.textContent = "Restored background focus probe";
      background?.append(target);
      target.focus();
      const restored = document.activeElement === target && background?.inert === false;
      target.remove();
      return restored;
    });
    expect(backgroundRestored).toBe(true);
  }
});

test("secure assistant destinations focus the matching account and admin controls", async ({ page, browserDiagnostics }) => {
  const paidModel = {
    ...model,
    id: "fixture-provider/paid-model",
    model_id: "fixture-provider/paid-model",
    name: "Fixture Paid Model",
    billing_class: "paid",
    free: false,
    billing_policy_version: "paid-billing-v2",
    cost_disclosure: "Synthetic test cost: $0.01 per request.",
    usable: false,
    enabled: false,
    revision: 7,
  };
  let paidModelEnabled = false;
  let paidModelRevision = 7;
  let policyConflictOnce = true;
  let policyRequestBody = null;
  let freeModelEnabled = true;
  let freeModelRevision = 4;
  let freeModelPolicyRequestBody = null;
  let zenSelectedModelId = null;
  let zenProviderSaveBody = null;
  let openAiCredentialConfigured = false;
  let openAiProviderSaveBody = null;
  let customProviderSaveBody = null;
  let customProviderSaved = null;
  const validationCalled = [];
  await page.route("**/api/v1/**", async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (path === "/api/v1/auth/totp/step-up" && request.method() === "POST") {
      return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ verified: true }) });
    }
    if (path === "/api/v1/assistant/providers" && request.method() === "GET") {
      const providers = [{
        provider_id: "opencode-zen",
        display_name: "OpenCode Zen",
        auth_methods: ["free_no_key"],
        selected_model_id: zenSelectedModelId,
        selected_base_url: "https://opencode.ai/zen/v1",
        credential_required: false,
        credential_configured: false,
        oauth_connected: false,
        connection_status: "ready",
        terms_url: "https://opencode.ai/docs/en/zen/",
        native_provider_id: "opencode-zen",
        adapter_id: "opencode-zen-openai-compatible-v1",
        protocol: "openai-chat-completions",
        supported_auth_methods: ["native_zen_free"],
        endpoint_editable: false,
        credential_supported: false,
        validation_requires_credential: false,
        unsupported_reason: null,
      }, {
        provider_id: "openai",
        display_name: "OpenAI",
        auth_methods: ["api_key"],
        selected_model_id: null,
        selected_base_url: "https://api.openai.com/v1",
        credential_required: true,
        credential_configured: openAiCredentialConfigured,
        oauth_connected: false,
        connection_status: openAiCredentialConfigured ? "configured" : "unconfigured",
        native_provider_id: "openai",
        adapter_id: "openai-compatible-v1",
        protocol: "openai-chat-completions",
        supported_auth_methods: ["api_key"],
        endpoint_editable: false,
        credential_supported: true,
        validation_requires_credential: true,
        unsupported_reason: null,
      }, {
        provider_id: "custom",
        display_name: "Custom compatible endpoint",
        auth_methods: ["api_key"],
        selected_model_id: null,
        selected_base_url: customProviderSaved?.base_url ?? null,
        credential_required: false,
        credential_configured: Boolean(customProviderSaved?.credential),
        oauth_connected: false,
        connection_status: customProviderSaved ? "configured" : "unconfigured",
        endpoint_editable: true,
        credential_supported: true,
        validation_requires_credential: true,
        selected_terms_url: customProviderSaved?.terms_url ?? null,
        selected_privacy_disclosure: customProviderSaved?.privacy_disclosure ?? null,
        selected_billing_disclosure: customProviderSaved?.billing_disclosure ?? null,
        selected_billing_class: customProviderSaved?.billing_class ?? "unknown",
        selected_endpoint_policy_reviewed: Boolean(customProviderSaved),
        unsupported_reason: null,
      }];
      return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ providers }) });
    }
    if (path === "/api/v1/assistant/models" && request.method() === "GET") {
      return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ items: [{ ...model, enabled: freeModelEnabled, usable: freeModelEnabled, revision: freeModelRevision }, { ...paidModel, enabled: paidModelEnabled, usable: paidModelEnabled, revision: paidModelRevision }] }) });
    }
    if (path === `/api/v1/assistant/models/${encodeURIComponent(model.id)}/policy` && request.method() === "PUT") {
      freeModelPolicyRequestBody = request.postDataJSON();
      if (freeModelPolicyRequestBody.expected_revision !== freeModelRevision) {
        return route.fulfill({ status: 409, contentType: "application/json", body: JSON.stringify({ error: { code: "assistant_model_policy_conflict", message: "Policy revision changed." } }) });
      }
      freeModelEnabled = freeModelPolicyRequestBody.enabled === true;
      freeModelRevision += 1;
      return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ model: { ...model, enabled: freeModelEnabled, usable: freeModelEnabled, revision: freeModelRevision } }) });
    }
    if (path === "/api/v1/assistant/providers/opencode-zen" && request.method() === "PUT") {
      zenProviderSaveBody = request.postDataJSON();
      zenSelectedModelId = zenProviderSaveBody.model_id;
      return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ provider: { provider_id: "opencode-zen", selected_model_id: zenSelectedModelId } }) });
    }
    if (path === "/api/v1/assistant/providers/openai" && request.method() === "PUT") {
      openAiProviderSaveBody = request.postDataJSON();
      openAiCredentialConfigured = typeof openAiProviderSaveBody.credential === "string";
      return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ provider: { provider_id: "openai", credential_configured: openAiCredentialConfigured } }) });
    }
    if (path === "/api/v1/assistant/providers/custom" && request.method() === "PUT") {
      customProviderSaveBody = request.postDataJSON();
      customProviderSaved = { ...customProviderSaveBody };
      return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ provider: { provider_id: "custom" } }) });
    }
    if (["/api/v1/assistant/providers/opencode-zen/validate", "/api/v1/assistant/providers/openai/validate"].includes(path) && request.method() === "POST") {
      validationCalled.push(path.includes("openai") ? "openai" : "opencode-zen");
      return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ provider: { provider_id: path.includes("openai") ? "openai" : "opencode-zen", connection_status: "ready" } }) });
    }
    if (path === "/api/v1/assistant/models/fixture-provider%2Fpaid-model/policy" && request.method() === "PUT") {
      policyRequestBody = request.postDataJSON();
      if (policyConflictOnce) {
        policyConflictOnce = false;
        paidModelRevision += 1;
        return route.fulfill({ status: 409, contentType: "application/json", body: JSON.stringify({ error: { code: "assistant_model_policy_conflict", message: "Policy revision changed." } }) });
      }
      paidModelEnabled = policyRequestBody.enabled === true;
      paidModelRevision += 1;
      return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ model: { ...paidModel, enabled: paidModelEnabled, usable: paidModelEnabled, revision: paidModelRevision } }) });
    }
    const values = {
      "/api/v1/auth/session": { authenticated: true, user: { id: 1, role: "admin", login: "fixture-admin" }, csrf_token: "fixture-csrf" },
      "/api/v1/auth/sessions": { sessions: [{ id: "current-session", current: true, last_seen_at: "2025-01-10T17:00:00Z", expires_at: "2025-01-11T17:00:00Z" }] },
      "/api/v1/auth/totp/status": { enrolled: true, recovery_codes_remaining: 8 },
      "/api/v1/auth/invites": { invitations: [], email_invites_enabled: false },
      "/api/v1/assistant/status": { ...status, enabled: false },
    };
    return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(values[path] ?? {}) });
  });

  await page.goto("/account#sessions");
  await expect(page.getByRole("heading", { name: "Active sessions" })).toBeFocused();
  await page.goto("/admin#invitations");
  await expect(page.locator("#invitations")).toBeFocused();
  await page.goto("/admin#backups");
  await expect(page.getByRole("heading", { name: "Verified backups" })).toBeFocused();
  await page.goto("/admin#restore");
  await expect(page.getByRole("heading", { name: "Promote a restore" })).toBeFocused();
  await page.goto("/admin#assistant-providers");
  await expect(page.locator("#assistant-providers")).toBeFocused();
  await expect(page.locator("#assistant-provider-url-opencode-zen")).toHaveCount(0);
  await expect(page.locator("#assistant-provider-secret-opencode-zen")).toHaveCount(0);
  const providersSection = page.locator("#assistant-providers");
  const zenProvider = providersSection.getByRole("article").filter({ has: page.getByRole("heading", { name: "OpenCode Zen" }) });
  const openAiProvider = providersSection.getByRole("article").filter({ has: page.getByRole("heading", { name: "OpenAI", exact: true }) });
  const customProvider = providersSection.getByRole("article").filter({ has: page.getByRole("heading", { name: "Custom compatible endpoint" }) });
  const zenValidate = zenProvider.getByRole("button", { name: "Validate provider" });
  const openAiValidate = openAiProvider.getByRole("button", { name: "Validate provider" });
  await expect(zenValidate).toBeDisabled();
  await expect(openAiValidate).toBeDisabled();
  const customSave = customProvider.getByRole("button", { name: "Save provider settings" });
  await expect(customSave).toBeDisabled();
  await expect(openAiProvider.getByRole("button", { name: "Save provider settings" })).toBeVisible();
  const policy = page.getByRole("article").filter({ has: page.getByRole("heading", { name: "Fixture Paid Model" }) });
  const approval = policy.getByRole("button", { name: "Approve this model" });
  await expect(approval).toBeDisabled();
  await page.getByLabel("Current authenticator code").fill("123456");
  await page.getByRole("button", { name: "Verify authenticator" }).click();
  await expect(zenProvider.getByRole("note").filter({ hasText: "Fresh authenticator verified for this session." })).toBeVisible();
  await expect(zenValidate).toBeEnabled();
  await expect(openAiValidate).toBeDisabled();
  const zenModelSelect = zenProvider.getByLabel("Provider default model");
  await zenModelSelect.selectOption(model.id);
  const zenSave = zenProvider.getByRole("button", { name: "Save provider settings" });
  await expect(zenSave).toBeEnabled();
  await zenSave.click();
  await expect.poll(() => zenProviderSaveBody).toEqual({ model_id: model.id });
  expect(zenProviderSaveBody).not.toHaveProperty("base_url");
  expect(zenProviderSaveBody).not.toHaveProperty("credential");
  await zenValidate.click();
  await expect.poll(() => validationCalled).toContain("opencode-zen");

  const openAiCredential = openAiProvider.getByLabel("New provider credential (write-only)");
  await openAiCredential.fill("test-only-synthetic-provider-value");
  await expect(openAiValidate).toBeDisabled();
  await expect.poll(() => openAiProviderSaveBody).toBeNull();

  await customProvider.getByLabel("Compatible HTTPS endpoint").fill("https://models.example.org/v1");
  await customProvider.getByLabel("Public provider terms URL").fill("https://terms.example.org/policy");
  await customProvider.getByLabel("Administrator-provided privacy disclosure (unverified)").fill("Administrator supplied synthetic privacy terms; details are unverified.");
  await customProvider.getByLabel("Administrator-provided billing disclosure (unverified)").fill("Billing is unknown until reviewed; this synthetic statement is unverified.");
  await expect(customSave).toBeDisabled();
  await customProvider.getByLabel("I reviewed this endpoint’s terms and administrator-provided statements.").check();
  await expect(customSave).toBeEnabled();
  await customSave.click();
  await expect.poll(() => customProviderSaveBody).toMatchObject({
    base_url: "https://models.example.org/v1",
    terms_url: "https://terms.example.org/policy",
    billing_class: "unknown",
    endpoint_policy_reviewed: true,
  });
  expect(customProviderSaveBody.privacy_disclosure).toContain("synthetic privacy terms");
  expect(customProviderSaveBody.billing_disclosure).toContain("Billing is unknown");
  expect(customProviderSaveBody).not.toHaveProperty("model_id");
  expect(customProviderSaveBody).not.toHaveProperty("credential");
  await expect(customProvider.getByRole("link", { name: "Administrator-provided terms (unverified)" })).toHaveAttribute("href", "https://terms.example.org/policy");
  await expect(customProvider.getByRole("note").filter({ hasText: "cannot confirm provider privacy" })).toBeVisible();
  await openAiProvider.getByRole("button", { name: "Save provider settings" }).click();
  await expect.poll(() => openAiProviderSaveBody).toMatchObject({ credential: "test-only-synthetic-provider-value" });
  expect(openAiProviderSaveBody).not.toHaveProperty("base_url");
  await expect(openAiValidate).toBeEnabled();
  await openAiValidate.click();
  await expect.poll(() => validationCalled).toContain("openai");
  openAiProviderSaveBody = null;
  await expect(approval).toBeDisabled();
  await policy.getByLabel(/privacy disclosure and version/).check();
  await expect(approval).toBeDisabled();
  await policy.getByLabel(/billing terms and cost disclosure/).check();
  await expect(approval).toBeEnabled();
  browserDiagnostics.expectHttpFailures({
    method: "PUT",
    path: "/api/v1/assistant/models/fixture-provider%2Fpaid-model/policy",
    status: 409,
  });
  await approval.click();
  await expect(page.locator("#assistant-providers > [role='alert']")).toContainText("policy changed in another session");
  await expect(policy.getByText(/Revision 8/)).toBeVisible();
  await expect(approval).toBeEnabled();
  await approval.click();
  await expect.poll(() => policyRequestBody).toMatchObject({
    enabled: true,
    acknowledged_privacy_policy_version: zenPrivacyPolicyVersion,
    acknowledged_billing_policy_version: "paid-billing-v2",
    expected_revision: 8,
  });
  await expect(policy.getByText("Enabled", { exact: true })).toBeVisible();

  const freePolicy = page.getByRole("article").filter({ has: page.getByRole("heading", { name: model.name }) });
  await freePolicy.getByRole("button", { name: "Disable this model" }).click();
  await expect(freePolicy.getByText("Disabled", { exact: true })).toBeVisible();
  const reapprove = freePolicy.getByRole("button", { name: "Approve this model" });
  await expect(reapprove).toBeDisabled();
  await freePolicy.getByLabel(/privacy disclosure and version/).check();
  await expect(reapprove).toBeDisabled();
  await freePolicy.getByLabel(/free availability and billing disclosure/).check();
  await expect(reapprove).toBeEnabled();
  await reapprove.click();
  await expect.poll(() => freeModelPolicyRequestBody).toMatchObject({
    enabled: true,
    acknowledged_privacy_policy_version: zenPrivacyPolicyVersion,
    acknowledged_billing_policy_version: zenBillingPolicyVersion,
    expected_revision: 5,
  });
  await expect(freePolicy.getByText("Enabled", { exact: true })).toBeVisible();
});

test("OpenCode catalog review and model approval stay owner-scoped and versioned", async ({ page, browserDiagnostics }) => {
  const consoleModelId = `opencode-console/${"c".repeat(64)}`;
  const baseModel = {
    model_id: consoleModelId,
    provider_id: "opencode-console",
    display_name: "Synthetic owner-scoped model",
    native_model_id: "fixture/model-v1",
    adapter_id: "openai-responses",
    protocol: "openai-responses",
    package_id: "@opencode/ai/providers/openai",
    endpoint: "https://api.example.test/v1",
    available: true,
    reviewed: false,
    billing_class: "unknown",
    training_policy: "unknown",
    confidential_data_policy: "unknown",
    terms_url: null,
    privacy_disclosure: null,
    billing_disclosure: null,
    privacy_policy_version: null,
    billing_policy_version: null,
    enabled: false,
    revision: 0,
    review_revision: 0,
    usable: false,
    availability_reason: "model_review_required",
    config_fingerprint: "d".repeat(64),
  };
  let row = { ...baseModel };
  let inventoryMode = "unavailable";
  let policyRevision = 0;
  let reviewRevision = 0;
  let reviewVersion = 0;
  const reviewRequests = [];
  const policyRequests = [];
  let clearRequest = null;
  browserDiagnostics.expectHttpFailures(
    { method: "GET", path: "/api/v1/assistant/providers/opencode/models", status: 409 },
    { method: "GET", path: "/api/v1/assistant/providers/opencode/models", status: 403 },
  );

  await page.route("**/api/v1/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;
    if (path === "/api/v1/auth/session") {
      return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ authenticated: true, user: { id: 7, role: "admin", login: "fixture-admin" }, csrf_token: "fixture-csrf" }) });
    }
    if (path === "/api/v1/auth/totp/step-up" && request.method() === "POST") {
      return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ verified: true }) });
    }
    if (path === "/api/v1/auth/totp/status") {
      return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ enrolled: true, recovery_codes_remaining: 8 }) });
    }
    if (path === "/api/v1/assistant/providers" && request.method() === "GET") {
      return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ providers: [] }) });
    }
    if (path === "/api/v1/assistant/models" && request.method() === "GET") {
      return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ items: [] }) });
    }
    if (path === "/api/v1/assistant/providers/oauth/methods") {
      return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ methods: [] }) });
    }
    if (path === "/api/v1/assistant/providers/oauth/attempts") {
      return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ attempts: [] }) });
    }
    if (path === "/api/v1/assistant/providers/oauth/connections") {
      return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ connections: [] }) });
    }
    if (path === "/api/v1/assistant/providers/opencode/models" && request.method() === "GET") {
      if (inventoryMode === "unavailable") {
        inventoryMode = "connection_required_reported";
        return route.fulfill({ status: 409, contentType: "application/json", body: JSON.stringify({ error: { code: "assistant_opencode_connection_required", message: "Connect this owner first." } }) });
      }
      if (inventoryMode === "denied") {
        inventoryMode = "ready";
        return route.fulfill({ status: 403, contentType: "application/json", body: JSON.stringify({ error: { code: "admin_step_up_required", message: "Fresh verification required." } }) });
      }
      return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ models: [row], unsupported_model_count: 2 }) });
    }
    if (path === `/api/v1/assistant/providers/opencode/models/${encodeURIComponent(consoleModelId)}/review` && request.method() === "PUT") {
      const body = request.postDataJSON();
      reviewRequests.push(body);
      if (body.expected_revision !== reviewRevision || body.expected_config_fingerprint !== row.config_fingerprint) {
        return route.fulfill({ status: 409, contentType: "application/json", body: JSON.stringify({ error: { code: "assistant_model_policy_conflict", message: "Review revision changed." } }) });
      }
      reviewVersion += 1;
      reviewRevision += 1;
      row = {
        ...row,
        reviewed: true,
        billing_class: body.billing_class,
        training_policy: body.training_policy,
        confidential_data_policy: body.confidential_data_policy,
        terms_url: body.terms_url,
        privacy_disclosure: body.privacy_disclosure,
        billing_disclosure: body.billing_disclosure,
        privacy_policy_version: `privacy-v${reviewVersion}`,
        billing_policy_version: `billing-v${reviewVersion}`,
        review_revision: reviewRevision,
        usable: false,
        availability_reason: "model_policy_ack_required",
      };
      return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ model: row }) });
    }
    if (path === `/api/v1/assistant/providers/opencode/models/${encodeURIComponent(consoleModelId)}/review` && request.method() === "DELETE") {
      clearRequest = { expected_revision: Number(url.searchParams.get("expected_revision")) };
      if (clearRequest.expected_revision !== reviewRevision) {
        return route.fulfill({ status: 409, contentType: "application/json", body: JSON.stringify({ error: { code: "assistant_model_policy_conflict", message: "Review revision changed." } }) });
      }
      reviewRevision += 1;
      policyRevision = 0;
      row = {
        ...baseModel,
        review_revision: reviewRevision,
        revision: policyRevision,
        availability_reason: "model_review_required",
      };
      return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ cleared: true }) });
    }
    if (path === `/api/v1/assistant/models/${encodeURIComponent(consoleModelId)}/policy` && request.method() === "PUT") {
      const body = request.postDataJSON();
      policyRequests.push(body);
      if (body.expected_revision !== policyRevision) {
        return route.fulfill({ status: 409, contentType: "application/json", body: JSON.stringify({ error: { code: "assistant_model_policy_conflict", message: "Policy revision changed." } }) });
      }
      if (body.enabled && (body.acknowledged_privacy_policy_version !== row.privacy_policy_version
        || body.acknowledged_billing_policy_version !== row.billing_policy_version)) {
        return route.fulfill({ status: 422, contentType: "application/json", body: JSON.stringify({ error: { code: "assistant_model_policy_ack_required", message: "Current policy acknowledgement required." } }) });
      }
      policyRevision += 1;
      row = {
        ...row,
        enabled: body.enabled,
        revision: policyRevision,
        usable: body.enabled,
        availability_reason: body.enabled ? null : "model_not_enabled",
      };
      return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ model: row }) });
    }
    const values = {
      "/api/v1/auth/sessions": { sessions: [] },
      "/api/v1/auth/invites": { invitations: [], email_invites_enabled: false },
      "/api/v1/operations/backups": { items: [] },
      "/api/v1/operations/backups/restore/preflight": { available: false },
      "/api/v1/assistant/status": { enabled: false, available: false },
    };
    return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(values[path] ?? {}) });
  });

  await page.goto("/admin#assistant-providers");
  const catalog = page.getByRole("region", { name: "This administrator’s OpenCode model catalog" });
  const refreshCatalog = catalog.getByRole("button", { name: "Refresh catalog" });
  await expect(refreshCatalog).toBeVisible();
  const refreshCatalogBounds = await refreshCatalog.boundingBox();
  expect(refreshCatalogBounds.width).toBeGreaterThanOrEqual(44);
  expect(refreshCatalogBounds.height).toBeGreaterThanOrEqual(44);
  await page.getByLabel("Current authenticator code").fill("123456");
  await page.getByRole("button", { name: "Verify authenticator" }).click();
  await expect(catalog.getByRole("status").filter({ hasText: "Connect the reviewed OpenCode device method" })).toBeVisible();
  inventoryMode = "ready";
  await catalog.getByRole("button", { name: "Refresh catalog" }).click();

  const card = catalog.getByRole("article").filter({ has: page.getByRole("heading", { name: baseModel.display_name }) });
  await expect(card).toBeVisible();
  await expect(catalog.getByText("model configuration entries use unsupported packages or settings", { exact: false })).toBeVisible();
  await expect(card.getByRole("note")).toContainText("unverified");
  await expect(card.getByText(/cannot be approved until its exact endpoint and administrator-reviewed terms/)).toBeVisible();
  await expect(card.getByRole("button", { name: "Approve this model" })).toHaveCount(0);

  await card.getByLabel("Public provider terms URL").fill("https://terms.example.com/fixture-model");
  await card.getByLabel("Administrator-provided privacy and data-use statement (unverified)").fill("Synthetic administrator privacy assessment. It is unverified.");
  await card.getByLabel("Administrator-provided billing statement (unverified)").fill("Synthetic administrator cost assessment. It is unverified.");
  await card.getByLabel("Administrator billing assessment").selectOption("paid");
  await card.getByLabel("Administrator training/data-use assessment").selectOption("no_training");
  await card.getByLabel("Administrator confidential-data assessment").selectOption("allowed");
  await card.getByLabel("I reviewed this exact endpoint, terms link, and administrator-provided statements.").check();
  await card.getByRole("button", { name: "Save administrator review" }).click();
  await expect.poll(() => reviewRequests).toHaveLength(1);
  expect(reviewRequests[0]).toMatchObject({
    endpoint_policy_reviewed: true,
    billing_class: "paid",
    training_policy: "no_training",
    confidential_data_policy: "allowed",
    expected_revision: 0,
    expected_config_fingerprint: baseModel.config_fingerprint,
  });
  expect(reviewRequests[0]).not.toHaveProperty("owner_id");
  await expect(page.getByRole("status").filter({ hasText: /Administrator-provided model review saved/ })).toBeVisible();

  const privacyAck = card.getByLabel("I reviewed this exact model’s current privacy statement and policy version.");
  const billingAck = card.getByLabel("I reviewed this exact model’s billing class and billing statement.");
  await privacyAck.check();
  await billingAck.check();
  const approve = card.getByRole("button", { name: "Approve this model" });
  await expect(approve).toBeEnabled();
  await approve.click();
  await expect.poll(() => policyRequests).toHaveLength(1);
  expect(policyRequests[0]).toMatchObject({
    enabled: true,
    acknowledged_privacy_policy_version: "privacy-v1",
    acknowledged_billing_policy_version: "billing-v1",
    expected_revision: 0,
  });
  await expect(card.getByText("Enabled", { exact: true })).toBeVisible();

  await card.getByLabel("Administrator-provided privacy and data-use statement (unverified)").fill("Changed synthetic privacy statement requiring fresh consent.");
  await card.getByLabel("I reviewed this exact endpoint, terms link, and administrator-provided statements.").check();
  await card.getByRole("button", { name: "Update administrator review" }).click();
  await expect.poll(() => reviewRequests).toHaveLength(2);
  await expect(card.getByRole("button", { name: "Reapprove this model" })).toBeDisabled();
  await expect(privacyAck).not.toBeChecked();
  await expect(billingAck).not.toBeChecked();
  await privacyAck.check();
  await billingAck.check();
  await card.getByRole("button", { name: "Reapprove this model" }).click();
  await expect.poll(() => policyRequests).toHaveLength(2);
  expect(policyRequests[1]).toMatchObject({
    enabled: true,
    acknowledged_privacy_policy_version: "privacy-v2",
    acknowledged_billing_policy_version: "billing-v2",
    expected_revision: 1,
  });

  await card.getByRole("button", { name: "Clear review…" }).click();
  await expect.poll(() => clearRequest).not.toBeNull();
  expect(clearRequest).toEqual({ expected_revision: 2 });
  await expect(card.getByText("Disabled", { exact: true })).toBeVisible();
  await card.getByLabel("Public provider terms URL").fill("https://terms.example.com/fixture-model");
  await card.getByLabel("Administrator-provided privacy and data-use statement (unverified)").fill("Re-reviewed synthetic privacy statement; unverified.");
  await card.getByLabel("Administrator-provided billing statement (unverified)").fill("Re-reviewed synthetic billing statement; unverified.");
  await card.getByLabel("Administrator billing assessment").selectOption("free");
  await card.getByLabel("Administrator training/data-use assessment").selectOption("training_possible");
  await card.getByLabel("Administrator confidential-data assessment").selectOption("allowed");
  await card.getByLabel("I reviewed this exact endpoint, terms link, and administrator-provided statements.").check();
  await card.getByRole("button", { name: "Save administrator review" }).click();
  await expect.poll(() => reviewRequests).toHaveLength(3);
  expect(reviewRequests[2]).toMatchObject({ expected_revision: 3, billing_class: "free", training_policy: "training_possible" });
  expect(reviewRequests[2]).not.toHaveProperty("owner_id");

  inventoryMode = "denied";
  await catalog.getByRole("button", { name: "Refresh catalog" }).click();
  await expect(catalog.getByText("Verify your authenticator to inspect this account’s private model catalog.")).toBeVisible();
  await expect(card).toHaveCount(0);
  await page.getByLabel("Current authenticator code").fill("123456");
  await page.getByRole("button", { name: "Verify authenticator" }).click();
  await expect(card).toBeVisible();
});

test("disabling context stays authoritative through preview refresh, conversation creation, and send", async ({ page }) => {
  const contextRequests = [];
  let conversationCreated = false;
  let creationContext = null;
  let turnContext = null;
  const createdConversation = {
    id: "conversation-context-1",
    title: "Instrument context check",
    revision: 1,
    created_at: "2025-01-10T17:00:00Z",
    updated_at: "2025-01-10T17:00:00Z",
  };
  const detail = {
    conversation: { ...createdConversation, delete_confirmation_phrase: "DELETE text-1" },
    messages: { items: [], page: 1, page_size: 50, total: 0 },
    turns: [],
    actions: [],
  };
  await page.route("**/api/v1/auth/session", (route) => route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify({ authenticated: true, user: { id: 1, role: "admin" }, csrf_token: "fixture-csrf" }),
  }));
  await page.route("**/api/v1/lists?kind=portfolio", (route) => route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify({ items: [] }),
  }));
  await page.route("**/api/v1/quotes?*", (route) => route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify({ items: [] }),
  }));
  await page.route("**/api/v1/assistant/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;
    if (path === "/api/v1/assistant/status") return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(status) });
    if (path === "/api/v1/assistant/models") return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ items: [model] }) });
    if (path === "/api/v1/assistant/context") {
      contextRequests.push(Object.fromEntries(url.searchParams.entries()));
      const includeInstrument = url.searchParams.has("symbol");
      const currentContext = {
        route: "/tools/live-trading",
        instrument: includeInstrument ? { symbol: "SPY", asset_type: "etf", provider: "Yahoo Finance", exchange: "ARCA", display_name: "SPDR S&P 500 ETF" } : null,
        event_ref: includeInstrument ? { id: 17, version: "event-v1" } : null,
        result_ref: includeInstrument ? { id: 21, version: "result-v1" } : null,
        context_version: includeInstrument ? "full-context-v1" : "route-context-v1",
      };
      return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({
        context: currentContext,
        preview: { summary: includeInstrument ? "Live Trading · SPY · ETF" : "Live Trading tool", fields: includeInstrument ? ["selected instrument", "saved event", "saved result"] : ["page route only"], note: "Only the selected fields are attached." },
      }) });
    }
    if (path === "/api/v1/assistant/conversations" && request.method() === "GET") {
      const items = conversationCreated ? [createdConversation] : [];
      return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ items, page: 1, page_size: 20, total: items.length }) });
    }
    if (path === "/api/v1/assistant/conversations" && request.method() === "POST") {
      creationContext = request.postDataJSON().context;
      conversationCreated = true;
      return route.fulfill({ status: 201, contentType: "application/json", body: JSON.stringify({ conversation: { conversation: createdConversation } }) });
    }
    if (path === "/api/v1/assistant/conversations/conversation-context-1" && request.method() === "GET") {
      return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(detail) });
    }
    if (path === "/api/v1/assistant/conversations/conversation-context-1/turns" && request.method() === "POST") {
      turnContext = request.postDataJSON().context;
      detail.messages.items = [{
        id: "assistant-message-context-1",
        turn_id: "turn-context-1",
        seq: 2,
        role: "assistant",
        text: "Synthetic research response from the local browser fixture.",
        created_at: "2025-01-10T17:02:00Z",
        sources: [],
      }];
      detail.messages.total = 1;
      detail.turns = [{ id: "turn-context-1", status: "completed", model_id: model.id, policy_version: model.policy_version, context_version: turnContext.context_version, context: turnContext, created_at: "2025-01-10T17:01:30Z", completed_at: "2025-01-10T17:02:00Z", actions: [] }];
      return route.fulfill({ status: 202, contentType: "application/json", body: JSON.stringify({ turn: { id: "turn-context-1", status: "running" } }) });
    }
    if (path === "/api/v1/assistant/conversations/conversation-context-1/turns/turn-context-1/events") {
      return route.fulfill({ status: 200, contentType: "text/event-stream", headers: { "Cache-Control": "no-store" }, body: 'id: 1\nevent: token\ndata: {"text":"Synthetic research response from the local browser fixture."}\n\nid: 2\nevent: complete\ndata: {"status":"completed"}\n\n' });
    }
    return route.fulfill({ status: 404, contentType: "application/json", body: JSON.stringify({ error: { code: "fixture_missing", message: "No assistant fixture route." } }) });
  });

  await page.goto("/tools/live-trading?symbol=SPY&asset_type=etf&provider=Yahoo%20Finance&exchange=ARCA&event_id=17&result_id=21");
  await page.getByRole("button", { name: "Open Ledger assistant" }).click();
  const panel = page.getByTestId("assistant-panel");
  await expect(panel).toBeVisible();
  await chooseFixtureModel(panel);
  await panel.getByText("Preview", { exact: true }).click();
  await expect(panel.getByText("SPDR S&P 500 ETF", { exact: false })).toBeVisible();
  await panel.getByLabel("Share selected references").uncheck();
  await panel.getByText("Preview", { exact: true }).click();
  await panel.getByRole("button", { name: "Refresh context preview" }).click();
  await expect(panel.getByText("Route only", { exact: true })).toBeVisible();
  const exactDetails = panel.locator("details");
  if (!(await exactDetails.evaluate((node) => node.open))) {
    await panel.getByText("Preview", { exact: true }).click();
  }
  await expect(panel.getByText("page route only", { exact: true })).toBeVisible();
  await chooseFixtureModel(panel);
  await panel.getByRole("textbox", { name: "Ask about this page" }).fill("Explain this page without private selections");
  await panel.getByRole("button", { name: "Send question" }).click();
  await expect.poll(() => turnContext).toMatchObject({
    route: "/tools/live-trading",
    instrument: null,
    event_ref: null,
    result_ref: null,
    context_version: "route-context-v1",
  });
  expect(creationContext).toEqual(turnContext);
  expect(contextRequests.at(-1)).toEqual({ route: "/tools/live-trading" });
  await expectAssistantLiveStatus(panel, "Assistant response complete.");
  await expect(panel.getByText("Synthetic research response from the local browser fixture.", { exact: true })).toBeVisible();
});

test("assistant keeps a terminal event provisional until the stream body reaches EOF", async ({ page }) => {
  const createdConversation = {
    id: "conversation-truncated-1",
    title: "Truncated stream check",
    revision: 1,
    created_at: "2025-01-10T17:00:00Z",
    updated_at: "2025-01-10T17:00:00Z",
  };
  let conversationDetails = 0;
  let releaseCompletionReload;
  let completionReloadStarted;
  const completionReloadRequested = new Promise((resolve) => { completionReloadStarted = resolve; });
  await page.addInitScript((fixtureModel) => {
    const originalFetch = window.fetch.bind(window);
    window.__assistantTerminalSent = false;
    window.__assistantStreamRequests = [];
    window.__failAssistantStreamBeforeEof = () => {};
    window.fetch = (input, init) => {
      const url = typeof input === "string" ? input : input instanceof Request ? input.url : String(input);
      if (!url.includes("/conversations/conversation-truncated-1/turns/")) {
        return originalFetch(input, init);
      }
      window.__assistantStreamRequests.push(url);
      const turnId = new URL(url, location.origin).pathname.split("/").at(-2);
      if (turnId === "turn-truncated-2") {
        const body = [
          [1, "meta", { model_id: fixtureModel.id, policy_version: fixtureModel.policy_version, context_version: "overview-context-v1" }],
          [2, "token", { text: "A new turn without terminal status." }],
        ].map(([id, event, data]) => `id: ${id}\nevent: ${event}\ndata: ${JSON.stringify(data)}\n\n`).join("");
        const finiteBody = new ReadableStream({
          start(controller) {
            controller.enqueue(new TextEncoder().encode(body));
            controller.close();
          },
        });
        return Promise.resolve(new Response(finiteBody, {
          status: 200,
          headers: { "Content-Type": "text/event-stream; charset=utf-8", "Cache-Control": "no-store" },
        }));
      }
      if (window.__assistantStreamRequests.length > 1) {
        return Promise.resolve(new Response("", {
          status: 200,
          headers: { "Content-Type": "text/event-stream; charset=utf-8", "Cache-Control": "no-store" },
        }));
      }
      const responseBody = new ReadableStream({
        start(controller) {
          const frames = [
            [1, "meta", { model_id: fixtureModel.id, policy_version: fixtureModel.policy_version, context_version: "overview-context-v1" }],
            [2, "token", { text: "Partial response before the truncated stream." }],
            [3, "complete", { status: "completed" }],
          ];
          const body = frames.map(([id, event, data]) => `id: ${id}\nevent: ${event}\ndata: ${JSON.stringify(data)}\n\n`).join("");
          controller.enqueue(new TextEncoder().encode(body));
          window.__assistantTerminalSent = true;
          window.__failAssistantStreamBeforeEof = () => controller.error(new TypeError("synthetic stream closed before EOF"));
        },
      });
      return Promise.resolve(new Response(responseBody, {
        status: 200,
        headers: { "Content-Type": "text/event-stream; charset=utf-8", "Cache-Control": "no-store" },
      }));
    };
  }, { id: model.id, policy_version: model.policy_version });
  await page.route("**/api/v1/auth/session", (route) => route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify({ authenticated: true, user: { id: 1, role: "admin" }, csrf_token: "fixture-csrf" }),
  }));
  await page.route("**/api/v1/assistant/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;
    if (path === "/api/v1/assistant/status") return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(status) });
    if (path === "/api/v1/assistant/models") return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ items: [model] }) });
    if (path === "/api/v1/assistant/context") return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ context: { ...context, route: "/overview", context_version: "overview-context-v1" }, preview: { summary: "Overview", fields: ["page route only"], note: "Route context." } }) });
    if (path === "/api/v1/assistant/conversations" && request.method() === "GET") return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ items: [createdConversation], page: 1, page_size: 20, total: 1 }) });
    if (path === "/api/v1/assistant/conversations" && request.method() === "POST") return route.fulfill({ status: 201, contentType: "application/json", body: JSON.stringify({ conversation: { conversation: createdConversation } }) });
    if (path === "/api/v1/assistant/conversations/conversation-truncated-1" && request.method() === "GET") {
      conversationDetails += 1;
      if (conversationDetails === 2) {
        completionReloadStarted();
        await new Promise((resolve) => { releaseCompletionReload = resolve; });
      }
      return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({
        conversation: { ...createdConversation, delete_confirmation_phrase: "DELETE ted-1" },
        messages: { items: [], page: 1, page_size: 50, total: 0 },
        turns: [],
        actions: [],
        action_pagination: { page: 1, page_size: 100, total: 0 },
        events: { items: [], page: 1, page_size: 100, total: 0 },
        event_pagination: { page: 1, page_size: 100, total: 0 },
      }) });
    }
    if (path === "/api/v1/assistant/conversations/conversation-truncated-1/turns" && request.method() === "POST") {
      const turnId = request.postDataJSON().prompt.includes("without a terminal") ? "turn-truncated-2" : "turn-truncated-1";
      return route.fulfill({ status: 202, contentType: "application/json", body: JSON.stringify({ turn: { id: turnId, status: "running" } }) });
    }
    return route.fulfill({ status: 404, contentType: "application/json", body: JSON.stringify({ error: { code: "fixture_missing", message: "No assistant fixture route." } }) });
  });

  await page.goto("/overview");
  await page.getByRole("button", { name: "Open Ledger assistant" }).click();
  const panel = page.getByTestId("assistant-panel");
  await chooseFixtureModel(panel);
  await panel.getByRole("textbox", { name: "Ask about this page" }).fill("Check that completion waits for EOF");
  await panel.getByRole("button", { name: "Send question" }).click();
  await expect.poll(() => page.evaluate(() => window.__assistantTerminalSent)).toBe(true);
  await expectAssistantLiveStatus(panel, "The assistant response is finishing.");
  await expectAssistantLiveStatusAbsent(panel, "Assistant response complete.");
  await page.evaluate(() => window.__failAssistantStreamBeforeEof());
  await expect(panel.getByRole("button", { name: "Reconnect to response" })).toBeVisible();
  await expectAssistantLiveStatus(panel, "The response connection was interrupted. Reconnect to replay events after the last received item.");
  await expectAssistantLiveStatusAbsent(panel, "Assistant response complete.");
  await expect(panel.getByRole("alert")).toContainText("synthetic stream closed before EOF");
  await panel.getByRole("button", { name: "Reconnect to response" }).click();
  await expectAssistantLiveStatus(panel, "Assistant response complete.");
  await completionReloadRequested;
  await expect(panel.getByRole("button", { name: "Send question" })).toBeDisabled();
  releaseCompletionReload();
  await expect(panel.getByText("Opening saved conversation…", { exact: true })).toHaveCount(0);
  await panel.getByRole("textbox", { name: "Ask about this page" }).fill("Start a new turn without a terminal event");
  await panel.getByRole("button", { name: "Send question" }).click();
  await expect(panel.getByRole("button", { name: "Reconnect to response" })).toBeVisible();
  await expectAssistantLiveStatus(panel, "The response stream ended without a completion event. Reconnect to continue.");
  await expectAssistantLiveStatusAbsent(panel, "Assistant response complete.");
  expect(await page.evaluate(() => window.__assistantStreamRequests.map((url) => new URL(url, location.origin).searchParams.get("after")))).toEqual(["0", "3", "0"]);
});

test("assistant ignores delayed conversation, pagination, and stream responses after switching history rows", async ({ page }) => {
  let releaseInitialA;
  let releaseOlderA;
  let initialAStarted;
  let olderAStarted;
  let holdInitialA = true;
  const initialARequest = new Promise((resolve) => { initialAStarted = resolve; });
  const olderARequest = new Promise((resolve) => { olderAStarted = resolve; });
  const summary = (id, title) => ({ id, title, revision: 1, created_at: "2025-01-10T17:00:00Z", updated_at: "2025-01-10T17:01:00Z", last_message_preview: title });
  const turn = { id: "turn-A", status: "running", model_id: model.id, policy_version: model.policy_version, context_version: context.context_version, context, created_at: "2025-01-10T17:00:00Z" };
  const detail = (id, text, { page = 1, total = 1, turns = [] } = {}) => ({
    conversation: { ...summary(id, id === "conversation-A" ? "A conversation" : "B conversation"), delete_confirmation_phrase: `DELETE ${id.slice(-1)}` },
    messages: { items: [{ id: `${id}-message-${page}`, turn_id: id === "conversation-A" ? "turn-A" : "turn-B", seq: page, role: "assistant", text, created_at: "2025-01-10T17:01:00Z", sources: [] }], page, page_size: 50, total },
    turns,
    actions: [],
    action_pagination: { page: 1, page_size: 100, total: 0 },
    events: { items: [], page: 1, page_size: 100, total: 0 },
  });
  const firstA = detail("conversation-A", "A latest page message", { total: 2, turns: [turn] });
  const oldA = detail("conversation-A", "STALE A older page must not appear in B", { page: 2, total: 2, turns: [turn] });
  const b = detail("conversation-B", "B selected conversation message");

  await page.addInitScript(() => {
    const originalFetch = window.fetch.bind(window);
    window.__assistantAStreamPending = false;
    window.__releaseAssistantAStream = undefined;
    window.fetch = (input, init) => {
      const url = typeof input === "string" ? input : input instanceof Request ? input.url : String(input);
      if (url.includes("/conversations/conversation-A/turns/turn-A/events")) {
        window.__assistantAStreamPending = true;
        return new Promise((resolve) => {
          window.__releaseAssistantAStream = () => resolve(new Response(
            'id: 1\nevent: token\ndata: {"text":"STALE A stream must not appear in B"}\n\nid: 2\nevent: complete\ndata: {"status":"completed"}\n\n',
            { status: 200, headers: { "content-type": "text/event-stream" } },
          ));
        });
      }
      return originalFetch(input, init);
    };
  });
  await page.route("**/api/v1/auth/session", (route) => route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify({ authenticated: true, user: { id: 1, role: "admin" }, csrf_token: "fixture-csrf" }),
  }));
  await page.route("**/api/v1/assistant/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;
    if (path === "/api/v1/assistant/status") return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(status) });
    if (path === "/api/v1/assistant/models") return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ items: [model] }) });
    if (path === "/api/v1/assistant/context") return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ context, preview: { summary: "Forecast workspace", fields: ["page route only"], note: "Route context." } }) });
    if (path === "/api/v1/assistant/conversations" && request.method() === "GET") return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ items: [summary("conversation-A", "A conversation"), summary("conversation-B", "B conversation")], page: 1, page_size: 20, total: 2 }) });
    if (path === "/api/v1/assistant/conversations/conversation-A" && request.method() === "GET") {
      if (url.searchParams.get("message_page") === "2") {
        olderAStarted();
        await new Promise((resolve) => { releaseOlderA = resolve; });
        return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(oldA) });
      }
      if (holdInitialA) {
        holdInitialA = false;
        initialAStarted();
        await new Promise((resolve) => { releaseInitialA = resolve; });
      }
      return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(firstA) });
    }
    if (path === "/api/v1/assistant/conversations/conversation-B" && request.method() === "GET") return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(b) });
    return route.fulfill({ status: 404, contentType: "application/json", body: JSON.stringify({ error: { code: "fixture_missing", message: "No assistant fixture route." } }) });
  });

  await page.goto("/overview");
  await page.getByRole("button", { name: "Open Ledger assistant" }).click();
  const panel = page.getByTestId("assistant-panel");
  await panel.getByRole("button", { name: "Open conversation history" }).click();
  await panel.getByRole("button", { name: /A conversation/ }).click();
  await initialARequest;
  await panel.getByRole("button", { name: /B conversation/ }).click();
  await expect(panel.getByText("B selected conversation message", { exact: true })).toBeVisible();
  releaseInitialA();
  await expect(panel.getByText("B selected conversation message", { exact: true })).toBeVisible();
  await expect(panel.getByText("A latest page message", { exact: true })).toHaveCount(0);

  await panel.getByRole("button", { name: "Open conversation history" }).click();
  await panel.getByRole("button", { name: /A conversation/ }).click();
  await expect(panel.getByText("A latest page message", { exact: true })).toBeVisible();
  await panel.getByRole("button", { name: "Load earlier messages" }).click();
  await olderARequest;
  await panel.getByRole("button", { name: "Open conversation history" }).click();
  await panel.getByRole("button", { name: /B conversation/ }).click();
  await expect(panel.getByText("B selected conversation message", { exact: true })).toBeVisible();
  releaseOlderA();
  await expect(panel.getByText("B selected conversation message", { exact: true })).toBeVisible();
  await expect(panel.getByText("STALE A older page must not appear in B", { exact: true })).toHaveCount(0);

  await panel.getByRole("button", { name: "Open conversation history" }).click();
  await panel.getByRole("button", { name: /A conversation/ }).click();
  await expect(panel.getByRole("button", { name: "Reconnect to response" })).toBeVisible();
  await panel.getByRole("button", { name: "Reconnect to response" }).click();
  await expect.poll(() => page.evaluate(() => window.__assistantAStreamPending)).toBe(true);
  await panel.getByRole("button", { name: "Open conversation history" }).click();
  await panel.getByRole("button", { name: /B conversation/ }).click();
  await expect(panel.getByText("B selected conversation message", { exact: true })).toBeVisible();
  await page.evaluate(() => window.__releaseAssistantAStream());
  await expect(panel.getByText("B selected conversation message", { exact: true })).toBeVisible();
  await expect(panel.getByText("STALE A stream must not appear in B", { exact: true })).toHaveCount(0);
});

test("real FastAPI assistant flow keeps route-only context and reopens durable proposal and tool receipts", async ({ page, assistantApplication, browserDiagnostics }, testInfo) => {
  const origin = assistantApplication.url;
  await page.context().addCookies([
    { name: "signal_ledger_session", value: "browser-assistant-fixture-session-not-a-production-credential", url: origin, httpOnly: true, sameSite: "Lax" },
    { name: "signal_ledger_csrf", value: "browser-assistant-fixture-csrf-token-not-a-production-credential", url: origin, sameSite: "Lax" },
  ]);
  const submitted = { creation: null, turn: null, consent: null, csrfHeaders: [] };
  const contextQueries = [];
  const conversationErrors = [];
  const streamRequestState = { responseCount: 0, networkOutcome: null, resolveNetworkOutcome: null };
  const streamNetworkOutcome = new Promise((resolve) => { streamRequestState.resolveNetworkOutcome = resolve; });
  const isAssistantEventsRequest = (request) => /^\/api\/v1\/assistant\/conversations\/[^/]+\/turns\/[^/]+\/events$/.test(new URL(request.url()).pathname);
  let eventStreamResponse = null;
  page.on("response", async (response) => {
    const url = new URL(response.url());
    if (/^\/api\/v1\/assistant\/conversations\/[^/]+\/turns\/[^/]+\/events$/.test(url.pathname)) {
      streamRequestState.responseCount += 1;
      eventStreamResponse = {
        url: response.url(),
        status: response.status(),
        contentType: (await response.allHeaders())["content-type"],
      };
    } else if (response.status() >= 400 && /^\/api\/v1\/assistant\/conversations\/[^/]+$/.test(url.pathname)) {
      const body = await response.json().catch(() => null);
      conversationErrors.push({ status: response.status(), code: body?.error?.code ?? null });
    }
  });
  page.on("requestfinished", (request) => {
    if (!isAssistantEventsRequest(request) || streamRequestState.networkOutcome) return;
    streamRequestState.networkOutcome = { kind: "finished", url: request.url(), error: null };
    streamRequestState.resolveNetworkOutcome(streamRequestState.networkOutcome);
  });
  page.on("requestfailed", (request) => {
    if (!isAssistantEventsRequest(request) || streamRequestState.networkOutcome) return;
    streamRequestState.networkOutcome = {
      kind: "failed",
      url: request.url(),
      error: request.failure()?.errorText || "unknown request failure",
    };
    streamRequestState.resolveNetworkOutcome(streamRequestState.networkOutcome);
  });
  page.on("request", (request) => {
    const url = new URL(request.url());
    if (url.origin !== origin || !url.pathname.startsWith("/api/v1/assistant/")) return;
    if (url.pathname === "/api/v1/assistant/context") contextQueries.push(Object.fromEntries(url.searchParams.entries()));
    if (request.method() === "PUT" && url.pathname.endsWith("/consent")) submitted.consent = request.postDataJSON();
    if (request.method() === "POST" && url.pathname === "/api/v1/assistant/conversations") submitted.creation = request.postDataJSON();
    if (request.method() === "POST" && /\/conversations\/[^/]+\/turns$/.test(url.pathname)) submitted.turn = request.postDataJSON();
    if (request.method() === "GET" && /\/conversations\/[^/]+\/turns\/[^/]+\/events$/.test(url.pathname)) submitted.eventStreamUrl = request.url();
    if (["POST", "PUT", "PATCH", "DELETE"].includes(request.method())) submitted.csrfHeaders.push(request.headers()["x-csrf-token"]);
  });

  await page.goto(`${origin}/overview`);
  const savedEventId = await page.evaluate(async () => {
    const response = await fetch("/api/v1/history");
    if (!response.ok) throw new Error(`History request failed: ${response.status}`);
    const payload = await response.json();
    return payload.items[0].id;
  });
  const fixtureStatus = await page.evaluate(async () => {
    const response = await fetch("/api/v1/assistant/status");
    return { status: response.status, body: await response.json() };
  });
  expect(fixtureStatus.status).toBe(200);
  expect(fixtureStatus.body).toMatchObject({ enabled: true, available: true, worker: { status: "ready" } });
  await page.goto(`${origin}/tools/live-trading?symbol=ACDC&asset_type=stock&provider=deterministic%20fixture&exchange=NMS&event_id=${savedEventId}`);
  const routeAuth = await page.evaluate(async () => {
    const [session, status] = await Promise.all([
      fetch("/api/v1/auth/session").then(async (response) => ({ status: response.status, body: await response.json() })),
      fetch("/api/v1/assistant/status").then(async (response) => ({ status: response.status, body: await response.json() })),
    ]);
    return { session, status };
  });
  expect(routeAuth.session).toMatchObject({ status: 200, body: { authenticated: true, user: { role: "admin" } } });
  expect(routeAuth.status).toMatchObject({ status: 200, body: { enabled: true } });
  await page.getByRole("button", { name: "Open Ledger assistant" }).click();
  const panel = page.getByTestId("assistant-panel");
  await expect(panel).toBeVisible();
  await chooseFixtureModel(panel);
  await panel.getByText("Preview", { exact: true }).click();
  await expect(panel.getByText(/ACDC · STOCK · NMS · deterministic fixture/)).toBeVisible();
  await expect(panel.getByText(`Saved event #${savedEventId}`, { exact: true })).toBeVisible();

  await panel.getByRole("checkbox", { name: /I accept this model's privacy terms/ }).check();
  await panel.getByRole("button", { name: "Save privacy choice" }).click();
  await expectAssistantLiveStatus(panel, "Model privacy consent saved for this policy version.");
  if (testInfo.project.name === "desktop-chromium") {
    await panel.getByRole("button", { name: "Expand assistant" }).click();
    await expect(panel.getByRole("button", { name: "Restore assistant size" })).toBeVisible();
  }
  await panel.getByLabel("Share selected references").uncheck();
  await panel.getByText("Preview", { exact: true }).click();
  await panel.getByRole("button", { name: "Refresh context preview" }).click();
  await expect(panel.getByText("Route only", { exact: true })).toBeVisible();
  const exactDetails = panel.locator("details");
  if (!(await exactDetails.evaluate((node) => node.open))) {
    await panel.getByText("Preview", { exact: true }).click();
  }
  await expect(panel.getByText("current route", { exact: true })).toBeVisible();
  await expect(panel.getByText(/ACDC · STOCK · NMS · deterministic fixture/)).toHaveCount(0);
  await panel.getByRole("textbox", { name: "Ask about this page" }).fill("Explain this page without selected references");
  await expect(panel.getByRole("button", { name: "Send question" })).toBeEnabled();
  await panel.getByRole("button", { name: "Send question" }).click();
  const completion = expect.poll(async () => {
    const transcript = await panel.innerText();
    if (transcript.includes("The assistant turn ended without a completed answer.")) {
      return `failed: ${assistantApplication.logs()}`;
    }
    if (conversationErrors.length) return `detail failed: ${JSON.stringify(conversationErrors)}`;
    return transcript.includes("Assistant response complete.")
      && transcript.includes("Synthetic research response from the local browser fixture.")
      ? "completed"
      : "pending";
  }).toBe("completed");
  try {
    await completion;
  } catch (error) {
    throw new Error(`${error instanceof Error ? error.message : "Assistant turn did not complete."}\nConversation errors ${JSON.stringify(conversationErrors)}\n${assistantApplication.logs()}`);
  }
  await expect.poll(() => eventStreamResponse).not.toBeNull();
  expect(eventStreamResponse).toMatchObject({
    url: submitted.eventStreamUrl,
    status: 200,
    contentType: "text/event-stream; charset=utf-8",
  });
  const streamAudit = await page.evaluate(async () => {
    const response = await fetch("/__qa/assistant-stream-audit", { cache: "no-store" });
    if (!response.ok) throw new Error(`SSE audit lookup failed: ${response.status}`);
    return response.json();
  });
  expect(streamAudit.items).toHaveLength(1);
  expect(streamAudit.items[0]).toMatchObject({
    path: new URL(submitted.eventStreamUrl).pathname,
    status: 200,
    complete_event: true,
    body_end: true,
    error: null,
  });
  expect(streamAudit.items[0].body_bytes).toBeGreaterThan(0);
  await expect(panel.getByRole("region", { name: "Preview: Change display theme" })).toBeVisible();
  await expect(panel.getByRole("heading", { name: "Research steps" })).toBeVisible();
  await expect(panel.getByText(/Receipt [0-9a-f]+ · \d+ bytes/)).toBeVisible();
  await expectAssistantLiveStatus(panel, "Assistant response complete.");
  await expect(panel.getByRole("button", { name: "Reconnect to response" })).toHaveCount(0);
  await expect(panel.getByRole("alert")).toHaveCount(0);
  await expect(panel.getByText("Synthetic research response from the local browser fixture.", { exact: true })).toBeVisible();

  expect(submitted.consent).toMatchObject({ policy_version: model.policy_version, accepted_terms: true, data_collection_opt_in: false });
  expect(submitted.creation.context).toMatchObject({ route: "/tools/live-trading", instrument: null, event_ref: null, result_ref: null });
  expect(submitted.turn.context).toMatchObject({ route: "/tools/live-trading", instrument: null, event_ref: null, result_ref: null });
  expect(contextQueries.at(-1)).toEqual({ route: "/tools/live-trading" });
  expect(submitted.csrfHeaders.length).toBeGreaterThanOrEqual(3);
  expect(submitted.csrfHeaders.every((value) => value === "browser-assistant-fixture-csrf-token-not-a-production-credential")).toBe(true);

  await panel.getByRole("button", { name: "Open conversation history" }).click();
  await panel.getByRole("button", { name: /Explain this page without selected references/ }).click();
  await expect(panel.getByText("Synthetic research response from the local browser fixture.", { exact: true })).toBeVisible();
  const reopenedProposal = panel.getByRole("region", { name: "Preview: Change display theme" });
  await expect(reopenedProposal).toBeVisible();
  await expect(panel.getByText(/Receipt [0-9a-f]+ · \d+ bytes/)).toBeVisible();
  const phrase = await reopenedProposal.locator("code").textContent();
  expect(phrase).toMatch(/^CONFIRM [a-f0-9]{8}$/);
  await reopenedProposal.getByRole("textbox").fill(phrase);
  const confirmButton = reopenedProposal.getByRole("button", { name: "Confirm change" });
  await confirmButton.scrollIntoViewIfNeeded();
  await confirmButton.click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await expect(panel.getByRole("region", { name: "Confirmed action receipts" })).toContainText("Change display theme · handed off");
  await expect(panel.getByRole("button", { name: "Reconnect to response" })).toHaveCount(0);
  await panel.getByRole("textbox", { name: "Ask about this page" }).fill("Ask a follow-up after reopening this conversation");
  await expect(panel.getByRole("button", { name: "Send question" })).toBeEnabled();
  expect(streamRequestState.responseCount).toBe(1);
  const networkOutcome = await Promise.race([
    streamNetworkOutcome,
    new Promise((resolve) => setTimeout(() => resolve(null), 3000)),
  ]);
  expect(networkOutcome).not.toBeNull();
  expect(new URL(networkOutcome.url).pathname).toBe(new URL(submitted.eventStreamUrl).pathname);
  if (networkOutcome.kind === "failed") {
    expect(networkOutcome.error).toBe("net::ERR_ABORTED");
    // This one-request classification follows terminal, EOF, server-end, and persistence checks.
    browserDiagnostics.expectRequestAborts({
      method: "GET",
      path: new URL(submitted.eventStreamUrl).pathname,
      count: 1,
    });
  } else {
    expect(networkOutcome.kind).toBe("finished");
  }
});

test("real FastAPI WebFetch preview shows the exact destination and binds one-time approval or decline", async ({ page, assistantApplication, browserDiagnostics }, testInfo) => {
  test.setTimeout(180_000);
  const origin = assistantApplication.url;
  const exactUrl = "https://example.com/research?fixture=browser-qa&view=research%2Fsummary";
  const confirmationRequests = [];
  const externalRequests = [];
  const eventStreamPaths = [];
  let baseContextResponse = null;
  page.on("request", (request) => {
    const url = new URL(request.url());
    if (url.origin === "https://example.com") externalRequests.push(url.href);
    if (/^\/api\/v1\/assistant\/conversations\/[^/]+\/turns\/[^/]+\/events$/.test(url.pathname)) {
      eventStreamPaths.push(url.pathname);
    }
    if (request.method() === "POST" && /\/webfetch-previews\/[0-9a-f]{32}\/confirm$/.test(url.pathname)) {
      confirmationRequests.push({ path: url.pathname, body: request.postDataJSON() });
    }
  });
  await page.route("**/api/v1/assistant/context**", async (route) => {
    const url = new URL(route.request().url());
    if (url.searchParams.get("symbol") === "MSFT") {
      if (!baseContextResponse) throw new Error("The initial workspace context was not captured before instrument selection.");
      const context = baseContextResponse.context;
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          ...baseContextResponse,
          context: {
            ...context,
            instrument: { symbol: "MSFT", asset_type: "stock", provider: "yahoo", exchange: "NASDAQ", display_name: "Microsoft" },
            context_version: "b".repeat(64),
          },
        }),
      });
    }
    const response = await route.fetch();
    if (!response.ok()) return route.fulfill({ response });
    const payload = await response.json();
    if (typeof payload?.context?.context_version === "string") baseContextResponse = payload;
    return route.fulfill({ response, body: JSON.stringify(payload) });
  });
  await page.context().addCookies([
    { name: "signal_ledger_session", value: "browser-assistant-fixture-session-not-a-production-credential", url: origin, httpOnly: true, sameSite: "Lax" },
    { name: "signal_ledger_csrf", value: "browser-assistant-fixture-csrf-token-not-a-production-credential", url: origin, sameSite: "Lax" },
  ]);
  await page.goto(`${origin}/overview`);
  await page.getByRole("button", { name: "Open Ledger assistant" }).click();
  const panel = page.getByTestId("assistant-panel");
  await expect(panel).toBeVisible();
  await chooseFixtureModel(panel);
  await panel.getByRole("checkbox", { name: /I accept this model's privacy terms/ }).check();
  await panel.getByRole("button", { name: "Save privacy choice" }).click();
  await expectAssistantLiveStatus(panel, "Model privacy consent saved for this policy version.");

  async function assertServerEndedStream(eventPath) {
    await expect.poll(async () => page.evaluate(async (path) => {
      const response = await fetch("/__qa/assistant-stream-audit", { cache: "no-store" });
      if (!response.ok) return null;
      const audit = await response.json();
      return audit.items?.some((item) => item.path === path) ?? false;
    }, eventPath), {
      message: "the fixture should record terminal SSE body completion for the exact turn",
    }).toBe(true);
    const auditItem = await page.evaluate(async (path) => {
      const response = await fetch("/__qa/assistant-stream-audit", { cache: "no-store" });
      if (!response.ok) return null;
      const audit = await response.json();
      return audit.items?.find((item) => item.path === path) ?? null;
    }, eventPath);
    expect(auditItem).toMatchObject({
      path: eventPath,
      status: 200,
      complete_event: true,
      body_end: true,
      error: null,
    });
    expect(auditItem.body_bytes).toBeGreaterThan(0);
    // The completion status is set after the reader reaches EOF; this also proves ASGI ended the body.
    browserDiagnostics.expectCompletedAssistantEventStream({ path: eventPath });
  }

  async function requestPreview(prompt, expectedAnswer, captureName, actionName) {
    const previousStreamCount = eventStreamPaths.length;
    const sendButton = panel.getByRole("button", { name: "Send question" });
    await panel.getByRole("textbox", { name: "Ask about this page" }).fill(prompt);
    await expect(sendButton).toBeEnabled();
    await sendButton.click();
    const card = panel.getByRole("region", { name: "Web page request confirmation" });
    try {
      await expect(card).toBeVisible();
    } catch (error) {
      const diagnostic = await page.evaluate(async (eventPath) => {
        const match = typeof eventPath === "string"
          ? eventPath.match(/^\/api\/v1\/assistant\/conversations\/([^/]+)\/turns\/([^/]+)\/events$/)
          : null;
        let audit = { items: [] };
        let turn = null;
        let eventTypes = [];
        for (let attempt = 0; attempt < 12; attempt += 1) {
          audit = await fetch("/__qa/assistant-stream-audit", { cache: "no-store" })
            .then((response) => response.json()).catch(() => ({ unavailable: true }));
          if (match) {
            const detail = await fetch(`/api/v1/assistant/conversations/${match[1]}?message_page=1&action_page=1&event_page=1`, { cache: "no-store" })
              .then((response) => response.json()).catch(() => null);
            turn = Array.isArray(detail?.turns)
              ? detail.turns.find((item) => item.id === match[2]) ?? null
              : null;
            eventTypes = Array.isArray(detail?.events?.items)
              ? detail.events.items.filter((item) => item.turn_id === match[2]).map((item) => item.type)
              : [];
          }
          if ((Array.isArray(audit.items) && audit.items.length) || turn?.status === "failed") break;
          await new Promise((resolve) => setTimeout(resolve, 100));
        }
        return {
          audit: Array.isArray(audit.items) ? audit.items.map(({ status, body_bytes, complete_event, body_end, error }) => ({ status, body_bytes, complete_event, body_end, error })) : audit,
          turn_status: turn?.status ?? null,
          turn_error_code: turn?.error_code ?? null,
          event_types: eventTypes,
        };
      }, eventStreamPaths.at(-1) ?? null);
      throw new Error(`${error instanceof Error ? error.message : "WebFetch preview did not appear."}\nSafe stream diagnostic ${JSON.stringify(diagnostic)}\n${assistantApplication.logs()}`);
    }
    await expect(card.getByRole("heading", { name: "Allow one request to this URL?" })).toBeVisible();
    await expect(card.getByText(/complete URL, including every query parameter/)).toBeVisible();
    await expect(card.locator("pre")).toHaveText(exactUrl);
    await expect(card.getByText(/Do not approve it if the URL contains a credential or private account information/)).toBeVisible();
    await expect(card.getByRole("link", { name: exactUrl })).toHaveCount(0);
    await expect(panel.getByRole("button", { name: "Approve exact URL once" })).toBeVisible();
    await expect(panel.getByRole("button", { name: "Decline request" })).toBeVisible();
    await expect.poll(() => eventStreamPaths.length).toBe(previousStreamCount + 1);
    const warning = card.getByText(/complete URL, including every query parameter/);
    const url = card.locator("pre");
    const action = card.getByRole("button", { name: actionName });
    await warning.scrollIntoViewIfNeeded();
    await expect(warning).toBeInViewport({ ratio: 0.9 });
    await page.screenshot({
      path: testInfo.outputPath(`${captureName}-warning-${testInfo.project.name}.png`),
      fullPage: false,
    });
    await action.scrollIntoViewIfNeeded();
    await expect(action).toBeInViewport({ ratio: 0.9 });
    await expect(url).toBeInViewport({ ratio: 0.8 });
    const urlVisibility = await url.evaluate((element, expectedText) => {
      const range = document.createRange();
      range.selectNodeContents(element);
      const textRects = Array.from(range.getClientRects());
      const viewport = { top: 0, right: window.innerWidth, bottom: window.innerHeight, left: 0 };
      const textLinesVisible = textRects.length > 0 && textRects.every((rect) =>
        rect.top >= viewport.top - 1 && rect.right <= viewport.right + 1
        && rect.bottom <= viewport.bottom + 1 && rect.left >= viewport.left - 1
      );
      const textLinesUnobscured = textRects.every((rect) => {
        const hit = document.elementFromPoint((rect.left + rect.right) / 2, (rect.top + rect.bottom) / 2);
        return hit === element || element.contains(hit);
      });
      return {
        exactText: element.textContent === expectedText,
        lineCount: textRects.length,
        textLinesVisible,
        textLinesUnobscured,
      };
    }, exactUrl);
    expect(urlVisibility).toMatchObject({
      exactText: true,
      textLinesVisible: true,
      textLinesUnobscured: true,
    });
    await page.screenshot({
      path: testInfo.outputPath(`${captureName}-url-and-action-${testInfo.project.name}.png`),
      fullPage: false,
    });
    return { card, expectedAnswer, eventPath: eventStreamPaths.at(-1) };
  }

  async function changeRoute(routeName) {
    await page.evaluate((path) => {
      const target = new URL(window.location.href);
      target.pathname = path;
      target.search = "";
      target.hash = "";
      window.history.pushState(window.history.state, "", `${target.pathname}${target.search}${target.hash}`);
      window.dispatchEvent(new PopStateEvent("popstate", { state: window.history.state }));
    }, routeName);
  }

  const approval = await requestPreview(
    "fixture webfetch approval",
    "Synthetic web page request was approved exactly once; no external request was made.",
    "webfetch-approval-preview",
    "Approve exact URL once",
  );
  await approval.card.getByRole("button", { name: "Approve exact URL once" }).click();
  await expect(panel.getByText(approval.expectedAnswer, { exact: true })).toBeVisible();
  await expectAssistantLiveStatus(panel, "Assistant response complete.");
  await expect(panel.getByRole("region", { name: "Web page request confirmation" })).toHaveCount(0);
  await panel.getByRole("textbox", { name: "Ask about this page" }).fill("Can I ask a follow-up after the approved request?");
  await expect(panel.getByRole("button", { name: "Send question" })).toBeEnabled();
  await panel.getByRole("textbox", { name: "Ask about this page" }).fill("");
  await assertServerEndedStream(approval.eventPath);
  await expectAssistantAxeClean(page, testInfo, "approved-preview");

  const staleContext = await requestPreview(
    "fixture webfetch stale context",
    "The old URL preview must not execute after instrument context changes.",
    "webfetch-stale-context-preview",
    "Approve exact URL once",
  );
  await page.evaluate(() => {
    const selected = new URL(window.location.href);
    selected.searchParams.set("symbol", "MSFT");
    selected.searchParams.set("asset_type", "stock");
    selected.searchParams.set("provider", "yahoo");
    selected.searchParams.set("exchange", "NASDAQ");
    window.history.replaceState(window.history.state, "", `${selected.pathname}${selected.search}${selected.hash}`);
    window.dispatchEvent(new Event("workspace-instrument-change"));
  });
  await expect(panel.getByRole("region", { name: "Workspace context" })).toContainText("MSFT · STOCK");
  await staleContext.card.getByRole("button", { name: "Approve exact URL once" }).click();
  await expect(staleContext.card).toHaveCount(0);
  await expect(panel.getByRole("alert")).toContainText("The page context changed after this URL preview. No URL was sent");
  expect(confirmationRequests).toHaveLength(1);
  const staleTurn = new URL(staleContext.eventPath, origin).pathname.match(/\/conversations\/([^/]+)\/turns\/([^/]+)\/events$/);
  expect(staleTurn).not.toBeNull();
  const staleActivity = await page.evaluate(async (conversationId) => {
    const response = await fetch(`/api/v1/assistant/conversations/${encodeURIComponent(conversationId)}?message_page=1&action_page=1&event_page=1`);
    if (!response.ok) throw new Error("The stale WebFetch turn activity could not be read.");
    const detail = await response.json();
    return (detail.events?.items ?? []).filter((item) => item.type === "tool")
      .map((item) => item.data?.name).filter((name) => typeof name === "string");
  }, staleTurn[1]);
  expect(staleActivity.some((name) => /web.?fetch/i.test(name))).toBe(false);
  browserDiagnostics.expectRequestAborts({ method: "GET", path: staleContext.eventPath, count: 1 });
  await panel.getByRole("button", { name: "Stop response" }).click();
  await expectAssistantLiveStatus(panel, "Response cancelled. Saved conversation history remains available.");

  await changeRoute("/overview");
  await expect(panel.getByRole("region", { name: "Workspace context" })).toContainText("Overview");
  await expect(panel.getByRole("region", { name: "Workspace context" })).not.toContainText("MSFT");
  const staleRouteContext = await requestPreview(
    "fixture webfetch stale route context",
    "The old URL preview must not execute after the workspace route changes.",
    "webfetch-stale-route-preview",
    "Approve exact URL once",
  );
  await changeRoute("/research");
  await expect(panel.getByRole("region", { name: "Workspace context" })).toContainText("Research");
  await staleRouteContext.card.getByRole("button", { name: "Approve exact URL once" }).click();
  await expect(staleRouteContext.card).toHaveCount(0);
  await expect(panel.getByRole("alert")).toContainText("The page context changed after this URL preview. No URL was sent");
  expect(confirmationRequests).toHaveLength(1);
  const staleRouteTurn = new URL(staleRouteContext.eventPath, origin).pathname.match(/\/conversations\/([^/]+)\/turns\/([^/]+)\/events$/);
  expect(staleRouteTurn).not.toBeNull();
  const staleRouteActivity = await page.evaluate(async (conversationId) => {
    const response = await fetch(`/api/v1/assistant/conversations/${encodeURIComponent(conversationId)}?message_page=1&action_page=1&event_page=1`);
    if (!response.ok) throw new Error("The stale route WebFetch turn activity could not be read.");
    const detail = await response.json();
    return (detail.events?.items ?? []).filter((item) => item.type === "tool")
      .map((item) => item.data?.name).filter((name) => typeof name === "string");
  }, staleRouteTurn[1]);
  expect(staleRouteActivity.some((name) => /web.?fetch/i.test(name))).toBe(false);
  browserDiagnostics.expectRequestAborts({ method: "GET", path: staleRouteContext.eventPath, count: 1 });
  await panel.getByRole("button", { name: "Stop response" }).click();
  await expectAssistantLiveStatus(panel, "Response cancelled. Saved conversation history remains available.");

  await changeRoute("/overview");
  await expect(panel.getByRole("region", { name: "Workspace context" })).toContainText("Overview");
  const decline = await requestPreview(
    "fixture webfetch stale decline",
    "Synthetic web page request was declined; no external request was made.",
    "webfetch-stale-decline-preview",
    "Decline request",
  );
  await changeRoute("/research");
  await expect(panel.getByRole("region", { name: "Workspace context" })).toContainText("Research");
  await decline.card.getByRole("button", { name: "Decline request" }).click();
  await expect(panel.getByText(decline.expectedAnswer, { exact: true })).toBeVisible();
  await expectAssistantLiveStatus(panel, "Assistant response complete.");
  await expect(panel.getByRole("region", { name: "Web page request confirmation" })).toHaveCount(0);
  await panel.getByRole("textbox", { name: "Ask about this page" }).fill("Can I ask after declining the request?");
  await expect(panel.getByRole("button", { name: "Send question" })).toBeEnabled();
  await panel.getByRole("textbox", { name: "Ask about this page" }).fill("");
  await assertServerEndedStream(decline.eventPath);

  const cancellation = await requestPreview(
    "fixture webfetch cancellation",
    "The active response should be cancelled before approval.",
    "webfetch-cancel-preview",
    "Approve exact URL once",
  );
  browserDiagnostics.expectRequestAborts({ method: "GET", path: cancellation.eventPath, count: 1 });
  await panel.getByRole("button", { name: "Stop response" }).click();
  await expectAssistantLiveStatus(panel, "Response cancelled. Saved conversation history remains available.");
  await panel.getByRole("textbox", { name: "Ask about this page" }).fill("Can I ask after cancelling the preview?");
  await expect(panel.getByRole("button", { name: "Send question" })).toBeEnabled();
  await panel.getByRole("textbox", { name: "Ask about this page" }).fill("");
  await expect(panel.getByRole("button", { name: "Stop response" })).toHaveCount(0);
  await expectAssistantAxeClean(page, testInfo, "cancelled-preview");

  expect(confirmationRequests).toHaveLength(2);
  expect(confirmationRequests[1].body).toMatchObject({ allow: false });
  expect(confirmationRequests[0].path).toMatch(/\/webfetch-previews\/[0-9a-f]{32}\/confirm$/);
  for (const [index, expectedAllow] of [true, false].entries()) {
    expect(confirmationRequests[index].body).toMatchObject({ allow: expectedAllow });
    expect(confirmationRequests[index].body.context_version).toMatch(/^[a-f0-9]{64}$/);
    expect(confirmationRequests[index].body.confirmation_phrase).toMatch(/^FETCH [a-f0-9]{8}$/);
    if (expectedAllow) {
      expect(confirmationRequests[index].body.context).toMatchObject({
        route: "/overview",
        context_version: confirmationRequests[index].body.context_version,
      });
    } else {
      expect(confirmationRequests[index].body).not.toHaveProperty("context");
    }
  }
  expect(eventStreamPaths).toHaveLength(5);
  expect(externalRequests).toEqual([]);
});

test("real FastAPI WebFetch approval and decline are keyboard operable with the exact URL visible", async ({ page, assistantApplication, browserDiagnostics }) => {
  const origin = assistantApplication.url;
  const exactUrl = "https://example.com/research?fixture=browser-qa&view=research%2Fsummary";
  const confirmationRequests = [];
  const externalRequests = [];
  const eventStreamPaths = [];
  page.on("request", (request) => {
    const url = new URL(request.url());
    if (url.origin === "https://example.com") externalRequests.push(url.href);
    if (/^\/api\/v1\/assistant\/conversations\/[^/]+\/turns\/[^/]+\/events$/.test(url.pathname)) {
      eventStreamPaths.push(url.pathname);
    }
    if (request.method() === "POST" && /\/webfetch-previews\/[0-9a-f]{32}\/confirm$/.test(url.pathname)) {
      confirmationRequests.push({ path: url.pathname, body: request.postDataJSON() });
    }
  });

  const panel = await openRealAssistant(page, origin);
  const composer = panel.getByRole("textbox", { name: "Ask about this page" });
  const send = panel.getByRole("button", { name: "Send question" });

  async function assertServerEndedStream(eventPath) {
    await expect.poll(async () => page.evaluate(async (path) => {
      const response = await fetch("/__qa/assistant-stream-audit", { cache: "no-store" });
      if (!response.ok) return null;
      const audit = await response.json();
      return audit.items?.some((item) => item.path === path) ?? false;
    }, eventPath), {
      message: "the fixture should record terminal SSE body completion for the exact turn",
    }).toBe(true);
    const auditItem = await page.evaluate(async (path) => {
      const response = await fetch("/__qa/assistant-stream-audit", { cache: "no-store" });
      if (!response.ok) return null;
      const audit = await response.json();
      return audit.items?.find((item) => item.path === path) ?? null;
    }, eventPath);
    expect(auditItem).toMatchObject({
      path: eventPath,
      status: 200,
      complete_event: true,
      body_end: true,
      error: null,
    });
    expect(auditItem.body_bytes).toBeGreaterThan(0);
    // The completion status is set after the reader reaches EOF; this also proves ASGI ended the body.
    browserDiagnostics.expectCompletedAssistantEventStream({ path: eventPath });
  }

  async function requestPreview(prompt, expectedAnswer) {
    const previousStreamCount = eventStreamPaths.length;
    await composer.fill(prompt);
    await composer.press("Tab");
    await expect(send).toBeFocused();
    await page.keyboard.press("Enter");

    const card = panel.getByRole("region", { name: "Web page request confirmation" });
    const url = card.locator("pre");
    const warning = card.getByRole("note");
    const decline = card.getByRole("button", { name: "Decline request" });
    const approve = card.getByRole("button", { name: "Approve exact URL once" });
    await expect(card.getByRole("heading", { name: "Allow one request to this URL?" })).toBeVisible();
    await expect(url).toHaveText(exactUrl);
    await expect(card.getByRole("link", { name: exactUrl })).toHaveCount(0);
    await expect(warning).toContainText("This complete URL, including every query parameter, will be sent to the destination website.");
    await expect(warning).toContainText("Do not approve it if the URL contains a credential or private account information.");
    await expect(card.getByText(/This approval applies only to the exact URL shown above\. It expires/)).toBeVisible();
    await expect(decline).toBeVisible();
    await expect(approve).toBeVisible();
    await expect(panel.getByRole("button", { name: "Stop response" })).toBeFocused();
    await warning.scrollIntoViewIfNeeded();
    await expect(warning).toBeInViewport({ ratio: 0.9 });
    await expect.poll(() => eventStreamPaths.length).toBe(previousStreamCount + 1);

    return { card, url, decline, approve, expectedAnswer, eventPath: eventStreamPaths.at(-1) };
  }

  async function expectExactUrlAndActionsUnobscured(card, url, decline, approve) {
    await expect(url).toBeInViewport({ ratio: 0.8 });
    await expect(decline).toBeInViewport({ ratio: 0.9 });
    await expect(approve).toBeInViewport({ ratio: 0.9 });
    const presentation = await card.evaluate((element, expectedUrl) => {
      const urlElement = element.querySelector("pre");
      if (!urlElement) return null;
      const range = document.createRange();
      range.selectNodeContents(urlElement);
      const lines = Array.from(range.getClientRects());
      const insideViewport = (rect) => rect.top >= -1 && rect.left >= -1
        && rect.bottom <= window.innerHeight + 1 && rect.right <= window.innerWidth + 1;
      const actions = Array.from(element.querySelectorAll("button")).map((button) => {
        const rect = button.getBoundingClientRect();
        const hit = document.elementFromPoint((rect.left + rect.right) / 2, (rect.top + rect.bottom) / 2);
        return {
          name: button.textContent.trim(),
          inViewport: insideViewport(rect),
          unobscured: hit === button || button.contains(hit),
          height: rect.height,
          minHeight: Number.parseFloat(getComputedStyle(button).minHeight),
        };
      });
      const linesUnobscured = lines.length > 0 && lines.every((rect) => {
        const hit = document.elementFromPoint((rect.left + rect.right) / 2, (rect.top + rect.bottom) / 2);
        return urlElement === hit || urlElement.contains(hit);
      });
      return {
        exactUrl: urlElement.textContent === expectedUrl,
        linesVisible: lines.length > 0 && lines.every(insideViewport),
        linesUnobscured,
        actions,
      };
    }, exactUrl);
    expect(presentation).not.toBeNull();
    expect(presentation).toMatchObject({ exactUrl: true, linesVisible: true, linesUnobscured: true });
    expect(presentation.actions.map((action) => action.name)).toEqual(["Decline request", "Approve exact URL once"]);
    expect(presentation.actions.every((action) => action.inViewport && action.unobscured && action.height >= 44 && action.minHeight >= 44)).toBe(true);
  }

  const approval = await requestPreview(
    "fixture webfetch approval",
    "Synthetic web page request was approved exactly once; no external request was made.",
  );
  await page.keyboard.press("Shift+Tab");
  await expect(approval.approve).toBeFocused();
  await expectExactUrlAndActionsUnobscured(approval.card, approval.url, approval.decline, approval.approve);
  await page.keyboard.press("Tab");
  await expect(panel.getByRole("button", { name: "Stop response" })).toBeFocused();
  await page.keyboard.press("Shift+Tab");
  await expect(approval.approve).toBeFocused();
  await page.keyboard.press("Space");
  await expect(panel.getByText(approval.expectedAnswer, { exact: true })).toBeVisible();
  await expectAssistantLiveStatus(panel, "Assistant response complete.");
  await expect(approval.card).toHaveCount(0);
  await assertServerEndedStream(approval.eventPath);
  await expect.poll(() => confirmationRequests.length).toBe(1);
  expect(confirmationRequests[0].path).toMatch(/\/webfetch-previews\/[0-9a-f]{32}\/confirm$/);
  expect(confirmationRequests[0].body).toMatchObject({ allow: true });
  expect(confirmationRequests[0].body.confirmation_phrase).toMatch(/^FETCH [a-f0-9]{8}$/);

  const decline = await requestPreview(
    "fixture webfetch decline",
    "Synthetic web page request was declined; no external request was made.",
  );
  await page.keyboard.press("Shift+Tab");
  await expect(decline.approve).toBeFocused();
  await expectExactUrlAndActionsUnobscured(decline.card, decline.url, decline.decline, decline.approve);
  await page.keyboard.press("Shift+Tab");
  await expect(decline.decline).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(panel.getByText(decline.expectedAnswer, { exact: true })).toBeVisible();
  await expectAssistantLiveStatus(panel, "Assistant response complete.");
  await expect(decline.card).toHaveCount(0);
  await assertServerEndedStream(decline.eventPath);
  await expect.poll(() => confirmationRequests.length).toBe(2);
  expect(confirmationRequests.map(({ body }) => body.allow)).toEqual([true, false]);
  expect(new Set(confirmationRequests.map(({ path }) => path)).size).toBe(2);
  for (const request of confirmationRequests) {
    expect(request.path).toMatch(/\/webfetch-previews\/[0-9a-f]{32}\/confirm$/);
    expect(request.body.context_version).toMatch(/^[a-f0-9]{64}$/);
    expect(request.body.confirmation_phrase).toMatch(/^FETCH [a-f0-9]{8}$/);
  }
  expect(eventStreamPaths).toHaveLength(2);
  expect(externalRequests).toEqual([]);
});

test("assistant readiness and policy changes recover without automatic consent or resend", async ({ page, browserDiagnostics }, testInfo) => {
  const collectedModel = {
    ...model,
    training: "data_collection",
    training_uses_data: true,
    consent: { accepted: true, data_collection_opt_in: true, accepted_at: "2025-01-01T00:00:00Z" },
  };
  const refreshedModel = {
    ...collectedModel,
    policy_version: `${collectedModel.policy_version}.browser-refresh`,
    privacy_policy_version: `${collectedModel.privacy_policy_version}.browser-refresh`,
    billing_policy_version: `${collectedModel.billing_policy_version}.browser-refresh`,
    consent: { accepted: false, data_collection_opt_in: false, accepted_at: null },
  };
  let readinessRecovered = false;
  let policyChanged = false;
  let conversationCreated = false;
  let turnRequests = 0;
  const consentRequests = [];
  const createdConversation = {
    id: "policy-refresh-conversation",
    title: "Policy refresh question",
    revision: 1,
    created_at: "2025-01-10T17:00:00Z",
    updated_at: "2025-01-10T17:00:00Z",
  };
  browserDiagnostics.expectHttpFailures({
    method: "POST",
    path: "/api/v1/assistant/conversations/policy-refresh-conversation/turns",
    status: 409,
  });
  await page.route("**/api/v1/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;
    let payload = { items: [], total: 0, page: 1, page_size: 20 };
    let responseStatus = 200;
    if (path === "/api/v1/auth/session") {
      payload = { authenticated: true, user: { id: 1, role: "admin", login: "browser-fixture" }, csrf_token: "fixture-csrf" };
    } else if (path === "/api/v1/assistant/status") {
      payload = readinessRecovered
        ? status
        : { ...status, available: false, worker: { status: "starting", reason: "The assistant worker is starting." } };
    } else if (path === "/api/v1/assistant/models") {
      payload = { items: [policyChanged ? refreshedModel : collectedModel] };
    } else if (path === "/api/v1/assistant/models/" + encodeURIComponent(model.id) + "/consent" && request.method() === "PUT") {
      consentRequests.push(request.postDataJSON());
      payload = { accepted: true };
    } else if (path === "/api/v1/assistant/context") {
      const routeName = url.searchParams.get("route") || "/";
      payload = { context: { ...context, route: routeName }, preview: { summary: "Current route only", fields: ["page route only"], note: "No selected references." } };
    } else if (path === "/api/v1/assistant/conversations" && request.method() === "GET") {
      const items = conversationCreated ? [{ ...createdConversation, last_message_preview: "No message was sent." }] : [];
      payload = { items, page: 1, page_size: 20, total: items.length };
    } else if (path === "/api/v1/assistant/conversations" && request.method() === "POST") {
      conversationCreated = true;
      payload = { conversation: { conversation: createdConversation } };
      responseStatus = 201;
    } else if (path === "/api/v1/assistant/conversations/policy-refresh-conversation") {
      payload = {
        conversation: { ...createdConversation, delete_confirmation_phrase: "DELETE refresh" },
        messages: { items: [], page: 1, page_size: 50, total: 0 },
        turns: [],
        actions: [],
        action_pagination: { page: 1, page_size: 100, total: 0 },
        events: { items: [], page: 1, page_size: 100, total: 0 },
        event_pagination: { page: 1, page_size: 100, total: 0 },
      };
    } else if (path === "/api/v1/assistant/conversations/policy-refresh-conversation/turns" && request.method() === "POST") {
      turnRequests += 1;
      policyChanged = true;
      payload = { error: { code: "policy_version", message: "The model policy changed." } };
      responseStatus = 409;
    }
    return route.fulfill({ status: responseStatus, contentType: "application/json", body: JSON.stringify(payload) });
  });

  await page.goto("/overview");
  await page.getByRole("button", { name: "Open Ledger assistant" }).click();
  const panel = page.getByTestId("assistant-panel");
  await expect(panel).toBeVisible();
  await expect(panel.locator('[data-ready="false"]')).toContainText("worker is starting");
  const readinessButton = panel.getByRole("button", { name: "Check readiness" });
  await expect(readinessButton).toBeEnabled();
  readinessRecovered = true;
  await readinessButton.click();
  await expect(panel.locator('[data-ready="true"]')).toBeVisible();

  await chooseFixtureModel(panel);
  await panel.getByRole("textbox", { name: "Ask about this page" }).fill("Keep this question while I review updated terms");
  const send = panel.getByRole("button", { name: "Send question" });
  await expect(send).toBeEnabled();
  await send.click();

  await expect(panel.getByRole("alert")).toContainText("model policy changed");
  await expect(panel.getByRole("checkbox", { name: /I accept this model's privacy terms/ })).not.toBeChecked();
  await expect(panel.getByRole("checkbox", { name: /I explicitly opt in to provider collection/ })).not.toBeChecked();
  await expect(panel.getByText(`I accept this model's privacy terms for policy ${refreshedModel.policy_version}.`, { exact: true })).toBeVisible();
  await expect(panel.getByRole("button", { name: "Save privacy choice" })).toBeDisabled();
  await expect(panel.getByRole("combobox", { name: "Assistant model" })).toHaveValue(model.id);
  await expect(panel.getByRole("textbox", { name: "Ask about this page" })).toHaveValue("Keep this question while I review updated terms");
  await expect(send).toBeDisabled();
  expect(turnRequests).toBe(1);
  expect(consentRequests).toEqual([]);
  if (testInfo.project.name === "mobile-chromium") {
    await expect(panel).toHaveAttribute("aria-modal", "true");
    const bounds = await panel.boundingBox();
    const viewportWidth = await page.evaluate(() => window.innerWidth);
    expect(bounds).not.toBeNull();
    expect(bounds.x).toBeGreaterThanOrEqual(-1);
    expect(bounds.x + bounds.width).toBeLessThanOrEqual(viewportWidth + 1);
  } else {
    await expect(panel).not.toHaveAttribute("aria-modal", "true");
  }
});

test("assistant automatically recovers a visible starting worker within its bounded window", async ({ page, browserDiagnostics }, testInfo) => {
  await installAssistantClock(page);
  let allowReady = false;
  let statusReads = 0;
  let turnPosts = 0;
  await page.route("**/api/v1/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;
    let payload = { items: [], total: 0, page: 1, page_size: 20 };
    if (path === "/api/v1/auth/session") {
      payload = { authenticated: true, user: { id: 1, role: "admin", login: "browser-fixture" }, csrf_token: "fixture-csrf" };
    } else if (path === "/api/v1/assistant/status") {
      statusReads += 1;
      payload = allowReady && statusReads >= 3
        ? status
        : { ...status, available: false, worker: { status: "starting", reason: "The assistant worker is starting." } };
    } else if (path === "/api/v1/assistant/models") {
      payload = { items: [model] };
    } else if (path === "/api/v1/assistant/context") {
      const routeName = url.searchParams.get("route") || "/";
      payload = { context: { ...context, route: routeName }, preview: { summary: "Current route only", fields: ["page route only"], note: "No selected references." } };
    } else if (path === "/api/v1/assistant/conversations" && request.method() === "GET") {
      payload = { items: [], page: 1, page_size: 20, total: 0 };
    } else if (/\/turns$/.test(path) && request.method() === "POST") {
      turnPosts += 1;
      payload = { error: { code: "unexpected_turn", message: "This readiness case must not send." } };
      return route.fulfill({ status: 409, contentType: "application/json", body: JSON.stringify(payload) });
    }
    return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(payload) });
  });

  await page.goto("/overview");
  await page.getByRole("button", { name: "Open Ledger assistant" }).click();
  const panel = page.getByTestId("assistant-panel");
  await expect(panel.locator('[data-ready="false"]')).toContainText("worker is starting");
  await expect(panel.getByRole("button", { name: "Check readiness" })).toBeVisible();
  allowReady = true;
  await page.clock.runFor(5_000);
  await expect(panel.locator('[data-ready="true"]')).toBeVisible();
  await expect(panel.getByRole("button", { name: "Check readiness" })).toHaveCount(0);
  expect(statusReads).toBe(3);
  expect(turnPosts).toBe(0);
  if (testInfo.project.name === "mobile-chromium") await expect(panel).toHaveAttribute("aria-modal", "true");
});

test("assistant recovers the real worker-unavailable turn response without resending", async ({ page, browserDiagnostics }) => {
  await installAssistantClock(page);
  let statusReads = 0;
  let turnPosts = 0;
  let failNewConversation = false;
  const conversation = {
    id: "worker-recovery-conversation",
    title: "Worker recovery question",
    revision: 1,
    created_at: "2025-01-10T17:00:00Z",
    updated_at: "2025-01-10T17:00:00Z",
  };
  browserDiagnostics.expectHttpFailures({
    method: "POST",
    path: "/api/v1/assistant/conversations/worker-recovery-conversation/turns",
    status: 503,
    count: 2,
  });
  browserDiagnostics.expectHttpFailures({ method: "GET", path: "/api/v1/assistant/context", status: 503, count: 2 });
  browserDiagnostics.expectHttpFailures({ method: "POST", path: "/api/v1/assistant/conversations", status: 503 });
  let failContextRefresh = false;
  let holdContextRecovery = false;
  let releaseContextRecovery = () => {};
  let contextRecoveryGate = Promise.resolve();
  const holdNextContextRecovery = () => {
    holdContextRecovery = true;
    contextRecoveryGate = new Promise((resolve) => { releaseContextRecovery = resolve; });
  };
  await page.route("**/api/v1/**", async (route) => {
    const request = route.request();
    const { pathname } = new URL(request.url());
    let payload = { items: [], total: 0, page: 1, page_size: 20 };
    let responseStatus = 200;
    if (pathname === "/api/v1/auth/session") {
      payload = { authenticated: true, user: { id: 1, role: "admin", login: "browser-fixture" }, csrf_token: "fixture-csrf" };
    } else if (pathname === "/api/v1/assistant/status") {
      statusReads += 1;
      payload = statusReads === 2 || statusReads === 4
        ? { ...status, available: false, worker: { status: "starting", reason: "The assistant worker is starting." } }
        : status;
    } else if (pathname === "/api/v1/assistant/models") {
      payload = { items: [model] };
    } else if (pathname === "/api/v1/assistant/context") {
      const routeName = new URL(request.url()).searchParams.get("route") || "/";
      if (failContextRefresh) {
        payload = { error: { code: "assistant_worker_unavailable", message: "The assistant worker is unavailable." } };
        responseStatus = 503;
      } else {
        if (holdContextRecovery) {
          holdContextRecovery = false;
          await contextRecoveryGate;
        }
        payload = { context: { ...context, route: routeName }, preview: { summary: "Current route only", fields: ["page route only"], note: "No selected references." } };
      }
    } else if (pathname === "/api/v1/assistant/conversations" && request.method() === "GET") {
      payload = { items: [], page: 1, page_size: 20, total: 0 };
    } else if (pathname === "/api/v1/assistant/conversations" && request.method() === "POST") {
      if (failNewConversation) {
        payload = { error: { code: "assistant_worker_unavailable", message: "The assistant worker is unavailable." } };
        responseStatus = 503;
      } else {
        payload = { conversation: { conversation } };
        responseStatus = 201;
      }
    } else if (pathname === `/api/v1/assistant/conversations/${conversation.id}` && request.method() === "GET") {
      payload = {
        conversation: { ...conversation, delete_confirmation_phrase: "DELETE worker" },
        messages: { items: [], page: 1, page_size: 50, total: 0 },
        turns: [],
        actions: [],
        action_pagination: { page: 1, page_size: 100, total: 0 },
        events: { items: [], page: 1, page_size: 100, total: 0 },
        event_pagination: { page: 1, page_size: 100, total: 0 },
      };
    } else if (pathname === "/api/v1/assistant/conversations/worker-recovery-conversation/turns" && request.method() === "POST") {
      turnPosts += 1;
      payload = { error: { code: "assistant_worker_unavailable", message: "The assistant worker is unavailable." } };
      responseStatus = 503;
    }
    return route.fulfill({ status: responseStatus, contentType: "application/json", body: JSON.stringify(payload) });
  });

  await page.goto("/overview");
  await page.getByRole("button", { name: "Open Ledger assistant" }).click();
  const panel = page.getByTestId("assistant-panel");
  await expect(panel.locator('[data-ready="true"]')).toBeVisible();
  await chooseFixtureModel(panel);
  const prompt = "Keep this question while the assistant worker recovers.";
  await panel.getByRole("textbox", { name: "Ask about this page" }).fill(prompt);
  await panel.getByRole("button", { name: "Send question" }).click();

  await expect(panel.getByRole("alert")).toHaveText("The assistant worker is unavailable. Your workspace remains available.");
  await expect(panel.getByRole("alert")).toHaveCount(1);
  await expect(panel.locator('[data-ready="false"]')).toContainText("worker is starting");
  await expect(panel.getByRole("textbox", { name: "Ask about this page" })).toHaveValue(prompt);
  expect(turnPosts).toBe(1);
  expect(statusReads).toBe(2);

  await page.clock.runFor(5_000);
  await expect(panel.locator('[data-ready="true"]')).toBeVisible();
  await expect(panel.getByRole("alert")).toHaveCount(0);
  await expect(panel.getByRole("textbox", { name: "Ask about this page" })).toHaveValue(prompt);
  await expect(panel.getByRole("button", { name: "Send question" })).toBeEnabled();
  expect(turnPosts).toBe(1);
  expect(statusReads).toBe(3);

  await panel.getByRole("button", { name: "Send question" }).click();
  await expect(panel.getByRole("alert")).toHaveText("The assistant worker is unavailable. Your workspace remains available.");
  await expect(panel.getByRole("alert")).toHaveCount(1);
  await expect(panel.locator('[data-ready="false"]')).toContainText("worker is starting");
  expect(turnPosts).toBe(2);
  expect(statusReads).toBe(4);
  failContextRefresh = true;
  const shareSelectedReferences = panel.getByRole("checkbox", { name: "Share selected references" });
  await shareSelectedReferences.focus();
  await expect(shareSelectedReferences).toBeFocused();
  await shareSelectedReferences.press("Space");
  await expect(panel.getByRole("alert")).toHaveText("The assistant worker is unavailable. Your workspace remains available.");
  await expect(panel.getByRole("alert")).toHaveCount(1);
  await expect(shareSelectedReferences).toHaveCount(1);
  await expect(shareSelectedReferences).not.toBeChecked();
  await expect(shareSelectedReferences).toBeFocused();
  const refreshContext = panel.getByRole("button", { name: "Refresh context preview" });
  await expect(refreshContext).toBeVisible();
  await expect(refreshContext).toBeEnabled();
  await page.clock.runFor(5_000);
  await expect(panel.locator('[data-ready="true"]')).toBeVisible();
  await expect(panel.getByRole("alert")).toHaveText("The assistant worker is unavailable. Your workspace remains available.");
  await expect(panel.getByRole("alert")).toHaveCount(1);
  await expect(panel.getByRole("textbox", { name: "Ask about this page" })).toHaveValue(prompt);
  expect(turnPosts).toBe(2);
  expect(statusReads).toBe(5);

  failContextRefresh = false;
  holdNextContextRecovery();
  await refreshContext.focus();
  await refreshContext.press("Enter");
  await expect(panel.getByText("Checking safe workspace context…")).toBeVisible();
  await expect(refreshContext).toBeFocused();
  await expect(shareSelectedReferences).toHaveCount(1);

  releaseContextRecovery();
  await expect(panel.getByText("Checking safe workspace context…")).toHaveCount(0);
  await expect(panel.getByRole("alert")).toHaveCount(0);
  await expect(refreshContext).toBeFocused();
  await expect(shareSelectedReferences).not.toBeChecked();
  await expect(panel.getByRole("textbox", { name: "Ask about this page" })).toHaveValue(prompt);
  await expect(panel.getByRole("button", { name: "Send question" })).toBeEnabled();
  await expect(panel.getByText("Worker recovery question", { exact: true })).toBeVisible();
  expect(turnPosts).toBe(2);
  expect(statusReads).toBe(5);

  failContextRefresh = true;
  await refreshContext.press("Enter");
  await expect(panel.getByRole("alert")).toHaveText("The assistant worker is unavailable. Your workspace remains available.");
  await expect(panel.getByRole("alert")).toHaveCount(1);
  await expect(shareSelectedReferences).not.toBeChecked();
  await expect(panel.getByRole("textbox", { name: "Ask about this page" })).toHaveValue(prompt);
  expect(turnPosts).toBe(2);

  failContextRefresh = false;
  holdNextContextRecovery();
  await refreshContext.focus();
  await refreshContext.press("Enter");
  await expect(panel.getByText("Checking safe workspace context…")).toBeVisible();
  await expect(refreshContext).toBeFocused();
  await expect(shareSelectedReferences).toHaveCount(1);

  await panel.getByRole("button", { name: "Open conversation history" }).click();
  const newConversation = panel.getByRole("button", { name: "New conversation" });
  await expect(newConversation).toBeVisible();
  failNewConversation = true;
  const failedNewConversation = page.waitForResponse((response) => (
    new URL(response.url()).pathname === "/api/v1/assistant/conversations"
      && response.request().method() === "POST"
      && response.status() === 503
  ));
  await newConversation.click();
  await failedNewConversation;
  await expect(panel.getByRole("alert")).toHaveText("The assistant worker is unavailable. Your workspace remains available.");
  await expect(panel.getByText("Worker recovery question", { exact: true })).toBeVisible();
  await expect(panel.getByRole("textbox", { name: "Ask about this page" })).toHaveValue(prompt);
  failNewConversation = false;
  await refreshContext.focus();
  await expect(refreshContext).toBeFocused();

  releaseContextRecovery();
  await expect(panel.getByText("Checking safe workspace context…")).toHaveCount(0);
  await expect(panel.getByRole("alert")).toHaveText("The assistant worker is unavailable. Your workspace remains available.");
  await expect(panel.getByRole("alert")).toHaveCount(1);
  await expect(refreshContext).toBeFocused();
  await expect(shareSelectedReferences).not.toBeChecked();
  await expect(panel.getByRole("textbox", { name: "Ask about this page" })).toHaveValue(prompt);
  await expect(panel.getByRole("button", { name: "Send question" })).toBeEnabled();
  await expect(panel.getByText("Worker recovery question", { exact: true })).toBeVisible();
  expect(turnPosts).toBe(2);
});

test("assistant readiness polling stops after six checks", async ({ page }) => {
  await installAssistantClock(page);
  let statusReads = 0;
  await page.route("**/api/v1/**", async (route) => {
    const request = route.request();
    const { pathname } = new URL(request.url());
    let payload = { items: [], total: 0, page: 1, page_size: 20 };
    if (pathname === "/api/v1/auth/session") {
      payload = { authenticated: true, user: { id: 1, role: "admin", login: "browser-fixture" }, csrf_token: "fixture-csrf" };
    } else if (pathname === "/api/v1/assistant/status") {
      statusReads += 1;
      payload = { ...status, available: false, worker: { status: "starting", reason: "The assistant worker is starting." } };
    } else if (pathname === "/api/v1/assistant/models") {
      payload = { items: [model] };
    } else if (pathname === "/api/v1/assistant/context") {
      payload = { context, preview: { summary: "Current route only", fields: ["page route only"], note: "No selected references." } };
    } else if (pathname === "/api/v1/assistant/conversations" && request.method() === "GET") {
      payload = { items: [], page: 1, page_size: 20, total: 0 };
    }
    return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(payload) });
  });

  await page.goto("/overview");
  await page.getByRole("button", { name: "Open Ledger assistant" }).click();
  const panel = page.getByTestId("assistant-panel");
  await expect(panel.locator('[data-ready="false"]')).toContainText("worker is starting");
  await expect.poll(() => statusReads).toBe(2);
  for (let nextRead = 3; nextRead <= 7; nextRead += 1) {
    await page.clock.runFor(5_000);
    await expect.poll(() => statusReads).toBe(nextRead);
    await expect(panel.getByRole("button", { name: "Check readiness" })).toBeEnabled();
  }
  expect(statusReads).toBe(7);
  await page.clock.runFor(30_000);
  expect(statusReads).toBe(7);
});

test("assistant readiness polling stops when the worker is disabled", async ({ page }) => {
  await installAssistantClock(page);
  let statusReads = 0;
  await page.route("**/api/v1/**", async (route) => {
    const request = route.request();
    const { pathname } = new URL(request.url());
    let payload = { items: [], total: 0, page: 1, page_size: 20 };
    if (pathname === "/api/v1/auth/session") {
      payload = { authenticated: true, user: { id: 1, role: "admin", login: "browser-fixture" }, csrf_token: "fixture-csrf" };
    } else if (pathname === "/api/v1/assistant/status") {
      statusReads += 1;
      payload = statusReads === 1
        ? { ...status, available: false, worker: { status: "starting", reason: "The assistant worker is starting." } }
        : { ...status, enabled: false, available: false, worker: { status: "stopped", reason: "Assistant is disabled." } };
    } else if (pathname === "/api/v1/assistant/models") {
      payload = { items: [model] };
    } else if (pathname === "/api/v1/assistant/context") {
      payload = { context, preview: { summary: "Current route only", fields: ["page route only"], note: "No selected references." } };
    } else if (pathname === "/api/v1/assistant/conversations" && request.method() === "GET") {
      payload = { items: [], page: 1, page_size: 20, total: 0 };
    }
    return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(payload) });
  });

  await page.goto("/overview");
  await page.getByRole("button", { name: "Open Ledger assistant" }).click();
  const disabledPanel = page.getByTestId("assistant-panel");
  await expect.poll(() => statusReads).toBe(2);
  await expect(disabledPanel.locator('[data-ready="false"]')).toContainText("disabled");
  await expect(disabledPanel.getByRole("button", { name: "Check readiness" })).toHaveCount(0);
  expect(statusReads).toBe(2);
  await page.clock.runFor(30_000);
  expect(statusReads).toBe(2);
});

test("assistant readiness pauses while hidden and ignores an aborted obsolete status response", async ({ page, browserDiagnostics }) => {
  await installAssistantClock(page);
  let statusReads = 0;
  let makeReadyOnNextRead = false;
  let releaseStaleResponse;
  const staleResponseGate = new Promise((resolve) => { releaseStaleResponse = resolve; });
  await page.route("**/api/v1/**", async (route) => {
    const request = route.request();
    const { pathname } = new URL(request.url());
    let payload = { items: [], total: 0, page: 1, page_size: 20 };
    if (pathname === "/api/v1/auth/session") {
      payload = { authenticated: true, user: { id: 1, role: "admin", login: "browser-fixture" }, csrf_token: "fixture-csrf" };
    } else if (pathname === "/api/v1/assistant/status") {
      statusReads += 1;
      if (statusReads === 2) {
        await staleResponseGate;
        try {
          return await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ ...status, available: false, worker: { status: "starting", reason: "The assistant worker is starting." } }) });
        } catch {
          return;
        }
      }
      payload = makeReadyOnNextRead && statusReads >= 3
        ? status
        : { ...status, available: false, worker: { status: "starting", reason: "The assistant worker is starting." } };
    } else if (pathname === "/api/v1/assistant/models") {
      payload = { items: [model] };
    } else if (pathname === "/api/v1/assistant/context") {
      payload = { context, preview: { summary: "Current route only", fields: ["page route only"], note: "No selected references." } };
    } else if (pathname === "/api/v1/assistant/conversations" && request.method() === "GET") {
      payload = { items: [], page: 1, page_size: 20, total: 0 };
    }
    return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(payload) });
  });

  await page.goto("/overview");
  await page.getByRole("button", { name: "Open Ledger assistant" }).click();
  const panel = page.getByTestId("assistant-panel");
  await expect.poll(() => statusReads).toBe(2);
  browserDiagnostics.expectRequestAborts({ method: "GET", path: "/api/v1/assistant/status", count: 1 });
  await page.evaluate(() => {
    Object.defineProperty(document, "visibilityState", { configurable: true, value: "hidden" });
    document.dispatchEvent(new Event("visibilitychange"));
  });
  await page.clock.runFor(15_000);
  expect(statusReads).toBe(2);

  makeReadyOnNextRead = true;
  await page.evaluate(() => {
    Object.defineProperty(document, "visibilityState", { configurable: true, value: "visible" });
    document.dispatchEvent(new Event("visibilitychange"));
  });
  await expect(panel.locator('[data-ready="true"]')).toBeVisible();
  expect(statusReads).toBe(3);
  releaseStaleResponse();
  await page.clock.runFor(10_000);
  await expect(panel.locator('[data-ready="true"]')).toBeVisible();
  await expect(panel.getByRole("button", { name: "Check readiness" })).toHaveCount(0);
  expect(statusReads).toBe(3);
});

test("assistant host readiness supersedes a late non-ready panel response", async ({ page, browserDiagnostics }) => {
  await installAssistantClock(page);
  let statusReads = 0;
  let routeRefreshPending = false;
  let routeStatusRefreshReads = 0;
  let readyHostStatusResponses = 0;
  let otherStatusReadsAfterRoute = 0;
  let releaseStaleResponse;
  const staleResponseGate = new Promise((resolve) => { releaseStaleResponse = resolve; });
  await page.route("**/api/v1/**", async (route) => {
    const request = route.request();
    const { pathname } = new URL(request.url());
    let payload = { items: [], total: 0, page: 1, page_size: 20 };
    if (pathname === "/api/v1/auth/session") {
      payload = { authenticated: true, user: { id: 1, role: "admin", login: "browser-fixture" }, csrf_token: "fixture-csrf" };
    } else if (pathname === "/api/v1/assistant/status") {
      statusReads += 1;
      if (statusReads === 2) {
        await staleResponseGate;
        try {
          return await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ ...status, available: false, worker: { status: "starting", reason: "The assistant worker is starting." } }) });
        } catch {
          return;
        }
      }
      if (routeRefreshPending) {
        routeRefreshPending = false;
        routeStatusRefreshReads += 1;
        readyHostStatusResponses += 1;
        payload = status;
      } else if (statusReads === 1) {
        payload = { ...status, available: false, worker: { status: "starting", reason: "The assistant worker is starting." } };
      } else {
        otherStatusReadsAfterRoute += 1;
        payload = status;
      }
    } else if (pathname === "/api/v1/assistant/models") {
      payload = { items: [model] };
    } else if (pathname === "/api/v1/assistant/context") {
      const routeName = new URL(request.url()).searchParams.get("route") || "/";
      payload = { context: { ...context, route: routeName }, preview: { summary: "Current route only", fields: ["page route only"], note: "No selected references." } };
    } else if (pathname === "/api/v1/assistant/conversations" && request.method() === "GET") {
      payload = { items: [], page: 1, page_size: 20, total: 0 };
    }
    return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(payload) });
  });

  await page.goto("/overview");
  await page.getByRole("button", { name: "Open Ledger assistant" }).click();
  const panel = page.getByTestId("assistant-panel");
  await expect.poll(() => statusReads).toBe(2);
  browserDiagnostics.expectRequestAborts({ method: "GET", path: "/api/v1/assistant/status", count: 1 });
  routeRefreshPending = true;
  await page.evaluate(() => {
    window.history.pushState({}, "", "/tools/markets");
    window.dispatchEvent(new PopStateEvent("popstate"));
  });
  await expect.poll(() => readyHostStatusResponses).toBe(1);
  expect(routeStatusRefreshReads).toBe(1);
  await expect(panel.locator('[data-ready="true"]')).toBeVisible();
  const settledReads = { statusReads, routeStatusRefreshReads, otherStatusReadsAfterRoute };
  releaseStaleResponse();
  await page.clock.runFor(10_000);
  await expect(panel.locator('[data-ready="true"]')).toBeVisible();
  await expect(panel.getByRole("button", { name: "Check readiness" })).toHaveCount(0);
  expect({ statusReads, routeStatusRefreshReads, otherStatusReadsAfterRoute }).toEqual(settledReads);
});

test("assistant recovers visibly when the authenticated session expires before a turn", async ({ page, assistantApplication, browserDiagnostics }, testInfo) => {
  const origin = assistantApplication.url;
  const panel = await openRealAssistant(page, origin);
  const logout = await page.context().request.post(`${origin}/api/v1/auth/logout`, {
    headers: { "x-csrf-token": "browser-assistant-fixture-csrf-token-not-a-production-credential" },
  });
  expect(logout.status()).toBe(204);
  browserDiagnostics.expectHttpFailures({
    method: "GET",
    path: "/api/v1/assistant/context",
    status: 401,
  });

  const prompt = "Check whether this expired session can still send a turn.";
  await panel.getByRole("textbox", { name: "Ask about this page" }).fill(prompt);
  await panel.getByRole("button", { name: "Send question" }).click();
  await expect(panel.getByRole("alert")).toHaveText("Your session ended. Sign in again before continuing.");
  await expect(panel.getByRole("textbox", { name: "Ask about this page" })).toHaveValue(prompt);
  await expect(panel.getByRole("button", { name: "Send question" })).toBeEnabled();
  await expectAssistantAxeClean(page, testInfo, "expired-session");
});

test("assistant explains a storage quota response and preserves the unsent question", async ({ page, assistantApplication, browserDiagnostics }, testInfo) => {
  const origin = assistantApplication.url;
  const panel = await openRealAssistant(page, origin);
  browserDiagnostics.expectHttpFailures({
    method: "POST",
    path: "/api/v1/assistant/conversations",
    status: 413,
  });
  await page.route("**/api/v1/assistant/conversations", async (route) => {
    if (route.request().method() !== "POST") return route.continue();
    return route.fulfill({
      status: 413,
      contentType: "application/json",
      body: JSON.stringify({
        error: {
          code: "assistant_quota_exceeded",
          message: "Assistant history reached its storage limit. Delete a conversation to continue.",
        },
      }),
    });
  });

  const prompt = "Keep this question while showing the storage limit.";
  await panel.getByRole("textbox", { name: "Ask about this page" }).fill(prompt);
  await panel.getByRole("button", { name: "Send question" }).click();
  await expect(panel.getByRole("alert")).toHaveText(
    "Assistant history has reached its storage limit. Existing workspace data is still available.",
  );
  await expect(panel.getByRole("textbox", { name: "Ask about this page" })).toHaveValue(prompt);
  await expect(panel.getByRole("button", { name: "Send question" })).toBeEnabled();
  await expectAssistantAxeClean(page, testInfo, "storage-quota");
});

test("assistant header model and named controls never overlap at tablet, desktop, or expanded widths", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "desktop-chromium", "header width geometry is evaluated in the desktop project");
  await page.route("**/api/v1/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    let payload = { items: [], page: 1, page_size: 20, total: 0 };
    if (path === "/api/v1/auth/session") payload = { authenticated: true, user: { id: 1, role: "admin" }, csrf_token: "fixture-csrf" };
    else if (path === "/api/v1/assistant/status") payload = status;
    else if (path === "/api/v1/assistant/models") payload = { items: [model] };
    else if (path === "/api/v1/assistant/context") payload = { context, preview: { summary: "Forecast workspace", fields: ["current route only"], note: "Route context." } };
    return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(payload) });
  });
  await page.goto("/overview");
  await page.getByRole("button", { name: "Open Ledger assistant" }).click();
  const panel = page.getByTestId("assistant-panel");
  await expect(panel).toBeVisible();
  const widths = [700, 768, 1280, 1440];
  for (const expanded of [false, true]) {
    if (expanded) await panel.getByRole("button", { name: "Expand assistant" }).click();
    for (const width of widths) {
      await page.setViewportSize({ width, height: 960 });
      const geometry = await panel.locator("header").evaluate((header) => {
        const rectangle = (element) => {
          const bounds = element.getBoundingClientRect();
          return { left: bounds.left, right: bounds.right, top: bounds.top, bottom: bounds.bottom, width: bounds.width, height: bounds.height };
        };
        const title = rectangle(header.querySelector('[data-testid="assistant-title-block"]'));
        const model = rectangle(header.querySelector('select[aria-label="Assistant model"]'));
        const controls = rectangle(header.querySelector("[data-testid='assistant-header-controls']"));
        const buttons = [...header.querySelectorAll("button")].map((button) => ({
          name: button.getAttribute("aria-label"),
          rect: rectangle(button),
        }));
        return { header: rectangle(header), title, model, controls, buttons };
      });
      expect(geometry.buttons.map((button) => button.name)).toEqual([
        "Open conversation history", expanded ? "Restore assistant size" : "Expand assistant", "Minimize assistant", "Close assistant",
      ]);
      expect(geometry.model.width).toBeGreaterThanOrEqual(geometry.header.width - 2);
      expect(geometry.model.height).toBeGreaterThanOrEqual(44);
      expect(geometry.controls.top).toBeLessThan(geometry.model.top);
      expect(geometry.title.right).toBeLessThanOrEqual(geometry.controls.left + 1);
      expect(geometry.model.top).toBeGreaterThanOrEqual(Math.max(geometry.title.bottom, geometry.controls.bottom) - 1);
      for (const button of geometry.buttons) {
        expect(Math.abs(button.rect.top - geometry.controls.top)).toBeLessThanOrEqual(1);
      }
      for (const button of geometry.buttons) {
        expect(button.rect.width).toBeGreaterThanOrEqual(44);
        expect(button.rect.height).toBeGreaterThanOrEqual(44);
        expect(button.rect.left).toBeGreaterThanOrEqual(geometry.header.left - 1);
        expect(button.rect.right).toBeLessThanOrEqual(geometry.header.right + 1);
      }
      for (let index = 0; index < geometry.buttons.length; index += 1) {
        for (let other = index + 1; other < geometry.buttons.length; other += 1) {
          const left = geometry.buttons[index].rect;
          const right = geometry.buttons[other].rect;
          const overlaps = left.left < right.right && left.right > right.left
            && left.top < right.bottom && left.bottom > right.top;
          expect(overlaps).toBe(false);
          expect(left.left).toBeLessThanOrEqual(right.left);
        }
      }
    }
    if (expanded) await panel.getByRole("button", { name: "Restore assistant size" }).click();
  }
});

test("assistant availability, context, focus, and bounds hold across workspace routes and themes", async ({ page }, testInfo) => {
  test.setTimeout(180_000);
  const routes = ["/", "/overview", "/research", "/tools", "/tools/forecast", "/tools/live-trading", "/tools/markets", "/api-docs", "/account", "/admin"];
  await page.route("**/api/v1/**", async (route) => {
    const url = new URL(route.request().url());
    const path = url.pathname;
    let payload = { items: [], total: 0, page: 1, page_size: 20 };
    if (path === "/api/v1/auth/session") {
      payload = { authenticated: true, user: { id: 1, role: "admin", login: "browser-fixture" }, csrf_token: "fixture-csrf" };
    } else if (path === "/api/v1/assistant/status") {
      payload = status;
    } else if (path === "/api/v1/assistant/models") {
      payload = { items: [model] };
    } else if (path === "/api/v1/assistant/context") {
      const routeName = url.searchParams.get("route") || "/";
      payload = {
        context: { ...context, route: routeName, context_version: `route:${routeName}` },
        preview: { summary: `Context for ${routeName}`, fields: ["current route only"], note: "No selected instrument or saved reference." },
      };
    } else if (path === "/api/v1/history") {
      payload = { items: [], page: 1, page_size: 20, total: 0 };
    }
    return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(payload) });
  });

  for (const theme of ["light", "dark"]) {
    await page.goto("/");
    await page.evaluate((selectedTheme) => localStorage.setItem("stock-probs.theme", selectedTheme), theme);
    for (const path of routes) {
      await page.goto(path);
      await expect(page.locator("html")).toHaveAttribute("data-theme", theme);
      const launcher = page.getByRole("button", { name: "Open Ledger assistant" });
      await expect(launcher).toBeVisible();
      await launcher.click();
      const panel = page.getByTestId("assistant-panel");
      await expect(panel).toBeVisible();
      await expect(panel.getByRole("region", { name: "Workspace context" })).toBeVisible();
      await expect(panel.getByText("Route + refs", { exact: true })).toBeVisible();
      await expect(panel.getByText("Share selected references", { exact: true })).toBeVisible();
      await expect(panel.getByText("Preview", { exact: true })).toBeVisible();
      if (testInfo.project.name !== "mobile-chromium") {
        const contextTargets = [
          panel.getByRole("button", { name: "Refresh context preview" }),
          panel.getByRole("checkbox", { name: "Share selected references" }).locator("xpath=.."),
          panel.locator("details > summary"),
        ];
        for (const target of contextTargets) {
          const bounds = await target.boundingBox();
          expect(bounds).not.toBeNull();
          expect(bounds.width).toBeGreaterThanOrEqual(44);
          expect(bounds.height).toBeGreaterThanOrEqual(44);
        }
      } else {
        const refreshTarget = panel.getByRole("button", { name: "Refresh context preview" });
        if (await refreshTarget.isVisible()) {
          const bounds = await refreshTarget.boundingBox();
          expect(bounds).not.toBeNull();
          expect(bounds.width).toBeGreaterThanOrEqual(44);
          expect(bounds.height).toBeGreaterThanOrEqual(44);
        }
      }
      await expect(panel.locator("details")).toHaveJSProperty("open", false);
      const compactContextHeight = await panel.getByRole("region", { name: "Workspace context" }).evaluate((node) => node.getBoundingClientRect().height);
      expect(compactContextHeight).toBeLessThanOrEqual(120);
      await expect(panel.locator('[data-ready="true"]')).toBeVisible();
      const geometry = await page.evaluate(() => {
        const panel = document.querySelector("[data-testid='assistant-panel']");
        const rect = panel?.getBoundingClientRect();
        return {
          panel: rect ? { left: rect.left, right: rect.right, top: rect.top, bottom: rect.bottom } : null,
          width: window.innerWidth,
          height: window.innerHeight,
          documentWidth: document.documentElement.scrollWidth,
          focusInside: !!panel?.contains(document.activeElement),
          backgroundInert: document.querySelector("[data-assistant-background]")?.inert ?? false,
        };
      });
      expect(geometry.panel).not.toBeNull();
      expect(geometry.panel.left).toBeGreaterThanOrEqual(-1);
      expect(geometry.panel.right).toBeLessThanOrEqual(geometry.width + 1);
      expect(geometry.panel.top).toBeGreaterThanOrEqual(-1);
      expect(geometry.panel.bottom).toBeLessThanOrEqual(geometry.height + 1);
      expect(geometry.documentWidth).toBeLessThanOrEqual(geometry.width + 1);
      expect(geometry.focusInside).toBe(true);
      const mobile = testInfo.project.name === "mobile-chromium";
      expect(geometry.backgroundInert).toBe(mobile);
      if (mobile) {
        await expect(panel).toHaveAttribute("aria-modal", "true");
        await expect(panel.getByRole("heading", { name: "Ledger assistant" })).toBeFocused();
        const focusWrapped = await panel.evaluate((node) => {
          const controls = [...node.querySelectorAll('a[href],button:not([disabled]),input:not([disabled]),select:not([disabled]),textarea:not([disabled]),[tabindex]:not([tabindex="-1"])')]
            .filter((element) => element.getAttribute("aria-hidden") !== "true" && element.getClientRects().length > 0);
          controls[0]?.focus();
          return controls.length > 1 && document.activeElement === controls[0];
        });
        expect(focusWrapped).toBe(true);
        await page.keyboard.press("Shift+Tab");
        expect(await panel.evaluate((node) => {
          const controls = [...node.querySelectorAll('a[href],button:not([disabled]),input:not([disabled]),select:not([disabled]),textarea:not([disabled]),[tabindex]:not([tabindex="-1"])')]
            .filter((element) => element.getAttribute("aria-hidden") !== "true" && element.getClientRects().length > 0);
          return controls.length > 1 && document.activeElement === controls.at(-1);
        })).toBe(true);
      } else {
        await expect(panel).not.toHaveAttribute("aria-modal", "true");
      }
      const routeSlug = path === "/" ? "home" : path.slice(1).replaceAll("/", "-");
      await page.screenshot({ path: testInfo.outputPath(`assistant-${testInfo.project.name}-${theme}-${routeSlug}.png`) });
      await panel.getByRole("button", { name: "Close assistant" }).click();
      await expect(launcher).toBeFocused();
      await expect(page.locator("[data-assistant-background]")).toHaveJSProperty("inert", false);
    }
  }
});

test("member sessions can use assistant workspace and account context but not the admin surface", async ({ page }) => {
  const assistantRequests = [];
  const protectedAdminRequests = [];
  const contextRoutes = [];
  let sessionReads = 0;
  await page.route("**/api/v1/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;
    if (path.startsWith("/api/v1/assistant/")) assistantRequests.push({ method: request.method(), path });
    if (/^\/api\/v1\/(?:auth\/invites|assistant\/providers|operations\/(?:backups|restores))(?:\/|$)/.test(path)) {
      protectedAdminRequests.push({ method: request.method(), path });
    }

    let payload = { items: [], page: 1, page_size: 20, total: 0 };
    if (path === "/api/v1/auth/session") {
      sessionReads += 1;
      payload = { authenticated: true, user: { id: 9, login: "fixture-member", role: "member" }, csrf_token: "fixture-csrf" };
    } else if (path === "/api/v1/auth/sessions") {
      payload = { sessions: [{ id: "member-session", current: true, last_seen_at: "2026-10-08T12:00:00Z", expires_at: "2026-10-09T12:00:00Z" }] };
    } else if (path === "/api/v1/auth/totp/status") {
      payload = { enrolled: true, enrollment_pending: false, recovery_codes_remaining: 8, requires_totp: true, can_enroll: false };
    } else if (path === "/api/v1/assistant/status") {
      payload = { ...status, authorization: { role: "member", admitted: true } };
    } else if (path === "/api/v1/assistant/models") {
      payload = { items: [model] };
    } else if (path === "/api/v1/assistant/context") {
      const routeName = url.searchParams.get("route") || "/";
      contextRoutes.push(routeName);
      payload = {
        context: { ...context, route: routeName, context_version: `member:${routeName}` },
        preview: { summary: `Member context for ${routeName}`, fields: ["current route only"], note: "No administrator data." },
      };
    } else if (path === "/api/v1/assistant/conversations") {
      payload = { items: [], page: 1, page_size: 20, total: 0 };
    } else if (path === "/api/v1/auth/invites") {
      payload = { invitations: [], email_invites_enabled: false };
    }
    return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(payload) });
  });

  for (const routeName of ["/overview", "/account"]) {
    await page.goto(routeName);
    if (routeName === "/account") {
      await expect(page.getByRole("heading", { name: "Your account" })).toBeVisible();
      await expect(page.getByRole("link", { name: "Open admin panel" })).toHaveCount(0);
    }
    const launcher = page.getByRole("button", { name: "Open Ledger assistant" });
    await expect(launcher).toBeVisible();
    await launcher.click();
    const panel = page.getByTestId("assistant-panel");
    await expect(panel.getByRole("region", { name: "Workspace context" })).toBeVisible();
    await panel.locator("details > summary").click();
    await expect(panel.getByText(`Member context for ${routeName}`, { exact: true })).toBeVisible();
    expect(contextRoutes.at(-1)).toBe(routeName);
    await panel.getByRole("button", { name: "Close assistant" }).click();
  }

  assistantRequests.length = 0;
  protectedAdminRequests.length = 0;
  const sessionReadsBeforeAdmin = sessionReads;
  await page.goto("/admin");
  await expect(page.getByRole("heading", { name: "Administrator access required" })).toBeVisible();
  await expect.poll(() => sessionReads).toBeGreaterThanOrEqual(sessionReadsBeforeAdmin + 2);
  await expect(page.getByRole("button", { name: "Open Ledger assistant" })).toHaveCount(0);
  await expect(page.getByTestId("assistant-panel")).toHaveCount(0);
  expect(assistantRequests).toEqual([]);
  expect(protectedAdminRequests).toEqual([]);
});

test("assistant stays absent on sign-in, invitation, authenticator, and legacy passkey routes", async ({ page }) => {
  const assistantRequests = [];
  await page.route("**/api/v1/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path.startsWith("/api/v1/assistant/")) assistantRequests.push(path);
    const payload = path === "/api/v1/auth/session"
      ? { authenticated: false }
      : path === "/api/v1/auth/status"
        ? { status: "github" }
        : path === "/api/v1/auth/totp/status"
          ? { enrolled: false, enrollment_pending: false, recovery_codes_remaining: 0, requires_totp: false, can_enroll: false }
          : {};
    return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(payload) });
  });

  for (const routeName of [
    "/sign-in",
    "/invite?error=invitation_rejected",
    "/authenticator?mode=enroll&next=%2Foverview",
    "/passkey?mode=verify&next=%2Foverview",
  ]) {
    await page.goto(routeName);
    await expect(page.locator("main")).toBeVisible();
    await expect(page.getByRole("button", { name: "Open Ledger assistant" })).toHaveCount(0);
    await expect(page.getByTestId("assistant-panel")).toHaveCount(0);
  }
  expect(assistantRequests).toEqual([]);
});

test("session revocation while the assistant is open prevents a pending action confirmation", async ({ page, assistantApplication, browserDiagnostics }) => {
  const origin = assistantApplication.url;
  const confirmationRequests = [];
  const eventStreamResponses = new Map();
  const eventStreamTerminals = new Map();
  const recordEventStreamTerminal = (path, outcome) => {
    eventStreamTerminals.set(path, [...(eventStreamTerminals.get(path) || []), outcome]);
  };
  page.on("response", (response) => {
    const url = new URL(response.url());
    if (response.request().method() === "GET" && /^\/api\/v1\/assistant\/conversations\/[^/]+\/turns\/[^/]+\/events$/.test(url.pathname)) {
      eventStreamResponses.set(url.pathname, { status: response.status(), contentType: response.headers()["content-type"] || "" });
    }
  });
  page.on("requestfinished", (request) => {
    const url = new URL(request.url());
    if (request.method() === "GET" && /^\/api\/v1\/assistant\/conversations\/[^/]+\/turns\/[^/]+\/events$/.test(url.pathname)) {
      recordEventStreamTerminal(url.pathname, { kind: "finished" });
    }
  });
  page.on("requestfailed", (request) => {
    const url = new URL(request.url());
    if (request.method() === "GET" && /^\/api\/v1\/assistant\/conversations\/[^/]+\/turns\/[^/]+\/events$/.test(url.pathname)) {
      recordEventStreamTerminal(url.pathname, { kind: "failed", error: request.failure()?.errorText || "unknown request failure" });
    }
  });
  const panel = await openRealAssistant(page, origin);
  const priorTheme = await page.locator("html").getAttribute("data-theme");
  if (!priorTheme) throw new Error("The workspace theme must be initialized before the action check.");
  await panel.getByRole("textbox", { name: "Ask about this page" }).fill("Explain this page without selected references");
  const turnResponsePromise = page.waitForResponse((response) => {
    const request = response.request();
    return request.method() === "POST"
      && /^\/api\/v1\/assistant\/conversations\/[^/]+\/turns$/.test(new URL(response.url()).pathname);
  });
  await panel.getByRole("button", { name: "Send question" }).click();
  const turnResponse = await turnResponsePromise;
  expect(turnResponse.status()).toBe(202);
  const turnPathMatch = new URL(turnResponse.url()).pathname.match(/^(\/api\/v1\/assistant\/conversations\/[^/]+)\/turns$/);
  const turnId = (await turnResponse.json()).turn?.id;
  expect(turnPathMatch).not.toBeNull();
  expect(turnId).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
  const eventPath = `${turnPathMatch[1]}/turns/${encodeURIComponent(turnId)}/events`;
  browserDiagnostics.expectCompletedAssistantEventStream({ path: eventPath });

  const proposal = panel.getByRole("region", { name: "Preview: Change display theme" });
  await expect(proposal).toBeVisible();
  await expect.poll(() => eventStreamResponses.get(eventPath)?.status).toBe(200);
  expect(eventStreamResponses.get(eventPath).contentType).toMatch(/^text\/event-stream(?:;|$)/);
  await expect.poll(() => eventStreamTerminals.get(eventPath)?.length ?? 0).toBe(1);
  const [streamTerminal] = eventStreamTerminals.get(eventPath);
  expect(["finished", "failed"]).toContain(streamTerminal.kind);
  if (streamTerminal.kind === "failed") expect(streamTerminal.error).toBe("net::ERR_ABORTED");
  const phrase = await proposal.locator("code").textContent();
  expect(phrase).toMatch(/^CONFIRM [a-f0-9]{8}$/);
  await proposal.getByRole("textbox").fill(phrase);
  const confirmation = proposal.getByRole("button", { name: "Confirm change" });
  await expect(confirmation).toBeEnabled();
  page.on("request", (request) => {
    const path = new URL(request.url()).pathname;
    if (path.includes("/actions/") && path.endsWith("/confirm")) confirmationRequests.push({ method: request.method(), path });
  });

  const logout = await page.context().request.post(`${origin}/api/v1/auth/logout`, {
    headers: { "x-csrf-token": "browser-assistant-fixture-csrf-token-not-a-production-credential" },
  });
  expect(logout.status()).toBe(204);
  browserDiagnostics.expectHttpFailures({ method: "GET", path: "/api/v1/assistant/context", status: 401 });
  await confirmation.click();

  await expect(panel.getByRole("alert")).toBeVisible();
  await expect(page.locator("html")).toHaveAttribute("data-theme", priorTheme);
  await expect(proposal).toBeVisible();
  expect(confirmationRequests).toEqual([]);
});

test("assistant print view keeps saved answer, citations, and receipts while omitting controls and covered page", async ({ page }, testInfo) => {
  const savedConversation = {
    id: "conversation-print-1",
    title: "Printable saved research",
    revision: 1,
    created_at: "2026-10-04T12:00:00Z",
    updated_at: "2026-10-04T12:01:00Z",
    last_message_preview: "Saved answer for print",
  };
  await page.route("**/api/v1/**", async (route) => {
    const url = new URL(route.request().url());
    const path = url.pathname;
    let payload = { items: [], total: 0, page: 1, page_size: 20 };
    if (path === "/api/v1/auth/session") {
      payload = { authenticated: true, user: { id: 1, role: "admin" }, csrf_token: "fixture-csrf" };
    } else if (path === "/api/v1/assistant/status") {
      payload = status;
    } else if (path === "/api/v1/assistant/models") {
      payload = { items: [model] };
    } else if (path === "/api/v1/assistant/context") {
      payload = { context: { ...context, route: "/overview" }, preview: { summary: "Overview", fields: ["current route only"], note: "Saved page context." } };
    } else if (path === "/api/v1/assistant/conversations") {
      payload = { items: [savedConversation], total: 1, page: 1, page_size: 20 };
    } else if (path === "/api/v1/assistant/conversations/conversation-print-1") {
      payload = {
        conversation: { ...savedConversation, delete_confirmation_phrase: "DELETE nt-1" },
        messages: { items: [{ id: "message-print-1", turn_id: "turn-print-1", seq: 1, role: "assistant", text: "Saved answer stays readable in print.", created_at: savedConversation.updated_at, sources: [
          { source_id: "source-print-1", title: "First party research source", url: "https://research.example.org/article", source_type: "retrieved source", as_of: savedConversation.updated_at },
          { source_id: "source-print-2", title: "Provider headline that is not a verified citation", url: "https://search.example.net/page", source_type: "native_search_text_unverified", retrieved_at: savedConversation.updated_at },
        ] }], page: 1, page_size: 50, total: 1 },
        turns: [{ id: "turn-print-1", status: "completed", model_id: model.id, policy_version: model.policy_version, context_version: "context-v1", context: { ...context, route: "/overview" }, created_at: savedConversation.created_at, completed_at: savedConversation.updated_at, actions: [] }],
        actions: [{ action_id: "action-print-1", action_type: "portfolio.add", status: "applied", expires_at: "2026-10-05T12:00:00Z", proposal: null, availability: "unavailable", receipt: { receipt_id: "receipt-print-1", outcome: "applied", message: "Saved action receipt stays readable.", destination: "/account#sessions" } }],
        action_pagination: { page: 1, page_size: 100, total: 1 },
        events: { items: [{ turn_id: "turn-print-1", sequence: 1, type: "tool", data: { name: "signal-ledger_workspace_summary", call_id: "call-print-1", receipt_id: "tool-receipt-print-1", status: "complete", description: "Saved bounded workspace summary", result_bytes: 64 }, created_at: savedConversation.updated_at }], page: 1, page_size: 100, total: 1 },
        event_pagination: { page: 1, page_size: 100, total: 1 },
      };
    }
    return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(payload) });
  });
  await page.emulateMedia({ forcedColors: "active", reducedMotion: "reduce" });
  await page.goto("/overview");
  await page.getByRole("button", { name: "Open Ledger assistant" }).click();
  const panel = page.getByTestId("assistant-panel");
  await expect(panel).toBeVisible();
  await expect.poll(() => page.evaluate(() => ({ forced: matchMedia("(forced-colors: active)").matches, reduced: matchMedia("(prefers-reduced-motion: reduce)").matches }))).toEqual({ forced: true, reduced: true });
  const motion = await panel.evaluate((node) => ({ transition: getComputedStyle(node).transitionDuration, animation: getComputedStyle(node).animationName }));
  expect(motion).toEqual({ transition: "0s", animation: "none" });
  await page.keyboard.press("Tab");
  const focusOutline = await page.evaluate(() => ({ visible: document.activeElement instanceof HTMLElement && document.activeElement.matches(":focus-visible"), width: document.activeElement instanceof HTMLElement ? getComputedStyle(document.activeElement).outlineWidth : "0px" }));
  expect(focusOutline.visible).toBe(true);
  expect(Number.parseFloat(focusOutline.width)).toBeGreaterThanOrEqual(3);
  await page.screenshot({ path: testInfo.outputPath(`assistant-${testInfo.project.name}-forced-colors-reduced-motion.png`) });

  await panel.getByRole("button", { name: "Open conversation history" }).click();
  await panel.getByRole("button", { name: /Printable saved research/ }).click();
  await expect(panel.getByText("Saved answer stays readable in print.", { exact: true })).toBeVisible();
  await expect(panel.getByText("Route + refs", { exact: true })).toBeVisible();
  const sourceLink = panel.getByRole("link", { name: /First party research source/ });
  const unverifiedSearchLink = panel.getByRole("link", { name: /Unverified search link/ });
  const receiptLink = panel.getByRole("link", { name: "Continue to account sessions" });
  await expect(sourceLink).toBeVisible();
  await expect(unverifiedSearchLink).toBeVisible();
  await expect(panel.getByText("Parsed from retrieved search text; source attribution was not independently verified.", { exact: true })).toBeVisible();
  await expect(panel.getByText("Provider headline that is not a verified citation", { exact: true })).toHaveCount(0);
  await expect(receiptLink).toBeVisible();
  for (const link of [sourceLink, unverifiedSearchLink, receiptLink]) {
    const height = await link.evaluate((node) => node.getBoundingClientRect().height);
    expect(height).toBeGreaterThanOrEqual(44);
  }

  await expect(panel.locator("details")).toHaveJSProperty("open", false);
  await page.evaluate(() => {
    window.__assistantPrintEvents = [];
    const disclosure = document.querySelector("[data-testid='assistant-panel'] details");
    window.addEventListener("beforeprint", () => window.__assistantPrintEvents.push({ type: "beforeprint", contextOpen: disclosure?.open ?? false }));
    window.addEventListener("afterprint", () => window.__assistantPrintEvents.push({ type: "afterprint", contextOpen: disclosure?.open ?? false }));
  });
  const printablePath = testInfo.outputPath(`assistant-${testInfo.project.name}-print.pdf`);
  await page.pdf({ path: printablePath, printBackground: true });
  expect(await page.evaluate(() => window.__assistantPrintEvents)).toEqual([
    { type: "beforeprint", contextOpen: true },
    { type: "afterprint", contextOpen: false },
  ]);
  await expect(panel.locator("details")).toHaveJSProperty("open", false);

  await panel.getByText("Preview", { exact: true }).click();
  await page.emulateMedia({ media: "print" });
  await expect(panel).toBeVisible();
  await expect(panel.getByText("Saved answer stays readable in print.", { exact: true })).toBeVisible();
  await expect(panel.getByText("Saved page context.", { exact: true })).toBeVisible();
  await expect(panel.locator("details")).toHaveJSProperty("open", true);
  await expect(panel.locator("#assistant-prompt")).toHaveCSS("display", "none");
  await expect(panel.locator('button[aria-label="Close assistant"]')).toHaveCSS("display", "none");
  await expect(page.locator("[data-assistant-background]")).toHaveCSS("display", "none");
  const printGeometry = await panel.evaluate((node) => ({
    display: getComputedStyle(node).display,
    position: getComputedStyle(node).position,
    overflow: getComputedStyle(node).overflow,
    scrollWidth: document.documentElement.scrollWidth,
    width: document.documentElement.clientWidth,
  }));
  expect(printGeometry).toMatchObject({ display: "block", position: "static", overflow: "visible" });
  expect(printGeometry.scrollWidth).toBeLessThanOrEqual(printGeometry.width + 1);
  await page.screenshot({ path: testInfo.outputPath(`assistant-${testInfo.project.name}-print.png`), fullPage: true });
  await page.emulateMedia({ media: "screen", forcedColors: "none", reducedMotion: "no-preference" });
  await panel.getByRole("button", { name: "Close assistant" }).click();
  await page.emulateMedia({ media: "print" });
  await expect(page.locator('button[aria-label="Open Ledger assistant"]')).toHaveCSS("display", "none");
  await expect(page.locator("[data-assistant-background]")).not.toHaveCSS("display", "none");
});

test("assistant keeps focus through send and cancel, and ignores stale focus handoffs", async ({ page, assistantApplication }, testInfo) => {
  const conversation = {
    id: "conversation-focus",
    title: "Keyboard focus regression",
    revision: 1,
    created_at: "2025-01-10T17:00:00Z",
    updated_at: "2025-01-10T17:00:00Z",
  };
  const turns = [];
  const turnStates = new Map();
  let holdNextConversationDetail = false;
  let releaseCompletionDetail;
  let signalCompletionDetailStarted;
  let signalCompletionDetailFinished;
  const completionDetailStarted = new Promise((resolve) => { signalCompletionDetailStarted = resolve; });
  const completionDetailFinished = new Promise((resolve) => { signalCompletionDetailFinished = resolve; });

  await page.addInitScript(({ modelId, policyVersion }) => {
    const originalFetch = window.fetch.bind(window);
    window.__assistantFocusModelId = modelId;
    window.__assistantFocusPolicyVersion = policyVersion;
    window.__assistantFocusStreams = [];
    window.fetch = (input, init) => {
      const url = typeof input === "string" ? input : input instanceof Request ? input.url : String(input);
      if (!/\/api\/v1\/assistant\/conversations\/[^/]+\/turns\/[^/]+\/events(?:\?|$)/.test(url)) {
        return originalFetch(input, init);
      }
      const signal = init?.signal || (input instanceof Request ? input.signal : undefined);
      return new Promise((resolve, reject) => {
        const stream = {
          url,
          aborted: false,
          released: false,
          release() {
            if (stream.aborted || stream.released) return;
            stream.released = true;
            const events = [
              [1, "meta", { model_id: window.__assistantFocusModelId, policy_version: window.__assistantFocusPolicyVersion, context_version: "focus-context-v1" }],
              [2, "token", { text: "A local focus regression response." }],
              [3, "complete", { status: "completed" }],
            ];
            const body = events.map(([id, name, data]) => `id: ${id}\nevent: ${name}\ndata: ${JSON.stringify(data)}\n\n`).join("");
            resolve(new Response(body, { status: 200, headers: { "content-type": "text/event-stream", "cache-control": "no-store" } }));
          },
        };
        signal?.addEventListener("abort", () => {
          stream.aborted = true;
          reject(new DOMException("The assistant stream was cancelled.", "AbortError"));
        }, { once: true });
        window.__assistantFocusStreams.push(stream);
      });
    };
  }, { modelId: model.id, policyVersion: model.policy_version });

  await page.route("**/api/v1/auth/session", (route) => route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify({ authenticated: true, user: { id: 1, role: "admin" }, csrf_token: "fixture-csrf" }),
  }));
  await page.route("**/api/v1/assistant/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;
    if (path === "/api/v1/assistant/status") return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(status) });
    if (path === "/api/v1/assistant/models") return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ items: [model] }) });
    if (path === "/api/v1/assistant/context") {
      const routeName = url.searchParams.get("route") || "/";
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ context: { ...context, route: routeName, context_version: "focus-context-v1" }, preview: { summary: "Focus regression fixture", fields: ["page route only"], note: "No external request is made." } }),
      });
    }
    if (path === "/api/v1/assistant/conversations" && request.method() === "GET") {
      const items = turns.length ? [{ ...conversation, last_message_preview: "Keyboard focus regression" }] : [];
      return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ items, page: 1, page_size: 20, total: items.length }) });
    }
    if (path === "/api/v1/assistant/conversations" && request.method() === "POST") {
      return route.fulfill({ status: 201, contentType: "application/json", body: JSON.stringify(conversation) });
    }
    if (path === `/api/v1/assistant/conversations/${conversation.id}` && request.method() === "GET") {
      const delayedCompletion = holdNextConversationDetail;
      if (delayedCompletion) {
        holdNextConversationDetail = false;
        signalCompletionDetailStarted();
        await new Promise((resolve) => { releaseCompletionDetail = resolve; });
      }
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          conversation: { ...conversation, delete_confirmation_phrase: "DELETE focus" },
          messages: { items: [], page: 1, page_size: 50, total: 0 },
          turns: turns.map((id) => ({ id, status: turnStates.get(id) || "running", model_id: model.id, policy_version: model.policy_version, context_version: "focus-context-v1", context: { ...context, context_version: "focus-context-v1" }, created_at: conversation.created_at })),
          actions: [],
          action_pagination: { page: 1, page_size: 100, total: 0 },
          events: { items: [], page: 1, page_size: 100, total: 0 },
        }),
      });
      if (delayedCompletion) signalCompletionDetailFinished();
      return;
    }
    if (path === `/api/v1/assistant/conversations/${conversation.id}/turns` && request.method() === "POST") {
      const id = `focus-turn-${turns.length + 1}`;
      turns.push(id);
      turnStates.set(id, "running");
      return route.fulfill({ status: 202, contentType: "application/json", body: JSON.stringify({ turn: { id, status: "running" } }) });
    }
    const cancelMatch = path.match(new RegExp(`^/api/v1/assistant/conversations/${conversation.id}/turns/([^/]+)/cancel$`));
    if (cancelMatch && request.method() === "POST") {
      turnStates.set(decodeURIComponent(cancelMatch[1]), "cancelled");
      return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ status: "cancelled" }) });
    }
    return route.fulfill({ status: 404, contentType: "application/json", body: JSON.stringify({ error: { code: "fixture_missing", message: "No assistant focus fixture route." } }) });
  });

  const panel = await openRealAssistant(page, assistantApplication.url);
  const composer = panel.getByRole("textbox", { name: "Ask about this page" });
  await composer.fill("Start a keyboard focus regression turn.");
  await composer.press("Tab");
  const send = panel.getByRole("button", { name: "Send question" });
  await expect(send).toBeFocused();
  await send.press("Enter");
  await expect.poll(() => page.evaluate(() => window.__assistantFocusStreams.length)).toBe(1);
  await expect(panel.getByRole("button", { name: "Stop response" })).toBeFocused();

  await panel.getByRole("button", { name: "Stop response" }).press("Enter");
  await expectAssistantLiveStatus(panel, "Response cancelled. Saved conversation history remains available.");
  await expect(composer).toBeFocused();
  await expect(panel.getByRole("button", { name: "Stop response" })).toHaveCount(0);

  await composer.fill("Keep delayed completion from reclaiming focus.");
  await composer.press("Tab");
  await expect(send).toBeFocused();
  await send.press("Enter");
  await expect.poll(() => page.evaluate(() => window.__assistantFocusStreams.length)).toBe(2);

  if (testInfo.project.name === "mobile-chromium") {
    await expect(panel).toHaveAttribute("aria-modal", "true");
    await expect(panel.getByRole("button", { name: "Stop response" })).toBeFocused();
    await panel.getByRole("button", { name: "Stop response" }).press("Enter");
    await expectAssistantLiveStatus(panel, "Response cancelled. Saved conversation history remains available.");
    await expect(composer).toBeFocused();
    return;
  }

  await panel.getByRole("button", { name: "Minimize assistant" }).click();
  await expect(panel.getByRole("button", { name: "Resume assistant" })).toBeFocused();
  holdNextConversationDetail = true;
  turnStates.set(turns[1], "completed");
  await page.evaluate(() => window.__assistantFocusStreams[1].release());
  await completionDetailStarted;
  await expect(panel.getByRole("button", { name: "Resume assistant" })).toBeFocused();
  await page.evaluate(() => {
    const button = document.createElement("button");
    button.id = "assistant-focus-external-probe";
    button.type = "button";
    button.textContent = "External focus target";
    button.style.cssText = "position:fixed;left:4px;top:4px;z-index:99999";
    document.body.append(button);
  });
  const externalTarget = page.getByRole("button", { name: "External focus target" });
  await externalTarget.click();
  await expect(externalTarget).toBeFocused();
  releaseCompletionDetail();
  await completionDetailFinished;
  await page.evaluate(() => new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve))));
  await expect(panel.getByText("Conversation saved on this page.", { exact: true })).toBeVisible();
  await expect(panel.getByRole("button", { name: "Resume assistant" })).toBeVisible();
  await expect(externalTarget).toBeFocused();
});
