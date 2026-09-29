"use client";

// Old bookmarks can reach this static export directly; the server redirects production
// requests, and this fallback offers only the current authenticator flow.

import { AuthShell } from "../../components/auth-shell";
import styles from "../auth.module.css";

export default function PasskeyPage() {
  return (
    <AuthShell eyebrow="Account security" title="Use your authenticator" description="Passkeys have been retired for Signal Ledger sign-in.">
      <section className={styles.authPanel} aria-labelledby="retired-heading">
        <h2 id="retired-heading">Continue with your authenticator</h2>
        <p className={styles.panelLead}>Sign in with GitHub, then set up or verify a code from your authenticator app.</p>
        <div className={styles.authLinks}>
          <a href="/sign-in">Open sign in</a>
          <a href="/authenticator?mode=enroll&next=%2Foverview">Open authenticator setup</a>
        </div>
      </section>
    </AuthShell>
  );
}
