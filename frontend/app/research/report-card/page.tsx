import type { Metadata } from "next";
import { ReportCardPage } from "../../../components/monitoring/report-card-page";

export const metadata: Metadata = { title: "Forecast report card | Signal Ledger", description: "Saved forecast outcomes, evidence and scoring denominators." };
export default function Page() { return <ReportCardPage />; }
