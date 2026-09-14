"use strict";

const fs = require("node:fs");
const fsp = require("node:fs/promises");
const net = require("node:net");
const os = require("node:os");
const path = require("node:path");
const crypto = require("node:crypto");
const { spawn, spawnSync } = require("node:child_process");

const ROOT = path.resolve(__dirname, "../..");
const OUTPUT = path.join(__dirname, "test-results", "latest");
const PUBLICATION = path.join(ROOT, "docs", "walkthrough");
const { chromium } = require(path.join(ROOT, "tools/browser/node_modules/playwright"));
const PLAYWRIGHT_VERSION = require(path.join(ROOT, "tools/browser/node_modules/playwright/package.json")).version;

const PROFILES = [
  { name: "desktop", viewport: { width: 1280, height: 1000 } },
  { name: "mobile", viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true },
];

const STEPS = [
  {
    id: "01-backup-status",
    title: "Confirm the local service and backup status",
    description: "Open the dashboard and confirm that the status line says ready, fixture provider, and backup available.",
    caption: "The ready status identifies deterministic fixture data and says managed backups are available; backup and restore are not exposed in the UI.",
    altText: "Dashboard masthead with ready, fixture provider, and backup available status labels.",
  },
  {
    id: "02-company-lookup",
    title: "Use company-name lookup",
    description: "Type ProFrac in the instrument field, then choose ProFrac Holding Corp. from the result list.",
    caption: "The ProFrac query returns one selectable ACDC stock result.",
    altText: "Instrument search containing ProFrac with a ProFrac Holding Corp., ACDC result card.",
  },
  {
    id: "03-symbol-identity",
    title: "Confirm the selected symbol identity",
    description: "Press Arrow Down and Enter, or tap the result, then check the confirmed ACDC identity before continuing.",
    caption: "The confirmation shows ACDC, NMS, USD, America/New_York, and Stock.",
    altText: "Confirmed identity panel for ProFrac Holding Corp. showing symbol ACDC and stock metadata.",
  },
  {
    id: "04-stock-horizons",
    title: "Run the stock forecast",
    description: "Select Stock, run the ACDC forecast, and compare the Close → next close and Completed 5m → close cards.",
    caption: "The ACDC result presents direction probabilities for both forecast origins.",
    altText: "ACDC forecast comparison with close-to-close and completed-five-minute-to-close result cards.",
  },
  {
    id: "05-chart-and-table",
    title: "Read a chart point and its table equivalent",
    description: "Focus the −10% chart point, read its 0.6% probability, then continue to the matching Return at or below −10% table row.",
    caption: "The focused −10% point and the continuation table row both report 0.6%.",
    altText: "Focused minus-ten-percent chart point with a tooltip reporting 0.6 percent at or below minus ten percent.",
  },
  {
    id: "06-etf-horizons",
    title: "Run the ETF forecast",
    description: "Enter SPY, select ETF, run the forecast, and compare the same two forecast horizons.",
    caption: "The SPY ETF result uses the close-to-close and completed-five-minute-to-close origins.",
    altText: "SPY ETF forecast with two horizon cards and direction probabilities.",
  },
  {
    id: "07-history-filter",
    title: "Search and filter the ledger",
    description: "Set symbol to SPY, status to Successful, and asset type to ETF; select Filter ledger and inspect the matching result.",
    caption: "The active filters narrow the ledger to the successful SPY ETF event.",
    altText: "History ledger filtered to a single successful SPY ETF result.",
  },
  {
    id: "08-saved-reopen",
    title: "Reopen the immutable saved forecast",
    description: "Select Reopen saved forecast on the SPY event and confirm the immutable recorded-result label.",
    caption: "Saved event 2 reopens as an immutable recorded SPY result.",
    altText: "Reopened SPY forecast headed Immutable recorded result and audit event 2.",
  },
  {
    id: "09-fresh-reconstruction",
    title: "Run a fresh historical-cutoff analysis",
    description: "Select Run fresh cutoff analysis and verify that the new calculation is labelled Not the saved forecast.",
    caption: "Fresh event 3 appears separately with its historical cutoff and leaves the saved result unchanged.",
    altText: "Fresh analysis panel labelled Not the saved forecast with a new event and historical cutoff.",
  },
  {
    id: "10-history-downloads",
    title: "Download the filtered CSV and JSON",
    description: "Keep the SPY, Successful, and ETF filters active; select Download CSV and Download JSON to save history.csv and history.json.",
    caption: "The two download controls export the currently filtered SPY history in CSV and JSON formats.",
    altText: "Filtered history controls with Download CSV and Download JSON links visible.",
  },
  {
    id: "11-theme-system",
    title: "Follow the system theme",
    description: "Choose System in the theme control and confirm that the dashboard follows the current dark system preference.",
    caption: "System is selected while the dashboard follows a dark operating-system preference.",
    altText: "Dark dashboard masthead with System selected in the color theme control.",
  },
  {
    id: "12-theme-dark",
    title: "Choose explicit dark mode",
    description: "Choose Dark in the theme control and confirm that the dashboard changes to the explicit dark theme.",
    caption: "Dark is selected as an explicit preference rather than inherited from the system.",
    altText: "Dashboard in dark colors with Dark selected in the theme control.",
  },
  {
    id: "13-theme-reset",
    title: "Reset the theme to system",
    description: "Choose System again to remove the explicit theme choice and return to the current light system preference.",
    caption: "System is selected and the dashboard has returned to the light system theme.",
    altText: "Light dashboard masthead after the color theme control is reset to System.",
  },
  {
    id: "14-theme-first-paint",
    title: "Open the loaded dark API page",
    description: "Choose Dark, open the local API documentation, and inspect the fully loaded dark page; first paint timing is recorded separately.",
    caption: "This image shows the settled dark API page, not the earlier paint transition.",
    altText: "Loaded local API documentation page using the dark theme.",
  },
  {
    id: "15-news-fresh",
    title: "Load fresh current headlines",
    description: "Open current headlines and inspect all five items. Simulated response — fixture clock 10 Jan 2025, 17:03 UTC.",
    caption: "The simulated fresh response shows five SPY headlines, source, as-of time, publication metadata, and safe links.",
    altText: "SPY news panel with five simulated fresh headlines at the 10 January 2025 fixture clock.",
  },
  {
    id: "16-news-empty",
    title: "Show an honest empty news result",
    description: "Open current headlines and confirm the successful empty message. Simulated response — fixture clock 10 Jan 2025, 17:03 UTC.",
    caption: "The simulated empty response says no current headlines were returned and does not present a provider error.",
    altText: "SPY news panel showing a simulated successful empty state at the fixture clock.",
  },
  {
    id: "17-news-partial",
    title: "Label partial headline metadata",
    description: "Inspect item 1 and confirm it remains usable without publisher or publication time. Simulated response — fixture clock 10 Jan 2025, 17:03 UTC.",
    caption: "In the simulated partial response, item 1 lacks publisher and time while the remaining headline data stays available.",
    altText: "Simulated partial SPY headline list whose first item has no publisher or publication time.",
  },
  {
    id: "18-news-stale",
    title: "Explain stale cached headlines",
    description: "Inspect the retained cached headlines and their warning. Simulated stale fallback — fixture clock 10 Jan 2025, 17:03 UTC.",
    caption: "The simulated stale fallback keeps cached headlines visible and labels the displayed as-of time as cached after refresh failure.",
    altText: "Simulated stale SPY news panel with cached headlines and a refresh-failed warning.",
  },
  {
    id: "19-news-provider-failure",
    title: "Report provider failure without cache",
    description: "Open current headlines and read the unavailable message. Simulated provider failure with no cache — fixture clock 10 Jan 2025, 17:03 UTC.",
    caption: "The simulated provider failure reports that no cached headlines can be shown and remains distinct from an empty result.",
    altText: "SPY news panel showing a simulated provider-unavailable state with no cached headlines.",
  },
  {
    id: "20-saved-current-news",
    title: "Keep saved evidence separate from current headlines",
    description: "Reopen the saved SPY forecast and leave Load current headlines for this symbol closed; use it only when current information is wanted.",
    caption: "The closed disclosure keeps current headlines separate; the recorded request-count delta for saved reopen is zero.",
    altText: "Immutable saved SPY forecast with the Load current headlines disclosure closed.",
  },
];

const DECLARED_REQUEST_PATHS = [
  /^\/$/,
  /^\/_next\/static\/.+$/,
  /^\/assets\/(?:app\.css|app\.js|favicon\.svg|theme\.js)$/,
  /^\/api\/v1\/(?:docs|news|readiness|operations\/backups\/status|instruments|forecasts|history|history-export\.(?:csv|json)|saved-forecasts\/\d+|history\/\d+\/reconstructions)$/,
];

const ARTIFACT_BUDGET_BYTES = 20 * 1024 * 1024;
const NEWS_ITEM_SELECTOR = "ol.news-list > li";

function assertStepDefinitions(steps = STEPS) {
  const required = ["lookup", "stock", "chart", "table", "ETF", "history", "saved", "fresh", "CSV", "JSON", "backup", "theme", "dark", "system", "first paint", "headlines", "empty", "partial", "stale", "provider"];
  const text = steps.map(({ title, description }) => `${title} ${description}`).join(" ");
  if (steps.length !== 20 || new Set(steps.map(({ id }) => id)).size !== steps.length) {
    throw new Error("Walkthrough steps must contain twenty unique identifiers.");
  }
  if (steps.some(({ description, caption, altText }) => !description || !caption || !altText || caption === altText)) {
    throw new Error("Every walkthrough step needs distinct instruction, caption, and alt text.");
  }
  for (const term of required) {
    if (!text.toLowerCase().includes(term.toLowerCase())) {
      throw new Error(`Walkthrough steps do not cover ${term}.`);
    }
  }
}

function requestPolicyViolation(url, baseURL) {
  let requestURL;
  try {
    requestURL = new URL(url);
  } catch (_) {
    return `Invalid request URL: ${url}`;
  }
  if (requestURL.origin !== new URL(baseURL).origin) return `Non-loopback request origin: ${requestURL.origin}`;
  if (requestURL.pathname.endsWith(".txt")) return `Undeclared Next RSC request path: ${requestURL.pathname}`;
  if (!DECLARED_REQUEST_PATHS.some((pattern) => pattern.test(requestURL.pathname))) {
    return `Undeclared request path: ${requestURL.pathname}`;
  }
  return null;
}

function assertTooltipMatchesTable(tooltipText, tableRows) {
  const match = /^(\d+(?:\.\d+)?%) probability of return (at or (?:below|above)) ([+-]?\d+%)$/.exec(tooltipText.trim());
  if (!match) throw new Error(`Chart tooltip did not expose a comparable probability: ${tooltipText}`);
  const [, tooltipProbability, operator, threshold] = match;
  const heading = `Return ${operator} ${threshold}`;
  const row = tableRows.find((item) => item.heading === heading);
  if (!row) throw new Error(`Details table did not contain chart threshold: ${heading}`);
  const tableProbability = row.value.split("·", 1)[0].trim();
  if (tooltipProbability !== tableProbability) {
    throw new Error(`Chart/table probability mismatch for ${heading}: ${tooltipProbability} !== ${tableProbability}`);
  }
  return { heading, probability: tooltipProbability };
}

function assertHeadlineEvidence(state, count, abortEventObserved = false) {
  if (state === "fresh" && count < 1) throw new Error(`${NEWS_ITEM_SELECTOR} detected no fresh headline items.`);
  if (state === "superseded" && !abortEventObserved) throw new Error("Pending news stub did not observe its abort event.");
  if (state === "superseded" && count) throw new Error(`Superseded news retained ${count} headline items.`);
  return {
    verification: "headline-items",
    state,
    selector: NEWS_ITEM_SELECTOR,
    count,
    ...(state === "superseded" ? { pending_stub_abort_event_observed: true } : {}),
  };
}

function executableOnPath(name, pathValue = process.env.PATH || "") {
  for (const directory of pathValue.split(path.delimiter).filter(Boolean)) {
    const candidate = path.join(directory, name);
    try {
      fs.accessSync(candidate, fs.constants.X_OK);
      return candidate;
    } catch (_) {
      // Continue through PATH; absence is the expected result on the current development host.
    }
  }
  return null;
}

function bundledFfmpegProbe() {
  const cache = process.env.PLAYWRIGHT_BROWSERS_PATH || path.join(os.homedir(), ".cache", "ms-playwright");
  let versions = [];
  try {
    versions = fs.readdirSync(cache).filter((name) => name.startsWith("ffmpeg-")).sort().reverse();
  } catch (_) {
    return { found: false, gif_capable: false, detail: "Playwright FFmpeg cache directory not found." };
  }
  for (const version of versions) {
    const executable = path.join(cache, version, "ffmpeg-linux");
    if (!fs.existsSync(executable)) continue;
    const probe = spawnSync(executable, ["-hide_banner", "-encoders"], { encoding: "utf8" });
    const output = `${probe.stdout || ""}\n${probe.stderr || ""}`;
    return {
      found: true,
      gif_capable: /\bgif\b/i.test(output),
      detail: /\bgif\b/i.test(output)
        ? "The Playwright-bundled FFmpeg advertises GIF support."
        : "The Playwright-bundled FFmpeg has PNG/VP8 support only; it has no GIF encoder.",
      executable: executable.replace(os.homedir(), "$HOME"),
    };
  }
  return { found: false, gif_capable: false, detail: "Playwright FFmpeg executable not found." };
}

function gifAssemblySupport(pathValue = process.env.PATH || "") {
  const pillow = spawnSync(path.join(ROOT, ".dev-venv/bin/python"), ["-c", "import PIL; print(PIL.__version__)"], {
    encoding: "utf8",
  });
  const probes = Object.fromEntries(
    ["ffmpeg", "magick", "convert", "gifski"].map((name) => [name, executableOnPath(name, pathValue)]),
  );
  const found = Object.entries(probes).find(([, executable]) => executable);
  if (found) {
    const [tool, executable] = found;
    const commands = {
      ffmpeg: "ffmpeg -framerate 1/3 -pattern_type glob -i 'screenshots/desktop-*.png' -loop 0 walkthrough-desktop.gif",
      magick: "magick -delay 300 -loop 0 screenshots/desktop-*.png walkthrough-desktop.gif",
      convert: "convert -delay 300 -loop 0 screenshots/desktop-*.png walkthrough-desktop.gif",
      gifski: "gifski --fps 0.33 -o walkthrough-desktop.gif screenshots/desktop-*.png",
    };
    return {
      status: "available",
      tool,
      executable,
      assembly_from_output_directory: commands[tool],
      note: "Run once per viewport; annotated PNG screenshots remain the source frames.",
    };
  }
  return {
    status: "unavailable",
    exact_missing_dependency: "Pillow/PIL in .dev-venv, or a GIF-capable ffmpeg, ImageMagick magick/convert, or gifski executable on PATH.",
    pillow_in_dev_venv: pillow.status === 0
      ? `available (${pillow.stdout.trim()}) but this harness has no Pillow assembler from the captured environment`
      : "not importable from .dev-venv/bin/python",
    probes: Object.fromEntries(Object.keys(probes).map((name) => [name, "not found on PATH"])),
    playwright_bundled_ffmpeg: bundledFfmpegProbe(),
    authoritative_media: "Annotated PNG screenshots listed in this manifest.",
  };
}

async function freeLoopbackPort() {
  const server = net.createServer();
  await new Promise((resolve, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", resolve);
  });
  const port = server.address().port;
  await new Promise((resolve, reject) => server.close((error) => (error ? reject(error) : resolve())));
  return port;
}

async function startApplication(profile) {
  const port = await freeLoopbackPort();
  const runtime = path.join(OUTPUT, `.runtime-${profile}`);
  const state = { exitCode: null, stderr: "" };
  const child = spawn(path.join(ROOT, "scripts/run-browser-app.sh"), [], {
    cwd: ROOT,
    env: {
      ...process.env,
      STOCK_PROBS_BROWSER_PORT: String(port),
      STOCK_PROBS_BROWSER_RUNTIME: runtime,
    },
    stdio: ["ignore", "ignore", "pipe"],
  });
  child.stderr.on("data", (chunk) => { state.stderr = `${state.stderr}${chunk}`.slice(-16_384); });
  child.once("exit", (code) => { state.exitCode = code; });
  const baseURL = `http://127.0.0.1:${port}`;
  const deadline = Date.now() + 30_000;
  while (Date.now() < deadline && state.exitCode === null) {
    try {
      const response = await fetch(`${baseURL}/api/v1/readiness`);
      if (response.ok) {
        return {
          baseURL,
          runtime,
          stop: async () => {
            if (state.exitCode === null) child.kill("SIGTERM");
            await Promise.race([
              new Promise((resolve) => child.once("exit", resolve)),
              new Promise((resolve) => setTimeout(resolve, 5_000)),
            ]);
            if (state.exitCode === null) child.kill("SIGKILL");
            await fsp.rm(runtime, { recursive: true, force: true });
          },
        };
      }
    } catch (_) {
      // Connection refusal is expected until uvicorn binds the isolated loopback port.
    }
    await new Promise((resolve) => setTimeout(resolve, 50));
  }
  if (state.exitCode === null) child.kill("SIGKILL");
  throw new Error(`Walkthrough app failed to start (${state.exitCode}): ${state.stderr}`);
}

function requireStatus(response, expected, label) {
  if (response.status() !== expected) {
    throw new Error(`${label} returned HTTP ${response.status()}, expected ${expected}.`);
  }
}

function latestResponseEvidence(responses, method, pathname) {
  for (let index = responses.length - 1; index >= 0; index -= 1) {
    const item = responses[index];
    const url = new URL(item.url);
    if (item.method === method && url.pathname === pathname) {
      return { method: item.method, path: `${url.pathname}${url.search}`, status: item.status };
    }
  }
  throw new Error(`Missing response evidence for ${method} ${pathname}.`);
}

function newsPayload(symbol, mode) {
  const count = mode === "empty" ? 0 : 5;
  const payload = {
    query: { symbol, limit: 5 },
    provider: "Yahoo Finance",
    as_of: "2025-01-10T17:03:00Z",
    cache_state: mode === "stale" ? "stale_fallback" : "miss",
    coverage: { returned_count: count, partial_metadata: mode === "partial", refresh_failed: mode === "stale" },
    items: Array.from({ length: count }, (_, index) => ({
      id: `walkthrough-${index + 1}`,
      title: `Current headline ${index + 1} for ${symbol}`,
      publisher: "Fixture News",
      published_at: `2025-01-10T16:${String(index * 7).padStart(2, "0")}:00Z`,
      url: `https://example.com/news/${index + 1}`,
      related_symbols: [symbol],
    })),
  };
  if (mode === "partial") {
    payload.items[0].publisher = null;
    payload.items[0].published_at = null;
  }
  return payload;
}

// Standalone capture requires service readiness and loaded-theme evidence, without expect or keyboard paths.
async function themeOrdering(page, response) {
  const html = await response.text();
  const theme = '<script src="/assets/theme.js"></script>';
  const css = '<link rel="stylesheet" href="/assets/app.css"';
  return {
    theme_before_css: html.indexOf(theme) >= 0 && html.indexOf(theme) < html.indexOf(css),
    parser_blocking: html.split(theme).length - 1 === 1,
    loaded_theme: await page.locator("html").getAttribute("data-theme"),
  };
}

async function waitForImperativeApp(page) {
  await page.locator("#system-label").filter({ hasText: "Local service ready" }).waitFor();
}

async function openSettings(page) {
  const menu = page.locator("#settings-menu.settings-menu[popover]");
  if (await menu.isHidden()) await page.locator('.settings-trigger[popovertarget="settings-menu"]').click();
  await menu.waitFor({ state: "visible" });
  return menu;
}

async function chooseTheme(page, value) {
  const menu = await openSettings(page);
  const radio = menu.locator(`[name="theme"][value="${value}"]`);
  await radio.click();
  if (!(await radio.isChecked())) throw new Error(`Theme ${value} was not selected.`);
}

async function firstPaintObservation(browser, application, profile) {
  const context = await browser.newContext({
    viewport: profile.viewport,
    isMobile: Boolean(profile.isMobile),
    hasTouch: Boolean(profile.hasTouch),
    colorScheme: "light",
  });
  await context.addInitScript(() => {
    localStorage.setItem("stock-probs.theme", "dark");
    window.__walkthroughFirstPaint = [];
    new PerformanceObserver((list) => {
      for (const entry of list.getEntries()) {
        window.__walkthroughFirstPaint.push({
          name: entry.name,
          start_time_ms: entry.startTime,
          theme: document.documentElement.dataset.theme || null,
        });
      }
    }).observe({ type: "paint", buffered: true });
  });
  const observations = {};
  try {
    for (const [surface, pathname] of [["dashboard", "/"], ["api_docs", "/api/v1/docs"]]) {
      const page = await context.newPage();
      await page.goto(`${application.baseURL}${pathname}`, { waitUntil: "load" });
      await page.waitForFunction(() => window.__walkthroughFirstPaint.some(({ name }) => name === "first-paint"));
      observations[surface] = await page.evaluate(() => ({
        csp_bypassed: false,
        entries: window.__walkthroughFirstPaint,
      }));
      const firstPaint = observations[surface].entries.find(({ name }) => name === "first-paint");
      if (firstPaint.theme !== "dark") throw new Error(`${surface} first paint did not observe the dark theme.`);
      await page.close();
    }
  } finally {
    await context.close();
  }
  return observations;
}

async function artifactInventory(directory, relative = "") {
  const inventory = [];
  for (const entry of (await fsp.readdir(path.join(directory, relative), { withFileTypes: true })).sort((a, b) => a.name.localeCompare(b.name))) {
    const item = path.join(relative, entry.name);
    if (entry.isDirectory()) inventory.push(...await artifactInventory(directory, item));
    else inventory.push({ path: item, bytes: (await fsp.stat(path.join(directory, item))).size });
  }
  return inventory;
}

function gitGenerationMetadata() {
  const run = (args) => spawnSync("git", args, { cwd: ROOT, encoding: "utf8" });
  const revision = run(["rev-parse", "HEAD"]);
  const status = run(["status", "--porcelain", "--untracked-files=normal"]);
  if (revision.status !== 0 || status.status !== 0) throw new Error("Unable to bind walkthrough generation to Git state.");
  const dirtyEntries = status.stdout.trimEnd();
  return {
    revision: revision.stdout.trim(),
    dirty: Boolean(dirtyEntries),
    dirty_entries: dirtyEntries ? dirtyEntries.split("\n") : [],
  };
}

async function addCaptureStyles(page) {
  await page.addStyleTag({ content: `
    *, *::before, *::after { animation-duration: 0s !important; transition-duration: 0s !important; scroll-behavior: auto !important; caret-color: transparent !important; }
    #walkthrough-annotation { position: fixed; z-index: 2147483647; right: 16px; bottom: 16px; width: min(430px, calc(100vw - 32px)); border: 3px solid #dce978; background: #10251f; color: #fff; padding: 12px 14px; box-shadow: 7px 7px 0 rgba(208,74,43,.9); font: 14px/1.35 system-ui, sans-serif; }
    #walkthrough-annotation strong, #walkthrough-annotation span, #walkthrough-annotation small { display: block; }
    #walkthrough-annotation span { color: #b8ddd0; font-size: 10px; font-weight: 800; letter-spacing: .12em; text-transform: uppercase; }
    #walkthrough-annotation strong { margin: 3px 0; font-size: 16px; }
    #walkthrough-annotation small { color: #fff; font-size: 12px; }
    @media (max-width: 600px) { #walkthrough-annotation { right: 10px; bottom: 10px; width: calc(100vw - 20px); padding: 9px 11px; } #walkthrough-annotation strong { font-size: 14px; } #walkthrough-annotation small { font-size: 11px; } }
  ` });
}

async function capture(page, profile, step, selector, evidence, state, block = "center", suffix = "") {
  const target = typeof selector === "string" ? page.locator(selector).first() : selector.first();
  await target.waitFor({ state: "visible" });
  await target.evaluate((element, placement) => element.scrollIntoView({ block: placement, inline: "nearest" }), block);
  await page.evaluate(({ item, profileName }) => {
    let annotation = document.querySelector("#walkthrough-annotation");
    if (!annotation) {
      annotation = document.createElement("aside");
      annotation.id = "walkthrough-annotation";
      annotation.setAttribute("aria-label", "Walkthrough annotation");
      document.body.append(annotation);
    }
    const marker = document.createElement("span");
    marker.textContent = `M08 WALKTHROUGH · ${profileName} · STEP ${item.id.slice(0, 2)}`;
    const title = document.createElement("strong");
    title.textContent = item.title;
    const description = document.createElement("small");
    description.textContent = item.description;
    annotation.replaceChildren(marker, title, description);
  }, { item: step, profileName: profile.name.toUpperCase() });
  await page.evaluate(() => new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve))));
  const relative = path.join("screenshots", `${profile.name}-${step.id}${suffix ? `-${suffix}` : ""}.png`);
  await page.screenshot({ path: path.join(OUTPUT, relative), animations: "disabled" });
  return {
    id: step.id,
    title: step.title,
    instruction: step.description,
    caption: step.caption,
    alt_text: step.altText,
    viewport: profile.viewport,
    request_status_evidence: Array.isArray(evidence) ? evidence : [evidence],
    state,
    screenshot: relative,
  };
}

async function runProfile(browser, profile) {
  const application = await startApplication(profile.name);
  const context = await browser.newContext({
    viewport: profile.viewport,
    isMobile: Boolean(profile.isMobile),
    hasTouch: Boolean(profile.hasTouch),
    locale: "en-US",
    timezoneId: "UTC",
    colorScheme: "light",
    reducedMotion: "reduce",
    acceptDownloads: true,
    bypassCSP: true,
  });
  const page = await context.newPage();
  const requests = [];
  const responses = [];
  const requestViolations = [];
  const pageErrors = [];
  let newsMode = "fresh";
  await context.route("**/*", async (route) => {
    const request = route.request();
    const violation = requestPolicyViolation(request.url(), application.baseURL);
    requests.push({ method: request.method(), resource_type: request.resourceType(), url: request.url() });
    if (violation) {
      requestViolations.push(violation);
      await route.abort("blockedbyclient");
    } else if (new URL(request.url()).pathname === "/api/v1/news") {
      if (newsMode === "provider") {
        await route.fulfill({ status: 502, contentType: "application/json", json: { error: { code: "provider_unavailable", message: "Provider unavailable" } } });
      } else if (newsMode === "busy") {
        await route.fulfill({ status: 503, contentType: "application/json", json: { error: { code: "capacity_busy", message: "Busy" } } });
      } else {
        const symbol = new URL(request.url()).searchParams.get("symbol");
        await route.fulfill({ status: 200, contentType: "application/json", json: newsPayload(symbol, newsMode) });
      }
    } else {
      await route.continue();
    }
  });
  context.on("response", (response) => responses.push({
    method: response.request().method(),
    url: response.url(),
    status: response.status(),
  }));
  context.on("page", (openedPage) => openedPage.on("pageerror", (error) => pageErrors.push(error.message)));
  page.on("pageerror", (error) => pageErrors.push(error.message));
  const captures = [];
  const supplementaryCaptures = [];
  const downloadDirectory = path.join(OUTPUT, "downloads", profile.name);
  await fsp.mkdir(downloadDirectory, { recursive: true });

  try {
    await page.goto(application.baseURL, { waitUntil: "domcontentloaded" });
    await addCaptureStyles(page);
    await waitForImperativeApp(page);
    const backup = await page.evaluate(async () => (await fetch("/api/v1/operations/backups/status")).json());
    if (backup.status !== "available" || !backup.managed_names_only || !backup.verification_required) {
      throw new Error("Backup status did not expose the expected managed, verification-required contract.");
    }
    captures.push(await capture(page, profile, STEPS[0], ".masthead",
      latestResponseEvidence(responses, "GET", "/api/v1/operations/backups/status"), "service-ready", "start"));

    const symbol = page.getByLabel("Company name or Yahoo Finance symbol");
    await symbol.fill("ProFrac");
    await page.getByRole("option", { name: /ProFrac Holding Corp/ }).waitFor();
    captures.push(await capture(page, profile, STEPS[1], ".search-panel",
      latestResponseEvidence(responses, "GET", "/api/v1/instruments"), "lookup-results"));
    await symbol.press("ArrowDown");
    await symbol.press("Enter");
    await page.locator("#identity-confirmation").filter({ hasText: "Confirmed identity: ACDC" }).waitFor();
    captures.push(await capture(page, profile, STEPS[2], ".search-panel",
      latestResponseEvidence(responses, "GET", "/api/v1/instruments"), "identity-confirmed"));

    let responsePromise = page.waitForResponse((response) => (
      response.request().method() === "POST" && new URL(response.url()).pathname === "/api/v1/forecasts"
    ));
    await page.getByRole("button", { name: "Run forecast" }).click();
    requireStatus(await responsePromise, 201, "Stock forecast");
    await page.getByRole("heading", { name: "Close → next close" }).waitFor();
    await page.getByRole("heading", { name: "Completed 5m → close" }).waitFor();
    captures.push(await capture(page, profile, STEPS[3], ".horizon-comparison",
      latestResponseEvidence(responses, "POST", "/api/v1/forecasts"), "successful-stock-forecast"));

    const chartCard = page.locator(".forecast-card").first();
    const point = chartCard.locator(".tail-figure .chart-point").first();
    await point.focus();
    const tooltip = chartCard.locator(".tail-figure .chart-tooltip").filter({ hasText: /probability of return/ });
    await tooltip.waitFor();
    const chartTableCheck = assertTooltipMatchesTable(
      await tooltip.innerText(),
      await chartCard.locator(".details-table tr").evaluateAll((rows) => rows.map((row) => ({
        heading: row.querySelector("th")?.textContent.trim(),
        value: row.querySelector("td")?.textContent.trim(),
      }))),
    );
    captures.push(await capture(page, profile, STEPS[4], ".tail-figure",
      latestResponseEvidence(responses, "POST", "/api/v1/forecasts"), "chart-table-equivalent", "start"));
    supplementaryCaptures.push(await capture(page, profile, {
      ...STEPS[4],
      id: `${STEPS[4].id}-table-continuation`,
      title: "Continue to the matching table row",
      description: "Continue below the chart and compare Return at or below −10% with the focused point.",
      caption: "The matching table row reports 0.6%, the same value as the focused −10% chart point.",
      altText: "Details table row for return at or below minus ten percent showing 0.6 percent.",
    }, chartCard.locator(".details-table tr").filter({ hasText: chartTableCheck.heading }),
    latestResponseEvidence(responses, "POST", "/api/v1/forecasts"), "chart-table-row-continuation", "center"));

    await symbol.fill("SPY");
    await page.getByLabel("ETF").check();
    responsePromise = page.waitForResponse((response) => (
      response.request().method() === "POST" && new URL(response.url()).pathname === "/api/v1/forecasts"
    ));
    await page.getByRole("button", { name: "Run forecast" }).click();
    requireStatus(await responsePromise, 201, "ETF forecast");
    await page.locator(".forecast-meta").getByText("SPY", { exact: true }).waitFor();
    await page.getByText("ETF / ETF", { exact: true }).waitFor();
    await page.locator(".forecast-grid").getByRole("heading", { name: "Close → next close", exact: true }).waitFor();
    await page.locator(".forecast-grid").getByRole("heading", { name: "Completed 5m → close", exact: true }).waitFor();
    captures.push(await capture(page, profile, STEPS[5], ".horizon-comparison",
      latestResponseEvidence(responses, "POST", "/api/v1/forecasts"), "successful-etf-forecast"));

    await page.getByLabel("Find symbol").fill("SPY");
    await page.getByLabel("Status", { exact: true }).selectOption("successful");
    await page.getByLabel("Asset type", { exact: true }).selectOption("etf");
    responsePromise = page.waitForResponse((response) => (
      response.request().method() === "GET" && new URL(response.url()).pathname === "/api/v1/history"
    ));
    await page.getByRole("button", { name: "Filter ledger" }).click();
    requireStatus(await responsePromise, 200, "History filter");
    const historyRow = page.locator("#history-content tbody tr").filter({ hasText: "SPY" }).first();
    await historyRow.waitFor();
    captures.push(await capture(page, profile, STEPS[6], profile.name === "mobile" ? historyRow : ".ledger",
      latestResponseEvidence(responses, "GET", "/api/v1/history"), "filtered-history", "start"));

    responsePromise = page.waitForResponse((response) => (
      response.request().method() === "GET" && new URL(response.url()).pathname.startsWith("/api/v1/saved-forecasts/")
    ));
    await historyRow.getByRole("button", { name: "Reopen saved forecast" }).click();
    requireStatus(await responsePromise, 200, "Saved forecast reopen");
    await page.getByText(/Immutable recorded result · audit event/).waitFor();
    captures.push(await capture(page, profile, STEPS[7], "#result-section",
      latestResponseEvidence(responses, "GET", new URL((await responsePromise).url()).pathname), "immutable-saved-result", "start"));

    responsePromise = page.waitForResponse((response) => (
      response.request().method() === "POST" && /\/api\/v1\/history\/\d+\/reconstructions$/.test(new URL(response.url()).pathname)
    ));
    await historyRow.getByRole("button", { name: "Run fresh cutoff analysis" }).click();
    requireStatus(await responsePromise, 201, "Fresh historical reconstruction");
    await page.locator("#fresh-analysis-content").filter({ hasText: "This is a new calculation" }).waitFor();
    captures.push(await capture(page, profile, STEPS[8], "#fresh-analysis-section",
      latestResponseEvidence(responses, "POST", new URL((await responsePromise).url()).pathname), "fresh-reconstruction", "start"));

    const downloads = {};
    const downloadEvidence = [];
    for (const format of ["CSV", "JSON"]) {
      const pathname = `/api/v1/history-export.${format.toLowerCase()}`;
      const [download] = await Promise.all([
        page.waitForEvent("download"),
        page.getByRole("link", { name: `Download ${format}` }).click(),
      ]);
      const destination = path.join(downloadDirectory, `history.${format.toLowerCase()}`);
      await download.saveAs(destination);
      const failure = await download.failure();
      if (failure) throw new Error(`${format} history export download failed: ${failure}`);
      downloadEvidence.push({ method: "GET", path: new URL(download.url()).pathname + new URL(download.url()).search, status: "downloaded-and-validated" });
      downloads[format.toLowerCase()] = path.relative(OUTPUT, destination);
    }
    const csv = await fsp.readFile(path.join(OUTPUT, downloads.csv), "utf8");
    const json = JSON.parse(await fsp.readFile(path.join(OUTPUT, downloads.json), "utf8"));
    if (!csv.startsWith("record_type,event_id,") || !csv.includes("SPY")) {
      throw new Error("CSV download did not contain the filtered history contract.");
    }
    if (json.format !== "stock-probs-history" || !json.records.some((record) => (
      record.record_type === "event" && record.data.normalized_symbol === "SPY"
    ))) {
      throw new Error("JSON download did not contain the filtered history contract.");
    }
    captures.push(await capture(page, profile, STEPS[9], ".ledger .section-head",
      downloadEvidence, "downloads-verified", "start"));

    const resetTheme = async (colorScheme) => {
      await page.evaluate(() => localStorage.removeItem("stock-probs.theme"));
      await page.emulateMedia({ colorScheme, reducedMotion: "reduce" });
      await page.reload({ waitUntil: "domcontentloaded" });
      await addCaptureStyles(page);
      await waitForImperativeApp(page);
    };

    await resetTheme("dark");
    if (await page.evaluate(() => localStorage.getItem("stock-probs.theme")) !== null) throw new Error("System theme retained an override.");
    const systemTheme = (await openSettings(page)).locator('[name="theme"][value="system"]');
    if (!(await systemTheme.isChecked())) throw new Error("System theme was not selected.");
    captures.push(await capture(page, profile, STEPS[10], ".masthead",
      latestResponseEvidence(responses, "GET", "/assets/theme.js"), "system-dark", "start"));

    await resetTheme("light");
    await chooseTheme(page, "dark");
    await page.locator('html[data-theme="dark"]').waitFor();
    if (await page.evaluate(() => localStorage.getItem("stock-probs.theme")) !== "dark") throw new Error("Dark theme was not stored.");
    captures.push(await capture(page, profile, STEPS[11], ".masthead",
      latestResponseEvidence(responses, "GET", "/assets/theme.js"), "explicit-dark", "start"));

    await resetTheme("light");
    await chooseTheme(page, "dark");
    await chooseTheme(page, "system");
    await page.locator('html[data-theme="light"]').waitFor();
    if (await page.evaluate(() => localStorage.getItem("stock-probs.theme")) !== null) throw new Error("Reset to system did not remove the override.");
    captures.push(await capture(page, profile, STEPS[12], ".masthead",
      latestResponseEvidence(responses, "GET", "/assets/theme.js"), "reset-to-system-light", "start"));

    await page.evaluate(() => {
      localStorage.removeItem("stock-probs.theme");
      localStorage.setItem("stock-probs.theme", "dark");
    });
    const dashboardResponse = await page.reload({ waitUntil: "domcontentloaded" });
    await addCaptureStyles(page);
    await waitForImperativeApp(page);
    const dashboardThemeOrdering = await themeOrdering(page, dashboardResponse);
    const docsPage = await context.newPage();
    const docsResponse = await docsPage.goto(`${application.baseURL}/api/v1/docs`, { waitUntil: "domcontentloaded" });
    await addCaptureStyles(docsPage);
    const docsThemeOrdering = await themeOrdering(docsPage, docsResponse);
    for (const [surface, ordering] of Object.entries({ dashboard: dashboardThemeOrdering, api_docs: docsThemeOrdering })) {
      if (!ordering.theme_before_css || !ordering.parser_blocking || ordering.loaded_theme !== "dark") {
        throw new Error(`${surface} did not provide a parser-blocking dark theme before CSS.`);
      }
    }
    captures.push(await capture(docsPage, profile, STEPS[13], ".masthead", [
      latestResponseEvidence(responses, "GET", "/api/v1/docs"),
      latestResponseEvidence(responses, "GET", "/assets/theme.js"),
      { verification: "dashboard", ...dashboardThemeOrdering },
      { verification: "api-docs", ...docsThemeOrdering },
    ], "loaded-dark-api-page", "start"));
    await docsPage.close();
    const firstPaint = await firstPaintObservation(browser, application, profile);

    const reopenSaved = async () => {
      const row = page.locator("#history-content tbody tr").filter({ hasText: "SPY" }).first();
      await row.waitFor();
      const savedResponse = page.waitForResponse((response) => (
        response.request().method() === "GET" && new URL(response.url()).pathname.startsWith("/api/v1/saved-forecasts/")
      ));
      await row.getByRole("button", { name: "Reopen saved forecast" }).click();
      requireStatus(await savedResponse, 200, "Saved forecast reopen");
      await page.getByText(/Immutable recorded result · audit event/).waitFor();
      return page.getByText("Load current headlines for this symbol", { exact: true });
    };
    const showSavedNews = async (mode, expectedState) => {
      newsMode = mode;
      const disclosure = await reopenSaved();
      const newsResponse = page.waitForResponse((response) => new URL(response.url()).pathname === "/api/v1/news");
      await disclosure.click();
      await page.locator(`.news-content[data-state="${expectedState}"]`).waitFor();
      return newsResponse;
    };

    let newsResponse = await showSavedNews("fresh", "fresh");
    requireStatus(await newsResponse, 200, "Fresh news");
    const freshHeadlineEvidence = assertHeadlineEvidence("fresh", await page.locator(NEWS_ITEM_SELECTOR).count());
    captures.push(await capture(page, profile, STEPS[14], ".news-panel",
      [latestResponseEvidence(responses, "GET", "/api/v1/news"), freshHeadlineEvidence], "fresh"));

    newsResponse = await showSavedNews("empty", "empty");
    requireStatus(await newsResponse, 200, "Empty news");
    captures.push(await capture(page, profile, STEPS[15], ".news-panel",
      latestResponseEvidence(responses, "GET", "/api/v1/news"), "empty"));

    newsResponse = await showSavedNews("partial", "partial");
    requireStatus(await newsResponse, 200, "Partial-metadata news");
    captures.push(await capture(page, profile, STEPS[16], ".news-panel",
      latestResponseEvidence(responses, "GET", "/api/v1/news"), "partial-metadata"));

    newsResponse = await showSavedNews("stale", "stale");
    requireStatus(await newsResponse, 200, "Stale fallback news");
    captures.push(await capture(page, profile, STEPS[17], ".news-panel",
      latestResponseEvidence(responses, "GET", "/api/v1/news"), "stale-fallback"));

    newsResponse = await showSavedNews("provider", "unavailable");
    requireStatus(await newsResponse, 502, "Provider-failure news");
    captures.push(await capture(page, profile, STEPS[18], ".news-panel",
      latestResponseEvidence(responses, "GET", "/api/v1/news"), "provider-unavailable"));

    const newsRequestsBeforeSavedReopen = requests.filter(({ url }) => new URL(url).pathname === "/api/v1/news").length;
    const savedDisclosure = await reopenSaved();
    await page.locator('.news-content[data-state="not-requested"]').waitFor({ state: "attached" });
    const newsRequestsAfterSavedReopen = requests.filter(({ url }) => new URL(url).pathname === "/api/v1/news").length;
    const savedReopenNewsRequestDelta = newsRequestsAfterSavedReopen - newsRequestsBeforeSavedReopen;
    if (savedReopenNewsRequestDelta !== 0) throw new Error(`Saved reopen issued ${savedReopenNewsRequestDelta} news requests.`);
    captures.push(await capture(page, profile, STEPS[19], "#result-section",
      latestResponseEvidence(responses, "GET", new URL(responses.filter(({ method, url }) => method === "GET" && new URL(url).pathname.startsWith("/api/v1/saved-forecasts/")).at(-1).url).pathname),
      "saved-provider-free-current-headlines-optional", "start"));
    const savedDisclosureCapture = await capture(page, profile, {
      ...STEPS[19],
      id: `${STEPS[19].id}-closed-disclosure`,
      title: "Leave current headlines closed",
      description: "Leave Load current headlines for this symbol closed after reopening the saved SPY result.",
      caption: "The closed disclosure is a separate optional action; saved reopen produced a zero news-request delta.",
      altText: "Closed Load current headlines disclosure beneath the immutable saved SPY forecast.",
    }, savedDisclosure, [{
      method: "GET",
      path: "/api/v1/news",
      status: "not-issued; asserted request delta 0",
    }], "not-requested", "center");
    supplementaryCaptures.push(savedDisclosureCapture);

    const companionNewsStates = [{
      title: "Headlines not requested",
      instruction: "Reopen the saved result and leave the current-headlines disclosure closed.",
      caption: "The closed saved-result disclosure is shown and the measured news-request delta is zero.",
      alt_text: savedDisclosureCapture.alt_text,
      viewport: profile.viewport,
      request_status_evidence: [{ method: "GET", path: "/api/v1/news", status: "not-issued; asserted request delta 0" }],
      state: "not-requested",
      screenshot: savedDisclosureCapture.screenshot,
    }];

    newsMode = "busy";
    newsResponse = page.waitForResponse((response) => new URL(response.url()).pathname === "/api/v1/news");
    await savedDisclosure.click();
    await page.locator('.news-content[data-state="busy"]').waitFor();
    requireStatus(await newsResponse, 503, "Capacity-busy news");
    const busyCapture = await capture(page, profile, {
      id: "20-news-capacity-busy",
      title: "Retry after headline capacity is busy",
      description: "Read the retryable busy message. Simulated 503 response — fixture clock 10 Jan 2025, 17:03 UTC.",
      caption: "The simulated capacity response presents a retryable busy state.",
      altText: "Current-headlines panel showing a simulated capacity-busy message.",
    }, ".news-panel", latestResponseEvidence(responses, "GET", "/api/v1/news"), "capacity-busy");
    supplementaryCaptures.push(busyCapture);
    companionNewsStates.push({
      title: "Headline capacity busy",
      instruction: "Read the busy message and retry later; this is a simulated 503 at the fixture clock.",
      caption: "A simulated 503 response is presented as a retryable capacity state.",
      alt_text: busyCapture.alt_text,
      viewport: profile.viewport,
      request_status_evidence: [latestResponseEvidence(responses, "GET", "/api/v1/news")],
      state: "capacity-busy",
      screenshot: busyCapture.screenshot,
    });

    let disclosure = await reopenSaved();
    await page.evaluate(() => {
      window.__walkthroughFetch = window.fetch;
      window.fetch = (url, options) => String(url).includes("/api/v1/news")
        ? Promise.reject(new TypeError("Local service unreachable")) : window.__walkthroughFetch(url, options);
    });
    await disclosure.click();
    await page.locator('.news-content[data-state="unreachable"]').waitFor();
    const unreachableCapture = await capture(page, profile, {
      id: "20-news-local-unreachable",
      title: "Recognize a local connection failure",
      description: "Read the local-service message and distinguish it from provider failure. Simulated fetch rejection — fixture clock 10 Jan 2025, 17:03 UTC.",
      caption: "The simulated local connection failure has its own message and makes no upstream-provider claim.",
      altText: "Current-headlines panel showing a simulated local service unreachable message.",
    }, ".news-panel", { method: "GET", path: "/api/v1/news", status: "local fetch rejected" }, "local-unreachable");
    supplementaryCaptures.push(unreachableCapture);
    companionNewsStates.push({
      title: "Local service unreachable",
      instruction: "Check the local service when this message appears; the walkthrough simulates the fetch rejection.",
      caption: "A simulated local network failure is distinct from an upstream provider failure.",
      alt_text: unreachableCapture.alt_text,
      viewport: profile.viewport,
      request_status_evidence: [{ method: "GET", path: "/api/v1/news", status: "local fetch rejected" }],
      state: "local-unreachable",
      screenshot: unreachableCapture.screenshot,
    });
    await page.evaluate(() => { window.fetch = window.__walkthroughFetch; delete window.__walkthroughFetch; });

    disclosure = await reopenSaved();
    await page.evaluate(() => {
      window.__walkthroughFetch = window.fetch;
      window.__walkthroughNewsAbortObserved = false;
      window.fetch = (url, options) => String(url).includes("/api/v1/news")
        ? new Promise((resolve, reject) => options.signal.addEventListener("abort", () => {
          window.__walkthroughNewsAbortObserved = true;
          reject(new DOMException("Aborted", "AbortError"));
        }, { once: true }))
        : window.__walkthroughFetch(url, options);
    });
    await disclosure.click();
    await page.locator('.news-content[data-state="loading"]').waitFor();
    const loadingCapture = await capture(page, profile, {
      id: "20-news-loading",
      title: "Wait while headlines load",
      description: "Keep the disclosure open while its live region says headlines are loading. Simulated pending response — fixture clock 10 Jan 2025, 17:03 UTC.",
      caption: "The simulated pending request leaves the current-headlines panel in its announced loading state.",
      altText: "Current-headlines panel displaying a simulated loading message.",
    }, ".news-panel", { method: "GET", path: "/api/v1/news", status: "pending" }, "loading");
    supplementaryCaptures.push(loadingCapture);
    companionNewsStates.push({
      title: "Headlines loading",
      instruction: "Wait while the live region reports loading; this walkthrough response remains deliberately pending.",
      caption: "The simulated pending response exposes its in-progress state.",
      alt_text: loadingCapture.alt_text,
      viewport: profile.viewport,
      request_status_evidence: [{ method: "GET", path: "/api/v1/news", status: "pending" }],
      state: "loading",
      screenshot: loadingCapture.screenshot,
    });
    await page.getByLabel("Company name or Yahoo Finance symbol").fill("S");
    await page.locator('.news-content[data-state="superseded"]').waitFor();
    const supersededHeadlineEvidence = assertHeadlineEvidence(
      "superseded",
      await page.locator(NEWS_ITEM_SELECTOR).count(),
      await page.evaluate(() => window.__walkthroughNewsAbortObserved),
    );
    const supersededRequestEvidence = {
      method: "GET",
      path: "/api/v1/news",
      status: "abort event observed; headline item count asserted",
      ...supersededHeadlineEvidence,
    };
    const supersededCapture = await capture(page, profile, {
      id: "20-news-superseded",
      title: "Change instrument to supersede a request",
      description: "Change the instrument while headlines load and confirm that the old request is superseded. Simulated pending response — fixture clock 10 Jan 2025, 17:03 UTC.",
      caption: "The capture observed the pending stub's abort event and no headline items remained in the superseded state.",
      altText: "Current-headlines panel showing that a simulated request was superseded after the instrument changed.",
    }, ".news-panel", supersededRequestEvidence, "superseded");
    supplementaryCaptures.push(supersededCapture);
    companionNewsStates.push({
      title: "Instrument changed and request superseded",
      instruction: "Change the instrument while loading and confirm the superseded message replaces the old request.",
      caption: "The capture observed the pending stub's abort event and asserted that no headline items remained.",
      alt_text: supersededCapture.alt_text,
      viewport: profile.viewport,
      request_status_evidence: [supersededRequestEvidence],
      state: "superseded",
      screenshot: supersededCapture.screenshot,
    });
    await page.evaluate(() => {
      window.fetch = window.__walkthroughFetch;
      delete window.__walkthroughFetch;
      delete window.__walkthroughNewsAbortObserved;
    });

    if (!requests.length) throw new Error("The walkthrough browser issued no requests.");
    if (requestViolations.length) throw new Error(`Blocked walkthrough requests: ${requestViolations.join("; ")}`);
    if (pageErrors.length) throw new Error(`Browser page errors: ${pageErrors.join("; ")}`);
    const dataRequests = requests.filter(({ resource_type }) => ["fetch", "xhr"].includes(resource_type));
    if (dataRequests.some(({ url }) => !new URL(url).pathname.startsWith("/api/v1/"))) {
      throw new Error("Browser data traffic escaped the local /api/v1 boundary.");
    }
    const requestTypes = Object.fromEntries([...new Set(requests.map(({ resource_type }) => resource_type))]
      .sort()
      .map((type) => [type, requests.filter(({ resource_type }) => resource_type === type).length]));
    return {
      viewport: profile.viewport,
      captures,
      supplementary_captures: supplementaryCaptures,
      downloads,
      checks: {
        backup_status: backup.status,
        managed_backup_names_only: backup.managed_names_only,
        backup_verification_required: backup.verification_required,
        chart_table_match: chartTableCheck,
        etf_horizon_headings: ["Close → next close", "Completed 5m → close"],
        declared_request_count: requests.length,
        api_data_request_count: dataRequests.length,
        api_only_data_traffic: true,
        request_types: requestTypes,
        blocked_or_undeclared_requests: requestViolations.length,
        page_errors: pageErrors.length,
        theme_loaded_ordering: { dashboard: dashboardThemeOrdering, api_docs: docsThemeOrdering },
        theme_first_paint_execution: firstPaint,
        saved_reopen_news_request_count: {
          before: newsRequestsBeforeSavedReopen,
          after: newsRequestsAfterSavedReopen,
          delta: savedReopenNewsRequestDelta,
        },
        news_screenshot_states: ["fresh", "empty", "partial-metadata", "stale-fallback", "provider-unavailable"],
      },
      companion_news_states: companionNewsStates,
    };
  } finally {
    await context.close();
    await application.stop();
  }
}

function publicationMarkdown(generation, profiles) {
  const lines = [
    "---",
    'title: "Stock Probability walkthrough"',
    'description: "An annotated desktop and mobile walkthrough of forecasts, history, themes, and current-headline states."',
    "---",
    "",
    "# Stock Probability walkthrough",
    "",
    "Follow these steps in order on the local dashboard. The desktop and mobile figures are annotated Chromium captures; mobile figures use emulation, not a physical phone.",
    "",
    `Generation revision: \`${generation.revision}\` (${generation.dirty ? "dirty working tree" : "clean working tree"})  `,
    `Generated UTC: \`${generation.generated_utc}\`  `,
    `Command: \`${generation.command}\``,
    "",
    "> Forecasts and news use deterministic walkthrough fixtures. Every news figure is a simulated production UI response at the fixture clock (10 Jan 2025, 17:03 UTC), not live Yahoo Finance evidence.",
    "",
  ];
  for (const step of STEPS) {
    lines.push(`## ${step.id.slice(0, 2)}. ${step.title}`, "", `**Do:** ${step.description}`, "", `**Expect:** ${step.caption}`, "");
    for (const profile of PROFILES) {
      const item = profiles[profile.name].captures.find(({ id }) => id === step.id);
      lines.push(`![${item.alt_text}](images/${path.basename(item.screenshot)})`, "", `*${profile.name[0].toUpperCase()}${profile.name.slice(1)}: ${item.caption}*`, "");
      for (const extra of profiles[profile.name].supplementary_captures.filter(({ id }) => id.startsWith(`${step.id}-`))) {
        lines.push(`![${extra.alt_text}](images/${path.basename(extra.screenshot)})`, "", `*Continuation: ${extra.caption}*`, "");
      }
    }
    if (step.id === "10-history-downloads") {
      lines.push("Generated examples: [desktop CSV](downloads/desktop/history.csv), [desktop JSON](downloads/desktop/history.json), [mobile CSV](downloads/mobile/history.csv), and [mobile JSON](downloads/mobile/history.json). Each export contains the active SPY / Successful / ETF filter context.", "");
    }
  }
  lines.push("## Companion news states", "", "These states remain attached to step 20 rather than extending the 20-step journey.", "");
  for (const profile of PROFILES) {
    lines.push(`### ${profile.name[0].toUpperCase()}${profile.name.slice(1)}`, "");
    for (const item of profiles[profile.name].companion_news_states) {
      lines.push(`**${item.title}.** ${item.instruction}`, "", `![${item.alt_text}](images/${path.basename(item.screenshot)})`, "", `*${item.caption}*`, "");
    }
  }
  lines.push(
    "## Evidence boundaries",
    "",
    "- The main set contains 20 desktop and 20 mobile figures. Continuation figures show the −10% table row, closed current-headlines disclosure, and simulated busy, unreachable, loading, and superseded states.",
    "- The capture context bypasses CSP only to add annotations. Separate first-paint observations run without CSP bypass; screenshots show settled pages and do not prove a transition by themselves.",
    "- Saved-result reopen records and asserts a zero browser news-request delta. Backend provider-free behavior remains separate QA evidence.",
    "- Backup and restore are not exposed in the UI. Use the documented local CLI for those operations.",
    "- Static PNGs are authoritative. No GIF encoder or animation dependency is required.",
    "",
  );
  return `${lines.join("\n")}\n`;
}

async function publishWalkthrough(generation, profiles) {
  await fsp.rm(PUBLICATION, { recursive: true, force: true });
  await fsp.mkdir(path.join(PUBLICATION, "images"), { recursive: true });
  for (const profile of Object.values(profiles)) {
    for (const item of [...profile.captures, ...profile.supplementary_captures]) {
      await fsp.copyFile(path.join(OUTPUT, item.screenshot), path.join(PUBLICATION, "images", path.basename(item.screenshot)));
    }
  }
  for (const profile of PROFILES) {
    const source = path.join(OUTPUT, "downloads", profile.name);
    const destination = path.join(PUBLICATION, "downloads", profile.name);
    await fsp.mkdir(destination, { recursive: true });
    for (const name of ["history.csv", "history.json"]) await fsp.copyFile(path.join(source, name), path.join(destination, name));
  }
  await fsp.writeFile(path.join(PUBLICATION, "index.md"), publicationMarkdown(generation, profiles));
}

async function writeArtifactManifests(manifest, output = OUTPUT, publication = PUBLICATION) {
  const manifestPaths = [path.join(output, "manifest.json"), path.join(publication, "manifest.json")];
  for (let attempt = 0; attempt < 10; attempt += 1) {
    const contents = `${JSON.stringify(manifest, null, 2)}\n`;
    await Promise.all(manifestPaths.map((manifestPath) => fsp.writeFile(manifestPath, contents)));
    const [files, publishedFiles] = await Promise.all([
      artifactInventory(output),
      artifactInventory(publication),
    ]);
    const totalBytes = files.reduce((total, item) => total + item.bytes, 0);
    const publishedBytes = publishedFiles.reduce((total, item) => total + item.bytes, 0);
    if (
      manifest.artifacts.total_bytes === totalBytes
      && JSON.stringify(manifest.artifacts.files) === JSON.stringify(files)
      && manifest.artifacts.published_total_bytes === publishedBytes
      && JSON.stringify(manifest.artifacts.published_files) === JSON.stringify(publishedFiles)
    ) return { manifestPath: manifestPaths[0], totalBytes, publishedBytes };
    Object.assign(manifest.artifacts, {
      total_bytes: totalBytes,
      files,
      published_total_bytes: publishedBytes,
      published_files: publishedFiles,
    });
  }
  throw new Error("Artifact byte accounting did not stabilize.");
}

async function main() {
  const startedUtc = new Date().toISOString();
  const generation = {
    ...gitGenerationMetadata(),
    started_utc: startedUtc,
    generated_utc: null,
    command: process.env.WALKTHROUGH_COMMAND || "node tools/walkthrough/capture.js",
  };
  assertStepDefinitions();
  await fsp.rm(OUTPUT, { recursive: true, force: true });
  await fsp.mkdir(path.join(OUTPUT, "screenshots"), { recursive: true });
  const browser = await chromium.launch({ headless: true });
  const chromiumVersion = browser.version();
  const profiles = {};
  try {
    for (const profile of PROFILES) profiles[profile.name] = await runProfile(browser, profile);
  } finally {
    await browser.close();
  }
  const primaryScreenshotCount = Object.values(profiles).reduce((total, profile) => total + profile.captures.length, 0);
  const supplementaryScreenshotCount = Object.values(profiles).reduce((total, profile) => total + profile.supplementary_captures.length, 0);
  const screenshotCount = primaryScreenshotCount + supplementaryScreenshotCount;
  if (primaryScreenshotCount !== 40) throw new Error(`Walkthrough produced ${primaryScreenshotCount} primary screenshots, expected 40.`);
  generation.generated_utc = new Date().toISOString();
  await publishWalkthrough(generation, profiles);
  const manifest = {
    task: "M08 walkthrough",
    completion_claim: "The 20-step walkthrough and attached companion states were generated at both authoritative viewports; acceptance remains a separate gate.",
    fixture: {
      provider: "fixture",
      now: "2025-01-10T17:03:00+00:00",
      isolation: "A reset runtime and an ephemeral 127.0.0.1 port per viewport.",
    },
    generation: {
      ...generation,
      completed_utc: new Date().toISOString(),
      versions: {
        node: process.version,
        playwright: PLAYWRIGHT_VERSION,
        chromium: chromiumVersion,
        platform: `${process.platform} ${process.arch}`,
      },
    },
    capture_limits: {
      news: "All displayed news states are simulated browser responses at the fixture clock; they are not live provider/cache/deadline evidence.",
      csp: "Annotation captures use bypassCSP=true only for injected labels; separate first-paint execution observations use bypassCSP=false.",
      mobile: "Chromium mobile/touch emulation at 390x844, not native or physical-phone evidence.",
      animation: "Reduced motion plus capture-only disabled animations; static PNGs are authoritative.",
    },
    browser: "Pinned Playwright Chromium from tools/browser",
    authoritative_media: "Annotated PNG screenshots",
    step_definitions: STEPS,
    profiles,
    gif_assembly: gifAssemblySupport(),
    artifacts: {
      budget_bytes: ARTIFACT_BUDGET_BYTES,
      total_bytes: 0,
      screenshot_count: screenshotCount,
      primary_screenshot_count: primaryScreenshotCount,
      supplementary_screenshot_count: supplementaryScreenshotCount,
      files: [],
      published_path: "docs/walkthrough",
      published_total_bytes: 0,
      published_files: [],
      prior_703_byte_discrepancy: {
        preparation_receipt_bytes: 5683157,
        prior_manifest_bytes: 5682454,
        difference_bytes: 703,
        resolution: "The prior aggregate mismatch cannot be attributed from the old inventory. This generation supersedes it with exact per-file byte inventories for generated and published artifacts.",
      },
    },
  };
  const { manifestPath, totalBytes, publishedBytes } = await writeArtifactManifests(manifest);
  for (const [label, bytes] of [["Walkthrough artifacts", totalBytes], ["Published walkthrough", publishedBytes]]) {
    if (bytes > ARTIFACT_BUDGET_BYTES) {
      throw new Error(`${label} use ${bytes} bytes, exceeding the ${ARTIFACT_BUDGET_BYTES}-byte budget.`);
    }
  }
  const manifestHash = crypto.createHash("sha256").update(await fsp.readFile(manifestPath)).digest("hex");
  const requestCounts = Object.fromEntries(Object.entries(profiles).map(([name, profile]) => [name, {
    total: profile.checks.declared_request_count,
    api_data: profile.checks.api_data_request_count,
  }]));
  process.stdout.write(`${manifestPath}\n${JSON.stringify({ manifest_sha256: manifestHash, primary_screenshot_count: primaryScreenshotCount, supplementary_screenshot_count: supplementaryScreenshotCount, screenshot_count: screenshotCount, request_counts: requestCounts, total_bytes: totalBytes, published_bytes: publishedBytes })}\n`);
}

if (require.main === module) {
  main().catch((error) => {
    process.stderr.write(`${error.stack || error.message}\n`);
    process.exitCode = 1;
  });
}

module.exports = {
  STEPS,
  PROFILES,
  ARTIFACT_BUDGET_BYTES,
  NEWS_ITEM_SELECTOR,
  assertHeadlineEvidence,
  assertStepDefinitions,
  assertTooltipMatchesTable,
  executableOnPath,
  gifAssemblySupport,
  gitGenerationMetadata,
  publicationMarkdown,
  requestPolicyViolation,
  writeArtifactManifests,
};
