"use strict";

const fs = require("node:fs");
const fsp = require("node:fs/promises");
const net = require("node:net");
const os = require("node:os");
const path = require("node:path");
const { spawn, spawnSync } = require("node:child_process");

const ROOT = path.resolve(__dirname, "../..");
const OUTPUT = path.join(__dirname, "test-results", "latest");
const { chromium } = require(path.join(ROOT, "tools/browser/node_modules/playwright"));

const PROFILES = [
  { name: "desktop", viewport: { width: 1440, height: 1000 } },
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
];

const DECLARED_REQUEST_PATHS = [
  /^\/$/,
  /^\/assets\/(?:app\.css|app\.js|favicon\.svg)$/,
  /^\/api\/v1\/(?:readiness|operations\/backups\/status|instruments|forecasts|history|history-export\.(?:csv|json)|saved-forecasts\/\d+|history\/\d+\/reconstructions)$/,
];

function assertStepDefinitions(steps = STEPS) {
  const required = ["lookup", "stock", "chart", "table", "ETF", "history", "saved", "fresh", "CSV", "JSON", "backup"];
  const text = steps.map(({ title, description }) => `${title} ${description}`).join(" ");
  if (steps.length !== 10 || new Set(steps.map(({ id }) => id)).size !== steps.length) {
    throw new Error("Walkthrough steps must contain ten unique identifiers.");
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

async function capture(page, profile, step, selector, block = "center") {
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
    marker.textContent = `M08 PREPARATION · ${profileName} · STEP ${item.id.slice(0, 2)}`;
    const title = document.createElement("strong");
    title.textContent = item.title;
    const description = document.createElement("small");
    description.textContent = item.description;
    annotation.replaceChildren(marker, title, description);
  }, { item: step, profileName: profile.toUpperCase() });
  await page.waitForTimeout(50);
  const relative = path.join("screenshots", `${profile}-${step.id}.png`);
  await page.screenshot({ path: path.join(OUTPUT, relative), animations: "disabled" });
  return { ...step, screenshot: relative };
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
  const requestViolations = [];
  const pageErrors = [];
  await page.route("**/*", async (route) => {
    const request = route.request();
    const violation = requestPolicyViolation(request.url(), application.baseURL);
    requests.push({ method: request.method(), resource_type: request.resourceType(), url: request.url() });
    if (violation) {
      requestViolations.push(violation);
      await route.abort("blockedbyclient");
    } else {
      await route.continue();
    }
  });
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
    captures.push(await capture(page, profile.name, STEPS[0], ".masthead", "start"));

    const symbol = page.getByLabel("Company name or Yahoo Finance symbol");
    await symbol.fill("ProFrac");
    await page.getByRole("option", { name: /ProFrac Holding Corp/ }).waitFor();
    captures.push(await capture(page, profile.name, STEPS[1], ".search-panel"));
    await symbol.press("ArrowDown");
    await symbol.press("Enter");
    await page.locator("#identity-confirmation").filter({ hasText: "Confirmed identity: ACDC" }).waitFor();
    captures.push(await capture(page, profile.name, STEPS[2], ".search-panel"));

    let responsePromise = page.waitForResponse((response) => (
      response.request().method() === "POST" && new URL(response.url()).pathname === "/api/v1/forecasts"
    ));
    await page.getByRole("button", { name: "Run forecast" }).click();
    requireStatus(await responsePromise, 201, "Stock forecast");
    await page.getByRole("heading", { name: "Close → next close" }).waitFor();
    await page.getByRole("heading", { name: "Completed 5m → close" }).waitFor();
    captures.push(await capture(page, profile.name, STEPS[3], ".horizon-comparison"));

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
    captures.push(await capture(page, profile.name, STEPS[4], ".tail-figure", "start"));

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
    captures.push(await capture(page, profile.name, STEPS[5], ".horizon-comparison"));

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
    captures.push(await capture(page, profile.name, STEPS[6], ".ledger", "start"));

    responsePromise = page.waitForResponse((response) => (
      response.request().method() === "GET" && new URL(response.url()).pathname.startsWith("/api/v1/saved-forecasts/")
    ));
    await historyRow.getByRole("button", { name: "Reopen saved forecast" }).click();
    requireStatus(await responsePromise, 200, "Saved forecast reopen");
    await page.getByText(/Immutable recorded result · audit event/).waitFor();
    captures.push(await capture(page, profile.name, STEPS[7], "#result-section", "start"));

    responsePromise = page.waitForResponse((response) => (
      response.request().method() === "POST" && /\/api\/v1\/history\/\d+\/reconstructions$/.test(new URL(response.url()).pathname)
    ));
    await historyRow.getByRole("button", { name: "Run fresh cutoff analysis" }).click();
    requireStatus(await responsePromise, 201, "Fresh historical reconstruction");
    await page.locator("#fresh-analysis-content").filter({ hasText: "This is a new calculation" }).waitFor();
    captures.push(await capture(page, profile.name, STEPS[8], "#fresh-analysis-section", "start"));

    const downloads = {};
    for (const format of ["CSV", "JSON"]) {
      const [download] = await Promise.all([
        page.waitForEvent("download"),
        page.getByRole("link", { name: `Download ${format}` }).click(),
      ]);
      const destination = path.join(downloadDirectory, `history.${format.toLowerCase()}`);
      await download.saveAs(destination);
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
    captures.push(await capture(page, profile.name, STEPS[9], ".ledger .section-head", "start"));

    if (!requests.length) throw new Error("The walkthrough browser issued no requests.");
    if (requestViolations.length) throw new Error(`Blocked walkthrough requests: ${requestViolations.join("; ")}`);
    if (pageErrors.length) throw new Error(`Browser page errors: ${pageErrors.join("; ")}`);
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
        request_types: requestTypes,
        blocked_or_undeclared_requests: requestViolations.length,
        page_errors: pageErrors.length,
      },
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
  const manifest = {
    task: "M08 preparation",
    completion_claim: "Reusable capture harness only; this is not M08 acceptance or final walkthrough content.",
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
  };
  await fsp.writeFile(path.join(OUTPUT, "manifest.json"), `${JSON.stringify(manifest, null, 2)}\n`);
  process.stdout.write(`${path.join(OUTPUT, "manifest.json")}\n`);
}

if (require.main === module) {
  main().catch((error) => {
    process.stderr.write(`${error.stack || error.message}\n`);
    process.exitCode = 1;
  });
}

module.exports = {
  STEPS,
  assertStepDefinitions,
  assertTooltipMatchesTable,
  executableOnPath,
  gifAssemblySupport,
  requestPolicyViolation,
};
