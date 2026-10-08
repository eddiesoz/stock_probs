import assert from "node:assert/strict";
import test from "node:test";

import { applyLiveTradingAssistantAction } from "./assistant-bridge.ts";

const identity = { symbol: "SPY", asset_type: "etf", provider: "Yahoo Finance", exchange: "ARCA" };

test("confirmed notes actions open local controls without overwriting or clearing browser drafts", () => {
  assert.deepEqual(applyLiveTradingAssistantAction({ type: "notes.set", payload: identity }, identity, []), {
    ok: true,
    state: {},
    message: "The local note controls are open. Review or edit the note there; chat did not change it.",
  });
  assert.deepEqual(applyLiveTradingAssistantAction({ type: "notes.clear", payload: identity }, identity, []), {
    ok: true,
    state: {},
    message: "The local note controls are open. Review or edit the note there; chat did not change it.",
  });
  assert.equal(applyLiveTradingAssistantAction({ type: "notes.set", payload: { ...identity, symbol: "QQQ" } }, identity, []).ok, false);
});

test("confirmed alert actions remain per-page, capped, and removals hand off without deleting", () => {
  assert.deepEqual(applyLiveTradingAssistantAction({ type: "alerts.add", payload: { ...identity, threshold: 512.5 } }, identity, [500]), {
    ok: true,
    state: { alerts: [500, 512.5] },
    message: "The threshold was added to this open page session only. No scheduler or delivery is configured.",
  });
  assert.equal(applyLiveTradingAssistantAction({ type: "alerts.add", payload: { ...identity, threshold: 512.5 } }, identity, [1, 2, 3, 4, 5]).ok, false);
  assert.deepEqual(applyLiveTradingAssistantAction({ type: "alerts.remove", payload: identity }, identity, [10, 20, 30]), {
    ok: true,
    state: {},
    message: "The current alert controls are open. Select and remove the existing alert there; chat did not remove any alert.",
  });
  assert.equal(applyLiveTradingAssistantAction({ type: "alerts.remove", payload: identity }, identity, [10]).ok, true);
});
