import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const root = new URL("../", import.meta.url);

test("legacy dashboard mutations retrieve a session-bound CSRF header on demand", async () => {
  const source = await readFile(new URL("../src/stock_probs/static/app.js", root), "utf8");

  assert.match(source, /const mutationMethods = new Set\(\["POST", "PUT", "PATCH", "DELETE"\]\)/);
  assert.match(source, /mutationMethods\.has\(String\(options\.method \|\| "GET"\)\.toUpperCase\(\)\)/);
  assert.match(source, /fetch\(`\$\{apiRoot\}\/auth\/session`/);
  assert.match(source, /credentials: "same-origin"/);
  assert.match(source, /headers\.set\("X-CSRF-Token", session\.csrf_token\)/);
  assert.equal((source.match(/method: "POST"/g) || []).length, 2);
  assert.doesNotMatch(source, /localStorage|sessionStorage|document\.cookie/);
});
