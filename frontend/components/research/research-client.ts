// Reuse the workspace authentication and CSRF boundary for every research request.
import { apiFetch } from "../auth-client";

export async function researchRequest<T>(path: string, options: RequestInit = {}): Promise<T> {
  const response = await apiFetch(path, { cache: "no-store", ...options });
  const data = await response.json().catch(() => null);
  if (!response.ok) throw new Error(typeof data?.error?.message === "string" ? data.error.message : `Research request failed (${response.status}).`);
  if (data === null || typeof data !== "object") throw new Error("The research response is unavailable.");
  return data as T;
}

export type ResearchPage<T> = { items: T[]; page: number; page_size: number; total: number; has_next: boolean };
