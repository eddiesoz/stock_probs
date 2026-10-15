const MAX_RESPONSE_BYTES = 256 * 1024;
const SYMBOL_PATTERN = /^[A-Z0-9.^-]{1,15}$/;
const CONTROL_PATTERN = /\p{C}/u;
const ROOT_KEYS = ["query", "provider", "as_of", "items", "coverage", "cache_state"];
const QUERY_KEYS = ["symbol", "limit"];
const ITEM_KEYS = ["id", "title", "publisher", "url", "published_at", "related_symbols"];
const COVERAGE_KEYS = ["returned_count", "partial_metadata", "refresh_failed"];

export class HeadlinesRequestError extends Error {
  constructor(kind, status = null) {
    super("The current headlines request could not be completed.");
    this.name = "HeadlinesRequestError";
    this.kind = kind;
    this.status = status;
  }
}

function isRecord(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    && (Object.getPrototypeOf(value) === Object.prototype || Object.getPrototypeOf(value) === null);
}

function hasExactKeys(value, keys) {
  return isRecord(value) && Object.keys(value).length === keys.length
    && keys.every((key) => Object.hasOwn(value, key));
}

function checkedText(value, maximum) {
  if (typeof value !== "string" || value.length < 1 || value.length > maximum
      || value.trim() !== value || CONTROL_PATTERN.test(value)) {
    throw new HeadlinesRequestError("malformed");
  }
  return value;
}

function checkedTimestamp(value, optional = false) {
  if (value === null && optional) return null;
  if (typeof value !== "string" || !/(?:[zZ]|[+-]\d{2}:\d{2})$/.test(value)
      || !Number.isFinite(Date.parse(value))) {
    throw new HeadlinesRequestError("malformed");
  }
  return value;
}

function checkedArticleUrl(value) {
  const text = checkedText(value, 2048);
  let url;
  try {
    url = new URL(text);
  } catch {
    throw new HeadlinesRequestError("malformed");
  }
  const host = url.hostname.toLowerCase();
  const labels = host.split(".");
  const domainHost = host.length <= 253 && labels.length >= 2
    && labels.every((label) => /^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$/.test(label))
    && /[a-z]/.test(labels.at(-1) ?? "")
    && !["localhost", "local", "internal", "test", "invalid", "example"].includes(labels.at(-1));
  if (url.protocol !== "https:" || !domainHost || url.username || url.password
      || (url.port !== "" && url.port !== "443")) {
    throw new HeadlinesRequestError("malformed");
  }
  return url.href;
}

function checkedNewsItem(item) {
  if (!hasExactKeys(item, ITEM_KEYS)) throw new HeadlinesRequestError("malformed");
  const publisher = item.publisher === null ? null : checkedText(item.publisher, 200);
  const publishedAt = checkedTimestamp(item.published_at, true);
  let relatedSymbols = null;
  if (item.related_symbols !== null) {
    if (!Array.isArray(item.related_symbols) || item.related_symbols.length > 32) {
      throw new HeadlinesRequestError("malformed");
    }
    relatedSymbols = item.related_symbols.map((symbol) => checkedText(symbol, 32));
  }
  return Object.freeze({
    id: checkedText(item.id, 128),
    title: checkedText(item.title, 500),
    publisher,
    published_at: publishedAt,
    url: checkedArticleUrl(item.url),
    related_symbols: relatedSymbols === null ? null : Object.freeze(relatedSymbols),
  });
}

export function projectCurrentNews(value, expectedSymbol, expectedLimit) {
  if (!SYMBOL_PATTERN.test(expectedSymbol) || !Number.isSafeInteger(expectedLimit)
      || expectedLimit < 1 || expectedLimit > 10 || !hasExactKeys(value, ROOT_KEYS)
      || !hasExactKeys(value.query, QUERY_KEYS) || value.query.symbol !== expectedSymbol
      || value.query.limit !== expectedLimit || !Array.isArray(value.items)
      || value.items.length > expectedLimit || !hasExactKeys(value.coverage, COVERAGE_KEYS)
      || !["miss", "hit", "stale_fallback"].includes(value.cache_state)) {
    throw new HeadlinesRequestError("malformed");
  }

  const provider = checkedText(value.provider, 80);
  const asOf = checkedTimestamp(value.as_of);
  const items = value.items.map(checkedNewsItem);
  const hasPartialMetadata = items.some((item) => item.publisher === null
    || item.published_at === null || item.related_symbols === null);
  const isStale = value.cache_state === "stale_fallback";
  const coverage = value.coverage;
  if (!Number.isSafeInteger(coverage.returned_count) || coverage.returned_count !== items.length
      || typeof coverage.partial_metadata !== "boolean"
      || coverage.partial_metadata !== hasPartialMetadata
      || typeof coverage.refresh_failed !== "boolean" || coverage.refresh_failed !== isStale) {
    throw new HeadlinesRequestError("malformed");
  }

  return Object.freeze({
    query: Object.freeze({ symbol: expectedSymbol, limit: expectedLimit }),
    provider,
    as_of: asOf,
    cache_state: value.cache_state,
    coverage: Object.freeze({
      returned_count: coverage.returned_count,
      partial_metadata: coverage.partial_metadata,
      refresh_failed: coverage.refresh_failed,
    }),
    items: Object.freeze(items),
  });
}

export function headlineInstrumentsForSnapshot(snapshot) {
  if (!snapshot) return [];
  const sources = new Map();
  const add = (symbol, source) => {
    if (typeof symbol !== "string" || !SYMBOL_PATTERN.test(symbol)) return;
    const current = sources.get(symbol) ?? new Set();
    current.add(source);
    sources.set(symbol, current);
  };
  for (const item of snapshot.price_changes ?? []) add(item?.symbol, "saved price move");
  for (const item of snapshot.triggered_alerts ?? []) add(item?.symbol, "saved alert");
  return Array.from(sources, ([symbol, kinds]) => Object.freeze({
    symbol,
    label: symbol + " — " + Array.from(kinds).join(" and "),
  }));
}

async function readBoundedJson(response) {
  const contentLength = response.headers.get("Content-Length");
  if (contentLength !== null && /^\d+$/.test(contentLength) && Number(contentLength) > MAX_RESPONSE_BYTES) {
    try { await response.body?.cancel(); } catch {}
    throw new HeadlinesRequestError("malformed");
  }
  if (!response.body || typeof response.body.getReader !== "function") {
    throw new HeadlinesRequestError("malformed");
  }
  const reader = response.body.getReader();
  const chunks = [];
  let size = 0;
  try {
    while (true) {
      const result = await reader.read();
      if (result.done) break;
      size += result.value.byteLength;
      if (size > MAX_RESPONSE_BYTES) {
        try { await reader.cancel(); } catch {}
        throw new HeadlinesRequestError("malformed");
      }
      chunks.push(result.value);
    }
  } finally {
    reader.releaseLock();
  }
  const bytes = new Uint8Array(size);
  let offset = 0;
  for (const chunk of chunks) {
    bytes.set(chunk, offset);
    offset += chunk.byteLength;
  }
  try {
    return JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(bytes));
  } catch {
    throw new HeadlinesRequestError("malformed");
  }
}

export function createCurrentHeadlinesClient(apiFetch) {
  if (typeof apiFetch !== "function") throw new TypeError("A same-origin authenticated request helper is required.");
  return Object.freeze({
    async getCurrent({ symbol, limit = 5, signal }) {
      if (typeof symbol !== "string" || !SYMBOL_PATTERN.test(symbol)
          || !Number.isSafeInteger(limit) || limit < 1 || limit > 10) {
        throw new HeadlinesRequestError("malformed");
      }
      const query = new URLSearchParams({ symbol, limit: String(limit) });
      let response;
      try {
        response = await apiFetch("/api/v1/news?" + query.toString(), {
          method: "GET",
          cache: "no-store",
          signal,
        });
      } catch (error) {
        if (signal?.aborted || error?.name === "AbortError") throw error;
        throw new HeadlinesRequestError("unreachable");
      }
      if (!response.ok) {
        if (response.status === 401 || response.status === 403) {
          try { await response.body?.cancel(); } catch {}
          throw new HeadlinesRequestError("authorization", response.status);
        }
        if (response.status === 502) {
          try { await response.body?.cancel(); } catch {}
          throw new HeadlinesRequestError("provider_unavailable", 502);
        }
        if (response.status === 503) {
          let errorBody;
          try {
            errorBody = await readBoundedJson(response);
          } catch {
            throw new HeadlinesRequestError("provider_unavailable", 503);
          }
          const code = isRecord(errorBody) && isRecord(errorBody.error)
            ? errorBody.error.code
            : null;
          throw new HeadlinesRequestError(
            code === "provider_busy" ? "provider_busy" : "provider_unavailable",
            503,
          );
        }
        try { await response.body?.cancel(); } catch {}
        throw new HeadlinesRequestError("rejected", response.status);
      }
      return projectCurrentNews(await readBoundedJson(response), symbol, limit);
    },
  });
}
