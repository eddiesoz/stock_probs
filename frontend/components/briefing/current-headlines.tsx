"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import type { ChangeEvent } from "react";
import { apiFetch } from "../auth-client";
import { createLatestRequestLane } from "./briefing-client.mjs";
import type { BriefingSnapshot } from "./briefing-client.mjs";
import {
  createCurrentHeadlinesClient,
  headlineInstrumentsForSnapshot,
  HeadlinesRequestError,
} from "./headlines-client.mjs";
import type { CurrentNewsResponse, HeadlinesErrorKind } from "./headlines-client.mjs";
import styles from "./briefing.module.css";

type HeadlinesView =
  | { kind: "idle" }
  | { kind: "superseded" }
  | { kind: "loading"; symbol: string; limit: number }
  | { kind: "loaded"; data: CurrentNewsResponse }
  | { kind: "error"; symbol: string; limit: number; error: HeadlinesErrorKind };

function formatNewsDate(value: string | null) {
  if (!value) return "Publication time unavailable";
  const date = new Date(value);
  return Number.isNaN(date.valueOf())
    ? "Publication time unavailable"
    : new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(date);
}

function errorCopy(kind: HeadlinesErrorKind) {
  switch (kind) {
    case "provider_unavailable": return "The news provider is temporarily unavailable. Your saved briefing is unchanged. Try again when ready.";
    case "provider_busy": return "News retrieval is busy. Your saved briefing is unchanged. Try again shortly.";
    case "unreachable": return "The local news service could not be reached. Your saved briefing is unchanged. Try again when it is available.";
    case "malformed": return "Current headlines could not be validated. Your saved briefing is unchanged. Try again.";
    case "rejected": return "The local service rejected this headlines request. Your saved briefing is unchanged.";
    case "authorization": return "Your session has ended. Sign in again to continue.";
  }
}

export function CurrentHeadlines({
  snapshot,
  onSessionFailure,
}: {
  snapshot: BriefingSnapshot | null;
  onSessionFailure: () => void;
}) {
  const client = useMemo(() => createCurrentHeadlinesClient(apiFetch), []);
  const instruments = useMemo(() => headlineInstrumentsForSnapshot(snapshot), [snapshot]);
  const lane = useRef<ReturnType<typeof createLatestRequestLane> | null>(null);
  if (!lane.current) lane.current = createLatestRequestLane();
  const [symbol, setSymbol] = useState("");
  const [view, setView] = useState<HeadlinesView>({ kind: "idle" });

  useEffect(() => () => lane.current?.cancel(), []);

  const chooseInstrument = (event: ChangeEvent<HTMLSelectElement>) => {
    const hadPendingRequest = view.kind === "loading";
    lane.current!.cancel();
    setSymbol(event.target.value);
    setView(hadPendingRequest ? { kind: "superseded" } : { kind: "idle" });
  };

  const loadCurrent = async (limit: number) => {
    if (!symbol) return;
    const request = lane.current!.begin();
    setView({ kind: "loading", symbol, limit });
    try {
      const data = await client.getCurrent({ symbol, limit, signal: request.signal });
      if (request.isCurrent()) setView({ kind: "loaded", data });
    } catch (cause) {
      if (!request.isCurrent() || request.signal.aborted) return;
      const error = cause instanceof HeadlinesRequestError
        ? cause
        : new HeadlinesRequestError("unreachable");
      if (error.kind === "authorization") {
        setView({ kind: "idle" });
        onSessionFailure();
        return;
      }
      setView({ kind: "error", symbol, limit, error: error.kind });
    }
  };

  const retryLimit = view.kind === "error" ? view.limit : 5;
  const canShowMore = view.kind === "loaded" && view.data.query.limit === 5 && view.data.items.length === 5;
  const buttonLabel = view.kind === "loading"
    ? "Loading headlines…"
    : view.kind === "error"
      ? "Retry current headlines"
      : canShowMore
        ? "Show up to 10 headlines"
        : view.kind === "loaded"
          ? "Refresh current headlines"
          : "Load current headlines";
  const loadLimit = view.kind === "error" ? retryLimit : canShowMore ? 10 : view.kind === "loaded" ? view.data.query.limit : 5;
  const statusText = view.kind === "loading"
    ? `Loading current headlines for ${view.symbol}…`
    : view.kind === "superseded"
      ? "The previous headline request was cancelled because the instrument changed. Its results were cleared."
    : view.kind === "error"
      ? errorCopy(view.error)
      : view.kind === "loaded" && view.data.items.length === 0
        ? `No current headlines were returned for ${view.data.query.symbol}.`
        : "";
  const dataState = view.kind === "idle"
    ? "not-requested"
    : view.kind === "superseded"
      ? "superseded"
      : view.kind === "loading"
        ? "loading"
        : view.kind === "error"
          ? view.error === "provider_unavailable"
            ? "provider-unavailable"
            : view.error === "provider_busy"
              ? "capacity-busy"
              : view.error === "unreachable"
                ? "service-unreachable"
                : view.error
          : view.data.items.length === 0
            ? "empty"
            : view.data.cache_state === "stale_fallback"
              ? "stale-fallback"
              : "fresh";

  return (
    <section className={styles.card} aria-labelledby="headlines-heading" aria-busy={view.kind === "loading"}
      data-state={dataState} data-cache-state={view.kind === "loaded" ? view.data.cache_state : undefined}
      data-partial-metadata={view.kind === "loaded" ? String(view.data.coverage.partial_metadata) : undefined}>
      <div className={styles.sectionHead}>
        <div><p className="panel-kicker">Current news context</p><h2 id="headlines-heading">Headlines</h2></div>
      </div>
      <p className={styles.empty}>Choose a saved price or alert instrument to load current headlines. This separate context does not change saved briefing or forecast evidence.</p>
      <div className={styles.headlineControls}>
        <label htmlFor="headlines-instrument">Instrument
          <select id="headlines-instrument" value={symbol} onChange={chooseInstrument}
            disabled={instruments.length === 0} aria-describedby="headlines-instrument-note">
            <option value="">Choose a saved instrument</option>
            {instruments.map((instrument) => (
              <option key={instrument.symbol} value={instrument.symbol}>{instrument.label}</option>
            ))}
          </select>
        </label>
        <button type="button" className="secondary" disabled={!symbol || view.kind === "loading"}
          onClick={() => void loadCurrent(loadLimit)}>{buttonLabel}</button>
      </div>
      <small id="headlines-instrument-note" className={styles.headlineNote}>
        {instruments.length === 0
          ? snapshot
            ? "No saved price or alert instruments are available in this briefing."
            : "Open a saved briefing with a price or alert record to choose an instrument."
          : "Headlines load only when you choose this action."}
      </small>
      {statusText && (
        <p className={view.kind === "error" ? styles.headlineError : styles.headlineStatus}
          role={view.kind === "error" ? "alert" : "status"} aria-live="polite"
          aria-busy={view.kind === "loading"}>
          {statusText}
        </p>
      )}
      {view.kind === "loaded" && (
        <div className={styles.headlineResults} aria-busy="false">
          <p className={styles.headlineMeta}>As of {formatNewsDate(view.data.as_of)} · {view.data.provider}</p>
          {view.data.coverage.refresh_failed && (
            <p className={styles.headlineWarning} role="status">
              The latest refresh failed; these cached headlines are shown as of the time above.
            </p>
          )}
          {view.data.coverage.partial_metadata && (
            <p className={styles.headlineMeta}>Some headlines have no publisher, publication time, or related-symbol details.</p>
          )}
          {view.data.items.length > 0 && (
            <ul className={styles.headlineList}>
              {view.data.items.map((item, index) => (
                <li key={item.id + "/" + index}>
                  <a href={item.url} target="_blank" rel="noopener noreferrer">{item.title}</a>
                  <small>{item.publisher ?? "Publisher unavailable"} · {formatNewsDate(item.published_at)}</small>
                  {item.related_symbols && item.related_symbols.length > 0 && (
                    <small>Related instruments: {item.related_symbols.join(", ")}</small>
                  )}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </section>
  );
}
