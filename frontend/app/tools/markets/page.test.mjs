import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

test("markets exports watchlist CRUD, quote filters, and local chart links", async () => {
  const source = await readFile(new URL("workspace.tsx", import.meta.url), "utf8");

  for (const label of ["Add or update an instrument", "Watchlist quotes", "Symbol or name", "Market / exchange", "Minimum price", "Minimum % change", "Minimum volume", "Reset filters", "Instrument detail"]) assert.match(source, new RegExp(label));
  assert.match(source, /\/api\/v1\/lists\?kind=watchlist/);
  for (const call of source.matchAll(/fetch\((?:`|")([^`"]+)/g)) assert.match(call[1], /^\/api\/v1\//);
  assert.match(source, /method: "DELETE"/);
  assert.match(source, /JSON\.stringify\(\{ kind: "watchlist", item: \{ symbol: item\.symbol, asset_type: item\.asset_type \} \}\)/);
  assert.match(source, /value\.display_name/);
  assert.doesNotMatch(source, /value\.name/);
  assert.match(source, /\/api\/v1\/bars\?\$\{query\}/);
  assert.match(source, /quoteBatches\(symbols\)/);
  assert.match(source, /range: chartRange/);
  assert.match(source, /interval: "1d"/);
  for (const range of ["5d", "1mo", "3mo", "6mo", "1y"]) assert.match(source, new RegExp(`\"${range}\"`));
  assert.match(source, /record\(payload\)\.items/);
  assert.match(source, /Array\.isArray\(value\.bars\)/);
  assert.match(source, /local (watchlist|quote|chart) response was malformed/);
  assert.doesNotMatch(source, /value\.quotes|Array\.isArray\(value\.items\)|barData\?\.items|loaded\.items/);
  assert.doesNotMatch(source, /response\.status === 501|Chart bars are not implemented by this local service/);
  assert.match(source, /\/tools\/live-trading\?/);
  assert.match(source, /\/tools\/forecast\?/);
  assert.match(source, /provider: item\.provider \?\? "yahoo"/);
  assert.match(source, /display_name: item\.display_name \?\? item\.symbol/);
  for (const disclosure of ["Quote unavailable", "Quote snapshot / provider / as of / delay", "Bars snapshot:", "Delay:"]) assert.match(source, new RegExp(disclosure));
  assert.doesNotMatch(source, />\s*(Buy|Sell)\s*</i);
  assert.doesNotMatch(source, /stock-probs\.watchlist-draft|Saved locally|Removed locally|Local entries remain visible/);
  assert.match(source, /import \{[^}]*quotePrice[^}]*\} from "\.\.\/client-utils"/);
  for (const field of ["change_percent", "volume", "open", "high", "low", "previous_close", "last_trade"]) {
    assert.match(source, new RegExp(`item\\.${field}|selectedQuote\\.${field}`));
    assert.match(source, new RegExp(`value="${field}"`));
  }
  assert.doesNotMatch(source, /function quotePrice/);
  assert.match(source, /setInterval\(.*QUOTE_REFRESH_MS/);
  assert.match(source, /clearInterval\(timer\)/);
  assert.match(source, /request\.signal\.aborted \|\| generation !== barGeneration\.current/);
  assert.match(source, /Chart range/);
  assert.match(source, /scope="col"/);
  assert.doesNotMatch(source, /<th>Close<|data-label="Close"/);
  for (const line of source.split("\n").filter((line) => line.includes("JSON.stringify({ kind:"))) assert.doesNotMatch(line, /\b(name|exchange)\b/);
});
