import { describe, expect, test } from "bun:test"
import { parseOAuthCallbackURL } from "./oauth-callback"

describe("native OAuth callback relay parser", () => {
  test("accepts one code for the exact attempt-bound localhost listener and state", () => {
    expect(
      parseOAuthCallbackURL(
        "http://localhost:1455/auth/callback?code=synthetic-code&state=synthetic-state",
        "http://localhost:1455/auth/callback",
        "synthetic-state",
      ),
    ).toEqual({ kind: "code", code: "synthetic-code" })
  })

  test("accepts the other fixed native callback port only when registered for that attempt", () => {
    expect(
      parseOAuthCallbackURL(
        "http://localhost:1457/auth/callback?state=state&code=code",
        "http://localhost:1457/auth/callback",
        "state",
      ),
    ).toEqual({ kind: "code", code: "code" })
  })

  test("returns denial without exposing native error text", () => {
    expect(
      parseOAuthCallbackURL(
        "http://localhost:1455/auth/callback?error=access_denied&error_description=cancelled&state=state",
        "http://localhost:1455/auth/callback",
        "state",
      ),
    ).toEqual({ kind: "denied" })
  })

  test.each([
    "http://127.0.0.1:1455/auth/callback?code=code&state=state",
    "http://localhost.evil.test:1455/auth/callback?code=code&state=state",
    "https://localhost:1455/auth/callback?code=code&state=state",
    "http://localhost:1456/auth/callback?code=code&state=state",
    "http://localhost:1455/other?code=code&state=state",
    "http://user@localhost:1455/auth/callback?code=code&state=state",
    "http://localhost:1455/auth/callback?code=code&state=state#fragment",
    "http://localhost:1455/auth/callback?code=code&state=wrong",
    "http://localhost:1455/auth/callback?code=one&code=two&state=state",
    "http://localhost:1455/auth/callback?code=code&state=state&next=https%3A%2F%2Fevil.test",
    "http://localhost:1455/auth/callback?error=access_denied&state=state&code=code",
  ])("rejects a callback outside the exact attempt boundary", (callbackURL) => {
    expect(() =>
      parseOAuthCallbackURL(callbackURL, "http://localhost:1455/auth/callback", "state"),
    ).toThrow()
  })

  test("rejects malformed and overlong callbacks before returning a code", () => {
    expect(() => parseOAuthCallbackURL("\nhttp://localhost:1455/auth/callback", "http://localhost:1455/auth/callback", "state")).toThrow()
    expect(() => parseOAuthCallbackURL(`http://localhost:1455/auth/callback?code=${"x".repeat(4097)}&state=state`, "http://localhost:1455/auth/callback", "state")).toThrow()
    expect(() => parseOAuthCallbackURL(`http://localhost:1455/auth/callback?code=${"x".repeat(8192)}&state=state`, "http://localhost:1455/auth/callback", "state")).toThrow()
  })
})
