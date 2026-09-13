"use strict";

const assert = require("node:assert/strict");
const fsp = require("node:fs/promises");
const os = require("node:os");
const path = require("node:path");
const test = require("node:test");
const {
  STEPS,
  PROFILES,
  ARTIFACT_BUDGET_BYTES,
  NEWS_ITEM_SELECTOR,
  assertHeadlineEvidence,
  assertStepDefinitions,
  assertTooltipMatchesTable,
  executableOnPath,
  gifAssemblySupport,
  publicationMarkdown,
  requestPolicyViolation,
  writeArtifactManifests,
} = require("./capture");

test("manifest steps are unique and cover every requested journey", () => {
  assert.doesNotThrow(() => assertStepDefinitions(STEPS));
  assert.equal(STEPS.length, 20);
  assert.equal(STEPS[0].id, "01-backup-status");
  assert.equal(STEPS[9].id, "10-history-downloads");
  assert.equal(STEPS.at(-1).id, "20-saved-current-news");
  assert.deepEqual(PROFILES.map(({ name, viewport }) => ({ name, viewport })), [
    { name: "desktop", viewport: { width: 1280, height: 1000 } },
    { name: "mobile", viewport: { width: 390, height: 844 } },
  ]);
  assert.equal(ARTIFACT_BUDGET_BYTES, 20 * 1024 * 1024);
  assert.ok(STEPS.every(({ description, caption, altText }) => description && caption && altText));
  assert.ok(STEPS.every(({ caption, altText }) => caption !== altText));
  assert.doesNotMatch(STEPS[9].description, /harness/i);
  assert.match(STEPS[13].caption, /settled dark API page.*not.*transition/i);
  for (const step of STEPS.slice(14, 19)) {
    assert.match(step.description, /Simulated/i);
    assert.match(step.description, /fixture clock 10 Jan 2025, 17:03 UTC/i);
  }
  assert.match(STEPS[16].description, /item 1.*publisher.*publication time/i);
});

test("published transcript gives actions, expected results, and image-specific alt text", () => {
  const profiles = Object.fromEntries(PROFILES.map(({ name }) => [name, {
    captures: STEPS.map((step) => ({
      id: step.id,
      caption: step.caption,
      alt_text: step.altText,
      screenshot: `screenshots/${name}-${step.id}.png`,
    })),
    supplementary_captures: [],
    companion_news_states: [{
      title: "Headlines not requested",
      instruction: "Leave the disclosure closed.",
      caption: "No request is issued.",
      alt_text: "Closed current-headlines disclosure.",
      screenshot: `screenshots/${name}-20-saved-current-news-closed-disclosure.png`,
    }],
  }]));
  const markdown = publicationMarkdown({
    revision: "abc123",
    dirty: true,
    generated_utc: "2026-09-12T00:00:00.000Z",
    command: "./scripts/capture-walkthrough.sh",
  }, profiles);
  assert.match(markdown, /^---\ntitle: "Stock Probability walkthrough"\ndescription: .+\n---\n/);
  assert.match(markdown, /\*\*Do:\*\* Type ProFrac/);
  assert.match(markdown, /\*\*Expect:\*\*/);
  assert.match(markdown, /Simulated response — fixture clock/);
  assert.match(markdown, /docs|downloads\/desktop\/history\.csv/);
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

test("headline evidence uses rendered list items and requires an observed abort", () => {
  assert.equal(NEWS_ITEM_SELECTOR, "ol.news-list > li");
  assert.deepEqual(assertHeadlineEvidence("fresh", 5), {
    verification: "headline-items",
    state: "fresh",
    selector: NEWS_ITEM_SELECTOR,
    count: 5,
  });
  assert.throws(() => assertHeadlineEvidence("fresh", 0), /no fresh headline items/);
  assert.deepEqual(assertHeadlineEvidence("superseded", 0, true), {
    verification: "headline-items",
    state: "superseded",
    selector: NEWS_ITEM_SELECTOR,
    count: 0,
    pending_stub_abort_event_observed: true,
  });
  assert.throws(() => assertHeadlineEvidence("superseded", 0), /did not observe its abort event/);
  assert.throws(() => assertHeadlineEvidence("superseded", 1, true), /retained 1 headline items/);
});

test("request policy allows only declared app paths on the isolated origin", () => {
  const baseURL = "http://127.0.0.1:43210";
  for (const pathname of [
    "/",
    "/assets/app.css",
    "/assets/app.js",
    "/assets/theme.js",
    "/assets/favicon.svg",
    "/api/v1/docs",
    "/api/v1/news?symbol=SPY&limit=5",
    "/api/v1/history?page=1",
    "/api/v1/saved-forecasts/12",
    "/api/v1/history/12/reconstructions",
  ]) assert.equal(requestPolicyViolation(`${baseURL}${pathname}`, baseURL), null, pathname);
  assert.match(requestPolicyViolation("https://example.com/app.js", baseURL), /Non-loopback/);
  assert.match(requestPolicyViolation(`${baseURL}/assets/undeclared.js`, baseURL), /Undeclared/);
});

test("generated and published manifests account for themselves and every artifact", async (t) => {
  const root = await fsp.mkdtemp(path.join(os.tmpdir(), "walkthrough-manifest-"));
  t.after(() => fsp.rm(root, { recursive: true, force: true }));
  const output = path.join(root, "output");
  const publication = path.join(root, "publication");
  await Promise.all([fsp.mkdir(output), fsp.mkdir(publication)]);
  await Promise.all([
    fsp.writeFile(path.join(output, "frame.png"), "frame"),
    fsp.writeFile(path.join(publication, "index.md"), "---\ntitle: test\n---\n"),
  ]);
  const manifest = { artifacts: {
    total_bytes: 0,
    files: [],
    published_total_bytes: 0,
    published_files: [],
  } };

  const totals = await writeArtifactManifests(manifest, output, publication);
  const generated = JSON.parse(await fsp.readFile(path.join(output, "manifest.json"), "utf8"));
  const published = JSON.parse(await fsp.readFile(path.join(publication, "manifest.json"), "utf8"));
  assert.deepEqual(generated, published);
  assert.deepEqual(generated.artifacts, manifest.artifacts);
  assert.equal(generated.artifacts.total_bytes, totals.totalBytes);
  assert.equal(generated.artifacts.published_total_bytes, totals.publishedBytes);
  assert.deepEqual(generated.artifacts.files.map(({ path: name }) => name), ["frame.png", "manifest.json"]);
  assert.deepEqual(generated.artifacts.published_files.map(({ path: name }) => name), ["index.md", "manifest.json"]);
});
