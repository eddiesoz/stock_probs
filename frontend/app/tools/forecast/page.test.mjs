import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

test("forecast tool exports an explicit, non-automatic interval form", async () => {
  const source = await readFile(new URL("workspace.tsx", import.meta.url), "utf8");

  for (const label of ["5 minutes", "1 session", "5 sessions", "21 sessions", "63 sessions"]) {
    assert.match(source, new RegExp(label));
  }
  for (const label of ["Exact origin", "Exact target"]) assert.match(source, new RegExp(label));
  assert.match(source, /fetch\("\/api\/v1\/forecasts"/);
  for (const call of source.matchAll(/fetch\((?:`|")([^`"]+)/g)) assert.match(call[1], /^\/api\/v1\//);
  assert.match(source, /JSON\.stringify\(\{ symbol: normalized, asset_type: assetType, interval \}\)/);
  assert.match(source, /item\.interval === interval \|\| item\.horizon === selected\.horizon/);
  assert.match(source, /Selected horizon unavailable/);
  assert.match(source, /The local API did not return \{selected\.label\}/);
  assert.doesNotMatch(source, /legacy omitted-interval contract|close_to_close|completed_5m_to_close/);
  assert.doesNotMatch(source, /results\.length\s*===\s*5|results\[[1-4]\]/);
  assert.match(source, /Threshold probabilities/);
  assert.match(source, /Return and price intervals/);
  assert.match(source, /Historical\/probability data/);
  assert.match(source, /not a live quote/);
  assert.match(source, /snapshotState/);
  assert.match(source, /delay\(snapshot\.delayed, snapshot\.delayMinutes\)/);
  assert.match(source, /provider_state/);
  assert.doesNotMatch(source, /definition_version|sample_counts|overlap_adjusted_effective/);
  const initializationEffect = source.match(/useEffect\(\(\) => \{[^]*?\n  \}, \[\]\);/)?.[0] ?? "";
  assert.ok(initializationEffect);
  assert.doesNotMatch(initializationEffect, /submit\(/);
});
