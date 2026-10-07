"use client";

import { FormEvent, useEffect, useRef, useState } from "react";

import { apiFetch } from "../../../components/auth-client";
import type { AssistantBrowserAction } from "../../../components/assistant/assistant-contract";
import { replaceInstrumentInUrl } from "../../../components/workspace-context-url";
import { apiPayload, delay, number, quoteBatches, quotePrice, record, snapshotState, time } from "../client-utils";
import { applyLiveTradingAssistantAction } from "./assistant-bridge";
import styles from "./workspace.module.css";

type LoadState = "loading" | "ready" | "empty" | "error";
type Identity = { symbol: string; assetType: "stock" | "etf"; exchange: string; provider: string; displayName: string };
type PortfolioEntry = { symbol: string; assetType: "stock" | "etf"; quantity: number | null };
type PortfolioDraftEntry = { symbol: string; quantity: number };
type Quote = {
  symbol: string;
  name?: string;
  asset_type?: string;
  exchange?: string;
  last?: number;
  price?: number;
  currency?: string;
  change?: number;
  change_percent?: number;
  open?: number;
  high?: number;
  low?: number;
  previous_close?: number;
  volume?: number;
  last_trade?: number;
  source?: string;
  provider?: string;
  as_of?: string;
  delayed?: boolean;
  delay_minutes?: number | null;
  label?: string;
  state?: string;
};
const SYMBOL_PATTERN = /^[A-Z0-9.^-]{1,15}$/;
const QUOTE_REFRESH_MS = 30_000;

function portfolioItems(payload: unknown): PortfolioEntry[] {
  const values = record(payload).items;
  if (!Array.isArray(values)) throw new Error("The local list response was malformed.");
  return values.map((item) => {
    const value = record(item);
    const symbol = value.symbol;
    const quantity = value.quantity;
    if (
      typeof symbol !== "string"
      || !SYMBOL_PATTERN.test(symbol.toUpperCase())
      || (value.asset_type !== "stock" && value.asset_type !== "etf")
      || !(
        quantity === null
        || (typeof quantity === "number" && Number.isFinite(quantity) && quantity >= 0)
      )
    ) throw new Error("The local portfolio response contained a malformed item.");
    const assetType = value.asset_type as "stock" | "etf";
    return { symbol: symbol.toUpperCase(), assetType, quantity: quantity as number | null };
  }).slice(0, 100);
}

function portfolioDraft(items: PortfolioEntry[]) {
  return items.map((item) => `${item.symbol}: ${item.quantity ?? ""}`).join("\n");
}

function parsePortfolioDraft(value: string): { entries: PortfolioDraftEntry[]; error: string } {
  const parts = value.split(/[\n,]+/).map((item) => item.trim()).filter(Boolean);
  if (parts.length > 100) return { entries: [], error: "Enter no more than 100 portfolio holdings." };
  const seen = new Set<string>();
  const entries: PortfolioDraftEntry[] = [];
  for (const part of parts) {
    const separator = part.indexOf(":");
    if (separator <= 0) {
      return { entries: [], error: `Use SYMBOL: quantity for each holding (for example, SPY: 10).` };
    }
    const symbol = part.slice(0, separator).trim().toUpperCase();
    const quantityText = part.slice(separator + 1).trim();
    if (!SYMBOL_PATTERN.test(symbol)) {
      return { entries: [], error: `${symbol || "This symbol"} must use 1–15 letters, numbers, periods, hyphens, or ^.` };
    }
    const quantity = Number(quantityText);
    if (!quantityText || !Number.isFinite(quantity) || quantity <= 0) {
      return { entries: [], error: `${symbol} quantity must be a finite number greater than zero.` };
    }
    if (seen.has(symbol)) return { entries: [], error: `${symbol} appears more than once; keep one quantity per symbol.` };
    seen.add(symbol);
    entries.push({ symbol, quantity });
  }
  return { entries, error: "" };
}

function quoteItems(payload: unknown): Quote[] {
  const values = record(payload).items;
  if (!Array.isArray(values)) throw new Error("The local quote response was malformed.");
  return values.map((item) => {
    const value = record(item);
    if (typeof value.symbol !== "string") throw new Error("The local quote response contained a malformed item.");
    return value as Quote;
  });
}

function identityQuery(identity: Identity) {
  return new URLSearchParams({
    symbol: identity.symbol,
    asset_type: identity.assetType,
    exchange: identity.exchange,
    provider: identity.provider,
    display_name: identity.displayName,
  }).toString();
}

// No-order boundary: this workspace only displays provider-labelled quotes and depth
// availability. It contains no buy/sell/order controls and never calls a trading endpoint.
export function LiveTradingWorkspace() {
  const [identity, setIdentity] = useState<Identity>({ symbol: "", assetType: "stock", exchange: "", provider: "yahoo", displayName: "" });
  const [draft, setDraft] = useState("");
  const [rowQuantities, setRowQuantities] = useState<Record<string, string>>({});
  const [newSymbol, setNewSymbol] = useState("");
  const [newQuantity, setNewQuantity] = useState("");
  const [holdingBusy, setHoldingBusy] = useState(false);
  const [portfolio, setPortfolio] = useState<PortfolioEntry[]>([]);
  const [portfolioState, setPortfolioState] = useState<LoadState>("loading");
  const [portfolioError, setPortfolioError] = useState("");
  const [listMessage, setListMessage] = useState("Loading server portfolio…");
  const [quotes, setQuotes] = useState<Quote[]>([]);
  const [quoteState, setQuoteState] = useState<LoadState>("loading");
  const [quoteError, setQuoteError] = useState("");
  const [quoteRefreshing, setQuoteRefreshing] = useState(false);
  const [quoteAttempt, setQuoteAttempt] = useState(0);
  const [paused, setPaused] = useState(false);
  const [compact, setCompact] = useState(false);
  const [notes, setNotes] = useState("");
  const [threshold, setThreshold] = useState("");
  const [alerts, setAlerts] = useState<number[]>([]);
  const [watchlistMessage, setWatchlistMessage] = useState("");
  const [expanded, setExpanded] = useState(false);
  const [depthVisible, setDepthVisible] = useState(true);
  const initialized = useRef(false);
  const quoteGeneration = useRef(0);

  useEffect(() => {
    const query = new URLSearchParams(window.location.search);
    const symbol = (query.get("symbol") ?? "").toUpperCase();
    const selected: Identity = {
      symbol,
      assetType: query.get("asset_type") === "etf" ? "etf" : "stock",
      exchange: query.get("exchange") ?? "",
      provider: query.get("provider") ?? "yahoo",
      displayName: query.get("display_name") ?? symbol,
    };
    setIdentity(selected);
    // Reduced-motion users get a paused strip by default; pause is presentation state only.
    setPaused(window.matchMedia("(prefers-reduced-motion: reduce)").matches);
    initialized.current = true;

    const request = new AbortController();
    void (async () => {
      try {
        const response = await fetch("/api/v1/lists?kind=portfolio", { signal: request.signal });
        const payload = await apiPayload(response, `Portfolio request failed (${response.status}).`);
          const holdings = portfolioItems(payload);
          setPortfolio(holdings);
          setDraft(portfolioDraft(holdings));
          setRowQuantities(Object.fromEntries(holdings.map((item) => [item.symbol, String(item.quantity ?? "")])));
          setPortfolioState(holdings.length ? "ready" : "empty");
          if (holdings.length) {
            setListMessage("Server portfolio loaded.");
        } else {
          setListMessage("Server portfolio is empty; add symbols below.");
        }
      } catch (error) {
        if (request.signal.aborted) return;
        setPortfolio([]);
        setPortfolioState("error");
        setDraft("");
        setListMessage(error instanceof Error ? error.message : "Server portfolio unavailable.");
      }
    })();
    return () => request.abort();
  }, []);

  useEffect(() => {
    const request = new AbortController();
    const refreshAfterAssistantAction = async () => {
      setListMessage("Refreshing the saved portfolio after the confirmed assistant action…");
      try {
        const response = await fetch("/api/v1/lists?kind=portfolio", { signal: request.signal });
        const holdings = portfolioItems(await apiPayload(response, `Portfolio request failed (${response.status}).`));
        const preserveDraft = draft !== portfolioDraft(portfolio);
        setPortfolio(holdings);
        setPortfolioState(holdings.length ? "ready" : "empty");
        setRowQuantities(Object.fromEntries(holdings.map((item) => [item.symbol, String(item.quantity ?? "")])));
        if (!preserveDraft) setDraft(portfolioDraft(holdings));
        setListMessage(preserveDraft
          ? "The confirmed assistant action changed the saved portfolio. Your unsaved bulk draft is unchanged; review it before applying."
          : holdings.length ? "Saved portfolio refreshed after the confirmed assistant action." : "Saved portfolio is empty after the confirmed assistant action.");
      } catch (error) {
        if (request.signal.aborted) return;
        setListMessage(error instanceof Error ? error.message : "The saved portfolio could not be refreshed.");
      }
    };
    window.addEventListener("signal-ledger:assistant-portfolio-updated", refreshAfterAssistantAction);
    return () => {
      request.abort();
      window.removeEventListener("signal-ledger:assistant-portfolio-updated", refreshAfterAssistantAction);
    };
  }, [draft, portfolio]);

  useEffect(() => {
    if (!initialized.current || portfolioState === "loading") return;
    const symbols = [...new Set([...(identity.symbol ? [identity.symbol] : []), ...portfolio.map((item) => item.symbol)])].slice(0, 100);
    if (!symbols.length) {
      setQuotes([]);
      setQuoteState("empty");
      return;
    }
    const generation = ++quoteGeneration.current;
    let disposed = false;
    let inFlight = false;
    let request: AbortController | null = null;

    const loadQuotes = async (initial: boolean) => {
      if (disposed || inFlight) return;
      inFlight = true;
      request = new AbortController();
      if (initial) {
        setQuoteState("loading");
        setQuoteError("");
      } else {
        setQuoteRefreshing(true);
      }
      try {
        const batches = await Promise.all(quoteBatches(symbols).map(async (batch) => {
          const requested = batch.join(",");
          const response = await fetch(`/api/v1/quotes?symbols=${encodeURIComponent(requested)}`, { signal: request?.signal });
          return quoteItems(await apiPayload(response, `Quote request failed (${response.status}).`));
        }));
        const items = batches.flat().filter((item) => symbols.includes(item.symbol.toUpperCase()));
        if (disposed || request?.signal.aborted || generation !== quoteGeneration.current) return;
        setQuotes(items);
        setQuoteState(items.length ? "ready" : "empty");
        setQuoteError("");
        if (!identity.symbol && initial && items[0]) selectQuote(items[0]);
      } catch (error) {
        if (disposed || request?.signal.aborted || generation !== quoteGeneration.current) return;
        setQuoteError(error instanceof Error ? error.message : "Quotes are unavailable.");
        setQuoteState("error");
      } finally {
        if (!disposed && generation === quoteGeneration.current) {
          inFlight = false;
          setQuoteRefreshing(false);
        }
      }
    };

    void loadQuotes(true);
    const timer = window.setInterval(() => void loadQuotes(false), QUOTE_REFRESH_MS);
    return () => {
      disposed = true;
      window.clearInterval(timer);
      request?.abort();
    };
  }, [identity.symbol, portfolio, portfolioState, quoteAttempt]);

  // Notes are a per-symbol browser draft kept in localStorage; they are never sent to the
  // server. Alerts reset on symbol change because they exist only for the open page session.
  useEffect(() => {
    if (!identity.symbol) return;
    setNotes(localStorage.getItem(`stock-probs.live-notes.${identity.symbol}`) ?? "");
    setAlerts([]);
  }, [identity.symbol]);

  useEffect(() => {
    const receiveAssistantAction = (event: Event) => {
      const custom = event as CustomEvent<{ action?: AssistantBrowserAction; finish?: (result: { ok: boolean; message: string }) => void }>;
      const action = custom.detail?.action;
      const finish = custom.detail?.finish;
      if (!action || !finish) return;
      const result = applyLiveTradingAssistantAction(action, {
        symbol: identity.symbol,
        asset_type: identity.assetType,
        provider: identity.provider,
        exchange: identity.exchange,
      }, alerts);
      if (result.ok) {
        if (result.state.note !== undefined) {
          setNotes(result.state.note);
          if (identity.symbol) {
            const key = `stock-probs.live-notes.${identity.symbol}`;
            if (result.state.note) localStorage.setItem(key, result.state.note);
            else localStorage.removeItem(key);
          }
        }
        if (result.state.alerts) setAlerts(result.state.alerts);
        if (action.type === "notes.set" || action.type === "notes.clear" || action.type === "alerts.remove") {
          const targetId = action.type === "alerts.remove" ? "alerts-heading" : "notes-heading";
          window.requestAnimationFrame(() => {
            const target = document.getElementById(targetId);
            if (!target) return;
            target.scrollIntoView({ block: "center" });
            target.focus({ preventScroll: true });
          });
        }
      }
      finish(result);
    };
    window.addEventListener("signal-ledger:assistant-action", receiveAssistantAction);
    return () => window.removeEventListener("signal-ledger:assistant-action", receiveAssistantAction);
  }, [identity, alerts]);

  const selectedQuote = quotes.find((item) => item.symbol.toUpperCase() === identity.symbol) ?? null;

  function applyPortfolio(holdings: PortfolioEntry[]) {
    setPortfolio(holdings);
    setPortfolioState(holdings.length ? "ready" : "empty");
    setDraft(portfolioDraft(holdings));
    setRowQuantities(Object.fromEntries(holdings.map((item) => [item.symbol, String(item.quantity ?? "")])));
  }

  async function saveOneHolding(symbol: string, quantityText: string, existingType?: "stock" | "etf") {
    const quantity = Number(quantityText);
    if (!SYMBOL_PATTERN.test(symbol) || !quantityText || !Number.isFinite(quantity) || quantity <= 0) {
      setListMessage("Enter a valid symbol and a manual quantity greater than zero.");
      return;
    }
    if (draft !== portfolioDraft(portfolio)) {
      setListMessage("Apply or discard the bulk draft before editing a single holding.");
      return;
    }
    setHoldingBusy(true);
    setListMessage(`Saving ${symbol} manual quantity…`);
    try {
      let assetType = existingType;
      if (!assetType) {
        const lookupResponse = await fetch(`/api/v1/instruments?${new URLSearchParams({ query: symbol, limit: "1" })}`);
        const lookup = record(await apiPayload(lookupResponse, `Instrument lookup failed (${lookupResponse.status}).`));
        const match = (Array.isArray(lookup.items) ? lookup.items : []).map(record).find((item) => item.canonical_symbol === symbol);
        if (!match || (match.asset_type !== "stock" && match.asset_type !== "etf")) throw new Error(`${symbol} was not found.`);
        assetType = match.asset_type;
      }
      const response = await apiFetch("/api/v1/lists", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ kind: "portfolio", item: { symbol, asset_type: assetType, quantity } }) });
      const saved = portfolioItems(await apiPayload(response, `Portfolio update failed (${response.status}).`));
      applyPortfolio(saved);
      setNewSymbol("");
      setNewQuantity("");
      setListMessage(`${symbol} saved. The add-holding form remains available.`);
    } catch (error) {
      setListMessage(error instanceof Error ? error.message : "Manual holding could not be saved.");
    } finally {
      setHoldingBusy(false);
    }
  }

  async function savePortfolio(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const parsed = parsePortfolioDraft(draft);
    setPortfolioError(parsed.error);
    if (parsed.error) {
      setListMessage("Portfolio was not saved. Correct the highlighted format and try again.");
      return;
    }
    const entries = parsed.entries;
    const symbols = entries.map((entry) => entry.symbol);
    setHoldingBusy(true);
    setListMessage("Updating server portfolio…");
    try {
      for (const entry of entries) {
        const existing = portfolio.find((item) => item.symbol === entry.symbol);
        let assetType = existing?.assetType;
        if (!assetType) {
          const query = new URLSearchParams({ query: entry.symbol, limit: "1" });
          const lookupResponse = await fetch(`/api/v1/instruments?${query}`);
          const lookup = record(await apiPayload(lookupResponse, `Instrument lookup failed (${lookupResponse.status}).`));
          // Resolve each new symbol through the local instrument lookup before persisting it, so
          // the stored portfolio holds a canonical identity rather than a free-typed ticker.
          const match = (Array.isArray(lookup.items) ? lookup.items : [])
            .map(record)
            .find((item) => item.canonical_symbol === entry.symbol);
          if (!match || (match.asset_type !== "stock" && match.asset_type !== "etf")) throw new Error(`${entry.symbol} was not found.`);
          assetType = match.asset_type;
        }
        const response = await apiFetch("/api/v1/lists", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ kind: "portfolio", item: { symbol: entry.symbol, asset_type: assetType, quantity: entry.quantity } }),
        });
        await apiPayload(response, `Portfolio update failed (${response.status}).`);
      }
      for (const item of portfolio.filter((current) => !symbols.includes(current.symbol))) {
        const response = await apiFetch(`/api/v1/lists?kind=portfolio&symbol=${encodeURIComponent(item.symbol)}`, { method: "DELETE" });
        await apiPayload(response, `Portfolio update failed (${response.status}).`);
      }
      const refreshedResponse = await fetch("/api/v1/lists?kind=portfolio");
       const refreshed = portfolioItems(await apiPayload(refreshedResponse, `Portfolio request failed (${refreshedResponse.status}).`));
       applyPortfolio(refreshed);
      setPortfolioError("");
      setListMessage(refreshed.length ? "Server portfolio updated." : "Server portfolio is empty.");
    } catch (error) {
      // A partial add/remove can leave the server list different from the draft, so the user is
      // told to reload rather than shown a locally invented success state.
      setListMessage(`${error instanceof Error ? error.message : "Server portfolio update failed."} Reload to reconcile the server list.`);
    } finally {
      setHoldingBusy(false);
    }
  }

  async function addToWatchlist() {
    if (!identity.symbol) return;
    setWatchlistMessage("Adding…");
    try {
      const response = await apiFetch("/api/v1/lists", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ kind: "watchlist", item: { symbol: identity.symbol, asset_type: identity.assetType } }),
      });
      await apiPayload(response, `Watchlist update failed (${response.status}).`);
      setWatchlistMessage("Added to watchlist.");
    } catch (error) {
      setWatchlistMessage(error instanceof Error ? error.message : "Watchlist update failed.");
    }
  }

  function selectQuote(quote: Quote) {
    const nextIdentity: Identity = {
      symbol: quote.symbol.toUpperCase(),
      assetType: quote.asset_type === "etf" ? "etf" : "stock",
      exchange: quote.exchange ?? "",
      provider: quote.provider ?? quote.source ?? "yahoo",
      displayName: quote.name ?? quote.symbol.toUpperCase(),
    };
    setIdentity(nextIdentity);
    if (nextIdentity.exchange) replaceInstrumentInUrl({
      provider: nextIdentity.provider,
      canonicalSymbol: nextIdentity.symbol,
      assetType: nextIdentity.assetType as "stock" | "etf",
      exchange: nextIdentity.exchange,
      displayName: nextIdentity.displayName,
    });
    setDepthVisible(true);
  }

  // Alerts are in-memory only and capped at five; there is no scheduler or delivery path.
  function addAlert(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const price = Number(threshold);
    if (!Number.isFinite(price) || price <= 0) return;
    setAlerts((current) => [...current, price].slice(-5));
    setThreshold("");
  }

  const summary: Array<readonly [string, number | undefined, Intl.NumberFormatOptions?]> = [
    ["Last", quotePrice(selectedQuote), { minimumFractionDigits: 2, maximumFractionDigits: 2 }],
    ["Change", selectedQuote?.change, { minimumFractionDigits: 2, maximumFractionDigits: 2, signDisplay: "always" as const }],
    ["% change", selectedQuote?.change_percent, { minimumFractionDigits: 2, maximumFractionDigits: 2, signDisplay: "always" as const }],
    ["Open", selectedQuote?.open, { minimumFractionDigits: 2, maximumFractionDigits: 2 }],
    ["High", selectedQuote?.high, { minimumFractionDigits: 2, maximumFractionDigits: 2 }],
    ["Low", selectedQuote?.low, { minimumFractionDigits: 2, maximumFractionDigits: 2 }],
    ["Volume", selectedQuote?.volume, { maximumFractionDigits: 0 }],
    ["Last trade", selectedQuote?.last_trade, { minimumFractionDigits: 2, maximumFractionDigits: 2 }],
  ];
  if (typeof selectedQuote?.previous_close === "number") {
    summary.splice(7, 0, ["Previous close", selectedQuote.previous_close, { minimumFractionDigits: 2, maximumFractionDigits: 2 }]);
  }

  return (
    <div className={`${styles.workspace} ${compact ? styles.compact : ""} ${expanded ? styles.expanded : ""}`}>
      <section className={styles.portfolio} aria-labelledby="portfolio-heading">
        <div className={styles.portfolioIntro}><p className="panel-kicker">Quote strip</p><h2 id="portfolio-heading">Portfolio holdings</h2><p role="status" aria-live="polite">{listMessage}</p><p className={styles.hint}>Manual quantities for research only. They are not brokerage positions, valuations, or orders.</p></div>
        <div className={styles.holdingsEditor}>
          <form className={styles.addHolding} onSubmit={(event) => { event.preventDefault(); void saveOneHolding(newSymbol.trim().toUpperCase(), newQuantity); }}>
            <label htmlFor="new-holding-symbol">Add holding symbol<input id="new-holding-symbol" value={newSymbol} onChange={(event) => setNewSymbol(event.target.value.toUpperCase())} maxLength={15} autoComplete="off" placeholder="ACDC" /></label>
            <label htmlFor="new-holding-quantity">Manual quantity<input id="new-holding-quantity" type="number" min="0.000001" step="any" value={newQuantity} onChange={(event) => setNewQuantity(event.target.value)} placeholder="10" /></label>
            <button className="primary" type="submit" disabled={holdingBusy || portfolioState === "loading"}>Add holding</button>
          </form>
          {portfolio.length > 0 && <ul className={styles.holdingRows} aria-label="Saved manual holdings">{portfolio.map((item) => <li key={item.symbol}><span><strong>{item.symbol}</strong><small>{item.assetType.toUpperCase()} · saved {item.quantity ?? "not recorded"}</small></span><label>New quantity<input type="number" min="0.000001" step="any" value={rowQuantities[item.symbol] ?? ""} onChange={(event) => setRowQuantities((current) => ({ ...current, [item.symbol]: event.target.value }))} aria-label={`${item.symbol} new quantity`} /></label><button className="secondary" type="button" onClick={() => void saveOneHolding(item.symbol, rowQuantities[item.symbol] ?? "", item.assetType)} disabled={holdingBusy || rowQuantities[item.symbol] === String(item.quantity ?? "")}>Save</button></li>)}</ul>}
          <details className={styles.bulkEditor}><summary>Bulk edit holdings</summary><p>Enter one holding per line as <code>SYMBOL: quantity</code>. Saving this list replaces removed symbols.</p><form className={styles.portfolioForm} onSubmit={savePortfolio} noValidate>
            <label htmlFor="portfolio-holdings">Symbols and quantities</label>
            <textarea id="portfolio-holdings" value={draft} onChange={(event) => { setDraft(event.target.value.toUpperCase()); setPortfolioError(""); }} maxLength={1599} rows={4} placeholder={'ACDC: 10\nSHOP.TO: 2.5'} aria-invalid={Boolean(portfolioError)} aria-describedby={portfolioError ? "portfolio-holdings-error" : undefined} />
            {portfolioError && <p id="portfolio-holdings-error" className={styles.formError} role="alert">{portfolioError}</p>}
            <button className="secondary" type="submit" disabled={holdingBusy || portfolioState === "loading"}>Update holdings</button>
          </form></details>
        </div>
      </section>

      <section className={styles.tickerPanel} aria-label="Portfolio quote strip" aria-busy={quoteState === "loading"}>
        <div className={styles.tickerControls}>
          <span>{quoteState === "loading" ? "Loading quote snapshots…" : `${quotes.length} quote snapshots${quoteRefreshing ? " · refreshing" : ""}`}</span>
          <span className={styles.refreshNote}>Snapshots refresh every 30 seconds while symbols exist.</span>
          <button className="secondary" type="button" onClick={() => setPaused((current) => !current)} aria-pressed={paused}>{paused ? "Resume visual strip" : "Pause visual strip"}</button>
          <button className="secondary" type="button" onClick={() => setQuoteAttempt((value) => value + 1)}>Refresh</button>
        </div>
        {quoteState === "error" && <div className="error-panel" role="alert"><strong>Quotes unavailable.</strong> {quoteError} <button className="secondary" type="button" onClick={() => setQuoteAttempt((value) => value + 1)}>Retry</button></div>}
        {quoteState === "empty" && <div className="empty-state"><h3>No portfolio quotes</h3><p>Add one or more symbols above.</p></div>}
        {quoteState === "ready" && (
          <div className={`${styles.tickerViewport} ${paused ? styles.paused : ""}`}>
            <div className={styles.tickerTrack}>
              <TickerSet quotes={quotes} identity={identity} onSelect={selectQuote} />
              <TickerSet quotes={quotes} identity={identity} onSelect={selectQuote} duplicate />
            </div>
          </div>
        )}
      </section>

      <div className={styles.workspaceControls} role="group" aria-label="Workspace view controls">
        <button className="secondary" type="button" onClick={() => setCompact((value) => !value)} aria-pressed={compact}>{compact ? "Comfortable density" : "Compact density"}</button>
        <button className="secondary" type="button" onClick={() => setExpanded((value) => !value)} aria-pressed={expanded}>{expanded ? "Restore view" : "Expand view"}</button>
        <button className="secondary" type="button" onClick={() => window.open(`${window.location.pathname}?${identityQuery(identity)}`, "live-trading-popout", "popup,width=1100,height=800")}>Pop out</button>
        <button className="secondary" type="button" onClick={() => setDepthVisible(false)} disabled={!depthVisible}>Close depth</button>
      </div>

      <section className={styles.quoteCard} aria-labelledby="quote-heading">
        <div className={styles.quoteHeading}>
           <div><p className="panel-kicker">Selected quote snapshot</p><h2 id="quote-heading">{identity.symbol || "No symbol selected"} <small>{selectedQuote?.name ?? ""}</small></h2></div>
           <div className={styles.source}><span>Snapshot: {snapshotState(selectedQuote?.state, selectedQuote?.delayed)}</span><span>Provider: {selectedQuote?.provider ?? selectedQuote?.source ?? "Unavailable"}</span><span>As of: {time(selectedQuote?.as_of)}</span><span>Delay: {delay(selectedQuote?.delayed, selectedQuote?.delay_minutes)}</span><span>Currency: {selectedQuote?.currency ?? "Unavailable"}</span></div>
        </div>
        {!selectedQuote && <div className="empty-state" role="status"><h3>Quote unavailable</h3><p>Select an instrument with a returned provider quote. No price is inferred.</p></div>}
        {selectedQuote?.label && <p className={styles.quoteNotice}>{selectedQuote.label}</p>}
        {selectedQuote && <dl className={styles.quoteGrid}>
          {summary.map(([label, value, options]) => <div key={label}><dt>{label}</dt><dd>{number(value, options)}{label === "% change" && value !== undefined ? "%" : ""}</dd></div>)}
        </dl>}
      </section>

      {depthVisible ? (
        <section className={styles.depthCard} aria-labelledby="depth-heading">
          <div className={styles.quoteHeading}>
             <div><p className="panel-kicker">Order-book availability</p><h2 id="depth-heading">Market depth</h2><p className={styles.subhead}>Nasdaq TotalView and live exchange depth are unavailable.</p></div>
             <div className={styles.source}><span>State: unavailable</span><span>Provider: Free data</span><span>As of: Unavailable</span><span>Delay: Unavailable</span></div>
          </div>
          <p className={styles.depthNotice}>Free data has no Nasdaq TotalView or exchange-depth entitlement. No rows are fabricated.</p>
          <details className={styles.depthDisclosure}><summary>Inspect empty bid and ask tables</summary><div className={styles.depthTables}>
            <DepthTable side="Bid" />
            <DepthTable side="Ask" />
          </div></details>
        </section>
      ) : <button className="secondary" type="button" onClick={() => setDepthVisible(true)}>Open depth view</button>}

      <div className={styles.lowerGrid}>
        <section className={styles.notes} aria-labelledby="notes-heading">
          <p className="panel-kicker">Private browser draft</p><h2 id="notes-heading" tabIndex={-1}>Research notes</h2>
          <label htmlFor="live-notes">Notes for {identity.symbol || "this view"} (local only; not sent to the server)</label>
          <textarea id="live-notes" value={notes} onChange={(event) => { const value = event.target.value; setNotes(value); if (identity.symbol) localStorage.setItem(`stock-probs.live-notes.${identity.symbol}`, value); }} maxLength={1000} rows={5} />
        </section>
        <section className={styles.alerts} aria-labelledby="alerts-heading">
          <p className="panel-kicker">Active session only</p><h2 id="alerts-heading" tabIndex={-1}>Price alerts</h2>
          <p>Bell thresholds exist only in this open page. No scheduler or delivery is configured.</p>
          <form onSubmit={addAlert}><label htmlFor="alert-price">Price threshold</label><div><input id="alert-price" type="number" min="0.01" step="0.01" value={threshold} onChange={(event) => setThreshold(event.target.value)} /><button className="secondary" type="submit" aria-label="Add active-session price alert">🔔 Add</button></div></form>
          {alerts.length ? <ul>{alerts.map((price, index) => <li key={`${price}-${index}`}>{identity.symbol} at {price.toFixed(2)} <button type="button" className="secondary" onClick={() => setAlerts((items) => items.filter((_, itemIndex) => itemIndex !== index))}>Remove</button></li>)}</ul> : <p>No active thresholds.</p>}
        </section>
      </div>

      <section className={styles.researchActions} aria-label="Research actions">
        <a className="text-link" data-research-action="forecast" href={`/tools/forecast?${identityQuery(identity)}`}>Forecast this instrument</a>
        <button className="secondary" data-research-action="watchlist" type="button" onClick={addToWatchlist} disabled={!identity.symbol}>Add to watchlist</button>
        <span role="status" aria-live="polite">{watchlistMessage}</span>
      </section>
    </div>
  );
}

// Depth is intentionally empty: free data has no exchange-depth entitlement, and the table
// must not fabricate rows. The empty tbody is the honest representation.
function DepthTable({ side }: { side: "Bid" | "Ask" }) {
  return (
    <div className={styles.depthTableWrap}>
      <h3>{side}</h3>
      <table className={styles.depthTable} role="presentation">
        <thead><tr><th scope="col">Size</th><th scope="col">Price</th></tr></thead>
        <tbody />
      </table>
    </div>
  );
}

function TickerSet({
  quotes,
  identity,
  onSelect,
  duplicate = false,
}: Readonly<{
  quotes: Quote[];
  identity: Identity;
  onSelect: (quote: Quote) => void;
  duplicate?: boolean;
}>) {
  return (
    <div className={styles.tickerSet} aria-hidden={duplicate || undefined}>
      {quotes.map((quote) => (
        duplicate ? <div className={styles.tickerItem} key={`${quote.symbol}-copy`}>
          <strong>{quote.symbol}</strong>
          <span>{number(quotePrice(quote), { minimumFractionDigits: 2 })}</span>
          <small className={(quote.change ?? 0) < 0 ? styles.negative : styles.positive}>
            {typeof quote.change_percent === "number" ? `${number(quote.change_percent, { maximumFractionDigits: 2, signDisplay: "always" })}%` : "Change unavailable"}
          </small>
        </div> : <button
          type="button"
          key={`${quote.symbol}-primary`}
          onClick={() => onSelect(quote)}
          aria-pressed={quote.symbol.toUpperCase() === identity.symbol}
        >
          <strong>{quote.symbol}</strong>
          <span>{number(quotePrice(quote), { minimumFractionDigits: 2 })}</span>
          <small className={(quote.change ?? 0) < 0 ? styles.negative : styles.positive}>
            {typeof quote.change_percent === "number" ? `${number(quote.change_percent, { maximumFractionDigits: 2, signDisplay: "always" })}%` : "Change unavailable"}
          </small>
        </button>
      ))}
    </div>
  );
}
