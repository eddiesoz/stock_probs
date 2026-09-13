# Browser fixtures and network containment

Reuse `tools/browser/tests/fixtures.js`. It launches the actual package entry point on a free
loopback port with a test-output runtime, `STOCK_PROBS_PROVIDER=fixture`, and a fixed fixture clock.
Wait on `/api/v1/readiness`, retain bounded stderr for diagnosis, and stop the child with bounded
SIGTERM then SIGKILL fallback. Tests that restart the app intentionally retain only their isolated
runtime between launches.

## Exact diagnostics

The shared diagnostic fixture records console errors, uncaught page errors, HTTP responses at 400
or above, and failed requests. Declare deliberate HTTP failures and aborts before triggering them.
At teardown, compare expected and actual events exactly; do not use a broad allowlist. A deliberate
HTTP failure's Chromium resource error must pair with that response, while every other console or
page error fails the test.

Record browser `fetch` and XHR URLs and require every application-data path to start with
`/api/v1`. News simulation uses Playwright route fulfillment for the local endpoint; the browser
must never call Yahoo or open SQLite directly.

## Determinism

- Seed state through local API requests or the shared fixture provider, not implementation globals.
- Use stable fixture symbols, timestamps, IDs, and HTTPS example article URLs.
- Await a specific response, locator state, or `expect.poll`; avoid timing-only success criteria.
- A short delay is acceptable only to force a known race or allow Chromium to deliver a paired
  diagnostic event, never to hide readiness or product synchronization defects.
