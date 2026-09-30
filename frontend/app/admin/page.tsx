"use client";

// UI gating is for clarity; the API independently authorizes every admin action.

import { FormEvent, useEffect, useRef, useState } from "react";

import { AuthRequestError, authErrorMessage, authRequest, formatAuthDate, getAuthSession, type AuthSession, type TotpStatus } from "../../components/auth-client";
import { WorkspaceNav } from "../../components/workspace-nav";
import styles from "../auth.module.css";

interface Invitation { id: string; github_id?: number; github_login?: string; code?: string; created_at?: string; expires_at?: string; redeemed_at?: string | null; }

export default function AdminPage() {
  const [session, setSession] = useState<AuthSession | null | undefined>(undefined);
  const [invitations, setInvitations] = useState<Invitation[]>([]);
  const [githubId, setGithubId] = useState("");
  const [githubLogin, setGithubLogin] = useState("");
  const [inviteEmail, setInviteEmail] = useState("");
  const [emailInvitesEnabled, setEmailInvitesEnabled] = useState<boolean | null>(null);
  const emailInputRef = useRef<HTMLInputElement>(null);
  const [backupName, setBackupName] = useState("");
  const [restoreName, setRestoreName] = useState("");
  const [totpCode, setTotpCode] = useState("");
  const [totpStatus, setTotpStatus] = useState<TotpStatus | null>(null);
  const [freshVerified, setFreshVerified] = useState(false);
  const [freshVerifiedUntil, setFreshVerifiedUntil] = useState<number | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [message, setMessage] = useState<{ tone: "error" | "success"; text: string } | null>(null);

  const clearFreshVerification = () => {
    setFreshVerified(false);
    setFreshVerifiedUntil(null);
  };

  useEffect(() => {
    if (freshVerifiedUntil === null) return;
    const remaining = Math.max(0, freshVerifiedUntil - Date.now());
    const timeout = window.setTimeout(() => {
      clearFreshVerification();
      setMessage({ tone: "error", text: "Fresh authenticator verification expired. Verify again before a backup or restore." });
    }, remaining);
    return () => window.clearTimeout(timeout);
  }, [freshVerifiedUntil]);

  useEffect(() => { document.title = "Administration | Signal Ledger"; }, []);

  async function load() {
    const auth = await getAuthSession();
    setSession(auth);
    if (auth?.authenticated && auth.user?.role === "admin") {
      const [response, factorStatus] = await Promise.all([
        authRequest<{ invitations?: Invitation[]; email_invites_enabled?: boolean }>("/api/v1/auth/invites", { cache: "no-store" }),
        authRequest<TotpStatus>("/api/v1/auth/totp/status", { cache: "no-store" }),
      ]);
      setInvitations(response.invitations || []);
      setEmailInvitesEnabled(response.email_invites_enabled === true);
      setTotpStatus(factorStatus);
    }
  }

  useEffect(() => { load().catch((error) => setMessage({ tone: "error", text: authErrorMessage(error) })); }, []);

  async function createInvitation(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusy("invite"); setMessage(null);
    try {
      const response = await authRequest<{ invitation?: Invitation; code?: string; github_id?: number; github_login?: string; expires_at?: string }>("/api/v1/auth/invites", { method: "POST", body: JSON.stringify({ github_id: Number(githubId), github_login: githubLogin.trim() || undefined }) });
      if (response.invitation) setInvitations((items) => [response.invitation as Invitation, ...items]);
      else setInvitations((items) => [{ id: crypto.randomUUID(), code: response.code, github_id: response.github_id, github_login: response.github_login, expires_at: response.expires_at }, ...items]);
      setGithubId(""); setGithubLogin(""); setMessage({ tone: "success", text: "Invitation created. Copy the single-use code through a private channel." });
    } catch (error) { setMessage({ tone: "error", text: authErrorMessage(error) }); }
    finally { setBusy(null); }
  }

  async function sendInvitationEmail() {
    if (emailInvitesEnabled !== true || !emailInputRef.current?.reportValidity()) return;
    setBusy("invite-email"); setMessage(null);
    try {
      await authRequest("/api/v1/auth/invites/email", {
        method: "POST",
        body: JSON.stringify({
          github_id: Number(githubId),
          github_login: githubLogin.trim() || undefined,
          email: inviteEmail.trim(),
        }),
      });
      setInviteEmail("");
      let refreshed = true;
      try {
        const response = await authRequest<{ invitations?: Invitation[]; email_invites_enabled?: boolean }>("/api/v1/auth/invites", { cache: "no-store" });
        setInvitations(response.invitations || []);
        setEmailInvitesEnabled(response.email_invites_enabled === true);
      } catch {
        refreshed = false;
      }
      setMessage({
        tone: "success",
        text: refreshed
          ? "Invitation submitted to mail server. Delivery is not confirmed."
          : "Invitation submitted to mail server. Delivery is not confirmed. The invitation list could not be refreshed.",
      });
    } catch (error) {
      const text = error instanceof AuthRequestError && [401, 403].includes(error.status)
        ? authErrorMessage(error)
        : "Invitation email could not be submitted. Check the recipient address and mail configuration, then try again.";
      setMessage({ tone: "error", text });
    }
    finally { setBusy(null); }
  }

  async function createBackup() {
    setBusy("backup"); setMessage(null);
    try {
      const response = await authRequest<{ name?: string }>("/api/v1/operations/backups", { method: "POST", body: JSON.stringify({ name: backupName.trim() || undefined }) });
      setMessage({ tone: "success", text: `Verified backup ${response.name || backupName || "created"}.` }); setBackupName(""); clearFreshVerification();
    } catch (error) {
      if (error instanceof AuthRequestError && error.status === 403) clearFreshVerification();
      setMessage({ tone: "error", text: authErrorMessage(error) });
    }
    finally { setBusy(null); }
  }

  async function verifyTotp() {
    setBusy("verify"); setMessage(null);
    try {
      await authRequest("/api/v1/auth/totp/step-up", { method: "POST", body: JSON.stringify({ code: totpCode.trim() }) });
      setTotpCode("");
      setFreshVerified(true);
      setFreshVerifiedUntil(Date.now() + 5 * 60 * 1000);
      setMessage({ tone: "success", text: "Fresh authenticator verification complete for this session." });
    }
    catch (error) { setMessage({ tone: "error", text: authErrorMessage(error) }); }
    finally { setBusy(null); }
  }

  async function restoreBackup(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusy("restore"); setMessage(null);
    try { await authRequest("/api/v1/operations/restores", { method: "POST", body: JSON.stringify({ name: restoreName.trim(), promote: true }) }); setMessage({ tone: "success", text: "Restore promoted. All sessions were revoked; sign in again before continuing." }); setRestoreName(""); clearFreshVerification(); }
    catch (error) {
      if (error instanceof AuthRequestError && error.status === 403) clearFreshVerification();
      setMessage({ tone: "error", text: authErrorMessage(error) });
    }
    finally { setBusy(null); }
  }

  if (session === undefined) return <><WorkspaceNav current="overview" /><main id="main" tabIndex={-1} className={styles.authMain}><p className={styles.loadingState}>Checking administrator access…</p></main></>;
  if (!session?.authenticated || session.user?.role !== "admin") return <><WorkspaceNav current="overview" /><main id="main" tabIndex={-1} className={styles.authMain}><section className={styles.deniedState}><h1>Administrator access required</h1><p>This panel is only available to the designated owner account. Every sensitive operation is checked again by the API.</p><div className={styles.authLinks}><a href="/account">Back to account</a><a href="/sign-in">Sign in</a></div></section></main></>;

  return (
    <>
      <WorkspaceNav current="overview" />
      <main id="main" tabIndex={-1} className={styles.authMain}>
        <div className={styles.authIntro}><p className="panel-kicker">Workspace / Administration</p><h1>Keep access deliberate</h1><p>Invite the people you trust and manage verified recovery operations without exposing database controls to the browser.</p></div>
        <section className={`${styles.authPanel} ${styles.widePanel}`} aria-labelledby="invite-heading">
          <div className={styles.sectionRule}><h2 id="invite-heading">Invite a GitHub account</h2><p>Invitation codes are single-use and expire. Resolve the identity before sharing the code.</p></div>
          <form className={styles.formGrid} onSubmit={createInvitation} noValidate><label htmlFor="github-id">GitHub account ID<input id="github-id" name="github_id" inputMode="numeric" pattern="[0-9]+" value={githubId} onChange={(event) => setGithubId(event.target.value.replace(/\D/g, ""))} placeholder="1234567" autoComplete="off" required /></label><label htmlFor="github-login">GitHub username (optional)<input id="github-login" name="github_login" value={githubLogin} onChange={(event) => setGithubLogin(event.target.value)} placeholder="octocat" autoComplete="off" /></label><button className="primary full" type="submit" disabled={busy === "invite" || busy === "invite-email" || !githubId.trim()}>{busy === "invite" ? "Creating invitation…" : "Create invitation"}</button></form>
          <div className={styles.sectionRule}><h2 id="email-invite-heading">Send invitation by email</h2><p>Use the same GitHub identity above and enter the address that should receive its invitation.</p></div>
          <div className={styles.permissionBox}>
            <div>
              <strong>{emailInvitesEnabled === true ? "Email invitations are enabled" : emailInvitesEnabled === false ? "Email invitations are not configured" : "Checking email invitation settings"}</strong>
              <p id="email-invites-help">{emailInvitesEnabled === true
                ? "A successful response confirms that the mail server accepted the message; it does not confirm delivery."
                : emailInvitesEnabled === false
                  ? "Mail sending is not configured on this server. You can still create a single-use code and share it through a private channel."
                  : "Email sending stays disabled until the server confirms that mail is configured."}</p>
            </div>
          </div>
          <div className={styles.formGrid}>
            <label className={styles.full} htmlFor="invite-email">Recipient email address<input ref={emailInputRef} id="invite-email" name="email" type="email" inputMode="email" autoComplete="email" maxLength={254} value={inviteEmail} onChange={(event) => setInviteEmail(event.target.value)} placeholder="person@example.com" aria-describedby="email-invites-help" required /></label>
            <button className="secondary full" type="button" aria-describedby="email-invites-help" disabled={emailInvitesEnabled !== true || busy === "invite-email" || busy === "invite" || !githubId.trim() || !inviteEmail.trim()} onClick={sendInvitationEmail}>{busy === "invite-email" ? "Submitting invitation email…" : "Send invitation email"}</button>
          </div>
          {invitations.length ? <ul className={styles.dataList}>{invitations.map((invite) => <li className={styles.dataRow} key={invite.id}><div><strong>{invite.github_login || `GitHub account ${invite.github_id || ""}`}</strong><small>{invite.redeemed_at ? `Redeemed ${formatAuthDate(invite.redeemed_at)}` : `Expires ${formatAuthDate(invite.expires_at)}`} {invite.code ? `· Code ${invite.code}` : ""}</small></div><span className="badge neutral">{invite.redeemed_at ? "Used" : "Open"}</span></li>)}</ul> : <p className={styles.loadingState}>No invitations created in this session.</p>}
          <div className={styles.sectionRule}><h2>Verified backups</h2><p>Backups are created and verified on the server. Enter a current authenticator code below before creating one.</p></div>
          <div className={styles.formGrid}><label className={styles.full} htmlFor="backup-name">Backup label (optional)<input id="backup-name" value={backupName} onChange={(event) => setBackupName(event.target.value)} placeholder="before-auth-migration" /></label><button className="secondary full" type="button" disabled={!freshVerified || busy === "backup"} onClick={createBackup}>{busy === "backup" ? "Creating verified backup…" : "Create verified backup"}</button></div>
          <div className={styles.sectionRule}><h2>Promote a restore</h2><p>Use only after reviewing the artifact. A promoted restore requires a fresh authenticator check and revokes other sessions.</p></div>
          <div className={styles.permissionBox}><div><strong>{freshVerified ? "Fresh authenticator verified" : "Authenticator verification required"}</strong><p>{freshVerified ? "Complete the operation now; the server also checks that verification is recent." : totpStatus?.enrolled ? "Enter the newest code immediately before a backup or promoted restore." : "Set up an authenticator before using backup controls."}</p></div></div>
          <div className={styles.formGrid}><label className={styles.full} htmlFor="admin-totp-code">Current authenticator code<input id="admin-totp-code" name="totp_code" type="text" inputMode="numeric" autoComplete="one-time-code" pattern="[0-9]{6}" maxLength={6} value={totpCode} onChange={(event) => setTotpCode(event.target.value.replace(/\D/g, "").slice(0, 6))} placeholder="000000" /></label><button className="secondary full" type="button" disabled={busy === "verify" || totpCode.length !== 6 || !totpStatus?.enrolled} onClick={verifyTotp}>{busy === "verify" ? "Verifying…" : freshVerified ? "Verify again" : "Verify authenticator"}</button></div>
          <form className={styles.formGrid} onSubmit={restoreBackup} noValidate><label className={styles.full} htmlFor="restore-name">Verified backup name<input id="restore-name" value={restoreName} onChange={(event) => setRestoreName(event.target.value)} placeholder="backup-2026-09-27" required /></label><button className="secondary full" type="submit" disabled={!freshVerified || busy === "restore" || !restoreName.trim()}>{busy === "restore" ? "Promoting restore…" : "Promote restore"}</button></form>
          {message ? <p className={styles.authMessage} data-tone={message.tone} role={message.tone === "error" ? "alert" : "status"}>{message.text}</p> : null}
        </section>
      </main>
    </>
  );
}
