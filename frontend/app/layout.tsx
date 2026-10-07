import type { ReactNode } from "react";

import { AssistantHost } from "../components/assistant/assistant-host";

export default function RootLayout({ children }: Readonly<{ children: ReactNode }>) {
  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        {/* Stored theme colors must be applied before the stylesheet can paint. */}
        <script src="/assets/theme.js" />
        <title>Signal Ledger</title>
        <link rel="icon" href="/assets/favicon.svg" type="image/svg+xml" />
        <link rel="stylesheet" href="/assets/app.css" />
      </head>
      <body><div data-assistant-background>{children}</div><AssistantHost /></body>
    </html>
  );
}
