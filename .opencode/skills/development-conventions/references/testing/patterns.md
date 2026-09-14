---
title: "Useful Tests — Patterns That Actually Catch Bugs"
impact: HIGH
impactDescription: "Ensures tests catch regressions rather than being noise"
tags: [testing, unit, integration, e2e, playwright, pytest]
---

## Useful Tests — Patterns That Actually Catch Bugs

## 🔴 HARD RULE — Every Code Change Must Have Tests

You MUST write or update tests in the same turn as code changes. This is not optional.

| Code change | Tests required |
|-------------|---------------|
| New function / class / module | At least one unit test covering happy path + one error path |
| Bug fix | A regression test that fails without the fix and passes with it |
| New API endpoint | Integration test for 200 + 4xx + 5xx |
| Refactored logic | Update existing tests; add new ones if behavior changed |

### The Test Pyramid

```
      ╱  E2E  ╲          Critical user flows against live app
     ╱──────────╲         Few tests.
    ╱ Integration ╲       API endpoints, DB queries, service boundaries
   ╱───────────────╲     Medium coverage.
  ╱   Unit Tests    ╲    Domain logic, pure functions, edge cases
 ╱───────────────────╲   Many tests. Fast. No I/O.
```

| Layer | Tool | Speed | Count |
|-------|------|-------|-------|
| **Unit** | Framework-native (Jest, pytest, go test) | <1ms each | Many |
| **Integration** | Framework-native + testcontainers | ~10ms each | Medium |
| **E2E** | Playwright test runner | ~500ms each | Few |

### Launching the App for E2E Tests

E2E tests require a real running application. Use the lifecycle pattern: launch → wait → test → teardown.

```bash
# scripts/run-e2e.sh pattern
trap cleanup EXIT INT TERM
npm run dev &
APP_PID=$!
for i in $(seq 1 30); do
    if curl -sf "http://localhost:$APP_PORT/health" >/dev/null 2>&1; then
        break
    fi
    sleep 1
done
npx playwright test --config=tests/playwright.config.ts --reporter=list
```

### Playwright E2E — Selectors

Use `data-testid` attributes, not CSS classes or DOM structure:
```typescript
// ❌ BAD — brittle, breaks on any UI change
await page.click('.btn-primary');

// ✅ GOOD — stable, semantic, survives refactors
await page.click('[data-testid="submit-order"]');
```

### What Makes a Test Useful

| Signal | Useless Test | Useful Test |
|--------|-------------|-------------|
| Tests behavior, not implementation | Asserts `setState` was called | Asserts the modal is visible |
| Can fail | Always passes | Fails when behavior breaks |
| Realistic data | `name: "test"` | `name: "Jane Smith"` |

### Anti-Patterns — AI-Generated Tests That Are Always Broken

| Pattern | Why | Fix |
|---------|-----|-----|
| No assertion | Agent wrote skeleton, never filled it in | Every test must have at least one `expect`/`assert` |
| `expect(true).toBe(true)` | Agent didn't know what to assert | Delete it |
| Over-mocking including function under test | Agent over-mocked to make it pass | Mock only I/O boundaries |
| `waitForTimeout(5000)` everywhere | Agent didn't know what to wait for | Replace with `waitForSelector` or `toBeVisible()` |
| Test depends on previous test's state | Agent wrote sequential tests sharing state | Each test is isolated. Reset in `beforeEach`. |
| E2E test that doesn't start the server | Agent ran tests without launching app | Use lifecycle script |
