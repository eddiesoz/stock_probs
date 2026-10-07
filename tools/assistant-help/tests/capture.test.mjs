import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { createRequire } from "node:module";
import { EventEmitter } from "node:events";
import { mkdir, mkdtemp, readFile, rm, symlink, truncate, writeFile } from "node:fs/promises";
import net from "node:net";
import os from "node:os";
import path from "node:path";
import { PassThrough } from "node:stream";
import test from "node:test";
import {
  CAPTURE_SOURCE_FILES,
  CAPTURE_SPECS,
  buildCandidateManifest,
  buildRunReceipt,
  hashCaptureSources,
  hashFilesNoFollow,
  inspectPng,
  listStagedAssetFiles,
  observeLocalPage,
  parseArguments,
  SAVED_FORECAST_ANSWER,
  savedForecastMessage,
  refreshHistoryContextPreview,
  startFixture,
  waitUntilReady,
  writeCaptureReceiptsAfterCleanup,
} from "../capture.mjs";
import { CAPTURE_IDS, REPO_ROOT, validateCaptureManifest } from "../render.mjs";

const REVISION = "a".repeat(40);
const hash = (text) => createHash("sha256").update(text).digest("hex");

test("saved forecast selection handles adjacent timestamps and nested citations and rejects duplicate authors", async () => {
  const require = createRequire(path.join(REPO_ROOT, "tools/browser/package.json"));
  const { chromium } = require("@playwright/test");
  const browser = await chromium.launch({ headless: true });
  try {
    const page = await browser.newPage();
    const row = '<li><div><strong>Ledger assistant</strong><time>Jan 10, 2025, 12:01 PM</time></div>'
      + '<p>' + SAVED_FORECAST_ANSWER + '</p><small>Context snapshot: Forecast tool · ACDC</small>'
      + '<ol><li><a href="https://example.com/record">Example Market Data Record</a></li>'
      + '<li><a href="https://example.com/method">Example Forecast Method Note</a></li></ol></li>';
    await page.setContent('<h2>Ledger assistant</h2><div role="group" aria-label="Conversation"><ol>' + row + '</ol></div>');
    const transcript = page.getByRole("group", { name: "Conversation" });
    const selected = await savedForecastMessage(transcript, page);
    assert.equal(await selected.count(), 1);
    assert.equal(await selected.getByRole("link").count(), 2);
    assert.equal(await selected.getByText("Context snapshot: Forecast tool · ACDC", { exact: true }).count(), 1);
    await page.setContent('<div role="group" aria-label="Conversation"><ol>' + row + row + '</ol></div>');
    await assert.rejects(savedForecastMessage(transcript, page), /strict mode violation/);
    await page.setContent('<div role="group" aria-label="Conversation"><ol>' + row.replace('<strong>Ledger assistant</strong>', '<strong>You</strong>') + '</ol></div>');
    await assert.rejects(savedForecastMessage(transcript, page), /exactly one Ledger assistant transcript item/);
    await page.setContent('<section aria-label="Workspace context"><details><summary>Preview</summary>'
      + '<strong>Only the selected page and validated references are attached.</strong>'
      + '<button>Refresh context preview</button></details></section>');
    await page.evaluate(() => {
      const section = document.querySelector("section");
      const readyMarkup = section.innerHTML;
      section.querySelector("button").addEventListener("click", () => {
        section.innerHTML = '<p>Checking safe workspace context…</p>';
        requestAnimationFrame(() => { section.innerHTML = readyMarkup; });
      });
    });
    const workspaceContext = page.getByLabel("Workspace context");
    await refreshHistoryContextPreview(workspaceContext);
    assert.equal(await workspaceContext.locator("details").getAttribute("open"), "");
    assert.equal(await workspaceContext.getByText("Only the selected page and validated references are attached.", { exact: true }).isVisible(), true);
  } finally {
    await browser.close();
  }
});

function capturesFixture() {
  return Object.fromEntries(CAPTURE_IDS.map((id) => {
    const spec = CAPTURE_SPECS[id];
    return [id, {
      file: "r120-" + id.replaceAll("_", "-") + ".png",
      sha256: hash(id),
      route: spec.route,
      viewport: { ...spec.viewport },
      image_dimensions: { ...spec.viewport },
      theme: spec.theme,
      data: "synthetic",
    }];
  }));
}

function capturePresentationFixture() {
  return Object.fromEntries(["action_preview", "action_receipt", "history_context"].map((id) => [id, {
    assistant_size: "expanded",
    viewport: { width: 1440, height: 1000 },
    panel_bounds: { x: 604, y: 16, width: 820, height: 920 },
  }]));
}

function png(width, height) {
  const bytes = Buffer.alloc(24);
  Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]).copy(bytes, 0);
  bytes.write("IHDR", 12, "ascii");
  bytes.writeUInt32BE(width, 16);
  bytes.writeUInt32BE(height, 20);
  return bytes;
}

test("capture arguments stay below the R-ASTRA-120 candidate artifact root", () => {
  assert.equal(
    parseArguments(["--output-dir", "test-results/assistant-r120/candidate-one"]),
    path.join(REPO_ROOT, "test-results/assistant-r120/candidate-one"),
  );
  assert.throws(() => parseArguments([]), /Usage:/);
  assert.throws(
    () => parseArguments(["--output-dir", "/tmp/assistant-captures"]),
    /below test-results\/assistant-r120/,
  );
  assert.throws(
    () => parseArguments(["--output-dir", "test-results/assistant-r120"]),
    /below test-results\/assistant-r120/,
  );
});

test("capture status waits use visible text without assuming status roles", async () => {
  const source = await readFile(new URL("../capture.mjs", import.meta.url), "utf8");
  const openAssistant = source.slice(
    source.indexOf("async function openAssistant"),
    source.indexOf("async function expandAssistant"),
  );
  const captureActions = source.slice(
    source.indexOf("async function captureActions"),
    source.indexOf("async function captureHistoryContext"),
  );

  assert.ok(openAssistant.includes('panel.locator("p")'));
  assert.ok(openAssistant.includes("hasText: /^Model privacy consent saved for this policy version\\.$/"));
  assert.doesNotMatch(openAssistant, /p\[role="status"\]/);
  assert.ok(captureActions.includes('panel.locator("p")'));
  assert.ok(captureActions.includes("hasText: /^Assistant response complete\\.$/"));
  assert.doesNotMatch(captureActions, /p\[role="status"\]/);
});

test("roleless paragraph status wait disambiguates duplicate screen-reader announcement", async () => {
  const require = createRequire(path.join(REPO_ROOT, "tools/browser/package.json"));
  const { chromium } = require("@playwright/test");
  const browser = await chromium.launch({ headless: true });
  try {
    const page = await browser.newPage();
    const statuses = [
      "Model privacy consent saved for this policy version.",
      "Assistant response complete.",
    ];
    // The expanded panel renders each message in a visible paragraph and an aria-live span.
    for (const status of statuses) {
      await page.setContent(
        '<style>.sr-only{position:absolute;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;'
          + 'clip:rect(0,0,0,0);white-space:nowrap;border:0}</style>'
          + '<section data-testid="assistant-panel"><p>' + status + '</p>'
          + '<span class="sr-only" aria-live="polite">' + status + '</span></section>',
      );
      const panel = page.getByTestId("assistant-panel");
      const duplicateText = panel.getByText(status, { exact: true });
      assert.equal(await duplicateText.count(), 2);
      await assert.rejects(duplicateText.waitFor({ state: "visible" }), /strict mode violation/);

      const escaped = status.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
      const visibleParagraph = panel.locator("p").filter({ hasText: new RegExp("^" + escaped + "$") });
      assert.equal(await visibleParagraph.count(), 1);
      await visibleParagraph.waitFor({ state: "visible" });
      assert.equal(await visibleParagraph.isVisible(), true);
    }
  } finally {
    await browser.close();
  }
});

test("candidate metadata binds each synthetic capture to its exact revision and PNG hash without a QA pass", () => {
  const captures = capturesFixture();
  const manifest = buildCandidateManifest({ revision: REVISION, captures });

  assert.equal(manifest.task, "R-ASTRA-120");
  assert.equal(manifest.revision, REVISION);
  assert.equal(manifest.qa_receipt_file, "assistant-help-qa-receipt.json");
  assert.equal(manifest.qa_receipt_sha256, "0".repeat(64));
  assert.deepEqual(Object.keys(manifest), [
    "schema_version",
    "task",
    "revision",
    "qa_receipt_file",
    "qa_receipt_sha256",
    "captures",
  ]);
  assert.deepEqual(Object.keys(manifest.captures), CAPTURE_IDS);
  for (const id of CAPTURE_IDS) {
    assert.equal(manifest.captures[id].sha256, captures[id].sha256);
    assert.equal(manifest.captures[id].revision, REVISION);
    assert.equal(manifest.captures[id].privacy_review, "pending");
  }
  assert.equal(manifest.captures.history_context.route, "/tools/live-trading");
  assert.throws(() => validateCaptureManifest(manifest, REVISION), /private-data review/);
});

test("candidate run receipt binds the dirty revision, all UI source inputs, and exact screenshot hashes", () => {
  const captures = capturesFixture();
  const sourceHashes = Object.fromEntries([
    ...CAPTURE_SOURCE_FILES.map((file) => [file, hash(file)]),
    ["src/stock_probs/static/next/index.html", hash("staged-index")],
  ]);
  const capturePresentation = capturePresentationFixture();
  const receipt = buildRunReceipt({ revision: REVISION, dirty: true, sourceHashes, captures, capturePresentation });

  assert.equal(receipt.status, "builder-candidate");
  assert.equal(receipt.revision, REVISION);
  assert.equal(receipt.revision_state, "dirty");
  assert.deepEqual(Object.keys(receipt.source_sha256), [
    ...CAPTURE_SOURCE_FILES,
    "src/stock_probs/static/next/index.html",
  ]);
  assert.deepEqual(receipt.capture_sha256, Object.fromEntries(
    CAPTURE_IDS.map((id) => [id, captures[id].sha256]),
  ));
  assert.ok(CAPTURE_SOURCE_FILES.includes("frontend/components/assistant/assistant-panel.tsx"));
  assert.ok(CAPTURE_SOURCE_FILES.includes("src/stock_probs/static/app.css"));
  assert.ok(CAPTURE_SOURCE_FILES.includes("tools/browser/assistant_qa_server.py"));
  assert.ok(CAPTURE_SOURCE_FILES.includes("tools/assistant-help/capture.mjs"));
  assert.equal(receipt.source_sha256["src/stock_probs/static/next/index.html"], hash("staged-index"));
  assert.deepEqual(receipt.capture_presentation, capturePresentation);

  const missingSource = { ...sourceHashes };
  delete missingSource["tools/browser/assistant_qa_server.py"];
  assert.throws(
    () => buildRunReceipt({ revision: REVISION, dirty: true, sourceHashes: missingSource, captures }),
    /authored inputs and the complete staged asset set/,
  );
  assert.throws(
    () => buildRunReceipt({ revision: REVISION, dirty: true, sourceHashes, captures }),
    /expanded assistant geometry for the three detail captures/,
  );
  const offscreenPresentation = capturePresentationFixture();
  offscreenPresentation.action_preview.panel_bounds.y = 200;
  assert.throws(
    () => buildRunReceipt({ revision: REVISION, dirty: true, sourceHashes, captures, capturePresentation: offscreenPresentation }),
    /invalid expanded assistant geometry for action_preview/,
  );

  const malformedCaptureHash = capturesFixture();
  malformedCaptureHash.history_context.sha256 = "not-a-sha256";
  assert.throws(
    () => buildRunReceipt({ revision: REVISION, dirty: true, sourceHashes, captures: malformedCaptureHash }),
    /approved history_context screenshot SHA-256/,
  );
});

test("capture input hashes cover every approved source file as a SHA-256", async () => {
  const hashes = await hashCaptureSources();
  const stagedFiles = await listStagedAssetFiles();
  assert.deepEqual(Object.keys(hashes), [...CAPTURE_SOURCE_FILES, ...stagedFiles]);
  assert.ok(stagedFiles.length > 0);
  assert.ok(stagedFiles.every((file) => file.startsWith("src/stock_probs/static/next/")));
  assert.ok(Object.values(hashes).every((value) => /^[0-9a-f]{64}$/.test(value)));
});

test("bounded source hashing refuses symlinked authored files and staged ancestors", async () => {
  const root = await mkdtemp(path.join(os.tmpdir(), "assistant-help-source-hash-"));
  try {
    const authoredDirectory = path.join(root, "frontend");
    await mkdir(authoredDirectory);
    const authoredFile = path.join(authoredDirectory, "source.ts");
    const authoredBytes = Buffer.from("synthetic authored source");
    await writeFile(authoredFile, authoredBytes, { mode: 0o600 });
    const authoredHash = await hashFilesNoFollow(root, ["frontend/source.ts"], "authored capture source");
    assert.equal(authoredHash["frontend/source.ts"], hash(authoredBytes));

    const externalFile = path.join(root, "linked-target.ts");
    await writeFile(externalFile, Buffer.from("synthetic symlink target"), { mode: 0o600 });
    await rm(authoredFile);
    await symlink(externalFile, authoredFile);
    await assert.rejects(
      hashFilesNoFollow(root, ["frontend/source.ts"], "authored capture source"),
      /must not traverse symbolic links/,
    );

    const nestedSource = path.join(root, "real-frontend", "nested", "source.ts");
    await mkdir(path.dirname(nestedSource), { recursive: true });
    await writeFile(nestedSource, Buffer.from("synthetic nested source"), { mode: 0o600 });
    await symlink(path.join(root, "real-frontend"), path.join(root, "frontend-alias"));
    await assert.rejects(
      hashFilesNoFollow(root, ["frontend-alias/nested/source.ts"], "authored capture source"),
      /must not traverse symbolic links/,
    );

    const stagedTarget = path.join(root, "real-static", "next", "bundle.js");
    await mkdir(path.dirname(stagedTarget), { recursive: true });
    await writeFile(stagedTarget, Buffer.from("synthetic staged bundle"), { mode: 0o600 });
    await symlink(path.join(root, "real-static"), path.join(root, "src"));
    await assert.rejects(
      hashFilesNoFollow(root, ["src/next/bundle.js"], "staged capture asset"),
      /must not traverse symbolic links/,
    );

    const oversizedFile = path.join(root, "oversized.ts");
    await writeFile(oversizedFile, Buffer.alloc(0), { mode: 0o600 });
    await truncate(oversizedFile, 16 * 1024 * 1024 + 1);
    await assert.rejects(
      hashFilesNoFollow(root, ["oversized.ts"], "authored capture source"),
      /bounded single-link regular file/,
    );
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});

test("candidate metadata rejects incomplete, wrong-route, and malformed-digest captures", () => {
  const captures = capturesFixture();
  delete captures.history_context;
  assert.throws(
    () => buildCandidateManifest({ revision: REVISION, captures }),
    /exact approved screenshot set/,
  );

  const wrongRoute = capturesFixture();
  wrongRoute.forecast_sources.route = "/tools/live-trading";
  assert.throws(
    () => buildCandidateManifest({ revision: REVISION, captures: wrongRoute }),
    /metadata does not match the approved forecast_sources/,
  );

  const wrongHash = capturesFixture();
  wrongHash.action_preview.sha256 = "not-a-sha256";
  assert.throws(
    () => buildCandidateManifest({ revision: REVISION, captures: wrongHash }),
    /missing the approved action_preview PNG and SHA-256/,
  );
  assert.throws(
    () => buildCandidateManifest({ revision: "not-a-revision", captures: capturesFixture() }),
    /exact 40-character Git revision/,
  );
});

test("PNG inspection reads only the canonical IHDR dimensions and rejects non-PNG input", () => {
  assert.deepEqual(inspectPng(png(390, 844)), { width: 390, height: 844 });
  assert.throws(() => inspectPng(Buffer.from("not a screenshot")), /not a PNG/);
});

function ownedFixtureProcess({ ignoreTerm = false } = {}) {
  const child = new EventEmitter();
  child.pid = 42420;
  child.exitCode = null;
  child.signalCode = null;
  child.stderr = new PassThrough();
  child.signals = [];
  let server;
  let port;
  let resolveListening;
  let rejectListening;
  const listening = new Promise((resolve, reject) => {
    resolveListening = resolve;
    rejectListening = reject;
  });
  const spawnProcess = (_executable, args) => {
    port = Number(args[args.indexOf("--port") + 1]);
    server = net.createServer();
    server.once("error", rejectListening);
    server.listen(port, "127.0.0.1", resolveListening);
    return child;
  };
  child.kill = (signal) => {
    child.signals.push(signal);
    if (signal === "SIGTERM" && ignoreTerm) return true;
    const finishExit = () => {
      child.exitCode = null;
      child.signalCode = signal;
      child.emit("exit", null, signal);
    };
    if (server.listening) server.close(finishExit);
    else finishExit();
    return true;
  };
  return {
    child,
    spawnProcess,
    port: () => port,
    waitReady: async () => { await listening; },
    async dispose() {
      if (!server?.listening) return;
      await new Promise((resolve, reject) => server.close((error) => error ? reject(error) : resolve()));
    },
  };
}

async function assertLoopbackPortCanBind(port) {
  const server = net.createServer();
  await new Promise((resolve, reject) => {
    server.once("error", reject);
    server.listen(port, "127.0.0.1", resolve);
  });
  await new Promise((resolve, reject) => server.close((error) => error ? reject(error) : resolve()));
}

test("readiness probe aborts a stalled local HTTP response at its overall deadline", { timeout: 4_000 }, async () => {
  let firstSocket;
  let resolveAccepted;
  let resolveRequest;
  const accepted = new Promise((resolve) => { resolveAccepted = resolve; });
  const requestReceived = new Promise((resolve) => { resolveRequest = resolve; });
  const server = net.createServer((socket) => {
    if (!firstSocket) {
      firstSocket = socket;
      resolveAccepted(socket);
      socket.once("data", (chunk) => resolveRequest(chunk.toString()));
    }
    socket.on("error", () => {});
  });
  await new Promise((resolve, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", resolve);
  });

  try {
    const address = server.address();
    const readiness = waitUntilReady("http://127.0.0.1:" + address.port, {
      exitObserved: false,
      spawnError: null,
      stderr: "",
    }, 500);
    await accepted;
    const request = await requestReceived;
    assert.match(request, /^GET \/api\/v1\/readiness HTTP\/1\.[01]/);
    await assert.rejects(readiness, /did not become ready/);
  } finally {
    firstSocket?.destroy();
    if (server.listening) {
      await new Promise((resolve, reject) => {
        server.close((error) => error ? reject(error) : resolve());
      });
    }
  }
});

test("fixture readiness failure waits for the child exit and releases its owned port", async () => {
  const fixture = ownedFixtureProcess({ ignoreTerm: true });
  try {
    let error;
    try {
      await startFixture(os.tmpdir(), {
        spawnProcess: fixture.spawnProcess,
        waitReady: async () => {
          await fixture.waitReady();
          throw new Error("synthetic readiness failure");
        },
        stopGraceMs: 0,
        stopKillMs: 1_000,
      });
    } catch (caught) {
      error = caught;
    }
    assert.ok(error instanceof Error, "startup failure must reject the fixture launch");
    assert.match(error.message, /synthetic readiness failure/);
    assert.ok(fixture.child.signalCode, "startup rejection must wait for the child exit event");
    assert.deepEqual(fixture.child.signals, ["SIGTERM", "SIGKILL"]);
    assert.match(error.message, /cleanup receipt/);
    assert.match(error.message, new RegExp(String(fixture.child.pid)));
    await assertLoopbackPortCanBind(fixture.port());
  } finally {
    await fixture.dispose();
  }
});

test("fixture stop escalates to SIGKILL and returns verified process and port cleanup", async () => {
  const fixtureProbe = ownedFixtureProcess({ ignoreTerm: true });
  try {
    const fixture = await startFixture(os.tmpdir(), {
      spawnProcess: fixtureProbe.spawnProcess,
      waitReady: fixtureProbe.waitReady,
      stopGraceMs: 0,
      stopKillMs: 1_000,
    });
    assert.equal(fixture.pid, fixtureProbe.child.pid);
    assert.equal(fixture.port, fixtureProbe.port());
    const cleanup = await fixture.stop();
    assert.deepEqual(fixtureProbe.child.signals, ["SIGTERM", "SIGKILL"]);
    assert.equal(cleanup.process_exit_verified, true);
    assert.equal(cleanup.loopback_port_released, true);
    assert.equal(cleanup.child_pid, fixtureProbe.child.pid);
    assert.equal(cleanup.loopback_port, fixtureProbe.port());
  } finally {
    await fixtureProbe.dispose();
  }
});

test("capture diagnostics retain browser console errors", async () => {
  const page = new EventEmitter();
  const context = { route: async () => {} };
  const checkDiagnostics = await observeLocalPage(context, "http://127.0.0.1:12345", page);
  page.emit("console", { type: () => "warning", text: () => "ignored warning" });
  page.emit("console", { type: () => "error", text: () => "synthetic console failure" });
  assert.throws(checkDiagnostics, /consoleErrors/);
  assert.throws(checkDiagnostics, /synthetic console failure/);
});

test("capture receipt is published only after verified child, port, and runtime cleanup", async () => {
  const outputDirectory = await mkdtemp(path.join(os.tmpdir(), "r120-capture-receipt-"));
  const runtimeDirectory = path.join(outputDirectory, "runtime");
  await mkdir(runtimeDirectory, { mode: 0o700 });
  const captures = capturesFixture();
  const manifest = buildCandidateManifest({ revision: REVISION, captures });
  const runReceipt = buildRunReceipt({
    revision: REVISION,
    dirty: true,
    sourceHashes: Object.fromEntries([
      ...CAPTURE_SOURCE_FILES.map((file) => [file, hash(file)]),
      ["src/stock_probs/static/next/index.html", hash("staged-index")],
    ]),
    captures,
    capturePresentation: capturePresentationFixture(),
  });
  const fixtureLifecycle = {
    child_pid: 42420,
    loopback_port: 43127,
    termination_signals: ["SIGTERM"],
    child_exit_code: null,
    child_exit_signal: "SIGTERM",
    process_exit_verified: true,
    loopback_port_released: true,
  };
  const runReceiptPath = path.join(outputDirectory, "assistant-help-capture-run.json");
  try {
    await assert.rejects(
      writeCaptureReceiptsAfterCleanup({ outputDirectory, runtimeDirectory, manifest, runReceipt, fixtureLifecycle }),
      /runtime directory to be removed/,
    );
    await assert.rejects(readFile(runReceiptPath), { code: "ENOENT" });

    await rm(runtimeDirectory, { recursive: true, force: true });
    const published = await writeCaptureReceiptsAfterCleanup({
      outputDirectory,
      runtimeDirectory,
      manifest,
      runReceipt,
      fixtureLifecycle,
    });
    const writtenReceipt = JSON.parse(await readFile(published.runReceiptPath, "utf8"));
    const writtenManifest = JSON.parse(await readFile(published.manifestPath, "utf8"));
    assert.equal(writtenReceipt.status, "builder-candidate");
    assert.deepEqual(writtenReceipt.fixture_lifecycle, { ...fixtureLifecycle, runtime_directory_removed: true });
    assert.equal(writtenManifest.captures.desktop_light.privacy_review, "pending");
  } finally {
    await rm(outputDirectory, { recursive: true, force: true });
  }
});

test("run candidate publishes capture receipts after fixture and runtime cleanup", async () => {
  const source = await readFile(new URL("../capture.mjs", import.meta.url), "utf8");
  const run = source.slice(source.indexOf("export async function runCaptureCandidate"));
  const cleanup = run.indexOf("removeAndVerifyDirectory(tempDirectory)");
  const finalHash = run.indexOf("const finalSourceHashes = await hashCaptureSources()");
  const publish = run.indexOf("await writeCaptureReceiptsAfterCleanup");
  assert.ok(cleanup >= 0 && finalHash > cleanup && publish > finalHash);
});
