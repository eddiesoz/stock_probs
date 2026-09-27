import { Settings } from "../app/settings";
import { SelectedInstrumentStatus, WorkspaceLink } from "./workspace-link";

// Fixed route order and labels keep the primary workspace navigation predictable.
const primaryItems = [
  ["/overview", "Overview"],
  ["/research", "Research"],
  ["/tools", "Tools"],
] as const;

const toolItems = [
  ["/tools/forecast", "Forecast"],
  ["/tools/live-trading", "Live Trading"],
  ["/tools/markets", "Markets"],
] as const;

// The skip link targets `#main`, which each route renders as a focusable main element.
export function WorkspaceNav({ current }: Readonly<{ current: "overview" | "research" | "tools" }>) {
  return (
    <>
      <a className="skip-link" href="#main">Skip to main content</a>
      <header className="masthead">
        <div className="masthead-primary">
          <WorkspaceLink path="/overview" className="brand-lockup">
            <span className="ledger-mark" aria-hidden="true"><i /><i /><i /></span>
            <strong>Signal Ledger</strong>
          </WorkspaceLink>
          <div className="header-controls">
            <nav className="section-nav" aria-label="Primary navigation">
              {primaryItems.map(([path, label]) => (
                <WorkspaceLink
                  key={path}
                  path={path}
                  current={path === `/${current}`}
                >
                  {label}
                </WorkspaceLink>
              ))}
            </nav>
            <Settings />
          </div>
        </div>
        <SelectedInstrumentStatus />
      </header>
    </>
  );
}

export function ToolsNav({ current }: Readonly<{ current?: "forecast" | "live-trading" | "markets" }>) {
  return (
    <nav className="section-nav" aria-label="Tools">
      {toolItems.map(([path, label]) => (
        <WorkspaceLink key={path} path={path} current={current ? path === `/tools/${current}` : undefined}>{label}</WorkspaceLink>
      ))}
    </nav>
  );
}
