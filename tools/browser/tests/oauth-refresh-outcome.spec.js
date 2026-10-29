const { test, expect } = require("./fixtures");

test("a stored OAuth connection remains reported as saved when refresh fails", async ({ page, browserDiagnostics }) => {
  const id = "a".repeat(32);
  const attempt = {
    attempt_id: id, integration_id: "openai", method_id: "chatgpt-browser",
    status: "handoff_ready", mode: "browser", expires_at: Date.now() / 1000 + 300,
    authorization_url: null, instructions: null,
  };
  let saved = false;
  let failedRefresh = false;
  browserDiagnostics.expectHttpFailures({ method: "GET", path: "/api/v1/assistant/providers/oauth/methods", status: 503 });
  await page.route("**/api/v1/**", async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    let status = 200;
    let value = {};
    if (path === "/api/v1/auth/session") value = { authenticated: true, user: { id: 7, role: "admin", login: "fixture-admin" }, csrf_token: "fixture-csrf" };
    else if (path === "/api/v1/auth/totp/status") value = { enrolled: true, recovery_codes_remaining: 8 };
    else if (path === "/api/v1/auth/totp/step-up") value = { verified: true };
    else if (path === "/api/v1/assistant/providers") value = { providers: [] };
    else if (path === "/api/v1/assistant/models") value = { items: [] };
    else if (path === "/api/v1/assistant/providers/oauth/methods") {
      if (saved && !failedRefresh) { failedRefresh = true; status = 503; value = { error: { code: "oauth_unavailable", message: "Temporarily unavailable." } }; }
      else value = { methods: [] };
    } else if (path === "/api/v1/assistant/providers/oauth/attempts") value = { attempts: [{ ...attempt, status: saved ? "connected" : "handoff_ready" }] };
    else if (path === "/api/v1/assistant/providers/oauth/connections") value = { connections: saved ? [{ integration_id: "openai", method_id: "chatgpt-browser", status: "connected", model_access_supported: true, availability_reason: null }] : [] };
    else if (path === `/api/v1/assistant/providers/oauth/attempts/${id}/complete`) { saved = true; value = { attempt: { ...attempt, status: "connected" } }; }
    else if (path === "/api/v1/assistant/providers/opencode/models") value = { models: [], unsupported_model_count: 0 };
    else if (path === "/api/v1/auth/sessions") value = { sessions: [] };
    else if (path === "/api/v1/auth/invites") value = { invitations: [], email_invites_enabled: false };
    else if (path === "/api/v1/operations/backups") value = { items: [] };
    else if (path === "/api/v1/operations/backups/restore/preflight") value = { available: false };
    else if (path === "/api/v1/assistant/status") value = { enabled: false, available: false };
    return route.fulfill({ status, contentType: "application/json", body: JSON.stringify(value) });
  });
  await page.goto("/admin#assistant-providers");
  await page.getByLabel("Current authenticator code").fill("123456");
  await page.getByRole("button", { name: "Verify authenticator" }).click();
  await page.getByRole("button", { name: "Save encrypted connection" }).click();
  await expect(page.getByText("The provider connection was stored encrypted for this account.", { exact: true })).toBeVisible();
  await expect(page.getByText("The connection was stored, but its status could not be refreshed. Use Refresh to check it.", { exact: true })).toBeVisible();
  await expect(page.getByText("The provider handoff could not be stored.", { exact: true })).toHaveCount(0);
  await page.getByRole("region", { name: "Provider settings" }).getByRole("button", { name: "Refresh", exact: true }).click();
  await expect(page.getByText("Encrypted app-side connection", { exact: true })).toBeVisible();
});
