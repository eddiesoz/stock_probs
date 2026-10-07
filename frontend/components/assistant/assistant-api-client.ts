import { AuthRequestError, authRequest } from "../auth-client";
import { assistantApiPath, assistantErrorMessage, AssistantClientError } from "./assistant-contract";

export async function assistantRequest<T>(path: string, options: RequestInit = {}): Promise<T> {
  try {
    return await authRequest<T>(assistantApiPath(path), { cache: "no-store", ...options });
  } catch (error) {
    if (error instanceof AuthRequestError) {
      throw new AssistantClientError(assistantErrorMessage(error.status, error.code), error.status, error.code);
    }
    throw error;
  }
}

// The event stream carries the signed-in cookie, so keep it same-origin and uncached.
export async function assistantStreamFetch(path: string, signal: AbortSignal, after?: number): Promise<Response> {
  const safePath = assistantApiPath(path);
  const url = new URL(safePath, window.location.origin);
  if (url.origin !== window.location.origin) throw new TypeError("Assistant streams must stay on this application origin.");
  if (after !== undefined && Number.isSafeInteger(after) && after >= 0) url.searchParams.set("after", String(after));
  const response = await fetch(`${url.pathname}${url.search}`, {
    method: "GET",
    credentials: "include",
    headers: { Accept: "text/event-stream", "Cache-Control": "no-cache" },
    cache: "no-store",
    signal,
  });
  if (!response.ok) {
    const body = await response.json().catch(() => null) as { error?: { code?: string } } | null;
    const code = typeof body?.error?.code === "string" ? body.error.code : "request_failed";
    throw new AssistantClientError(assistantErrorMessage(response.status, code), response.status, code);
  }
  return response;
}
