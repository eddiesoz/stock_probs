"use client";

import { FormEvent, useEffect, useRef, useState } from "react";

import { apiFetch } from "../../../components/auth-client";
import { replaceInstrumentInUrl } from "../../../components/workspace-context-url";
import { apiPayload, delay, snapshotState, time } from "../client-utils";
import styles from "./workspace.module.css";

type Horizon = "five_min_forward" | "daily_1" | "weekly_5" | "monthly_21" | "quarterly_63";
type Interval = "5min" | "daily" | "weekly" | "monthly" | "quarterly";
type AssetType = "stock" | "etf";
type LoadState = "idle" | "loading" | "ready" | "empty" | "error";
type ProviderSnapshot = {
  provider?: string;
  source?: string;
  as_of?: string;
  state?: string;
  status?: string;
  delayed?: boolean;
  delay_minutes?: number | null;
  label?: string;
};

type ForecastResult = {
  horizon?: string;
  interval?: Interval;
  provider?: string;
  source?: string;
  provider_as_of?: string;
  state?: string;
  delayed?: boolean;
  delay_minutes?: number | null;
  label?: string;
  availability?: "available" | "unavailable";
  unavailable_reason?: string | null;
  horizon_start_timestamp?: string;
  horizon_end_timestamp?: string;
  origin_timestamp?: string;
  reference_timestamp?: string;
  target_timestamp?: string;
  origin_price?: number;
  direction_probabilities?: { up?: number; down?: number; unchanged?: number; flat?: number };
  threshold_probabilities?: Array<{
    operator?: "lte" | "gte";
    threshold?: number;
    probability?: number;
    rare_event?: boolean;
  }>;
  magnitude_intervals?: Array<{
    level?: number;
    price?: { low?: number; high?: number };
    percent?: { low?: number; high?: number };
  }>;
  definition?: string;
  stale_state?: "current" | "stale";
  model_version?: string;
  sample_size?: number;
  provenance?: {
    adjustment_basis?: string;
    calendar?: { name?: string; version?: string; timezone?: string };
    provider_snapshot?: ProviderSnapshot;
  };
};

type ForecastResponse = {
  event?: { request_id?: string };
  input?: {
    canonical_symbol?: string;
    asset_type?: AssetType;
    display_name?: string;
    exchange?: string;
    currency?: string;
    provider?: string;
    provider_as_of?: string;
    provider_state?: string;
    delayed?: boolean;
    delay_minutes?: number | null;
    provider_label?: string;
  };
  results?: ForecastResult[];
};

// UI interval -> API horizon mapping. Labels and horizon ids must stay aligned with the
// backend's rolling-horizon names; the origin/target text states the exact completed bars used.
const intervalDetails: Record<Interval, { horizon: Horizon; label: string; origin: string; target: string }> = {
  "5min": {
    horizon: "five_min_forward",
    label: "5 minutes",
    origin: "Latest completed 5-minute bar close",
    target: "Next completed 5-minute bar close",
  },
  daily: {
    horizon: "daily_1",
    label: "1 session",
    origin: "Latest completed regular-session close",
    target: "Next regular-session close",
  },
  weekly: {
    horizon: "weekly_5",
    label: "5 sessions",
    origin: "Latest completed regular-session close",
    target: "Close after 5 scheduled sessions",
  },
  monthly: {
    horizon: "monthly_21",
    label: "21 sessions",
    origin: "Latest completed regular-session close",
    target: "Close after 21 scheduled sessions",
  },
  quarterly: {
    horizon: "quarterly_63",
    label: "63 sessions",
    origin: "Latest completed regular-session close",
    target: "Close after 63 scheduled sessions",
  },
};

function formatPercent(value?: number) {
  return typeof value === "number" ? `${(value * 100).toFixed(1)}%` : "Unavailable";
}

function formatPrice(value?: number, currency?: string) {
  return typeof value === "number" && Number.isFinite(value)
    ? `${value.toFixed(2)}${currency ? ` ${currency}` : ""}`
    : "Unavailable";
}

function forecastSnapshot(result: ForecastResult | undefined, input: ForecastResponse["input"]) {
  const snapshot = result?.provenance?.provider_snapshot;
  return {
    provider: snapshot?.provider ?? snapshot?.source ?? result?.provider ?? result?.source ?? input?.provider,
    asOf: snapshot?.as_of ?? result?.provider_as_of ?? input?.provider_as_of,
    state: snapshot?.state ?? snapshot?.status ?? result?.state ?? input?.provider_state ?? (result?.stale_state === "stale" ? "stale" : undefined),
    delayed: snapshot?.delayed ?? result?.delayed ?? input?.delayed,
    delayMinutes: snapshot?.delay_minutes ?? result?.delay_minutes ?? input?.delay_minutes,
    label: snapshot?.label ?? result?.label ?? input?.provider_label,
  };
}

function forecastDisclosure(result: ForecastResult | undefined, input: ForecastResponse["input"]) {
  const snapshot = forecastSnapshot(result, input);
  const state = result?.availability === "unavailable"
    ? "Unavailable"
    : snapshotState(snapshot.state, snapshot.delayed);
  const disclosedDelay = typeof snapshot.delayMinutes === "number"
    ? delay(true, snapshot.delayMinutes)
    : delay(snapshot.delayed, snapshot.delayMinutes);
  return `Historical/probability data — not a live quote. Provenance: ${state}. Delay: ${disclosedDelay}.`;
}

export function ForecastWorkspace() {
  const [symbol, setSymbol] = useState("");
  const [assetType, setAssetType] = useState<AssetType>("stock");
  const [exchange, setExchange] = useState("");
  const [interval, setInterval] = useState<Interval>("daily");
  const [state, setState] = useState<LoadState>("idle");
  const [response, setResponse] = useState<ForecastResponse | null>(null);
  const [message, setMessage] = useState("");
  const controller = useRef<AbortController | null>(null);

  // Opening the page with a symbol only preselects it; a forecast is never submitted
  // automatically. The cleanup aborts an in-flight request on unmount.
  useEffect(() => {
    const query = new URLSearchParams(window.location.search);
    setSymbol((query.get("symbol") ?? "").toUpperCase());
    setExchange(query.get("exchange") ?? "");
    if (query.get("asset_type") === "etf") setAssetType("etf");
    return () => controller.current?.abort();
  }, []);

  const selected = intervalDetails[interval];
  const results = response?.results ?? [];
  const result = results.find((item) => item.interval === interval || item.horizon === selected.horizon);

  // An edited request has no result yet. Clear the previous response and stop its pending
  // retrieval so another interval cannot briefly appear to have failed before submission.
  function resetForInputChange() {
    controller.current?.abort();
    controller.current = null;
    setResponse(null);
    setMessage("");
    setState("idle");
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const normalized = symbol.trim().toUpperCase();
    if (!normalized) {
      setMessage("Enter a symbol before running a forecast.");
      setState("error");
      return;
    }

    // Abort any superseded request so only the latest submitted horizon can set results.
    controller.current?.abort();
    const request = new AbortController();
    controller.current = request;
    setState("loading");
    setMessage("");
    setResponse(null);

    try {
      const apiResponse = await apiFetch("/api/v1/forecasts", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ symbol: normalized, asset_type: assetType, interval }),
        signal: request.signal,
      });
      const payload = await apiPayload(apiResponse, `Forecast request failed (${apiResponse.status}).`);
      if (request.signal.aborted) return;
      const forecast = payload as ForecastResponse;
      if (!forecast.results?.length) {
        setState("empty");
        setMessage("The service returned no forecast results.");
        return;
      }
      setResponse(forecast);
      if (forecast.input?.canonical_symbol && forecast.input.exchange && forecast.input.asset_type) {
        replaceInstrumentInUrl({
          provider: forecast.input.provider ?? "yahoo",
          canonicalSymbol: forecast.input.canonical_symbol,
          assetType: forecast.input.asset_type,
          exchange: forecast.input.exchange,
          displayName: forecast.input.display_name ?? forecast.input.canonical_symbol,
        });
      }
      setState("ready");
    } catch (error) {
      if (request.signal.aborted) return;
      setMessage(error instanceof Error ? error.message : "Forecast request failed.");
      setState("error");
    }
  }

  const direction = result?.direction_probabilities;
  // Prefer the explicit 80% coverage interval; falling back to the first band avoids
  // rendering a blank range when only a different level is returned.
  const range = result?.magnitude_intervals?.find((item) => item.level === 0.8)
    ?? result?.magnitude_intervals?.[0];
  const identity = response?.input;
  const snapshot = forecastSnapshot(result, identity);
  const provider = snapshot.provider;
  const providerAsOf = snapshot.asOf;

  return (
    <>
      <section className={styles.composer} aria-labelledby="forecast-input-heading">
        <div className={styles.sectionHeading}>
          <div>
            <p className="panel-kicker">Instrument and horizon</p>
            <h2 id="forecast-input-heading">Forecast input</h2>
          </div>
          {exchange && <span className={styles.identity}>{exchange} · {assetType.toUpperCase()}</span>}
        </div>
        <form onSubmit={submit} noValidate>
          <div className={styles.fields}>
            <label>
              <span>Symbol</span>
              <input
                name="symbol"
                value={symbol}
                onChange={(event) => {
                  resetForInputChange();
                  setSymbol(event.target.value.toUpperCase());
                  setExchange("");
                }}
                maxLength={15}
                autoComplete="off"
                spellCheck={false}
                required
              />
            </label>
            <label>
              <span>Asset type</span>
              <select value={assetType} onChange={(event) => {
                resetForInputChange();
                setAssetType(event.target.value as AssetType);
                setExchange("");
              }}>
                <option value="stock">Stock</option>
                <option value="etf">ETF</option>
              </select>
            </label>
            <label>
              <span>Forecast horizon</span>
              <select value={interval} onChange={(event) => {
                resetForInputChange();
                setInterval(event.target.value as Interval);
              }}>
                {Object.entries(intervalDetails).map(([value, detail]) => (
                  <option key={value} value={value}>{detail.label}</option>
                ))}
              </select>
            </label>
          </div>

          <dl className={styles.boundary} aria-label="Selected forecast boundaries">
            <div><dt>Origin</dt><dd>{selected.origin}</dd></div>
            <div><dt>Target</dt><dd>{selected.target}</dd></div>
          </dl>
          <p className={styles.hint}>Opening this page with a symbol preselects it; forecasts never run automatically.</p>
          <button className="primary" type="submit" disabled={state === "loading"}>
            {state === "loading" ? "Running forecast…" : "Run forecast"}
          </button>
        </form>
      </section>

      <section className={styles.results} aria-labelledby="forecast-result-heading" aria-busy={state === "loading"}>
        <div className={styles.sectionHeading}>
          <div>
            <p className="panel-kicker">Result</p>
            <h2 id="forecast-result-heading">Interval outlook</h2>
          </div>
          {state === "ready" && <span className="badge current">Current result</span>}
        </div>

        {state === "idle" && <div className="empty-state"><h3>No forecast submitted</h3><p>Review the interval boundaries above, then run the forecast.</p></div>}
        {state === "loading" && <div className="empty-state loading" role="status"><h3>Calculating forecast</h3><p>Requesting bounded market data from the local service.</p></div>}
        {state === "empty" && <div className="empty-state" role="status"><h3>No result available</h3><p>{message}</p><button className="secondary" type="button" onClick={() => setState("idle")}>Try again</button></div>}
        {state === "error" && <div className="error-panel" role="alert"><h3>Forecast unavailable</h3><p>{message}</p><button className="secondary" type="button" onClick={() => setState("idle")}>Retry</button></div>}
         {state === "ready" && !result && <div className="empty-state" role="status"><h3>Selected horizon unavailable</h3><p>The local API did not return {selected.label}. Choose another horizon or run the forecast again.</p><p className={styles.dataNotice}>{forecastDisclosure(undefined, identity)}</p></div>}
         {state === "ready" && result?.availability === "unavailable" && (
           <div className="empty-state" role="status">
             <h3>{selected.label} forecast unavailable</h3>
             <p>{result.unavailable_reason ?? "The local API did not provide a reason."}</p>
             <p>Provider: {provider ?? "Unavailable"} · As of: {time(providerAsOf)}</p>
             <p className={styles.dataNotice}>{forecastDisclosure(result, identity)}</p>
           </div>
         )}
         {state === "ready" && result && result.availability !== "unavailable" && (
           <div className={styles.resultCard}>
            <div className={styles.resultIdentity}>
              <div><span>Instrument</span><strong>{identity?.canonical_symbol ?? symbol} · {identity?.display_name ?? "Selected instrument"}</strong></div>
               <div><span>Provider / as of</span><strong>{provider ?? "Unavailable"} · {time(providerAsOf)}</strong></div>
             </div>
             <p className={styles.dataNotice}>{forecastDisclosure(result, identity)}{snapshot.label ? ` ${snapshot.label}` : ""}</p>
            <dl className={styles.exactBoundary}>
              <div><dt>Exact origin</dt><dd>{time(result.horizon_start_timestamp ?? result.reference_timestamp ?? result.origin_timestamp)}</dd></div>
              <div><dt>Exact target</dt><dd>{time(result.horizon_end_timestamp ?? result.target_timestamp)}</dd></div>
            </dl>
            <div className={styles.probabilities}>
              <div className={styles.loss}><span>Down</span><strong>{formatPercent(direction?.down)}</strong></div>
              <div><span>Unchanged</span><strong>{formatPercent(direction?.unchanged ?? direction?.flat)}</strong></div>
              <div className={styles.gain}><span>Up</span><strong>{formatPercent(direction?.up)}</strong></div>
            </div>
            <dl className={styles.range}>
              <div><dt>Origin price</dt><dd>{formatPrice(result.origin_price, identity?.currency)}</dd></div>
              <div><dt>80% price interval</dt><dd>{formatPrice(range?.price?.low, identity?.currency)} – {formatPrice(range?.price?.high, identity?.currency)}</dd></div>
              <div><dt>80% return interval</dt><dd>{typeof range?.percent?.low === "number" ? `${range.percent.low.toFixed(2)}%` : "Unavailable"} – {typeof range?.percent?.high === "number" ? `${range.percent.high.toFixed(2)}%` : "Unavailable"}</dd></div>
            </dl>
            <div className={styles.resultSection}>
              <h3>Threshold probabilities</h3>
              {result.threshold_probabilities?.length ? <dl className={styles.thresholds}>{result.threshold_probabilities.map((item) => {
                // Thresholds are stored as signed values; the label renders the magnitude with
                // the operator deciding the direction, so lte/gte are never double-negated.
                const threshold = typeof item.threshold === "number" ? Math.abs(item.threshold) : null;
                const label = item.operator === "lte" ? `Return ≤ −${threshold}%` : `Return ≥ +${threshold}%`;
                return <div key={`${item.operator}-${item.threshold}`}><dt>{threshold === null ? "Threshold unavailable" : label}</dt><dd>{formatPercent(item.probability)}{item.rare_event ? " · sparse history" : ""}</dd></div>;
              })}</dl> : <p>Threshold probabilities unavailable.</p>}
            </div>
            <div className={styles.resultSection}>
              <h3>Return and price intervals</h3>
               {result.magnitude_intervals?.length ? <div className={styles.intervalTableWrap} role="region" aria-label="Return and price interval table" tabIndex={0}><table className={styles.intervalTable}>
                <thead><tr><th scope="col">Coverage</th><th scope="col">Return interval</th><th scope="col">Price interval</th></tr></thead>
                <tbody>{result.magnitude_intervals.map((item) => <tr key={item.level}><th scope="row">{formatPercent(item.level)}</th><td>{typeof item.percent?.low === "number" ? `${item.percent.low.toFixed(2)}%` : "Unavailable"} – {typeof item.percent?.high === "number" ? `${item.percent.high.toFixed(2)}%` : "Unavailable"}</td><td>{formatPrice(item.price?.low, identity?.currency)} – {formatPrice(item.price?.high, identity?.currency)}</td></tr>)}</tbody>
              </table></div> : <p>Return and price intervals unavailable.</p>}
            </div>
            <dl className={styles.provenance}>
              <div><dt>Definition</dt><dd>{result.definition ?? "Unavailable"}</dd></div>
              <div><dt>Data state</dt><dd>{result.stale_state ?? "Unavailable"}</dd></div>
              <div><dt>Model / sample</dt><dd>{result.model_version ?? "Unavailable"} · {result.sample_size ?? "Unavailable"} observations</dd></div>
              <div><dt>Calendar / timezone</dt><dd>{result.provenance?.calendar?.name ?? "Unavailable"} · {result.provenance?.calendar?.timezone ?? "Unavailable"}</dd></div>
              <div><dt>Adjustment basis</dt><dd>{result.provenance?.adjustment_basis ?? "Unavailable"}</dd></div>
            </dl>
          </div>
        )}
      </section>
    </>
  );
}
