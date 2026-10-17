// Exercise saved private research on the actual fixture server in both themes and viewports.
const AxeBuilder = require("@axe-core/playwright").default;
const { test, expect } = require("./fixtures");

async function attachAxeResults(page, testInfo, name) {
  const results = await new AxeBuilder({ page }).analyze();
  await testInfo.attach(`${name}-axe.json`, {
    body: Buffer.from(JSON.stringify(results, null, 2)),
    contentType: "application/json",
  });
  return results;
}

async function prepareCapture(page) {
  await page.locator("main").focus();
  // Fixed offscreen skip links must be captured from the document origin after focus scrolls.
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
}

for (const theme of ["light", "dark"]) {
  test(`thesis editing and immutable history in ${theme}`, async ({ page, restartableApplication }, testInfo) => {
    await page.addInitScript(value => localStorage.setItem("stock-probs.theme", value), theme);
    await page.goto(`${restartableApplication.url}/research/theses`);
    const thesisList = page.getByRole("complementary", { name: "My theses" }).locator("li");
    await expect(page.getByText("No theses yet. Record an idea to start your research history.", { exact: true })).toBeVisible();
    await expect(thesisList).toHaveCount(0);
    const title = `Research idea ${testInfo.project.name} ${theme}`;
    await page.getByRole("button", { name: "New thesis", exact: true }).click();
    await page.getByLabel("Instrument symbol", { exact: true }).fill("SPY");
    await page.getByRole("combobox", { name: "Instrument type", exact: true }).selectOption("etf");
    await page.getByLabel("Title", { exact: true }).fill(title);
    await page.getByRole("textbox", { name: "My thesis", exact: true }).fill("Diversification with an explicit review date.");
    await page.getByLabel("Risks", { exact: true }).fill("Market concentration.");
    await page.getByLabel("What would change my mind", { exact: true }).fill("A changed index mandate.");
    await page.getByLabel("Review date", { exact: true }).fill("2026-12-01");
    const saved = page.waitForResponse(response => response.url().endsWith("/api/v1/theses") && response.request().method() === "POST");
    await page.getByRole("button", { name: "Save reviewed thesis" }).click();
    expect((await saved).status()).toBe(201);
    await expect(page.getByRole("heading", { name: title, exact: true })).toBeVisible();
    await expect(thesisList).toHaveCount(1);
    const timeline = page.getByRole("group", { name: "Thesis timeline", exact: true });
    await expect(timeline.locator("div").nth(0).locator("span").first()).toHaveText("Created");
    await expect(timeline.locator("div").nth(1).locator("span").first()).toHaveText("Reviewed");
    await expect(timeline.locator("div").nth(1).getByText("Unknown", { exact: true })).toBeVisible();
    await expect(timeline.locator("div").nth(2).locator("span").first()).toHaveText("Revised");
    await expect(timeline.locator("div").nth(2).getByText("Unknown", { exact: true })).toBeVisible();
    await expect(page.getByRole("button", { name: "Ask assistant to draft", exact: true })).toBeVisible();
    if (await page.evaluate(() => matchMedia("(max-width: 760px)").matches)) {
      const listToggle = page.getByRole("complementary", { name: "My theses" }).getByRole("button").first();
      await expect(listToggle).toHaveAccessibleName("My theses (1)");
      await expect(listToggle).toHaveAttribute("aria-expanded", "false");
      await expect(thesisList.first()).toBeHidden();
      await expect(page.getByRole("heading", { name: title, exact: true })).toBeVisible();
      await listToggle.click();
      await expect(listToggle).toHaveAccessibleName("Hide My theses");
      await expect(thesisList.first()).toBeVisible();
      await listToggle.click();
      await expect(listToggle).toHaveAttribute("aria-expanded", "false");
    }
    await page.getByRole("button", { name: "Edit thesis", exact: true }).click();
    await page.getByRole("textbox", { name: "My thesis", exact: true }).fill("Revised reasoning, retaining the original evidence.");
    await page.getByRole("button", { name: "Save reviewed thesis" }).click();
    await expect(page.getByText("Revised reasoning, retaining the original evidence.", { exact: true })).toBeVisible();
    await expect(page.getByRole("heading", { name: title, exact: true })).toBeFocused();
    await expect(timeline.locator("div").nth(2).getByText("Unknown", { exact: true })).toBeVisible();
    await page.getByRole("button", { name: "Record review", exact: true }).click();
    await page.getByLabel("Next review date", { exact: true }).fill("2027-01-01");
    await page.getByRole("button", { name: "Confirm reviewed", exact: true }).click();
    await expect(page.getByText("Review date: 2027-01-01", { exact: true })).toBeVisible();
    await expect(timeline.locator("div").nth(1).locator("time")).toHaveCount(1);
    await page.getByRole("button", { name: "Revision history", exact: true }).click();
    const historySection = page.locator("details").filter({ has: page.getByText("Full revision history", { exact: true }) });
    await expect(historySection).toHaveAttribute("open", "");
    await expect(historySection.locator("details")).toHaveCount(3);
    await expect(timeline.locator("div").nth(2).locator("time")).toHaveCount(1);
    const firstRevision = historySection.getByText(/^Revision 1 ·/);
    await firstRevision.click();
    await expect(page.getByText("Diversification with an explicit review date.", { exact: true })).toBeVisible();
    const axe = await attachAxeResults(page, testInfo, "thesis-history");
    expect(axe.violations).toEqual([]);
    expect(axe.incomplete).toEqual([]);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
    await firstRevision.click();
    await expect(historySection.locator("details[open]")).toHaveCount(0);
    await historySection.getByText("Full revision history", { exact: true }).click();
    await expect(historySection).not.toHaveAttribute("open", "");
    await page.getByRole("button", { name: "Revision history", exact: true }).click();
    await expect(historySection).toHaveAttribute("open", "");
    await expect(firstRevision).toBeVisible();
    await historySection.getByText("Full revision history", { exact: true }).click();
    await expect(historySection).not.toHaveAttribute("open", "");
    await expect(thesisList).toHaveCount(1);
    await prepareCapture(page);
    await page.screenshot({ path: testInfo.outputPath(`theses-${theme}.png`), fullPage: true });
  });

  test(`comparison capture and provider-free saved replay in ${theme}`, async ({ page, restartableApplication }, testInfo) => {
    await page.addInitScript(value => localStorage.setItem("stock-probs.theme", value), theme);
    const requests = [];
    page.on("request", request => requests.push(new URL(request.url()).pathname));
    await page.goto(`${restartableApplication.url}/tools/compare`);
    const savedComparisonList = page.getByRole("heading", { name: "Saved comparisons", exact: true }).locator("..").getByRole("listitem");
    await expect(page.getByText("No saved comparisons yet.", { exact: true })).toBeVisible();
    await expect(savedComparisonList).toHaveCount(0);
    await expect(page.getByRole("heading", { name: "Choose two to four instruments" })).toBeVisible();
    expect(requests).not.toContain("/api/v1/forecasts");
    const selectedInstruments = page.getByRole("group", { name: "Selected instruments", exact: true });
    await expect(selectedInstruments.getByRole("group")).toHaveCount(2);
    await expect(page.getByLabel("Instrument 1 symbol", { exact: true })).toBeVisible();
    await expect(page.getByLabel("Instrument 1 type", { exact: true })).toBeVisible();
    await expect(page.getByLabel("Instrument 2 symbol", { exact: true })).toBeVisible();
    await expect(page.getByLabel("Instrument 2 type", { exact: true })).toBeVisible();
    const addInstrument = page.getByRole("button", { name: "Add instrument", exact: true });
    await expect(addInstrument).toBeVisible();
    if (await page.evaluate(() => matchMedia("(max-width: 760px)").matches)) {
      for (const control of [
        selectedInstruments.getByRole("group", { name: "Instrument 1", exact: true }),
        page.getByLabel("Instrument 1 symbol", { exact: true }),
        page.getByLabel("Instrument 1 type", { exact: true }),
        addInstrument,
        page.getByRole("combobox", { name: /^Chart range/ }),
        page.getByRole("button", { name: "Compare instruments", exact: true }),
      ]) {
        const box = await control.boundingBox();
        expect(box).not.toBeNull();
        expect(Math.round(box.height)).toBe(44);
      }
    }
    await addInstrument.click();
    await expect(selectedInstruments.getByRole("group")).toHaveCount(3);
    await expect(page.getByLabel("Instrument 3 symbol", { exact: true })).toBeVisible();
    await expect(page.getByLabel("Instrument 3 type", { exact: true })).toBeVisible();
    const removeInstrument = page.getByRole("button", { name: "Remove instrument 3", exact: true });
    await expect(removeInstrument).toBeVisible();
    if (await page.evaluate(() => matchMedia("(max-width: 760px)").matches)) {
      const box = await removeInstrument.boundingBox();
      expect(box).not.toBeNull();
      expect(Math.round(box.height)).toBe(44);
    }
    await removeInstrument.click();
    await expect(selectedInstruments.getByRole("group")).toHaveCount(2);
    await page.getByLabel("Instrument 1 symbol").fill("ACDC");
    await page.getByLabel("Instrument 2 symbol").fill("SPY");
    await page.getByRole("button", { name: "Compare instruments", exact: true }).click();
    await expect(page.getByRole("heading", { name: "Comparison metrics" })).toBeVisible();
    await expect(page.getByText("Weekly forecast · 5 trading sessions", { exact: true })).toBeVisible();
    expect(requests).not.toContain("/api/v1/forecasts");
    await page.getByRole("button", { name: "Save comparison", exact: true }).click();
    await expect(page.getByRole("button", { name: "Comparison saved" })).toBeDisabled();
    await expect(savedComparisonList).toHaveCount(1);
    const before = requests.filter(path => path === "/api/v1/comparisons/preview").length;
    await page.getByRole("button", { name: /ACDC \/ SPY/ }).first().click();
    expect(requests.filter(path => path === "/api/v1/comparisons/preview")).toHaveLength(before);
    const exactValues = page.locator("details").filter({ has: page.getByText("Exact chart values", { exact: true }) });
    await exactValues.getByText("Exact chart values", { exact: true }).click();
    await expect(page.getByRole("table", { name: "Normalized unadjusted values on common observed sessions" })).toBeVisible();
    expect(await page.getByRole("table", { name: "Normalized unadjusted values on common observed sessions" }).locator("tbody tr").count()).toBeLessThanOrEqual(20);
    const axe = await attachAxeResults(page, testInfo, "comparison-saved-values-open");
    expect(axe.violations).toEqual([]);
    expect(axe.incomplete).toEqual([]);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true);
    await expect(savedComparisonList).toHaveCount(1);
    await exactValues.getByText("Exact chart values", { exact: true }).click();
    await expect(page.getByRole("table", { name: "Normalized unadjusted values on common observed sessions" })).toBeHidden();
    await prepareCapture(page);
    await page.screenshot({ path: testInfo.outputPath(`compare-${theme}.png`), fullPage: true });
  });

  test(`split evidence explains unavailable metrics and survives saved replay in ${theme}`, async ({ page }, testInfo) => {
    await page.addInitScript(value => localStorage.setItem("stock-probs.theme", value), theme);
    const previewId = "11111111-1111-4111-8111-111111111111";
    const savedId = "22222222-2222-4222-8222-222222222222";
    const capturedAt = "2026-10-16T20:00:00+00:00";
    const commonEvidence = {
      provider: "Yahoo Finance",
      requested_range: "1mo",
      series_as_of: capturedAt,
      completeness: "not_established",
    };
    const data = {
      captured_at: capturedAt,
      dates: ["2026-10-01", "2026-10-02", "2026-10-03"],
      range: "1mo",
      basis: "Unadjusted daily closes; not total return.",
      instruments: [
        {
          symbol: "ABC",
          identity: { display_name: "Example ABC", asset_type: "stock", currency: "USD" },
          currency: "USD",
          source: "Yahoo Finance",
          as_of: capturedAt,
          label: "Yahoo Finance comparison.",
          normalized: [{ date: "2026-10-01", value: 100 }, { date: "2026-10-02", value: 66.67 }, { date: "2026-10-03", value: 70 }],
          price_change: null,
          volatility: null,
          max_drawdown: null,
          sample_count: 3,
          excluded_chart_sessions: 0,
          common_sample_count: 3,
          missing_observations: 0,
          quality: "corporate_action_detected",
          metric_suppression_reason: "Unadjusted closes include a provider-reported split ratio of 1.5 new shares per old share on 2026-10-02; price change, volatility, and drawdown are unavailable.",
          action_evidence: {
            ...commonEvidence,
            status: "provider_events_returned",
            canonical_symbol: "ABC",
            available_fields: ["Dividends", "Stock Splits"],
            events: [
              { kind: "split", date: "2026-10-02", new_shares_per_old_share: 1.5 },
              { kind: "dividend", date: "2026-10-03", amount: 0.42, currency: null },
            ],
          },
          raw_bars: [
            { timestamp: "2026-10-01T16:00:00+00:00", close: 150 },
            { timestamp: "2026-10-02T16:00:00+00:00", close: 100 },
            { timestamp: "2026-10-03T16:00:00+00:00", close: 105 },
          ],
        },
        {
          symbol: "SPY",
          identity: { display_name: "Example S&P ETF", asset_type: "etf", currency: "USD" },
          currency: "USD",
          source: "Yahoo Finance",
          as_of: capturedAt,
          label: "Yahoo Finance comparison.",
          normalized: [{ date: "2026-10-01", value: 100 }, { date: "2026-10-02", value: 102 }, { date: "2026-10-03", value: 104 }],
          price_change: 0.04,
          volatility: 0.2,
          max_drawdown: 0,
          sample_count: 3,
          excluded_chart_sessions: 0,
          common_sample_count: 3,
          missing_observations: 0,
          quality: "unadjusted_price_only",
          metric_suppression_reason: null,
          action_evidence: { ...commonEvidence, status: "no_reported_action_evidence", canonical_symbol: "SPY", available_fields: [], events: [] },
          raw_bars: [
            { timestamp: "2026-10-01T16:00:00+00:00", close: 100 },
            { timestamp: "2026-10-02T16:00:00+00:00", close: 102 },
            { timestamp: "2026-10-03T16:00:00+00:00", close: 104 },
          ],
        },
      ],
    };
    const saved = { id: savedId, created_at: capturedAt, data };
    let isSaved = false;
    let previewRequests = 0;
    page.on("request", request => {
      if (new URL(request.url()).pathname === "/api/v1/comparisons/preview") previewRequests += 1;
    });
    await page.route("**/api/v1/comparisons**", async route => {
      const request = route.request();
      const url = new URL(request.url());
      if (url.pathname.endsWith("/preview")) {
        await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ preview_id: previewId, expires_at: "2026-10-16T20:10:00+00:00", data }) });
      } else if (request.method() === "POST") {
        isSaved = true;
        await route.fulfill({ status: 201, contentType: "application/json", body: JSON.stringify(saved) });
      } else {
        const items = isSaved ? [saved] : [];
        await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ items, total: items.length, page: 1, page_size: 20, has_next: false }) });
      }
    });
    await page.goto("/tools/compare");
    await page.getByLabel("Instrument 1 symbol").fill("ABC");
    await page.getByLabel("Instrument 2 symbol").fill("SPY");
    await page.getByRole("button", { name: "Compare instruments", exact: true }).click();
    await expect(page.getByText("Daily closes · unadjusted", { exact: true })).toBeVisible();
    const metricsSection = page.getByRole("heading", { name: "Comparison metrics", exact: true }).locator("..");
    const splitWarning = metricsSection.getByRole("note").filter({ hasText: "ABC:" });
    await expect(splitWarning).toContainText("provider-reported split ratio of 1.5 new shares per old share");
    const evidenceDisclosure = page.locator("details").filter({ has: page.getByText("Provider and corporate-action details", { exact: true }) });
    await evidenceDisclosure.getByText("Provider and corporate-action details", { exact: true }).click();
    await expect(evidenceDisclosure).toContainText("2026-10-02: 1.5 new shares per old share");
    await expect(evidenceDisclosure).toContainText("2026-10-03: dividend 0.42; currency not provided");
    const affectedRow = page.getByRole("row").filter({ hasText: "ABC" }).last();
    await expect(affectedRow).toContainText("Unavailable");
    const unaffectedRow = page.getByRole("row").filter({ hasText: "SPY" }).last();
    await expect(unaffectedRow).toContainText("4.0%");
    await page.getByRole("button", { name: "Save comparison", exact: true }).click();
    await expect(page.getByRole("button", { name: "Comparison saved", exact: true })).toBeDisabled();
    const countBeforeReopen = previewRequests;
    await page.getByRole("button", { name: /ABC \/ SPY/ }).last().click();
    await expect(splitWarning).toContainText("provider-reported split ratio of 1.5 new shares per old share");
    expect(previewRequests).toBe(countBeforeReopen);
    const axe = await attachAxeResults(page, testInfo, "comparison-split-evidence");
    expect(axe.violations).toEqual([]);
    expect(axe.incomplete).toEqual([]);
  });
}

function createBoundedGate(maximumWaitMs = 10_000) {
  let timer;
  let releasePromise;
  let released = false;
  let autoReleased = false;
  const promise = new Promise(resolve => {
    releasePromise = () => {
      if (released) return;
      released = true;
      if (timer) clearTimeout(timer);
      resolve();
    };
  });
  return {
    wait: () => {
      if (!released && !timer) {
        timer = setTimeout(() => {
          autoReleased = true;
          releasePromise();
        }, maximumWaitMs);
      }
      return promise;
    },
    release: releasePromise,
    autoReleased: () => autoReleased,
  };
}

for (const theme of ["light", "dark"]) {
  test(`research empty loading error and unavailable states in ${theme}`, async ({ page, browserDiagnostics }, testInfo) => {
    browserDiagnostics.expectHttpFailures(
      { method: "GET", path: "/api/v1/theses", status: 503, count: 2 },
      { method: "GET", path: "/api/v1/comparisons", status: 503 },
      { method: "POST", path: "/api/v1/comparisons/preview", status: 422 },
    );
    const empty = { items: [], total: 0, page: 1, page_size: 20, has_next: false };
    const thesisLoading = createBoundedGate();
    const comparisonLoading = createBoundedGate();
    let thesisMode = "loading";
    let comparisonMode = "loading";
    try {
      await page.addInitScript(value => localStorage.setItem("stock-probs.theme", value), theme);
      await page.route("**/api/v1/theses?*", async route => {
        if (thesisMode === "loading") await thesisLoading.wait();
        if (thesisMode === "error" || thesisMode === "unavailable") {
          const message = thesisMode === "error" ? "The thesis list could not be loaded." : "These research features are not enabled for this account.";
          return route.fulfill({ status: 503, contentType: "application/json", body: JSON.stringify({ error: { code: "research_unavailable", message } }) });
        }
        return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(empty) });
      });
      await page.goto("/research/theses");
      await expect(page.getByText("Loading your theses…", { exact: true })).toBeVisible();
      await expect(page.getByRole("button", { name: "New thesis", exact: true })).toBeDisabled();
      await prepareCapture(page);
      await page.screenshot({ path: testInfo.outputPath(`theses-loading-${theme}.png`), fullPage: true });
      await expect(page.getByText("Loading your theses…", { exact: true })).toBeVisible();
      expect(thesisLoading.autoReleased()).toBe(false);
      thesisMode = "empty";
      thesisLoading.release();
      const thesisList = page.getByRole("complementary", { name: "My theses" }).locator("li");
      await expect(page.getByText("No theses yet. Record an idea to start your research history.", { exact: true })).toBeVisible();
      await expect(thesisList).toHaveCount(0);
      await prepareCapture(page);
      await page.screenshot({ path: testInfo.outputPath(`theses-empty-${theme}.png`), fullPage: true });
      thesisMode = "error";
      await page.reload();
      await expect(page.locator("main").getByRole("alert")).toContainText("The thesis list could not be loaded.");
      await expect(page.getByRole("button", { name: "Retry loading", exact: true })).toBeVisible();
      await prepareCapture(page);
      await page.screenshot({ path: testInfo.outputPath(`theses-error-${theme}.png`), fullPage: true });
      thesisMode = "empty";
      await page.getByRole("button", { name: "Retry loading", exact: true }).click();
      await expect(page.locator("main").getByRole("alert")).toHaveCount(0);
      await expect(page.getByText("No theses yet. Record an idea to start your research history.", { exact: true })).toBeVisible();
      thesisMode = "unavailable";
      await page.reload();
      await expect(page.locator("main").getByRole("alert")).toContainText("These research features are not enabled for this account.");
      await expect(page.getByRole("button", { name: "Retry loading", exact: true })).toBeVisible();
      const thesisAxe = await attachAxeResults(page, testInfo, "thesis-unavailable");
      expect(thesisAxe.violations).toEqual([]);
      expect(thesisAxe.incomplete).toEqual([]);
      await prepareCapture(page);
      await page.screenshot({ path: testInfo.outputPath(`theses-unavailable-${theme}.png`), fullPage: true });

      await page.route("**/api/v1/comparisons?*", async route => {
        if (comparisonMode === "loading") await comparisonLoading.wait();
        if (comparisonMode === "unavailable") {
          return route.fulfill({ status: 503, contentType: "application/json", body: JSON.stringify({ error: { code: "research_unavailable", message: "Saved comparisons are unavailable for this account." } }) });
        }
        return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(empty) });
      });
      await page.route("**/api/v1/comparisons/preview", route => route.fulfill({ status: 422, contentType: "application/json", body: JSON.stringify({ error: { code: "insufficient_common_history", message: "These instruments have too few common daily sessions." } }) }));
      await page.goto("/tools/compare");
      await expect(page.getByText("Loading saved comparisons…", { exact: true })).toBeVisible();
      await prepareCapture(page);
      await page.screenshot({ path: testInfo.outputPath(`compare-loading-${theme}.png`), fullPage: true });
      await expect(page.getByText("Loading saved comparisons…", { exact: true })).toBeVisible();
      expect(comparisonLoading.autoReleased()).toBe(false);
      comparisonMode = "empty";
      comparisonLoading.release();
      const savedComparisonList = page.getByRole("heading", { name: "Saved comparisons", exact: true }).locator("..").getByRole("listitem");
      await expect(page.getByText("No saved comparisons yet.", { exact: true })).toBeVisible();
      await expect(savedComparisonList).toHaveCount(0);
      await prepareCapture(page);
      await page.screenshot({ path: testInfo.outputPath(`compare-empty-${theme}.png`), fullPage: true });
      comparisonMode = "unavailable";
      await page.reload();
      await expect(page.locator("main").getByRole("alert")).toContainText("Saved comparisons are unavailable for this account.");
      await expect(page.getByRole("button", { name: "Retry saved comparisons", exact: true })).toBeVisible();
      await prepareCapture(page);
      await page.screenshot({ path: testInfo.outputPath(`compare-unavailable-${theme}.png`), fullPage: true });
      comparisonMode = "empty";
      await page.getByRole("button", { name: "Retry saved comparisons", exact: true }).click();
      await expect(page.locator("main").getByRole("alert")).toHaveCount(0);
      await expect(page.getByText("No saved comparisons yet.", { exact: true })).toBeVisible();
      await page.getByLabel("Instrument 1 symbol").fill("ACDC");
      await page.getByLabel("Instrument 2 symbol").fill("SPY");
      await page.getByRole("button", { name: "Compare instruments", exact: true }).click();
      await expect(page.locator("main").getByRole("alert")).toContainText("These instruments have too few common daily sessions.");
      await expect(page.getByRole("heading", { name: "Choose two to four instruments", exact: true })).toBeVisible();
      const comparisonAxe = await attachAxeResults(page, testInfo, "comparison-error");
      expect(comparisonAxe.violations).toEqual([]);
      expect(comparisonAxe.incomplete).toEqual([]);
      await prepareCapture(page);
      await page.screenshot({ path: testInfo.outputPath(`compare-error-${theme}.png`), fullPage: true });
    } finally {
      thesisLoading.release();
      comparisonLoading.release();
    }
  });
}
