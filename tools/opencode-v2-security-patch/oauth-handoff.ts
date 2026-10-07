/** Exact-source OpenCode V2 OAuth broker transform, separate from the WebFetch patch. */
import { createHash } from "node:crypto"
import { mkdir, readFile, writeFile } from "node:fs/promises"
import { dirname, join } from "node:path"

export const OAUTH_SOURCE_HASHES = {
  "packages/core/src/integration.ts": "9ca977e0853d478003ef8a6bee047b58b693b562fc5cd7bc1f12da5d0acc7643",
  "packages/core/src/plugin/provider/openai.ts": "efd0627cf510f24bbe0a4261c114be06528e66f5440fdc08904c135b350d0452",
  "packages/core/src/plugin/provider/opencode.ts": "72bcb6fdd7715b1bfc86c66538499b7f6ea1121616b14e363d79b7188535cbe1",
  "packages/core/src/plugin/host.ts": "1385d595a23c3d6baa99ccc21b6ac4c31c34a9903d8503d845058d464fda24fc",
  "packages/plugin/src/effect/integration.ts": "f3d89e5bf5e80d0938a37361d15e62adae7574ba785fcc0b9a8458e996fc6519",
  "packages/core/test/plugin/provider-openai.test.ts": "034007dedec16ac942a2768dbbbe2325eb40e0db3dbdd898233d9d84bcdbb07a",
  "packages/core/test/plugin/provider-opencode.test.ts": "30d35e246cdc8f2297d5e331209c87003f96417ebdb50d97dac5bd9cf965184e",
  "packages/protocol/src/groups/integration.ts": "3947341255402b397a69d9ff69f16c1161defc8cd6fe94d98373e7674cb293c1",
  "packages/schema/src/credential.ts": "18afc88d8e8174c663fd4bfa5432232e04ee526435ebe844eefdc23006f73341",
  "packages/server/src/handlers/integration.ts": "738a60e91fdc7821eb184162a76a261c1b8e1a1bdfb981a4ca057c7a6786226c",
  "packages/core/test/integration.test.ts": "df8a8ccd6c7b50d3cfd3a6080ba7890dc30c9edf696c9c4de93dcd310904ec06",
} as const

const HANDOFF_ENV = "OPENCODE_ASSISTANT_OAUTH_HANDOFF"
const HANDOFF_LIMIT = 32
const HANDOFF_TTL = 60_000
const BROKER_CONTEXT_TYPE = `/** Per-attempt app broker capability; held only in native attempt memory. */
export type AssistantOAuthBroker = {
  readonly attemptID: string
  readonly capability: string
}`

type SourcePath = keyof typeof OAUTH_SOURCE_HASHES
type SourceMap = Record<SourcePath, string>

function replaceOnce(source: string, before: string, after: string, name: string): string {
  if (source.split(before).length !== 2) throw new Error(`OAuth patch anchor mismatch: ${name}`)
  return source.replace(before, after)
}

function replaceBetween(source: string, start: string, end: string, replacement: string, name: string): string {
  const first = source.indexOf(start)
  const last = source.indexOf(end, first + start.length)
  if (first < 0 || last < 0 || source.indexOf(start, first + start.length) >= 0) {
    throw new Error(`OAuth patch anchor mismatch: ${name}`)
  }
  return source.slice(0, first) + replacement + source.slice(last)
}

function replaceFirst(source: string, before: string, after: string, name: string): string {
  const index = source.indexOf(before)
  if (index < 0) throw new Error(`OAuth patch anchor mismatch: ${name}`)
  return source.slice(0, index) + after + source.slice(index + before.length)
}

export function transformOAuthCore(source: string): string {
  source = replaceOnce(
    source,
    `export type OAuthAuthorization = {\n`,
    `${BROKER_CONTEXT_TYPE}\n\nexport type OAuthAuthorization = {\n`,
    "managed-broker-context-type",
  )
  source = replaceOnce(
    source,
    `  readonly expiresAt?: number\n} & (\n`,
    `  readonly expiresAt?: number\n  /** Attempt-bound callback relay; only browser OAuth implementations provide it. */\n  readonly relay?: (callbackURL: string) => Effect.Effect<void, unknown>\n} & (\n`,
    "authorization-relay-type",
  )
  source = replaceOnce(
    source,
    `readonly authorize: (answer: Form.Answer) => Effect.Effect<OAuthAuthorization, unknown, Scope.Scope>\n`,
    `readonly authorize: (answer: Form.Answer, assistantOAuth?: AssistantOAuthBroker) => Effect.Effect<OAuthAuthorization, unknown, Scope.Scope>\n`,
    "provider-authorize-broker-argument",
  )
  source = replaceOnce(
    source,
    `      readonly label?: string\n    }) => Effect.Effect<Attempt, AuthorizationError>\n`,
    `      readonly label?: string\n      /** Private app lease for the managed worker; never returned in Attempt. */\n      readonly assistantOAuth?: AssistantOAuthBroker\n    }) => Effect.Effect<Attempt, AuthorizationError>\n`,
    "oauth-connect-broker-input",
  )

  source = replaceOnce(
    source,
    `    /** Cancels an attempt and releases its resources. */\n    readonly cancel: (input: { readonly integrationID: ID; readonly attemptID: AttemptID }) => Effect.Effect<void>\n`,
    `    /** Relays a copied callback URL only through the attempt's registered callback. */\n    readonly callback: (input: {\n      readonly integrationID: ID\n      readonly attemptID: AttemptID\n      readonly callbackURL: string\n    }) => Effect.Effect<void, AuthorizationError | AttemptNotFoundError>\n    /** Consumes an ephemeral OAuth value once; available only in managed-worker mode. */\n    readonly handoff: (input: { readonly integrationID: ID; readonly attemptID: AttemptID }) => Effect.Effect<Credential.OAuth, AttemptNotFoundError>\n    /** Cancels an attempt and releases its resources, including an unclaimed credential. */\n    readonly cancel: (input: { readonly integrationID: ID; readonly attemptID: AttemptID }) => Effect.Effect<void>\n`,
    "oauth-private-methods",
  )

  source = replaceOnce(
    source,
    `type PendingAttempt = {\n  status: "pending"\n`,
    `type StartingAttempt = {\n  status: "starting"\n  integrationID: ID\n  methodID: MethodID\n  label?: string\n  assistantOAuth?: AssistantOAuthBroker\n  scope: Scope.Closeable\n  time: AttemptTime\n}\ntype PendingAttempt = {\n  status: "pending"\n`,
    "starting-attempt-type",
  )
  source = replaceOnce(
    source,
    `  completing: boolean\n  persisting: boolean\n`,
    `  completing: boolean\n  callbackSubmitted: boolean\n  persisting: boolean\n`,
    "callback-replay-state",
  )
  source = replaceOnce(
    source,
    `  label?: string\n  scope: Scope.Closeable\n`,
    `  label?: string\n  assistantOAuth?: AssistantOAuthBroker\n  scope: Scope.Closeable\n`,
    "pending-broker-context",
  )
  source = replaceOnce(
    source,
    `type TerminalAttempt = {\n  status: "complete" | "failed" | "expired"\n  integrationID: ID\n  message?: string\n  removeAt: number\n  time: AttemptTime\n}\ntype AttemptEntry = PendingAttempt | TerminalAttempt\n`,
    `type TerminalAttempt = {\n  status: "complete" | "failed" | "expired"\n  integrationID: ID\n  message?: string\n  credential?: Credential.OAuth\n  credentialExpiresAt?: number\n  removeAt: number\n  time: AttemptTime\n}\ntype AttemptEntry = StartingAttempt | PendingAttempt | TerminalAttempt\n`,
    "ephemeral-terminal-credential",
  )
  source = replaceFirst(
    source,
    `        for (const [id, attempt] of current) {\n          if (attempt.status === "pending" && !attempt.persisting && attempt.time.expires <= now) {\n`,
    `        for (const [id, attempt] of current) {\n          if (attempt.status === "starting" && attempt.time.expires <= now) {\n            scopes.push(attempt.scope)\n            next.delete(id)\n            continue\n          }\n          if (attempt.status === "pending" && !attempt.persisting && attempt.time.expires <= now) {\n`,
    "starting-attempt-expiry",
  )
  source = replaceFirst(
    source,
    `          if (attempt.status !== "pending" && attempt.removeAt <= now) next.delete(id)\n`,
    `          if (attempt.status !== "pending" && attempt.status !== "starting" && attempt.removeAt <= now)\n            next.delete(id)\n`,
    "starting-attempt-scrub-union",
  )
  source = replaceOnce(
    source,
    `const attemptLifetime = Duration.toMillis(Duration.minutes(10))\nconst terminalRetention = Duration.toMillis(Duration.minutes(1))\n`,
    `const attemptLifetime = Duration.toMillis(Duration.minutes(10))\nconst terminalRetention = Duration.toMillis(Duration.minutes(1))\nconst maxOAuthAttempts = ${HANDOFF_LIMIT}\nconst handoffCredentialLifetime = ${HANDOFF_TTL}\nconst handoffEnabled = () => process.env["${HANDOFF_ENV}"] === "1"\nconst validAssistantOAuthBroker = (value: unknown): value is AssistantOAuthBroker => {\n  if (!value || typeof value !== "object") return false\n  const broker = value as Partial<AssistantOAuthBroker>\n  return /^[0-9a-f]{32}$/.test(broker.attemptID ?? "") && /^[0-9a-f]{32}$/.test(broker.capability ?? "")\n}\n`,
    "bounded-handoff-settings",
  )

  source = replaceBetween(
    source,
    `    const connectOAuth = Effect.fn("Integration.oauth.connect")(function* (input: {`,
    `    const connectCommand = Effect.fn("Integration.command.connect")(function* (input: {`,
    `    const connectOAuth = Effect.fn("Integration.oauth.connect")(function* (input: {
      readonly integrationID: ID
      readonly methodID: MethodID
      readonly answer?: Form.Answer
      readonly label?: string
      readonly assistantOAuth?: AssistantOAuthBroker
    }) {
      const method = state.get().integrations.get(input.integrationID)?.implementations.get(input.methodID)
      if (!method) {
        return yield* Effect.die(new Error("OAuth method not found"))
      }
      const assistantOAuth = input.assistantOAuth
      if (handoffEnabled() !== (assistantOAuth !== undefined) || (assistantOAuth && !validAssistantOAuthBroker(assistantOAuth))) {
        return yield* new AuthorizationError({ cause: new Error("Managed OAuth broker required") })
      }
      const answer = input.answer ?? {}
      if (method.method.form) {
        const invalid = Form.validateFields(method.method.form) ?? Form.validateAnswer(method.method.form, answer)
        if (invalid) return yield* new AuthorizationError({ cause: new Error(invalid) })
      }
      const id = AttemptID.create()
      const created = yield* Clock.currentTimeMillis
      const reservationTime = { created, expires: created + attemptLifetime }
      const attemptScope = yield* Scope.fork(scope)
      const reserved = yield* SynchronizedRef.modify(attempts, (current) => {
        if (current.size >= maxOAuthAttempts) return [false, current]
        const next = new Map(current)
        next.set(id, {
          status: "starting",
          integrationID: input.integrationID,
          methodID: input.methodID,
          label: input.label,
          assistantOAuth,
          scope: attemptScope,
          time: reservationTime,
        })
        return [true, next]
      })
      if (!reserved) {
        yield* close(attemptScope)
        return yield* new AuthorizationError({ cause: new Error("OAuth attempt capacity reached") })
      }
      let installed = false
      return yield* Effect.gen(function* () {
        const authorization = yield* authorize(method.authorize(answer, assistantOAuth)).pipe(
          Scope.provide(attemptScope),
          Effect.onExit((exit) => (Exit.isFailure(exit) ? Scope.close(attemptScope, exit) : Effect.void)),
        )
        const time = {
          created,
          expires: Math.min(reservationTime.expires, Math.max(created, authorization.expiresAt ?? reservationTime.expires)),
        }
        const accepted = yield* SynchronizedRef.modify(attempts, (current) => {
          const match = current.get(id)
          if (!match || match.status !== "starting") return [false, current]
          const next = new Map(current).set(id, {
            status: "pending" as const,
            completing: authorization.mode === "auto",
            callbackSubmitted: false,
            persisting: false,
            authorization,
            integrationID: input.integrationID,
            methodID: input.methodID,
            label: input.label,
            assistantOAuth,
            scope: attemptScope,
            time,
          })
          return [true, next]
        })
        if (!accepted) {
          yield* close(attemptScope)
          return yield* new AuthorizationError({ cause: new Error("OAuth attempt is no longer available") })
        }
        if (authorization.mode === "auto") {
          yield* authorization.callback.pipe(
            Effect.exit,
            Effect.flatMap((exit) => settle(id, exit)),
            Effect.forkIn(attemptScope, { startImmediately: true }),
          )
        }
        installed = true
        return new Attempt({
          attemptID: id,
          url: authorization.url,
          instructions: authorization.instructions,
          mode: authorization.mode,
          time,
        })
      }).pipe(
        Effect.ensuring(
          SynchronizedRef.update(attempts, (current) => {
            if (installed) return current
            const match = current.get(id)
            if (!match || match.status !== "starting") return current
            const next = new Map(current)
            next.delete(id)
            return next
          }),
        ),
      )
    })

`,
    "bounded-oauth-connect",
  )

  source = replaceOnce(
    source,
    `      yield* Effect.gen(function* () {\n        const persistence = yield* Effect.suspend(() => {\n`,
    `      if (handoffEnabled()) {\n        const settledAt = yield* Clock.currentTimeMillis\n        const credentialExpiresAt = Math.min(\n          attempt.time.expires,\n          settledAt + Duration.toMillis(handoffCredentialLifetime),\n        )\n        const terminal: TerminalAttempt = {\n          status: "complete",\n          integrationID: attempt.integrationID,\n          credential: exit.value,\n          credentialExpiresAt,\n          time: attempt.time,\n          removeAt: credentialExpiresAt,\n        }\n        yield* SynchronizedRef.update(attempts, (current) => new Map(current).set(attemptID, terminal))\n        yield* close(attempt.scope)\n        return\n      }\n\n      yield* Effect.gen(function* () {\n        const persistence = yield* Effect.suspend(() => {\n`,
    "ephemeral-handoff-settlement",
  )

  source = replaceOnce(
    source,
    `          if (attempt.status === "failed") {\n            return { status: attempt.status, message: attempt.message ?? "Authorization failed", time: attempt.time }\n          }\n          return { status: attempt.status, time: attempt.time }\n`,
    `          if (attempt.status === "failed") {\n            return { status: attempt.status, message: attempt.message ?? "Authorization failed", time: attempt.time }\n          }\n          if (attempt.status === "starting") return { status: "pending" as const, time: attempt.time }\n          return { status: attempt.status, time: attempt.time }\n`,
    "starting-status-projection",
  )

  source = replaceOnce(
    source,
    `        cancel: Effect.fn("Integration.oauth.cancel")(function* (input) {\n          const attempt = yield* SynchronizedRef.modify(attempts, (current) => {\n            const match = current.get(input.attemptID)\n            if (!match || match.integrationID !== input.integrationID || match.status !== "pending" || match.persisting)\n              return [undefined, current]\n            const next = new Map(current)\n            next.delete(input.attemptID)\n            return [match, next]\n          })\n          if (attempt) yield* Scope.close(attempt.scope, Exit.void)\n        }),\n`,
    `        callback: Effect.fn("Integration.oauth.callback")(function* (input) {\n          const now = yield* Clock.currentTimeMillis\n          const attempt = yield* SynchronizedRef.modify(attempts, (current) => {\n            const match = current.get(input.attemptID)\n            if (\n              !match ||\n              match.integrationID !== input.integrationID ||\n              match.status !== "pending" ||\n              match.time.expires <= now ||\n              match.callbackSubmitted ||\n              !match.authorization.relay\n            ) return [undefined, current]\n            return [match, new Map(current).set(input.attemptID, { ...match, callbackSubmitted: true })]\n          })\n          if (!attempt) return yield* new AttemptNotFoundError(input)\n          const result = yield* authorize(attempt.authorization.relay!(input.callbackURL)).pipe(Effect.exit)\n          if (Exit.isFailure(result)) {\n            yield* SynchronizedRef.update(attempts, (current) => {\n              const match = current.get(input.attemptID)\n              if (!match || match.integrationID !== input.integrationID || match.status !== "pending") return current\n              return new Map(current).set(input.attemptID, { ...match, callbackSubmitted: false })\n            })\n            return yield* Effect.failCause(result.cause)\n          }\n        }),\n        handoff: Effect.fn("Integration.oauth.handoff")(function* (input) {\n          if (!handoffEnabled()) return yield* new AttemptNotFoundError(input)\n          const now = yield* Clock.currentTimeMillis\n          const value = yield* SynchronizedRef.modify(attempts, (current) => {\n            const match = current.get(input.attemptID)\n            if (!match || match.integrationID !== input.integrationID || match.status !== "complete" || !match.credential) {\n              return [undefined, current]\n            }\n            if ((match.credentialExpiresAt ?? 0) <= now) {\n              const next = new Map(current)\n              next.delete(input.attemptID)\n              return [undefined, next]\n            }\n            const next = new Map(current)\n            next.set(input.attemptID, {\n              ...match,\n              credential: undefined,\n              credentialExpiresAt: undefined,\n              removeAt: now + terminalRetention,\n            })\n            return [match.credential, next]\n          })\n          if (!value) return yield* new AttemptNotFoundError(input)\n          return value\n        }),\n        cancel: Effect.fn("Integration.oauth.cancel")(function* (input) {\n          const attempt = yield* SynchronizedRef.modify(attempts, (current) => {\n            const match = current.get(input.attemptID)\n            if (!match || match.integrationID !== input.integrationID) return [undefined, current]\n            if (match.status === "pending" && match.persisting) return [undefined, current]\n            const next = new Map(current)\n            next.delete(input.attemptID)\n            return [match, next]\n          })\n          if (attempt && (attempt.status === "starting" || attempt.status === "pending"))\n            yield* Scope.close(attempt.scope, Exit.void)\n        }),\n`,
    "oauth-callback-handoff-cancel",
  )
  return source
}

export function transformOAuthProvider(source: string): string {
  source = replaceOnce(
    source,
    `import { Integration } from "../../integration.js"\n`,
    `import { Integration } from "../../integration.js"\nimport { parseOAuthCallbackURL } from "../../integration/oauth-callback.js"\nimport { requestNativeOAuth } from "../../integration/oauth-broker.js"\n`,
    "callback-helper-import",
  )
  source = replaceOnce(
    source,
    `type TokenResponse = {\n  id_token: string\n  access_token: string\n  refresh_token: string\n  expires_in?: number\n}\n`,
    `type TokenResponse = {\n  id_token: string\n  access_token: string\n  refresh_token: string\n  expires_in?: number\n}\n\nconst OAuthBrokerTokenResponse = Schema.Struct({\n  id_token: Schema.String,\n  access_token: Schema.String,\n  refresh_token: Schema.String,\n  expires_in: Schema.optional(Schema.Number),\n})\n\nfunction nativeBrokerRequest<Operation extends import("../../integration/oauth-broker.js").NativeOAuthOperation>(\n  broker: import("../../integration/oauth-broker.js").NativeOAuthBroker,\n  operation: Operation,\n  input: import("../../integration/oauth-broker.js").NativeOAuthInput<Operation>,\n) {\n  return Effect.tryPromise({\n    try: (signal) => requestNativeOAuth(broker, operation, input, signal),\n    catch: () => new Error("OAuth broker request failed"),\n  })\n}\n`,
    "openai-managed-oauth-broker-helper",
  )
  source = replaceOnce(
    source,
    `const OAuthBrokerTokenResponse = Schema.Struct({\n  id_token: Schema.String,\n  access_token: Schema.String,\n  refresh_token: Schema.String,\n  expires_in: Schema.optional(Schema.Number),\n})\n`,
    `const OAuthBrokerTokenResponse = Schema.Struct({\n  id_token: Schema.String,\n  access_token: Schema.String,\n  refresh_token: Schema.String,\n  expires_in: Schema.optional(Schema.Number),\n})\nconst OAuthBrokerDeviceStart = Schema.Struct({\n  device_auth_id: Schema.String,\n  user_code: Schema.String,\n  interval: Schema.String,\n})\nconst OAuthBrokerDevicePoll = Schema.Union([\n  Schema.Struct({ status: Schema.Literal("pending") }),\n  Schema.Struct({ status: Schema.Literal("authorized"), authorization_code: Schema.String, code_verifier: Schema.String }),\n])\n`,
    "openai-managed-device-schemas",
  )
  source = replaceOnce(
    source,
    `])\n\nfunction nativeBrokerRequest`,
    `])\n\nfunction decodeOAuthBrokerToken(value: unknown): TokenResponse | undefined {\n  const token = Option.getOrUndefined(Schema.decodeUnknownOption(OAuthBrokerTokenResponse)(value))\n  if (!token || !token.id_token || !token.access_token || !token.refresh_token) return undefined\n  if ([token.id_token, token.access_token, token.refresh_token].some((item) => item.length > 16_384)) return undefined\n  if (token.expires_in !== undefined && (!Number.isFinite(token.expires_in) || token.expires_in <= 0 || token.expires_in > 2_592_000)) return undefined\n  return token\n}\n\nfunction nativeBrokerRequest`,
    "openai-broker-token-bounds",
  )
  source = replaceFirst(
    source,
    `    authorize: () =>\n      Effect.gen(function* () {\n`,
    `    authorize: (_answer, assistantOAuth) =>\n      Effect.gen(function* () {\n`,
    "openai-browser-broker-argument",
  )
  source = replaceOnce(
    source,
    `const headless = (app: App.Info) =>\n`,
    `function pollManagedOpenAI(\n  broker: import("../../integration/oauth-broker.js").NativeOAuthBroker,\n  device: { device_auth_id: string; user_code: string },\n  interval: number,\n): Effect.Effect<Credential.OAuth, unknown> {\n  const loop = (): Effect.Effect<Credential.OAuth, unknown> =>\n    Effect.gen(function* () {\n      yield* Effect.sleep(interval + pollingSafetyMargin)\n      const raw = yield* nativeBrokerRequest(broker, "openai.device_poll", {\n        device_auth_id: device.device_auth_id,\n        user_code: device.user_code,\n      })\n      const result = Option.getOrUndefined(Schema.decodeUnknownOption(OAuthBrokerDevicePoll)(raw))\n      if (!result) return yield* Effect.fail(new Error("OAuth device response invalid"))\n      if (result.status === "pending") return yield* Effect.suspend(loop)\n      if (!result.authorization_code || result.authorization_code.length > 4096 || !result.code_verifier || result.code_verifier.length > 4096)\n        return yield* Effect.fail(new Error("OAuth device response invalid"))\n      const exchanged = yield* nativeBrokerRequest(broker, "openai.token_exchange", {\n        code: result.authorization_code,\n        redirect_uri: "https://auth.openai.com/deviceauth/callback",\n        code_verifier: result.code_verifier,\n      })\n      const tokens = decodeOAuthBrokerToken(exchanged)\n      if (!tokens) return yield* Effect.fail(new Error("OAuth token response invalid"))\n      return credential(headlessMethodID, tokens)\n    })\n  return loop()\n}\n\nconst headless = (app: App.Info) =>\n`,
    "openai-managed-device-poll",
  )
  source = replaceFirst(
    source,
    `    authorize: () =>\n      Effect.gen(function* () {\n        const device = yield* request<{ device_auth_id: string; user_code: string; interval: string }>(\n`,
    `    authorize: (_answer, assistantOAuth) =>\n      Effect.gen(function* () {\n        if (assistantOAuth) {\n          const raw = yield* nativeBrokerRequest(assistantOAuth, "openai.device_start", {})\n          const device = Option.getOrUndefined(Schema.decodeUnknownOption(OAuthBrokerDeviceStart)(raw))\n          if (!device || !device.device_auth_id || device.device_auth_id.length > 4096 || /[\\u0000-\\u001f\\u007f]/.test(device.device_auth_id) || !/^[A-Za-z0-9-]{1,256}$/.test(device.user_code) || !/^\\d{1,2}$/.test(device.interval))\n            return yield* Effect.fail(new Error("OAuth device response invalid"))\n          const intervalSeconds = Number.parseInt(device.interval, 10) || 5\n          const interval = Math.max(1, Math.min(intervalSeconds, 60)) * 1000\n          return {\n            mode: "auto" as const,\n            url: "\${issuer}/codex/device",\n            instructions: "Enter code: \${device.user_code}",\n            callback: pollManagedOpenAI(assistantOAuth, device, interval),\n          }\n        }\n        const device = yield* request<{ device_auth_id: string; user_code: string; interval: string }>(\n`,
    "openai-managed-device-start",
  )
  source = replaceBetween(
    source,
    `        // Lazy so runtimes without a loopback listener (workerd) never evaluate node:http.`,
    `        return {\n          mode: "auto" as const,\n`,
    [
      `        let redirect = \`http://localhost:\${callbackPort}/auth/callback\``,
      `        if (!assistantOAuth) {`,
      `          // Preserve native CLI behavior; managed workers never bind or cancel user-loopback ports.`,
      `          const { createServer } = yield* Effect.promise(() => import("node:http"))`,
      `          const server = createServer((request, response) => {`,
      `            const url = new URL(request.url ?? "/", "http://localhost")`,
      `            if (url.pathname !== "/auth/callback") {`,
      `              response.writeHead(404).end("Not found")`,
      `              return`,
      `            }`,
      `            const error = url.searchParams.get("error_description") ?? url.searchParams.get("error")`,
      `            const value = url.searchParams.get("code")`,
      `            if (error) {`,
      `              Effect.runFork(Deferred.fail(code, new Error(error)))`,
      `              response.writeHead(400, { "Content-Type": "text/html" }).end(OauthCallbackPage.error(error, { provider: "ChatGPT" }))`,
      `              return`,
      `            }`,
      `            if (!value || url.searchParams.get("state") !== state) {`,
      `              const message = value ? "Invalid OAuth state" : "Missing authorization code"`,
      `              Effect.runFork(Deferred.fail(code, new Error(message)))`,
      `              response.writeHead(400, { "Content-Type": "text/html" }).end(OauthCallbackPage.error(message, { provider: "ChatGPT" }))`,
      `              return`,
      `            }`,
      `            Effect.runFork(Deferred.succeed(code, value))`,
      `            response.writeHead(200, { "Content-Type": "text/html" }).end(OauthCallbackPage.success({ provider: "ChatGPT" }))`,
      `          })`,
      `          const port = yield* listen(server)`,
      `          yield* Effect.addFinalizer(() => Effect.sync(() => server.close()))`,
      `          redirect = \`http://localhost:\${port}/auth/callback\``,
      `        }`,
    ].join("\n") + "\n",
    "managed-openai-browser-listener",
  )
  const before = [
    `          callback: Deferred.await(code).pipe(`,
    `            Effect.flatMap((value) => exchange(value, redirect, pkce, app)),`,
    `            Effect.map((tokens) => credential(browserMethodID, tokens)),`,
    `          ),`,
  ].join("\n") + "\n"
  const after = [
    `          callback: Deferred.await(code).pipe(`,
    `            Effect.flatMap((value) => {`,
    `              if (!assistantOAuth) return exchange(value, redirect, pkce, app).pipe(Effect.map((tokens) => credential(browserMethodID, tokens)))`,
    `              return nativeBrokerRequest(assistantOAuth, "openai.token_exchange", { code: value, redirect_uri: redirect, code_verifier: pkce.verifier }).pipe(`,
    `                Effect.flatMap((result) => {`,
    `                  const tokens = decodeOAuthBrokerToken(result)`,
    `                  return tokens ? Effect.succeed(tokens) : Effect.fail(new Error("OAuth token response invalid"))`,
    `                }),`,
    `                Effect.map((tokens) => credential(browserMethodID, tokens)),`,
    `              )`,
    `            }),`,
    `          ),`,
    `          ...(assistantOAuth ? { relay: (callbackURL) =>`,
    `            Effect.try({`,
    `              try: () => parseOAuthCallbackURL(callbackURL, redirect, state),`,
    `              catch: (cause) => (cause instanceof Error ? cause : new Error("OAuth callback rejected")),`,
    `            }).pipe(`,
    `              Effect.flatMap((parsed) =>`,
    `                parsed.kind === "denied"`,
    `                  ? Deferred.fail(code, new Error("Authorization denied")).pipe(Effect.asVoid)`,
    `                  : Deferred.succeed(code, parsed.code).pipe(Effect.asVoid),`,
    `              ),`,
    `            ) } : {}),`,
  ].join("\n") + "\n"
  return replaceOnce(source, before, after, "attempt-bound-browser-relay")
}

export function transformOAuthOpencode(source: string): string {
  source = replaceOnce(
    source,
    `import { Duration, Effect, Equal, Schema, Semaphore, Stream } from "effect"\n`,
    `import { Clock, Duration, Effect, Equal, Option, Schema, Semaphore, Stream } from "effect"\n`,
    "opencode-managed-oauth-effect-imports",
  )
  source = replaceOnce(
    source,
    `import { Integration } from "../../integration.js"\n`,
    `import { Integration } from "../../integration.js"\nimport { requestNativeOAuth, validateOpenCodeDeviceLaunch } from "../../integration/oauth-broker.js"\n`,
    "opencode-managed-oauth-broker-import",
  )
  source = replaceOnce(
    source,
    `const Org = Schema.Struct({ id: Schema.String, name: Schema.String })\n`,
    `const Org = Schema.Struct({ id: Schema.String, name: Schema.String })
const OAuthBrokerDeviceToken = Schema.Union([
  Token,
  Schema.Struct({ error: Schema.Literal("authorization_pending") }),
  Schema.Struct({ error: Schema.Literal("slow_down") }),
])

function nativeBrokerRequest<Operation extends import("../../integration/oauth-broker.js").NativeOAuthOperation>(
  broker: import("../../integration/oauth-broker.js").NativeOAuthBroker,
  operation: Operation,
  input: import("../../integration/oauth-broker.js").NativeOAuthInput<Operation>,
) {
  return Effect.tryPromise({
    try: (signal) => requestNativeOAuth(broker, operation, input, signal),
    catch: () => new Error("OAuth broker request failed"),
  })
}

function exactKeys(value: unknown, required: readonly string[], optional: readonly string[] = []) {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false
  const keys = Object.keys(value)
  return required.every((key) => keys.includes(key)) && keys.every((key) => required.includes(key) || optional.includes(key))
}

function validToken(value: unknown): typeof Token.Type | undefined {
  if (!exactKeys(value, ["access_token", "refresh_token", "expires_in"], ["org_id"])) return undefined
  const token = Option.getOrUndefined(Schema.decodeUnknownOption(Token)(value))
  if (!token || !token.access_token || !token.refresh_token) return undefined
  if ([token.access_token, token.refresh_token].some((item) => item.length > 16_384)) return undefined
  if (!Number.isFinite(token.expires_in) || token.expires_in <= 0 || token.expires_in > 2_592_000) return undefined
  if (token.org_id != null && (token.org_id.length === 0 || token.org_id.length > 256)) return undefined
  return token
}

function pollManagedOpenCode(
  broker: import("../../integration/oauth-broker.js").NativeOAuthBroker,
  device: import("../../integration/oauth-broker.js").OpenCodeDeviceLaunch,
): Effect.Effect<Credential.OAuth, unknown> {
  const loop = (wait: number, expiresAt: number): Effect.Effect<Credential.OAuth, unknown> =>
    Effect.gen(function* () {
      const beforeWait = yield* Clock.currentTimeMillis
      if (beforeWait >= expiresAt) return yield* Effect.fail(new Error("OAuth device attempt expired"))
      yield* Effect.sleep(Math.min(wait, expiresAt - beforeWait))
      const pollStarted = yield* Clock.currentTimeMillis
      if (pollStarted >= expiresAt) return yield* Effect.fail(new Error("OAuth device attempt expired"))
      const raw = yield* nativeBrokerRequest(broker, "opencode.device_poll", { device_code: device.deviceCode })
      const result = Option.getOrUndefined(Schema.decodeUnknownOption(OAuthBrokerDeviceToken)(raw))
      const receivedAt = yield* Clock.currentTimeMillis
      if (receivedAt >= expiresAt || !result) return yield* Effect.fail(new Error("OAuth device response invalid"))
      if ("error" in result) {
        if (result.error === "authorization_pending") return yield* Effect.suspend(() => loop(wait, expiresAt))
        return yield* Effect.suspend(() => loop(Math.min(wait + 5_000, 60_000), expiresAt))
      }
      const token = validToken(result)
      if (!token) return yield* Effect.fail(new Error("OAuth token response invalid"))

      const userValue = yield* nativeBrokerRequest(broker, "opencode.user", { access_token: token.access_token })
      if (!exactKeys(userValue, ["id", "email"])) return yield* Effect.fail(new Error("OAuth account response invalid"))
      const user = Option.getOrUndefined(Schema.decodeUnknownOption(User)(userValue))
      if (!user || !user.id || !user.email || user.id.length > 512 || user.email.length > 512)
        return yield* Effect.fail(new Error("OAuth account response invalid"))

      const orgValue = yield* nativeBrokerRequest(broker, "opencode.orgs", { access_token: token.access_token })
      const orgs = Option.getOrUndefined(Schema.decodeUnknownOption(Schema.Array(Org))(orgValue))
      if (!orgs || orgs.length > 100 || orgs.some((org) => !org.id || org.id.length > 256 || org.name.length > 512))
        return yield* Effect.fail(new Error("OAuth organization response invalid"))
      const requestedOrgID = token.org_id ?? undefined
      const org = requestedOrgID
        ? orgs.find((candidate) => candidate.id === requestedOrgID)
        : orgs.toSorted((left, right) => left.name.localeCompare(right.name) || left.id.localeCompare(right.id))[0]
      if (requestedOrgID && !org) return yield* Effect.fail(new Error("OAuth organization response invalid"))

      return Credential.OAuth.make({
        type: "oauth" as const,
        methodID,
        access: token.access_token,
        refresh: token.refresh_token,
        expires: Date.now() + token.expires_in * 1000,
        metadata: {
          server: defaultServer,
          accountID: user.id,
          email: user.email,
          orgID: org?.id,
          orgName: org?.name,
        },
      })
    })

  return Effect.gen(function* () {
    const now = yield* Clock.currentTimeMillis
    return yield* loop(device.interval * 1000, now + device.expiresIn * 1000)
  })
}
`,
    "opencode-managed-oauth-helpers",
  )

  const authorizeStart = `    authorize: (answer) =>\n      Effect.gen(function* () {\n`
  const refreshStart = `    refresh: (credential) =>\n`
  const after = `    authorize: (answer, assistantOAuth) =>
      Effect.gen(function* () {
        if (assistantOAuth) {
          if (answer.server !== undefined && answer.server !== defaultServer)
            return yield* Effect.fail(new Error("Managed OpenCode authorization uses the fixed server"))
          const raw = yield* nativeBrokerRequest(assistantOAuth, "opencode.device_start", {})
          const device = yield* Effect.try({
            try: () => validateOpenCodeDeviceLaunch(raw),
            catch: () => new Error("OAuth device response invalid"),
          })
          return {
            mode: "auto" as const,
            url: device.url,
            instructions: \`Enter code: \${device.userCode}\`,
            callback: pollManagedOpenCode(assistantOAuth, device),
          }
        }
        const server = yield* normalizeServer(answer.server ?? defaultServer)
        const device = yield* post(
          http,
          \`\${server}/auth/device/code\`,
          { client_id: clientID, supports_org_scope: true },
          Device,
        )
        const verification = yield* Effect.try({
          try: () => {
            const url = new URL(device.verification_uri_complete, \`\${server}/\`)
            if (url.protocol !== "http:" && url.protocol !== "https:") throw new Error("expected HTTP(S)")
            return url
          },
          catch: (cause) =>
            new Error(\`Invalid device verification URL: \${cause instanceof Error ? cause.message : String(cause)}\`),
        })
        return {
          mode: "auto" as const,
          url: verification.href,
          instructions: \`Enter code: \${device.user_code}\`,
          callback: poll(http, server, device.device_code, Duration.seconds(device.interval)),
        }
      }),
`
  const startIndex = source.indexOf(authorizeStart)
  const endIndex = source.indexOf(refreshStart, startIndex + authorizeStart.length)
  if (startIndex < 0 || endIndex < 0 || source.indexOf(authorizeStart, startIndex + authorizeStart.length) >= 0) {
    throw new Error("OAuth patch anchor mismatch: managed-opencode-device-oauth")
  }
  const before = source.slice(startIndex, endIndex)
  return replaceOnce(source, before, after, "managed-opencode-device-oauth")
}

/** Preserve the private broker lease through native effect-provider registration. */
export function transformOAuthPluginHost(source: string): string {
  return replaceOnce(
    source,
    `      authorize: (answer) =>\n        input.authorize(answer).pipe(\n`,
    `      authorize: (answer, assistantOAuth) =>\n        input.authorize(answer, assistantOAuth).pipe(\n`,
    "plugin-host-managed-broker-forwarding",
  )
}

export function transformOAuthPluginRegistration(source: string): string {
  source = replaceOnce(
    source,
    `export type IntegrationOAuthAuthorization = {\n`,
    `${BROKER_CONTEXT_TYPE}\n\nexport type IntegrationOAuthAuthorization = {\n`,
    "plugin-managed-broker-context-type",
  )
  source = replaceOnce(
    source,
    `  readonly expiresAt?: number\n} & (\n`,
    `  readonly expiresAt?: number\n  /** Attempt-bound callback relay; never persisted or included in public attempt data. */\n  readonly relay?: (callbackURL: string) => Effect.Effect<void, unknown>\n} & (\n`,
    "plugin-authorization-relay-type",
  )
  return replaceOnce(
    source,
    `readonly authorize: (answer: Form.Answer) => Effect.Effect<IntegrationOAuthAuthorization, unknown, Scope.Scope>\n`,
    `readonly authorize: (answer: Form.Answer, assistantOAuth?: AssistantOAuthBroker) => Effect.Effect<IntegrationOAuthAuthorization, unknown, Scope.Scope>\n`,
    "plugin-provider-authorize-broker-argument",
  )
}

/** Exercise the transformed native provider through its actual Integration and Credential services. */
export function transformOAuthOpencodeTest(source: string): string {
  source = replaceOnce(
    source,
    `import { Effect, Layer, Stream } from "effect"\n`,
    `import { Duration, Effect, Layer, Stream } from "effect"\n`,
    "managed-opencode-test-duration-import",
  )
  const ending = source.endsWith("\n})\n") ? "\n})\n" : source.endsWith("\n})") ? "\n})" : undefined
  if (!ending) throw new Error("OAuth patch anchor mismatch: opencode-provider-test-end")
  const test = [
    `  it.effect("keeps managed OpenCode OAuth ephemeral behind the fixed broker", () =>`,
    `    withEnv({ OPENCODE_ASSISTANT_OAUTH_HANDOFF: "1" }, () =>`,
    `      Effect.acquireUseRelease(`,
    `        Effect.sync(() => {`,
    `          const originalFetch = globalThis.fetch`,
    `          const requests: { operation: string; attemptID: string; capabilityMatches: boolean; inputKeys: string[] }[] = []`,
    `          globalThis.fetch = (async (input, init) => {`,
    `            const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url`,
    `            let envelope: { attempt_id?: unknown; operation?: unknown; input?: unknown }`,
    `            try { envelope = JSON.parse(String(init?.body)) } catch { return new Response(null, { status: 400 }) }`,
    `            const headers = new Headers(init?.headers)`,
    `            const inputObject = envelope.input && typeof envelope.input === "object" ? envelope.input as Record<string, unknown> : {}`,
    `            const operation = typeof envelope.operation === "string" ? envelope.operation : "invalid"`,
    `            requests.push({`,
    `              operation,`,
    `              attemptID: typeof envelope.attempt_id === "string" && /^[0-9a-f]{32}$/.test(envelope.attempt_id) ? "valid" : "invalid",`,
    `              capabilityMatches: headers.get("authorization") === "Bearer " + "c".repeat(32),`,
    `              inputKeys: Object.keys(inputObject).sort(),`,
    `            })`,
    `            const result = operation === "opencode.device_start"`,
    `              ? { device_code: "synthetic-device", user_code: "SYNTH-123", verification_uri_complete: "https://opencode.ai/console/device?user_code=SYNTH-123&client_id=opencode-cli", expires_in: 120, interval: 0 }`,
    `              : operation === "opencode.device_poll"`,
    `                ? { access_token: "synthetic-access", refresh_token: "synthetic-refresh", expires_in: 600, org_id: "synthetic-org" }`,
    `                : operation === "opencode.user"`,
    `                  ? { id: "synthetic-account", email: "synthetic@example.invalid" }`,
    `                  : operation === "opencode.orgs" ? [{ id: "synthetic-org", name: "Synthetic Org" }] : undefined`,
    `            return Response.json({ result })`,
    `          }) as typeof fetch`,
    `          return { originalFetch, requests }`,
    `        }),`,
    `        ({ requests }) =>`,
    `          Effect.gen(function* () {`,
    `            yield* addPlugin()`,
    `            const integrations = yield* Integration.Service`,
    `            const integrationID = Integration.ID.make("opencode")`,
    `            const attempt = yield* integrations.oauth.connect({`,
    `              integrationID,`,
    `              methodID: Integration.MethodID.make("device"),`,
    `              answer: { server: "https://opencode.ai/console" },`,
    `              assistantOAuth: { attemptID: "a".repeat(32), capability: "c".repeat(32) },`,
    `            })`,
    `            expect(attempt.url).toBe("https://opencode.ai/console/device?user_code=SYNTH-123&client_id=opencode-cli")`,
    `            expect(attempt.instructions).toBe("Enter code: SYNTH-123")`,
    `            yield* TestClock.adjust(Duration.seconds(2))`,
    `            const status = yield* eventually(`,
    `              integrations.oauth.status({ integrationID, attemptID: attempt.attemptID }),`,
    `              (value) => value.status !== "pending",`,
    `            )`,
    `            expect(status.status).toBe("complete")`,
    `            const credentials = yield* Credential.Service`,
    `            expect(yield* credentials.list(integrationID)).toEqual([])`,
    `            const handoff = yield* integrations.oauth.handoff({ integrationID, attemptID: attempt.attemptID })`,
    `            expect(handoff).toMatchObject({`,
    `              type: "oauth",`,
    `              methodID: Integration.MethodID.make("device"),`,
    `              access: "synthetic-access",`,
    `              refresh: "synthetic-refresh",`,
    `              metadata: { server: "https://opencode.ai/console", accountID: "synthetic-account", orgID: "synthetic-org" },`,
    `            })`,
    `            const replay = yield* integrations.oauth.handoff({ integrationID, attemptID: attempt.attemptID }).pipe(Effect.flip)`,
    `            expect(replay).toBeInstanceOf(Integration.AttemptNotFoundError)`,
    `            expect(requests.map((request) => request.operation)).toEqual([`,
    `              "opencode.device_start", "opencode.device_poll", "opencode.user", "opencode.orgs",`,
    `            ])`,
    `            expect(requests.every((request) => request.attemptID === "valid" && request.capabilityMatches)).toBe(true)`,
    `            expect(requests.map((request) => request.inputKeys)).toEqual([[], ["device_code"], ["access_token"], ["access_token"]])`,
    `          }),`,
    `        ({ originalFetch }) => Effect.sync(() => { globalThis.fetch = originalFetch }),`,
    `      ),`,
    `    ),`,
    `  )`,
    ``,
    `  it.effect("cancels a managed OpenCode device attempt before any credential handoff", () =>`,
    `    withEnv({ OPENCODE_ASSISTANT_OAUTH_HANDOFF: "1" }, () =>`,
    `      Effect.acquireUseRelease(`,
    `        Effect.sync(() => {`,
    `          const originalFetch = globalThis.fetch`,
    `          const operations: string[] = []`,
    `          globalThis.fetch = (async (_input, init) => {`,
    `            const envelope = JSON.parse(String(init?.body)) as { operation?: unknown }`,
    `            operations.push(typeof envelope.operation === "string" ? envelope.operation : "invalid")`,
    `            return Response.json({ result: {`,
    `              device_code: "synthetic-device",`,
    `              user_code: "SYNTH-123",`,
    `              verification_uri_complete: "https://opencode.ai/console/device?user_code=SYNTH-123&client_id=opencode-cli",`,
    `              expires_in: 120,`,
    `              interval: 60,`,
    `            } })`,
    `          }) as typeof fetch`,
    `          return { originalFetch, operations }`,
    `        }),`,
    `        ({ operations }) =>`,
    `          Effect.gen(function* () {`,
    `            yield* addPlugin()`,
    `            const integrations = yield* Integration.Service`,
    `            const credentials = yield* Credential.Service`,
    `            const integrationID = Integration.ID.make("opencode")`,
    `            const attempt = yield* integrations.oauth.connect({`,
    `              integrationID,`,
    `              methodID: Integration.MethodID.make("device"),`,
    `              answer: { server: "https://opencode.ai/console" },`,
    `              assistantOAuth: { attemptID: "f".repeat(32), capability: "9".repeat(32) },`,
    `            })`,
    `            yield* integrations.oauth.cancel({ integrationID, attemptID: attempt.attemptID })`,
    `            yield* TestClock.adjust(Duration.seconds(61))`,
    `            const absent = yield* integrations.oauth.status({ integrationID, attemptID: attempt.attemptID }).pipe(Effect.flip)`,
    `            expect(absent).toBeInstanceOf(Integration.AttemptNotFoundError)`,
    `            const noHandoff = yield* integrations.oauth.handoff({ integrationID, attemptID: attempt.attemptID }).pipe(Effect.flip)`,
    `            expect(noHandoff).toBeInstanceOf(Integration.AttemptNotFoundError)`,
    `            expect(yield* credentials.list(integrationID)).toEqual([])`,
    `            expect(operations).toEqual(["opencode.device_start"])`,
    `          }),`,
    `        ({ originalFetch }) => Effect.sync(() => { globalThis.fetch = originalFetch }),`,
    `      ),`,
    `    ),`,
    `  )`,
  ].join("\n")
  return source.slice(0, -ending.length) + "\n\n" + test + "\n})\n"
}

/** Exercise the managed OpenAI browser callback relay through its native integration service. */
export function transformOAuthOpenAITest(source: string): string {
  const ending = source.endsWith("\n})\n") ? "\n})\n" : source.endsWith("\n})") ? "\n})" : undefined
  if (!ending) throw new Error("OAuth patch anchor mismatch: openai-provider-test-end")
  source = replaceOnce(
    source,
    `import { describe, expect } from "bun:test"\n`,
    `import { describe, expect } from "bun:test"\nimport { withEnv } from "../fixture/env"\n`,
    "openai-provider-test-managed-oauth-environment",
  )
  const test = [
    `  it.effect("relays managed browser OAuth through the fixed broker without a local listener", () =>`,
    `    withEnv({ OPENCODE_ASSISTANT_OAUTH_HANDOFF: "1" }, () =>`,
    `      Effect.acquireUseRelease(`,
    `        Effect.sync(() => {`,
    `          const originalFetch = globalThis.fetch`,
    `          const requests: { url: string; operation: string; inputKeys: string[]; capabilityMatches: boolean }[] = []`,
    `          globalThis.fetch = (async (input, init) => {`,
    `            const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url`,
    `            let envelope: { attempt_id?: unknown; operation?: unknown; input?: unknown }`,
    `            try { envelope = JSON.parse(String(init?.body)) } catch { return new Response(null, { status: 400 }) }`,
    `            const headers = new Headers(init?.headers)`,
    `            const payload = envelope.input && typeof envelope.input === "object" ? envelope.input as Record<string, unknown> : {}`,
    `            requests.push({`,
    `              url,`,
    `              operation: typeof envelope.operation === "string" ? envelope.operation : "invalid",`,
    `              inputKeys: Object.keys(payload).sort(),`,
    `              capabilityMatches: headers.get("authorization") === "Bearer " + "d".repeat(32),`,
    `            })`,
    `            return Response.json({ result: { id_token: "synthetic-id-token", access_token: "synthetic-access", refresh_token: "synthetic-refresh", expires_in: 600 } })`,
    `          }) as typeof fetch`,
    `          return { originalFetch, requests }`,
    `        }),`,
    `        ({ requests }) =>`,
    `          Effect.gen(function* () {`,
    `            yield* addPlugin()`,
    `            const integrations = yield* Integration.Service`,
    `            const integrationID = Integration.ID.make("openai")`,
    `            const attempt = yield* integrations.oauth.connect({`,
    `              integrationID,`,
    `              methodID: Integration.MethodID.make("chatgpt-browser"),`,
    `              assistantOAuth: { attemptID: "e".repeat(32), capability: "d".repeat(32) },`,
    `            })`,
    `            const authorization = new URL(attempt.url!)`,
    `            const redirect = authorization.searchParams.get("redirect_uri")`,
    `            const state = authorization.searchParams.get("state")`,
    `            expect(redirect).toBe("http://localhost:1455/auth/callback")`,
    `            expect(state).toBeTruthy()`,
    `            expect(attempt.instructions).toBe("Complete authorization in your browser. This window will close automatically.")`,
    `            const invalid = yield* integrations.oauth.callback({`,
    `              integrationID,`,
    `              attemptID: attempt.attemptID,`,
    `              callbackURL: \`\${redirect}?code=synthetic-code&state=wrong-state\`,`,
    `            }).pipe(Effect.flip)`,
    `            expect(invalid).toBeInstanceOf(Integration.AuthorizationError)`,
    `            expect(requests).toEqual([])`,
    `            yield* integrations.oauth.callback({`,
    `              integrationID,`,
    `              attemptID: attempt.attemptID,`,
    `              callbackURL: \`\${redirect}?code=synthetic-code&state=\${encodeURIComponent(state!)}\`,`,
    `            })`,
    `            const status = yield* Effect.gen(function* () {`,
    `              for (let remaining = 1000; remaining > 0; remaining -= 1) {`,
    `                const value = yield* integrations.oauth.status({ integrationID, attemptID: attempt.attemptID })`,
    `                if (value.status !== "pending") return value`,
    `                yield* Effect.promise(() => Bun.sleep(1))`,
    `              }`,
    `              return yield* Effect.fail(new Error("OAuth callback did not settle"))`,
    `            })`,
    `            expect(status.status).toBe("complete")`,
    `            const credentials = yield* Credential.Service`,
    `            expect(yield* credentials.list(integrationID)).toEqual([])`,
    `            const handoff = yield* integrations.oauth.handoff({ integrationID, attemptID: attempt.attemptID })`,
    `            expect(handoff).toMatchObject({ type: "oauth", methodID: Integration.MethodID.make("chatgpt-browser"), access: "synthetic-access", refresh: "synthetic-refresh" })`,
    `            const replay = yield* integrations.oauth.handoff({ integrationID, attemptID: attempt.attemptID }).pipe(Effect.flip)`,
    `            expect(replay).toBeInstanceOf(Integration.AttemptNotFoundError)`,
    `            expect(requests).toEqual([{`,
    `              url: "http://127.0.0.1:8000/api/v1/assistant/internal/oauth",`,
    `              operation: "openai.token_exchange",`,
    `              inputKeys: ["code", "code_verifier", "redirect_uri"],`,
    `              capabilityMatches: true,`,
    `            }])`,
    `          }),`,
    `        ({ originalFetch }) => Effect.sync(() => { globalThis.fetch = originalFetch }),`,
    `      ),`,
    `    ),`,
    `  )`,
  ].join("\n")
  return source.slice(0, -ending.length) + "\n\n" + test + "\n})\n"
}

export function transformOAuthProtocol(source: string): string {
  source = replaceOnce(
    source,
    `        methodID: Integration.MethodID,\n        answer: Schema.optional(Form.Answer),\n        label: Schema.optional(Schema.String),\n`,
    `        methodID: Integration.MethodID,\n        answer: Schema.optional(Form.Answer),\n        label: Schema.optional(Schema.String),\n        assistantOAuth: Schema.optional(\n          Schema.Struct({ attemptID: Schema.String, capability: Schema.String }),\n        ),\n`,
    "managed-oauth-connect-payload",
  )
  source = replaceOnce(
    source,
    `import { Form } from "@opencode/schema/form"\n`,
    `import { Form } from "@opencode/schema/form"\nimport { Credential } from "@opencode/schema/credential"\n`,
    "credential-schema-import",
  )

  const cancelEndpoint = `  .add(\n    HttpApiEndpoint.delete("integration.oauth.cancel", "/api/integration/:integrationID/connect/oauth/:attemptID", {\n      params: { integrationID: Integration.ID, attemptID: Integration.AttemptID },\n      query: LocationQuery,\n      success: HttpApiSchema.NoContent,\n    })\n      .annotateMerge(locationQueryOpenApi)\n      .annotateMerge(\n        OpenApi.annotations({\n          identifier: "integration.oauth.cancel",\n          summary: "Cancel OAuth connection",\n          description: "Cancel an OAuth attempt and release its resources.",\n        }),\n      ),\n  )\n`
  const privateEndpoints = `  .add(\n    HttpApiEndpoint.post("integration.oauth.callback", "/api/integration/:integrationID/connect/oauth/:attemptID/callback", {\n      params: { integrationID: Integration.ID, attemptID: Integration.AttemptID },\n      query: LocationQuery,\n      payload: Schema.Struct({ callbackURL: Schema.String }),\n      success: HttpApiSchema.NoContent,\n      error: [IntegrationNotFoundError, IntegrationAttemptNotFoundError, InvalidRequestError],\n    }).annotateMerge(locationQueryOpenApi),\n  )\n  .add(\n    HttpApiEndpoint.post("integration.oauth.handoff", "/api/integration/:integrationID/connect/oauth/:attemptID/handoff", {\n      params: { integrationID: Integration.ID, attemptID: Integration.AttemptID },\n      query: LocationQuery,\n      success: Location.response(Credential.OAuth),\n      error: [IntegrationNotFoundError, IntegrationAttemptNotFoundError],\n    }).annotateMerge(locationQueryOpenApi),\n  )\n`
  return replaceOnce(source, cancelEndpoint, `${privateEndpoints}${cancelEndpoint}`, "oauth-private-endpoints")
}

export function transformOAuthHandler(source: string): string {
  source = replaceOnce(
    source,
    `                methodID: ctx.payload.methodID,\n                answer: ctx.payload.answer,\n                label: ctx.payload.label,\n`,
    `                methodID: ctx.payload.methodID,\n                answer: ctx.payload.answer,\n                label: ctx.payload.label,\n                assistantOAuth: ctx.payload.assistantOAuth,\n`,
    "managed-oauth-connect-handler",
  )
  return replaceOnce(
    source,
    `      .handle(\n        "integration.oauth.cancel",\n`,
    `      .handle(\n        "integration.oauth.callback",\n        Effect.fn(function* (ctx) {\n          const service = yield* Integration.Service\n          if (!(yield* service.get(ctx.params.integrationID)))\n            return yield* new IntegrationNotFoundError({\n              integrationID: ctx.params.integrationID,\n              message: "Integration not found",\n            })\n          yield* service.oauth\n            .callback({\n              integrationID: ctx.params.integrationID,\n              attemptID: ctx.params.attemptID,\n              callbackURL: ctx.payload.callbackURL,\n            })\n            .pipe(\n              Effect.mapError((error) =>\n                error._tag === "Integration.AttemptNotFound"\n                  ? new IntegrationAttemptNotFoundError({\n                      integrationID: error.integrationID,\n                      attemptID: error.attemptID,\n                      message: "OAuth attempt not found",\n                    })\n                  : new InvalidRequestError({ message: "OAuth callback was rejected", kind: "integration_callback" }),\n              ),\n            )\n          return HttpApiSchema.NoContent.make()\n        }),\n      )\n      .handle(\n        "integration.oauth.handoff",\n        Effect.fn(function* (ctx) {\n          const service = yield* Integration.Service\n          if (!(yield* service.get(ctx.params.integrationID)))\n            return yield* new IntegrationNotFoundError({\n              integrationID: ctx.params.integrationID,\n              message: "Integration not found",\n            })\n          const value = yield* service.oauth\n            .handoff({ integrationID: ctx.params.integrationID, attemptID: ctx.params.attemptID })\n            .pipe(\n              Effect.mapError(\n                (error) =>\n                  new IntegrationAttemptNotFoundError({\n                    integrationID: error.integrationID,\n                    attemptID: error.attemptID,\n                    message: "OAuth handoff unavailable",\n                  }),\n              ),\n            )\n          return yield* response(Effect.succeed(value))\n        }),\n      )\n      .handle(\n        "integration.oauth.cancel",\n`,
    "oauth-private-route-handlers",
  )
}

export function transformOAuthCoreTest(source: string): string {
  source = replaceOnce(
    source,
    `import { Cause, Clock, Duration, Effect, Exit, Fiber, Layer, Scope, Stream } from "effect"\n`,
    `import { Cause, Clock, Deferred, Duration, Effect, Exit, Fiber, Layer, Scope, Stream } from "effect"\n`,
    "managed-oauth-core-test-deferred-import",
  )
  source = replaceOnce(
    source,
    `import { Integration } from "@opencode/core/integration"\n`,
    `import { Integration } from "@opencode/core/integration"\nimport { parseOAuthCallbackURL } from "../src/integration/oauth-callback.js"\n`,
    "managed-oauth-test-helper-import",
  )
  const managedTest = `
  it.effect("managed browser OAuth relays one state-bound callback into a one-time handoff", () =>
    Effect.acquireUseRelease(
      Effect.sync(() => {
        const previous = process.env.OPENCODE_ASSISTANT_OAUTH_HANDOFF
        process.env.OPENCODE_ASSISTANT_OAUTH_HANDOFF = "1"
        return previous
      }),
      () =>
        Effect.gen(function* () {
          const integrations = yield* Integration.Service
          const credentials = yield* Credential.Service
          const integrationID = Integration.ID.make("openai")
          const methodID = Integration.MethodID.make("browser")
          const expectedState = "fixture-state"
          const redirect = "http://localhost:1455/auth/callback"
          const assistantOAuth = { attemptID: "a".repeat(32), capability: "b".repeat(32) }
          const code = yield* Deferred.make<string, Error>()
          let relayCalls = 0
          let receivedBroker: typeof assistantOAuth | undefined
          yield* integrations.transform((editor) =>
            editor.method.update({
              integrationID,
              method: { id: methodID, type: "oauth", label: "Browser" },
              authorize: (_answer, broker) => {
                receivedBroker = broker
                return Effect.succeed({
                  mode: "auto" as const,
                  url: "https://auth.openai.com/oauth/authorize?fixture=1",
                  instructions: "Complete sign-in in your browser.",
                  callback: Deferred.await(code).pipe(
                    Effect.map((value) =>
                      Credential.OAuth.make({
                        type: "oauth",
                        methodID,
                        access: "fixture-access",
                        refresh: "fixture-refresh",
                        expires: 123,
                        metadata: { callbackCode: value },
                      }),
                    ),
                  ),
                  relay: (callbackURL: string) =>
                    Effect.try({
                      try: () => parseOAuthCallbackURL(callbackURL, redirect, expectedState),
                      catch: (cause) => (cause instanceof Error ? cause : new Error("Callback rejected")),
                    }).pipe(
                      Effect.tap(() => Effect.sync(() => (relayCalls += 1))),
                      Effect.flatMap((parsed) =>
                        parsed.kind === "denied"
                          ? Deferred.fail(code, new Error("Authorization denied")).pipe(Effect.asVoid)
                          : Deferred.succeed(code, parsed.code).pipe(Effect.asVoid),
                      ),
                    ),
                })
              },
            }),
          )

          const attempt = yield* integrations.oauth.connect({ integrationID, methodID, assistantOAuth })
          expect(receivedBroker).toEqual(assistantOAuth)
          const mismatch = yield* integrations.oauth
            .callback({
              integrationID,
              attemptID: attempt.attemptID,
              callbackURL: "http://localhost:1455/auth/callback?code=wrong&state=other",
            })
            .pipe(Effect.flip)
          expect(mismatch).toBeInstanceOf(Integration.AuthorizationError)
          expect(relayCalls).toBe(0)

          yield* integrations.oauth.callback({
            integrationID,
            attemptID: attempt.attemptID,
            callbackURL: "http://localhost:1455/auth/callback?code=fixture-code&state=fixture-state",
          })
          expect(
            yield* eventually(
              integrations.oauth.status({ integrationID, attemptID: attempt.attemptID }),
              (status) => status.status === "complete",
            ),
          ).toEqual({ status: "complete", time: attempt.time })

          const credential = yield* integrations.oauth.handoff({ integrationID, attemptID: attempt.attemptID })
          expect(credential).toEqual(
            Credential.OAuth.make({
              type: "oauth",
              methodID,
              access: "fixture-access",
              refresh: "fixture-refresh",
              expires: 123,
              metadata: { callbackCode: "fixture-code" },
            }),
          )
          expect(relayCalls).toBe(1)
          expect(yield* credentials.list(integrationID)).toEqual([])
          expect(
            Exit.isFailure(
              yield* integrations.oauth
                .handoff({ integrationID, attemptID: attempt.attemptID })
                .pipe(Effect.exit),
            ),
          ).toBe(true)
          expect(
            Exit.isFailure(
              yield* integrations.oauth
                .callback({
                  integrationID,
                  attemptID: attempt.attemptID,
                  callbackURL: "http://localhost:1455/auth/callback?code=replay&state=fixture-state",
                })
                .pipe(Effect.exit),
            ),
          ).toBe(true)
          expect(relayCalls).toBe(1)
          expect(yield* credentials.list(integrationID)).toEqual([])
        }),
      (previous) =>
        Effect.sync(() => {
          if (previous === undefined) delete process.env.OPENCODE_ASSISTANT_OAUTH_HANDOFF
          else process.env.OPENCODE_ASSISTANT_OAUTH_HANDOFF = previous
        }),
    ),
  )

  it.effect("does not invoke a browser relay after its native attempt expires", () =>
    Effect.gen(function* () {
      const integrations = yield* Integration.Service
      const integrationID = Integration.ID.make("openai")
      const methodID = Integration.MethodID.make("expired-browser")
      let relayCalls = 0
      yield* integrations.transform((editor) =>
        editor.method.update({
          integrationID,
          method: { id: methodID, type: "oauth", label: "Browser" },
          authorize: () =>
            Effect.gen(function* () {
              const now = yield* Clock.currentTimeMillis
              return {
                mode: "auto" as const,
                url: "https://auth.openai.com/oauth/authorize?fixture=1",
                instructions: "Complete sign-in in your browser.",
                expiresAt: now + 100,
                callback: Effect.never,
                relay: () => Effect.sync(() => (relayCalls += 1)),
              }
            }),
        }),
      )
      const attempt = yield* integrations.oauth.connect({ integrationID, methodID })
      yield* TestClock.adjust(Duration.millis(101))
      expect((yield* integrations.oauth.status({ integrationID, attemptID: attempt.attemptID })).status).toBe("pending")
      const result = yield* integrations.oauth
        .callback({
          integrationID,
          attemptID: attempt.attemptID,
          callbackURL: "http://localhost:1455/auth/callback?code=late&state=fixture-state",
        })
        .pipe(Effect.exit)
      expect(Exit.isFailure(result)).toBe(true)
      expect(relayCalls).toBe(0)
    }),
  )

  it.effect("isolates concurrent managed OAuth broker contexts per native attempt", () =>
    Effect.acquireUseRelease(
      Effect.sync(() => {
        const previous = process.env.OPENCODE_ASSISTANT_OAUTH_HANDOFF
        process.env.OPENCODE_ASSISTANT_OAUTH_HANDOFF = "1"
        return previous
      }),
      () =>
        Effect.gen(function* () {
          const integrations = yield* Integration.Service
          const integrationID = Integration.ID.make("fixture-oauth-isolation")
          const cases = [
            {
              methodID: Integration.MethodID.make("first"),
              broker: { attemptID: "1".repeat(32), capability: "a".repeat(32) },
            },
            {
              methodID: Integration.MethodID.make("second"),
              broker: { attemptID: "2".repeat(32), capability: "b".repeat(32) },
            },
          ]
          const received = new Map<string, unknown>()
          yield* integrations.transform((editor) => {
            for (const item of cases) {
              editor.method.update({
                integrationID,
                method: { id: item.methodID, type: "oauth", label: item.methodID },
                authorize: (_answer, broker) => {
                  received.set(item.methodID, broker)
                  return Effect.succeed({
                    mode: "code" as const,
                    url: "https://auth.example.invalid/",
                    instructions: "Fixture only.",
                    callback: () => Effect.never,
                  })
                },
              })
            }
          })

          const attempts = yield* Effect.all(
            cases.map((item) =>
              integrations.oauth.connect({
                integrationID,
                methodID: item.methodID,
                assistantOAuth: item.broker,
              }),
            ),
            { concurrency: 2 },
          )
          expect(received.get(cases[0].methodID)).toEqual(cases[0].broker)
          expect(received.get(cases[1].methodID)).toEqual(cases[1].broker)
          expect(received.get(cases[0].methodID)).not.toEqual(cases[1].broker)
          yield* Effect.forEach(attempts, (attempt) =>
            integrations.oauth.cancel({ integrationID, attemptID: attempt.attemptID }),
          )
        }),
      (previous) =>
        Effect.sync(() => {
          if (previous === undefined) delete process.env.OPENCODE_ASSISTANT_OAUTH_HANDOFF
          else process.env.OPENCODE_ASSISTANT_OAUTH_HANDOFF = previous
        }),
    ),
  )

  it.effect("rejects managed OAuth without an app broker before provider authorization", () =>
    Effect.acquireUseRelease(
      Effect.sync(() => {
        const previous = process.env.OPENCODE_ASSISTANT_OAUTH_HANDOFF
        process.env.OPENCODE_ASSISTANT_OAUTH_HANDOFF = "1"
        return previous
      }),
      () =>
        Effect.gen(function* () {
          const integrations = yield* Integration.Service
          const integrationID = Integration.ID.make("fixture-oauth-managed-required")
          const methodID = Integration.MethodID.make("browser")
          let authorizeCalls = 0
          yield* integrations.transform((editor) =>
            editor.method.update({
              integrationID,
              method: { id: methodID, type: "oauth", label: "Browser" },
              authorize: () => {
                authorizeCalls += 1
                return Effect.die(new Error("must not start without broker"))
              },
            }),
          )
          const result = yield* integrations.oauth.connect({ integrationID, methodID }).pipe(Effect.exit)
          expect(Exit.isFailure(result)).toBe(true)
          expect(authorizeCalls).toBe(0)
        }),
      (previous) =>
        Effect.sync(() => {
          if (previous === undefined) delete process.env.OPENCODE_ASSISTANT_OAUTH_HANDOFF
          else process.env.OPENCODE_ASSISTANT_OAUTH_HANDOFF = previous
        }),
    ),
  )
`
  return replaceOnce(
    source,
    `\n})\n\ndescribe("AuthorizationError", () => {`,
    `${managedTest}\n})\n\ndescribe("AuthorizationError", () => {`,
    "managed-oauth-core-tests",
  )
}

function digest(source: string): string {
  return createHash("sha256").update(source, "utf8").digest("hex")
}

/** Apply only to the exact pinned V2.0.7 source tree. */
export async function applyOAuthHandoffPatch(sourceRoot: string): Promise<Record<string, string>> {
  const files = {} as SourceMap
  for (const relative of Object.keys(OAUTH_SOURCE_HASHES) as SourcePath[]) {
    const source = await readFile(join(sourceRoot, relative), "utf8")
    if (digest(source) !== OAUTH_SOURCE_HASHES[relative]) {
      throw new Error(`Pinned OAuth source digest mismatch: ${relative}`)
    }
    files[relative] = source
  }

  const transformed: SourceMap = {
    "packages/core/src/integration.ts": transformOAuthCore(files["packages/core/src/integration.ts"]),
    "packages/core/src/plugin/provider/openai.ts": transformOAuthProvider(
      files["packages/core/src/plugin/provider/openai.ts"],
    ),
    "packages/core/src/plugin/provider/opencode.ts": transformOAuthOpencode(
      files["packages/core/src/plugin/provider/opencode.ts"],
    ),
    "packages/core/src/plugin/host.ts": transformOAuthPluginHost(files["packages/core/src/plugin/host.ts"]),
    "packages/plugin/src/effect/integration.ts": transformOAuthPluginRegistration(
      files["packages/plugin/src/effect/integration.ts"],
    ),
    "packages/core/test/plugin/provider-opencode.test.ts": transformOAuthOpencodeTest(
      files["packages/core/test/plugin/provider-opencode.test.ts"],
    ),
    "packages/core/test/plugin/provider-openai.test.ts": transformOAuthOpenAITest(
      files["packages/core/test/plugin/provider-openai.test.ts"],
    ),
    "packages/protocol/src/groups/integration.ts": transformOAuthProtocol(
      files["packages/protocol/src/groups/integration.ts"],
    ),
    "packages/schema/src/credential.ts": files["packages/schema/src/credential.ts"],
    "packages/server/src/handlers/integration.ts": transformOAuthHandler(
      files["packages/server/src/handlers/integration.ts"],
    ),
    "packages/core/test/integration.test.ts": transformOAuthCoreTest(
      files["packages/core/test/integration.test.ts"],
    ),
  }

  for (const [relative, source] of Object.entries(transformed) as [SourcePath, string][]) {
    await writeFile(join(sourceRoot, relative), source, "utf8")
  }
  const helperPath = join(sourceRoot, "packages/core/src/integration/oauth-callback.ts")
  await mkdir(dirname(helperPath), { recursive: true })
  await writeFile(helperPath, await readFile(new URL("./oauth-callback.ts", import.meta.url), "utf8"), "utf8")
  await writeFile(
    join(sourceRoot, "packages/core/src/integration/oauth-broker.ts"),
    await readFile(new URL("./oauth-broker.ts", import.meta.url), "utf8"),
    "utf8",
  )

  return Object.fromEntries(Object.entries(transformed).map(([relative, source]) => [relative, digest(source)]))
}
