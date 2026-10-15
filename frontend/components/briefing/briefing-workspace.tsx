"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { FormEvent } from "react";
import { apiFetch } from "../auth-client";
import { WorkspaceLink } from "../workspace-link";
import { CurrentHeadlines } from "./current-headlines";
import { createBriefingPrivateLifecycle } from "./briefing-private-lifecycle.mjs";
import {
  BriefingRequestError,
  IDLE_REFRESH_STATE,
  classifyBriefingFailure,
  createBriefingClient,
  createLatestRequestLane,
  createSnapshotAttempt,
  refreshButtonModel,
  refreshStateReducer,
} from "./briefing-client.mjs";
import type {
  BriefingSnapshot,
  BriefingState,
  BriefingWindow,
  RefreshState,
  SnapshotAttempt,
} from "./briefing-client.mjs";
import styles from "./briefing.module.css";

type LoadState = "loading" | "ready" | "unavailable";
type ActivityRow = {
  key: string;
  category: string;
  subject: string;
  state: string;
  occurredAt: string;
};

const WINDOW_LABELS: Record<BriefingWindow, string> = {
  since_last_visit: "Since last visit",
  last_24_hours: "Last 24 hours",
  last_7_days: "Last 7 days",
};

function safeError(error: unknown) {
  if (error instanceof BriefingRequestError) return error.message;
  if (error instanceof Error && [
    "The saved briefing response is malformed.",
    "The briefing status response is malformed.",
    "The briefing history response is malformed.",
    "The briefing response exceeded its size limit.",
    "The briefing response is malformed.",
    "The briefing response is unavailable.",
    "Secure request retry is unavailable in this browser.",
    "The request could not be safely prepared.",
    "Briefings are not available for this account yet.",
  ].includes(error.message)) return error.message;
  return "The local briefing service could not be reached. Try again when it is available.";
}

function formatTime(value: string | null) {
  if (!value) return "Not recorded";
  const parsed = new Date(value);
  return Number.isNaN(parsed.valueOf())
    ? "Not recorded"
    : new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(parsed);
}

function dailyEmailStatus() {
  return "Daily email is currently unavailable.";
}

function isAuthorizationFailure(error: unknown) {
  const failure = classifyBriefingFailure(error);
  return failure.kind === "authorization";
}

function authorizationStatus(error: unknown): 401 | 403 {
  const failure = classifyBriefingFailure(error);
  return failure.kind === "authorization" ? failure.status : 401;
}

function formatChange(basisPoints: string | null) {
  if (basisPoints === null) return "Unavailable";
  const numeric = Number(basisPoints);
  if (!Number.isFinite(numeric)) return "Unavailable";
  const percent = numeric / 100;
  const sign = percent > 0 ? "+" : "";
  return sign + percent.toLocaleString(undefined, { maximumFractionDigits: 2 }) + "%";
}

function priceStateLabel(state: BriefingSnapshot["price_changes"][number]["state"]) {
  switch (state) {
    case "threshold_crossed": return "Threshold crossed";
    case "below_threshold": return "Below threshold";
    case "first_observation": return "First observation";
    case "insufficient_history": return "Insufficient history";
    case "unavailable": return "Unavailable";
  }
}

function outcomeStateLabel(state: BriefingSnapshot["outcome_changes"][number]["state"]) {
  switch (state) {
    case "observed": return "Outcome observed";
    case "corrected": return "Outcome corrected";
    case "unavailable": return "Outcome unavailable";
    case "incomparable": return "Not comparable";
    case "manual_review": return "Manual review";
  }
}

function PriceChangeRow({ item }: { item: BriefingSnapshot["price_changes"][number] }) {
  return (
    <li>
      <div className={styles.changeTitle}>
        <strong>{item.symbol}</strong><span>{item.asset_type}</span>
        <b className={item.state === "threshold_crossed" ? styles.positive : ""}>{item.state === "threshold_crossed" || item.state === "below_threshold" ? formatChange(item.change_bps) : priceStateLabel(item.state)}</b>
      </div>
      <p>{priceStateLabel(item.state)}{item.state === "first_observation" ? " · no earlier comparable observation is available" : ""}{item.state === "unavailable" || item.state === "insufficient_history" ? " · the source did not establish a comparable change" : ""}</p>
      <small>{item.currency ?? "Currency unavailable"}{item.provider ? " · " + item.provider : ""} · observed {formatTime(item.observed_at)}</small>
    </li>
  );
}

function OutcomeChangeRow({ item }: { item: BriefingSnapshot["outcome_changes"][number] }) {
  return (
    <li>
      <div className={styles.changeTitle}><strong>Forecast outcome</strong><b>{outcomeStateLabel(item.state)}</b></div>
      <p>Revision {item.revision}{item.correction_of ? " · corrects " + item.correction_of : ""}</p>
      <small>Reference {item.resource_ref} · recorded {formatTime(item.recorded_at)}{item.observed_at ? " · observed " + formatTime(item.observed_at) : ""}</small>
    </li>
  );
}

function AlertRow({ item }: { item: BriefingSnapshot["triggered_alerts"][number] }) {
  return (
    <li>
      <strong>{item.symbol}</strong><span>{item.asset_type} · triggered {formatTime(item.triggered_at)}</span>
      <small>Alert reference {item.resource_ref}</small>
    </li>
  );
}

function activityFor(snapshot: BriefingSnapshot): ActivityRow[] {
  const rows: ActivityRow[] = [
    ...snapshot.price_changes.map((item, index) => ({
      key: "price-" + item.symbol + "-" + index,
      category: "Price movement",
      subject: item.symbol + " · " + item.asset_type,
      state: priceStateLabel(item.state),
      occurredAt: item.observed_at ?? item.baseline_at ?? snapshot.generated_at,
    })),
    ...snapshot.outcome_changes.map((item, index) => ({
      key: "outcome-" + item.resource_ref + "-" + item.revision + "-" + index,
      category: "Forecast outcome",
      subject: "Forecast outcome",
      state: outcomeStateLabel(item.state) + " · revision " + item.revision,
      occurredAt: item.recorded_at,
    })),
    ...snapshot.triggered_alerts.map((item, index) => ({
      key: "alert-" + item.resource_ref + "-" + index,
      category: "Alert",
      subject: item.symbol + " · " + item.asset_type,
      state: "Triggered",
      occurredAt: item.triggered_at,
    })),
    ...snapshot.due_thesis_reviews.map((item, index) => ({
      key: "review-" + item.thesis_ref + "-" + item.revision + "-" + index,
      category: "Thesis review",
      subject: "Thesis review",
      state: "Review due · revision " + item.revision,
      occurredAt: item.due_at,
    })),
  ];
  return rows.sort((left, right) => right.occurredAt.localeCompare(left.occurredAt)).slice(0, 20);
}

function uniqueSnapshots(items: BriefingSnapshot[]) {
  const seen = new Set<string>();
  return items.filter((item) => {
    if (seen.has(item.id)) return false;
    seen.add(item.id);
    return true;
  });
}

export function BriefingWorkspace() {
  const client = useMemo(() => createBriefingClient(apiFetch), []);
  const loadLane = useRef<ReturnType<typeof createLatestRequestLane> | null>(null);
  const openLane = useRef<ReturnType<typeof createLatestRequestLane> | null>(null);
  const historyLane = useRef<ReturnType<typeof createLatestRequestLane> | null>(null);
  const auxiliaryReadLane = useRef<ReturnType<typeof createLatestRequestLane> | null>(null);
  const privateLifecycle = useRef<ReturnType<typeof createBriefingPrivateLifecycle> | null>(null);
  if (!loadLane.current) loadLane.current = createLatestRequestLane();
  if (!openLane.current) openLane.current = createLatestRequestLane();
  if (!historyLane.current) historyLane.current = createLatestRequestLane();
  if (!auxiliaryReadLane.current) auxiliaryReadLane.current = createLatestRequestLane();
  if (!privateLifecycle.current) privateLifecycle.current = createBriefingPrivateLifecycle();
  const alive = useRef(false);

  const [loadState, setLoadState] = useState<LoadState>("loading");
  const [state, setState] = useState<BriefingState | null>(null);
  const [snapshots, setSnapshots] = useState<BriefingSnapshot[]>([]);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [window, setWindow] = useState<BriefingWindow>("since_last_visit");
  const [selected, setSelected] = useState<BriefingSnapshot | null>(null);
  const [busy, setBusy] = useState<"refresh" | "history" | "preference" | "visit" | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [thresholdDraft, setThresholdDraft] = useState("300");
  const [refreshState, setRefreshState] = useState<RefreshState>(IDLE_REFRESH_STATE);
  const [clockNow, setClockNow] = useState(() => Date.now());

  const clearPrivateView = useCallback((statusCode: 401 | 403 = 401) => {
    privateLifecycle.current!.invalidate();
    loadLane.current?.cancel();
    openLane.current?.cancel();
    historyLane.current?.cancel();
    auxiliaryReadLane.current?.cancel();
    setBusy(null);
    setState(null);
    setSnapshots([]);
    setNextCursor(null);
    setSelected(null);
    setThresholdDraft("300");
    setLoadState("unavailable");
    setNotice("");
    setRefreshState({ status: "authorization", statusCode });
  }, []);

  const handleHeadlinesSessionFailure = useCallback(() => {
    clearPrivateView();
    setError("Your session has ended. Sign in again to continue.");
  }, [clearPrivateView]);

  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
      privateLifecycle.current?.invalidate();
      loadLane.current?.cancel();
      openLane.current?.cancel();
      historyLane.current?.cancel();
      auxiliaryReadLane.current?.cancel();
    };
  }, []);

  const retryAt = refreshState.status === "rate_limited" ? refreshState.retryAt : null;
  useEffect(() => {
    if (retryAt === null) return;
    let timer: ReturnType<typeof globalThis.setTimeout> | undefined;
    const updateCountdown = () => {
      const now = Date.now();
      setClockNow(now);
      const remaining = retryAt - now;
      if (remaining > 0) {
        const cadence = remaining > 60_000 ? 10_000 : 1_000;
        timer = globalThis.setTimeout(updateCountdown, Math.min(cadence, remaining));
      }
    };
    updateCountdown();
    return () => { if (timer !== undefined) globalThis.clearTimeout(timer); };
  }, [retryAt]);

  const loadWorkspace = useCallback(async () => {
    const operation = privateLifecycle.current!.capture();
    const request = loadLane.current!.begin();
    operation.commit(() => {
      if (!alive.current) return;
      setLoadState("loading");
      setError("");
    });
    try {
      const [currentState, history] = await Promise.all([
        client.getState({ signal: request.signal }),
        client.listSnapshots({ limit: 20, signal: request.signal }),
      ]);
      if (!request.isCurrent() || !alive.current) return false;
      return operation.commit(() => {
        setState(currentState);
        setThresholdDraft(String(currentState.preference.threshold_bps));
        setSnapshots(history.items);
        setNextCursor(history.next_cursor);
        const latest = history.items[0] ?? null;
        setSelected(latest);
        if (latest) setWindow(latest.window);
        setLoadState(currentState.features.enabled ? "ready" : "unavailable");
        setNotice(latest ? "Showing the newest saved briefing. Its baseline and observation time stay frozen." : "");
      });
    } catch (cause) {
      if (!request.isCurrent() || !alive.current || !operation.isCurrent()) return false;
      if (isAuthorizationFailure(cause)) {
        operation.commit(() => {
          clearPrivateView(authorizationStatus(cause));
          setError(safeError(cause));
        });
        return false;
      }
      operation.commit(() => {
        setError(safeError(cause));
        setLoadState("unavailable");
      });
      return false;
    }
  }, [client, clearPrivateView]);

  useEffect(() => {
    void loadWorkspace();
    return () => loadLane.current?.cancel();
  }, [loadWorkspace]);

  async function reloadSavedWorkspace() {
    const recovery = privateLifecycle.current!.capture();
    const loaded = await loadWorkspace();
    if (loaded && alive.current) recovery.commit(() => setRefreshState(IDLE_REFRESH_STATE));
  }

  function changeWindow(next: BriefingWindow) {
    setWindow(next);
    setSelected(snapshots.find((item) => item.window === next) ?? null);
    setError("");
    setNotice(snapshots.some((item) => item.window === next)
      ? "Showing a saved snapshot for this window; reopening it does not refresh data."
      : "No saved snapshot exists for this window yet. Use Refresh briefing to create one.");
  }

  function refreshFailureMessage(failure: ReturnType<typeof classifyBriefingFailure>) {
    if (failure.kind === "conflict") {
      return "This request conflicts with saved state. Reload saved state to confirm the latest snapshot before starting another request.";
    }
    if (failure.kind === "rate_limited") {
      const seconds = failure.retryAfterSeconds ?? 30;
      if (seconds === 0) return "The service's requested wait has ended. Start a new briefing request when ready.";
      return "The briefing service is limiting requests. Wait at least " + seconds + " seconds before starting another request.";
    }
    if (failure.kind === "uncertain") {
      return "The response was not conclusive. Retrying will reuse the same request key and frozen observation time.";
    }
    return failure.kind === "authorization"
      ? safeError(new BriefingRequestError(failure.status))
      : "The briefing request was rejected. Reload saved state before starting another request.";
  }

  async function refreshBriefing() {
    const control = refreshButtonModel(refreshState, {
      busy: busy !== null,
      available: loadState === "ready" && state?.features.enabled === true,
      hasSnapshot: Boolean(selected),
      nowMs: clockNow,
    });
    if (control.disabled) return;
    const lifecycle = privateLifecycle.current!;
    const lockId = lifecycle.acquireRefresh();
    if (lockId === null) return;
    const operation = lifecycle.capture();

    if (control.action === "reload_state") {
      operation.commit(() => {
        setBusy("refresh");
        setError("");
        setNotice("");
      });
      try {
        const loaded = await loadWorkspace();
        if (loaded && alive.current) operation.commit(() => {
          setRefreshState(IDLE_REFRESH_STATE);
          setNotice("Latest saved state loaded. Review it, then choose Refresh briefing to start a new request.");
        });
      } finally {
        if (lifecycle.ownsRefresh(lockId)) {
          if (alive.current) operation.commit(() => setBusy(null));
          lifecycle.releaseRefresh(lockId);
        }
      }
      return;
    }

    if (control.action !== "new" && control.action !== "retry_same") {
      lifecycle.releaseRefresh(lockId);
      return;
    }
    operation.commit(() => {
      setBusy("refresh");
      setError("");
      setNotice("");
    });
    let attempt: SnapshotAttempt | null = null;
    let attemptStarted = false;
    try {
      if (control.action === "retry_same") {
        if (refreshState.status !== "uncertain") return;
        attempt = refreshState.attempt;
        operation.commit(() => setRefreshState((current) => operation.isCurrent()
          ? refreshStateReducer(current, { type: "retry" }) : current));
        attemptStarted = true;
      } else {
        const stateRequest = auxiliaryReadLane.current!.begin();
        const latestState = await client.getState({ signal: stateRequest.signal });
        if (!stateRequest.isCurrent() || !alive.current || !operation.isCurrent()) return;
        operation.commit(() => {
          setState(latestState);
          setThresholdDraft(String(latestState.preference.threshold_bps));
        });
        if (!latestState.features.enabled) {
          operation.commit(() => setLoadState("unavailable"));
          throw new Error("Briefings are not available for this account yet.");
        }
        attempt = createSnapshotAttempt(window, latestState.server_time);
        operation.commit(() => setRefreshState((current) => operation.isCurrent()
          ? refreshStateReducer(current, { type: "begin", attempt: attempt! }) : current));
        attemptStarted = true;
      }
      if (!attempt) return;
      const snapshot = await client.createSnapshot(attempt);
      if (!alive.current) return;
      operation.commit(() => {
        setRefreshState((current) => operation.isCurrent()
          ? refreshStateReducer(current, { type: "succeeded" }) : current);
        setSelected(snapshot);
        setWindow(snapshot.window);
        setSnapshots((current) => operation.isCurrent()
          ? uniqueSnapshots([snapshot, ...current]).slice(0, 20) : current);
        setNotice("Saved briefing. Baseline " + (snapshot.baseline_at ? formatTime(snapshot.baseline_at) : "first observation")
          + " · prices observed as of " + formatTime(snapshot.observed_as_of) + ".");
      });
    } catch (cause) {
      if (!alive.current || !operation.isCurrent()) return;
      const failure = classifyBriefingFailure(cause);
      if (failure.kind === "authorization") {
        operation.commit(() => {
          clearPrivateView(failure.status);
          setError(refreshFailureMessage(failure));
        });
        return;
      }
      operation.commit(() => {
        if (attemptStarted || failure.kind === "rate_limited") {
          setRefreshState((current) => operation.isCurrent() ? refreshStateReducer(current, {
            type: "failed", failure, at: Date.now(),
          }) : current);
        }
        setError(attemptStarted || failure.kind === "rate_limited"
          ? refreshFailureMessage(failure) : safeError(cause));
      });
    } finally {
      if (lifecycle.ownsRefresh(lockId)) {
        if (alive.current) operation.commit(() => setBusy(null));
        lifecycle.releaseRefresh(lockId);
      }
    }
  }

  async function openSavedSnapshot(snapshotId: string) {
    const operation = privateLifecycle.current!.capture();
    const request = openLane.current!.begin();
    operation.commit(() => {
      setBusy("history");
      setError("");
      setNotice("");
    });
    try {
      const snapshot = await client.getSnapshot(snapshotId, { signal: request.signal });
      if (!request.isCurrent() || !alive.current) return;
      operation.commit(() => {
        setSelected(snapshot);
        setWindow(snapshot.window);
        setNotice("Reopened a saved snapshot. No prices or outcomes were refreshed.");
      });
    } catch (cause) {
      if (!request.isCurrent() || !alive.current || !operation.isCurrent()) return;
      if (isAuthorizationFailure(cause)) {
        operation.commit(() => {
          clearPrivateView(authorizationStatus(cause));
          setError(safeError(cause));
        });
        return;
      }
      operation.commit(() => setError(safeError(cause)));
    } finally {
      if (request.isCurrent() && alive.current) operation.commit(() => setBusy(null));
    }
  }

  async function loadOlderSnapshots() {
    if (!nextCursor || busy) return;
    const operation = privateLifecycle.current!.capture();
    const request = historyLane.current!.begin();
    const cursor = nextCursor;
    operation.commit(() => {
      setBusy("history");
      setError("");
    });
    try {
      const page = await client.listSnapshots({ limit: 20, cursor, signal: request.signal });
      if (!alive.current) return;
      operation.commit(() => {
        setSnapshots((current) => operation.isCurrent() ? uniqueSnapshots([...current, ...page.items]) : current);
        setNextCursor(page.next_cursor);
        setNotice("Loaded older saved briefings. Opening one keeps its original baseline.");
      });
    } catch (cause) {
      if (!request.isCurrent() || !alive.current || !operation.isCurrent()) return;
      if (isAuthorizationFailure(cause)) {
        operation.commit(() => {
          clearPrivateView(authorizationStatus(cause));
          setError(safeError(cause));
        });
        return;
      }
      operation.commit(() => setError(safeError(cause)));
    } finally {
      if (request.isCurrent() && alive.current) operation.commit(() => setBusy(null));
    }
  }

  async function saveThreshold(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!state || busy) return;
    const operation = privateLifecycle.current!.capture();
    const basisPoints = Number(thresholdDraft);
    operation.commit(() => {
      setBusy("preference");
      setError("");
      setNotice("");
    });
    try {
      const preference = await client.updateThreshold(basisPoints, state.preference.revision);
      if (!alive.current) return;
      operation.commit(() => {
        setState((current) => operation.isCurrent() && current ? { ...current, preference } : current);
        setNotice("Threshold saved for new briefings. Existing saved snapshots keep their recorded threshold.");
      });
    } catch (cause) {
      if (!alive.current || !operation.isCurrent()) return;
      if (isAuthorizationFailure(cause)) {
        operation.commit(() => {
          clearPrivateView(authorizationStatus(cause));
          setError(safeError(cause));
        });
        return;
      }
      operation.commit(() => setError(safeError(cause)));
      if (cause instanceof BriefingRequestError && cause.status === 409) {
        const reloadRequest = auxiliaryReadLane.current!.begin();
        try {
          const latestState = await client.getState({ signal: reloadRequest.signal });
          if (alive.current && reloadRequest.isCurrent()) {
            operation.commit(() => {
              setState(latestState);
              setThresholdDraft(String(latestState.preference.threshold_bps));
              setNotice("Another session changed this threshold. The current value has been loaded; review before saving again.");
            });
          }
        } catch (reloadCause) {
          if (alive.current && reloadRequest.isCurrent() && operation.isCurrent()
              && isAuthorizationFailure(reloadCause)) {
            operation.commit(() => {
              clearPrivateView(authorizationStatus(reloadCause));
              setError(safeError(reloadCause));
            });
          }
        }
      }
    } finally {
      if (alive.current) operation.commit(() => setBusy(null));
    }
  }

  async function markReviewed() {
    if (!selected || !state || busy) return;
    const operation = privateLifecycle.current!.capture();
    operation.commit(() => {
      setBusy("visit");
      setError("");
      setNotice("");
    });
    try {
      const anchor = await client.recordVisit(selected.id, state.visit_anchor.revision);
      if (!alive.current) return;
      operation.commit(() => {
        setState((current) => operation.isCurrent() && current ? {
          ...current,
          visit_anchor: {
            revision: anchor.revision,
            baseline_at: anchor.baseline_at,
            snapshot_id: anchor.snapshot_id,
            visited_at: anchor.visited_at,
          },
        } : current);
        setNotice("Reviewed at " + formatTime(anchor.visited_at) + ". This is the baseline for the next since-last-visit briefing; this snapshot is unchanged.");
      });
    } catch (cause) {
      if (!alive.current || !operation.isCurrent()) return;
      if (isAuthorizationFailure(cause)) {
        operation.commit(() => {
          clearPrivateView(authorizationStatus(cause));
          setError(safeError(cause));
        });
        return;
      }
      operation.commit(() => setError(safeError(cause)));
      if (cause instanceof BriefingRequestError && cause.status === 409) {
        const reloadRequest = auxiliaryReadLane.current!.begin();
        try {
          const latestState = await client.getState({ signal: reloadRequest.signal });
          if (alive.current && reloadRequest.isCurrent()) {
            operation.commit(() => {
              setState(latestState);
              setNotice("The visit baseline changed elsewhere. The saved snapshot is unchanged; review the latest baseline before trying again.");
            });
          }
        } catch (reloadCause) {
          if (alive.current && reloadRequest.isCurrent() && operation.isCurrent()
              && isAuthorizationFailure(reloadCause)) {
            operation.commit(() => {
              clearPrivateView(authorizationStatus(reloadCause));
              setError(safeError(reloadCause));
            });
          }
        }
      }
    } finally {
      if (alive.current) operation.commit(() => setBusy(null));
    }
  }

  const activity = selected ? activityFor(selected) : [];
  const priceCrossings = selected?.price_changes.filter((item) => item.state === "threshold_crossed").length ?? 0;
  const firstObservations = selected?.price_changes.filter((item) => item.state === "first_observation").length ?? 0;
  const incompletePrices = selected?.price_changes.filter((item) => ["unavailable", "insufficient_history"].includes(item.state)).length ?? 0;
  const outcomesNeedingReview = selected?.outcome_changes.filter((item) => ["unavailable", "incomparable", "manual_review"].includes(item.state)).length ?? 0;
  const actionsDisabled = busy !== null || loadState !== "ready" || !state?.features.enabled;
  const refreshControl = refreshButtonModel(refreshState, {
    busy: busy !== null,
    available: !actionsDisabled,
    hasSnapshot: Boolean(selected),
    nowMs: clockNow,
  });

  return (
    <main id="main" tabIndex={-1} className={styles.page}>
      <nav className={styles.nav} aria-label="Overview">
        <WorkspaceLink path="/overview">Portfolio</WorkspaceLink>
        <WorkspaceLink path="/overview/transactions">Transactions</WorkspaceLink>
        <WorkspaceLink path="/overview/what-changed" current>What changed?</WorkspaceLink>
      </nav>

      <header className={styles.hero}>
        <div>
          <p className="panel-kicker">Workspace / Overview</p>
          <h1>Your research briefing</h1>
          <p>Review recorded price observations, forecast outcomes, alerts, and due thesis reviews in one saved view.</p>
        </div>
        <aside className={styles.heroAside} aria-label="Briefing freshness">
          <strong>{selected ? "Saved snapshot" : "No saved snapshot selected"}</strong>
          <span>{selected
            ? "Generated " + formatTime(selected.generated_at) + " · observed as of " + formatTime(selected.observed_as_of)
            : "Opening this page never refreshes prices or creates a new snapshot."}</span>
          <span>{dailyEmailStatus()}</span>
        </aside>
      </header>

      <section className={styles.toolbar} aria-label="Briefing controls">
        <label>
          Compare window
          <select
            value={window}
            onChange={(event) => changeWindow(event.target.value as BriefingWindow)}
            disabled={busy !== null || loadState !== "ready" || refreshControl.windowDisabled}
          >
            <option value="since_last_visit">Since last visit</option>
            <option value="last_24_hours">Last 24 hours</option>
            <option value="last_7_days">Last 7 days</option>
          </select>
        </label>
        <button className="primary" type="button" disabled={actionsDisabled || refreshControl.disabled} onClick={() => void refreshBriefing()}>
          {busy === "refresh" ? "Saving briefing…" : refreshControl.label}
        </button>
        <p className={styles.frozenNote}>Refresh is an explicit saved action. Reopening a snapshot keeps its original baseline and as-of time.</p>
      </section>

      <p className={styles.status} role="status" aria-live="polite">
        {loadState === "loading" ? "Loading saved briefing and account settings…" : ""}
        {busy === "refresh" ? (refreshState.status === "uncertain" || refreshState.status === "pending"
          ? "Retrying the same saved request…" : "Creating a new saved snapshot…") : ""}
        {refreshState.status === "uncertain" ? " The request may have reached the service; use the same-request retry to avoid creating a duplicate." : ""}
        {refreshState.status === "rejected" ? " Reload saved state before starting a new request." : ""}
        {refreshState.status === "rate_limited" && refreshControl.action === "wait"
          ? " The service asked you to wait before another request." : ""}
        {refreshState.status === "rate_limited" && !refreshControl.disabled
          ? " The wait has ended. A new request uses a fresh server time and request key." : ""}
        {busy === "history" ? "Opening saved history…" : ""}
        {busy === "preference" ? "Saving threshold…" : ""}
        {busy === "visit" ? "Recording review…" : ""}
        {notice || (loadState === "ready" && !notice ? "Saved snapshots are unchanged until you choose an action." : "")}
      </p>
      {error && (
        <div className={styles.error} role="alert">
          <p>{refreshState.status === "rate_limited" && refreshControl.action === "new"
            ? "The service's requested wait has ended. You may start a fresh request."
            : error}</p>
          {(refreshState.status === "idle" || (loadState === "unavailable" && state === null)) && (
            <button type="button" className="secondary" onClick={() => void reloadSavedWorkspace()} disabled={busy !== null}>
              Retry loading saved briefing
            </button>
          )}
        </div>
      )}
      {state?.features.enabled === false && (
        <div className={styles.notice} role="status">Briefings are not enabled for this account yet. Saved views are read-only when the feature is unavailable.</div>
      )}
      {loadState === "unavailable" && !error && !state && (
        <div className={styles.notice} role="status">The briefing service is unavailable. No refresh, assistant request, or email action was sent.</div>
      )}

      <div className={styles.workspaceGrid}>
        <div className={styles.primaryColumn}>
          <section className={styles.contentGrid} aria-label="What changed">
            <section className={styles.card} aria-labelledby="price-heading">
              <div className={styles.sectionHead}>
                <div><p className="panel-kicker">Market observations</p><h2 id="price-heading">Price moves</h2></div>
                {selected && <span className={styles.pill}>{selected.price_changes.length} {selected.price_changes.length === 1 ? "instrument" : "instruments"}</span>}
              </div>
              {!selected && <p className={styles.empty}>{loadState === "loading" ? "Loading saved price observations…" : "Choose a saved snapshot or create one with Refresh briefing."}</p>}
              {selected && selected.price_changes.length === 0 && <p className={styles.empty}>No price movement records were included in this saved briefing.</p>}
              {selected && selected.price_changes.length > 0 && (
                <>
                  <ul className={styles.changeList}>
                    {selected.price_changes.slice(0, 1).map((item, index) => (
                      <PriceChangeRow key={item.symbol + "/" + item.asset_type + "/" + index} item={item} />
                    ))}
                  </ul>
                  {selected.price_changes.length > 1 && (
                    <details className={styles.moreItems}>
                      <summary>View {selected.price_changes.length - 1} more price {selected.price_changes.length === 2 ? "move" : "moves"}</summary>
                      <ul className={styles.changeList}>
                        {selected.price_changes.slice(1).map((item, index) => (
                          <PriceChangeRow key={item.symbol + "/" + item.asset_type + "/" + (index + 1)} item={item} />
                        ))}
                      </ul>
                    </details>
                  )}
                </>
              )}
              {selected && incompletePrices > 0 && <p className={styles.notice}>Some price records are unavailable or lack enough history. No price or currency is guessed.</p>}
            </section>

            <section className={styles.card} aria-labelledby="outcomes-heading">
              <div className={styles.sectionHead}>
                <div><p className="panel-kicker">Evidence updates</p><h2 id="outcomes-heading">Forecast outcomes</h2></div>
                {selected && <span className={styles.pill}>{selected.outcome_changes.length} {selected.outcome_changes.length === 1 ? "record" : "records"}</span>}
              </div>
              {!selected && <p className={styles.empty}>{loadState === "loading" ? "Loading saved outcome evidence…" : "No saved outcome summary for this window."}</p>}
              {selected && selected.outcome_changes.length === 0 && <p className={styles.empty}>No forecast outcome changes were included in this saved briefing.</p>}
              {selected && selected.outcome_changes.length > 0 && (
                <>
                  <ul className={styles.changeList}>
                    {selected.outcome_changes.slice(0, 1).map((item, index) => (
                      <OutcomeChangeRow key={item.resource_ref + "/" + item.revision + "/" + index} item={item} />
                    ))}
                  </ul>
                  {selected.outcome_changes.length > 1 && (
                    <details className={styles.moreItems}>
                      <summary>View {selected.outcome_changes.length - 1} more {selected.outcome_changes.length === 2 ? "outcome" : "outcomes"}</summary>
                      <ul className={styles.changeList}>
                        {selected.outcome_changes.slice(1).map((item, index) => (
                          <OutcomeChangeRow key={item.resource_ref + "/" + item.revision + "/" + (index + 1)} item={item} />
                        ))}
                      </ul>
                    </details>
                  )}
                </>
              )}
              <p className={styles.disclaimer}>Stored evidence only; forecasts are not rescored.</p>
            </section>

            <section className={styles.card} aria-labelledby="alerts-heading">
              <div className={styles.sectionHead}>
                <div><p className="panel-kicker">Monitoring</p><h2 id="alerts-heading">Alerts</h2></div>
                {selected && <span className={styles.pill}>{selected.triggered_alerts.length} {selected.triggered_alerts.length === 1 ? "trigger" : "triggers"}</span>}
              </div>
              {!selected && <p className={styles.empty}>{loadState === "loading" ? "Loading saved alerts…" : "No saved alert summary for this window."}</p>}
              {selected && selected.triggered_alerts.length === 0 && <p className={styles.empty}>No persisted alert triggers were included in this saved briefing.</p>}
              {selected && selected.triggered_alerts.length > 0 && (
                <>
                  <ul className={styles.compactList}>
                    {selected.triggered_alerts.slice(0, 1).map((item, index) => (
                      <AlertRow key={item.resource_ref + "/" + index} item={item} />
                    ))}
                  </ul>
                  {selected.triggered_alerts.length > 1 && (
                    <details className={styles.moreItems}>
                      <summary>View {selected.triggered_alerts.length - 1} more {selected.triggered_alerts.length === 2 ? "alert" : "alerts"}</summary>
                      <ul className={styles.compactList}>
                        {selected.triggered_alerts.slice(1).map((item, index) => (
                          <AlertRow key={item.resource_ref + "/" + (index + 1)} item={item} />
                        ))}
                      </ul>
                    </details>
                  )}
                </>
              )}
            </section>

            <CurrentHeadlines key={selected?.id ?? "no-snapshot"} snapshot={selected}
              onSessionFailure={handleHeadlinesSessionFailure} />
          </section>

          <section className={styles.card} aria-labelledby="activity-heading">
            <div className={styles.sectionHead}>
              <div><p className="panel-kicker">Saved evidence</p><h2 id="activity-heading">Recent activity</h2></div>
              {selected && <span className={styles.pill}>Snapshot · {WINDOW_LABELS[selected.window]}</span>}
            </div>
            {!selected && <p className={styles.empty}>{loadState === "loading" ? "Loading activity…" : "Activity appears after a briefing snapshot is saved."}</p>}
            {selected && activity.length === 0 && <p className={styles.empty}>No activity rows were included in this saved briefing.</p>}
            {selected && activity.length > 0 && (
              <div className={styles.tableWrap}>
                <table className={styles.table}>
                  <caption>Recent records in this immutable briefing. No balances or thesis text are included.</caption>
                  <thead><tr><th scope="col">Type</th><th scope="col">Record</th><th scope="col">State</th><th scope="col">Recorded time</th></tr></thead>
                  <tbody>{activity.map((row) => (
                    <tr key={row.key}>
                      <td data-label="Type">{row.category}</td>
                      <td data-label="Record">{row.subject}</td>
                      <td data-label="State">{row.state}</td>
                      <td data-label="Recorded time">{formatTime(row.occurredAt)}</td>
                    </tr>
                  ))}</tbody>
                </table>
              </div>
            )}
          </section>
        </div>

        <aside className={styles.sideColumn} aria-label="Research actions and saved history">
          <section className={styles.card} aria-labelledby="reviews-heading">
            <div className={styles.sectionHead}><div><p className="panel-kicker">Research to revisit</p><h2 id="reviews-heading">Thesis reviews</h2></div></div>
            {!selected && <p className={styles.empty}>Open a saved briefing to review its due thesis references.</p>}
            {selected && selected.due_thesis_reviews.length === 0 && <p className={styles.empty}>No due thesis reviews were included in this saved briefing.</p>}
            {selected && selected.due_thesis_reviews.length > 0 && (
              <ul className={styles.reviewList}>
                {selected.due_thesis_reviews.map((item) => (
                  <li key={item.thesis_ref + "/" + item.revision}>
                    <a href={"/research/theses?thesis_id=" + encodeURIComponent(item.thesis_ref)}>Review saved thesis</a>
                    <span>Reference {item.thesis_ref} · revision {item.revision}</span>
                    <small>Due {formatTime(item.due_at)}</small>
                  </li>
                ))}
              </ul>
            )}
          </section>

          <section className={styles.card} aria-labelledby="history-heading">
            <div className={styles.sectionHead}><div><p className="panel-kicker">Immutable history</p><h2 id="history-heading">Saved briefings</h2></div></div>
            {snapshots.length === 0 && <p className={styles.empty}>{loadState === "loading" ? "Loading saved history…" : "No briefing snapshots have been saved yet."}</p>}
            {snapshots.length > 0 && (
              <ul className={styles.historyList}>
                {snapshots.slice(0, 20).map((item) => (
                  <li key={item.id}>
                    <button type="button" className={styles.historyButton} aria-current={selected?.id === item.id ? "true" : undefined}
                      disabled={busy !== null} onClick={() => void openSavedSnapshot(item.id)}>
                      <strong>{WINDOW_LABELS[item.window]}</strong>
                      <span>Generated {formatTime(item.generated_at)}</span>
                      <small>Observed as of {formatTime(item.observed_as_of)}</small>
                    </button>
                  </li>
                ))}
              </ul>
            )}
            {nextCursor && <button className="secondary" type="button" disabled={busy !== null} onClick={() => void loadOlderSnapshots()}>{busy === "history" ? "Loading history…" : "Load older snapshots"}</button>}
          </section>

          <section className={styles.card} aria-labelledby="settings-heading">
            <p className="panel-kicker">Preferences</p><h2 id="settings-heading">Change threshold</h2>
            <p>A 3% default flags larger price moves when enough same-provider, same-currency observations exist.</p>
    <form className={styles.thresholdForm} onSubmit={(event) => void saveThreshold(event)}>
              <label htmlFor="briefing-threshold">Price-change threshold</label>
              <div className={styles.thresholdInput}>
                <input id="briefing-threshold" type="number" min="0.5" max="10" step="0.5"
                  value={Number(thresholdDraft) / 100}
                  onChange={(event) => setThresholdDraft(String(Math.round(Number(event.target.value) * 100)))}
                  disabled={actionsDisabled || busy !== null} />
                <span>%</span>
              </div>
              <small>Saved revision {state?.preference.revision ?? "—"} · applies to new snapshots; existing snapshots keep their recorded threshold.</small>
              <button type="submit" className="secondary" disabled={actionsDisabled || busy !== null
                || !Number.isSafeInteger(Number(thresholdDraft)) || Number(thresholdDraft) < 50 || Number(thresholdDraft) > 1000}>
                {busy === "preference" ? "Saving threshold…" : "Save threshold"}
              </button>
            </form>
          </section>

          <section className={styles.card} aria-labelledby="explain-heading">
            <p className="panel-kicker">Optional help</p><h2 id="explain-heading">Load and Explain</h2>
            <p>Assistant explanations are only started by a selected action. The briefing handoff is not connected yet.</p>
            <button type="button" className="secondary" disabled aria-describedby="explain-note">Explain selected changes</button>
            <small id="explain-note">Unavailable until a reviewed briefing-to-assistant handoff is connected.</small>
            <p className={styles.emailStatus}>{dailyEmailStatus()}</p>
            <button type="button" className="secondary" disabled aria-describedby="email-note">Configure daily email</button>
            <small id="email-note">No email preference was changed or message sent.</small>
          </section>

          {selected && (
            <section className={styles.card} aria-labelledby="reviewed-heading">
              <p className="panel-kicker">Since last visit</p><h2 id="reviewed-heading">Review acknowledgement</h2>
              <p>Marking this snapshot reviewed updates the next since-last-visit baseline. It does not change this saved snapshot.</p>
              <p className={styles.muted}>Current baseline: {formatTime(state?.visit_anchor.baseline_at ?? null)}</p>
              <button type="button" className="secondary" disabled={actionsDisabled || busy !== null}
                onClick={() => void markReviewed()}>{busy === "visit" ? "Recording review…" : "Mark this briefing reviewed"}</button>
            </section>
          )}
        </aside>
      </div>
    </main>
  );
}
