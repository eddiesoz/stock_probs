import type { Metadata } from "next";

import { WorkspaceLink } from "../../components/workspace-link";
import { ToolsNav } from "../../components/workspace-nav";

export const metadata: Metadata = {
  title: "Tools | Signal Ledger",
  description: "Open the local forecast, live quote, and markets research workspaces.",
};

// Tab navigation only routes to local pages; it never submits a forecast or places a trade.
export default function ToolsPage() {
  return (
    <>
      <section className="masthead" aria-label="Tools navigation"><div className="masthead-primary"><p className="panel-kicker">Tools</p><ToolsNav /></div></section>
      <main id="main" tabIndex={-1}>
        <section className="hero" aria-labelledby="tools-heading">
          <div className="hero-copy">
            <p className="panel-kicker">Workspace / Tools</p>
            <h1 id="tools-heading">Research tools</h1>
            <p className="workspace-summary">Open a tool with the selected instrument preserved. Changing tabs never submits a forecast or places a trade.</p>
          </div>
        </section>
        <ul className="api-endpoint-list tool-card-list" aria-label="Available tools">
          <li><h2>Forecast</h2><p>Build an explicit probability forecast.</p><WorkspaceLink className="text-link" path="/tools/forecast">Open Forecast</WorkspaceLink></li>
          <li><h2>Live Trading</h2><p>Inspect provider-labelled quote and depth availability. Trade execution is not available.</p><WorkspaceLink className="text-link" path="/tools/live-trading">Open Live Trading</WorkspaceLink></li>
          <li><h2>Markets</h2><p>Review a watchlist with explicit quote and chart provenance.</p><WorkspaceLink className="text-link" path="/tools/markets">Open Markets</WorkspaceLink></li>
        </ul>
      </main>
    </>
  );
}
