"use client";

// The server's auth status decides which sign-in path is offered in this environment.

import { FormEvent, useEffect, useState } from "react";

import { authErrorMessage, authRequest, getAuthSession, safeLocalNext, type AuthSession } from "../../components/auth-client";
import { AuthShell } from "../../components/auth-shell";
import styles from "../auth.module.css";

const GITHUB_START_PATH = "/api/v1/auth/github/start";

export default function SignInPage() {
  const [session, setSession] = useState<AuthSession | null | undefined>(undefined);
  const [localEnabled, setLocalEnabled] = useState(false);
  const [githubEnabled, setGithubEnabled] = useState(false);
  const [statusLoaded, setStatusLoaded] = useState(false);
  const [login, setLogin] = useState("");
  const [password, setPassword] = useState("");
  const [nextPath, setNextPath] = useState("/overview");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ tone: "error" | "success"; text: string } | null>(null);

  useEffect(() => {
    let active = true;
    const params = new URLSearchParams(window.location.search);
    setNextPath(safeLocalNext(params.get("next")));
    Promise.all([
      getAuthSession(),
      authRequest<{ status?: string }>("/api/v1/auth/status", { cache: "no-store" }),
    ]).then(([value, status]) => {
      if (!active) return;
      setSession(value);
      setLocalEnabled(status.status === "local");
      setGithubEnabled(status.status === "github");
      setStatusLoaded(true);
    }).catch(() => {
      if (active) {
        setSession(null);
        setLocalEnabled(false);
        setGithubEnabled(false);
        setStatusLoaded(true);
        setMessage({ tone: "error", text: "Sign-in options could not load. Check the connection and reload this page." });
      }
    });
    return () => { active = false; };
  }, []);

  const requiresAuthenticator = Boolean(session?.authenticated && (session.requires_totp || session.totp_required));
  const authenticatorPath = `/authenticator?mode=${session?.totp_enrolled ? "verify" : "enroll"}&next=${encodeURIComponent(nextPath)}`;

  useEffect(() => {
    if (!session?.authenticated) return;
    setMessage({
      tone: "success",
      text: requiresAuthenticator
        ? "Your identity is signed in. Complete authenticator setup or verification to continue."
        : "You are already signed in. Open the workspace when you are ready.",
    });
  }, [requiresAuthenticator, session]);

  async function submitLocal(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setMessage(null);
    try {
      const response = await authRequest<{ requires_totp?: boolean; user?: unknown }>("/api/v1/auth/local/login", {
        method: "POST",
        body: JSON.stringify({ username: login.trim(), password }),
      });
      if (response.requires_totp) {
        window.location.assign(`/authenticator?mode=enroll&next=${encodeURIComponent(nextPath)}`);
      } else {
        window.location.assign(nextPath);
      }
    } catch (error) {
      setBusy(false);
      setMessage({ tone: "error", text: authErrorMessage(error) });
    }
  }

  return (
    <AuthShell showAccount={false} eyebrow="Secure access" title="Return to the ledger" description="Signal Ledger keeps research private, attributable, and easy to audit. Sign in to continue to your instrument workspace.">
      <section className={styles.authPanel} aria-labelledby="sign-in-heading">
        <h2 id="sign-in-heading">Sign in</h2>
        <p className={styles.panelLead}>{!statusLoaded ? "Checking sign-in options…" : githubEnabled ? "Use your invited GitHub account. An authenticator app code is required after the first successful sign-in." : localEnabled ? "Sign in with your development account to continue." : "Sign-in options are unavailable."}</p>
        {githubEnabled ? <a className="primary buttonIcon" href={GITHUB_START_PATH} data-testid="github-sign-in">
          <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 2.3a9.7 9.7 0 0 0-3.07 18.9c.49.09.67-.21.67-.47v-1.65c-2.73.59-3.31-1.16-3.31-1.16-.45-1.13-1.1-1.43-1.1-1.43-.89-.61.07-.6.07-.6.98.07 1.5 1 1.5 1 .88 1.5 2.3 1.06 2.86.81.09-.63.34-1.06.62-1.3-2.18-.25-4.47-1.09-4.47-4.84 0-1.07.38-1.94 1-2.62-.1-.25-.43-1.25.1-2.59 0 0 .82-.26 2.67 1a9.25 9.25 0 0 1 4.86 0c1.85-1.26 2.67-1 2.67-1 .53 1.34.2 2.34.1 2.59.62.68 1 1.55 1 2.62 0 3.76-2.29 4.59-4.48 4.83.35.3.66.88.66 1.78v2.65c0 .26.18.57.68.47A9.7 9.7 0 0 0 12 2.3Z" /></svg>
          Continue with GitHub
        </a> : null}
        {localEnabled ? <>
          <div className={styles.divider}><span>Development only</span></div>
          <form className={styles.authForm} onSubmit={submitLocal} noValidate>
            <label htmlFor="login">Local account
              <input id="login" name="login" type="text" autoComplete="username" value={login} onChange={(event) => setLogin(event.target.value)} required />
            </label>
            <label htmlFor="password">Password
              <input id="password" name="password" type="password" autoComplete="current-password" value={password} onChange={(event) => setPassword(event.target.value)} required />
            </label>
            <button className="secondary" type="submit" disabled={busy || !login.trim() || !password}>{busy ? "Signing in…" : "Use local account"}</button>
          </form>
        </> : null}
        {message ? <p className={styles.authMessage} data-tone={message.tone} role={message.tone === "error" ? "alert" : "status"}>{message.text}</p> : null}
        {requiresAuthenticator ? <div className={styles.authLinks}><a href={authenticatorPath}>Complete authenticator {session?.totp_enrolled ? "verification" : "setup"}</a></div> : null}
        <p className={styles.securityNote}>Sessions use an HttpOnly cookie and expire automatically. Credentials never live in browser storage.</p>
        <div className={styles.authLinks}>
          <a href="/invite">Have an invitation?</a>
          <a href="/account">Account recovery and sessions</a>
        </div>
      </section>
    </AuthShell>
  );
}
