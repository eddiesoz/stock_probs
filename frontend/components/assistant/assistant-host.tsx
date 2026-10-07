"use client";

import { lazy, Suspense, useEffect, useLayoutEffect, useRef, useState } from "react";
import { usePathname, useSearchParams } from "next/navigation";

import { getAuthSession } from "../auth-client";
import { instrumentChangeEvent } from "../workspace-context-url";
import { assistantRequest } from "./assistant-api-client";
import { AssistantClientError, assistantContextRequest, type AssistantContextRequest, type AssistantStatus } from "./assistant-contract";
import styles from "./assistant.module.css";

type HostState = "checking" | "hidden" | "ready";
const AssistantPanel = lazy(() => import("./assistant-panel").then((module) => ({ default: module.AssistantPanel })));

export function AssistantHost() {
  return <Suspense fallback={null}><AssistantHostClient /></Suspense>;
}

function AssistantHostClient() {
  const launcherRef = useRef<HTMLButtonElement>(null);
  const [contextRequest, setContextRequest] = useState<AssistantContextRequest | null>(null);
  const [status, setStatus] = useState<AssistantStatus | null>(null);
  const [hostState, setHostState] = useState<HostState>("checking");
  const [open, setOpen] = useState(false);
  const [isMobileViewport, setIsMobileViewport] = useState(false);
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const search = searchParams?.toString() ?? "";

  useEffect(() => {
    const media = window.matchMedia("(max-width: 699px)");
    const update = () => setIsMobileViewport(media.matches);
    update();
    media.addEventListener("change", update);
    return () => media.removeEventListener("change", update);
  }, []);

  useLayoutEffect(() => {
    if (!open || !isMobileViewport) return;
    const background = document.querySelector<HTMLElement>("[data-assistant-background]");
    if (!background) return;
    const underlayAttribute = "data-assistant-mobile-modal-underlay";
    const previousUnderlayValue = background.getAttribute(underlayAttribute);
    const wasInert = background.inert;
    background.inert = true;
    background.setAttribute(underlayAttribute, "hidden");
    return () => {
      background.inert = wasInert;
      if (previousUnderlayValue === null) {
        background.removeAttribute(underlayAttribute);
      } else {
        background.setAttribute(underlayAttribute, previousUnderlayValue);
      }
    };
  }, [isMobileViewport, open]);

  useEffect(() => {
    if (!open) {
      delete document.body.dataset.assistantOpen;
      return;
    }
    document.body.dataset.assistantOpen = "true";
    return () => { delete document.body.dataset.assistantOpen; };
  }, [open]);

  useEffect(() => {
    const syncLocation = () => {
      setContextRequest(assistantContextRequest({ pathname: window.location.pathname, search: window.location.search }));
    };
    syncLocation();
    window.addEventListener("popstate", syncLocation);
    window.addEventListener(instrumentChangeEvent, syncLocation);
    return () => {
      window.removeEventListener("popstate", syncLocation);
      window.removeEventListener(instrumentChangeEvent, syncLocation);
    };
  }, [pathname, search]);

  useEffect(() => {
    let current = true;
    if (!contextRequest) {
      setStatus(null);
      setOpen(false);
      setHostState("hidden");
      return () => { current = false; };
    }
    // Keep an already-mounted panel and its conversation stable while the page context changes.
    // A transient status refresh must not discard an active stream or visible saved history.
    if (!status) setHostState("checking");
    void (async () => {
      try {
        const session = await getAuthSession();
        if (!session?.authenticated) {
          if (current) {
            setStatus(null);
            setOpen(false);
            setHostState("hidden");
          }
          return;
        }
        if (contextRequest.route === "/admin" && session.user?.role !== "admin") {
          if (current) {
            setStatus(null);
            setOpen(false);
            setHostState("hidden");
          }
          return;
        }
        const result = await assistantRequest<AssistantStatus>("/api/v1/assistant/status");
        if (!current) return;
        setStatus(result);
        // Keep provider-free history and saved conversations available during worker outages.
        setHostState(result.enabled ? "ready" : "hidden");
        if (!result.enabled) setOpen(false);
      } catch (error) {
        if (!current) return;
        const accessRevoked = error instanceof AssistantClientError
          && [401, 403, 404].includes(error.status);
        if (accessRevoked) {
          // The canary status endpoint is deliberately hidden outside the enabled owner scope.
          setStatus(null);
          setOpen(false);
          setHostState("hidden");
        } else if (status) {
          // Preserve provider-free history and the current transcript through transient outages.
          setHostState("ready");
        } else {
          setHostState("hidden");
        }
      }
    })();
    return () => { current = false; };
  }, [contextRequest]);

  function closePanel() {
    setOpen(false);
    window.requestAnimationFrame(() => launcherRef.current?.focus());
  }

  if (hostState !== "ready" || !status || !contextRequest) return null;
  return (
    <>
      {!open ? (
        <button
          ref={launcherRef}
          className={styles.launcher}
          type="button"
          aria-label="Open Ledger assistant"
          onClick={() => setOpen(true)}
        >
          <span className={styles.mark} aria-hidden="true"><i /><i /><i /></span>
          <span>Ledger assistant</span>
        </button>
      ) : (
        <Suspense fallback={<p role="status">Opening Ledger assistant…</p>}>
          <AssistantPanel
            contextRequest={contextRequest}
            initialStatus={status}
            onClose={closePanel}
          />
        </Suspense>
      )}
    </>
  );
}
