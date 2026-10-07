import { describe, expect, test } from "bun:test"
import { requestNativeOAuth, validateOpenCodeDeviceLaunch } from "./oauth-broker"

const broker = { attemptID: "a".repeat(32), capability: "b".repeat(32) }

describe("fixed native OAuth egress bridge", () => {
  test("sends one bounded named request with only the attempt capability", async () => {
    const originalFetch = globalThis.fetch
    let request: { url: string; init?: RequestInit } | undefined
    globalThis.fetch = (async (input, init) => {
      request = { url: String(input), init }
      return new Response(JSON.stringify({ result: { status: "pending" } }), {
        status: 200,
        headers: { "content-type": "application/json" },
      })
    }) as typeof fetch
    try {
      const result = await requestNativeOAuth(
        broker,
        "openai.device_poll",
        { device_auth_id: "synthetic-device-auth", user_code: "synthetic-user-code" },
        new AbortController().signal,
      )
      expect(result).toEqual({ status: "pending" })
      expect(request?.url).toBe("http://127.0.0.1:8000/api/v1/assistant/internal/oauth")
      expect(request?.init?.method).toBe("POST")
      expect(request?.init?.redirect).toBe("error")
      expect(request?.init?.credentials).toBe("omit")
      expect(request?.init?.headers).toEqual({
        Accept: "application/json",
        Authorization: `Bearer ${broker.capability}`,
        "Content-Type": "application/json",
      })
      expect(JSON.parse(String(request?.init?.body))).toEqual({
        attempt_id: broker.attemptID,
        operation: "openai.device_poll",
        input: { device_auth_id: "synthetic-device-auth", user_code: "synthetic-user-code" },
      })
    } finally {
      globalThis.fetch = originalFetch
    }
  })

  test("does not make a request with malformed attempt capabilities", async () => {
    const originalFetch = globalThis.fetch
    let calls = 0
    globalThis.fetch = (async () => {
      calls += 1
      return new Response("{}", { status: 200 })
    }) as typeof fetch
    try {
      await expect(
        requestNativeOAuth(
          { ...broker, capability: "not-a-capability" },
          "openai.device_start",
          {},
          new AbortController().signal,
        ),
      ).rejects.toThrow("OAuth broker request failed")
      expect(calls).toBe(0)
    } finally {
      globalThis.fetch = originalFetch
    }
  })

  test("rejects redirects, non-JSON responses, and oversized response bodies", async () => {
    const originalFetch = globalThis.fetch
    try {
      globalThis.fetch = (async () =>
        new Response("", { status: 302, headers: { location: "https://example.invalid/" } })) as typeof fetch
      await expect(requestNativeOAuth(broker, "openai.device_start", {}, new AbortController().signal)).rejects.toThrow()

      globalThis.fetch = (async () => new Response("{}", { status: 200 })) as typeof fetch
      await expect(requestNativeOAuth(broker, "openai.device_start", {}, new AbortController().signal)).rejects.toThrow()

      globalThis.fetch = (async () =>
        new Response(new Uint8Array(64 * 1024 + 1), {
          status: 200,
          headers: { "content-type": "application/json" },
        })) as typeof fetch
      await expect(requestNativeOAuth(broker, "openai.device_start", {}, new AbortController().signal)).rejects.toThrow()
    } finally {
      globalThis.fetch = originalFetch
    }
  })
})

describe("managed OpenCode device launch validation", () => {
  const device = {
    device_code: "synthetic-device-code",
    user_code: "ABC-123",
    verification_uri_complete: "/console/device?user_code=ABC-123&client_id=opencode-cli",
    expires_in: 600,
    interval: 5,
  }

  test("accepts only the fixed HTTPS console device flow", () => {
    expect(validateOpenCodeDeviceLaunch(device)).toEqual({
      deviceCode: "synthetic-device-code",
      userCode: "ABC-123",
      url: "https://opencode.ai/console/device?user_code=ABC-123&client_id=opencode-cli",
      expiresIn: 600,
      interval: 5,
    })
  })

  test.each([
    { ...device, verification_uri_complete: "http://opencode.ai/console/device?user_code=ABC-123&client_id=opencode-cli" },
    { ...device, verification_uri_complete: "https://opencode.ai:444/console/device?user_code=ABC-123&client_id=opencode-cli" },
    { ...device, verification_uri_complete: "https://opencode.ai.evil.test/console/device?user_code=ABC-123&client_id=opencode-cli" },
    { ...device, verification_uri_complete: "https://user@opencode.ai/console/device?user_code=ABC-123&client_id=opencode-cli" },
    { ...device, verification_uri_complete: "https://opencode.ai/console/other?user_code=ABC-123&client_id=opencode-cli" },
    { ...device, verification_uri_complete: "https://opencode.ai/console/device?user_code=other&client_id=opencode-cli" },
    { ...device, verification_uri_complete: "https://opencode.ai/console/device?user_code=ABC-123&user_code=ABC-123&client_id=opencode-cli" },
    { ...device, verification_uri_complete: "https://opencode.ai/console/device?user_code=ABC-123&client_id=opencode-cli&next=https%3A%2F%2Fevil.test" },
    { ...device, verification_uri_complete: "https://opencode.ai/console/device?user_code=ABC-123&client_id=other" },
    { ...device, verification_uri_complete: "https://opencode.ai/console/device?user_code=ABC-123&client_id=opencode-cli#fragment" },
    { ...device, verification_uri_complete: "https://opencode.ai/console/device?user_code=ABC-123&client_id=opencode-cli&client_id=opencode-cli" },
    { ...device, device_code: "bad\ncode" },
    { ...device, expires_in: 601 },
    { ...device, interval: 61 },
    { ...device, user_code: "ABC 123" },
    { ...device, extra: "unexpected" },
  ])("rejects an unsafe or malformed launch response", (value) => {
    expect(() => validateOpenCodeDeviceLaunch(value)).toThrow()
  })
})
