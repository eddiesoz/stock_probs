import assert from "node:assert/strict";
import test from "node:test";

import { apiPayload, delay, number, quoteBatches, quotePrice, snapshotState } from "./client-utils.ts";

test("apiPayload returns local JSON and preserves the API error message", async () => {
  assert.deepEqual(await apiPayload(new Response('{"items":["SPY"]}', { status: 200 }), "Fallback"), { items: ["SPY"] });
  await assert.rejects(
    apiPayload(new Response('{"error":{"message":"Provider unavailable"}}', { status: 503 }), "Fallback"),
    /Provider unavailable/,
  );
  assert.equal(number(Number.NaN), "Unavailable");
  assert.equal(quotePrice({ price: 101, last: 100 }), 101);
  assert.equal(quotePrice({ last: 100 }), 100);
  assert.equal(delay(undefined, undefined), "Delay unavailable");
  assert.equal(snapshotState("simulated"), "Simulated snapshot");
  assert.equal(snapshotState("delayed", true), "Delayed snapshot");
});

test("quoteBatches keeps up to 100 symbols in requests of at most 20", () => {
  const symbols = Array.from({ length: 101 }, (_, index) => `S${index}`);
  const batches = quoteBatches(symbols);
  assert.deepEqual(batches.map((batch) => batch.length), [20, 20, 20, 20, 20]);
  assert.deepEqual(batches.flat(), symbols.slice(0, 100));
});
