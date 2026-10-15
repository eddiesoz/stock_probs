import assert from "node:assert/strict";
import test from "node:test";

import { createBriefingPrivateLifecycle } from "../components/briefing/briefing-private-lifecycle.mjs";

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

test("session invalidation blocks a delayed saved-write result and its stale finally", async () => {
  const lifecycle = createBriefingPrivateLifecycle();
  const pendingWrite = deferred();
  const privateView = {
    snapshot: { id: "saved-before" },
    error: "",
    busy: "refresh",
    refreshState: "pending",
  };
  const writeOperation = lifecycle.capture();
  const oldRefreshLock = lifecycle.acquireRefresh();
  assert.notEqual(oldRefreshLock, null);
  let oldFinallyReleasedItsLock = null;

  const oldWrite = (async () => {
    try {
      const snapshot = await pendingWrite.promise;
      writeOperation.commit(() => { privateView.snapshot = snapshot; });
    } catch (error) {
      writeOperation.commit(() => { privateView.error = error.message; });
    } finally {
      writeOperation.commit(() => { privateView.busy = null; });
      oldFinallyReleasedItsLock = lifecycle.releaseRefresh(oldRefreshLock);
    }
  })();

  lifecycle.invalidate();
  privateView.snapshot = null;
  privateView.error = "Your session has ended.";
  privateView.busy = null;
  privateView.refreshState = "authorization";

  const recoveryOperation = lifecycle.capture();
  const recoveryRefreshLock = lifecycle.acquireRefresh();
  assert.notEqual(recoveryRefreshLock, null);
  privateView.busy = "loading";
  pendingWrite.resolve({ id: "late-private-result" });
  await oldWrite;

  assert.equal(privateView.snapshot, null);
  assert.equal(privateView.error, "Your session has ended.");
  assert.equal(privateView.busy, "loading");
  assert.equal(privateView.refreshState, "authorization");
  assert.equal(oldFinallyReleasedItsLock, false);
  assert.equal(lifecycle.ownsRefresh(recoveryRefreshLock), true);
  assert.equal(recoveryOperation.isCurrent(), true);

  const recoveredState = await Promise.resolve({ id: "reloaded-snapshot" });
  assert.equal(recoveryOperation.commit(() => {
    privateView.snapshot = recoveredState;
    privateView.error = "";
    privateView.busy = null;
    privateView.refreshState = "idle";
  }), true);
  assert.deepEqual(privateView.snapshot, { id: "reloaded-snapshot" });
  assert.equal(privateView.refreshState, "idle");
  assert.equal(lifecycle.releaseRefresh(recoveryRefreshLock), true);
});

test("a fresh explicit load can recover after invalidation while stale errors stay suppressed", async () => {
  const lifecycle = createBriefingPrivateLifecycle();
  const pendingHistory = deferred();
  const privateView = { snapshots: [], error: "", busy: "history" };
  const oldHistoryOperation = lifecycle.capture();

  const oldHistory = (async () => {
    try {
      const page = await pendingHistory.promise;
      oldHistoryOperation.commit(() => { privateView.snapshots = page; });
    } catch (error) {
      oldHistoryOperation.commit(() => { privateView.error = error.message; });
    } finally {
      oldHistoryOperation.commit(() => { privateView.busy = null; });
    }
  })();

  lifecycle.invalidate();
  privateView.snapshots = [];
  privateView.error = "Your session has ended.";
  privateView.busy = null;

  const recoveryOperation = lifecycle.capture();
  privateView.error = "";
  privateView.busy = "loading";
  pendingHistory.reject(new Error("stale history failure"));
  await oldHistory;

  assert.deepEqual(privateView.snapshots, []);
  assert.equal(privateView.error, "");
  assert.equal(privateView.busy, "loading");

  const freshLoad = deferred();
  freshLoad.resolve([{ id: "reloaded-snapshot" }]);
  const page = await freshLoad.promise;
  assert.equal(recoveryOperation.commit(() => {
    privateView.snapshots = page;
    privateView.busy = null;
  }), true);
  assert.deepEqual(privateView.snapshots, [{ id: "reloaded-snapshot" }]);
  assert.equal(privateView.busy, null);
});
