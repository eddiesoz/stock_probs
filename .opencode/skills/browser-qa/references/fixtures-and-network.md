# Browser fixtures and network containment

`tools/browser/playwright.config.js` starts the main test server through
`scripts/run-browser-app.sh`; restart and failure scenarios use `tools/browser/tests/fixtures.js` to
launch the Python CLI on separate free loopback ports. Both use isolated runtimes,
`STOCK_PROBS_PROVIDER=fixture`, and the fixed fixture clock. The restart fixtures wait on
`/api/v1/readiness`, retain the last 16 KiB of stderr, and use a five-second SIGTERM wait followed by
SIGKILL. A restart intentionally preserves only that fixture's runtime between starts.

Run `make browser-install` when the locked Chromium and operating-system dependencies are absent;
then use `make browser-test`. The latter runs Node setup and `npm ci`, allocates a loopback port, and
lets Playwright launch the fixture server. Node's exact version comes from `scripts/install-node.sh`;
direct npm versions come from `tools/browser/package.json`, while `package-lock.json` is the resolved
dependency authority.

## Exact diagnostics

The automatic diagnostic fixture records console errors, uncaught page errors, HTTP responses at
400 or above, and failed requests for the Playwright page. Declare deliberate HTTP failures and
aborts before triggering them. At teardown, the fixture compares those expected and actual arrays
exactly. Each expected HTTP response also requires its matching Chromium resource-console error;
other console and page errors fail the test.

`applicationRequests` records only browser `fetch` and XHR URLs; it does not inventory navigation,
stylesheet, script, image, or font requests. For data-boundary assertions, require both the local
application origin and a pathname beginning `/api/v1`. News simulation fulfills that local endpoint.
The walkthrough harness separately routes every resource and enforces its declared same-origin path
list; use that stronger artifact for all-request accounting. Neither mechanism instruments browser
filesystem access, so assert observable HTTP behavior rather than claiming it does.

## Determinism

- Seed state through local API requests or the shared fixture provider, not implementation globals.
- Use stable fixture symbols, timestamps, IDs, and HTTPS example article URLs.
- Await a specific response, locator state, or `expect.poll`; avoid timing-only success criteria.
- A short delay is acceptable only to force a known race or allow Chromium to deliver a paired
  diagnostic event, never to hide readiness or product synchronization defects.

## MCP and walkthrough boundaries

`make mcp-smoke` reads the command and flags from `opencode.json` and proves initialization, tool
listing, and an isolated Chromium tab context. It does not start the FastAPI app or navigate to it;
application interaction requires a separately running loopback app and its own evidence.
`./scripts/capture-walkthrough.sh` requires `.dev-venv`, the installed locked Playwright module, and
write ownership for its generated and published paths. It is a fixture capture, not an MCP run.
