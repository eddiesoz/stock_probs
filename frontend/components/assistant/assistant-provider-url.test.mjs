import assert from "node:assert/strict";
import test from "node:test";

import { providerBaseUrlIsSecure, safeConfiguredBaseUrl } from "./assistant-provider-url.ts";

test("provider settings accept compatible HTTPS URLs only", () => {
  assert.equal(providerBaseUrlIsSecure("https://api.example.test/v1"), true);
  assert.equal(providerBaseUrlIsSecure("https://user:secret@api.example.test"), false);
  assert.equal(providerBaseUrlIsSecure("https://api.example.test/?token=private"), false);
  assert.equal(providerBaseUrlIsSecure("http://localhost:8000"), false);
  assert.equal(providerBaseUrlIsSecure("http://127.0.0.1:8000"), false);
  assert.equal(providerBaseUrlIsSecure("file:///tmp/provider"), false);
  assert.equal(safeConfiguredBaseUrl("https://api.example.test/v1"), "https://api.example.test/v1");
  assert.equal(safeConfiguredBaseUrl("http://localhost:8000"), "");
});
