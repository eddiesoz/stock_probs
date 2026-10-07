"use client";

import { FormEvent, useEffect, useMemo, useRef, useState } from "react";

import { apiFetch } from "../../../components/auth-client";
import { readAssistantMarketsAction } from "../../../components/assistant/assistant-contract";
import { replaceInstrumentInUrl } from "../../../components/workspace-context-url";
import { apiPayload, delay, number, quoteBatches, quotePrice, record, snapshotState, time } from "../client-utils";
import styles from "./workspace.module.css";

type LoadState = "loading" | "ready" | "empty" | "error";
type ChartRange = "5d" | "1mo" | "3mo" | "6mo" | "1y";
type WatchItem = { symbol: string; display_name?: string; provider?: string; exchange?: string; asset_type?: string };
type Quote = WatchItem & {
  last?: number;
  price?: number;
  currency?: string;
  change_percent?: number;
  volume?: number;
  open?: number;
  high?: number;
  low?: number;
  previous_close?: number;
  last_trade?: number;
  source?: string;
  provider?: string;
  as_of?: string;
  delayed?: boolean;
  delay_minutes?: number | null;
  label?: string;
  state?: string;
  sparkline?: number[];
};
type Bar = { timestamp?: string; close?: number; high?: number; low?: number };
type BarsPayload = {
  bars: Bar[];
  source?: string;
  provider?: string;
  as_of?: string;
  state?: string;
  delayed?: boolean;
  delay_minutes?: number | null;
  label?: string;
  adjustment_basis?: string;
  range?: ChartRange;
  interval?: "1d";
};
type Filters = { query: string; exchange: string; assetType: string; minPrice: string; maxPrice: string; minChange: string; maxChange: string; minVolume: string; quoteField: string; quoteMin: string; quoteMax: string };

const emptyFilters: Filters = { query: "", exchange: "", assetType: "", minPrice: "", maxPrice: "", minChange: "", maxChange: "", minVolume: "", quoteField: "", quoteMin: "", quoteMax: "" };
const chartRanges: ReadonlyArray<readonly [ChartRange, string]> = [["5d", "5 days"], ["1mo", "1 month"], ["3mo", "3 months"], ["6mo", "6 months"], ["1y", "1 year"]];
const QUOTE_REFRESH_MS = 30_000;

// Validate each watchlist item strictly and cap at 100; a malformed item fails the whole
// response so the table never renders a half-parsed row.
function watchItems(payload: unknown): WatchItem[] {
  const values = record(payload).items;
  if (!Array.isArray(values)) throw new Error("The local watchlist response was malformed.");
  return values.map((item) => {
    const value = record(item);
    if (
      typeof value.symbol !== "string"
      || typeof value.display_name !== "string"
      || typeof value.exchange !== "string"
      || (value.asset_type !== "stock" && value.asset_type !== "etf")
    ) throw new Error("The local watchlist response contained a malformed item.");
    return {
      symbol: value.symbol.toUpperCase(),
      display_name: value.display_name,
      provider: typeof value.provider === "string" ? value.provider : undefined,
      exchange: value.exchange,
      asset_type: value.asset_type,
    };
  }).slice(0, 100);
}

function quotes(payload: unknown): Quote[] {
  const items = record(payload).items;
  if (!Array.isArray(items)) throw new Error("The local quote response was malformed.");
  return items.map((item) => {
    const value = record(item);
    if (typeof value.symbol !== "string") throw new Error("The local quote response contained a malformed item.");
    return value as Quote;
  });
}

function bars(payload: unknown): BarsPayload {
  const value = record(payload);
  if (!Array.isArray(value.bars)) throw new Error("The local chart response was malformed.");
  const parsed = value.bars.map((item) => {
    const bar = record(item);
    if (typeof bar.timestamp !== "string" || typeof bar.close !== "number") throw new Error("The local chart response contained a malformed bar.");
    return bar as Bar;
  });
  return { ...value, bars: parsed } as BarsPayload;
}

function percent(value?: number) {
  return typeof value === "number" && Number.isFinite(value)
    ? `${number(value, { maximumFractionDigits: 2, signDisplay: "always" })}%`
    : "Unavailable";
}

// Cross-tool links carry the full identity so the target tool can restore the instrument
// without re-looking it up or querying a provider.
function identityQuery(item: WatchItem) {
  return new URLSearchParams({
    symbol: item.symbol,
    asset_type: item.asset_type === "etf" ? "etf" : "stock",
    exchange: item.exchange ?? "",
    provider: item.provider ?? "yahoo",
    display_name: item.display_name ?? item.symbol,
  }).toString();
}

function quoteMetric(item: Quote, field: string) {
  const value = item[field as keyof Quote];
  return typeof value === "number" && Number.isFinite(value) ? value : undefined;
}

export function MarketsWorkspace() {
  const [items, setItems] = useState<WatchItem[]>([]);
  const [listState, setListState] = useState<LoadState>("loading");
  const [listMessage, setListMessage] = useState("");
  const [listAttempt, setListAttempt] = useState(0);
  const [quoteRows, setQuoteRows] = useState<Quote[]>([]);
  const [quoteState, setQuoteState] = useState<LoadState>("loading");
  const [quoteMessage, setQuoteMessage] = useState("");
  const [quoteRefreshing, setQuoteRefreshing] = useState(false);
  const [quoteAttempt, setQuoteAttempt] = useState(0);
  const [selected, setSelected] = useState<WatchItem | null>(null);
  const [barData, setBarData] = useState<BarsPayload | null>(null);
  const [barState, setBarState] = useState<LoadState>("empty");
  const [barMessage, setBarMessage] = useState("");
  const [barAttempt, setBarAttempt] = useState(0);
  const [chartRange, setChartRange] = useState<ChartRange>("1mo");
  const [filters, setFilters] = useState<Filters>(emptyFilters);
  const [sort, setSort] = useState("symbol:asc");
  const [showAllColumns, setShowAllColumns] = useState(false);
  const [edit, setEdit] = useState<WatchItem>({ symbol: "", asset_type: "stock" });
  const [mutationMessage, setMutationMessage] = useState("");
  const initialSelection = useRef<WatchItem | null>(null);
  const quoteGeneration = useRef(0);
  const barGeneration = useRef(0);

  useEffect(() => {
    const refreshWatchlist = () => {
      setMutationMessage("");
      setListAttempt((current) => current + 1);
    };
    window.addEventListener("signal-ledger:assistant-watchlist-updated", refreshWatchlist);
    return () => window.removeEventListener("signal-ledger:assistant-watchlist-updated", refreshWatchlist);
  }, []);

  // URL context seeds the initial selection once; later selection changes are user-driven.
  useEffect(() => {
    const query = new URLSearchParams(window.location.search);
    const symbol = (query.get("symbol") ?? "").toUpperCase();
    initialSelection.current = symbol ? {
      symbol,
      asset_type: query.get("asset_type") === "etf" ? "etf" : "stock",
      exchange: query.get("exchange") ?? "",
      provider: query.get("provider") ?? "yahoo",
      display_name: query.get("display_name") ?? symbol,
    } : null;
    if (initialSelection.current) setSelected(initialSelection.current);
  }, []);

  useEffect(() => {
    const request = new AbortController();
    setListState("loading");
    setListMessage("");
    void (async () => {
      try {
        const response = await fetch("/api/v1/lists?kind=watchlist", { signal: request.signal });
        const payload = await apiPayload(response, `Watchlist request failed (${response.status}).`);
        const loaded = watchItems(payload);
        setItems(loaded);
        setListState(loaded.length ? "ready" : "empty");
        setListMessage(loaded.length ? "Watchlist loaded." : "Your watchlist is empty.");
        if (!initialSelection.current && loaded[0]) selectItem(loaded[0]);
      } catch (error) {
        if (request.signal.aborted) return;
        setItems([]);
        setListState("error");
        setListMessage(error instanceof Error ? error.message : "Server watchlist unavailable.");
      }
    })();
    return () => request.abort();
  }, [listAttempt]);

  // Quotes are fetched in bounded batches (see quoteBatches); the selected symbol is included
  // even before it appears in the loaded list, and results for unrequested symbols are dropped.
  useEffect(() => {
    if (listState === "loading") return;
    const symbols = [...new Set([...(selected ? [selected.symbol] : []), ...items.map((item) => item.symbol)])].slice(0, 100);
    if (!symbols.length) {
      setQuoteRows([]);
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
        setQuoteRows([]);
        setQuoteState("loading");
        setQuoteMessage("");
      } else {
        setQuoteRefreshing(true);
      }
      try {
        const batches = await Promise.all(quoteBatches(symbols).map(async (batch) => {
          const requested = batch.join(",");
          const response = await fetch(`/api/v1/quotes?symbols=${encodeURIComponent(requested)}`, { signal: request?.signal });
          return quotes(await apiPayload(response, `Quote request failed (${response.status}).`));
        }));
        const loaded = batches.flat().filter((item) => symbols.includes(item.symbol.toUpperCase()));
        if (disposed || request?.signal.aborted || generation !== quoteGeneration.current) return;
        setQuoteRows(loaded);
        setQuoteState(loaded.length ? "ready" : "empty");
        setQuoteMessage("");
      } catch (error) {
        if (disposed || request?.signal.aborted || generation !== quoteGeneration.current) return;
        setQuoteMessage(error instanceof Error ? error.message : "Quotes unavailable.");
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
  }, [items, listState, quoteAttempt, selected?.symbol]);

  // One bars request per selected instrument; the captured symbol and abort guard keep a
  // slow earlier response from painting over the newly selected chart.
  useEffect(() => {
    if (!selected?.symbol) {
      setBarData(null);
      setBarState("empty");
      return;
    }
    const requestedSymbol = selected.symbol;
    const generation = ++barGeneration.current;
    const request = new AbortController();
    setBarData(null);
    setBarState("loading");
    setBarMessage("");
    void (async () => {
      try {
        const query = new URLSearchParams({
          symbol: requestedSymbol,
          asset_type: selected.asset_type === "etf" ? "etf" : "stock",
          range: chartRange,
          interval: "1d",
        });
        const response = await fetch(`/api/v1/bars?${query}`, { signal: request.signal });
        const payload = await apiPayload(response, `Chart request failed (${response.status}).`);
        const loaded = bars(payload);
        if (request.signal.aborted || generation !== barGeneration.current) return;
        setBarData(loaded);
        setBarState(loaded.bars.length ? "ready" : "empty");
        if (!loaded.bars.length) setBarMessage("No chart bars are available for this instrument.");
      } catch (error) {
        if (request.signal.aborted || generation !== barGeneration.current) return;
        setBarMessage(error instanceof Error ? error.message : "Chart unavailable.");
        setBarState("error");
      }
    })();
    return () => request.abort();
  }, [selected?.symbol, selected?.asset_type, chartRange, barAttempt]);

  const mergedRows = items.map((item) => ({
    ...item,
    ...quoteRows.find((quote) => quote.symbol.toUpperCase() === item.symbol),
  }));

  // A row is excluded when a requested numeric filter cannot be evaluated, so a missing
  // quote field is never coerced to zero and shown as a match.
  const filteredRows = (() => {
    const value = (text: string) => text.trim().toLowerCase();
    const minPrice = Number(filters.minPrice);
    const maxPrice = Number(filters.maxPrice);
    const minChange = Number(filters.minChange);
    const maxChange = Number(filters.maxChange);
    const minVolume = Number(filters.minVolume);
    const quoteMin = Number(filters.quoteMin);
    const quoteMax = Number(filters.quoteMax);
    const rows = mergedRows.filter((item) => {
      const query = value(filters.query);
      if (query && !`${item.symbol} ${item.display_name ?? ""}`.toLowerCase().includes(query)) return false;
      if (filters.exchange && item.exchange !== filters.exchange) return false;
      if (filters.assetType && item.asset_type !== filters.assetType) return false;
      const price = quotePrice(item);
      if (filters.minPrice && (price === undefined || price < minPrice)) return false;
      if (filters.maxPrice && (price === undefined || price > maxPrice)) return false;
      if (filters.minChange && (item.change_percent === undefined || item.change_percent < minChange)) return false;
      if (filters.maxChange && (item.change_percent === undefined || item.change_percent > maxChange)) return false;
      if (filters.minVolume && (item.volume === undefined || item.volume < minVolume)) return false;
      if (filters.quoteField) {
        const metric = quoteMetric(item, filters.quoteField);
        if (metric === undefined) return false;
        if (filters.quoteMin && metric < quoteMin) return false;
        if (filters.quoteMax && metric > quoteMax) return false;
      }
      return true;
    });
    const [field, direction] = sort.split(":");
    return rows.sort((left, right) => {
      const a = field === "symbol" ? left.symbol : field === "price" ? quotePrice(left) : field === "change" ? left.change_percent : left[field as keyof Quote];
      const b = field === "symbol" ? right.symbol : field === "price" ? quotePrice(right) : field === "change" ? right.change_percent : right[field as keyof Quote];
      const compared = typeof a === "number" && typeof b === "number" ? a - b : String(a ?? "").localeCompare(String(b ?? ""));
      return direction === "desc" ? -compared : compared;
    });
  })();

  const exchanges = useMemo(() => [...new Set(items.map((item) => item.exchange).filter(Boolean))] as string[], [items]);
  const selectedQuote = quoteRows.find((quote) => quote.symbol.toUpperCase() === selected?.symbol) ?? null;
  const hasPreviousClose = mergedRows.some((item) => typeof item.previous_close === "number");

  useEffect(() => {
    const handleAssistantAction = (event: Event) => {
      const detail = (event as CustomEvent<{ action?: unknown; finish?: unknown }>).detail;
      if (typeof detail?.finish !== "function") return;
      const finish = detail.finish as (result: { ok: boolean; message: string }) => void;
      const result = readAssistantMarketsAction(detail.action, {
        route: window.location.pathname,
        selected,
        exchanges,
      });
      if (!result.ok) {
        finish({ ok: false, message: result.message });
        return;
      }
      const action = result.action;
      if (action.type === "market.filters.apply") {
        setFilters({
          query: action.payload.query,
          exchange: action.payload.exchange,
          assetType: action.payload.asset_type,
          minPrice: action.payload.min_price,
          maxPrice: action.payload.max_price,
          minChange: action.payload.min_change,
          maxChange: action.payload.max_change,
          minVolume: action.payload.min_volume,
          quoteField: action.payload.quote_field,
          quoteMin: action.payload.quote_min,
          quoteMax: action.payload.quote_max,
        });
        setSort(action.payload.sort);
      } else if (action.type === "market.chart_range.set") {
        setChartRange(action.payload.range);
      } else if (action.type === "market.columns.set") {
        setShowAllColumns(action.payload.show_all_columns);
      } else if (action.payload.kind === "quotes") {
        setQuoteAttempt((current) => current + 1);
      } else if (action.payload.kind === "watchlist") {
        setMutationMessage("");
        setListAttempt((current) => current + 1);
      } else {
        setBarAttempt((current) => current + 1);
      }
      finish({ ok: true, message: result.message });
    };
    window.addEventListener("signal-ledger:assistant-action", handleAssistantAction);
    return () => window.removeEventListener("signal-ledger:assistant-action", handleAssistantAction);
  }, [exchanges, selected]);

  function selectItem(item: WatchItem) {
    setSelected(item);
    if (item.exchange && (item.asset_type === "stock" || item.asset_type === "etf")) replaceInstrumentInUrl({
      provider: item.provider ?? "yahoo",
      canonicalSymbol: item.symbol,
      assetType: item.asset_type,
      exchange: item.exchange,
      displayName: item.display_name ?? item.symbol,
    });
  }

  async function saveItem(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const item = { symbol: edit.symbol.trim().toUpperCase(), asset_type: edit.asset_type === "etf" ? "etf" : "stock" };
    if (!item.symbol) return;
    setMutationMessage("Saving watchlist item…");
    try {
      const response = await apiFetch("/api/v1/lists", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ kind: "watchlist", item: { symbol: item.symbol, asset_type: item.asset_type } }),
      });
      const payload = await apiPayload(response, `Watchlist update failed (${response.status}).`);
      const next = watchItems(payload);
      setItems(next);
      selectItem(next.find((current) => current.symbol === item.symbol) ?? item);
      setEdit({ symbol: "", asset_type: "stock" });
      setListState(next.length ? "ready" : "empty");
      setMutationMessage("Watchlist item saved.");
    } catch (error) {
      setMutationMessage(error instanceof Error ? error.message : "Watchlist update failed.");
    }
  }

  async function removeItem(item: WatchItem) {
    setMutationMessage(`Removing ${item.symbol}…`);
    try {
      const response = await apiFetch(`/api/v1/lists?kind=watchlist&symbol=${encodeURIComponent(item.symbol)}`, { method: "DELETE" });
      await apiPayload(response, `Watchlist removal failed (${response.status}).`);
      const next = items.filter((current) => current.symbol !== item.symbol);
      setItems(next);
      if (selected?.symbol === item.symbol) next[0] ? selectItem(next[0]) : setSelected(null);
      setListState(next.length ? "ready" : "empty");
      setMutationMessage(`${item.symbol} removed.`);
    } catch (error) {
      setMutationMessage(error instanceof Error ? error.message : "Watchlist removal failed.");
    }
  }

  function updateFilter(name: keyof Filters, value: string) {
    setFilters((current) => ({ ...current, [name]: value }));
  }

  const activeAdvancedFilterCount = [filters.minPrice, filters.maxPrice, filters.minChange, filters.maxChange, filters.minVolume, filters.quoteField, filters.quoteMin, filters.quoteMax].filter(Boolean).length;

  return (
    <>
      <section className={styles.editor} aria-labelledby="watchlist-editor-heading">
        <div><p className="panel-kicker">Watchlist</p><h2 id="watchlist-editor-heading">Add or update an instrument</h2></div>
        <form onSubmit={saveItem}>
          <label>Symbol<input value={edit.symbol} onChange={(event) => setEdit((current) => ({ ...current, symbol: event.target.value.toUpperCase() }))} maxLength={15} required /></label>
          <label>Asset type<select value={edit.asset_type} onChange={(event) => setEdit((current) => ({ ...current, asset_type: event.target.value }))}><option value="stock">Stock</option><option value="etf">ETF</option></select></label>
          <button className="primary" type="submit">Add or update</button>
        </form>
        <p className={styles.status} role="status" aria-live="polite">{mutationMessage || listMessage}</p>
      </section>

      <section className={styles.marketList} aria-labelledby="watchlist-heading">
        <div className={styles.heading}>
          <div><p className="panel-kicker">Saved instruments</p><h2 id="watchlist-heading">Watchlist quotes</h2></div>
           <div className={styles.actions}><span className={styles.refreshNote}>Quote snapshots refresh every 30 seconds while symbols exist{quoteRefreshing ? " · refreshing" : ""}.</span><button className="secondary" type="button" onClick={() => setShowAllColumns((value) => !value)} aria-pressed={showAllColumns}>{showAllColumns ? "Summary columns" : "All quote fields"}</button><button className="secondary" type="button" onClick={() => setListAttempt((value) => value + 1)}>Reload list</button><button className="secondary" type="button" onClick={() => setQuoteAttempt((value) => value + 1)}>Refresh quotes</button></div>
        </div>

        <form className={styles.filters} role="search" onSubmit={(event) => event.preventDefault()}>
          <label>Symbol or name<input type="search" value={filters.query} onChange={(event) => updateFilter("query", event.target.value)} /></label>
          <label>Market / exchange<select value={filters.exchange} onChange={(event) => updateFilter("exchange", event.target.value)}><option value="">All exchanges</option>{exchanges.map((exchange) => <option key={exchange}>{exchange}</option>)}</select></label>
          <label>Asset type<select value={filters.assetType} onChange={(event) => updateFilter("assetType", event.target.value)}><option value="">All types</option><option value="stock">Stock</option><option value="etf">ETF</option></select></label>
          <label>Sort<select value={sort} onChange={(event) => setSort(event.target.value)}><option value="symbol:asc">Symbol A–Z</option><option value="symbol:desc">Symbol Z–A</option><option value="price:desc">Last high–low</option><option value="price:asc">Last low–high</option><option value="change:desc">% change high–low</option><option value="volume:desc">Volume high–low</option><option value="open:desc">Open high–low</option><option value="high:desc">High high–low</option><option value="low:desc">Low high–low</option><option value="last:desc">Last high–low</option><option value="previous_close:desc">Previous close high–low</option><option value="last_trade:desc">Last trade high–low</option></select></label>
          <details className={styles.advancedFilters}>
            <summary>More quote filters{activeAdvancedFilterCount ? ` · ${activeAdvancedFilterCount} active` : ""}</summary>
            <div className={styles.advancedGrid}>
              <label>Minimum price<input type="number" step="0.01" value={filters.minPrice} onChange={(event) => updateFilter("minPrice", event.target.value)} /></label>
              <label>Maximum price<input type="number" step="0.01" value={filters.maxPrice} onChange={(event) => updateFilter("maxPrice", event.target.value)} /></label>
              <label>Minimum % change<input type="number" step="0.01" value={filters.minChange} onChange={(event) => updateFilter("minChange", event.target.value)} /></label>
              <label>Maximum % change<input type="number" step="0.01" value={filters.maxChange} onChange={(event) => updateFilter("maxChange", event.target.value)} /></label>
              <label>Minimum volume<input type="number" step="1" value={filters.minVolume} onChange={(event) => updateFilter("minVolume", event.target.value)} /></label>
              <label>Additional quote metric<select value={filters.quoteField} onChange={(event) => updateFilter("quoteField", event.target.value)}><option value="">None</option><option value="change_percent">% change</option><option value="volume">Volume</option><option value="open">Open</option><option value="high">High</option><option value="low">Low</option><option value="last">Last</option><option value="previous_close">Previous close</option><option value="last_trade">Last trade</option></select></label>
              <label>Metric minimum<input type="number" step="any" value={filters.quoteMin} onChange={(event) => updateFilter("quoteMin", event.target.value)} disabled={!filters.quoteField} /></label>
              <label>Metric maximum<input type="number" step="any" value={filters.quoteMax} onChange={(event) => updateFilter("quoteMax", event.target.value)} disabled={!filters.quoteField} /></label>
            </div>
          </details>
          <button className="secondary" type="button" onClick={() => setFilters(emptyFilters)}>Reset filters</button>
        </form>

         {(listState === "loading" || quoteState === "loading") && <div className="empty-state loading" role="status"><h3>Loading watchlist quote snapshots</h3></div>}
        {listState === "error" && <div className="error-panel" role="alert"><h3>Server watchlist unavailable</h3><p>{listMessage}</p><button className="secondary" type="button" onClick={() => setListAttempt((value) => value + 1)}>Retry</button></div>}
        {quoteState === "error" && <div className="error-panel" role="alert"><h3>Quotes unavailable</h3><p>{quoteMessage}</p><button className="secondary" type="button" onClick={() => setQuoteAttempt((value) => value + 1)}>Retry</button></div>}
        {listState === "empty" && <div className="empty-state"><h3>Your watchlist is empty</h3><p>Add an instrument above.</p></div>}
        {listState !== "loading" && quoteState !== "loading" && items.length > 0 && filteredRows.length === 0 && <div className="empty-state"><h3>No instruments match these filters</h3><button className="secondary" type="button" onClick={() => setFilters(emptyFilters)}>Reset filters</button></div>}
        {listState !== "loading" && quoteState !== "loading" && filteredRows.length > 0 && (
          <div className={styles.tableWrap}>
            <table className={`${styles.table} ${showAllColumns ? styles.fullTable : styles.compactTable}`}>
               <thead><tr><th scope="col">Symbol / name</th><th scope="col">Market</th><th scope="col">Type</th><th scope="col">Last</th><th scope="col">% change</th><th className={styles.secondaryColumn} scope="col">Volume</th><th className={styles.secondaryColumn} scope="col">Open</th><th className={styles.secondaryColumn} scope="col">High</th><th className={styles.secondaryColumn} scope="col">Low</th>{hasPreviousClose && <th className={styles.secondaryColumn} scope="col">Previous close</th>}<th className={styles.secondaryColumn} scope="col">Last trade</th><th className={styles.secondaryColumn} scope="col">Trend</th><th scope="col">Provider / as of / delay</th><th scope="col">Actions</th></tr></thead>
               <tbody>{filteredRows.map((item) => <tr key={item.symbol} className={selected?.symbol === item.symbol ? styles.selected : ""}>
                 <td data-label="Symbol / name"><button className={styles.symbolButton} type="button" onClick={() => selectItem(item)}><strong>{item.symbol}</strong><span>{item.display_name ?? "Name unavailable"}</span></button></td>
                 <td data-label="Market">{item.exchange ?? "—"}</td><td data-label="Type">{item.asset_type ?? "—"}</td>
                  <td data-label="Last">{number(quotePrice(item), { minimumFractionDigits: 2 })}</td><td data-label="% change" className={(item.change_percent ?? 0) < 0 ? styles.negative : styles.positive}>{percent(item.change_percent)}</td><td className={styles.secondaryColumn} data-label="Volume">{number(item.volume, { maximumFractionDigits: 0 })}</td>
                    <td className={styles.secondaryColumn} data-label="Open">{number(item.open, { minimumFractionDigits: 2 })}</td><td className={styles.secondaryColumn} data-label="High">{number(item.high, { minimumFractionDigits: 2 })}</td><td className={styles.secondaryColumn} data-label="Low">{number(item.low, { minimumFractionDigits: 2 })}</td>{hasPreviousClose && <td className={styles.secondaryColumn} data-label="Previous close">{number(item.previous_close, { minimumFractionDigits: 2 })}</td>}<td className={styles.secondaryColumn} data-label="Last trade">{number(item.last_trade, { minimumFractionDigits: 2 })}</td>
                   <td className={styles.secondaryColumn} data-label="Trend"><Sparkline values={item.sparkline ?? []} symbol={item.symbol} /></td><td data-label="Provider / as of / delay"><small>{snapshotState(item.state, item.delayed)}<br />{item.provider ?? item.source ?? "Provider unavailable"}<br />{time(item.as_of)}<br />{delay(item.delayed, item.delay_minutes)}</small></td>
                 <td data-label="Actions"><button className="secondary" type="button" onClick={() => { setEdit(item); selectItem(item); }}>Edit</button><button className="secondary" type="button" onClick={() => void removeItem(item)}>Remove</button></td>
              </tr>)}</tbody>
            </table>
          </div>
        )}
      </section>

      <section className={styles.detail} aria-labelledby="market-detail-heading" aria-busy={barState === "loading"}>
        <div className={styles.heading}>
          <div><p className="panel-kicker">Instrument detail</p><h2 id="market-detail-heading">{selected?.symbol ?? "Select an instrument"} {selected?.display_name ? `· ${selected.display_name}` : ""}</h2></div>
          {selected && <div className={styles.actions}><a className="text-link" href={`/tools/live-trading?${identityQuery(selected)}`}>Live Trading</a><a className="text-link" href={`/tools/forecast?${identityQuery(selected)}`}>Forecast this instrument</a></div>}
        </div>
        {selected && !selectedQuote && quoteState !== "loading" && <div className="empty-state" role="status"><h3>Quote unavailable</h3><p>No provider price, as-of time, or delay status was returned for {selected.symbol}.</p></div>}
         {selectedQuote && <><dl className={styles.detailQuote}><div><dt>Last</dt><dd>{number(quotePrice(selectedQuote), { minimumFractionDigits: 2 })} {selectedQuote.currency ?? "Currency unavailable"}</dd></div><div><dt>% change</dt><dd>{percent(selectedQuote.change_percent)}</dd></div><div><dt>Volume</dt><dd>{number(selectedQuote.volume)}</dd></div><div><dt>Open</dt><dd>{number(selectedQuote.open, { minimumFractionDigits: 2 })}</dd></div><div><dt>High</dt><dd>{number(selectedQuote.high, { minimumFractionDigits: 2 })}</dd></div><div><dt>Low</dt><dd>{number(selectedQuote.low, { minimumFractionDigits: 2 })}</dd></div>{typeof selectedQuote.previous_close === "number" && <div><dt>Previous close</dt><dd>{number(selectedQuote.previous_close, { minimumFractionDigits: 2 })}</dd></div>}<div><dt>Last trade</dt><dd>{number(selectedQuote.last_trade, { minimumFractionDigits: 2 })}</dd></div><div><dt>Quote snapshot / provider / as of / delay</dt><dd>{snapshotState(selectedQuote.state, selectedQuote.delayed)} · {selectedQuote.provider ?? selectedQuote.source ?? "Unavailable"} · {time(selectedQuote.as_of)} · {delay(selectedQuote.delayed, selectedQuote.delay_minutes)}</dd></div></dl>{selectedQuote.label && <p className={styles.provenance}>{selectedQuote.label}</p>}</>}
         {selected && <div className={styles.chartControls}><label htmlFor="chart-range">Chart range<select id="chart-range" value={chartRange} onChange={(event) => setChartRange(event.target.value as ChartRange)}>{chartRanges.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label><span>Daily bars · interval <code>1d</code></span></div>}
        {barState === "loading" && <div className="empty-state loading" role="status"><h3>Loading chart bars</h3></div>}
        {barState === "empty" && <div className="empty-state"><h3>{selected ? "Chart unavailable" : "No instrument selected"}</h3><p>{barMessage || "Choose a watchlist row to inspect its chart."}</p>{selected && <button className="secondary" type="button" onClick={() => setBarAttempt((value) => value + 1)}>Retry</button>}</div>}
        {barState === "error" && <div className="error-panel" role="alert"><h3>Chart request failed</h3><p>{barMessage}</p><button className="secondary" type="button" onClick={() => setBarAttempt((value) => value + 1)}>Retry</button></div>}
        {barState === "ready" && barData && <MarketChart bars={barData.bars} symbol={selected?.symbol ?? ""} range={barData.range} interval={barData.interval} />}
        {barState === "ready" && barData && <details className={styles.chartValues}><summary>Read chart values · latest {Math.min(barData.bars.length, 20)} of {barData.bars.length} daily bars</summary><div className={styles.chartTableWrap}><table><caption>{selected?.symbol} daily closing values</caption><thead><tr><th scope="col">Bar date / time</th><th scope="col">Close</th></tr></thead><tbody>{barData.bars.slice(-20).map((bar, index) => <tr key={`${bar.timestamp}-${index}`}><th scope="row">{time(bar.timestamp)}</th><td>{number(bar.close, { minimumFractionDigits: 2, maximumFractionDigits: 2 })} {selectedQuote?.currency ?? ""}</td></tr>)}</tbody></table></div></details>}
         {barData && <p className={styles.provenance}>Bars snapshot: {snapshotState(barData.state, barData.delayed)} · Provider: {barData.provider ?? barData.source ?? "Unavailable"} · Last bar: {time(barData.bars.at(-1)?.timestamp)} · Retrieved: {time(barData.as_of)} · Delay: {delay(barData.delayed, barData.delay_minutes)} · State: {barData.state ?? "available"}. {barData.label ?? ""} {barData.adjustment_basis ? `Basis: ${barData.adjustment_basis}.` : "Adjustment basis unavailable."}</p>}
      </section>
    </>
  );
}

// Inline sparkline uses the last 20 finite closes; with fewer than two points it reports
// "unavailable" instead of drawing a fabricated line.
function Sparkline({ values, symbol }: { values: number[]; symbol: string }) {
  const finite = values.filter(Number.isFinite).slice(-20);
  if (finite.length < 2) return <span role="img" aria-label={`${symbol} trend unavailable`}>—</span>;
  const low = Math.min(...finite);
  const high = Math.max(...finite);
  const span = high - low || 1;
  const points = finite.map((value, index) => `${index * 80 / (finite.length - 1)},${24 - (value - low) * 20 / span}`).join(" ");
  return <svg className={styles.sparkline} viewBox="0 0 80 28" role="img" aria-label={`${symbol} recent price trend`}><polyline points={points} /></svg>;
}

// A chart needs at least two finite closes; otherwise it shows an empty state rather than
// implying a trend from a single point.
function MarketChart({ bars: values, symbol, range, interval }: { bars: Bar[]; symbol: string; range?: string; interval?: string }) {
  const finite = values.filter((item): item is Bar & { close: number } => typeof item.close === "number" && Number.isFinite(item.close));
  if (finite.length < 2) return <div className="empty-state"><h3>Not enough chart bars</h3></div>;
  const low = Math.min(...finite.map((item) => item.low ?? item.close));
  const high = Math.max(...finite.map((item) => item.high ?? item.close));
  const span = high - low || 1;
  const points = finite.map((item, index) => `${index * 100 / (finite.length - 1)},${38 - (item.close - low) * 34 / span}`).join(" ");
  return <figure className={styles.chart}><figcaption>{symbol} · {range ?? "bounded range"} · {interval ?? "interval unavailable"} bars</figcaption><svg viewBox="0 0 100 42" role="img" aria-label={`${symbol} closing-price chart for ${range ?? "a bounded range"} at ${interval ?? "an unavailable interval"}`} preserveAspectRatio="none"><line x1="0" y1="38" x2="100" y2="38" /><polyline points={points} /></svg><div><span>{time(finite[0].timestamp)}</span><span>{time(finite.at(-1)?.timestamp)}</span></div></figure>;
}
