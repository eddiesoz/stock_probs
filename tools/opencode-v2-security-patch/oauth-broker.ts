export type NativeOAuthBroker = {
  readonly attemptID: string
  readonly capability: string
}

export type NativeOAuthOperation =
  | "openai.device_start"
  | "openai.device_poll"
  | "openai.token_exchange"
  | "opencode.device_start"
  | "opencode.device_poll"
  | "opencode.user"
  | "opencode.orgs"

type OperationInputs = {
  "openai.device_start": Record<string, never>
  "openai.device_poll": { readonly device_auth_id: string; readonly user_code: string }
  "openai.token_exchange": {
    readonly code: string
    readonly redirect_uri: string
    readonly code_verifier: string
  }
  "opencode.device_start": Record<string, never>
  "opencode.device_poll": { readonly device_code: string }
  "opencode.user": { readonly access_token: string }
  "opencode.orgs": { readonly access_token: string }
}

export type NativeOAuthInput<Operation extends NativeOAuthOperation> = OperationInputs[Operation]

export type OpenCodeDeviceLaunch = {
  readonly deviceCode: string
  readonly userCode: string
  readonly url: string
  readonly expiresIn: number
  readonly interval: number
}

const OPENCODE_DEVICE_ORIGIN = "https://opencode.ai"
const OPENCODE_DEVICE_PATH = "/console/device"

/** Validate the native device response before exposing a link or polling with its code. */
export function validateOpenCodeDeviceLaunch(value: unknown): OpenCodeDeviceLaunch {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error("invalid device response")
  const device = value as Record<string, unknown>
  const expectedKeys = ["device_code", "user_code", "verification_uri_complete", "expires_in", "interval"]
  if (Object.keys(device).length !== expectedKeys.length || expectedKeys.some((key) => !(key in device))) {
    throw new Error("invalid device response")
  }
  if (
    typeof device.device_code !== "string" ||
    device.device_code.length < 1 ||
    device.device_code.length > 4096 ||
    /[\u0000-\u001f\u007f]/.test(device.device_code) ||
    typeof device.user_code !== "string" ||
    !/^[A-Za-z0-9-]{1,64}$/.test(device.user_code) ||
    typeof device.verification_uri_complete !== "string" ||
    device.verification_uri_complete.length > 8192 ||
    typeof device.expires_in !== "number" ||
    !Number.isFinite(device.expires_in) ||
    device.expires_in < 1 ||
    device.expires_in > 600 ||
    typeof device.interval !== "number" ||
    !Number.isFinite(device.interval) ||
    device.interval < 0 ||
    device.interval > 60
  ) {
    throw new Error("invalid device response")
  }

  let url: URL
  try {
    url = new URL(device.verification_uri_complete, `${OPENCODE_DEVICE_ORIGIN}/console/`)
  } catch {
    throw new Error("invalid verification URL")
  }
  const keys = [...url.searchParams.keys()]
  const userCodes = url.searchParams.getAll("user_code")
  const clientIDs = url.searchParams.getAll("client_id")
  if (
    url.origin !== OPENCODE_DEVICE_ORIGIN ||
    url.pathname !== OPENCODE_DEVICE_PATH ||
    url.username !== "" ||
    url.password !== "" ||
    url.hash !== "" ||
    url.port !== "" ||
    keys.length !== 2 ||
    keys.some((key) => key !== "user_code" && key !== "client_id") ||
    userCodes.length !== 1 ||
    userCodes[0] !== device.user_code ||
    clientIDs.length !== 1 ||
    clientIDs[0] !== "opencode-cli"
  ) {
    throw new Error("verification URL is outside the fixed OpenCode device flow")
  }

  return {
    deviceCode: device.device_code,
    userCode: device.user_code,
    url: url.href,
    expiresIn: device.expires_in,
    interval: Math.max(1, device.interval),
  }
}

const BROKER_URL = "http://127.0.0.1:8000/api/v1/assistant/internal/oauth"
const MAX_REQUEST_BYTES = 16 * 1024
const MAX_RESPONSE_BYTES = 64 * 1024
const REQUEST_TIMEOUT_MS = 8_000
const OPERATIONS = new Set<NativeOAuthOperation>([
  "openai.device_start",
  "openai.device_poll",
  "openai.token_exchange",
  "opencode.device_start",
  "opencode.device_poll",
  "opencode.user",
  "opencode.orgs",
])

/** Fixed loopback-only OAuth egress bridge. The app validates the same attempt capability. */
export async function requestNativeOAuth<Operation extends NativeOAuthOperation>(
  broker: NativeOAuthBroker,
  operation: Operation,
  input: NativeOAuthInput<Operation>,
  signal: AbortSignal,
): Promise<unknown> {
  try {
      if (
        !/^[0-9a-f]{32}$/.test(broker.attemptID) ||
        !/^[0-9a-f]{32}$/.test(broker.capability) ||
        !OPERATIONS.has(operation)
      ) {
        throw new Error("invalid broker request")
      }
      const body = JSON.stringify({ attempt_id: broker.attemptID, operation, input })
      if (new TextEncoder().encode(body).byteLength > MAX_REQUEST_BYTES) throw new Error("broker request too large")
      const response = await fetch(BROKER_URL, {
        method: "POST",
        redirect: "error",
        cache: "no-store",
        credentials: "omit",
        headers: {
          Accept: "application/json",
          Authorization: `Bearer ${broker.capability}`,
          "Content-Type": "application/json",
        },
        body,
        signal: AbortSignal.any([signal, AbortSignal.timeout(REQUEST_TIMEOUT_MS)]),
      })
      if (
        response.status !== 200 ||
        response.headers.get("content-type")?.split(";", 1)[0].trim().toLowerCase() !== "application/json"
      ) {
        await response.body?.cancel().catch(() => undefined)
        throw new Error("broker response rejected")
      }
      const reader = response.body?.getReader()
      if (!reader) throw new Error("broker response missing")
      const chunks: Uint8Array[] = []
      let total = 0
      let completed = false
      try {
        while (true) {
          const item = await reader.read()
          if (item.done) {
            completed = true
            break
          }
          total += item.value.byteLength
          if (total > MAX_RESPONSE_BYTES) throw new Error("broker response too large")
          chunks.push(item.value)
        }
      } finally {
        if (!completed) await reader.cancel().catch(() => undefined)
        reader.releaseLock()
      }
      const bytes = new Uint8Array(total)
      let offset = 0
      for (const chunk of chunks) {
        bytes.set(chunk, offset)
        offset += chunk.byteLength
      }
      const parsed: unknown = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(bytes))
      if (
        !parsed ||
        typeof parsed !== "object" ||
        Array.isArray(parsed) ||
        Object.keys(parsed).length !== 1 ||
        !("result" in parsed)
      ) {
        throw new Error("broker response shape rejected")
      }
      return parsed.result
  } catch {
    throw new Error("OAuth broker request failed")
  }
}
