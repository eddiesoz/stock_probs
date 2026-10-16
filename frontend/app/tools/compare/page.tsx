// Navigation renders controls without submitting market-data or forecast work.
import type { Metadata } from "next";
import { Comparison } from "../../../components/research/comparison";
import { ToolsNav } from "../../../components/workspace-nav";

export const metadata: Metadata = { title: "Compare instruments | Signal Ledger", description: "Compare dated daily price history and save immutable research snapshots." };
export default function ComparePage() { return <><ToolsNav current="compare" /><Comparison /></>; }
