// This fixture records application-data traffic so every journey can enforce the API-only boundary.
const base = require("@playwright/test");
const { spawn } = require("node:child_process");
const net = require("node:net");
const path = require("node:path");
const fs = require("node:fs/promises");

const root = path.resolve(__dirname, "../../..");

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
  const deadline = Date.now() + 10_000;
  while (Date.now() < deadline) {
    if (processState.exit !== null) {
      throw new Error(`${label} exited early (${processState.exit}): ${processState.stderr}`);
    }
    try {
      const response = await fetch(`${url}/api/v1/readiness`);
      if (response.ok) return;
    } catch (_) {
      // A refused connection is expected while the local process binds its loopback port.
    }
    await new Promise((resolve) => setTimeout(resolve, 50));
  }
  throw new Error(`${label} did not become ready: ${processState.stderr}`);
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

  async function start() {
    if (child) throw new Error(`${label} is already running.`);
    processState = { exit: null, stderr: "" };
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
    runningChild.stderr.on("data", (chunk) => {
      processState.stderr = `${processState.stderr}${chunk}`.slice(-16_384);
    });
    runningChild.once("exit", (code) => {
      processState.exit = code;
      if (child === runningChild) child = null;
    });
    await waitForReadiness(url, processState, label);
  }

  async function stop() {
    if (!child) return;
    const stoppingChild = child;
    const exited = new Promise((resolve) => stoppingChild.once("exit", resolve));
    stoppingChild.kill("SIGTERM");
    await Promise.race([exited, new Promise((resolve) => setTimeout(resolve, 5_000))]);
    if (stoppingChild.exitCode === null) {
      stoppingChild.kill("SIGKILL");
      await exited;
    }
    if (child === stoppingChild) child = null;
  }

  try {
    await start();
  } catch (startupError) {
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
    }
    throw startupError;
  }
  return { url, logs: () => processState.stderr, restart: async () => { await stop(); await start(); }, stop };
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
      await application.stop();
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
