import type { ReactNode } from "react";

import { WorkspaceNav } from "../../components/workspace-nav";
import { ResearchNav } from "../../components/research/feature-nav";

// Every workspace route renders the shared nav so primary navigation and the selected
// instrument persist across local page transitions.
export default function ResearchLayout({ children }: Readonly<{ children: ReactNode }>) {
  return <><WorkspaceNav current="research" /><ResearchNav />{children}</>;
}
