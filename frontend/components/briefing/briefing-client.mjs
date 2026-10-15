// Keep the browser boundary owner-authenticated, bounded, and explicit about writes.
export const BRIEFING_WINDOWS = Object.freeze([
  "since_last_visit",
  "last_24_hours",
  "last_7_days",
]);
export const IDLE_REFRESH_STATE = Object.freeze({ status: "idle" });

const MAX_RESPONSE_BYTES = 2 * 1024 * 1024;
const MAX_PAGE_SIZE = 20;
const MAX_ITEMS_PER_SOURCE = 100;
const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const REFERENCE_RE = /^[A-Za-z0-9_.:-]{1,128}$/;
const SYMBOL_RE = /^[A-Z0-9][A-Z0-9.-]{0,19}$/;
const TIMESTAMP_RE = /^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,6})?Z$/;
const DECIMAL_RE = /^-?(?:0|[1-9]\d{0,69})(?:\.\d{1,18})?$/;

export class BriefingRequestError extends Error {
  constructor(status, retryAfterSeconds = null) {
    super(messageForStatus(status));
    this.name = "BriefingRequestError";
    this.status = status;
    this.retryAfterSeconds = retryAfterSeconds;
  }
}

function parseRetryAfter(value, nowMs) {
  if (typeof value !== "string" || value.length > 64) return null;
  let seconds;
  if (/^\d{1,6}$/.test(value)) {
    seconds = Number(value);
  } else {
    const date = Date.parse(value);
    if (!Number.isFinite(date)) return null;
    seconds = Math.max(0, Math.ceil((date - nowMs) / 1000));
  }
  if (!Number.isFinite(seconds) || seconds < 0 || seconds > 86400) return null;
  return seconds;
}

export function classifyBriefingFailure(error) {
  if (error instanceof BriefingRequestError) {
    if (error.status === 401 || error.status === 403) {
      return { kind: "authorization", status: error.status };
    }
    if (error.status === 409) return { kind: "conflict", status: 409 };
    if (error.status === 429) {
      return {
        kind: "rate_limited",
        status: 429,
        retryAfterSeconds: Number.isSafeInteger(error.retryAfterSeconds)
          ? error.retryAfterSeconds : null,
      };
    }
    if (error.status >= 400 && error.status < 500) {
      return { kind: "rejected", status: error.status };
    }
    return { kind: "uncertain", status: error.status };
  }
  return { kind: "uncertain", status: null };
}

export function refreshStateReducer(current, event) {
  if (event.type === "reset" || event.type === "succeeded") return IDLE_REFRESH_STATE;
  if (event.type === "begin" && event.attempt) {
    return { status: "pending", attempt: event.attempt };
  }
  if (event.type === "retry" && current.status === "uncertain") {
    return { status: "pending", attempt: current.attempt };
  }
  if (event.type !== "failed") return current;

  const failure = event.failure;
  if (failure.kind === "rate_limited"
      && (current.status === "idle" || current.status === "rate_limited")) {
    const seconds = Number.isSafeInteger(failure.retryAfterSeconds)
      ? failure.retryAfterSeconds : 30;
    const at = Number.isSafeInteger(event.at) ? event.at : Date.now();
    return { status: "rate_limited", retryAt: at + seconds * 1000 };
  }
  if (current.status !== "pending") return current;
  if (failure.kind === "uncertain") {
    return { status: "uncertain", attempt: current.attempt, failureStatus: failure.status };
  }
  if (failure.kind === "authorization") return { status: "authorization", statusCode: failure.status };
  if (failure.kind === "rate_limited") {
    const seconds = Number.isSafeInteger(failure.retryAfterSeconds)
      ? failure.retryAfterSeconds : 30;
    const at = Number.isSafeInteger(event.at) ? event.at : Date.now();
    return { status: "rate_limited", retryAt: at + seconds * 1000 };
  }
  return { status: "rejected", failureKind: failure.kind, statusCode: failure.status };
}

export function refreshButtonModel(refreshState, {
  busy = false,
  available = true,
  hasSnapshot = false,
  nowMs = Date.now(),
} = {}) {
  const blocked = busy || !available;
  if (refreshState.status === "pending") {
    return { action: "none", label: "Saving briefing…", disabled: true, windowDisabled: true };
  }
  if (refreshState.status === "uncertain") {
    return {
      action: "retry_same", label: "Retry same briefing request",
      disabled: blocked, windowDisabled: true,
    };
  }
  if (refreshState.status === "rejected") {
    return {
      action: "reload_state", label: "Reload saved state",
      disabled: blocked, windowDisabled: false,
    };
  }
  if (refreshState.status === "authorization") {
    return { action: "none", label: "Briefing unavailable", disabled: true, windowDisabled: true };
  }
  if (refreshState.status === "rate_limited") {
    const remaining = Math.max(0, Math.ceil((refreshState.retryAt - nowMs) / 1000));
    if (remaining > 0) {
      return {
        action: "wait", label: "Wait " + remaining + " seconds to retry",
        disabled: true, windowDisabled: false,
      };
    }
  }
  return {
    action: "new", label: hasSnapshot ? "Refresh briefing" : "Create briefing",
    disabled: blocked, windowDisabled: busy,
  };
}

function messageForStatus(status) {
  if (status === 401) return "Your session ended. Sign in again to continue.";
  if (status === 403) return "This account cannot access the briefing.";
  if (status === 404 || status === 503) return "Briefings are not available for this account yet.";
  if (status === 409) return "The saved briefing changed. Reload it and review before trying again.";
  return "The briefing request could not be completed.";
}

function isRecord(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function boundedString(value, max = 128) {
  return typeof value === "string" && value.length > 0 && value.length <= max;
}

function reference(value, field) {
  if (typeof value !== "string" || !REFERENCE_RE.test(value)) {
    throw new Error("The saved briefing response is malformed.");
  }
  return value;
}

function timestamp(value, nullable = false) {
  if (nullable && value === null) return null;
  if (typeof value !== "string" || value.length > 40 || !TIMESTAMP_RE.test(value)
      || Number.isNaN(Date.parse(value))) {
    throw new Error("The saved briefing response is malformed.");
  }
  return value;
}

function revision(value) {
  if (!Number.isSafeInteger(value) || value < 0) {
    throw new Error("The saved briefing response is malformed.");
  }
  return value;
}

function nullableText(value, max = 128) {
  if (value === null) return null;
  if (!boundedString(value, max)) throw new Error("The saved briefing response is malformed.");
  return value;
}

function projectPrice(item) {
  if (!isRecord(item) || typeof item.symbol !== "string" || !SYMBOL_RE.test(item.symbol)
      || typeof item.asset_type !== "string" || !/^[a-z][a-z0-9_]{0,31}$/.test(item.asset_type)
      || !["threshold_crossed", "below_threshold", "first_observation", "insufficient_history", "unavailable"].includes(item.state)) {
    throw new Error("The saved briefing response is malformed.");
  }
  if (item.change_bps !== null
      && (typeof item.change_bps !== "string" || item.change_bps.length > 90 || !DECIMAL_RE.test(item.change_bps))) {
    throw new Error("The saved briefing response is malformed.");
  }
  const scored = item.state === "threshold_crossed" || item.state === "below_threshold";
  if ((scored && (item.change_bps === null || item.reason !== null
      || item.baseline_at === null || item.observed_at === null || item.currency === null || item.provider === null))
      || (!scored && item.change_bps !== null)) {
    throw new Error("The saved briefing response is malformed.");
  }
  const currency = nullableText(item.currency, 3);
  if (currency !== null && !/^[A-Z]{3}$/.test(currency)) throw new Error("The saved briefing response is malformed.");
  const provider = nullableText(item.provider, 80);
  if (provider !== null && !/^[A-Za-z0-9_.:-]{1,80}$/.test(provider)) {
    throw new Error("The saved briefing response is malformed.");
  }
  const reason = nullableText(item.reason, 80);
  if (reason !== null && !/^[a-z][a-z0-9_]{0,79}$/.test(reason)) {
    throw new Error("The saved briefing response is malformed.");
  }
  return {
    symbol: item.symbol,
    asset_type: item.asset_type,
    state: item.state,
    baseline_at: timestamp(item.baseline_at, true),
    observed_at: timestamp(item.observed_at, true),
    currency,
    provider,
    change_bps: item.change_bps,
    reason,
  };
}

function projectOutcome(item) {
  if (!isRecord(item) || !["observed", "corrected", "unavailable", "incomparable", "manual_review"].includes(item.state)
      || !Number.isSafeInteger(item.revision) || item.revision < 1) {
    throw new Error("The saved briefing response is malformed.");
  }
  return {
    resource_ref: reference(item.resource_ref, "resource_ref"),
    state: item.state,
    revision: item.revision,
    recorded_at: timestamp(item.recorded_at),
    observed_at: timestamp(item.observed_at, true),
    correction_of: item.correction_of === null ? null : reference(item.correction_of, "correction_of"),
  };
}

function projectAlert(item) {
  if (!isRecord(item) || typeof item.symbol !== "string" || !SYMBOL_RE.test(item.symbol)
      || typeof item.asset_type !== "string" || !/^[a-z][a-z0-9_]{0,31}$/.test(item.asset_type)) {
    throw new Error("The saved briefing response is malformed.");
  }
  return {
    resource_ref: reference(item.resource_ref, "resource_ref"),
    symbol: item.symbol,
    asset_type: item.asset_type,
    triggered_at: timestamp(item.triggered_at),
  };
}

function projectReview(item) {
  if (!isRecord(item) || !Number.isSafeInteger(item.revision) || item.revision < 1) {
    throw new Error("The saved briefing response is malformed.");
  }
  return {
    thesis_ref: reference(item.thesis_ref, "thesis_ref"),
    revision: item.revision,
    due_at: timestamp(item.due_at),
  };
}

function boundedItems(value, project) {
  if (!Array.isArray(value) || value.length > MAX_ITEMS_PER_SOURCE) {
    throw new Error("The saved briefing response is malformed.");
  }
  return value.map(project);
}

export function projectBriefingSnapshot(value) {
  if (!isRecord(value) || typeof value.id !== "string" || !UUID_RE.test(value.id)
      || !BRIEFING_WINDOWS.includes(value.window)
      || !Number.isSafeInteger(value.threshold_bps)
      || value.threshold_bps < 50 || value.threshold_bps > 1000
      || !Number.isSafeInteger(value.baseline_anchor_revision) || value.baseline_anchor_revision < 0
      || !Number.isSafeInteger(value.preference_revision) || value.preference_revision < 0) {
    throw new Error("The saved briefing response is malformed.");
  }
  return {
    id: value.id.toLowerCase(),
    window: value.window,
    baseline_at: timestamp(value.baseline_at, true),
    observed_as_of: timestamp(value.observed_as_of),
    generated_at: timestamp(value.generated_at),
    threshold_bps: value.threshold_bps,
    baseline_anchor_revision: value.baseline_anchor_revision,
    preference_revision: value.preference_revision,
    price_changes: boundedItems(value.price_changes, projectPrice),
    outcome_changes: boundedItems(value.outcome_changes, projectOutcome),
    triggered_alerts: boundedItems(value.triggered_alerts, projectAlert),
    due_thesis_reviews: boundedItems(value.due_thesis_reviews, projectReview),
  };
}

export function projectBriefingState(value) {
  if (!isRecord(value) || !isRecord(value.features) || !isRecord(value.preference)
      || !isRecord(value.visit_anchor)
      || ["enabled", "headlines_available", "digest_available", "assistant_available"]
        .some((key) => typeof value.features[key] !== "boolean")) {
    throw new Error("The briefing status response is malformed.");
  }
  const threshold = value.preference.threshold_bps;
  if (!Number.isSafeInteger(threshold) || threshold < 50 || threshold > 1000) {
    throw new Error("The briefing status response is malformed.");
  }
  const anchor = value.visit_anchor;
  if ((anchor.baseline_at !== null && anchor.baseline_at !== undefined)
      !== (anchor.snapshot_id !== null && anchor.snapshot_id !== undefined)
      || (anchor.visited_at !== null && anchor.visited_at !== undefined)
        !== (anchor.snapshot_id !== null && anchor.snapshot_id !== undefined)) {
    throw new Error("The briefing status response is malformed.");
  }
  const snapshotId = anchor.snapshot_id ?? null;
  if (snapshotId !== null && (typeof snapshotId !== "string" || !UUID_RE.test(snapshotId))) {
    throw new Error("The briefing status response is malformed.");
  }
  return {
    features: {
      enabled: value.features.enabled,
      headlines_available: value.features.headlines_available,
      digest_available: value.features.digest_available,
      assistant_available: value.features.assistant_available,
    },
    server_time: timestamp(value.server_time),
    preference: {
      revision: revision(value.preference.revision),
      threshold_bps: threshold,
      updated_at: timestamp(value.preference.updated_at, true),
    },
    visit_anchor: {
      revision: revision(anchor.revision),
      baseline_at: timestamp(anchor.baseline_at ?? null, true),
      snapshot_id: snapshotId,
      visited_at: timestamp(anchor.visited_at ?? null, true),
    },
  };
}

export function createLatestRequestLane() {
  let current = null;
  let sequence = 0;
  return {
    begin() {
      if (current) current.abort();
      const controller = new AbortController();
      current = controller;
      const requestId = ++sequence;
      return {
        signal: controller.signal,
        isCurrent: () => current === controller && requestId === sequence && !controller.signal.aborted,
      };
    },
    cancel() {
      sequence += 1;
      if (current) current.abort();
      current = null;
    },
  };
}

function secureUuid(uuidFactory) {
  const create = uuidFactory ?? globalThis.crypto?.randomUUID?.bind(globalThis.crypto);
  if (typeof create !== "function") throw new Error("Secure request retry is unavailable in this browser.");
  const value = create();
  if (typeof value !== "string" || !UUID_RE.test(value)) {
    throw new Error("The request could not be safely prepared.");
  }
  return value.toLowerCase();
}

export function createSnapshotAttempt(window, observedAsOf, uuidFactory) {
  if (!BRIEFING_WINDOWS.includes(window)) throw new Error("Choose a supported briefing window.");
  const asOf = timestamp(observedAsOf);
  const idempotencyKey = secureUuid(uuidFactory);
  const body = JSON.stringify({ window, observed_as_of: asOf });
  return Object.freeze({ window, observedAsOf: asOf, idempotencyKey, body });
}

async function readBoundedJson(response) {
  if (!response.body || typeof response.body.getReader !== "function") {
    throw new Error("The briefing response is unavailable.");
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
        await reader.cancel();
        throw new Error("The briefing response exceeded its size limit.");
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
    throw new Error("The briefing response is malformed.");
  }
}

async function requestJson(apiFetch, path, options) {
  const response = await apiFetch(path, { cache: "no-store", ...options });
  if (!response.ok) {
    try { await response.body?.cancel(); } catch {}
    const retryAfterSeconds = response.status === 429
      ? parseRetryAfter(response.headers.get("Retry-After"), Date.now()) : null;
    throw new BriefingRequestError(response.status, retryAfterSeconds);
  }
  const value = await readBoundedJson(response);
  if (!isRecord(value)) throw new Error("The briefing response is malformed.");
  return value;
}

function checkedPage(value) {
  if (!isRecord(value) || !Array.isArray(value.items) || value.items.length > MAX_PAGE_SIZE
      || !(value.next_cursor === null || (typeof value.next_cursor === "string" && UUID_RE.test(value.next_cursor)))) {
    throw new Error("The briefing history response is malformed.");
  }
  return {
    items: value.items.map(projectBriefingSnapshot),
    next_cursor: value.next_cursor,
  };
}

export function createBriefingClient(apiFetch) {
  if (typeof apiFetch !== "function") throw new TypeError("A same-origin authenticated request helper is required.");
  return Object.freeze({
    async getState(options = {}) {
      return projectBriefingState(await requestJson(apiFetch, "/api/v1/briefing-state", {
        method: "GET",
        signal: options.signal,
      }));
    },
    async listSnapshots(options = {}) {
      const limit = options.limit ?? MAX_PAGE_SIZE;
      if (!Number.isSafeInteger(limit) || limit < 1 || limit > MAX_PAGE_SIZE) {
        throw new Error("The briefing history page size is invalid.");
      }
      const query = new URLSearchParams({ limit: String(limit) });
      if (options.cursor !== undefined && options.cursor !== null) {
        if (typeof options.cursor !== "string" || !UUID_RE.test(options.cursor)) {
          throw new Error("The briefing history cursor is invalid.");
        }
        query.set("cursor", options.cursor);
      }
      return checkedPage(await requestJson(apiFetch, "/api/v1/briefings?" + query.toString(), {
        method: "GET",
        signal: options.signal,
      }));
    },
    async getSnapshot(snapshotId, options = {}) {
      if (typeof snapshotId !== "string" || !UUID_RE.test(snapshotId)) {
        throw new Error("The saved briefing is unavailable.");
      }
      return projectBriefingSnapshot(await requestJson(apiFetch,
        "/api/v1/briefings/" + encodeURIComponent(snapshotId), {
          method: "GET",
          signal: options.signal,
        }));
    },
    async createSnapshot(attempt) {
      if (!attempt || !UUID_RE.test(attempt.idempotencyKey)
          || !BRIEFING_WINDOWS.includes(attempt.window)
          || typeof attempt.body !== "string" || attempt.body.length > 256) {
        throw new Error("The briefing retry request is invalid.");
      }
      const expectedBody = JSON.stringify({ window: attempt.window, observed_as_of: timestamp(attempt.observedAsOf) });
      if (attempt.body !== expectedBody) throw new Error("The briefing retry request is invalid.");
      const value = await requestJson(apiFetch, "/api/v1/briefings", {
        method: "POST",
        headers: { "Content-Type": "application/json", "Idempotency-Key": attempt.idempotencyKey },
        body: attempt.body,
      });
      return projectBriefingSnapshot(value);
    },
    async updateThreshold(thresholdBps, expectedRevision) {
      if (!Number.isSafeInteger(thresholdBps) || thresholdBps < 50 || thresholdBps > 1000
          || !Number.isSafeInteger(expectedRevision) || expectedRevision < 0) {
        throw new Error("The threshold change is invalid.");
      }
      const value = await requestJson(apiFetch, "/api/v1/briefing-preference", {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ threshold_bps: thresholdBps, expected_revision: expectedRevision }),
      });
      const threshold = value.threshold_bps;
      if (!Number.isSafeInteger(value.revision) || value.revision < 1
          || !Number.isSafeInteger(threshold) || threshold < 50 || threshold > 1000) {
        throw new Error("The threshold response is malformed.");
      }
      return {
        revision: value.revision,
        threshold_bps: threshold,
        updated_at: timestamp(value.updated_at),
      };
    },
    async recordVisit(snapshotId, expectedRevision) {
      if (typeof snapshotId !== "string" || !UUID_RE.test(snapshotId)
          || !Number.isSafeInteger(expectedRevision) || expectedRevision < 0) {
        throw new Error("The visit acknowledgement is invalid.");
      }
      const value = await requestJson(apiFetch,
        "/api/v1/briefings/" + encodeURIComponent(snapshotId) + "/visits", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ expected_revision: expectedRevision }),
        });
      if (!Number.isSafeInteger(value.revision) || value.revision < 1
          || value.snapshot_id !== snapshotId) {
        throw new Error("The visit acknowledgement response is malformed.");
      }
      return {
        revision: value.revision,
        snapshot_id: snapshotId,
        baseline_at: timestamp(value.baseline_at),
        visited_at: timestamp(value.visited_at),
      };
    },
  });
}
