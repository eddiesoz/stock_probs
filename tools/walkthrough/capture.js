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
const { chromium } = require(path.join(ROOT, "tools/browser/node_modules/playwright"));

const PROFILES = [
  { name: "desktop", viewport: { width: 1280, height: 1000 } },
  { name: "mobile", viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true },
];

const STEPS = [
  {
    id: "01-backup-status",
    title: "Confirm the local service and backup status",
    description: "The loopback service reports the deterministic fixture provider and an available managed-backup surface.",
  },
  {
    id: "02-company-lookup",
    title: "Use company-name lookup",
    description: "A bounded company-name query returns the matching Yahoo Finance instrument identity.",
  },
  {
    id: "03-symbol-identity",
    title: "Confirm the selected symbol identity",
    description: "Keyboard selection binds ProFrac Holding Corp. to canonical symbol ACDC and its stock metadata.",
  },
  {
    id: "04-stock-horizons",
    title: "Run the stock forecast",
    description: "The stock result compares close-to-close and latest-completed-five-minute-to-close probabilities.",
  },
  {
    id: "05-chart-and-table",
    title: "Read a chart point and its table equivalent",
    description: "A focused threshold point exposes its exact probability while the adjacent details table preserves the same values as text.",
  },
  {
    id: "06-etf-horizons",
    title: "Run the ETF forecast",
    description: "A direct SPY symbol submission produces the same two explicit horizons for an ETF.",
  },
  {
    id: "07-history-filter",
    title: "Search and filter the ledger",
    description: "Symbol, status, and asset-type filters narrow the permanent request history to the SPY ETF result.",
  },
  {
    id: "08-saved-reopen",
    title: "Reopen the immutable saved forecast",
    description: "The saved result reopens exactly as recorded and is labelled as an immutable audit event.",
  },
  {
    id: "09-fresh-reconstruction",
    title: "Run a fresh historical-cutoff analysis",
    description: "A separate region clearly labels the new calculation without replacing the saved forecast.",
  },
  {
    id: "10-history-downloads",
    title: "Download the filtered CSV and JSON",
    description: "Both filtered exports are downloaded and structurally checked by the harness before capture completes.",
  },
  {
    id: "11-theme-system",
    title: "Follow the system theme",
    description: "With no stored override, the dashboard follows the operating-system color preference.",
  },
  {
    id: "12-theme-dark",
    title: "Choose explicit dark mode",
    description: "The accessible theme control applies and stores an explicit dark preference.",
  },
  {
    id: "13-theme-reset",
    title: "Reset the theme to system",
    description: "Choosing System removes the stored override and immediately follows the system preference.",
  },
  {
    id: "14-theme-first-paint",
    title: "Verify no-flash first paint",
    description: "The dashboard and local API contract load theme.js before CSS so their first styled paint uses the selected theme.",
  },
  {
    id: "15-news-fresh",
    title: "Load fresh current headlines",
    description: "Five current headlines show source, as-of time, publication metadata, and HTTPS-safe external links.",
  },
  {
    id: "16-news-empty",
    title: "Show an honest empty news result",
    description: "A successful empty response says that no current headlines were returned instead of reporting an error.",
  },
  {
    id: "17-news-partial",
    title: "Label partial headline metadata",
    description: "A headline remains usable when optional publisher and publication-time metadata are absent.",
  },
  {
    id: "18-news-stale",
    title: "Explain stale cached headlines",
    description: "Cached headlines remain visible and are explicitly labelled when the provider refresh fails.",
  },
  {
    id: "19-news-provider-failure",
    title: "Report provider failure without cache",
    description: "The disclosure reports provider unavailability when no cached headlines can be shown.",
  },
  {
    id: "20-saved-current-news",
    title: "Keep saved evidence separate from current headlines",
    description: "The immutable saved forecast stays provider-free while current headlines remain a separate, optional live action.",
  },
];

const DECLARED_REQUEST_PATHS = [
  /^\/$/,
  /^\/assets\/(?:app\.css|app\.js|favicon\.svg|theme\.js)$/,
  /^\/api\/v1\/(?:docs|news|readiness|operations\/backups\/status|instruments|forecasts|history|history-export\.(?:csv|json)|saved-forecasts\/\d+|history\/\d+\/reconstructions)$/,
];

const ARTIFACT_BUDGET_BYTES = 20 * 1024 * 1024;

function assertStepDefinitions(steps = STEPS) {
  const required = ["lookup", "stock", "chart", "table", "ETF", "history", "saved", "fresh", "CSV", "JSON", "backup", "theme", "dark", "system", "first paint", "headlines", "empty", "partial", "stale", "provider"];
  const text = steps.map(({ title, description }) => `${title} ${description}`).join(" ");
  if (steps.length !== 20 || new Set(steps.map(({ id }) => id)).size !== steps.length) {
    throw new Error("Walkthrough steps must contain twenty unique identifiers.");
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

async function themeOrdering(page) {
  return page.evaluate(() => {
    const theme = document.querySelector('script[src="/assets/theme.js"]');
    const css = document.querySelector('link[href="/assets/app.css"]');
    return {
      theme_before_css: Boolean(theme && css && (theme.compareDocumentPosition(css) & Node.DOCUMENT_POSITION_FOLLOWING)),
      parser_blocking: Boolean(theme && !theme.async && !theme.defer && !theme.type),
      first_paint_theme: document.documentElement.dataset.theme,
    };
  });
}

async function directoryBytes(directory) {
  let total = 0;
  for (const entry of await fsp.readdir(directory, { withFileTypes: true })) {
    const target = path.join(directory, entry.name);
    total += entry.isDirectory() ? await directoryBytes(target) : (await fsp.stat(target)).size;
  }
  return total;
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

async function capture(page, profile, step, selector, evidence, state, block = "center") {
  const target = page.locator(selector).first();
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
  await page.waitForTimeout(50);
  const relative = path.join("screenshots", `${profile.name}-${step.id}.png`);
  await page.screenshot({ path: path.join(OUTPUT, relative), animations: "disabled" });
  return {
    id: step.id,
    title: step.title,
    caption: step.description,
    alt_text: `Annotated ${profile.name} view: ${step.description}`,
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
  const downloadDirectory = path.join(OUTPUT, "downloads", profile.name);
  await fsp.mkdir(downloadDirectory, { recursive: true });

  try {
    await page.goto(application.baseURL, { waitUntil: "domcontentloaded" });
    await addCaptureStyles(page);
    await page.locator("#system-label").filter({ hasText: "backup available" }).waitFor();
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
    captures.push(await capture(page, profile, STEPS[6], ".ledger",
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
      await page.locator("#system-label").filter({ hasText: "backup available" }).waitFor();
    };

    await resetTheme("dark");
    if (await page.evaluate(() => localStorage.getItem("stock-probs.theme")) !== null) throw new Error("System theme retained an override.");
    await page.locator('html[data-theme="dark"] select[name="theme"]').waitFor();
    captures.push(await capture(page, profile, STEPS[10], ".masthead",
      latestResponseEvidence(responses, "GET", "/assets/theme.js"), "system-dark", "start"));

    await resetTheme("light");
    await page.getByLabel("Color theme").selectOption("dark");
    await page.locator('html[data-theme="dark"]').waitFor();
    if (await page.evaluate(() => localStorage.getItem("stock-probs.theme")) !== "dark") throw new Error("Dark theme was not stored.");
    captures.push(await capture(page, profile, STEPS[11], ".masthead",
      latestResponseEvidence(responses, "GET", "/assets/theme.js"), "explicit-dark", "start"));

    await resetTheme("light");
    await page.getByLabel("Color theme").selectOption("dark");
    await page.getByLabel("Color theme").selectOption("system");
    await page.locator('html[data-theme="light"]').waitFor();
    if (await page.evaluate(() => localStorage.getItem("stock-probs.theme")) !== null) throw new Error("Reset to system did not remove the override.");
    captures.push(await capture(page, profile, STEPS[12], ".masthead",
      latestResponseEvidence(responses, "GET", "/assets/theme.js"), "reset-to-system-light", "start"));

    await page.evaluate(() => {
      localStorage.removeItem("stock-probs.theme");
      localStorage.setItem("stock-probs.theme", "dark");
    });
    await page.reload({ waitUntil: "domcontentloaded" });
    await addCaptureStyles(page);
    const dashboardThemeOrdering = await themeOrdering(page);
    const docsPage = await context.newPage();
    await docsPage.goto(`${application.baseURL}/api/v1/docs`, { waitUntil: "domcontentloaded" });
    await addCaptureStyles(docsPage);
    const docsThemeOrdering = await themeOrdering(docsPage);
    for (const [surface, ordering] of Object.entries({ dashboard: dashboardThemeOrdering, api_docs: docsThemeOrdering })) {
      if (!ordering.theme_before_css || !ordering.parser_blocking || ordering.first_paint_theme !== "dark") {
        throw new Error(`${surface} did not provide a parser-blocking dark theme before CSS.`);
      }
    }
    captures.push(await capture(docsPage, profile, STEPS[13], ".masthead", [
      latestResponseEvidence(responses, "GET", "/api/v1/docs"),
      latestResponseEvidence(responses, "GET", "/assets/theme.js"),
      { verification: "dashboard", ...dashboardThemeOrdering },
      { verification: "api-docs", ...docsThemeOrdering },
    ], "no-flash-dark-first-paint", "start"));
    await docsPage.close();

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
    captures.push(await capture(page, profile, STEPS[14], ".news-panel",
      latestResponseEvidence(responses, "GET", "/api/v1/news"), "fresh"));

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

    const savedDisclosure = await reopenSaved();
    await page.locator('.news-content[data-state="not-requested"]').waitFor({ state: "attached" });
    captures.push(await capture(page, profile, STEPS[19], "#result-section",
      latestResponseEvidence(responses, "GET", new URL(responses.filter(({ method, url }) => method === "GET" && new URL(url).pathname.startsWith("/api/v1/saved-forecasts/")).at(-1).url).pathname),
      "saved-provider-free-current-headlines-optional", "start"));

    const companionNewsStates = [{
      title: "Headlines not requested",
      caption: "The closed saved-result disclosure issues no news request.",
      viewport: profile.viewport,
      request_status_evidence: [{ method: "GET", path: "/api/v1/news", status: "not issued" }],
      state: "not-requested",
    }];

    newsMode = "busy";
    newsResponse = page.waitForResponse((response) => new URL(response.url()).pathname === "/api/v1/news");
    await savedDisclosure.click();
    await page.locator('.news-content[data-state="busy"]').waitFor();
    requireStatus(await newsResponse, 503, "Capacity-busy news");
    companionNewsStates.push({
      title: "Headline capacity busy",
      caption: "A bounded 503 response is presented as a retryable capacity state.",
      viewport: profile.viewport,
      request_status_evidence: [latestResponseEvidence(responses, "GET", "/api/v1/news")],
      state: "capacity-busy",
    });

    let disclosure = await reopenSaved();
    await page.evaluate(() => {
      window.__walkthroughFetch = window.fetch;
      window.fetch = (url, options) => String(url).includes("/api/v1/news")
        ? Promise.reject(new TypeError("Local service unreachable")) : window.__walkthroughFetch(url, options);
    });
    await disclosure.click();
    await page.locator('.news-content[data-state="unreachable"]').waitFor();
    companionNewsStates.push({
      title: "Local service unreachable",
      caption: "A local network failure is distinct from an upstream provider failure.",
      viewport: profile.viewport,
      request_status_evidence: [{ method: "GET", path: "/api/v1/news", status: "local fetch rejected" }],
      state: "local-unreachable",
    });
    await page.evaluate(() => { window.fetch = window.__walkthroughFetch; delete window.__walkthroughFetch; });

    disclosure = await reopenSaved();
    await page.evaluate(() => {
      window.__walkthroughFetch = window.fetch;
      window.fetch = (url, options) => String(url).includes("/api/v1/news")
        ? new Promise((resolve, reject) => options.signal.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError"))))
        : window.__walkthroughFetch(url, options);
    });
    await disclosure.click();
    await page.locator('.news-content[data-state="loading"]').waitFor();
    companionNewsStates.push({
      title: "Headlines loading",
      caption: "The live region exposes its bounded in-progress state.",
      viewport: profile.viewport,
      request_status_evidence: [{ method: "GET", path: "/api/v1/news", status: "pending" }],
      state: "loading",
    });
    await page.getByLabel("Company name or Yahoo Finance symbol").fill("S");
    await page.locator('.news-content[data-state="superseded"]').waitFor();
    companionNewsStates.push({
      title: "Instrument changed and request superseded",
      caption: "Changing the instrument aborts the prior headline request and prevents stale rendering.",
      viewport: profile.viewport,
      request_status_evidence: [{ method: "GET", path: "/api/v1/news", status: "aborted" }],
      state: "superseded",
    });
    await page.evaluate(() => { window.fetch = window.__walkthroughFetch; delete window.__walkthroughFetch; });

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
        theme_first_paint: { dashboard: dashboardThemeOrdering, api_docs: docsThemeOrdering },
        news_screenshot_states: ["fresh", "empty", "partial-metadata", "stale-fallback", "provider-unavailable"],
      },
      companion_news_states: companionNewsStates,
    };
  } finally {
    await context.close();
    await application.stop();
  }
}

async function main() {
  assertStepDefinitions();
  await fsp.rm(OUTPUT, { recursive: true, force: true });
  await fsp.mkdir(path.join(OUTPUT, "screenshots"), { recursive: true });
  const browser = await chromium.launch({ headless: true });
  const profiles = {};
  try {
    for (const profile of PROFILES) profiles[profile.name] = await runProfile(browser, profile);
  } finally {
    await browser.close();
  }
  const screenshotCount = Object.values(profiles).reduce((total, profile) => total + profile.captures.length, 0);
  if (screenshotCount !== 40) throw new Error(`Walkthrough produced ${screenshotCount} screenshots, expected 40.`);
  const manifest = {
    task: "M08 walkthrough",
    completion_claim: "Approved 20-step walkthrough captured at both authoritative viewports; acceptance remains a separate gate.",
    fixture: {
      provider: "fixture",
      now: "2025-01-10T17:03:00+00:00",
      isolation: "A reset runtime and an ephemeral 127.0.0.1 port per viewport.",
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
    },
  };
  const manifestPath = path.join(OUTPUT, "manifest.json");
  for (let attempt = 0; attempt < 5; attempt += 1) {
    await fsp.writeFile(manifestPath, `${JSON.stringify(manifest, null, 2)}\n`);
    const totalBytes = await directoryBytes(OUTPUT);
    if (manifest.artifacts.total_bytes === totalBytes) break;
    manifest.artifacts.total_bytes = totalBytes;
  }
  const totalBytes = await directoryBytes(OUTPUT);
  if (manifest.artifacts.total_bytes !== totalBytes) throw new Error("Artifact byte accounting did not stabilize.");
  if (totalBytes > ARTIFACT_BUDGET_BYTES) {
    throw new Error(`Walkthrough artifacts use ${totalBytes} bytes, exceeding the ${ARTIFACT_BUDGET_BYTES}-byte budget.`);
  }
  const manifestHash = crypto.createHash("sha256").update(await fsp.readFile(manifestPath)).digest("hex");
  const requestCounts = Object.fromEntries(Object.entries(profiles).map(([name, profile]) => [name, {
    total: profile.checks.declared_request_count,
    api_data: profile.checks.api_data_request_count,
  }]));
  process.stdout.write(`${manifestPath}\n${JSON.stringify({ manifest_sha256: manifestHash, screenshot_count: screenshotCount, request_counts: requestCounts, total_bytes: totalBytes })}\n`);
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
  assertStepDefinitions,
  assertTooltipMatchesTable,
  executableOnPath,
  gifAssemblySupport,
  requestPolicyViolation,
};
