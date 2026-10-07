"use strict";

const { test, expect } = require("@playwright/test");
const { readFileSync } = require("node:fs");
const path = require("node:path");
const AxeBuilder = require("@axe-core/playwright").default;
const {
  calculateContrast,
  captureAssistantContrastSnapshot,
  evaluateAssistantContrastAudit,
  parseRgb,
} = require("./assistant-contrast-audit");

const catalog = JSON.parse(readFileSync(path.resolve(__dirname, "../../../src/stock_probs/assistant/assistant_catalog.json"), "utf8"));
const zen = catalog.zen;
const [modelKey, modelPolicy] = Object.entries(zen.reviewed_models)
  .filter(([, candidate]) => candidate.available === true
    && candidate.free === true
    && candidate.training === false
    && candidate.data_collection_allowed === false
    && candidate.data_collection_default === false
    && candidate.route === "openai-compatible")
  .sort(([left], [right]) => left.localeCompare(right))[0] || [];
if (!modelKey) throw new Error("No eligible local synthetic assistant model is present in the maintained catalog.");

const modelId = `${zen.provider_id}/${modelKey}`;
const model = {
  id: modelId,
  model_id: modelId,
  provider: zen.provider_id,
  provider_id: zen.provider_id,
  native_provider_id: zen.provider_id,
  name: "Local QA model",
  availability: "available",
  available: true,
  enabled: true,
  usable: true,
  free: true,
  training: "no_training",
  training_uses_data: false,
  terms_url: zen.terms_url,
  terms_reviewed_at: zen.terms_reviewed_at,
  policy_version: zen.policy_version,
  disclosure: "Synthetic local browser fixture; no external model is called.",
  privacy_policy_version: modelPolicy.privacy_policy_version ?? zen.privacy_policy_version,
  privacy_disclosure: "Synthetic local browser fixture; no external model is called.",
  billing_class: "free",
  billing_policy_version: modelPolicy.billing_policy_version ?? zen.billing_policy_version,
  cost_disclosure: modelPolicy.disclosure,
  revision: 1,
  availability_reason: null,
  consent: { accepted: true, data_collection_opt_in: false, accepted_at: "2025-01-01T00:00:00Z" },
};

const status = {
  available: true,
  enabled: true,
  worker: { status: "ready" },
  limits: { active_per_user: 1, active_global: 2, tools_per_turn: 8, turn_seconds: 120 },
  storage: { user_bytes: 1024, user_limit: 2097152, global_bytes: 4096, global_limit: 25165824, database_bytes: 8192, database_limit: 50331648, backup_retention_note: "Existing backup retention applies." },
};

const context = {
  context: { route: "/overview", instrument: null, event_ref: null, result_ref: null, context_version: "contrast-v1" },
  preview: { summary: "Overview", fields: ["current route only"], note: "Synthetic contrast audit fixture." },
};

const savedAnswer = [
  "## Contrast audit answer",
  "The **measured answer text** remains visible in the saved conversation.",
  "- Down: 20%",
  "- Up: 65%",
].join("\n");

const conversationDetail = {
  conversation: {
    id: "contrast-conversation",
    title: "Saved contrast conversation",
    revision: 1,
    created_at: "2025-01-10T17:00:00Z",
    updated_at: "2025-01-10T17:01:00Z",
    delete_confirmation_phrase: "DELETE nversation",
  },
  messages: {
    items: [{ id: "contrast-answer", turn_id: "contrast-turn", seq: 1, role: "assistant", text: savedAnswer, created_at: "2025-01-10T17:01:00Z", sources: [] }],
    page: 1,
    page_size: 50,
    total: 1,
  },
  turns: [],
  actions: [],
  events: { items: [], page: 1, page_size: 100, total: 0 },
};

async function installApiFixtures(page) {
  await page.route("**/api/v1/**", async (route) => {
    const url = new URL(route.request().url());
    const pathName = url.pathname;
    let payload = { items: [], page: 1, page_size: 20, total: 0 };
    if (pathName === "/api/v1/auth/session") {
      payload = { authenticated: true, user: { id: 1, role: "admin", login: "contrast-audit-fixture" }, csrf_token: "fixture-csrf" };
    } else if (pathName === "/api/v1/assistant/status") {
      payload = status;
    } else if (pathName === "/api/v1/assistant/models") {
      payload = { items: [model] };
    } else if (pathName === "/api/v1/assistant/context") {
      payload = context;
    } else if (pathName === "/api/v1/assistant/conversations") {
      payload = { items: [{ id: "contrast-conversation", title: "Saved contrast conversation", revision: 1, created_at: conversationDetail.conversation.created_at, updated_at: conversationDetail.conversation.updated_at, last_message_preview: "Measured answer text." }], page: 1, page_size: 20, total: 1 };
    } else if (pathName === "/api/v1/assistant/conversations/contrast-conversation") {
      payload = conversationDetail;
    } else if (pathName === "/api/v1/auth/csrf") {
      payload = { csrf_token: "fixture-csrf" };
    }
    return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(payload) });
  });
}

async function attachJson(testInfo, name, body) {
  await testInfo.attach(name, {
    body: Buffer.from(JSON.stringify(body, null, 2)),
    contentType: "application/json",
  });
}

for (const theme of ["light", "dark"]) {
  test(`assistant contrast audit preserves axe evidence and measures exact text in ${theme}`, async ({ page }, testInfo) => {
    test.setTimeout(60_000);
    await installApiFixtures(page);
    await page.addInitScript((selectedTheme) => localStorage.setItem("stock-probs.theme", selectedTheme), theme);
    await page.goto("/overview");
    await expect(page.locator("html")).toHaveAttribute("data-theme", theme);
    await page.getByRole("button", { name: "Open Ledger assistant" }).click();
    const panel = page.getByTestId("assistant-panel");
    await expect(panel).toBeVisible();
    await panel.getByRole("combobox", { name: "Assistant model" }).selectOption(modelId);
    await expect(panel.locator('[data-ready="true"]')).toBeVisible();
    await panel.getByRole("button", { name: "Open conversation history" }).click();
    await panel.getByRole("button", { name: /Saved contrast conversation/ }).click();
    await expect(panel.getByText("measured answer text", { exact: false })).toBeVisible();
    await expect(panel.locator("#assistant-disclaimer")).toBeVisible();

    const placeholderStyle = await panel.locator("#assistant-prompt").evaluate((textarea) => {
      const inputStyle = getComputedStyle(textarea);
      const placeholder = getComputedStyle(textarea, "::placeholder");
      const ancestors = [];
      for (let current = textarea.parentElement; current; current = current.parentElement) {
        const style = getComputedStyle(current);
        ancestors.push({
          tag: current.tagName.toLowerCase(),
          testId: current.getAttribute("data-testid"),
          opacity: style.opacity,
          mixBlendMode: style.mixBlendMode,
          filter: style.filter,
          backdropFilter: style.backdropFilter || style.webkitBackdropFilter || "none",
        });
        if (current === document.documentElement) break;
      }
      return {
        disabled: textarea.disabled,
        placeholderColor: placeholder.color,
        placeholderOpacity: placeholder.opacity,
        backgroundColor: inputStyle.backgroundColor,
        backgroundImage: inputStyle.backgroundImage,
        elementOpacity: inputStyle.opacity,
        mixBlendMode: inputStyle.mixBlendMode,
        filter: inputStyle.filter,
        ancestors,
      };
    });
    const parsedPlaceholder = parseRgb(placeholderStyle.placeholderColor);
    const parsedBackground = parseRgb(placeholderStyle.backgroundColor);
    const placeholderOpacity = Number(placeholderStyle.placeholderOpacity);
    const effectsClear = placeholderStyle.disabled === false
      && placeholderStyle.backgroundImage === "none"
      && placeholderStyle.elementOpacity === "1"
      && placeholderStyle.mixBlendMode === "normal"
      && placeholderStyle.filter === "none"
      && placeholderStyle.ancestors.every((ancestor) => ancestor.opacity === "1"
        && ancestor.mixBlendMode === "normal"
        && ancestor.filter === "none"
        && ancestor.backdropFilter === "none");
    const effectivePlaceholder = parsedPlaceholder && parsedBackground && parsedBackground.alpha === 1
      && Number.isFinite(placeholderOpacity) && placeholderOpacity >= 0 && placeholderOpacity <= 1
      ? {
        red: parsedPlaceholder.red * parsedPlaceholder.alpha * placeholderOpacity + parsedBackground.red * (1 - parsedPlaceholder.alpha * placeholderOpacity),
        green: parsedPlaceholder.green * parsedPlaceholder.alpha * placeholderOpacity + parsedBackground.green * (1 - parsedPlaceholder.alpha * placeholderOpacity),
        blue: parsedPlaceholder.blue * parsedPlaceholder.alpha * placeholderOpacity + parsedBackground.blue * (1 - parsedPlaceholder.alpha * placeholderOpacity),
        alpha: 1,
      }
      : null;
    const placeholderContrast = effectivePlaceholder && parsedBackground
      ? Number(calculateContrast(effectivePlaceholder, parsedBackground).toFixed(4))
      : null;
    const placeholderEvidence = {
      project: testInfo.project.name,
      theme,
      viewport: await page.evaluate(() => ({ width: innerWidth, height: innerHeight })),
      ...placeholderStyle,
      effectivePlaceholder,
      contrastRatio: placeholderContrast,
      threshold: 4.5,
      effectsClear,
    };
    console.log(`assistant-placeholder-contrast ${JSON.stringify(placeholderEvidence)}`);
    await attachJson(testInfo, `assistant-placeholder-contrast-${testInfo.project.name}-${theme}.json`, placeholderEvidence);
    expect(placeholderEvidence.disabled, "the enabled composer is measured").toBe(false);
    expect(placeholderEvidence.effectsClear, "placeholder and opaque textarea background have no opacity/blend/filter effects").toBe(true);
    expect(placeholderEvidence.contrastRatio, "placeholder contrast can be measured against an opaque textarea background").toEqual(expect.any(Number));
    expect(placeholderEvidence.contrastRatio, "placeholder text meets the 4.5:1 normal-text contrast threshold").toBeGreaterThanOrEqual(4.5);

    const axe = await new AxeBuilder({ page }).include('[data-testid="assistant-panel"]').analyze();
    const snapshot = await captureAssistantContrastSnapshot(page, axe);
    const audit = evaluateAssistantContrastAudit(snapshot);
    const evidence = {
      project: testInfo.project.name,
      theme,
      viewport: snapshot.viewport,
      targetRootCounts: snapshot.targetRootCounts,
      rawAxe: snapshot.rawAxe,
      rawNodeMappings: snapshot.rawNodeMappings,
      targets: snapshot.targets,
      audit,
    };
    await attachJson(testInfo, `assistant-contrast-${theme}-raw-axe.json`, snapshot.rawAxe);
    await attachJson(testInfo, `assistant-contrast-${theme}-measurements.json`, evidence);
    await page.screenshot({ path: testInfo.outputPath(`assistant-contrast-${testInfo.project.name}-${theme}.png`), fullPage: false });

    // Raw axe incompletes stay in the evidence. This audit resolves their exact nodes separately.
    expect(snapshot.rawAxe.counts.violations, "raw axe violations").toBe(0);
    expect(snapshot.targetRootCounts, "the measured semantic target roots").toEqual({ readiness: 1, answers: 1, disclaimers: 1 });
    expect(audit.issues, "measured contrast and line visibility issues").toEqual([]);
  });
}
