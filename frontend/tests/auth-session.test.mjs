import assert from "node:assert/strict";
import test from "node:test";

let moduleId = 0;
async function freshClient() {
  const url = new URL("../components/auth-client.ts", import.meta.url);
  url.searchParams.set("test-instance", String(++moduleId));
  return import(url.href);
}

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}

function sessionResponse(authenticated = true) {
  return Response.json({ authenticated });
}

test("concurrent session consumers share only the pending server check", async (t) => {
  const client = await freshClient();
  const pending = deferred();
  const calls = [];
  t.mock.method(globalThis, "fetch", (path, options) => {
    calls.push({ path, options });
    return calls.length === 1 ? pending.promise.then(() => sessionResponse()) : Promise.resolve(sessionResponse(false));
  });
  const first = client.getAuthSession();
  const second = client.getAuthSession();
  assert.equal(calls.length, 1, "account controls and assistant must share their simultaneous check");
  assert.equal(calls[0].path, "/api/v1/auth/session");
  assert.equal(calls[0].options.cache, "no-store");
  assert.equal(calls[0].options.credentials, "include");
  pending.resolve();
  assert.deepEqual(await first, { authenticated: true });
  assert.deepEqual(await second, { authenticated: true });
  assert.deepEqual(await client.getAuthSession(), { authenticated: false });
  assert.equal(calls.length, 2, "a settled result must never become a session cache");
});

test("failed shared checks release the request and preserve authentication errors", async (t) => {
  const client = await freshClient();
  const pending = deferred();
  let calls = 0;
  t.mock.method(globalThis, "fetch", () => {
    calls += 1;
    return calls === 1 ? pending.promise : Promise.resolve(Response.json({}, { status: 401 }));
  });
  const first = client.getAuthSession();
  const second = client.getAuthSession();
  const results = Promise.allSettled([first, second]);
  pending.reject(new Error("fixture network unavailable"));
  assert.deepEqual((await results).map((row) => row.status), ["rejected", "rejected"]);
  assert.equal(calls, 1);
  assert.equal(await client.getAuthSession(), null);
  assert.equal(calls, 2);
});

test("account mutations separate checks before, during, and after the request", async (t) => {
  const client = await freshClient();
  const oldCheck = deferred();
  const duringCheck = deferred();
  const mutation = deferred();
  let sessionCalls = 0;
  t.mock.method(globalThis, "fetch", (path) => {
    if (path === "/api/v1/auth/logout") return mutation.promise;
    sessionCalls += 1;
    if (sessionCalls === 1) return oldCheck.promise;
    if (sessionCalls === 2) return duringCheck.promise;
    return Promise.resolve(sessionResponse(false));
  });
  const before = client.getAuthSession();
  const logout = client.authRequest("/api/v1/auth/logout", {
    method: "POST", headers: { "X-CSRF-Token": "fixture-token" }, body: "{}",
  });
  const during = client.getAuthSession();
  assert.equal(sessionCalls, 2, "a check after mutation dispatch cannot join the pre-mutation check");
  mutation.resolve(Response.json({}));
  await logout;
  assert.deepEqual(await client.getAuthSession(), { authenticated: false });
  assert.equal(sessionCalls, 3, "a check after mutation completion cannot join an earlier check");
  oldCheck.resolve(sessionResponse());
  duringCheck.resolve(sessionResponse());
  await Promise.all([before, during]);
});

test("an earlier check settling cannot remove a newer pending check", async (t) => {
  const client = await freshClient();
  const oldCheck = deferred();
  const newCheck = deferred();
  let sessionCalls = 0;
  t.mock.method(globalThis, "fetch", (path) => {
    if (path !== "/api/v1/auth/session") return Promise.resolve(Response.json({}));
    sessionCalls += 1;
    return sessionCalls === 1 ? oldCheck.promise : newCheck.promise.then(() => sessionResponse(false));
  });
  const before = client.getAuthSession();
  await client.apiFetch("/api/v1/auth/logout", {
    method: "POST", headers: { "X-CSRF-Token": "fixture-token" }, body: "{}",
  });
  const newer = client.getAuthSession();
  oldCheck.resolve(sessionResponse());
  await before;
  const joined = client.getAuthSession();
  assert.equal(sessionCalls, 2, "old completion must not discard the new shared request");
  newCheck.resolve();
  assert.deepEqual(await newer, { authenticated: false });
  assert.deepEqual(await joined, { authenticated: false });
});
