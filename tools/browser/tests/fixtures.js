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

async function launchApplication(testInfo, runtimeName, pythonArguments, label) {
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

  await start();
  return { url, restart: async () => { await stop(); await start(); }, stop };
}

exports.expect = base.expect;
exports.test = base.test.extend({
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
});
