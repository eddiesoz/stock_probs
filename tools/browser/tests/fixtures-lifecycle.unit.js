"use strict";

const assert = require("node:assert/strict");
const { EventEmitter } = require("node:events");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const fixturePath = path.join(__dirname, "fixtures.js");
const fixtureSource = fs.readFileSync(fixturePath, "utf8");

function loadLaunchApplication(options = {}) {
  let now = 0;
  let spawnCount = 0;
  const children = [];
  const timerDelays = [];
  const filesystemCalls = [];
  const readinessCalls = [];
  const readinessTimeouts = [];
  const fetchAborts = [];
  const lifecycleRecords = [];
  const spawnError = options.spawnError || null;

  class FakeChild extends EventEmitter {
    constructor(childOptions) {
      super();
      this.options = childOptions;
      this.pid = 50_000 + spawnCount;
      this.stderr = new EventEmitter();
      this.exitCode = null;
      this.killCalls = [];
    }

    finish(code) {
      this.exitCode = code;
      this.emit("exit", code, null);
    }

    kill(signal) {
      this.killCalls.push(signal);
      if (options.throwOnKill === signal) {
        throw new Error("fake stop error detail");
      }
      if (
        (signal === "SIGTERM" && options.exitOnTerm !== false)
        || (signal === "SIGKILL" && options.exitOnKill === true)
      ) {
        queueMicrotask(() => this.finish(0));
      }
      return true;
    }
  }

  const fakeSpawn = (...args) => {
    spawnCount += 1;
    if (spawnError) throw spawnError;
    const child = new FakeChild(args[2]);
    children.push(child);
    if (options.exitCodeBeforeReady !== undefined && spawnCount === 1) {
      queueMicrotask(() => child.finish(options.exitCodeBeforeReady));
    }
    return child;
  };

  const fakeNet = {
    createServer() {
      return {
        once() { return this; },
        listen(_port, _host, callback) { callback(); },
        address() { return { port: 45678 }; },
        close(callback) { callback(null); },
      };
    },
  };
  const fakePath = {
    resolve() { return "/repo"; },
    join(...parts) { return parts.join("/"); },
  };
  const fakeFs = {
    async rm(...args) { filesystemCalls.push(["rm", ...args]); },
    async mkdir(...args) { filesystemCalls.push(["mkdir", ...args]); },
  };
  const fakeBase = {
    expect() {},
    test: { extend(fixtures) { return fixtures; } },
  };
  const moduleExports = {};
  const context = {
    __dirname: "/repo/tools/browser/tests",
    exports: moduleExports,
    process: { env: { BASE_ENV: "preserved" } },
    require(moduleName) {
      const modules = {
        "@playwright/test": fakeBase,
        "node:child_process": { spawn: fakeSpawn },
        "node:net": fakeNet,
        "node:path": fakePath,
        "node:fs/promises": fakeFs,
      };
      if (!(moduleName in modules)) throw new Error(`unexpected module: ${moduleName}`);
      return modules[moduleName];
    },
    Date: class extends Date {
      static now() { return now; }
    },
    AbortSignal: {
      timeout(timeoutMs) {
        readinessTimeouts.push(timeoutMs);
        const abortListeners = [];
        return {
          timeoutMs,
          addEventListener(eventName, callback) {
            if (eventName === "abort") abortListeners.push(callback);
          },
          expire() {
            for (const callback of abortListeners) callback();
          },
        };
      },
    },
    fetch: async (url, requestOptions = {}) => {
      readinessCalls.push(url);
      if (options.stallFirstFetch && readinessCalls.length === 1) {
        return new Promise((_resolve, reject) => {
          requestOptions.signal.addEventListener("abort", () => {
            fetchAborts.push(requestOptions.signal.timeoutMs);
            reject(new Error("readiness request timed out"));
          });
          queueMicrotask(() => {
            now += requestOptions.signal.timeoutMs;
            requestOptions.signal.expire();
          });
        });
      }
      if (options.fetchError) throw new Error("fixture fetch unavailable");
      const ready = options.readyAfterMs === undefined
        ? options.ready !== false
        : now >= options.readyAfterMs;
      return { ok: ready };
    },
    setTimeout(callback, delay) {
      timerDelays.push(delay);
      if (delay === 50) {
        now += delay;
        queueMicrotask(callback);
      } else if (delay === 5000 && options.expireStopTimer) {
        now += delay;
        queueMicrotask(callback);
      }
      return { unref() {} };
    },
    clearTimeout() {},
    queueMicrotask,
    console: { log(value) { lifecycleRecords.push(JSON.parse(value)); } },
  };
  const testOnlySource = `${fixtureSource}\nexports.__launchApplicationForUnitTest = launchApplication;\n`;
  vm.runInNewContext(testOnlySource, context, { filename: fixturePath });

  return {
    launch: (name = "fixture-runtime") => moduleExports.__launchApplicationForUnitTest(
      { outputPath: (runtimeName) => `/private/${runtimeName}` },
      name,
      (port) => ["-m", "fake.server", "--port", String(port)],
      "Fixture application",
    ),
    children,
    filesystemCalls,
    readinessCalls,
    readinessTimeouts,
    fetchAborts,
    timerDelays,
    lifecycleRecords,
    get now() { return now; },
  };
}

test("initial child exit preserves its error without waiting through the readiness budget", async () => {
  const harness = loadLaunchApplication({ exitCodeBeforeReady: 7, fetchError: true });
  await assert.rejects(harness.launch(), /Fixture application exited early \(7\):/);
  assert.equal(harness.children.length, 1);
  assert.deepEqual(harness.children[0].killCalls, []);
  assert.equal(harness.readinessCalls.length, 1);
  assert.equal(harness.now, 0);
  assert.deepEqual(harness.filesystemCalls.map(([kind]) => kind), ["rm", "mkdir"]);
});

test("readiness may complete after the old ten-second watchdog window", async () => {
  const harness = loadLaunchApplication({ readyAfterMs: 12_000 });
  const application = await harness.launch("slow-start-runtime");
  assert.equal(application.url, "http://127.0.0.1:45678");
  assert.ok(harness.now > 10_000 && harness.now < 30_000);
  await application.stop();
});

test("a stalled readiness request is aborted within one second before retrying", async () => {
  const harness = loadLaunchApplication({ stallFirstFetch: true });
  const application = await harness.launch("stalled-readiness-runtime");
  assert.equal(harness.fetchAborts.length, 1);
  assert.ok(harness.fetchAborts[0] > 0 && harness.fetchAborts[0] <= 1_000);
  assert.ok(harness.readinessTimeouts.every((timeoutMs) => timeoutMs > 0 && timeoutMs <= 1_000));
  assert.ok(harness.readinessCalls.length >= 2);
  await application.stop();
});

test("readiness timeout awaits SIGTERM cleanup at the shared thirty-second budget", async () => {
  const harness = loadLaunchApplication({ ready: false });
  await assert.rejects(harness.launch(), /Fixture application did not become ready:/);
  assert.equal(harness.now, 30_000);
  assert.ok(harness.readinessCalls.length > 200);
  assert.ok(harness.readinessTimeouts.every((timeoutMs) => timeoutMs > 0 && timeoutMs <= 1_000));
  assert.ok(harness.timerDelays.includes(5000));
  assert.deepEqual(harness.children[0].killCalls, ["SIGTERM"]);
  assert.equal(harness.children[0].exitCode, 0);
});

test("cleanup failure is sanitized without replacing the original readiness error", async () => {
  const harness = loadLaunchApplication({ ready: false, exitOnTerm: false, expireStopTimer: true, throwOnKill: "SIGKILL" });
  let thrown;
  try {
    await harness.launch();
  } catch (error) {
    thrown = error;
  }
  assert.equal(typeof thrown.message, "string");
  assert.equal(thrown.message, "Fixture application did not become ready: ");
  assert.equal(thrown.cleanupError, "application_process_cleanup_failed");
  assert.deepEqual(harness.children[0].killCalls, ["SIGTERM", "SIGKILL"]);
  assert.equal(thrown.message.includes("fake stop error detail"), false);
});

test("successful startup and teardown retain the public application contract", async () => {
  const harness = loadLaunchApplication();
  const application = await harness.launch("success-runtime");
  assert.equal(application.url, "http://127.0.0.1:45678");
  assert.equal(application.logs(), "");
  await application.stop();
  assert.deepEqual(harness.children[0].killCalls, ["SIGTERM"]);
  assert.deepEqual(harness.filesystemCalls.map(([kind]) => kind), ["rm", "mkdir"]);
  assert.equal(harness.children[0].options.env.STOCK_PROBS_DATA_DIR, "/private/success-runtime");
});

test("successful restart preserves runtime data and only replaces the child", async () => {
  const harness = loadLaunchApplication();
  const application = await harness.launch("restart-runtime");
  await application.restart();
  assert.equal(harness.children.length, 2);
  assert.deepEqual(harness.children[0].killCalls, ["SIGTERM"]);
  assert.equal(harness.children[1].killCalls.length, 0);
  assert.deepEqual(harness.filesystemCalls.map(([kind]) => kind), ["rm", "mkdir"]);
  assert.equal(harness.children[1].options.env.STOCK_PROBS_DATA_DIR, "/private/restart-runtime");
  await application.stop();
  assert.deepEqual(harness.children[1].killCalls, ["SIGTERM"]);
});

test("actual fixture identities survive startup, restart, and teardown in bounded lifecycle records", async () => {
  const harness = loadLaunchApplication();
  const application = await harness.launch("restart-runtime");
  await application.restart();
  await application.stop();
  assert.deepEqual(harness.lifecycleRecords, [
    { qa_fixture_lifecycle: "started", runtime: "restart-runtime", port: 45678, pid: 50001 },
    { qa_fixture_lifecycle: "exited", runtime: "restart-runtime", port: 45678, pid: 50001, code: 0, signal: null },
    { qa_fixture_lifecycle: "started", runtime: "restart-runtime", port: 45678, pid: 50002 },
    { qa_fixture_lifecycle: "exited", runtime: "restart-runtime", port: 45678, pid: 50002, code: 0, signal: null },
  ]);
});

test("an early fixture exit records its exact allocated identity before readiness failure", async () => {
  const harness = loadLaunchApplication({ exitCodeBeforeReady: 7, fetchError: true });
  await assert.rejects(harness.launch("early-exit-runtime"), /exited early \(7\)/);
  assert.deepEqual(harness.lifecycleRecords, [
    { qa_fixture_lifecycle: "started", runtime: "early-exit-runtime", port: 45678, pid: 50001 },
    { qa_fixture_lifecycle: "exited", runtime: "early-exit-runtime", port: 45678, pid: 50001, code: 7, signal: null },
  ]);
});

test("synchronous spawn throws retain identity when no child was created", async () => {
  const spawnError = new Error("spawn failed");
  const harness = loadLaunchApplication({ spawnError });
  let thrown;
  try {
    await harness.launch();
  } catch (error) {
    thrown = error;
  }
  assert.strictEqual(thrown, spawnError);
  assert.equal(harness.children.length, 0);
  assert.deepEqual(harness.filesystemCalls.map(([kind]) => kind), ["rm", "mkdir"]);
});


test("SIGKILL fallback awaits exit after the five-second TERM grace period", async () => {
  const harness = loadLaunchApplication({
    exitOnTerm: false,
    exitOnKill: true,
    expireStopTimer: true,
  });
  const application = await harness.launch("kill-fallback-runtime");
  await application.stop();
  assert.deepEqual(harness.children[0].killCalls, ["SIGTERM", "SIGKILL"]);
  assert.equal(harness.children[0].exitCode, 0);
  assert.equal(harness.now, 5000);
  await application.stop();
  assert.deepEqual(harness.children[0].killCalls, ["SIGTERM", "SIGKILL"]);
});
