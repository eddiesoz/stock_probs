import assert from "node:assert/strict";
import test from "node:test";

import {
  customProviderReviewIsValid,
  customProviderReviewTupleChanged,
} from "./assistant-custom-provider-contract.ts";

const validReview = {
  terms_url: "https://terms.example.org/policy",
  privacy_disclosure: "Administrator-provided privacy statement; unverified.",
  billing_disclosure: "Billing is unknown until the administrator reviews it.",
  billing_class: "unknown",
  endpoint_policy_reviewed: true,
};

test("custom provider review requires secure endpoint, public terms, bounded statements and explicit review", () => {
  assert.equal(customProviderReviewIsValid("https://models.example.org/v1", validReview), true);
  assert.equal(customProviderReviewIsValid("http://models.example.org/v1", validReview), false);
  assert.equal(customProviderReviewIsValid("https://user:secret@models.example.org/v1", validReview), false);
  assert.equal(customProviderReviewIsValid("https://models.example.org/v1?key=private", validReview), false);
  assert.equal(customProviderReviewIsValid("https://models.example.org/v1", { ...validReview, terms_url: "http://terms.example.org" }), false);
  assert.equal(customProviderReviewIsValid("https://models.example.org/v1", { ...validReview, billing_class: "free-ish" }), false);
  assert.equal(customProviderReviewIsValid("https://models.example.org/v1", { ...validReview, endpoint_policy_reviewed: false }), false);
  assert.equal(customProviderReviewIsValid("https://models.example.org/v1", { ...validReview, privacy_disclosure: "x".repeat(2001) }), false);
  assert.equal(customProviderReviewIsValid("https://models.example.org/v1", { ...validReview, billing_disclosure: "statement\u0000marker" }), false);
});

test("custom provider tuple changes require policy review and a later model selection save", () => {
  const saved = {
    selected_base_url: "https://models.example.org/v1",
    selected_terms_url: validReview.terms_url,
    selected_privacy_disclosure: validReview.privacy_disclosure,
    selected_billing_disclosure: validReview.billing_disclosure,
    selected_billing_class: "unknown",
  };
  assert.equal(customProviderReviewTupleChanged("https://models.example.org/v1", validReview, saved), false);
  assert.equal(customProviderReviewTupleChanged("https://models.example.org/v2", validReview, saved), true);
  assert.equal(customProviderReviewTupleChanged("https://models.example.org/v1", { ...validReview, billing_class: "paid" }, saved), true);
});
