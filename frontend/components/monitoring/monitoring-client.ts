import { apiFetch, AuthRequestError } from "../auth-client";
import type { AlertRecord, NotificationRecord } from "./NotificationsWorkspace";

export interface MonitoringFeatures { enabled: boolean; can_arm: boolean; email_available: boolean; reported_at?: string }
export interface MonitoringPage<T> { items: T[]; next_cursor: string | null }
export interface VerifiedNotificationAddress { id: string; verified_at: string }
export type VerificationState = "queued" | "submitting" | "accepted" | "uncertain" | "failed" | "blocked" | "unavailable" | "verified" | "expired" | "already_verified" | "superseded";
export interface NotificationVerification {
  verification_id: string;
  address_id: string | null;
  state: VerificationState;
  revision: number;
  attempts: number;
  expires_at: string;
  invalidated: boolean;
}

const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
const verificationStates = new Set<VerificationState>(["queued", "submitting", "accepted", "uncertain", "failed", "blocked", "unavailable", "verified", "expired", "already_verified", "superseded"]);
export function isRecord(value: unknown): value is Record<string, unknown> { return value !== null && typeof value === "object" && !Array.isArray(value); }
function exactKeys(value: Record<string, unknown>, expected: readonly string[]): boolean { const keys = Object.keys(value); return keys.length === expected.length && expected.every(key => Object.hasOwn(value, key)); }
function text(value: unknown, length: number): value is string { return typeof value === "string" && value.length > 0 && value.length <= length; }
function revision(value: unknown): value is number { return Number.isSafeInteger(value) && (value as number) > 0; }
function positivePrice(value: unknown): boolean { return text(value, 64) && /^[+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$/.test(value) && Number.isFinite(Number(value)) && Number(value) > 0 && Number(value) <= 1e15; }
function nullableInstant(value: unknown): boolean { return value === null || (text(value, 40) && Number.isFinite(Date.parse(value))); }

export function validNotification(value: unknown): value is NotificationRecord {
  if (!isRecord(value) || !text(value.id, 36) || !uuid.test(value.id) || value.kind !== "price_alert" || typeof value.is_read !== "boolean" || !revision(value.revision) || !text(value.created_at, 40) || !nullableInstant(value.created_at)) return false;
  const payload = value.payload;
  return isRecord(payload) && text(payload.alert_id, 36) && uuid.test(payload.alert_id) && revision(payload.generation) && text(payload.symbol, 80) && text(payload.currency, 3) && /^[A-Z]{3}$/.test(payload.currency) && positivePrice(payload.threshold) && positivePrice(payload.price) && ["above", "below"].includes(payload.direction as string) && text(payload.provider, 80) && text(payload.observed_at, 40) && Number.isFinite(Date.parse(payload.observed_at));
}

export function validAlert(value: unknown): value is AlertRecord {
  if (!isRecord(value) || !text(value.id, 36) || !uuid.test(value.id) || !revision(value.revision) || !revision(value.monitor_revision) || !revision(value.arm_generation)) return false;
  const config = value.config;
  if (!isRecord(config) || !text(config.symbol, 80) || !text(config.currency, 3) || !/^[A-Z]{3}$/.test(config.currency) || !positivePrice(config.threshold) || !["above", "below"].includes(config.direction as string) || typeof config.repeating !== "boolean") return false;
  if (!text(value.created_at, 40) || !text(value.updated_at, 40)) return false;
  if (!["enabled", "configured_enabled", "baseline_ready", "ready"].every(key => typeof value[key] === "boolean") || !["arming", "watching", "paused", "triggered", "unavailable"].includes(value.state as string)) return false;
  if (!["arm_snapshot_requested_at", "arm_snapshot_received_at", "last_observed_at", "last_check_at", "last_success_at", "created_at", "updated_at"].every(key => nullableInstant(value[key]))) return false;
  if (!(value.arm_snapshot_generation === null || revision(value.arm_snapshot_generation)) || !(value.last_side === null || [-1, 0, 1].includes(value.last_side as number))) return false;
  if (value.last_observation !== null) {
    const quote = value.last_observation;
    if (!isRecord(quote) || !text(quote.symbol, 80) || !text(quote.currency, 3) || !positivePrice(quote.price) || !text(quote.provider, 80) || !text(quote.observed_at, 40) || !Number.isFinite(Date.parse(quote.observed_at))) return false;
  }
  return true;
}

export function parseMonitoringPage<T extends { id: string }>(value: unknown, valid: (item: unknown) => item is T): MonitoringPage<T> {
  if (!isRecord(value) || !Array.isArray(value.items) || value.items.length > 100 || !(value.next_cursor === null || text(value.next_cursor, 256)) || !value.items.every(valid)) throw new Error("The saved monitoring response is malformed. Refresh before making changes.");
  const items = value.items as T[];
  if (new Set(items.map(item => item.id)).size !== items.length) throw new Error("The monitoring response contains duplicate records.");
  return { items, next_cursor: value.next_cursor as string | null };
}

export function parseVerifiedAddresses(value: unknown): VerifiedNotificationAddress[] {
  if (!isRecord(value) || !exactKeys(value, ["items"]) || !Array.isArray(value.items) || value.items.length > 100) throw new Error("Verified addresses are unavailable.");
  const items = value.items.map(item => {
    if (!isRecord(item) || !exactKeys(item, ["id", "verified_at"]) || !text(item.id, 36) || !uuid.test(item.id) || !text(item.verified_at, 40) || !Number.isFinite(Date.parse(item.verified_at))) throw new Error("Verified addresses are unavailable.");
    return { id: item.id, verified_at: item.verified_at };
  });
  if (new Set(items.map(item => item.id)).size !== items.length) throw new Error("Verified addresses are unavailable.");
  return items;
}

export function parseNotificationVerification(value: unknown): NotificationVerification {
  if (!isRecord(value) || !exactKeys(value, ["verification_id", "address_id", "state", "revision", "attempts", "expires_at", "invalidated"]) || !text(value.verification_id, 36) || !uuid.test(value.verification_id) || !(value.address_id === null || (text(value.address_id, 36) && uuid.test(value.address_id))) || !verificationStates.has(value.state as VerificationState) || !Number.isSafeInteger(value.revision) || (value.revision as number) < 1 || !Number.isSafeInteger(value.attempts) || (value.attempts as number) < 0 || (value.attempts as number) > 5 || !text(value.expires_at, 40) || !Number.isFinite(Date.parse(value.expires_at)) || typeof value.invalidated !== "boolean") throw new Error("Verification status is unavailable.");
  return value as unknown as NotificationVerification;
}

export function parseVerificationIssue(value: unknown): NotificationVerification {
  if (!isRecord(value) || !exactKeys(value, ["verification_id", "address_id", "state", "revision", "expires_at", "replayed"]) || !text(value.verification_id, 36) || !uuid.test(value.verification_id) || !(value.address_id === null || (text(value.address_id, 36) && uuid.test(value.address_id))) || !verificationStates.has(value.state as VerificationState) || !Number.isSafeInteger(value.revision) || (value.revision as number) < 1 || !text(value.expires_at, 40) || !Number.isFinite(Date.parse(value.expires_at)) || typeof value.replayed !== "boolean") throw new Error("Verification status is unavailable.");
  return { verification_id: value.verification_id, address_id: value.address_id as string | null, state: value.state as VerificationState, revision: value.revision as number, attempts: 0, expires_at: value.expires_at, invalidated: false };
}

export function safeNotificationEmailError(cause: unknown): string {
  if (cause instanceof AuthRequestError) {
    if (cause.code === "VERIFICATION_RATE_LIMITED") return "A code was requested recently. Wait before requesting another.";
    if (cause.code === "REVISION_CONFLICT" || cause.code === "REVISION_OR_IDEMPOTENCY_CONFLICT") return "Saved notification settings changed. Refresh them before trying again.";
    if (cause.code === "DIGEST_EMAIL_UNAVAILABLE") return "Daily digest email is not available yet.";
    if (cause.code === "ALERT_EMAIL_UNAVAILABLE" || cause.code === "EMAIL_VERIFICATION_UNAVAILABLE") return "Email delivery is currently unavailable.";
    if (cause.status === 401 || cause.status === 403) return "Notification email settings are unavailable for this session.";
    if (cause.status === 422 || cause.status === 409) return "The request could not be accepted. Check the form and saved settings.";
  }
  return "Notification email settings could not be confirmed. Refresh and try again.";
}

export async function monitoringRequest(path: string, options: RequestInit = {}): Promise<Record<string, unknown>> {
  const response = await apiFetch(path, { cache: "no-store", ...options });
  const body: unknown = await response.json();
  if (!response.ok) {
    const error = isRecord(body) && isRecord(body.error) ? body.error : null;
    throw new AuthRequestError(typeof error?.message === "string" ? error.message : "Monitoring is unavailable.", response.status, typeof error?.code === "string" ? error.code : "monitoring_unavailable");
  }
  if (!isRecord(body)) throw new Error("The monitoring response is unavailable.");
  return body;
}

export function parseMonitoringFeatures(value: unknown): MonitoringFeatures {
  if (!isRecord(value) || typeof value.enabled !== "boolean" || typeof value.can_arm !== "boolean" || typeof value.email_available !== "boolean") throw new Error("Monitoring availability could not be confirmed.");
  if (value.reported_at !== undefined && (!text(value.reported_at, 64) || !Number.isFinite(Date.parse(value.reported_at)))) throw new Error("The monitoring check time is unavailable.");
  return { enabled: value.enabled, can_arm: value.can_arm, email_available: value.email_available, reported_at: value.reported_at as string | undefined };
}
