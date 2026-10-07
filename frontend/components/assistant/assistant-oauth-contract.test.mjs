import assert from "node:assert/strict";
import test from "node:test";

import {
  nativeOAuthAvailabilityText,
  readNativeOAuthAttempts,
  readNativeOAuthConnections,
  readNativeOAuthMethods,
  safeNativeOAuthAuthorizationUrl,
  safePastedOAuthCallback,
} from "./assistant-oauth-contract.ts";

const browserUrl = "https://auth.openai.com/oauth/authorize?response_type=code&client_id=app_EMoamEEZ73f0CkXaXp7hrann&redirect_uri=http%3A%2F%2Flocalhost%3A1455%2Fauth%2Fcallback&scope=openid+profile+email+offline_access&code_challenge="
  + "C".repeat(43)
  + "&code_challenge_method=S256&id_token_add_organizations=true&codex_cli_simplified_flow=true&state="
  + "S".repeat(43)
  + "&originator=opencode";

test("native OAuth launch links are exact pinned host, path, and query contracts", () => {
  assert.equal(safeNativeOAuthAuthorizationUrl("openai", "chatgpt-browser", browserUrl), true);
  assert.equal(safeNativeOAuthAuthorizationUrl("openai", "chatgpt-headless", "https://auth.openai.com/codex/device"), true);
  assert.equal(safeNativeOAuthAuthorizationUrl("opencode", "device", "https://opencode.ai/console/device?user_code=AB-123&client_id=opencode-cli"), true);
  assert.equal(safeNativeOAuthAuthorizationUrl("openai", "chatgpt-headless", "https://auth.openai.com.evil/codex/device"), false);
  assert.equal(safeNativeOAuthAuthorizationUrl("opencode", "device", "https://opencode.ai/console/device?user_code=A&user_code=B&client_id=opencode-cli"), false);
  assert.equal(safeNativeOAuthAuthorizationUrl("opencode", "device", "https://opencode.ai/console/device?user_code=A&client_id=opencode-cli&next=https://evil.test"), false);
  assert.equal(safeNativeOAuthAuthorizationUrl("openai", "chatgpt-browser", browserUrl + "&state=second"), false);
});

test("pasted loopback callback is fixed and contains one attempt code and state", () => {
  const callback = `http://localhost:1455/auth/callback?code=sample-code&state=${"S".repeat(43)}`;
  assert.equal(safePastedOAuthCallback(callback), true);
  assert.equal(safePastedOAuthCallback(callback + "&next=https://evil.test"), false);
  assert.equal(safePastedOAuthCallback(callback.replace("localhost", "127.0.0.1")), false);
  assert.equal(safePastedOAuthCallback(callback.replace(":1455", ":1456")), false);
  assert.equal(safePastedOAuthCallback(callback.replace("state=", "state=wrong&state=")), false);
});

test("OAuth DTO readers reject unknown methods, malformed states and secret-like fields", () => {
  const methods = readNativeOAuthMethods({ methods: [
    { integration_id: "openai", method_id: "chatgpt-headless", label: "Headless", mode: "device", connection_status: "ready", connection_supported: true, model_access_supported: true, availability_reason: null },
    { integration_id: "opencode", method_id: "device", label: "OpenCode device", mode: "device", connection_status: "ready", connection_supported: true, model_access_supported: false, availability_reason: "oauth_proxy_pending" },
    { integration_id: "openai", method_id: "chatgpt-headless", label: "Wrong capability", mode: "device", connection_status: "ready", connection_supported: true, model_access_supported: false, availability_reason: "oauth_proxy_pending" },
    { integration_id: "custom", method_id: "arbitrary", label: "Unknown", mode: "device", connection_status: "available", connection_supported: true, model_access_supported: false, availability_reason: null },
  ] });
  assert.equal(methods.length, 2);
  assert.equal(methods[0].method_id, "chatgpt-headless");
  assert.equal(methods[0].model_access_supported, true);
  assert.equal(methods[0].availability_reason, null);
  assert.equal(methods[1].integration_id, "opencode");

  const attempt = {
    attempt_id: "a".repeat(32), integration_id: "openai", method_id: "chatgpt-headless",
    status: "handoff_ready", mode: "device", expires_at: Date.now() / 1000 + 120,
    authorization_url: "https://auth.openai.com/codex/device", instructions: "Enter code: AB-123",
  };
  assert.equal(readNativeOAuthAttempts({ attempts: [attempt] }).length, 1);
  assert.equal(readNativeOAuthAttempts({ attempts: [{ ...attempt, access_token: "must-not-appear" }] }).length, 0);
  assert.equal(readNativeOAuthAttempts({ attempts: [{ ...attempt, authorization_url: "https://evil.test" }] }).length, 0);

  const connection = {
    integration_id: "openai", method_id: "chatgpt-headless", status: "connected",
    model_access_supported: true, availability_reason: null,
  };
  const connections = readNativeOAuthConnections({ connections: [connection] });
  assert.equal(connections.length, 1);
  assert.deepEqual(connections[0], {
    integration_id: "openai", method_id: "chatgpt-headless", status: "connected",
    model_access_supported: true, availability_reason: null,
  });
  assert.equal(readNativeOAuthConnections({ connections: [{ ...connection, access: "not accepted" }] }).length, 0);
  assert.equal(readNativeOAuthConnections({ connections: [{
    integration_id: "opencode", method_id: "device", status: "connected",
    model_access_supported: false, availability_reason: "oauth_proxy_pending",
  }] }).length, 1);
  assert.equal(readNativeOAuthConnections({ connections: [{
    ...connection, model_access_supported: false, availability_reason: "oauth_proxy_pending",
  }] }).length, 0);
});

test("availability copy does not expose internal enums or overstate model access", () => {
  assert.match(nativeOAuthAvailabilityText("oauth_proxy_pending"), /cannot yet be used for model requests/);
  assert.doesNotMatch(nativeOAuthAvailabilityText("oauth_proxy_pending"), /oauth_proxy_pending/);
  assert.match(nativeOAuthAvailabilityText(null), /approved models after user consent/);
});
