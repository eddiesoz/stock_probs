export function record(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" ? value as Record<string, unknown> : {};
}

// Prefer the server's structured error message so provider/staleness reasons survive to the UI.
export function apiMessage(payload: unknown, fallback: string) {
  const error = record(record(payload).error);
  return typeof error.message === "string" ? error.message : fallback;
}

export async function apiPayload(response: Response, fallback: string) {
  const payload: unknown = await response.json().catch(() => null);
  if (!response.ok) throw new Error(apiMessage(payload, fallback));
  return payload;
}

// Missing values render as "Unavailable" rather than 0 or a guessed price.
export function number(value?: number, options?: Intl.NumberFormatOptions) {
  return typeof value === "number" && Number.isFinite(value) ? value.toLocaleString(undefined, options) : "Unavailable";
}

export function quotePrice(value?: { price?: number; last?: number } | null) {
  return value?.price ?? value?.last;
}

// The quotes endpoint accepts a bounded symbol list, so cap the watchlist at 100 and chunk
// each request to at most 20 symbols.
export function quoteBatches(symbols: string[]) {
  const bounded = symbols.slice(0, 100);
  return Array.from({ length: Math.ceil(bounded.length / 20) }, (_, index) => bounded.slice(index * 20, index * 20 + 20));
}

export function time(value?: string) {
  if (!value) return "Unavailable";
  const parsed = new Date(value);
  return Number.isNaN(parsed.valueOf()) ? value : parsed.toLocaleString();
}

// A false provider delay flag is not a real-time guarantee, so the wording never claims one.
export function delay(delayed?: boolean, minutes?: number | null) {
  if (delayed === true) return typeof minutes === "number" ? `Approximately ${minutes} minutes delayed` : "Delayed; duration unavailable";
  if (delayed === false) return "No provider-reported delay; real-time delivery is not guaranteed";
  return "Delay unavailable";
}

// A provider state is useful context, but it is not a freshness guarantee. Keep the
// wording explicit so simulated fixtures and unavailable provenance cannot look live.
export function snapshotState(state?: string, delayed?: boolean) {
  const normalized = state?.trim().toLowerCase();
  if (normalized?.includes("simulat")) return "Simulated snapshot";
  if (normalized?.includes("unavailable")) return "Snapshot provenance unavailable";
  if (normalized?.includes("delay") || delayed === true) return "Delayed snapshot";
  if (normalized?.includes("provider")) return "Provider-reported snapshot";
  if (normalized?.includes("stale")) return "Stale historical snapshot";
  return state ? `${state} snapshot` : "Snapshot provenance unavailable";
}
