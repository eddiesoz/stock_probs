"use client";

// A session-bound server challenge drives each enrollment or verification ceremony.

import { useEffect, useState } from "react";

import { authErrorMessage, getAuthSession, runPasskeyCeremony, safeLocalNext, type AuthSession } from "../../components/auth-client";
import { AuthShell } from "../../components/auth-shell";
import styles from "../auth.module.css";

type PasskeyMode = "enroll" | "verify";

export default function PasskeyPage() {
  const [session, setSession] = useState<AuthSession | null | undefined>(undefined);
  const [mode, setMode] = useState<PasskeyMode>("enroll");
  const [nextPath, setNextPath] = useState("/overview");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ tone: "error" | "success"; text: string } | null>(null);

  useEffect(() => {
    const query = new URLSearchParams(window.location.search);
    setMode(query.get("mode") === "verify" ? "verify" : "enroll");
    setNextPath(safeLocalNext(query.get("next")));
    let active = true;
    getAuthSession().then((value) => { if (active) setSession(value); }).catch((error) => { if (active) setMessage({ tone: "error", text: authErrorMessage(error) }); });
    return () => { active = false; };
  }, []);

  async function runCeremony() {
    setBusy(true);
    setMessage(null);
    try {
      const paths = mode === "enroll"
        ? ["/api/v1/auth/passkeys/register/options", "/api/v1/auth/passkeys/register"]
        : ["/api/v1/auth/passkeys/authenticate/options", "/api/v1/auth/passkeys/authenticate"];
      await runPasskeyCeremony(paths[0], paths[1], mode === "enroll" ? "create" : "get");
      setMessage({ tone: "success", text: mode === "enroll" ? "Passkey enrolled. Your account is ready." : "Fresh passkey verification complete." });
      window.setTimeout(() => window.location.assign(nextPath), 350);
    } catch (error) {
      setMessage({ tone: "error", text: authErrorMessage(error) });
    } finally {
      setBusy(false);
    }
  }

  const title = mode === "enroll" ? "Create your passkey" : "Verify your passkey";
  const description = mode === "enroll"
    ? "Passkeys keep the account boundary tied to your device. There is no shared secret to copy, export, or store in the browser."
    : "This sensitive action needs a fresh proof of account control. Your passkey response is checked by the local service and never stored in page state.";

  return (
    <AuthShell eyebrow="Account security" title={title} description={description}>
      <section className={styles.authPanel} aria-labelledby="passkey-heading">
        <h2 id="passkey-heading">{mode === "enroll" ? "Protect this account" : "Confirm it’s you"}</h2>
        <p className={styles.panelLead}>{session?.user ? `Signed in as ${session.user.name || session.user.login || "your account"}.` : "Checking your session…"}</p>
        {session === undefined ? <p className={styles.loadingState} role="status">Checking account security…</p> : null}
        {session === null ? <div className={styles.deniedState}><h2>Sign in first</h2><p>A passkey ceremony can only be attached to an active invitation or account session.</p><div className={styles.authLinks}><a href="/sign-in">Open sign in</a></div></div> : null}
        {session?.authenticated ? <>
          <div className={styles.permissionBox}><div><strong>{mode === "enroll" ? "One device, one strong key" : "Fresh verification"}</strong><p>{mode === "enroll" ? "Use your device unlock, security key, or platform authenticator. You can add another passkey later from Account." : "Your browser will return to the workspace after the check succeeds."}</p></div></div>
          <button className="primary" type="button" onClick={runCeremony} disabled={busy}>{busy ? "Waiting for passkey…" : mode === "enroll" ? "Create passkey" : "Verify with passkey"}</button>
          {message ? <p className={styles.authMessage} data-tone={message.tone} role={message.tone === "error" ? "alert" : "status"}>{message.text}</p> : null}
          <div className={styles.authLinks}><a href="/account">Manage account</a><a href={nextPath}>Return to workspace</a></div>
        </> : null}
      </section>
    </AuthShell>
  );
}
