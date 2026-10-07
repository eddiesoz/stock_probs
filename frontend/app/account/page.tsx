"use client";

// Account state is always loaded from the authenticated API, never browser storage.

import { useEffect, useState } from "react";

import { authErrorMessage, authRequest, formatAuthDate, getAuthSession, type AuthSession, type SessionRecord, type TotpStatus } from "../../components/auth-client";
import { WorkspaceNav } from "../../components/workspace-nav";
import styles from "../auth.module.css";

export default function AccountPage() {
  const [session, setSession] = useState<AuthSession | null | undefined>(undefined);
  const [sessions, setSessions] = useState<SessionRecord[]>([]);
  const [totpStatus, setTotpStatus] = useState<TotpStatus | null>(null);
  const [message, setMessage] = useState<{ tone: "error" | "success"; text: string } | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  useEffect(() => { document.title = "Account | Signal Ledger"; }, []);

  async function load() {
    const [auth, sessionList, factorStatus] = await Promise.all([
      getAuthSession(),
      authRequest<{ sessions?: SessionRecord[] }>("/api/v1/auth/sessions", { cache: "no-store" }).catch(() => ({ sessions: [] })),
      authRequest<TotpStatus>("/api/v1/auth/totp/status", { cache: "no-store" }).catch(() => null),
    ]);
    setSession(auth);
    setSessions(sessionList.sessions || []);
    setTotpStatus(factorStatus);
  }

  useEffect(() => { load().catch((error) => setMessage({ tone: "error", text: authErrorMessage(error) })); }, []);

  useEffect(() => {
    if (session === undefined || window.location.hash !== "#sessions") return;
    const frame = window.requestAnimationFrame(() => {
      const target = document.getElementById("sessions");
      if (!target) return;
      target.scrollIntoView({ block: "start" });
      target.focus({ preventScroll: true });
    });
    return () => window.cancelAnimationFrame(frame);
  }, [session]);

  async function revoke(id: string) {
    setBusy(id);
    setMessage(null);
    try {
      await authRequest(`/api/v1/auth/sessions/${encodeURIComponent(id)}`, { method: "DELETE" });
      setSessions((items) => items.filter((item) => item.id !== id));
      setMessage({ tone: "success", text: "Session revoked." });
    } catch (error) {
      setMessage({ tone: "error", text: authErrorMessage(error) });
    } finally { setBusy(null); }
  }

  if (session === undefined) return <><WorkspaceNav current="overview" /><main id="main" tabIndex={-1} className={styles.authMain}><p className={styles.loadingState}>Loading account…</p></main></>;
  if (!session?.authenticated || !session.user) return <><WorkspaceNav current="overview" /><main id="main" tabIndex={-1} className={styles.authMain}><section className={styles.deniedState}><h1>Sign in required</h1><p>Account controls are available to invited users only.</p><div className={styles.authLinks}><a href="/sign-in">Open sign in</a></div></section></main></>;

  const authenticatorSetupPath = `/authenticator?mode=enroll&next=${encodeURIComponent("/account")}`;
  const authenticatorManagePath = totpStatus?.enrolled
    ? `/authenticator?mode=step-up&next=${encodeURIComponent(authenticatorSetupPath)}`
    : authenticatorSetupPath;

  return (
    <>
      <WorkspaceNav current="overview" />
      <main id="main" tabIndex={-1} className={styles.authMain}>
        <div className={styles.authIntro}><p className="panel-kicker">Workspace / Account</p><h1>Your account</h1><p>Review identity, session access, and the authenticator that protects private research.</p></div>
        <section className={`${styles.authPanel} ${styles.widePanel}`} aria-labelledby="identity-heading">
          <div className={styles.sectionRule}><h2 id="identity-heading">Identity</h2><p>Your account identity determines which saved records you can access.</p></div>
          <div className={styles.statGrid}><div className={styles.stat}><strong>{session.user.name || session.user.login || "Member"}</strong><span>Display name</span></div><div className={styles.stat}><strong>{session.user.login ? `@${session.user.login}` : session.user.email || "Invited account"}</strong><span>{session.local_login_enabled ? "Development account" : "GitHub identity"}</span></div><div className={styles.stat}><strong>{session.user.role === "admin" ? "Administrator" : "Member"}</strong><span>Role</span></div></div>
          <div className={styles.permissionBox}><div><strong>{totpStatus?.enrolled ? "Authenticator protected" : "Authenticator setup required"}</strong><p>{totpStatus?.enrolled ? `${totpStatus.recovery_codes_remaining} recovery codes remain. Sensitive actions require a fresh code when needed.` : "Connect an authenticator app before using protected operations."}</p></div><a className="secondary" href={authenticatorManagePath}>{totpStatus?.enrolled ? "Manage authenticator" : "Set up authenticator"}</a></div>
          <div className={styles.sectionRule}><h2 id="sessions" tabIndex={-1}>Active sessions</h2><p>Revoke sessions you do not recognize. The current session is marked for clarity.</p></div>
          {sessions.length ? <ul className={styles.dataList}>{sessions.map((item) => <li className={styles.dataRow} key={item.id}><div><strong>{item.current ? "This browser" : item.user_agent || "Signed-in session"}</strong><small>Last seen {formatAuthDate(item.last_seen_at)} · Expires {formatAuthDate(item.expires_at)}</small></div><button className="secondary" type="button" disabled={Boolean(item.current) || busy === item.id} onClick={() => revoke(item.id)}>{busy === item.id ? "Revoking…" : item.current ? "Current" : "Revoke"}</button></li>)}</ul> : <p className={styles.loadingState}>No session details are available yet.</p>}
          {message ? <p className={styles.authMessage} data-tone={message.tone} role={message.tone === "error" ? "alert" : "status"}>{message.text}</p> : null}
          <div className={styles.authLinks}>{session.user.role === "admin" ? <a href="/admin">Open admin panel</a> : null}<a href="/overview">Return to workspace</a></div>
        </section>
      </main>
    </>
  );
}
