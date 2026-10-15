"use client";

import { useId, useRef, useState, type FormEvent } from "react";

import type { NotificationVerification, VerifiedNotificationAddress } from "./monitoring-client";
import styles from "./NotificationsWorkspace.module.css";

export type MonitoringPanelState = "loading" | "ready" | "error" | "unavailable";

export interface NotificationRecord {
  id: string;
  kind: "price_alert";
  payload: {
    alert_id: string;
    generation: number;
    symbol: string;
    currency: string;
    threshold: string;
    direction: "above" | "below";
    price: string;
    provider: string;
    observed_at: string;
  };
  is_read: boolean;
  revision: number;
  created_at: string;
}

export interface AlertRecord {
  id: string;
  revision: number;
  monitor_revision: number;
  enabled: boolean;
  configured_enabled: boolean;
  baseline_ready: boolean;
  config: {
    symbol: string;
    currency: string;
    threshold: string;
    direction: "above" | "below";
    repeating: boolean;
  };
  arm_generation: number;
  arm_snapshot_generation: number | null;
  arm_snapshot_requested_at: string | null;
  arm_snapshot_received_at: string | null;
  last_side: number | null;
  ready: boolean;
  last_observed_at: string | null;
  last_observation: {
    symbol: string;
    currency: string;
    price: string;
    provider: string;
    observed_at: string;
  } | null;
  last_check_at: string | null;
  last_success_at: string | null;
  state: "arming" | "watching" | "paused" | "triggered" | "unavailable";
  created_at: string;
  updated_at: string;
}

export interface NotificationPreferences {
  revision: number;
  alert_email: boolean;
  digest_email: boolean;
  digest_time: string;
  digest_timezone: string;
  address_configured: boolean;
  updated_at: string | null;
}

export interface AlertConfiguration {
  symbol: string;
  currency: string;
  threshold: string;
  direction: "above" | "below";
  repeating: boolean;
}

export interface AlertCreateSubmission {
  config: AlertConfiguration;
  idempotencyKey: string;
}

export interface NotificationsWorkspaceProps {
  state: MonitoringPanelState;
  notifications: readonly NotificationRecord[];
  alerts: readonly AlertRecord[];
  preferences: NotificationPreferences | null;
  errorMessage?: string;
  statusMessage?: string;
  canCreateAlert?: boolean;
  canResumeAlert?: boolean;
  checksAvailable?: boolean;
  reportedAt?: string;
  onSetNotificationRead?: (
    notificationId: string,
    expectedRevision: number,
    isRead: boolean,
  ) => void | Promise<void>;
  onPauseAlert?: (alertId: string, expectedRevision: number) => void | Promise<void>;
  onResumeAlert?: (alertId: string, expectedRevision: number) => void | Promise<void>;
  onCreateAlert?: (submission: AlertCreateSubmission) => void | Promise<void>;
  verifiedAddresses?: readonly VerifiedNotificationAddress[] | null;
  verification?: NotificationVerification | null;
  emailAvailable?: boolean;
  emailLoading?: boolean;
  emailBusy?: boolean;
  emailError?: string;
  onRefreshEmailSettings?: () => void | Promise<void>;
  onRequestEmailVerification?: (address: string, idempotencyKey: string) => Promise<NotificationVerification>;
  onReplaceEmailVerification?: (address: string, verification: NotificationVerification, idempotencyKey: string) => Promise<NotificationVerification>;
  onConfirmEmailVerification?: (verification: NotificationVerification, code: string) => Promise<NotificationVerification>;
  onSelectEmailAddress?: (addressId: string) => void | Promise<void>;
  onSaveAlertEmail?: (enabled: boolean) => void | Promise<void>;
}

interface AlertDraft {
  symbol: string;
  currency: string;
  threshold: string;
  direction: "above" | "below";
  repeating: boolean;
}

const EMPTY_DRAFT: AlertDraft = {
  symbol: "",
  currency: "",
  threshold: "",
  direction: "above",
  repeating: false,
};

function displayInstant(value: string | null | undefined): string {
  if (!value) return "Not recorded";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.valueOf())) return "Unavailable";
  return `${parsed.toISOString().slice(0, 19).replace("T", " ")} UTC`;
}

function checkIsStale(alert: AlertRecord): boolean {
  if (!alert.last_check_at || !alert.last_success_at) return false;
  const latestCheck = Date.parse(alert.last_check_at);
  const latestSuccess = Date.parse(alert.last_success_at);
  return Number.isFinite(latestCheck) && Number.isFinite(latestSuccess) && latestCheck > latestSuccess;
}

function alertStatus(alert: AlertRecord): { label: string; state: string } {
  if (alert.state === "paused") return { label: "Paused", state: "paused" };
  if (alert.state === "triggered") return { label: "Triggered", state: "triggered" };
  if (alert.state === "unavailable") {
    return { label: "Monitoring unavailable", state: "unavailable" };
  }
  if (!alert.baseline_ready || alert.state === "arming") {
    return { label: "Waiting for initial baseline", state: "pending" };
  }
  if (checkIsStale(alert)) return { label: "Stale · latest check did not succeed", state: "stale" };
  if (alert.enabled && !alert.ready) return { label: "Waiting for price to reset", state: "pending" };
  return { label: alert.enabled ? "Monitoring active" : "Not active", state: "active" };
}

function validDraft(draft: AlertDraft): string | null {
  if (!draft.symbol.trim() || /[^\x20-\x7e]/.test(draft.symbol.trim())) return "Enter a symbol using printable ASCII characters.";
  if (!/^[a-z]{3}$/i.test(draft.currency.trim())) return "Enter a three-letter currency code.";
  const threshold = draft.threshold.trim();
  if (!/^[+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$/.test(threshold) || !Number.isFinite(Number(threshold)) || Number(threshold) <= 0 || Number(threshold) > 1e15) {
    return "Enter a positive finite threshold.";
  }
  return null;
}

function NotificationCard({
  item,
  busy,
  locked,
  onSetRead,
}: {
  item: NotificationRecord;
  busy: boolean;
  locked: boolean;
  onSetRead?: NotificationsWorkspaceProps["onSetNotificationRead"];
}) {
  const { payload } = item;
  const actionLabel = item.is_read ? "Mark unread" : "Mark read";

  return (
    <li className={styles.notificationItem}>
      <article className={styles.notificationCard}>
        <div className={styles.notificationHeading}>
          <div>
            <p className={styles.kicker}>Price threshold crossed</p>
            <h3>{payload.symbol}</h3>
          </div>
          <span className={styles.readState} data-read={item.is_read ? "read" : "unread"}>
            {item.is_read ? "Read" : "Unread"}
          </span>
        </div>
        <p className={styles.crossing}>
          {payload.currency} {payload.price} was {payload.direction === "above" ? "above" : "below"} the {payload.currency} {payload.threshold} threshold.
        </p>
        <dl className={styles.notificationFacts}>
          <div><dt>Observed</dt><dd><time dateTime={payload.observed_at}>{displayInstant(payload.observed_at)}</time></dd></div>
          <div><dt>Provider</dt><dd>{payload.provider}</dd></div>
          <div><dt>Notice created</dt><dd><time dateTime={item.created_at}>{displayInstant(item.created_at)}</time></dd></div>
        </dl>
        <button
          className={styles.secondaryButton}
          type="button"
          disabled={!onSetRead || locked}
          onClick={() => onSetRead?.(item.id, item.revision, !item.is_read)}
        >
          {busy ? "Saving…" : actionLabel}
        </button>
      </article>
    </li>
  );
}

export function NotificationsWorkspace({
  state,
  notifications,
  alerts,
  preferences,
  errorMessage,
  statusMessage,
  canCreateAlert = false,
  canResumeAlert = false,
  checksAvailable,
  reportedAt,
  onSetNotificationRead,
  onPauseAlert,
  onResumeAlert,
  onCreateAlert,
  verifiedAddresses = null,
  verification = null,
  emailAvailable = false,
  emailLoading = false,
  emailBusy = false,
  emailError = "",
  onRefreshEmailSettings,
  onRequestEmailVerification,
  onReplaceEmailVerification,
  onConfirmEmailVerification,
  onSelectEmailAddress,
  onSaveAlertEmail,
}: NotificationsWorkspaceProps) {
  const headingId = useId();
  const formId = useId();
  const [draft, setDraft] = useState<AlertDraft>(EMPTY_DRAFT);
  const [formError, setFormError] = useState("");
  const [localStatus, setLocalStatus] = useState("");
  const [busyAction, setBusyAction] = useState("");
  const [emailAddressDraft, setEmailAddressDraft] = useState("");
  const [verificationCode, setVerificationCode] = useState("");
  const [verifiedAddressDraft, setVerifiedAddressDraft] = useState("");
  const [alertEmailDraft, setAlertEmailDraft] = useState<{ revision: number; enabled: boolean } | null>(null);
  const [acknowledgeDigestOff, setAcknowledgeDigestOff] = useState(false);
  const [emailFormError, setEmailFormError] = useState("");
  const [emailStatus, setEmailStatus] = useState("");
  const inFlightAction = useRef<string | null>(null);
  const pendingCreation = useRef<{ fingerprint: string; key: string } | null>(null);
  const isReadOnly = state !== "ready";
  const selectedAlertEmail = preferences && alertEmailDraft?.revision === preferences.revision ? alertEmailDraft.enabled : preferences?.alert_email === true;
  const replaceableVerification = verification && !verification.invalidated && ["queued", "accepted", "uncertain", "failed", "expired"].includes(verification.state);

  async function runAction(actionKey: string, action: () => void | Promise<void>, success: string): Promise<boolean> {
    // State updates render later; this ref closes the double-click/racing-row gap synchronously.
    if (inFlightAction.current !== null) return false;
    inFlightAction.current = actionKey;
    setBusyAction(actionKey);
    setLocalStatus("Saving the requested change…");
    try {
      await action();
      setLocalStatus(success);
      return true;
    } catch {
      setLocalStatus("The change could not be confirmed. Reload the saved monitoring state before trying again.");
      return false;
    } finally {
      if (inFlightAction.current === actionKey) {
        inFlightAction.current = null;
        setBusyAction("");
      }
    }
  }

  async function submitAlert(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setFormError("");
    if (!onCreateAlert || !canCreateAlert) return;
    const validation = validDraft(draft);
    if (validation) {
      setFormError(validation);
      return;
    }
    if (typeof crypto === "undefined" || typeof crypto.randomUUID !== "function") {
      setFormError("Secure idempotent alert creation is unavailable in this browser.");
      return;
    }
    const config: AlertConfiguration = {
      symbol: draft.symbol.trim().toUpperCase(),
      currency: draft.currency.trim().toUpperCase(),
      threshold: draft.threshold.trim(),
      direction: draft.direction,
      repeating: draft.repeating,
    };
    const fingerprint = JSON.stringify(config);
    if (pendingCreation.current?.fingerprint !== fingerprint) {
      pendingCreation.current = { fingerprint, key: crypto.randomUUID() };
    }
    const idempotencyKey = pendingCreation.current.key;
    const submitted = await runAction("create-alert", () => onCreateAlert({ config, idempotencyKey }), "The alert request was submitted. Review the returned saved state before relying on it.");
    if (submitted) {
      pendingCreation.current = null;
      setDraft(EMPTY_DRAFT);
    }
  }

  async function requestVerification(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setEmailFormError(""); setEmailStatus("");
    if (!emailAvailable || emailError || !onRequestEmailVerification || isReadOnly || emailBusy) { setEmailFormError("Email verification is unavailable right now. Refresh settings and try again later."); return; }
    if (typeof crypto === "undefined" || typeof crypto.randomUUID !== "function") { setEmailFormError("Secure verification requests are unavailable in this browser."); return; }
    const address = emailAddressDraft.trim();
    if (!address || address.length > 320 || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(address)) { setEmailFormError("Enter a valid email address to request verification."); return; }
    if (verification && !verification.invalidated && verification.state === "submitting") { setEmailFormError("This verification request is still processing. Refresh status before requesting another code."); return; }
    try {
      const key = crypto.randomUUID();
      const next = replaceableVerification && onReplaceEmailVerification
        ? await onReplaceEmailVerification(address, verification, key)
        : await onRequestEmailVerification(address, key);
      setEmailAddressDraft(""); setVerificationCode(""); setEmailStatus(verificationMessage(next));
    } catch {
      setEmailFormError("The verification request could not be confirmed. Refresh notification email settings before trying again.");
    }
  }

  async function confirmVerification(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setEmailFormError(""); setEmailStatus("");
    if (!verification || verification.invalidated || emailError || !onConfirmEmailVerification || isReadOnly || emailBusy) return;
    const code = verificationCode.trim();
    setVerificationCode("");
    if (!/^[A-Za-z0-9_-]{43}$/.test(code)) { setEmailFormError("Enter the 43-character one-time code from the verification message."); return; }
    try {
      const result = await onConfirmEmailVerification(verification, code);
      setEmailStatus(result.state === "verified" ? "Address verified. Select it below if you want it to receive alert email." : "The code was not accepted. Check it and try again before the request expires.");
    } catch {
      setEmailFormError("The code could not be confirmed. Refresh verification status before trying again.");
    }
  }

  async function selectVerifiedAddress(addressId: string) {
    setEmailFormError(""); setEmailStatus("");
    if (!onSelectEmailAddress || isReadOnly || emailBusy || !preferences) return;
    const accepted = await runAction("select-email-address", () => onSelectEmailAddress(addressId), "Verified recipient selected. Alert email remains off until you opt in.");
    if (accepted) setVerifiedAddressDraft(addressId);
  }

  async function saveAlertEmail(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setEmailFormError(""); setEmailStatus("");
    if (!preferences || !onSaveAlertEmail || isReadOnly || emailBusy) return;
    if (selectedAlertEmail && !emailAvailable) { setEmailFormError("Email delivery is unavailable. Turn alert email off or refresh later."); return; }
    if (selectedAlertEmail && !preferences.address_configured) { setEmailFormError("Select a verified recipient before opting in to alert email."); return; }
    if (preferences.digest_email && !acknowledgeDigestOff) { setEmailFormError("Confirm that this save will turn off the unavailable daily digest."); return; }
    const accepted = await runAction("save-alert-email", () => onSaveAlertEmail(selectedAlertEmail), selectedAlertEmail ? "Alert email is opted in for the selected verified recipient." : "Alert email is opted out.");
    if (accepted) { setAlertEmailDraft(null); setAcknowledgeDigestOff(false); setVerifiedAddressDraft(""); }
  }

  const stateMessage = state === "loading"
    ? "Loading saved notifications and alert rules…"
    : state === "error"
      ? `${errorMessage || "Monitoring data could not be loaded."}${notifications.length || alerts.length ? " Previously loaded records may be stale." : ""}`
      : state === "unavailable"
        ? "Monitoring is unavailable. Any displayed saved observations may be stale."
        : statusMessage || "Monitoring records are up to date with the latest response.";

  return (
    <section className={styles.workspace} aria-labelledby={headingId} aria-busy={state === "loading"}>
      <header className={styles.pageHead}>
        <div>
          <p className={styles.kicker}>Private monitoring</p>
          <h2 id={headingId}>Notifications</h2>
          <p>Review saved threshold notices and manage rules. Monitoring does not place trades.</p>
        </div>
        <span className={styles.scopeBadge}>Owner account only</span>
      </header>

      <div className={state === "error" ? styles.errorBanner : styles.stateBanner} role={state === "error" ? "alert" : "status"} aria-live={state === "error" ? "assertive" : "polite"}>
        {stateMessage}
      </div>
      {localStatus ? <p className={styles.actionStatus} role="status" aria-live="polite">{localStatus}</p> : null}

      <div className={styles.infoBanner}>
        <strong>Checks target a 15-minute cadence when monitoring is available.</strong>
        <span>Provider timing can be delayed. A price can cross and return between checks, so a brief crossing may be missed. Always review the last check and its observation time.</span>
      </div>

      <div className={styles.topGrid}>
        <section className={styles.panel} aria-labelledby={`${headingId}-inbox`}>
          <div className={styles.panelHeading}>
            <div>
              <p className={styles.kicker}>Saved notices</p>
              <h3 id={`${headingId}-inbox`}>Inbox</h3>
            </div>
            <span className={styles.countBadge}>{notifications.length} shown</span>
          </div>
          {state === "loading" && notifications.length === 0 ? (
            <div className={styles.emptyState} role="status">Loading notifications…</div>
          ) : state !== "ready" && notifications.length === 0 ? (
            <div className={styles.emptyState}>Saved notifications are unavailable until the service responds.</div>
          ) : notifications.length === 0 ? (
            <div className={styles.emptyState}>
              <strong>No threshold notices yet</strong>
              <span>When a saved rule records a crossing, the owner-safe notice will appear here.</span>
            </div>
          ) : (
            <ul className={styles.notificationList}>
              {notifications.map((item) => (
                <NotificationCard
                  key={item.id}
                  item={item}
                  busy={busyAction === `read:${item.id}`}
                  locked={busyAction !== "" || isReadOnly}
                  onSetRead={onSetNotificationRead ? async (id, revision, isRead) => {
                    await runAction(
                      `read:${id}`,
                      () => onSetNotificationRead(id, revision, isRead),
                      "Read state saved. The inbox will reflect the server-confirmed revision.",
                    );
                  } : undefined}
                />
              ))}
            </ul>
          )}
        </section>

        <section className={styles.panel} aria-labelledby={`${headingId}-create`}>
          <div className={styles.panelHeading}>
            <div>
              <p className={styles.kicker}>Explicit rule setup</p>
              <h3 id={`${headingId}-create`}>Create a threshold alert</h3>
            </div>
          </div>
          <p className={styles.formIntro}>Set the condition you want to monitor. Saving a rule requires a trusted initial observation before checks can be armed.</p>
          {!canCreateAlert || !onCreateAlert ? (
            <p className={styles.unavailableNote}>
              Alert creation is currently unavailable until the service can commit and verify an initial price baseline. This form does not arm a rule.
            </p>
          ) : null}
          <form id={formId} className={styles.alertForm} onSubmit={submitAlert} noValidate>
            <label>
              <span>Symbol</span>
              <input autoComplete="off" disabled={busyAction !== ""} maxLength={80} value={draft.symbol} onChange={(event) => setDraft((current) => ({ ...current, symbol: event.target.value }))} />
            </label>
            <label>
              <span>Currency</span>
              <input autoComplete="off" disabled={busyAction !== ""} maxLength={3} value={draft.currency} onChange={(event) => setDraft((current) => ({ ...current, currency: event.target.value }))} />
            </label>
            <label>
              <span>Threshold price</span>
              <input disabled={busyAction !== ""} inputMode="decimal" maxLength={64} value={draft.threshold} onChange={(event) => setDraft((current) => ({ ...current, threshold: event.target.value }))} />
            </label>
            <label>
              <span>Notify when price is</span>
              <select disabled={busyAction !== ""} value={draft.direction} onChange={(event) => setDraft((current) => ({ ...current, direction: event.target.value as AlertDraft["direction"] }))}>
                <option value="above">Above the threshold</option>
                <option value="below">Below the threshold</option>
              </select>
            </label>
            <fieldset className={styles.choiceGroup} disabled={busyAction !== ""}>
              <legend>When the condition crosses</legend>
              <label className={styles.repeatChoice}>
                <input type="radio" name={`${formId}-repeat`} checked={!draft.repeating} onChange={() => setDraft((current) => ({ ...current, repeating: false }))} />
                <span>One notice</span>
              </label>
              <label className={styles.repeatChoice}>
                <input type="radio" name={`${formId}-repeat`} checked={draft.repeating} onChange={() => setDraft((current) => ({ ...current, repeating: true }))} />
                <span>Allow another notice after a later crossing</span>
              </label>
            </fieldset>
            <fieldset className={styles.choiceGroup} disabled={busyAction !== ""}>
              <legend>Delivery method</legend>
              <label className={styles.repeatChoice}>
                <input type="checkbox" checked disabled aria-label="In-app inbox delivery selected" />
                <span>In-app inbox <small>Saved to this private workspace</small></span>
              </label>
              <label className={styles.repeatChoice}>
                <input type="checkbox" disabled aria-describedby={`${formId}-email-unavailable`} />
                <span>Email <small>Unavailable</small></span>
              </label>
              <p className={styles.deliveryNote} id={`${formId}-email-unavailable`}>
                Email alerts are not configured per rule. Account-wide email preferences do not enable delivery for this alert.
              </p>
            </fieldset>
            {formError ? <p className={styles.formError} role="alert">{formError}</p> : null}
            <button className={styles.primaryButton} type="submit" disabled={!canCreateAlert || !onCreateAlert || isReadOnly || busyAction !== ""}>
              {busyAction === "create-alert" ? "Submitting…" : "Save alert request"}
            </button>
          </form>
        </section>
      </div>

      <section className={styles.panel} aria-labelledby={`${headingId}-rules`}>
        <div className={styles.panelHeading}>
          <div>
            <p className={styles.kicker}>Saved conditions</p>
            <h3 id={`${headingId}-rules`}>Alert rules</h3>
          </div>
          <span className={styles.countBadge}>{alerts.length} shown</span>
        </div>
        {alerts.length === 0 && state !== "ready" ? (
          <div className={styles.emptyState}>Saved alert rules are unavailable until the service responds.</div>
        ) : alerts.length === 0 ? (
          <div className={styles.emptyState}>
            <strong>No alert rules are recorded</strong>
            <span>A rule appears here only after the local service confirms it was saved.</span>
          </div>
        ) : (
          <ul className={styles.alertList}>
            {alerts.map((alert) => {
              const checkAge = reportedAt && alert.last_success_at ? Date.parse(reportedAt) - Date.parse(alert.last_success_at) : null;
              const overdue = alert.state === "watching" && checkAge !== null && checkAge > 900_000;
              const status = checksAvailable === false && alert.configured_enabled && alert.state !== "triggered" ? { state: "unavailable", label: "Checks unavailable" } : overdue ? { state: "stale", label: "Check overdue" } : alertStatus(alert);
              const canPause = alert.configured_enabled && ["arming", "watching", "unavailable"].includes(alert.state) && Boolean(onPauseAlert) && !isReadOnly;
              const canResume = ["paused", "triggered"].includes(alert.state) && canResumeAlert && Boolean(onResumeAlert) && !isReadOnly;
              return (
                <li className={styles.alertItem} key={alert.id}>
                  <article className={styles.alertCard}>
                    <div className={styles.alertTitle}>
                      <div>
                        <h4>{alert.config.symbol}</h4>
                        <p>{alert.config.currency} {alert.config.threshold} · {alert.config.direction === "above" ? "Above" : "Below"} threshold{alert.config.repeating ? " · Repeating" : " · One notice"}</p>
                      </div>
                      <span className={styles.statusBadge} data-state={status.state}>{status.label}</span>
                    </div>
                    {!alert.baseline_ready ? <p className={styles.alertNote}>Waiting for a verified initial baseline. The rule is not active until that observation is saved.</p> : null}
                    {checkIsStale(alert) ? <p className={styles.staleNote}>Latest check failed; the last successful observation may be stale.</p> : null}
                    {overdue ? <p className={styles.staleNote}>The last successful check is more than 15 minutes old. A crossing may have been missed.</p> : null}
                    {alert.state === "unavailable" ? <p className={styles.unavailableNote}>Monitoring status is unavailable. Do not rely on an old observation as current.</p> : null}
                    {alert.state === "watching" && !alert.ready && checksAvailable !== false ? <p className={styles.alertNote}>The initial baseline is saved. A later notice requires the price to return to the opposite side and cross again.</p> : null}
                    <dl className={styles.alertFacts}>
                      <div><dt>Last check</dt><dd><time dateTime={alert.last_check_at ?? undefined}>{displayInstant(alert.last_check_at)}</time></dd></div>
                      <div><dt>Last successful check</dt><dd><time dateTime={alert.last_success_at ?? undefined}>{displayInstant(alert.last_success_at)}</time></dd></div>
                      <div><dt>Last observation</dt><dd>{alert.last_observation ? <><span>{alert.last_observation.currency} {alert.last_observation.price} · {alert.last_observation.provider}</span><small><time dateTime={alert.last_observation.observed_at}>{displayInstant(alert.last_observation.observed_at)}</time></small></> : "No observation recorded"}</dd></div>
                    </dl>
                    {(onPauseAlert || onResumeAlert) ? (
                      <div className={styles.alertActions}>
                        {["arming", "watching", "unavailable"].includes(alert.state) ? <button className={styles.secondaryButton} type="button" disabled={!canPause || busyAction !== ""} onClick={() => onPauseAlert && void runAction(`pause:${alert.id}`, () => onPauseAlert(alert.id, alert.revision), "Pause request submitted. Confirm the updated saved revision before relying on it.")}>Pause alert</button> : null}
                        {["paused", "triggered"].includes(alert.state) ? <button className={styles.secondaryButton} type="button" disabled={!canResume || busyAction !== ""} onClick={() => onResumeAlert && void runAction(`resume:${alert.id}`, () => onResumeAlert(alert.id, alert.revision), "Resume request submitted. A verified fresh baseline is required before monitoring is active.")}>{alert.state === "triggered" ? "Re-arm alert" : "Resume alert"}</button> : null}
                        {["paused", "triggered"].includes(alert.state) && !canResume ? <span className={styles.actionHint}>Resume is unavailable until a fresh verified baseline can be committed.</span> : null}
                      </div>
                    ) : null}
                  </article>
                </li>
              );
            })}
          </ul>
        )}
      </section>

      <section className={styles.preferencesPanel} aria-labelledby={`${headingId}-preferences`}>
        <div>
          <p className={styles.kicker}>Recipient and delivery controls</p>
          <h3 id={`${headingId}-preferences`}>Email notifications</h3>
          <p className={styles.formIntro}>Verifying a new address does not change the current recipient. Choosing a verified entry replaces it and turns email preferences off. Turning email off detaches its recipient from preferences, while verified entries stay saved.</p>
        </div>
        {preferences ? (
          <div className={styles.emailWorkflow} aria-busy={emailLoading || emailBusy}>
            <div className={emailError ? styles.emailError : styles.emailStatus} role={emailError ? "alert" : "status"} aria-live={emailError ? "assertive" : "polite"}>
              {emailLoading ? "Loading notification email settings…" : emailError || (emailAvailable ? "Email verification and alert delivery are available." : "Email delivery is currently unavailable. Existing settings remain visible; new opt-in is disabled.")}
            </div>
            {emailStatus ? <p className={styles.emailSuccess} role="status" aria-live="polite">{emailStatus}</p> : null}
            {emailFormError ? <p className={styles.emailError} role="alert">{emailFormError}</p> : null}
            <div className={styles.emailSubsection}>
              <h4>Verify an address</h4>
              {verification && !verification.invalidated ? <p className={styles.emailNote}>{verificationMessage(verification)} Expires {displayInstant(verification.expires_at)}. Attempts used: {verification.attempts}.</p> : <p className={styles.emailNote}>No active verification request is shown. A message is sent only after you submit this form.</p>}
              <form className={styles.emailForm} data-email-action="verify" onSubmit={requestVerification}>
                <label className={styles.emailField} htmlFor={`${formId}-email-address`}>Email address
                  <input id={`${formId}-email-address`} name="notification-email-address" type="email" autoComplete="email" maxLength={320} value={emailAddressDraft} onChange={event => setEmailAddressDraft(event.target.value)} disabled={isReadOnly || emailLoading || emailBusy || !emailAvailable} />
                </label>
                <button className={styles.secondaryButton} type="submit" disabled={isReadOnly || emailLoading || emailBusy || Boolean(emailError) || !emailAvailable || !onRequestEmailVerification || verification?.state === "submitting"}>
                  {emailBusy ? "Sending…" : replaceableVerification ? "Send replacement code" : "Send verification code"}
                </button>
              </form>
              {verification && !verification.invalidated && ["accepted", "uncertain"].includes(verification.state) ? (
                <form className={styles.emailForm} data-email-action="confirm" onSubmit={confirmVerification}>
                  <label className={styles.emailField} htmlFor={`${formId}-verification-code`}>One-time verification code
                    <input id={`${formId}-verification-code`} name="notification-verification-code" type="text" inputMode="text" autoComplete="one-time-code" maxLength={43} value={verificationCode} onChange={event => setVerificationCode(event.target.value)} disabled={isReadOnly || emailBusy} />
                  </label>
                  <button className={styles.primaryButton} type="submit" disabled={isReadOnly || emailLoading || emailBusy || Boolean(emailError) || !onConfirmEmailVerification}>Confirm address</button>
                </form>
              ) : null}
            </div>
            <div className={styles.emailSubsection}>
              <div className={styles.emailHeadingRow}><h4>Verified recipients</h4><span>{verifiedAddresses === null ? "Unavailable" : `${verifiedAddresses.length} saved`}</span></div>
              {preferences.address_configured ? <p className={styles.emailNote}>{verifiedAddressDraft ? "The recipient selected during this visit is marked below." : "A verified recipient is configured. Its identity is hidden; choose a row below to replace it."}</p> : <p className={styles.emailNote}>No recipient is selected. Select a verified address before opting in.</p>}
              <p className={styles.emailNote}>For privacy, saved email addresses are not displayed. Choose an entry by its verification date.</p>
              {verifiedAddresses === null ? <p className={styles.unavailableNote}>Saved verified addresses could not be loaded. Refresh notification email settings before changing recipients.</p> : verifiedAddresses.length ? (
                <ul className={styles.addressList}>{verifiedAddresses.map((address, index) => <li className={styles.addressRow} key={address.id}>
                  <span>Verified recipient {index + 1} · {displayInstant(address.verified_at)}{verifiedAddressDraft === address.id ? " · selected this visit" : ""}</span>
                  <button className={styles.secondaryButton} type="button" disabled={isReadOnly || emailLoading || emailBusy || !onSelectEmailAddress} onClick={() => void selectVerifiedAddress(address.id)}>
                    {verifiedAddressDraft === address.id ? "Selected" : "Use this address"}
                  </button>
                </li>)}</ul>
              ) : <p className={styles.emptyState}>No verified recipients are saved yet.</p>}
            </div>
            <form className={styles.emailSubsection} data-email-action="save-preference" onSubmit={saveAlertEmail}>
              <h4>Alert email preference</h4>
              <dl className={styles.preferenceFacts}>
                <div><dt>Saved choice</dt><dd>{preferences.alert_email ? "Opted in" : "Opted out"}</dd></div>
                <div><dt>Recipient status</dt><dd>{preferences.address_configured ? "Configured" : "Not selected"}</dd></div>
                <div><dt>Daily digest</dt><dd>{preferences.digest_email ? `Unavailable · currently on (${preferences.digest_time} ${preferences.digest_timezone})` : "Unavailable · off"}</dd></div>
                <div><dt>Settings updated</dt><dd>{displayInstant(preferences.updated_at)}</dd></div>
              </dl>
              <label className={styles.emailChoice}>
                <input type="checkbox" name="alert-email-opt-in" checked={selectedAlertEmail} onChange={event => setAlertEmailDraft({ revision: preferences.revision, enabled: event.target.checked })} disabled={isReadOnly || emailLoading || emailBusy || (!emailAvailable && !selectedAlertEmail)} />
                <span>Send me email when a saved price alert triggers</span>
              </label>
              {preferences.digest_email ? <label className={styles.emailChoice}><input type="checkbox" name="acknowledge-digest-off" checked={acknowledgeDigestOff} onChange={event => setAcknowledgeDigestOff(event.target.checked)} disabled={isReadOnly || emailBusy} /><span>I understand that saving will turn off the unavailable daily digest.</span></label> : <p className={styles.emailNote}>Daily digest email is not available. It stays off.</p>}
              <p className={styles.emailNote}>Changing this preference never enables alert rules or sends a test message. You can turn alert email off even while delivery is unavailable.</p>
              <button className={styles.primaryButton} type="submit" disabled={isReadOnly || emailLoading || emailBusy || !onSaveAlertEmail || (selectedAlertEmail && (!emailAvailable || !preferences.address_configured)) || (preferences.digest_email && !acknowledgeDigestOff)}>{emailBusy ? "Saving…" : "Save email preference"}</button>
            </form>
            <button className={styles.secondaryButton} type="button" disabled={emailLoading || emailBusy || !onRefreshEmailSettings} onClick={() => { void onRefreshEmailSettings?.(); }}>Refresh email settings</button>
          </div>
        ) : (
          <div className={styles.emailWorkflow}>
            <p className={styles.unavailableNote}>{emailLoading ? "Loading notification email settings…" : emailError || "Preference status is unavailable. Email changes are disabled until saved settings can be loaded."}</p>
            <button className={styles.secondaryButton} type="button" disabled={emailLoading || emailBusy || !onRefreshEmailSettings} onClick={() => { void onRefreshEmailSettings?.(); }}>Refresh email settings</button>
          </div>
        )}
      </section>
    </section>
  );
}

function verificationMessage(value: NotificationVerification): string {
  if (value.invalidated) return "This request was replaced or is no longer active.";
  if (value.state === "verified" || value.state === "already_verified") return "Address verified. Select it below if you want it to receive alert email.";
  if (value.state === "accepted") return "The email service accepted the message; delivery is not confirmed.";
  if (value.state === "uncertain") return "The delivery result is uncertain. Check your mailbox before requesting another code.";
  if (value.state === "queued" || value.state === "submitting") return "The verification request is being processed.";
  if (value.state === "expired") return "This code expired. Submit the address form to request a replacement.";
  return "This verification request did not complete. You can explicitly request a replacement code.";
}
