"use client";

import { useId, useState } from "react";

import styles from "./ReportCardWorkspace.module.css";
import {
  describeReportCardReturnPlotOmissions,
  getReportCardReturnAxis,
  getReportCardReturnPlot,
} from "./report-card-axis-label-boxes";
import type { ReportCardReturnPlotPoint } from "./report-card-axis-label-boxes";

export type ReportOutcomeState = "scored" | "pending" | "unavailable" | "disputed" | "incomparable";
export type ReportPanelState = "loading" | "ready" | "error" | "unavailable";
type DirectionClass = "down" | "unchanged" | "up";
type DatePeriod = "all" | "7" | "30" | "90" | "365";

export interface ReportOutcome {
  result_id: number;
  symbol: string;
  horizon: string;
  model_version: string;
  five_minute: boolean;
  target_timestamp: string | null;
  state: ReportOutcomeState;
  reason: string;
  predicted_class: DirectionClass | null;
  observed_class: DirectionClass | null;
  direction_correct: boolean | null;
  interval_80_covered: boolean | null;
  observed_return: number | null;
  interval_80_price: { low: number; high: number } | null;
  outcome: { observed_close?: number | null } | null;
  source: { method: "provider_bar" | "manual_review" } | null;
}

export interface ReportModelHorizonGroup {
  horizon: string;
  model_version: string;
  five_minute: boolean;
  counts: Record<ReportOutcomeState, number>;
  direction: { correct: number; denominator: number; accuracy: number | null };
  interval_80: { covered: number; denominator: number; coverage: number | null };
  tied_predictions: number;
}

export interface ReportCardSummary {
  as_of: string;
  counts: Record<ReportOutcomeState, number>;
  groups: readonly ReportModelHorizonGroup[];
  items: readonly ReportOutcome[];
  label: string;
  sample_limit: string;
  direction_boundaries: { down: string; unchanged: string; up: string };
}

export interface ReportCardWorkspaceProps {
  state: ReportPanelState;
  summary: ReportCardSummary | null;
  errorMessage?: string;
  statusMessage?: string;
  onRetry?: () => void;
}

const OUTCOME_STATES: readonly ReportOutcomeState[] = ["scored", "pending", "unavailable", "disputed", "incomparable"];
const DIRECTION_CLASSES: readonly DirectionClass[] = ["down", "unchanged", "up"];
const FIVE_MINUTE_HORIZONS = new Set(["five_min_forward", "completed_5m_to_close"]);
const PLOT_LIMIT = 60;
const TABLE_PAGE_SIZE = 20;
const MAX_INPUT_ROWS = 1_000;
const MAX_PRICE = 1e15;
const MAX_RETURN = 100;
const MAX_PLOT_RETURN_PERCENT = 100_000;

type UnknownRecord = Record<string, unknown>;
type PlotPoint = ReportCardReturnPlotPoint<ReportOutcome>;

function isRecord(value: unknown): value is UnknownRecord {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function boundedText(value: unknown, maximum: number, allowEmpty = false): string | null {
  if (typeof value !== "string" || value.length > maximum || /[\u0000-\u001f\u007f]/.test(value)) return null;
  const trimmed = value.trim();
  if (!allowEmpty && (trimmed.length === 0 || trimmed !== value)) return null;
  return trimmed;
}

function finiteNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

function awareTimestamp(value: unknown): string | null {
  if (typeof value !== "string" || value.length > 40 || !/(?:Z|[+-]\d{2}:\d{2})$/i.test(value)) return null;
  return Number.isFinite(Date.parse(value)) ? value : null;
}

function nullableBoolean(value: unknown): value is boolean | null {
  return value === null || typeof value === "boolean";
}

function nullableClass(value: unknown): value is DirectionClass | null {
  return value === null || DIRECTION_CLASSES.includes(value as DirectionClass);
}

function validateOutcome(value: unknown): ReportOutcome | null {
  if (!isRecord(value)) return null;
  const { result_id: resultId, five_minute: fiveMinute, state } = value;
  if (!Number.isSafeInteger(resultId) || (resultId as number) <= 0 || typeof fiveMinute !== "boolean" || !OUTCOME_STATES.includes(state as ReportOutcomeState)) return null;
  const symbol = boundedText(value.symbol, 32);
  const horizon = boundedText(value.horizon, 64);
  const modelVersion = boundedText(value.model_version, 160);
  const reason = boundedText(value.reason, 320, true);
  const targetTimestamp = value.target_timestamp === null ? null : awareTimestamp(value.target_timestamp);
  if (!symbol || !horizon || !modelVersion || reason === null || (value.target_timestamp !== null && targetTimestamp === null)) return null;
  if (fiveMinute !== FIVE_MINUTE_HORIZONS.has(horizon)) return null;

  const predictedClass = value.predicted_class;
  const observedClass = value.observed_class;
  const directionCorrect = value.direction_correct;
  const intervalCovered = value.interval_80_covered;
  const observedReturn = value.observed_return;
  if (!nullableClass(predictedClass) || !nullableClass(observedClass) || !nullableBoolean(directionCorrect) || !nullableBoolean(intervalCovered)) return null;
  if (observedReturn !== null && (!finiteNumber(observedReturn) || observedReturn <= -1 || observedReturn > MAX_RETURN)) return null;

  let interval: ReportOutcome["interval_80_price"] = null;
  if (value.interval_80_price !== null) {
    if (!isRecord(value.interval_80_price)) return null;
    const { low, high } = value.interval_80_price;
    if (!finiteNumber(low) || !finiteNumber(high) || low <= 0 || high <= 0 || low > high || high > MAX_PRICE) return null;
    interval = { low, high };
  }

  const outcomeValue = value.outcome;
  const sourceValue = value.source;
  let observedClose: number | null | undefined;
  let sourceMethod: "provider_bar" | "manual_review" | null = null;
  if (outcomeValue !== null && outcomeValue !== undefined) {
    if (!isRecord(outcomeValue)) return null;
    observedClose = outcomeValue.observed_close as number | null | undefined;
    if (observedClose !== undefined && observedClose !== null && (!finiteNumber(observedClose) || observedClose <= 0 || observedClose > MAX_PRICE)) return null;
  }
  if (sourceValue === null) {
    sourceMethod = null;
  } else {
    if (!isRecord(sourceValue)) return null;
    const method = sourceValue.method;
    if (method !== "provider_bar" && method !== "manual_review") return null;
    sourceMethod = method;
  }
  if (state === "scored") {
    if (
      targetTimestamp === null || observedReturn === null || interval === null || typeof intervalCovered !== "boolean" ||
      observedClose === undefined || observedClose === null || sourceMethod === null
    ) return null;
    if (sourceMethod === "manual_review" && !FIVE_MINUTE_HORIZONS.has(horizon)) return null;
  } else if (
    predictedClass !== null || observedClass !== null || directionCorrect !== null || intervalCovered !== null ||
    observedReturn !== null || interval !== null || sourceValue !== null
  ) {
    return null;
  }

  return {
    result_id: resultId as number,
    symbol,
    horizon,
    model_version: modelVersion,
    five_minute: fiveMinute,
    target_timestamp: targetTimestamp,
    state: state as ReportOutcomeState,
    reason,
    predicted_class: predictedClass,
    observed_class: observedClass,
    direction_correct: directionCorrect,
    interval_80_covered: intervalCovered,
    observed_return: observedReturn,
    interval_80_price: interval,
    outcome: outcomeValue === null || outcomeValue === undefined ? null : { observed_close: observedClose },
    source: sourceMethod === null ? null : { method: sourceMethod },
  };
}

export interface ReportItemsValidation {
  status: "valid" | "malformed" | "too_large";
  rows: ReportOutcome[];
  omitted: number;
  inputCount: number;
}

export function validateReportItems(value: unknown): ReportItemsValidation {
  if (!Array.isArray(value)) return { status: "malformed", rows: [], omitted: 0, inputCount: 0 };
  const rawItems = value as unknown[];
  if (rawItems.length > MAX_INPUT_ROWS) return { status: "too_large", rows: [], omitted: rawItems.length, inputCount: rawItems.length };
  const parsed = rawItems.map(validateOutcome);
  const frequencies = new Map<number, number>();
  for (const row of parsed) if (row) frequencies.set(row.result_id, (frequencies.get(row.result_id) ?? 0) + 1);
  const rows = parsed.filter((row): row is ReportOutcome => row !== null && frequencies.get(row.result_id) === 1);
  return { status: "valid", rows, omitted: rawItems.length - rows.length, inputCount: rawItems.length };
}

function groupKey(row: Pick<ReportOutcome, "model_version" | "horizon" | "five_minute">): string {
  return JSON.stringify([row.model_version, row.horizon, row.five_minute]);
}

function groupChoices(rows: readonly ReportOutcome[]): Array<Pick<ReportOutcome, "model_version" | "horizon" | "five_minute">> {
  const choices = new Map<string, Pick<ReportOutcome, "model_version" | "horizon" | "five_minute">>();
  for (const row of rows) choices.set(groupKey(row), { model_version: row.model_version, horizon: row.horizon, five_minute: row.five_minute });
  return [...choices.values()].sort((left, right) => left.model_version.localeCompare(right.model_version) || left.horizon.localeCompare(right.horizon));
}

function parseDate(value: string): number | null {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return null;
  const timestamp = Date.parse(`${value}T00:00:00.000Z`);
  return Number.isFinite(timestamp) && new Date(timestamp).toISOString().slice(0, 10) === value ? timestamp : null;
}

function dateRangeError(fromDate: string, throughDate: string): string | null {
  const from = fromDate ? parseDate(fromDate) : null;
  const through = throughDate ? parseDate(throughDate) : null;
  if (fromDate && from === null) return "The start date is invalid.";
  if (throughDate && through === null) return "The end date is invalid.";
  if (from !== null && through !== null && from > through) return "The start date must be on or before the end date.";
  return null;
}

function validCount(value: number): number | null {
  return Number.isSafeInteger(value) && value >= 0 ? value : null;
}

function percent(numerator: number, denominator: number): string {
  if (!Number.isSafeInteger(numerator) || !Number.isSafeInteger(denominator) || denominator <= 0 || numerator < 0 || numerator > denominator) return "Unavailable";
  return `${((numerator / denominator) * 100).toFixed(1)}%`;
}

function formatInstant(value: string | null): string {
  const parsed = value ? awareTimestamp(value) : null;
  return parsed === null ? "Unavailable" : `${new Date(parsed).toISOString().slice(0, 19).replace("T", " ")} UTC`;
}

function formatDateLabel(value: string | null): string {
  const parsed = value ? awareTimestamp(value) : null;
  return parsed === null ? "Date unavailable" : new Date(parsed).toISOString().slice(0, 10);
}

function formatReturn(value: number | null): string {
  return value !== null && Number.isFinite(value) && Math.abs(value) <= MAX_RETURN ? `${(value * 100).toFixed(2)}%` : "Unavailable";
}

function formatPercentPoints(value: number): string {
  return Number.isFinite(value) && Math.abs(value) <= MAX_PLOT_RETURN_PERCENT ? `${value.toFixed(2)}%` : "Unavailable";
}

function compareTarget(left: string | null, right: string | null): number {
  const leftTime = left ? Date.parse(left) : Number.NaN;
  const rightTime = right ? Date.parse(right) : Number.NaN;
  if (Number.isFinite(leftTime) && Number.isFinite(rightTime)) return leftTime - rightTime;
  return (left ?? "").localeCompare(right ?? "");
}

function horizonLabel(value: string, fiveMinute: boolean): string {
  const known: Record<string, string> = {
    five_min_forward: "5-minute forward",
    completed_5m_to_close: "5-minute to close",
    close_to_close: "Close to close",
    daily_1: "Daily · 1 session",
    weekly_5: "Weekly · 5 sessions",
    monthly_21: "Monthly · 21 sessions",
    quarterly_63: "Quarterly · 63 sessions",
  };
  return known[value] ?? `${fiveMinute ? "5-minute · " : ""}${value}`;
}

function asPlotPoint(row: ReportOutcome): PlotPoint | null {
  if (row.state !== "scored") return null;
  const observedClose = row.outcome?.observed_close;
  const observedReturn = row.observed_return;
  const interval = row.interval_80_price;
  if (observedClose === undefined || observedClose === null || observedReturn === null || interval === null) return null;
  const origin = observedClose / (1 + observedReturn);
  if (!Number.isFinite(origin) || origin <= 0 || origin > MAX_PRICE) return null;
  const lowPercent = ((interval.low / origin) - 1) * 100;
  const highPercent = ((interval.high / origin) - 1) * 100;
  const observedPercent = observedReturn * 100;
  if ([lowPercent, highPercent, observedPercent].some((value) => !Number.isFinite(value) || Math.abs(value) > MAX_PLOT_RETURN_PERCENT) || lowPercent > highPercent) return null;
  return { row, lowPercent, highPercent, observedPercent };
}

function formatAxisPercent(value: number): string {
  return value === 0 ? "0%" : `${value.toFixed(0)}%`;
}

function plotPointDescription(point: PlotPoint): string {
  return `${point.row.symbol}, target ${formatDateLabel(point.row.target_timestamp)}; predicted 80% return range ${formatPercentPoints(point.lowPercent)} to ${formatPercentPoints(point.highPercent)}; observed return ${formatPercentPoints(point.observedPercent)}; observed ${point.row.interval_80_covered ? "inside" : "outside"} the range.`;
}

function ReturnEvidencePlot({ records, titleId }: { records: readonly ReportOutcome[]; titleId: string }) {
  const scored = records
    .filter((row) => row.state === "scored")
    .slice()
    .sort((left, right) => compareTarget(left.target_timestamp, right.target_timestamp));
  const plot = getReportCardReturnPlot(scored.map((row) => ({
    row,
    observedClose: row.outcome?.observed_close,
    observedReturn: row.observed_return,
    interval: row.interval_80_price,
    intervalCovered: row.interval_80_covered,
  })), PLOT_LIMIT, MAX_PRICE, MAX_PLOT_RETURN_PERCENT);
  const plotted = plot.plotted;
  const omissionText = describeReportCardReturnPlotOmissions(plot.omissions);
  const values = plotted.flatMap((point) => [point.lowPercent, point.highPercent, point.observedPercent]);
  const axis = getReportCardReturnAxis(values);
  const symbolCounts = new Map<string, number>();
  for (const point of plotted) symbolCounts.set(point.row.symbol, (symbolCounts.get(point.row.symbol) ?? 0) + 1);
  const latest = plotted[plotted.length - 1];

  return (
    <figure className={styles.plotFigure}>
      <figcaption id={titleId}>Forecast outcome returns</figcaption>
      {plotted.length === 0 ? (
        <div className={styles.plotEmpty}>
          {plot.status === "no_scored_outcomes"
            ? "No scored outcomes are available in this view."
            : <>No scored outcomes in this view can be plotted. {omissionText}</>}
        </div>
      ) : (
        <>
          {latest ? (
            <section className={styles.featuredResult} aria-label="Featured forecast result">
              <div className={styles.featuredHeading}>
                <div><p className={styles.kicker}>Featured forecast result</p><h4>{latest.row.symbol}</h4></div>
                <span className={styles.featuredStatus} data-inside-range={latest.row.interval_80_covered ? "true" : "false"}>{latest.row.interval_80_covered ? "Within range" : "Outside range"}</span>
              </div>
              <dl className={styles.featuredFacts}>
                <div><dt>Target date</dt><dd>{formatDateLabel(latest.row.target_timestamp)}</dd></div>
                <div><dt>Predicted 80% range</dt><dd>{formatPercentPoints(latest.lowPercent)} to {formatPercentPoints(latest.highPercent)}</dd></div>
                <div><dt>Observed return</dt><dd>{formatPercentPoints(latest.observedPercent)}</dd></div>
              </dl>
              <svg className={styles.featuredRange} viewBox="0 0 1000 100" preserveAspectRatio="none" role="img" aria-label={plotPointDescription(latest)}>
                <line className={styles.zeroLine} x1={axis.position(0)} x2={axis.position(0)} y1="10" y2="90" vectorEffect="non-scaling-stroke" />
                <line className={styles.intervalRangeOutline} x1={axis.position(latest.lowPercent)} x2={axis.position(latest.highPercent)} y1="50" y2="50" vectorEffect="non-scaling-stroke" />
                <line className={styles.intervalRange} x1={axis.position(latest.lowPercent)} x2={axis.position(latest.highPercent)} y1="50" y2="50" vectorEffect="non-scaling-stroke" />
                <line className={styles.pointHalo} x1={axis.position(latest.observedPercent)} x2={axis.position(latest.observedPercent)} y1="50" y2="50" vectorEffect="non-scaling-stroke" />
                <line className={latest.row.interval_80_covered ? styles.coveredPoint : styles.outsidePoint} x1={axis.position(latest.observedPercent)} x2={axis.position(latest.observedPercent)} y1="50" y2="50" vectorEffect="non-scaling-stroke" />
              </svg>
              <div className={styles.featuredAxis} aria-hidden="true"><span>{formatAxisPercent(-axis.maximum)}</span><span>0%</span><span>{formatAxisPercent(axis.maximum)}</span></div>
              <p className={styles.featuredTarget}>Most recent result shown: {formatDateLabel(latest.row.target_timestamp)}.</p>
            </section>
          ) : null}
          <div className={styles.plotChart} role="group" aria-label="Outcome return chart">
            <div className={styles.plotAxisRow} aria-hidden="true">
              <span className={styles.plotAxisLead}>Instrument · target</span>
              <div className={styles.plotAxisTrack}>{axis.ticks.map((tick) => <span className={styles.plotAxisTick} key={tick}>{formatAxisPercent(tick)}</span>)}</div>
            </div>
            <div className={styles.plotRows} role="region" aria-label="Scrollable return chart rows" tabIndex={0}>
              {plotted.map((point) => {
                const repeatedSymbol = (symbolCounts.get(point.row.symbol) ?? 0) > 1;
                const date = formatDateLabel(point.row.target_timestamp);
                return (
                  <div className={styles.plotRow} data-testid="report-chart-row" key={point.row.result_id}>
                    <span className={styles.plotRowLabel}><strong>{point.row.symbol}</strong>{repeatedSymbol ? <small>{date}</small> : null}</span>
                    <svg className={styles.plotRowRange} viewBox="0 0 1000 100" preserveAspectRatio="none" role="img" aria-label={plotPointDescription(point)}>
                      {axis.ticks.map((tick) => <line className={tick === 0 ? styles.zeroLine : styles.gridLine} key={tick} x1={axis.position(tick)} x2={axis.position(tick)} y1="8" y2="92" vectorEffect="non-scaling-stroke" />)}
                      <line className={styles.intervalRangeOutline} x1={axis.position(point.lowPercent)} x2={axis.position(point.highPercent)} y1="50" y2="50" vectorEffect="non-scaling-stroke" />
                      <line className={styles.intervalRange} x1={axis.position(point.lowPercent)} x2={axis.position(point.highPercent)} y1="50" y2="50" vectorEffect="non-scaling-stroke" />
                      <line className={styles.pointHalo} x1={axis.position(point.observedPercent)} x2={axis.position(point.observedPercent)} y1="50" y2="50" vectorEffect="non-scaling-stroke" />
                      <line className={point.row.interval_80_covered ? styles.coveredPoint : styles.outsidePoint} x1={axis.position(point.observedPercent)} x2={axis.position(point.observedPercent)} y1="50" y2="50" vectorEffect="non-scaling-stroke" />
                    </svg>
                  </div>
                );
              })}
            </div>
            <div className={styles.plotAxisTitle}>Return over forecast horizon</div>
          </div>
          <div className={styles.plotLegend} aria-hidden="true">
            <span><i className={styles.intervalSwatch} />Predicted 80% return range</span>
            <span><i className={styles.coveredSwatch} />Observed return inside range</span>
            <span><i className={styles.outsideSwatch} />Observed return outside range</span>
          </div>
          <p className={styles.plotCaption}>The horizontal axis is return over each forecast horizon. Every interval and observed point is normalized against that row’s inferred origin price, so different symbols and currencies are not compared as native prices. Rows are ordered by target date; repeated symbols include their target date. The chart shows at most the latest {PLOT_LIMIT} rows.</p>
          <details className={styles.plotTextAlternative}>
            <summary>Read plotted values as text</summary>
            <ol>
              {plotted.map((point) => (
                <li key={point.row.result_id}>
                  <strong>{point.row.symbol}</strong> · {formatDateLabel(point.row.target_timestamp)} · predicted 80% return range {formatPercentPoints(point.lowPercent)} to {formatPercentPoints(point.highPercent)} · observed return {formatPercentPoints(point.observedPercent)} · {point.row.interval_80_covered ? "inside range" : "outside range"}
                </li>
              ))}
            </ol>
            {omissionText ? <p>{omissionText}</p> : null}
          </details>
        </>
      )}
    </figure>
  );
}

function stateLabel(state: ReportOutcomeState): string {
  switch (state) {
    case "scored": return "Scored";
    case "pending": return "Pending";
    case "unavailable": return "Unavailable";
    case "disputed": return "Under review";
    case "incomparable": return "Incomparable";
  }
}

function outcomeDirection(row: ReportOutcome): string {
  if (row.direction_correct === true) return `Correct · ${row.predicted_class ?? "direction"}`;
  if (row.direction_correct === false) return `Incorrect · ${row.predicted_class ?? "direction"}`;
  return row.state === "scored" ? "No unique direction prediction" : "Not scored";
}

function normalizedRangeLabel(row: ReportOutcome): string {
  const point = asPlotPoint(row);
  return point ? `${formatPercentPoints(point.lowPercent)} to ${formatPercentPoints(point.highPercent)}` : "Unavailable";
}

export function ReportCardWorkspace({ state, summary, errorMessage, statusMessage, onRetry }: ReportCardWorkspaceProps) {
  const headingId = useId();
  const plotId = useId();
  const [selectedGroupKey, setSelectedGroupKey] = useState("");
  const [selectedSymbol, setSelectedSymbol] = useState("");
  const [period, setPeriod] = useState<DatePeriod>("all");
  const [fromDate, setFromDate] = useState("");
  const [throughDate, setThroughDate] = useState("");
  const [page, setPage] = useState(0);
  const itemValidation = validateReportItems(summary?.items);
  const validItems = itemValidation.rows;
  const responseTooLarge = itemValidation.status === "too_large";
  const malformedItems = itemValidation.status === "malformed";
  const omittedRows = itemValidation.omitted;
  const groups = groupChoices(validItems);
  const selectedGroup = groups.find((group) => groupKey(group) === selectedGroupKey) ?? groups[0] ?? null;
  const activeGroupKey = selectedGroup ? groupKey(selectedGroup) : "";
  const baseRows = selectedGroup ? validItems.filter((row) => groupKey(row) === activeGroupKey && (!selectedSymbol || row.symbol === selectedSymbol)) : [];
  const dateError = dateRangeError(fromDate, throughDate);
  const asOf = summary ? awareTimestamp(summary.as_of) : null;
  const selectedDays = period === "all" ? null : Number(period);
  const periodNeedsAsOf = selectedDays !== null && asOf === null;
  const filterError = dateError ?? (periodNeedsAsOf ? "The report timestamp is invalid, so this period cannot be calculated safely." : null);
  const fromEpoch = fromDate ? parseDate(fromDate) : null;
  const throughEpoch = throughDate ? parseDate(throughDate) : null;
  const periodStart = selectedDays !== null && asOf !== null ? Date.parse(asOf) - selectedDays * 86_400_000 : null;
  const usesTargetDateFilter = selectedDays !== null || Boolean(fromDate) || Boolean(throughDate);
  const excludedWithoutTarget = usesTargetDateFilter ? baseRows.filter((row) => row.target_timestamp === null).length : 0;
  const filteredRows = filterError ? [] : baseRows.filter((row) => {
    if (!usesTargetDateFilter) return true;
    if (!row.target_timestamp) return false;
    const target = Date.parse(row.target_timestamp);
    if (selectedDays !== null && (periodStart === null || target < periodStart || target > Date.parse(asOf as string))) return false;
    if (fromEpoch !== null && target < fromEpoch) return false;
    if (throughEpoch !== null && target >= throughEpoch + 86_400_000) return false;
    return true;
  });
  const orderedRows = filteredRows.slice().sort((left, right) => compareTarget(right.target_timestamp, left.target_timestamp));
  const pageCount = Math.max(1, Math.ceil(orderedRows.length / TABLE_PAGE_SIZE));
  const currentPage = Math.min(page, pageCount - 1);
  const pageRows = orderedRows.slice(currentPage * TABLE_PAGE_SIZE, (currentPage + 1) * TABLE_PAGE_SIZE);
  const scoredRows = orderedRows.filter((row) => row.state === "scored");
  const pendingCount = orderedRows.filter((row) => row.state === "pending").length;
  const unavailableCount = orderedRows.filter((row) => row.state === "unavailable").length;
  const incomparableCount = orderedRows.filter((row) => row.state === "incomparable").length;
  const disputedCount = orderedRows.filter((row) => row.state === "disputed").length;
  const directionRows = scoredRows.filter((row) => row.direction_correct !== null);
  const directionCorrect = directionRows.filter((row) => row.direction_correct === true).length;
  const intervalRows = scoredRows.filter((row) => row.interval_80_covered !== null);
  const intervalsCovered = intervalRows.filter((row) => row.interval_80_covered === true).length;
  const fiveMinuteRows = orderedRows.filter((row) => row.five_minute && row.state === "scored");
  const fiveMinuteProvider = fiveMinuteRows.filter((row) => row.source?.method === "provider_bar").length;
  const fiveMinuteManual = fiveMinuteRows.filter((row) => row.source?.method === "manual_review").length;
  const symbols = [...new Set(validItems.map((row) => row.symbol))].sort((left, right) => left.localeCompare(right));
  const boundaryDown = summary ? boundedText(summary.direction_boundaries?.down, 120) : null;
  const boundaryUnchanged = summary ? boundedText(summary.direction_boundaries?.unchanged, 120) : null;
  const boundaryUp = summary ? boundedText(summary.direction_boundaries?.up, 120) : null;
  const sampleLimit = summary ? boundedText(summary.sample_limit, 400) : null;
  const stateMessage = state === "loading"
    ? "Loading recorded forecast outcomes…"
    : state === "error"
      ? `${errorMessage || "The report card could not be loaded."}${summary ? " Previously loaded values may be stale." : ""}`
      : state === "unavailable"
        ? "The outcome service is unavailable. Previously loaded values may be stale."
        : statusMessage || (summary ? `As of ${formatInstant(asOf)}.` : "No report is available.");
  const changeGroup = (value: string) => { setSelectedGroupKey(value); setPage(0); };
  const changeSymbol = (value: string) => { setSelectedSymbol(value); setPage(0); };
  const changePeriod = (value: string) => { setPeriod(value as DatePeriod); setPage(0); };
  const changeFrom = (value: string) => { setFromDate(value); setPage(0); };
  const changeThrough = (value: string) => { setThroughDate(value); setPage(0); };

  return (
    <section className={styles.workspace} aria-labelledby={headingId} aria-busy={state === "loading"}>
      <header className={styles.pageHead}>
        <div>
          <p className={styles.kicker}>Saved forecast outcomes</p>
          <h2 id={headingId}>Report card</h2>
          <p>Review recorded forecast results with their source evidence and scoring denominators.</p>
        </div>
        <div className={styles.pageHeadActions}>
          <span className={styles.scopeBadge}>Recorded outcomes · not a backtest</span>
          {onRetry ? <button className={styles.secondaryButton} type="button" disabled={state === "loading"} onClick={onRetry}>Refresh report</button> : null}
        </div>
      </header>

      <div className={state === "error" ? styles.errorBanner : styles.stateBanner} role={state === "error" ? "alert" : "status"} aria-live={state === "error" ? "assertive" : "polite"}>
        {stateMessage}
        {state === "error" && onRetry ? <button className={styles.secondaryButton} type="button" onClick={onRetry}>Retry report</button> : null}
      </div>

      {state === "loading" && !summary ? (
        <div className={styles.emptyState} role="status">Loading report data…</div>
      ) : state !== "ready" && !summary ? (
        <div className={styles.emptyState}>Report data is unavailable. No performance values are being inferred.</div>
      ) : !summary ? (
        <div className={styles.emptyState}>
          <strong>No recorded outcomes to score</strong>
          <span>Metrics appear only after an owner-scoped forecast has a published, comparable outcome.</span>
        </div>
      ) : (
        <>
          <div className={styles.controls} role="group" aria-label="Report filters">
            <label>
              <span>Model and horizon</span>
              <select value={activeGroupKey} onChange={(event) => changeGroup(event.target.value)}>
                {groups.map((group) => <option key={groupKey(group)} value={groupKey(group)}>{group.model_version} · {horizonLabel(group.horizon, group.five_minute)}</option>)}
              </select>
            </label>
            <label>
              <span>Symbol</span>
              <select value={selectedSymbol} onChange={(event) => changeSymbol(event.target.value)}>
                <option value="">All symbols</option>
                {symbols.map((symbol) => <option key={symbol} value={symbol}>{symbol}</option>)}
              </select>
            </label>
            <label>
              <span>Period</span>
              <select value={period} onChange={(event) => changePeriod(event.target.value)}>
                <option value="all">All recorded dates</option>
                <option value="7">Last 7 days</option>
                <option value="30">Last 30 days</option>
                <option value="90">Last 90 days</option>
                <option value="365">Last year</option>
              </select>
            </label>
            <label>
              <span>Target from (UTC)</span>
              <input type="date" value={fromDate} onChange={(event) => changeFrom(event.target.value)} />
            </label>
            <label>
              <span>Target through (UTC)</span>
              <input type="date" value={throughDate} onChange={(event) => changeThrough(event.target.value)} />
            </label>
          </div>
          {filterError ? <p className={styles.filterError} role="alert">{filterError} No filtered rows or derived values are shown.</p> : null}
          {malformedItems ? <p className={styles.filterError} role="alert">The report response is malformed or unavailable: “items” must be an array. No rows or metrics are shown.</p> : responseTooLarge ? <p className={styles.filterError} role="alert">This response exceeds the safe limit of {MAX_INPUT_ROWS} rows. The entire response is excluded from metrics and charts.</p> : omittedRows > 0 ? <p className={styles.dataNotice} role="status">{omittedRows} malformed or duplicate result row{omittedRows === 1 ? " was" : "s were"} omitted before calculating filters, charts, and denominators.</p> : null}
          {excludedWithoutTarget > 0 && !filterError ? <p className={styles.dataNotice} role="status">{excludedWithoutTarget} row{excludedWithoutTarget === 1 ? " has" : "s have"} no target timestamp and was omitted by the date filter.</p> : null}

          {malformedItems ? (
            <div className={styles.emptyState} role="alert">
              <strong>Report data unavailable</strong>
              <span>The outcome list is missing or has the wrong response type. Reload the report before relying on any values.</span>
            </div>
          ) : responseTooLarge ? (
            <div className={styles.emptyState}>
              <strong>Report data unavailable</strong>
              <span>The response was excluded because it exceeded the safe row limit. No partial metrics are presented.</span>
            </div>
          ) : selectedGroup ? (
            <>
              <div className={styles.metricGrid} role="group" aria-label="Selected report metrics">
                <article className={styles.metricCard}>
                  <span>Forecasts in scope</span>
                  <strong>{validCount(orderedRows.length) ?? "Unavailable"}</strong>
                  <small>Validated rows after all selected filters</small>
                </article>
                <article className={styles.metricCard}>
                  <span>Scored outcomes</span>
                  <strong>{validCount(scoredRows.length) ?? "Unavailable"}</strong>
                  <small>{scoredRows.length} scored / {orderedRows.length} rows in this scope</small>
                </article>
                <article className={styles.metricCard}>
                  <span>Direction correct</span>
                  <strong>{percent(directionCorrect, directionRows.length)}</strong>
                  <small>{directionCorrect} correct / {directionRows.length} scored direction comparisons</small>
                </article>
                <article className={styles.metricCard}>
                  <span>80% range coverage</span>
                  <strong>{percent(intervalsCovered, intervalRows.length)}</strong>
                  <small>{intervalsCovered} covered / {intervalRows.length} scored comparable intervals</small>
                </article>
              </div>

              <div className={styles.evidenceGrid}>
                <section className={styles.panel} aria-labelledby={`${headingId}-plot-heading`}>
                  <h3 id={`${headingId}-plot-heading`} className={styles.sectionHeading}>Outcome evidence · {horizonLabel(selectedGroup.horizon, selectedGroup.five_minute)}</h3>
                  <ReturnEvidencePlot records={orderedRows} titleId={plotId} />
                </section>
                <aside className={styles.explanation} aria-labelledby={`${headingId}-explanation`}>
                  <div className={styles.statusGrid} role="group" aria-label="Outcome states in selected scope">
                    <article><span>Pending</span><strong>{pendingCount}</strong><small>Waiting for supported target-session evidence</small></article>
                    <article><span>Unavailable</span><strong>{unavailableCount + incomparableCount}</strong><small>{unavailableCount} unavailable · {incomparableCount} incomparable</small></article>
                    <article><span>Under review</span><strong>{disputedCount}</strong><small>Disputed rows stay outside scored denominators</small></article>
                  </div>
                  <a className={styles.reviewOutcomes} href={`#${headingId}-outcomes`}>Review outcomes</a>
                  <details className={styles.methodDisclosure}>
                    <summary>View scoring method</summary>
                    <strong>How recorded outcomes are scored</strong>
                    <span>Daily-or-longer outcomes can be scored automatically when a supported target-session source is available. Five-minute rows require supported saved evidence; when provider evidence is missing or unsuitable, explicit manual review is required. This report is not a backtest.</span>
                  </details>
                  <p className={styles.kicker}>How to read this</p>
                  <h3 id={`${headingId}-explanation`}>Recorded, not simulated</h3>
                  <p>This report scores saved forecasts against published target outcomes. It does not run or summarize a historical walk-forward backtest.</p>
                  <dl className={styles.explanationFacts}>
                    <div><dt>Target dates</dt><dd>{fromDate || "Any start"} – {throughDate || (period === "all" ? "Any end" : `Last ${period} days`)}</dd></div>
                    <div><dt>Symbol</dt><dd>{selectedSymbol || "All symbols"}</dd></div>
                    <div><dt>Horizon</dt><dd>{horizonLabel(selectedGroup.horizon, selectedGroup.five_minute)}</dd></div>
                    <div><dt>Model version</dt><dd>{selectedGroup.model_version}</dd></div>
                    <div><dt>Direction denominator</dt><dd>{directionRows.length} scored unique predictions</dd></div>
                    <div><dt>Interval denominator</dt><dd>{intervalRows.length} scored comparable intervals</dd></div>
                    {selectedGroup.five_minute ? <div><dt>Five-minute source</dt><dd>{fiveMinuteProvider} provider-bar rows · {fiveMinuteManual} manual reviews</dd></div> : null}
                  </dl>
                  {sampleLimit ? <p className={styles.limitations}>{sampleLimit}</p> : <p className={styles.limitations}>Scoring limits are unavailable in this response.</p>}
                  {boundaryDown && boundaryUnchanged && boundaryUp ? <p className={styles.limitations}>Direction boundaries: {boundaryDown}; {boundaryUnchanged}; {boundaryUp}.</p> : <p className={styles.limitations}>Direction boundary details are unavailable.</p>}
                </aside>
              </div>

              <section className={styles.panel} aria-labelledby={`${headingId}-outcomes`}>
                <div className={styles.tableHeading}>
                  <div>
                    <p className={styles.kicker}>Owner-scoped saved rows</p>
                    <h3 id={`${headingId}-outcomes`}>Recent outcomes</h3>
                  </div>
                  <span>{orderedRows.length} records after selected filters</span>
                </div>
                {orderedRows.length === 0 ? <div className={styles.emptyState}>No rows match the selected model, horizon, symbol, and target-date filters.</div> : (
                  <>
                    <div className={styles.tableWrap}>
                      <table className={styles.outcomesTable}>
                        <caption>Metric denominators are recomputed from these validated, filtered rows. Unscored rows do not enter scored metrics.</caption>
                        <thead><tr><th scope="col">Instrument</th><th scope="col">Target session</th><th scope="col">Status</th><th scope="col">Direction</th><th scope="col">Predicted 80% range</th><th scope="col">Observed return</th></tr></thead>
                        <tbody>
                          {pageRows.map((row) => (
                            <tr key={row.result_id}>
                              <td data-label="Instrument"><strong>{row.symbol}</strong><small>{row.model_version} · {horizonLabel(row.horizon, row.five_minute)}</small></td>
                              <td data-label="Target session"><time dateTime={row.target_timestamp ?? undefined}>{formatInstant(row.target_timestamp)}</time></td>
                              <td data-label="Status"><span className={styles.outcomeState} data-state={row.state}>{stateLabel(row.state)}</span><small>{row.reason || "No additional status detail"}</small></td>
                              <td data-label="Direction">{row.state === "scored" ? outcomeDirection(row) : "Not scored"}</td>
                              <td data-label="Predicted 80% range">{row.state === "scored" ? normalizedRangeLabel(row) : "Not scored"}<small>{row.state !== "scored" ? "Scoring evidence unavailable" : row.interval_80_covered === true ? "Observed inside range" : row.interval_80_covered === false ? "Observed outside range" : "Coverage not scored"}</small></td>
                              <td data-label="Observed return">{row.state === "scored" ? formatReturn(row.observed_return) : "Not scored"}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                    {pageCount > 1 ? <nav className={styles.pagination} aria-label="Outcome pages">
                      <button className={styles.secondaryButton} type="button" disabled={currentPage === 0} onClick={() => setPage((value) => Math.max(0, value - 1))}>Previous</button>
                      <span>Page {currentPage + 1} of {pageCount}</span>
                      <button className={styles.secondaryButton} type="button" disabled={currentPage + 1 >= pageCount} onClick={() => setPage((value) => Math.min(pageCount - 1, value + 1))}>Next</button>
                    </nav> : null}
                  </>
                )}
              </section>
            </>
          ) : (
            <div className={styles.emptyState}>
              {itemValidation.inputCount === 0 ? <><strong>No recorded outcomes to score</strong><span>Metrics appear after an owner-scoped forecast has a published, comparable target outcome.</span></> : <><strong>No valid report rows</strong><span>Validated outcome data is unavailable. Invalid rows are excluded from all metrics.</span></>}
            </div>
          )}
        </>
      )}
    </section>
  );
}
