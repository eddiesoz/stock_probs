// Gate the transaction-derived portfolio while retaining the original manual workspace when disabled.
import type { Metadata } from "next";

import { PortfolioEntry } from "../../components/portfolio/portfolio-workspace";

export const metadata: Metadata = {
  title: "Overview | Signal Ledger",
  description: "Manually maintained accounts, portfolio values and original-currency transactions.",
};

export default function OverviewPage() {
  return <PortfolioEntry />;
}
