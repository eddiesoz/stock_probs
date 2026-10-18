// This fixture records application-data traffic so every journey can enforce the API-only boundary.
const base = require("@playwright/test");
const { spawn } = require("node:child_process");
const net = require("node:net");
const path = require("node:path");
const fs = require("node:fs/promises");

const root = path.resolve(__dirname, "../../..");
const READINESS_TIMEOUT_MS = 30_000;
const READINESS_REQUEST_TIMEOUT_MS = 1_000;

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

async function waitForReadiness(url, processState, label) {
  const deadline = Date.now() + READINESS_TIMEOUT_MS;
  while (Date.now() < deadline) {
    if (processState.exit !== null) {
      throw new Error(`${label} exited early (${processState.exit}): ${processState.stderr}`);
    }
    try {
      const requestTimeoutMs = Math.max(1, Math.min(READINESS_REQUEST_TIMEOUT_MS, deadline - Date.now()));
      const response = await fetch(`${url}/api/v1/readiness`, {
        signal: AbortSignal.timeout(requestTimeoutMs),
      });
      if (response.ok && processState.exit === null && Date.now() < deadline) return;
    } catch (_) {
      // A refused connection is expected while the local process binds its loopback port.
    }
    if (processState.exit !== null) {
      throw new Error(`${label} exited early (${processState.exit}): ${processState.stderr}`);
    }
    const remainingMs = deadline - Date.now();
    if (remainingMs > 0) {
      await new Promise((resolve) => setTimeout(resolve, Math.min(50, remainingMs)));
    }
  }
  throw new Error(`${label} did not become ready: ${processState.stderr}`);
}

const ASSISTANT_FIXTURE_DIAGNOSTIC_EVENT_LIMIT = 32;
const ASSISTANT_FIXTURE_STAGE_NAMES = new Set([
  "fixture_started",
  "turn_started",
  "workspace_summary_received",
  "response_delay_started",
  "runtime_completed",
]);
const ASSISTANT_FIXTURE_SIGNALS = new Set(["SIGTERM", "SIGKILL", "SIGINT"]);

function createAssistantFixtureDiagnostics() {
  const startedAt = performance.now();
  const events = [];
  let overflow = false;
  let invalidEvent = false;
  let attachmentFailed = false;
  let pendingStderr = "";
  const add = (kind, details = {}) => {
    if (events.length >= ASSISTANT_FIXTURE_DIAGNOSTIC_EVENT_LIMIT) {
      overflow = true;
      return;
    }
    events.push({
      kind,
      at_utc: new Date().toISOString(),
      elapsed_monotonic_ms: Math.max(0, Math.round(performance.now() - startedAt)),
      ...details,
    });
  };
  const captureStderrChunk = (chunk) => {
    const lines = `${pendingStderr}${chunk.toString("utf8")}`.split(/\r?\n/);
    pendingStderr = lines.pop() || "";
    if (pendingStderr.length > 4_096) {
      pendingStderr = "";
      overflow = true;
    }
    for (const line of lines) {
      if (line.length > 4_096) {
        overflow = true;
        continue;
      }
      const normalizedLine = line.trimStart();
      if (!normalizedLine.startsWith("{") || !normalizedLine.includes('"qa_stage"')) continue;
      try {
        const parsed = JSON.parse(line);
        if (!Object.hasOwn(parsed, "qa_stage")) continue;
        const stage = parsed.qa_stage;
        if (typeof stage !== "string" || !ASSISTANT_FIXTURE_STAGE_NAMES.has(stage)) {
          invalidEvent = true;
          continue;
        }
        add("runtime_stage", { stage });
      } catch (_) {
        invalidEvent = true;
      }
    }
  };
  const markAttachmentFailed = () => {
    attachmentFailed = true;
    add("attachment_failed", { category: "attachment_unavailable" });
  };
  return {
    add,
    captureStderrChunk,
    markAttachmentFailed,
    snapshot: () => ({
      version: 1,
      result: overflow ? "failed_overflow" : invalidEvent ? "failed_invalid_event" : pendingStderr.length > 0 ? "incomplete_pending_line" : "captured",
      overflow,
      invalid_event: invalidEvent,
      attachment_failed: attachmentFailed,
      pending_line: pendingStderr.length > 0,
      events: events.map((event) => ({ ...event })),
    }),
  };
}

async function attachAssistantFixtureDiagnosticSnapshot(testInfo, name, snapshot, markFailure) {
  if (snapshot === null || snapshot === undefined) return;
  try {
    await testInfo.attach(name, {
      body: Buffer.from(JSON.stringify(snapshot)),
      contentType: "application/json",
    });
  } catch (_) {
    try {
      markFailure?.();
    } catch (_) {
      // Preserve the original startup, test, or teardown result if diagnostics cannot be recorded.
    }
  }
}

async function launchApplication(testInfo, runtimeName, pythonArguments, label, environment = {}) {
  const port = await freeLoopbackPort();
  const url = `http://127.0.0.1:${port}`;
  const runtime = testInfo.outputPath(runtimeName);
  // Runtime removal belongs outside start() because restart regressions intentionally retain it.
  await fs.rm(runtime, { recursive: true, force: true });
  await fs.mkdir(runtime, { recursive: true });
  let child = null;
  let processState = null;
  const diagnostics = runtimeName === "assistant-runtime" ? createAssistantFixtureDiagnostics() : null;

  async function start() {
    if (child) throw new Error(`${label} is already running.`);
    processState = { exit: null, signal: null, stderr: "" };
    child = spawn(path.join(root, ".dev-venv/bin/python"), pythonArguments(port), {
      cwd: root,
      env: {
        ...process.env,
        STOCK_PROBS_DATA_DIR: runtime,
        STOCK_PROBS_PROVIDER: "fixture",
        STOCK_PROBS_FIXTURE_NOW: "2025-01-10T17:03:00+00:00",
        STOCK_PROBS_PORT: String(port),
        ...environment,
      },
      stdio: ["ignore", "ignore", "pipe"],
    });
    const runningChild = child;
    runningChild.once("spawn", () => diagnostics?.add("child_started"));
    runningChild.stderr.on("data", (chunk) => {
      processState.stderr = `${processState.stderr}${chunk}`.slice(-16_384);
      diagnostics?.captureStderrChunk(chunk);
    });
    runningChild.once("exit", (code, signal) => {
      processState.exit = code;
      processState.signal = signal;
      diagnostics?.add("child_exit", {
        exit_code: Number.isInteger(code) ? code : null,
        signal: signal === null ? null : ASSISTANT_FIXTURE_SIGNALS.has(signal) ? signal : "other",
      });
      if (child === runningChild) child = null;
    });
    await waitForReadiness(url, processState, label);
    diagnostics?.add("readiness_succeeded");
  }

  async function stop() {
    const childRunningAtStop = child !== null;
    diagnostics?.add("owned_stop_started", {
      child_running: childRunningAtStop,
      requested_signal: "SIGTERM",
    });
    if (!child) {
      diagnostics?.add("owned_stop_finished", { child_running: false, sigkill_attempted: false });
      return;
    }
    const stoppingChild = child;
    const exited = new Promise((resolve) => stoppingChild.once("exit", resolve));
    stoppingChild.kill("SIGTERM");
    await Promise.race([exited, new Promise((resolve) => setTimeout(resolve, 5_000))]);
    let sigkillAttempted = false;
    if (stoppingChild.exitCode === null) {
      sigkillAttempted = true;
      stoppingChild.kill("SIGKILL");
      await exited;
    }
    if (child === stoppingChild) child = null;
    diagnostics?.add("owned_stop_finished", { child_running: child !== null, sigkill_attempted: sigkillAttempted });
  }

  try {
    await start();
  } catch (startupError) {
    diagnostics?.add("startup_failed", {
      category: processState?.exit !== null || processState?.signal !== null
        ? "process_exited_before_readiness"
        : "startup_not_ready",
    });
    const beforeStop = diagnostics?.snapshot();
    try {
      await stop();
    } catch (_) {
      if (startupError && typeof startupError === "object") {
        try {
          Object.defineProperty(startupError, "cleanupError", {
            configurable: true,
            value: "application_process_cleanup_failed",
          });
        } catch (_) {
          // Preserve the original startup error even if it cannot be annotated.
        }
      }
      diagnostics?.add("owned_stop_failed");
    }
    if (diagnostics) {
      await attachAssistantFixtureDiagnosticSnapshot(
        testInfo,
        "assistant-fixture-startup-before-stop.json",
        beforeStop,
        () => diagnostics.markAttachmentFailed(),
      );
      await attachAssistantFixtureDiagnosticSnapshot(
        testInfo,
        "assistant-fixture-startup-after-stop.json",
        diagnostics.snapshot(),
        () => diagnostics.markAttachmentFailed(),
      );
    }
    throw startupError;
  }
  return {
    url,
    logs: () => processState.stderr,
    diagnostics: () => diagnostics?.snapshot() ?? null,
    markDiagnosticAttachmentFailed: () => diagnostics?.markAttachmentFailed(),
    restart: async () => { await stop(); await start(); },
    stop,
  };
}

exports.expect = base.expect;
exports.test = base.test.extend({
  browserDiagnostics: [async ({ page }, use) => {
    const consoleErrors = [];
    const pageErrors = [];
    const failedResponses = [];
    const failedRequests = [];
    const expectedHttpFailures = [];
    const expectedRequestAborts = [];
    const finiteAssistantStreams = [];
    const assistantStreamNetworkEvents = [];
    page.on("console", (message) => {
      if (message.type() === "error") {
        consoleErrors.push({ text: message.text(), location: message.location() });
      }
    });
    page.on("pageerror", (error) => pageErrors.push(error.message));
    page.on("response", (response) => {
      if (response.status() >= 400) {
        failedResponses.push({
          method: response.request().method(),
          path: new URL(response.url()).pathname,
          status: response.status(),
          url: response.url(),
        });
      }
      const url = new URL(response.url());
      if (response.request().method() === "GET" && /^\/api\/v1\/assistant\/conversations\/[^/]+\/turns\/[^/]+\/events$/.test(url.pathname)) {
        assistantStreamNetworkEvents.push({
          kind: "response",
          method: response.request().method(),
          path: url.pathname,
          url: response.url(),
          status: response.status(),
          contentType: response.headers()["content-type"] || null,
        });
      }
    });
    page.on("request", (request) => {
      const url = new URL(request.url());
      if (request.method() === "GET" && /^\/api\/v1\/assistant\/conversations\/[^/]+\/turns\/[^/]+\/events$/.test(url.pathname)) {
        assistantStreamNetworkEvents.push({
          kind: "request",
          method: request.method(),
          path: url.pathname,
          url: request.url(),
        });
      }
    });
    page.on("requestfinished", (request) => {
      const url = new URL(request.url());
      if (request.method() === "GET" && /^\/api\/v1\/assistant\/conversations\/[^/]+\/turns\/[^/]+\/events$/.test(url.pathname)) {
        assistantStreamNetworkEvents.push({
          kind: "finished",
          method: request.method(),
          path: url.pathname,
          url: request.url(),
        });
      }
    });
    page.on("requestfailed", (request) => {
      const url = new URL(request.url());
      if (request.method() === "GET" && /^\/api\/v1\/assistant\/conversations\/[^/]+\/turns\/[^/]+\/events$/.test(url.pathname)) {
        assistantStreamNetworkEvents.push({
          kind: "failed",
          method: request.method(),
          path: url.pathname,
          url: request.url(),
          error: request.failure()?.errorText || "unknown request failure",
        });
      }
      failedRequests.push({
        method: request.method(),
        path: url.pathname,
        error: request.failure()?.errorText || "unknown request failure",
      });
    });

    const expand = (items) => items.flatMap(({ count = 1, ...item }) => (
      Array.from({ length: count }, () => item)
    ));
    const diagnosticKey = ({ method, path, status, error }) => (
      `${method} ${path} ${status ?? error}`
    );
    try {
      await use({
        expectHttpFailures: (...items) => expectedHttpFailures.push(...items),
        expectRequestAborts: (...items) => expectedRequestAborts.push(...items),
        expectCompletedAssistantEventStream: ({ path }) => {
          if (typeof path !== "string" || !/^\/api\/v1\/assistant\/conversations\/[^/]+\/turns\/[^/]+\/events$/.test(path)) {
            throw new Error("Only an exact assistant turn-event path can use the finite-stream classification.");
          }
          if (finiteAssistantStreams.includes(path)) {
            throw new Error("A finite assistant stream path was classified more than once.");
          }
          finiteAssistantStreams.push(path);
        },
      });
    } finally {
      // Let Chromium deliver the resource console event paired with the final HTTP response.
      await new Promise((resolve) => setTimeout(resolve, 25));
      const expectedHttp = expand(expectedHttpFailures).sort((a, b) => diagnosticKey(a).localeCompare(diagnosticKey(b)));
      const actualHttp = failedResponses
        .map(({ url, ...failure }) => failure)
        .sort((a, b) => diagnosticKey(a).localeCompare(diagnosticKey(b)));
      base.expect(actualHttp, "unexpected or missing browser HTTP failure response").toEqual(expectedHttp);

      const httpResourcePattern = /^Failed to load resource: the server responded with a status of (\d{3})(?: \([^)]*\))?$/;
      const resourceErrors = [];
      const unexpectedConsoleErrors = [];
      for (const message of consoleErrors) {
        const match = message.text.match(httpResourcePattern);
        const response = match && failedResponses.find((failure) => (
          failure.status === Number(match[1]) && failure.url === message.location.url
        ));
        if (response) {
          resourceErrors.push({ method: response.method, path: response.path, status: response.status });
        } else {
          unexpectedConsoleErrors.push(message);
        }
      }
      resourceErrors.sort((a, b) => diagnosticKey(a).localeCompare(diagnosticKey(b)));
      base.expect(
        resourceErrors,
        "HTTP resource console errors must exactly match deliberate failure journeys",
      ).toEqual(expectedHttp);
      base.expect(unexpectedConsoleErrors, "uncaught JS, CSP, or unexpected console errors").toEqual([]);
      base.expect(pageErrors, "uncaught page errors").toEqual([]);

      const finiteStreamAborts = [];
      for (const path of finiteAssistantStreams) {
        const requests = assistantStreamNetworkEvents.filter((item) => item.kind === "request" && item.path === path);
        const responses = assistantStreamNetworkEvents.filter((item) => item.kind === "response" && item.path === path);
        const finished = assistantStreamNetworkEvents.filter((item) => item.kind === "finished" && item.path === path);
        const failed = assistantStreamNetworkEvents.filter((item) => item.kind === "failed" && item.path === path);
        base.expect(requests, `expected one finite assistant stream request for ${path}`).toHaveLength(1);
        base.expect(responses, `expected one HTTP response for ${path}`).toHaveLength(1);
        base.expect(responses[0]).toMatchObject({ status: 200 });
        base.expect(responses[0].contentType || "").toMatch(/^text\/event-stream(?:;|$)/);
        base.expect(finished.length + failed.length, `expected exactly one terminal browser outcome for ${path}`).toBe(1);
        if (failed.length === 1) {
          base.expect(failed[0].error, `unexpected finite-stream failure for ${path}`).toBe("net::ERR_ABORTED");
          finiteStreamAborts.push({ method: "GET", path, error: "net::ERR_ABORTED" });
        }
      }

      const expectedAborts = [...expand(expectedRequestAborts), ...finiteStreamAborts]
        .map((item) => ({ ...item, error: "net::ERR_ABORTED" }))
        .sort((a, b) => diagnosticKey(a).localeCompare(diagnosticKey(b)));
      failedRequests.sort((a, b) => diagnosticKey(a).localeCompare(diagnosticKey(b)));
      base.expect(failedRequests, "unexpected browser network request failures").toEqual(expectedAborts);
    }
  }, { auto: true }],
  applicationRequests: async ({ page }, use) => {
    const requests = [];
    page.on("request", (request) => {
      if (["fetch", "xhr"].includes(request.resourceType())) requests.push(request.url());
    });
    await use(requests);
  },
  restartableApplication: async ({}, use, testInfo) => {
    const application = await launchApplication(
      testInfo,
      "restart-runtime",
      (port) => ["-m", "stock_probs.cli", "serve", "--host", "127.0.0.1", "--port", String(port)],
      "Restart test application",
    );
    try {
      await use({ url: application.url, restart: application.restart });
    } finally {
      await application.stop();
    }
  },
  assistantApplication: async ({}, use, testInfo) => {
    const application = await launchApplication(
      testInfo,
      "assistant-runtime",
      (port) => [path.join(root, "tools/browser/assistant_qa_server.py"), "--port", String(port)],
      "Assistant FastAPI browser fixture",
    );
    try {
      await use({ url: application.url, logs: application.logs });
    } finally {
      try {
        await attachAssistantFixtureDiagnosticSnapshot(
          testInfo,
          "assistant-fixture-before-stop.json",
          application.diagnostics(),
          application.markDiagnosticAttachmentFailed,
        );
      } finally {
        try {
          await application.stop();
        } finally {
          await attachAssistantFixtureDiagnosticSnapshot(
            testInfo,
            "assistant-fixture-after-stop.json",
            application.diagnostics(),
            application.markDiagnosticAttachmentFailed,
          );
        }
      }
    }
  },
  unexpectedFailureApplication: async ({}, use, testInfo) => {
    const application = await launchApplication(
      testInfo,
      "unexpected-failure-runtime",
      () => [path.join(root, "tools/browser/unexpected_failure_app.py")],
      "Unexpected-failure test application",
    );
    try {
      await use({ url: application.url });
    } finally {
      await application.stop();
    }
  },
  outOfSessionApplication: async ({}, use, testInfo) => {
    const application = await launchApplication(
      testInfo,
      "out-of-session-runtime",
      (port) => ["-m", "stock_probs.cli", "serve", "--host", "127.0.0.1", "--port", String(port)],
      "Out-of-session test application",
      { STOCK_PROBS_FIXTURE_NOW: "2025-01-10T22:03:00+00:00" },
    );
    try {
      await use({ url: application.url });
    } finally {
      await application.stop();
    }
  },
});
