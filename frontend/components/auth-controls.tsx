"use client";

// Resolve the current account from the server so navigation follows session revocation.

import { useEffect, useState } from "react";

import { authErrorMessage, authRequest, getAuthSession, type AuthSession } from "./auth-client";

export function AuthControls() {
  const [session, setSession] = useState<AuthSession | null | undefined>(undefined);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    getAuthSession().then((value) => { if (active) setSession(value); }).catch(() => { if (active) setSession(null); });
    return () => { active = false; };
  }, []);

  if (session === undefined) return <span className="auth-status-skeleton" aria-label="Checking account" />;
  if (!session?.authenticated || !session.user) return <a className="auth-link" href="/sign-in">Sign in</a>;

  const label = session.user.name || session.user.login || "Account";
  const role = session.user.role || session.role;
  return (
    <div className="auth-controls" role="group" aria-label="Account controls">
      <span className="auth-user-label" title={label}>{label}</span>
      <a className="auth-link" href="/account">Account</a>
      {role === "admin" ? <a className="auth-link" href="/admin">Admin</a> : null}
      <button
        className="auth-signout"
        type="button"
        disabled={busy}
        onClick={async () => {
          setBusy(true);
          setError("");
          try {
            await authRequest("/api/v1/auth/logout", { method: "POST", body: "{}" });
            window.location.assign("/sign-in");
          } catch (error) {
            setBusy(false);
            setError(authErrorMessage(error));
          }
        }}
      >{busy ? "Signing out…" : "Sign out"}</button>
      {error ? <span className="sr-only" role="alert">{error}</span> : null}
    </div>
  );
}
