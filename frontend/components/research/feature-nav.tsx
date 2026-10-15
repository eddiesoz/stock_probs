// Disabled rollout controls must not advertise unavailable workspace features.
"use client";

import { useEffect, useState } from "react";
import { apiFetch } from "../auth-client";
import { WorkspaceLink } from "../workspace-link";
import styles from "./research.module.css";
import { useMonitoringEnabled } from "../monitoring/feature-nav";

export function ResearchNav() {
  const [enabled, setEnabled] = useState(false);
  const monitoringEnabled = useMonitoringEnabled();
  useEffect(() => {
    const controller = new AbortController();
    apiFetch("/api/v1/research/features", { signal: controller.signal, cache: "no-store" })
      .then(async response => { if (response.ok) { const data = await response.json(); if (!controller.signal.aborted) setEnabled(data.enabled === true); } })
      .catch(() => {});
    return () => controller.abort();
  }, []);
  return enabled || monitoringEnabled ? <nav className={styles.nav} aria-label="Research"><WorkspaceLink path="/research">Ledger</WorkspaceLink>{enabled ? <WorkspaceLink path="/research/theses">Theses</WorkspaceLink> : null}{monitoringEnabled ? <WorkspaceLink path="/research/report-card">Report card</WorkspaceLink> : null}</nav> : null;
}

export function ComparisonLink() {
  const [enabled, setEnabled] = useState(false);
  useEffect(() => {
    const controller = new AbortController();
    apiFetch("/api/v1/research/features", { signal: controller.signal, cache: "no-store" }).then(async response => {
      if (response.ok) { const data = await response.json(); if (!controller.signal.aborted) setEnabled(data.enabled === true); }
    }).catch(() => {});
    return () => controller.abort();
  }, []);
  return enabled ? <WorkspaceLink path="/tools/compare">Compare</WorkspaceLink> : null;
}
