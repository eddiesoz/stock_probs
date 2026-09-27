import type { ReactNode } from "react";

import { ToolsNav } from "../../components/workspace-nav";
import styles from "./tool-page.module.css";

type ToolPageProps = Readonly<{
  badge: string;
  children: ReactNode;
  kicker: string;
  summary: string;
  title: string;
  tool: "forecast" | "live-trading" | "markets";
}>;

// Shared tool shell. `id="main"` is the skip-link target and the badge is required copy so
// each tool states its own limits (research only / no trading controls).
export function ToolPage({ badge, children, kicker, summary, title, tool }: ToolPageProps) {
  return (
    <>
      <section className={styles.toolNav} aria-label="Tools navigation"><div className="masthead"><div className="masthead-primary"><p className="panel-kicker">Tools</p><ToolsNav current={tool} /></div></div></section>
      <main className={styles.page} id="main" tabIndex={-1}>
        <header className={styles.hero}>
          <div><p className="panel-kicker">{kicker}</p><h1>{title}</h1><p>{summary}</p></div>
          <span className="badge neutral">{badge}</span>
        </header>
        {children}
      </main>
    </>
  );
}
