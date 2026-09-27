"use client";

import { FormEvent, useEffect, useState } from "react";

import { instrumentFromSearch, replaceInstrumentInUrl } from "../../components/workspace-context-url";
import { manualHoldingErrors, type PortfolioHolding, portfolioFromPayload, portfolioMutation } from "./portfolio-data";
import styles from "./workspace.module.css";

type PortfolioState =
  | { status: "loading" }
  | { status: "ready"; items: PortfolioHolding[] }
  | { status: "error"; message: string };

type HoldingContext = {
  quote: { last?: number; currency?: string; source?: string; as_of?: string; delayed?: boolean; delay_minutes?: number | null; label?: string } | null;
  latest: { id: number; status: string; horizons: string[]; outcome_count: number; submitted_at: string } | null;
};
type ContextState = { status: "idle" | "loading" } | { status: "ready"; data: HoldingContext } | { status: "error"; message: string };

function identityQuery(item: PortfolioHolding) {
  return new URLSearchParams({ symbol: item.symbol, asset_type: item.assetType, exchange: item.exchange, provider: item.provider, display_name: item.displayName }).toString();
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" ? value as Record<string, unknown> : {};
}

function readableTime(value?: string) {
  return value && !Number.isNaN(Date.parse(value)) ? new Date(value).toLocaleString() : "Unavailable";
}

export function PortfolioWorkspace() {
  const [state, setState] = useState<PortfolioState>({ status: "loading" });
  const [reload, setReload] = useState(0);
  const [symbol, setSymbol] = useState("");
  const [assetType, setAssetType] = useState<"stock" | "etf">("stock");
  const [quantity, setQuantity] = useState("");
  const [errors, setErrors] = useState({ symbol: "", quantity: "" });
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState("");
  const [selected, setSelected] = useState<PortfolioHolding | null>(null);
  const [contextState, setContextState] = useState<ContextState>({ status: "idle" });
  const [contextAttempt, setContextAttempt] = useState(0);

  // Seed the form from URL context only; seeding must never save a holding on its own.
  useEffect(() => {
    const selectedInstrument = instrumentFromSearch(window.location.search);
    if (!selectedInstrument) return;
    setSymbol(selectedInstrument.canonicalSymbol);
    setAssetType(selectedInstrument.assetType);
  }, []);

  // Abort on unmount/reload so a superseded response cannot overwrite newer portfolio state.
  useEffect(() => {
    const request = new AbortController();
    setState({ status: "loading" });
    fetch("/api/v1/lists?kind=portfolio", { headers: { Accept: "application/json" }, signal: request.signal })
      .then(async (response) => {
        const payload: unknown = await response.json().catch(() => null);
        if (!response.ok) throw new Error(`Portfolio request failed (${response.status}).`);
        const items = portfolioFromPayload(payload);
        if (!items) throw new Error("The local service returned an invalid portfolio response.");
        setState({ status: "ready", items });
      })
      .catch((error: unknown) => {
        if (request.signal.aborted) return;
        setState({ status: "error", message: error instanceof Error ? error.message : "Portfolio records are unavailable." });
      });
    return () => request.abort();
  }, [reload]);

  // Load context only for the opened holding. It is a read-only snapshot, never a valuation.
  useEffect(() => {
    if (!selected) return;
    const request = new AbortController();
    setContextState({ status: "loading" });
    void (async () => {
      try {
        const [quoteResponse, historyResponse] = await Promise.all([
          fetch(`/api/v1/quotes?symbols=${encodeURIComponent(selected.symbol)}`, { signal: request.signal }),
          fetch(`/api/v1/history?symbol=${encodeURIComponent(selected.symbol)}&page_size=100`, { signal: request.signal }),
        ]);
        const quotePayload: unknown = await quoteResponse.json();
        const historyPayload: unknown = await historyResponse.json();
        if (!quoteResponse.ok || !historyResponse.ok) throw new Error("Local quote or ledger request failed.");
        const quoteValues = asRecord(quotePayload).items;
        const historyValues = asRecord(historyPayload).items;
        if (!Array.isArray(quoteValues) || !Array.isArray(historyValues)) throw new Error("Local context response was malformed.");
        const quote = quoteValues.map(asRecord).find((value) => value.symbol === selected.symbol) ?? null;
        const history = historyValues.map(asRecord).find((value) => value.canonical_symbol === selected.symbol && value.forecast_available === true);
        if (request.signal.aborted) return;
        setContextState({ status: "ready", data: {
          quote: quote ? {
            last: typeof quote.last === "number" ? quote.last : undefined,
            currency: typeof quote.currency === "string" ? quote.currency : undefined,
            source: typeof quote.source === "string" ? quote.source : undefined,
            as_of: typeof quote.as_of === "string" ? quote.as_of : undefined,
            delayed: quote.delayed === true,
            delay_minutes: typeof quote.delay_minutes === "number" ? quote.delay_minutes : null,
            label: typeof quote.label === "string" ? quote.label : undefined,
          } : null,
          latest: history && typeof history.id === "number" ? {
            id: history.id,
            status: typeof history.status === "string" ? history.status : "recorded",
            horizons: Array.isArray(history.horizons) ? history.horizons.filter((value): value is string => typeof value === "string") : [],
            outcome_count: typeof history.outcome_count === "number" ? history.outcome_count : 0,
            submitted_at: typeof history.submitted_at === "string" ? history.submitted_at : "",
          } : null,
        } });
      } catch (error) {
        if (!request.signal.aborted) setContextState({ status: "error", message: error instanceof Error ? error.message : "Research context is unavailable." });
      }
    })();
    return () => request.abort();
  }, [selected, contextAttempt]);

  async function addHolding(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const nextErrors = manualHoldingErrors(symbol, quantity);
    setErrors(nextErrors);
    if (nextErrors.symbol || nextErrors.quantity) return;

    setSaving(true);
    setMessage("Saving manual holding…");
    try {
      const response = await fetch("/api/v1/lists", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(portfolioMutation(symbol, assetType, quantity)),
      });
      const payload: unknown = await response.json().catch(() => null);
      if (!response.ok) throw new Error(`Portfolio update failed (${response.status}).`);
      const items = portfolioFromPayload(payload);
      if (!items) throw new Error("The local service returned an invalid portfolio response.");
      // The POST response is authoritative; mirror the saved instrument back into URL context.
      setState({ status: "ready", items });
      const normalized = symbol.trim().toUpperCase();
      const saved = items.find((item) => item.symbol === normalized);
      if (saved) replaceInstrumentInUrl({
        provider: saved.provider,
        canonicalSymbol: saved.symbol,
        assetType: saved.assetType,
        exchange: saved.exchange,
        displayName: saved.displayName,
      });
      setMessage(`${normalized} saved to the local portfolio.`);
      setSymbol("");
      setQuantity("");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Portfolio update failed.");
    } finally {
      setSaving(false);
    }
  }

  const items = state.status === "ready" ? state.items : [];
  const clearError = (field: "symbol" | "quantity") => {
    if (errors[field]) setErrors((current) => ({ ...current, [field]: "" }));
  };

  return (
    <section className={styles.workspace} aria-labelledby="portfolio-heading" aria-busy={state.status === "loading"}>
      <div className={styles.heading}>
        <div>
          <p className="panel-kicker">Manual records</p>
          <h2 id="portfolio-heading">Manual portfolio holdings</h2>
          <p>Quantities are user-entered research context. They are not brokerage positions, live valuations, or executable orders.</p>
        </div>
        <span className="badge neutral">Research only</span>
      </div>

      <form className={styles.form} onSubmit={addHolding} noValidate>
        <label>
          <span>Holding symbol</span>
          <input value={symbol} onChange={(event) => { setSymbol(event.target.value.toUpperCase()); clearError("symbol"); }} aria-invalid={Boolean(errors.symbol)} aria-describedby={errors.symbol ? "holding-symbol-error" : undefined} maxLength={15} autoComplete="off" spellCheck={false} />
          {errors.symbol ? <span id="holding-symbol-error" className={styles.error} role="alert">{errors.symbol}</span> : null}
        </label>
        <label>
          <span>Shares / quantity</span>
          <input type="number" min="0" step="any" value={quantity} onChange={(event) => { setQuantity(event.target.value); clearError("quantity"); }} aria-invalid={Boolean(errors.quantity)} aria-describedby={errors.quantity ? "holding-quantity-error" : undefined} />
          {errors.quantity ? <span id="holding-quantity-error" className={styles.error} role="alert">{errors.quantity}</span> : null}
        </label>
        <label>
          <span>Asset type</span>
          <select value={assetType} onChange={(event) => setAssetType(event.target.value as "stock" | "etf")}><option value="stock">Stock</option><option value="etf">ETF</option></select>
        </label>
        <button className="primary" type="submit" disabled={saving || state.status === "loading"}>{saving ? "Saving…" : state.status === "loading" ? "Loading…" : "Add holding"}</button>
      </form>
      <p className={styles.status} role="status" aria-live="polite">{message}</p>

      {state.status === "loading" ? (
        <div className="empty-state loading" role="status"><h3>Loading portfolio records</h3></div>
      ) : state.status === "error" ? (
        <div className="error-panel" role="alert"><h3>Portfolio records unavailable</h3><p>{state.message}</p><button className="secondary" type="button" onClick={() => setReload((value) => value + 1)}>Retry</button></div>
      ) : items.length === 0 ? (
        <div className="empty-state"><h3>No manual holdings recorded</h3><p>Add a symbol and quantity above. No market value will be inferred.</p></div>
      ) : (
        <article className={styles.portfolios}>
          <div className={styles.portfolioHeading}><h3>Portfolio</h3><span>{items.length} holding{items.length === 1 ? "" : "s"}</span></div>
          <ul>
            {items.map((item) => (
              <li key={`${item.provider}:${item.assetType}:${item.symbol}`}>
                <span><strong>{item.symbol}</strong><small>{item.displayName} · {item.assetType.toUpperCase()} · {item.exchange}</small></span>
                <span><small>Manual quantity</small><strong>{item.quantity ?? "Not recorded"}</strong></span>
                <button className="secondary" type="button" onClick={() => setSelected(item)} aria-pressed={selected?.symbol === item.symbol}>Research summary</button>
              </li>
            ))}
          </ul>
        </article>
      )}
      {selected && <section className={styles.context} aria-labelledby="holding-context-heading" aria-busy={contextState.status === "loading"}>
        <div className={styles.contextHead}><div><p className="panel-kicker">Connected research</p><h3 id="holding-context-heading">{selected.symbol} · {selected.displayName}</h3></div><button className="secondary" type="button" onClick={() => setSelected(null)}>Close summary</button></div>
        {contextState.status === "loading" && <p role="status">Loading local quote and recorded research…</p>}
        {contextState.status === "error" && <div className="error-panel" role="alert"><p>{contextState.message}</p><button className="secondary" type="button" onClick={() => setContextAttempt((value) => value + 1)}>Retry</button></div>}
        {contextState.status === "ready" && <div className={styles.contextGrid}>
          <div><span className="panel-kicker">Provider quote snapshot</span><strong>{typeof contextState.data.quote?.last === "number" ? `${new Intl.NumberFormat(undefined, { maximumFractionDigits: 2 }).format(contextState.data.quote.last)} ${contextState.data.quote.currency ?? ""}` : "Price unavailable"}</strong><p>{contextState.data.quote?.source ?? "Provider unavailable"} · as of {readableTime(contextState.data.quote?.as_of)} · {contextState.data.quote?.delayed ? `Delayed${contextState.data.quote.delay_minutes ? ` ${contextState.data.quote.delay_minutes} min` : ""}` : "Delay unavailable or unreported"}</p><small>{contextState.data.quote?.label ?? "No quote snapshot returned. No price is inferred."}</small></div>
          <div><span className="panel-kicker">Latest recorded forecast</span><strong>{contextState.data.latest ? `Event #${contextState.data.latest.id}` : "None recorded"}</strong><p>{contextState.data.latest ? `${contextState.data.latest.horizons.map((value) => value.replaceAll("_", " ")).join(", ")} · ${contextState.data.latest.status} · ${contextState.data.latest.outcome_count} recorded outcomes` : "A forecast has not been saved for this instrument."}</p><small>{contextState.data.latest ? `Submitted ${readableTime(contextState.data.latest.submitted_at)}` : "No outcome is inferred from market movement."}</small></div>
        </div>}
        <div className={styles.contextActions}><a className="text-link" href={`/tools/live-trading?${identityQuery(selected)}`}>Quote workspace</a><a className="text-link" href={`/tools/forecast?${identityQuery(selected)}`}>New forecast</a>{contextState.status === "ready" && contextState.data.latest && <a className="text-link" href={`/?event_id=${contextState.data.latest.id}#result-section`}>Open saved forecast</a>}</div>
      </section>}
    </section>
  );
}
