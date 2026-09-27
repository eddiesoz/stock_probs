import type { ReactNode } from "react";

import { WorkspaceNav } from "../../components/workspace-nav";

// Every workspace route renders the shared nav so primary navigation and the selected
// instrument persist across local page transitions.
export default function OverviewLayout({ children }: Readonly<{ children: ReactNode }>) {
  return <><WorkspaceNav current="overview" />{children}</>;
}
