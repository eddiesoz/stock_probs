import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const root = new URL("../", import.meta.url);

async function source(path) {
  return readFile(new URL(path, root), "utf8");
}

test("authentication surfaces use same-origin API paths and keep credentials out of storage", async () => {
  const files = await Promise.all([
    source("app/sign-in/page.tsx"),
    source("app/invite/page.tsx"),
    source("app/passkey/page.tsx"),
    source("app/authenticator/page.tsx"),
    source("app/account/page.tsx"),
    source("app/admin/page.tsx"),
    source("components/auth-client.ts"),
  ]);
  const joined = files.join("\n");
  for (const call of joined.matchAll(/(?:fetch|authRequest)\((?:`|\")([^`\"]+)/g)) {
    assert.match(call[1], /^\/api\/v1\//, `unexpected external API path ${call[1]}`);
  }
  assert.doesNotMatch(joined, /localStorage|sessionStorage|document\.cookie/);
  assert.match(joined, /credentials:\s*"include"/);
  assert.match(joined, /X-CSRF-Token/);
  assert.match(joined, /HttpOnly cookie/);
});

test("auth routes cover invited sign-in, authenticator setup, retired passkey links, account, and admin controls", async () => {
  const [signIn, invite, passkey, authenticator, account, admin] = await Promise.all([
    source("app/sign-in/page.tsx"),
    source("app/invite/page.tsx"),
    source("app/passkey/page.tsx"),
    source("app/authenticator/page.tsx"),
    source("app/account/page.tsx"),
    source("app/admin/page.tsx"),
  ]);
  assert.match(signIn, /github\/start/);
  assert.match(signIn, /Checking sign-in options/);
  assert.match(signIn, /const GITHUB_START_PATH = "\/api\/v1\/auth\/github\/start";/);
  assert.match(signIn, /href=\{GITHUB_START_PATH\} data-testid="github-sign-in"/);
  assert.doesNotMatch(signIn, /startGithub|onClick=\{startGithub\}|window\.location\.assign\(GITHUB_START_PATH\)|GITHUB_NAVIGATION_TIMEOUT_MS/);
  assert.match(signIn, /Sign-in options could not load/);
  assert.match(signIn, /local\/login/);
  assert.match(signIn, /Complete authenticator setup or verification/);
  assert.match(signIn, /authenticatorPath/);
  assert.match(invite, /invites\/redeem/);
  assert.match(passkey, /Passkeys have been retired/);
  assert.match(passkey, /authenticator\?mode=enroll/);
  assert.doesNotMatch(passkey, /runPasskeyCeremony|Verify legacy passkey/);
  assert.doesNotMatch(account, /Verify legacy passkey|\/passkey\?mode/);
  assert.match(authenticator, /auth\/totp\/enroll\/start/);
  assert.match(authenticator, /auth\/totp\/enroll\/finish/);
  assert.match(authenticator, /auth\/totp\/verify/);
  assert.match(authenticator, /auth\/totp\/step-up/);
  assert.match(authenticator, /auth\/totp\/recover/);
  assert.match(authenticator, /Manual setup key/);
  assert.match(authenticator, /otpauth_uri/);
  assert.match(authenticator, /recovery codes/i);
  assert.match(authenticator, /QRCode\.toDataURL\(enrollment\.otpauth_uri/);
  assert.match(authenticator, /Which authenticator do you want to use/);
  assert.match(authenticator, /Apple Passwords/);
  assert.match(authenticator, /Google Authenticator/);
  assert.match(authenticator, /1Password/);
  assert.match(authenticator, /navigator\.clipboard\.writeText\(enrollment\.secret\)/);
  assert.match(authenticator, /Try device’s default otpauth handler/);
  assert.match(authenticator, /iOS chooses which app opens an otpauth link/);
  assert.doesNotMatch(authenticator, /Open in authenticator app/);
  assert.doesNotMatch(authenticator, /api\.qrserver|chart\.googleapis|external QR/i);
  assert.match(account, /auth\/sessions/);
  assert.match(account, /auth\/totp\/status/);
  assert.match(account, /Authenticator protected/);
  assert.match(account, /totpStatus\?\.enrolled/);
  assert.match(account, /Set up authenticator/);
  assert.match(account, /Revoke/);
  assert.match(admin, /auth\/invites/);
  assert.match(admin, /operations\/backups/);
  assert.match(admin, /operations\/restores/);
  assert.match(admin, /auth\/totp\/step-up/);
  assert.match(admin, /Fresh authenticator verification complete/);
  assert.doesNotMatch(admin, /runPasskeyCeremony/);
  assert.match(admin, /disabled={!freshVerified/);
});

test("workspace navigation exposes account controls without replacing the primary landmarks", async () => {
  const navigation = await source("components/workspace-nav.tsx");
  const controls = await source("components/auth-controls.tsx");
  assert.match(navigation, /<AuthControls \/>/);
  assert.match(controls, /href="\/sign-in"/);
  assert.match(controls, /href="\/account"/);
  assert.match(controls, /href="\/admin"/);
  assert.match(controls, /auth\/logout/);
  assert.match(controls, /role="group" aria-label="Account controls"/);
});

test("auth routes expose a real document title and preserve invitation errors", async () => {
  const [layout, shell, client, account, admin] = await Promise.all([
    source("app/layout.tsx"),
    source("components/auth-shell.tsx"),
    source("components/auth-client.ts"),
    source("app/account/page.tsx"),
    source("app/admin/page.tsx"),
  ]);
  assert.match(layout, /<title>Signal Ledger<\/title>/);
  assert.match(shell, /document\.title = `\$\{title\} \| Signal Ledger`/);
  assert.doesNotMatch(shell, /<title>/);
  assert.match(account, /document\.title = "Account \| Signal Ledger"/);
  assert.match(admin, /document\.title = "Administration \| Signal Ledger"/);
  assert.doesNotMatch(account, /<title>/);
  assert.doesNotMatch(admin, /<title>/);
  assert.match(client, /error\.code === "invitation_rejected"/);
  assert.match(client, /invalid, expired, revoked, or already used/);
});

test("invitation rejection keeps its precise recovery message", async () => {
  const { AuthRequestError, authErrorMessage } = await import("../components/auth-client.ts");
  const invitation = new AuthRequestError("The invitation is invalid or has expired.", 403, "invitation_rejected");
  const session = new AuthRequestError("Authentication required.", 401, "authentication_required");
  const rejectedTotp = new AuthRequestError("The authenticator code was not accepted.", 403, "totp_rejected");
  assert.equal(authErrorMessage(invitation), "The invitation is invalid or has expired.");
  assert.equal(authErrorMessage(session), "Your session has ended. Sign in again to continue.");
  assert.equal(authErrorMessage(rejectedTotp), "That authenticator code was not accepted. Wait for the next code and try again.");
});

test("auth redirects stay on the configured origin", async () => {
  const previousWindow = globalThis.window;
  globalThis.window = { location: { origin: "https://ledger.jtmb.cc" } };
  try {
    const { safeLocalNext } = await import("../components/auth-client.ts");
    assert.equal(safeLocalNext("/overview?symbol=ACDC"), "/overview?symbol=ACDC");
    assert.equal(safeLocalNext("//example.com"), "/overview");
    assert.equal(safeLocalNext("/\\example.com"), "/overview");
    assert.equal(safeLocalNext("https://example.com"), "/overview");
  } finally {
    globalThis.window = previousWindow;
  }
});

test("shared API mutations obtain a session CSRF token without breaking auth-disabled mode", async () => {
  const { apiFetch } = await import("../components/auth-client.ts");
  const previousFetch = globalThis.fetch;
  const calls = [];
  let sessionCalls = 0;
  globalThis.fetch = async (input, init = {}) => {
    const url = String(input);
    calls.push({ url, headers: new Headers(init.headers) });
    if (url === "/api/v1/auth/session") {
      sessionCalls += 1;
      const body = sessionCalls === 1
        ? { authenticated: false, requires_totp: false }
        : { authenticated: true, csrf_token: "csrf-test-token" };
      return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
    }
    return new Response(JSON.stringify({ items: [] }), { status: 200, headers: { "Content-Type": "application/json" } });
  };
  try {
    await apiFetch("/api/v1/lists", { method: "POST", body: "{}" });
    assert.equal(calls[1].headers.get("X-CSRF-Token"), null);

    await apiFetch("/api/v1/lists", { method: "POST", body: "{}" });
    assert.equal(calls[3].headers.get("X-CSRF-Token"), "csrf-test-token");
    await apiFetch("/api/v1/lists", { method: "DELETE" });
    assert.equal(calls[4].headers.get("X-CSRF-Token"), "csrf-test-token");
    assert.equal(sessionCalls, 2);
  } finally {
    globalThis.fetch = previousFetch;
  }
});

test("portfolio, market, and forecast mutations use the CSRF-aware API helper", async () => {
  const files = await Promise.all([
    source("app/overview/portfolio-workspace.tsx"),
    source("app/tools/live-trading/workspace.tsx"),
    source("app/tools/markets/workspace.tsx"),
    source("app/tools/forecast/workspace.tsx"),
  ]);
  for (const file of files) {
    assert.match(file, /apiFetch/);
    assert.doesNotMatch(file, /fetch\([\s\S]{0,260}?method:\s*["'](?:POST|DELETE|PUT|PATCH)["']/);
  }
});
