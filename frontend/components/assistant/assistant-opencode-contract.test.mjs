import assert from "node:assert/strict";
import test from "node:test";

import { readOpenCodeConsoleInventory } from "./assistant-opencode-contract.ts";

const validModel = {
  model_id: `opencode-console/${"a".repeat(64)}`,
  provider_id: "opencode-console",
  display_name: "Synthetic reviewed model",
  native_model_id: "synthetic/model-v1",
  adapter_id: "openai-responses",
  protocol: "openai-responses",
  package_id: "@opencode/ai/providers/openai",
  endpoint: "https://api.example.test/v1",
  available: true,
  reviewed: true,
  billing_class: "paid",
  training_policy: "no_training",
  confidential_data_policy: "allowed",
  terms_url: "https://terms.example.com/model",
  privacy_disclosure: "Administrator-provided statement; unverified.",
  billing_disclosure: "Administrator-provided cost statement; unverified.",
  privacy_policy_version: "privacy-v1",
  billing_policy_version: "billing-v1",
  enabled: false,
  revision: 2,
  review_revision: 4,
  usable: false,
  availability_reason: "model_not_enabled",
  config_fingerprint: "b".repeat(64),
};

test("OpenCode inventory accepts the closed owner model contract and CAS revisions", () => {
  assert.deepEqual(readOpenCodeConsoleInventory({
    models: [validModel],
    unsupported_model_count: 3,
  }), {
    models: [validModel],
    unsupported_model_count: 3,
  });
});

test("OpenCode inventory fails closed for missing state, unreviewed packages, and unsafe endpoints", () => {
  const missingEnabled = { ...validModel };
  delete missingEnabled.enabled;
  const wrongPackage = { ...validModel, package_id: "@unreviewed/provider" };
  const noncanonicalEndpoint = { ...validModel, endpoint: "https://user:secret@api.example.test/v1" };
  const badReviewRevision = { ...validModel, review_revision: -1 };

  assert.deepEqual(readOpenCodeConsoleInventory({
    models: [missingEnabled, wrongPackage, noncanonicalEndpoint, badReviewRevision],
    unsupported_model_count: 0,
  }).models, []);
});

test("OpenCode inventory bounds unsupported counts and drops malformed rows", () => {
  assert.deepEqual(readOpenCodeConsoleInventory({
    models: [{ ...validModel, config_fingerprint: "bad" }],
    unsupported_model_count: 999999,
  }), { models: [], unsupported_model_count: 0 });
});
