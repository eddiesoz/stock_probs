"use client";

// Shared auth chrome keeps account flows readable without changing workspace navigation.

import { useEffect } from "react";
import type { ReactNode } from "react";

import { AuthControls } from "./auth-controls";
import styles from "../app/auth.module.css";

export function AuthShell({
  children,
  eyebrow = "Private research workspace",
  title,
  description,
  showAccount = true,
}: Readonly<{
  children: ReactNode;
  eyebrow?: string;
  title: string;
  description: string;
  showAccount?: boolean;
}>) {
  useEffect(() => {
    document.title = `${title} | Signal Ledger`;
  }, [title]);

  return (
    <>
      <a className="skip-link" href="#main">Skip to main content</a>
      <header className={styles.authHeader}>
        <a className="brand-lockup" href="/overview" aria-label="Signal Ledger home">
          <span className="ledger-mark" aria-hidden="true"><i /><i /><i /></span>
          <span className={styles.brandName}>Signal Ledger</span>
        </a>
        {showAccount ? <AuthControls /> : <span className={styles.headerNote}>Local, auditable research</span>}
      </header>
      <main id="main" tabIndex={-1} className={styles.authMain}>
        <div className={styles.authIntro}>
          <p className="panel-kicker">{eyebrow}</p>
          <h1>{title}</h1>
          <p>{description}</p>
        </div>
        {children}
      </main>
      <footer className={styles.authFooter}>
        <span>Signal Ledger</span>
        <span>Research output, not investment advice.</span>
      </footer>
    </>
  );
}
