import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import {
  BriefingRequestError,
  IDLE_REFRESH_STATE,
  classifyBriefingFailure,
  createBriefingClient,
  createLatestRequestLane,
  createSnapshotAttempt,
  projectBriefingSnapshot,
  refreshButtonModel,
  refreshStateReducer,
} from "../components/briefing/briefing-client.mjs";

const snapshotId = "11111111-1111-4111-8111-111111111111";
const asOf = "2026-10-14T14:00:00.000000Z";
const workspaceSource = await readFile(new URL("../components/briefing/briefing-workspace.tsx", import.meta.url), "utf8");
const workspaceStyles = await readFile(new URL("../components/briefing/briefing.module.css", import.meta.url), "utf8");

function savedSnapshot(overrides = {}) {
  return {
    id: snapshotId,
    window: "last_24_hours",
    baseline_at: "2026-10-13T14:00:00.000000Z",
    observed_as_of: asOf,
    generated_at: asOf,
    threshold_bps: 300,
    baseline_anchor_revision: 0,
    preference_revision: 0,
    price_changes: [{
      symbol: "ACDC", asset_type: "stock", state: "threshold_crossed",
      baseline_at: "2026-10-13T14:00:00.000000Z", observed_at: asOf,
      currency: "USD", provider: "fixture", change_bps: "350", reason: null,
      owner_user_id: 9, price: "999999", account_balance: "private",
    }],
    outcome_changes: [{
      resource_ref: "event.12", state: "manual_review", revision: 2,
      recorded_at: asOf, observed_at: null, correction_of: null,
      thesis_text: "must not cross the UI boundary",
    }],
    triggered_alerts: [],
    due_thesis_reviews: [{
      thesis_ref: "thesis.7", revision: 4, due_at: asOf,
      title: "private title must not be projected",
    }],
    owner_user_id: 9,
    idempotency_key: "private-idempotency-key",
    request_sha256: "a".repeat(64),
    ...overrides,
  };
}

test("snapshot projection retains the approved safe DTO and drops private fields", () => {
  const result = projectBriefingSnapshot(savedSnapshot());
  assert.equal(result.price_changes[0].symbol, "ACDC");
  assert.equal(result.outcome_changes[0].state, "manual_review");
  assert.equal(result.due_thesis_reviews[0].thesis_ref, "thesis.7");
  assert.equal("owner_user_id" in result, false);
  assert.equal("idempotency_key" in result, false);
  assert.equal("request_sha256" in result, false);
  assert.equal("price" in result.price_changes[0], false);
  assert.equal("thesis_text" in result.outcome_changes[0], false);
  assert.equal("title" in result.due_thesis_reviews[0], false);
});

test("snapshot projection rejects inconsistent score state and unbounded source labels", () => {
  const pendingWithScore = savedSnapshot({
    price_changes: [{
      symbol: "ACDC", asset_type: "stock", state: "first_observation",
      baseline_at: null, observed_at: asOf, currency: "USD", provider: "fixture",
      change_bps: "350", reason: null,
    }],
  });
  assert.throws(() => projectBriefingSnapshot(pendingWithScore), /malformed/);
  const injection = savedSnapshot({
    price_changes: [{
      symbol: "ACDC", asset_type: "stock", state: "threshold_crossed",
      baseline_at: "2026-10-13T14:00:00.000000Z", observed_at: asOf,
      currency: "USD", provider: "fixture\nprivate note", change_bps: "350", reason: null,
    }],
  });
  assert.throws(() => projectBriefingSnapshot(injection), /malformed/);
});

test("latest request lane aborts superseded reads and rejects stale completion", () => {
  const lane = createLatestRequestLane();
  const first = lane.begin();
  const second = lane.begin();
  assert.equal(first.signal.aborted, true);
  assert.equal(first.isCurrent(), false);
  assert.equal(second.signal.aborted, false);
  assert.equal(second.isCurrent(), true);
  lane.cancel();
  assert.equal(second.signal.aborted, true);
  assert.equal(second.isCurrent(), false);
});

test("an ambiguous failed create exposes same-key retry and reuses the exact body", async () => {
  const calls = [];
  const client = createBriefingClient(async (path, options) => {
    calls.push({ path, options });
    return calls.length === 1
      ? new Response("temporary failure", { status: 503 })
      : new Response(JSON.stringify(savedSnapshot()), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
  });
  const attempt = createSnapshotAttempt("last_24_hours", asOf, () => snapshotId);
  let refreshState = refreshStateReducer(IDLE_REFRESH_STATE, { type: "begin", attempt });

  await assert.rejects(client.createSnapshot(attempt), (error) => {
    const failure = classifyBriefingFailure(error);
    assert.deepEqual(failure, { kind: "uncertain", status: 503 });
    refreshState = refreshStateReducer(refreshState, { type: "failed", failure, at: 1000 });
    assert.deepEqual(refreshButtonModel(refreshState), {
      action: "retry_same", label: "Retry same briefing request", disabled: false, windowDisabled: true,
    });
    return true;
  });
  const retryControl = refreshButtonModel(refreshState);
  assert.equal(retryControl.action, "retry_same");
  refreshState = refreshStateReducer(refreshState, { type: "retry" });
  await client.createSnapshot(refreshState.attempt);
  refreshState = refreshStateReducer(refreshState, { type: "succeeded" });
  assert.equal(refreshState.status, "idle");

  assert.equal(calls.length, 2);
  assert.equal(calls[0].path, "/api/v1/briefings");
  assert.equal(calls[0].options.method, "POST");
  assert.equal(calls[0].options.headers["Idempotency-Key"], snapshotId);
  assert.equal(calls[0].options.body, calls[1].options.body);
  assert.equal(calls[0].options.headers["Idempotency-Key"], calls[1].options.headers["Idempotency-Key"]);
  assert.equal(calls[0].options.body, JSON.stringify({ window: "last_24_hours", observed_as_of: asOf }));
});

test("a definitive 409 requires an explicit reload before a fresh request is available", async () => {
  const calls = [];
  const client = createBriefingClient(async (path, options) => {
    calls.push({ path, options });
    if (options.method === "POST") {
      return calls.filter((call) => call.options.method === "POST").length === 1
        ? new Response("conflict", { status: 409 })
        : new Response(JSON.stringify(savedSnapshot({ id: "22222222-2222-4222-8222-222222222222" })), { status: 201 });
    }
    if (path === "/api/v1/briefing-state") {
      return new Response(JSON.stringify({
        features: { enabled: true, headlines_available: false, digest_available: false, assistant_available: false },
        server_time: "2026-10-14T15:00:00.000000Z",
        preference: { revision: 1, threshold_bps: 300, updated_at: null },
        visit_anchor: { revision: 0, baseline_at: null, snapshot_id: null, visited_at: null },
      }), { status: 200 });
    }
    return new Response(JSON.stringify({ items: [], next_cursor: null }), { status: 200 });
  });

  const firstAttempt = createSnapshotAttempt("last_24_hours", asOf, () => snapshotId);
  let state = refreshStateReducer(IDLE_REFRESH_STATE, { type: "begin", attempt: firstAttempt });
  await assert.rejects(client.createSnapshot(firstAttempt), (error) => {
    const failure = classifyBriefingFailure(error);
    assert.deepEqual(failure, { kind: "conflict", status: 409 });
    state = refreshStateReducer(state, { type: "failed", failure, at: 1000 });
    return true;
  });
  const rejectedControl = refreshButtonModel(state, { hasSnapshot: true });
  assert.equal(rejectedControl.action, "reload_state");
  assert.equal(rejectedControl.windowDisabled, false);
  assert.equal(calls.length, 1, "the rejection must not trigger an automatic POST or GET");

  await Promise.all([client.getState(), client.listSnapshots({ limit: 20 })]);
  state = refreshStateReducer(state, { type: "reset" });
  const nextAttempt = createSnapshotAttempt("last_7_days", "2026-10-14T15:00:00.000000Z", () => "33333333-3333-4333-8333-333333333333");
  assert.equal(refreshButtonModel(state, { hasSnapshot: true }).action, "new");
  assert.notEqual(nextAttempt.idempotencyKey, firstAttempt.idempotencyKey);
  assert.notEqual(nextAttempt.body, firstAttempt.body);
  state = refreshStateReducer(state, { type: "begin", attempt: nextAttempt });
  await client.createSnapshot(state.attempt);
  assert.equal(calls.filter((call) => call.options.method === "POST").length, 2);
  assert.equal(calls.at(-1).options.headers["Idempotency-Key"], nextAttempt.idempotencyKey);
});

test("a failed same-key replay becomes a reload action, not an endless retry", async () => {
  const calls = [];
  const client = createBriefingClient(async (path, options) => {
    calls.push({ path, options });
    return new Response(calls.length === 1 ? "temporary failure" : "conflict", {
      status: calls.length === 1 ? 503 : 409,
    });
  });
  const attempt = createSnapshotAttempt("since_last_visit", asOf, () => snapshotId);
  let state = refreshStateReducer(IDLE_REFRESH_STATE, { type: "begin", attempt });
  await assert.rejects(client.createSnapshot(attempt), (error) => {
    state = refreshStateReducer(state, {
      type: "failed", failure: classifyBriefingFailure(error), at: 1000,
    });
    return true;
  });
  state = refreshStateReducer(state, { type: "retry" });
  await assert.rejects(client.createSnapshot(state.attempt), (error) => {
    state = refreshStateReducer(state, {
      type: "failed", failure: classifyBriefingFailure(error), at: 2000,
    });
    return true;
  });
  assert.deepEqual(refreshButtonModel(state), {
    action: "reload_state", label: "Reload saved state", disabled: false, windowDisabled: false,
  });
  assert.equal(calls.length, 2);
  assert.equal(calls[0].options.headers["Idempotency-Key"], calls[1].options.headers["Idempotency-Key"]);
  assert.equal(calls[0].options.body, calls[1].options.body);
  assert.equal(calls[0].options.headers["Idempotency-Key"], attempt.idempotencyKey);
  assert.equal(calls[0].options.body, attempt.body);
});

test("429 Retry-After blocks fresh attempts until an explicit retry time", async () => {
  let calls = 0;
  const client = createBriefingClient(async () => {
    calls += 1;
    return new Response("slow down", {
    status: 429, headers: { "Retry-After": "17" },
    });
  });
  const attempt = createSnapshotAttempt("since_last_visit", asOf, () => snapshotId);
  let state = refreshStateReducer(IDLE_REFRESH_STATE, { type: "begin", attempt });
  await assert.rejects(client.createSnapshot(attempt), (error) => {
    assert.equal(error.retryAfterSeconds, 17);
    state = refreshStateReducer(state, {
      type: "failed", failure: classifyBriefingFailure(error), at: 1000,
    });
    return true;
  });
  assert.deepEqual(refreshButtonModel(state, { nowMs: 1000 }), {
    action: "wait", label: "Wait 17 seconds to retry", disabled: true, windowDisabled: false,
  });
  assert.equal(refreshButtonModel(state, { nowMs: 17999 }).action, "wait");
  assert.equal(refreshButtonModel(state, { nowMs: 18000 }).action, "new");
  assert.equal(calls, 1, "waiting and the explicit-action model must not send another request");

  const longerWaitClient = createBriefingClient(async () => new Response("slow down", {
    status: 429, headers: { "Retry-After": "9000" },
  }));
  const longerWaitAttempt = createSnapshotAttempt("last_24_hours", asOf, () => "55555555-5555-4555-8555-555555555555");
  await assert.rejects(longerWaitClient.createSnapshot(longerWaitAttempt), (error) => {
    assert.equal(error.retryAfterSeconds, 9000);
    return true;
  });

  const fixedNow = 1791900000000;
  const originalNow = Date.now;
  Date.now = () => fixedNow;
  try {
    const dateHeaderClient = createBriefingClient(async () => new Response("slow down", {
      status: 429, headers: { "Retry-After": new Date(fixedNow + 25000).toUTCString() },
    }));
    await assert.rejects(dateHeaderClient.createSnapshot(longerWaitAttempt), (error) => {
      assert.equal(error.retryAfterSeconds, 25);
      return true;
    });
  } finally {
    Date.now = originalNow;
  }

  const invalidHeaderClient = createBriefingClient(async () => new Response("slow down", {
    status: 429, headers: { "Retry-After": "whenever" },
  }));
  const invalidHeaderAttempt = createSnapshotAttempt("since_last_visit", asOf, () => "44444444-4444-4444-8444-444444444444");
  let fallbackState = refreshStateReducer(IDLE_REFRESH_STATE, {
    type: "begin", attempt: invalidHeaderAttempt,
  });
  await assert.rejects(invalidHeaderClient.createSnapshot(invalidHeaderAttempt), (error) => {
    assert.equal(error.retryAfterSeconds, null);
    fallbackState = refreshStateReducer(fallbackState, {
      type: "failed", failure: classifyBriefingFailure(error), at: 2000,
    });
    return true;
  });
  assert.equal(refreshButtonModel(fallbackState, { nowMs: 2000 }).label, "Wait 30 seconds to retry");
});

test("authorization failures clear private workspace state and disable briefing actions", () => {
  for (const status of [401, 403]) {
    let state = refreshStateReducer(IDLE_REFRESH_STATE, {
      type: "begin", attempt: createSnapshotAttempt("since_last_visit", asOf, () => snapshotId),
    });
    state = refreshStateReducer(state, {
      type: "failed", failure: classifyBriefingFailure(new BriefingRequestError(status)), at: 1000,
    });
    assert.equal(state.status, "authorization");
    assert.equal(refreshButtonModel(state).disabled, true);
  }
});

test("history and threshold access use bounded reads and explicit revisioned writes", async () => {
  const calls = [];
  const client = createBriefingClient(async (path, options) => {
    calls.push({ path, options });
    const body = path.startsWith("/api/v1/briefings?")
      ? { items: [savedSnapshot()], next_cursor: null }
      : { revision: 3, threshold_bps: 450, updated_at: asOf };
    return new Response(JSON.stringify(body), { status: 200 });
  });

  const page = await client.listSnapshots({ limit: 20 });
  assert.equal(page.items[0].id, snapshotId);
  assert.match(calls[0].path, /limit=20/);
  assert.equal(calls[0].options.method, "GET");

  const preference = await client.updateThreshold(450, 2);
  assert.deepEqual(preference, { revision: 3, threshold_bps: 450, updated_at: asOf });
  assert.equal(calls[1].options.method, "PATCH");
  assert.deepEqual(JSON.parse(calls[1].options.body), { threshold_bps: 450, expected_revision: 2 });
  await assert.rejects(client.listSnapshots({ limit: 500 }), /page size/);
});

test("rejected CAS remains visible as a safe conflict and does not retry by itself", async () => {
  let calls = 0;
  const client = createBriefingClient(async () => {
    calls += 1;
    return new Response("{}", { status: 409 });
  });
  await assert.rejects(client.updateThreshold(500, 1), (error) => {
    assert.ok(error instanceof BriefingRequestError);
    assert.equal(error.status, 409);
    assert.match(error.message, /changed/);
    return true;
  });
  assert.equal(calls, 1);
});

test("visit acknowledgement is an explicit revisioned action against the selected immutable snapshot", async () => {
  let call;
  const client = createBriefingClient(async (path, options) => {
    call = { path, options };
    return new Response(JSON.stringify({
      revision: 5,
      snapshot_id: snapshotId,
      baseline_at: asOf,
      visited_at: asOf,
      owner_user_id: 9,
    }), { status: 200 });
  });
  const visit = await client.recordVisit(snapshotId, 4);
  assert.deepEqual(visit, { revision: 5, snapshot_id: snapshotId, baseline_at: asOf, visited_at: asOf });
  assert.equal(call.path, "/api/v1/briefings/" + snapshotId + "/visits");
  assert.equal(call.options.method, "POST");
  assert.deepEqual(JSON.parse(call.options.body), { expected_revision: 4 });
});

test("snapshot creation rejects unsupported windows, invalid server time, and non-UUID keys", () => {
  assert.throws(() => createSnapshotAttempt("custom", asOf, () => snapshotId), /supported/);
  assert.throws(() => createSnapshotAttempt("last_24_hours", "tomorrow", () => snapshotId), /malformed/);
  assert.throws(() => createSnapshotAttempt("last_24_hours", asOf, () => "unsafe"), /safely prepared/);
});

test("oversized response bodies fail closed before their payload is projected", async () => {
  const client = createBriefingClient(async () => new Response(" ".repeat(2 * 1024 * 1024 + 1)));
  await assert.rejects(client.getSnapshot(snapshotId), /size limit/);
});

test("opening the workspace only reads status and saved history; writes stay behind explicit handlers", () => {
  assert.match(workspaceSource, /useEffect\(\(\) => \{\s*void loadWorkspace\(\)/);
  assert.match(workspaceSource, /client\.getState\(\{ signal: request\.signal \}\)[\s\S]*client\.listSnapshots\(\{ limit: 20, signal: request\.signal \}\)/);
  assert.match(workspaceSource, /async function refreshBriefing\(\)[\s\S]*client\.createSnapshot\(attempt\)/);
  assert.match(workspaceSource, /refreshButtonModel\(refreshState/);
  assert.match(workspaceSource, /control\.action === "reload_state"[\s\S]*await loadWorkspace\(\)/);
  assert.match(workspaceSource, /classifyBriefingFailure\(cause\)/);
  assert.match(workspaceSource, /disabled=\{busy !== null \|\| loadState !== "ready" \|\| refreshControl\.windowDisabled\}/);
  assert.match(workspaceSource, /disabled=\{actionsDisabled \|\| refreshControl\.disabled\}/);
  assert.match(workspaceSource, /clearPrivateView\(\)/);
  assert.match(workspaceSource, /Daily email is currently unavailable\./);
  assert.doesNotMatch(workspaceSource, /settings are reported available, but are not connected to this view/);
  assert.match(workspaceStyles, /\.page button,\.page select,\.page input\{min-height:44px\}/);
  assert.match(workspaceSource, /async function saveThreshold\(/);
  assert.match(workspaceSource, /async function markReviewed\(/);
  assert.match(workspaceSource, /Explain selected changes[\s\S]*disabled/);
  assert.match(workspaceSource, /Configure daily email[\s\S]*disabled/);
  assert.doesNotMatch(workspaceSource, /localStorage|sessionStorage|dangerouslySetInnerHTML/);
});

test("a GET-only initial load cannot silently create a snapshot", async () => {
  const calls = [];
  const client = createBriefingClient(async (path, options) => {
    calls.push({ path, method: options.method });
    const value = path === "/api/v1/briefing-state"
      ? {
        features: { enabled: true, headlines_available: false, digest_available: false, assistant_available: false },
        server_time: asOf,
        preference: { revision: 0, threshold_bps: 300, updated_at: null },
        visit_anchor: { revision: 0, baseline_at: null, snapshot_id: null, visited_at: null },
      }
      : { items: [], next_cursor: null };
    return new Response(JSON.stringify(value), { status: 200 });
  });
  await Promise.all([client.getState(), client.listSnapshots({ limit: 20 })]);
  assert.deepEqual(calls.map((call) => call.method), ["GET", "GET"]);
  assert.equal(calls.some((call) => call.path === "/api/v1/briefings"), false);
});
