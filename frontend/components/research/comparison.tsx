// Reopening a saved snapshot never refreshes its provider observations.
"use client";

import { useEffect, useState } from "react";
import { researchRequest, type ResearchPage } from "./research-client";
import styles from "./research.module.css";

type Instrument = { symbol: string; asset_type: "stock" | "etf" };
type Compared = { symbol: string; identity: { display_name: string; asset_type: "stock" | "etf" }; currency: string; normalized: { date: string; value: number }[]; source: string; as_of: string; label: string; price_change: number | null; volatility: number | null; max_drawdown: number | null; sample_count: number; excluded_chart_sessions: number; missing_observations: number; common_sample_count: number; quality: string };
type Snapshot = { instruments: Compared[]; dates: string[]; range: string; basis: string; captured_at: string };
type Saved = { id: string; created_at: string; data: Snapshot };
type Preview = { preview_id: string; expires_at: string; data: Snapshot };
type Forecast = { event: { id: number }; input: { canonical_symbol: string }; results: { horizon: string; availability: string; target_timestamp?: string; direction_probabilities?: { up?: number; flat?: number; down?: number }; magnitude_intervals?: { level: number; percent: { low: number; high: number } }[] }[] };
const percent = (value: number | null | undefined) => typeof value === "number" && Number.isFinite(value) ? `${(value * 100).toFixed(1)}%` : "Unavailable";
function volatilityDisplay(item: Compared) {
  if (item.missing_observations > 0) {
    return "Unavailable — missing observations in the shared window";
  }
  return percent(item.volatility);
}

export function Comparison() {
  const [instruments, setInstruments] = useState<Instrument[]>([{ symbol: "", asset_type: "stock" }, { symbol: "", asset_type: "etf" }]);
  const [chartPage, setChartPage] = useState(1);
  const [range, setRange] = useState("1y"), [busy, setBusy] = useState(false), [error, setError] = useState("");
  const [preview, setPreview] = useState<Preview | null>(null), [snapshot, setSnapshot] = useState<Snapshot | null>(null), [savedId, setSavedId] = useState<string | null>(null), [saveKey, setSaveKey] = useState("");
  const [saved, setSaved] = useState<ResearchPage<Saved> | null>(null), [page, setPage] = useState(1), [refresh, setRefresh] = useState(0), [listError, setListError] = useState("");
  const [forecasts, setForecasts] = useState<Forecast[]>([]), [forecastErrors, setForecastErrors] = useState<string[]>([]);
  useEffect(() => {
    const controller = new AbortController(); setListError("");
    researchRequest<ResearchPage<Saved>>(`/api/v1/comparisons?page=${page}`, { signal: controller.signal }).then(data => { if (!controller.signal.aborted) setSaved(data); }).catch(reason => { if (!controller.signal.aborted) setListError(reason.message); });
    return () => controller.abort();
  }, [page, refresh]);
  function change(index: number, change: Partial<Instrument>) { setInstruments(old => old.map((item, i) => i === index ? { ...item, ...change } : item)); }
  async function compare() {
    if (busy) return; setBusy(true); setError("");
    try {
      const result = await researchRequest<Preview>("/api/v1/comparisons/preview", { method: "POST", body: JSON.stringify({ instruments, range }) });
      if (!Array.isArray(result.data?.instruments) || !Array.isArray(result.data?.dates)) throw new Error("The comparison response is malformed.");
      setChartPage(1); setPreview(result); setSnapshot(result.data); setSavedId(null); setSaveKey(crypto.randomUUID()); setForecasts([]); setForecastErrors([]);
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Comparison unavailable."); } finally { setBusy(false); }
  }
  async function save() {
    if (!preview || busy) return; setBusy(true); setError("");
    try { const item = await researchRequest<Saved>("/api/v1/comparisons", { method: "POST", body: JSON.stringify({ preview_id: preview.preview_id, idempotency_key: saveKey }) }); setSavedId(item.id); setRefresh(value => value + 1); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "The snapshot could not be saved."); } finally { setBusy(false); }
  }
  async function runForecasts() {
    if (!snapshot || busy) return; setBusy(true); setForecasts([]); setForecastErrors([]);
    for (const item of snapshot.instruments) {
      try { const result = await researchRequest<Forecast>("/api/v1/forecasts", { method: "POST", body: JSON.stringify({ symbol: item.symbol, asset_type: item.identity.asset_type, interval: "weekly" }) }); setForecasts(old => [...old, result]); }
      catch (reason) { setForecastErrors(old => [...old, `${item.symbol}: ${reason instanceof Error ? reason.message : "Forecast unavailable."}`]); }
    }
    setBusy(false);
  }
  const values = snapshot?.instruments.flatMap(item => item.normalized.map(point => point.value)) ?? [100];
  const low = Math.min(90, ...values), high = Math.max(110, ...values), span = high - low;
  const y = (value: number) => 280 - (value - low) / span * 230;
  return <main id="main" tabIndex={-1} className={styles.page}>
    <header className={styles.head}><div><p className="panel-kicker">Tools / Compare</p><h1>Compare your research options</h1><p>Review price history and risk measures side by side, with dated evidence.</p></div></header>
    <section className={styles.card} aria-label="Choose instruments"><div className={styles.controls}>{instruments.map((item, index) => <div className={styles.instrument} key={index}><label>Instrument {index + 1}<input aria-label={`Instrument ${index + 1} symbol`} maxLength={15} value={item.symbol} onChange={event => change(index, { symbol: event.target.value.toUpperCase() })} disabled={busy} /></label><label>Type<select aria-label={`Instrument ${index + 1} type`} value={item.asset_type} onChange={event => change(index, { asset_type: event.target.value as "stock" | "etf" })} disabled={busy}><option value="stock">Stock</option><option value="etf">ETF</option></select></label>{instruments.length > 2 && <button className="secondary" disabled={busy} onClick={() => setInstruments(old => old.filter((_, i) => i !== index))} aria-label={`Remove instrument ${index + 1}`}>Remove</button>}</div>)}</div><div className={styles.controls}><button className="secondary" disabled={busy || instruments.length === 4} onClick={() => setInstruments(old => [...old, { symbol: "", asset_type: "stock" }])}>Add instrument</button><label>Chart range<select value={range} onChange={event => setRange(event.target.value)} disabled={busy}><option value="5d">5 days</option><option value="1mo">1 month</option><option value="3mo">3 months</option><option value="6mo">6 months</option><option value="1y">1 year</option></select></label><button className="primary" disabled={busy || instruments.some(item => !item.symbol.trim())} onClick={compare}>{busy ? "Working…" : snapshot ? "Refresh comparison" : "Compare instruments"}</button></div></section>
    {error && <div role="alert" className={styles.error}>{error}</div>}{busy && <p role="status">Working on your requested research…</p>}
    {!snapshot && <div className={styles.card}><h2>Choose two to four instruments</h2><p>No forecast runs when you open this page. Select your instruments and request a comparison.</p></div>}
    {snapshot && <><div className={styles.notice}>{savedId ? "Saved immutable comparison" : "Unsaved comparison preview"} · Captured {new Date(snapshot.captured_at).toLocaleString()}<br />{snapshot.basis}</div><section className={styles.card}><h2>Normalized price history</h2><p className={styles.muted}>Starts at 100 on {snapshot.dates[0]} · daily closes in each instrument’s currency</p><div className={styles.chartGrid}><div className={styles.yAxis} role="group" aria-label="Index scale">{[high, (low + high) / 2, low].map(value => <span key={value}>{value.toFixed(0)}</span>)}</div><svg className={styles.chart} viewBox="0 0 900 325" role="img" aria-label="Normalized price history. Index scale and dates are beside the chart; exact values are in the table below."><line x1="55" y1="280" x2="840" y2="280" />{[low, (low + high) / 2, high].map(value => <line key={value} x1="55" y1={y(value)} x2="840" y2={y(value)} />)}{snapshot.instruments.map((item, index) => <polyline key={item.symbol} className={styles[`line${index}`]} points={item.normalized.map((point, i) => `${55 + i / Math.max(1, item.normalized.length - 1) * 785},${y(point.value)}`).join(" ")} />)}</svg></div><div className={styles.chartDates}><span>{snapshot.dates[0]}</span><span>{snapshot.dates.at(-1)}</span></div><ul>{snapshot.instruments.map((item, i) => <li key={item.symbol}>{item.symbol} · line {i + 1} · {item.source} · {new Date(item.as_of).toLocaleString()} · {item.label} · {item.common_sample_count} common chart sessions · {item.missing_observations} dates without an observation compared with the observed session union{item.quality === "discontinuity_detected" ? " · Discontinuity detected: affected metrics unavailable" : ""}</li>)}</ul><details><summary>Exact chart values</summary><div className={`${styles.tableWrap} ${styles.chartValues}`} role="region" aria-label="Exact chart values scroll region" tabIndex={0}><table className={styles.table}><caption>Normalized values on common observed sessions</caption><thead><tr><th>Date</th>{snapshot.instruments.map(item => <th key={item.symbol}>{item.symbol}</th>)}</tr></thead><tbody>{snapshot.dates.slice((chartPage - 1) * 5, chartPage * 5).map((day, i) => <tr key={day}><td data-label="Date">{day}</td>{snapshot.instruments.map(item => <td key={item.symbol} data-label={item.symbol}>{item.normalized[(chartPage - 1) * 5 + i].value.toFixed(2)}</td>)}</tr>)}</tbody></table></div><div className={styles.actions}><button className="secondary" disabled={chartPage === 1} onClick={() => setChartPage(value => value - 1)}>Previous chart values</button><span>Chart values page {chartPage} / {Math.ceil(snapshot.dates.length / 5)}</span><button className="secondary" disabled={chartPage * 5 >= snapshot.dates.length} onClick={() => setChartPage(value => value + 1)}>Next chart values</button></div></details></section>
      <section className={styles.card}><h2>Comparison metrics</h2><div className={styles.tableWrap}><table className={styles.table}><caption>Unadjusted price statistics over the shared period · volatility and drawdown use each instrument’s native sessions</caption><thead><tr>{["Instrument", "Price change", "Annualized volatility", "Maximum drawdown", "Currency", "Samples"].map(label => <th key={label}>{label}</th>)}</tr></thead><tbody>{snapshot.instruments.map(item => <tr key={item.symbol}><td data-label="Instrument"><strong>{item.symbol}</strong><br />{item.identity.display_name}</td><td data-label="Price change">{percent(item.price_change)}</td><td data-label="Annualized volatility">{volatilityDisplay(item)}</td><td data-label="Maximum drawdown">{percent(item.max_drawdown)}</td><td data-label="Currency">{item.currency}</td><td data-label="Samples">{item.sample_count}{item.excluded_chart_sessions > 0 ? ` · ${item.excluded_chart_sessions} native sessions outside common dates` : ""}</td></tr>)}</tbody></table></div></section>
      <section className={styles.card}><h2>Weekly forecast · 5 trading sessions</h2><p>Each forecast keeps its own exact origin and target. Differing targets are not directly comparable.</p><button className="primary" disabled={busy} onClick={runForecasts}>Run selected forecasts</button>{forecasts.map(item => <article key={item.event.id}><h3>{item.input.canonical_symbol} · Event #{item.event.id}</h3>{item.results.map(result => <p key={result.horizon}>{result.availability} · Target {result.target_timestamp ? new Date(result.target_timestamp).toLocaleString() : "Unavailable"} · Up {percent(result.direction_probabilities?.up)} · Down {percent(result.direction_probabilities?.down)}</p>)}</article>)}{forecastErrors.map(message => <p role="alert" key={message}>{message}</p>)}</section><div className={styles.actions}><button className="primary" disabled={busy || !preview || !!savedId} onClick={save}>{savedId ? "Comparison saved" : "Save comparison"}</button>{savedId && <><a href={`/api/v1/comparisons/${savedId}/export?format=csv`}>Export CSV</a><a href={`/api/v1/comparisons/${savedId}/export?format=json`}>Export JSON</a></>}{preview && !savedId && <span className={styles.muted}>Preview expires {new Date(preview.expires_at).toLocaleTimeString()}</span>}</div></>}
    <section className={`${styles.card} ${styles.history}`}><h2>Saved comparisons</h2>{listError ? <div role="alert">{listError}<button className="secondary" onClick={() => setRefresh(value => value + 1)}>Retry saved comparisons</button></div> : !saved ? <p role="status">Loading saved comparisons…</p> : !saved.items.length ? <p>No saved comparisons yet.</p> : <ul className={styles.list}>{saved.items.map(item => <li key={item.id}><button disabled={busy} onClick={() => { setChartPage(1); setSnapshot(item.data); setPreview(null); setSavedId(item.id); setInstruments(item.data.instruments.map(i => ({ symbol: i.symbol, asset_type: i.identity.asset_type }))); setRange(item.data.range); setForecasts([]); setForecastErrors([]); }}><strong>{item.data.instruments.map(i => i.symbol).join(" / ")}</strong><small>{new Date(item.created_at).toLocaleString()} · {item.data.range}</small></button></li>)}</ul>}<div className={styles.actions}><button className="secondary" disabled={page === 1 || busy} onClick={() => setPage(value => value - 1)}>Previous snapshots</button><span>Page {page}</span><button className="secondary" disabled={!saved?.has_next || busy} onClick={() => setPage(value => value + 1)}>Next snapshots</button></div></section>
  </main>;
}
