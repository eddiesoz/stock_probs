/** Strict parser for an OAuth browser callback copied from the registered local listener. */
export type OAuthCallback = { readonly kind: "code"; readonly code: string } | { readonly kind: "denied" }

const MAX_CALLBACK_URL_BYTES = 8_192
const MAX_CODE_LENGTH = 4_096
const CALLBACK_PATH = "/auth/callback"
const CALLBACK_PORTS = new Set(["1455", "1457"])
const CALLBACK_QUERY_KEYS = new Set(["code", "state", "error", "error_description"])

const localRedirect = (value: string): URL => {
  let url: URL
  try {
    url = new URL(value)
  } catch {
    throw new Error("OAuth callback target is invalid")
  }
  if (
    url.protocol !== "http:" ||
    url.hostname !== "localhost" ||
    !CALLBACK_PORTS.has(url.port) ||
    url.pathname !== CALLBACK_PATH ||
    url.username !== "" ||
    url.password !== "" ||
    url.search !== "" ||
    url.hash !== ""
  ) {
    throw new Error("OAuth callback target is not the registered local listener")
  }
  return url
}

/**
 * Validate a pasted callback against the redirect URI and state captured by one native
 * OpenAI browser attempt. The returned value contains only the authorization code, never the
 * callback URL, error text, or state. This function performs no network request.
 */
export function parseOAuthCallbackURL(
  callbackURL: string,
  registeredRedirect: string,
  expectedState: string,
): OAuthCallback {
  if (
    typeof callbackURL !== "string" ||
    callbackURL.length === 0 ||
    callbackURL.length > MAX_CALLBACK_URL_BYTES ||
    new TextEncoder().encode(callbackURL).byteLength > MAX_CALLBACK_URL_BYTES ||
    callbackURL !== callbackURL.trim() ||
    /[\u0000-\u001f\u007f]/.test(callbackURL)
  ) {
    throw new Error("OAuth callback URL is invalid")
  }

  const redirect = localRedirect(registeredRedirect)
  let callback: URL
  try {
    callback = new URL(callbackURL)
  } catch {
    throw new Error("OAuth callback URL is invalid")
  }
  if (
    callback.origin !== redirect.origin ||
    callback.pathname !== redirect.pathname ||
    callback.username !== "" ||
    callback.password !== "" ||
    callback.hash !== ""
  ) {
    throw new Error("OAuth callback URL does not match the registered listener")
  }

  for (const key of callback.searchParams.keys()) {
    if (!CALLBACK_QUERY_KEYS.has(key)) throw new Error("OAuth callback URL has an unsupported field")
  }
  const values = (key: string) => callback.searchParams.getAll(key)
  const state = values("state")
  if (state.length !== 1 || state[0] !== expectedState) {
    throw new Error("OAuth callback state does not match this attempt")
  }

  const code = values("code")
  const error = values("error")
  const description = values("error_description")
  if (description.length > 1 || error.length > 1) throw new Error("OAuth callback URL is ambiguous")
  if (error.length === 1 && code.length === 0 && error[0] !== "") return { kind: "denied" }
  if (
    code.length !== 1 ||
    error.length !== 0 ||
    code[0] === "" ||
    code[0].length > MAX_CODE_LENGTH ||
    description.length !== 0
  ) {
    throw new Error("OAuth callback URL is incomplete")
  }
  return { kind: "code", code: code[0] }
}
