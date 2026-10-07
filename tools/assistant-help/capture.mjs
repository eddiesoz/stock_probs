import { createHash } from "node:crypto";
import { spawn, spawnSync } from "node:child_process";
import { createRequire } from "node:module";
import net from "node:net";
import {
  chmod, constants as fsConstants, lstat, mkdir, mkdtemp, open, readFile, readdir, realpath, rm, writeFile,
} from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { CAPTURE_IDS, REPO_ROOT } from "./render.mjs";

const browserRequire = createRequire(path.join(REPO_ROOT, "tools/browser/package.json"));
const { chromium } = browserRequire("@playwright/test");
const PYTHON = path.join(REPO_ROOT, ".dev-venv/bin/python");
const FIXTURE_SERVER = path.join(REPO_ROOT, "tools/browser/assistant_qa_server.py");
const OUTPUT_PARENT = path.join(REPO_ROOT, "test-results/assistant-r120");
const MAX_CAPTURE_BYTES = 12 * 1024 * 1024;
const MAX_CAPTURE_SOURCE_BYTES = 16 * 1024 * 1024;
const HASH_READ_CHUNK_BYTES = 64 * 1024;
const PENDING_RECEIPT_SHA256 = "0".repeat(64);
const FIXTURE_SESSION = "browser-assistant-fixture-session-not-a-production-credential";
const FIXTURE_CSRF = "browser-assistant-fixture-csrf-token-not-a-production-credential";
const FIXTURE_TIME = "2025-01-10T17:03:00+00:00";
const STAGED_ASSET_ROOT = path.join(REPO_ROOT, "src/stock_probs/static/next");
const STAGED_ASSET_PREFIX = "src/stock_probs/static/next/";
export const SAVED_FORECAST_ANSWER = "This saved forecast is a synthetic example. Its up probability is 65%; treat the cited records as demonstration data.";

export async function savedForecastMessage(transcript, page) {
  await transcript.getByText(SAVED_FORECAST_ANSWER, { exact: true }).waitFor({ state: "visible" });
  // Author and time have no intervening DOM text; match the author element, not combined row text.
  // Page-rooted inner locators are relative to each row in `has`, without a nested Conversation group.
  const messages = transcript.locator(":scope > ol > li")
    .filter({ has: page.getByText("Ledger assistant", { exact: true }) })
    .filter({ has: page.getByText(SAVED_FORECAST_ANSWER, { exact: true }) });
  if (await messages.count() !== 1) {
    throw new Error("history context must identify exactly one Ledger assistant transcript item");
  }
  return messages;
}

export async function refreshHistoryContextPreview(workspaceContext) {
  await workspaceContext.getByText("Preview", { exact: true }).click();
  await workspaceContext.getByRole("button", { name: "Refresh context preview" }).click();
  await workspaceContext.getByText("Checking safe workspace context…", { exact: true })
    .waitFor({ state: "hidden" });
  // Loading unmounts the disclosure; the ready response remounts it closed.
  await workspaceContext.getByText("Preview", { exact: true }).click();
  await workspaceContext.getByText("Only the selected page and validated references are attached.", { exact: true })
    .waitFor({ state: "visible" });
}

export const CAPTURE_SPECS = Object.freeze({
  desktop_light: Object.freeze({ route: "/tools/live-trading", theme: "light", viewport: { width: 1440, height: 1000 }, mobile: false }),
  desktop_dark: Object.freeze({ route: "/tools/live-trading", theme: "dark", viewport: { width: 1440, height: 1000 }, mobile: false }),
  mobile_light: Object.freeze({ route: "/tools/live-trading", theme: "light", viewport: { width: 390, height: 844 }, mobile: true }),
  mobile_dark: Object.freeze({ route: "/tools/live-trading", theme: "dark", viewport: { width: 390, height: 844 }, mobile: true }),
  forecast_sources: Object.freeze({ route: "/tools/forecast", theme: "light", viewport: { width: 1440, height: 1000 }, mobile: false }),
  action_preview: Object.freeze({ route: "/tools/live-trading", theme: "light", viewport: { width: 1440, height: 1000 }, mobile: false }),
  action_receipt: Object.freeze({ route: "/tools/live-trading", theme: "light", viewport: { width: 1440, height: 1000 }, mobile: false }),
  history_context: Object.freeze({ route: "/tools/live-trading", theme: "light", viewport: { width: 1440, height: 1000 }, mobile: false }),
});

const EXPANDED_CAPTURE_IDS = Object.freeze(["action_preview", "action_receipt", "history_context"]);

export const CAPTURE_SOURCE_FILES = Object.freeze([
  "frontend/components/assistant/assistant-panel.tsx",
  "frontend/components/assistant/assistant-host.tsx",
  "frontend/components/assistant/assistant-answer.tsx",
  "frontend/components/assistant/assistant-answer-model.ts",
  "frontend/components/assistant/assistant-api-client.ts",
  "frontend/components/assistant/assistant-contract.ts",
  "frontend/components/assistant/assistant.module.css",
  "frontend/components/auth-client.ts",
  "frontend/components/auth-controls.tsx",
  "frontend/components/workspace-nav.tsx",
  "frontend/components/workspace-link.tsx",
  "frontend/components/workspace-context-url.ts",
  "frontend/app/layout.tsx",
  "frontend/app/settings.tsx",
  "frontend/app/tools/layout.tsx",
  "frontend/app/tools/page.tsx",
  "frontend/app/tools/tool-page.tsx",
  "frontend/app/tools/tool-page.module.css",
  "frontend/app/tools/client-utils.ts",
  "frontend/app/tools/live-trading/page.tsx",
  "frontend/app/tools/live-trading/workspace.tsx",
  "frontend/app/tools/live-trading/assistant-bridge.ts",
  "frontend/app/tools/live-trading/workspace.module.css",
  "frontend/app/tools/forecast/page.tsx",
  "frontend/app/tools/forecast/workspace.tsx",
  "frontend/app/tools/forecast/workspace.module.css",
  "src/stock_probs/api.py",
  "src/stock_probs/provider.py",
  "src/stock_probs/domain.py",
  "src/stock_probs/service.py",
  "src/stock_probs/assistant/api.py",
  "src/stock_probs/assistant/service.py",
  "src/stock_probs/assistant/storage.py",
  "src/stock_probs/assistant/schemas.py",
  "src/stock_probs/assistant/tools.py",
  "src/stock_probs/assistant/assistant_catalog.json",
  "src/stock_probs/static/app.css",
  "src/stock_probs/static/app.js",
  "src/stock_probs/static/theme.js",
  "src/stock_probs/static/favicon.svg",
  "tools/browser/assistant_qa_server.py",
  "tools/assistant-help/capture.mjs",
  "tools/assistant-help/finalize-captures.mjs",
  "tools/assistant-help/render.mjs",
  "tools/assistant-help/guide.template.html",
  "tools/assistant-help/guide.css",
]);

const OUTPUT_FILES = Object.freeze(Object.fromEntries(
  CAPTURE_IDS.map((id) => [id, "r120-" + id.replaceAll("_", "-") + ".png"]),
));

function isRevision(value) {
  return typeof value === "string" && /^[0-9a-f]{40}$/.test(value);
}

export function parseArguments(argv) {
  if (argv.length !== 2 || argv[0] !== "--output-dir" || typeof argv[1] !== "string" || !argv[1]) {
    throw new Error("Usage: node tools/assistant-help/capture.mjs --output-dir test-results/assistant-r120/<new-directory>");
  }
  const requested = path.resolve(REPO_ROOT, argv[1]);
  const relative = path.relative(OUTPUT_PARENT, requested);
  if (!relative || relative.startsWith(".." + path.sep) || path.isAbsolute(relative)) {
    throw new Error("capture output must be a new directory below test-results/assistant-r120");
  }
  return requested;
}

export function buildCandidateManifest({ revision, captures }) {
  if (!isRevision(revision)) throw new Error("capture candidate needs the exact 40-character Git revision");
  if (!captures || Object.keys(captures).length !== CAPTURE_IDS.length
      || Object.keys(captures).some((id) => !CAPTURE_IDS.includes(id))) {
    throw new Error("capture candidate must include the exact approved screenshot set");
  }

  const entries = {};
  for (const id of CAPTURE_IDS) {
    const source = captures[id];
    const spec = CAPTURE_SPECS[id];
    if (!source || source.file !== OUTPUT_FILES[id] || !/^[0-9a-f]{64}$/.test(source.sha256)) {
      throw new Error("capture candidate is missing the approved " + id + " PNG and SHA-256");
    }
    if (
      source.route !== spec.route
      || source.theme !== spec.theme
      || source.data !== "synthetic"
      || source.viewport?.width !== spec.viewport.width
      || source.viewport?.height !== spec.viewport.height
      || !Number.isInteger(source.image_dimensions?.width)
      || !Number.isInteger(source.image_dimensions?.height)
    ) {
      throw new Error("capture candidate metadata does not match the approved " + id + " state");
    }
    entries[id] = {
      file: source.file,
      sha256: source.sha256,
      revision,
      route: source.route,
      viewport: { ...source.viewport },
      image_dimensions: { ...source.image_dimensions },
      theme: source.theme,
      data: "synthetic",
      privacy_review: "pending",
    };
  }
  return Object.freeze({
    schema_version: 1,
    task: "R-ASTRA-120",
    revision,
    qa_receipt_file: "assistant-help-qa-receipt.json",
    qa_receipt_sha256: PENDING_RECEIPT_SHA256,
    captures: Object.freeze(entries),
  });
}

export function buildRunReceipt({ revision, dirty, sourceHashes, captures, capturePresentation }) {
  if (!isRevision(revision)) throw new Error("capture run needs the exact 40-character Git revision");
  if (typeof dirty !== "boolean") throw new Error("capture run must label whether the worktree is dirty");
  const sourceFiles = sourceHashes && Object.keys(sourceHashes);
  const unexpectedSource = sourceFiles?.some((file) => (
    !CAPTURE_SOURCE_FILES.includes(file) && !file.startsWith(STAGED_ASSET_PREFIX)
  ));
  const missingSource = CAPTURE_SOURCE_FILES.some((file) => !sourceHashes?.[file]);
  const stagedAssets = sourceFiles?.filter((file) => file.startsWith(STAGED_ASSET_PREFIX)) || [];
  if (!sourceHashes || unexpectedSource || missingSource || stagedAssets.length === 0) {
    throw new Error("capture run must bind authored inputs and the complete staged asset set");
  }
  for (const file of sourceFiles) {
    if (!/^[0-9a-f]{64}$/.test(sourceHashes[file] || "")) {
      throw new Error("capture run is missing an approved input SHA-256 for " + file);
    }
  }
  if (!captures || Object.keys(captures).length !== CAPTURE_IDS.length
      || Object.keys(captures).some((id) => !CAPTURE_IDS.includes(id))) {
    throw new Error("capture run must bind the exact approved screenshot set");
  }
  for (const id of CAPTURE_IDS) {
    if (!/^[0-9a-f]{64}$/.test(captures[id]?.sha256 || "")) {
      throw new Error("capture run is missing the approved " + id + " screenshot SHA-256");
    }
  }
  if (!capturePresentation || Object.keys(capturePresentation).length !== EXPANDED_CAPTURE_IDS.length
      || EXPANDED_CAPTURE_IDS.some((id) => !capturePresentation[id])) {
    throw new Error("capture run must record expanded assistant geometry for the three detail captures");
  }
  const checkedPresentation = {};
  for (const id of EXPANDED_CAPTURE_IDS) {
    const presentation = capturePresentation[id];
    const viewport = CAPTURE_SPECS[id].viewport;
    const bounds = presentation?.panel_bounds;
    if (presentation?.assistant_size !== "expanded"
        || presentation.viewport?.width !== viewport.width
        || presentation.viewport?.height !== viewport.height
        || !bounds || ![bounds.x, bounds.y, bounds.width, bounds.height].every(Number.isFinite)
        || bounds.x < 0 || bounds.y < 0
        || bounds.x + bounds.width > viewport.width + 1
        || bounds.y + bounds.height > viewport.height + 1
        || bounds.width < 800 || bounds.height < 900) {
      throw new Error("capture run has invalid expanded assistant geometry for " + id);
    }
    checkedPresentation[id] = Object.freeze({
      assistant_size: "expanded",
      viewport: Object.freeze({ ...presentation.viewport }),
      panel_bounds: Object.freeze({ ...bounds }),
    });
  }
  return Object.freeze({
    task: "R-ASTRA-120",
    status: "builder-candidate",
    revision,
    revision_state: dirty ? "dirty" : "clean",
    source_sha256: Object.freeze({ ...sourceHashes }),
    capture_sha256: Object.freeze(Object.fromEntries(
      CAPTURE_IDS.map((id) => [id, captures[id].sha256]),
    )),
    capture_presentation: Object.freeze(checkedPresentation),
  });
}

async function assertNoSymlinkInputComponents(root, relativePath, label, leafKind = "file") {
  const base = path.resolve(root);
  const components = relativePath.split("/");
  if (path.isAbsolute(relativePath) || components.some((part) => !part || part === "." || part === ".." || part.includes("\\"))) {
    throw new Error(`${label} has an unsafe fixed relative path`);
  }
  const baseInfo = await lstat(base);
  if (!baseInfo.isDirectory() || baseInfo.isSymbolicLink() || await realpath(base) !== base) {
    throw new Error(`${label} root must be a real directory without symlink traversal`);
  }
  let current = base;
  for (const [index, component] of components.entries()) {
    current = path.join(current, component);
    const info = await lstat(current);
    if (info.isSymbolicLink()) throw new Error(`${label} must not traverse symbolic links`);
    const isLeaf = index === components.length - 1;
    if ((!isLeaf || leafKind === "directory") && !info.isDirectory()) {
      throw new Error(`${label} parent components must be real directories`);
    }
    if (isLeaf && leafKind === "file" && !info.isFile()) {
      throw new Error(`${label} is not a regular file`);
    }
  }
  const target = path.join(base, ...components);
  if (await realpath(target) !== target) throw new Error(`${label} resolves through an unexpected path`);
  return target;
}

async function readBoundedNoFollowFile(root, relativePath, label) {
  const filePath = await assertNoSymlinkInputComponents(root, relativePath, label);
  if (fsConstants.O_NOFOLLOW === undefined) throw new Error("capture source hashing requires O_NOFOLLOW support");
  const handle = await open(filePath, fsConstants.O_RDONLY | fsConstants.O_NOFOLLOW | fsConstants.O_NONBLOCK);
  try {
    const opened = await handle.stat();
    if (!opened.isFile() || opened.nlink !== 1 || opened.size < 1 || opened.size > MAX_CAPTURE_SOURCE_BYTES) {
      throw new Error(`${label} is not a bounded single-link regular file`);
    }
    const chunks = [];
    let totalBytes = 0;
    while (totalBytes <= MAX_CAPTURE_SOURCE_BYTES) {
      const remaining = MAX_CAPTURE_SOURCE_BYTES + 1 - totalBytes;
      const buffer = Buffer.allocUnsafe(Math.min(HASH_READ_CHUNK_BYTES, remaining));
      const { bytesRead } = await handle.read(buffer, 0, buffer.length, null);
      if (bytesRead === 0) break;
      totalBytes += bytesRead;
      if (totalBytes > MAX_CAPTURE_SOURCE_BYTES) {
        throw new Error(`${label} exceeds the capture source size bound`);
      }
      chunks.push(buffer.subarray(0, bytesRead));
    }
    const after = await handle.stat();
    if (totalBytes !== opened.size || totalBytes !== after.size
        || opened.dev !== after.dev || opened.ino !== after.ino
        || opened.mtimeMs !== after.mtimeMs || opened.ctimeMs !== after.ctimeMs) {
      throw new Error(`${label} changed while it was being verified`);
    }
    await assertNoSymlinkInputComponents(root, relativePath, label);
    return Buffer.concat(chunks, totalBytes);
  } finally {
    await handle.close();
  }
}

export async function hashFilesNoFollow(root, files, label = "capture input") {
  if (!Array.isArray(files) || new Set(files).size !== files.length) {
    throw new Error(`${label} file list must contain unique paths`);
  }
  const hashes = {};
  for (const file of files) {
    const bytes = await readBoundedNoFollowFile(root, file, `${label} ${file}`);
    hashes[file] = createHash("sha256").update(bytes).digest("hex");
  }
  return Object.freeze(hashes);
}

export async function hashCaptureSources() {
  const authored = await hashFilesNoFollow(REPO_ROOT, CAPTURE_SOURCE_FILES, "authored capture source");
  const stagedFiles = await listStagedAssetFiles();
  const staged = await hashFilesNoFollow(REPO_ROOT, stagedFiles, "staged capture asset");
  return Object.freeze({ ...authored, ...staged });
}

export async function listStagedAssetFiles() {
  const files = [];
  async function visit(directory) {
    await assertNoSymlinkInputComponents(
      REPO_ROOT,
      path.relative(REPO_ROOT, directory).split(path.sep).join("/"),
      "staged capture asset directory",
      "directory",
    );
    const entries = await readdir(directory, { withFileTypes: true });
    entries.sort((left, right) => left.name.localeCompare(right.name));
    for (const entry of entries) {
      const entryPath = path.join(directory, entry.name);
      if (entry.isSymbolicLink()) throw new Error("staged capture assets must not contain symbolic links");
      if (entry.isDirectory()) {
        await visit(entryPath);
      } else if (entry.isFile()) {
        files.push(path.relative(REPO_ROOT, entryPath).split(path.sep).join("/"));
      } else {
        throw new Error("staged capture assets may contain only regular files and directories");
      }
    }
  }
  await visit(STAGED_ASSET_ROOT);
  if (!files.length) throw new Error("the staged Next export has no files to bind to the capture receipt");
  return Object.freeze(files.sort());
}

export function inspectPng(bytes) {
  const signature = Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]);
  if (bytes.length < 24 || !bytes.subarray(0, 8).equals(signature) || bytes.toString("ascii", 12, 16) !== "IHDR") {
    throw new Error("capture output is not a PNG image");
  }
  return Object.freeze({ width: bytes.readUInt32BE(16), height: bytes.readUInt32BE(20) });
}

function gitMetadata() {
  const revision = spawnSync("git", ["rev-parse", "HEAD"], {
    cwd: REPO_ROOT, encoding: "utf8", stdio: ["ignore", "pipe", "ignore"],
  });
  const status = spawnSync("git", ["status", "--porcelain", "--untracked-files=all"], {
    cwd: REPO_ROOT, encoding: "utf8", stdio: ["ignore", "pipe", "ignore"],
  });
  if (revision.status !== 0 || status.status !== 0 || !isRevision(revision.stdout.trim())) {
    throw new Error("could not record exact current Git revision and dirty state");
  }
  return { revision: revision.stdout.trim(), dirty: status.stdout.length > 0 };
}

async function assertNoSymlinkComponents(target) {
  const relative = path.relative(REPO_ROOT, target);
  let current = REPO_ROOT;
  for (const component of relative.split(path.sep)) {
    if (!component || component === ".") continue;
    current = path.join(current, component);
    try {
      if ((await lstat(current)).isSymbolicLink()) {
        throw new Error("capture output must not traverse symbolic links");
      }
    } catch (error) {
      if (error.code !== "ENOENT") throw error;
    }
  }
}

async function prepareOutputDirectory(outputDirectory) {
  const relative = path.relative(OUTPUT_PARENT, outputDirectory);
  if (!relative || relative.startsWith(".." + path.sep) || path.isAbsolute(relative)) {
    throw new Error("capture output must be below test-results/assistant-r120");
  }
  await mkdir(OUTPUT_PARENT, { recursive: true, mode: 0o700 });
  await assertNoSymlinkComponents(OUTPUT_PARENT);
  await assertNoSymlinkComponents(outputDirectory);
  try {
    await lstat(outputDirectory);
    throw new Error("capture output already exists; choose a new candidate directory");
  } catch (error) {
    if (error.code !== "ENOENT") throw error;
  }
  await mkdir(outputDirectory, { recursive: true, mode: 0o700 });
  if (await realpath(outputDirectory) !== outputDirectory) {
    throw new Error("capture output path resolves unexpectedly");
  }
}

async function findFreeLoopbackPort() {
  const server = net.createServer();
  await new Promise((resolve, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", resolve);
  });
  const port = server.address().port;
  await new Promise((resolve, reject) => server.close((error) => (error ? reject(error) : resolve())));
  return port;
}

async function loopbackPortIsFree(port) {
  const server = net.createServer();
  try {
    await new Promise((resolve, reject) => {
      server.once("error", reject);
      server.listen(port, "127.0.0.1", resolve);
    });
    await new Promise((resolve, reject) => server.close((error) => (error ? reject(error) : resolve())));
    return true;
  } catch (error) {
    if (server.listening) {
      await new Promise((resolve) => server.close(() => resolve()));
    }
    if (error.code === "EADDRINUSE") return false;
    throw error;
  }
}

function waitForChildExit(child, processState, timeoutMs) {
  if (processState.exitObserved) return Promise.resolve(true);
  return new Promise((resolve) => {
    let timer;
    const finish = (exited) => {
      clearTimeout(timer);
      child.removeListener("exit", onExit);
      resolve(exited || processState.exitObserved);
    };
    const onExit = () => finish(true);
    child.once("exit", onExit);
    if (processState.exitObserved) {
      finish(true);
      return;
    }
    timer = setTimeout(() => finish(false), timeoutMs);
  });
}

async function stopFixtureProcess(child, processState, port, stopGraceMs, stopKillMs) {
  const terminationSignals = [];
  let signalError;
  if (!processState.exitObserved) {
    terminationSignals.push("SIGTERM");
    try {
      child.kill("SIGTERM");
    } catch (error) {
      signalError = error instanceof Error ? error.message : String(error);
    }
    if (!await waitForChildExit(child, processState, stopGraceMs)) {
      terminationSignals.push("SIGKILL");
      try {
        child.kill("SIGKILL");
      } catch (error) {
        signalError = error instanceof Error ? error.message : String(error);
      }
      await waitForChildExit(child, processState, stopKillMs);
    }
  }

  let portReleased = false;
  let portCheckError;
  try {
    portReleased = await loopbackPortIsFree(port);
  } catch (error) {
    portCheckError = error instanceof Error ? error.message : String(error);
  }
  const receipt = Object.freeze({
    child_pid: child.pid ?? null,
    loopback_port: port,
    termination_signals: Object.freeze(terminationSignals),
    child_exit_code: processState.exitCode,
    child_exit_signal: processState.exitSignal,
    process_exit_verified: processState.exitObserved,
    loopback_port_released: portReleased,
  });
  if (!receipt.process_exit_verified || !receipt.loopback_port_released) {
    throw new Error("synthetic assistant fixture cleanup not verified: " + JSON.stringify({
      ...receipt,
      signal_error: signalError || null,
      port_check_error: portCheckError || null,
      spawn_error: processState.spawnError,
    }));
  }
  return receipt;
}

async function directoryIsAbsent(directory) {
  try {
    await lstat(directory);
    return false;
  } catch (error) {
    if (error.code === "ENOENT") return true;
    throw error;
  }
}

async function removeAndVerifyDirectory(directory) {
  await rm(directory, { recursive: true, force: true });
  return directoryIsAbsent(directory);
}

export async function writeCaptureReceiptsAfterCleanup({
  outputDirectory,
  runtimeDirectory,
  manifest,
  runReceipt,
  fixtureLifecycle,
}) {
  if (!fixtureLifecycle
      || !Number.isInteger(fixtureLifecycle.child_pid)
      || !Number.isInteger(fixtureLifecycle.loopback_port)
      || fixtureLifecycle.process_exit_verified !== true
      || fixtureLifecycle.loopback_port_released !== true) {
    throw new Error("capture receipts require verified fixture process exit and loopback port release");
  }
  if (!await directoryIsAbsent(runtimeDirectory)) {
    throw new Error("capture receipts require the fixture runtime directory to be removed");
  }
  const completedRunReceipt = Object.freeze({
    ...runReceipt,
    fixture_lifecycle: Object.freeze({ ...fixtureLifecycle, runtime_directory_removed: true }),
  });
  const manifestPath = path.join(outputDirectory, "assistant-help-captures.json");
  await writeFile(manifestPath, JSON.stringify(manifest, null, 2) + "\n", { flag: "wx", mode: 0o600 });
  const runReceiptPath = path.join(outputDirectory, "assistant-help-capture-run.json");
  await writeFile(runReceiptPath, JSON.stringify(completedRunReceipt, null, 2) + "\n", { flag: "wx", mode: 0o600 });
  return Object.freeze({ manifestPath, runReceiptPath, runReceipt: completedRunReceipt });
}

export async function waitUntilReady(origin, processState, timeoutMs = 10_000) {
  const deadline = Date.now() + timeoutMs;
  let lastError = "readiness has not returned a response";
  while (Date.now() < deadline) {
    if (processState.spawnError) {
      throw new Error("synthetic assistant fixture failed to spawn: " + processState.spawnError);
    }
    if (processState.exitObserved) {
      throw new Error("synthetic assistant fixture exited (" + processState.exitCode
        + "; signal " + processState.exitSignal + "): " + processState.stderr);
    }
    try {
      const remainingMs = deadline - Date.now();
      if (remainingMs <= 0) break;
      // Bound stalled response headers by the same deadline as the readiness loop.
      const response = await fetch(origin + "/api/v1/readiness", {
        signal: AbortSignal.timeout(remainingMs),
      });
      if (response.ok) return;
      lastError = "readiness returned HTTP " + response.status;
    } catch (error) {
      lastError = error instanceof Error ? error.message : "readiness request failed";
    }
    const retryDelayMs = Math.min(50, deadline - Date.now());
    if (retryDelayMs > 0) await new Promise((resolve) => setTimeout(resolve, retryDelayMs));
  }
  throw new Error("synthetic assistant fixture did not become ready: " + lastError + "; " + processState.stderr);
}

export async function startFixture(runtimeDirectory, {
  allocatePort = findFreeLoopbackPort,
  spawnProcess = spawn,
  waitReady = waitUntilReady,
  stopGraceMs = 5_000,
  stopKillMs = 5_000,
} = {}) {
  const port = await allocatePort();
  const origin = "http://127.0.0.1:" + port;
  const processState = {
    exitObserved: false,
    exitCode: null,
    exitSignal: null,
    spawnError: null,
    stderr: "",
  };
  const child = spawnProcess(PYTHON, [FIXTURE_SERVER, "--port", String(port)], {
    cwd: REPO_ROOT,
    env: {
      PATH: process.env.PATH || "/usr/bin:/bin",
      LANG: "C.UTF-8",
      PYTHONPATH: path.join(REPO_ROOT, "src"),
      STOCK_PROBS_DATA_DIR: runtimeDirectory,
      STOCK_PROBS_PROVIDER: "fixture",
      STOCK_PROBS_FIXTURE_NOW: FIXTURE_TIME,
      STOCK_PROBS_PORT: String(port),
    },
    stdio: ["ignore", "ignore", "pipe"],
  });
  child.stderr.on("data", (chunk) => {
    processState.stderr = (processState.stderr + chunk).slice(-16_384);
  });
  child.once("error", (error) => {
    processState.spawnError = error instanceof Error ? error.message : String(error);
  });
  child.once("exit", (code, signal) => {
    processState.exitObserved = true;
    processState.exitCode = code;
    processState.exitSignal = signal;
  });
  let cleanupPromise;
  const stop = () => {
    if (!cleanupPromise) {
      cleanupPromise = stopFixtureProcess(child, processState, port, stopGraceMs, stopKillMs);
    }
    return cleanupPromise;
  };
  try {
    await waitReady(origin, processState);
  } catch (error) {
    const startupError = error instanceof Error ? error.message : String(error);
    let cleanupReceipt;
    try {
      cleanupReceipt = await stop();
    } catch (cleanupError) {
      throw new Error(startupError + "; startup cleanup failed: " + cleanupError.message, { cause: error });
    }
    throw new Error(startupError + "; fixture cleanup receipt " + JSON.stringify(cleanupReceipt), { cause: error });
  }
  return {
    origin,
    pid: child.pid ?? null,
    port,
    stop,
  };
}

async function addFixtureSession(context, origin) {
  await context.addCookies([
    { name: "signal_ledger_session", value: FIXTURE_SESSION, url: origin, httpOnly: true, sameSite: "Lax" },
    { name: "signal_ledger_csrf", value: FIXTURE_CSRF, url: origin, sameSite: "Lax" },
  ]);
}

async function seededWorkspaceUrl(page, origin, route) {
  await page.goto(origin + "/overview");
  const eventId = await page.evaluate(async () => {
    const response = await fetch("/api/v1/history", { cache: "no-store" });
    if (!response.ok) throw new Error("synthetic history fixture returned HTTP " + response.status);
    const payload = await response.json();
    if (!Array.isArray(payload.items) || payload.items.length < 1) {
      throw new Error("synthetic workspace has no seeded event");
    }
    return payload.items[0].id;
  });
  const query = new URLSearchParams({
    symbol: "ACDC",
    asset_type: "stock",
    provider: "deterministic fixture",
    exchange: "NMS",
    event_id: String(eventId),
  });
  return origin + route + "?" + query.toString();
}

async function openAssistant(page) {
  await page.getByRole("button", { name: "Open Ledger assistant" }).click();
  const panel = page.getByTestId("assistant-panel");
  await panel.waitFor({ state: "visible" });
  const modelResponse = await page.evaluate(async () => {
    const response = await fetch("/api/v1/assistant/models", { cache: "no-store" });
    if (!response.ok) throw new Error("synthetic assistant model fixture returned HTTP " + response.status);
    return response.json();
  });
  const modelId = modelResponse.items?.[0]?.id;
  if (typeof modelId !== "string") throw new Error("synthetic assistant model fixture has no model");
  await panel.getByRole("combobox", { name: "Assistant model" }).selectOption(modelId);
  const consent = panel.getByRole("checkbox", { name: /I accept this model's privacy terms/ });
  if (await consent.count()) {
    await consent.check();
    await panel.getByRole("button", { name: "Save privacy choice" }).click();
    await panel.locator("p")
      .filter({ hasText: /^Model privacy consent saved for this policy version\.$/ })
      .waitFor({ state: "visible" });
  }
  return panel;
}

async function expandAssistant(panel, page, label) {
  const expandButton = panel.getByRole("button", { name: "Expand assistant" });
  if (await expandButton.count() !== 1) throw new Error(label + " has no unique Expand assistant control");
  await expandButton.click();
  const restoreButton = panel.getByRole("button", { name: "Restore assistant size" });
  await restoreButton.waitFor({ state: "visible" });
  if (await restoreButton.getAttribute("aria-pressed") !== "true") {
    throw new Error(label + " did not enter expanded assistant mode");
  }
  const viewport = page.viewportSize();
  const bounds = await panel.boundingBox();
  if (!viewport || viewport.width !== 1440 || viewport.height !== 1000 || !bounds) {
    throw new Error(label + " was not measured at the approved 1440x1000 desktop viewport");
  }
  if (
    bounds.x < 0 || bounds.y < 0
    || bounds.x + bounds.width > viewport.width + 1
    || bounds.y + bounds.height > viewport.height + 1
    || bounds.width < 800 || bounds.height < 900
  ) {
    throw new Error(label + " expanded panel does not fit the 1440x1000 viewport at expanded dimensions");
  }
  return Object.freeze({
    assistant_size: "expanded",
    viewport: Object.freeze(viewport),
    panel_bounds: Object.freeze({ x: bounds.x, y: bounds.y, width: bounds.width, height: bounds.height }),
  });
}

async function installSourceHistoryFixture(page, origin, modelId, savedContext = null) {
  await page.route((url) => (
    url.origin === origin && url.pathname === "/api/v1/assistant/conversations"
  ), async (route) => {
    if (route.request().method() !== "GET") return route.continue();
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        items: [{
          id: "conversation-source-fixture",
          title: "Explain this synthetic forecast",
          revision: 1,
          created_at: "2025-01-10T17:00:00Z",
          updated_at: "2025-01-10T17:01:00Z",
          last_message_preview: "A sample probability with attributed fixture sources.",
        }],
        page: 1,
        page_size: 20,
        total: 1,
      }),
    });
  });
  await page.route((url) => (
    url.origin === origin && url.pathname === "/api/v1/assistant/conversations/conversation-source-fixture"
  ), async (route) => {
    if (route.request().method() !== "GET") return route.continue();
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        conversation: {
          id: "conversation-source-fixture",
          title: "Explain this synthetic forecast",
          revision: 1,
          created_at: "2025-01-10T17:00:00Z",
          updated_at: "2025-01-10T17:01:00Z",
          delete_confirmation_phrase: "DELETE source-fixture",
        },
        messages: {
          items: [{
            id: "assistant-source-message",
            turn_id: "turn-source-fixture",
            seq: 2,
            role: "assistant",
            text: SAVED_FORECAST_ANSWER,
            created_at: "2025-01-10T17:01:00Z",
            sources: [
              {
                source_id: "source-synthetic-market-record",
                title: "Example Market Data Record",
                url: "https://example.com/synthetic-market-record",
                source_type: "workspace fixture",
                retrieved_at: "2025-01-10T17:00:00Z",
                as_of: "2025-01-10T16:55:00Z",
              },
              {
                source_id: "source-synthetic-method-note",
                title: "Example Forecast Method Note",
                url: "https://example.com/synthetic-method-note",
                source_type: "saved forecast fixture",
                retrieved_at: "2025-01-10T17:00:00Z",
                as_of: "2025-01-10T16:55:00Z",
              },
            ],
          }],
          page: 1,
          page_size: 50,
          total: 1,
        },
        turns: [{
          id: "turn-source-fixture",
          status: "completed",
          model_id: modelId,
          policy_version: "synthetic-policy-v1",
          context_version: savedContext?.context_version ?? "source-context-v1",
          context: {
            route: "/tools/forecast",
            instrument: savedContext?.instrument ?? null,
            event_ref: savedContext?.event_ref ?? null,
            result_ref: null,
            context_version: savedContext?.context_version ?? "source-context-v1",
          },
          created_at: "2025-01-10T17:00:00Z",
          completed_at: "2025-01-10T17:01:00Z",
          actions: [],
        }],
        actions: [],
        events: {
          items: [{
            turn_id: "turn-source-fixture",
            sequence: 1,
            type: "tool",
            data: {
              name: "signal-ledger_workspace_summary",
              call_id: "fixture-source-call",
              receipt_id: "fixture-source-receipt",
              status: "complete",
              description: "Read synthetic forecast context",
              result_bytes: 128,
            },
            created_at: "2025-01-10T17:00:30Z",
          }],
          page: 1,
          page_size: 100,
          total: 1,
        },
      }),
    });
  });
}

async function makeBrowserContext(browser, spec) {
  const context = await browser.newContext({
    viewport: spec.viewport,
    deviceScaleFactor: spec.mobile ? 2.625 : 1,
    isMobile: spec.mobile,
    hasTouch: spec.mobile,
    colorScheme: spec.theme,
  });
  await context.addInitScript((theme) => localStorage.setItem("stock-probs.theme", theme), spec.theme);
  return context;
}

export async function observeLocalPage(context, origin, page) {
  const diagnostics = { externalRequests: [], failedResponses: [], consoleErrors: [], pageErrors: [] };
  await context.route("**/*", async (route) => {
    const requestUrl = new URL(route.request().url());
    if ((requestUrl.protocol === "http:" || requestUrl.protocol === "https:") && requestUrl.origin !== origin) {
      diagnostics.externalRequests.push(requestUrl.origin);
      return route.abort();
    }
    return route.continue();
  });
  page.on("response", (response) => {
    if (response.status() >= 400) diagnostics.failedResponses.push({ status: response.status(), url: response.url() });
  });
  page.on("console", (message) => {
    if (message.type() === "error") diagnostics.consoleErrors.push(message.text());
  });
  page.on("pageerror", (error) => diagnostics.pageErrors.push(error.message));
  return () => {
    if (diagnostics.externalRequests.length || diagnostics.failedResponses.length
        || diagnostics.consoleErrors.length || diagnostics.pageErrors.length) {
      throw new Error("capture diagnostics failed: " + JSON.stringify(diagnostics));
    }
  };
}

async function saveCapture(page, outputDirectory, id) {
  const spec = CAPTURE_SPECS[id];
  const file = OUTPUT_FILES[id];
  const outputPath = path.join(outputDirectory, file);
  const viewport = await page.evaluate(() => ({ width: window.innerWidth, height: window.innerHeight }));
  if (viewport.width !== spec.viewport.width || viewport.height !== spec.viewport.height) {
    throw new Error("capture " + id + " rendered at an unexpected CSS viewport");
  }
  const renderedTheme = await page.locator("html").getAttribute("data-theme");
  if (renderedTheme !== spec.theme) {
    throw new Error("capture " + id + " rendered in " + renderedTheme + " instead of " + spec.theme);
  }
  // CSS scale avoids a DPR-sized raster while preserving the full viewport and component geometry.
  const bytes = await page.screenshot({ path: outputPath, animations: "disabled", scale: "css" });
  if (bytes.length < 1 || bytes.length > MAX_CAPTURE_BYTES) {
    throw new Error("capture " + id + " exceeds its PNG size bound");
  }
  await chmod(outputPath, 0o600);
  return {
    file,
    sha256: createHash("sha256").update(bytes).digest("hex"),
    route: spec.route,
    viewport,
    image_dimensions: inspectPng(bytes),
    theme: spec.theme,
    data: "synthetic",
  };
}

async function assertVisibleInsideAssistantBody(panel, elements, label) {
  // The direct div is the assistant's scrollable body between its header and composer.
  const body = panel.locator(":scope > div");
  if (await body.count() !== 1) throw new Error(label + " has no unique assistant scroll body");
  const bodyBounds = await body.boundingBox();
  if (!bodyBounds) throw new Error(label + " assistant scroll body is not visible");
  for (const [name, element] of elements) {
    if (!await element.isVisible()) throw new Error(label + " " + name + " is not visible");
    const bounds = await element.boundingBox();
    if (!bounds) throw new Error(label + " " + name + " has no visible bounds");
    const epsilon = 1;
    if (
      bounds.x < bodyBounds.x - epsilon
      || bounds.y < bodyBounds.y - epsilon
      || bounds.x + bounds.width > bodyBounds.x + bodyBounds.width + epsilon
      || bounds.y + bounds.height > bodyBounds.y + bodyBounds.height + epsilon
    ) {
      throw new Error(label + " " + name + " falls outside the visible assistant scroll body");
    }
  }
}

async function captureBaseline(browser, origin, outputDirectory, id) {
  const spec = CAPTURE_SPECS[id];
  const context = await makeBrowserContext(browser, spec);
  try {
    await addFixtureSession(context, origin);
    const page = await context.newPage();
    const checkDiagnostics = await observeLocalPage(context, origin, page);
    const workspaceUrl = await seededWorkspaceUrl(page, origin, spec.route);
    await page.goto(workspaceUrl);
    await openAssistant(page);
    checkDiagnostics();
    return await saveCapture(page, outputDirectory, id);
  } finally {
    await context.close();
  }
}

async function captureForecastSources(browser, origin, outputDirectory) {
  const id = "forecast_sources";
  const spec = CAPTURE_SPECS[id];
  const context = await makeBrowserContext(browser, spec);
  try {
    await addFixtureSession(context, origin);
    const page = await context.newPage();
    const checkDiagnostics = await observeLocalPage(context, origin, page);
    const workspaceUrl = await seededWorkspaceUrl(page, origin, spec.route);
    await page.goto(workspaceUrl);
    const modelResponse = await page.evaluate(async () => {
      const response = await fetch("/api/v1/assistant/models", { cache: "no-store" });
      if (!response.ok) throw new Error("synthetic assistant model fixture returned HTTP " + response.status);
      return response.json();
    });
    const modelId = modelResponse.items?.[0]?.id;
    if (typeof modelId !== "string") throw new Error("synthetic assistant model fixture has no model");
    await installSourceHistoryFixture(page, origin, modelId);
    const panel = await openAssistant(page);
    await panel.getByRole("button", { name: "Open conversation history" }).click();
    await panel.getByRole("button", { name: /Explain this synthetic forecast/ }).click();
    await panel.getByRole("link", { name: /Example Market Data Record/ }).waitFor({ state: "visible" });
    await panel.getByRole("link", { name: /Example Forecast Method Note/ }).waitFor({ state: "visible" });
    checkDiagnostics();
    return await saveCapture(page, outputDirectory, id);
  } finally {
    await context.close();
  }
}

async function captureActions(browser, origin, outputDirectory) {
  const context = await makeBrowserContext(browser, CAPTURE_SPECS.action_preview);
  try {
    await addFixtureSession(context, origin);
    const page = await context.newPage();
    const checkDiagnostics = await observeLocalPage(context, origin, page);
    const workspaceUrl = await seededWorkspaceUrl(page, origin, "/tools/live-trading");
    await page.goto(workspaceUrl);
    const panel = await openAssistant(page);
    const previewGeometry = await expandAssistant(panel, page, "action preview");
    const prompt = "Explain this synthetic workspace and preview a display change";
    await panel.getByRole("textbox", { name: "Ask about this page" }).fill(prompt);
    await panel.getByRole("button", { name: "Send question" }).click();
    const proposal = panel.getByRole("region", { name: "Preview: Change display theme" });
    await proposal.waitFor({ state: "visible" });
    await panel.locator("p")
      .filter({ hasText: /^Assistant response complete\.$/ })
      .waitFor({ state: "visible" });
    const proposalHeading = proposal.getByRole("heading", { level: 3 });
    const confirmationInput = proposal.getByRole("textbox", { name: /Type CONFIRM [a-f0-9]{8} to confirm/ });
    const confirmButton = proposal.getByRole("button", { name: "Confirm change" });
    await proposal.scrollIntoViewIfNeeded();
    await assertVisibleInsideAssistantBody(panel, [
      ["proposal heading", proposalHeading],
      ["confirmation phrase input", confirmationInput],
      ["confirm button", confirmButton],
    ], "action preview");
    if (!(await proposalHeading.textContent())?.trim()) throw new Error("action preview has no visible heading text");
    if (await confirmationInput.inputValue() !== "" || !await confirmButton.isDisabled()) {
      throw new Error("action preview must leave the exact phrase empty and confirmation disabled");
    }
    const preview = await saveCapture(page, outputDirectory, "action_preview");

    const phrase = (await proposal.locator("code").textContent())?.trim();
    if (!phrase || !/^CONFIRM [a-f0-9]{8}$/.test(phrase)) {
      throw new Error("synthetic action preview did not provide its exact confirmation phrase");
    }
    await proposal.getByRole("textbox").fill(phrase);
    await proposal.getByRole("button", { name: "Confirm change" }).click();
    await panel.getByText("Change display theme · handed off", { exact: true }).waitFor({ state: "visible" });
    await page.evaluate(() => localStorage.setItem("stock-probs.theme", "light"));
    await page.reload();
    const reopened = await openAssistant(page);
    const receiptGeometry = await expandAssistant(reopened, page, "action receipt");
    await reopened.getByRole("button", { name: "Open conversation history" }).click();
    await reopened.getByRole("button", { name: new RegExp(prompt) }).click();
    const receipts = reopened.getByRole("region", { name: "Confirmed action receipts" });
    const receiptRow = receipts.getByRole("listitem").filter({ hasText: "Change display theme · handed off" });
    const receiptStatus = receiptRow.getByText("Change display theme · handed off", { exact: true });
    const receiptHeading = receipts.getByRole("heading", { name: "Confirmed action receipts" });
    await receiptRow.waitFor({ state: "visible" });
    await receiptRow.scrollIntoViewIfNeeded();
    await assertVisibleInsideAssistantBody(reopened, [
      ["receipt heading", receiptHeading],
      ["handed-off receipt status", receiptStatus],
    ], "action receipt");
    const receipt = await saveCapture(page, outputDirectory, "action_receipt");
    checkDiagnostics();
    return {
      captures: { action_preview: preview, action_receipt: receipt },
      presentation: { action_preview: previewGeometry, action_receipt: receiptGeometry },
    };
  } finally {
    await context.close();
  }
}

async function captureHistoryContext(browser, origin, outputDirectory) {
  const id = "history_context";
  const spec = CAPTURE_SPECS[id];
  const context = await makeBrowserContext(browser, spec);
  try {
    await addFixtureSession(context, origin);
    const page = await context.newPage();
    const checkDiagnostics = await observeLocalPage(context, origin, page);
    const workspaceUrl = await seededWorkspaceUrl(page, origin, spec.route);
    await page.goto(workspaceUrl);
    const modelResponse = await page.evaluate(async () => {
      const response = await fetch("/api/v1/assistant/models", { cache: "no-store" });
      if (!response.ok) throw new Error("synthetic assistant model fixture returned HTTP " + response.status);
      return response.json();
    });
    const modelId = modelResponse.items?.[0]?.id;
    if (typeof modelId !== "string") throw new Error("synthetic assistant model fixture has no model");
    const eventId = Number(new URL(workspaceUrl).searchParams.get("event_id"));
    if (!Number.isSafeInteger(eventId) || eventId <= 0) throw new Error("synthetic workspace has no saved ACDC event");
    await installSourceHistoryFixture(page, origin, modelId, {
      instrument: {
        symbol: "ACDC",
        asset_type: "stock",
        provider: "deterministic fixture",
        exchange: "NMS",
        display_name: "Synthetic ACDC equity",
      },
      event_ref: { id: eventId, version: "saved-forecast-context-v1" },
      context_version: "saved-forecast-context-v1",
    });
    const panel = await openAssistant(page);
    const panelGeometry = await expandAssistant(panel, page, "history context");
    await panel.getByRole("button", { name: "Open conversation history" }).click();
    const historyConversation = panel.getByRole("button", { name: /Explain this synthetic forecast/ });
    if (await historyConversation.count() !== 1) {
      throw new Error("history context does not have one exact synthetic forecast conversation");
    }
    await historyConversation.click();
    const transcript = panel.getByRole("group", { name: "Conversation" });
    const assistantMessage = await savedForecastMessage(transcript, page);
    // The saved snapshot keeps its ACDC identity while the separately refreshed page is Live Trading.
    const answerSnapshot = assistantMessage.getByText("Context snapshot: Forecast tool · ACDC", { exact: true });
    await answerSnapshot.waitFor({ state: "visible" });
    await assistantMessage.getByRole("link", { name: /Example Market Data Record/ })
      .waitFor({ state: "visible" });
    await assistantMessage.getByRole("link", { name: /Example Forecast Method Note/ })
      .waitFor({ state: "visible" });
    const workspaceContext = panel.getByLabel("Workspace context");
    await refreshHistoryContextPreview(workspaceContext);
    await workspaceContext.getByText("owner-validated saved event reference", { exact: true })
      .waitFor({ state: "visible" });
    await workspaceContext.getByText("selected public instrument reference", { exact: true })
      .waitFor({ state: "visible" });
    await workspaceContext
      .getByText("Live Trading tool · ACDC · STOCK", { exact: true }).waitFor({ state: "visible" });
    checkDiagnostics();
    return {
      capture: await saveCapture(page, outputDirectory, id),
      presentation: panelGeometry,
    };
  } finally {
    await context.close();
  }
}

export async function runCaptureCandidate({ outputDirectory }) {
  const resolvedOutput = path.resolve(outputDirectory);
  const git = gitMetadata();
  const sourceHashes = await hashCaptureSources();
  await prepareOutputDirectory(resolvedOutput);
  const tempDirectory = await mkdtemp(path.join(os.tmpdir(), "r120-assistant-capture-"));
  const runtimeDirectory = path.join(tempDirectory, "runtime");
  let fixture;
  let browser;
  let candidate;
  let captureError;
  try {
    await mkdir(runtimeDirectory, { mode: 0o700 });
    fixture = await startFixture(runtimeDirectory);
    browser = await chromium.launch({ headless: true });
    const captures = {};
    const capturePresentation = {};
    for (const id of ["desktop_light", "desktop_dark", "mobile_light", "mobile_dark"]) {
      captures[id] = await captureBaseline(browser, fixture.origin, resolvedOutput, id);
    }
    captures.forecast_sources = await captureForecastSources(browser, fixture.origin, resolvedOutput);
    const actions = await captureActions(browser, fixture.origin, resolvedOutput);
    Object.assign(captures, actions.captures);
    Object.assign(capturePresentation, actions.presentation);
    const historyContext = await captureHistoryContext(browser, fixture.origin, resolvedOutput);
    captures.history_context = historyContext.capture;
    capturePresentation.history_context = historyContext.presentation;
    candidate = { captures, capturePresentation };
  } catch (error) {
    captureError = error;
  }

  const cleanupErrors = [];
  if (browser) {
    try {
      await browser.close();
    } catch (error) {
      cleanupErrors.push("browser close: " + (error instanceof Error ? error.message : String(error)));
    }
  }
  let fixtureLifecycle;
  if (fixture) {
    try {
      fixtureLifecycle = await fixture.stop();
    } catch (error) {
      cleanupErrors.push("fixture stop: " + (error instanceof Error ? error.message : String(error)));
    }
  }
  let runtimeDirectoryRemoved = false;
  try {
    runtimeDirectoryRemoved = await removeAndVerifyDirectory(tempDirectory);
  } catch (error) {
    cleanupErrors.push("runtime directory removal: " + (error instanceof Error ? error.message : String(error)));
  }
  if (!runtimeDirectoryRemoved) cleanupErrors.push("runtime directory remains present");

  if (captureError || cleanupErrors.length || !fixtureLifecycle) {
    const message = captureError instanceof Error
      ? captureError.message
      : String(captureError || "fixture lifecycle unavailable");
    throw new Error(message + "; capture cleanup " + JSON.stringify({
      fixture_lifecycle: fixtureLifecycle || null,
      runtime_directory_removed: runtimeDirectoryRemoved,
      cleanup_errors: cleanupErrors,
    }), { cause: captureError });
  }

  const finalSourceHashes = await hashCaptureSources();
  if (JSON.stringify(sourceHashes) !== JSON.stringify(finalSourceHashes)) {
    throw new Error("capture inputs changed during the browser run; fixture cleanup " + JSON.stringify({
      ...fixtureLifecycle,
      runtime_directory_removed: runtimeDirectoryRemoved,
    }));
  }

  const manifest = buildCandidateManifest({ revision: git.revision, captures: candidate.captures });
  const runReceipt = buildRunReceipt({
    ...git,
    sourceHashes,
    captures: candidate.captures,
    capturePresentation: candidate.capturePresentation,
  });
  const persisted = await writeCaptureReceiptsAfterCleanup({
    outputDirectory: resolvedOutput,
    runtimeDirectory,
    manifest,
    runReceipt,
    fixtureLifecycle,
  });
  return {
    task: "R-ASTRA-120",
    status: persisted.runReceipt.status,
    revision: persisted.runReceipt.revision,
    revision_state: persisted.runReceipt.revision_state,
    output: path.relative(REPO_ROOT, resolvedOutput),
    manifest: path.relative(REPO_ROOT, persisted.manifestPath),
    run_receipt: path.relative(REPO_ROOT, persisted.runReceiptPath),
    source_sha256: persisted.runReceipt.source_sha256,
    captures: persisted.runReceipt.capture_sha256,
    capture_presentation: persisted.runReceipt.capture_presentation,
    fixture_lifecycle: persisted.runReceipt.fixture_lifecycle,
  };
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try {
    const outputDirectory = parseArguments(process.argv.slice(2));
    const result = await runCaptureCandidate({ outputDirectory });
    process.stdout.write(JSON.stringify(result, null, 2) + "\n");
  } catch (error) {
    process.stderr.write((error instanceof Error ? error.message : String(error)) + "\n");
    process.exitCode = 1;
  }
}
