// Saved simulations reopen immutable baselines and never submit portfolio transactions.
import type { Metadata } from "next";
import { WhatIf } from "../../../components/portfolio/what-if";
import { ToolsNav } from "../../../components/workspace-nav";

export const metadata: Metadata = { title: "Portfolio what-if | Signal Ledger", description: "Explore simulations using frozen balances, quotes and indicative FX." };
export default function WhatIfPage() { return <><ToolsNav current="what-if" /><WhatIf /></>; }
