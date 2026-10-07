import { Resolver } from "node:dns"
import { request as httpRequest, type IncomingHttpHeaders } from "node:http"
import { request as httpsRequest } from "node:https"
import { isIP } from "node:net"

export const MAX_REDIRECTS = 5
export const DNS_TIMEOUT_MS = 2_000
export const MAX_FETCH_TIMEOUT_MS = 120_000
const REQUEST_IDLE_TIMEOUT_MS = 10_000
const MAX_URL_LENGTH = 4_096
const MAX_APPROVED_PREVIEW_URL_BYTES = 2_048
const allowedHeaderNames = new Set(["accept", "accept-language", "user-agent"])
const secretishQueryKey =
  /^(?:access[_-]?token|api[_-]?key|auth(?:orization)?|bearer|code|credential|jwt|key|password|secret|session|signature|token)$/i
const invalidPercentEscape = /%(?![0-9a-f]{2})/i
const blockedRedirectHintSuffixes = [
  ".localhost",
  ".local",
  ".internal",
  ".lan",
  ".home",
  ".home.arpa",
  ".test",
  ".example",
  ".invalid",
  ".onion",
] as const

export type ResolvedAddress = { address: string; family: 4 | 6 }
export type FetchResponse = {
  status: number
  headers: IncomingHttpHeaders
  body: Buffer
}
export type GuardedFetchResult = {
  finalUrl: string
  status: number
  headers: IncomingHttpHeaders
  contentType: string
  body: Buffer
}

export type FetchDependencies = {
  resolve: (hostname: string, signal: AbortSignal) => Promise<ResolvedAddress[]>
  request: (
    url: URL,
    headers: Record<string, string>,
    address: ResolvedAddress,
    maximumBytes: number,
    signal: AbortSignal,
  ) => Promise<FetchResponse>
}
export type RedirectApproval = (
  destination: string,
  signal: AbortSignal,
) => Promise<string | null | undefined>

const deniedIPv4Ranges: ReadonlyArray<readonly [number, number]> = [
  [0x00000000, 0x00ffffff], // This network.
  [0x0a000000, 0x0affffff], // Private use.
  [0x64400000, 0x647fffff], // Shared address space.
  [0x7f000000, 0x7fffffff], // Loopback.
  [0xa9fe0000, 0xa9feffff], // Link local.
  [0xac100000, 0xac1fffff], // Private use.
  [0xc0000000, 0xc00000ff], // IETF protocol assignments.
  [0xc0000200, 0xc00002ff], // Documentation.
  [0xc0586300, 0xc05863ff], // Deprecated 6to4 relay anycast.
  [0xc0a80000, 0xc0a8ffff], // Private use.
  [0xc6120000, 0xc613ffff], // Benchmarking.
  [0xc6336400, 0xc63364ff], // Documentation.
  [0xcb007100, 0xcb0071ff], // Documentation.
  [0xe0000000, 0xffffffff], // Multicast and reserved.
]

function ipv4Value(address: string): number | undefined {
  if (isIP(address) !== 4) return undefined
  const parts = address.split(".").map(Number)
  if (parts.length !== 4 || parts.some((part) => !Number.isInteger(part) || part < 0 || part > 255))
    return undefined
  return parts.reduce((value, part) => value * 256 + part, 0)
}

function ipv6Value(address: string): bigint | undefined {
  if (isIP(address) !== 6 || address.includes("%")) return undefined
  let text = address.toLowerCase()
  if (text.includes(".")) {
    const lastColon = text.lastIndexOf(":")
    const ipv4 = ipv4Value(text.slice(lastColon + 1))
    if (lastColon < 0 || ipv4 === undefined) return undefined
    const high = Math.floor(ipv4 / 65_536).toString(16)
    const low = (ipv4 % 65_536).toString(16)
    text = `${text.slice(0, lastColon + 1)}${high}:${low}`
  }

  const sections = text.split("::")
  if (sections.length > 2) return undefined
  const left = sections[0] ? sections[0].split(":") : []
  const right = sections.length === 2 && sections[1] ? sections[1].split(":") : []
  const missing = 8 - left.length - right.length
  if ((sections.length === 1 && missing !== 0) || (sections.length === 2 && missing < 1)) return undefined
  const groups = [...left, ...Array(Math.max(0, missing)).fill("0"), ...right]
  if (groups.length !== 8 || groups.some((group) => !/^[0-9a-f]{1,4}$/.test(group))) return undefined
  return groups.reduce((value, group) => (value << 16n) | BigInt(`0x${group}`), 0n)
}

function inIPv6Prefix(address: bigint, prefix: bigint, bits: number): boolean {
  const shift = BigInt(128 - bits)
  return address >> shift === prefix >> shift
}

export function isPublicAddress(address: string): boolean {
  const ipv4 = ipv4Value(address)
  if (ipv4 !== undefined) return !deniedIPv4Ranges.some(([first, last]) => ipv4 >= first && ipv4 <= last)

  const ipv6 = ipv6Value(address)
  if (ipv6 === undefined) return false
  const globalUnicast = inIPv6Prefix(ipv6, 0x20000000000000000000000000000000n, 3)
  const specialProtocol = inIPv6Prefix(ipv6, 0x20010000000000000000000000000000n, 23)
  const documentation = inIPv6Prefix(ipv6, 0x20010db8000000000000000000000000n, 32)
  const sixToFour = inIPv6Prefix(ipv6, 0x20020000000000000000000000000000n, 16)
  const documentationV2 = inIPv6Prefix(ipv6, 0x3fff0000000000000000000000000000n, 20)
  return globalUnicast && !specialProtocol && !documentation && !sixToFour && !documentationV2
}

export function validateFetchURL(input: string): URL {
  if (input.length === 0 || input.length > MAX_URL_LENGTH || /[\u0000-\u0020\u007f]/.test(input))
    throw new Error("Invalid URL")
  let url: URL
  try {
    url = new URL(input)
  } catch {
    throw new Error("Invalid URL")
  }
  if (url.protocol !== "http:" && url.protocol !== "https:") throw new Error("URL must use http:// or https://")
  if (url.username || url.password || !url.hostname || url.port) throw new Error("URL is not a public web destination")
  const host = url.hostname.replace(/^\[|\]$/g, "")
  if (isIP(host) !== 0 && !isPublicAddress(host)) throw new Error("URL is not a public web destination")
  if (
    isIP(host) === 0 &&
    (!host.includes(".") ||
      host.endsWith(".") ||
      [".localhost", ".local", ".internal", ".home.arpa", ".test", ".example", ".invalid", ".onion"].some(
        (suffix) => host.endsWith(suffix),
      ))
  )
    throw new Error("URL is not a public web destination")
  return url
}

function validateHeaders(headers: Record<string, string>): Record<string, string> {
  const result: Record<string, string> = {}
  for (const [rawName, value] of Object.entries(headers)) {
    const name = rawName.toLowerCase()
    if (
      !allowedHeaderNames.has(name) ||
      Object.hasOwn(result, name) ||
      typeof value !== "string" ||
      value.length > 2_048 ||
      /[\u0000-\u001f\u007f]/.test(value)
    )
      throw new Error("Unsupported request header")
    result[name] = value
  }
  return result
}

function hasSecretishQueryKey(query: string): boolean {
  if (!query) return false
  const fields = query.replace(/;/g, "&").split("&")
  if (fields.length > 64) return true
  for (const field of fields) {
    const rawKey = field.split("=", 1)[0] ?? ""
    if (invalidPercentEscape.test(rawKey)) return true
    let key: string
    try {
      key = decodeURIComponent(rawKey.replace(/\+/g, " "))
    } catch {
      return true
    }
    if (key.includes("%") || /[\u0000-\u001f\u007f]/.test(key) || secretishQueryKey.test(key))
      return true
  }
  return false
}

function redirectRetryError(destination: URL): Error {
  const exactURL = destination.toString()
  const hostname = destination.hostname.replace(/^\[|\]$/g, "").toLowerCase()
  const safeHost =
    hostname.includes(".") &&
    !hostname.endsWith(".") &&
    !blockedRedirectHintSuffixes.some((suffix) => hostname.endsWith(suffix))
  if (
    destination.protocol === "https:" &&
    !destination.username &&
    !destination.password &&
    !destination.port &&
    safeHost &&
    !destination.hash &&
    !exactURL.includes("#") &&
    !hasSecretishQueryKey(destination.search.slice(1)) &&
    Buffer.byteLength(exactURL, "utf8") <= MAX_APPROVED_PREVIEW_URL_BYTES
  ) {
    return new Error(`Redirect blocked before contact. REDIRECT_APPROVAL_REQUIRED ${exactURL}`)
  }
  return new Error("Redirect blocked before contact; destination needs a safe exact URL preview.")
}

function dnsQuery(resolver: Resolver, family: 4 | 6, hostname: string): Promise<string[]> {
  return new Promise((resolve, reject) => {
    const callback = (error: NodeJS.ErrnoException | null, addresses: string[]) => {
      if (error) reject(error)
      else resolve(addresses)
    }
    if (family === 4) resolver.resolve4(hostname, callback)
    else resolver.resolve6(hostname, callback)
  })
}

export async function resolvePublicAddresses(hostname: string, signal: AbortSignal): Promise<ResolvedAddress[]> {
  const normalizedHost = hostname.replace(/^\[|\]$/g, "")
  const literalFamily = isIP(normalizedHost)
  if (literalFamily) {
    if (!isPublicAddress(normalizedHost)) throw new Error("Destination address is not public")
    return [{ address: normalizedHost, family: literalFamily as 4 | 6 }]
  }
  if (signal.aborted) throw new Error("Request aborted")

  const resolver = new Resolver()
  let timedOut = false
  const cancel = () => resolver.cancel()
  const timer = setTimeout(() => {
    timedOut = true
    resolver.cancel()
  }, DNS_TIMEOUT_MS)
  timer.unref?.()
  signal.addEventListener("abort", cancel, { once: true })
  try {
    const results = await Promise.allSettled([
      dnsQuery(resolver, 4, normalizedHost),
      dnsQuery(resolver, 6, normalizedHost),
    ])
    if (signal.aborted) throw new Error("Request aborted")
    if (timedOut) throw new Error("DNS lookup timed out")

    const addresses: ResolvedAddress[] = []
    for (const [index, result] of results.entries()) {
      if (result.status === "fulfilled") {
        addresses.push(
          ...result.value.map((address) => ({ address, family: index === 0 ? 4 : 6 }) as ResolvedAddress),
        )
        continue
      }
      const code = (result.reason as NodeJS.ErrnoException | undefined)?.code
      if (code !== "ENODATA" && code !== "ENOTFOUND") throw new Error("DNS lookup failed")
    }
    if (addresses.length === 0 || addresses.some(({ address }) => !isPublicAddress(address)))
      throw new Error("Destination address is not public")
    return addresses
  } finally {
    clearTimeout(timer)
    signal.removeEventListener("abort", cancel)
  }
}

function pinnedLookup(expectedHost: string, selected: ResolvedAddress) {
  return (hostname: string, options: { all?: boolean }, callback: (...args: any[]) => void) => {
    if (hostname.toLowerCase() !== expectedHost.toLowerCase()) {
      callback(new Error("Unexpected connection hostname"))
      return
    }
    if (options?.all) callback(null, [{ address: selected.address, family: selected.family }])
    else callback(null, selected.address, selected.family)
  }
}

function requestOnce(
  url: URL,
  headers: Record<string, string>,
  address: ResolvedAddress,
  maximumBytes: number,
  signal: AbortSignal,
): Promise<FetchResponse> {
  return new Promise((resolve, reject) => {
    if (signal.aborted) {
      reject(new Error("Request aborted"))
      return
    }
    const hostname = url.hostname.replace(/^\[|\]$/g, "")
    const options = {
      agent: false,
      method: "GET",
      headers: { ...headers, host: url.host, "accept-encoding": "identity" },
      lookup: pinnedLookup(hostname, address),
      ...(url.protocol === "https:" && isIP(hostname) === 0 ? { servername: hostname } : {}),
    }
    const send = url.protocol === "https:" ? httpsRequest : httpRequest
    const request = send(url, options, (response) => {
      const status = response.statusCode ?? 0
      const contentLength = response.headers["content-length"]
      const declaredLength = typeof contentLength === "string" ? Number(contentLength) : undefined
      if (declaredLength !== undefined && Number.isSafeInteger(declaredLength) && declaredLength > maximumBytes) {
        response.destroy()
        request.destroy()
        reject(new Error("Response exceeds byte limit"))
        return
      }
      const encoding = response.headers["content-encoding"]
      if (typeof encoding === "string" && encoding.toLowerCase() !== "identity") {
        response.destroy()
        request.destroy()
        reject(new Error("Unsupported response encoding"))
        return
      }
      if ([301, 302, 303, 307, 308].includes(status)) {
        response.destroy()
        resolve({ status, headers: response.headers, body: Buffer.alloc(0) })
        return
      }

      const chunks: Buffer[] = []
      let size = 0
      response.on("data", (chunk: Buffer | string) => {
        const bytes = Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk)
        size += bytes.byteLength
        if (size > maximumBytes) {
          response.destroy(new Error("Response exceeds byte limit"))
          request.destroy()
          return
        }
        chunks.push(bytes)
      })
      response.once("end", () => resolve({ status, headers: response.headers, body: Buffer.concat(chunks, size) }))
      response.once("error", reject)
    })
    const abort = () => request.destroy(new Error("Request aborted"))
    const fail = (error: Error) => {
      signal.removeEventListener("abort", abort)
      reject(error)
    }
    signal.addEventListener("abort", abort, { once: true })
    request.setTimeout(REQUEST_IDLE_TIMEOUT_MS, () => request.destroy(new Error("Request timed out")))
    request.once("error", fail)
    request.once("close", () => signal.removeEventListener("abort", abort))
    request.end()
  })
}

const defaultDependencies: FetchDependencies = {
  resolve: resolvePublicAddresses,
  request: requestOnce,
}

async function resolveDestination(
  url: URL,
  signal: AbortSignal,
  dependencies: FetchDependencies,
): Promise<ResolvedAddress[]> {
  const hostname = url.hostname.replace(/^\[|\]$/g, "")
  const family = isIP(hostname)
  if (family) {
    if (!isPublicAddress(hostname)) throw new Error("Destination address is not public")
    return [{ address: hostname, family: family as 4 | 6 }]
  }
  const addresses = await dependencies.resolve(hostname, signal)
  if (addresses.length === 0 || addresses.some(({ address }) => !isPublicAddress(address)))
    throw new Error("Destination address is not public")
  return addresses
}

function awaitWithAbort<T>(promise: Promise<T>, signal: AbortSignal): Promise<T> {
  return new Promise((resolve, reject) => {
    if (signal.aborted) {
      reject(new Error("Request aborted"))
      return
    }
    const cleanup = () => signal.removeEventListener("abort", abort)
    const abort = () => {
      cleanup()
      reject(new Error("Request aborted"))
    }
    signal.addEventListener("abort", abort, { once: true })
    promise.then(
      (value) => {
        cleanup()
        resolve(value)
      },
      (error: unknown) => {
        cleanup()
        reject(error)
      },
    )
  })
}

export async function fetchPublicURL(
  input: string,
  headers: Record<string, string>,
  maximumBytes: number,
  signal: AbortSignal,
  dependencies: FetchDependencies = defaultDependencies,
  timeoutMs = MAX_FETCH_TIMEOUT_MS,
  approveRedirect?: RedirectApproval,
): Promise<GuardedFetchResult> {
  if (!Number.isSafeInteger(maximumBytes) || maximumBytes < 1) throw new Error("Invalid byte limit")
  if (!Number.isFinite(timeoutMs) || timeoutMs <= 0 || timeoutMs > MAX_FETCH_TIMEOUT_MS)
    throw new Error("Invalid fetch deadline")
  const safeHeaders = validateHeaders(headers)
  if (signal.aborted) throw new Error("Request aborted")
  const original = validateFetchURL(input)
  const controller = new AbortController()
  let deadlineExceeded = false
  const abortFromCaller = () => controller.abort()
  signal.addEventListener("abort", abortFromCaller, { once: true })
  const timer = setTimeout(() => {
    deadlineExceeded = true
    controller.abort()
  }, timeoutMs)
  let current = original
  const visited = new Set([original.toString()])
  try {
    for (let redirects = 0; ; redirects += 1) {
      const destination = validateFetchURL(current.toString())
      const addresses = await resolveDestination(destination, controller.signal, dependencies)
      const response = await dependencies.request(
        destination,
        safeHeaders,
        addresses[0],
        maximumBytes,
        controller.signal,
      )
      if ([301, 302, 303, 307, 308].includes(response.status)) {
        if (redirects >= MAX_REDIRECTS) throw new Error("Too many redirects")
        const location = response.headers.location
        if (typeof location !== "string" || location.length > MAX_URL_LENGTH)
          throw new Error("Invalid redirect")
        let resolvedLocation: URL
        try {
          resolvedLocation = new URL(location, destination)
        } catch {
          throw new Error("Invalid redirect")
        }
        const next = validateFetchURL(resolvedLocation.toString())
        if (destination.protocol === "https:" && next.protocol !== "https:")
          throw new Error("Insecure redirect")
        const nextURL = next.toString()
        if (visited.has(nextURL)) throw new Error("Redirect loop")
        if (!approveRedirect) throw redirectRetryError(next)
        const approvedURL = await awaitWithAbort(
          Promise.resolve().then(() => approveRedirect(nextURL, controller.signal)),
          controller.signal,
        )
        if (approvedURL !== nextURL) throw new Error("Redirect destination was not approved")
        visited.add(nextURL)
        current = next
        continue
      }
      if (response.body.byteLength > maximumBytes) throw new Error("Response exceeds byte limit")
      const contentType = response.headers["content-type"]
      return {
        finalUrl: destination.toString(),
        status: response.status,
        headers: response.headers,
        contentType: typeof contentType === "string" ? contentType : "",
        body: response.body,
      }
    }
  } catch (error) {
    if (deadlineExceeded) throw new Error("Fetch deadline exceeded")
    throw error
  } finally {
    clearTimeout(timer)
    signal.removeEventListener("abort", abortFromCaller)
  }
}
