export type BriefingWindow = "since_last_visit" | "last_24_hours" | "last_7_days";
export type BriefingFeatureState = {
  enabled: boolean;
  headlines_available: boolean;
  digest_available: boolean;
  assistant_available: boolean;
};
export type BriefingState = {
  features: BriefingFeatureState;
  server_time: string;
  preference: { revision: number; threshold_bps: number; updated_at: string | null };
  visit_anchor: { revision: number; baseline_at: string | null; snapshot_id: string | null; visited_at: string | null };
};
export type BriefingSnapshot = {
  id: string;
  window: BriefingWindow;
  baseline_at: string | null;
  observed_as_of: string;
  generated_at: string;
  threshold_bps: number;
  baseline_anchor_revision: number;
  preference_revision: number;
  price_changes: Array<{
    symbol: string; asset_type: string;
    state: "threshold_crossed" | "below_threshold" | "first_observation" | "insufficient_history" | "unavailable";
    baseline_at: string | null; observed_at: string | null; currency: string | null;
    provider: string | null; change_bps: string | null; reason: string | null;
  }>;
  outcome_changes: Array<{
    resource_ref: string; state: "observed" | "corrected" | "unavailable" | "incomparable" | "manual_review";
    revision: number; recorded_at: string; observed_at: string | null; correction_of: string | null;
  }>;
  triggered_alerts: Array<{ resource_ref: string; symbol: string; asset_type: string; triggered_at: string }>;
  due_thesis_reviews: Array<{ thesis_ref: string; revision: number; due_at: string }>;
};
export type SnapshotAttempt = {
  window: BriefingWindow; observedAsOf: string; idempotencyKey: string; body: string;
};
export type BriefingFetch = (path: string, options?: RequestInit) => Promise<Response>;
export declare const BRIEFING_WINDOWS: readonly BriefingWindow[];
export type BriefingFailure =
  | { kind: "authorization"; status: 401 | 403 }
  | { kind: "conflict"; status: 409 }
  | { kind: "rate_limited"; status: 429; retryAfterSeconds: number | null }
  | { kind: "rejected"; status: number }
  | { kind: "uncertain"; status: number | null };
export type RefreshState =
  | { status: "idle" }
  | { status: "pending"; attempt: SnapshotAttempt }
  | { status: "uncertain"; attempt: SnapshotAttempt; failureStatus: number | null }
  | { status: "rejected"; failureKind: "conflict" | "rejected"; statusCode: number }
  | { status: "authorization"; statusCode: number }
  | { status: "rate_limited"; retryAt: number };
export type RefreshAction = "none" | "retry_same" | "reload_state" | "wait" | "new";
export declare const IDLE_REFRESH_STATE: RefreshState;
export declare class BriefingRequestError extends Error {
  constructor(status: number, retryAfterSeconds?: number | null);
  status: number;
  retryAfterSeconds: number | null;
}
export declare function classifyBriefingFailure(error: unknown): BriefingFailure;
export declare function refreshStateReducer(
  current: RefreshState,
  event:
    | { type: "reset" | "succeeded" }
    | { type: "begin"; attempt: SnapshotAttempt }
    | { type: "retry" }
    | { type: "failed"; failure: BriefingFailure; at?: number }
): RefreshState;
export declare function refreshButtonModel(
  refreshState: RefreshState,
  options?: { busy?: boolean; available?: boolean; hasSnapshot?: boolean; nowMs?: number }
): {
  action: RefreshAction;
  label: string;
  disabled: boolean;
  windowDisabled: boolean;
};
export declare function projectBriefingSnapshot(value: unknown): BriefingSnapshot;
export declare function projectBriefingState(value: unknown): BriefingState;
export declare function createLatestRequestLane(): {
  begin(): { signal: AbortSignal; isCurrent(): boolean };
  cancel(): void;
};
export declare function createSnapshotAttempt(
  window: BriefingWindow, observedAsOf: string, uuidFactory?: () => string
): SnapshotAttempt;
export declare function createBriefingClient(apiFetch: BriefingFetch): {
  getState(options?: { signal?: AbortSignal }): Promise<BriefingState>;
  listSnapshots(options?: { limit?: number; cursor?: string | null; signal?: AbortSignal }): Promise<{
    items: BriefingSnapshot[]; next_cursor: string | null;
  }>;
  getSnapshot(snapshotId: string, options?: { signal?: AbortSignal }): Promise<BriefingSnapshot>;
  createSnapshot(attempt: SnapshotAttempt): Promise<BriefingSnapshot>;
  updateThreshold(thresholdBps: number, expectedRevision: number): Promise<{
    revision: number; threshold_bps: number; updated_at: string;
  }>;
  recordVisit(snapshotId: string, expectedRevision: number): Promise<{
    revision: number; snapshot_id: string; baseline_at: string; visited_at: string;
  }>;
};
