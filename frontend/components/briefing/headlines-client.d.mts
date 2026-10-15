import type { BriefingSnapshot } from "./briefing-client.mjs";

export type CurrentNewsItem = Readonly<{
  id: string;
  title: string;
  publisher: string | null;
  published_at: string | null;
  url: string;
  related_symbols: readonly string[] | null;
}>;
export type CurrentNewsResponse = Readonly<{
  query: Readonly<{ symbol: string; limit: number }>;
  provider: string;
  as_of: string;
  cache_state: "miss" | "hit" | "stale_fallback";
  coverage: Readonly<{
    returned_count: number;
    partial_metadata: boolean;
    refresh_failed: boolean;
  }>;
  items: readonly CurrentNewsItem[];
}>;
export type HeadlineInstrumentOption = Readonly<{ symbol: string; label: string }>;
export type CurrentNewsRequest = Readonly<{
  symbol: string;
  limit?: number;
  signal?: AbortSignal;
}>;
export type CurrentNewsFetch = (path: string, options?: RequestInit) => Promise<Response>;
export type HeadlinesErrorKind =
  | "authorization"
  | "provider_unavailable"
  | "provider_busy"
  | "unreachable"
  | "malformed"
  | "rejected";

export declare class HeadlinesRequestError extends Error {
  constructor(kind: HeadlinesErrorKind, status?: number | null);
  kind: HeadlinesErrorKind;
  status: number | null;
}
export declare function projectCurrentNews(
  value: unknown,
  expectedSymbol: string,
  expectedLimit: number,
): CurrentNewsResponse;
export declare function headlineInstrumentsForSnapshot(snapshot: BriefingSnapshot | null): HeadlineInstrumentOption[];
export declare function createCurrentHeadlinesClient(apiFetch: CurrentNewsFetch): {
  getCurrent(options: CurrentNewsRequest): Promise<CurrentNewsResponse>;
};
