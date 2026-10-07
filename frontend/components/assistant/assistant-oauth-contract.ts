export type NativeOAuthMethod = {
  integration_id: "openai" | "opencode";
  method_id: "chatgpt-browser" | "chatgpt-headless" | "device";
  label: string;
  mode: "device" | "code" | "browser";
  connection_status: string;
  connection_supported: boolean;
  model_access_supported: boolean;
  availability_reason: string | null;
};

export type NativeOAuthAttempt = {
  attempt_id: string;
  integration_id: "openai" | "opencode";
  method_id: "chatgpt-browser" | "chatgpt-headless" | "device";
  status: "pending" | "handoff_ready" | "connected" | "denied" | "expired" | "cancelled";
  mode: "device" | "code" | "browser";
  expires_at: number;
  authorization_url: string | null;
  instructions: string | null;
};

export type NativeOAuthConnection = {
  integration_id: "openai" | "opencode";
  method_id: "chatgpt-browser" | "chatgpt-headless" | "device";
  status: "connected";
  model_access_supported: boolean;
  availability_reason: string | null;
};

type OAuthMethodPair = `${NativeOAuthMethod["integration_id"]}/${NativeOAuthMethod["method_id"]}`;
const knownMethods = new Set<OAuthMethodPair>([
  "openai/chatgpt-browser",
  "openai/chatgpt-headless",
  "opencode/device",
]);
const attemptIdPattern = /^[0-9a-f]{32}$/;
const identifierPattern = /^[a-z][a-z0-9-]{0,63}$/;

function isKnownPair(integration: unknown, method: unknown): integration is string {
  return typeof integration === "string" && typeof method === "string"
    && knownMethods.has(`${integration}/${method}` as OAuthMethodPair);
}

function modelAccessIsReviewed(
  integration: unknown,
  method: unknown,
  supported: unknown,
  reason: unknown,
): supported is boolean {
  if (integration === "openai" && (method === "chatgpt-browser" || method === "chatgpt-headless")) {
    return supported === true && reason === null;
  }
  return integration === "opencode" && method === "device"
    && supported === false && reason === "oauth_proxy_pending";
}

function modeIsReviewed(integration: unknown, method: unknown, mode: unknown): boolean {
  if (integration === "openai" && method === "chatgpt-browser") return mode === "browser";
  return (integration === "openai" && method === "chatgpt-headless"
    || integration === "opencode" && method === "device") && mode === "device";
}

function cleanText(value: unknown, maximum: number): value is string {
  return typeof value === "string" && value.length > 0 && value.length <= maximum
    && !/[\u0000-\u001f\u007f-\u009f]/.test(value);
}

function hasExactKeys(value: Record<string, unknown>, keys: readonly string[]): boolean {
  const actual = Object.keys(value).sort();
  return actual.length === keys.length && actual.every((key, index) => key === [...keys].sort()[index]);
}

export function readNativeOAuthMethods(payload: unknown): NativeOAuthMethod[] {
  if (!payload || typeof payload !== "object" || !Array.isArray((payload as { methods?: unknown }).methods)) return [];
  return ((payload as { methods: unknown[] }).methods).flatMap((row) => {
    if (!row || typeof row !== "object") return [];
    const item = row as Record<string, unknown>;
    if (!hasExactKeys(item, ["integration_id", "method_id", "label", "mode", "connection_status", "connection_supported", "model_access_supported", "availability_reason"])
      || !isKnownPair(item.integration_id, item.method_id)
      || !cleanText(item.label, 128)
      || !modeIsReviewed(item.integration_id, item.method_id, item.mode)
      || !cleanText(item.connection_status, 64)
      || item.connection_supported !== true
      || !modelAccessIsReviewed(
        item.integration_id,
        item.method_id,
        item.model_access_supported,
        item.availability_reason,
      )) return [];
    return [{
      integration_id: item.integration_id as NativeOAuthMethod["integration_id"],
      method_id: item.method_id as NativeOAuthMethod["method_id"],
      label: item.label,
      mode: item.mode as NativeOAuthMethod["mode"],
      connection_status: item.connection_status,
      connection_supported: true,
      model_access_supported: item.model_access_supported,
      availability_reason: item.availability_reason as string | null,
    }];
  });
}

export function readNativeOAuthAttempts(payload: unknown): NativeOAuthAttempt[] {
  if (!payload || typeof payload !== "object" || !Array.isArray((payload as { attempts?: unknown }).attempts)) return [];
  const now = Date.now() / 1000;
  return ((payload as { attempts: unknown[] }).attempts).flatMap((row) => {
    if (!row || typeof row !== "object") return [];
    const item = row as Record<string, unknown>;
    if (!hasExactKeys(item, ["attempt_id", "integration_id", "method_id", "status", "mode", "expires_at", "authorization_url", "instructions"])
      || !attemptIdPattern.test(String(item.attempt_id ?? ""))
      || !isKnownPair(item.integration_id, item.method_id)
      || !["pending", "handoff_ready", "connected", "denied", "expired", "cancelled"].includes(String(item.status))
      || !["device", "code", "browser"].includes(String(item.mode))
      || typeof item.expires_at !== "number" || !Number.isFinite(item.expires_at)
      || item.expires_at < now - 600 || item.expires_at > now + 600
      || !(item.authorization_url === null || safeNativeOAuthAuthorizationUrl(item.integration_id, item.method_id, item.authorization_url))
      || !(item.instructions === null || cleanText(item.instructions, 2048))) return [];
    return [{
      attempt_id: item.attempt_id as string,
      integration_id: item.integration_id as NativeOAuthAttempt["integration_id"],
      method_id: item.method_id as NativeOAuthAttempt["method_id"],
      status: item.status as NativeOAuthAttempt["status"],
      mode: item.mode as NativeOAuthAttempt["mode"],
      expires_at: item.expires_at,
      authorization_url: item.authorization_url as string | null,
      instructions: item.instructions as string | null,
    }];
  }).slice(0, 32);
}

export function readNativeOAuthConnections(payload: unknown): NativeOAuthConnection[] {
  if (!payload || typeof payload !== "object" || !Array.isArray((payload as { connections?: unknown }).connections)) return [];
  return ((payload as { connections: unknown[] }).connections).flatMap((row) => {
    if (!row || typeof row !== "object") return [];
    const item = row as Record<string, unknown>;
    if (!hasExactKeys(item, ["integration_id", "method_id", "status", "model_access_supported", "availability_reason"])
      || !isKnownPair(item.integration_id, item.method_id)
      || item.status !== "connected"
      || !modelAccessIsReviewed(
        item.integration_id,
        item.method_id,
        item.model_access_supported,
        item.availability_reason,
      )) return [];
    return [{
      integration_id: item.integration_id as NativeOAuthConnection["integration_id"],
      method_id: item.method_id as NativeOAuthConnection["method_id"],
      status: "connected" as const,
      model_access_supported: item.model_access_supported as boolean,
      availability_reason: item.availability_reason as string | null,
    }];
  }).slice(0, 16);
}

export function safeNativeOAuthAuthorizationUrl(
  integration: unknown,
  method: unknown,
  raw: unknown,
): raw is string {
  if (!isKnownPair(integration, method) || !cleanText(raw, 4096) || raw.includes("\\")) return false;
  try {
    const url = new URL(raw);
    if (url.protocol !== "https:" || url.username || url.password || url.hash || (url.port && url.port !== "443")) return false;
    const query = [...url.searchParams.entries()];
    const params = new Map<string, string>();
    for (const [key, value] of query) {
      if (params.has(key)) return false;
      params.set(key, value);
    }
    if (integration === "openai" && method === "chatgpt-headless") {
      return url.hostname === "auth.openai.com" && url.pathname === "/codex/device" && query.length === 0;
    }
    if (integration === "opencode" && method === "device") {
      return url.hostname === "opencode.ai" && url.pathname === "/console/device"
        && query.length === 2 && params.size === 2
        && params.get("client_id") === "opencode-cli"
        && /^[A-Za-z0-9-]{1,256}$/.test(params.get("user_code") ?? "");
    }
    const fixed: Record<string, string> = {
      response_type: "code",
      client_id: "app_EMoamEEZ73f0CkXaXp7hrann",
      redirect_uri: "http://localhost:1455/auth/callback",
      scope: "openid profile email offline_access",
      code_challenge_method: "S256",
      id_token_add_organizations: "true",
      codex_cli_simplified_flow: "true",
      originator: "opencode",
    };
    return integration === "openai" && method === "chatgpt-browser"
      && url.hostname === "auth.openai.com" && url.pathname === "/oauth/authorize"
      && query.length === 10 && params.size === 10
      && Object.entries(fixed).every(([key, value]) => params.get(key) === value)
      && /^[A-Za-z0-9_-]{43}$/.test(params.get("code_challenge") ?? "")
      && /^[A-Za-z0-9_-]{43}$/.test(params.get("state") ?? "");
  } catch {
    return false;
  }
}

export function safePastedOAuthCallback(raw: string): boolean {
  if (!cleanText(raw, 4096)) return false;
  try {
    const url = new URL(raw);
    const query = [...url.searchParams.entries()];
    const params = new Map<string, string>();
    for (const [key, value] of query) {
      if (params.has(key)) return false;
      params.set(key, value);
    }
    return url.protocol === "http:" && url.hostname === "localhost" && url.port === "1455"
      && !url.username && !url.password && url.pathname === "/auth/callback" && !url.hash
      && query.length === 2 && params.size === 2
      && /^[A-Za-z0-9_-]{1,2048}$/.test(params.get("code") ?? "")
      && /^[A-Za-z0-9_-]{43}$/.test(params.get("state") ?? "");
  } catch {
    return false;
  }
}

export function nativeOAuthAvailabilityText(reason: string | null): string {
  if (reason === "oauth_proxy_pending") return "Secure login can be stored, but this account cannot yet be used for model requests.";
  if (reason === null) return "This reviewed connection can be used by its approved models after user consent.";
  return "Model access is unavailable until the provider connection is reviewed.";
}
