import assert from "node:assert/strict";
import test from "node:test";

import {
  createCurrentHeadlinesClient,
  HeadlinesRequestError,
  headlineInstrumentsForSnapshot,
  projectCurrentNews,
} from "../components/briefing/headlines-client.mjs";

const asOf = "2026-10-15T13:00:00Z";

function newsItem(overrides = {}) {
  return {
    id: "story-1",
    title: "Company reports quarterly results",
    publisher: "Market Chronicle",
    url: "https://news.example.com/company-results",
    published_at: "2026-10-15T12:45:00Z",
    related_symbols: ["ACDC"],
    ...overrides,
  };
}

function newsResponse(overrides = {}) {
  const items = overrides.items ?? [newsItem()];
  const cacheState = overrides.cache_state ?? "miss";
  const partial = items.some((item) => item.publisher === null
    || item.published_at === null || item.related_symbols === null);
  return {
    query: { symbol: "ACDC", limit: 5 },
    provider: "Yahoo Finance",
    as_of: asOf,
    items,
    coverage: {
      returned_count: items.length,
      partial_metadata: partial,
      refresh_failed: cacheState === "stale_fallback",
    },
    cache_state: cacheState,
    ...overrides,
  };
}

test("closed current-news projection keeps partial metadata and stale fallback explicit", () => {
  const response = newsResponse({
    cache_state: "stale_fallback",
    items: [newsItem({ publisher: null, published_at: null, related_symbols: null })],
  });

  const projected = projectCurrentNews(response, "ACDC", 5);

  assert.equal(projected.cache_state, "stale_fallback");
  assert.equal(projected.coverage.refresh_failed, true);
  assert.equal(projected.coverage.partial_metadata, true);
  assert.equal(projected.items[0].publisher, null);
  assert.equal(projected.items[0].published_at, null);
  assert.equal(projected.items[0].related_symbols, null);
  assert.equal(Object.isFrozen(projected.items), true);
});

test("empty news remains a valid success and bounded ten-item payloads remain separate", () => {
  const empty = newsResponse({ items: [] });
  const emptyProjected = projectCurrentNews(empty, "ACDC", 5);
  assert.deepEqual(emptyProjected.items, []);
  assert.equal(emptyProjected.coverage.returned_count, 0);

  const tenItems = Array.from({ length: 10 }, (_, index) => newsItem({ id: "story-" + index }));
  const ten = newsResponse({
    query: { symbol: "ACDC", limit: 10 },
    items: tenItems,
    coverage: { returned_count: 10, partial_metadata: false, refresh_failed: false },
  });
  assert.equal(projectCurrentNews(ten, "ACDC", 10).items.length, 10);
});

test("current-news projection rejects open, mismatched, inconsistent, and unsafe contracts", () => {
  const malformed = [
    { ...newsResponse(), extra: true },
    { ...newsResponse(), query: { symbol: "SPY", limit: 5 } },
    { ...newsResponse(), coverage: { returned_count: 2, partial_metadata: false, refresh_failed: false } },
    { ...newsResponse(), coverage: { returned_count: 1, partial_metadata: false, refresh_failed: true } },
    { ...newsResponse(), items: [newsItem({ url: "javascript:alert(1)" })] },
    { ...newsResponse(), items: [newsItem({ url: "https://user:pass@news.example.com/story" })] },
    { ...newsResponse(), items: [newsItem({ url: "http://news.example.com/story" })] },
    { ...newsResponse(), items: [newsItem({ url: "https://127.0.0.1/story" })] },
    { ...newsResponse(), items: [newsItem({ title: "Unsafe\u202e headline" })] },
    { ...newsResponse(), items: [newsItem({ publisher: "x".repeat(201) })] },
  ];
  for (const value of malformed) {
    assert.throws(() => projectCurrentNews(value, "ACDC", 5), (error) => {
      assert.ok(error instanceof HeadlinesRequestError);
      assert.equal(error.kind, "malformed");
      return true;
    });
  }
  assert.throws(() => projectCurrentNews(newsResponse(), "ACDC", 10), /current headlines request/i);
});

test("news requests use only the authenticated local API path and pass cancellation through", async () => {
  const calls = [];
  const controller = new AbortController();
  const client = createCurrentHeadlinesClient(async (path, options) => {
    calls.push({ path, options });
    const responseBody = path.endsWith("limit=10")
      ? newsResponse({ query: { symbol: "ACDC", limit: 10 } })
      : newsResponse();
    return new Response(JSON.stringify(responseBody), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  });

  const data = await client.getCurrent({ symbol: "ACDC", limit: 5, signal: controller.signal });
  const expanded = await client.getCurrent({ symbol: "ACDC", limit: 10, signal: controller.signal });

  assert.equal(data.query.symbol, "ACDC");
  assert.equal(expanded.query.limit, 10);
  assert.equal(calls.length, 2);
  assert.equal(calls[0].path, "/api/v1/news?symbol=ACDC&limit=5");
  assert.equal(calls[1].path, "/api/v1/news?symbol=ACDC&limit=10");
  assert.equal(calls[0].options.method, "GET");
  assert.equal(calls[0].options.cache, "no-store");
  assert.equal(calls[0].options.signal, controller.signal);
  assert.equal(new URL(calls[0].path, "https://app.example").origin, "https://app.example");
});

test("news request maps provider, capacity, session, service, and network failures distinctly", async () => {
  for (const [status, kind] of [[502, "provider_unavailable"], [503, "provider_busy"], [401, "authorization"], [403, "authorization"]]) {
    const client = createCurrentHeadlinesClient(async () => new Response("ignored", { status }));
    await assert.rejects(client.getCurrent({ symbol: "ACDC" }), (error) => {
      assert.ok(error instanceof HeadlinesRequestError);
      assert.equal(error.kind, kind);
      assert.equal(error.status, status);
      return true;
    });
  }
  const rejected = createCurrentHeadlinesClient(async () => new Response("ignored", { status: 429 }));
  await assert.rejects(rejected.getCurrent({ symbol: "ACDC" }), (error) => error.kind === "rejected");
  const offline = createCurrentHeadlinesClient(async () => { throw new TypeError("offline"); });
  await assert.rejects(offline.getCurrent({ symbol: "ACDC" }), (error) => error.kind === "unreachable");
});

test("invalid instruments are rejected before any local news request", async () => {
  let calls = 0;
  const client = createCurrentHeadlinesClient(async () => { calls += 1; return new Response("{}", { status: 200 }); });
  await assert.rejects(client.getCurrent({ symbol: "acdc" }), (error) => error.kind === "malformed");
  await assert.rejects(client.getCurrent({ symbol: "ACDC", limit: 11 }), (error) => error.kind === "malformed");
  assert.equal(calls, 0);
});

test("an aborted current-news request preserves cancellation instead of showing a service failure", async () => {
  const controller = new AbortController();
  const client = createCurrentHeadlinesClient((_path, options) => new Promise((_resolve, reject) => {
    options.signal.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError")), { once: true });
  }));
  const pending = client.getCurrent({ symbol: "ACDC", signal: controller.signal });
  controller.abort();
  await assert.rejects(pending, (error) => error.name === "AbortError");
});

test("instrument choices come only from saved price movements and alerts", () => {
  const choices = headlineInstrumentsForSnapshot({
    price_changes: [{ symbol: "ACDC" }, { symbol: "SHOP.TO" }, { symbol: "ACDC" }, { symbol: "bad symbol" }],
    triggered_alerts: [{ symbol: "SPY" }, { symbol: "ACDC" }],
    outcome_changes: [{ symbol: "FORECAST-ONLY" }],
  });

  assert.deepEqual(choices, [
    { symbol: "ACDC", label: "ACDC — saved price move and saved alert" },
    { symbol: "SHOP.TO", label: "SHOP.TO — saved price move" },
    { symbol: "SPY", label: "SPY — saved alert" },
  ]);
  assert.deepEqual(headlineInstrumentsForSnapshot(null), []);
});

test("news response bodies are rejected above the contract size ceiling", async () => {
  const body = "{" + " ".repeat(257 * 1024);
  const client = createCurrentHeadlinesClient(async () => new Response(body, { status: 200 }));
  await assert.rejects(client.getCurrent({ symbol: "ACDC" }), (error) => error.kind === "malformed");
});
