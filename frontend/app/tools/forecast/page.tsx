import type { Metadata } from "next";

import { ToolPage } from "../tool-page";
import { ForecastWorkspace } from "./workspace";

export const metadata: Metadata = {
  title: "Forecast | Signal Ledger",
  description: "Compare direction, threshold, return, and price probabilities across explicit rolling horizons.",
};

// Horizon and origin/target wording is deliberate: users must confirm the exact completed
// interval before an explicit submit, and no forecast is run on page load.
export default function ForecastPage() {
  return (
    <ToolPage
      badge="Research only"
      kicker="Analysis workspace"
      summary="Choose an interval, confirm its completed origin and future target, then submit deliberately."
      title="Probability forecast"
      tool="forecast"
    >
      <ForecastWorkspace />
    </ToolPage>
  );
}
