import assert from "node:assert/strict";
import { readFile, readdir } from "node:fs/promises";
import test from "node:test";

const buildId = "stock-probs";
const dashboardIds = [
  "settings-menu", "system-label", "main", "forecast-heading", "forecast-form", "symbol",
  "symbol-help", "lookup-status", "instrument-options", "identity-confirmation", "symbol-error",
  "forecast-submit", "announcement", "result-section", "result-heading", "quality-badge",
  "result-content", "fresh-analysis-section", "fresh-analysis-heading", "fresh-analysis-content",
  "history-heading", "export-csv", "export-json", "history-form", "history-query", "history-status",
  "history-asset", "history-analysis", "history-from", "history-to", "history-model",
  "history-horizon", "history-sort", "history-page-size", "history-content", "history-previous",
  "history-page", "history-next",
];

function headResourceElements(html) {
  const start = html.indexOf("<head>");
  const end = html.indexOf("</head>");
  assert.ok(start >= 0 && end > start);
  return [...html.slice(start, end).matchAll(/<(script|link)\b([^>]*)>/g)].map((match) => ({
    tag: match[1],
    offset: start + match.index,
    attributes: Object.fromEntries(
      [...match[2].matchAll(/\s([A-Za-z][\w:-]*)(?:="([^"]*)")?/g)]
        .map((attribute) => [attribute[1].toLowerCase(), attribute[2] ?? ""]),
    ),
  }));
}

function resourcesFor(elements, path) {
  return elements.filter(({ attributes }) => attributes.src === path || attributes.href === path);
}

test("static export keeps dashboard hooks and route-specific scripts", async () => {
  const dashboard = await readFile(new URL("../out/index.html", import.meta.url), "utf8");
  const apiDocs = await readFile(new URL("../out/api-docs.html", import.meta.url), "utf8");
  const dashboardResources = headResourceElements(dashboard);
  const apiDocsResources = headResourceElements(apiDocs);

  for (const id of dashboardIds) assert.match(dashboard, new RegExp(`id=["']${id}["']`));
  assert.match(dashboard, /class=["']settings-trigger secondary["']/);
  assert.match(dashboard, /id=["']settings-menu["'][^>]*popover=["']["']/);
  assert.match(apiDocs, /id=["']contract-heading["']/);
  assert.match(apiDocs, /id=["']settings-menu["'][^>]*popover=["']["']/);

  for (const resources of [dashboardResources, apiDocsResources]) {
    const [theme] = resourcesFor(resources, "/assets/theme.js");
    const [stylesheet] = resourcesFor(resources, "/assets/app.css")
      .filter(({ tag, attributes }) => tag === "link" && attributes.rel === "stylesheet");
    assert.equal(resourcesFor(resources, "/assets/theme.js").length, 1);
    assert.equal(theme.tag, "script");
    assert.equal(theme.attributes.async, undefined);
    assert.equal(theme.attributes.defer, undefined);
    assert.ok(theme.offset < stylesheet.offset);
    assert.ok(resources.some(({ attributes }) =>
      (attributes.src ?? attributes.href)?.startsWith("/_next/")));
  }

  const dashboardApp = resourcesFor(dashboardResources, "/assets/app.js");
  assert.equal(dashboardApp.length, 1);
  assert.deepEqual(dashboardApp[0].attributes, {
    rel: "preload",
    href: "/assets/app.js",
    as: "script",
  });
  assert.equal(resourcesFor(apiDocsResources, "/assets/app.js").length, 0);

  assert.equal((await readFile(new URL("../.next/BUILD_ID", import.meta.url), "utf8")).trim(), buildId);
  const staticRoot = new URL("../out/_next/static/", import.meta.url);
  const staticDirectories = (await readdir(staticRoot, { withFileTypes: true }))
    .filter((entry) => entry.isDirectory())
    .map((entry) => entry.name)
    .sort();
  assert.deepEqual(staticDirectories, [buildId, "chunks"].sort());
  await readFile(new URL(`${buildId}/_buildManifest.js`, staticRoot));
  await readFile(new URL(`${buildId}/_ssgManifest.js`, staticRoot));
});
