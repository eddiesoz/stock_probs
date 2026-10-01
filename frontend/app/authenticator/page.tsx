"use client";

// Authenticator codes are verified by the server; this page never persists a secret or code.

import { FormEvent, useEffect, useMemo, useState } from "react";
import QRCode from "qrcode";

import {
  AuthRequestError,
  authErrorMessage,
  authRequest,
  getAuthSession,
  safeLocalNext,
  type AuthenticatorMode,
  type AuthSession,
  type TotpEnrollment,
  type TotpStatus,
} from "../../components/auth-client";
import { AuthShell } from "../../components/auth-shell";
import styles from "../auth.module.css";

interface TotpResponse {
  authenticated?: boolean;
  csrf_token?: string;
  recovery_codes?: string[];
  restricted?: boolean;
  verified?: boolean;
  verified_at?: string;
}

const CODE_LENGTH = 6;
type SetupApp = "" | "apple-passwords" | "google-authenticator" | "1password" | "other";

function enrollmentExpiryMs(enrollment: TotpEnrollment | null): number {
  return enrollment ? Date.parse(enrollment.expires_at) : Number.NaN;
}

function formatEnrollmentExpiry(value: string): string {
  const timestamp = Date.parse(value);
  if (!Number.isFinite(timestamp)) return "an unknown time";
  return new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(new Date(timestamp));
}

function formatEnrollmentCountdown(expiresAt: string, nowMs: number): string {
  const timestamp = Date.parse(expiresAt);
  if (!Number.isFinite(timestamp) || nowMs <= 0) return "checking…";
  const seconds = Math.max(0, Math.ceil((timestamp - nowMs) / 1000));
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
}

function enrollmentErrorMessage(error: unknown, phase: "start" | "finish"): string {
  if (error instanceof AuthRequestError) {
    if (error.code === "totp_rejected") {
      return phase === "start"
        ? "A pending setup already exists in another session. Continue with that session, or choose Start over with new key to replace it."
        : "That authenticator code was not accepted. A previously scanned QR code may be stale; choose Start over with new key to replace it, then try the current code.";
    }
    if (error.code === "totp_rate_limited" || error.code === "totp_required" || [401, 403, 409].includes(error.status)) {
      return authErrorMessage(error);
    }
  }
  return phase === "start"
    ? "A setup key could not be created. Try again."
    : "That setup code could not be confirmed. Use the current code or start over with a new key.";
}

function setupInstructions(app: SetupApp) {
  switch (app) {
    case "apple-passwords":
      return "Open Passwords and select the Signal Ledger login (create it first if needed). Tap Edit, then Set Up Code, enter this setup key, and tap Use Setup Key.";
    case "google-authenticator":
      return "Open Google Authenticator, tap +, then Enter a setup key. Name it Signal Ledger, paste the key, choose Time based if asked, and add it.";
    case "1password":
      return "Open and unlock 1Password. Open or create the Signal Ledger Login item, tap Edit, then Add More > One-Time Password. On this iPhone, paste the copied setup key into the field; from another screen, you can scan this page’s QR code instead. Save the item.";
    case "other":
      return "In your chosen app, add an account using Enter setup key or manual entry. Name it Signal Ledger, paste this key, and choose time-based (TOTP) if asked.";
    default:
      return "Choose your authenticator to see its setup steps. The manual key is available above for apps that support entering a setup key.";
  }
}

function modeFromQuery(value: string | null): AuthenticatorMode {
  if (value === "enroll" || value === "recover" || value === "step-up") return value;
  return "verify";
}

function modeCopy(mode: AuthenticatorMode, hasRecoveryCodes: boolean) {
  if (hasRecoveryCodes) {
    return {
      eyebrow: "Account recovery",
      title: "Save your recovery codes",
      description: "These one-time codes are the fallback for a lost authenticator. Store them in a private password manager before returning to the ledger.",
    };
  }
  if (mode === "enroll") {
    return {
      eyebrow: "Authenticator setup",
      title: "Protect your account",
      description: "Use an authenticator app on each device you trust. Your setup key appears only during enrollment and is never saved in browser storage.",
    };
  }
  if (mode === "recover") {
    return {
      eyebrow: "Account recovery",
      title: "Use a recovery code",
      description: "A recovery code can restore access long enough to replace a lost authenticator. Each code works once and then expires permanently.",
    };
  }
  if (mode === "step-up") {
    return {
      eyebrow: "Fresh account proof",
      title: "Confirm it’s you",
      description: "This sensitive action needs a fresh authenticator code. Your code is checked by the local service and never stored in page state.",
    };
  }
  return {
    eyebrow: "Secure access",
    title: "Enter your authenticator code",
    description: "Open your authenticator app and enter the current six-digit code to continue to your private workspace.",
  };
}

export default function AuthenticatorPage() {
  const [session, setSession] = useState<AuthSession | null | undefined>(undefined);
  const [status, setStatus] = useState<TotpStatus | null | undefined>(undefined);
  const [mode, setMode] = useState<AuthenticatorMode>("verify");
  const [nextPath, setNextPath] = useState("/overview");
  const [enrollment, setEnrollment] = useState<TotpEnrollment | null>(null);
  const [qrCodeUrl, setQrCodeUrl] = useState<string | null>(null);
  const [qrUnavailable, setQrUnavailable] = useState(false);
  const [code, setCode] = useState("");
  const [recoveryCodes, setRecoveryCodes] = useState<string[] | null>(null);
  const [copied, setCopied] = useState(false);
  const [setupKeyCopied, setSetupKeyCopied] = useState(false);
  const [setupApp, setSetupApp] = useState<SetupApp>("");
  const [busy, setBusy] = useState<string | null>(null);
  const [enrollmentClock, setEnrollmentClock] = useState(0);
  const [rotatedEnrollment, setRotatedEnrollment] = useState(false);
  const [pendingSetupConflict, setPendingSetupConflict] = useState(false);
  const [message, setMessage] = useState<{ tone: "error" | "success"; text: string } | null>(null);

  useEffect(() => {
    const query = new URLSearchParams(window.location.search);
    setMode(modeFromQuery(query.get("mode")));
    setNextPath(safeLocalNext(query.get("next")));
    let active = true;
    getAuthSession()
      .then(async (value) => {
        if (!active) return;
        setSession(value);
        if (!value?.authenticated) {
          setStatus(null);
          return;
        }
        try {
          const factorStatus = await authRequest<TotpStatus>("/api/v1/auth/totp/status", {
            cache: "no-store",
          });
          if (active) setStatus(factorStatus);
        } catch (error) {
          if (active) {
            setStatus(null);
            setMessage({ tone: "error", text: authErrorMessage(error) });
          }
        }
      })
      .catch((error) => {
        if (active) {
          setSession(null);
          setStatus(null);
          setMessage({ tone: "error", text: authErrorMessage(error) });
        }
      });
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    if (!enrollment) {
      setEnrollmentClock(0);
      return;
    }
    let active = true;
    const updateClock = () => {
      if (active) setEnrollmentClock(Date.now());
    };
    updateClock();
    const interval = window.setInterval(updateClock, 1000);
    return () => {
      active = false;
      window.clearInterval(interval);
    };
  }, [enrollment]);

  const enrollmentExpiresAtMs = enrollmentExpiryMs(enrollment);
  const enrollmentExpired = Boolean(
    enrollment && (!Number.isFinite(enrollmentExpiresAtMs) || (enrollmentClock > 0 && enrollmentClock >= enrollmentExpiresAtMs)),
  );

  useEffect(() => {
    if (!enrollmentExpired) return;
    setQrCodeUrl(null);
    setCode("");
    setSetupKeyCopied(false);
  }, [enrollmentExpired]);

  useEffect(() => {
    setQrCodeUrl(null);
    setQrUnavailable(false);
    if (!enrollment) return;
    const expiresAtMs = enrollmentExpiryMs(enrollment);
    if (!Number.isFinite(expiresAtMs) || Date.now() >= expiresAtMs) {
      setQrUnavailable(true);
      return;
    }
    if (!enrollment.otpauth_uri.startsWith("otpauth://totp/")) {
      setQrUnavailable(true);
      return;
    }
    let active = true;
    // Render locally: the one-time setup URI must never be sent to a QR service.
    QRCode.toDataURL(enrollment.otpauth_uri, {
      errorCorrectionLevel: "M",
      margin: 4,
      width: 240,
      color: { dark: "#111827", light: "#FFFFFFFF" },
    }).then((url) => {
      if (active) setQrCodeUrl(url);
    }).catch(() => {
      if (active) setQrUnavailable(true);
    });
    return () => { active = false; };
  }, [enrollment]);

  const copy = modeCopy(mode, Boolean(recoveryCodes));
  const isEnrolled = Boolean(status?.enrolled || session?.user?.totp_enrolled);
  const codeReady = code.trim().length === CODE_LENGTH;
  const shouldShowCodeForm = mode !== "enroll" || Boolean(enrollment && !enrollmentExpired);
  const enrollmentPath = `/authenticator?mode=enroll&next=${encodeURIComponent(nextPath)}`;
  const freshEnrollmentPath = `/authenticator?mode=step-up&next=${encodeURIComponent(enrollmentPath)}`;

  const recoveryText = useMemo(() => recoveryCodes?.join("\n") ?? "", [recoveryCodes]);

  async function startEnrollment(replace = false) {
    if (busy !== null) return;
    const preserveConflictOnFailure = replace && pendingSetupConflict;
    // Remove the previous QR/key before rotating so an in-flight request cannot leave stale setup data actionable.
    setEnrollment(null);
    setQrCodeUrl(null);
    setQrUnavailable(false);
    setCode("");
    setSetupApp("");
    setSetupKeyCopied(false);
    setRotatedEnrollment(false);
    setBusy(replace ? "replace" : "start");
    setMessage(null);
    setCopied(false);
    try {
      const response = await authRequest<TotpEnrollment>("/api/v1/auth/totp/enroll/start", {
        method: "POST",
        body: replace ? JSON.stringify({ replace: true }) : "{}",
      });
      setEnrollment(response);
      setRotatedEnrollment(replace);
      setPendingSetupConflict(false);
      setMessage({
        tone: "success",
        text: replace
          ? "New setup key created. Replace the old authenticator entry before entering a code."
          : "Setup key created. Add it to your authenticator, then enter the current code below.",
      });
    } catch (error) {
      const isPendingSetupConflict = error instanceof AuthRequestError && error.code === "totp_rejected";
      setPendingSetupConflict(preserveConflictOnFailure || (!replace && isPendingSetupConflict));
      setMessage({ tone: "error", text: enrollmentErrorMessage(error, "start") });
    } finally {
      setBusy(null);
    }
  }

  async function copySetupKey() {
    if (enrollmentExpired) {
      setMessage({ tone: "error", text: "This setup key has expired. Start over with a new key before copying it." });
      return;
    }
    if (!enrollment?.secret || !navigator.clipboard) {
      setMessage({ tone: "error", text: "Copy is unavailable here. Select the setup key above and choose Copy." });
      return;
    }
    try {
      await navigator.clipboard.writeText(enrollment.secret);
      setSetupKeyCopied(true);
      setMessage({ tone: "success", text: "Setup key copied. Paste it only into your chosen authenticator app." });
    } catch {
      setSetupKeyCopied(false);
      setMessage({ tone: "error", text: "Copy was blocked. Select the setup key above and choose Copy." });
    }
  }

  async function copyRecoveryCodes() {
    if (!recoveryText || !navigator.clipboard) {
      setMessage({ tone: "error", text: "Copy is unavailable here. Select the codes and save them in a private place." });
      return;
    }
    try {
      await navigator.clipboard.writeText(recoveryText);
      setCopied(true);
      setMessage({ tone: "success", text: "Recovery codes copied. Keep them private; each code works once." });
    } catch {
      setMessage({ tone: "error", text: "Copy was blocked. Select the codes and save them in a private place." });
    }
  }

  async function finishOrVerify(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (mode === "recover" ? !code.trim() : !codeReady) return;
    if (mode === "enroll" && enrollmentExpired) {
      setCode("");
      setMessage({ tone: "error", text: "This setup key has expired. Start over with a new key before entering a code." });
      return;
    }
    setBusy("code");
    setMessage(null);
    try {
      const path = mode === "enroll"
        ? "/api/v1/auth/totp/enroll/finish"
        : mode === "recover"
          ? "/api/v1/auth/totp/recover"
          : mode === "step-up"
            ? "/api/v1/auth/totp/step-up"
            : "/api/v1/auth/totp/verify";
      const response = await authRequest<TotpResponse>(path, {
        method: "POST",
        body: JSON.stringify({ code: code.trim() }),
      });
      setCode("");
      if (mode === "enroll" && response.recovery_codes?.length) {
        setEnrollment(null);
        setRecoveryCodes(response.recovery_codes);
        setStatus((current) => current ? { ...current, enrolled: true, enrollment_pending: false } : current);
        setMessage({ tone: "success", text: "Authenticator enabled. Save these recovery codes before continuing." });
      } else if (mode === "recover") {
        setMessage({ tone: "success", text: "Recovery accepted. Replace the lost authenticator now." });
        window.setTimeout(() => window.location.assign(enrollmentPath), 350);
      } else if (mode === "step-up") {
        setMessage({ tone: "success", text: "Fresh authenticator verification complete." });
        window.setTimeout(() => window.location.assign(nextPath), 350);
      } else {
        setMessage({ tone: "success", text: "Authenticator verification complete." });
        window.setTimeout(() => window.location.assign(nextPath), 350);
      }
    } catch (error) {
      setMessage({ tone: "error", text: mode === "enroll" ? enrollmentErrorMessage(error, "finish") : authErrorMessage(error) });
    } finally {
      setBusy(null);
    }
  }

  function continueAfterRecoveryCodes() {
    if (!recoveryCodes) return;
    window.location.assign(nextPath);
  }

  if (session === undefined || status === undefined) {
    return (
      <AuthShell eyebrow="Account security" title="Checking your authenticator" description="Loading the server-confirmed account security state.">
        <section className={styles.authPanel} aria-labelledby="authenticator-loading-heading">
          <h2 id="authenticator-loading-heading">Loading security state</h2>
          <p className={styles.loadingState} role="status">Checking your session and authenticator…</p>
        </section>
      </AuthShell>
    );
  }

  if (!session?.authenticated || !session.user) {
    return (
      <AuthShell eyebrow="Account security" title="Sign in first" description="Your authenticator is connected to your invited account. Sign in before continuing.">
        <section className={styles.authPanel} aria-labelledby="authenticator-denied-heading">
          <h2 id="authenticator-denied-heading">Authentication required</h2>
          <p className={styles.panelLead}>The session may have expired or been revoked.</p>
          <div className={styles.deniedState}><p>Return to sign in, then follow the authenticator setup or verification step.</p><div className={styles.authLinks}><a href={`/sign-in?next=${encodeURIComponent(nextPath)}`}>Open sign in</a></div></div>
        </section>
      </AuthShell>
    );
  }

  return (
    <AuthShell eyebrow={copy.eyebrow} title={copy.title} description={copy.description}>
      <section className={`${styles.authPanel} ${styles.factorPanel}`} aria-labelledby="authenticator-heading">
        <div className={styles.panelHeaderRow}>
          <div>
            <p className="panel-kicker">{mode === "step-up" ? "Administrator check" : "Authenticator app"}</p>
            <h2 id="authenticator-heading">{copy.title}</h2>
          </div>
          <span className={`${styles.factorBadge} ${isEnrolled ? styles.factorBadgeGood : ""}`}>{isEnrolled ? "Enabled" : "Setup needed"}</span>
        </div>
        <p className={styles.panelLead}>Signed in as {session.user.name || session.user.login || "your account"}.</p>

        {mode === "enroll" && !enrollment && !recoveryCodes ? <div className={styles.factorIntro}>
          <div className={styles.stepCard}><span className={styles.stepNumber}>1</span><div><strong>Add Signal Ledger to your app</strong><p>Generate a setup key, then add it to 1Password, Authenticator, Aegis, or another trusted authenticator.</p></div></div>
          <div className={styles.stepCard}><span className={styles.stepNumber}>2</span><div><strong>Confirm one current code</strong><p>The setup window expires in ten minutes. A code from the app proves the key was entered correctly.</p></div></div>
          {pendingSetupConflict ? <div className={styles.deniedState} role="alert" aria-labelledby="totp-pending-setup-heading" aria-describedby="totp-pending-setup-warning">
            <strong id="totp-pending-setup-heading">A pending setup is active in another session</strong>
            <p id="totp-pending-setup-warning">Continue with that session if possible. Starting over invalidates the other session’s pending QR and setup key.</p>
            <button className="secondary full" type="button" onClick={() => startEnrollment(true)} disabled={busy !== null || status?.can_enroll === false}>{busy === "replace" ? "Starting over…" : "Start over with new key"}</button>
          </div> : <button className="primary full" type="button" onClick={() => startEnrollment()} disabled={busy !== null || status?.can_enroll === false}>{busy === "replace" ? "Starting over…" : busy === "start" ? "Creating setup key…" : "Generate setup key"}</button>}
          {status?.can_enroll === false ? <p className={styles.securityNote}>Complete a fresh check before replacing an existing authenticator. <a href={freshEnrollmentPath}>Verify current authenticator</a></p> : null}
        </div> : null}

        {mode === "enroll" && enrollment && !recoveryCodes ? <div className={styles.enrollmentBox}>
          <div className={styles.stepLabel}><span className={styles.stepNumber}>1</span><span>Add Signal Ledger to your authenticator</span></div>
          <p
            className={styles.securityNote}
            data-testid="totp-enrollment-expiry"
            data-state={enrollmentExpired ? "expired" : "active"}
            role={enrollmentExpired ? "alert" : "timer"}
            aria-live={enrollmentExpired ? "assertive" : "off"}
            aria-atomic="true"
          >
            {enrollmentExpired
              ? <>This setup key expired at <time dateTime={enrollment.expires_at}>{formatEnrollmentExpiry(enrollment.expires_at)}</time>. It cannot be scanned or used.</>
              : <>Setup key expires in <strong>{formatEnrollmentCountdown(enrollment.expires_at, enrollmentClock)}</strong> at <time dateTime={enrollment.expires_at}>{formatEnrollmentExpiry(enrollment.expires_at)}</time>.</>}
          </p>
          {enrollmentExpired ? <div className={styles.deniedState}>
            <strong>Start a fresh setup</strong>
            <p>The QR code and code entry are disabled until you create a new setup key.</p>
            <button className="secondary" type="button" onClick={() => startEnrollment(true)} disabled={busy !== null || status?.can_enroll === false}>{busy === "replace" ? "Starting over…" : "Start over with new key"}</button>
          </div> : <>
            <label className={styles.setupChoice} htmlFor="totp-app-choice">
              Which authenticator do you want to use?
              <select id="totp-app-choice" value={setupApp} onChange={(event) => setSetupApp(event.target.value as SetupApp)} aria-describedby="totp-app-guidance" autoFocus>
                <option value="">Choose an app</option>
                <option value="apple-passwords">Apple Passwords</option>
                <option value="google-authenticator">Google Authenticator</option>
                <option value="1password">1Password</option>
                <option value="other">Other authenticator app</option>
              </select>
            </label>
            <p className={styles.appGuidance} id="totp-app-guidance" aria-live="polite">{setupInstructions(setupApp)}</p>
            <div className={styles.secretCard}>
              <span className={styles.secretLabel}>Manual setup key</span>
              <code className={styles.setupKey} data-testid="totp-setup-key">{enrollment.secret}</code>
              <p>On this iPhone, copy this key and add it inside the app you chose above. iOS chooses which app opens an otpauth link and may open Apple Passwords instead.</p>
              <button className="secondary" type="button" onClick={copySetupKey}>{setupKeyCopied ? "Copied setup key" : "Copy setup key"}</button>
            </div>
            <div className={styles.qrCard}>
              <span className={styles.secretLabel}>QR setup with another device</span>
              {qrCodeUrl ? <img className={styles.qrImage} src={qrCodeUrl} width="240" height="240" alt="QR code for adding Signal Ledger to an authenticator app" /> : <div className={styles.qrPlaceholder} role="status">{qrUnavailable ? "QR code unavailable. Use the manual key above." : "Creating QR code…"}</div>}
              <p>Display this QR code on one device, then scan it from your chosen authenticator on the other.</p>
            </div>
            <div className={styles.handlerAction}>
              <p>Trying this link asks your device’s default otpauth handler to open. The app choice above cannot change iOS routing.</p>
              <a className="secondary" href={enrollment.otpauth_uri}>Try device’s default otpauth handler</a>
            </div>
            {rotatedEnrollment ? <p className={styles.securityNote} id="totp-rotation-warning">This new key replaces the pending setup. Replace the old Signal Ledger entry in your authenticator before entering a code.</p> : null}
            <form className={styles.codeForm} onSubmit={finishOrVerify} noValidate>
              <div className={styles.stepLabel}><span className={styles.stepNumber}>2</span><label htmlFor="totp-code">Enter the current six-digit code</label></div>
              <input className={styles.codeInput} id="totp-code" name="code" type="text" inputMode="numeric" autoComplete="one-time-code" pattern="[0-9]{6}" maxLength={CODE_LENGTH} value={code} onChange={(event) => setCode(event.target.value.replace(/\D/g, "").slice(0, CODE_LENGTH))} aria-describedby="totp-code-help" required />
              <p id="totp-code-help" className={styles.fieldHelp}>Use the newest code. Codes are valid briefly and cannot be reused for the same time window.</p>
              <button className="primary full" type="submit" disabled={busy === "code" || !codeReady}>{busy === "code" ? "Confirming authenticator…" : "Enable authenticator"}</button>
            </form>
            <button className="secondary full" type="button" onClick={() => startEnrollment(true)} disabled={busy !== null || status?.can_enroll === false}>{busy === "replace" ? "Starting over…" : "Start over with new key"}</button>
          </>}
        </div> : null}

        {recoveryCodes ? <div className={styles.recoveryBox}>
          <div className={styles.recoveryNotice}><strong>Save these codes now</strong><p>They are shown once. Anyone with a code can recover this account, so store them in a private password manager.</p></div>
          <div className={styles.recoveryGrid} aria-label="One-time recovery codes">{recoveryCodes.map((item) => <code key={item}>{item}</code>)}</div>
          <div className={styles.recoveryActions}><button className="secondary" type="button" onClick={copyRecoveryCodes}>{copied ? "Copied" : "Copy codes"}</button><button className="primary" type="button" onClick={continueAfterRecoveryCodes}>I saved the codes</button></div>
        </div> : null}

        {shouldShowCodeForm && !enrollment && !recoveryCodes ? <form className={styles.codeForm} onSubmit={finishOrVerify} noValidate>
          <label htmlFor="totp-code">{mode === "recover" ? "Recovery code" : "Current authenticator code"}
            <input className={styles.codeInput} id="totp-code" name="code" type="text" inputMode={mode === "recover" ? "text" : "numeric"} autoComplete="one-time-code" pattern={mode === "recover" ? undefined : "[0-9]{6}"} maxLength={39} value={code} onChange={(event) => setCode(event.target.value.trimStart())} aria-describedby="totp-code-help" autoFocus required />
          </label>
          <p id="totp-code-help" className={styles.fieldHelp}>{mode === "step-up" ? "If the code just changed, wait for the next code before retrying. A code is accepted once per time window." : mode === "recover" ? "Use one of the single-use codes you saved during setup." : "Use the newest six-digit code. A code is accepted once per time window."}</p>
          <button className="primary full" type="submit" disabled={busy === "code" || (mode !== "recover" && !codeReady) || (mode === "recover" && !code.trim())}>{busy === "code" ? "Checking code…" : mode === "recover" ? "Recover account" : mode === "step-up" ? "Verify authenticator" : "Continue"}</button>
        </form> : null}

        {mode === "verify" && !isEnrolled ? <div className={styles.deniedState}><p>No active authenticator is enrolled yet. Set one up before trying to verify a code.</p><div className={styles.authLinks}><a href={enrollmentPath}>Set up authenticator</a></div></div> : null}
        {mode === "verify" || mode === "step-up" ? <div className={styles.factorLinks}><a href={`/authenticator?mode=recover&next=${encodeURIComponent(nextPath)}`}>Use a recovery code</a>{mode === "verify" ? <a href={freshEnrollmentPath}>Replace authenticator</a> : null}</div> : null}
        {message ? <p className={styles.authMessage} data-tone={message.tone} role={message.tone === "error" ? "alert" : "status"}>{message.text}</p> : null}
        <div className={styles.authLinks}><a href={nextPath}>Return to workspace</a><a href="/account">Manage account</a></div>
      </section>
    </AuthShell>
  );
}
