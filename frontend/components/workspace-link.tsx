"use client";

import type { ReactNode } from "react";
import { useEffect, useState } from "react";

import { instrumentChangeEvent, instrumentFromSearch, instrumentHref } from "./workspace-context-url";

// Client component because the href depends on window.location. It re-derives the instrument
// context on history navigation and on the custom instrument-change event, and sets
// aria-current so the active route is exposed to assistive tech.
export function WorkspaceLink({ path, children, current, className }: Readonly<{ path: string; children: ReactNode; current?: boolean; className?: string }>) {
  const [href, setHref] = useState(path);
  const [active, setActive] = useState(current);
  useEffect(() => {
    const sync = () => {
      setHref(instrumentHref(path, instrumentFromSearch(window.location.search)));
      setActive(current === undefined ? window.location.pathname === path : current);
    };
    sync();
    window.addEventListener("popstate", sync);
    window.addEventListener(instrumentChangeEvent, sync);
    return () => {
      window.removeEventListener("popstate", sync);
      window.removeEventListener(instrumentChangeEvent, sync);
    };
  }, [current, path]);
  return <a className={className} href={href} aria-current={active ? "page" : undefined}>{children}</a>;
}

// Announced via an aria-live status region so a programmatic URL identity change is perceivable
// without a full navigation.
export function SelectedInstrumentStatus() {
  const [label, setLabel] = useState("");
  useEffect(() => {
    const sync = () => {
      const instrument = instrumentFromSearch(window.location.search);
      setLabel(instrument ? `${instrument.displayName} / ${instrument.canonicalSymbol} / ${instrument.exchange}` : "");
    };
    sync();
    window.addEventListener("popstate", sync);
    window.addEventListener(instrumentChangeEvent, sync);
    return () => {
      window.removeEventListener("popstate", sync);
      window.removeEventListener(instrumentChangeEvent, sync);
    };
  }, []);
  return label ? <div className="system-state" role="status" aria-live="polite" aria-label="Selected instrument">{label}</div> : null;
}
