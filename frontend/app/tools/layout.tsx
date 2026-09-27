import type { ReactNode } from "react";

import { WorkspaceNav } from "../../components/workspace-nav";

// Tools render the shared primary nav plus a tool sub-nav so the selected instrument stays
// in context while moving between tools.
export default function ToolsLayout({ children }: Readonly<{ children: ReactNode }>) {
  return (
    <>
      <WorkspaceNav current="tools" />
      {children}
    </>
  );
}
