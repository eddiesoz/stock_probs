"use client";

import { FormEvent, useEffect, useState } from "react";

import { authErrorMessage, authRequest } from "../../components/auth-client";
import { AuthShell } from "../../components/auth-shell";
import styles from "../auth.module.css";

type InvitationRecoveryCode = "invitation_email_mismatch" | "invitation_rejected";

function invitationRecoveryCode(value: string | null): InvitationRecoveryCode | null {
  if (value === "invitation_email_mismatch" || value === "invitation_rejected") return value;
  return null;
}

export default function InvitePage() {
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [recoveryCode, setRecoveryCode] = useState<InvitationRecoveryCode | null>(null);
  const [message, setMessage] = useState<{ tone: "error" | "success"; text: string } | null>(null);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    setRecoveryCode(invitationRecoveryCode(params.get("error")));
    const queryCode = params.get("code");
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
    <AuthShell showAccount={false} eyebrow="Invitation only" title="Join the workspace" description="An invitation is single-use and expires automatically. Email-only invitations are checked against the verified email on the GitHub account you use to continue.">
      <section className={styles.authPanel} aria-labelledby="invite-heading">
        <h2 id="invite-heading">Redeem invitation</h2>
        <p className={styles.panelLead}>Paste the single-use code from your administrator. For an email-only invitation, continue with a GitHub account that has the invitation email marked verified. If your administrator restricted it to an account, use that GitHub account. After GitHub confirms your identity, you will connect an authenticator app.</p>
        <form className={styles.authForm} onSubmit={redeem} noValidate>
          <label htmlFor="invite-code">Invitation code
            <input id="invite-code" name="code" type="text" autoComplete="one-time-code" spellCheck={false} value={code} onChange={(event) => setCode(event.target.value)} placeholder="Paste your code" required />
          </label>
          <button className="primary" type="submit" disabled={busy || !code.trim()}>{busy ? "Checking invitation…" : "Continue"}</button>
        </form>
        {recoveryCode === "invitation_email_mismatch" ? <p className={styles.authMessage} data-tone="error" role="alert">
          <strong>GitHub could not verify the invited email address.</strong> This invitation is still available. Add and verify the exact invited address in <a href="https://github.com/settings/emails" target="_blank" rel="noopener noreferrer">GitHub email settings</a>, then return to the original invitation email, paste its code above, and continue with the GitHub account that has that exact address marked verified.
        </p> : null}
        {recoveryCode === "invitation_rejected" ? <p className={styles.authMessage} data-tone="error" role="alert">
          <strong>This invitation code cannot be used.</strong> It may be invalid, expired, or already used. If you have already joined, use normal <a href="/sign-in">sign in</a>. If this is your first sign-in and the invitation expired, ask your administrator for a fresh invitation.
        </p> : null}
        {message ? <p className={styles.authMessage} data-tone={message.tone} role="alert">{message.text}</p> : null}
        <p className={styles.securityNote}>The code is sent only to the local service over the current origin. Never share it in a public issue or chat.</p>
        <div className={styles.authLinks}><a href="/sign-in">Back to sign in</a></div>
      </section>
    </AuthShell>
  );
}
