"use client";

import { useEffect, useState } from "react";

import styles from "./workspace.module.css";

type HistoryItem = {
  id: number;
  canonical_symbol: string;
  display_name: string;
  status: string;
  submitted_at: string;
  forecast_available: boolean;
  horizons: string[];
  outcome_count: number;
};
type SavedResult = {
  horizon: string;
  target_timestamp?: string;
  availability?: string;
  direction_probabilities?: { down?: number; flat?: number; up?: number };
  magnitude_intervals?: Array<{ level: number; percent: { low: number; high: number }; price: { low: number; high: number } }>;
};
type SavedForecast = {
  event: { id: number };
  input: { canonical_symbol: string; display_name?: string; model?: { name?: string; version?: string }; quality?: string; provider?: string; provider_as_of?: string; currency?: string };
  results: SavedResult[];
};
type LoadState = { status: "loading" } | { status: "error"; message: string } | { status: "ready"; items: HistoryItem[]; recent: Map<number, SavedForecast> };

function record(value: unknown): Record<string, unknown> {
  return value !== null && typeof value === "object" ? value as Record<string, unknown> : {};
}

function historyItems(value: unknown): HistoryItem[] {
  const items = record(value).items;
  if (!Array.isArray(items)) throw new Error("The local ledger response was malformed.");
  return items.map((raw) => {
    const item = record(raw);
    if (typeof item.id !== "number" || typeof item.status !== "string") throw new Error("A ledger row was malformed.");
    return {
      id: item.id,
      canonical_symbol: typeof item.canonical_symbol === "string" ? item.canonical_symbol : String(item.normalized_symbol ?? item.submitted_symbol ?? "Unknown"),
      display_name: typeof item.display_name === "string" ? item.display_name : "",
      status: item.status,
      submitted_at: typeof item.submitted_at === "string" ? item.submitted_at : "",
      forecast_available: item.forecast_available === true,
      horizons: Array.isArray(item.horizons) ? item.horizons.filter((entry): entry is string => typeof entry === "string") : [],
      outcome_count: typeof item.outcome_count === "number" ? item.outcome_count : 0,
    };
  });
}

function savedForecast(value: unknown): SavedForecast {
  const data = record(value);
  const event = record(data.event);
  const input = record(data.input);
  if (typeof event.id !== "number" || typeof input.canonical_symbol !== "string" || !Array.isArray(data.results)) throw new Error("A saved forecast was malformed.");
  return data as SavedForecast;
}

async function fetchJson(path: string, signal: AbortSignal): Promise<unknown> {
  const response = await fetch(path, { signal, headers: { Accept: "application/json" } });
  const value: unknown = await response.json().catch(() => null);
  if (!response.ok) throw new Error(`Local research request failed (${response.status}).`);
  return value;
}

function time(value?: string) {
  return value && !Number.isNaN(Date.parse(value)) ? new Date(value).toLocaleString() : "Unavailable";
}

function probability(value?: number) {
  return typeof value === "number" && Number.isFinite(value)
    ? new Intl.NumberFormat(undefined, { style: "percent", maximumFractionDigits: 1 }).format(value)
    : "Unavailable";
}

function horizon(value: string) {
  const names: Record<string, string> = {
    close_to_close: "Next close · daily origin",
    completed_5m_to_close: "Next close · completed 5-minute origin",
    five_min_forward: "Next completed 5-minute bar",
    daily_1: "1 trading session",
    weekly_5: "5 trading sessions",
    monthly_21: "21 trading sessions",
    quarterly_63: "63 trading sessions",
  };
  return names[value] ?? value.replaceAll("_", " ");
}

function outcomeStatus(item: HistoryItem, saved?: SavedForecast) {
  if (!item.forecast_available) return "No forecast saved";
  if (item.outcome_count > 0) return `${item.outcome_count} recorded outcome${item.outcome_count === 1 ? "" : "s"}`;
  const targets = saved?.results.map((result) => result.target_timestamp).filter((value): value is string => Boolean(value)) ?? [];
  if (targets.length && targets.every((value) => Date.parse(value) > Date.now())) return "Targets pending · no outcome recorded";
  return "No outcome recorded";
}

// Read-only comparisons use immutable saved results. No provider call or recomputation occurs.
export function ResearchWorkspace() {
  const [state, setState] = useState<LoadState>({ status: "loading" });
  const [attempt, setAttempt] = useState(0);
  const [symbol, setSymbol] = useState("");
  const [eventA, setEventA] = useState("");
  const [eventB, setEventB] = useState("");
  const [savedA, setSavedA] = useState<SavedForecast | null>(null);
  const [savedB, setSavedB] = useState<SavedForecast | null>(null);
  const [horizonA, setHorizonA] = useState("");
  const [horizonB, setHorizonB] = useState("");
  const [compareError, setCompareError] = useState("");

  useEffect(() => {
    const request = new AbortController();
    setState({ status: "loading" });
    void (async () => {
      try {
        const items = historyItems(await fetchJson("/api/v1/history?page_size=100", request.signal));
        const recent = new Map<number, SavedForecast>();
        await Promise.all(items.slice(0, 5).filter((item) => item.forecast_available).map(async (item) => {
          try {
            recent.set(item.id, savedForecast(await fetchJson(`/api/v1/saved-forecasts/${item.id}`, request.signal)));
          } catch {
            // The ledger row remains visible if an individual saved detail cannot be loaded.
          }
        }));
        if (!request.signal.aborted) setState({ status: "ready", items, recent });
      } catch (error) {
        if (!request.signal.aborted) setState({ status: "error", message: error instanceof Error ? error.message : "Recent research is unavailable." });
      }
    })();
    return () => request.abort();
  }, [attempt]);

  const available = state.status === "ready" ? state.items.filter((item) => item.forecast_available) : [];
  const symbols = [...new Set(available.map((item) => item.canonical_symbol))];
  const selectedSymbol = symbol || symbols[0] || "";
  const candidates = available.filter((item) => item.canonical_symbol === selectedSymbol);
  const selectedA = candidates.some((item) => String(item.id) === eventA) ? eventA : String(candidates[0]?.id ?? "");
  const selectedB = candidates.some((item) => String(item.id) === eventB && String(item.id) !== selectedA)
    ? eventB : String(candidates.find((item) => String(item.id) !== selectedA)?.id ?? "");

  useEffect(() => {
    if (!selectedA || !selectedB) {
      setSavedA(null);
      setSavedB(null);
      return;
    }
    const request = new AbortController();
    setSavedA(null);
    setSavedB(null);
    setCompareError("");
    void (async () => {
      try {
        const [left, right] = await Promise.all([
          fetchJson(`/api/v1/saved-forecasts/${selectedA}`, request.signal),
          fetchJson(`/api/v1/saved-forecasts/${selectedB}`, request.signal),
        ]);
        const a = savedForecast(left);
        const b = savedForecast(right);
        if (a.input.canonical_symbol !== b.input.canonical_symbol || a.input.canonical_symbol !== selectedSymbol) throw new Error("Saved events do not share an instrument.");
        if (request.signal.aborted) return;
        setSavedA(a);
        setSavedB(b);
        setHorizonA(a.results[0]?.horizon ?? "");
        setHorizonB(b.results[0]?.horizon ?? "");
      } catch (error) {
        if (!request.signal.aborted) setCompareError(error instanceof Error ? error.message : "Saved comparison is unavailable.");
      }
    })();
    return () => request.abort();
  }, [selectedA, selectedB, selectedSymbol]);

  const resultA = savedA?.results.find((result) => result.horizon === horizonA);
  const resultB = savedB?.results.find((result) => result.horizon === horizonB);
  const sameHorizon = Boolean(resultA && resultB && resultA.horizon === resultB.horizon && resultA.target_timestamp === resultB.target_timestamp);

  return <div className={styles.researchWorkspace}>
    <section className={styles.recent} aria-labelledby="recent-research-heading" aria-busy={state.status === "loading"}>
      <div className={styles.workspaceHead}><div><p className="panel-kicker">Local ledger</p><h2 id="recent-research-heading">Recent research</h2><p>Five latest requests from the newest 100 ledger events. Outcomes appear only when recorded in the append-only ledger.</p></div><button className="secondary" type="button" onClick={() => setAttempt((value) => value + 1)}>Refresh records</button></div>
      {state.status === "loading" && <p role="status">Loading recent requests…</p>}
      {state.status === "error" && <div className="error-panel" role="alert"><p>{state.message}</p><button className="secondary" type="button" onClick={() => setAttempt((value) => value + 1)}>Retry</button></div>}
      {state.status === "ready" && state.items.length === 0 && <div className="empty-state"><h3>No recorded research</h3><p>Run a forecast to create the first immutable event.</p></div>}
      {state.status === "ready" && state.items.length > 0 && <ol className={styles.recentList}>{state.items.slice(0, 5).map((item) => <li key={item.id}>
        <div><strong>{item.canonical_symbol}</strong><span>{item.display_name || "Name unavailable"} · event #{item.id}</span></div>
        <div><span>{item.status} · {time(item.submitted_at)}</span><small>{item.horizons.map(horizon).join(", ") || "No forecast result"} · {outcomeStatus(item, state.recent.get(item.id))}</small></div>
        {item.forecast_available && <a className="text-link" href={`/?event_id=${item.id}#result-section`}>Open saved result</a>}
      </li>)}</ol>}
    </section>
    <section className={styles.compare} aria-labelledby="compare-heading">
      <div className={styles.workspaceHead}><div><p className="panel-kicker">Immutable results</p><h2 id="compare-heading">Compare saved forecasts</h2><p>Select two of the newest 100 ledger events for the same instrument. Values are reopened as saved; differing horizons and targets are shown side by side without a change claim.</p></div><span className="badge neutral">Provider-free replay</span></div>
      {state.status === "ready" && !symbols.length && <div className="empty-state"><h3>No saved forecasts in the latest 100 events</h3></div>}
      {state.status === "ready" && symbols.length > 0 && <div className={styles.compareControls}>
        <label>Instrument<select value={selectedSymbol} onChange={(event) => { setSymbol(event.target.value); setEventA(""); setEventB(""); }}>{symbols.map((value) => <option key={value} value={value}>{value}</option>)}</select></label>
        <label>First recorded event<select value={selectedA} onChange={(event) => setEventA(event.target.value)}>{candidates.map((item) => <option key={item.id} value={item.id}>#{item.id} · {time(item.submitted_at)}</option>)}</select></label>
        <label>Second recorded event<select value={selectedB} onChange={(event) => setEventB(event.target.value)} disabled={candidates.length < 2}>{candidates.filter((item) => String(item.id) !== selectedA).map((item) => <option key={item.id} value={item.id}>#{item.id} · {time(item.submitted_at)}</option>)}</select></label>
      </div>}
      {state.status === "ready" && candidates.length === 1 && <p className={styles.comparisonNote}>Only one saved event is available for {selectedSymbol}. A second run is needed for comparison.</p>}
      {selectedA && selectedB && !savedA && !compareError && <p role="status">Loading immutable saved events…</p>}
      {compareError && <div className="error-panel" role="alert">{compareError}</div>}
      {savedA && savedB && <><div className={styles.horizonControls}>
        <label>First horizon<select value={horizonA} onChange={(event) => setHorizonA(event.target.value)}>{savedA.results.map((result) => <option key={result.horizon} value={result.horizon}>{horizon(result.horizon)}</option>)}</select></label>
        <label>Second horizon<select value={horizonB} onChange={(event) => setHorizonB(event.target.value)}>{savedB.results.map((result) => <option key={result.horizon} value={result.horizon}>{horizon(result.horizon)}</option>)}</select></label>
      </div>
      <p className={styles.comparisonNote}>{sameHorizon ? "Same horizon and target: values can be compared directly." : "Different horizon or target: each probability and interval describes its own target. No performance or change is inferred."}</p>
      <div className={styles.comparisonGrid}>{[[savedA, resultA], [savedB, resultB]].map(([saved, result]) => {
        const item = saved as SavedForecast;
        const forecast = result as SavedResult | undefined;
        const interval = forecast?.magnitude_intervals?.[0];
        return <article key={item.event.id}>
          <span className="panel-kicker">Saved event #{item.event.id}</span><h3>{horizon(forecast?.horizon ?? "Unknown horizon")}</h3>
          <dl><div><dt>Target</dt><dd>{time(forecast?.target_timestamp)}</dd></div><div><dt>Availability</dt><dd>{forecast?.availability ?? "Unavailable"}</dd></div><div><dt>Model</dt><dd>{item.input.model?.name ?? "Unavailable"} · {item.input.model?.version ?? "Version unavailable"}</dd></div><div><dt>Quality</dt><dd>{item.input.quality ?? "Unavailable"}</dd></div><div><dt>Provider / as of</dt><dd>{item.input.provider ?? "Unavailable"} · {time(item.input.provider_as_of)}</dd></div></dl>
          {forecast?.direction_probabilities ? <div className={styles.probabilities}><span>Down <strong>{probability(forecast.direction_probabilities.down)}</strong></span><span>Unchanged <strong>{probability(forecast.direction_probabilities.flat)}</strong></span><span>Up <strong>{probability(forecast.direction_probabilities.up)}</strong></span></div> : <p>Direction probabilities unavailable.</p>}
          <p className={styles.interval}>{interval ? `${probability(interval.level)} interval · ${interval.percent.low.toFixed(2)}% to ${interval.percent.high.toFixed(2)}% · ${item.input.currency ?? "quote currency"} ${interval.price.low.toFixed(2)} to ${interval.price.high.toFixed(2)}` : "Magnitude interval unavailable."}</p>
          <a className="text-link" href={`/?event_id=${item.event.id}#result-section`}>Inspect full evidence</a>
        </article>;
      })}</div></>}
    </section>
  </div>;
}
