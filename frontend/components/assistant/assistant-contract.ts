export type AssistantRoute =
  | "/"
  | "/overview"
  | "/research"
  | "/tools"
  | "/tools/forecast"
  | "/tools/live-trading"
  | "/tools/markets"
  | "/api-docs"
  | "/account"
  | "/admin";

export type AssistantContextRequest = {
  route: AssistantRoute;
  symbol?: string;
  asset_type?: "stock" | "etf";
  provider?: string;
  exchange?: string;
  event_id?: number;
  result_id?: number;
};

export type AssistantTurnContext = {
  route: AssistantRoute;
  instrument: {
    symbol: string;
    asset_type: "stock" | "etf";
    provider: string;
    exchange: string;
    display_name: string;
  } | null;
  event_ref: { id: number; version?: number | string | null } | null;
  result_ref: { id: number; version?: number | string | null } | null;
  context_version: string;
};

export type AssistantContext = AssistantTurnContext & {
  preview: { summary: string; fields: string[]; note?: string };
};

export function assistantTurnContext(context: AssistantContext): AssistantTurnContext {
  return {
    route: context.route,
    instrument: context.instrument
      ? {
        symbol: context.instrument.symbol,
        asset_type: context.instrument.asset_type,
        provider: context.instrument.provider,
        exchange: context.instrument.exchange,
        display_name: context.instrument.display_name,
      }
      : null,
    event_ref: context.event_ref ? { id: context.event_ref.id, version: context.event_ref.version ?? null } : null,
    result_ref: context.result_ref ? { id: context.result_ref.id, version: context.result_ref.version ?? null } : null,
    context_version: context.context_version,
  };
}

export type AssistantStatus = {
  available: boolean;
  enabled: boolean;
  worker: { status: string; reason?: string | null };
  limits: { active_per_user: number; active_global: number; tools_per_turn: number; turn_seconds: number };
  storage: {
    user_bytes: number;
    user_limit: number;
    global_bytes: number;
    global_limit: number;
    database_bytes: number;
    database_limit: number;
    backup_retention_note?: string;
  };
};

export type AssistantModel = {
  id: string;
  provider: string;
  model_id?: string;
  provider_id?: string;
  native_provider_id?: string;
  name: string;
  availability: "available" | "unavailable" | "pending" | string;
  available?: boolean;
  enabled?: boolean;
  usable?: boolean;
  free: boolean;
  training: "no_training" | "data_collection" | "unknown" | string;
  training_uses_data?: boolean;
  terms_url?: string | null;
  terms_reviewed_at?: string | null;
  policy_version: string;
  disclosure: string;
  privacy_policy_version?: string;
  privacy_disclosure?: string;
  billing_class?: string;
  billing_policy_version?: string | null;
  cost_disclosure?: string | null;
  revision?: number;
  availability_reason?: string | null;
  consent?: { accepted: boolean; data_collection_opt_in: boolean; accepted_at?: string | null } | null;
};

export type ConversationSummary = {
  id: string;
  title: string;
  revision: number;
  created_at: string;
  updated_at: string;
  last_message_preview?: string | null;
};

export type AssistantSource = {
  source_id: string;
  title: string;
  url?: string | null;
  source_type?: string;
  retrieved_at?: string | null;
  as_of?: string | null;
};

export type AssistantMessage = {
  id: string;
  turn_id?: string | null;
  seq: number;
  role: "user" | "assistant" | "system";
  text: string;
  created_at: string;
  sources?: AssistantSource[];
};

export type AssistantTurn = {
  id: string;
  status: string;
  model_id: string;
  policy_version: string;
  context_version?: string | null;
  context?: AssistantTurnContext | null;
  created_at: string;
  completed_at?: string | null;
  actions?: AssistantSavedAction[];
};

export type AssistantConversationDetail = {
  conversation: ConversationSummary & { delete_confirmation_phrase: string };
  messages: { items: AssistantMessage[]; page: number; page_size: number; total: number };
  turns: AssistantTurn[];
  actions?: AssistantSavedAction[];
  action_pagination?: { page: number; page_size: number; total: number };
  events?: { items: Array<{ turn_id: string; sequence: number; type: string; data: Record<string, unknown>; created_at: string }>; page: number; page_size: number; total: number };
};

export type AssistantSavedAction = {
  action_id: string;
  action_type: string;
  status: string;
  expires_at: string;
  availability?: "confirmable" | "different_session" | "expired" | "policy_changed" | "authorization_required" | "stale" | "unavailable";
  proposal?: null | {
    title: string;
    summary: string;
    changes: Array<{ label: string; after?: string | number | boolean | null }>;
    action_version: number;
    context_version: string;
    confirmation_phrase: string | null;
  };
  receipt: null | {
    receipt_id: string;
    outcome: string;
    message: string;
    destination?: string | null;
    browser_action?: unknown;
  };
};

export type AssistantToolEvent = {
  name: string;
  call_id: string;
  receipt_id?: string;
  status: "pending" | "complete" | "failed" | string;
  description?: string;
  result_bytes?: number;
  result_sha256?: string;
};

export type AssistantActionProposal = {
  action_id: string;
  action_type: string;
  title: string;
  summary: string;
  changes: Array<{ label: string; before?: string | number | boolean | null; after?: string | number | boolean | null }>;
  version: number;
  expires_at: string;
  confirmation_phrase: string | null;
  context_version?: string;
  availability?: AssistantSavedAction["availability"];
};

export type PrivateSearchPreview = {
  preview_id: string;
  query: string;
  reason: string;
  context_version: string;
  expires_at: string;
  confirmation_phrase: string;
};

export type PrivateWebFetchPreview = {
  preview_id: string;
  url: string;
  reason: string;
  context_version: string;
  expires_at: string;
  confirmation_phrase: string;
};

export type AssistantEvent =
  | { type: "meta"; model_id: string; policy_version: string; context_version?: string }
  | { type: "token"; text: string }
  | ({ type: "tool" } & AssistantToolEvent)
  | ({ type: "source" } & AssistantSource)
  | ({ type: "proposed_action" } & AssistantActionProposal)
  | ({ type: "private_context_preview" } & PrivateSearchPreview)
  | ({ type: "webfetch_preview" } & PrivateWebFetchPreview)
  | { type: "complete"; status: "completed" | "cancelled" | "failed" | "timed_out"; assistant_message_id?: string }
  | { type: "error"; code: string; message: string };

export type AssistantEventName = AssistantEvent["type"];

export type AssistantEventEnvelope = { id: number; event: AssistantEvent };

export type AssistantBrowserAction =
  | { type: "theme.set"; payload: { theme: "light" | "dark" | "system" } }
  | { type: "filters.apply"; payload: {
    query: string;
    asset_type?: "" | "stock" | "etf";
    status?: "" | "successful" | "repeated" | "failed";
    analysis_kind?: "" | "submitted_forecast" | "fresh_historical_reconstruction";
    submitted_from?: string;
    submitted_to?: string;
    model?: string;
    horizon?: "close_to_close" | "completed_5m_to_close" | "five_min_forward" | "daily_1" | "weekly_5" | "monthly_21" | "quarterly_63";
    sort?: "event_id:desc" | "event_id:asc" | "symbol:asc" | "company:asc" | "status:asc";
    page_size?: 10 | 20 | 50;
  } }
  | { type: "market.filters.apply"; payload: {
    query: string;
    exchange: string;
    asset_type: "" | "stock" | "etf";
    sort: "symbol:asc" | "symbol:desc" | "price:desc" | "price:asc" | "change:desc" | "volume:desc" | "open:desc" | "high:desc" | "low:desc" | "last:desc" | "previous_close:desc" | "last_trade:desc";
    min_price: string;
    max_price: string;
    min_change: string;
    max_change: string;
    min_volume: string;
    quote_field: "" | "change_percent" | "volume" | "open" | "high" | "low" | "last" | "previous_close" | "last_trade";
    quote_min: string;
    quote_max: string;
  } }
  | { type: "market.chart_range.set"; payload: { symbol: string; asset_type: "stock" | "etf"; provider: string; exchange: string; range: "5d" | "1mo" | "3mo" | "6mo" | "1y" } }
  | { type: "market.columns.set"; payload: { show_all_columns: boolean } }
  | { type: "market.refresh"; payload: { kind: "quotes" | "watchlist" | "chart" } }
  | { type: "notes.set"; payload: { symbol: string; asset_type: "stock" | "etf"; provider: string; exchange: string } }
  | { type: "notes.clear"; payload: { symbol: string; asset_type: "stock" | "etf"; provider: string; exchange: string } }
  | { type: "alerts.add"; payload: { symbol: string; asset_type: "stock" | "etf"; provider: string; exchange: string; threshold: number } }
  | { type: "alerts.remove"; payload: { symbol: string; asset_type: "stock" | "etf"; provider: string; exchange: string } };

export type AssistantMarketSelection = {
  symbol: string;
  asset_type?: string;
  provider?: string;
  exchange?: string;
} | null;

export type AssistantMarketsAction = Extract<AssistantBrowserAction, { type: `market.${string}` }>;

export type AssistantMarketsBridgeResult =
  | { ok: true; action: AssistantMarketsAction; message: string }
  | { ok: false; message: string };

export type AssistantMarketsBridgeContext = {
  route: string;
  selected: AssistantMarketSelection;
  exchanges: readonly string[];
};

const boundedSearchQuery = (value: unknown): value is string => typeof value === "string" && value.trim().length <= 30;
const bridgeStatus = new Set(["successful", "repeated", "failed"]);
const historyAnalysisKinds = new Set(["submitted_forecast", "fresh_historical_reconstruction"]);
const historyHorizons = new Set(["close_to_close", "completed_5m_to_close", "five_min_forward", "daily_1", "weekly_5", "monthly_21", "quarterly_63"]);
const historySorts = new Set(["event_id:desc", "event_id:asc", "symbol:asc", "company:asc", "status:asc"]);
const historyPageSizes = new Set([10, 20, 50]);
const marketSorts = new Set(["symbol:asc", "symbol:desc", "price:desc", "price:asc", "change:desc", "volume:desc", "open:desc", "high:desc", "low:desc", "last:desc", "previous_close:desc", "last_trade:desc"]);
const quoteFields = new Set(["change_percent", "volume", "open", "high", "low", "last", "previous_close", "last_trade"]);
const chartRanges = new Set(["5d", "1mo", "3mo", "6mo", "1y"]);
const identityLabelPattern = /^[A-Za-z0-9][A-Za-z0-9 ._-]{0,79}$/;
const decimalFilterPattern = /^-?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$/;

function hasExactKeys(value: Record<string, unknown>, allowed: readonly string[], required: readonly string[] = []): boolean {
  const keys = Object.keys(value);
  return keys.every((key) => allowed.includes(key)) && required.every((key) => Object.hasOwn(value, key));
}

function safeBoundedText(value: unknown, maximum: number): value is string {
  return typeof value === "string" && value.length <= maximum && !/[\u0000-\u001f\u007f]/.test(value);
}

function validCalendarDate(value: unknown): value is string {
  if (typeof value !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
  if (value.startsWith("0000")) return false;
  const timestamp = Date.parse(`${value}T00:00:00.000Z`);
  return Number.isFinite(timestamp) && new Date(timestamp).toISOString().slice(0, 10) === value;
}

function validDatePair(from: unknown, to: unknown): boolean {
  if (from !== undefined && !validCalendarDate(from)) return false;
  if (to !== undefined && !validCalendarDate(to)) return false;
  return from === undefined || to === undefined || String(from) <= String(to);
}

function finiteFilterNumber(value: string, options: { nonnegative?: boolean; integer?: boolean } = {}): number | undefined {
  if (value === "") return undefined;
  if (value.length > 40 || value.trim() !== value || !decimalFilterPattern.test(value)) return Number.NaN;
  const parsed = Number(value);
  if (!Number.isFinite(parsed) || Math.abs(parsed) > Number.MAX_SAFE_INTEGER
      || (options.nonnegative && parsed < 0)
      || (options.integer && !Number.isSafeInteger(parsed))) return Number.NaN;
  return parsed;
}

function validMarketNumberPair(minimum: string, maximum: string, options: { nonnegative?: boolean; integer?: boolean } = {}): boolean {
  const min = finiteFilterNumber(minimum, options);
  const max = finiteFilterNumber(maximum, options);
  return !Number.isNaN(min) && !Number.isNaN(max) && (min === undefined || max === undefined || min <= max);
}

/** Parse only the exact typed browser bridge DTOs. Model supplied objects never execute directly. */
export function readAssistantBrowserAction(value: unknown, currentRoute: string): AssistantBrowserAction | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const item = value as Record<string, unknown>;
  if (typeof item.type !== "string" || !item.payload || typeof item.payload !== "object" || Array.isArray(item.payload)) return null;
  const payload = item.payload as Record<string, unknown>;
  const pageActionRoute = item.type === "filters.apply"
    ? "/"
    : item.type.startsWith("market.") ? "/tools/markets" : undefined;
  if (["filters.apply", "market.filters.apply", "market.chart_range.set", "market.columns.set", "market.refresh"].includes(item.type)) {
    if (!hasExactKeys(item, ["type", "payload", "destination"], ["type", "payload"])) return null;
    if (item.destination !== undefined) {
      const destination = item.destination;
      if (!destination || typeof destination !== "object" || Array.isArray(destination)) return null;
      const target = destination as Record<string, unknown>;
      if (!hasExactKeys(target, ["kind", "route"], ["kind", "route"])
          || target.kind !== "current-page" || target.route !== pageActionRoute || currentRoute !== pageActionRoute) return null;
    }
  }
  if (item.type === "theme.set" && (payload.theme === "light" || payload.theme === "dark" || payload.theme === "system")) {
    return { type: "theme.set", payload: { theme: payload.theme } };
  }
  if (item.type === "filters.apply" && currentRoute === "/" && boundedSearchQuery(payload.query) && safeBoundedText(payload.query, 30)) {
    const filterKeys = ["query", "symbol", "asset_type", "status", "analysis_kind", "submitted_from", "submitted_to", "model", "horizon", "sort", "page_size"];
    if (!hasExactKeys(payload, filterKeys, ["query"])) return null;
    const clean: Extract<AssistantBrowserAction, { type: "filters.apply" }>["payload"] = { query: payload.query.trim() };
    if (payload.symbol !== undefined) {
      if (payload.symbol !== "") return null;
    }
    if (payload.asset_type !== undefined) {
      if (payload.asset_type !== "" && payload.asset_type !== "stock" && payload.asset_type !== "etf") return null;
      if (payload.asset_type) clean.asset_type = payload.asset_type;
    }
    if (payload.status !== undefined) {
      if (typeof payload.status !== "string" || (payload.status !== "" && !bridgeStatus.has(payload.status))) return null;
      if (payload.status) clean.status = payload.status as "successful" | "repeated" | "failed";
    }
    if (payload.analysis_kind !== undefined) {
      if (typeof payload.analysis_kind !== "string" || (payload.analysis_kind !== "" && !historyAnalysisKinds.has(payload.analysis_kind))) return null;
      if (payload.analysis_kind) clean.analysis_kind = payload.analysis_kind as "submitted_forecast" | "fresh_historical_reconstruction";
    }
    if (payload.submitted_from !== undefined) {
      if (payload.submitted_from !== "" && !validCalendarDate(payload.submitted_from)) return null;
      if (payload.submitted_from) clean.submitted_from = payload.submitted_from;
    }
    if (payload.submitted_to !== undefined) {
      if (payload.submitted_to !== "" && !validCalendarDate(payload.submitted_to)) return null;
      if (payload.submitted_to) clean.submitted_to = payload.submitted_to;
    }
    if (!validDatePair(clean.submitted_from, clean.submitted_to)) return null;
    if (payload.model !== undefined) {
      if (typeof payload.model !== "string" || (payload.model !== "" && (!safeBoundedText(payload.model, 120) || !payload.model.trim()))) return null;
      if (payload.model) clean.model = payload.model.trim();
    }
    if (payload.horizon !== undefined) {
      if (typeof payload.horizon !== "string" || (payload.horizon !== "" && !historyHorizons.has(payload.horizon))) return null;
      if (payload.horizon) clean.horizon = payload.horizon as Extract<AssistantBrowserAction, { type: "filters.apply" }>["payload"]["horizon"];
    }
    if (payload.sort !== undefined) {
      if (typeof payload.sort !== "string" || !historySorts.has(payload.sort)) return null;
      clean.sort = payload.sort as Extract<AssistantBrowserAction, { type: "filters.apply" }>["payload"]["sort"];
    }
    if (payload.page_size !== undefined) {
      if (typeof payload.page_size !== "number" || !Number.isInteger(payload.page_size) || !historyPageSizes.has(payload.page_size)) return null;
      clean.page_size = payload.page_size as 10 | 20 | 50;
    }
    return { type: "filters.apply", payload: clean };
  }
  if (item.type === "market.filters.apply" && currentRoute === "/tools/markets") {
    const keys = ["query", "exchange", "asset_type", "sort", "min_price", "max_price", "min_change", "max_change", "min_volume", "quote_field", "quote_min", "quote_max"];
    if (!hasExactKeys(payload, keys, keys)) return null;
    const stringFields = keys.filter((key) => !["asset_type", "sort", "quote_field"].includes(key));
    if (stringFields.some((key) => typeof payload[key] !== "string")) return null;
    const query = payload.query as string;
    const exchange = payload.exchange as string;
    const minPrice = payload.min_price as string;
    const maxPrice = payload.max_price as string;
    const minChange = payload.min_change as string;
    const maxChange = payload.max_change as string;
    const minVolume = payload.min_volume as string;
    const quoteMin = payload.quote_min as string;
    const quoteMax = payload.quote_max as string;
    if (!safeBoundedText(query, 120)
        || (exchange !== "" && !identityLabelPattern.test(exchange))
        || (payload.asset_type !== "" && payload.asset_type !== "stock" && payload.asset_type !== "etf")
        || typeof payload.sort !== "string" || !marketSorts.has(payload.sort)
        || typeof payload.quote_field !== "string" || (payload.quote_field !== "" && !quoteFields.has(payload.quote_field))
        || !validMarketNumberPair(minPrice, maxPrice, { nonnegative: true })
        || !validMarketNumberPair(minChange, maxChange)
        || !validMarketNumberPair(minVolume, "", { nonnegative: true, integer: true })
        || !validMarketNumberPair(quoteMin, quoteMax, {
          nonnegative: payload.quote_field !== "change_percent",
          integer: payload.quote_field === "volume",
        })
        || (!payload.quote_field && (quoteMin !== "" || quoteMax !== ""))) return null;
    return {
      type: "market.filters.apply",
      payload: {
        query, exchange, asset_type: payload.asset_type as "" | "stock" | "etf", sort: payload.sort as Extract<AssistantBrowserAction, { type: "market.filters.apply" }>["payload"]["sort"],
        min_price: minPrice, max_price: maxPrice, min_change: minChange, max_change: maxChange, min_volume: minVolume,
        quote_field: payload.quote_field as Extract<AssistantBrowserAction, { type: "market.filters.apply" }>["payload"]["quote_field"], quote_min: quoteMin, quote_max: quoteMax,
      },
    };
  }
  if (item.type === "market.chart_range.set" && currentRoute === "/tools/markets") {
    if (!hasExactKeys(payload, ["symbol", "asset_type", "provider", "exchange", "range"], ["symbol", "asset_type", "provider", "exchange", "range"])
        || typeof payload.symbol !== "string" || !symbolPattern.test(payload.symbol)
        || (payload.asset_type !== "stock" && payload.asset_type !== "etf")
        || typeof payload.provider !== "string" || !identityLabelPattern.test(payload.provider)
        || typeof payload.exchange !== "string" || !identityLabelPattern.test(payload.exchange)
        || typeof payload.range !== "string" || !chartRanges.has(payload.range)) return null;
    return { type: "market.chart_range.set", payload: {
      symbol: payload.symbol, asset_type: payload.asset_type, provider: payload.provider, exchange: payload.exchange,
      range: payload.range as "5d" | "1mo" | "3mo" | "6mo" | "1y",
    } };
  }
  if (item.type === "market.columns.set" && currentRoute === "/tools/markets") {
    if (!hasExactKeys(payload, ["show_all_columns"], ["show_all_columns"]) || typeof payload.show_all_columns !== "boolean") return null;
    return { type: "market.columns.set", payload: { show_all_columns: payload.show_all_columns } };
  }
  if (item.type === "market.refresh" && currentRoute === "/tools/markets") {
    if (!hasExactKeys(payload, ["kind"], ["kind"]) || !["quotes", "watchlist", "chart"].includes(String(payload.kind))) return null;
    return { type: "market.refresh", payload: { kind: payload.kind as "quotes" | "watchlist" | "chart" } };
  }
  const identity = () => {
    if (currentRoute !== "/tools/live-trading"
        || typeof payload.symbol !== "string" || !symbolPattern.test(payload.symbol)
        || (payload.asset_type !== "stock" && payload.asset_type !== "etf")
        || typeof payload.provider !== "string" || !identityLabelPattern.test(payload.provider)
        || typeof payload.exchange !== "string" || !identityLabelPattern.test(payload.exchange)) return null;
    return {
      symbol: payload.symbol,
      asset_type: payload.asset_type as "stock" | "etf",
      provider: payload.provider,
      exchange: payload.exchange,
    };
  };
  if (item.type === "notes.set" || item.type === "notes.clear" || item.type === "alerts.add" || item.type === "alerts.remove") {
    const canonical = identity();
    if (!canonical) return null;
    if (item.type === "notes.set") return { type: "notes.set", payload: canonical };
    if (item.type === "notes.clear") return { type: "notes.clear", payload: canonical };
    if (item.type === "alerts.add") {
      if (typeof payload.threshold !== "number" || !Number.isFinite(payload.threshold) || payload.threshold <= 0) return null;
      return { type: "alerts.add", payload: { ...canonical, threshold: payload.threshold } };
    }
    return { type: "alerts.remove", payload: canonical };
  }
  return null;
}

function matchesMarketSelection(action: Extract<AssistantMarketsAction, { type: "market.chart_range.set" }>, selected: AssistantMarketSelection): boolean {
  return Boolean(selected
    && action.payload.symbol === selected.symbol
    && action.payload.asset_type === selected.asset_type
    && action.payload.provider === (selected.provider ?? "yahoo")
    && action.payload.exchange === selected.exchange);
}

function isMarketsAction(action: AssistantBrowserAction): action is AssistantMarketsAction {
  return action.type === "market.filters.apply"
    || action.type === "market.chart_range.set"
    || action.type === "market.columns.set"
    || action.type === "market.refresh";
}

/** Re-validate the event at the page boundary before changing route-local Markets state. */
export function readAssistantMarketsAction(value: unknown, context: AssistantMarketsBridgeContext): AssistantMarketsBridgeResult {
  if (context.route !== "/tools/markets") return { ok: false, message: "This Markets action is no longer on its approved page." };
  const parsed = readAssistantBrowserAction(value, context.route);
  if (!parsed || !isMarketsAction(parsed)) {
    return { ok: false, message: "The Markets action was malformed or outside the approved page controls." };
  }
  if (parsed.type === "market.filters.apply") {
    if (parsed.payload.exchange && !context.exchanges.includes(parsed.payload.exchange)) {
      return { ok: false, message: "The selected exchange is no longer available in the current watchlist." };
    }
    return { ok: true, action: parsed, message: "Confirmed Markets filters applied for this page." };
  }
  if (parsed.type === "market.chart_range.set") {
    if (!matchesMarketSelection(parsed, context.selected)) {
      return { ok: false, message: "The selected instrument changed after this chart preview." };
    }
    return { ok: true, action: parsed, message: `Confirmed ${parsed.payload.range} chart range applied to ${parsed.payload.symbol}.` };
  }
  if (parsed.type === "market.columns.set") {
    return { ok: true, action: parsed, message: parsed.payload.show_all_columns ? "All quote columns are shown for this page." : "Summary quote columns are shown for this page." };
  }
  if (parsed.payload.kind === "chart" && !context.selected) {
    return { ok: false, message: "Select an instrument before refreshing its chart." };
  }
  const messages = {
    quotes: "Quote refresh requested for the current watchlist.",
    watchlist: "Saved watchlist reload requested.",
    chart: "Chart refresh requested for the current instrument.",
  };
  return { ok: true, action: parsed, message: messages[parsed.payload.kind] };
}

/** Destinations are parsed as same-origin application paths and then matched to fixed routes. */
export function safeAssistantDestination(value: unknown): string | undefined {
  if (typeof value !== "string" || value.length > 512 || !value.startsWith("/") || value.startsWith("//") || value.includes("\\")) return undefined;
  let url: URL;
  try { url = new URL(value, "https://signal-ledger.invalid"); } catch { return undefined; }
  if (url.origin !== "https://signal-ledger.invalid" || url.hash.length > 80) return undefined;
  if (["/admin#invitations", "/admin#backups", "/admin#restore", "/admin#assistant-providers", "/account#sessions"].includes(`${url.pathname}${url.hash}`)
      && !url.search) return `${url.pathname}${url.hash}`;
  const params = [...url.searchParams.entries()];
  const uniqueKeys = new Set(params.map(([key]) => key));
  if (url.pathname === "/api/v1/history-export.csv" || url.pathname === "/api/v1/history-export.json") {
    if (url.hash || params.length === 0) return undefined;
    const entries = Object.fromEntries(params);
    const allowed = ["q", "symbol", "status", "asset_type", "analysis_kind", "submitted_from", "submitted_to", "model", "horizon", "sort_by", "sort_order"];
    if (params.length > allowed.length || uniqueKeys.size !== params.length || params.some(([key]) => !allowed.includes(key))
        || !Object.hasOwn(entries, "sort_by") || !Object.hasOwn(entries, "sort_order")
        || !["event_id", "symbol", "company", "status"].includes(entries.sort_by)
        || !["asc", "desc"].includes(entries.sort_order)
        || (entries.q !== undefined && !safeBoundedText(entries.q, 30))
        || (entries.symbol !== undefined && !canonicalSymbol(entries.symbol))
        || (entries.status !== undefined && !bridgeStatus.has(entries.status))
        || (entries.asset_type !== undefined && entries.asset_type !== "stock" && entries.asset_type !== "etf")
        || (entries.analysis_kind !== undefined && !historyAnalysisKinds.has(entries.analysis_kind))
        || (entries.submitted_from !== undefined && !validExportDateBoundary(entries.submitted_from, "from"))
        || (entries.submitted_to !== undefined && !validExportDateBoundary(entries.submitted_to, "to"))
        || (entries.submitted_from && entries.submitted_to && entries.submitted_from.slice(0, 10) > entries.submitted_to.slice(0, 10))
        || (entries.model !== undefined && (!safeBoundedText(entries.model, 120) || !entries.model.trim()))
        || (entries.horizon !== undefined && !historyHorizons.has(entries.horizon))) return undefined;
    return `${url.pathname}?${new URLSearchParams(params).toString()}`;
  }
  if (url.pathname === "/" && url.hash === "#result-section" && params.length === 1
      && params[0][0] === "event_id" && positiveId(params[0][1])) return `/?event_id=${params[0][1]}#result-section`;
  if (url.pathname === "/" && url.hash === "#history-heading" && params.length <= 10) {
    const entries = Object.fromEntries(params);
    if (uniqueKeys.size !== params.length
        || params.some(([key]) => !["q", "status", "asset_type", "analysis_kind", "submitted_from", "submitted_to", "model", "horizon", "sort", "page_size"].includes(key))
        || (entries.q !== undefined && !safeBoundedText(entries.q, 30))
        || (entries.status !== undefined && !bridgeStatus.has(entries.status))
        || (entries.asset_type !== undefined && entries.asset_type !== "stock" && entries.asset_type !== "etf")
        || (entries.analysis_kind !== undefined && !historyAnalysisKinds.has(entries.analysis_kind))
        || (entries.submitted_from !== undefined && !validCalendarDate(entries.submitted_from))
        || (entries.submitted_to !== undefined && !validCalendarDate(entries.submitted_to))
        || (entries.submitted_from && entries.submitted_to && entries.submitted_from > entries.submitted_to)
        || (entries.model !== undefined && (!safeBoundedText(entries.model, 120) || !entries.model.trim()))
        || (entries.horizon !== undefined && !historyHorizons.has(entries.horizon))
        || (entries.sort !== undefined && !historySorts.has(entries.sort))
        || (entries.page_size !== undefined && !["10", "20", "50"].includes(entries.page_size))) return undefined;
    const query = new URLSearchParams(params).toString();
    return `${query ? `/?${query}` : "/"}#history-heading`;
  }
  if (url.pathname === "/tools/markets" && !url.hash && params.length === 4) {
    const entries = Object.fromEntries(params);
    const symbol = canonicalSymbol(entries.symbol ?? null);
    const provider = entries.provider;
    const exchange = entries.exchange;
    if (symbol && (entries.asset_type === "stock" || entries.asset_type === "etf")
        && provider && identityLabelPattern.test(provider) && exchange && identityLabelPattern.test(exchange)
        && new Set(params.map(([key]) => key)).size === 4
        && ["symbol", "asset_type", "provider", "exchange"].every((key) => Object.hasOwn(entries, key))) {
      const query = new URLSearchParams({ symbol, asset_type: entries.asset_type, provider, exchange });
      return `/tools/markets?${query.toString()}`;
    }
  }
  return undefined;
}

function validExportDateBoundary(value: string, side: "from" | "to"): boolean {
  const suffix = side === "from" ? "T00:00:00Z" : "T23:59:59.999Z";
  return value.endsWith(suffix) && validCalendarDate(value.slice(0, 10)) && value === `${value.slice(0, 10)}${suffix}`;
}

export function assistantHistoryDestination(payload: Extract<AssistantBrowserAction, { type: "filters.apply" }>["payload"]): string | undefined {
  const params = new URLSearchParams();
  const query = payload.query.trim();
  if (query) params.set("q", query);
  for (const key of ["asset_type", "status", "analysis_kind", "submitted_from", "submitted_to", "model", "horizon", "sort"] as const) {
    const value = payload[key];
    if (value) params.set(key, value);
  }
  if (payload.page_size) params.set("page_size", String(payload.page_size));
  const queryString = params.toString();
  return safeAssistantDestination(`${queryString ? `/?${queryString}` : "/"}#history-heading`);
}

export class AssistantClientError extends Error {
  readonly status: number;
  readonly code: string;

  constructor(message: string, status: number, code: string) {
    super(message);
    this.status = status;
    this.code = code;
    this.name = "AssistantClientError";
  }
}

const visibleRoutes = new Set<AssistantRoute>([
  "/", "/overview", "/research", "/tools", "/tools/forecast", "/tools/live-trading", "/tools/markets", "/api-docs", "/account", "/admin",
]);

const sensitiveRoutes = new Set(["/sign-in", "/invite", "/authenticator", "/passkey"]);
const symbolPattern = /^[A-Z0-9][A-Z0-9.^-]{0,14}$/;
const providerPattern = identityLabelPattern;
const exchangePattern = identityLabelPattern;
const positiveIdPattern = /^[1-9]\d{0,9}$/;
const workspaceRoutes = new Set<AssistantRoute>([
  "/", "/overview", "/research", "/tools", "/tools/forecast", "/tools/live-trading", "/tools/markets",
]);
const savedReferenceRoutes = new Set<AssistantRoute>([
  "/research", "/tools/forecast", "/tools/live-trading", "/tools/markets",
]);

function positiveId(value: string | null): number | undefined {
  if (!value || !positiveIdPattern.test(value)) return undefined;
  const parsed = Number(value);
  return Number.isSafeInteger(parsed) && parsed <= 2_147_483_647 ? parsed : undefined;
}

function canonicalSymbol(value: string | null): string | undefined {
  const symbol = value?.trim().toUpperCase();
  return symbol && symbolPattern.test(symbol) ? symbol : undefined;
}

/** Extract only known page and instrument identifiers; free-form URL values never enter model context. */
export function assistantContextRequest(location: { pathname: string; search: string }): AssistantContextRequest | null {
  const pathname = location.pathname.replace(/\/+$/, "") || "/";
  if (sensitiveRoutes.has(pathname) || !visibleRoutes.has(pathname as AssistantRoute)) return null;
  const route = pathname as AssistantRoute;
  const query = new URLSearchParams(location.search);
  const symbol = canonicalSymbol(query.get("symbol"));
  const assetType = query.get("asset_type");
  const provider = query.get("provider")?.trim();
  const exchange = query.get("exchange")?.trim();
  const context: AssistantContextRequest = { route };

  // Display names and all other query values can contain arbitrary/private text; only send
  // stable identity assertions for routes where the backend can re-resolve the instrument.
  if (workspaceRoutes.has(route) && symbol && (assetType === "stock" || assetType === "etf")
      && provider && providerPattern.test(provider) && exchange && exchangePattern.test(exchange)) {
    Object.assign(context, { symbol, asset_type: assetType, provider, exchange });
  }
  if (savedReferenceRoutes.has(route)) {
    const eventId = positiveId(query.get("event_id"));
    const resultId = positiveId(query.get("result_id"));
    if (eventId) context.event_id = eventId;
    if (eventId && resultId) context.result_id = resultId;
  }
  return context;
}

export function assistantContextUrl(context: AssistantContextRequest): string {
  if (!visibleRoutes.has(context.route)) throw new TypeError("Assistant context route is not allowed.");
  const query = new URLSearchParams({ route: context.route });
  if (workspaceRoutes.has(context.route) && context.symbol && symbolPattern.test(context.symbol)
      && (context.asset_type === "stock" || context.asset_type === "etf")
      && context.provider && providerPattern.test(context.provider)
      && context.exchange && exchangePattern.test(context.exchange)) {
    query.set("symbol", context.symbol);
    query.set("asset_type", context.asset_type);
    query.set("provider", context.provider);
    query.set("exchange", context.exchange);
  }
  if (savedReferenceRoutes.has(context.route) && context.event_id && Number.isSafeInteger(context.event_id) && context.event_id > 0) query.set("event_id", String(context.event_id));
  if (savedReferenceRoutes.has(context.route) && context.event_id && context.result_id && Number.isSafeInteger(context.result_id) && context.result_id > 0) query.set("result_id", String(context.result_id));
  return `/api/v1/assistant/context?${query.toString()}`;
}

export function assistantApiPath(path: string): string {
  if (!path.startsWith("/api/v1/assistant/") || path.startsWith("//") || path.includes("\\")) {
    throw new TypeError("Assistant requests must use a fixed local API route.");
  }
  const resolved = new URL(path, "http://assistant.local");
  if (resolved.origin !== "http://assistant.local" || !resolved.pathname.startsWith("/api/v1/assistant/")) {
    throw new TypeError("Assistant requests must stay under the local assistant API.");
  }
  return path;
}

export function assistantErrorMessage(status: number, code: string): string {
  if (status === 401) return "Your session ended. Sign in again before continuing.";
  if (status === 403) return "This assistant request is not allowed for your current session.";
  if (status === 404) return "The assistant is not available for this account or conversation.";
  if (code === "policy_version" || code === "provider_policy_changed") return "The model policy changed. Review the current privacy terms before continuing.";
  if (status === 409) return "The workspace context changed. Refresh the preview before continuing.";
  if (status === 413) return "Assistant history has reached its storage limit. Existing workspace data is still available.";
  if (status === 428 || code === "consent_required") return "Review and accept this model's current privacy terms before sending a request.";
  if (status === 429) return "The assistant is busy. Wait for the active request to finish, then try again.";
  if (status === 503 && code === "assistant_cache_clear_pending") return "Temporary assistant data could not be cleared yet, so this conversation is still saved. Retry deletion shortly.";
  if (status === 503 && code === "assistant_worker_unavailable") return "The assistant worker is unavailable. Your workspace remains available.";
  if (status === 502) return "The selected provider could not complete this request.";
  if (status === 503) return "The assistant service is unavailable. Your workspace remains available.";
  return "The assistant request could not be completed. Review the conversation and try again.";
}

type ParsedSseFrame = { id: number; name: string; data: unknown };

const eventNames = new Set<AssistantEventName>([
  "meta", "token", "tool", "source", "proposed_action", "private_context_preview", "webfetch_preview", "complete", "error",
]);
const terminalStatuses = new Set(["completed", "cancelled", "failed", "timed_out"]);

export function parseAssistantSseFrame(frame: string): ParsedSseFrame | null {
  let idText = "";
  let eventName = "message";
  const dataLines: string[] = [];
  for (const line of frame.split(/\r?\n/)) {
    if (!line || line.startsWith(":")) continue;
    const separator = line.indexOf(":");
    const field = separator === -1 ? line : line.slice(0, separator);
    const value = separator === -1 ? "" : line.slice(separator + 1).replace(/^ /, "");
    if (field === "id") idText = value;
    else if (field === "event") eventName = value;
    else if (field === "data") dataLines.push(value);
  }
  if (!eventNames.has(eventName as AssistantEventName) || !dataLines.length) return null;
  const id = Number(idText);
  if (!Number.isSafeInteger(id) || id < 1) throw new TypeError("Assistant stream returned an invalid event cursor.");
  let data: unknown;
  try {
    data = JSON.parse(dataLines.join("\n"));
  } catch {
    throw new TypeError("Assistant stream returned malformed event data.");
  }
  if (!data || typeof data !== "object" || Array.isArray(data)) throw new TypeError("Assistant stream event must be an object.");
  return { id, name: eventName, data };
}

export async function consumeAssistantStream(
  response: Response,
  after: number,
  onEvent: (event: AssistantEventEnvelope) => void,
): Promise<number> {
  if (!response.body) throw new TypeError("Assistant stream did not include a readable event body.");
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let cursor = after;
  let terminal = false;
  let errorSeen = false;

  const consumeFrame = (frame: string) => {
    const parsed = parseAssistantSseFrame(frame);
    if (!parsed) return;
    if (terminal) throw new TypeError("Assistant stream continued after a terminal event.");
    if (parsed.id <= cursor) return;
    if (!eventNames.has(parsed.name as AssistantEventName)) return;
    if (parsed.name === "complete"
        && !terminalStatuses.has((parsed.data as Record<string, unknown>).status as string)) {
      throw new TypeError("Assistant stream returned an invalid terminal status.");
    }
    const event = { ...(parsed.data as Record<string, unknown>), type: parsed.name } as AssistantEvent;
    if (errorSeen && event.type !== "complete") throw new TypeError("Assistant stream continued after a turn error.");
    cursor = parsed.id;
    onEvent({ id: cursor, event });
    errorSeen = errorSeen || event.type === "error";
    // The service emits a sanitized error before its final complete event on failed turns.
    terminal = event.type === "complete";
  };

  try {
    while (true) {
      const { value, done } = await reader.read();
      buffer += done ? decoder.decode() : decoder.decode(value, { stream: true });
      let boundary = buffer.search(/\r?\n\r?\n/);
      while (boundary >= 0) {
        const frame = buffer.slice(0, boundary);
        const delimiter = buffer.slice(boundary).match(/^\r?\n\r?\n/)?.[0] ?? "\n\n";
        buffer = buffer.slice(boundary + delimiter.length);
        consumeFrame(frame);
        boundary = buffer.search(/\r?\n\r?\n/);
      }
      if (done) {
        break;
      }
    }
    if (buffer.trim()) consumeFrame(buffer);
  } finally {
    reader.releaseLock();
  }
  return cursor;
}

export function safeTermsUrl(value?: string | null): string | undefined {
  if (!value || value.length > 2048 || /[\u0000-\u0020\u007f\\]/.test(value)) return undefined;
  try {
    const url = new URL(value);
    const hostname = url.hostname.toLowerCase();
    const specialSuffixes = [".localhost", ".local", ".localdomain", ".internal", ".lan", ".home.arpa", ".test", ".invalid", ".example", ".onion"];
    const literalAddress = hostname.startsWith("[") || /^(?:\d{1,3}\.){3}\d{1,3}$/.test(hostname);
    const localName = hostname === "localhost" || specialSuffixes.some((suffix) => hostname.endsWith(suffix));
    return url.protocol === "https:" && !url.username && !url.password && !url.port
      && !literalAddress && !localName && hostname.includes(".") ? url.toString() : undefined;
  } catch {
    return undefined;
  }
}

/** Validate a native webfetch destination without rewriting its exact approved bytes. */
export function readPrivateWebFetchPreview(value: unknown): PrivateWebFetchPreview | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const item = value as Record<string, unknown>;
  const expectedKeys = [
    "preview_id", "url", "reason", "context_version", "expires_at", "confirmation_phrase",
  ];
  const actualKeys = Object.keys(item).filter((key) => key !== "type").sort();
  if (item.type !== undefined && item.type !== "webfetch_preview") return null;
  if (actualKeys.length !== expectedKeys.length
    || !actualKeys.every((key, index) => key === [...expectedKeys].sort()[index])) return null;
  if (typeof item.preview_id !== "string" || !/^[0-9a-f]{32}$/.test(item.preview_id)
    || typeof item.url !== "string" || item.url.length > 2048
    || /[\u0000-\u0020\u007f\\]/.test(item.url)
    || typeof item.reason !== "string" || item.reason.length > 300
    || /[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f-\u009f]/.test(item.reason)
    || typeof item.context_version !== "string" || !/^[a-f0-9]{64}$/.test(item.context_version)
    || typeof item.expires_at !== "string" || item.expires_at.length > 40
    || !Number.isFinite(Date.parse(item.expires_at))
    || typeof item.confirmation_phrase !== "string" || item.confirmation_phrase.length > 100
    || !item.confirmation_phrase) return null;
  try {
    const parsed = new URL(item.url);
    const host = parsed.hostname.toLowerCase();
    if (parsed.protocol !== "https:" || parsed.username || parsed.password || parsed.hash
      || (parsed.port && parsed.port !== "443") || !host || host.endsWith(".")) return null;
  } catch {
    return null;
  }
  return {
    preview_id: item.preview_id,
    // Preserve the original URL byte-for-byte. It is intentionally shown as text, not linked.
    url: item.url,
    reason: item.reason,
    context_version: item.context_version,
    expires_at: item.expires_at,
    confirmation_phrase: item.confirmation_phrase,
  };
}

/** Local citations may link only to the app's existing saved-result viewer. */
export function safeAssistantCitationUrl(value?: string | null): string | undefined {
  if (!value || value.length > 2048 || /[\u0000-\u0020\u007f\\]/.test(value)) return undefined;
  if (!value.startsWith("/")) return safeTermsUrl(value);
  if (value.startsWith("//")) return undefined;
  try {
    const url = new URL(value, "https://signal-ledger.invalid");
    const entries = [...url.searchParams.entries()];
    if (url.origin !== "https://signal-ledger.invalid" || url.pathname !== "/"
        || url.hash !== "#result-section" || entries.length !== 1
        || entries[0][0] !== "event_id" || !/^[1-9]\d{0,9}$/.test(entries[0][1])) return undefined;
    const eventId = Number(entries[0][1]);
    return Number.isSafeInteger(eventId) && eventId <= 2_147_483_647
      ? `/?event_id=${entries[0][1]}#result-section` : undefined;
  } catch {
    return undefined;
  }
}

export function readableTimestamp(value?: string | null): string {
  if (!value || Number.isNaN(Date.parse(value))) return "Date unavailable";
  return new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(new Date(value));
}
