"use client";

import { FormEvent, useEffect, useState } from "react";

import { authErrorMessage, authRequest } from "../../components/auth-client";
import { AuthShell } from "../../components/auth-shell";
import styles from "../auth.module.css";

export default function InvitePage() {
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<{ tone: "error" | "success"; text: string } | null>(null);

  useEffect(() => {
    const queryCode = new URLSearchParams(window.location.search).get("code");
    if (queryCode) {
      setCode(queryCode);
      const cleanUrl = new URL(window.location.href);
      cleanUrl.searchParams.delete("code");
      window.history.replaceState(window.history.state, "", `${cleanUrl.pathname}${cleanUrl.search}${cleanUrl.hash}`);
    }
  }, []);

  async function redeem(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setMessage(null);
    try {
      const response = await authRequest<{ authorization_url?: string }>("/api/v1/auth/invites/redeem", {
        method: "POST",
        body: JSON.stringify({ code: code.trim() }),
      });
      const destination = response.authorization_url;
      if (!destination || new URL(destination).origin !== "https://github.com") {
        throw new Error("The GitHub authorization link is unavailable.");
      }
      window.location.assign(destination);
    } catch (error) {
      setBusy(false);
      setMessage({ tone: "error", text: authErrorMessage(error) });
    }
  }

  return (
    <AuthShell showAccount={false} eyebrow="Invitation only" title="Join the workspace" description="An invitation connects one GitHub identity to a private Signal Ledger account. It can be redeemed once and expires automatically.">
      <section className={styles.authPanel} aria-labelledby="invite-heading">
        <h2 id="invite-heading">Redeem invitation</h2>
        <p className={styles.panelLead}>Paste the single-use code from your administrator. You will set up a passkey after the code is accepted.</p>
        <form className={styles.authForm} onSubmit={redeem} noValidate>
          <label htmlFor="invite-code">Invitation code
            <input id="invite-code" name="code" type="text" autoComplete="one-time-code" spellCheck={false} value={code} onChange={(event) => setCode(event.target.value)} placeholder="Paste your code" required />
          </label>
          <button className="primary" type="submit" disabled={busy || !code.trim()}>{busy ? "Checking invitation…" : "Continue"}</button>
        </form>
        {message ? <p className={styles.authMessage} data-tone={message.tone} role="alert">{message.text}</p> : null}
        <p className={styles.securityNote}>The code is sent only to the local service over the current origin. Never share it in a public issue or chat.</p>
        <div className={styles.authLinks}><a href="/sign-in">Back to sign in</a></div>
      </section>
    </AuthShell>
  );
}
