// Node's built-in test runner resolves TypeScript modules by explicit extension.
// @ts-expect-error The Next.js bundler resolves this source-only TypeScript import.
import { safeTermsUrl } from "./assistant-contract.ts";
// @ts-expect-error The Next.js bundler resolves this source-only TypeScript import.
import { safeConfiguredBaseUrl } from "./assistant-provider-url.ts";

export type OpenCodeConsoleModel = {
  model_id: string;
  provider_id: "opencode-console";
  display_name: string;
  native_model_id: string;
  adapter_id: "openai-responses" | "anthropic-messages" | "google-generative-language" | "openai-compatible-chat";
  protocol: "openai-responses" | "anthropic-messages" | "google-generative-language" | "openai-compatible-chat";
  package_id: string;
  endpoint: string;
  available: boolean;
  reviewed: boolean;
  billing_class: "unknown" | "free" | "paid";
  training_policy: "unknown" | "no_training" | "training_possible";
  confidential_data_policy: "unknown" | "allowed" | "prohibited";
  terms_url: string | null;
  privacy_disclosure: string | null;
  billing_disclosure: string | null;
  privacy_policy_version: string | null;
  billing_policy_version: string | null;
  enabled: boolean;
  revision: number;
  review_revision: number;
  usable: boolean;
  availability_reason: string | null;
  config_fingerprint: string;
};

export type OpenCodeConsoleInventory = {
  models: OpenCodeConsoleModel[];
  unsupported_model_count: number;
};

const adapterPairs = new Map([
  ["openai-responses", "@opencode/ai/providers/openai"],
  ["anthropic-messages", "@opencode/ai/providers/anthropic"],
  ["google-generative-language", "@opencode/ai/providers/google"],
  ["openai-compatible-chat", "@opencode/ai/providers/openai-compatible"],
]);
const modelIdPattern = /^opencode-console\/[0-9a-f]{64}$/;
const nativeModelIdPattern = /^[A-Za-z0-9][A-Za-z0-9._:+/-]{0,159}$/;
const fingerprintPattern = /^[0-9a-f]{64}$/;
const optionalText = (value: unknown, limit: number): string | null | undefined => {
  if (value === null) return null;
  if (typeof value !== "string" || new TextEncoder().encode(value).length > limit) return undefined;
  return value;
};

function readConsoleModel(value: unknown): OpenCodeConsoleModel | null {
  if (!value || typeof value !== "object") return null;
  const row = value as Record<string, unknown>;
  const adapterId = row.adapter_id;
  const protocol = row.protocol;
  if (
    typeof adapterId !== "string"
    || !adapterPairs.has(adapterId)
    || protocol !== adapterId
    || row.package_id !== adapterPairs.get(adapterId)
    || row.provider_id !== "opencode-console"
    || typeof row.model_id !== "string"
    || !modelIdPattern.test(row.model_id)
    || typeof row.native_model_id !== "string"
    || !nativeModelIdPattern.test(row.native_model_id)
    || typeof row.display_name !== "string"
    || !row.display_name.length
    || new TextEncoder().encode(row.display_name).length > 160
    || /[\u0000-\u001f\u007f-\u009f]/.test(row.display_name)
    || typeof row.endpoint !== "string"
    || safeConfiguredBaseUrl(row.endpoint) !== row.endpoint
    || typeof row.available !== "boolean"
    || typeof row.reviewed !== "boolean"
    || typeof row.enabled !== "boolean"
    || typeof row.usable !== "boolean"
    || !["unknown", "free", "paid"].includes(String(row.billing_class))
    || !["unknown", "no_training", "training_possible"].includes(String(row.training_policy))
    || !["unknown", "allowed", "prohibited"].includes(String(row.confidential_data_policy))
    || typeof row.revision !== "number"
    || !Number.isSafeInteger(row.revision)
    || (row.revision as number) < 0
    || typeof row.review_revision !== "number"
    || !Number.isSafeInteger(row.review_revision)
    || (row.review_revision as number) < 0
    || typeof row.config_fingerprint !== "string"
    || !fingerprintPattern.test(row.config_fingerprint)
  ) return null;

  const termsUrl = optionalText(row.terms_url, 2048);
  const privacy = optionalText(row.privacy_disclosure, 2000);
  const billing = optionalText(row.billing_disclosure, 2000);
  const privacyVersion = optionalText(row.privacy_policy_version, 128);
  const billingVersion = optionalText(row.billing_policy_version, 128);
  const availabilityReason = optionalText(row.availability_reason, 64);
  if (
    termsUrl === undefined
    || (termsUrl !== null && safeTermsUrl(termsUrl) !== termsUrl)
    || privacy === undefined
    || billing === undefined
    || privacyVersion === undefined
    || billingVersion === undefined
    || availabilityReason === undefined
    || (availabilityReason !== null && !/^[a-z0-9_]{1,64}$/.test(availabilityReason))
  ) return null;

  return {
    model_id: row.model_id,
    provider_id: "opencode-console",
    display_name: row.display_name,
    native_model_id: row.native_model_id,
    adapter_id: adapterId as OpenCodeConsoleModel["adapter_id"],
    protocol: protocol as OpenCodeConsoleModel["protocol"],
    package_id: row.package_id as string,
    endpoint: row.endpoint,
    available: row.available,
    reviewed: row.reviewed,
    billing_class: row.billing_class as OpenCodeConsoleModel["billing_class"],
    training_policy: row.training_policy as OpenCodeConsoleModel["training_policy"],
    confidential_data_policy: row.confidential_data_policy as OpenCodeConsoleModel["confidential_data_policy"],
    terms_url: termsUrl,
    privacy_disclosure: privacy,
    billing_disclosure: billing,
    privacy_policy_version: privacyVersion,
    billing_policy_version: billingVersion,
    enabled: row.enabled,
    revision: row.revision as number,
    review_revision: row.review_revision as number,
    usable: row.usable,
    availability_reason: availabilityReason,
    config_fingerprint: row.config_fingerprint,
  };
}

export function readOpenCodeConsoleInventory(value: unknown): OpenCodeConsoleInventory {
  if (!value || typeof value !== "object") return { models: [], unsupported_model_count: 0 };
  const envelope = value as Record<string, unknown>;
  const rawModels = Array.isArray(envelope.models) ? envelope.models.slice(0, 2048) : [];
  const models = rawModels.flatMap((item) => {
    const parsed = readConsoleModel(item);
    return parsed ? [parsed] : [];
  });
  const count = envelope.unsupported_model_count;
  return {
    models,
    unsupported_model_count: Number.isInteger(count) && Number(count) >= 0 && Number(count) <= 2048
      ? Number(count)
      : 0,
  };
}
