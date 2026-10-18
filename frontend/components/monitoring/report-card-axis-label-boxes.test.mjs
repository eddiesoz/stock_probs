import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
import vm from "node:vm";

const requireFromFrontend = createRequire(new URL(`${process.cwd()}/package.json`, import.meta.url));
const ts = requireFromFrontend("typescript");

const source = readFileSync(new URL("./report-card-axis-label-boxes.ts", import.meta.url), "utf8");
const code = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
}).outputText;
const axisModule = { exports: {} };
vm.runInNewContext(code, { module: axisModule, exports: axisModule.exports, RangeError });

test("return chart uses a shared symmetric percent domain with zero centered", () => {
  const axis = axisModule.exports.getReportCardReturnAxis([-12, 8, 2.4]);
  assert.equal(axis.maximum, 15);
  assert.deepEqual(Array.from(axis.ticks), [-15, -10, -5, 0, 5, 10, 15]);
  assert.equal(axis.position(-15), 0);
  assert.equal(axis.position(0), 500);
  assert.equal(axis.position(15), 1_000);
  assert.equal(axis.position(2.4), 580);
});

test("return chart expands the common domain without clipping valid outliers", () => {
  const axis = axisModule.exports.getReportCardReturnAxis([-21.2, 17]);
  assert.equal(axis.maximum, 30);
  assert.deepEqual(Array.from(axis.ticks), [-30, -20, -10, 0, 10, 20, 30]);
  assert.ok(axis.position(-21.2) > 0);
  assert.ok(axis.position(17) < 1_000);
  assert.throws(() => axis.position(31), /outside the shared chart domain/);
});

test("empty or non-finite inputs keep a stable minimum axis", () => {
  assert.equal(axisModule.exports.getReportCardReturnAxis([]).maximum, 15);
  assert.equal(axisModule.exports.getReportCardReturnAxis([Number.NaN, Infinity, -Infinity]).maximum, 15);
});

test("zero plotted rows distinguish no scored outcomes from missing chart evidence", () => {
  const noScoredOutcomes = axisModule.exports.getReportCardReturnPlot([], 60, 1e15, 100_000);
  assert.equal(noScoredOutcomes.status, "no_scored_outcomes");
  assert.equal(axisModule.exports.describeReportCardReturnPlotOmissions(noScoredOutcomes.omissions), null);

  const noPlottableOutcomes = axisModule.exports.getReportCardReturnPlot([
    { row: "coverage-missing", observedClose: 100, observedReturn: 0.02, interval: { low: 97, high: 105 }, intervalCovered: null },
    { row: "return-data-missing", observedClose: null, observedReturn: 0.02, interval: { low: 97, high: 105 }, intervalCovered: true },
  ], 60, 1e15, 100_000);
  assert.equal(noPlottableOutcomes.status, "no_plottable_outcomes");
  assert.equal(noPlottableOutcomes.omissions.total, 2);
  assert.equal(noPlottableOutcomes.omissions.missingCoverage, 1);
  assert.equal(noPlottableOutcomes.omissions.missingOrUnusableData, 1);
  assert.equal(noPlottableOutcomes.omissions.outsideDisplayLimits, 0);
  assert.match(
    axisModule.exports.describeReportCardReturnPlotOmissions(noPlottableOutcomes.omissions),
    /1 scored outcome lacks recorded interval coverage; 1 scored outcome has missing or unusable return or interval data/,
  );
});

test("all out-of-range returns are disclosed when no outcome can be plotted", () => {
  const plot = axisModule.exports.getReportCardReturnPlot([
    { row: "outside-a", observedClose: 1, observedReturn: 0, interval: { low: 1, high: 2_001 }, intervalCovered: false },
    { row: "outside-b", observedClose: 1, observedReturn: 0, interval: { low: 1, high: 3_001 }, intervalCovered: true },
  ], 60, 1e15, 100_000);
  assert.equal(plot.status, "no_plottable_outcomes");
  assert.equal(plot.plotted.length, 0);
  assert.equal(plot.omissions.total, 2);
  assert.equal(plot.omissions.outsideDisplayLimits, 2);
  assert.match(axisModule.exports.describeReportCardReturnPlotOmissions(plot.omissions), /2 scored outcomes have return percentages beyond chart display limits/);
});

test("mixed omissions count null coverage, out-of-range data, and the display cap", () => {
  const validRows = Array.from({ length: 61 }, (_, index) => ({
    row: `valid-${index}`,
    observedClose: 102,
    observedReturn: 0.02,
    interval: { low: 97, high: 105 },
    intervalCovered: true,
  }));
  const plot = axisModule.exports.getReportCardReturnPlot([
    ...validRows,
    { row: "coverage-missing", observedClose: 102, observedReturn: 0.02, interval: { low: 97, high: 105 }, intervalCovered: null },
    { row: "outside-display", observedClose: 1, observedReturn: 0, interval: { low: 1, high: 2_001 }, intervalCovered: false },
  ], 60, 1e15, 100_000);
  assert.equal(plot.status, "plotted");
  assert.equal(plot.plotted.length, 60);
  assert.equal(plot.omissions.total, 3);
  assert.equal(plot.omissions.limit, 1);
  assert.equal(plot.omissions.missingCoverage, 1);
  assert.equal(plot.omissions.missingOrUnusableData, 0);
  assert.equal(plot.omissions.outsideDisplayLimits, 1);
  assert.ok(Math.abs(plot.plotted[0].lowPercent - -3) < 1e-9);
  assert.ok(Math.abs(plot.plotted[0].highPercent - 5) < 1e-9);
  assert.ok(Math.abs(plot.plotted[0].observedPercent - 2) < 1e-9);
  assert.equal(
    axisModule.exports.describeReportCardReturnPlotOmissions(plot.omissions),
    "3 scored outcomes are omitted from this chart: 1 scored outcome exceeds the 60-result chart limit; 1 scored outcome lacks recorded interval coverage; 1 scored outcome has return percentages beyond chart display limits. The table and scoring totals still include all validated outcomes.",
  );
});
