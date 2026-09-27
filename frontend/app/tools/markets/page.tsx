import type { Metadata } from "next";

import { ToolPage } from "../tool-page";
import { MarketsWorkspace } from "./workspace";

export const metadata: Metadata = {
  title: "Markets | Signal Ledger",
  description: "Filter a local watchlist and inspect provider-labelled quote and bounded chart data.",
};

// All quote and chart data is served from the local /api/v1 boundary; the browser never
// reaches a market-data provider directly.
export default function MarketsPage() {
  return (
    <ToolPage
      badge="Research only"
      kicker="Watchlist & charts"
      summary="Compare watchlist quotes and charts, with each source and update time clearly labelled."
      title="Markets"
      tool="markets"
    >
      <MarketsWorkspace />
    </ToolPage>
  );
}
