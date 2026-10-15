"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { AuthRequestError } from "../auth-client";
import { WorkspaceLink } from "../workspace-link";
import { NotificationsWorkspace, type AlertRecord, type NotificationRecord, type NotificationPreferences, type MonitoringPanelState } from "./NotificationsWorkspace";
import { isRecord, monitoringRequest, parseMonitoringFeatures, parseMonitoringPage, parseNotificationVerification, parseVerificationIssue, parseVerifiedAddresses, safeNotificationEmailError, validAlert, validNotification, type MonitoringFeatures, type NotificationVerification, type VerifiedNotificationAddress } from "./monitoring-client";
import styles from "./monitoring-navigation.module.css";

export function NotificationsPage() {
  const [state, setState] = useState<MonitoringPanelState>("loading");
  const [features, setFeatures] = useState<MonitoringFeatures | null>(null);
  const [notifications, setNotifications] = useState<NotificationRecord[]>([]);
  const [alerts, setAlerts] = useState<AlertRecord[]>([]);
  const [preferences, setPreferences] = useState<NotificationPreferences | null>(null);
  const [verifiedAddresses, setVerifiedAddresses] = useState<VerifiedNotificationAddress[] | null>(null);
  const [verification, setVerification] = useState<NotificationVerification | null>(null);
  const [emailLoading, setEmailLoading] = useState(true);
  const [emailBusy, setEmailBusy] = useState(false);
  const [emailError, setEmailError] = useState("");
  const [nextNotifications, setNextNotifications] = useState<string | null>(null);
  const [nextAlerts, setNextAlerts] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const generation = useRef(0);
  const emailGeneration = useRef(0);
  const request = useRef<AbortController | null>(null);
  const writing = useRef(false);
  const emailWriting = useRef(false);

  async function refreshEmailSettings(signal?: AbortSignal) {
    const current = ++emailGeneration.current;
    setEmailLoading(true); setEmailError("");
    const results = await Promise.allSettled([
      monitoringRequest("/api/v1/notification-preferences", { signal }),
      monitoringRequest("/api/v1/notification-addresses", { signal }),
      monitoringRequest("/api/v1/notification-address-verifications/current", { signal }),
    ]);
    if (signal?.aborted || current !== emailGeneration.current) return;
    const errors: string[] = [];
    const preferenceResult = results[0];
    if (preferenceResult.status === "fulfilled") {
      const value = preferenceResult.value;
      const preferenceKeys = ["revision", "alert_email", "digest_email", "digest_time", "digest_timezone", "address_configured", "updated_at"];
      if (Object.keys(value).length === preferenceKeys.length && preferenceKeys.every(key => Object.hasOwn(value, key)) && Number.isSafeInteger(value.revision) && (value.revision as number) >= 0 && typeof value.alert_email === "boolean" && typeof value.digest_email === "boolean" && typeof value.address_configured === "boolean" && typeof value.digest_time === "string" && typeof value.digest_timezone === "string" && (value.updated_at === null || typeof value.updated_at === "string")) {
        setPreferences(value as unknown as NotificationPreferences);
      } else { setPreferences(null); errors.push("preferences"); }
    } else { setPreferences(null); errors.push("preferences"); }
    const addressResult = results[1];
    if (addressResult.status === "fulfilled") {
      try { setVerifiedAddresses(parseVerifiedAddresses(addressResult.value)); }
      catch { setVerifiedAddresses(null); errors.push("addresses"); }
    } else { setVerifiedAddresses(null); errors.push("addresses"); }
    const verificationResult = results[2];
    if (verificationResult.status === "fulfilled") {
      try { setVerification(parseNotificationVerification(verificationResult.value)); }
      catch { setVerification(null); errors.push("verification"); }
    } else if (verificationResult.reason instanceof AuthRequestError && verificationResult.reason.code === "VERIFICATION_UNAVAILABLE") {
      setVerification(null);
    } else { setVerification(null); errors.push("verification"); }
    if (errors.length) setEmailError("Some notification email settings could not be loaded. Refresh before making changes.");
    setEmailLoading(false);
  }

  const load = useCallback(async () => {
    const current = ++generation.current;
    request.current?.abort();
    const controller = new AbortController(); request.current = controller;
    setState("loading"); setError("");
    try {
      const capability = parseMonitoringFeatures(await monitoringRequest("/api/v1/monitoring/features", { signal: controller.signal }));
      if (controller.signal.aborted || current !== generation.current) return;
      setFeatures(capability);
      if (!capability.enabled) { setPreferences(null); setVerifiedAddresses(null); setVerification(null); setEmailLoading(false); setState("unavailable"); return; }
      void refreshEmailSettings(controller.signal);
      const [noticeData, alertData] = await Promise.all([
        monitoringRequest("/api/v1/notifications?limit=100", { signal: controller.signal }),
        monitoringRequest("/api/v1/alerts?limit=100", { signal: controller.signal }),
      ]);
      const notices = parseMonitoringPage(noticeData, validNotification);
      const rules = parseMonitoringPage(alertData, validAlert);
      if (controller.signal.aborted || current !== generation.current) return;
      setNotifications(notices.items); setAlerts(rules.items);
      setNextNotifications(notices.next_cursor); setNextAlerts(rules.next_cursor); setState("ready");
    } catch (cause) {
      if (controller.signal.aborted || current !== generation.current) return;
      setError(cause instanceof Error ? cause.message : "Monitoring could not be loaded.");
      setEmailLoading(false);
      setState(cause instanceof AuthRequestError && cause.status === 503 ? "unavailable" : "error");
    }
  }, []);

  useEffect(() => { void load(); return () => { ++generation.current; request.current?.abort(); }; }, [load]);

  async function write(path: string, body: unknown, method = "POST", idempotencyKey?: string) {
    if (writing.current || emailWriting.current) throw new Error("Wait for the current change to finish.");
    writing.current = true; setBusy(true);
    ++generation.current; request.current?.abort();
    try {
      await monitoringRequest(path, { method, headers: idempotencyKey ? { "Idempotency-Key": idempotencyKey } : undefined, body: JSON.stringify(body) });
      await load();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "The saved change could not be confirmed."); setState("error"); throw cause;
    } finally { writing.current = false; setBusy(false); }
  }

  async function mutateEmail(path: string, body: unknown, method = "POST", idempotencyKey?: string, refreshAfter = true) {
    if (writing.current || emailWriting.current) throw new Error("Wait for the current change to finish.");
    emailWriting.current = true; setEmailBusy(true); setEmailError("");
    try {
      const result = await monitoringRequest(path, { method, headers: idempotencyKey ? { "Idempotency-Key": idempotencyKey } : undefined, body: JSON.stringify(body) });
      if (refreshAfter) await refreshEmailSettings();
      return result;
    } catch (cause) {
      const safe = safeNotificationEmailError(cause);
      setEmailError(safe);
      throw new Error(safe);
    } finally { emailWriting.current = false; setEmailBusy(false); }
  }

  async function requestEmailVerification(address: string, idempotencyKey: string) {
    const result = await mutateEmail("/api/v1/notification-address-verifications", { address }, "POST", idempotencyKey);
    return parseVerificationIssue(result);
  }

  async function replaceEmailVerification(address: string, current: NotificationVerification, idempotencyKey: string) {
    const result = await mutateEmail("/api/v1/notification-address-verifications/regenerate", { address, verification_id: current.verification_id, expected_revision: current.revision }, "POST", idempotencyKey);
    return parseVerificationIssue(result);
  }

  async function confirmEmailVerification(current: NotificationVerification, code: string) {
    const result = await mutateEmail("/api/v1/notification-address-verifications/confirm", { verification_id: current.verification_id, code, expected_revision: current.revision }, "POST", undefined, false);
    if (!isRecord(result) || !["verified", "accepted", "uncertain", "failed", "expired"].includes(result.state as string) || !Number.isSafeInteger(result.revision) || !Number.isSafeInteger(result.attempts)) throw new Error("Verification status is unavailable.");
    const parsed: NotificationVerification = { ...current, state: result.state as NotificationVerification["state"], revision: result.revision as number, attempts: result.attempts as number, address_id: typeof result.address_id === "string" ? result.address_id : current.address_id };
    await refreshEmailSettings();
    return parsed;
  }

  async function selectEmailAddress(addressId: string) {
    if (!preferences) throw new Error("Refresh notification settings before choosing an address.");
    if (!verifiedAddresses?.some(address => address.id === addressId)) throw new Error("The verified address is unavailable.");
    await mutateEmail("/api/v1/notification-addresses/select", { address_id: addressId, expected_revision: preferences.revision });
  }

  async function saveEmailPreference(alertEmail: boolean) {
    if (!preferences) throw new Error("Refresh notification settings before changing email preferences.");
    await mutateEmail("/api/v1/notification-preferences", { expected_revision: preferences.revision, alert_email: alertEmail, digest_email: false }, "PUT");
  }

  async function moreNotices() {
    if (!nextNotifications || writing.current) return;
    writing.current = true; setBusy(true);
    const current = generation.current;
    try {
      const page = parseMonitoringPage(await monitoringRequest(`/api/v1/notifications?limit=100&cursor=${encodeURIComponent(nextNotifications)}`), validNotification);
      if (current !== generation.current) return;
      if (page.items.some(item => notifications.some(existing => existing.id === item.id)) || notifications.length + page.items.length > 1_000) throw new Error("The loaded inbox changed or reached 1,000 notices. Refresh to continue.");
      setNotifications(previous => [...previous, ...page.items]); setNextNotifications(page.next_cursor);
    } catch (cause) { if (current === generation.current) { setError(cause instanceof Error ? cause.message : "More notifications are unavailable."); setState("error"); } }
    finally { writing.current = false; setBusy(false); }
  }

  return <main id="main" tabIndex={-1}>
    <h1 className="sr-only">Notifications</h1>
    <div className={styles.controls}><WorkspaceLink path="/overview">Overview</WorkspaceLink><button type="button" disabled={busy || state === "loading"} onClick={() => { if (!writing.current) void load(); }}>Refresh inbox</button>{nextAlerts ? <p>Additional alert rules are available; only the first 100 are shown.</p> : null}{nextNotifications ? <button type="button" disabled={busy || state !== "ready"} onClick={() => void moreNotices()}>Load older notices</button> : null}</div>
    <NotificationsWorkspace state={state} notifications={notifications} alerts={alerts} preferences={preferences} verifiedAddresses={verifiedAddresses} verification={verification} emailAvailable={features?.email_available === true} emailLoading={emailLoading} emailBusy={emailBusy} emailError={emailError} onRefreshEmailSettings={() => refreshEmailSettings()} errorMessage={error} statusMessage={`Showing ${notifications.length} loaded notices${nextNotifications ? "; older notices are available" : ""}. ${features?.can_arm ? "Checks target a 15-minute cadence." : "Background price checks are currently unavailable; saved observations may be stale."}`} checksAvailable={features?.can_arm === true} reportedAt={features?.reported_at} canCreateAlert={features?.can_arm === true} canResumeAlert={features?.can_arm === true}
      onRequestEmailVerification={requestEmailVerification} onReplaceEmailVerification={replaceEmailVerification} onConfirmEmailVerification={confirmEmailVerification} onSelectEmailAddress={selectEmailAddress} onSaveAlertEmail={saveEmailPreference}
      onCreateAlert={({ config, idempotencyKey }) => write("/api/v1/alerts", config, "POST", idempotencyKey)}
      onPauseAlert={(id, expectedRevision) => write(`/api/v1/alerts/${id}/pause`, { expected_revision: expectedRevision })}
      onResumeAlert={(id, expectedRevision) => write(`/api/v1/alerts/${id}/resume`, { expected_revision: expectedRevision })}
      onSetNotificationRead={(id, expectedRevision, isRead) => write(`/api/v1/notifications/${id}/read`, { expected_revision: expectedRevision, is_read: isRead }, "PUT")} />
  </main>;
}
