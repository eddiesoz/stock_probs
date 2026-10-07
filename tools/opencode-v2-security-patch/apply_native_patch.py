#!/usr/bin/env python3
"""Apply the exact R120 network guard to the pinned OpenCode WebFetch tool."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path

from google_mcp_patch import patch_mcp_tool

MANIFEST_PATH = Path(__file__).with_name("manifest.json")
GUARD_PATH = Path(__file__).with_name("webfetch-guard.ts")

_OLD_HTTP_IMPORT = (
    "import { HttpClient, type HttpClientError, HttpClientRequest, "
    'HttpClientResponse } from "effect/unstable/http"\n'
)
_OLD_HTTP_HELPERS = (
    "\n".join(
        (
            "const isCloudflareChallenge = (error: HttpClientError.HttpClientError) => {",
            '  if (error.reason._tag !== "StatusCodeError") return false',
            "  const response = error.reason.response",
            '  return response.status === 403 && response.headers["cf-mitigated"] === "challenge"',
            "}",
            "",
            "const request = (url: string, format: Format, userAgent = openCodeUserAgent) =>",
            (
                "  HttpClientRequest.get(url).pipe(HttpClientRequest.setHeaders("
                "headers(format, userAgent)))"
            ),
            "",
            "const assertHttpUrl = (url: URL) => {",
            '  if (url.protocol !== "http:" && url.protocol !== "https:") '
            'throw new Error("URL must use http:// or https://")',
            "}",
            "",
            "const execute = (http: HttpClient.HttpClient, url: string, format: Format, "
            "userAgent = openCodeUserAgent) =>",
            (
                "  http.execute(request(url, format, userAgent)).pipe("
                "Effect.flatMap(HttpClientResponse.filterStatusOk))"
            ),
            "",
            "const collectBody = (response: HttpClientResponse.HttpClientResponse) =>",
            "  collectBoundedResponseBody(",
            "    response,",
            "    MAX_RESPONSE_BYTES,",
            "    () => new Error(`Response too large (exceeds ${MAX_RESPONSE_BYTES} byte limit)`),",
            "  )",
            "",
        )
    )
    + "\n"
)
_OLD_TOOL_HTTP_BLOCK = (
    "\n".join(
        (
            "              const { body, contentType } = yield* Effect.gen(function* () {",
            "                const response = yield* execute(http, input.url, input.format).pipe(",
            (
                "                  Effect.catchIf(isCloudflareChallenge, () => "
                "execute(http, input.url, input.format, "
                '"opencode")),'
            ),
            "                )",
            '                const contentType = response.headers["content-type"] || ""',
            "                const mime = mimeFrom(contentType)",
            "                if (isImageAttachment(mime))",
            (
                "                  return yield* Effect.fail(new Error(`Unsupported fetched image "
                "content type: ${mime}`))"
            ),
            "                if (!isTextualMime(mime))",
            (
                "                  return yield* Effect.fail(new Error(`Unsupported fetched file "
                "content type: ${mime}`))"
            ),
            "                return { body: yield* collectBody(response), contentType }",
            "              }).pipe(",
            "                Effect.timeoutOrElse({",
            (
                "                  duration: Duration.seconds(input.timeout ?? "
                "DEFAULT_TIMEOUT_SECONDS),"
            ),
            '                  orElse: () => Effect.fail(new Error("Request timed out")),',
            "                }),",
            "              )",
        )
    )
    + "\n"
)
_NEW_HTTP_IMPORT = 'import { fetchPublicURL } from "./webfetch-guard.js"\n'
_NEW_HTTP_HELPERS = (
    "\n".join(
        (
            "class CloudflareChallenge extends Error {",
            "  constructor() {",
            '    super("Cloudflare challenge")',
            "  }",
            "}",
            "",
            (
                "const executeGuarded = (url: string, format: Format, userAgent: string, "
                "timeoutMs: number) =>"
            ),
            "  Effect.tryPromise({",
            (
                "    try: (signal) => fetchPublicURL(url, headers(format, userAgent), "
                "MAX_RESPONSE_BYTES, signal, undefined, timeoutMs),"
            ),
            "    catch: (error) => error,",
            "  }).pipe(",
            "    Effect.flatMap((response) => {",
            '      const challenge = response.headers["cf-mitigated"]',
            '      if (response.status === 403 && challenge === "challenge") '
            "return Effect.fail(new CloudflareChallenge())",
            "      if (response.status < 200 || response.status >= 300) "
            "return Effect.fail(new Error(`HTTP ${response.status}`))",
            "      return Effect.succeed({ body: response.body, "
            "contentType: response.contentType, finalUrl: response.finalUrl })",
            "    }),",
            "  )",
            "",
            "const assertHttpUrl = (url: URL) => {",
            '  if (url.protocol !== "http:" && url.protocol !== "https:") '
            'throw new Error("URL must use http:// or https://")',
            "}",
            "",
        )
    )
    + "\n"
)
_NEW_TOOL_HTTP_BLOCK = (
    "\n".join(
        (
            "              const timeoutSeconds = input.timeout ?? DEFAULT_TIMEOUT_SECONDS",
            "              const timeoutMs = timeoutSeconds * 1000",
            (
                "              const { body, contentType, finalUrl } = yield* executeGuarded(input.url, "
                "input.format, openCodeUserAgent, timeoutMs)"
            ),
            (
                "                .pipe(Effect.catchIf((error) => error instanceof "
                "CloudflareChallenge, () =>"
            ),
            '                  executeGuarded(input.url, input.format, "opencode", timeoutMs),',
            "                ))",
            "                .pipe(",
            "                  Effect.flatMap((response) => {",
            "                    const mime = mimeFrom(response.contentType)",
            "                    if (isImageAttachment(mime))",
            (
                "                      return Effect.fail(new Error(`Unsupported fetched image "
                "content type: ${mime}`))"
            ),
            "                    if (!isTextualMime(mime))",
            (
                "                      return Effect.fail(new Error(`Unsupported fetched file "
                "content type: ${mime}`))"
            ),
            "                    return Effect.succeed(response)",
            "                  }),",
            "                  Effect.timeoutOrElse({",
            "                    duration: Duration.seconds(timeoutSeconds),",
            '                    orElse: () => Effect.fail(new Error("Request timed out")),',
            "                  }),",
            "                )",
        )
    )
    + "\n"
)

_OLD_RESULT_RETURN = (
    "              return { output: result, content: result.output, "
    "metadata: { contentType: result.contentType } }"
)
_NEW_RESULT_RETURN = (
    "              return { output: result, content: result.output, "
    "metadata: { contentType: result.contentType, finalUrl } }"
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _replace_once(source: str, old: str, new: str, *, label: str) -> str:
    if source.count(old) != 1:
        raise ValueError(f"pinned WebFetch patch anchor mismatch: {label}")
    return source.replace(old, new, 1)


def patch_webfetch(source: str) -> str:
    """Transform only the known V2.0.7 WebFetch source body."""

    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    opencode = manifest["opencode"]
    expected = opencode["webfetch_sha256"]
    if hashlib.sha256(source.encode("utf-8")).hexdigest() != expected:
        raise ValueError("pinned WebFetch source digest mismatch")
    source = _replace_once(source, _OLD_HTTP_IMPORT, "", label="http-import")
    source = _replace_once(
        source,
        'import { Duration, Effect, Schema } from "effect"\n',
        'import { Duration, Effect, Schema } from "effect"\n' + _NEW_HTTP_IMPORT,
        label="effect-import",
    )
    source = _replace_once(
        source,
        'import { collectBoundedResponseBody } from "../http-body.js"\n',
        "",
        label="bounded-body-import",
    )
    source = _replace_once(source, _OLD_HTTP_HELPERS, _NEW_HTTP_HELPERS, label="http-helpers")
    source = _replace_once(
        source,
        "    const http = yield* HttpClient.HttpClient\n",
        "",
        label="http-client-service",
    )
    patched = _replace_once(
        source, _OLD_TOOL_HTTP_BLOCK, _NEW_TOOL_HTTP_BLOCK, label="tool-execution"
    )
    patched = _replace_once(patched, _OLD_RESULT_RETURN, _NEW_RESULT_RETURN, label="final-url-metadata")
    if hashlib.sha256(patched.encode("utf-8")).hexdigest() != opencode["webfetch_patched_sha256"]:
        raise ValueError("pinned WebFetch patch output digest mismatch")
    if _sha256(GUARD_PATH) != opencode["webfetch_guard_sha256"]:
        raise ValueError("pinned WebFetch guard digest mismatch")
    return patched


def apply_patch(source_root: Path) -> dict[str, str]:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    opencode = manifest["opencode"]
    package = json.loads((source_root / "package.json").read_text(encoding="utf-8"))
    if package.get("version") != opencode["version"]:
        raise ValueError("pinned OpenCode package version mismatch")
    tool_path = source_root / opencode["webfetch_path"]
    helper_path = tool_path.with_name("webfetch-guard.ts")
    original_hash = _sha256(tool_path)
    patched_source = patch_webfetch(tool_path.read_text(encoding="utf-8"))
    if helper_path.exists():
        raise ValueError("pinned WebFetch helper destination already exists")
    shutil.copyfile(GUARD_PATH, helper_path)
    tool_path.write_text(patched_source, encoding="utf-8")
    patched_hash = _sha256(tool_path)
    mcp_patch_receipt = patch_mcp_tool(source_root)
    return {
        "opencode_version": opencode["version"],
        "source_commit": opencode["source_commit"],
        "webfetch_source_sha256": original_hash,
        "webfetch_patched_sha256": patched_hash,
        "webfetch_guard_sha256": _sha256(helper_path),
        **mcp_patch_receipt,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path, required=True)
    args = parser.parse_args()
    result = apply_patch(args.source_root)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
