import type { Metadata } from "next";

import { BriefingWorkspace } from "../../../components/briefing/briefing-workspace";

export const metadata: Metadata = {
  title: "What changed? | Signal Ledger",
  description: "Review a saved, owner-scoped research briefing without refreshing it automatically.",
};

export default function WhatChangedPage() {
  return <BriefingWorkspace />;
}
