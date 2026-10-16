// Advertise the what-if route only after the authenticated rollout check succeeds.
"use client";

import { useEffect, useState } from "react";
import { apiFetch } from "../auth-client";
import { WorkspaceLink } from "../workspace-link";

export function WhatIfLink({ current = false }: { current?: boolean }) {
  const [enabled, setEnabled] = useState(false);
  useEffect(() => { const controller = new AbortController(); apiFetch("/api/v1/portfolio/features", { signal: controller.signal, cache: "no-store" }).then(async response => { if (response.ok) { const data = await response.json(); if (!controller.signal.aborted) setEnabled(data.enabled === true); } }).catch(() => {}); return () => controller.abort(); }, []);
  return enabled ? <WorkspaceLink path="/tools/what-if" current={current}>What-if</WorkspaceLink> : null;
}
