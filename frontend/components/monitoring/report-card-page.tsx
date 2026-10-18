"use client";

import { useEffect, useState } from "react";
import { AuthRequestError } from "../auth-client";
import { ReportCardWorkspace, type ReportCardSummary, type ReportPanelState } from "./ReportCardWorkspace";
import { monitoringRequest, parseMonitoringFeatures } from "./monitoring-client";
import styles from "./ReportCardWorkspace.module.css";

interface ReportPage extends ReportCardSummary { page: number; page_size: number; total: number; has_next: boolean; denominator_scope: "current_page"; denominator_count: number }

export function ReportCardPage() {
  const [state, setState] = useState<ReportPanelState>("loading");
  const [summary, setSummary] = useState<ReportPage | null>(null);
  const [page, setPage] = useState(1);
  const [reload, setReload] = useState(0);
  const [error, setError] = useState("");
  useEffect(() => {
    const controller = new AbortController();
    setState("loading"); setError("");
    (async () => {
      const feature = parseMonitoringFeatures(await monitoringRequest("/api/v1/monitoring/features", { signal: controller.signal }));
      if (controller.signal.aborted) return;
      if (!feature.enabled) { setState("unavailable"); return; }
      const value = await monitoringRequest(`/api/v1/report-cards?page=${page}&page_size=100`, { signal: controller.signal });
      if (!Array.isArray(value.items) || value.items.length > 100 || value.page !== page || value.page_size !== 100 || value.denominator_scope !== "current_page" || value.denominator_count !== value.items.length || typeof value.has_next !== "boolean" || !Number.isSafeInteger(value.total) || (value.total as number) < value.items.length || typeof value.as_of !== "string" || !Number.isFinite(Date.parse(value.as_of)) || typeof value.label !== "string" || typeof value.sample_limit !== "string") throw new Error("The bounded report response is unavailable.");
      if (controller.signal.aborted) return;
      setSummary(value as unknown as ReportPage); setState("ready");
    })().catch(cause => {
      if (!controller.signal.aborted) { setError(cause instanceof Error ? cause.message : "The report is unavailable."); setState(cause instanceof AuthRequestError && cause.status === 503 ? "unavailable" : "error"); }
    });
    return () => controller.abort();
  }, [page, reload]);
  const scope = summary ? `Metrics and filters describe the ${summary.denominator_count} saved forecasts on page ${summary.page}, out of ${summary.total} matching records. Other pages are excluded from these denominators.` : "Metrics appear only for saved, comparable outcomes.";
  return <main id="main" tabIndex={-1}><h1 className="sr-only" tabIndex={-1}>Forecast report card</h1>
    <ReportCardWorkspace state={state} summary={summary} errorMessage={error} statusMessage={scope} onRetry={() => setReload(value => value + 1)} />
    {summary ? <nav className={styles.pagePagination} aria-label="Report data pages">
      <button className={styles.secondaryButton} type="button" disabled={state === "loading" || page <= 1} onClick={() => setPage(value => value - 1)}>Previous report page</button>
      <span>Page {summary.page} of {Math.max(1, Math.ceil(summary.total / summary.page_size))}</span>
      <button className={styles.secondaryButton} type="button" disabled={state === "loading" || summary.page !== page || !summary.has_next} onClick={() => setPage(value => value + 1)}>Next report page</button>
    </nav> : null}
  </main>;
}
