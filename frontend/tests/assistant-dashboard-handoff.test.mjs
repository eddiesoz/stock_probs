import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const appJs = await readFile(new URL("../../src/stock_probs/static/app.js", import.meta.url), "utf8");

test("assistant filter handoff hydrates only bounded fields consumed by the real dashboard history form", () => {
  assert.match(appJs, /function initializeAssistantHistoryFilters\(\)/);
  assert.match(appJs, /location\.hash !== "#history-heading"/);
  assert.match(appJs, /new Set\(\["q", "status", "asset_type", "analysis_kind", "submitted_from", "submitted_to", "model", "horizon", "sort", "page_size"\]\)/);
  assert.match(appJs, /entries\.some\(\(\[key\]\) => !allowed\.has\(key\)\)/);
  assert.match(appJs, /const formValues = \{ \.\.\.values, sort: values\.sort \|\| "event_id:desc", page_size: values\.page_size \|\| "10" \};/);
  assert.match(appJs, /values\.q\.length > 30/);
  assert.match(appJs, /\["successful", "repeated", "failed"\]/);
  assert.match(appJs, /\["stock", "etf"\]/);
  assert.match(appJs, /initializeAssistantHistoryFilters\(\);\s*await loadHistory\(\);/);
  assert.match(appJs, /for \(const name of \["q", "status", "asset_type", "analysis_kind", "model", "horizon"\]\)/);
  assert.match(appJs, /await api\(`\/history\?\$\{params\}`\)/);
});

test("confirmed forecast replay handoff uses the dashboard's existing event_id replay path", () => {
  assert.match(appJs, /const requestedEvent = new URLSearchParams\(window\.location\.search\)\.get\("event_id"\)/);
  assert.match(appJs, /await showHistoryEvent\(Number\(requestedEvent\)\)/);
  assert.match(appJs, /focusResultSection\(\)/);
});
