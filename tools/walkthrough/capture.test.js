"use strict";

const assert = require("node:assert/strict");
const test = require("node:test");
const {
  STEPS,
  assertStepDefinitions,
  assertTooltipMatchesTable,
  executableOnPath,
  gifAssemblySupport,
  requestPolicyViolation,
} = require("./capture");

test("manifest steps are unique and cover every requested journey", () => {
  assert.doesNotThrow(() => assertStepDefinitions(STEPS));
  assert.equal(STEPS[0].id, "01-backup-status");
  assert.equal(STEPS.at(-1).id, "10-history-downloads");
});

// PNG frames remain authoritative so optional GIF tooling cannot block walkthrough capture.
test("missing optional GIF tooling leaves PNG captures authoritative", () => {
  assert.equal(executableOnPath("ffmpeg", ""), null);
  const support = gifAssemblySupport("");
  assert.equal(support.status, "unavailable");
  assert.match(support.exact_missing_dependency, /Pillow\/PIL.*GIF-capable/);
  assert.match(support.pillow_in_dev_venv, /not importable/);
  assert.match(support.authoritative_media, /PNG/);
});

test("chart tooltip probability must equal its corresponding table value", () => {
  const rows = [{ heading: "Return at or below -10%", value: "12.3% · definition" }];
  assert.deepEqual(
    assertTooltipMatchesTable("12.3% probability of return at or below -10%", rows),
    { heading: "Return at or below -10%", probability: "12.3%" },
  );
  assert.throws(
    () => assertTooltipMatchesTable("12.4% probability of return at or below -10%", rows),
    /probability mismatch/,
  );
});

test("request policy allows only declared app paths on the isolated origin", () => {
  const baseURL = "http://127.0.0.1:43210";
  for (const pathname of [
    "/",
    "/assets/app.css",
    "/assets/app.js",
    "/assets/favicon.svg",
    "/api/v1/history?page=1",
    "/api/v1/saved-forecasts/12",
    "/api/v1/history/12/reconstructions",
  ]) assert.equal(requestPolicyViolation(`${baseURL}${pathname}`, baseURL), null, pathname);
  assert.match(requestPolicyViolation("https://example.com/app.js", baseURL), /Non-loopback/);
  assert.match(requestPolicyViolation(`${baseURL}/assets/undeclared.js`, baseURL), /Undeclared/);
});
