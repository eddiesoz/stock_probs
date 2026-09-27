import type { Metadata } from "next";

import { PortfolioWorkspace } from "./portfolio-workspace";
import styles from "./workspace.module.css";

export const metadata: Metadata = {
  title: "Overview | Signal Ledger",
  description: "A local, manually maintained portfolio overview for research context.",
};

// `id="main"` is the skip-link target. The hero states the no-brokerage/no-real-time
// boundary up front because holdings are user-entered context, not positions.
export default function OverviewPage() {
  return (
    <main className={styles.page} id="main" tabIndex={-1}>
      <section className={styles.hero} aria-labelledby="overview-heading">
        <div>
          <p className="panel-kicker">Workspace / Overview</p>
          <h1 id="overview-heading">Portfolio overview</h1>
          <p>Organize manually entered holdings before moving into recorded research and analysis tools.</p>
        </div>
        <aside aria-label="Workspace limits">
          <strong>Decision support only</strong>
          <span>No brokerage connection, order routing, or assumed real-time valuation.</span>
        </aside>
      </section>
      <PortfolioWorkspace />
    </main>
  );
}
