import { describe, expect, test } from "bun:test"
import {
  transformOAuthCoreTest,
  transformOAuthOpenAITest,
  transformOAuthOpencode,
  transformOAuthOpencodeTest,
  transformOAuthPluginHost,
  transformOAuthPluginRegistration,
} from "./oauth-handoff"

describe("pinned native OAuth test transform", () => {
  // Synthetic source snippets isolate each exact patch anchor without downloading upstream code.
  test("preserves each managed broker lease through the PluginHost registration wrapper", () => {
    const source = [
      "return {",
      "      authorize: (answer) =>",
      "        input.authorize(answer).pipe(",
      "          (authorization) => authorization,",
      "        ),",
      "}",
    ].join("\n") + "\n"
    const received: unknown[] = []
    const register = new Function("input", transformOAuthPluginHost(source))
    const implementation = register({
      authorize: (answer: unknown, broker: unknown) => {
        received.push({ answer, broker })
        return { pipe: (mapper: (value: unknown) => unknown) => mapper("fixture-authorization") }
      },
    })
    const first = { attemptID: "a".repeat(32), capability: "b".repeat(32) }
    const second = { attemptID: "c".repeat(32), capability: "d".repeat(32) }
    expect(implementation.authorize({}, first)).toBe("fixture-authorization")
    expect(implementation.authorize({}, second)).toBe("fixture-authorization")
    expect(received).toEqual([{ answer: {}, broker: first }, { answer: {}, broker: second }])
    expect(() => transformOAuthPluginHost(source + source)).toThrow("anchor mismatch")
    const registration = transformOAuthPluginRegistration([
      "export type IntegrationOAuthAuthorization = {",
      "  readonly expiresAt?: number",
      "} & (",
      "unknown)",
      "readonly authorize: (answer: Form.Answer) => Effect.Effect<IntegrationOAuthAuthorization, unknown, Scope.Scope>",
      "",
    ].join("\n"))
    expect(registration).toContain("assistantOAuth?: AssistantOAuthBroker")
    expect(registration).toContain("readonly relay?:")
  })

  test("injects an expired-but-unscrubbed callback rejection regression", () => {
    const source = [
      'import { Cause, Clock, Duration, Effect, Exit, Fiber, Layer, Scope, Stream } from "effect"',
      'import { Integration } from "@opencode/core/integration"',
      "",
      'describe("Integration", () => {',
      "",
      "})",
      "",
      'describe("AuthorizationError", () => {',
    ].join("\n")

    const transformed = transformOAuthCoreTest(source)
    expect(transformed).toContain('import { Cause, Clock, Deferred, Duration, Effect, Exit, Fiber, Layer, Scope, Stream } from "effect"')
    expect(transformed).toContain("does not invoke a browser relay after its native attempt expires")
    expect(transformed).toContain("Duration.millis(101)")
    expect(transformed).toContain(').status).toBe("pending")')
    expect(transformed).toContain("expect(relayCalls).toBe(0)")
  })

  test("keeps managed OpenCode device OAuth on the fixed broker path", () => {
    const source = [
      'import { Duration, Effect, Equal, Schema, Semaphore, Stream } from "effect"',
      'import { Integration } from "../../integration.js"',
      'const Org = Schema.Struct({ id: Schema.String, name: Schema.String })',
      'const method = {',
      '    authorize: (answer) =>',
      '      Effect.gen(function* () {',
      '        const server = yield* normalizeServer(answer.server ?? defaultServer)',
      '        const device = yield* post(http, `${server}/auth/device/code`, { client_id: clientID, supports_org_scope: true }, Device)',
      '        return { mode: "auto" as const, url: device.verification_uri_complete }',
      '      }),',
      '    refresh: (credential) =>',
      '      Effect.void,',
      '}',
    ].join("\n")

    const transformed = transformOAuthOpencode(source)
    expect(transformed).toContain('nativeBrokerRequest(assistantOAuth, "opencode.device_start", {})')
    expect(transformed).toContain('nativeBrokerRequest(broker, "opencode.device_poll", { device_code: device.deviceCode })')
    expect(transformed).toContain('nativeBrokerRequest(broker, "opencode.user", { access_token: token.access_token })')
    expect(transformed).toContain('nativeBrokerRequest(broker, "opencode.orgs", { access_token: token.access_token })')
    expect(transformed).toContain("validateOpenCodeDeviceLaunch(raw)")
    expect(transformed).toContain('if (answer.server !== undefined && answer.server !== defaultServer)')
    expect(transformed).toContain('instructions: `Enter code: ${device.userCode}`')
    new Bun.Transpiler({ loader: "ts", target: "bun" }).transformSync(transformed)
  })

  test("adds an actual managed OpenCode provider handoff regression to the pinned provider suite", () => {
    const source = [
      'import { describe, expect } from "bun:test"',
      'import { Effect, Layer, Stream } from "effect"',
      'import { TestClock } from "effect/testing"',
      'import { Credential } from "@opencode/core/credential"',
      'import { Integration } from "@opencode/core/integration"',
      'import { withEnv } from "../fixture/env"',
      'const it = testEffect(PluginTestLayer)',
      'const addPlugin = Effect.fn(function* () {})',
      'function eventually() {}',
      'describe("OpencodePlugin", () => {',
      '})',
    ].join("\n")

    const transformed = transformOAuthOpencodeTest(source)
    expect(transformed).toContain('import { Duration, Effect, Layer, Stream } from "effect"')
    expect(transformed).toContain("keeps managed OpenCode OAuth ephemeral behind the fixed broker")
    expect(transformed).toContain('"opencode.device_start", "opencode.device_poll", "opencode.user", "opencode.orgs"')
    expect(transformed).toContain("credentials.list(integrationID)).toEqual([])")
    expect(transformed).toContain("cancels a managed OpenCode device attempt before any credential handoff")
    expect(transformed.match(/answer: \{ server: "https:\/\/opencode\.ai\/console" \}/g)).toHaveLength(2)
    expect(transformed).toContain('operations).toEqual(["opencode.device_start"])')
    expect(transformed).toContain("integrations.oauth.handoff({ integrationID, attemptID: attempt.attemptID })")
    expect(transformed).toContain("expect(replay).toBeInstanceOf(Integration.AttemptNotFoundError)")
    new Bun.Transpiler({ loader: "ts", target: "bun" }).transformSync(transformed)
  })

  test("adds an actual managed OpenAI browser relay regression to the pinned provider suite", () => {
    const source = [
      'import { describe, expect } from "bun:test"',
      'import { Effect } from "effect"',
      'import { Credential } from "@opencode/core/credential"',
      'import { Integration } from "@opencode/core/integration"',
      'const it = testEffect(PluginTestLayer)',
      'const addPlugin = Effect.fn(function* () {})',
      'describe("OpenAIPlugin", () => {',
      '})',
    ].join("\n") + "\n"

    const transformed = transformOAuthOpenAITest(source)
    expect(transformed).toContain('import { withEnv } from "../fixture/env"')
    expect(transformed).toContain("relays managed browser OAuth through the fixed broker")
    expect(transformed).toContain('methodID: Integration.MethodID.make("chatgpt-browser")')
    expect(transformed).toContain("callbackURL: `${redirect}?code=synthetic-code&state=wrong-state`")
    expect(transformed).toContain("expect(invalid).toBeInstanceOf(Integration.AuthorizationError)")
    expect(transformed).toContain('operation: "openai.token_exchange"')
    expect(transformed).toContain("expect(replay).toBeInstanceOf(Integration.AttemptNotFoundError)")
    new Bun.Transpiler({ loader: "ts", target: "bun" }).transformSync(transformed)
  })
})
