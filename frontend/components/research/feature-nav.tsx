// Disabled rollout controls must not advertise unavailable workspace features.
"use client";

import { useEffect, useState } from "react";
import { apiFetch } from "../auth-client";
import { WorkspaceLink } from "../workspace-link";
import styles from "./research.module.css";

export function ResearchNav() {
  const [enabled, setEnabled] = useState(false);
  useEffect(() => {
    const controller = new AbortController();
    apiFetch("/api/v1/research/features", { signal: controller.signal, cache: "no-store" })
      .then(async response => { if (response.ok) { const data = await response.json(); if (!controller.signal.aborted) setEnabled(data.enabled === true); } })
      .catch(() => {});
    return () => controller.abort();
  }, []);
  return enabled ? <nav className={styles.nav} aria-label="Research"><WorkspaceLink path="/research">Ledger</WorkspaceLink><WorkspaceLink path="/research/theses">Theses</WorkspaceLink></nav> : null;
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
