// Deterministic Chromium timings use browser APIs and local fixtures; no Lighthouse or network is used.
const { test, expect } = require("@playwright/test");
const { spawn } = require("node:child_process");
const fs = require("node:fs/promises");
const net = require("node:net");
const path = require("node:path");
const { performance } = require("node:perf_hooks");

const root = path.resolve(__dirname, "../../..");
const budgets = require("../performance-budgets.json");
const artifactPath = process.env.STOCK_PROBS_PERFORMANCE_ARTIFACT;
const nativeArchitecture = process.arch === "x64" ? "x86_64" : process.arch;
const staticShellPaths = ["index.html", "api-docs.html", "app.css", "app.js", "theme.js", "favicon.svg"];

function isoNow() {
  return new Date().toISOString();
}

function percentile(values, fraction) {
  if (!values.length) throw new Error("percentile requires samples");
  const ordered = [...values].sort((left, right) => left - right);
  return ordered[Math.max(0, Math.ceil(fraction * ordered.length) - 1)];
}

function statistics(values, unit) {
  return {
    p50: Number(percentile(values, 0.5).toFixed(3)),
    p95: Number(percentile(values, 0.95).toFixed(3)),
    max: Number(Math.max(...values).toFixed(3)),
    unit,
  };
}

async function freePort() {
  const server = net.createServer();
  await new Promise((resolve, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", resolve);
  });
  const port = server.address().port;
  await new Promise((resolve, reject) => server.close((error) => (error ? reject(error) : resolve())));
  return port;
}

async function waitForReady(port, state) {
  const attempts = [];
  const deadline = performance.now() + 20_000;
  while (performance.now() < deadline) {
    if (state.exit !== null) throw new Error(`browser fixture app exited (${state.exit}): ${state.stderr}`);
    const started = performance.now();
    try {
      const response = await fetch(`http://127.0.0.1:${port}/api/v1/readiness`);
      attempts.push({ elapsed_ms: performance.now() - started, status: response.status, error: null });
      if (response.ok && (await response.json()).status === "ready") return attempts;
    } catch (error) {
      attempts.push({ elapsed_ms: null, status: null, error: error.constructor.name });
    }
    await new Promise((resolve) => setTimeout(resolve, 50));
  }
  throw new Error("browser fixture app did not become ready within 20 seconds");
}

async function bounded(label, action, timeoutMs = 5_000) {
  let timer;
  try {
    return await Promise.race([
      action,
      new Promise((resolve, reject) => {
        timer = setTimeout(() => reject(new Error(`${label} exceeded ${timeoutMs}ms`)), timeoutMs);
      }),
    ]);
  } finally {
    clearTimeout(timer);
  }
}

async function stop(child) {
  if (child.exitCode !== null) {
    return { stopped: true, signal: "already-exited", exit_code: child.exitCode };
  }
  const exited = new Promise((resolve) => child.once("exit", resolve));
  child.kill("SIGTERM");
  try {
    await bounded("browser fixture SIGTERM", exited);
    return {
      stopped: true, signal: "SIGTERM", exit_code: child.exitCode, signal_code: child.signalCode,
    };
  } catch (error) {
    child.kill("SIGKILL");
    await bounded("browser fixture SIGKILL", exited);
    return {
      stopped: true,
      signal: "SIGKILL",
      exit_code: child.exitCode,
      signal_code: child.signalCode,
      term_error: error.message,
    };
  }
}

async function removeRuntime(runtime) {
  await bounded("browser runtime removal", fs.rm(runtime, { recursive: true, force: true }));
  try {
    await fs.stat(runtime);
  } catch (error) {
    if (error.code === "ENOENT") return true;
    throw error;
  }
  return false;
}

async function writeArtifact(payload) {
  if (!artifactPath) throw new Error("STOCK_PROBS_PERFORMANCE_ARTIFACT is required");
  await fs.mkdir(path.dirname(artifactPath), { recursive: true });
  await fs.writeFile(artifactPath, `${JSON.stringify(payload, null, 2)}\n`);
}

test("pinned render interaction layout and request budgets", async ({ page }, testInfo) => {
  test.skip(process.env.STOCK_PROBS_PERFORMANCE !== "1", "Run only through the M06 harness.");
  test.setTimeout(180_000);
  const startedUtc = isoNow();
  const staticShell = Object.fromEntries(await Promise.all(staticShellPaths.map(async (name) => (
    [name, (await fs.stat(path.join(root, "src/stock_probs/static", name))).size]
  ))));
  const staticShellBytes = Object.values(staticShell).reduce((total, size) => total + size, 0);
  const runtime = testInfo.outputPath("runtime");
  await fs.rm(runtime, { recursive: true, force: true });
  await fs.mkdir(runtime, { recursive: true });
  const port = await freePort();
  const baseURL = `http://127.0.0.1:${port}`;
  const command = [
    path.join(root, ".dev-venv/bin/python"), "-m", "stock_probs.cli", "serve",
    "--host", "127.0.0.1", "--port", String(port),
  ];
  const child = spawn(command[0], command.slice(1), {
    cwd: root,
    env: {
      ...process.env,
      STOCK_PROBS_DATA_DIR: runtime,
      STOCK_PROBS_PROVIDER: "fixture",
      STOCK_PROBS_FIXTURE_NOW: "2025-01-10T17:03:00+00:00",
    },
    stdio: ["ignore", "ignore", "pipe"],
  });
  const state = { exit: null, stderr: "" };
  child.stderr.on("data", (chunk) => { state.stderr = `${state.stderr}${chunk}`.slice(-16_384); });
  child.once("exit", (code) => { state.exit = code; });

  const renderWarmups = [];
  const renderSamples = [];
  const interactionWarmups = [];
  const interactionSamples = [];
  const layoutSamples = [];
  const navigationRequests = [];
  const networkRequests = [];
  const networkResponses = [];
  const networkRequestItems = new Map();
  const networkBodies = [];
  let m09Browser = null;
  let networkPhase = "startup";
  let readinessAttempts = [];
  let runError = null;
  const cleanupProof = {
    order: ["stop-child", "remove-runtime", "verify-runtime-absent"],
    child_stop: null,
    database_present_before_removal: false,
    runtime_removed: false,
    database_removed: false,
    error: null,
  };
  const auditRequest = (request) => {
    const parsed = new URL(request.url());
    const item = {
      sequence: networkRequests.length + 1,
      phase: networkPhase,
      method: request.method(),
      url: request.url(),
      origin: parsed.origin,
      hostname: parsed.hostname,
      pathname: parsed.pathname,
      path: `${parsed.pathname}${parsed.search}`,
      resource_type: request.resourceType(),
      response_sequence: null,
      failure: null,
    };
    networkRequestItems.set(request, item);
    networkRequests.push(item);
  };
  const auditResponse = (response) => {
    const request = response.request();
    const parsed = new URL(response.url());
    const proof = {
      sequence: networkResponses.length + 1,
      request_sequence: networkRequestItems.get(request)?.sequence ?? null,
      phase: networkRequestItems.get(request)?.phase ?? networkPhase,
      method: request.method(),
      url: response.url(),
      origin: parsed.origin,
      pathname: parsed.pathname,
      path: `${parsed.pathname}${parsed.search}`,
      status: response.status(),
      bytes: null,
      body_error: null,
    };
    networkResponses.push(proof);
    const item = networkRequestItems.get(request);
    if (item) item.response_sequence = proof.sequence;
    networkBodies.push(response.body().then(
      (body) => { proof.bytes = body.length; },
      (error) => { proof.body_error = `${error.constructor.name}: ${error.message}`; },
    ));
  };
  const auditRequestFailed = (request) => {
    const item = networkRequestItems.get(request);
    if (item) item.failure = request.failure()?.errorText ?? "unknown request failure";
  };
  page.on("request", auditRequest);
  page.on("response", auditResponse);
  page.on("requestfailed", auditRequestFailed);

  await page.addInitScript(() => {
    window.__m06LayoutShifts = [];
    new PerformanceObserver((list) => {
      for (const entry of list.getEntries()) {
        if (!entry.hadRecentInput) window.__m06LayoutShifts.push(entry.value);
      }
    }).observe({ type: "layout-shift", buffered: true });
  });

  async function navigate(viewport, phase, sampleIndex) {
    networkPhase = `${phase}-navigation-${sampleIndex}`;
    await page.setViewportSize({ width: viewport, height: 900 });
    const requestStart = networkRequests.length;
    const responseStart = networkResponses.length;
    const bodyStart = networkBodies.length;
    const started = performance.now();
    await page.goto(baseURL, { waitUntil: "domcontentloaded" });
    await expect(page.locator("#system-label")).toContainText("Local service ready");
    await expect(page.locator("#history-content")).not.toContainText("Loading");
    await page.evaluate(() => new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve))));
    const readyMs = performance.now() - started;
    await Promise.all(networkBodies.slice(bodyStart));
    const requests = networkRequests.slice(requestStart);
    const responses = networkResponses.slice(responseStart);
    const browserMetrics = await page.evaluate(() => ({
      fcp_ms: performance.getEntriesByName("first-contentful-paint")[0]?.startTime ?? null,
      cls: window.__m06LayoutShifts.reduce((total, value) => total + value, 0),
      body_width: document.body.scrollWidth,
      viewport_width: window.visualViewport?.width || document.documentElement.clientWidth,
      interactive_rects: [...document.querySelectorAll("a, button, input, select")]
        .filter((element) => {
           const style = getComputedStyle(element);
           const rect = element.getBoundingClientRect();
           return style.visibility !== "hidden" && style.display !== "none"
             && !element.closest("details:not([open])") && rect.width > 0 && rect.height > 0;
        })
        .map((element) => {
          const rect = element.getBoundingClientRect();
          return { tag: element.tagName, id: element.id, left: rect.left, right: rect.right, top: rect.top, bottom: rect.bottom };
        }),
    }));
    let overlaps = 0;
    for (let left = 0; left < browserMetrics.interactive_rects.length; left += 1) {
      for (let right = left + 1; right < browserMetrics.interactive_rects.length; right += 1) {
        const a = browserMetrics.interactive_rects[left];
        const b = browserMetrics.interactive_rects[right];
        if (Math.min(a.right, b.right) > Math.max(a.left, b.left)
          && Math.min(a.bottom, b.bottom) > Math.max(a.top, b.top)) overlaps += 1;
      }
    }
    const responseBytes = responses.reduce((total, response) => total + (response.bytes ?? 0), 0);
    const designated = responses.find((response) => response.pathname === "/api/v1/readiness");
    const sample = {
      phase,
      sample_index: sampleIndex,
      viewport,
      ready_ms: readyMs,
      fcp_ms: browserMetrics.fcp_ms,
      render_ms: Math.max(readyMs, browserMetrics.fcp_ms ?? 0),
      cls: browserMetrics.cls,
      overlap_count: overlaps,
      overflow: browserMetrics.body_width > Math.ceil(browserMetrics.viewport_width),
      request_count: requests.length,
      response_bytes: responseBytes,
      designated_response_bytes: designated?.bytes ?? null,
      requests,
      responses,
    };
    navigationRequests.push(sample);
    return sample;
  }

  async function interaction() {
    networkPhase = "interaction";
    const select = page.locator("#history-page-size");
    const next = (await select.inputValue()) === "10" ? "20" : "10";
    const started = performance.now();
    await select.selectOption(next);
    await expect(select).toHaveValue(next);
    return performance.now() - started;
  }

  try {
    readinessAttempts = await waitForReady(port, state);
    for (let index = 0; index < budgets.warmups; index += 1) {
      renderWarmups.push((await navigate(1440, "warmup", index + 1)).render_ms);
    }
    for (let index = 0; index < budgets.measured_samples; index += 1) {
      const sample = await navigate(
        budgets.viewports[index % budgets.viewports.length], "measured", index + 1,
      );
      renderSamples.push(sample.render_ms);
      if (index < budgets.viewports.length) layoutSamples.push(sample);
    }
    const details = page.locator(".advanced-filters");
    if (!(await details.evaluate((element) => element.open))) await details.locator("summary").click();
    for (let index = 0; index < budgets.warmups; index += 1) interactionWarmups.push(await interaction());
    for (let index = 0; index < budgets.measured_samples; index += 1) interactionSamples.push(await interaction());
    if (process.env.STOCK_PROBS_PERFORMANCE_M09 === "true") {
      page.off("request", auditRequest);
      page.off("response", auditResponse);
      page.off("requestfailed", auditRequestFailed);
      m09Browser = {
        startedUtc: isoNow(), themeWarmups: [], themeSamples: [],
        renderWarmups: [], renderSamples: [], itemCounts: [],
      };
      await Promise.all([
        page.waitForResponse((response) => response.url().includes("/api/v1/forecasts")),
        page.locator("#forecast-submit").click(),
      ]);
      await page.locator(".news-panel").waitFor();
      const fixtureItems = Array.from({ length: 10 }, (_, index) => ({
        id: `fixture-${index + 1}`,
        title: `Fixture headline ${index + 1}`,
        publisher: "Fixture News",
        published_at: "2025-01-10T17:00:00Z",
        url: `https://example.com/news/${index + 1}`,
        related_symbols: ["ACDC"],
      }));
      await page.route("**/api/v1/news?*", (route) => route.fulfill({
        json: {
          query: { symbol: "ACDC", limit: 10 },
          provider: "deterministic browser fixture",
          as_of: "2025-01-10T17:03:00Z",
          items: fixtureItems,
          coverage: { returned_count: 10, partial_metadata: false, refresh_failed: false },
          cache_state: "hit",
        },
      }));
      for (let index = 0; index < budgets.warmups + budgets.measured_samples; index += 1) {
        await page.evaluate(() => { window.__themeActionStart = performance.now(); });
        const selected = index % 2 ? "light" : "dark";
        await page.locator(`.theme-control [name="theme"][value="${selected}"]`).click();
        const elapsed = await page.evaluate(async (value) => {
          await new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)));
          if (document.documentElement.dataset.theme !== value) throw new Error("theme did not paint");
          return performance.now() - window.__themeActionStart;
        }, selected);
        (index < budgets.warmups ? m09Browser.themeWarmups : m09Browser.themeSamples).push(elapsed);
      }
      await page.locator(".news-panel summary").click();
      await page.locator('.news-content[data-state="fresh"], .news-content[data-state="partial"]').waitFor();
      for (let index = 0; index < budgets.warmups + budgets.measured_samples; index += 1) {
        const sample = await page.evaluate(async () => {
          performance.clearResourceTimings();
          const content = document.querySelector(".news-content");
          await window.loadNews(content, "ACDC", 10);
          const entries = performance.getEntriesByType("resource")
            .filter((entry) => entry.name.includes("/api/v1/news?"));
          const responseEnd = entries.at(-1)?.responseEnd;
          if (responseEnd === undefined) throw new Error("news response timing is missing");
          await new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)));
          return {
            elapsed: performance.now() - responseEnd,
            itemCount: content.querySelectorAll(".news-list > li").length,
          };
        });
        (index < budgets.warmups ? m09Browser.renderWarmups : m09Browser.renderSamples)
          .push(sample.elapsed);
        if (index >= budgets.warmups) m09Browser.itemCounts.push(sample.itemCount);
      }
    }
  } catch (error) {
    runError = `${error.constructor.name}: ${error.message}`;
  } finally {
    try {
      page.off("request", auditRequest);
      page.off("response", auditResponse);
      page.off("requestfailed", auditRequestFailed);
      try {
        await bounded("browser response proof collection", Promise.all(networkBodies));
      } catch (error) {
        runError = [runError, `${error.constructor.name}: ${error.message}`].filter(Boolean).join("; ");
      }
      cleanupProof.child_stop = await stop(child);
      try {
        await fs.stat(path.join(runtime, "stock_probs.sqlite3"));
        cleanupProof.database_present_before_removal = true;
      } catch (error) {
        if (error.code !== "ENOENT") throw error;
      }
      cleanupProof.runtime_removed = await removeRuntime(runtime);
      try {
        await fs.stat(path.join(runtime, "stock_probs.sqlite3"));
      } catch (error) {
        if (error.code === "ENOENT") cleanupProof.database_removed = true;
        else throw error;
      }
      if (!cleanupProof.database_present_before_removal
        || !cleanupProof.runtime_removed || !cleanupProof.database_removed) {
        throw new Error("browser runtime or database remained after bounded cleanup");
      }
    } catch (error) {
      cleanupProof.error = `${error.constructor.name}: ${error.message}`;
      runError = [runError, cleanupProof.error].filter(Boolean).join("; ");
    }
  }

  const renderStats = renderSamples.length ? statistics(renderSamples, "ms") : { p50: null, p95: null, max: null, unit: "ms" };
  const interactionStats = interactionSamples.length ? statistics(interactionSamples, "ms") : { p50: null, p95: null, max: null, unit: "ms" };
  const measuredNavigations = navigationRequests.slice(budgets.warmups);
  const allRequests = networkRequests;
  const allResponses = networkResponses;
  const unexpectedRequests = allRequests.filter((request) => (
    request.method !== "GET" || !budgets.allowed_paths.includes(request.pathname)
  ));
  const unexpectedOriginRequests = allRequests.filter((request) => request.origin !== baseURL);
  const externalRequests = allRequests.filter((request) => (
    !["127.0.0.1", "localhost", "::1"].includes(request.hostname)
  ));
  const directYahooRequests = allRequests.filter((request) => (
    request.hostname === "yahoo.com" || request.hostname.endsWith(".yahoo.com")
    || request.hostname === "yahooapis.com" || request.hostname.endsWith(".yahooapis.com")
  ));
  const missingResponses = allRequests.filter((request) => request.response_sequence === null || request.failure);
  const unexpectedResponses = allResponses.filter((response) => (
    response.origin !== baseURL || response.status < 200 || response.status >= 400
    || response.bytes === null || response.body_error !== null
  ));
  const failures = [];
  if (runError) failures.push(runError);
  if (renderWarmups.length < budgets.warmups || renderSamples.length < budgets.measured_samples) failures.push("missing render samples");
  if (interactionWarmups.length < budgets.warmups || interactionSamples.length < budgets.measured_samples) failures.push("missing interaction samples");
  if (renderStats.p95 === null || renderStats.p95 > budgets.render_p95_ms) failures.push("render p95 exceeded");
  if (interactionStats.p95 === null || interactionStats.p95 > budgets.interaction_p95_ms) failures.push("interaction p95 exceeded");
  if (layoutSamples.length !== budgets.viewports.length || layoutSamples.some((sample) => sample.cls > budgets.cls_max)) failures.push("CLS exceeded or viewport missing");
  if (layoutSamples.some((sample) => sample.overlap_count > budgets.overlap_count_max)) failures.push("interactive controls overlap");
  if (layoutSamples.some((sample) => sample.overflow)) failures.push("viewport overflow");
  if (unexpectedRequests.length) failures.push("unexpected request");
  if (externalRequests.length) failures.push("external browser request");
  if (directYahooRequests.length) failures.push("direct Yahoo browser request");
  if (unexpectedOriginRequests.length) failures.push("unexpected browser origin");
  if (missingResponses.length) failures.push("browser request missing a successful response event");
  if (unexpectedResponses.length) failures.push("unexpected browser response");
  if (!cleanupProof.database_present_before_removal || !cleanupProof.runtime_removed
    || !cleanupProof.database_removed || cleanupProof.error) failures.push("browser runtime cleanup failed");
  if (measuredNavigations.some((sample) => sample.request_count > budgets.request_count_max_per_navigation)) failures.push("request count exceeded");
  if (measuredNavigations.some((sample) => sample.response_bytes > budgets.response_bytes_max_per_navigation)) failures.push("response bytes exceeded");
  if (staticShellBytes >= budgets.static_shell_bytes_strict_max) failures.push("static shell bytes exceeded");
  if (measuredNavigations.some((sample) => sample.designated_response_bytes === null
    || sample.designated_response_bytes >= budgets.designated_response_bytes_strict_max)) failures.push("designated response bytes exceeded");
  const result = failures.length ? "Fail" : "Pass";
  const payload = {
    schema_version: 1,
    task_id: process.env.STOCK_PROBS_TASK_ID || "M06",
    row: "browser-budgets",
    fixture_identity: {
      name: "checked-in compact fixture / empty isolated browser history",
      fixture_now: "2025-01-10T17:03:00+00:00",
    },
    isolation: {
      host: "127.0.0.1",
      port,
      temp_dir: runtime,
      process_pid: child.pid,
      process_tree: [child.pid],
      cleanup: "application process terminated; runtime/database removed and absence verified",
      cleanup_proof: cleanupProof,
    },
    environment: {
      architecture: nativeArchitecture,
      execution: `native ${nativeArchitecture}`,
      node: process.version,
      browser: "pinned Playwright Chromium",
    },
    revision: {
      commit: process.env.STOCK_PROBS_REVISION || "working-tree",
      dirty: process.env.STOCK_PROBS_WORKING_TREE_DIRTY === "true",
    },
    utc: { start: startedUtc, end: isoNow() },
    command: [
      "npx", "playwright", "test", "--config",
      process.env.STOCK_PROBS_PERFORMANCE_CONFIG || "generated-performance-config.js",
      "tools/browser/tests/performance.spec.js", "--project=desktop-chromium",
    ],
    warmups: {
      count: Math.min(renderWarmups.length, interactionWarmups.length),
      excluded: true,
      raw: { render_ms: renderWarmups, interaction_ms: interactionWarmups },
    },
    measured_samples: {
      count: Math.min(renderSamples.length, interactionSamples.length),
      unit: "ms",
      raw: { render_ms: renderSamples, interaction_ms: interactionSamples },
    },
    statistics: { render: renderStats, interaction: interactionStats },
    raw: {
      readiness_attempts: readinessAttempts,
      render_samples: measuredNavigations,
      layout_samples: layoutSamples,
      interaction_samples_ms: interactionSamples,
      static_shell: { files: staticShell, bytes: staticShellBytes },
      requests: allRequests,
      responses: allResponses,
      unexpected_requests: unexpectedRequests,
      external_requests: externalRequests,
      direct_yahoo_requests: directYahooRequests,
      unexpected_origin_requests: unexpectedOriginRequests,
      missing_responses: missingResponses,
      unexpected_responses: unexpectedResponses,
      console_result: runError === null ? "no runner error" : runError,
      lighthouse_used: false,
      external_network_used: externalRequests.length > 0,
      ...(m09Browser && { m09_browser: m09Browser }),
      failures,
    },
    threshold: { class: "proposed browser budgets", manifest: "tools/browser/performance-budgets.json", ...budgets },
    result,
    limitation: failures.length ? failures.join("; ") : null,
    artifact: "browser-budgets.json",
    reviewer: process.env.PERFORMANCE_REVIEWER || "PENDING_INDEPENDENT_REVIEW",
  };
  await writeArtifact(payload);
  expect(result, failures.join("; ")).toBe("Pass");
});
