import { describe, expect, test } from "bun:test"
import {
  fetchPublicURL,
  isPublicAddress,
  type FetchDependencies,
  type FetchResponse,
  type RedirectApproval,
  type ResolvedAddress,
} from "./webfetch-guard"

const publicAddress: ResolvedAddress = { address: "93.184.216.34", family: 4 }
const publicAddress6: ResolvedAddress = { address: "2606:4700:4700::1111", family: 6 }

function response(status: number, headers: FetchResponse["headers"] = {}, body = "ok"): FetchResponse {
  return { status, headers, body: Buffer.from(body) }
}

function dependencies(
  resolve: FetchDependencies["resolve"] = async () => [publicAddress],
  request: FetchDependencies["request"] = async () => response(200, { "content-type": "text/plain" }),
): FetchDependencies {
  return { resolve, request }
}

describe("native webfetch destination boundary", () => {
  test.each([
    ["127.0.0.1", false],
    ["10.2.3.4", false],
    ["100.64.0.1", false],
    ["169.254.1.1", false],
    ["192.0.2.1", false],
    ["198.18.0.1", false],
    ["224.0.0.1", false],
    ["8.8.8.8", true],
    ["2606:4700:4700::1111", true],
    ["::1", false],
    ["fc00::1", false],
    ["fe80::1", false],
    ["2001:db8::1", false],
    ["2002::1", false],
    ["::ffff:127.0.0.1", false],
  ])("classifies address %s as public=%s", (address, expected) => {
    expect(isPublicAddress(address)).toBe(expected)
  })

  test.each([
    "http://localhost/private",
    "http://127.0.0.1/private",
    "https://user:pass@example.com/private",
    "https://example.com:8443/private",
    "https://example.com./private",
    "https://internal.localhost/private",
    "file:///etc/passwd",
  ])("rejects unsafe URL before resolution: %s", async (url) => {
    let resolutions = 0
    let requests = 0
    const deps = dependencies(
      async () => {
        resolutions += 1
        return [publicAddress]
      },
      async () => {
        requests += 1
        return response(200)
      },
    )
    await expect(fetchPublicURL(url, {}, 1024, new AbortController().signal, deps)).rejects.toThrow()
    expect(resolutions).toBe(0)
    expect(requests).toBe(0)
  })

  test("rejects caller-controlled credentials and header injection before resolving", async () => {
    let resolutions = 0
    const deps = dependencies(async () => {
      resolutions += 1
      return [publicAddress]
    })
    await expect(
      fetchPublicURL(
        "https://example.com",
        { Authorization: "Bearer private-marker" },
        1024,
        new AbortController().signal,
        deps,
      ),
    ).rejects.toThrow("Unsupported request header")
    await expect(
      fetchPublicURL(
        "https://example.com",
        { accept: "text/plain\r\nAuthorization: Bearer private-marker" },
        1024,
        new AbortController().signal,
        deps,
      ),
    ).rejects.toThrow("Unsupported request header")
    expect(resolutions).toBe(0)
  })

  test("rejects a mixed public/private DNS answer before connecting", async () => {
    let requests = 0
    const deps = dependencies(async () => [publicAddress, { address: "10.0.0.4", family: 4 }], async () => {
      requests += 1
      return response(200)
    })
    await expect(fetchPublicURL("https://example.com", {}, 1024, new AbortController().signal, deps)).rejects.toThrow(
      "not public",
    )
    expect(requests).toBe(0)
  })

  test("pins each redirect hop only after exact approval of its complete URL", async () => {
    const requested: Array<{ host: string; path: string; address: string }> = []
    const approvals: string[] = []
    const deps = dependencies(
      async (host) => (host === "example.com" ? [publicAddress] : [publicAddress6]),
      async (url, _headers, address) => {
        requested.push({ host: url.hostname, path: `${url.pathname}${url.search}`, address: address.address })
        if (requested.length === 1)
          return response(302, { location: "https://other.example.com/next?document=7#section" })
        return response(200, { "content-type": "text/plain" }, "final")
      },
    )
    const approveRedirect: RedirectApproval = async (candidate) => {
      approvals.push(candidate)
      return candidate
    }

    const result = await fetchPublicURL(
      "https://example.com/start?query=1",
      { accept: "text/plain" },
      1024,
      new AbortController().signal,
      deps,
      undefined,
      approveRedirect,
    )

    expect(result.finalUrl).toBe("https://other.example.com/next?document=7#section")
    expect(result.body.toString()).toBe("final")
    expect(approvals).toEqual(["https://other.example.com/next?document=7#section"])
    expect(requested).toEqual([
      { host: "example.com", path: "/start?query=1", address: publicAddress.address },
      { host: "other.example.com", path: "/next?document=7", address: publicAddress6.address },
    ])
  })

  test("blocks a changed same-host path or query before resolving or requesting it without approval", async () => {
    let resolutions = 0
    const requested: string[] = []
    const deps = dependencies(
      async () => {
        resolutions += 1
        return [publicAddress]
      },
      async (url) => {
        requested.push(url.toString())
        return response(302, { location: "/other?document=2" })
      },
    )

    let failure: unknown
    try {
      await fetchPublicURL("https://example.com/start?document=1", {}, 1024, new AbortController().signal, deps)
    } catch (error) {
      failure = error
    }
    expect(failure).toBeInstanceOf(Error)
    expect((failure as Error).message).toContain(
      "REDIRECT_APPROVAL_REQUIRED https://example.com/other?document=2",
    )
    expect(requested).toEqual(["https://example.com/start?document=1"])
    expect(resolutions).toBe(1)
  })

  test.each([
    ["secret query key", "/other?access_token=private-marker", "private-marker"],
    ["encoded secret query key", "/other?%74oken=private-marker", "private-marker"],
    ["fragment", "/other#private-marker", "private-marker"],
    ["overlong preview URL", `/${"x".repeat(2_050)}`, "x".repeat(2_050)],
  ])("omits the redirect retry hint for %s", async (_label, location, sensitiveValue) => {
    const source = "https://example.com/start"
    const requested: string[] = []
    const deps = dependencies(undefined, async (url) => {
      requested.push(url.toString())
      return response(302, { location })
    })
    let failure: unknown
    try {
      await fetchPublicURL(source, {}, 1024, new AbortController().signal, deps)
    } catch (error) {
      failure = error
    }
    expect(failure).toBeInstanceOf(Error)
    expect((failure as Error).message).toContain("safe exact URL preview")
    expect((failure as Error).message).not.toContain("REDIRECT_APPROVAL_REQUIRED")
    expect((failure as Error).message).not.toContain(sensitiveValue)
    expect(requested).toEqual([source])
  })

  test("does not resolve or request a second public host before exact approval", async () => {
    const resolutions: string[] = []
    const requested: string[] = []
    const approvals: string[] = []
    const target = "https://redirect.example.com/report?symbol=SPY"
    const deps = dependencies(
      async (host) => {
        resolutions.push(host)
        return [publicAddress]
      },
      async (url) => {
        requested.push(url.toString())
        return response(302, { location: target })
      },
    )
    const approveRedirect: RedirectApproval = async (candidate) => {
      approvals.push(candidate)
      return null
    }

    await expect(
      fetchPublicURL(
        "https://example.com/start",
        {},
        1024,
        new AbortController().signal,
        deps,
        undefined,
        approveRedirect,
      ),
    ).rejects.toThrow("was not approved")
    expect(approvals).toEqual([target])
    expect(resolutions).toEqual(["example.com"])
    expect(requested).toEqual(["https://example.com/start"])
  })

  test("resolves a relative Location before asking for exact approval", async () => {
    const requested: string[] = []
    const approvals: string[] = []
    const deps = dependencies(undefined, async (url) => {
      requested.push(url.toString())
      return requested.length === 1
        ? response(302, { location: "../report?symbol=SPY" })
        : response(200, {}, "approved relative target")
    })
    const approveRedirect: RedirectApproval = async (candidate) => {
      approvals.push(candidate)
      return candidate
    }

    const result = await fetchPublicURL(
      "https://example.com/research/start",
      {},
      1024,
      new AbortController().signal,
      deps,
      undefined,
      approveRedirect,
    )

    expect(approvals).toEqual(["https://example.com/report?symbol=SPY"])
    expect(requested).toEqual([
      "https://example.com/research/start",
      "https://example.com/report?symbol=SPY",
    ])
    expect(result.finalUrl).toBe("https://example.com/report?symbol=SPY")
  })

  test.each([
    ["denied", async (_candidate: string) => null],
    ["expired", async (_candidate: string) => undefined],
  ] as const)("does not request a redirect after %s approval", async (_outcome, decide) => {
    const requested: string[] = []
    const approvals: string[] = []
    const deps = dependencies(undefined, async (url) => {
      requested.push(url.toString())
      return response(302, { location: "https://example.com/approved-target" })
    })
    const approveRedirect: RedirectApproval = async (candidate) => {
      approvals.push(candidate)
      return decide(candidate)
    }

    await expect(
      fetchPublicURL(
        "https://example.com/start",
        {},
        1024,
        new AbortController().signal,
        deps,
        undefined,
        approveRedirect,
      ),
    ).rejects.toThrow("was not approved")
    expect(approvals).toEqual(["https://example.com/approved-target"])
    expect(requested).toEqual(["https://example.com/start"])
  })

  test("does not replay an earlier destination approval for a later redirect", async () => {
    const requested: string[] = []
    const approvals: string[] = []
    const reusedApproval = "https://example.com/first-target"
    const deps = dependencies(undefined, async (url) => {
      requested.push(url.toString())
      if (requested.length === 1) return response(302, { location: "/first-target" })
      return response(302, { location: "/second-target" })
    })
    const approveRedirect: RedirectApproval = async (candidate) => {
      approvals.push(candidate)
      return approvals.length === 1 ? candidate : reusedApproval
    }

    await expect(
      fetchPublicURL(
        "https://example.com/start",
        {},
        1024,
        new AbortController().signal,
        deps,
        undefined,
        approveRedirect,
      ),
    ).rejects.toThrow("was not approved")
    expect(approvals).toEqual([
      "https://example.com/first-target",
      "https://example.com/second-target",
    ])
    expect(requested).toEqual(["https://example.com/start", reusedApproval])
  })

  test("aborts a pending redirect approval at the absolute fetch deadline", async () => {
    const requested: string[] = []
    let approvalAborted = false
    const deps = dependencies(undefined, async (url) => {
      requested.push(url.toString())
      return response(302, { location: "/slow-approval" })
    })
    const approveRedirect: RedirectApproval = async (_candidate, signal) =>
      new Promise<string | null>((resolve) => {
        signal.addEventListener(
          "abort",
          () => {
            approvalAborted = true
            resolve(null)
          },
          { once: true },
        )
      })

    await expect(
      fetchPublicURL(
        "https://example.com/start",
        {},
        1024,
        new AbortController().signal,
        deps,
        20,
        approveRedirect,
      ),
    ).rejects.toThrow("Fetch deadline exceeded")
    expect(approvalAborted).toBe(true)
    expect(requested).toEqual(["https://example.com/start"])
  })

  test("blocks repeated redirect URLs before requesting or reusing approval", async () => {
    let approvals = 0
    let requests = 0
    const deps = dependencies(undefined, async () => {
      requests += 1
      return response(302, { location: "/start" })
    })
    const approveRedirect: RedirectApproval = async (candidate) => {
      approvals += 1
      return candidate
    }

    await expect(
      fetchPublicURL(
        "https://example.com/start",
        {},
        1024,
        new AbortController().signal,
        deps,
        undefined,
        approveRedirect,
      ),
    ).rejects.toThrow("Redirect loop")
    expect(requests).toBe(1)
    expect(approvals).toBe(0)
  })

  async function expectInvalidRedirectLocation(location: string | string[]): Promise<void> {
    let requests = 0
    const deps = dependencies(undefined, async () => {
      requests += 1
      return response(302, { location } as FetchResponse["headers"])
    })

    await expect(
      fetchPublicURL("https://example.com/start", {}, 1024, new AbortController().signal, deps),
    ).rejects.toThrow("Invalid redirect")
    expect(requests).toBe(1)
  }

  test("rejects malformed redirect Location before another request", async () => {
    await expectInvalidRedirectLocation("https://[")
  })

  test("rejects array-valued redirect Location before another request", async () => {
    await expectInvalidRedirectLocation(["https://example.com/target"])
  })

  test("reports the requested URL as the final URL when no redirect occurs", async () => {
    const result = await fetchPublicURL(
      "https://example.com/research?symbol=SPY",
      {},
      1024,
      new AbortController().signal,
      dependencies(),
    )

    expect(result.finalUrl).toBe("https://example.com/research?symbol=SPY")
  })

  test("rejects a redirect to a private destination before its second request", async () => {
    let requests = 0
    let approvals = 0
    const target = "https://redirect.example.com/private"
    const deps = dependencies(
      async (host) =>
        host === "example.com" ? [publicAddress] : [{ address: "127.0.0.1", family: 4 }],
      async () => {
        requests += 1
        return response(302, { location: target })
      },
    )
    const approveRedirect: RedirectApproval = async (candidate) => {
      approvals += 1
      return candidate
    }
    await expect(
      fetchPublicURL(
        "https://example.com/start",
        {},
        1024,
        new AbortController().signal,
        deps,
        undefined,
        approveRedirect,
      ),
    ).rejects.toThrow("not public")
    expect(requests).toBe(1)
    expect(approvals).toBe(1)
  })

  test("rejects a private literal redirect before approval or a target request", async () => {
    let requests = 0
    let approvals = 0
    const deps = dependencies(undefined, async () => {
      requests += 1
      return response(302, { location: "https://127.0.0.1/private" })
    })

    await expect(
      fetchPublicURL(
        "https://example.com/start",
        {},
        1024,
        new AbortController().signal,
        deps,
        undefined,
        async (candidate) => {
          approvals += 1
          return candidate
        },
      ),
    ).rejects.toThrow("not a public web destination")
    expect(requests).toBe(1)
    expect(approvals).toBe(0)
  })

  test("rejects HTTPS downgrade before asking for approval", async () => {
    let approvals = 0
    const downgrade = dependencies(undefined, async () => response(302, { location: "http://example.com/plain" }))
    await expect(
      fetchPublicURL(
        "https://example.com/start",
        {},
        1024,
        new AbortController().signal,
        downgrade,
        undefined,
        async (candidate) => {
          approvals += 1
          return candidate
        },
      ),
    ).rejects.toThrow("Insecure redirect")
    expect(approvals).toBe(0)
  })

  test("caps redirect count even when every followed URL is separately approved", async () => {
    let requests = 0
    const approvals: string[] = []
    const loop = dependencies(undefined, async () => {
      requests += 1
      return response(302, { location: `/hop/${requests}` })
    })
    const approveRedirect: RedirectApproval = async (candidate) => {
      approvals.push(candidate)
      return candidate
    }
    await expect(
      fetchPublicURL(
        "https://example.com/start",
        {},
        1024,
        new AbortController().signal,
        loop,
        undefined,
        approveRedirect,
      ),
    ).rejects.toThrow("Too many redirects")
    expect(requests).toBe(6)
    expect(approvals).toEqual([
      "https://example.com/hop/1",
      "https://example.com/hop/2",
      "https://example.com/hop/3",
      "https://example.com/hop/4",
      "https://example.com/hop/5",
    ])
  })

  test("bounds response bytes even if the transport returns an oversized body", async () => {
    const deps = dependencies(undefined, async () => response(200, {}, "12345"))
    await expect(
      fetchPublicURL("https://example.com", {}, 4, new AbortController().signal, deps),
    ).rejects.toThrow("byte limit")
  })

  test("passes cancellation to an in-flight request", async () => {
    let observedAbort = false
    const controller = new AbortController()
    let markRequestStarted = () => {}
    const requestStarted = new Promise<void>((resolve) => {
      markRequestStarted = resolve
    })
    const deps = dependencies(undefined, (_url, _headers, _address, _maximumBytes, signal) =>
      new Promise((resolve, reject) => {
        markRequestStarted()
        if (signal.aborted) {
          observedAbort = true
          reject(new Error("aborted"))
          return
        }
        signal.addEventListener(
          "abort",
          () => {
            observedAbort = true
            reject(new Error("aborted"))
          },
          { once: true },
        )
      }),
    )
    const pending = fetchPublicURL("https://example.com", {}, 1024, controller.signal, deps)
    await requestStarted
    controller.abort()
    await expect(pending).rejects.toThrow("aborted")
    expect(observedAbort).toBe(true)
  })

  test("enforces an absolute deadline across an in-flight request", async () => {
    let observedAbort = false
    const deps = dependencies(undefined, (_url, _headers, _address, _maximumBytes, signal) =>
      new Promise((_resolve, reject) => {
        signal.addEventListener(
          "abort",
          () => {
            observedAbort = true
            reject(new Error("aborted"))
          },
          { once: true },
        )
      }),
    )

    await expect(
      fetchPublicURL("https://example.com", {}, 1024, new AbortController().signal, deps, 20),
    ).rejects.toThrow("Fetch deadline exceeded")
    expect(observedAbort).toBe(true)
  })

  test("enforces the same absolute deadline across DNS resolution", async () => {
    let observedAbort = false
    let requests = 0
    const deps = dependencies(
      (_host, signal) =>
        new Promise((_resolve, reject) => {
          signal.addEventListener(
            "abort",
            () => {
              observedAbort = true
              reject(new Error("aborted"))
            },
            { once: true },
          )
        }),
      async () => {
        requests += 1
        return response(200)
      },
    )

    await expect(
      fetchPublicURL("https://example.com", {}, 1024, new AbortController().signal, deps, 20),
    ).rejects.toThrow("Fetch deadline exceeded")
    expect(observedAbort).toBe(true)
    expect(requests).toBe(0)
  })

  test("does not let a caller widen the native fetch deadline", async () => {
    await expect(
      fetchPublicURL("https://example.com", {}, 1024, new AbortController().signal, undefined, 120_001),
    ).rejects.toThrow("Invalid fetch deadline")
  })
})
