// Transactions remain explicit workspace previews and commits rather than assistant actions.
import type { Metadata } from "next";
import { PortfolioEntry } from "../../../components/portfolio/portfolio-workspace";

export const metadata: Metadata = { title: "Transactions | Signal Ledger", description: "Review original transactions and resulting balances before committing." };
export default function TransactionsPage() { return <PortfolioEntry transactions />; }
