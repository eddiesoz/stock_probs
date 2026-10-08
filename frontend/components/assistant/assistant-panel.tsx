"use client";

import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type FormEvent, type KeyboardEvent, type MouseEvent } from "react";

import { getAuthSession } from "../auth-client";
import { assistantRequest, assistantStreamFetch } from "./assistant-api-client";
import { AssistantAnswer } from "./assistant-answer";
import {
  assistantContextRequest,
  assistantContextUrl,
  assistantHistoryDestination,
  assistantErrorMessage,
  assistantTurnContext,
  consumeAssistantStream,
  readableTimestamp,
  readPrivateWebFetchPreview,
  readAssistantBrowserAction,
  safeAssistantDestination,
  safeAssistantCitationUrl,
  safeTermsUrl,
  AssistantClientError,
  type AssistantActionProposal,
  type AssistantContext,
  type AssistantContextRequest,
  type AssistantConversationDetail,
  type AssistantEvent,
  type AssistantMessage,
  type AssistantModel,
  type AssistantSource,
  type AssistantSavedAction,
  type AssistantStatus,
  type AssistantToolEvent,
  type AssistantTurnContext,
  type ConversationSummary,
  type PrivateSearchPreview,
  type PrivateWebFetchPreview,
} from "./assistant-contract";
import styles from "./assistant.module.css";

type LoadState = "loading" | "ready" | "error";
type StreamState = "idle" | "connecting" | "streaming" | "interrupted" | "complete" | "cancelled" | "failed";
type PanelErrorState = Readonly<{ message: string; owner: symbol | null }>;
type ActiveTurn = { conversationId: string; turnId: string };
type FocusRequest = {
  kind: "load" | "send" | "cancel";
  source: HTMLElement;
  target: HTMLElement | null;
  interaction: number;
  conversationId: string | null;
  generation: number;
};
type ActiveWebFetchPreview = PrivateWebFetchPreview & { turn_id: string };
type BusyOperation = { key: string; token: number };

const routeLabels: Record<AssistantContextRequest["route"], string> = {
  "/": "Forecast workspace",
  "/overview": "Overview",
  "/research": "Research",
  "/tools": "Research tools",
  "/tools/forecast": "Forecast tool",
  "/tools/live-trading": "Live Trading tool",
  "/tools/markets": "Markets tool",
  "/api-docs": "API reference",
  "/account": "Account",
  "/admin": "Administration",
};

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function listItems<T>(payload: unknown, key: string): T[] {
  const values = asRecord(payload)[key];
  return Array.isArray(values) ? values as T[] : [];
}

function readModel(value: unknown): AssistantModel | null {
  const item = asRecord(value);
  if (
    typeof item.id !== "string" || !item.id || typeof item.provider !== "string"
    || typeof item.name !== "string" || typeof item.policy_version !== "string"
    || typeof item.disclosure !== "string" || typeof item.free !== "boolean"
    || typeof item.training !== "string" || typeof item.availability !== "string"
  ) return null;
  const consentValue = asRecord(item.consent);
  const consent = typeof consentValue.accepted === "boolean" && typeof consentValue.data_collection_opt_in === "boolean"
    ? { accepted: consentValue.accepted, data_collection_opt_in: consentValue.data_collection_opt_in, accepted_at: typeof consentValue.accepted_at === "string" ? consentValue.accepted_at : null }
    : null;
  return {
    id: item.id,
    provider: item.provider,
    model_id: typeof item.model_id === "string" ? item.model_id : item.id,
    provider_id: typeof item.provider_id === "string" ? item.provider_id : item.provider,
    native_provider_id: typeof item.native_provider_id === "string" ? item.native_provider_id : undefined,
    name: item.name,
    availability: item.availability,
    available: item.available === true,
    enabled: item.enabled === true,
    usable: item.usable === true,
    free: item.free,
    training: item.training_uses_data === true ? "data_collection" : item.training_uses_data === false ? "no_training" : item.training,
    training_uses_data: typeof item.training_uses_data === "boolean" ? item.training_uses_data : item.training === "data_collection",
    terms_url: typeof item.terms_url === "string" ? item.terms_url : null,
    terms_reviewed_at: typeof item.terms_reviewed_at === "string" ? item.terms_reviewed_at : null,
    policy_version: item.policy_version,
    disclosure: item.disclosure,
    privacy_policy_version: typeof item.privacy_policy_version === "string" ? item.privacy_policy_version : item.policy_version,
    privacy_disclosure: typeof item.privacy_disclosure === "string" ? item.privacy_disclosure : item.disclosure,
    billing_class: typeof item.billing_class === "string" ? item.billing_class : item.free ? "free" : "paid",
    billing_policy_version: typeof item.billing_policy_version === "string" ? item.billing_policy_version : null,
    cost_disclosure: typeof item.cost_disclosure === "string" ? item.cost_disclosure : null,
    revision: Number.isSafeInteger(item.revision) && Number(item.revision) >= 0 ? Number(item.revision) : undefined,
    availability_reason: typeof item.availability_reason === "string" ? item.availability_reason.slice(0, 240) : null,
    consent,
  };
}

function readConversation(value: unknown): ConversationSummary | null {
  let item = asRecord(value);
  for (let depth = 0; depth < 2 && item.conversation && typeof item.conversation === "object"; depth += 1) {
    item = asRecord(item.conversation);
  }
  if (
    typeof item.id !== "string" || typeof item.title !== "string" || !Number.isSafeInteger(item.revision)
    || typeof item.created_at !== "string" || typeof item.updated_at !== "string"
  ) return null;
  return {
    id: item.id,
    title: item.title,
    revision: Number(item.revision),
    created_at: item.created_at,
    updated_at: item.updated_at,
    last_message_preview: typeof item.last_message_preview === "string" ? item.last_message_preview : null,
  };
}

function readSources(value: unknown): AssistantSource[] {
  if (!Array.isArray(value)) return [];
  return value.flatMap((item) => {
    const source = asRecord(item);
    if (typeof source.source_id !== "string" || typeof source.title !== "string") return [];
    return [{
      source_id: source.source_id,
      title: source.title,
      url: typeof source.url === "string" ? source.url : null,
      source_type: typeof source.source_type === "string" ? source.source_type : undefined,
      retrieved_at: typeof source.retrieved_at === "string" ? source.retrieved_at : null,
      as_of: typeof source.as_of === "string" ? source.as_of : null,
    }];
  });
}

function readMessages(value: unknown): AssistantMessage[] {
  return listItems<unknown>(value, "items").flatMap((item) => {
    const message = asRecord(item);
    if (
      typeof message.id !== "string" || !Number.isSafeInteger(message.seq)
      || !(message.role === "user" || message.role === "assistant" || message.role === "system")
      || typeof message.text !== "string" || typeof message.created_at !== "string"
    ) return [];
    const role = message.role as AssistantMessage["role"];
    return [{
      id: message.id,
      turn_id: typeof message.turn_id === "string" ? message.turn_id : null,
      seq: Number(message.seq),
      role,
      text: message.text,
      created_at: message.created_at,
      sources: readSources(message.sources),
    }];
  }).sort((a, b) => a.seq - b.seq);
}

function readSavedActions(value: unknown): AssistantSavedAction[] {
  if (!Array.isArray(value)) return [];
  return value.flatMap((item) => {
    const action = asRecord(item);
    if (typeof action.action_id !== "string" || typeof action.action_type !== "string"
        || typeof action.status !== "string" || typeof action.expires_at !== "string") return [];
    const rawReceipt = action.receipt;
    if (!rawReceipt || typeof rawReceipt !== "object" || Array.isArray(rawReceipt)) {
      return [{
        action_id: action.action_id,
        action_type: action.action_type,
        status: action.status,
        expires_at: action.expires_at,
        availability: action.availability as AssistantSavedAction["availability"],
        proposal: action.proposal && typeof action.proposal === "object" ? action.proposal as AssistantSavedAction["proposal"] : null,
        receipt: null,
      }];
    }
    const receipt = rawReceipt as Record<string, unknown>;
    if (typeof receipt.receipt_id !== "string" || typeof receipt.outcome !== "string" || typeof receipt.message !== "string") return [];
    const saved: AssistantSavedAction = {
      action_id: action.action_id,
      action_type: action.action_type,
      status: action.status,
      expires_at: action.expires_at,
      availability: action.availability as AssistantSavedAction["availability"],
      proposal: action.proposal && typeof action.proposal === "object" ? action.proposal as AssistantSavedAction["proposal"] : null,
      receipt: {
        receipt_id: receipt.receipt_id,
        outcome: receipt.outcome,
        message: receipt.message.slice(0, 500),
        destination: safeAssistantDestination(receipt.destination),
        browser_action: receipt.browser_action,
      },
    };
    return [saved];
  });
}

function readActionProposals(value: unknown): AssistantActionProposal[] {
  if (!Array.isArray(value)) return [];
  return value.flatMap((item) => {
    const action = asRecord(item);
    const card = asRecord(action.proposal);
    const changes = Array.isArray(card.changes) ? card.changes.flatMap((entry) => {
      const change = asRecord(entry);
      if (typeof change.label !== "string") return [];
      return [{ label: change.label.slice(0, 120), ...(change.after === undefined ? {} : { after: change.after as string | number | boolean | null }) }];
    }).slice(0, 24) : [];
    if (action.status !== "pending" || typeof action.action_id !== "string" || typeof action.action_type !== "string"
        || typeof action.expires_at !== "string" || typeof card.title !== "string"
        || typeof card.summary !== "string" || !Number.isSafeInteger(card.action_version)
        || typeof card.context_version !== "string") return [];
    const allowedAvailability = new Set(["confirmable", "different_session", "expired", "policy_changed", "authorization_required", "stale", "unavailable"]);
    const availability = typeof action.availability === "string" && allowedAvailability.has(action.availability)
      ? action.availability as AssistantActionProposal["availability"]
      : "unavailable";
    const confirmationPhrase = typeof card.confirmation_phrase === "string" ? card.confirmation_phrase : null;
    return [{
      action_id: action.action_id,
      action_type: action.action_type,
      title: card.title.slice(0, 160),
      summary: card.summary.slice(0, 500),
      changes,
      version: Number(card.action_version),
      expires_at: action.expires_at,
      confirmation_phrase: confirmationPhrase,
      context_version: card.context_version,
      availability,
    }];
  });
}

function readToolEvents(value: unknown): AssistantToolEvent[] {
  const items = asRecord(value).items;
  if (!Array.isArray(items)) return [];
  return items.flatMap((item) => {
    const event = asRecord(item);
    const data = asRecord(event.data);
    if (event.type !== "tool" || typeof data.name !== "string" || typeof data.status !== "string"
        || (typeof data.call_id !== "string" && typeof data.receipt_id !== "string")) return [];
    return [{
      name: data.name.slice(0, 80),
      call_id: (typeof data.call_id === "string" ? data.call_id : String(data.receipt_id)).slice(0, 128),
      receipt_id: typeof data.receipt_id === "string" ? data.receipt_id.slice(0, 80) : undefined,
      status: data.status,
      description: typeof data.description === "string" ? data.description.slice(0, 240) : undefined,
      result_bytes: Number.isSafeInteger(data.result_bytes) && Number(data.result_bytes) >= 0 ? Number(data.result_bytes) : undefined,
      result_sha256: typeof data.result_sha256 === "string" && /^[a-f0-9]{64}$/i.test(data.result_sha256) ? data.result_sha256 : undefined,
    }];
  });
}

function readPendingWebFetchReferences(
  value: unknown,
  activeTurnId: string,
): string[] {
  const items = asRecord(value).items;
  if (!Array.isArray(items)) return [];
  const seen = new Set<string>();
  for (const item of items) {
    const event = asRecord(item);
    const data = asRecord(event.data);
    if (event.type !== "webfetch_preview" || event.turn_id !== activeTurnId
      || typeof data.preview_id !== "string" || !/^[0-9a-f]{32}$/.test(data.preview_id)
      || typeof data.context_version !== "string" || !/^[a-f0-9]{64}$/.test(data.context_version)
      || typeof data.expires_at !== "string" || Date.parse(data.expires_at) <= Date.now()) continue;
    seen.add(data.preview_id);
  }
  return [...seen].slice(-8);
}

function readTurnContexts(detail: AssistantConversationDetail): Record<string, AssistantTurnContext> {
  const snapshots: Record<string, AssistantTurnContext> = {};
  for (const turn of Array.isArray(detail.turns) ? detail.turns : []) {
    const snapshot = turn.context;
    if (typeof turn.id === "string" && snapshot && routeLabels[snapshot.route] && typeof snapshot.context_version === "string") {
      snapshots[turn.id] = snapshot;
    }
  }
  return snapshots;
}

function readContextResponse(value: unknown, expectedRoute: AssistantContextRequest["route"]): AssistantContext {
  const payload = asRecord(value);
  const context = asRecord(payload.context);
  const preview = asRecord(payload.preview);
  if (context.route !== expectedRoute || typeof context.context_version !== "string" || !context.context_version || !Array.isArray(preview.fields)) {
    throw new Error("The workspace context response was malformed.");
  }
  const instrumentValue = context.instrument === null ? null : asRecord(context.instrument);
  const instrument = instrumentValue && typeof instrumentValue.symbol === "string"
      && /^[A-Z0-9][A-Z0-9.^-]{0,14}$/.test(instrumentValue.symbol)
      && (instrumentValue.asset_type === "stock" || instrumentValue.asset_type === "etf")
      && typeof instrumentValue.provider === "string" && /^[A-Za-z0-9][A-Za-z0-9 ._-]{0,79}$/.test(instrumentValue.provider)
      && typeof instrumentValue.exchange === "string" && /^[A-Za-z0-9][A-Za-z0-9 ._-]{0,79}$/.test(instrumentValue.exchange)
      && typeof instrumentValue.display_name === "string" && instrumentValue.display_name.length <= 200
    ? {
      symbol: instrumentValue.symbol,
      asset_type: instrumentValue.asset_type as "stock" | "etf",
      provider: instrumentValue.provider,
      exchange: instrumentValue.exchange,
      display_name: instrumentValue.display_name,
    }
    : null;
  if (context.instrument !== null && !instrument) throw new Error("The workspace returned an invalid canonical instrument identity.");
  const eventValue = context.event_ref === null ? null : asRecord(context.event_ref);
  const resultValue = context.result_ref === null ? null : asRecord(context.result_ref);
  const eventRef = eventValue && Number.isSafeInteger(eventValue.id)
    ? { id: Number(eventValue.id), version: typeof eventValue.version === "number" || typeof eventValue.version === "string" ? eventValue.version : null }
    : null;
  const resultRef = resultValue && Number.isSafeInteger(resultValue.id)
    ? { id: Number(resultValue.id), version: typeof resultValue.version === "number" || typeof resultValue.version === "string" ? resultValue.version : null }
    : null;
  if (typeof preview.summary !== "string" || preview.fields.some((field) => typeof field !== "string")) {
    throw new Error("The workspace context preview was malformed.");
  }
  return {
    route: expectedRoute,
    instrument,
    event_ref: eventRef,
    result_ref: resultRef,
    context_version: context.context_version,
    preview: { summary: preview.summary, fields: (preview.fields as string[]).slice(0, 20), note: typeof preview.note === "string" ? preview.note : undefined },
  };
}

function displayTitle(prompt: string): string {
  const title = prompt.trim().replace(/\s+/g, " ").slice(0, 72);
  return title || "Research conversation";
}

function conversationPath(id: string, tail = ""): string {
  return `/api/v1/assistant/conversations/${encodeURIComponent(id)}${tail}`;
}

function conversationDetailPath(
  id: string,
  messagePage = 1,
  actionPage = 1,
  eventPage = 1,
  actionPageSize = 100,
  eventPageSize = 100,
): string {
  return `${conversationPath(id)}?message_page=${messagePage}&message_page_size=50&action_page=${actionPage}&action_page_size=${actionPageSize}&event_page=${eventPage}&event_page_size=${eventPageSize}`;
}

function eventPath(conversationId: string, turnId: string): string {
  return `${conversationPath(conversationId)}/turns/${encodeURIComponent(turnId)}/events`;
}

function currentPath(): string {
  return `${window.location.pathname}`;
}

function browserActionIdentityMatches(action: Extract<ReturnType<typeof readAssistantBrowserAction>, { type: "notes.set" | "notes.clear" | "alerts.add" | "alerts.remove" }>, canonical: AssistantContext["instrument"] | undefined): boolean {
  return Boolean(canonical && action.payload.symbol === canonical.symbol && action.payload.asset_type === canonical.asset_type
    && action.payload.provider === canonical.provider && action.payload.exchange === canonical.exchange);
}

function marketChartIdentityMatches(action: Extract<ReturnType<typeof readAssistantBrowserAction>, { type: "market.chart_range.set" }>, canonical: AssistantContext["instrument"] | undefined): boolean {
  return Boolean(canonical && action.payload.symbol === canonical.symbol && action.payload.asset_type === canonical.asset_type
    && action.payload.provider === canonical.provider && action.payload.exchange === canonical.exchange);
}

function actionTypeLabel(value: string): string {
  const known: Record<string, string> = {
    "theme.set": "Change display theme",
    "watchlist.add": "Add instrument to watchlist",
    "watchlist.remove": "Remove instrument from watchlist",
    "portfolio.add": "Add portfolio holding",
    "portfolio.remove": "Remove portfolio holding",
    "portfolio.set_quantity": "Change portfolio quantity",
    "notes.create": "Create a research note",
    "notes.update": "Update a research note",
    "notes.set": "Open local note controls",
    "notes.clear": "Open local note controls",
    "alerts.create": "Create a research alert",
    "alerts.add": "Add a session-only price threshold",
    "alerts.remove": "Open current alert controls",
    "filters.apply": "Apply research filters",
    "market.filters.apply": "Apply Markets filters",
    "market.chart_range.set": "Change chart range",
    "market.columns.set": "Change quote columns",
    "market.refresh": "Refresh Markets data",
    "forecast.create": "Create a forecast",
    "forecast.reopen": "Open a saved forecast",
    "market.open": "Open market context",
    "history.export.csv": "Download CSV history",
    "history.export.json": "Download JSON history",
  };
  return known[value] ?? "Proposed workspace action";
}

function safeCitationHref(value?: string | null): string | undefined {
  return safeAssistantCitationUrl(value);
}

function citationLabel(source: AssistantSource): string {
  if (source.source_type === "native_search_text_unverified") {
    const date = source.as_of || source.retrieved_at;
    return date ? `Unverified search link · ${readableTimestamp(date)}` : "Unverified search link";
  }
  const date = source.as_of || source.retrieved_at;
  return date ? `${source.title} · ${readableTimestamp(date)}` : source.title;
}

function citationTypeLabel(source: AssistantSource): string | undefined {
  if (source.source_type === "native_search_text_unverified") {
    return "Parsed from retrieved search text; source attribution was not independently verified.";
  }
  return source.source_type;
}

function showWorkerReason(status: AssistantStatus | null): string {
  if (!status) return "Assistant status is unavailable. Your workspace is still available.";
  if (!status.enabled) return "Assistant features are disabled for this account.";
  if (!status.available && status.worker?.reason) return status.worker.reason;
  const state = status.worker?.status;
  if (state === "ready") return "Ready when you are. No research runs until you send a request.";
  if (status.worker?.reason) return status.worker.reason;
  return "The assistant worker is not ready. Your workspace is still available.";
}

function formatStorage(value: number, limit: number): string {
  const mb = (bytes: number) => `${(bytes / (1024 * 1024)).toFixed(1)} MiB`;
  return `${mb(value)} of ${mb(limit)}`;
}

function safeTurnError(code: string): string {
  const messages: Record<string, string> = {
    provider_unavailable: "The selected model provider is unavailable.",
    provider_policy_changed: "The model policy changed. Review the current privacy terms before continuing.",
    turn_timeout: "The response reached its time limit.",
    turn_cancelled: "The response was cancelled.",
    runtime_restarted: "The assistant stopped during a service restart.",
    tool_failed: "An approved research step could not finish.",
    tool_unavailable: "An approved research step is currently unavailable.",
    worker_unavailable: "The assistant worker is unavailable.",
    assistant_worker_unavailable: "The assistant worker is unavailable.",
    invalid_runtime_event: "The response could not be safely displayed.",
  };
  return messages[code] ?? "The assistant could not complete this turn.";
}

function selectedContextRequest(request: AssistantContextRequest, includeSelectedReferences: boolean): AssistantContextRequest {
  return includeSelectedReferences ? request : { route: request.route };
}

export function AssistantPanel({
  contextRequest,
  initialStatus,
  onClose,
  onLocalHandoff,
}: Readonly<{
  contextRequest: AssistantContextRequest;
  initialStatus: AssistantStatus;
  onClose: () => void;
  onLocalHandoff: (target: "notes-heading" | "alerts-heading", expectedHref: string) => void;
}>) {
  const panelRef = useRef<HTMLElement>(null);
  const headingRef = useRef<HTMLHeadingElement>(null);
  const resumeButtonRef = useRef<HTMLButtonElement>(null);
  const composerRef = useRef<HTMLTextAreaElement>(null);
  const cancelButtonRef = useRef<HTMLButtonElement>(null);
  const reconnectButtonRef = useRef<HTMLButtonElement>(null);
  const focusRequestRef = useRef<FocusRequest | null>(null);
  const focusInteractionRef = useRef(0);
  const panelMinimizedRef = useRef(false);
  const contextDetailsRef = useRef<HTMLDetailsElement>(null);
  const contextWasOpenBeforePrintRef = useRef<boolean | null>(null);
  const streamAbortRef = useRef<AbortController | null>(null);
  const cursorRef = useRef(0);
  const streamGeneration = useRef(0);
  const selectedConversationId = useRef<string | null>(null);
  const canceledRef = useRef(false);
  const contextKey = JSON.stringify(contextRequest);
  const [isMobile, setIsMobile] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const [minimized, setMinimized] = useState(false);
  // A minimized desktop strip must not leave a mobile dialog without its modal contents.
  const panelMinimized = minimized && !isMobile;
  const [status, setStatus] = useState<AssistantStatus | null>(initialStatus);
  const statusRef = useRef<AssistantStatus | null>(initialStatus);
  const readinessGenerationRef = useRef(0);
  const readinessRemainingRef = useRef(0);
  const readinessControllerRef = useRef<AbortController | null>(null);
  const readinessErrorRef = useRef<symbol | null>(null);
  const workerRecoveryErrorRef = useRef<symbol | null>(null);
  const modelLoadGenerationRef = useRef(0);
  const [readinessTick, setReadinessTick] = useState(0);
  const [readinessChecking, setReadinessChecking] = useState(false);
  const [pageVisible, setPageVisible] = useState(true);
  const [modelState, setModelState] = useState<LoadState>("loading");
  const [models, setModels] = useState<AssistantModel[]>([]);
  const [selectedModelId, setSelectedModelId] = useState("");
  const [acceptTerms, setAcceptTerms] = useState(false);
  const [allowCollection, setAllowCollection] = useState(false);
  const consentPolicyKeyRef = useRef("");
  const [consentBusy, setConsentBusy] = useState(false);
  const [contextState, setContextState] = useState<LoadState>("loading");
  const [context, setContext] = useState<AssistantContext | null>(null);
  const contextErrorRef = useRef<symbol | null>(null);
  const [includeContext, setIncludeContext] = useState(true);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [historyState, setHistoryState] = useState<LoadState>("loading");
  const [historyError, setHistoryError] = useState("");
  const [conversations, setConversations] = useState<ConversationSummary[]>([]);
  const [historyTotal, setHistoryTotal] = useState(0);
  const [historyPage, setHistoryPage] = useState(1);
  const [conversation, setConversation] = useState<AssistantConversationDetail["conversation"] | null>(null);
  const [messages, setMessages] = useState<AssistantMessage[]>([]);
  const [messagePage, setMessagePage] = useState(1);
  const [messageTotal, setMessageTotal] = useState(0);
  const [messagesLoading, setMessagesLoading] = useState(false);
  const [actionPagination, setActionPagination] = useState({ page: 1, page_size: 100, total: 0 });
  const [eventPagination, setEventPagination] = useState({ page: 1, page_size: 100, total: 0 });
  const [activityLoading, setActivityLoading] = useState(false);
  const [savedActions, setSavedActions] = useState<AssistantSavedAction[]>([]);
  const [turnContexts, setTurnContexts] = useState<Record<string, AssistantTurnContext>>({});
  const [conversationState, setConversationState] = useState<LoadState>("ready");
  const [titleDraft, setTitleDraft] = useState("");
  const [deletePhrase, setDeletePhrase] = useState("");
  const [showDelete, setShowDelete] = useState(false);
  const [prompt, setPrompt] = useState("");
  const [draft, setDraft] = useState("");
  const [draftSources, setDraftSources] = useState<AssistantSource[]>([]);
  const [toolEvents, setToolEvents] = useState<AssistantToolEvent[]>([]);
  const [actionProposals, setActionProposals] = useState<AssistantActionProposal[]>([]);
  const [searchPreviews, setSearchPreviews] = useState<PrivateSearchPreview[]>([]);
  const [webFetchPreviews, setWebFetchPreviews] = useState<ActiveWebFetchPreview[]>([]);
  const [activeTurn, setActiveTurn] = useState<ActiveTurn | null>(null);
  const activeTurnRef = useRef<ActiveTurn | null>(null);
  const [streamState, setStreamState] = useState<StreamState>("idle");
  const terminalEventRef = useRef<Extract<AssistantEvent, { type: "complete" }> | null>(null);
  const terminalTurnRef = useRef<ActiveTurn | null>(null);
  const [liveStatus, setLiveStatus] = useState("");
  const [panelErrorState, setPanelErrorState] = useState<PanelErrorState>({ message: "", owner: null });
  const panelError = panelErrorState.message;
  const setPanelError = useCallback((next: string | ((message: string) => string)) => {
    setPanelErrorState((current) => {
      if (typeof next !== "function") return { message: next, owner: null };
      const message = next(current.message);
      return message === current.message ? current : { message, owner: null };
    });
  }, []);
  const [busy, setBusy] = useState<string | null>(null);
  const busyOperationRef = useRef<BusyOperation | null>(null);
  const busyOperationSequence = useRef(0);
  const contextRequestGeneration = useRef(0);
  const conversationLoadGeneration = useRef(0);
  const historyLoadGeneration = useRef(0);
  const includeContextRef = useRef(includeContext);
  const selectedModel = useMemo(() => models.find((model) => model.id === selectedModelId) ?? null, [models, selectedModelId]);
  const consentPolicyKey = selectedModel ? JSON.stringify([
    selectedModel.id,
    selectedModel.policy_version,
    selectedModel.privacy_policy_version ?? selectedModel.policy_version,
    selectedModel.billing_policy_version ?? null,
  ]) : "";
  const modelConsentReady = selectedModel?.consent?.accepted === true
    && (selectedModel.training !== "data_collection" || selectedModel.consent.data_collection_opt_in === true);
  const modelUsable = selectedModel?.usable === true
    && selectedModel.enabled === true
    && selectedModel.available === true
    && selectedModel.availability === "available"
    && (selectedModel.training === "no_training" || selectedModel.training === "data_collection")
    && Boolean(safeTermsUrl(selectedModel.terms_url))
    && Boolean(selectedModel.terms_reviewed_at && Number.isFinite(Date.parse(selectedModel.terms_reviewed_at)));
  const workerReady = status?.available === true && status.enabled === true && status.worker?.status === "ready";
  const busyTurn = streamState === "connecting" || streamState === "streaming";
  panelMinimizedRef.current = panelMinimized;

  const clearOwnedPanelError = useCallback((owner: symbol) => {
    setPanelErrorState((current) => current.owner === owner ? { message: "", owner: null } : current);
  }, []);

  const clearContextError = useCallback(() => {
    const contextError = contextErrorRef.current;
    contextErrorRef.current = null;
    if (contextError) clearOwnedPanelError(contextError);
  }, [clearOwnedPanelError]);

  const reportContextError = useCallback((error: unknown) => {
    const message = error instanceof Error ? error.message : "Workspace context is unavailable.";
    const owner = Symbol("assistant-context-error");
    contextErrorRef.current = owner;
    setPanelErrorState({ message, owner });
  }, []);

  const refreshAssistantStatus = useCallback(async (startWindow = false, force = false): Promise<AssistantStatus | null> => {
    if (typeof document === "undefined" || document.visibilityState !== "visible" || panelMinimizedRef.current) return null;
    if (startWindow) readinessRemainingRef.current = 6;
    const current = statusRef.current;
    if (current && !current.enabled) {
      readinessRemainingRef.current = 0;
      return null;
    }
    if (readinessRemainingRef.current <= 0 || (readinessControllerRef.current && !force)) return null;
    readinessControllerRef.current?.abort();
    const generation = ++readinessGenerationRef.current;
    const controller = new AbortController();
    readinessControllerRef.current = controller;
    readinessRemainingRef.current -= 1;
    setReadinessChecking(true);
    try {
      const fresh = await assistantRequest<AssistantStatus>("/api/v1/assistant/status", { signal: controller.signal });
      if (generation !== readinessGenerationRef.current) return null;
      statusRef.current = fresh;
      setStatus(fresh);
      const workerIsReady = fresh.enabled && fresh.available && fresh.worker.status === "ready";
      if (!fresh.enabled || workerIsReady) {
        readinessRemainingRef.current = 0;
      }
      const readinessError = readinessErrorRef.current;
      readinessErrorRef.current = null;
      if (readinessError) clearOwnedPanelError(readinessError);
      if (workerIsReady) {
        const workerError = workerRecoveryErrorRef.current;
        workerRecoveryErrorRef.current = null;
        if (workerError) clearOwnedPanelError(workerError);
      }
      return fresh;
    } catch (error) {
      if (generation !== readinessGenerationRef.current || controller.signal.aborted) return null;
      const message = error instanceof Error ? error.message : "Assistant status is unavailable. Use Check readiness to try again.";
      const owner = Symbol("assistant-readiness-error");
      readinessErrorRef.current = owner;
      setPanelErrorState({ message, owner });
      return null;
    } finally {
      if (generation === readinessGenerationRef.current) {
        readinessControllerRef.current = null;
        setReadinessChecking(false);
        setReadinessTick((tick) => tick + 1);
      }
    }
  }, [clearOwnedPanelError]);

  function beginFocusRequest(
    kind: FocusRequest["kind"],
    source: HTMLElement | null | undefined,
    conversationId: string | null = selectedConversationId.current,
    generation = conversationLoadGeneration.current,
  ): FocusRequest | null {
    const request = source && panelRef.current?.contains(source)
      ? { kind, source, target: null, interaction: focusInteractionRef.current, conversationId, generation }
      : null;
    focusRequestRef.current = request;
    return request;
  }

  function currentFocusRequest(conversationId: string): FocusRequest | null {
    const request = focusRequestRef.current;
    return request
      && request.interaction === focusInteractionRef.current
      && request.conversationId === conversationId
      && request.generation === conversationLoadGeneration.current
      ? request
      : null;
  }

  function beginOwnedBusy(key: string): BusyOperation {
    const operation = { key, token: ++busyOperationSequence.current };
    busyOperationRef.current = operation;
    setBusy(key);
    return operation;
  }

  function finishOwnedBusy(operation: BusyOperation) {
    if (busyOperationRef.current !== operation) return;
    busyOperationRef.current = null;
    setBusy((current) => current === operation.key ? null : current);
  }

  useEffect(() => { activeTurnRef.current = activeTurn; }, [activeTurn]);

  useEffect(() => {
    const trackPointer = (event: globalThis.PointerEvent) => {
      if (focusRequestRef.current?.source === event.target) return;
      focusInteractionRef.current += 1;
    };
    const trackKey = (event: globalThis.KeyboardEvent) => {
      const request = focusRequestRef.current;
      const sourceIsEditable = request?.source instanceof HTMLInputElement
        || request?.source instanceof HTMLTextAreaElement;
      if (request && event.target === request.source && sourceIsEditable && event.key !== "Tab") return;
      focusInteractionRef.current += 1;
    };
    const trackFocus = (event: globalThis.FocusEvent) => {
      const request = focusRequestRef.current;
      if (!request || event.target === request.source || event.target === request.target) return;
      const sourceUnavailable = !request.source.isConnected || request.source.matches(":disabled");
      if (event.target === document.body && sourceUnavailable) return;
      focusInteractionRef.current += 1;
    };
    document.addEventListener("pointerdown", trackPointer, true);
    document.addEventListener("keydown", trackKey, true);
    document.addEventListener("focusin", trackFocus, true);
    return () => {
      document.removeEventListener("pointerdown", trackPointer, true);
      document.removeEventListener("keydown", trackKey, true);
      document.removeEventListener("focusin", trackFocus, true);
    };
  }, []);

  useLayoutEffect(() => {
    const request = focusRequestRef.current;
    if (!request) return;
    const panel = panelRef.current;
    const isCurrent = request.interaction === focusInteractionRef.current
      && request.generation === conversationLoadGeneration.current
      && request.conversationId === selectedConversationId.current
      && !panelMinimizedRef.current
      && panel?.isConnected === true;
    if (!isCurrent) {
      if (focusRequestRef.current === request) focusRequestRef.current = null;
      return;
    }

    const active = document.activeElement;
    const sourceUnavailable = !request.source.isConnected || request.source.matches(":disabled");
    const targetUnavailable = request.target !== null
      && (!request.target.isConnected || request.target.matches(":disabled"));
    const ownsFocus = active === request.source || active === request.target
      || (active === document.body && (sourceUnavailable || targetUnavailable));
    if (!ownsFocus) {
      focusRequestRef.current = null;
      return;
    }

    let target: HTMLElement | null = null;
    let finishRequest = false;
    if (busyTurn) {
      target = busy === "cancel" ? headingRef.current : cancelButtonRef.current;
    } else if (request.kind === "send" && busy === "send") {
      if (active === request.source && !sourceUnavailable) return;
      target = headingRef.current;
    } else if (request.kind === "cancel" && busy === "cancel") {
      target = headingRef.current;
    } else if (conversationState === "loading") {
      target = headingRef.current;
    } else {
      target = streamState === "interrupted" && activeTurn
        ? reconnectButtonRef.current
        : composerRef.current;
      finishRequest = true;
    }

    if (!target || target.matches(":disabled") || !panel?.contains(target)) return;
    request.target = target;
    if (document.activeElement !== target) target.focus({ preventScroll: true });
    if (finishRequest) focusRequestRef.current = null;
  }, [activeTurn, busy, busyTurn, conversationState, panelMinimized, streamState]);

  useEffect(() => {
    const media = window.matchMedia("(max-width: 699px)");
    const updateMobile = () => setIsMobile(media.matches);
    updateMobile();
    media.addEventListener("change", updateMobile);
    const syncViewport = () => {
      const viewport = window.visualViewport;
      const target = panelRef.current;
      if (!viewport || !target) return;
      target.style.setProperty("--assistant-visual-height", `${viewport.height}px`);
      target.style.setProperty("--assistant-visual-top", `${viewport.offsetTop}px`);
    };
    syncViewport();
    window.visualViewport?.addEventListener("resize", syncViewport);
    window.visualViewport?.addEventListener("scroll", syncViewport);
    window.addEventListener("resize", syncViewport);
    return () => {
      media.removeEventListener("change", updateMobile);
      window.visualViewport?.removeEventListener("resize", syncViewport);
      window.visualViewport?.removeEventListener("scroll", syncViewport);
      window.removeEventListener("resize", syncViewport);
      streamAbortRef.current?.abort();
      streamAbortRef.current = null;
    };
  }, []);

  useEffect(() => {
    const openContextForPrint = () => {
      const disclosure = contextDetailsRef.current;
      if (!disclosure) return;
      contextWasOpenBeforePrintRef.current = disclosure.open;
      disclosure.open = true;
    };
    const restoreContextAfterPrint = () => {
      const disclosure = contextDetailsRef.current;
      const wasOpen = contextWasOpenBeforePrintRef.current;
      if (disclosure && wasOpen !== null) disclosure.open = wasOpen;
      contextWasOpenBeforePrintRef.current = null;
    };
    window.addEventListener("beforeprint", openContextForPrint);
    window.addEventListener("afterprint", restoreContextAfterPrint);
    return () => {
      window.removeEventListener("beforeprint", openContextForPrint);
      window.removeEventListener("afterprint", restoreContextAfterPrint);
    };
  }, []);

  useEffect(() => {
    if (isMobile && minimized) setMinimized(false);
  }, [isMobile, minimized]);

  useEffect(() => {
    if (panelMinimized) {
      resumeButtonRef.current?.focus({ preventScroll: true });
      return;
    }
    (isMobile ? headingRef.current : panelRef.current)?.focus({ preventScroll: true });
  }, [isMobile, panelMinimized]);

  useEffect(() => {
    if (!isMobile || panelMinimized) return;
    const panel = panelRef.current;
    if (!panel) return;
    const focusableElements = () => [...panel.querySelectorAll<HTMLElement>(
      'a[href],button:not([disabled]),input:not([disabled]),select:not([disabled]),textarea:not([disabled]),[tabindex]:not([tabindex="-1"])',
    )].filter((element) => element.getAttribute("aria-hidden") !== "true" && element.getClientRects().length > 0);
    const trapTab = (event: globalThis.KeyboardEvent) => {
      if (event.key !== "Tab") return;
      const focusable = focusableElements();
      if (!focusable.length) {
        event.preventDefault();
        panel.focus();
        return;
      }
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      const active = document.activeElement;
      if (event.shiftKey && (!panel.contains(active) || active === first)) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && (!panel.contains(active) || active === last)) {
        event.preventDefault();
        first.focus();
      }
    };
    const restoreFocus = (event: FocusEvent) => {
      if (panel.contains(event.target as Node)) return;
      (focusableElements()[0] ?? panel).focus({ preventScroll: true });
    };
    document.addEventListener("keydown", trapTab, true);
    document.addEventListener("focusin", restoreFocus, true);
    return () => {
      document.removeEventListener("keydown", trapTab, true);
      document.removeEventListener("focusin", restoreFocus, true);
    };
  }, [isMobile, panelMinimized]);

  async function reloadContext() {
    const generation = ++contextRequestGeneration.current;
    const request = contextRequest;
    const selection = selectedContextRequest(request, includeContextRef.current);
    setContextState("loading");
    try {
      const response = await assistantRequest(assistantContextUrl(selection));
      if (generation !== contextRequestGeneration.current) return;
      setContext(readContextResponse(response, request.route));
      setContextState("ready");
      clearContextError();
    } catch (error) {
      if (generation !== contextRequestGeneration.current) return;
      setContext(null);
      setContextState("error");
      reportContextError(error);
    }
  }

  async function latestConfirmationContext(
    request: AssistantContextRequest = contextRequest,
  ): Promise<AssistantTurnContext> {
    for (let attempt = 0; attempt < 2; attempt += 1) {
      const generation = contextRequestGeneration.current;
      const selection = selectedContextRequest(request, includeContextRef.current);
      const response = await assistantRequest(assistantContextUrl(selection));
      if (generation === contextRequestGeneration.current) {
        return assistantTurnContext(readContextResponse(response, request.route));
      }
    }
    throw new AssistantClientError("The page context changed while it was being refreshed. Review the preview and try again.", 409, "stale_context");
  }

  async function loadConversations(page = 1, append = false) {
    const generation = ++historyLoadGeneration.current;
    setHistoryState("loading");
    setHistoryError("");
    try {
      const response = await assistantRequest<{ items?: unknown[]; total?: number; page?: number; page_size?: number }>(
        `/api/v1/assistant/conversations?page=${page}&page_size=20`,
      );
      if (generation !== historyLoadGeneration.current) return;
      const loaded = (Array.isArray(response.items) ? response.items : []).map(readConversation).filter((item): item is ConversationSummary => item !== null);
      setConversations((current) => append ? [...current, ...loaded] : loaded);
      setHistoryTotal(typeof response.total === "number" ? response.total : loaded.length);
      setHistoryPage(typeof response.page === "number" ? response.page : page);
      setHistoryState("ready");
    } catch (error) {
      if (generation !== historyLoadGeneration.current) return;
      setHistoryState("error");
      setHistoryError(error instanceof Error ? error.message : "Conversation history is unavailable.");
    }
  }

  async function loadModels() {
    const generation = ++modelLoadGenerationRef.current;
    setModelState("loading");
    try {
      const response = await assistantRequest<{ items?: unknown[] }>("/api/v1/assistant/models");
      if (generation !== modelLoadGenerationRef.current) return;
      const loaded = (Array.isArray(response.items) ? response.items : []).map(readModel).filter((item): item is AssistantModel => item !== null);
      setModels(loaded);
      setSelectedModelId((current) => {
        return current && loaded.some((model) => model.id === current) ? current : "";
      });
      setModelState("ready");
    } catch (error) {
      if (generation !== modelLoadGenerationRef.current) return;
      setModels([]);
      setModelState("error");
      setPanelError(error instanceof Error ? error.message : "The model catalog is unavailable.");
    }
  }

  function assistantErrorCode(error: unknown): string | null {
    return error instanceof AssistantClientError ? error.code : null;
  }

  async function reloadAfterPolicyChange(error: unknown, turnWasStarted = false) {
    setAcceptTerms(false);
    setAllowCollection(false);
    await loadModels();
    setPanelError(error instanceof Error
      ? error.message
      : "The model policy changed. Review the current privacy terms before continuing.");
    setLiveStatus(turnWasStarted
      ? "The assistant turn stopped because its model policy changed. Review the current terms before continuing."
      : "No assistant turn was started. Review the current model terms before continuing.");
  }

  useLayoutEffect(() => {
    if (consentPolicyKeyRef.current === consentPolicyKey) return;
    consentPolicyKeyRef.current = consentPolicyKey;
    setAcceptTerms(false);
    setAllowCollection(false);
  }, [consentPolicyKey]);

  useLayoutEffect(() => {
    statusRef.current = initialStatus;
    setStatus(initialStatus);
    readinessControllerRef.current?.abort();
    readinessControllerRef.current = null;
    readinessGenerationRef.current += 1;
    setReadinessChecking(false);
    const isReady = initialStatus.available && initialStatus.enabled && initialStatus.worker.status === "ready";
    readinessRemainingRef.current = initialStatus.enabled && !isReady ? 6 : 0;
    if (isReady) {
      const workerError = workerRecoveryErrorRef.current;
      workerRecoveryErrorRef.current = null;
      if (workerError) clearOwnedPanelError(workerError);
    }
    if (!isReady && initialStatus.enabled) void refreshAssistantStatus(true, true);
    return () => {
      readinessGenerationRef.current += 1;
      readinessControllerRef.current?.abort();
      readinessControllerRef.current = null;
    };
  }, [initialStatus, refreshAssistantStatus, clearOwnedPanelError]);

  useEffect(() => {
    const visible = () => {
      const nextVisible = document.visibilityState === "visible";
      setPageVisible(nextVisible);
      if (!nextVisible) {
        readinessGenerationRef.current += 1;
        readinessControllerRef.current?.abort();
        readinessControllerRef.current = null;
        setReadinessChecking(false);
      } else if (statusRef.current?.enabled
          && !(statusRef.current.available && statusRef.current.worker.status === "ready")) {
        void refreshAssistantStatus(true, true);
      }
    };
    document.addEventListener("visibilitychange", visible);
    setPageVisible(document.visibilityState === "visible");
    return () => {
      document.removeEventListener("visibilitychange", visible);
      readinessGenerationRef.current += 1;
      readinessControllerRef.current?.abort();
      readinessControllerRef.current = null;
    };
  }, [refreshAssistantStatus]);

  useEffect(() => {
    if (panelMinimized) {
      readinessGenerationRef.current += 1;
      readinessControllerRef.current?.abort();
      readinessControllerRef.current = null;
      setReadinessChecking(false);
    }
  }, [panelMinimized]);

  useEffect(() => {
    const current = statusRef.current;
    if (!pageVisible || panelMinimized || !current?.enabled
        || (current.available && current.worker.status === "ready")
        || readinessRemainingRef.current <= 0) return;
    const timer = window.setTimeout(() => { void refreshAssistantStatus(); }, 5000);
    return () => window.clearTimeout(timer);
  }, [status, pageVisible, panelMinimized, readinessTick, refreshAssistantStatus]);

  useEffect(() => {
    let current = true;
    void (async () => {
      try {
        const session = await getAuthSession();
        if (!current || !session?.authenticated) {
          if (current) setPanelError("Your session ended. Sign in again before continuing.");
          return;
        }
        await Promise.all([loadModels(), loadConversations()]);
      } catch (error) {
        if (current) setPanelError(error instanceof Error ? error.message : "Assistant status is unavailable.");
      }
    })();
    return () => { current = false; };
  }, []);

  useEffect(() => {
    if (!conversation) return;
    setTitleDraft(conversation.title);
  }, [conversation?.id]);

  useEffect(() => {
    let current = true;
    const generation = ++contextRequestGeneration.current;
    void (async () => {
      setContextState("loading");
      try {
        const selection = selectedContextRequest(contextRequest, includeContextRef.current);
        const response = await assistantRequest(assistantContextUrl(selection));
        if (!current || generation !== contextRequestGeneration.current) return;
        setContext(readContextResponse(response, contextRequest.route));
        setContextState("ready");
        clearContextError();
      } catch (error) {
        if (!current || generation !== contextRequestGeneration.current) return;
        setContext(null);
        setContextState("error");
        reportContextError(error);
      }
    })();
    return () => { current = false; };
  }, [contextKey, includeContext, clearContextError, reportContextError]);

  function handlePanelKeyDown(event: KeyboardEvent<HTMLElement>) {
    if (event.key === "Escape") {
      if (searchPreviews.length) {
        event.preventDefault();
        setSearchPreviews([]);
        setLiveStatus("The private search preview was closed. No search was approved.");
        return;
      }
      if (webFetchPreviews.length) {
        event.preventDefault();
        void confirmWebFetch(webFetchPreviews[0], false);
        return;
      }
      if (actionProposals.length) {
        event.preventDefault();
        setActionProposals([]);
        setLiveStatus("The action preview was closed. No action was applied.");
        return;
      }
      event.preventDefault();
      onClose();
    }
  }

  async function loadConversation(id: string, preserveBusy = false, focusRequest?: FocusRequest | null): Promise<number | undefined> {
    const previousConversationId = selectedConversationId.current;
    selectedConversationId.current = id;
    const generation = ++conversationLoadGeneration.current;
    if (focusRequest && focusRequestRef.current === focusRequest) {
      focusRequest.conversationId = id;
      focusRequest.generation = generation;
    }
    if (previousConversationId !== id) {
      streamGeneration.current += 1;
      streamAbortRef.current?.abort();
      streamAbortRef.current = null;
      terminalEventRef.current = null;
      terminalTurnRef.current = null;
      cursorRef.current = 0;
      setConversation(null);
      setTurnContexts({});
      setActiveTurn(null);
      setStreamState("idle");
      if (!preserveBusy) setBusy(null);
    }
    setConversationState("loading");
    setMessagesLoading(false);
    setActivityLoading(false);
    setPanelError("");
    setDraft("");
    setDraftSources([]);
    setToolEvents([]);
    setActionProposals([]);
    setSearchPreviews([]);
    setWebFetchPreviews([]);
    setSavedActions([]);
    setMessages([]);
    setPrompt("");
    setDeletePhrase("");
    setShowDelete(false);
    try {
      const detail = await assistantRequest<AssistantConversationDetail>(conversationDetailPath(id));
      if (generation !== conversationLoadGeneration.current) return;
      const safeSummary = readConversation(detail.conversation);
      if (!safeSummary || typeof detail.conversation.delete_confirmation_phrase !== "string") throw new Error("The saved conversation response was malformed.");
      setConversation({ ...safeSummary, delete_confirmation_phrase: detail.conversation.delete_confirmation_phrase });
      setMessages(readMessages(detail.messages));
      setMessagePage(typeof detail.messages.page === "number" ? detail.messages.page : 1);
      setMessageTotal(typeof detail.messages.total === "number" ? detail.messages.total : 0);
      setSavedActions(readSavedActions(detail.actions));
      setActionProposals(readActionProposals(detail.actions));
      setToolEvents(readToolEvents(detail.events));
      const actionPageInfo = detail.action_pagination;
      const eventPageInfo = detail.events;
      setActionPagination({
        page: actionPageInfo && Number.isSafeInteger(actionPageInfo.page) ? actionPageInfo.page : 1,
        page_size: actionPageInfo && Number.isSafeInteger(actionPageInfo.page_size) ? actionPageInfo.page_size : 100,
        total: actionPageInfo && Number.isSafeInteger(actionPageInfo.total) ? actionPageInfo.total : 0,
      });
      setEventPagination({
        page: eventPageInfo && Number.isSafeInteger(eventPageInfo.page) ? eventPageInfo.page : 1,
        page_size: eventPageInfo && Number.isSafeInteger(eventPageInfo.page_size) ? eventPageInfo.page_size : 100,
        total: eventPageInfo && Number.isSafeInteger(eventPageInfo.total) ? eventPageInfo.total : 0,
      });
      setTurnContexts(readTurnContexts(detail));
      setConversationState("ready");
      const currentTurn = Array.isArray(detail.turns)
        ? detail.turns.find((turn) => ["running", "queued", "streaming", "pending"].includes(turn.status))
        : undefined;
      if (currentTurn) {
        const pendingFetchRefs = readPendingWebFetchReferences(detail.events, currentTurn.id);
        const pendingFetches = await Promise.all(pendingFetchRefs.map(async (previewId) => {
          try {
            const payload = await assistantRequest<{ preview?: unknown }>(
              `${conversationPath(id)}/turns/${encodeURIComponent(currentTurn.id)}/webfetch-previews/${encodeURIComponent(previewId)}`,
            );
            const preview = readPrivateWebFetchPreview(payload.preview);
            return preview ? { ...preview, turn_id: currentTurn.id } : null;
          } catch {
            return null;
          }
        }));
        if (generation !== conversationLoadGeneration.current) return;
        setWebFetchPreviews(pendingFetches.filter((preview): preview is ActiveWebFetchPreview => preview !== null));
        const sameTerminalTurn = terminalTurnRef.current?.conversationId === id
          && terminalTurnRef.current.turnId === currentTurn.id;
        if (!sameTerminalTurn) {
          terminalEventRef.current = null;
          terminalTurnRef.current = { conversationId: id, turnId: currentTurn.id };
          cursorRef.current = 0;
        }
        setActiveTurn({ conversationId: id, turnId: currentTurn.id });
        setStreamState("interrupted");
        setLiveStatus("A response was interrupted. Reconnect to its saved event stream.");
      } else {
        terminalEventRef.current = null;
        terminalTurnRef.current = null;
        cursorRef.current = 0;
        setActiveTurn(null);
        setStreamState("idle");
      }
      setHistoryOpen(false);
    } catch (error) {
      if (generation !== conversationLoadGeneration.current) return;
      setConversationState("error");
      setPanelError(error instanceof Error ? error.message : "The saved conversation could not be opened.");
      return;
    }
    return generation;
  }

  async function loadEarlierMessages() {
    if (!conversation || messagesLoading || messages.length >= messageTotal) return;
    const conversationId = conversation.id;
    const generation = conversationLoadGeneration.current;
    setMessagesLoading(true);
    try {
      const nextPage = messagePage + 1;
      const detail = await assistantRequest<AssistantConversationDetail>(conversationDetailPath(
        conversationId,
        nextPage,
        actionPagination.page,
        eventPagination.page,
        actionPagination.page_size,
        eventPagination.page_size,
      ));
      if (generation !== conversationLoadGeneration.current || selectedConversationId.current !== conversationId) return;
      const older = readMessages(detail.messages);
      setMessages((current) => {
        if (generation !== conversationLoadGeneration.current || selectedConversationId.current !== conversationId) return current;
        const merged = new Map(current.map((message) => [message.id, message]));
        older.forEach((message) => merged.set(message.id, message));
        return [...merged.values()].sort((a, b) => a.seq - b.seq);
      });
      setMessagePage(typeof detail.messages.page === "number" ? detail.messages.page : nextPage);
      setMessageTotal(typeof detail.messages.total === "number" ? detail.messages.total : messageTotal);
      setSavedActions(readSavedActions(detail.actions));
      setActionProposals(readActionProposals(detail.actions));
      setToolEvents(readToolEvents(detail.events));
      setTurnContexts((current) => ({ ...current, ...readTurnContexts(detail) }));
    } catch (error) {
      if (generation !== conversationLoadGeneration.current || selectedConversationId.current !== conversationId) return;
      setPanelError(error instanceof Error ? error.message : "Earlier conversation messages could not be loaded.");
    } finally {
      if (generation === conversationLoadGeneration.current && selectedConversationId.current === conversationId) {
        setMessagesLoading(false);
      }
    }
  }

  async function loadActivityPage(kind: "actions" | "events", direction: "older" | "newer") {
    if (!conversation || activityLoading) return;
    const conversationId = conversation.id;
    const generation = conversationLoadGeneration.current;
    const selectedPage = kind === "actions" ? actionPagination.page : eventPagination.page;
    const pageCount = Math.max(1, Math.ceil((kind === "actions" ? actionPagination.total / actionPagination.page_size : eventPagination.total / eventPagination.page_size)));
    const page = direction === "older" ? Math.min(pageCount, selectedPage + 1) : Math.max(1, selectedPage - 1);
    if (page === selectedPage) return;
    const actionPage = kind === "actions" ? page : actionPagination.page;
    const eventPage = kind === "events" ? page : eventPagination.page;
    setActivityLoading(true);
    try {
      const detail = await assistantRequest<AssistantConversationDetail>(conversationDetailPath(
        conversationId,
        messagePage,
        actionPage,
        eventPage,
        actionPagination.page_size,
        eventPagination.page_size,
      ));
      if (generation !== conversationLoadGeneration.current || selectedConversationId.current !== conversationId) return;
      setTurnContexts((current) => ({ ...current, ...readTurnContexts(detail) }));
      if (kind === "actions") {
        setSavedActions(readSavedActions(detail.actions));
        setActionProposals(readActionProposals(detail.actions));
        const pageInfo = detail.action_pagination;
        setActionPagination({
          page: pageInfo && Number.isSafeInteger(pageInfo.page) ? pageInfo.page : page,
          page_size: pageInfo && Number.isSafeInteger(pageInfo.page_size) ? pageInfo.page_size : actionPagination.page_size,
          total: pageInfo && Number.isSafeInteger(pageInfo.total) ? pageInfo.total : actionPagination.total,
        });
      } else {
        setToolEvents(readToolEvents(detail.events));
        const pageInfo = detail.events;
        setEventPagination({
          page: pageInfo && Number.isSafeInteger(pageInfo.page) ? pageInfo.page : page,
          page_size: pageInfo && Number.isSafeInteger(pageInfo.page_size) ? pageInfo.page_size : eventPagination.page_size,
          total: pageInfo && Number.isSafeInteger(pageInfo.total) ? pageInfo.total : eventPagination.total,
        });
      }
    } catch (error) {
      if (generation !== conversationLoadGeneration.current || selectedConversationId.current !== conversationId) return;
      setPanelError(error instanceof Error ? error.message : "Saved assistant activity could not be loaded.");
    } finally {
      if (generation === conversationLoadGeneration.current && selectedConversationId.current === conversationId) setActivityLoading(false);
    }
  }

  async function createConversation(
    title = "Research conversation",
    turnContext: AssistantTurnContext | null = context ? assistantTurnContext(context) : null,
    focusRequest?: FocusRequest | null,
  ) {
    const previousConversationId = selectedConversationId.current;
    const previousGeneration = conversationLoadGeneration.current;
    const response = await assistantRequest<ConversationSummary>("/api/v1/assistant/conversations", {
      method: "POST",
      body: JSON.stringify({ title: title.slice(0, 120), context: turnContext }),
    });
    const created = readConversation(response);
    if (!created) throw new Error("The assistant returned a malformed new conversation.");
    await loadConversations(1, false);
    if (selectedConversationId.current === previousConversationId
        && conversationLoadGeneration.current === previousGeneration) {
      await loadConversation(created.id, true, focusRequest);
    }
    return created.id;
  }

  async function createNewConversation(event: MouseEvent<HTMLButtonElement>) {
    const focusRequest = beginFocusRequest("load", event.currentTarget);
    setBusy("new-conversation");
    setPanelError("");
    try {
      await createConversation("Research conversation", await latestConfirmationContext(), focusRequest);
      setLiveStatus("New conversation created. No assistant request has been sent.");
    } catch (error) {
      setPanelError(error instanceof Error ? error.message : "A new conversation could not be created.");
    } finally {
      setBusy(null);
    }
  }

  async function saveTitle(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!conversation || !titleDraft.trim()) return;
    setBusy("rename");
    setPanelError("");
    try {
      const updated = await assistantRequest<ConversationSummary>(conversationPath(conversation.id), {
        method: "PATCH",
        body: JSON.stringify({ title: titleDraft.trim().slice(0, 120), expected_revision: conversation.revision }),
      });
      const summary = readConversation(updated);
      if (!summary) throw new Error("The assistant returned a malformed conversation update.");
      setConversation({ ...summary, delete_confirmation_phrase: conversation.delete_confirmation_phrase });
      await loadConversations(1, false);
      setLiveStatus("Conversation title saved.");
    } catch (error) {
      setPanelError(error instanceof Error ? error.message : "The conversation title could not be saved.");
    } finally {
      setBusy(null);
    }
  }

  async function deleteConversation() {
    if (!conversation || deletePhrase !== conversation.delete_confirmation_phrase) return;
    const deletedId = conversation.id;
    setBusy("delete");
    setPanelError("");
    try {
      await assistantRequest(conversationPath(deletedId), {
        method: "DELETE",
        body: JSON.stringify({ expected_revision: conversation.revision, confirmation_phrase: deletePhrase }),
      });
      if (selectedConversationId.current === deletedId) clearConversationView();
      setDeletePhrase("");
      setShowDelete(false);
      await loadConversations(1, false);
      setLiveStatus("Conversation deleted. Its compact deletion record remains for audit purposes.");
    } catch (error) {
      setPanelError(error instanceof Error ? error.message : "The conversation could not be deleted.");
    } finally {
      setBusy(null);
    }
  }

  function clearConversationView() {
    conversationLoadGeneration.current += 1;
    streamGeneration.current += 1;
    selectedConversationId.current = null;
    streamAbortRef.current?.abort();
    streamAbortRef.current = null;
    setConversation(null);
    setMessages([]);
    setMessagePage(1);
    setMessageTotal(0);
    setActionPagination({ page: 1, page_size: 100, total: 0 });
    setEventPagination({ page: 1, page_size: 100, total: 0 });
    setTurnContexts({});
    setSavedActions([]);
    setActionProposals([]);
    setSearchPreviews([]);
    setWebFetchPreviews([]);
    setDraft("");
    setDraftSources([]);
    setToolEvents([]);
    setPrompt("");
    setActiveTurn(null);
    setStreamState("idle");
    terminalEventRef.current = null;
    terminalTurnRef.current = null;
    cursorRef.current = 0;
    setConversationState("ready");
    setMessagesLoading(false);
    setActivityLoading(false);
    setTitleDraft("");
    setDeletePhrase("");
    setShowDelete(false);
    setPanelError("");
    setLiveStatus("");
  }

  async function loadMoreHistory() {
    await loadConversations(historyPage + 1, true);
  }

  async function acceptModelConsent() {
    if (!selectedModel || !acceptTerms || (selectedModel.training === "data_collection" && !allowCollection)) return;
    setConsentBusy(true);
    setPanelError("");
    try {
      await assistantRequest(`/api/v1/assistant/models/${encodeURIComponent(selectedModel.id)}/consent`, {
        method: "PUT",
        body: JSON.stringify({ policy_version: selectedModel.policy_version, accepted_terms: true, data_collection_opt_in: allowCollection }),
      });
      await loadModels();
      setAcceptTerms(false);
      setAllowCollection(false);
      setLiveStatus("Model privacy consent saved for this policy version.");
    } catch (error) {
      if (["policy_version", "provider_policy_changed"].includes(assistantErrorCode(error) ?? "")) {
        await reloadAfterPolicyChange(error);
      } else {
        setPanelError(error instanceof Error ? error.message : "Model consent could not be saved.");
      }
    } finally {
      setConsentBusy(false);
    }
  }

  async function connectToTurn(turn: ActiveTurn, focusRequest?: FocusRequest | null) {
    if (busyTurn) return;
    const generation = ++streamGeneration.current;
    const sameTurn = terminalTurnRef.current?.conversationId === turn.conversationId
      && terminalTurnRef.current.turnId === turn.turnId;
    if (!sameTurn) {
      terminalEventRef.current = null;
      terminalTurnRef.current = turn;
    }
    setActiveTurn(turn);
    setStreamState("connecting");
    setLiveStatus("Connecting to the saved assistant response…");
    setPanelError("");
    canceledRef.current = false;
    const controller = new AbortController();
    streamAbortRef.current = controller;
    try {
      const response = await assistantStreamFetch(eventPath(turn.conversationId, turn.turnId), controller.signal, cursorRef.current);
      if (generation !== streamGeneration.current || selectedConversationId.current !== turn.conversationId) return;
      setStreamState("streaming");
      setLiveStatus("Assistant response streaming.");
      const nextCursor = await consumeAssistantStream(response, cursorRef.current, ({ id, event }) => {
        if (generation !== streamGeneration.current || selectedConversationId.current !== turn.conversationId) return;
        cursorRef.current = id;
        handleAssistantEvent(event, turn);
      });
      if (generation !== streamGeneration.current || selectedConversationId.current !== turn.conversationId) return;
      cursorRef.current = nextCursor;
      if (canceledRef.current) {
        setStreamState("cancelled");
      } else if (terminalEventRef.current) {
        const terminal = terminalEventRef.current as Extract<AssistantEvent, { type: "complete" }>;
        setActiveTurn(null);
        if (terminal.status === "completed") {
          setStreamState("complete");
          setPanelError("");
          setLiveStatus("Assistant response complete.");
        } else if (terminal.status === "cancelled") {
          setStreamState("cancelled");
          setLiveStatus("Response cancelled. Review the saved conversation for its final state.");
        } else {
          setStreamState("failed");
          setPanelError(terminal.status === "timed_out"
            ? "The response timed out before it finished. Review any action receipts and reopen the conversation to check the saved state."
            : "The response did not finish. Review any action receipts and reopen the conversation to check the saved state.");
          setLiveStatus("The assistant turn ended without a completed answer.");
        }
        void loadConversation(turn.conversationId, false, focusRequest ?? currentFocusRequest(turn.conversationId));
      } else if (streamAbortRef.current === controller) {
        setStreamState((current) => current === "failed" ? current : "interrupted");
        setLiveStatus("The response stream ended without a completion event. Reconnect to continue.");
      }
    } catch (error) {
      if (generation !== streamGeneration.current || selectedConversationId.current !== turn.conversationId) return;
      if (canceledRef.current || controller.signal.aborted) return;
      const terminalFailure = error instanceof AssistantClientError && [401, 403, 404].includes(error.status);
      setStreamState(terminalFailure ? "failed" : "interrupted");
      if (terminalFailure) setActiveTurn(null);
      setLiveStatus(terminalFailure ? "Access to this response is no longer available." : "The response connection was interrupted. Reconnect to replay events after the last received item.");
      setPanelError(error instanceof Error ? error.message : "The assistant response stream was interrupted.");
    } finally {
      if (streamAbortRef.current === controller) streamAbortRef.current = null;
    }
  }

  function handleAssistantEvent(event: AssistantEvent, turn: ActiveTurn) {
    if (event.type === "meta") {
      setLiveStatus(`Using ${models.find((model) => model.id === event.model_id)?.name ?? "the selected model"}.`);
    } else if (event.type === "token") {
      setDraft((current) => current + event.text);
      setLiveStatus("Assistant response is updating.");
    } else if (event.type === "tool") {
      setToolEvents((current) => {
        const callId = event.call_id || event.receipt_id || `${event.name}:${current.length}`;
        const next = current.filter((item) => item.call_id !== callId);
        return [...next, {
          name: event.name,
          call_id: callId,
          receipt_id: event.receipt_id,
          status: event.status,
          description: event.description,
          result_bytes: event.result_bytes,
          result_sha256: event.result_sha256,
        }];
      });
      setLiveStatus(`${event.name.replaceAll("_", " ")} ${event.status}.`);
    } else if (event.type === "source") {
      setDraftSources((current) => current.some((source) => source.source_id === event.source_id)
        ? current
        : [...current, { source_id: event.source_id, title: event.title, url: event.url, source_type: event.source_type, retrieved_at: event.retrieved_at, as_of: event.as_of }]);
    } else if (event.type === "proposed_action") {
      setActionProposals((current) => [...current.filter((item) => item.action_id !== event.action_id), { ...event, availability: "confirmable" }]);
      setLiveStatus("An action preview needs your review. No change has been applied.");
    } else if (event.type === "private_context_preview") {
      setSearchPreviews((current) => [...current.filter((item) => item.preview_id !== event.preview_id), event]);
      setLiveStatus("A public search would include private context. Review the exact query before allowing it.");
    } else if (event.type === "webfetch_preview") {
      const preview = readPrivateWebFetchPreview(event);
      if (!preview) {
        setPanelError("The web page request preview was malformed. No page was fetched.");
        setLiveStatus("The web page request could not be confirmed.");
        return;
      }
      setWebFetchPreviews((current) => [
        ...current.filter((item) => item.preview_id !== preview.preview_id),
        { ...preview, turn_id: turn.turnId },
      ]);
      setLiveStatus("A web page request needs approval. Inspect the exact URL before it is sent.");
    } else if (event.type === "complete") {
      terminalEventRef.current = event;
      setLiveStatus("The assistant response is finishing.");
    } else if (event.type === "error") {
      setPanelError(safeTurnError(event.code));
      setLiveStatus("The assistant reported a turn error. Checking its final status.");
      if (event.code === "provider_policy_changed") void reloadAfterPolicyChange(new AssistantClientError(safeTurnError(event.code), 409, event.code), true);
      if (event.code === "worker_unavailable" || event.code === "assistant_worker_unavailable" || event.code === "runtime_restarted") void refreshAssistantStatus(true, true);
    }
  }

  async function startTurn(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const text = prompt.trim();
    if (!text || !selectedModel || !modelUsable || !modelConsentReady || !workerReady || busyTurn
        || conversationState === "loading") return;
    if (contextState !== "ready" || !context) {
      setPanelError("Review the current page context before sending.");
      return;
    }
    const startingConversationId = conversation?.id ?? null;
    const startingGeneration = conversationLoadGeneration.current;
    const contextGeneration = contextRequestGeneration.current;
    const routeAtStart = currentPath();
    let expectedConversationId = startingConversationId;
    let expectedGeneration = startingGeneration;
    const isCurrentSelection = () => expectedGeneration === conversationLoadGeneration.current
      && selectedConversationId.current === expectedConversationId;
    const isStartingSelectionCurrent = () => startingGeneration === conversationLoadGeneration.current
      && selectedConversationId.current === startingConversationId;
    const isStartingContextCurrent = () => isStartingSelectionCurrent()
      && contextGeneration === contextRequestGeneration.current
      && routeAtStart === currentPath();
    const submitter = event.nativeEvent instanceof SubmitEvent ? event.nativeEvent.submitter : null;
    const activeElement = document.activeElement;
    const focusSource = submitter instanceof HTMLElement
      ? submitter
      : activeElement instanceof HTMLElement ? activeElement : composerRef.current;
    const focusRequest = beginFocusRequest("send", focusSource, startingConversationId, startingGeneration);
    setBusy("send");
    setPanelError("");
    setDraft("");
    setDraftSources([]);
    setToolEvents([]);
    setActionProposals([]);
    setSearchPreviews([]);
    setWebFetchPreviews([]);
    cursorRef.current = 0;
    try {
      const turnContext = await latestConfirmationContext();
      if (!isStartingContextCurrent()) return;
      const conversationId = startingConversationId ?? await createConversation(displayTitle(text), turnContext, focusRequest);
      if (startingConversationId === null) {
        expectedConversationId = conversationId;
        expectedGeneration = conversationLoadGeneration.current;
      }
      if (!isCurrentSelection() || contextGeneration !== contextRequestGeneration.current || routeAtStart !== currentPath()) return;
      const turnEnvelope = await assistantRequest<{ turn?: unknown }>(`${conversationPath(conversationId)}/turns`, {
        method: "POST",
        body: JSON.stringify({
          prompt: text,
          model_id: selectedModel.id,
          policy_version: selectedModel.policy_version,
          context: turnContext,
          context_preview_accepted: true,
        }),
      });
      if (!isCurrentSelection()) return;
      const turn = asRecord(turnEnvelope.turn);
      if (typeof turn.id !== "string" || typeof turn.status !== "string") throw new Error("The assistant returned a malformed turn identifier.");
      terminalEventRef.current = null;
      terminalTurnRef.current = { conversationId, turnId: turn.id };
      if (turnContext) setTurnContexts((current) => ({ ...current, [turn.id as string]: turnContext }));
      setMessages((current) => [...current, {
        id: `pending-${turn.id as string}`,
        turn_id: turn.id as string,
        seq: current.length + 1,
        role: "user",
        text,
        created_at: new Date().toISOString(),
      }]);
      setPrompt("");
      setActiveTurn({ conversationId, turnId: turn.id as string });
      setBusy(null);
      await connectToTurn({ conversationId, turnId: turn.id as string });
    } catch (error) {
      if (!isCurrentSelection()) return;
      const code = assistantErrorCode(error);
      if (code === "policy_version" || code === "provider_policy_changed") {
        setPrompt(text);
        await reloadAfterPolicyChange(error);
      } else if (code === "assistant_worker_unavailable") {
        const message = error instanceof Error ? error.message : "The assistant worker is unavailable. Your workspace remains available.";
        const owner = Symbol("assistant-worker-error");
        workerRecoveryErrorRef.current = owner;
        setPrompt(text);
        setPanelErrorState({ message, owner });
        setLiveStatus("The assistant worker is unavailable. Your question is still here; readiness will be checked.");
        void refreshAssistantStatus(true, true);
      } else {
        setPanelError(error instanceof Error ? error.message : "The assistant request could not be started.");
        setLiveStatus("No assistant response was started.");
        if (code === "worker_unavailable" || code === "runtime_restarted") void refreshAssistantStatus(true, true);
      }
    } finally {
      if (isCurrentSelection()) setBusy(null);
    }
  }

  async function cancelTurn(source?: HTMLElement | null) {
    if (!activeTurn || !busyTurn) return;
    const target = activeTurn;
    const generation = conversationLoadGeneration.current;
    const focusRequest = beginFocusRequest("cancel", source, target.conversationId, generation);
    const isCurrent = () => generation === conversationLoadGeneration.current
      && selectedConversationId.current === target.conversationId;
    const busyOperation = beginOwnedBusy("cancel");
    try {
      await assistantRequest(`${conversationPath(target.conversationId)}/turns/${encodeURIComponent(target.turnId)}/cancel`, {
        method: "POST",
        body: JSON.stringify({}),
      });
      if (!isCurrent()) return;
      canceledRef.current = true;
      streamAbortRef.current?.abort();
      setStreamState("cancelled");
      setActiveTurn(null);
      setLiveStatus("Response cancelled. Saved conversation history remains available.");
      await loadConversation(target.conversationId, false, focusRequest);
    } catch (error) {
      if (!isCurrent()) return;
      setPanelError(error instanceof Error ? error.message : "The response could not be cancelled.");
    } finally {
      finishOwnedBusy(busyOperation);
    }
  }

  async function confirmAction(proposal: AssistantActionProposal, phrase: string, allow = true) {
    if (!conversation || (proposal.availability && proposal.availability !== "confirmable")
        || (allow && (!proposal.confirmation_phrase || phrase !== proposal.confirmation_phrase))
        || Date.parse(proposal.expires_at) <= Date.now()) return;
    const targetConversationId = conversation.id;
    const generation = conversationLoadGeneration.current;
    const contextGeneration = contextRequestGeneration.current;
    const routeAtStart = currentPath();
    const hrefAtStart = window.location.href;
    const isCurrent = () => generation === conversationLoadGeneration.current
      && selectedConversationId.current === targetConversationId;
    const contextIsCurrent = () => isCurrent()
      && contextGeneration === contextRequestGeneration.current
      && routeAtStart === currentPath();
    let localHandoffRejected = false;
    let localControlsHandoffTarget: "notes-heading" | "alerts-heading" | null = null;
    let localControlsHandoffReloadGeneration: number | undefined;
    const recordLocalHandoffRejection = (message: string) => {
      localHandoffRejected = true;
      const detail = message.slice(0, 300);
      setSavedActions((current) => current.map((action) => action.action_id === proposal.action_id && action.receipt
        ? { ...action, status: "handoff_rejected_locally", receipt: {
          ...action.receipt,
          outcome: "handoff_rejected_locally",
          message: `The confirmed change could not be applied in this browser: ${detail}`.slice(0, 500),
        } }
        : action));
      setLiveStatus(`The confirmed change could not be applied in this browser: ${detail}`);
    };
    const busyOperation = beginOwnedBusy(`action:${proposal.action_id}`);
    setPanelError("");
    try {
      const confirmationContext = await latestConfirmationContext();
      if (!contextIsCurrent()) return;
      if (proposal.context_version && confirmationContext.context_version !== proposal.context_version) {
        throw new AssistantClientError("The page context changed after this preview. Refresh the conversation before confirming.", 409, "stale_context");
      }
      const result = await assistantRequest<{ status?: string; message?: string; receipt_id?: string; destination?: string; browser_action?: unknown }>(`${conversationPath(targetConversationId)}/actions/${encodeURIComponent(proposal.action_id)}/confirm`, {
        method: "POST",
        body: JSON.stringify({ action_version: proposal.version, context: confirmationContext, allow, ...(allow ? { confirmation_phrase: phrase } : {}) }),
      });
      if (!isCurrent()) return;
      setActionProposals((current) => current.filter((item) => item.action_id !== proposal.action_id));
      if (typeof result.receipt_id === "string" && typeof result.status === "string" && typeof result.message === "string") {
        setSavedActions((current) => [...current.filter((item) => item.action_id !== proposal.action_id), {
          action_id: proposal.action_id,
          action_type: proposal.action_type,
          status: result.status || "applied",
          expires_at: proposal.expires_at,
          receipt: {
            receipt_id: result.receipt_id as string,
            outcome: result.status || "applied",
            message: (result.message || "Action confirmed.").slice(0, 500),
            destination: safeAssistantDestination(result.destination),
          },
        }]);
      }
      setLiveStatus(result.status === "denied"
        ? "The proposal was declined. No application change was requested."
        : result.status === "applied"
        ? result.message || `${actionTypeLabel(proposal.action_type)} applied by the application.`
        : result.status === "handed_off"
          ? result.message || "The application opened the requested protected form. No action was applied in chat."
          : "The application accepted the confirmation request. Review the updated workspace state before assuming an effect.");
      if (allow && result.status === "applied"
          && ["portfolio.add", "portfolio.remove", "portfolio.set_quantity"].includes(proposal.action_type)) {
        window.dispatchEvent(new Event("signal-ledger:assistant-portfolio-updated"));
      }
      if (allow && result.status === "applied" && ["watchlist.add", "watchlist.remove"].includes(proposal.action_type)) {
        window.dispatchEvent(new Event("signal-ledger:assistant-watchlist-updated"));
      }
      if (allow && result.status === "handed_off" && contextIsCurrent()) {
        const browserAction = readAssistantBrowserAction(result.browser_action, routeAtStart);
        if (browserAction) {
          if (browserAction.type === "theme.set") {
            window.dispatchEvent(new CustomEvent("signal-ledger:assistant-theme", { detail: browserAction.payload }));
            setLiveStatus(`Theme changed to ${browserAction.payload.theme}.`);
          } else if (browserAction.type === "filters.apply") {
            const destination = assistantHistoryDestination(browserAction.payload);
            if (destination) {
              setLiveStatus("Opening the history form with the confirmed filters, sort, and page size.");
              window.location.assign(destination);
            } else {
              recordLocalHandoffRejection("The confirmed filters were outside the supported history form.");
            }
          } else if (browserAction.type === "market.filters.apply"
              || browserAction.type === "market.chart_range.set"
              || browserAction.type === "market.columns.set"
              || browserAction.type === "market.refresh") {
            if (browserAction.type === "market.chart_range.set" && !marketChartIdentityMatches(browserAction, confirmationContext.instrument ?? undefined)) {
              recordLocalHandoffRejection("The confirmed chart range did not match the current instrument.");
            } else {
              const result = await new Promise<{ ok: boolean; message: string }>((resolve) => {
                let completed = false;
                const finish = (value: { ok: boolean; message: string }) => {
                  if (completed) return;
                  completed = true;
                  resolve(value);
                };
                window.dispatchEvent(new CustomEvent("signal-ledger:assistant-action", {
                  detail: { action: browserAction, finish },
                }));
                window.setTimeout(() => finish({ ok: false, message: "The current Markets workspace could not apply this local action." }), 250);
              });
              if (isCurrent()) {
                if (result.ok) setLiveStatus(result.message);
                else recordLocalHandoffRejection(result.message);
              }
            }
          } else {
            const instrument = confirmationContext.instrument ?? undefined;
            if (!browserActionIdentityMatches(browserAction, instrument)) {
              recordLocalHandoffRejection("The confirmed browser action did not match the currently selected instrument.");
            } else {
              const result = await new Promise<{ ok: boolean; message: string }>((resolve) => {
                let completed = false;
                const finish = (value: { ok: boolean; message: string }) => {
                  if (completed) return;
                  completed = true;
                  resolve(value);
                };
                window.dispatchEvent(new CustomEvent("signal-ledger:assistant-action", {
                  detail: { action: browserAction, finish },
                }));
                window.setTimeout(() => finish({ ok: false, message: "The current workspace could not apply this local browser action." }), 250);
              });
              if (isCurrent()) {
                if (result.ok) setLiveStatus(result.message);
                else recordLocalHandoffRejection(result.message);
                if (result.ok && isMobile && contextIsCurrent() && window.location.href === hrefAtStart) {
                  if (browserAction.type === "notes.set" || browserAction.type === "notes.clear") {
                    localControlsHandoffTarget = "notes-heading";
                  } else if (browserAction.type === "alerts.remove") {
                    localControlsHandoffTarget = "alerts-heading";
                  }
                }
              }
            }
          }
        } else if (result.browser_action !== undefined) {
          recordLocalHandoffRejection("The confirmed browser action was malformed or targeted a different page.");
        } else {
          const destination = safeAssistantDestination(result.destination);
          if (destination) {
            setLiveStatus(destination.startsWith("/api/v1/history-export.csv?")
              ? "Downloading the approved filtered CSV history export."
              : destination.startsWith("/api/v1/history-export.json?")
                ? "Downloading the approved filtered JSON history export."
                : "Opening the application destination approved in this action.");
            window.location.assign(destination);
          } else if (result.destination || result.browser_action) {
            recordLocalHandoffRejection("The confirmed action returned an unsupported browser destination.");
          }
        }
      }
      if (isCurrent() && !localHandoffRejected
          && (!localControlsHandoffTarget || contextIsCurrent())) {
        const reloadGeneration = await loadConversation(targetConversationId);
        if (localControlsHandoffTarget) localControlsHandoffReloadGeneration = reloadGeneration;
      }
    } catch (error) {
      if (!isCurrent()) return;
      setPanelError(error instanceof Error ? error.message : "The action was not confirmed.");
      setLiveStatus("The application did not confirm this action. No change is assumed.");
    } finally {
      finishOwnedBusy(busyOperation);
    }
    if (isMobile && localControlsHandoffTarget && localControlsHandoffReloadGeneration !== undefined
        && conversationLoadGeneration.current === localControlsHandoffReloadGeneration
        && selectedConversationId.current === targetConversationId
        && contextGeneration === contextRequestGeneration.current
        && routeAtStart === currentPath() && window.location.href === hrefAtStart) {
      onLocalHandoff(localControlsHandoffTarget, hrefAtStart);
    }
  }

  async function confirmSearch(preview: PrivateSearchPreview, allow: boolean) {
    if (allow && Date.parse(preview.expires_at) <= Date.now()) {
      setPanelError("This search preview expired. Ask again to create a fresh preview.");
      return;
    }
    if (!conversation || !activeTurn) return;
    const targetConversationId = conversation.id;
    const targetTurnId = activeTurn.turnId;
    const generation = conversationLoadGeneration.current;
    const contextGeneration = contextRequestGeneration.current;
    const routeAtStart = currentPath();
    const isCurrent = () => generation === conversationLoadGeneration.current
      && selectedConversationId.current === targetConversationId;
    const contextIsCurrent = () => isCurrent()
      && contextGeneration === contextRequestGeneration.current
      && routeAtStart === currentPath();
    const busyOperation = beginOwnedBusy(`search:${preview.preview_id}`);
    setPanelError("");
    try {
      const confirmationContext = await latestConfirmationContext();
      if (!contextIsCurrent()) return;
      if (confirmationContext.context_version !== preview.context_version) {
        throw new AssistantClientError("The page context changed after this preview. Refresh the response before confirming.", 409, "stale_context");
      }
      const result = await assistantRequest<{ status?: string }>(`${conversationPath(targetConversationId)}/turns/${encodeURIComponent(targetTurnId)}/search-previews/${encodeURIComponent(preview.preview_id)}/confirm`, {
        method: "POST",
        body: JSON.stringify({ context_version: preview.context_version, context: confirmationContext, confirmation_phrase: preview.confirmation_phrase, allow }),
      });
      if (!isCurrent()) return;
      setSearchPreviews((current) => current.filter((item) => item.preview_id !== preview.preview_id));
      setLiveStatus(result.status === "approved"
        ? "The application approved this exact search query. It is limited to this preview."
        : result.status === "denied" || !allow
          ? "Search declined. The private query was not approved."
          : "The application recorded the search choice.");
    } catch (error) {
      if (!isCurrent()) return;
      setPanelError(error instanceof Error ? error.message : "The search preview could not be confirmed.");
    } finally {
      finishOwnedBusy(busyOperation);
    }
  }

  async function confirmWebFetch(preview: ActiveWebFetchPreview, allow: boolean) {
    const targetConversationId = selectedConversationId.current;
    if (!targetConversationId || !conversation || !activeTurn
      || conversation.id !== targetConversationId
      || activeTurn.conversationId !== targetConversationId
      || activeTurn.turnId !== preview.turn_id) return;
    const generation = conversationLoadGeneration.current;
    const contextGeneration = contextRequestGeneration.current;
    const routeAtStart = currentPath();
    const busyKey = `webfetch:${preview.preview_id}`;
    const isConversationCurrent = () => generation === conversationLoadGeneration.current
      && selectedConversationId.current === targetConversationId;
    const isSelectionCurrent = () => isConversationCurrent()
      && activeTurnRef.current?.turnId === preview.turn_id;
    const isContextCurrent = () => isSelectionCurrent()
      && contextGeneration === contextRequestGeneration.current
      && routeAtStart === currentPath();
    const rejectStalePreview = () => {
      if (!isSelectionCurrent()) return;
      setWebFetchPreviews((current) => current.filter((item) => item.preview_id !== preview.preview_id));
      setPanelError("The page context changed after this URL preview. No URL was sent; ask again for a fresh preview.");
      setLiveStatus("The old URL preview is stale. No web page request was approved.");
    };
    if (allow && Date.parse(preview.expires_at) <= Date.now()) {
      setPanelError("This web page request preview expired. No URL was sent. Ask again to create a fresh preview.");
      return;
    }
    if (allow && !isContextCurrent()) {
      rejectStalePreview();
      return;
    }
    const busyOperation = beginOwnedBusy(busyKey);
    setPanelError("");
    try {
      let confirmationContext: AssistantTurnContext | null = null;
      if (allow) {
        const requestAtStart = assistantContextRequest({
          pathname: window.location.pathname,
          search: window.location.search,
        });
        if (!requestAtStart || JSON.stringify(requestAtStart) !== contextKey) {
          rejectStalePreview();
          return;
        }
        confirmationContext = await latestConfirmationContext(requestAtStart);
        if (!isSelectionCurrent()) return;
        const requestAfterRefresh = assistantContextRequest({
          pathname: window.location.pathname,
          search: window.location.search,
        });
        if (!isContextCurrent() || !requestAfterRefresh
            || JSON.stringify(requestAfterRefresh) !== JSON.stringify(requestAtStart)
            || confirmationContext.context_version !== preview.context_version) {
          rejectStalePreview();
          return;
        }
      }
      const result = await assistantRequest<{ preview_id?: string; status?: string }>(
        `${conversationPath(targetConversationId)}/turns/${encodeURIComponent(preview.turn_id)}/webfetch-previews/${encodeURIComponent(preview.preview_id)}/confirm`,
        {
          method: "POST",
          body: JSON.stringify({
            context_version: preview.context_version,
            ...(confirmationContext ? { context: confirmationContext } : {}),
            confirmation_phrase: preview.confirmation_phrase,
            allow,
          }),
        },
      );
      if (!isConversationCurrent()) return;
      setWebFetchPreviews((current) => current.filter((item) => item.preview_id !== preview.preview_id));
      setLiveStatus(result.status === "approved"
        ? "This exact URL was approved for one web page request."
        : result.status === "expired"
          ? "The web page request preview expired. No URL was sent."
          : "Web page request declined. No URL was sent.");
    } catch (error) {
      if (!isSelectionCurrent()) return;
      if (allow && (!isContextCurrent()
          || (error instanceof AssistantClientError && error.code === "webfetch_context_stale"))) {
        rejectStalePreview();
        return;
      }
      setPanelError(error instanceof Error ? error.message : "The web page request could not be confirmed.");
    } finally {
      finishOwnedBusy(busyOperation);
    }
  }

  const modelTerms = safeTermsUrl(selectedModel?.terms_url);
  const consentReady = selectedModel?.consent?.accepted === true
    && (selectedModel.training !== "data_collection" || selectedModel.consent.data_collection_opt_in === true);
  const sendDisabled = !prompt.trim() || !selectedModel || !modelUsable || !consentReady || !workerReady
    || busyTurn || busy !== null || conversationState === "loading" || contextState !== "ready" || !context;
  const contextLabel = context?.instrument
    ? `${routeLabels[context.route]} · ${context.instrument.symbol} · ${context.instrument.asset_type.toUpperCase()}`
    : routeLabels[contextRequest.route];

  return (
    <section
      ref={panelRef}
      className={`${styles.panel} ${expanded ? styles.expanded : ""} ${panelMinimized ? styles.minimized : ""}`}
      data-testid="assistant-panel"
      data-mobile={isMobile ? "true" : "false"}
      role="dialog"
      aria-modal={isMobile && !panelMinimized ? true : undefined}
      aria-labelledby="assistant-heading"
      tabIndex={-1}
      onKeyDown={handlePanelKeyDown}
    >
      <header className={styles.header} role="group" aria-label="Assistant controls">
        <span className={styles.mark} aria-hidden="true"><i /><i /><i /></span>
        <div className={styles.titleBlock} data-testid="assistant-title-block">
          <h2 ref={headingRef} id="assistant-heading" tabIndex={-1}>Ledger assistant</h2>
          {!panelMinimized ? <p>{conversation?.title || "Research companion"}</p> : null}
        </div>
        {!panelMinimized ? (
          <>
            <label className={styles.modelSelectLabel}>
              <span className="sr-only">Assistant model</span>
              <select aria-label="Assistant model" value={selectedModelId} onChange={(event) => { setSelectedModelId(event.target.value); setAcceptTerms(false); setAllowCollection(false); }} disabled={modelState !== "ready"}>
                <option value="">Choose a model</option>
                {models.map((model) => (
                  <option key={model.id} value={model.id} disabled={!model.usable}>
                    {model.name} · {model.billing_class === "free" ? "Free" : model.billing_class === "paid" ? "Paid" : "Billing unverified"} · {model.usable ? "Approved" : "Unavailable"}
                  </option>
                ))}
              </select>
            </label>
            <div className={styles.headerControls} data-testid="assistant-header-controls">
              <button type="button" className={styles.iconButton} aria-label={historyOpen ? "Close conversation history" : "Open conversation history"} title={historyOpen ? "Close conversation history" : "Open conversation history"} aria-expanded={historyOpen} onClick={() => setHistoryOpen((value) => !value)}>
                <svg aria-hidden="true" viewBox="0 0 24 24"><path d="M4 5.5h16M4 12h16M4 18.5h16" /></svg>
              </button>
              {!isMobile ? <button type="button" className={styles.iconButton} aria-label={expanded ? "Restore assistant size" : "Expand assistant"} title={expanded ? "Restore assistant size" : "Expand assistant"} aria-pressed={expanded} onClick={() => setExpanded((value) => !value)}>
                <svg aria-hidden="true" viewBox="0 0 24 24"><path d={expanded ? "M8 4v4H4M16 20v-4h4M4 8l6-6M20 16l-6 6" : "M8 4H4v4M16 20h4v-4M4 8l6-6M20 16l-6 6"} /></svg>
              </button> : null}
              {!isMobile ? <button type="button" className={styles.iconButton} aria-label="Minimize assistant" title="Minimize assistant" onClick={() => setMinimized(true)}>
                <svg aria-hidden="true" viewBox="0 0 24 24"><path d="M5 12h14" /></svg>
              </button> : null}
              <button type="button" className={styles.iconButton} aria-label="Close assistant" title="Close assistant" onClick={onClose}>
                <svg aria-hidden="true" viewBox="0 0 24 24"><path d="m6 6 12 12M18 6 6 18" /></svg>
              </button>
            </div>
          </>
        ) : (
          <div className={styles.headerControls} data-testid="assistant-header-controls">
            <button ref={resumeButtonRef} type="button" className={styles.iconButton} aria-label="Resume assistant" title="Resume assistant" onClick={() => setMinimized(false)}>
              <svg aria-hidden="true" viewBox="0 0 24 24"><path d="M8 5 19 12 8 19z" /></svg>
            </button>
            <button type="button" className={styles.iconButton} aria-label="Close assistant" title="Close assistant" onClick={onClose}>
              <svg aria-hidden="true" viewBox="0 0 24 24"><path d="m6 6 12 12M18 6 6 18" /></svg>
            </button>
          </div>
        )}
      </header>

      {!panelMinimized ? (
        <>
          <div className={styles.body}>
          <div className={styles.readiness} data-ready={workerReady ? "true" : "false"} role="status">
            <span className={styles.statusDot} aria-hidden="true" />
            <span>{showWorkerReason(status)}</span>
            {status?.enabled && !workerReady ? <button type="button" className={styles.textButton} onClick={() => void refreshAssistantStatus(true, true)} disabled={readinessChecking}>
              {readinessChecking ? "Checking…" : "Check readiness"}
            </button> : null}
          </div>

          {panelError ? <p className={styles.error} role="alert">{panelError}</p> : null}

          {historyOpen ? (
            <section className={styles.history} aria-labelledby="assistant-history-heading">
              <div className={styles.sectionHeading}>
                <h3 id="assistant-history-heading">Conversation history</h3>
                <button type="button" className={styles.textButton} onClick={createNewConversation} disabled={busy !== null}>New conversation</button>
              </div>
              {historyState === "loading" ? <p role="status">Loading saved conversations…</p> : null}
              {historyState === "error" ? <div role="alert"><p>{historyError}</p><button type="button" className={styles.textButton} onClick={() => void loadConversations(1, false)}>Retry history</button></div> : null}
              {historyState === "ready" && conversations.length === 0 ? <p>No conversations saved yet.</p> : null}
              {conversations.length ? (
                <ul className={styles.historyList}>
                  {conversations.map((item) => (
                    <li key={item.id}>
                      <button type="button" onClick={(event) => {
                        const focusRequest = beginFocusRequest("load", event.currentTarget, item.id);
                        void loadConversation(item.id, false, focusRequest);
                      }} aria-current={conversation?.id === item.id ? "true" : undefined}>
                        <strong>{item.title}</strong>
                        <span>{item.last_message_preview || "No messages yet"}</span>
                        <small>{readableTimestamp(item.updated_at)}</small>
                      </button>
                    </li>
                  ))}
                </ul>
              ) : null}
              {historyTotal > conversations.length ? <button type="button" className={styles.textButton} onClick={() => void loadMoreHistory()} disabled={historyState === "loading"}>Load older conversations</button> : null}
              {conversation ? (
                <form className={styles.renameForm} onSubmit={saveTitle}>
                  <label htmlFor="assistant-title">Rename selected conversation</label>
                  <div><input id="assistant-title" value={titleDraft} maxLength={120} onChange={(event) => setTitleDraft(event.target.value)} /><button type="submit" disabled={busy !== null || !titleDraft.trim()}>Save title</button></div>
                  {!showDelete ? <button type="button" className={styles.dangerLink} onClick={() => setShowDelete(true)}>Delete selected conversation…</button> : (
                    <div className={styles.deleteConfirm}>
                      <p>Deletion removes this conversation and its transient runtime cache. This cannot be undone from the assistant.</p>
                      <label htmlFor="assistant-delete-phrase">Type <code>{conversation.delete_confirmation_phrase}</code> to confirm</label>
                      <input id="assistant-delete-phrase" value={deletePhrase} autoComplete="off" onChange={(event) => setDeletePhrase(event.target.value)} />
                      <div><button type="button" onClick={() => { setShowDelete(false); setDeletePhrase(""); }}>Keep conversation</button><button type="button" className={styles.dangerButton} disabled={busy !== null || deletePhrase !== conversation.delete_confirmation_phrase} onClick={() => void deleteConversation()}>Delete conversation</button></div>
                    </div>
                  )}
                </form>
              ) : null}
            </section>
          ) : null}

          <section className={styles.context} aria-label="Workspace context">
            <div className={styles.contextTop}>
              <span>{contextLabel}</span>
              <button type="button" className={`${styles.textButton} ${styles.contextRefresh}`} aria-label="Refresh context preview" onClick={() => void reloadContext()} disabled={busy !== null}>Refresh preview</button>
            </div>
            <div className={styles.contextControlRow}>
              <label className={styles.contextToggle}>
                <input aria-label="Share selected references" type="checkbox" checked={includeContext} disabled={busy !== null} onChange={(event) => {
                  includeContextRef.current = event.target.checked;
                  contextRequestGeneration.current += 1;
                  setContextState("loading");
                  setIncludeContext(event.target.checked);
                }} />
                <span>Share selected references</span>
                <small className={styles.contextShareMode} aria-hidden="true">{includeContext ? "Route + refs" : "Route only"}</small>
              </label>
              {contextState === "ready" && context ? (
                <details ref={contextDetailsRef} className={styles.contextDetails}>
                  <summary>Preview</summary>
                  <p className={styles.contextNote}>The current page route is always included. Turn off sharing to send only the route name.</p>
                  <p className={styles.contextNote}>Request scope: {includeContext ? "route and available selections" : "route only"}.</p>
                  <div className={styles.contextPreview}>
                    <strong>{context.preview.summary || "Exact context shown for the next request"}</strong>
                    <ul>{context.preview.fields.map((field, index) => <li key={`${index}:${field}`}>{field}</li>)}</ul>
                    {context.instrument ? <p>{context.instrument.display_name} · {context.instrument.symbol} · {context.instrument.asset_type.toUpperCase()} · {context.instrument.exchange} · {context.instrument.provider}</p> : null}
                    {context.event_ref ? <p>Saved event #{context.event_ref.id}</p> : null}
                    {context.result_ref ? <p>Saved result #{context.result_ref.id}</p> : null}
                    {context.preview.note ? <p>{context.preview.note}</p> : null}
                  </div>
                </details>
              ) : null}
            </div>
            {contextState === "loading" ? <p className={styles.muted} role="status">Checking safe workspace context…</p> : null}
            {contextState === "error" ? <p className={styles.muted}>Workspace context could not be loaded. Refresh the preview before sending a request.</p> : null}
          </section>

          {selectedModel && (!consentReady || !modelUsable) ? (
            <section className={styles.consent} aria-labelledby="assistant-consent-heading">
              <h3 id="assistant-consent-heading">{modelUsable ? "Review model privacy terms" : "Model availability"}</h3>
              <p>{selectedModel.privacy_disclosure ?? selectedModel.disclosure}</p>
              <p className={styles.muted}>{selectedModel.provider} · {selectedModel.billing_class === "paid" ? "Paid model" : selectedModel.billing_class === "free" ? "Free model" : "Billing status unavailable"} · Terms reviewed {readableTimestamp(selectedModel.terms_reviewed_at)}</p>
              {selectedModel.cost_disclosure ? <p>{selectedModel.cost_disclosure}</p> : null}
              {selectedModel.availability_reason && !modelUsable ? <p role="status">{selectedModel.availability_reason}</p> : null}
              {modelTerms ? <p><a href={modelTerms} target="_blank" rel="noopener noreferrer">Read provider terms</a></p> : <p role="alert">A verified HTTPS terms link is unavailable, so this model cannot be enabled.</p>}
              {modelUsable ? !consentReady ? (
                <>
                  <label className={styles.consentCheck}><input type="checkbox" checked={acceptTerms} onChange={(event) => setAcceptTerms(event.target.checked)} /><span>I accept this model's privacy terms for policy {selectedModel.policy_version}.</span></label>
                  {selectedModel.training === "data_collection" ? <label className={styles.consentCheck}><input type="checkbox" checked={allowCollection} onChange={(event) => setAllowCollection(event.target.checked)} /><span>I explicitly opt in to provider collection of prompts, context, and tool results.</span></label> : <p className={styles.muted}>The catalog describes this model as no-training. This is provider terms information, not an OpenCode setting.</p>}
                  <button type="button" onClick={() => void acceptModelConsent()} disabled={consentBusy || !acceptTerms || (selectedModel.training === "data_collection" && !allowCollection) || !modelTerms}>{consentBusy ? "Saving consent…" : "Save privacy choice"}</button>
                </>
              ) : null : <p role="status">{selectedModel.availability_reason || "This exact model is not currently approved and usable. Ask an administrator to review its provider, privacy, and billing status."}</p>}
            </section>
          ) : null}

          <div className={styles.storage} role="group" aria-label="Assistant storage usage">
            <span>Conversation storage</span>
            <strong>{status ? formatStorage(status.storage.user_bytes, status.storage.user_limit) : "Unavailable"}</strong>
          </div>

          <div className={webFetchPreviews.length > 0 ? `${styles.transcript} ${styles.transcriptWebFetchApproval}` : styles.transcript} role="group" aria-label="Conversation" tabIndex={0}>
            {conversationState === "loading" ? <p role="status">Opening saved conversation…</p> : null}
            {conversationState === "error" ? <div role="alert"><p>The conversation could not be opened.</p><button type="button" onClick={(event) => {
              if (!conversation) return;
              const focusRequest = beginFocusRequest("load", event.currentTarget, conversation.id);
              void loadConversation(conversation.id, false, focusRequest);
            }}>Retry</button></div> : null}
            {conversation && messageTotal > messages.length ? <button type="button" className={styles.reconnect} onClick={() => void loadEarlierMessages()} disabled={messagesLoading}>{messagesLoading ? "Loading earlier messages…" : "Load earlier messages"}</button> : null}
            {conversation && actionPagination.total > actionPagination.page_size ? (
              <div className={styles.activityPaging} aria-label="Action receipt history pages">
                {actionPagination.page > 1 ? <button type="button" className={styles.reconnect} onClick={() => void loadActivityPage("actions", "newer")} disabled={activityLoading}>Show newer receipts</button> : null}
                {actionPagination.page * actionPagination.page_size < actionPagination.total ? <button type="button" className={styles.reconnect} onClick={() => void loadActivityPage("actions", "older")} disabled={activityLoading}>{activityLoading ? "Loading receipts…" : "Load older receipts"}</button> : null}
              </div>
            ) : null}
            {conversation && eventPagination.total > eventPagination.page_size ? (
              <div className={styles.activityPaging} aria-label="Research step history pages">
                {eventPagination.page > 1 ? <button type="button" className={styles.reconnect} onClick={() => void loadActivityPage("events", "newer")} disabled={activityLoading}>Show newer research steps</button> : null}
                {eventPagination.page * eventPagination.page_size < eventPagination.total ? <button type="button" className={styles.reconnect} onClick={() => void loadActivityPage("events", "older")} disabled={activityLoading}>{activityLoading ? "Loading research steps…" : "Load older research steps"}</button> : null}
              </div>
            ) : null}
            {conversation && messages.length === 0 && !activeTurn ? <p className={styles.empty}>Ask about the current research page, or use conversation history to reopen a saved answer.</p> : null}
            <ol className={styles.messageList} aria-live="off">
              {messages.map((message) => (
                <li className={message.role === "user" ? styles.userMessage : styles.assistantMessage} key={message.id}>
                  <div className={styles.messageHeading}><strong>{message.role === "user" ? "You" : "Ledger assistant"}</strong><time dateTime={message.created_at}>{readableTimestamp(message.created_at)}</time></div>
                  {message.role === "assistant" ? <AssistantAnswer text={message.text} /> : <p>{message.text}</p>}
      {message.turn_id && turnContexts[message.turn_id] ? (() => {
                    const snapshot = turnContexts[message.turn_id];
                    return <small>Context snapshot: {routeLabels[snapshot.route]}{snapshot.instrument ? ` · ${snapshot.instrument.symbol}` : ""}</small>;
                  })() : null}
                  {message.sources?.length ? <CitationList sources={message.sources} /> : null}
                </li>
              ))}
              {activeTurn && draft !== "" ? <li className={styles.assistantMessage}><div className={styles.messageHeading}><strong>Ledger assistant</strong><span role="status">Streaming</span></div><AssistantAnswer text={draft} />{draftSources.length ? <CitationList sources={draftSources} /> : null}</li> : null}
            </ol>

            {savedActions.some((action) => action.receipt) ? (
              <section className={styles.receipts} aria-label="Confirmed action receipts">
                <h3>Confirmed action receipts</h3>
                <ul>{savedActions.filter((action) => action.receipt).map((action) => {
                  const receipt = action.receipt;
                  if (!receipt) return null;
                  return <li key={receipt.receipt_id}>
                    <strong>{actionTypeLabel(action.action_type)} · {receipt.outcome.replaceAll("_", " ")}</strong>
                    <span>{receipt.message}</span>
                    <small>Receipt {receipt.receipt_id}</small>
                    {receipt.destination ? <a href={receipt.destination}>{receipt.destination.startsWith("/account") ? "Continue to account sessions" : receipt.destination.startsWith("/tools/markets") ? "Continue to market context" : receipt.destination.startsWith("/research") || receipt.destination.includes("#history-heading") ? "Continue to recorded research" : receipt.destination.includes("history-export") ? "Download filtered history" : "Continue in workspace settings"}</a> : null}
                  </li>;
                })}</ul>
              </section>
            ) : null}

            {toolEvents.length ? (
              <section className={styles.toolActivity} aria-label="Assistant tool activity">
                <h3>Research steps</h3>
                <ol>{toolEvents.map((tool) => <li key={tool.call_id} data-state={tool.status}><strong>{tool.name.replaceAll("_", " ")}</strong><span>{tool.description || tool.status}</span>{tool.receipt_id ? <small>Receipt {tool.receipt_id}{typeof tool.result_bytes === "number" ? ` · ${tool.result_bytes} bytes` : ""}</small> : null}</li>)}</ol>
              </section>
            ) : null}

            {actionProposals.map((proposal) => <ActionCard key={proposal.action_id} proposal={proposal} busy={busy === `action:${proposal.action_id}`} onConfirm={confirmAction} />)}
            {searchPreviews.map((preview) => <SearchPreviewCard key={preview.preview_id} preview={preview} busy={busy === `search:${preview.preview_id}`} onConfirm={confirmSearch} />)}
            {webFetchPreviews.map((preview) => <WebFetchPreviewCard key={preview.preview_id} preview={preview} busy={busy === `webfetch:${preview.preview_id}`} onConfirm={confirmWebFetch} />)}

            {activeTurn && streamState === "interrupted" ? <button ref={reconnectButtonRef} type="button" className={styles.reconnect} onClick={(event) => {
              const focusRequest = beginFocusRequest("load", event.currentTarget, activeTurn.conversationId);
              void connectToTurn(activeTurn, focusRequest);
            }}>Reconnect to response</button> : null}
            {busyTurn ? <button ref={cancelButtonRef} type="button" className={styles.cancel} onClick={(event) => void cancelTurn(event.currentTarget)} disabled={busy === "cancel"}>{busy === "cancel" ? "Cancelling…" : "Stop response"}</button> : null}
            {streamState === "failed" ? <p className={styles.error} role="alert">The response did not finish. Review any action receipts and reopen the conversation to check the saved state.</p> : null}
            {!conversation && conversationState === "ready" ? <p className={styles.empty}>Start a conversation with a specific research question. The assistant does not trade or place orders.</p> : null}
          </div>

          {liveStatus ? <p className={styles.liveStatus}>{liveStatus}</p> : null}
          </div>

          <form className={styles.composer} onSubmit={startTurn}>
            <label htmlFor="assistant-prompt">Ask about this page</label>
            <textarea
              ref={composerRef}
              id="assistant-prompt"
              value={prompt}
              onChange={(event) => setPrompt(event.target.value.slice(0, 8000))}
              onKeyDown={(event) => {
                if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
                  event.preventDefault();
                  event.currentTarget.form?.requestSubmit();
                }
              }}
              maxLength={8000}
              rows={2}
              placeholder="Ask about a probability, source, or research result…"
              disabled={busyTurn || conversationState === "loading" || !workerReady}
              aria-describedby="assistant-disclaimer"
            />
            <div className={styles.composerActions}>
              <p id="assistant-disclaimer">Research only. Answers can be wrong; no trades are placed.</p>
              <button type="submit" disabled={sendDisabled}>{busyTurn ? "Responding…" : "Send question"}</button>
            </div>
          </form>
        </>
      ) : (
        <p className={styles.minimizedStatus} role="status">{busyTurn ? "A response is running." : "Conversation saved on this page."}</p>
      )}
      {/* Keep liveStatus in one persistent region; visible expanded status text stays non-live. */}
      <span className="sr-only" aria-live="polite">{liveStatus}</span>
    </section>
  );
}

function CitationList({ sources }: Readonly<{ sources: AssistantSource[] }>) {
  return (
    <ul className={styles.citations} aria-label="Sources and retrieval dates">
      {sources.map((source) => {
        const href = safeCitationHref(source.url);
        const typeLabel = citationTypeLabel(source);
        return (
          <li key={source.source_id}>
            {href ? <a href={href} target={href.startsWith("/") ? undefined : "_blank"} rel={href.startsWith("/") ? undefined : "noopener noreferrer"}>{citationLabel(source)}</a> : <span>{citationLabel(source)} · Link unavailable</span>}
            {typeLabel ? <small title={source.source_type === "native_search_text_unverified" ? typeLabel : undefined}>{typeLabel}</small> : null}
          </li>
        );
      })}
    </ul>
  );
}

function ActionCard({
  proposal,
  busy,
  onConfirm,
}: Readonly<{
  proposal: AssistantActionProposal;
  busy: boolean;
  onConfirm: (proposal: AssistantActionProposal, phrase: string, allow?: boolean) => Promise<void>;
}>) {
  const [phrase, setPhrase] = useState("");
  const expired = !Number.isFinite(Date.parse(proposal.expires_at)) || Date.parse(proposal.expires_at) <= Date.now();
  const changes = Array.isArray(proposal.changes) ? proposal.changes.slice(0, 24) : [];
  const localControlsHandoff = ["notes.set", "notes.clear", "alerts.remove"].includes(proposal.action_type);
  const confirmable = (!proposal.availability || proposal.availability === "confirmable")
    && typeof proposal.confirmation_phrase === "string";
  const unavailableReason: Record<string, string> = {
    different_session: "This proposal belongs to a different sign-in session. It is shown for history and cannot be confirmed here.",
    expired: "This proposal expired. Ask again to create a fresh preview.",
    policy_changed: "The model policy changed after this proposal. Review the current policy and ask again.",
    authorization_required: "This proposal needs fresh administrator authorization before it can be confirmed.",
    stale: "The saved page context changed after this proposal. Ask again to create a current preview.",
    unavailable: "This proposal is saved for history but is not available for confirmation.",
  };
  const handoffText = proposal.action_type.startsWith("notes.")
    ? "Confirmation opens the local note editor. Review or change the note there; the chat will not replace or clear your browser draft."
    : "Confirmation opens the current alert controls. Choose the threshold there; the chat will not remove an alert.";
  return (
    <section className={styles.actionCard} aria-label={`Preview: ${actionTypeLabel(proposal.action_type)}`}>
      <p className={styles.panelKicker}>Action preview</p>
      <h3>{localControlsHandoff ? actionTypeLabel(proposal.action_type) : proposal.title || actionTypeLabel(proposal.action_type)}</h3>
      <p>{localControlsHandoff ? handoffText : proposal.summary || "Review the application-provided action details before confirming."}</p>
      {localControlsHandoff ? <p className={styles.muted}>Current local values stay in this page until you use its controls.</p>
        : changes.length ? <dl>{changes.map((change, index) => <div key={`${index}:${change.label}`}><dt>{change.label}</dt><dd>{change.before === undefined ? null : <span><strong>Before:</strong> {String(change.before)}</span>}{change.after === undefined ? null : <span><strong>After:</strong> {String(change.after)}</span>}</dd></div>)}</dl> : <p>No change has been applied yet. Review its summary and destination before confirming.</p>}
      <p className={styles.muted}>Expires {readableTimestamp(proposal.expires_at)}. Confirmation is single-use and tied to this exact preview.</p>
      {confirmable && !expired ? (
        <>
          <label>Type <code>{proposal.confirmation_phrase}</code> to confirm<input value={phrase} autoComplete="off" onChange={(event) => setPhrase(event.target.value)} /></label>
          <div className={styles.cardActions}>
            <button type="button" className={styles.secondaryButton} onClick={() => void onConfirm(proposal, "", false)} disabled={busy}>Decline proposal</button>
            <button type="button" disabled={busy || phrase !== proposal.confirmation_phrase} onClick={() => void onConfirm(proposal, phrase)}>{busy ? "Confirming…" : localControlsHandoff ? "Open local controls" : "Confirm change"}</button>
          </div>
        </>
      ) : <p role="status">{unavailableReason[proposal.availability ?? ""] || (expired ? "This preview expired; ask again to create a fresh one." : "Confirmation is unavailable for this saved proposal.")}</p>}
    </section>
  );
}

function SearchPreviewCard({
  preview,
  busy,
  onConfirm,
}: Readonly<{
  preview: PrivateSearchPreview;
  busy: boolean;
  onConfirm: (preview: PrivateSearchPreview, allow: boolean) => Promise<void>;
}>) {
  const expired = !Number.isFinite(Date.parse(preview.expires_at)) || Date.parse(preview.expires_at) <= Date.now();
  return (
    <section className={styles.searchCard} aria-label="Private-context public search preview">
      <p className={styles.panelKicker}>Review before public search</p>
      <h3>This query would include private workspace context</h3>
      <blockquote>{preview.query}</blockquote>
      <p>{preview.reason}</p>
      <p className={styles.muted}>Only this exact query is covered. It expires {readableTimestamp(preview.expires_at)}.</p>
      <div className={styles.cardActions}>
        <button type="button" className={styles.secondaryButton} onClick={() => void onConfirm(preview, false)} disabled={busy}>Decline search</button>
        <button type="button" onClick={() => void onConfirm(preview, true)} disabled={busy || expired}>{busy ? "Saving choice…" : "Allow this search"}</button>
      </div>
    </section>
  );
}

function WebFetchPreviewCard({
  preview,
  busy,
  onConfirm,
}: Readonly<{
  preview: ActiveWebFetchPreview;
  busy: boolean;
  onConfirm: (preview: ActiveWebFetchPreview, allow: boolean) => Promise<void>;
}>) {
  const expired = !Number.isFinite(Date.parse(preview.expires_at)) || Date.parse(preview.expires_at) <= Date.now();
  return (
    <section className={styles.webFetchCard} aria-label="Web page request confirmation">
      <p className={styles.panelKicker}>Review exact web page URL</p>
      <h3>Allow one request to this URL?</h3>
      <p>{preview.reason}</p>
      <div className={styles.webFetchWarning} role="note">
        This complete URL, including every query parameter, will be sent to the destination website. The fetched page will be returned to the assistant for this turn. Do not approve it if the URL contains a credential or private account information.
      </div>
      <pre className={styles.webFetchUrl} dir="ltr">{preview.url}</pre>
      <p className={styles.muted}>This approval applies only to the exact URL shown above. It expires {readableTimestamp(preview.expires_at)}.</p>
      {expired ? <p role="status">Expired. No URL will be sent.</p> : null}
      <div className={styles.cardActions}>
        <button type="button" className={styles.secondaryButton} onClick={() => void onConfirm(preview, false)} disabled={busy}>Decline request</button>
        <button type="button" onClick={() => void onConfirm(preview, true)} disabled={busy || expired}>{busy ? "Saving choice…" : "Approve exact URL once"}</button>
      </div>
    </section>
  );
}
