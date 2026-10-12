// Keep the exported route static; private records load through the authenticated API.
import type { Metadata } from "next";
import { Theses } from "../../../components/research/theses";

export const metadata: Metadata = { title: "Research theses | Signal Ledger", description: "Record private investment reasoning, evidence, and review dates." };
export default function ThesesPage() { return <Theses />; }
