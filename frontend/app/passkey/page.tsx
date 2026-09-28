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
    getAuthSession().then((value) => { if (active) setSession(value); }).catch((error) => {
      if (active) {
        setSession(null);
        setMessage({ tone: "error", text: authErrorMessage(error) });
      }
    });
    return () => { active = false; };
  }, []);

  async function runCeremony() {
    setBusy(true);
    setMessage(null);
    try {
      await runPasskeyCeremony("/api/v1/auth/passkeys/authenticate/options", "/api/v1/auth/passkeys/authenticate", "get");
      setMessage({ tone: "success", text: "Legacy passkey verification complete. Continue with authenticator setup." });
      window.setTimeout(() => window.location.assign(nextPath), 350);
    } catch (error) {
      setMessage({ tone: "error", text: authErrorMessage(error) });
    } finally {
      setBusy(false);
    }
  }

  const title = "Verify your legacy passkey";
  const description = "This one-time transition is for accounts that already have a passkey. New accounts use an authenticator app so you can sign in from any trusted device.";

  return (
    <AuthShell eyebrow="Account security" title={title} description={description}>
      <section className={styles.authPanel} aria-labelledby="passkey-heading">
        <h2 id="passkey-heading">{mode === "enroll" ? "Protect this account" : "Confirm it’s you"}</h2>
        <p className={styles.panelLead}>{session?.authenticated && session.user ? `Signed in as ${session.user.name || session.user.login || "your account"}.` : session === undefined ? "Checking your session…" : "Sign in again to continue the legacy transition."}</p>
        {session === undefined ? <p className={styles.loadingState} role="status">Checking account security…</p> : null}
        {session !== undefined && (!session?.authenticated || !session.user) ? <div className={styles.deniedState}><h2>Sign in first</h2><p>Your session may have ended. Sign in again, then continue the authenticator setup.</p><div className={styles.authLinks}><a href="/sign-in">Open sign in</a></div></div> : null}
        {session?.authenticated && session.user ? <>
          <div className={styles.permissionBox}><div><strong>One-time legacy check</strong><p>Verify the existing passkey, then the browser will take you to authenticator enrollment. Signal Ledger does not create or export new passkeys.</p></div></div>
          <button className="primary" type="button" onClick={runCeremony} disabled={busy}>{busy ? "Waiting for passkey…" : "Verify legacy passkey"}</button>
          <div className={styles.authLinks}><a href="/account">Manage account</a><a href={nextPath}>Return to workspace</a></div>
        </> : null}
        {message ? <p className={styles.authMessage} data-tone={message.tone} role={message.tone === "error" ? "alert" : "status"}>{message.text}</p> : null}
      </section>
    </AuthShell>
  );
}
