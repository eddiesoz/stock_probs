"use client";

import { useEffect, useState } from "react";
import { apiFetch } from "../auth-client";
import { WorkspaceLink } from "../workspace-link";
import styles from "./monitoring-navigation.module.css";

export function useMonitoringEnabled() {
  const [enabled, setEnabled] = useState(false);
  useEffect(() => {
    const controller = new AbortController();
    apiFetch("/api/v1/monitoring/features", { signal: controller.signal, cache: "no-store" })
      .then(async response => {
        if (!response.ok) return;
        const value: unknown = await response.json();
        if (!controller.signal.aborted && value && typeof value === "object" && "enabled" in value) setEnabled(value.enabled === true);
      }).catch(() => {});
    return () => controller.abort();
  }, []);
  return enabled;
}

export function NotificationsLink() {
  const enabled = useMonitoringEnabled();
  return enabled ? <WorkspaceLink path="/notifications" className={styles.bell}><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9Z" /><path d="M10 21h4" /></svg><span className="sr-only">Notifications</span></WorkspaceLink> : null;
}

export function ReportCardLink() {
  const enabled = useMonitoringEnabled();
  return enabled ? <WorkspaceLink path="/research/report-card">Report card</WorkspaceLink> : null;
}
