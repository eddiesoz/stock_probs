import type { Metadata } from "next";

import { WorkspaceLink } from "../../components/workspace-link";
import { ResearchWorkspace } from "./research-workspace";
import styles from "./workspace.module.css";

export const metadata: Metadata = {
  title: "Research | Signal Ledger",
  description: "Recorded forecasts and market context for local research only.",
};

// `id="main"` with tabIndex is the skip-link target; it must exist on every route for
// keyboard users. Copy stays research-framed so no order workflow is implied.
export default function ResearchPage() {
  return (
    <main className={styles.page} id="main" tabIndex={-1}>
      <section className={styles.hero} aria-labelledby="research-heading">
        <div>
          <p className="panel-kicker">Workspace / Research</p>
          <h1 id="research-heading">Recorded research</h1>
          <p>Move from immutable forecast evidence to bounded market context without creating an order workflow.</p>
        </div>
        <span className="badge neutral">Research only</span>
      </section>

      <aside className={styles.notice} aria-label="Research data limits">
        <strong>Not a trading platform.</strong> Data can be delayed, stale, partial, or unavailable. Check each result’s source and as-of time before using it for a decision.
      </aside>

      <section className={styles.destinations} aria-label="Research destinations">
        <article>
          <p className="panel-kicker">Recorded evidence</p>
          <h2>Forecast ledger and saved results</h2>
          <p>Find successful, repeated, and failed requests, export the filtered immutable record, or reopen a result exactly as saved. Fresh historical-cutoff analysis remains separate.</p>
          <WorkspaceLink className="text-link" path="/#history-heading">Open search ledger</WorkspaceLink>
        </article>
        <article>
          <p className="panel-kicker">Probability analysis</p>
          <h2>Forecast tool</h2>
          <p>Choose a completed origin and future target, then submit an explicit probability request.</p>
          <WorkspaceLink className="text-link" path="/tools/forecast">Open forecast tool</WorkspaceLink>
        </article>
        <article>
          <p className="panel-kicker">Market context</p>
          <h2>Markets</h2>
          <p>Inspect source-labelled watchlist and chart context. Availability does not mean real-time delivery.</p>
          <WorkspaceLink className="text-link" path="/tools/markets">Open markets</WorkspaceLink>
        </article>
      </section>
      <ResearchWorkspace />
    </main>
  );
}
