import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import vm from "node:vm";

test("news client distinguishes provider capacity from provider unavailability", async () => {
  const source = await readFile(
    new URL("../../src/stock_probs/static/app.js", import.meta.url),
    "utf8",
  );
  const start = source.indexOf("async function loadNews(");
  const end = source.indexOf("\nfunction newsDisclosure(", start);
  assert.ok(start >= 0 && end > start, "loadNews implementation should remain present");
  const implementation = source.slice(start, end);

  const unavailableMessage = "The headline provider is unavailable and no cached headlines exist.";
  const cases = [
    {
      name: "capacity busy 503",
      error: { status: 503, code: "provider_busy", message: "private text" },
      state: "busy",
      message: "Headline capacity is busy. Try again shortly.",
    },
    {
      name: "provider unavailable 503",
      error: { status: 503, code: "provider_unavailable", message: "private text" },
      state: "unavailable",
      message: unavailableMessage,
    },
    {
      name: "other 503 code",
      error: { status: 503, code: "other_error", message: "private text" },
      state: "unavailable",
      message: unavailableMessage,
    },
    {
      name: "provider unavailable 502",
      error: { status: 502, code: "provider_unavailable", message: "private text" },
      state: "unavailable",
      message: unavailableMessage,
    },
    {
      name: "local service unreachable",
      error: "TypeError",
      state: "unreachable",
      message: "The local service is unreachable. Start it and try again.",
    },
    {
      name: "request timeout",
      error: "AbortError",
      timedOut: true,
      state: "unreachable",
      message: "The headline request timed out. Check the local service and try again.",
    },
    {
      name: "superseded abort remains silent",
      error: "AbortError",
      superseded: true,
      state: null,
      message: null,
    },
  ];

  for (const scenario of cases) {
    let timeoutCallback;
    const retries = [];
    const states = [];
    const context = {
      AbortController,
      TypeError,
      URLSearchParams,
      newsTimeoutMs: 30000,
      clearTimeout: (handle) => assert.equal(handle, 7),
      setTimeout: (callback) => {
        timeoutCallback = callback;
        return 7;
      },
      supersedeNews: () => {},
      setNewsState: (_content, state) => states.push(state),
      setNewsRetryState: (_content, state, message, symbol, limit) => {
        retries.push({ state, message, symbol, limit });
      },
      renderNews: () => assert.fail("failed request must not render headlines"),
      newsRequest: null,
      api: async (path, options) => {
        assert.equal(path, "/news?symbol=SPY&limit=5");
        assert.ok(options.signal);
        if (scenario.timedOut) timeoutCallback();
        if (scenario.superseded) context.newsRequest = null;
        if (scenario.error === "TypeError") {
          throw new context.TypeError("connection failed");
        }
        if (scenario.error === "AbortError") {
          const error = new Error("request was aborted");
          error.name = "AbortError";
          throw error;
        }
        throw Object.assign(new Error(scenario.error.message), {
          status: scenario.error.status,
          code: scenario.error.code,
        });
      },
    };
    vm.runInNewContext(`${implementation}\nglobalThis.invokeLoadNews = loadNews;`, context, {
      timeout: 1000,
    });
    await context.invokeLoadNews({}, "SPY", 5);

    assert.deepEqual(states, ["loading"], scenario.name);
    if (scenario.state === null) {
      assert.deepEqual(retries, [], scenario.name);
      continue;
    }
    assert.deepEqual(
      retries,
      [{ state: scenario.state, message: scenario.message, symbol: "SPY", limit: 5 }],
      scenario.name,
    );
  }
});
