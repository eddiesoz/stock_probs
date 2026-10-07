import { afterAll, beforeEach, describe, expect, mock } from "bun:test"
import { Effect, Fiber, Layer } from "effect"
import { Permission } from "@opencode/core/permission"
import { Session } from "@opencode/core/session"
import { Tool } from "@opencode/core/tool"
import { AppNodeBuilder } from "@opencode/core/effect/app-node-builder"
import { LayerNode } from "@opencode/util/effect/layer-node"
import { permissionLayer } from "./lib/permission"
import { executeTool, registerToolPlugin, toolIdentity } from "./lib/tool"
import { testEffect } from "./lib/effect"
import { Image } from "@opencode/core/image"
import { imagePassthrough } from "./lib/image"
import { makeLocationNode } from "@opencode/util/effect/app-node"

const guard = await import("../src/tool/plugin/webfetch-guard-test-copy.js")
type GuardDependencies = Parameters<typeof guard.fetchPublicURL>[4]
type GuardResponse = Awaited<ReturnType<typeof guard.fetchPublicURL>> extends never ? never : {
  status: number
  contentType: string
  body: Buffer
  headers: Record<string, string>
}

const publicAddress = { address: "93.184.216.34", family: 4 as const }
let addresses = [publicAddress]
let responder: (url: URL, signal: AbortSignal) => Promise<GuardResponse>
let requests: Array<{ url: string; headers: Record<string, string>; address: string }> = []
let assertions: Array<Record<string, unknown>> = []

const dependencies: GuardDependencies = {
  resolve: async () => addresses,
  request: async (url, headers, address, _maximumBytes, signal) => {
    requests.push({ url: url.toString(), headers, address: address.address })
    return responder(url, signal)
  },
}

mock.module("../src/tool/plugin/webfetch-guard.js", () => ({
  fetchPublicURL: (
    input: string,
    headers: Record<string, string>,
    maximumBytes: number,
    signal: AbortSignal,
    _dependencies?: GuardDependencies,
    timeoutMs?: number,
  ) => guard.fetchPublicURL(input, headers, maximumBytes, signal, dependencies, timeoutMs),
}))

const { WebFetchTool } = await import("@opencode/core/tool/plugin/webfetch")
const sessionID = Session.ID.make("ses_webfetch_guard_integration")
const pluginNode = makeLocationNode({
  name: "test/guarded-webfetch-tool",
  layer: Layer.effectDiscard(registerToolPlugin(WebFetchTool.Plugin)),
  deps: [Tool.node, Permission.node],
})

const permission = permissionLayer({ assert: (input) => Effect.sync(() => assertions.push(input as never)) })
const toolLayer = AppNodeBuilder.build(LayerNode.group([Tool.node, pluginNode]), [
  Permission.node.replace(permission),
  Image.node.replace(imagePassthrough),
])
const it = testEffect(toolLayer)
const registry = () => Effect.gen(function* () {
  const tools = yield* Tool.Service
  const available = yield* tools.snapshot()
  return { tools, available }
})

const call = (url: string, timeout?: number, id = "call-guarded-webfetch") => ({
  sessionID,
  ...toolIdentity,
  call: { type: "tool-call" as const, id, name: "webfetch", input: { url, format: "text", ...(timeout ? { timeout } : {}) } },
})

function resultText(value: unknown, visited = new Set<object>()): string {
  if (typeof value === "string") return value
  if (value instanceof Error) return value.message
  if (value === null || typeof value !== "object" || visited.has(value)) return ""
  visited.add(value)
  const values = Object.getOwnPropertyNames(value).map((key) => {
    try {
      return resultText(Reflect.get(value, key), visited)
    } catch {
      return ""
    }
  })
  return values.join(" ")
}

const response = (status = 200, contentType = "text/plain", body = "guarded text", headers: Record<string, string> = {}) => ({
  status,
  contentType,
  body: Buffer.from(body),
  headers,
})

describe("pinned native WebFetchTool guarded transport integration", () => {
  beforeEach(() => {
    addresses = [publicAddress]
    responder = async () => response()
    requests = []
    assertions = []
  })

  afterAll(() => mock.restore())

  it.effect("executes the registered native tool through the pinned transport after permission", () =>
    Effect.gen(function* () {
      const { tools } = yield* registry()
      const url = "https://example.com/research"
      const result = yield* executeTool(tools, call(url))

      expect(result.status).toBe("completed")
      expect(result.content).toEqual([{ type: "text", text: "guarded text" }])
      expect(result.metadata).toMatchObject({ finalUrl: url })
      expect(assertions).toMatchObject([{ action: "webfetch", resources: [url], sessionID }])
      expect(requests).toMatchObject([{ url, address: publicAddress.address }])
      expect(requests[0]?.headers.authorization).toBeUndefined()
      expect(requests[0]?.headers.host).toBeUndefined()
    }),
  )

  it.effect("denies private DNS answers in the real native tool path before connecting", () =>
    Effect.gen(function* () {
      addresses = [{ address: "127.0.0.1", family: 4 }]
      const { tools } = yield* registry()
      const result = yield* executeTool(tools, call("https://example.com/private"))

      expect(result.status).toBe("error")
      expect(requests).toEqual([])
      expect(assertions).toHaveLength(1)
    }),
  )

  it.effect("blocks an unapproved redirect before the native tool requests its destination", () =>
    Effect.gen(function* () {
      const { tools } = yield* registry()
      responder = async (_url, _signal) => requests.length === 1
        ? response(302, "", "", { location: "https://redirect.example.com/target" })
        : response(200, "text/plain", "redirected safely")
      const url = "https://example.com/start"
      const result = yield* executeTool(tools, call(url))

      expect(result.status).toBe("error")
      expect(requests.map((item) => item.url)).toEqual([url])
      expect(assertions).toMatchObject([{ resources: [url] }])
      expect(resultText(result)).toContain(
        "REDIRECT_APPROVAL_REQUIRED https://redirect.example.com/target",
      )
    }),
  )

  it.effect("retries same-host path/query and cross-host redirect hints as fresh exact fetches", () =>
    Effect.gen(function* () {
      const { tools } = yield* registry()
      const scenarios = [
        {
          source: "https://example.com/start?view=old",
          target: "https://example.com/article?view=new",
        },
        {
          source: "https://example.com/start",
          target: "https://redirect.example.com/article?view=public",
        },
      ]
      for (const [index, { source, target }] of scenarios.entries()) {
        requests = []
        assertions = []
        responder = async (url) => url.toString() === source
          ? response(302, "", "", { location: target })
          : response(200, "text/plain", "approved redirected page")

        const first = yield* executeTool(tools, call(source, undefined, `call-source-${index}`))
        expect(first.status).toBe("error")
        expect(resultText(first)).toContain(`REDIRECT_APPROVAL_REQUIRED ${target}`)
        expect(requests.map((item) => item.url)).toEqual([source])
        expect(assertions).toMatchObject([
          { action: "webfetch", resources: [source], sessionID },
        ])

        const second = yield* executeTool(
          tools,
          call(target, undefined, `call-redirected-${index}`),
        )
        expect(second.status).toBe("completed")
        expect(second.content).toEqual([{ type: "text", text: "approved redirected page" }])
        expect(second.metadata).toMatchObject({ finalUrl: target })
        expect(assertions).toMatchObject([
          { action: "webfetch", resources: [source], sessionID },
          { action: "webfetch", resources: [target], sessionID },
        ])
        expect(requests.map((item) => item.url)).toEqual([source, target])
      }
    }),
  )

  it.effect("rejects a private redirect before the native transport connects to it", () =>
    Effect.gen(function* () {
      const { tools } = yield* registry()
      responder = async () => response(302, "", "", { location: "http://127.0.0.1/private" })
      const url = "https://example.com/start"
      const result = yield* executeTool(tools, call(url))

      expect(result.status).toBe("error")
      expect(requests.map((item) => item.url)).toEqual([url])
      expect(assertions).toMatchObject([{ resources: [url] }])
    }),
  )

  it.effect("caps response bytes when the actual native tool calls the guard", () =>
    Effect.gen(function* () {
      const { tools } = yield* registry()
      responder = async () => response(200, "text/plain", "x".repeat(WebFetchTool.MAX_RESPONSE_BYTES + 1))
      const result = yield* executeTool(tools, call("https://example.com/large"))

      expect(result.status).toBe("error")
      expect(requests).toHaveLength(1)
    }),
  )

  it.effect("propagates deadline cancellation from the native tool to an in-flight request", () =>
    Effect.gen(function* () {
      const { tools } = yield* registry()
      let started!: () => void
      const requestStarted = new Promise<void>((resolve) => { started = resolve })
      let aborted = false
      responder = (_url, signal) => new Promise((_resolve, reject) => {
        started()
        signal.addEventListener("abort", () => {
          aborted = true
          reject(new Error("aborted"))
        }, { once: true })
      })
      const result = yield* executeTool(tools, call("https://example.com/slow", 0.02))

      expect(result.status).toBe("error")
      yield* Effect.promise(() => requestStarted)
      expect(aborted).toBe(true)
    }),
  )

  it.effect("propagates native execution interruption to an in-flight request", () =>
    Effect.gen(function* () {
      const { tools } = yield* registry()
      let started!: () => void
      const requestStarted = new Promise<void>((resolve) => { started = resolve })
      let aborted = false
      responder = (_url, signal) => new Promise((_resolve, reject) => {
        started()
        signal.addEventListener("abort", () => {
          aborted = true
          reject(new Error("aborted"))
        }, { once: true })
      })
      const fiber = yield* executeTool(tools, call("https://example.com/cancel")).pipe(
        Effect.forkChild({ startImmediately: true }),
      )
      yield* Effect.promise(() => requestStarted)
      yield* Fiber.interrupt(fiber)

      expect(aborted).toBe(true)
    }),
  )
})
