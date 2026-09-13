---
name: "browser-qa"
description: "Build and audit deterministic Stock Probability browser QA for accessibility, responsive themes, race handling, and complete news states. Use when adding or reviewing Playwright fixtures, dashboard regressions, walkthrough captures, axe or contrast checks, no-flash behavior, or request supersession."
---

# Stock Probability browser QA

Use this project skill for the real local FastAPI application exercised through pinned Playwright
Chromium. Reuse the shared browser fixtures and test observable behavior through actual controls.

## Workflow

1. Start from the shared isolated fixture runtime and diagnostics in
   [`references/fixtures-and-network.md`](references/fixtures-and-network.md).
2. Exercise semantic controls, keyboard behavior, responsive layouts, theme ordering, computed
   contrast, axe, forced colors, reduced motion, and print with
   [`references/accessibility-and-theme.md`](references/accessibility-and-theme.md).
3. Cover every required news terminal state and force races with held requests and explicit release
   ordering as described in [`references/states-and-races.md`](references/states-and-races.md).
4. Assert the API-only boundary and account exactly for deliberate HTTP failures and request
   aborts. Fail on every undeclared request, console error, page error, or network failure.

## Hard boundaries

- Use deterministic fixtures for the gate; keep opt-in live-provider probes separate.
- Prefer role/label locators and actual clicks, typing, focus, disclosure, retry, and paging actions.
- Do not treat screenshots as proof of first-paint ordering, axe as a screen-reader session, or
  viewport emulation as physical-mobile evidence.
- Do not add browser dependencies, a second fixture framework, arbitrary sleeps, hidden retries,
  direct SQLite access, or direct Yahoo requests.

## Reference files

| File | Purpose |
| --- | --- |
| [`references/fixtures-and-network.md`](references/fixtures-and-network.md) | Isolated real-app fixtures and exact browser diagnostics. |
| [`references/accessibility-and-theme.md`](references/accessibility-and-theme.md) | Keyboard, axe, contrast, responsive, and no-flash checks. |
| [`references/states-and-races.md`](references/states-and-races.md) | News-state matrix and deterministic race guards. |
