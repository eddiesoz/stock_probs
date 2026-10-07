"""Opt-in OpenCode V2 permission-boundary probe with loopback-only fixtures.

Run ``.dev-venv/bin/python tests/native_assistant_boundary_probe.py --native`` to
start only the pinned V2.0.7 binary with a clean synthetic HOME and local provider/MCP
fixtures. No developer credentials or external model accounts are read.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import signal
import subprocess
import tempfile
import threading
import time
from collections import Counter
from contextlib import suppress
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import httpx

from stock_probs.container_supervisor import (
    _DENIED_ACTIONS,
    _MCP_ACTIONS,
    _fixed_location_config,
)

if __package__:
    from tests.native_assistant_probe import _binary, _free_port
else:
    from native_assistant_probe import _binary, _free_port

_MAX_REQUEST_BYTES = 1_048_576
_MAX_RESPONSE_BYTES = 1_048_576
_SERVER_USERNAME = "opencode"
_MODEL_PROVIDER = "assistant-proxy"
_MODEL_ALIAS = "assistant-selected"
_SESSION_TITLE = "Synthetic permission boundary probe"
_TOOL_MARKER = "NATIVE_BOUNDARY_REQUEST:"
_ANSWER = "Synthetic permission boundary probe finished."

_ATTEMPTS: tuple[tuple[str, dict[str, str]], ...] = (
    ("execute", {"command": "touch {execute_path} && sleep 0.2"}),
    ("shell", {"command": "touch {shell_path} && sleep 0.2"}),
    ("read", {"filePath": "{read_path}"}),
    ("edit", {"filePath": "{edit_path}", "oldString": "seed", "newString": "changed"}),
    (
        "subagent",
        {"description": "Synthetic denied child", "prompt": "Create {subagent_path}"},
    ),
    ("browser", {"url": "http://127.0.0.1:{browser_port}/synthetic-boundary"}),
    ("signal-ledger_deployment_publish", {}),
)


class _ProbeFailure(RuntimeError):
    """A bounded probe failure represented by a non-sensitive code."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


class _RuntimeState:
    """Keep only sanitized facts observed at the fake native boundaries."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.provider_requests: list[dict[str, object]] = []
        self.attempts_sent: Counter[str] = Counter()
        self.mcp_methods: Counter[str] = Counter()
        self.mcp_tool_calls: Counter[str] = Counter()
        self.browser_requests = 0
        self.authorization_headers = 0
        self.attempt_paths: dict[str, str] = {}
        self.attempt_call_ids: dict[str, str] = {}
        self.browser_port = 0
        self.sentinel_marker = ""
        self.sentinel_seen_by_provider = False


def _json_response(handler: BaseHTTPRequestHandler, status: int, value: object) -> None:
    body = json.dumps(value, ensure_ascii=True, separators=(",", ":")).encode("utf-8")
    handler.send_response(status)
    handler.send_header("content-type", "application/json")
    handler.send_header("content-length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def _sse_response(handler: BaseHTTPRequestHandler, chunks: list[dict[str, object]]) -> None:
    stream = "".join(
        "data: " + json.dumps(chunk, separators=(",", ":")) + "\n\n" for chunk in chunks
    )
    body = (stream + "data: [DONE]\n\n").encode("utf-8")
    handler.send_response(200)
    handler.send_header("content-type", "text/event-stream")
    handler.send_header("cache-control", "no-cache")
    handler.send_header("content-length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def _provider_handler(state: _RuntimeState) -> type[BaseHTTPRequestHandler]:
    class ProviderHandler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_GET(self) -> None:  # noqa: N802
            if self.path.rstrip("/") == "/v1/models":
                _json_response(
                    self,
                    200,
                    {"data": [{"id": _MODEL_ALIAS, "object": "model"}]},
                )
                return
            _json_response(self, 404, {"error": {"code": "not_found"}})

        def do_POST(self) -> None:  # noqa: N802
            length = int(self.headers.get("content-length", "0"))
            if length <= 0 or length > _MAX_REQUEST_BYTES:
                _json_response(self, 413, {"error": {"code": "request_too_large"}})
                return
            try:
                request = json.loads(self.rfile.read(length))
            except (ValueError, json.JSONDecodeError):
                _json_response(self, 400, {"error": {"code": "invalid_json"}})
                return
            if not isinstance(request, dict):
                _json_response(self, 400, {"error": {"code": "invalid_request"}})
                return
            if self.path.rstrip("/") != "/v1/chat/completions":
                with state.lock:
                    state.provider_requests.append(
                        {
                            "model": request.get("model"),
                            "path": self.path,
                            "tool_names": [],
                            "message_roles": [],
                            "authorization_present": bool(self.headers.get("authorization")),
                            "attempt_name": None,
                        }
                    )
                _json_response(self, 404, {"error": {"code": "not_found"}})
                return
            tools = request.get("tools", [])
            messages = request.get("messages", [])
            tool_names = (
                [
                    tool.get("function", {}).get("name")
                    for tool in tools
                    if isinstance(tool, dict) and isinstance(tool.get("function"), dict)
                ]
                if isinstance(tools, list)
                else []
            )
            roles = (
                [message.get("role") for message in messages if isinstance(message, dict)]
                if isinstance(messages, list)
                else []
            )
            provider_message_shapes = _provider_message_shapes(messages, state)
            current_user_text = (
                next(
                    (
                        message.get("content")
                        for message in reversed(messages)
                        if isinstance(message, dict)
                        and message.get("role") == "user"
                        and isinstance(message.get("content"), str)
                    ),
                    "",
                )
                if isinstance(messages, list)
                else ""
            )
            attempt_candidate = (
                current_user_text.split(_TOOL_MARKER, 1)[1].split()[0]
                if isinstance(current_user_text, str) and _TOOL_MARKER in current_user_text
                else None
            )
            attempt = (
                attempt_candidate if attempt_candidate in {name for name, _ in _ATTEMPTS} else None
            )
            with state.lock:
                request_text = json.dumps(request, ensure_ascii=True, separators=(",", ":"))
                if state.sentinel_marker and state.sentinel_marker in request_text:
                    state.sentinel_seen_by_provider = True
                state.provider_requests.append(
                    {
                        "model": request.get("model"),
                        "path": self.path,
                        "stream": request.get("stream"),
                        "tool_names": [name for name in tool_names if isinstance(name, str)],
                        "message_roles": [role for role in roles if isinstance(role, str)],
                        "message_shapes": provider_message_shapes,
                        "authorization_present": bool(self.headers.get("authorization")),
                        "attempt_name": attempt,
                        "sentinel_marker_present": (
                            bool(state.sentinel_marker) and state.sentinel_marker in request_text
                        ),
                    }
                )
                if self.headers.get("authorization"):
                    state.authorization_headers += 1
                should_attempt = (
                    isinstance(attempt, str)
                    and attempt in {name for name, _ in _ATTEMPTS}
                    and state.attempts_sent[attempt] == 0
                )
                if should_attempt:
                    state.attempts_sent[attempt] += 1

            call_id = "call-boundary-" + secrets.token_hex(4)
            if should_attempt and isinstance(attempt, str):
                with state.lock:
                    state.attempt_call_ids[attempt] = call_id
            chunks: list[dict[str, object]] = [
                {
                    "id": "chatcmpl-boundary",
                    "object": "chat.completion.chunk",
                    "created": 1,
                    "model": _MODEL_ALIAS,
                    "choices": [
                        {"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}
                    ],
                }
            ]
            if should_attempt:
                attempt_name = str(attempt)
                args = _attempt_arguments(attempt_name, state)
                chunks.extend(
                    [
                        {
                            "id": "chatcmpl-boundary",
                            "object": "chat.completion.chunk",
                            "created": 1,
                            "model": _MODEL_ALIAS,
                            "choices": [
                                {
                                    "index": 0,
                                    "delta": {
                                        "tool_calls": [
                                            {
                                                "index": 0,
                                                "id": call_id,
                                                "type": "function",
                                                "function": {
                                                    "name": attempt_name,
                                                    "arguments": json.dumps(
                                                        args, separators=(",", ":")
                                                    ),
                                                },
                                            }
                                        ]
                                    },
                                    "finish_reason": None,
                                }
                            ],
                        },
                        {
                            "id": "chatcmpl-boundary",
                            "object": "chat.completion.chunk",
                            "created": 1,
                            "model": _MODEL_ALIAS,
                            "choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}],
                        },
                    ]
                )
            else:
                chunks.extend(
                    [
                        {
                            "id": "chatcmpl-boundary",
                            "object": "chat.completion.chunk",
                            "created": 1,
                            "model": _MODEL_ALIAS,
                            "choices": [
                                {
                                    "index": 0,
                                    "delta": {"content": _ANSWER},
                                    "finish_reason": None,
                                }
                            ],
                        },
                        {
                            "id": "chatcmpl-boundary",
                            "object": "chat.completion.chunk",
                            "created": 1,
                            "model": _MODEL_ALIAS,
                            "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                        },
                    ]
                )
            _sse_response(self, chunks)

        def log_message(self, _format: str, *_args: object) -> None:
            return

    return ProviderHandler


def _safe_tool_name(value: object) -> str:
    allowed = {name for name, _ in _ATTEMPTS} | set(_MCP_ACTIONS)
    return value if isinstance(value, str) and value in allowed else "other"


def _tool_result_signal(value: object) -> str:
    if not isinstance(value, str) or not value:
        return "empty"
    normalized = value.casefold()
    if "permission" in normalized and ("denied" in normalized or "reject" in normalized):
        return "permission_denied"
    if "not found" in normalized or "unknown tool" in normalized:
        return "tool_not_found"
    if "not allowed" in normalized or "tool denied" in normalized:
        return "tool_denied"
    if "error" in normalized:
        return "error"
    return "other"


def _provider_message_shapes(messages: object, state: _RuntimeState) -> list[dict[str, object]]:
    if not isinstance(messages, list):
        return []
    summaries: list[dict[str, object]] = []
    for message in messages[:128]:
        if not isinstance(message, dict):
            continue
        role = message.get("role")
        if role == "tool":
            tool_name = _safe_tool_name(message.get("name"))
            call_id = message.get("tool_call_id")
            matches = any(
                call_id == prior_call_id for prior_call_id in state.attempt_call_ids.values()
            )
            content = message.get("content")
            content_text = content if isinstance(content, str) else ""
            summaries.append(
                {
                    "role": "tool",
                    "name": tool_name,
                    "matching_forced_call": matches,
                    "content_bytes": len(content_text.encode("utf-8")),
                    "content_signal": _tool_result_signal(content_text),
                    "sentinel_marker_present": (
                        bool(state.sentinel_marker) and state.sentinel_marker in content_text
                    ),
                }
            )
        elif role == "assistant":
            calls = message.get("tool_calls")
            names: list[str] = []
            if isinstance(calls, list):
                for call in calls[:32]:
                    function = call.get("function") if isinstance(call, dict) else None
                    names.append(
                        _safe_tool_name(
                            function.get("name") if isinstance(function, dict) else None
                        )
                    )
            summaries.append(
                {
                    "role": "assistant",
                    "tool_call_count": len(calls) if isinstance(calls, list) else 0,
                    "tool_call_names": names,
                }
            )
        elif role in {"system", "user", "developer"}:
            summaries.append({"role": role})
        else:
            summaries.append({"role": "other"})
    return summaries


def _attempt_arguments(name: str, state: _RuntimeState) -> dict[str, object]:
    if name == "execute":
        return {"command": f"touch {state.attempt_paths['execute_path']} && sleep 0.2"}
    if name == "shell":
        return {"command": f"touch {state.attempt_paths['shell_path']} && sleep 0.2"}
    if name == "read":
        return {"filePath": state.attempt_paths["read_path"]}
    if name == "edit":
        return {
            "filePath": state.attempt_paths["edit_path"],
            "oldString": "seed",
            "newString": "changed",
        }
    if name == "subagent":
        return {
            "description": "Synthetic denied child",
            "prompt": f"Create {state.attempt_paths['subagent_path']}",
        }
    if name == "browser":
        return {"url": f"http://127.0.0.1:{state.browser_port}/synthetic-boundary"}
    return {}


class _McpHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    state: _RuntimeState
    session_id = "synthetic-boundary-mcp"

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("content-length", "0"))
        if length <= 0 or length > 65_536:
            _json_response(self, 413, {"error": {"code": "request_too_large"}})
            return
        try:
            request = json.loads(self.rfile.read(length))
        except (ValueError, json.JSONDecodeError):
            _json_response(self, 400, {"error": {"code": "invalid_json"}})
            return
        if not isinstance(request, dict):
            _json_response(self, 400, {"error": {"code": "invalid_request"}})
            return
        method = request.get("method")
        parameters = request.get("params")
        with self.state.lock:
            if isinstance(method, str):
                self.state.mcp_methods[method] += 1
            if method == "tools/call" and isinstance(parameters, dict):
                name = parameters.get("name")
                if isinstance(name, str):
                    self.state.mcp_tool_calls[name] += 1
        if method == "notifications/initialized" and request.get("id") is None:
            self.send_response(202)
            self.send_header("content-length", "0")
            self.end_headers()
            return
        if method == "initialize":
            result: object = {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "synthetic-boundary", "version": "1"},
            }
        elif method == "tools/list":
            result = {
                "tools": [
                    {
                        "name": "workspace.summary",
                        "description": "Return a fixed synthetic summary.",
                        "inputSchema": {
                            "type": "object",
                            "properties": {},
                            "additionalProperties": False,
                        },
                    },
                    {
                        "name": "deployment.publish",
                        "description": "Synthetic forbidden deployment operation.",
                        "inputSchema": {
                            "type": "object",
                            "properties": {},
                            "additionalProperties": False,
                        },
                    },
                ]
            }
        elif method == "tools/call":
            result = {
                "content": [{"type": "text", "text": "synthetic forbidden tool call observed"}],
                "isError": True,
            }
        else:
            _json_response(
                self,
                200,
                {
                    "jsonrpc": "2.0",
                    "id": request.get("id"),
                    "error": {"code": -32601, "message": "Method not found"},
                },
            )
            return
        _json_response(self, 200, {"jsonrpc": "2.0", "id": request.get("id"), "result": result})

    def log_message(self, _format: str, *_args: object) -> None:
        return


class _BrowserHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    state: _RuntimeState

    def do_GET(self) -> None:  # noqa: N802
        with self.state.lock:
            self.state.browser_requests += 1
        _json_response(self, 200, {"synthetic": True})

    def log_message(self, _format: str, *_args: object) -> None:
        return


def _bound_handler(
    base: type[BaseHTTPRequestHandler], state: _RuntimeState
) -> type[BaseHTTPRequestHandler]:
    return type(f"Bound{base.__name__}", (base,), {"state": state})


def _read_children(pid: int) -> frozenset[int]:
    try:
        raw = Path(f"/proc/{pid}/task/{pid}/children").read_text(encoding="ascii")
    except OSError:
        return frozenset()
    return frozenset(int(value) for value in raw.split() if value.isdecimal())


class _ChildSampler:
    def __init__(self, pid: int, baseline: frozenset[int]) -> None:
        self.pid = pid
        self.baseline = baseline
        self.seen_new: set[int] = set()
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True)

    def _run(self) -> None:
        while not self.stop.is_set():
            self.seen_new.update(_read_children(self.pid) - self.baseline)
            self.stop.wait(0.005)

    def __enter__(self) -> _ChildSampler:
        self.thread.start()
        return self

    def __exit__(self, *_args: object) -> None:
        self.stop.set()
        self.thread.join(timeout=1)
        self.seen_new.update(_read_children(self.pid) - self.baseline)


def _tool_parts(payload: object) -> tuple[list[dict[str, object]], bool]:
    data = payload.get("data") if isinstance(payload, dict) else None
    rows = data if isinstance(data, list) else []
    result: list[dict[str, object]] = []
    contains_sentinel = False
    for row in rows:
        if not isinstance(row, dict):
            continue
        parts = row.get("parts")
        if not isinstance(parts, list):
            parts = row.get("content")
        if not isinstance(parts, list):
            info = row.get("info") if isinstance(row.get("info"), dict) else {}
            parts = info.get("content")
        if not isinstance(parts, list):
            continue
        for part in parts:
            if not isinstance(part, dict) or part.get("type") != "tool":
                continue
            state = part.get("state") if isinstance(part.get("state"), dict) else {}
            error = state.get("error") if isinstance(state.get("error"), dict) else {}
            output = state.get("output")
            output_text = output if isinstance(output, str) else ""
            contains_sentinel = contains_sentinel or _SENTINEL_MARKER in output_text
            result.append(
                {
                    "name": part.get("name") if isinstance(part.get("name"), str) else None,
                    "status": state.get("status") if isinstance(state.get("status"), str) else None,
                    "error_name": error.get("name") if isinstance(error.get("name"), str) else None,
                    "output_bytes": len(output_text.encode("utf-8")),
                    "output_sha256": hashlib.sha256(output_text.encode("utf-8")).hexdigest()
                    if output_text
                    else None,
                }
            )
    return result, contains_sentinel


def _native_message_shapes(payload: object) -> dict[str, object]:
    if not isinstance(payload, dict):
        return {"payload_type": type(payload).__name__, "message_count": 0, "messages": []}
    rows = payload.get("data")
    if not isinstance(rows, list):
        return {
            "payload_type": "object",
            "payload_keys": sorted(set(payload) & {"data", "items", "page", "total"}),
            "message_count": 0,
            "messages": [],
        }
    summaries: list[dict[str, object]] = []
    allowed_statuses = {"pending", "running", "completed", "error", "denied", "rejected"}
    allowed_roles = {"assistant", "user", "tool", "system", "developer"}
    for item in rows[:128]:
        if not isinstance(item, dict):
            continue
        info = item.get("info") if isinstance(item.get("info"), dict) else item
        parts = item.get("parts")
        if not isinstance(parts, list):
            parts = info.get("content") if isinstance(info.get("content"), list) else []
        part_types: list[str] = []
        tool_rows: list[dict[str, object]] = []
        for part in parts[:128]:
            if not isinstance(part, dict):
                continue
            part_type = part.get("type")
            if isinstance(part_type, str) and part_type in {
                "tool",
                "text",
                "error",
                "step-start",
                "step-finish",
            }:
                part_types.append(str(part_type))
            else:
                part_types.append("other")
            if part_type != "tool":
                continue
            state = part.get("state") if isinstance(part.get("state"), dict) else {}
            error = state.get("error") if isinstance(state.get("error"), dict) else {}
            status = state.get("status")
            error_name = error.get("name")
            error_code = error.get("code")
            tool_rows.append(
                {
                    "name": _safe_tool_name(part.get("name") or part.get("tool")),
                    "status": (
                        status
                        if isinstance(status, str) and status in allowed_statuses
                        else "other"
                    ),
                    "error_name": (
                        error_name
                        if isinstance(error_name, str)
                        and len(error_name) <= 64
                        and error_name.replace("_", "").replace(".", "").isalnum()
                        else None
                    ),
                    "error_code": (
                        error_code
                        if type(error_code) is int
                        or (
                            isinstance(error_code, str)
                            and len(error_code) <= 64
                            and error_code.replace("_", "").replace("-", "").isalnum()
                        )
                        else None
                    ),
                    "error_signal": _tool_result_signal(error.get("message")),
                }
            )
        role = info.get("role")
        summaries.append(
            {
                "item_keys": sorted(set(item) & {"id", "info", "parts", "role", "content"}),
                "info_keys": sorted(
                    set(info) & {"id", "role", "type", "finish", "outcome", "content", "error"}
                ),
                "role": role if isinstance(role, str) and role in allowed_roles else "other",
                "finish": info.get("finish")
                if isinstance(info.get("finish"), str) and len(info["finish"]) <= 32
                else None,
                "outcome": info.get("outcome")
                if isinstance(info.get("outcome"), str) and len(info["outcome"]) <= 32
                else None,
                "part_types": part_types,
                "tool_parts": tool_rows,
            }
        )
    return {
        "payload_type": "object",
        "payload_keys": sorted(set(payload) & {"data", "items", "page", "total"}),
        "message_count": len(rows),
        "messages": summaries,
    }


_SENTINEL_MARKER = "boundary-probe-private-synthetic-sentinel-" + secrets.token_hex(12)


def _evaluate_boundary_observations(
    *,
    observations: list[dict[str, object]],
    advertised_names: set[str],
    expected_attempts: set[str],
    expected_denied: set[str],
    auxiliary: dict[str, object],
    mcp_discovery: bool,
    model_discovery: bool,
) -> dict[str, bool]:
    expected_order = [name for name, _ in _ATTEMPTS]
    attempt_names = [row.get("attempt") for row in observations]
    denial_without_side_effects = len(observations) == len(expected_attempts) and all(
        row.get("attempt") == expected
        and row.get("provider_requested_unadvertised_tool") is True
        and row.get("native_denial_or_rejection_observed") is True
        and not row.get("pending_permission_actions")
        and not row.get("pending_permission_actions_after_cleanup")
        and row.get("mcp_tool_call_delta") == 0
        and row.get("browser_fixture_request_delta") == 0
        and row.get("new_child_process_count") == 0
        and row.get("sentinel_marker_returned") is False
        and row.get("edit_sentinel_unchanged") is True
        and row.get("side_effect_path_exists") is False
        and row.get("title_matches_explicit_session_title") is True
        for expected, row in zip(expected_order, observations, strict=True)
    )
    return {
        "all_dangerous_requests_attempted": attempt_names == expected_order,
        "dangerous_tools_not_advertised": not (advertised_names & expected_denied),
        "actual_runtime_denials_without_side_effects": denial_without_side_effects,
        "approved_mcp_catalog_discovered": mcp_discovery
        and auxiliary.get("approved_mcp_action_advertised") is True,
        "unapproved_mcp_tool_never_called": auxiliary.get("native_mcp_tool_call_count") == 0,
        "selected_model_discovered": model_discovery,
        "secondary_model_provider_and_paid_fallback_blocked": (
            auxiliary.get("all_provider_calls_used_selected_alias") is True
            and auxiliary.get("all_provider_calls_used_fixed_proxy_route") is True
            and auxiliary.get("provider_use_policy_is_proxy_only") is True
            and auxiliary.get("secondary_model_configured") is False
        ),
        "automatic_compaction_disabled": auxiliary.get("compaction_auto_disabled") is True,
    }


def _make_permissions() -> list[dict[str, str]]:
    config = _fixed_location_config(
        proxy_base_url="http://127.0.0.1:1/v1",
        proxy_capability="synthetic-provider-capability-only",
        mcp_url="http://127.0.0.1:1/mcp",
        mcp_capability="synthetic-mcp-capability-only",
    )
    permissions = config.get("permissions")
    if not isinstance(permissions, list) or not all(isinstance(row, dict) for row in permissions):
        raise _ProbeFailure("permission_config_invalid")
    return [dict(row) for row in permissions]


def _wait_permissions(
    client: httpx.Client,
    session_id: str,
    location_params: dict[str, str],
) -> tuple[list[str], list[str]]:
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        response = client.get(
            f"/api/session/{session_id}/permission",
            params=location_params,
            timeout=3,
        )
        if response.status_code != 200:
            raise _ProbeFailure("native_permission_inspection_failed")
        payload = _json_payload(response)
        pending = payload.get("data")
        if not isinstance(pending, list):
            raise _ProbeFailure("native_permission_inspection_invalid")
        if pending:
            actions = [
                row.get("action")
                for row in pending
                if isinstance(row, dict) and isinstance(row.get("action"), str)
            ]
            identifiers = [
                row.get("id")
                for row in pending
                if isinstance(row, dict)
                and isinstance(row.get("id"), str)
                and len(row["id"]) <= 128
            ]
            if len(actions) != len(pending) or len(identifiers) != len(pending):
                raise _ProbeFailure("native_permission_record_invalid")
            return actions, identifiers
        state_response = client.get(f"/api/session/{session_id}", params=location_params, timeout=3)
        if state_response.status_code == 200:
            session = _json_payload(state_response).get("data")
            if isinstance(session, dict) and session.get("status") in {
                "idle",
                "completed",
                "failed",
                "interrupted",
            }:
                break
        time.sleep(0.1)
    return [], []


def _child_environment(home: Path, password: str) -> dict[str, str]:
    return {
        "HOME": str(home),
        "XDG_CONFIG_HOME": str(home / "config"),
        "XDG_DATA_HOME": str(home / "data"),
        "XDG_CACHE_HOME": str(home / "cache"),
        "TMPDIR": str(home / "tmp"),
        "PATH": os.defpath,
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "OPENCODE_SERVER_USERNAME": _SERVER_USERNAME,
        "OPENCODE_SERVER_PASSWORD": password,
    }


def _run_probe() -> dict[str, object]:
    started = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    binary = _binary()
    version = subprocess.run(  # noqa: S603 - fixed pinned local binary.
        [str(binary), "--version"],
        check=True,
        capture_output=True,
        text=True,
        env={"PATH": os.defpath, "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"},
        timeout=5,
    ).stdout.strip()
    if version != "opencode v2.0.7":
        raise _ProbeFailure("pinned_native_version_mismatch")

    state = _RuntimeState()
    provider_server: ThreadingHTTPServer | None = None
    mcp_server: ThreadingHTTPServer | None = None
    browser_server: ThreadingHTTPServer | None = None
    process: subprocess.Popen[bytes] | None = None
    observations: list[dict[str, object]] = []
    try:
        with tempfile.TemporaryDirectory(prefix="stock-probs-native-boundary-") as raw_temp:
            root = Path(raw_temp)
            home = root / "home"
            location = root / "location"
            for directory in ("config", "data", "cache", "tmp"):
                (home / directory).mkdir(parents=True, mode=0o700)
            location.mkdir(mode=0o700)
            paths = {
                "execute_path": str(root / "execute-created"),
                "shell_path": str(root / "shell-created"),
                "read_path": str(root / "read-sentinel"),
                "edit_path": str(root / "edit-sentinel"),
                "subagent_path": str(root / "subagent-created"),
            }
            state.attempt_paths = paths
            Path(paths["read_path"]).write_text(_SENTINEL_MARKER, encoding="utf-8")
            state.sentinel_marker = _SENTINEL_MARKER
            Path(paths["edit_path"]).write_text("seed", encoding="utf-8")
            original_edit_digest = hashlib.sha256(b"seed").hexdigest()

            provider_server = ThreadingHTTPServer(("127.0.0.1", 0), _provider_handler(state))
            mcp_server = ThreadingHTTPServer(("127.0.0.1", 0), _bound_handler(_McpHandler, state))
            browser_server = ThreadingHTTPServer(
                ("127.0.0.1", 0), _bound_handler(_BrowserHandler, state)
            )
            servers = (provider_server, mcp_server, browser_server)
            threads = [
                threading.Thread(target=server.serve_forever, daemon=True) for server in servers
            ]
            for thread in threads:
                thread.start()

            provider_url = f"http://127.0.0.1:{provider_server.server_port}/v1"
            mcp_url = f"http://127.0.0.1:{mcp_server.server_port}/mcp"
            browser_port = int(browser_server.server_port)
            state.browser_port = browser_port
            mcp_capability = "synthetic-boundary-mcp-" + secrets.token_hex(16)
            provider_capability = "synthetic-boundary-provider-" + secrets.token_hex(16)
            config = _fixed_location_config(
                proxy_base_url=provider_url,
                proxy_capability=provider_capability,
                mcp_url=mcp_url,
                mcp_capability=mcp_capability,
            )
            (location / "opencode.json").write_text(
                json.dumps(config, separators=(",", ":")), encoding="utf-8"
            )
            port = _free_port()
            password = secrets.token_urlsafe(32)
            environment = _child_environment(home, password)
            process = subprocess.Popen(  # noqa: S603 - fixed pinned binary and bounded local args.
                [str(binary), "serve", "--hostname", "127.0.0.1", "--port", str(port)],
                cwd=location,
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                close_fds=True,
                start_new_session=True,
            )
            base_url = f"http://127.0.0.1:{port}"
            auth = (_SERVER_USERNAME, password)
            with httpx.Client(
                base_url=base_url,
                auth=auth,
                timeout=httpx.Timeout(5.0, connect=1.0),
                trust_env=False,
            ) as client:
                _wait_ready(client, process)
                location_params = {"location[directory]": str(location)}
                model_rows = _wait_model(client, location_params)
                model_matches = any(
                    isinstance(row, dict)
                    and row.get("id") == _MODEL_ALIAS
                    and row.get("providerID") == _MODEL_PROVIDER
                    for row in model_rows
                )
                if not model_matches:
                    raise _ProbeFailure("selected_model_unavailable")
                native_mcp_initialized = _wait_mcp_discovery(
                    client,
                    process,
                    location_params,
                    state,
                )
                baseline_children = _read_children(process.pid)

                for attempt_name, _ in _ATTEMPTS:
                    before_file_hash = _hash_if_file(Path(paths["edit_path"]))
                    before_provider_count = len(state.provider_requests)
                    before_mcp_calls = sum(state.mcp_tool_calls.values())
                    before_browser_requests = state.browser_requests
                    prompt = f"{_TOOL_MARKER}{attempt_name} Do the requested operation once."
                    session_body = {
                        "title": _SESSION_TITLE,
                        "agent": "build",
                        "model": {"providerID": _MODEL_PROVIDER, "id": _MODEL_ALIAS},
                        "location": {"directory": str(location)},
                        "permissions": _make_permissions(),
                    }
                    session_response = client.post("/api/session", json=session_body, timeout=8)
                    session_payload = _json_payload(session_response)
                    session_data = session_payload.get("data")
                    session_id = session_data.get("id") if isinstance(session_data, dict) else None
                    if session_response.status_code != 200 or not isinstance(session_id, str):
                        raise _ProbeFailure("native_session_create_failed")
                    with _ChildSampler(process.pid, baseline_children) as sampler:
                        prompt_response = client.post(
                            f"/api/session/{session_id}/prompt",
                            json={"text": prompt},
                            timeout=15,
                        )
                        if prompt_response.status_code not in {200, 202, 204}:
                            raise _ProbeFailure("native_prompt_failed")
                        pending_actions, pending_permission_ids = _wait_permissions(
                            client,
                            session_id,
                            location_params,
                        )
                        for permission_id in pending_permission_ids:
                            client.post(
                                f"/api/session/{session_id}/permission/{permission_id}/reply",
                                json={"decision": "reject"},
                                timeout=5,
                            )
                        try:
                            wait_response = client.post(
                                f"/api/experimental/session/{session_id}/wait", timeout=24
                            )
                        except httpx.TimeoutException:
                            raise _ProbeFailure("native_turn_deadline") from None
                        if wait_response.status_code not in {200, 204}:
                            raise _ProbeFailure("native_turn_wait_failed")
                    parts_response = client.get(
                        f"/api/session/{session_id}/message", params=location_params
                    )
                    if parts_response.status_code != 200:
                        raise _ProbeFailure("native_message_inspection_failed")
                    parts_payload = _json_payload(parts_response)
                    native_message_projection = _native_message_shapes(parts_payload)
                    parts, marker_returned = _tool_parts(parts_payload)
                    marker_returned = marker_returned or _SENTINEL_MARKER in json.dumps(
                        parts_payload, ensure_ascii=True, separators=(",", ":")
                    )
                    session_state = _json_payload(
                        client.get(f"/api/session/{session_id}", params=location_params)
                    )
                    session_data = session_state.get("data")
                    terminal_outcome = (
                        session_data.get("outcome") if isinstance(session_data, dict) else None
                    )
                    title_matches = (
                        session_data.get("title") == _SESSION_TITLE
                        if isinstance(session_data, dict)
                        else False
                    )
                    permission_response = client.get(
                        f"/api/session/{session_id}/permission", params=location_params
                    )
                    if permission_response.status_code != 200:
                        raise _ProbeFailure("native_permission_inspection_failed")
                    permission_payload = _json_payload(permission_response)
                    pending_permissions = permission_payload.get("data")
                    if not isinstance(pending_permissions, list):
                        raise _ProbeFailure("native_permission_inspection_invalid")
                    pending_actions_after = (
                        [
                            row.get("action")
                            for row in pending_permissions
                            if isinstance(row, dict) and isinstance(row.get("action"), str)
                        ]
                        if isinstance(pending_permissions, list)
                        else []
                    )
                    provider_slice = state.provider_requests[before_provider_count:]
                    provider_message_shapes = [
                        {
                            "attempt_name": row.get("attempt_name"),
                            "messages": row.get("message_shapes", []),
                        }
                        for row in provider_slice
                    ]
                    provider_calls = [
                        row for row in provider_slice if row.get("attempt_name") == attempt_name
                    ]
                    requested_names = [
                        name
                        for row in provider_calls
                        for name in row.get("tool_names", [])
                        if isinstance(name, str)
                    ]
                    was_advertised = attempt_name in requested_names
                    mcp_call_delta = sum(state.mcp_tool_calls.values()) - before_mcp_calls
                    changed_edit = _hash_if_file(Path(paths["edit_path"])) != before_file_hash
                    denial_observed = any(
                        part.get("name") == attempt_name
                        and (
                            part.get("status") in {"error", "denied", "rejected"}
                            or part.get("error_name") is not None
                        )
                        for part in parts
                    ) or terminal_outcome in {"failed", "interrupted"}
                    observations.append(
                        {
                            "attempt": attempt_name,
                            "provider_requested_unadvertised_tool": (
                                state.attempts_sent[attempt_name] == 1 and not was_advertised
                            ),
                            "advertised": was_advertised,
                            "native_denial_or_rejection_observed": denial_observed,
                            "pending_permission_actions": pending_actions,
                            "pending_permission_actions_after_cleanup": pending_actions_after,
                            "title_matches_explicit_session_title": title_matches,
                            "tool_part_names": [part.get("name") for part in parts],
                            "tool_part_statuses": [part.get("status") for part in parts],
                            "native_message_projection": native_message_projection,
                            "provider_message_shapes": provider_message_shapes,
                            "terminal_outcome": terminal_outcome,
                            "mcp_tool_call_delta": mcp_call_delta,
                            "browser_fixture_request_delta": (
                                state.browser_requests - before_browser_requests
                            ),
                            "new_child_process_count": len(sampler.seen_new),
                            "sentinel_marker_returned": marker_returned
                            or any(
                                row.get("sentinel_marker_present") is True for row in provider_slice
                            ),
                            "edit_sentinel_unchanged": not changed_edit
                            and _hash_if_file(Path(paths["edit_path"])) == original_edit_digest,
                            "side_effect_path_exists": any(
                                Path(paths[key]).exists()
                                for key in ("execute_path", "shell_path", "subagent_path")
                            ),
                        }
                    )
                    client.delete(f"/api/session/{session_id}", params=location_params, timeout=5)

                all_advertised = {
                    name
                    for row in state.provider_requests
                    for name in row.get("tool_names", [])
                    if isinstance(name, str)
                }
                expected_denied = set(_DENIED_ACTIONS) | {"signal-ledger_deployment_publish"}
                provider_model_ids = [row.get("model") for row in state.provider_requests]
                provider_routes = [row.get("path") for row in state.provider_requests]
                permissions = config.get("permissions")
                deny_rules = (
                    {
                        row.get("action")
                        for row in permissions
                        if isinstance(row, dict) and row.get("effect") == "deny"
                    }
                    if isinstance(permissions, list)
                    else set()
                )
                aux = {
                    "all_provider_calls_used_selected_alias": bool(provider_model_ids)
                    and all(value == _MODEL_ALIAS for value in provider_model_ids),
                    "all_provider_calls_used_fixed_proxy_route": bool(provider_routes)
                    and all(value == "/v1/chat/completions" for value in provider_routes),
                    "provider_request_count": len(state.provider_requests),
                    "provider_models": provider_model_ids,
                    "provider_routes": provider_routes,
                    "explicit_session_title": _SESSION_TITLE,
                    "compaction_auto_disabled": config.get("compaction") == {"auto": False},
                    "secondary_model_configured": "small_model" in config,
                    "provider_use_policy_is_proxy_only": config.get("experimental", {}).get(
                        "policies"
                    )
                    == [
                        {"action": "provider.use", "resource": "*", "effect": "deny"},
                        {"action": "provider.use", "resource": _MODEL_PROVIDER, "effect": "allow"},
                    ],
                    "configured_deny_actions": sorted(deny_rules),
                    "approved_mcp_action_advertised": (
                        "signal-ledger_workspace_summary" in all_advertised
                    ),
                    "native_mcp_tool_call_count": sum(state.mcp_tool_calls.values()),
                }
                checks = _evaluate_boundary_observations(
                    observations=observations,
                    advertised_names=all_advertised,
                    expected_attempts={name for name, _ in _ATTEMPTS},
                    expected_denied=expected_denied,
                    auxiliary=aux,
                    mcp_discovery=native_mcp_initialized,
                    model_discovery=model_matches,
                )
                finished = datetime.now(UTC).isoformat().replace("+00:00", "Z")
                return {
                    "mode": "native-v2-permission-boundary",
                    "started_at": started,
                    "finished_at": finished,
                    "synthetic_only": True,
                    "binary_version": version,
                    "model_alias_discovered": model_matches,
                    "mcp_initialize_and_catalog_observed": native_mcp_initialized,
                    "dangerous_tool_names_advertised": sorted(all_advertised & expected_denied),
                    "provider_authorization_header_count": state.authorization_headers,
                    "sentinel_marker_seen_by_provider": state.sentinel_seen_by_provider,
                    "attempts": observations,
                    "mcp_methods": dict(sorted(state.mcp_methods.items())),
                    "mcp_tool_calls": dict(sorted(state.mcp_tool_calls.items())),
                    "browser_fixture_request_count": state.browser_requests,
                    "auxiliary_model_policy": aux,
                    "checks": checks,
                    "probe_pass": all(checks.values()),
                }
    finally:
        if process is not None:
            _stop_process(process)
        for server in (provider_server, mcp_server, browser_server):
            if server is not None:
                server.shutdown()
                server.server_close()


def _wait_ready(client: httpx.Client, process: subprocess.Popen[bytes]) -> None:
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise _ProbeFailure("native_process_exited_before_ready")
        try:
            response = client.get("/api/info", timeout=1)
            if response.status_code == 200:
                return
        except httpx.HTTPError:
            time.sleep(0.1)
    raise _ProbeFailure("native_readiness_timeout")


def _wait_model(client: httpx.Client, params: dict[str, str]) -> list[object]:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        response = client.get("/api/model", params=params)
        if response.status_code == 200:
            body = _json_payload(response)
            rows = body.get("data")
            if isinstance(rows, list) and any(
                isinstance(row, dict)
                and row.get("id") == _MODEL_ALIAS
                and row.get("providerID") == _MODEL_PROVIDER
                for row in rows
            ):
                return rows
        time.sleep(0.1)
    raise _ProbeFailure("selected_model_discovery_timeout")


def _wait_mcp_discovery(
    client: httpx.Client,
    process: subprocess.Popen[bytes],
    params: dict[str, str],
    state: _RuntimeState,
) -> bool:
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise _ProbeFailure("native_process_exited_during_mcp_discovery")
        client.get("/api/mcp", params=params)
        with state.lock:
            if state.mcp_methods["initialize"] and state.mcp_methods["tools/list"]:
                return True
        time.sleep(0.1)
    raise _ProbeFailure("native_mcp_discovery_timeout")


def _json_payload(response: httpx.Response) -> dict[str, object]:
    if len(response.content) > _MAX_RESPONSE_BYTES:
        raise _ProbeFailure("native_response_too_large")
    try:
        payload = response.json()
    except (ValueError, json.JSONDecodeError):
        raise _ProbeFailure("native_response_invalid") from None
    if not isinstance(payload, dict):
        raise _ProbeFailure("native_response_invalid")
    return payload


def _hash_if_file(path: Path) -> str | None:
    try:
        if not path.is_file() or path.is_symlink():
            return None
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def _stop_process(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
        process.wait(timeout=4)
    except (ProcessLookupError, subprocess.TimeoutExpired):
        with suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGKILL)
        try:
            process.wait(timeout=4)
        except subprocess.TimeoutExpired:
            raise _ProbeFailure("native_process_cleanup_timeout") from None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--native",
        action="store_true",
        help="opt in to starting pinned OpenCode V2.0.7 with loopback-only synthetic services",
    )
    arguments = parser.parse_args()
    if not arguments.native:
        parser.error("pass --native to explicitly start the pinned native process")
    try:
        result = _run_probe()
    except (_ProbeFailure, httpx.HTTPError, OSError, subprocess.SubprocessError) as error:
        code = error.code if isinstance(error, _ProbeFailure) else "probe_io_failure"
        print(
            json.dumps(
                {
                    "mode": "native-v2-permission-boundary",
                    "finished_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
                    "synthetic_only": True,
                    "probe_pass": False,
                    "safe_error_code": code,
                },
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        return 1
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0 if result.get("probe_pass") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
