"use client";

export type AuthRole = "admin" | "member";

export interface AuthUser {
  id: number | string;
  login?: string;
  name?: string;
  email?: string;
  avatar_url?: string;
  role: AuthRole;
  username?: string;
  passkey_registered?: boolean;
  passkey_enrolled?: boolean;
  passkey_required?: boolean;
}

export interface AuthSession {
  authenticated: boolean;
  user?: AuthUser | null;
  role?: AuthRole | null;
  local_login_enabled?: boolean;
  passkey_required?: boolean;
  requires_passkey?: boolean;
  csrf_token?: string;
  message?: string;
}

export interface SessionRecord {
  id: string;
  created_at?: string;
  last_seen_at?: string;
  expires_at?: string;
  current?: boolean;
  user_agent?: string;
}

export class AuthRequestError extends Error {
  status: number;
  code: string;
  details?: unknown;

  constructor(message: string, status: number, code = "request_failed", details?: unknown) {
    super(message);
    this.name = "AuthRequestError";
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

let csrfToken: string | undefined;
let csrfRequest: Promise<string | undefined> | undefined;

const CSRF_METHODS = new Set(["POST", "PUT", "PATCH", "DELETE"]);

function apiPath(path: string): string {
  if (!path.startsWith("/api/v1/")) throw new Error("Auth requests must use the local API.");
  return path;
}

async function readBody(response: Response): Promise<Record<string, unknown>> {
  try {
    const body = await response.json();
    return body && typeof body === "object" ? body as Record<string, unknown> : {};
  } catch {
    return {};
  }
}

function errorFromBody(body: Record<string, unknown>, response: Response): AuthRequestError {
  const error = body.error && typeof body.error === "object" ? body.error as Record<string, unknown> : null;
  const message = typeof error?.message === "string"
    ? error.message
    : typeof body.detail === "string"
      ? body.detail
      : "The local service could not complete that request.";
  const code = typeof error?.code === "string" ? error.code : "request_failed";
  return new AuthRequestError(message, response.status, code, error?.details);
}

async function ensureCsrfToken(): Promise<string | undefined> {
  if (csrfToken) return csrfToken;
  if (!csrfRequest) {
    csrfRequest = (async () => {
      try {
        const response = await fetch(apiPath("/api/v1/auth/session"), {
          cache: "no-store",
          headers: { Accept: "application/json" },
          credentials: "include",
        });
        const body = await readBody(response);
        if (typeof body.csrf_token === "string") csrfToken = body.csrf_token;
        return csrfToken;
      } catch {
        // Auth-disabled deployments still allow the original request to proceed; the
        // response from that request remains the source of truth for availability.
        return undefined;
      }
    })().finally(() => {
      csrfRequest = undefined;
    });
  }
  return csrfRequest;
}

export async function apiFetch(path: string, options: RequestInit = {}): Promise<Response> {
  const headers = new Headers(options.headers);
  headers.set("Accept", "application/json");
  if (options.body !== undefined && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
  const method = (options.method ?? "GET").toUpperCase();
  if (CSRF_METHODS.has(method) && !headers.has("X-CSRF-Token")) {
    const token = await ensureCsrfToken();
    if (token) headers.set("X-CSRF-Token", token);
  }
  return fetch(apiPath(path), { ...options, headers, credentials: "include" });
}

export async function authRequest<T = Record<string, unknown>>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const response = await apiFetch(path, options);
  const body = await readBody(response);
  if (!response.ok) {
    if (response.status === 401 || response.status === 403) csrfToken = undefined;
    throw errorFromBody(body, response);
  }
  if (typeof body.csrf_token === "string") csrfToken = body.csrf_token;
  if (path === "/api/v1/auth/logout") csrfToken = undefined;
  return body as T;
}

export async function getAuthSession(): Promise<AuthSession | null> {
  try {
    const body = await authRequest<AuthSession>("/api/v1/auth/session", { cache: "no-store" });
    if (typeof body.csrf_token === "string") csrfToken = body.csrf_token;
    return body;
  } catch (error) {
    if (error instanceof AuthRequestError && [401, 403, 404].includes(error.status)) return null;
    throw error;
  }
}

export function authErrorMessage(error: unknown): string {
  if (error instanceof AuthRequestError) {
    if (error.code === "invitation_rejected") {
      return error.message || "That invitation is invalid, expired, revoked, or already used. Ask the administrator for a new invitation.";
    }
    if (error.status === 401) return "Your session has ended. Sign in again to continue.";
    if (error.status === 403) return "Your account is not allowed to perform that action.";
    if (error.status === 409) return "That request conflicts with the current account state.";
    return error.message;
  }
  return "The local service is unavailable. Try again in a moment.";
}

export function formatAuthDate(value?: string): string {
  if (!value) return "Not recorded";
  const date = new Date(value);
  if (Number.isNaN(date.valueOf())) return "Not recorded";
  return new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(date);
}

export function safeLocalNext(value: string | null, fallback = "/overview"): string {
  if (!value || !value.startsWith("/") || value.startsWith("//") || value.includes("\\")) return fallback;
  try {
    const target = new URL(value, window.location.origin);
    return target.origin === window.location.origin
      ? `${target.pathname}${target.search}${target.hash}`
      : fallback;
  } catch {
    return fallback;
  }
}

function decodeBase64Url(value: string): ArrayBuffer {
  const padded = value.replace(/-/g, "+").replace(/_/g, "/") + "=".repeat((4 - value.length % 4) % 4);
  const binary = window.atob(padded);
  const bytes = Uint8Array.from(binary, (character) => character.charCodeAt(0));
  return bytes.buffer;
}

function encodeBase64Url(value: ArrayBuffer | ArrayBufferView): string {
  const bytes = value instanceof ArrayBuffer ? new Uint8Array(value) : new Uint8Array(value.buffer, value.byteOffset, value.byteLength);
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return window.btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/g, "");
}

export function publicKeyValue(value: unknown, keyPath = ""): unknown {
  if (Array.isArray(value)) return value.map((item, index) => publicKeyValue(item, `${keyPath}.${index}`));
  if (!value || typeof value !== "object") return value;
  const result: Record<string, unknown> = {};
  for (const [key, item] of Object.entries(value as Record<string, unknown>)) {
    const path = keyPath ? `${keyPath}.${key}` : key;
    // WebAuthn descriptor and user IDs are bytes; rp.id is a hostname and must stay text.
    const binaryField = path === "challenge" || path === "user.id"
      || (key === "id" && /^(allowCredentials|excludeCredentials)\.\d+\.id$/.test(path));
    result[key] = typeof item === "string" && binaryField
      ? decodeBase64Url(item)
      : publicKeyValue(item, path);
  }
  return result;
}

function credentialPayload(credential: PublicKeyCredential): Record<string, unknown> {
  const response = credential.response;
  const payload: Record<string, unknown> = {
    id: credential.id,
    raw_id: encodeBase64Url(credential.rawId),
    type: credential.type,
  };
  if ("attestationObject" in response) {
    const attestation = response as AuthenticatorAttestationResponse;
    payload.response = {
      clientDataJSON: encodeBase64Url(attestation.clientDataJSON),
      attestationObject: encodeBase64Url(attestation.attestationObject),
      transports: attestation.getTransports?.() ?? [],
    };
  } else if ("authenticatorData" in response) {
    const assertion = response as AuthenticatorAssertionResponse;
    payload.response = {
      clientDataJSON: encodeBase64Url(assertion.clientDataJSON),
      authenticatorData: encodeBase64Url(assertion.authenticatorData),
      signature: encodeBase64Url(assertion.signature),
      userHandle: assertion.userHandle ? encodeBase64Url(assertion.userHandle) : null,
    };
  }
  return payload;
}

export async function runPasskeyCeremony(
  path: string,
  completionPath: string,
  kind: "create" | "get",
): Promise<Record<string, unknown>> {
  if (!window.PublicKeyCredential || !navigator.credentials) {
    throw new AuthRequestError("This browser does not support passkeys. Use a modern browser or contact an administrator.", 422, "passkey_unsupported");
  }
  const options = await authRequest<{ public_key: Record<string, unknown>; options?: Record<string, unknown> }>(path, { method: "POST", body: "{}" });
  const publicKey = publicKeyValue(options.public_key ?? options.options ?? options);
  const credential = kind === "create"
    ? await navigator.credentials.create({ publicKey: publicKey as PublicKeyCredentialCreationOptions })
    : await navigator.credentials.get({ publicKey: publicKey as PublicKeyCredentialRequestOptions });
  if (!credential || !(credential instanceof PublicKeyCredential)) throw new AuthRequestError("The passkey ceremony was cancelled.", 499, "passkey_cancelled");
  return authRequest<Record<string, unknown>>(completionPath, { method: "POST", body: JSON.stringify(credentialPayload(credential)) });
}
