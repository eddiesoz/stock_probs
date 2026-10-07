"""Opt-in pinned OpenCode wire check for loopback execution capabilities.

This probe uses a clean temporary HOME, local-only HTTP fixtures, fixed adapter IDs, and a
synthetic capability. It never reads native credentials or calls a public provider.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import secrets
import socket
import subprocess
import tempfile
import threading
import time
import traceback
from collections.abc import Mapping
from contextlib import suppress
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

import httpx

from stock_probs.assistant.native_provider_adapters import (
    NATIVE_WEBFETCH_DESCRIPTION_SHA256,
    NativeProviderDescriptorError,
    native_adapter_descriptors,
    native_webfetch_schema,
    native_websearch_description_sha256,
    native_websearch_schema,
    project_gemini_tool_schema,
)
from stock_probs.assistant.tools import AssistantToolGateway

_BINARY_CANDIDATES = (
    Path("/home/james/.local/opt/opencode-v2/opencode"),
    Path("/home/james/.local/opt/opencode-v2/bin/opencode"),
)
_MAX_CAPTURED_REQUESTS = 32
_MAX_NATIVE_BODY_BYTES = 1_048_576
_WAIT_SECONDS = 12.0
_MAIN_PROMPT_MARKER = "NATIVE_PROVIDER_MAIN_PROMPT_R120"
_GOOGLE_CONTINUATION_APP_TOOL = "workspace.summary"
_GOOGLE_CONTINUATION_TEXT = "Synthetic Google tool continuation completed."
_GOOGLE_AUXILIARY_TEXT = "Synthetic auxiliary title response."
_SAFE_SESSION_STATES = frozenset(
    {"busy", "idle", "retry", "running", "completed", "error", "aborted"}
)
_OBSERVED_PATHS = {
    "openai": "/v1/responses",
    "anthropic": "/v1/messages",
    "google": "/v1/models/synthetic-model:streamGenerateContent",
}


def _free_port() -> int:
    with socket.socket() as candidate:
        candidate.bind(("127.0.0.1", 0))
        return int(candidate.getsockname()[1])


def _fixed_binary() -> Path:
    for candidate in _BINARY_CANDIDATES:
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return candidate
    raise RuntimeError("pinned_native_binary_unavailable")


def _binary_build_facts(binary: Path) -> dict[str, object]:
    """Bind the executed file to its adjacent, bounded native build manifest if present."""

    digest = hashlib.sha256()
    size = 0
    with binary.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            size += len(chunk)
            digest.update(chunk)
    binary_sha256 = digest.hexdigest()
    manifest_path = binary.with_name("build.json")
    manifest: object = None
    if manifest_path.is_file() and manifest_path.stat().st_size <= 65_536:
        with suppress(OSError, json.JSONDecodeError, UnicodeDecodeError):
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest_fields: dict[str, object] = {}
    if isinstance(manifest, Mapping):
        for key in (
            "native_version",
            "source_commit",
            "source_archive_sha256",
            "manifest_sha256",
            "oauth_transformed_source_set_sha256",
            "mcp_tool_source_sha256",
            "mcp_tool_patched_sha256",
            "webfetch_source_sha256",
            "webfetch_patched_sha256",
            "build_arch",
            "target_arch",
        ):
            value = manifest.get(key)
            if isinstance(value, str) and len(value) <= 160:
                manifest_fields[key] = value
        manifest_hash = manifest.get("binary_sha256")
        manifest_bytes = manifest.get("binary_bytes")
        manifest_bound = (
            manifest_hash == binary_sha256
            and type(manifest_bytes) is int
            and manifest_bytes == size
        )
    else:
        manifest_bound = False
    return {
        "binary_sha256": binary_sha256,
        "binary_bytes": size,
        "manifest_present": isinstance(manifest, Mapping),
        "manifest_binary_binding_matches": manifest_bound,
        "manifest_facts": manifest_fields,
    }


class _FixtureEventOrder:
    """Order only synthetic loopback fixture requests; never retain request bodies."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._value = 0

    def next(self) -> int:
        with self._lock:
            self._value += 1
            return self._value


def _google_sse_frame(
    kind: str,
    *,
    native_tool_name: str,
    text: str = _GOOGLE_CONTINUATION_TEXT,
) -> bytes:
    """Build one fixed synthetic Gemini SSE frame for tool then text continuation."""

    if kind == "function_call":
        content_part: dict[str, object] = {
            "functionCall": {
                "id": "synthetic-summary-call",
                "name": native_tool_name,
                "args": {},
            }
        }
    elif kind == "text":
        content_part = {"text": text}
    else:
        raise ValueError("unknown_google_fixture_frame")
    event = {
        "candidates": [{
            "content": {"role": "model", "parts": [content_part]},
            "finishReason": "STOP",
        }],
    }
    return ("data: " + json.dumps(event, separators=(",", ":")) + "\n\n").encode("utf-8")


def _google_function_response_names(value: object) -> list[str]:
    """Project only the names of bounded Gemini function-result parts."""

    contents = value.get("contents") if isinstance(value, Mapping) else None
    if not isinstance(contents, list) or len(contents) > 128:
        return []
    expected_names = _EXPECTED_NATIVE_APP_TOOL_NAMES
    output: list[str] = []
    for content in contents:
        parts = content.get("parts") if isinstance(content, Mapping) else None
        if not isinstance(parts, list) or len(parts) > 256:
            continue
        for part in parts:
            response = part.get("functionResponse") if isinstance(part, Mapping) else None
            name = response.get("name") if isinstance(response, Mapping) else None
            if isinstance(name, str) and re.fullmatch(r"[A-Za-z0-9_.:-]{1,160}", name):
                output.append(name if name in expected_names else "unclassified")
            if len(output) >= 32:
                return output
    return output


def _google_continuation_tool_names() -> tuple[str, str]:
    """Resolve the canonical app tool and its exact Gemini wire alias."""

    candidates = [
        tool
        for tool in AssistantToolGateway.list_tools()
        if tool.get("name") == _GOOGLE_CONTINUATION_APP_TOOL
    ]
    if len(candidates) != 1:
        raise RuntimeError("google_continuation_app_tool_missing")
    tool = candidates[0]
    schema = tool.get("inputSchema")
    if not isinstance(schema, Mapping) or schema.get("type") != "object":
        raise RuntimeError("google_continuation_app_tool_schema_invalid")
    properties = schema.get("properties")
    required = schema.get("required", [])
    if (
        properties != {}
        or required != []
        or schema.get("additionalProperties") is not False
        or project_gemini_tool_schema(schema) is not None
    ):
        raise RuntimeError("google_continuation_app_tool_requires_arguments")
    native_name = "signal-ledger_" + _GOOGLE_CONTINUATION_APP_TOOL.replace(".", "_")
    rows = [
        row
        for row in _app_tool_rows(protocol="google-generative-language")
        if row.get("name") == native_name
    ]
    if len(rows) != 1:
        raise RuntimeError("google_continuation_native_alias_missing")
    return _GOOGLE_CONTINUATION_APP_TOOL, native_name


def _google_continuation_facts(
    attempts: list[dict[str, object]],
    mcp_requests: list[dict[str, object]],
    session_messages: list[dict[str, object]],
    *,
    enabled: bool,
) -> dict[str, object]:
    """Summarize one exact Google tool continuation without retaining content."""

    app_name, native_name = _google_continuation_tool_names()
    main_requests = _main_request_attempts(attempts)
    observed_names = sorted(_EXPECTED_NATIVE_APP_TOOL_NAMES)
    declaration_checks = [
        bool(
            row.get("protocol") == "google-generative-language"
            and row.get("native_tool_count") == len(observed_names) + 2
            and row.get("app_tool_names_observed") == observed_names
            and row.get("missing_app_tool_names") == []
            and row.get("app_tool_schema_mismatch_names") == []
            and row.get("builtin_tool_names_observed") == ["webfetch", "websearch"]
            and row.get("websearch_schema_matches") is True
            and row.get("webfetch_schema_matches") is True
        )
        for row in main_requests
    ]
    calls = [
        row
        for row in mcp_requests
        if row.get("method") == "tools/call" and row.get("requested_tool") == app_name
    ]
    first_order = main_requests[0].get("event_order") if main_requests else None
    second_order = main_requests[1].get("event_order") if len(main_requests) > 1 else None
    call_order = calls[0].get("event_order") if calls else None
    final_text_count = sum(
        (
            row.get("role") == "assistant" or row.get("message_type") == "assistant"
        )
        and row.get("fixed_final_text_present") is True
        for row in session_messages
    )
    call_succeeded = bool(
        len(calls) == 1
        and calls[0].get("response_status") == 200
        and calls[0].get("capability_matches") is True
        and calls[0].get("arguments_empty_object") is True
        and calls[0].get("arguments_key_count") == 0
    )
    response_bound = bool(
        len(main_requests) == 2
        and main_requests[0].get("fixture_response") == "google_tool_call"
        and main_requests[0].get("function_response_names") == []
        and main_requests[1].get("fixture_response") == "google_final_text"
        and main_requests[1].get("function_response_names") == [native_name]
    )
    ordered = bool(
        type(first_order) is int
        and type(call_order) is int
        and type(second_order) is int
        and first_order < call_order < second_order
    )
    return {
        "enabled": enabled,
        "app_tool_name": app_name,
        "native_tool_name": native_name,
        "main_request_count": len(main_requests),
        "main_request_tool_declarations_match": bool(declaration_checks)
        and all(declaration_checks),
        "main_request_declaration_checks": declaration_checks,
        "workspace_summary_call_count": len(calls),
        "workspace_summary_call_succeeded": call_succeeded,
        "continuation_response_bound": response_bound,
        "event_order_proves_tool_between_requests": ordered,
        "final_synthetic_text_message_count": final_text_count,
        "final_synthetic_text_observed": final_text_count == 1,
        "no_native_search_or_fetch_invocation_observed": not any(
            row.get("tool_names")
            and any(name in {"websearch", "webfetch"} for name in row["tool_names"])
            for row in session_messages
        ),
    }


def _request_handler(
    capability: str,
    captured: list[dict[str, object]],
    *,
    google_continuation: bool = False,
    google_app_tool_name: str | None = None,
    google_native_tool_name: str | None = None,
    mcp_requests: list[dict[str, object]] | None = None,
    event_order: _FixtureEventOrder | None = None,
) -> type[BaseHTTPRequestHandler]:
    capture_lock = threading.Lock()
    continuation_lock = threading.Lock()
    continuation_state = {"function_call_sent": False, "final_text_sent": False}

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_POST(self) -> None:  # noqa: N802
            raw_length = self.headers.get("content-length", "0")
            try:
                length = int(raw_length)
            except ValueError:
                length = _MAX_NATIVE_BODY_BYTES + 1
            if length < 0 or length > _MAX_NATIVE_BODY_BYTES:
                self.send_response(413)
                self.send_header("content-length", "0")
                self.end_headers()
                return
            raw_body = self.rfile.read(length)
            try:
                body: object = json.loads(raw_body)
            except (json.JSONDecodeError, UnicodeDecodeError):
                body = None
            auth = self.headers.get("Authorization")
            parsed_url = urlsplit(self.path)
            query_pairs = parse_qsl(parsed_url.query, keep_blank_values=True, max_num_fields=16)
            body_keys = sorted(body) if isinstance(body, Mapping) else []
            protocol = _protocol_for_path(parsed_url.path)
            main_prompt_marker_present = _contains_marker(body, _MAIN_PROMPT_MARKER)
            main_prompt_marker_fields = _marker_top_level_fields(body, _MAIN_PROMPT_MARKER)
            tool_rows = _tool_rows(body)
            tool_group_facts = _safe_tool_group_facts(body)
            expected_schemas = _expected_native_app_tool_schemas(protocol)
            websearch_schema = next(
                (
                    _safe_schema_facts(
                        row.get("schema"), description=row.get("description")
                    )
                    for row in _raw_tool_rows(body)
                    if row.get("name") == "websearch"
                ),
                None,
            )
            websearch_row = next(
                (row for row in tool_rows if row.get("name") == "websearch"), None
            )
            expected_search_schema = (
                native_websearch_schema(protocol) if protocol is not None else None
            )
            websearch_schema_matches = bool(
                isinstance(websearch_row, Mapping)
                and isinstance(websearch_row.get("schema_facts"), Mapping)
                and websearch_row["schema_facts"].get("description_sha256")
                == native_websearch_description_sha256()
                and websearch_row["schema_facts"].get("schema_content_sha256")
                == _schema_content_digest(expected_search_schema)
            )
            webfetch_row = next(
                (row for row in tool_rows if row.get("name") == "webfetch"), None
            )
            expected_fetch_schema = (
                native_webfetch_schema(protocol) if protocol is not None else None
            )
            webfetch_schema = next(
                (
                    _safe_schema_facts(row.get("schema"), description=row.get("description"))
                    for row in _raw_tool_rows(body)
                    if row.get("name") == "webfetch"
                ),
                None,
            )
            webfetch_schema_matches = bool(
                isinstance(webfetch_row, Mapping)
                and isinstance(webfetch_row.get("schema_facts"), Mapping)
                and webfetch_row["schema_facts"].get("description_sha256")
                == NATIVE_WEBFETCH_DESCRIPTION_SHA256
                and webfetch_row["schema_facts"].get("schema_content_sha256")
                == _schema_content_digest(expected_fetch_schema)
            )
            query_keys = sorted({key[:64] for key, _value in query_pairs})
            safe_query_values = {
                key: sorted(
                    value[:96]
                    for name, value in query_pairs
                    if name == key and value.isascii() and len(value) <= 96
                )
                for key in ("alt", "beta")
                if any(name == key for name, _value in query_pairs)
            }
            function_response_names = (
                _google_function_response_names(body)
                if protocol == "google-generative-language"
                else []
            )
            phase = "capture_only_401"
            if google_continuation and protocol == "google-generative-language":
                if not main_prompt_marker_present:
                    phase = "google_auxiliary_text"
                else:
                    with continuation_lock:
                        if not continuation_state["function_call_sent"]:
                            if (
                                isinstance(google_native_tool_name, str)
                                and google_native_tool_name
                                in {
                                    str(row.get("name"))
                                    for row in tool_rows
                                    if row.get("name") in _EXPECTED_NATIVE_APP_TOOL_NAMES
                                }
                            ):
                                continuation_state["function_call_sent"] = True
                                phase = "google_tool_call"
                            else:
                                phase = "google_tool_not_advertised"
                        elif (
                            not continuation_state["final_text_sent"]
                            and google_native_tool_name is not None
                            and function_response_names == [google_native_tool_name]
                            and mcp_requests is not None
                            and google_app_tool_name is not None
                            and any(
                                row.get("method") == "tools/call"
                                and row.get("requested_tool") == google_app_tool_name
                                and row.get("response_status") == 200
                                for row in mcp_requests
                            )
                        ):
                            continuation_state["final_text_sent"] = True
                            phase = "google_final_text"
                        else:
                            phase = "google_continuation_without_tool_result"
            record = {
                "method": "POST",
                "path": parsed_url.path[:512],
                "query_keys": query_keys,
                "safe_query_values": safe_query_values,
                "query_contains_credential_parameter": any(
                    key.casefold() in {"key", "api_key", "token", "access_token"}
                    for key in query_keys
                ),
                "body_keys": body_keys[:64],
                "body_model_matches_synthetic": (
                    body.get("model") == "synthetic-model"
                    if isinstance(body, Mapping)
                    else False
                ),
                "body_stream_true": (
                    body.get("stream") is True if isinstance(body, Mapping) else False
                ),
                "main_prompt_marker_present": main_prompt_marker_present,
                "main_prompt_marker_fields": main_prompt_marker_fields,
                "protocol": protocol,
                "tool_rows": tool_rows,
                "tool_group_facts": tool_group_facts,
                "websearch_schema": websearch_schema,
                "websearch_schema_matches": websearch_schema_matches,
                "webfetch_schema": webfetch_schema,
                "webfetch_schema_matches": webfetch_schema_matches,
                "native_tool_count": len(tool_rows),
                "app_tool_names_observed": sorted(
                    {
                        str(row["name"])
                        for row in tool_rows
                        if row.get("name") in _EXPECTED_NATIVE_APP_TOOL_NAMES
                    }
                ),
                "missing_app_tool_names": sorted(
                    _EXPECTED_NATIVE_APP_TOOL_NAMES
                    - {
                        str(row["name"])
                        for row in tool_rows
                        if row.get("name") in _EXPECTED_NATIVE_APP_TOOL_NAMES
                    }
                ),
                "app_tool_schema_mismatch_names": sorted(
                    name
                    for name, expected_digest in expected_schemas.items()
                    if not any(
                        row.get("name") == name
                        and row.get("schema_sha256") == expected_digest
                        for row in tool_rows
                    )
                ),
                "builtin_tool_names_observed": sorted(
                    {
                        str(row["name"])
                        for row in tool_rows
                        if row.get("name") not in _EXPECTED_NATIVE_APP_TOOL_NAMES
                    }
                ),
                "authorization_present": isinstance(auth, str),
                "capability_matches": auth == f"Bearer {capability}",
                "content_type_present": bool(self.headers.get("content-type")),
                "function_response_names": function_response_names,
                "fixture_response": phase,
                "event_order": event_order.next() if event_order is not None else None,
            }
            with capture_lock:
                if len(captured) < _MAX_CAPTURED_REQUESTS:
                    captured.append(record)
            if phase in {"google_auxiliary_text", "google_final_text"}:
                response_body = _google_sse_frame(
                    "text",
                    native_tool_name=google_native_tool_name or "unavailable",
                    text=(
                        _GOOGLE_CONTINUATION_TEXT
                        if phase == "google_final_text"
                        else _GOOGLE_AUXILIARY_TEXT
                    ),
                )
                self.send_response(200)
                self.send_header("content-type", "text/event-stream; charset=utf-8")
                self.send_header("cache-control", "no-store")
                self.send_header("content-length", str(len(response_body)))
                self.send_header("connection", "close")
                self.end_headers()
                self.wfile.write(response_body)
                return
            if phase == "google_tool_call":
                response_body = _google_sse_frame(
                    "function_call",
                    native_tool_name=google_native_tool_name or "unavailable",
                )
                self.send_response(200)
                self.send_header("content-type", "text/event-stream; charset=utf-8")
                self.send_header("cache-control", "no-store")
                self.send_header("content-length", str(len(response_body)))
                self.send_header("connection", "close")
                self.end_headers()
                self.wfile.write(response_body)
                return
            if phase in {"google_tool_not_advertised", "google_continuation_without_tool_result"}:
                response_body = b'{"error":{"message":"synthetic app tool continuation missing"}}'
                self.send_response(409)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(response_body)))
                self.send_header("connection", "close")
                self.end_headers()
                self.wfile.write(response_body)
                return
            body = b'{"error":{"message":"synthetic local probe"}}'
            self.send_response(401)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(body)))
            self.send_header("connection", "close")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802
            self.send_response(404)
            self.send_header("content-length", "0")
            self.end_headers()

        def log_message(self, _format: str, *_args: object) -> None:
            return

    return Handler


def _canonical_tool_schema(value: object) -> object:
    """Normalize only known provider case conversion, preserving all schema constraints."""

    if isinstance(value, Mapping):
        output: dict[str, object] = {}
        for key, item in value.items():
            normalized = item
            if key == "type" and isinstance(item, str):
                normalized = item.casefold()
            else:
                normalized = _canonical_tool_schema(item)
            output[str(key)] = normalized
        return output
    if isinstance(value, list):
        return [_canonical_tool_schema(item) for item in value]
    return value


def _tool_schema_digest(description: object, schema: object) -> str:
    digest_material = {
        "description": description if isinstance(description, str) else None,
        "schema": _canonical_tool_schema(schema),
    }
    try:
        encoded = json.dumps(
            digest_material,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError):
        encoded = b"invalid-native-tool-schema"
    return hashlib.sha256(encoded).hexdigest()


def _tool_rows(body: object) -> list[dict[str, object]]:
    """Project native provider tool declarations to safe names and schema digests."""

    if not isinstance(body, Mapping):
        return []
    declarations: list[dict[str, object]] = []
    for row in _raw_tool_rows(body):
        name = row.get("name", row.get("type"))
        if not isinstance(name, str) or re.fullmatch(r"[A-Za-z0-9_.:-]{1,160}", name) is None:
            name = "unclassified"
        schema = row.get("schema")
        description = row.get("description")
        declarations.append(
            {
                "name": name,
                "schema_sha256": _tool_schema_digest(description, schema),
                "schema_facts": _safe_schema_facts(schema, description=description),
            }
        )
    return declarations[:32]


def _safe_tool_group_facts(body: object) -> dict[str, object]:
    """Count native tool groups and declarations without retaining group contents."""

    raw_tools = body.get("tools") if isinstance(body, Mapping) else None
    if not isinstance(raw_tools, list) or len(raw_tools) > 16:
        return {"valid": False, "group_count": 0, "declaration_count": 0, "groups": []}
    groups: list[dict[str, object]] = []
    total = 0
    for group in raw_tools:
        kind = "other"
        count = 0
        if isinstance(group, Mapping):
            declarations = group.get("functionDeclarations")
            if isinstance(declarations, list):
                kind = "function_declarations"
                count = len(declarations)
            elif isinstance(group.get("function"), Mapping):
                kind = "function"
                count = 1
            elif isinstance(group.get("name"), str) or isinstance(group.get("type"), str):
                kind = "declaration"
                count = 1
        count = min(count, 128)
        total += count
        groups.append({"kind": kind, "declaration_count": count})
    return {
        "valid": True,
        "group_count": len(raw_tools),
        "declaration_count": min(total, 512),
        "groups": groups,
    }


def _raw_tool_rows(body: object) -> list[dict[str, object]]:
    """Extract only bounded declaration maps from the supported native request shapes."""

    if not isinstance(body, Mapping):
        return []
    raw_tools = body.get("tools")
    if not isinstance(raw_tools, list):
        return []
    declarations: list[dict[str, object]] = []
    for group in raw_tools:
        if not isinstance(group, Mapping):
            continue
        functions = group.get("functionDeclarations")
        if isinstance(functions, list):
            rows = functions
        elif isinstance(group.get("function"), Mapping):
            rows = [group["function"]]
        else:
            rows = [group]
        for row in rows:
            if not isinstance(row, Mapping):
                continue
            name = row.get("name", row.get("type"))
            schema = row.get(
                "parameters",
                row.get("input_schema", row.get("parametersJsonSchema")),
            )
            declarations.append(
                {
                    "name": name,
                    "description": row.get("description"),
                    "schema": schema,
                }
            )
    return declarations[:32]


def _safe_schema_facts(value: object, *, description: object = None) -> dict[str, object]:
    """Report fixed schema structure without retaining descriptions or request content."""

    if not isinstance(value, Mapping):
        return {"valid": False, "schema_type": type(value).__name__}
    properties = value.get("properties")
    required = value.get("required")
    safe_properties: dict[str, object] = {}
    if isinstance(properties, Mapping) and len(properties) <= 32:
        for key, child in properties.items():
            if (
                not isinstance(key, str)
                or len(key) > 64
                or not isinstance(child, Mapping)
            ):
                continue
            child_facts: dict[str, object] = {}
            for field in ("type", "format", "enum"):
                field_value = child.get(field)
                if field == "enum" and isinstance(field_value, list) and len(field_value) <= 16:
                    child_facts[field] = [
                        item[:64] if isinstance(item, str) else item
                        for item in field_value
                        if item is None or isinstance(item, str | int | float | bool)
                    ]
                elif isinstance(field_value, str) and len(field_value) <= 64:
                    child_facts[field] = field_value
            nested = child.get("properties")
            if isinstance(nested, Mapping) and len(nested) <= 32:
                child_facts["properties"] = sorted(
                    str(name)[:64] for name in nested if isinstance(name, str)
                )
            safe_properties[key] = child_facts
    digest = _tool_schema_digest(description, value)
    return {
        "valid": True,
        "schema_type": value.get("type") if isinstance(value.get("type"), str) else None,
        "required": sorted(
            item[:64] for item in required if isinstance(item, str)
        )[:32]
        if isinstance(required, list)
        else [],
        "additional_properties": value.get("additionalProperties")
        if type(value.get("additionalProperties")) is bool
        else None,
        "properties": safe_properties,
        "schema_shape": _safe_schema_shape(value),
        "schema_content_sha256": _schema_content_digest(value),
        "description_sha256": hashlib.sha256(
            description.encode("utf-8") if isinstance(description, str) else b""
        ).hexdigest(),
        "schema_sha256": digest,
    }


def _mcp_handler(
    tools: list[dict[str, object]],
    captured: list[dict[str, object]],
    capability: str,
    *,
    event_order: _FixtureEventOrder | None = None,
) -> type[BaseHTTPRequestHandler]:
    """Serve the application gateway's actual fixed tool declarations over loopback."""

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_POST(self) -> None:  # noqa: N802
            length_text = self.headers.get("content-length", "0")
            try:
                length = int(length_text)
            except ValueError:
                length = 1_048_577
            if not 0 <= length <= 1_048_576:
                self.send_response(413)
                self.send_header("content-length", "0")
                self.end_headers()
                return
            request = json.loads(self.rfile.read(length))
            method = request.get("method") if isinstance(request, Mapping) else None
            parameters = request.get("params") if isinstance(request, Mapping) else None
            arguments = (
                parameters.get("arguments")
                if isinstance(parameters, Mapping)
                else None
            )
            requested_tool = (
                parameters.get("name")
                if isinstance(parameters, Mapping)
                and isinstance(parameters.get("name"), str)
                and re.fullmatch(r"[A-Za-z0-9_.:-]{1,160}", parameters["name"])
                else None
            )
            capability_matches = self.headers.get("Authorization") == (
                f"Bearer {capability}"
            )
            request_record: dict[str, object] = {
                    "method": method
                    if isinstance(method, str)
                    and method
                    in {
                        "initialize",
                        "notifications/initialized",
                        "tools/list",
                        "tools/call",
                    }
                    else "other",
                    "requested_tool": requested_tool,
                    "arguments_empty_object": type(arguments) is dict and not arguments,
                    "arguments_key_count": (
                        len(arguments) if isinstance(arguments, Mapping) else None
                    ),
                    "capability_present": isinstance(
                        self.headers.get("Authorization"), str
                    ),
                    "capability_matches": capability_matches,
                    "session_header_present": isinstance(
                        self.headers.get("Mcp-Session-Id"), str
                    ),
                    "protocol_version_matches": self.headers.get(
                        "MCP-Protocol-Version"
                    )
                    == "2024-11-05",
                    "response_status": None,
                    "response_tool_count": None,
                    "event_order": event_order.next() if event_order is not None else None,
                }
            captured.append(request_record)
            if not capability_matches:
                self.send_response(401)
                request_record["response_status"] = 401
                self.send_header("content-length", "0")
                self.end_headers()
                return
            if method == "tools/call" and requested_tool not in {
                str(tool.get("name"))
                for tool in tools
                if isinstance(tool, Mapping)
            }:
                self.send_response(404)
                request_record["response_status"] = 404
                self.send_header("content-length", "0")
                self.end_headers()
                return
            if (
                method == "tools/call"
                and requested_tool == _GOOGLE_CONTINUATION_APP_TOOL
                and not (type(arguments) is dict and not arguments)
            ):
                self.send_response(422)
                request_record["response_status"] = 422
                self.send_header("content-length", "0")
                self.end_headers()
                return
            if method == "initialize":
                result: dict[str, object] = {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": {"name": "signal-ledger", "version": "synthetic"},
                }
                self.send_response(200)
                request_record["response_status"] = 200
                self.send_header("Mcp-Session-Id", "synthetic-wire-session")
                self.send_header("MCP-Protocol-Version", "2024-11-05")
            elif method == "tools/list":
                result = {"tools": tools}
                self.send_response(200)
                request_record["response_status"] = 200
                request_record["response_tool_count"] = len(tools)
            elif method == "tools/call":
                result = {
                    "content": [{"type": "text", "text": "Synthetic workspace summary fixture."}],
                    "isError": False,
                }
                self.send_response(200)
                request_record["response_status"] = 200
            elif method == "notifications/initialized":
                self.send_response(202)
                request_record["response_status"] = 202
                self.send_header("content-length", "0")
                self.end_headers()
                return
            else:
                self.send_response(400)
                request_record["response_status"] = 400
                self.send_header("content-length", "0")
                self.end_headers()
                return
            payload = json.dumps(
                {"jsonrpc": "2.0", "id": request.get("id"), "result": result},
                separators=(",", ":"),
            ).encode("utf-8")
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def do_GET(self) -> None:  # noqa: N802
            self.send_response(405)
            self.send_header("content-length", "0")
            self.end_headers()

        def log_message(self, _format: str, *_args: object) -> None:
            return

    return Handler


def _safe_schema_shape(value: object, *, depth: int = 0, budget: list[int] | None = None) -> object:
    """Recursively retain bounded JSON Schema structure while hashing descriptive text."""

    counter = budget if budget is not None else [512]
    counter[0] -= 1
    if counter[0] < 0 or depth > 10:
        return {"truncated": True}
    if isinstance(value, Mapping):
        if len(value) > 64:
            return {"truncated": True}
        output: dict[str, object] = {}
        for key, item in value.items():
            if not isinstance(key, str) or len(key) > 128:
                continue
            if key in {"description", "title", "examples", "default"}:
                if isinstance(item, str):
                    output[key + "_sha256"] = hashlib.sha256(item.encode("utf-8")).hexdigest()
                continue
            if key == "pattern":
                if isinstance(item, str):
                    output["pattern_sha256"] = hashlib.sha256(item.encode("utf-8")).hexdigest()
                continue
            if key == "properties" and isinstance(item, Mapping):
                if len(item) > 64:
                    output[key] = {"truncated": True}
                else:
                    output[key] = {
                        str(name)[:128]: _safe_schema_shape(
                            child, depth=depth + 1, budget=counter
                        )
                        for name, child in sorted(item.items(), key=lambda pair: str(pair[0]))
                        if isinstance(name, str)
                    }
                continue
            if key in {"items", "additionalProperties", "not", "if", "then", "else"}:
                if isinstance(item, bool):
                    output[key] = item
                elif isinstance(item, Mapping):
                    output[key] = _safe_schema_shape(item, depth=depth + 1, budget=counter)
                continue
            if key in {"allOf", "anyOf", "oneOf"} and isinstance(item, list):
                output[key] = [
                    _safe_schema_shape(child, depth=depth + 1, budget=counter)
                    for child in item[:64]
                ]
                continue
            if key in {"required", "enum"} and isinstance(item, list):
                output[key] = [
                    child[:128] if isinstance(child, str) else child
                    for child in item[:128]
                    if child is None or isinstance(child, str | int | float | bool)
                ]
                continue
            if (
                (isinstance(item, str) and len(item) <= 128)
                or item is None
                or isinstance(item, bool | int)
                or (isinstance(item, float) and item == item and abs(item) < float("inf"))
            ):
                output[key] = item
        return output
    return {"invalid_type": type(value).__name__}


def _schema_content_digest(value: object) -> str:
    try:
        encoded = json.dumps(
            _canonical_tool_schema(value),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError):
        encoded = b"invalid-native-tool-schema"
    return hashlib.sha256(encoded).hexdigest()


def _protocol_for_path(path: str) -> str | None:
    if path.endswith("/responses"):
        return "openai-responses"
    if path.endswith("/messages"):
        return "anthropic-messages"
    if re.fullmatch(r"/v1/models/[A-Za-z0-9._:-]{1,160}:streamGenerateContent", path):
        return "google-generative-language"
    return None


def _app_tool_rows(*, protocol: str) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for tool in AssistantToolGateway.list_tools():
        name = tool.get("name")
        schema = tool.get("inputSchema")
        description = tool.get("description")
        if not isinstance(name, str) or not isinstance(schema, Mapping):
            continue
        native_schema: object = schema
        if protocol == "google-generative-language":
            native_schema = project_gemini_tool_schema(schema)
        rows.append(
            {
                "name": "signal-ledger_" + name.replace(".", "_"),
                "schema_sha256": _tool_schema_digest(description, native_schema),
                "schema_facts": _safe_schema_facts(native_schema, description=description),
            }
        )
    return rows


def _safe_app_tool_rows(*, protocol: str) -> tuple[list[dict[str, object]], str | None]:
    """Keep an unsupported expected-schema projection visible without losing wire capture."""

    try:
        return _app_tool_rows(protocol=protocol), None
    except NativeProviderDescriptorError as exc:
        return [], exc.code


def _expected_app_tool_names() -> set[str]:
    return {
        "signal-ledger_" + str(tool["name"]).replace(".", "_")
        for tool in AssistantToolGateway.list_tools()
        if isinstance(tool.get("name"), str)
    }


def _expected_native_app_tool_schemas(protocol: str | None) -> dict[str, str]:
    if protocol is None:
        return {}
    rows, error = _safe_app_tool_rows(protocol=protocol)
    if error is not None:
        # A sentinel digest makes every comparison fail closed while retaining the actual
        # native request shape for a bounded fixture diagnosis.
        return {name: f"projection-error:{error}" for name in _expected_app_tool_names()}
    return {
        str(row["name"]): str(row["schema_sha256"])
        for row in rows
    }


def _integration_inventory(value: object) -> dict[str, object]:
    """Keep only fixed-shape native integration and auth-method IDs/types."""

    rows = value.get("data") if isinstance(value, Mapping) else None
    if not isinstance(rows, list) or len(rows) > 512:
        return {"valid_envelope": False, "row_count": 0, "rows": []}
    integration_ids: list[str] = []
    integrations_with_methods: list[dict[str, object]] = []
    method_type_counts: dict[str, int] = {}
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        integration_id = row.get("id")
        if (
            not isinstance(integration_id, str)
            or re.fullmatch(r"[a-z][a-z0-9-]{0,63}", integration_id) is None
        ):
            continue
        integration_ids.append(integration_id)
        raw_methods = row.get("methods")
        methods: list[dict[str, str]] = []
        if isinstance(raw_methods, list) and len(raw_methods) <= 32:
            for method in raw_methods:
                if not isinstance(method, Mapping):
                    continue
                method_id = method.get("id")
                kind = method.get("type")
                if (
                    isinstance(method_id, str)
                    and re.fullmatch(r"[a-z][a-z0-9-]{0,95}", method_id)
                    and kind in {"oauth", "key", "env", "command"}
                ):
                    methods.append({"id": method_id, "type": str(kind)})
                    method_type_counts[str(kind)] = method_type_counts.get(str(kind), 0) + 1
        if methods:
            integrations_with_methods.append({"id": integration_id, "methods": methods})
    integration_ids.sort()
    integrations_with_methods.sort(key=lambda item: str(item["id"]))
    return {
        "valid_envelope": True,
        "row_count": len(integration_ids),
        "method_type_counts": dict(sorted(method_type_counts.items())),
        "integration_ids": integration_ids,
        "integrations_with_methods": integrations_with_methods,
    }


def _provider_inventory(value: object) -> list[dict[str, object]]:
    rows = value.get("data") if isinstance(value, Mapping) else None
    if not isinstance(rows, list) or len(rows) > 128:
        return []
    output: list[dict[str, object]] = []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        provider_id = row.get("id")
        package = row.get("package")
        activation = row.get("activation")
        if (
            isinstance(provider_id, str)
            and re.fullmatch(r"[A-Za-z0-9-]{1,64}", provider_id)
            and isinstance(package, str)
            and re.fullmatch(r"@opencode/ai/providers/[A-Za-z0-9_./-]{1,160}", package)
            and activation in {"auto", "enabled", "disabled"}
        ):
            output.append(
                {"id": provider_id, "package": package, "activation": str(activation)}
            )
    return sorted(output, key=lambda item: str(item["id"]))


def _model_inventory(value: object) -> list[dict[str, object]]:
    rows = value.get("data") if isinstance(value, Mapping) else None
    if not isinstance(rows, list) or len(rows) > 1024:
        return []
    output: list[dict[str, object]] = []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        model_id = row.get("id")
        model_ref = row.get("modelID")
        provider_id = row.get("providerID")
        package = row.get("package")
        if (
            isinstance(model_id, str)
            and re.fullmatch(r"[A-Za-z0-9._:/+-]{1,160}", model_id)
            and isinstance(provider_id, str)
            and re.fullmatch(r"[A-Za-z0-9-]{1,64}", provider_id)
            and (model_ref is None or isinstance(model_ref, str) and len(model_ref) <= 160)
        ):
            if model_id != "synthetic-model":
                continue
            output.append(
                {
                    "id": model_id,
                    "providerID": provider_id,
                    "modelID": model_ref if isinstance(model_ref, str) else None,
                    "package": package
                    if isinstance(package, str)
                    and re.fullmatch(r"@opencode/ai/providers/[A-Za-z0-9_./-]{1,160}", package)
                    else None,
                    "enabled": row.get("enabled") is True,
                    "capabilities": _safe_model_capabilities(row.get("capabilities")),
                }
            )
    return sorted(output, key=lambda item: (str(item["providerID"]), str(item["id"])))


def _safe_model_capabilities(value: object) -> dict[str, object]:
    """Keep only documented model capability flags and media-kind enums."""

    if not isinstance(value, Mapping):
        return {"present": False}
    output: dict[str, object] = {"present": True}
    tools = value.get("tools")
    if type(tools) is bool:
        output["tools"] = tools
    for key in ("input", "output"):
        kinds = value.get(key)
        if isinstance(kinds, list) and len(kinds) <= 16 and all(
            isinstance(item, str) and re.fullmatch(r"[a-z0-9_-]{1,32}", item)
            for item in kinds
        ):
            output[key] = sorted(set(kinds))
    return output


def _mcp_inventory(value: object) -> dict[str, object]:
    """Project bounded server identifiers and status from native readiness data."""

    data = value.get("data") if isinstance(value, Mapping) else None
    rows: list[tuple[str, object]] = []
    if isinstance(data, Mapping) and len(data) <= 128:
        nested = data.get("servers")
        if isinstance(nested, Mapping) and len(nested) <= 128:
            rows = [(str(key), item) for key, item in nested.items()]
        else:
            rows = [(str(key), item) for key, item in data.items()]
    elif isinstance(data, list) and len(data) <= 128:
        for item in data:
            if not isinstance(item, Mapping):
                continue
            name = item.get("name", item.get("id"))
            if isinstance(name, str):
                rows.append((name, item))
    safe_rows: list[dict[str, object]] = []
    for name, item in rows:
        if re.fullmatch(r"[A-Za-z0-9_-]{1,64}", name) is None:
            continue
        if not isinstance(item, Mapping):
            safe_rows.append({"name": name, "value_type": type(item).__name__})
            continue
        raw_status = item.get("status")
        status_value = raw_status.get("status") if isinstance(raw_status, Mapping) else raw_status
        status = (
            status_value
            if isinstance(status_value, str)
            and re.fullmatch(r"[A-Za-z0-9_-]{1,48}", status_value)
            else None
        )
        tools = item.get("tools")
        safe_rows.append(
            {
                "name": name,
                "status": status,
                "status_type": type(raw_status).__name__,
                "status_fields": (
                    sorted(str(key)[:48] for key in raw_status if isinstance(key, str))[:24]
                    if isinstance(raw_status, Mapping)
                    else []
                ),
                "tool_count": len(tools) if isinstance(tools, list) and len(tools) <= 512 else None,
                "keys": sorted(str(key)[:48] for key in item if isinstance(key, str))[:32],
            }
        )
    return {
        "valid_envelope": isinstance(value, Mapping),
        "top_keys": (
            sorted(str(key)[:48] for key in value if isinstance(key, str))[:32]
            if isinstance(value, Mapping)
            else []
        ),
        "data_type": type(data).__name__,
        "data_keys": (
            sorted(str(key)[:48] for key in data if isinstance(key, str))[:32]
            if isinstance(data, Mapping)
            else []
        ),
        "rows": sorted(safe_rows, key=lambda row: str(row["name"])),
    }


def _mcp_handshake_complete(requests: list[dict[str, object]]) -> bool:
    methods = {row.get("method") for row in requests}
    return {
        "initialize",
        "notifications/initialized",
        "tools/list",
    } <= methods


def _mcp_server_seen(projection: Mapping[str, object]) -> bool:
    rows = projection.get("rows")
    return isinstance(rows, list) and any(
        isinstance(row, Mapping)
        and row.get("name") == "signal-ledger"
        and row.get("status") == "connected"
        for row in rows
    )


def _mcp_ready_for_prompt(
    projection: Mapping[str, object],
    requests: list[dict[str, object]],
    expected_tool_count: int,
) -> bool:
    """Require completed authenticated discovery before prompting the native model."""

    returned_count = max(
        (
            int(row["response_tool_count"])
            for row in requests
            if row.get("method") == "tools/list"
            and row.get("response_status") == 200
            and type(row.get("response_tool_count")) is int
        ),
        default=0,
    )
    return (
        _mcp_server_seen(projection)
        and _mcp_handshake_complete(requests)
        and bool(requests)
        and all(row.get("capability_matches") is True for row in requests)
        and returned_count == expected_tool_count
    )


def _first_request_has_expected_app_schemas(
    attempts: list[dict[str, object]], expected_names: set[str]
) -> bool:
    """Do not hide an initial incomplete declaration by selecting a later retry."""

    if not attempts:
        return False
    first = attempts[0]
    return (
        set(first.get("app_tool_names_observed", [])) == expected_names
        and not first.get("missing_app_tool_names")
        and not first.get("app_tool_schema_mismatch_names")
    )


def _main_request_attempts(attempts: list[dict[str, object]]) -> list[dict[str, object]]:
    """Select only requests carrying the exact synthetic user-turn marker."""

    return [
        row
        for row in attempts
        if row.get("main_prompt_marker_present") is True
    ]


def _main_request_schemas_advertised(
    attempts: list[dict[str, object]], expected_names: set[str]
) -> bool:
    """Require every observed main-turn request to carry the complete app schema set."""

    main_attempts = _main_request_attempts(attempts)
    return bool(main_attempts) and all(
        _first_request_has_expected_app_schemas([attempt], expected_names)
        for attempt in main_attempts
    )


def _native_app_schemas_advertised(
    checks: list[dict[str, object]], expected_names: set[str]
) -> bool:
    """Require exact app schemas on each provider's first observed request."""

    return bool(checks) and all(
        _main_request_schemas_advertised(
            row.get("request_attempts", [])
            if isinstance(row.get("request_attempts"), list)
            else [], expected_names
        )
        for row in checks
    )


def _contains_marker(value: object, marker: str) -> bool:
    """Find a fixed synthetic marker in bounded decoded JSON without retaining text."""

    pending: list[tuple[object, int]] = [(value, 0)]
    visited = 0
    while pending and visited < 4096:
        node, depth = pending.pop()
        visited += 1
        if depth > 32:
            continue
        if isinstance(node, str):
            if marker in node:
                return True
        elif isinstance(node, Mapping):
            pending.extend((child, depth + 1) for child in node.values())
        elif isinstance(node, list):
            pending.extend((child, depth + 1) for child in node)
    return False


def _marker_top_level_fields(value: object, marker: str) -> list[str]:
    """Return only top-level field names that contain the fixed synthetic marker."""

    if not isinstance(value, Mapping):
        return []
    return sorted(
        key[:64]
        for key, child in value.items()
        if isinstance(key, str) and len(key) <= 256 and _contains_marker(child, marker)
    )[:32]


def _session_message_facts(payload: object) -> list[dict[str, object]]:
    """Project bounded role/agent/model/part metadata without message or tool text."""

    rows = payload.get("data") if isinstance(payload, Mapping) else None
    if not isinstance(rows, list) or len(rows) > 128:
        return []
    output: list[dict[str, object]] = []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        info = row.get("info") if isinstance(row.get("info"), Mapping) else row
        role = info.get("role") if isinstance(info, Mapping) else None
        message_type = row.get("type")
        finish = info.get("finish") if isinstance(info, Mapping) else None
        error = info.get("error") if isinstance(info, Mapping) else None
        mode = info.get("mode") if isinstance(info, Mapping) else None
        agent = info.get("agent") if isinstance(info, Mapping) else None
        model = info.get("model") if isinstance(info, Mapping) else None
        provider_id = model.get("providerID") if isinstance(model, Mapping) else None
        model_id = model.get("modelID", model.get("id")) if isinstance(model, Mapping) else None
        safe_mode = mode if isinstance(mode, str) and mode in {"chat", "summary", "title"} else None
        safe_agent = (
            agent
            if isinstance(agent, str)
            and re.fullmatch(r"[a-z][a-z0-9_-]{0,31}", agent)
            else None
        )
        safe_provider_id = (
            provider_id
            if isinstance(provider_id, str)
            and re.fullmatch(r"[A-Za-z0-9-]{1,64}", provider_id)
            else None
        )
        safe_model_id = (
            model_id
            if isinstance(model_id, str)
            and re.fullmatch(r"[A-Za-z0-9._:/+-]{1,160}", model_id)
            else None
        )
        safe_message_type = (
            message_type if message_type in {"user", "assistant"} else None
        )
        safe_finish = (
            finish
            if isinstance(finish, str)
            and finish in {"stop", "tool-calls", "length", "error", "aborted"}
            else None
        )
        safe_error_kind = None
        safe_error_status = None
        error_keys: list[str] = []
        if isinstance(error, Mapping):
            error_keys = sorted(
                key[:48]
                for key in error
                if isinstance(key, str) and re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,47}", key)
            )[:16]
            error_name = error.get("name")
            if isinstance(error_name, str) and re.fullmatch(
                r"[A-Za-z][A-Za-z0-9_]{0,47}", error_name
            ):
                safe_error_kind = error_name
            status = error.get("statusCode", error.get("status"))
            if type(status) is int and 100 <= status <= 599:
                safe_error_status = status
        elif isinstance(error, str):
            # Never echo native error messages; identify only a coarse presence tag.
            safe_error_kind = "message_present"
        parts = row.get("parts")
        parts_source = "parts" if isinstance(parts, list) else None
        if not isinstance(parts, list) and isinstance(info, Mapping):
            parts = info.get("parts")
            parts_source = "info.parts" if isinstance(parts, list) else None
        if not isinstance(parts, list):
            parts = row.get("content")
            parts_source = "content" if isinstance(parts, list) else None
        if not isinstance(parts, list) and isinstance(info, Mapping):
            parts = info.get("content")
            parts_source = "info.content" if isinstance(parts, list) else None
        part_types: list[str] = []
        tool_names: list[str] = []
        fixed_final_text_present = False
        if isinstance(parts, list) and len(parts) <= 256:
            for part in parts:
                if not isinstance(part, Mapping):
                    continue
                kind = part.get("type")
                if isinstance(kind, str) and re.fullmatch(r"[a-z][a-z0-9_-]{0,31}", kind):
                    part_types.append(kind)
                text_value = part.get("text")
                if isinstance(text_value, str) and text_value == _GOOGLE_CONTINUATION_TEXT:
                    fixed_final_text_present = True
                name = part.get("name")
                if isinstance(name, str) and re.fullmatch(r"[A-Za-z0-9_.:-]{1,160}", name):
                    tool_names.append(name)
        output.append(
            {
                "role": role if role in {"user", "assistant"} else None,
                "role_value_type": type(role).__name__,
                "message_type": safe_message_type,
                "mode": safe_mode,
                "agent": safe_agent,
                "finish_tag": safe_finish,
                "error_kind": safe_error_kind,
                "error_status": safe_error_status,
                "error_keys": error_keys,
                "provider_id": safe_provider_id,
                "model_id": safe_model_id,
                "part_count": len(parts) if isinstance(parts, list) else 0,
                "parts_source": parts_source,
                "part_types": part_types[:64],
                "tool_names": sorted(set(tool_names))[:32],
                "fixed_final_text_present": fixed_final_text_present,
                "row_keys": sorted(str(key)[:48] for key in row if isinstance(key, str))[:32],
                "info_keys": (
                    sorted(str(key)[:48] for key in info if isinstance(key, str))[:32]
                    if isinstance(info, Mapping)
                    else []
                ),
            }
        )
    return output


_EXPECTED_NATIVE_APP_TOOL_SCHEMAS = _expected_native_app_tool_schemas("openai-responses")
_EXPECTED_NATIVE_APP_TOOL_NAMES = set(_EXPECTED_NATIVE_APP_TOOL_SCHEMAS)


def _write_location(
    location: Path,
    *,
    adapter_id: str,
    native_provider_id: str,
    package_id: str,
    fixture_base_url: str,
    capability: str,
    mcp_url: str,
    search_enabled: bool,
    fetch_enabled: bool,
) -> str:
    location.mkdir(mode=0o700)
    app_tools = AssistantToolGateway.list_tools()
    mcp_permissions = [
        {
            "action": "signal-ledger_" + str(tool["name"]).replace(".", "_"),
            "resource": "*",
            "effect": "allow",
        }
        for tool in app_tools
    ]
    permissions: list[dict[str, str]] = [
        {"action": "*", "resource": "*", "effect": "deny"},
        *mcp_permissions,
    ]
    if search_enabled:
        permissions.append({"action": "websearch", "resource": "*", "effect": "ask"})
    if fetch_enabled:
        permissions.append({"action": "webfetch", "resource": "*", "effect": "ask"})
    config: dict[str, object] = {
        "$schema": "https://opencode.ai/config.json",
        "model": f"{native_provider_id}/synthetic-model",
        "share": "disabled",
        "update": "disable",
        "compaction": {"auto": False},
        "permissions": permissions,
        "mcp": {
            "servers": {
                "signal-ledger": {
                    "type": "remote",
                    "url": mcp_url,
                    "headers": {"Authorization": "Bearer synthetic-mcp-capability"},
                    "codemode": False,
                    "timeout": {"startup": 5000, "catalog": 5000, "execution": 5000},
                }
            }
        },
        "experimental": {
            "policies": [
                {"action": "provider.use", "resource": "*", "effect": "deny"},
                {
                    "action": "provider.use",
                    "resource": native_provider_id,
                    "effect": "allow",
                },
            ]
        },
        "providers": {
            native_provider_id: {
                "name": f"Synthetic {adapter_id}",
                "package": package_id,
                "settings": {"baseURL": fixture_base_url},
                # This is the same opaque, per-execution capability used by the app proxy.
                # No real vendor credential is present in this native config.
                "headers": {"Authorization": f"Bearer {capability}"},
                "models": {
                    "synthetic-model": {
                        "modelID": "synthetic-model",
                        "name": "Synthetic local wire probe",
                        "capabilities": {
                            "tools": True,
                            "input": ["text"],
                            "output": ["text"],
                        },
                    }
                },
            }
        },
    }
    if search_enabled:
        config["websearch"] = {"provider": "exa"}
    (location / "opencode.json").write_text(
        json.dumps(config, ensure_ascii=True, separators=(",", ":")), encoding="utf-8"
    )
    return f"{native_provider_id}/synthetic-model"


def run_probe(
    *,
    search_enabled: bool = True,
    fetch_enabled: bool = False,
    google_continuation: bool = False,
) -> dict[str, object]:
    """Send one local, synthetic request through each pinned native provider package."""

    binary = _fixed_binary()
    version_result = subprocess.run(  # noqa: S603 - executable is a fixed pinned path.
        [str(binary), "--version"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        timeout=5,
        check=False,
    )
    version = version_result.stdout.strip()[:64]
    if version_result.returncode != 0 or re.fullmatch(r"opencode v2\.0\.7", version) is None:
        raise RuntimeError("pinned_native_version_mismatch")
    binary_facts = _binary_build_facts(binary)

    google_app_tool_name, google_native_tool_name = _google_continuation_tool_names()
    captured: list[dict[str, object]] = []
    mcp_tools = AssistantToolGateway.list_tools()
    mcp_requests: list[dict[str, object]] = []
    event_order = _FixtureEventOrder()
    capability = secrets.token_urlsafe(36)
    fixture = ThreadingHTTPServer(
        ("127.0.0.1", 0),
        _request_handler(
            capability,
            captured,
            google_continuation=google_continuation,
            google_app_tool_name=google_app_tool_name,
            google_native_tool_name=google_native_tool_name,
            mcp_requests=mcp_requests,
            event_order=event_order,
        ),
    )
    fixture_thread = threading.Thread(target=fixture.serve_forever, daemon=True)
    fixture_thread.start()
    native_port = _free_port()
    native_password = secrets.token_urlsafe(36)
    mcp_fixture = ThreadingHTTPServer(
        ("127.0.0.1", 0),
        _mcp_handler(
            mcp_tools,
            mcp_requests,
            "synthetic-mcp-capability",
            event_order=event_order,
        ),
    )
    mcp_thread = threading.Thread(target=mcp_fixture.serve_forever, daemon=True)
    mcp_thread.start()
    locations_by_provider: dict[str, tuple[Path, str]] = {}
    process: subprocess.Popen[bytes] | None = None
    try:
        with tempfile.TemporaryDirectory(prefix="stock-probs-native-provider-wire-") as root_name:
            root = Path(root_name)
            home = root / "home"
            for child in ("config", "data", "cache", "tmp"):
                (home / child).mkdir(parents=True, mode=0o700)
            location_root = root / "locations"
            location_root.mkdir(mode=0o700)
            base_url = f"http://127.0.0.1:{fixture.server_port}/v1"
            for descriptor in native_adapter_descriptors():
                if descriptor.adapter_id == "openai-compatible-chat":
                    continue
                location = location_root / descriptor.adapter_id
                model_ref = _write_location(
                    location,
                    adapter_id=descriptor.adapter_id,
                    native_provider_id=descriptor.native_provider_id,
                    package_id=descriptor.package_id,
                    fixture_base_url=base_url,
                    capability=capability,
                    mcp_url=f"http://127.0.0.1:{mcp_fixture.server_port}/mcp",
                    search_enabled=search_enabled,
                    fetch_enabled=fetch_enabled,
                )
                locations_by_provider[descriptor.native_provider_id] = (location, model_ref)

            environment = {
                "HOME": str(home),
                "XDG_CONFIG_HOME": str(home / "config"),
                "XDG_DATA_HOME": str(home / "data"),
                "XDG_CACHE_HOME": str(home / "cache"),
                "TMPDIR": str(home / "tmp"),
                "PATH": os.defpath,
                "LANG": "C.UTF-8",
                "LC_ALL": "C.UTF-8",
                "OPENCODE_SERVER_USERNAME": "opencode",
                "OPENCODE_SERVER_PASSWORD": native_password,
                # Synthetic fixture value enables native search declaration only. No search
                # request is routed outside this local probe and no vendor account is used.
            }
            if search_enabled:
                environment["EXA_API_KEY"] = "synthetic-local-fixture-key-do-not-use"
            environment.pop("OPENCODE_DISABLE_PROJECT_CONFIG", None)
            process = subprocess.Popen(  # noqa: S603 - executable and args are fixed above.
                [str(binary), "serve", "--hostname", "127.0.0.1", "--port", str(native_port)],
                cwd=location_root,
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                close_fds=True,
            )
            api_base = f"http://127.0.0.1:{native_port}"
            auth = ("opencode", native_password)
            with httpx.Client(
                base_url=api_base,
                auth=auth,
                timeout=httpx.Timeout(3.0, connect=1.0),
                trust_env=False,
            ) as client:
                deadline = time.monotonic() + _WAIT_SECONDS
                while time.monotonic() < deadline:
                    if process.poll() is not None:
                        raise RuntimeError("native_server_exited")
                    try:
                        if client.get("/api/info").status_code == 200:
                            break
                    except httpx.HTTPError:
                        time.sleep(0.1)
                else:
                    raise RuntimeError("native_server_readiness_timeout")

                checks: list[dict[str, object]] = []
                integration_response = client.get("/api/integration")
                native_mcp_response = client.get("/api/mcp")
                integration_inventory = _integration_inventory(
                    integration_response.json() if integration_response.status_code == 200 else None
                )
                initial_mcp_projection = _mcp_inventory(
                    native_mcp_response.json() if native_mcp_response.status_code == 200 else None
                )
                api_schema_response = client.get("/openapi.json")
                openapi_mcp_parameters: list[dict[str, str]] = []
                if api_schema_response.status_code == 200:
                    schema_value = api_schema_response.json()
                    paths = schema_value.get("paths") if isinstance(schema_value, Mapping) else None
                    mcp_path = paths.get("/api/mcp") if isinstance(paths, Mapping) else None
                    get_operation = mcp_path.get("get") if isinstance(mcp_path, Mapping) else None
                    parameters = (
                        get_operation.get("parameters")
                        if isinstance(get_operation, Mapping)
                        else None
                    )
                    if isinstance(parameters, list):
                        openapi_mcp_parameters = [
                            {"name": str(row["name"]), "in": str(row["in"])}
                            for row in parameters
                            if isinstance(row, Mapping)
                            and isinstance(row.get("name"), str)
                            and len(row["name"]) <= 128
                            and isinstance(row.get("in"), str)
                            and row["in"] in {"query", "path", "header"}
                        ][:16]
                for native_provider_id, (location, model_ref) in locations_by_provider.items():
                    location_mcp_start = len(mcp_requests)
                    params = {"location[directory]": str(location)}
                    cold_provider_response = client.get("/api/provider", params=params)
                    cold_model_response = client.get("/api/model", params=params)
                    cold_projection = {
                        "provider_status": cold_provider_response.status_code,
                        "model_status": cold_model_response.status_code,
                        "providers": _provider_inventory(
                            cold_provider_response.json()
                            if cold_provider_response.status_code == 200
                            else None
                        ),
                        "models": _model_inventory(
                            cold_model_response.json()
                            if cold_model_response.status_code == 200
                            else None
                        ),
                    }
                    settled_provider_response = cold_provider_response
                    settled_model_response = cold_model_response
                    settled_projection = cold_projection
                    cold_mcp_response = client.get("/api/mcp", params=params)
                    cold_mcp_projection = _mcp_inventory(
                        cold_mcp_response.json()
                        if cold_mcp_response.status_code == 200
                        else None
                    )
                    settled_mcp_response = cold_mcp_response
                    settled_mcp_projection = cold_mcp_projection
                    for _attempt in range(24):
                        if (
                            any(
                                row.get("id") == native_provider_id
                                and row.get("package") == next(
                                    item.package_id
                                    for item in native_adapter_descriptors()
                                    if item.native_provider_id == native_provider_id
                                )
                                for row in settled_projection["providers"]
                            )
                            and any(
                                row.get("providerID") == native_provider_id
                                and row.get("id") == "synthetic-model"
                                for row in settled_projection["models"]
                            )
                            and _mcp_ready_for_prompt(
                                settled_mcp_projection,
                                mcp_requests[location_mcp_start:],
                                len(mcp_tools),
                            )
                        ):
                            break
                        time.sleep(0.25)
                        settled_provider_response = client.get("/api/provider", params=params)
                        settled_model_response = client.get("/api/model", params=params)
                        settled_projection = {
                            "provider_status": settled_provider_response.status_code,
                            "model_status": settled_model_response.status_code,
                            "providers": _provider_inventory(
                                settled_provider_response.json()
                                if settled_provider_response.status_code == 200
                                else None
                            ),
                            "models": _model_inventory(
                                settled_model_response.json()
                                if settled_model_response.status_code == 200
                                else None
                            ),
                        }
                        settled_mcp_response = client.get("/api/mcp", params=params)
                        settled_mcp_projection = _mcp_inventory(
                            settled_mcp_response.json()
                            if settled_mcp_response.status_code == 200
                            else None
                        )
                    session_response = client.post(
                        "/api/session",
                        json={
                            "title": "Synthetic provider capability probe",
                            "agent": "build",
                            "model": {
                                "providerID": native_provider_id,
                                "id": "synthetic-model",
                            },
                            "location": {"directory": str(location)},
                        },
                    )
                    session_data = (
                        session_response.json().get("data", {})
                        if session_response.status_code == 200
                        else {}
                    )
                    session_id = (
                        session_data.get("id") if isinstance(session_data, Mapping) else None
                    )
                    pre_prompt_mcp_projection = settled_mcp_projection
                    pre_prompt_mcp_response = settled_mcp_response
                    for _attempt in range(24):
                        if _mcp_ready_for_prompt(
                            pre_prompt_mcp_projection,
                            mcp_requests[location_mcp_start:],
                            len(mcp_tools),
                        ):
                            break
                        time.sleep(0.25)
                        pre_prompt_mcp_response = client.get("/api/mcp", params=params)
                        pre_prompt_mcp_projection = _mcp_inventory(
                            pre_prompt_mcp_response.json()
                            if pre_prompt_mcp_response.status_code == 200
                            else None
                        )
                    mcp_tool_list_response_count = max(
                        (
                            int(row["response_tool_count"])
                            for row in mcp_requests[location_mcp_start:]
                            if row.get("method") == "tools/list"
                            and row.get("response_status") == 200
                            and type(row.get("response_tool_count")) is int
                        ),
                        default=0,
                    )
                    prompt_status: int | None = None
                    wait_status: int | None = None
                    session_state_status: int | None = None
                    safe_outcome: str | None = None
                    safe_status: str | None = None
                    session_message_status: int | None = None
                    session_message_facts: list[dict[str, object]] = []
                    request_start = len(captured)
                    mcp_ready_before_prompt = _mcp_ready_for_prompt(
                        pre_prompt_mcp_projection,
                        mcp_requests[location_mcp_start:],
                        len(mcp_tools),
                    )
                    if (
                        mcp_ready_before_prompt
                        and isinstance(session_id, str)
                        and len(session_id) <= 128
                    ):
                        prompt_response = client.post(
                            f"/api/session/{session_id}/prompt",
                            json={"text": _MAIN_PROMPT_MARKER},
                        )
                        prompt_status = prompt_response.status_code
                        with suppress(httpx.HTTPError):
                            wait_response = client.post(
                                f"/api/experimental/session/{session_id}/wait", timeout=3.0
                            )
                            wait_status = wait_response.status_code
                        state_response = client.get(
                            f"/api/session/{session_id}", params=params, timeout=3.0
                        )
                        session_state_status = state_response.status_code
                        state_payload = (
                            state_response.json()
                            if state_response.status_code == 200
                            else {}
                        )
                        state_data = (
                            state_payload.get("data", {})
                            if isinstance(state_payload, Mapping)
                            else {}
                        )
                        raw_outcome = (
                            state_data.get("outcome")
                            if isinstance(state_data, Mapping)
                            else None
                        )
                        safe_outcome = (
                            raw_outcome
                            if isinstance(raw_outcome, str)
                            and re.fullmatch(r"[a-z_-]{1,32}", raw_outcome)
                            else None
                        )
                        raw_status = (
                            state_data.get("status")
                            if isinstance(state_data, Mapping)
                            else None
                        )
                        safe_status = (
                            raw_status
                            if isinstance(raw_status, str)
                            and raw_status in _SAFE_SESSION_STATES
                            else None
                        )
                        messages_response = client.get(
                            f"/api/session/{session_id}/message", params=params, timeout=3.0
                        )
                        session_message_status = messages_response.status_code
                        if messages_response.status_code == 200:
                            session_message_facts = _session_message_facts(
                                messages_response.json()
                            )
                    post_prompt_mcp_response = client.get("/api/mcp", params=params)
                    post_prompt_mcp_projection = _mcp_inventory(
                        post_prompt_mcp_response.json()
                        if post_prompt_mcp_response.status_code == 200
                        else None
                    )
                    request_attempts = captured[request_start:]
                    main_request_attempts = _main_request_attempts(request_attempts)
                    request = main_request_attempts[0] if main_request_attempts else None
                    auxiliary_request_count = len(request_attempts) - len(
                        main_request_attempts
                    )
                    request_segment = mcp_requests[location_mcp_start:]
                    google_tool_continuation = (
                        _google_continuation_facts(
                            request_attempts,
                            request_segment,
                            session_message_facts,
                            enabled=google_continuation
                            and native_provider_id == "google",
                        )
                        if native_provider_id == "google"
                        else None
                    )
                    checks.append(
                        {
                            "native_provider_id": native_provider_id,
                            "provider_inventory_status": settled_provider_response.status_code,
                            "model_inventory_status": settled_model_response.status_code,
                            "cold_projection": cold_projection,
                            "settled_projection": settled_projection,
                            "mcp_cold_status": cold_mcp_response.status_code,
                            "mcp_cold_projection": cold_mcp_projection,
                            "mcp_settled_status": settled_mcp_response.status_code,
                            "mcp_settled_projection": settled_mcp_projection,
                            "mcp_ready_before_prompt": mcp_ready_before_prompt,
                            "prompt_skipped_until_mcp_ready": not mcp_ready_before_prompt,
                            "mcp_before_prompt_projection": pre_prompt_mcp_projection,
                            "mcp_post_prompt_status": post_prompt_mcp_response.status_code,
                            "mcp_post_prompt_projection": post_prompt_mcp_projection,
                            "mcp_http_requests": request_segment,
                            "mcp_handshake_methods": [
                                row.get("method") for row in request_segment
                            ],
                            "mcp_all_capabilities_match": bool(request_segment)
                            and all(
                                row.get("capability_matches") is True for row in request_segment
                            ),
                            "mcp_tools_list_seen": any(
                                row.get("method") == "tools/list" for row in request_segment
                            ),
                            "mcp_ready_tool_count": next(
                                (
                                    row.get("tool_count")
                                    for row in pre_prompt_mcp_projection.get("rows", [])
                                    if isinstance(row, Mapping)
                                    and row.get("name") == "signal-ledger"
                                ),
                                None,
                            ),
                            "mcp_tool_list_response_count": mcp_tool_list_response_count,
                            "session_status": session_response.status_code,
                            "prompt_status": prompt_status,
                            "wait_status": wait_status,
                            "session_state_status": session_state_status,
                            "session_status_value": safe_status,
                            "session_outcome": safe_outcome,
                            "session_message_status": session_message_status,
                            "session_messages": session_message_facts,
                            "google_tool_continuation": google_tool_continuation,
                            "session_terminal": (
                                safe_status in {"idle", "completed", "error", "aborted"}
                                or safe_outcome in {"succeeded", "failed", "aborted", "error"}
                            ),
                            "model_ref_matches": model_ref
                            == f"{native_provider_id}/synthetic-model",
                            "request_observed": request is not None,
                            "request_attempt_count": len(request_attempts),
                            "request_attempts": request_attempts,
                            "main_request_attempt_count": len(main_request_attempts),
                            "main_request_attempts": main_request_attempts,
                            "auxiliary_request_count": auxiliary_request_count,
                            "capability_forwarded": (
                                request.get("capability_matches") is True
                                if request is not None
                                else False
                            ),
                            "request_path": request.get("path") if request is not None else None,
                            "request_path_matches_observed": (
                                request.get("path") == _OBSERVED_PATHS.get(native_provider_id)
                                if request is not None
                                else False
                            ),
                            "request_query_keys": (
                                request.get("query_keys", []) if request is not None else []
                            ),
                            "safe_query_values": (
                                request.get("safe_query_values", {}) if request is not None else {}
                            ),
                            "query_contains_credential_parameter": (
                                request.get("query_contains_credential_parameter") is True
                                if request is not None
                                else False
                            ),
                            "request_body_keys": (
                                request.get("body_keys", []) if request is not None else []
                            ),
                            "body_model_matches_synthetic": (
                                request.get("body_model_matches_synthetic") is True
                                if request is not None
                                else False
                            ),
                            "body_stream_true": (
                                request.get("body_stream_true") is True
                                if request is not None
                                else False
                            ),
                            "authorization_present": (
                                request.get("authorization_present") is True
                                if request is not None
                                else False
                            ),
                            "native_tool_count": request.get("native_tool_count", 0)
                            if request is not None
                            else 0,
                            "tool_group_facts": request.get("tool_group_facts")
                            if request is not None
                            else None,
                            "tool_rows": (
                                request.get("tool_rows", []) if request is not None else []
                            ),
                            "app_tool_names_observed": request.get(
                                "app_tool_names_observed", []
                            )
                            if request is not None
                            else [],
                            "missing_app_tool_names": request.get(
                                "missing_app_tool_names", sorted(_EXPECTED_NATIVE_APP_TOOL_NAMES)
                            )
                            if request is not None
                            else sorted(_EXPECTED_NATIVE_APP_TOOL_NAMES),
                            "app_tool_schema_mismatch_names": request.get(
                                "app_tool_schema_mismatch_names",
                                sorted(_EXPECTED_NATIVE_APP_TOOL_NAMES),
                            )
                            if request is not None
                            else sorted(_EXPECTED_NATIVE_APP_TOOL_NAMES),
                            "websearch_schema": request.get("websearch_schema")
                            if request is not None
                            else None,
                            "websearch_schema_matches": request.get(
                                "websearch_schema_matches", False
                            )
                            if request is not None
                            else False,
                            "webfetch_schema": request.get("webfetch_schema")
                            if request is not None
                            else None,
                            "webfetch_schema_matches": request.get(
                                "webfetch_schema_matches", False
                            )
                            if request is not None
                            else False,
                            "builtin_tool_names_observed": request.get(
                                "builtin_tool_names_observed", []
                            )
                            if request is not None
                            else [],
                        }
                    )
            google_check = next(
                (row for row in checks if row.get("native_provider_id") == "google"),
                {},
            )
            continuation = google_check.get("google_tool_continuation")
            continuation_facts = (
                continuation if isinstance(continuation, Mapping) else {}
            )
            google_continuation_pass = bool(
                google_continuation
                and google_check.get("session_status") == 200
                and google_check.get("prompt_status") == 200
                and google_check.get("wait_status") in {200, 204}
                and google_check.get("session_terminal") is True
                and continuation_facts.get("main_request_count") == 2
                and continuation_facts.get("main_request_tool_declarations_match") is True
                and continuation_facts.get("workspace_summary_call_count") == 1
                and continuation_facts.get("workspace_summary_call_succeeded") is True
                and continuation_facts.get("continuation_response_bound") is True
                and continuation_facts.get("event_order_proves_tool_between_requests") is True
                and continuation_facts.get("final_synthetic_text_observed") is True
                and continuation_facts.get("no_native_search_or_fetch_invocation_observed") is True
            )
            return {
                "mode": "synthetic_native_provider_capability_wire_probe",
                "native_version": version,
                "native_binary": binary_facts,
                "real_credentials_used": False,
                "provider_upstream_is_loopback": True,
                "mcp_upstream_is_loopback": True,
                "search_enabled": search_enabled,
                "fetch_enabled": fetch_enabled,
                "google_continuation_enabled": google_continuation,
                "google_continuation_app_tool_name": google_app_tool_name,
                "google_continuation_native_tool_name": google_native_tool_name,
                "google_continuation": continuation_facts,
                "google_native_app_mcp_continuation_pass": google_continuation_pass,
                "mcp_tool_count": len(mcp_tools),
                "mcp_tool_names": [str(tool["name"]) for tool in mcp_tools],
                "expected_wire_app_tool_names": sorted(_EXPECTED_NATIVE_APP_TOOL_NAMES),
                "expected_wire_app_tool_rows_by_protocol": {
                    protocol: {
                        "rows": sorted(rows, key=lambda item: str(item["name"])),
                        "projection_error": projection_error,
                    }
                    for protocol in (
                        "openai-responses",
                        "anthropic-messages",
                        "google-generative-language",
                    )
                    for rows, projection_error in (
                        _safe_app_tool_rows(protocol=protocol),
                    )
                },
                "integration_inventory_status": integration_response.status_code,
                "integration_inventory": integration_inventory,
                "mcp_api_status": native_mcp_response.status_code,
                "mcp_api_projection": initial_mcp_projection,
                "openapi_status": api_schema_response.status_code,
                "openapi_mcp_parameters": openapi_mcp_parameters,
                "mcp_http_requests": mcp_requests,
                "vendor_adapter_checks": checks,
                "all_vendor_packages_exercised": all(
                    check["session_status"] == 200
                    and check["prompt_status"] == 200
                    and check["request_observed"]
                    and check["request_path_matches_observed"]
                    and check["session_terminal"] is True
                    and check["wait_status"] in {200, 204}
                    for check in checks
                ),
                "all_main_requests_identified_and_terminal": all(
                    check["main_request_attempt_count"] >= 1
                    and check["session_terminal"] is True
                    and check["wait_status"] in {200, 204}
                    for check in checks
                ),
                "all_capabilities_forwarded": all(
                    check["request_observed"] and check["capability_forwarded"] for check in checks
                ),
                "all_mcp_handshakes_ready_before_prompt": all(
                    check["mcp_ready_before_prompt"]
                    and check["mcp_all_capabilities_match"]
                    and check["mcp_tools_list_seen"]
                    and check["mcp_tool_list_response_count"] == len(mcp_tools)
                    for check in checks
                ),
                "all_native_app_tool_schemas_advertised": _native_app_schemas_advertised(
                    checks, _EXPECTED_NATIVE_APP_TOOL_NAMES
                ),
                "native_search_advertised": all(
                    "websearch" in check["builtin_tool_names_observed"] for check in checks
                ),
                "native_search_absent_when_disabled": (not search_enabled)
                and all(
                    "websearch" not in check["builtin_tool_names_observed"] for check in checks
                ),
                "native_search_schema_matches": all(
                    check["websearch_schema_matches"] for check in checks
                ),
                "native_webfetch_advertised": fetch_enabled
                and all(
                    "webfetch" in check["builtin_tool_names_observed"] for check in checks
                ),
                "native_webfetch_schema_matches": fetch_enabled
                and all(check["webfetch_schema_matches"] for check in checks),
                "native_webfetch_not_advertised": not fetch_enabled
                and all(
                    "webfetch" not in check["builtin_tool_names_observed"] for check in checks
                ),
            }
    finally:
        if process is not None:
            process.terminate()
            try:
                process.wait(timeout=3.0)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=3.0)
        fixture.shutdown()
        fixture.server_close()
        fixture_thread.join(timeout=1.0)
        mcp_fixture.shutdown()
        mcp_fixture.server_close()
        mcp_thread.join(timeout=1.0)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--without-search", action="store_true")
    parser.add_argument("--with-webfetch", action="store_true")
    parser.add_argument("--google-tool-continuation", action="store_true")
    args = parser.parse_args()
    if not args.run:
        parser.error("--run is required")
    if args.google_tool_continuation and (args.without_search or not args.with_webfetch):
        parser.error("--google-tool-continuation requires search and webfetch")
    try:
        result = run_probe(
            search_enabled=not args.without_search,
            fetch_enabled=args.with_webfetch,
            google_continuation=args.google_tool_continuation,
        )
    except Exception as exc:
        message = str(exc)
        safe_code = message if re.fullmatch(r"[A-Za-z0-9_]{1,64}", message) else "probe_failed"
        frames = traceback.extract_tb(exc.__traceback__)
        safe_frames: list[dict[str, object]] = []
        for frame in frames[-6:]:
            filename = Path(frame.filename).name
            if (
                re.fullmatch(r"[A-Za-z0-9_.-]{1,96}", filename)
                and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,63}", frame.name)
                and type(frame.lineno) is int
            ):
                safe_frames.append(
                    {"file": filename, "function": frame.name, "line": frame.lineno}
                )
        error_type = type(exc).__name__
        print(
            json.dumps(
                {
                    "mode": "synthetic_native_provider_capability_wire_probe",
                    "safe_error": safe_code,
                    "error_type": error_type
                    if re.fullmatch(r"[A-Za-z][A-Za-z0-9]{0,63}", error_type)
                    else "UnknownError",
                    "trace": safe_frames,
                },
                separators=(",", ":"),
            )
        )
        return 1
    print(json.dumps(result, separators=(",", ":")))
    required = [
        "all_vendor_packages_exercised",
        "all_main_requests_identified_and_terminal",
        "all_capabilities_forwarded",
        "all_mcp_handshakes_ready_before_prompt",
        "all_native_app_tool_schemas_advertised",
    ]
    required.append(
        "native_webfetch_advertised"
        if args.with_webfetch
        else "native_webfetch_not_advertised"
    )
    if args.with_webfetch:
        required.append("native_webfetch_schema_matches")
    required.extend(
        ("native_search_absent_when_disabled",)
        if args.without_search
        else ("native_search_advertised", "native_search_schema_matches")
    )
    if args.google_tool_continuation:
        required.append("google_native_app_mcp_continuation_pass")
    return 0 if all(result.get(key) is True for key in required) else 1


if __name__ == "__main__":
    raise SystemExit(main())
