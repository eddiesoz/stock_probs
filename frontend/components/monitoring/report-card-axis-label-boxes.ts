const AXIS_TICK_COUNT = 7;
const AXIS_SEGMENTS = AXIS_TICK_COUNT - 1;
const AXIS_WIDTH = 1_000;
const MINIMUM_AXIS_RETURN = 15;
const AXIS_DOMAIN_STEP = 15;
const MAXIMUM_PLOT_RETURN = 100_000;

export interface ReportCardReturnAxis {
  maximum: number;
  ticks: readonly number[];
  position(value: number): number;
}

export interface ReportCardReturnPlotInput<T> {
  row: T;
  observedClose: number | null | undefined;
  observedReturn: number | null | undefined;
  interval: { low: number; high: number } | null | undefined;
  intervalCovered: boolean | null | undefined;
}

export interface ReportCardReturnPlotPoint<T> {
  row: T;
  lowPercent: number;
  highPercent: number;
  observedPercent: number;
}

export interface ReportCardReturnPlotOmissions {
  total: number;
  displayLimit: number;
  missingCoverage: number;
  missingOrUnusableData: number;
  outsideDisplayLimits: number;
  limit: number;
}

export interface ReportCardReturnPlot<T> {
  status: "no_scored_outcomes" | "no_plottable_outcomes" | "plotted";
  plotted: readonly ReportCardReturnPlotPoint<T>[];
  omissions: ReportCardReturnPlotOmissions;
}

export function getReportCardReturnPlot<T>(
  inputs: readonly ReportCardReturnPlotInput<T>[],
  displayLimit: number,
  maximumPrice: number,
  maximumReturnPercent: number,
): ReportCardReturnPlot<T> {
  if (!Number.isSafeInteger(displayLimit) || displayLimit < 1) throw new RangeError("Return chart display limit must be a positive integer.");
  if (!Number.isFinite(maximumPrice) || maximumPrice <= 0 || !Number.isFinite(maximumReturnPercent) || maximumReturnPercent <= 0) {
    throw new RangeError("Return chart bounds must be positive finite numbers.");
  }

  const candidates: ReportCardReturnPlotPoint<T>[] = [];
  let missingCoverage = 0;
  let missingOrUnusableData = 0;
  let outsideDisplayLimits = 0;

  for (const input of inputs) {
    if (typeof input.intervalCovered !== "boolean") {
      missingCoverage += 1;
      continue;
    }
    const { observedClose, observedReturn, interval } = input;
    if (
      typeof observedClose !== "number" || !Number.isFinite(observedClose) || observedClose <= 0 || observedClose > maximumPrice ||
      typeof observedReturn !== "number" || !Number.isFinite(observedReturn) ||
      !interval || !Number.isFinite(interval.low) || !Number.isFinite(interval.high) ||
      interval.low <= 0 || interval.high <= 0 || interval.low > interval.high
    ) {
      missingOrUnusableData += 1;
      continue;
    }

    const origin = observedClose / (1 + observedReturn);
    if (!Number.isFinite(origin) || origin <= 0 || origin > maximumPrice) {
      missingOrUnusableData += 1;
      continue;
    }
    const lowPercent = ((interval.low / origin) - 1) * 100;
    const highPercent = ((interval.high / origin) - 1) * 100;
    const observedPercent = observedReturn * 100;
    const values = [lowPercent, highPercent, observedPercent];
    if (values.some((value) => !Number.isFinite(value))) {
      missingOrUnusableData += 1;
      continue;
    }
    if (values.some((value) => Math.abs(value) > maximumReturnPercent)) {
      outsideDisplayLimits += 1;
      continue;
    }
    candidates.push({ row: input.row, lowPercent, highPercent, observedPercent });
  }

  const plotted = candidates.slice(-displayLimit);
  const limit = candidates.length - plotted.length;
  const omitted = inputs.length - plotted.length;
  const status = inputs.length === 0
    ? "no_scored_outcomes"
    : plotted.length === 0
      ? "no_plottable_outcomes"
      : "plotted";

  return {
    status,
    plotted,
    omissions: {
      total: omitted,
      displayLimit,
      missingCoverage,
      missingOrUnusableData,
      outsideDisplayLimits,
      limit,
    },
  };
}

export function describeReportCardReturnPlotOmissions(omissions: ReportCardReturnPlotOmissions): string | null {
  if (omissions.total === 0) return null;
  const subject = (count: number) => `${count} scored ${count === 1 ? "outcome" : "outcomes"}`;
  const clauses: string[] = [];
  if (omissions.limit > 0) {
    clauses.push(`${subject(omissions.limit)} ${omissions.limit === 1 ? "exceeds" : "exceed"} the ${omissions.displayLimit}-result chart limit`);
  }
  if (omissions.missingCoverage > 0) {
    clauses.push(`${subject(omissions.missingCoverage)} ${omissions.missingCoverage === 1 ? "lacks" : "lack"} recorded interval coverage`);
  }
  if (omissions.missingOrUnusableData > 0) {
    clauses.push(`${subject(omissions.missingOrUnusableData)} ${omissions.missingOrUnusableData === 1 ? "has" : "have"} missing or unusable return or interval data`);
  }
  if (omissions.outsideDisplayLimits > 0) {
    clauses.push(`${subject(omissions.outsideDisplayLimits)} ${omissions.outsideDisplayLimits === 1 ? "has" : "have"} return percentages beyond chart display limits`);
  }
  const reasons = clauses.join("; ");
  return `${omissions.total} scored ${omissions.total === 1 ? "outcome is" : "outcomes are"} omitted from this chart: ${reasons}. The table and scoring totals still include all validated outcomes.`;
}

export function getReportCardReturnAxis(values: readonly number[]): ReportCardReturnAxis {
  const safeValues = values.filter((value) => Number.isFinite(value) && Math.abs(value) <= MAXIMUM_PLOT_RETURN);
  const observedMaximum = safeValues.reduce((maximum, value) => Math.max(maximum, Math.abs(value)), 0);
  const maximum = Math.max(MINIMUM_AXIS_RETURN, Math.ceil(observedMaximum / AXIS_DOMAIN_STEP) * AXIS_DOMAIN_STEP);
  const ticks = Array.from({ length: AXIS_TICK_COUNT }, (_, index) => ((index - AXIS_SEGMENTS / 2) * maximum) / (AXIS_SEGMENTS / 2));

  return {
    maximum,
    ticks,
    position(value: number): number {
      if (!Number.isFinite(value) || Math.abs(value) > maximum) throw new RangeError("Return value is outside the shared chart domain.");
      return ((value + maximum) / (2 * maximum)) * AXIS_WIDTH;
    },
  };
}
