import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";
import ts from "typescript";

function loadModule(name, dependencies, globals = {}) {
  const source = readFileSync(new URL(`../components/monitoring/${name}`, import.meta.url), "utf8");
  const code = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, target: ts.ScriptTarget.ES2020 } }).outputText;
  const exports = {};
  vm.runInNewContext(code, { exports, require(name) { assert.ok(name in dependencies, `Unexpected dependency: ${name}`); return dependencies[name]; }, Error, ...globals });
  return exports;
}

class RequestError extends Error { constructor(message, status, code) { super(message); this.status = status; this.code = code; } }
const client = loadModule("monitoring-client.ts", { "../auth-client": { AuthRequestError: RequestError, apiFetch: async () => { throw new Error("Provider calls are outside validator tests."); } } });

function notice() {
  return { id: "a1ca8674-505d-4c9e-b17a-27a3d5eb3350", kind: "price_alert", is_read: false, revision: 1, created_at: "2026-10-14T12:00:00Z", payload: { alert_id: "f1ea20ee-d20d-4b09-bf72-57f658caed55", generation: 1, symbol: "SPY", currency: "USD", threshold: "100", direction: "above", price: "101.25", provider: "Yahoo Finance", observed_at: "2026-10-14T11:59:00Z" } };
}

test("saved inbox accepts valid empty pages and rejects malformed, duplicate and oversized pages", () => {
  assert.equal(client.parseMonitoringPage({ items: [], next_cursor: null }, client.validNotification).items.length, 0);
  assert.equal(client.parseMonitoringPage({ items: [notice()], next_cursor: "bounded-cursor" }, client.validNotification).next_cursor, "bounded-cursor");
  for (const value of [{}, { items: null, next_cursor: null }, { items: [notice(), notice()], next_cursor: null }, { items: Array(101).fill(notice()), next_cursor: null }, { items: [], next_cursor: "x".repeat(257) }]) assert.throws(() => client.parseMonitoringPage(value, client.validNotification));
});

test("invalid price, currency, timestamps and caller shapes never reach an inbox card", () => {
  assert.equal(client.validNotification(notice()), true);
  for (const price of ["Infinity", "NaN", "-1", "0", "0x100", "1e16", ""]) assert.equal(client.validNotification({ ...notice(), payload: { ...notice().payload, price } }), false);
  for (const currency of ["", "U", "usd", "USDX"]) assert.equal(client.validNotification({ ...notice(), payload: { ...notice().payload, currency } }), false);
  assert.equal(client.validNotification({ ...notice(), payload: null }), false);
  assert.equal(client.validNotification({ ...notice(), created_at: null }), false);
  assert.equal(client.validNotification({ ...notice(), payload: { ...notice().payload, observed_at: "not-a-date" } }), false);
});

test("availability requires explicit feature booleans", () => {
  assert.equal(client.parseMonitoringFeatures({ enabled: true, can_arm: false, email_available: false }).can_arm, false);
  for (const value of [null, {}, { enabled: "true", can_arm: true, email_available: false }]) assert.throws(() => client.parseMonitoringFeatures(value));
});

test("verified-address and challenge parsers retain only bounded opaque identifiers and safe status", () => {
  const addressId = "a1ca8674-505d-4c9e-b17a-27a3d5eb3350";
  const verificationId = "f1ea20ee-d20d-4b09-bf72-57f658caed55";
  const addresses = client.parseVerifiedAddresses({ items: [{ id: addressId, verified_at: "2026-10-14T12:00:00Z" }] });
  assert.equal(addresses.length, 1); assert.equal(addresses[0].id, addressId); assert.equal(addresses[0].verified_at, "2026-10-14T12:00:00Z");
  assert.throws(() => client.parseVerifiedAddresses({ items: [{ id: "mail@example.test", verified_at: "2026-10-14T12:00:00Z" }] }));
  assert.throws(() => client.parseVerifiedAddresses({ items: [{ id: addressId, verified_at: "no date" }] }));
  const challenge = { verification_id: verificationId, address_id: null, state: "accepted", revision: 2, attempts: 0, expires_at: "2026-10-14T12:20:00Z", invalidated: false };
  const parsed = client.parseNotificationVerification(challenge);
  assert.equal(parsed.verification_id, challenge.verification_id); assert.equal(parsed.state, challenge.state); assert.equal(parsed.revision, challenge.revision);
  assert.throws(() => client.parseNotificationVerification({ ...challenge, attempts: 6 }));
  assert.equal(client.parseVerificationIssue({ verification_id: verificationId, address_id: null, state: "accepted", revision: 2, expires_at: "2026-10-14T12:20:00Z", replayed: false }).state, "accepted");
  assert.throws(() => client.parseNotificationVerification({ ...challenge, code: "should-never-be-returned" }));
});

test("notification email errors expose fixed messages rather than backend or submitted values", () => {
  const unsafe = new RequestError("Unsafe raw mailbox code-SECRET should not render", 422, "INVALID_REQUEST");
  assert.equal(client.safeNotificationEmailError(unsafe), "The request could not be accepted. Check the form and saved settings.");
  assert.equal(client.safeNotificationEmailError(new RequestError("raw", 429, "VERIFICATION_RATE_LIMITED")), "A code was requested recently. Wait before requesting another.");
  assert.equal(client.safeNotificationEmailError(new Error("raw address and code")), "Notification email settings could not be confirmed. Refresh and try again.");
});

function notificationHarness(onCreateAlert, overrides = {}) {
  const hooks = []; let cursor = 0; let serial = 0;
  const react = {
    useId: () => "monitoring-test",
    useState(initial) { const i = cursor++; if (!(i in hooks)) hooks[i] = initial; return [hooks[i], value => { hooks[i] = typeof value === "function" ? value(hooks[i]) : value; }]; },
    useRef(initial) { const i = cursor++; if (!(i in hooks)) hooks[i] = { current: initial }; return hooks[i]; },
  };
  const jsx = (type, props) => ({ type, props });
  const module = loadModule("NotificationsWorkspace.tsx", { react, "react/jsx-runtime": { jsx, jsxs: jsx }, "./NotificationsWorkspace.module.css": { default: {} } }, { crypto: { randomUUID: () => `f41a3c4c-e273-4b02-b099-${String(++serial).padStart(12, "0")}` } });
  function nodes(root) { const result = []; function visit(node) { if (Array.isArray(node)) return node.forEach(visit); if (node && typeof node === "object" && "type" in node) { result.push(node); visit(node.props.children); } } visit(root); return result; }
  function render() { cursor = 0; return nodes(module.NotificationsWorkspace({ state: "ready", notifications: [], alerts: [], preferences: null, canCreateAlert: true, onCreateAlert, ...overrides })); }
  function setDraft(symbol, currency, threshold) { const fields = render().filter(node => node.type === "input" && node.props.type === undefined); fields[0].props.onChange({ target: { value: symbol } }); fields[1].props.onChange({ target: { value: currency } }); fields[2].props.onChange({ target: { value: threshold } }); }
  function submit() { return render().find(node => node.type === "form").props.onSubmit({ preventDefault() {} }); }
  return { setDraft, submit, render };
}

function visibleText(nodes) {
  const parts = [];
  function visit(value) {
    if (Array.isArray(value)) return value.forEach(visit);
    if (typeof value === "string") { parts.push(value); return; }
    if (value && typeof value === "object" && "type" in value) visit(value.props.children);
  }
  nodes.forEach(visit);
  return parts.join(" ");
}

const preference = (changes = {}) => ({ revision: 3, alert_email: false, digest_email: false, digest_time: "09:00", digest_timezone: "America/Toronto", address_configured: false, updated_at: null, ...changes });

test("verification is sent only after explicit submit, uses an idempotency key, and keeps address IDs hidden", async () => {
  const calls = [];
  const sideEffects = [];
  const addressId = "a1ca8674-505d-4c9e-b17a-27a3d5eb3350";
  const harness = notificationHarness(async () => {}, {
    preferences: preference({ address_configured: true }), emailAvailable: true, verifiedAddresses: [{ id: addressId, verified_at: "2026-10-14T12:00:00Z" }],
    onRequestEmailVerification: async (...args) => { calls.push(args); return { verification_id: "f1ea20ee-d20d-4b09-bf72-57f658caed55", address_id: null, state: "accepted", revision: 1, attempts: 0, expires_at: "2026-10-14T12:20:00Z", invalidated: false }; },
    onReplaceEmailVerification: async () => { throw new Error("unexpected replacement"); },
    onSelectEmailAddress: async id => { sideEffects.push(["select", id]); }, onSaveAlertEmail: async enabled => { sideEffects.push(["preference", enabled]); },
  });
  const input = harness.render().find(node => node.type === "input" && node.props.name === "notification-email-address");
  input.props.onChange({ target: { value: "person@example.test" } });
  assert.equal(calls.length, 0);
  const form = harness.render().find(node => node.type === "form" && node.props["data-email-action"] === "verify");
  await form.props.onSubmit({ preventDefault() {} });
  assert.equal(calls.length, 1);
  assert.equal(calls[0][0], "person@example.test");
  assert.match(calls[0][1], /^[0-9a-f-]{36}$/);
  const output = harness.render();
  assert.equal(visibleText(output).includes(addressId), false);
  assert.equal(output.some(node => node.props.value === addressId), false);
  assert.match(visibleText(output), /A verified recipient is configured/);
  assert.deepEqual(sideEffects, []);
});

test("verification code is submitted only by explicit confirmation and cleared from the form", async () => {
  const calls = [];
  const challenge = { verification_id: "f1ea20ee-d20d-4b09-bf72-57f658caed55", address_id: null, state: "accepted", revision: 2, attempts: 0, expires_at: "2026-10-14T12:20:00Z", invalidated: false };
  const code = "Abcdefghijklmnopqrstuvwxyz0123456789_-ABCDE";
  assert.equal(code.length, 43);
  const harness = notificationHarness(async () => {}, {
    preferences: preference(), emailAvailable: true, verification: challenge,
    onConfirmEmailVerification: async (...args) => { calls.push(args); return { ...challenge, state: "verified", address_id: "a1ca8674-505d-4c9e-b17a-27a3d5eb3350" }; },
  });
  const codeInput = harness.render().find(node => node.type === "input" && node.props.name === "notification-verification-code");
  codeInput.props.onChange({ target: { value: code } });
  assert.equal(calls.length, 0);
  const form = harness.render().find(node => node.type === "form" && node.props["data-email-action"] === "confirm");
  await form.props.onSubmit({ preventDefault() {} });
  assert.equal(calls.length, 1);
  assert.equal(calls[0][0].verification_id, challenge.verification_id);
  assert.equal(calls[0][1], code);
  const after = harness.render().find(node => node.type === "input" && node.props.name === "notification-verification-code");
  assert.equal(after.props.value, "");
  assert.equal(visibleText(harness.render()).includes(code), false);
});

test("an opted-in user can explicitly opt out while email transport is unavailable", async () => {
  const calls = [];
  const harness = notificationHarness(async () => {}, {
    preferences: preference({ alert_email: true, address_configured: true }), emailAvailable: false,
    onSaveAlertEmail: async enabled => { calls.push(enabled); },
  });
  const toggle = harness.render().find(node => node.type === "input" && node.props.name === "alert-email-opt-in");
  assert.equal(toggle.props.checked, true);
  assert.equal(toggle.props.disabled, false);
  toggle.props.onChange({ target: { checked: false } });
  const form = harness.render().find(node => node.type === "form" && node.props["data-email-action"] === "save-preference");
  await form.props.onSubmit({ preventDefault() {} });
  assert.deepEqual(calls, [false]);
});

test("alert email remains off by default and choosing a verified recipient is a separate action", async () => {
  const selected = [];
  const savedPreferences = [];
  const ids = ["a1ca8674-505d-4c9e-b17a-27a3d5eb3350", "f1ea20ee-d20d-4b09-bf72-57f658caed55"];
  const harness = notificationHarness(async () => {}, {
    preferences: preference({ address_configured: true }), emailAvailable: true,
    verifiedAddresses: ids.map((id, index) => ({ id, verified_at: `2026-10-${14 - index}T12:00:00Z` })),
    onSelectEmailAddress: async id => { selected.push(id); }, onSaveAlertEmail: async enabled => { savedPreferences.push(enabled); },
  });
  const initial = harness.render();
  const optIn = initial.find(node => node.type === "input" && node.props.name === "alert-email-opt-in");
  assert.equal(optIn.props.checked, false);
  assert.equal(selected.length, 0); assert.equal(savedPreferences.length, 0);
  const choose = initial.filter(node => node.type === "button" && node.props.children === "Use this address");
  assert.equal(choose.length, 2);
  choose[1].props.onClick();
  await new Promise(resolve => setImmediate(resolve));
  assert.deepEqual(selected, [ids[1]]);
  assert.deepEqual(savedPreferences, []);
  assert.equal(visibleText(harness.render()).includes(ids[1]), false);
});

test("an unsupported existing digest requires an explicit acknowledgement before saving it off", async () => {
  const calls = [];
  const harness = notificationHarness(async () => {}, {
    preferences: preference({ digest_email: true }), emailAvailable: false,
    onSaveAlertEmail: async enabled => { calls.push(enabled); },
  });
  const save = harness.render().find(node => node.type === "button" && node.props.children === "Save email preference");
  assert.equal(save.props.disabled, true);
  const acknowledge = harness.render().find(node => node.type === "input" && node.props.name === "acknowledge-digest-off");
  acknowledge.props.onChange({ target: { checked: true } });
  const form = harness.render().find(node => node.type === "form" && node.props["data-email-action"] === "save-preference");
  assert.equal(harness.render().find(node => node.type === "button" && node.props.children === "Save email preference").props.disabled, false);
  await form.props.onSubmit({ preventDefault() {} });
  assert.deepEqual(calls, [false]);
});

test("notification email controls retain the 44 CSS-pixel target and mobile single-column form", () => {
  const css = readFileSync(new URL("../components/monitoring/NotificationsWorkspace.module.css", import.meta.url), "utf8");
  assert.match(css, /\.secondaryButton,\.primaryButton\{[^}]*min-height:44px/);
  assert.match(css, /\.emailField input\{[^}]*min-height:44px/);
  assert.match(css, /@media\(max-width:460px\)\{[^}]*\.emailForm\{grid-template-columns:1fr\}/);
});

test("an uncertain creation keeps the same idempotency key when the user retries its unchanged draft", async () => {
  const submitted = [];
  const harness = notificationHarness(async request => { submitted.push(request); if (submitted.length === 1) throw new Error("Lost response after commit."); });
  harness.setDraft("SPY", "USD", "100");
  await harness.submit(); await harness.submit();
  assert.equal(submitted.length, 2);
  assert.equal(submitted[0].idempotencyKey, submitted[1].idempotencyKey);
  harness.setDraft("SPY", "USD", "105"); await harness.submit();
  assert.notEqual(submitted[1].idempotencyKey, submitted[2].idempotencyKey);
});

test("rapid duplicate submissions cannot create a second in-flight rule", async () => {
  let release; let calls = 0;
  const harness = notificationHarness(async () => { calls++; await new Promise(resolve => { release = resolve; }); });
  harness.setDraft("SPY", "USD", "100");
  const first = harness.submit(); await harness.submit();
  assert.equal(calls, 1); release(); await first;
});

function rule(state, changes = {}) {
  return { id: "f1ea20ee-d20d-4b09-bf72-57f658caed55", revision: 1, monitor_revision: 2, enabled: state === "watching", configured_enabled: state !== "paused", baseline_ready: state !== "arming", state, ready: true, config: { symbol: "SPY", currency: "USD", threshold: "100", direction: "above", repeating: false }, last_check_at: "2026-10-14T12:00:00Z", last_success_at: "2026-10-14T12:00:00Z", last_observation: null, ...changes };
}

test("pending and failed checks can be paused, and a completed one-shot requires explicit rearming", async () => {
  for (const state of ["arming", "unavailable"]) {
    const harness = notificationHarness(async () => {}, { alerts: [rule(state)], onPauseAlert: async () => {} });
    const pause = harness.render().find(node => node.type === "button" && node.props.children === "Pause alert");
    assert.ok(pause); assert.equal(pause.props.disabled, false);
  }
  const calls = [];
  const harness = notificationHarness(async () => {}, { alerts: [rule("triggered")], canResumeAlert: true, onResumeAlert: async (...args) => calls.push(args) });
  const rearm = harness.render().find(node => node.type === "button" && node.props.children === "Re-arm alert");
  assert.ok(rearm); assert.equal(rearm.props.disabled, false); rearm.props.onClick();
  await Promise.resolve();
  assert.deepEqual(calls, [[rule("triggered").id, 1]]);
});

test("monitor control, overdue checks, and waiting for a reset have distinct visible labels", () => {
  const unavailable = notificationHarness(async () => {}, { alerts: [rule("watching")], checksAvailable: false });
  assert.ok(unavailable.render().some(node => node.props.children === "Checks unavailable"));
  const overdue = notificationHarness(async () => {}, { alerts: [rule("watching")], checksAvailable: true, reportedAt: "2026-10-14T12:16:00Z" });
  assert.ok(overdue.render().some(node => node.props.children === "Check overdue"));
  const waiting = notificationHarness(async () => {}, { alerts: [rule("watching", { ready: false })], checksAvailable: true });
  assert.ok(waiting.render().some(node => node.props.children === "Waiting for price to reset"));
  assert.equal(waiting.render().some(node => node.props.children === "Monitoring unavailable"), false);
});

test("a failed first check shows unavailable while retaining its pending baseline explanation", () => {
  const harness = notificationHarness(async () => {}, { alerts: [rule("unavailable", { baseline_ready: false, ready: false })], checksAvailable: true });
  const rendered = harness.render();
  assert.ok(rendered.some(node => node.props.children === "Monitoring unavailable"));
  assert.ok(!rendered.some(node => node.props.children === "Waiting for initial baseline"));
});
