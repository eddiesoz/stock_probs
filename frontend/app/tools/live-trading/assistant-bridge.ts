import type { AssistantBrowserAction } from "../../../components/assistant/assistant-contract";

export type LiveTradingIdentity = { symbol: string; asset_type: "stock" | "etf"; provider: string; exchange: string };
export type LiveTradingBridgeState = { note?: string; alerts?: number[] };

export function applyLiveTradingAssistantAction(
  action: AssistantBrowserAction,
  identity: LiveTradingIdentity,
  alerts: number[],
): { ok: true; state: LiveTradingBridgeState; message: string } | { ok: false; message: string } {
  if (action.type !== "notes.set" && action.type !== "notes.clear" && action.type !== "alerts.add" && action.type !== "alerts.remove") {
    return { ok: false, message: "This workspace action is not supported here." };
  }
  const target = action.payload;
  // A delayed proposal may outlive navigation; never apply its instrument data to a new selection.
  if (target.symbol !== identity.symbol || target.asset_type !== identity.asset_type
      || target.provider !== identity.provider || target.exchange !== identity.exchange) {
    return { ok: false, message: "The selected instrument changed. The local note or alert was not changed." };
  }
  if (action.type === "notes.set" || action.type === "notes.clear") {
    return { ok: true, state: {}, message: "The local note controls are open. Review or edit the note there; chat did not change it." };
  }
  if (action.type === "alerts.add") {
    if (alerts.length >= 5) return { ok: false, message: "This page already has five active session-only thresholds; no alert was added." };
    return { ok: true, state: { alerts: [...alerts, action.payload.threshold] }, message: "The threshold was added to this open page session only. No scheduler or delivery is configured." };
  }
  return { ok: true, state: {}, message: "The current alert controls are open. Select and remove the existing alert there; chat did not remove any alert." };
}
