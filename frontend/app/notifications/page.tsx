import type { Metadata } from "next";
import { WorkspaceNav } from "../../components/workspace-nav";
import { NotificationsPage } from "../../components/monitoring/notifications-page";

export const metadata: Metadata = { title: "Notifications | Signal Ledger", description: "Private saved price alerts and notifications." };
export default function Page() { return <><WorkspaceNav current="overview" /><NotificationsPage /></>; }
