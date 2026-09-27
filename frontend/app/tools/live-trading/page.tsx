import type { Metadata } from "next";

import { ToolPage } from "../tool-page";
import { LiveTradingWorkspace } from "./workspace";

export const metadata: Metadata = {
  title: "Live Trading | Signal Ledger",
  description: "A provider-labelled quote and market-depth availability workspace without order execution.",
};

// Badge and summary state the no-order boundary; the workspace below offers research
// actions only and cannot route orders.
export default function LiveTradingPage() {
  return (
    <ToolPage
      badge="No order entry"
      kicker="Market workspace"
      summary="Follow provider-labelled quote snapshots and market depth availability for research. Prices may be delayed."
      title="Live Trading"
      tool="live-trading"
    >
      <LiveTradingWorkspace />
    </ToolPage>
  );
}
