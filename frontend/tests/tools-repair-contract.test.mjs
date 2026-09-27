import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

test("forecast interval table stays locally scrollable inside shrinking result items", async () => {
  const css = await readFile(new URL("../app/tools/forecast/workspace.module.css", import.meta.url), "utf8");

  for (const selector of [".composer,.results", ".resultCard", ".resultSection", ".intervalTableWrap"]) {
    const rule = css.match(new RegExp(`${selector.replace(/[.*+?^${}()|[\\]\\]/g, "\\$&")}\\{([^}]*)\\}`))?.[1] ?? "";
    assert.match(rule, /min-width:0/);
    assert.match(rule, /max-width:100%/);
  }
  assert.match(css, /\.intervalTableWrap\{[^}]*overflow-x:auto/);
  assert.match(css, /\.intervalTable\{[^}]*min-width:520px/);
  assert.doesNotMatch(css, /\.intervalTable\{[^}]*max-width:100%/);
});

test("forecast interval table fits and wraps all columns at the mobile breakpoint", async () => {
  const css = await readFile(new URL("../app/tools/forecast/workspace.module.css", import.meta.url), "utf8");
  const mobileStart = css.indexOf("@media (max-width:700px){");
  const mobileEnd = css.indexOf("@media (max-width:420px){", mobileStart);
  const mobile = css.slice(mobileStart, mobileEnd);

  assert.ok(mobileStart >= 0 && mobileEnd > mobileStart);
  assert.match(css, /\.intervalTable\{[^}]*min-width:520px/);
  assert.match(mobile, /\.intervalTable\{[^}]*min-width:0[^}]*table-layout:fixed\}/);
  assert.match(mobile, /\.intervalTable th,\.intervalTable td\{[^}]*overflow-wrap:anywhere\}/);
});

test("forecast interval scroll region is keyboard-focusable and named", async () => {
  const source = await readFile(new URL("../app/tools/forecast/workspace.tsx", import.meta.url), "utf8");
  const scrollRegion = source.match(/<div\s+className=\{styles\.intervalTableWrap\}[\s\S]*?<table/)?.[0] ?? "";

  assert.match(scrollRegion, /role="region"/);
  assert.match(scrollRegion, /aria-label="Return and price interval table"/);
  assert.match(scrollRegion, /tabIndex=\{0\}/);
});

test("tool sub-navigation labels its wrapper without nesting another navigation landmark", async () => {
  const source = await readFile(new URL("../app/tools/tool-page.tsx", import.meta.url), "utf8");

  assert.match(source, /<section className=\{styles\.toolNav\} aria-label="Tools navigation">/);
  assert.match(source, /<p className="panel-kicker">Tools<\/p>[\s\S]*<ToolsNav current=\{tool\} \/>/);
  assert.equal((source.match(/<ToolsNav\b/g) ?? []).length, 1);
  assert.doesNotMatch(source, /<nav[^>]*>[\s\S]*<ToolsNav\b/);
});

test("live-trading waits for a terminal portfolio-list state before its first quote request", async () => {
  const source = await readFile(new URL("../app/tools/live-trading/workspace.tsx", import.meta.url), "utf8");
  const quoteEffect = source.match(/useEffect\(\(\) => \{[\s\S]*?\n  \}, \[identity\.symbol, portfolio, portfolioState, quoteAttempt\]\);/)?.[0] ?? "";

  assert.ok(quoteEffect);
  assert.match(source, /const \[portfolioState, setPortfolioState\] = useState<LoadState>\("loading"\)/);
  assert.match(source, /setPortfolioState\(holdings\.length \? "ready" : "empty"\)/);
  assert.match(source, /setPortfolioState\("error"\)/);
  assert.match(quoteEffect, /if \(!initialized\.current \|\| portfolioState === "loading"\) return;/);
  assert.ok(quoteEffect.indexOf("portfolioState === \"loading\"") < quoteEffect.indexOf("const symbols"));
  for (const guard of ["request\\?\\.signal\\.aborted", "generation !== quoteGeneration\\.current", "request\\?\\.abort\\(\\)", "setInterval\\(.*QUOTE_REFRESH_MS"]) {
    assert.match(source, new RegExp(guard));
  }
  assert.match(source, /setPaused\(\(current\) => !current\)/);
});
