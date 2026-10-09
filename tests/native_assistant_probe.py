"""Opt-in native OpenCode V2 protocol probe using only disposable synthetic services.

Run ``.dev-venv/bin/python tests/native_assistant_probe.py --native`` to start the pinned
OpenCode binary with a clean synthetic HOME and query its real loopback API. This file is not
collected by pytest and never imports or reads the developer's OpenCode credential store.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import concurrent.futures
import contextvars
import errno
import hashlib
import hmac
import json
import math
import os
import re
import secrets
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import AsyncIterator, Callable, Mapping
from contextlib import nullcontext
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote, urlsplit, urlunsplit

import httpx
import uvicorn

from stock_probs.assistant.model_catalog import AssistantModel
from stock_probs.assistant.providers import AssistantProviderManager
from stock_probs.assistant.tools import AssistantToolGateway
from stock_probs.container_supervisor import _fixed_location_config

_BINARY_CANDIDATES = (
    Path("/home/james/.local/opt/opencode-v2/opencode"),
    Path("/home/james/.local/opt/opencode-v2/bin/opencode"),
)
_MCP_REQUESTS: list[dict[str, object]] = []
_PROVIDER_REQUESTS: list[dict[str, object]] = []
_PROVIDER_CALLS = 0
_EXPECTED_MCP_SESSIONS: set[str] = set()
_APP_PROVIDER_CALLS: list[dict[str, object]] = []
_APP_PROVIDER_HTTP: list[dict[str, object]] = []
_APP_PROVIDER_REQUESTS: list[dict[str, object]] = []
_APP_NATIVE_REQUESTS: list[dict[str, object]] = []
_APP_NATIVE_CLEANUP: list[dict[str, object]] = []
_APP_CONTINUATION_WAITING = threading.Event()
_APP_CONTINUE = threading.Event()
_NATIVE_ZEN_EXPECTED_IDENTITY: contextvars.ContextVar[
    tuple[str | None, str | None, str | None, str | None, str | None, str | None]
] = contextvars.ContextVar(
    "native_zen_expected_identity", default=(None, None, None, None, None, None)
)
_NATIVE_ZEN_COMPONENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,63}$")
_NATIVE_ZEN_USER_AGENT_MAX = 256
_NATIVE_OPENCODE_SESSION_ID = re.compile(r"^ses_[0-9a-f]{12}[A-Za-z0-9]{14}$")
_NATIVE_PROJECT_ID_MAX = 128
_TOOL_ACTIONS = tuple(
    "signal-ledger_" + str(tool["name"]).replace(".", "_")
    for tool in AssistantToolGateway.list_tools()
)
_ATTACH_ORIGIN = "https://ledger-r120.test"
_ATTACH_SEARCH_QUERY = "IANA reserved example domains purpose"
_ATTACH_WEBFETCH_URL = "https://www.iana.org/domains/reserved"
_ATTACH_MAX_STDIN_BYTES = 8192
_ATTACH_MAX_ACK_BYTES = 128
_ATTACH_MAX_RESPONSE_BYTES = 1_048_576
_ATTACH_DELETE_RETRY_INITIAL_SECONDS = 0.25
_ATTACH_DELETE_RETRY_MAX_SECONDS = 1.0


def _attached_probe_prompts() -> tuple[str, str]:
    """Return the two owner prompts, keeping the retrieval fixture coherent and bounded."""

    return (
        "Use workspace.summary to read my saved instruments. State the number of saved "
        "instruments and do not infer data that the tool did not return.",
        "Use workspace.summary once to read my saved instruments and state the holding count "
        "without guessing. Then research why IANA reserves example domains for documentation. "
        "Use built-in web search exactly once with exactly this public query: "
        f"{_ATTACH_SEARCH_QUERY}. "
        "Use one relevant fact from the search result. Then use the native WebFetch tool exactly "
        f"once for {_ATTACH_WEBFETCH_URL}; wait for explicit approval of that exact URL before "
        "fetching, and use one fact from the fetched page. Finish with a concise answer of no "
        "more than 100 words that includes the holding count and one fact from each retrieval. "
        "Do not fetch any other URL or invent facts.",
    )


_ATTACH_TIMELINE_PHASES = (
    "search_preview",
    "search_approval",
    "search_source",
    "fetch_preview",
    "fetch_approval",
    "fetch_source",
    "terminal",
)
_ATTACH_TIMELINE_MAX_ELAPSED_MS = 180_000
_ATTACH_TIMELINE_MAX_PHASE_COUNT = 64
_ATTACH_TIMELINE_MAX_EVENT_SEQUENCE = 2_147_483_647
_ATTACH_FAILURE_STAGES = frozenset(
    {
        "input_validation",
        "model_inventory",
        "admin_step_up",
        "admin_model_policy",
        "user_consent_and_conversation_setup",
        "pre_turn_readiness",
        "concurrent_turn_create",
        "turn_poll_and_search_confirmation",
        "owner_evidence_and_isolation",
        "conversation_delete_and_health",
        "acceptance_validation",
    }
)
_ATTACH_ACCEPTANCE_FAILURES = frozenset(
    {
        "turn_requests_not_concurrent",
        "search_not_approved",
        "active_search_checkpoint_missing",
        "native_search_sources_missing",
        "webfetch_not_approved",
        "webfetch_approval_not_owner_bound",
        "native_webfetch_source_missing",
        "owner0_turn_not_completed",
        "owner0_model_id_mismatch",
        "owner0_answer_empty",
        "owner0_workspace_summary_receipt_count_invalid",
        "owner0_workspace_summary_digest_mismatch",
        "owner0_selected_model_mismatch",
        "owner1_turn_not_completed",
        "owner1_model_id_mismatch",
        "owner1_answer_empty",
        "owner1_workspace_summary_receipt_count_invalid",
        "owner1_workspace_summary_digest_mismatch",
        "owner1_selected_model_mismatch",
        "owner0_conversation_delete_failed",
        "owner1_conversation_delete_failed",
        "cross_owner_access_not_denied",
        "forged_internal_mcp_not_denied",
        "worker_not_ready_after_turns",
        "supervised_app_not_reachable",
    }
)
_ATTACH_SAFE_TURN_ERROR_CODES = frozenset(
    {
        "worker_unavailable",
        "provider_unavailable",
        "provider_policy_changed",
        "tool_failed",
        "tool_unavailable",
        "turn_timeout",
        "turn_cancelled",
        "invalid_runtime_event",
        "runtime_restarted",
        "output_too_large",
        "empty_response",
        "sensitive_output_rejected",
        "session_revoked",
    }
)
_ATTACH_DELETE_PUBLIC_ERROR_CODES = frozenset(
    {
        "assistant_authorization_required",
        "assistant_busy",
        "assistant_cache_clear_pending",
        "assistant_conflict",
        "assistant_quota_exceeded",
        "assistant_storage_unavailable",
        "assistant_worker_unavailable",
        "conversation_revision",
        "delete_confirmation",
        "not_found",
        "session_revoked",
    }
)
_ATTACH_TURN_FAILURE_STAGES = frozenset(
    {"none", "before_model_session_event", "after_model_session_event", "unknown_terminal"}
)


class _McpHandler(BaseHTTPRequestHandler):
    """Serve a fixed, private fixture tool catalog to native V2 discovery."""

    protocol_version = "HTTP/1.1"
    _session_identifier = "synthetic-mcp-session"

    def do_GET(self) -> None:  # noqa: N802
        _MCP_REQUESTS.append(
            {
                "http_method": "GET",
                "accept": self.headers.get("accept"),
                "session_header_present": bool(self.headers.get("Mcp-Session-Id")),
                "server_session_header": self._session_identifier,
            }
        )
        self.send_response(405)
        self.send_header("content-length", "0")
        self.end_headers()

    def do_POST(self) -> None:  # noqa: N802
        length = int(self.headers.get("content-length", "0"))
        request = json.loads(self.rfile.read(length))
        method = request.get("method")
        parameters = request.get("params")
        _MCP_REQUESTS.append(
            {
                "http_method": "POST",
                "method": method,
                "request_id_present": request.get("id") is not None,
                "tool_name": parameters.get("name") if isinstance(parameters, dict) else None,
                "params_keys": sorted(parameters) if isinstance(parameters, dict) else [],
                "argument_keys": sorted(parameters.get("arguments", {}))
                if isinstance(parameters, dict) and isinstance(parameters.get("arguments"), dict)
                else [],
                "session_header_present": bool(self.headers.get("Mcp-Session-Id")),
                "protocol_header": self.headers.get("MCP-Protocol-Version"),
                "opencode_session_id_present": (
                    isinstance(parameters, dict)
                    and isinstance(parameters.get("_meta"), dict)
                    and "sessionID" in parameters["_meta"]
                ),
                "session_id_matches_expected": (
                    parameters.get("_meta", {}).get("sessionID") in _EXPECTED_MCP_SESSIONS
                    if method == "tools/call"
                    and isinstance(parameters, dict)
                    and isinstance(parameters.get("_meta"), dict)
                    and "sessionID" in parameters["_meta"]
                    else None
                ),
            }
        )
        if method == "initialize":
            result: dict[str, object] = {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "signal-ledger", "version": "probe"},
            }
        elif method == "tools/list":
            result = {"tools": AssistantToolGateway.list_tools()}
        elif method == "tools/call":
            result = {
                "content": [{"type": "text", "text": "synthetic tool result"}],
                "isError": False,
            }
        else:
            result = {"content": [{"type": "text", "text": "synthetic tool result"}]}
        if method == "notifications/initialized" and request.get("id") is None:
            self.send_response(202)
            self.send_header("content-length", "0")
            self.end_headers()
            return
        body = json.dumps(
            {"jsonrpc": "2.0", "id": request.get("id"), "result": result},
            separators=(",", ":"),
        ).encode()
        self.send_response(200)
        self.send_header("content-type", "application/json")
        if method == "initialize":
            self.send_header("Mcp-Session-Id", self._session_identifier)
            self.send_header("MCP-Protocol-Version", "2024-11-05")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, _format: str, *_args: object) -> None:
        return


class _ProviderHandler(BaseHTTPRequestHandler):
    """Serve deterministic OpenAI-compatible tool and answer continuations."""

    protocol_version = "HTTP/1.1"

    def do_GET(self) -> None:  # noqa: N802
        if self.path.rstrip("/") == "/v1/models":
            body = json.dumps({"data": [{"id": "assistant-selected", "object": "model"}]}).encode()
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_response(404)
        self.send_header("content-length", "0")
        self.end_headers()

    def do_POST(self) -> None:  # noqa: N802
        global _PROVIDER_CALLS
        length = int(self.headers.get("content-length", "0"))
        request = json.loads(self.rfile.read(length))
        tools = request.get("tools", [])
        messages = request.get("messages", [])
        names = [
            tool.get("function", {}).get("name")
            for tool in tools
            if isinstance(tool, dict) and isinstance(tool.get("function"), dict)
        ]
        roles = [item.get("role") for item in messages if isinstance(item, dict)]
        tool_result_count = sum(
            1 for item in messages if isinstance(item, dict) and item.get("role") == "tool"
        )
        tool_result_names = [
            item.get("name")
            for item in messages
            if isinstance(item, dict)
            and item.get("role") == "tool"
            and isinstance(item.get("name"), str)
        ]
        contains_synthetic_prompt = any(
            isinstance(item, dict)
            and isinstance(item.get("content"), str)
            and "Use the synthetic workspace summary tool and then answer." in item["content"]
            for item in messages
        )
        contains_search_probe = any(
            isinstance(item, dict)
            and isinstance(item.get("content"), str)
            and "NATIVE SEARCH PROBE:" in item["content"]
            for item in messages
        )
        _PROVIDER_REQUESTS.append(
            {
                "path": self.path,
                "model": request.get("model"),
                "request_keys": sorted(request),
                "stream": request.get("stream"),
                "tool_names": names,
                "tool_shapes": [
                    {
                        "type": tool.get("type"),
                        "keys": sorted(tool),
                        "function_keys": sorted(tool.get("function", {}))
                        if isinstance(tool.get("function"), dict)
                        else [],
                    }
                    for tool in tools
                    if isinstance(tool, dict)
                ],
                "tool_schemas": [
                    tool.get("function", {}).get("parameters")
                    for tool in tools
                    if isinstance(tool, dict) and isinstance(tool.get("function"), dict)
                ],
                "tool_descriptions": [
                    tool.get("function", {}).get("description")
                    for tool in tools
                    if isinstance(tool, dict) and isinstance(tool.get("function"), dict)
                ],
                "tool_strict_values": [
                    tool.get("function", {}).get("strict")
                    for tool in tools
                    if isinstance(tool, dict) and isinstance(tool.get("function"), dict)
                ],
                "store": request.get("store"),
                "stream_options": request.get("stream_options"),
                "tool_choice": request.get("tool_choice"),
                "authorization_present": bool(self.headers.get("authorization")),
                "message_roles": roles,
                "tool_result_count": tool_result_count,
                "tool_result_names": tool_result_names,
                "contains_synthetic_prompt": contains_synthetic_prompt,
                "contains_search_probe": contains_search_probe,
                "tool_result_content": [
                    {
                        "bytes": len(item.get("content", "").encode("utf-8"))
                        if isinstance(item.get("content"), str)
                        else None,
                        "sha256": hashlib.sha256(item["content"].encode("utf-8")).hexdigest()
                        if isinstance(item.get("content"), str)
                        else None,
                        "tool_call_id": item.get("tool_call_id"),
                    }
                    for item in messages
                    if isinstance(item, dict) and item.get("role") == "tool"
                ],
            }
        )
        _PROVIDER_CALLS += 1
        if (
            names
            and tool_result_count == 0
            and (contains_synthetic_prompt or contains_search_probe)
        ):
            selected = (
                "websearch"
                if contains_search_probe and "websearch" in names
                else next((name for name in names if name.endswith("_workspace_summary")), names[0])
            )
            arguments = (
                json.dumps({"query": "site:nasa.gov Artemis II schedule"}, separators=(",", ":"))
                if selected == "websearch"
                else "{}"
            )
            chunks = [
                {
                    "id": "chatcmpl-probe",
                    "object": "chat.completion.chunk",
                    "created": 1,
                    "model": "assistant-selected",
                    "choices": [
                        {"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}
                    ],
                },
                {
                    "id": "chatcmpl-probe",
                    "object": "chat.completion.chunk",
                    "created": 1,
                    "model": "assistant-selected",
                    "choices": [
                        {
                            "index": 0,
                            "delta": {
                                "tool_calls": [
                                    {
                                        "index": 0,
                                        "id": "call-probe",
                                        "type": "function",
                                        "function": {"name": selected, "arguments": arguments},
                                    }
                                ]
                            },
                            "finish_reason": None,
                        }
                    ],
                },
                {
                    "id": "chatcmpl-probe",
                    "object": "chat.completion.chunk",
                    "created": 1,
                    "model": "assistant-selected",
                    "choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}],
                },
            ]
        else:
            chunks = [
                {
                    "id": "chatcmpl-probe",
                    "object": "chat.completion.chunk",
                    "created": 1,
                    "model": "assistant-selected",
                    "choices": [
                        {
                            "index": 0,
                            "delta": {
                                "role": "assistant",
                                "content": "Synthetic native tool continuation completed.",
                            },
                            "finish_reason": None,
                        }
                    ],
                },
                {
                    "id": "chatcmpl-probe",
                    "object": "chat.completion.chunk",
                    "created": 1,
                    "model": "assistant-selected",
                    "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                },
            ]
        payload = (
            "".join(
                "data: " + json.dumps(chunk, separators=(",", ":")) + "\n\n" for chunk in chunks
            )
            + "data: [DONE]\n\n"
        )
        body = payload.encode()
        self.send_response(200)
        self.send_header("content-type", "text/event-stream")
        self.send_header("cache-control", "no-cache")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, _format: str, *_args: object) -> None:
        return


def _free_port() -> int:
    with socket.socket() as candidate:
        candidate.bind(("127.0.0.1", 0))
        return int(candidate.getsockname()[1])


def _mcp_handler(session_identifier: str) -> type[_McpHandler]:
    return type(
        f"McpHandler{session_identifier[-1]}",
        (_McpHandler,),
        {"_session_identifier": session_identifier},
    )


def _mcp_status(payload: object) -> object:
    if not isinstance(payload, dict):
        return None
    data = payload.get("data")
    if not isinstance(data, list):
        return None
    rows = [row for row in data if isinstance(row, dict) and row.get("name") == "signal-ledger"]
    if len(rows) != 1:
        return None
    status = rows[0].get("status")
    return status.get("status") if isinstance(status, dict) else status


def _native_provider_inventory_summary(
    provider_status: int,
    provider_payload: object,
    auth_status: int,
    auth_payload: object,
) -> dict[str, object]:
    """Retain native provider/auth-method identifiers while dropping all credential fields."""

    provider_data = provider_payload.get("data") if isinstance(provider_payload, dict) else None
    provider_rows = (
        provider_data
        if isinstance(provider_data, list)
        else provider_data.get("all")
        if isinstance(provider_data, dict)
        else None
    )
    provider_ids: list[str] = []
    model_counts: dict[str, int] = {}
    provider_row_keys: set[str] = set()
    if isinstance(provider_rows, list):
        for row in provider_rows[:256]:
            if not isinstance(row, dict):
                continue
            provider_row_keys.update(
                key
                for key in row
                if isinstance(key, str) and re.fullmatch(r"[A-Za-z0-9._-]{1,64}", key)
            )
            provider_id = row.get("id", row.get("providerID"))
            if not isinstance(provider_id, str) or not re.fullmatch(
                r"[A-Za-z0-9._-]{1,128}", provider_id
            ):
                continue
            provider_ids.append(provider_id)
            models = row.get("models")
            if isinstance(models, dict | list):
                model_counts[provider_id] = min(len(models), 4096)
    connected_raw = provider_data.get("connected") if isinstance(provider_data, dict) else None
    connected = (
        sorted(
            value
            for value in connected_raw[:256]
            if isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9._-]{1,128}", value)
        )
        if isinstance(connected_raw, list)
        else []
    )
    auth_data = auth_payload.get("data") if isinstance(auth_payload, dict) else None
    auth_methods: dict[str, list[str]] = {}
    if isinstance(auth_data, dict):
        for provider_id, methods in list(auth_data.items())[:256]:
            if (
                not isinstance(provider_id, str)
                or re.fullmatch(r"[A-Za-z0-9._-]{1,128}", provider_id) is None
                or not isinstance(methods, list)
            ):
                continue
            types = sorted(
                {
                    method.get("type")
                    for method in methods[:32]
                    if isinstance(method, dict)
                    and isinstance(method.get("type"), str)
                    and re.fullmatch(r"[a-z0-9_-]{1,48}", method["type"])
                }
            )
            auth_methods[provider_id] = types
    return {
        "provider_status": provider_status,
        "provider_envelope_keys": (
            sorted(provider_payload) if isinstance(provider_payload, dict) else []
        ),
        "provider_data_type": type(provider_data).__name__,
        "provider_data_keys": sorted(provider_data) if isinstance(provider_data, dict) else [],
        "provider_rows_count": len(provider_rows) if isinstance(provider_rows, list) else 0,
        "provider_row_keys": sorted(provider_row_keys),
        "provider_ids": sorted(set(provider_ids)),
        "provider_model_counts": model_counts,
        "connected_provider_ids": connected,
        "auth_status": auth_status,
        "auth_envelope_keys": sorted(auth_payload) if isinstance(auth_payload, dict) else [],
        "auth_error_code": (
            auth_payload.get("error", {}).get("name")
            if isinstance(auth_payload, dict) and isinstance(auth_payload.get("error"), dict)
            else None
        ),
        "auth_provider_ids": sorted(auth_methods),
        "auth_method_types": auth_methods,
    }


def _reviewed_free_zen_model_id(
    catalog: Mapping[str, object] | None = None,
) -> str:
    """Return only the explicitly selected, reviewed free Zen model."""

    from importlib.resources import files

    if catalog is None:
        catalog = json.loads(
            files("stock_probs.assistant")
            .joinpath("assistant_catalog.json")
            .read_text(encoding="utf-8")
        )
    zen = catalog.get("zen") if isinstance(catalog, Mapping) else None
    if not isinstance(zen, Mapping):
        raise RuntimeError("reviewed_zen_acceptance_model_invalid")

    provider_id = zen.get("provider_id")
    model_suffix = zen.get("native_acceptance_model_id")
    reviewed_models = zen.get("reviewed_models")
    excluded_models = zen.get("excluded_models")
    if (
        provider_id != "opencode-zen"
        or not isinstance(model_suffix, str)
        or _NATIVE_ZEN_COMPONENT.fullmatch(model_suffix) is None
        or not isinstance(reviewed_models, Mapping)
        or not isinstance(excluded_models, Mapping)
        or any(
            not isinstance(excluded_id, str) or not isinstance(reason, str) or not reason
            for excluded_id, reason in excluded_models.items()
        )
    ):
        raise RuntimeError("reviewed_zen_acceptance_model_invalid")

    policy = reviewed_models.get(model_suffix)
    if (
        not isinstance(policy, Mapping)
        or any(excluded_id.casefold() == model_suffix.casefold() for excluded_id in excluded_models)
        or policy.get("available") is not True
        or policy.get("free") is not True
        or policy.get("training") is not False
        or policy.get("data_collection_allowed") is not False
        or policy.get("data_collection_default") is not False
        or policy.get("route") != "openai-compatible"
    ):
        raise RuntimeError("reviewed_zen_acceptance_model_invalid")
    return f"{provider_id}/{model_suffix}"


def _discovered_reviewed_zen_model(models: object, reviewed_model_id: str) -> AssistantModel | None:
    """Return the exact reviewed model only when current discovery still approves it."""

    if not isinstance(models, list | tuple):
        return None
    return next(
        (
            model
            for model in models
            if isinstance(model, AssistantModel)
            and model.model_id == reviewed_model_id
            and model.provider_id == "opencode-zen"
            and model.available is True
            and model.free is True
            and model.training is False
            and model.data_collection_allowed is False
            and model.data_collection_default is False
        ),
        None,
    )


def _synthetic_application_zen_model(terms_reviewed_at: str) -> AssistantModel:
    """Build the synthetic probe model with the provider manager's maintained identity."""

    model_id = _reviewed_free_zen_model_id()
    provider_id, separator, _ = model_id.partition("/")
    definition = AssistantProviderManager._load_definitions().get(provider_id)
    native_provider_id = (
        definition.get("native_provider_id") if isinstance(definition, Mapping) else None
    )
    if (
        not separator
        or not isinstance(definition, Mapping)
        or definition.get("provider_id") != provider_id
        or not isinstance(native_provider_id, str)
    ):
        raise RuntimeError("synthetic_zen_provider_definition_invalid")

    return AssistantModel(
        model_id=model_id,
        provider_id=provider_id,
        display_name="Synthetic local harness model",
        available=True,
        free=True,
        training=False,
        terms_url=str(definition["terms_url"]),
        terms_reviewed_at=terms_reviewed_at,
        policy_version="r120-native-probe-v1",
        disclosure="Synthetic local-only provider used by the native harness.",
        data_collection_allowed=False,
        data_collection_default=False,
        native_provider_id=native_provider_id,
        privacy_policy_version="r120-native-probe-privacy-v1",
        billing_policy_version="r120-native-probe-billing-v1",
        billing_class="free",
        privacy_disclosure="Synthetic local-only provider used by the native harness.",
        cost_disclosure="Synthetic transport; no provider call is made.",
    )


def _loopback_listener_refused(port: int) -> bool:
    """Confirm the owned loopback listener no longer accepts connections."""

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.settimeout(0.25)
            probe.connect(("127.0.0.1", port))
    except OSError as error:
        return error.errno == errno.ECONNREFUSED
    return False


def _application_server_cleanup_projection(
    port: int,
    *,
    server_started: bool,
    thread_started: bool,
    thread_stopped: bool,
) -> dict[str, object]:
    """Project only the owned synthetic app server's port and terminal cleanup facts."""

    port_refused = _loopback_listener_refused(port) if thread_started and thread_stopped else False
    return {
        "app_server_port": port,
        "app_server_started": server_started,
        "app_server_thread_started": thread_started,
        "app_server_thread_stopped": thread_stopped,
        "app_port_refused_after_shutdown": port_refused,
        "owned_app_server_cleanup": (thread_started and thread_stopped and port_refused is True),
    }


def _emit_application_server_cleanup_diagnostic(
    port: int,
    *,
    server_started: bool,
    thread_started: bool,
    thread_stopped: bool,
) -> dict[str, object]:
    """Write one bounded closed-field record and return its cleanup facts."""

    projection = _application_server_cleanup_projection(
        port,
        server_started=server_started,
        thread_started=thread_started,
        thread_stopped=thread_stopped,
    )
    record = {
        "event": "native_app_server_cleanup_v1",
        "app_port": projection["app_server_port"],
        "app_server_started": projection["app_server_started"],
        "app_server_thread_started": projection["app_server_thread_started"],
        "app_server_thread_stopped": projection["app_server_thread_stopped"],
        "app_port_refused_after_shutdown": projection["app_port_refused_after_shutdown"],
        "owned_app_server_cleanup": projection["owned_app_server_cleanup"],
    }
    try:
        sys.stderr.write(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n")
        sys.stderr.flush()
    except (OSError, ValueError):
        pass
    return projection


def _compact_provider_call(row: dict[str, object], *, include_tools: bool) -> dict[str, object]:
    names = row.get("tool_names")
    schemas = row.get("tool_schemas")
    descriptions = row.get("tool_descriptions")
    strict_values = row.get("tool_strict_values")
    declarations: list[dict[str, object]] = []
    if include_tools and all(
        isinstance(items, list) for items in (names, schemas, descriptions, strict_values)
    ):
        for name, schema, description, strict in zip(
            names, schemas, descriptions, strict_values, strict=True
        ):
            declarations.append(
                {
                    "name": name,
                    "description": description,
                    "parameters": schema,
                    "strict": strict,
                }
            )
    result = {
        key: row.get(key)
        for key in (
            "path",
            "model",
            "request_keys",
            "stream",
            "store",
            "stream_options",
            "message_roles",
            "tool_result_count",
            "tool_result_names",
            "contains_synthetic_prompt",
        )
    }
    result["tool_names"] = names
    result["tool_result_receipts"] = row.get("tool_result_content", [])
    if include_tools:
        result["tool_declarations"] = declarations
    return result


def _compact_turn(turn: dict[str, object]) -> dict[str, object]:
    messages = turn.get("messages")
    message_rows = messages.get("messages", []) if isinstance(messages, dict) else []
    return {
        key: turn.get(key)
        for key in (
            "location",
            "attempted",
            "model_ref",
            "session_create_status",
            "prompt_status",
            "wait_status",
            "messages_status",
            "native_terminal_answer",
            "session_state",
            "history_status",
            "log_status",
            "log_content_type",
            "delete_status",
            "post_delete_session_status",
            "post_delete_message_status",
            "post_delete_history_status",
            "post_delete_export_status",
        )
        if key in turn
    } | {
        "messages": [
            {
                "item_keys": row.get("item_keys"),
                "info_keys": row.get("info_keys"),
                "native_type": row.get("native_type"),
                "role": row.get("role"),
                "finish": row.get("finish"),
                "outcome": row.get("outcome"),
                "content_shape": row.get("content_shape"),
                "content_shapes": row.get("content_shapes"),
                "part_types": row.get("part_types"),
                "tool_names": row.get("tool_names"),
                "error_types": row.get("error_types"),
                "text_bytes": row.get("text_bytes"),
            }
            for row in message_rows
            if isinstance(row, dict)
        ],
        "provider_calls": [
            _compact_provider_call(row, include_tools=False)
            for row in turn.get("provider_calls", [])
            if isinstance(row, dict)
        ],
        "mcp_tool_calls": [
            {
                "tool_name": row.get("tool_name"),
                "params_keys": row.get("params_keys"),
                "argument_keys": row.get("argument_keys"),
                "opencode_session_id_present": row.get("opencode_session_id_present"),
                "session_id_matches_expected": row.get("session_id_matches_expected"),
                "synthetic_result": row.get("synthetic_result"),
            }
            for row in turn.get("mcp_calls", [])
            if isinstance(row, dict)
        ],
    }


def _run_native_search_probe(
    client: httpx.Client,
    selected: dict[str, object],
    location: Path,
) -> dict[str, object]:
    """Ask native Exa to run one exact public query and inspect its permission/result envelope."""

    from stock_probs.assistant.runtime import _native_search_text_links
    from stock_probs.assistant.schemas import AssistantTurnContext
    from stock_probs.assistant.search import NativeSearchPermissionBridge

    provider_start = len(_PROVIDER_REQUESTS)
    params = {"location[directory]": str(location)}
    registry_response = client.get("/api/websearch/provider", params=params, timeout=5)
    registry = registry_response.json() if registry_response.status_code == 200 else {}
    rows = registry.get("data") if isinstance(registry, dict) else None
    provider_ids = (
        [
            row.get("id") or row.get("providerID") or row.get("name")
            for row in rows
            if isinstance(row, dict)
        ]
        if isinstance(rows, list)
        else []
    )
    exa_registered = any(str(value).casefold() == "exa" for value in provider_ids)
    result: dict[str, object] = {
        "provider_registry_status": registry_response.status_code,
        "provider_registry_data_type": type(rows).__name__,
        "registered_provider_ids": provider_ids[:16],
        "exa_registered": exa_registered,
    }
    session_response = client.post(
        "/api/session",
        json={
            "title": "Synthetic native Exa feasibility probe",
            "agent": "build",
            "model": {"providerID": selected["providerID"], "id": selected["id"]},
            "location": {"directory": str(location)},
            "permissions": [
                {"action": "*", "resource": "*", "effect": "deny"},
                *[
                    {"action": action, "resource": "*", "effect": "allow"}
                    for action in _TOOL_ACTIONS
                ],
                {"action": "websearch", "resource": "*", "effect": "ask"},
                *[
                    {"action": action, "resource": "*", "effect": "deny"}
                    for action in (
                        "webfetch",
                        "execute",
                        "browser",
                        "subagent",
                        "question",
                        "skill",
                        "plugins",
                    )
                ],
            ],
        },
        timeout=8,
    )
    session_payload = session_response.json() if session_response.content else {}
    data = session_payload.get("data") if isinstance(session_payload, dict) else None
    session_id = data.get("id") if isinstance(data, dict) else None
    result["session_status"] = session_response.status_code
    if not isinstance(session_id, str):
        result["status"] = "native_session_unavailable"
        return result
    _EXPECTED_MCP_SESSIONS.add(session_id)
    prompt_response = client.post(
        f"/api/session/{session_id}/prompt",
        json={
            "text": (
                "NATIVE SEARCH PROBE: Search the public web for site:nasa.gov Artemis II schedule. "
                "Use the native search tool and report a short result."
            )
        },
        timeout=12,
    )
    result["prompt_status"] = prompt_response.status_code
    permission: dict[str, object] | None = None
    permission_deadline = time.monotonic() + 12.0
    while time.monotonic() < permission_deadline:
        response = client.get(f"/api/session/{session_id}/permission", timeout=4)
        payload = response.json() if response.status_code == 200 else {}
        pending = payload.get("data") if isinstance(payload, dict) else None
        if isinstance(pending, list):
            permission = next(
                (
                    row
                    for row in pending
                    if isinstance(row, dict) and row.get("action") == "websearch"
                ),
                None,
            )
            if permission is not None:
                break
        state_response = client.get(f"/api/session/{session_id}", params=params, timeout=4)
        state_payload = state_response.json() if state_response.status_code == 200 else {}
        state_data = state_payload.get("data") if isinstance(state_payload, dict) else {}
        if isinstance(state_data, dict) and state_data.get("outcome") in {
            "failed",
            "interrupted",
        }:
            break
        time.sleep(0.15)
    if permission is None:
        result["permission_observed"] = False
        result["status"] = "permission_unavailable"
    else:
        resources = permission.get("resources")
        query = NativeSearchPermissionBridge._single_query(resources)
        result.update(
            {
                "permission_observed": True,
                "permission_action": permission.get("action"),
                "permission_keys": sorted(permission),
                "permission_session_matches": permission.get("sessionID") == session_id,
                "permission_resource_type": type(resources).__name__,
                "permission_resource_keys": sorted(resources)
                if isinstance(resources, dict)
                else [],
                "permission_query": query,
            }
        )

        async def approved_exact_query(_context, approved_query: str, _emit):
            return approved_query

        async def noop_emit(_event):
            return None

        bridge = NativeSearchPermissionBridge(approved_exact_query)
        decision = asyncio.run(
            bridge.decide(
                context=AssistantTurnContext(
                    user_id=1,
                    app_id="signal-ledger-probe",
                    conversation_id="synthetic-conversation",
                    turn_id="synthetic-turn",
                    execution_id="0" * 32,
                    capability="synthetic-capability",
                    model_id="synthetic/model",
                    policy_version="synthetic-policy-v1",
                    context_version="0" * 64,
                    page_context={},
                    history=(),
                ),
                permission=str(permission.get("action", "")),
                resources=resources,
                emit=noop_emit,
            )
        )
        result["bridge_decision"] = decision.decision
        result["bridge_reason"] = decision.reason
        permission_id = permission.get("id")
        if isinstance(permission_id, str) and decision.decision == "once":
            reply = client.post(
                f"/api/session/{session_id}/permission/{permission_id}/reply",
                json={"decision": "once"},
                timeout=5,
            )
            result["permission_reply_status"] = reply.status_code
        else:
            result["permission_reply_status"] = None
    wait_response = client.post(f"/api/experimental/session/{session_id}/wait", timeout=30)
    result["wait_status"] = wait_response.status_code
    state_response = client.get(f"/api/session/{session_id}", params=params, timeout=5)
    state_payload = state_response.json() if state_response.status_code == 200 else {}
    state = state_payload.get("data") if isinstance(state_payload, dict) else {}
    result["terminal_outcome"] = state.get("outcome") if isinstance(state, dict) else None
    messages_response = client.get(f"/api/session/{session_id}/message", params=params, timeout=5)
    messages_payload = messages_response.json() if messages_response.status_code == 200 else {}
    summary = _session_message_summary(messages_payload)
    messages = messages_payload.get("data") if isinstance(messages_payload, dict) else None
    completed_searches: list[dict[str, object]] = []
    if isinstance(messages, list):
        for message in messages:
            if not isinstance(message, dict):
                continue
            parts = message.get("parts")
            if not isinstance(parts, list):
                parts = message.get("content")
            if not isinstance(parts, list):
                continue
            for part in parts:
                if not isinstance(part, dict) or part.get("type") != "tool":
                    continue
                if part.get("name") != "websearch":
                    continue
                state = part.get("state")
                if not isinstance(state, dict):
                    state = {}
                content = state.get("content")
                text_parts = (
                    [
                        item.get("text")
                        for item in content
                        if isinstance(item, dict)
                        and item.get("type") == "text"
                        and isinstance(item.get("text"), str)
                    ]
                    if isinstance(content, list)
                    else []
                )
                content_bytes = sum(len(text.encode("utf-8")) for text in text_parts)
                source_line_shapes = {
                    "lines_with_https": 0,
                    "bare_or_labeled_url_lines": 0,
                    "embedded_or_ambiguous_url_lines": 0,
                    "markdown_link_lines": 0,
                    "markdown_link_list_item_lines": 0,
                    "markdown_link_prefix_lines": 0,
                    "markdown_link_suffix_lines": 0,
                    "multiple_markdown_link_lines": 0,
                }
                markdown_record_shapes: list[dict[str, object]] = []
                for text in text_parts:
                    lines = text.splitlines()[:4096]
                    for line_index, raw_line in enumerate(lines):
                        line = raw_line.strip()
                        if re.search(r"https://", line, re.IGNORECASE) is None:
                            continue
                        source_line_shapes["lines_with_https"] += 1
                        markdown_links = re.findall(
                            r"\[[^\]\r\n]{1,300}\]\(https://[^\s]+",
                            line,
                            re.IGNORECASE,
                        )
                        if markdown_links:
                            source_line_shapes["markdown_link_lines"] += 1
                            if len(markdown_links) > 1:
                                source_line_shapes["multiple_markdown_link_lines"] += 1
                            if re.match(r"^(?:[-*+]\s+|\d{1,3}[.)]\s+)?\[[^\]]+\]\(https://", line):
                                source_line_shapes["markdown_link_list_item_lines"] += 1
                            link_marker = line.find("](")
                            title_open = line.rfind("[", 0, link_marker) if link_marker >= 0 else -1
                            prefix = line[:title_open].strip() if title_open >= 0 else line
                            closing = line.find(")", link_marker + 2) if link_marker >= 0 else -1
                            suffix = line[closing + 1 :].strip() if closing >= 0 else ""
                            if prefix:
                                source_line_shapes["markdown_link_prefix_lines"] += 1
                            if suffix:
                                source_line_shapes["markdown_link_suffix_lines"] += 1
                            if len(markdown_record_shapes) < 16:
                                prefix_kind = "prose"
                                if not prefix:
                                    prefix_kind = "none"
                                elif re.fullmatch(r"(?:[-*+]\s+|\d{1,3}[.)]\s+)", prefix):
                                    prefix_kind = "list_marker"
                                elif re.fullmatch(
                                    r"(?:source|result|citation)\s*:\s*", prefix, re.I
                                ):
                                    prefix_kind = "source_label"
                                elif re.fullmatch(
                                    r"\*{1,2}[^*\r\n]{1,200}\*{1,2}\s*[:—-]?\s*",
                                    prefix,
                                ):
                                    prefix_kind = "bold_title"
                                elif re.fullmatch(
                                    r"\d{1,3}[.)]\s+\*{1,2}[^*\r\n]{1,200}\*{1,2}\s*[:—-]?\s*",
                                    prefix,
                                ):
                                    prefix_kind = "numbered_bold_title"
                                markdown_record_shapes.append(
                                    {
                                        "prefix_kind": prefix_kind,
                                        "prefix_chars": len(prefix),
                                        "prefix_has_alphanumeric": any(
                                            char.isalnum() for char in prefix
                                        ),
                                        "prefix_codepoints": [ord(char) for char in prefix[:8]],
                                        "anchor_chars": max(0, link_marker - title_open - 1)
                                        if link_marker >= 0 and title_open >= 0
                                        else None,
                                        "suffix_chars": len(suffix),
                                        "previous_line_kind": _search_line_kind(
                                            lines[line_index - 1] if line_index > 0 else ""
                                        ),
                                        "next_line_kind": _search_line_kind(
                                            lines[line_index + 1]
                                            if line_index + 1 < len(lines)
                                            else ""
                                        ),
                                    }
                                )
                        source_row = re.sub(r"^(?:[-*+]\s+|\d{1,3}[.)]\s+)", "", line)
                        labeled = re.fullmatch(
                            r"(?:url|source url)\s*:\s*https://\S+",
                            source_row,
                            re.IGNORECASE,
                        )
                        bare = source_row.casefold().startswith("https://") and not any(
                            character.isspace() for character in source_row
                        )
                        bucket = (
                            "bare_or_labeled_url_lines"
                            if (bare or labeled is not None)
                            and len(source_row.encode("utf-8")) <= 2048
                            else "embedded_or_ambiguous_url_lines"
                        )
                        source_line_shapes[bucket] += 1
                completed_searches.append(
                    {
                        "status": state.get("status"),
                        "native_provider": (
                            state.get("metadata", {}).get("provider")
                            if isinstance(state.get("metadata"), Mapping)
                            and state.get("metadata", {}).get("provider")
                            in {"exa", "firecrawl", "parallel", "tavily"}
                            else None
                        ),
                        "record_boundary": (
                            "unstructured_text"
                            if isinstance(content, list)
                            and text_parts
                            and len(text_parts) == len(content)
                            else "mixed_or_structured"
                        ),
                        "result_bytes": content_bytes,
                        "result_sha256": hashlib.sha256(
                            "\n".join(text_parts).encode("utf-8")
                        ).hexdigest()
                        if text_parts
                        else None,
                        "unverified_links": _native_search_text_links(content),
                        "source_line_shapes": source_line_shapes,
                        "markdown_record_shapes": markdown_record_shapes,
                    }
                )
    completed_search = next(
        (row for row in completed_searches if row.get("status") in {"completed", "success"}),
        None,
    )
    result_bytes = int(completed_search.get("result_bytes", 0)) if completed_search else 0
    link_rows = completed_search.get("unverified_links", []) if completed_search else []
    unverified_link_count = len(link_rows) if isinstance(link_rows, list | tuple) else 0
    retrieved_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    result["search_result"] = {
        "tool_status": completed_search.get("status") if completed_search else None,
        "native_provider": completed_search.get("native_provider") if completed_search else None,
        "record_boundary": completed_search.get("record_boundary") if completed_search else None,
        "completed_tool_count": sum(
            1 for row in completed_searches if row.get("status") in {"completed", "success"}
        ),
        "tool_error_count": sum(
            1 for row in completed_searches if row.get("status") in {"error", "failed"}
        ),
        "result_bytes": result_bytes,
        "nonempty_result": result_bytes > 0,
        "result_sha256": completed_search.get("result_sha256") if completed_search else None,
        "unverified_link_count": unverified_link_count,
        "unverified_links": link_rows,
        "source_line_shapes": completed_search.get("source_line_shapes", {})
        if completed_search
        else {},
        "markdown_record_shapes": completed_search.get("markdown_record_shapes", [])
        if completed_search
        else [],
        "native_observed_at": retrieved_at,
        "published_at": None,
        "as_of": None,
    }
    result["messages_status"] = messages_response.status_code
    result["native_message_summary"] = [
        {
            "native_type": row.get("native_type"),
            "finish": row.get("finish"),
            "outcome": row.get("outcome"),
            "content_shapes": row.get("content_shapes"),
            "tool_details": row.get("tool_details"),
            "tool_names": row.get("tool_names"),
            "error_types": row.get("error_types"),
            "text_bytes": row.get("text_bytes"),
        }
        for row in summary.get("messages", [])
        if isinstance(row, dict)
    ]
    provider_rows = _PROVIDER_REQUESTS[provider_start:]
    result["synthetic_model_calls"] = [
        {
            "model": row.get("model"),
            "store": row.get("store"),
            "stream": row.get("stream"),
            "message_roles": row.get("message_roles"),
            "tool_result_count": row.get("tool_result_count"),
            "tool_result_names": row.get("tool_result_names"),
        }
        for row in provider_rows
    ]
    result["synthetic_continuation_observed"] = any(
        row.get("tool_result_count", 0) > 0
        and isinstance(row.get("message_roles"), list)
        and "tool" in row.get("message_roles", [])
        for row in provider_rows
    )
    result["synthetic_model_answer_nonempty"] = bool(summary.get("expected_synthetic_answer"))
    # The pinned V2 message-list response places text under info.content for flat message rows;
    # it does not expose the legacy parts[].text counter here. Count only the exact synthetic
    # answer marker already observed by the structural walker, never raw answer text.
    result["synthetic_model_answer_bytes"] = (
        len(b"Synthetic native tool continuation completed.")
        if summary.get("expected_synthetic_answer")
        else 0
    )
    result["delete_status"] = client.delete(
        f"/api/session/{session_id}", params=params, timeout=5
    ).status_code
    if result.get("permission_observed") is not True:
        return result
    if result.get("bridge_decision") != "once" or query is None:
        result["status"] = "permission_rejected_by_bridge"
    elif (
        result.get("terminal_outcome") == "succeeded"
        and completed_search is not None
        and result_bytes > 0
        and unverified_link_count > 0
        and not any(row.get("error_types") for row in result["native_message_summary"])
    ):
        result["status"] = "native_search_completed"
    elif any(row.get("status") in {"error", "failed"} for row in completed_searches):
        result["status"] = "search_tool_returned_error"
    else:
        result["status"] = "native_search_failed"
    return result


def _search_line_kind(value: str) -> str:
    """Classify adjacent public-result lines without retaining titles or snippets."""

    line = value.strip()
    if not line:
        return "blank"
    if re.match(r"^#{1,6}\s+", line):
        return "heading"
    if re.match(r"^(?:[-*+]\s+|\d{1,3}[.)]\s+)", line):
        return "list"
    if re.search(r"https://", line, re.IGNORECASE):
        return "link"
    return "text"


def _session_log_summary(content: bytes, session_id: str) -> dict[str, object]:
    entries: list[dict[str, object]] = []
    event_name = ""
    data_lines: list[bytes] = []
    foreign_session_ids: set[str] = set()
    for raw_line in content.splitlines():
        if raw_line.startswith(b"event:"):
            event_name = raw_line[6:].decode("utf-8", "replace").strip()
        elif raw_line.startswith(b"data:"):
            data_lines.append(raw_line[5:].lstrip())
        elif not raw_line and data_lines:
            try:
                event = json.loads(b"\n".join(data_lines))
            except (UnicodeDecodeError, json.JSONDecodeError):
                event = {}
            if isinstance(event, dict):
                properties = event.get("properties")
                properties = properties if isinstance(properties, dict) else event
                identities: list[object] = []
                for holder in (event, properties):
                    for key in ("sessionID", "sessionId"):
                        if key in holder:
                            identities.append(holder[key])
                message = properties.get("message")
                if isinstance(message, dict):
                    for key in ("sessionID", "sessionId"):
                        if key in message:
                            identities.append(message[key])
                part = properties.get("part")
                if isinstance(part, dict):
                    for key in ("sessionID", "sessionId"):
                        if key in part:
                            identities.append(part[key])
                foreign_session_ids.update(
                    value for value in identities if isinstance(value, str) and value != session_id
                )
                part_state = part.get("state") if isinstance(part, dict) else None
                entries.append(
                    {
                        "event": event.get("type") or event_name,
                        "envelope_keys": sorted(event),
                        "properties_keys": sorted(properties),
                        "session_identity_paths": [
                            path
                            for path, holder in (
                                ("event", event),
                                ("properties", properties),
                                ("properties.message", message),
                                ("properties.part", part),
                            )
                            if isinstance(holder, dict)
                            and any(key in holder for key in ("sessionID", "sessionId"))
                        ],
                        "part_type": part.get("type") if isinstance(part, dict) else None,
                        "part_name": part.get("name") if isinstance(part, dict) else None,
                        "part_status": part_state.get("status")
                        if isinstance(part_state, dict)
                        else None,
                        "delta_field": properties.get("field"),
                        "delta_bytes": len(properties.get("delta", "").encode("utf-8"))
                        if isinstance(properties.get("delta"), str)
                        else None,
                    }
                )
            event_name = ""
            data_lines = []
    return {
        "event_count": len(entries),
        "events": entries,
        "foreign_session_ids": sorted(foreign_session_ids),
        "all_present_session_ids_match": not foreign_session_ids,
    }


def _session_history_summary(payload: object, session_id: str) -> dict[str, object]:
    if not isinstance(payload, dict):
        return {"shape": type(payload).__name__, "events": []}
    rows = payload.get("data")
    if not isinstance(rows, list):
        return {"shape": type(rows).__name__, "events": []}
    events: list[dict[str, object]] = []
    foreign_ids: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        identities: list[object] = []
        holders: list[tuple[str, object]] = [("event", row)]
        for key in ("properties", "payload", "data"):
            nested = row.get(key)
            if isinstance(nested, dict):
                holders.append((key, nested))
                for child_key in ("message", "part", "delta", "tool", "assistantMessage"):
                    child = nested.get(child_key)
                    if isinstance(child, dict):
                        holders.append((f"{key}.{child_key}", child))
        for _path, holder in holders:
            if isinstance(holder, dict):
                for key in ("sessionID", "sessionId", "aggregateID"):
                    value = holder.get(key)
                    if isinstance(value, str):
                        identities.append(value)
                        if key != "aggregateID" and value != session_id:
                            foreign_ids.add(value)
        properties = row.get("properties")
        properties = properties if isinstance(properties, dict) else {}
        part = properties.get("part") if isinstance(properties.get("part"), dict) else {}
        delta = properties.get("delta")
        events.append(
            {
                "type": row.get("type"),
                "seq": row.get("seq"),
                "event_keys": sorted(row),
                "properties_keys": sorted(properties),
                "session_identity_paths": [
                    path
                    for path, holder in holders
                    if isinstance(holder, dict)
                    and any(key in holder for key in ("sessionID", "sessionId"))
                ],
                "identity_count": len(identities),
                "part_type": part.get("type"),
                "part_name": part.get("name"),
                "part_status": (part.get("state") or {}).get("status")
                if isinstance(part.get("state"), dict)
                else None,
                "delta_field": properties.get("field"),
                "delta_bytes": len(delta.encode("utf-8")) if isinstance(delta, str) else None,
            }
        )
    return {
        "event_count": len(events),
        "has_more": payload.get("hasMore"),
        "events": events,
        "foreign_session_ids": sorted(foreign_ids),
        "all_present_session_ids_match": not foreign_ids,
    }


def _session_message_summary(payload: object) -> dict[str, object]:
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, list):
        return {"shape": type(data).__name__, "messages": []}
    messages: list[dict[str, object]] = []
    answer = None

    def summarize_tool_output(value: object) -> dict[str, object]:
        if isinstance(value, str):
            encoded = value.encode("utf-8")
            result: dict[str, object] = {
                "type": "str",
                "bytes": len(encoded),
                "sha256": hashlib.sha256(encoded).hexdigest(),
            }
            if len(encoded) > 65_536:
                return result
            try:
                value = json.loads(value)
            except json.JSONDecodeError:
                return result
        else:
            result = {"type": type(value).__name__}
        rows: list[object] = []
        if isinstance(value, dict):
            result["keys"] = sorted(value)
            for key in ("results", "sources", "items", "data"):
                candidate = value.get(key)
                if isinstance(candidate, list):
                    rows = candidate[:32]
                    result["row_collection_field"] = key
                    result["row_count"] = len(candidate)
                    break
        elif isinstance(value, list):
            rows = value[:32]
            result["row_count"] = len(value)
        sources: list[dict[str, object]] = []
        for row in rows[:16]:
            if not isinstance(row, dict):
                continue
            url = row.get("url") or row.get("link")
            try:
                parsed = urlsplit(url) if isinstance(url, str) else None
                host = parsed.hostname if parsed is not None else None
                scheme = parsed.scheme if parsed is not None else None
            except ValueError:
                host, scheme = None, None
            title = row.get("title")
            sources.append(
                {
                    "keys": sorted(row),
                    "url_field": "url"
                    if isinstance(row.get("url"), str)
                    else ("link" if isinstance(row.get("link"), str) else None),
                    "url_scheme": scheme,
                    "url_host": host,
                    "title_bytes": len(title.encode("utf-8")) if isinstance(title, str) else None,
                    "date_fields": [
                        key
                        for key in (
                            "publishedDate",
                            "published_at",
                            "publishedAt",
                            "retrievedAt",
                            "retrieved_at",
                            "date",
                        )
                        if key in row
                    ],
                }
            )
        result["source_rows"] = sources
        return result

    def summarize_tool_content(value: object) -> dict[str, object]:
        parts = value if isinstance(value, list) else [value]
        text_parts = [
            item
            for item in parts
            if isinstance(item, dict)
            and item.get("type") == "text"
            and isinstance(item.get("text"), str)
        ]
        text_values = [item["text"] for item in text_parts]
        encoded = "\n".join(text_values).encode("utf-8")
        candidates: list[str] = []
        for text_value in text_values:
            candidates.extend(
                match.rstrip(".,;:!?") for match in re.findall(r"https?://[^\s<>()\"]+", text_value)
            )
        safe_urls: list[dict[str, object]] = []
        for candidate in candidates[:24]:
            try:
                parsed = urlsplit(candidate)
            except ValueError:
                continue
            if (
                parsed.scheme != "https"
                or not parsed.hostname
                or parsed.username
                or parsed.password
            ):
                continue
            safe_urls.append(
                {
                    "url": urlunsplit(("https", parsed.netloc, parsed.path, "", ""))[:512],
                    "host": parsed.hostname[:253],
                }
            )
        text_part_shapes: list[dict[str, object]] = []
        for text_value in text_values[:16]:
            lines = text_value.splitlines()[:4096]
            fenced: str | None = None
            headings_outside_fence = 0
            headings_inside_fence = 0
            headings_after_blank = 0
            headings_after_body = 0
            previous_line_blank = True
            fence_lines = 0
            for line in lines:
                fence = re.match(r"^[ \t]{0,3}(`{3,}|~{3,})", line)
                if fence is not None:
                    marker = fence.group(1)[0]
                    fenced = None if fenced == marker else (marker if fenced is None else fenced)
                    previous_line_blank = False
                    fence_lines += 1
                    continue
                heading_link = re.fullmatch(r"## \[[^\]\r\n]{1,300}\]\(https://.*\)", line)
                if heading_link is not None:
                    if fenced is None:
                        headings_outside_fence += 1
                        if previous_line_blank:
                            headings_after_blank += 1
                        else:
                            headings_after_body += 1
                    else:
                        headings_inside_fence += 1
                if fenced is not None:
                    previous_line_blank = not line.strip()
                elif not line:
                    previous_line_blank = True
                else:
                    previous_line_blank = False
            nonblank_lines = [line for line in lines if line.strip()]
            text_part_shapes.append(
                {
                    "bytes": len(text_value.encode("utf-8")),
                    "line_count": len(lines),
                    "first_nonblank_line_kind": _search_line_kind(
                        nonblank_lines[0] if nonblank_lines else ""
                    ),
                    "textual_heading_links_outside_fences": headings_outside_fence,
                    "textual_heading_links_inside_fences": headings_inside_fence,
                    "heading_links_after_blank": headings_after_blank,
                    "heading_links_after_body": headings_after_body,
                    "code_fence_boundary_lines": fence_lines,
                }
            )
        return {
            "type": type(value).__name__,
            "part_count": len(parts),
            "part_keys": [sorted(item) for item in parts[:16] if isinstance(item, dict)],
            "record_boundary": "unstructured_text",
            "text_part_count": len(text_parts),
            "text_part_shapes": text_part_shapes,
            "text_bytes": len(encoded),
            "text_sha256": hashlib.sha256(encoded).hexdigest() if encoded else None,
            "https_citations": safe_urls,
            "citation_count": len(safe_urls),
        }

    def describe_content(value: object) -> tuple[object, int, bool, list[object]]:
        shapes: list[object] = []
        byte_count = 0
        expected_answer = False
        tool_details: list[dict[str, object]] = []

        def visit(item: object) -> None:
            nonlocal byte_count, expected_answer
            if isinstance(item, str):
                byte_count += len(item.encode("utf-8"))
                if item == "Synthetic native tool continuation completed.":
                    expected_answer = True
                return
            if isinstance(item, dict):
                shapes.append(
                    {
                        "type": item.get("type"),
                        "keys": sorted(item),
                        "name": item.get("name") if isinstance(item.get("name"), str) else None,
                        "status": item.get("status")
                        if isinstance(item.get("status"), str)
                        else None,
                    }
                )
                if item.get("type") == "tool":
                    state = item.get("state")
                    state = state if isinstance(state, dict) else {}
                    metadata = state.get("metadata")
                    metadata = metadata if isinstance(metadata, Mapping) else {}
                    native_provider = metadata.get("provider")
                    tool_details.append(
                        {
                            "name": item.get("name"),
                            "state_keys": sorted(state),
                            "status": state.get("status"),
                            "native_provider": native_provider
                            if native_provider in {"exa", "firecrawl", "parallel", "tavily"}
                            else None,
                            "input_keys": sorted(state.get("input", {}))
                            if isinstance(state.get("input"), dict)
                            else [],
                            "output": summarize_tool_output(state.get("output"))
                            if "output" in state
                            else None,
                            "metadata": summarize_tool_output(state.get("metadata"))
                            if "metadata" in state
                            else None,
                            "content": summarize_tool_content(state.get("content"))
                            if "content" in state
                            else None,
                        }
                    )
                for key, nested in item.items():
                    if key in {"text", "content", "output", "result"}:
                        visit(nested)
                return
            if isinstance(item, list):
                for nested in item:
                    visit(nested)

        visit(value)
        # The native flat message protocol stores tool detail inside content parts. Expose only
        # bounded keys, status, public URL hosts, hashes, and presence of date fields.
        content_tools[:] = tool_details
        return type(value).__name__, byte_count, expected_answer, shapes

    for item in data:
        if not isinstance(item, dict):
            continue
        info = item.get("info") if isinstance(item.get("info"), dict) else item
        parts = item.get("parts") if isinstance(item.get("parts"), list) else []
        nested_message = info.get("message") if isinstance(info.get("message"), dict) else {}
        native_error = info.get("error")
        if isinstance(native_error, Mapping):
            raw_error_message = native_error.get("message")
            error_summary: dict[str, object] | None = {
                "keys": sorted(native_error),
                "name": native_error.get("name")
                if isinstance(native_error.get("name"), str)
                else None,
                "type": native_error.get("type")
                if isinstance(native_error.get("type"), str)
                else None,
                "code": native_error.get("code")
                if isinstance(native_error.get("code"), str | int)
                else None,
                "status": native_error.get("status")
                if type(native_error.get("status")) is int
                else None,
                "message_bytes": len(raw_error_message.encode("utf-8"))
                if isinstance(raw_error_message, str)
                else None,
                "message_sha256": hashlib.sha256(raw_error_message.encode("utf-8")).hexdigest()
                if isinstance(raw_error_message, str)
                else None,
            }
        else:
            error_summary = None
        content_tools: list[dict[str, object]] = []
        content_shape, content_bytes, has_expected_answer, content_shapes = describe_content(
            info.get("content")
        )
        if has_expected_answer:
            answer = "Synthetic native tool continuation completed."
        summary: dict[str, object] = {
            "item_keys": sorted(item),
            "info_keys": sorted(info),
            "native_type": info.get("type"),
            "finish": info.get("finish"),
            "raw_finish": info.get("rawFinish"),
            "outcome": info.get("outcome"),
            "role": info.get("role") or nested_message.get("role"),
            "sessionID": info.get("sessionID") or nested_message.get("sessionID"),
            "content_shape": content_shape,
            "content_bytes": content_bytes,
            "content_sha256": hashlib.sha256(
                json.dumps(info.get("content"), sort_keys=True, default=str).encode("utf-8")
            ).hexdigest()
            if "content" in info
            else None,
            "content_shapes": content_shapes,
            "tool_details": content_tools,
            "part_types": [],
            "tool_names": [],
            "error_types": [],
            "native_error": error_summary,
        }
        part_types: list[object] = []
        tool_names: list[object] = []
        error_types: list[object] = []
        for part in parts:
            if not isinstance(part, dict):
                continue
            part_type = part.get("type")
            part_types.append(part_type)
            if part_type == "tool":
                tool_names.append(part.get("name"))
            if part_type == "text" and isinstance(part.get("text"), str):
                text = part["text"]
                if text == "Synthetic native tool continuation completed.":
                    answer = text
                summary.setdefault("text_sha256", hashlib.sha256(text.encode()).hexdigest())
                summary["text_bytes"] = int(summary.get("text_bytes", 0)) + len(
                    text.encode("utf-8")
                )
            if part_type == "step-start" or part_type == "step-finish":
                continue
            if part_type == "error":
                error = part.get("error")
                error_types.append(
                    error.get("name") if isinstance(error, dict) else type(error).__name__
                )
        summary["part_keys"] = [sorted(part) for part in parts if isinstance(part, dict)]
        summary["part_types"] = part_types
        summary["tool_names"] = tool_names
        summary["error_types"] = error_types
        messages.append(summary)
    return {"shape": "list", "messages": messages, "expected_synthetic_answer": answer}


def _binary() -> Path:
    for candidate in _BINARY_CANDIDATES:
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return candidate
    raise RuntimeError("Pinned OpenCode V2.0.7 binary is unavailable")


def _write_location_config(location: Path, mcp_url: str, provider_url: str) -> None:
    config = _fixed_location_config(
        proxy_base_url=provider_url,
        proxy_capability="synthetic-provider-capability-" + location.name,
        mcp_url=mcp_url,
        mcp_capability="synthetic-mcp-capability-" + location.name,
    )
    (location / "opencode.json").write_text(
        json.dumps(config, ensure_ascii=True, separators=(",", ":")), encoding="utf-8"
    )


def _generated_config_summary(document: dict[str, object]) -> dict[str, object]:
    providers = document.get("providers")
    proxy = providers.get("assistant-proxy") if isinstance(providers, dict) else None
    models = proxy.get("models") if isinstance(proxy, dict) else None
    mcp = document.get("mcp")
    servers = mcp.get("servers") if isinstance(mcp, dict) else None
    server = servers.get("signal-ledger") if isinstance(servers, dict) else None
    return {
        "top_level_keys": sorted(document),
        "permission_actions": [
            row.get("action") for row in document.get("permissions", []) if isinstance(row, dict)
        ],
        "provider_id": "assistant-proxy" if isinstance(proxy, dict) else None,
        "provider_keys": sorted(proxy) if isinstance(proxy, dict) else [],
        "provider_enabled_field_present": (
            "enabled" in proxy if isinstance(proxy, dict) else False
        ),
        "provider_package": proxy.get("package") if isinstance(proxy, dict) else None,
        "provider_settings_keys": sorted(proxy.get("settings", {}))
        if isinstance(proxy, dict) and isinstance(proxy.get("settings"), dict)
        else [],
        "provider_header_names": sorted(proxy.get("headers", {}))
        if isinstance(proxy, dict) and isinstance(proxy.get("headers"), dict)
        else [],
        "model_alias": next(iter(models), None) if isinstance(models, dict) else None,
        "mcp_server_keys": sorted(server) if isinstance(server, dict) else [],
        "mcp_enabled_field_present": "enabled" in server if isinstance(server, dict) else False,
        "mcp_header_names": sorted(server.get("headers", {}))
        if isinstance(server, dict) and isinstance(server.get("headers"), dict)
        else [],
    }


def _scan_synthetic_storage(
    home: Path,
    tmpdir: Path | None = None,
    *,
    markers: Mapping[str, bytes] | None = None,
) -> dict[str, object]:
    """Search only disposable native state for the exact synthetic prompt and result markers."""

    markers = markers or {
        "prompt": b"Use the synthetic workspace summary tool and then answer.",
        "tool_result": b"synthetic tool result",
        "assistant_answer": b"Synthetic native tool continuation completed.",
    }
    markers = {label: marker for label, marker in markers.items() if marker}
    scanned_files = 0
    scanned_bytes = 0
    occurrences = dict.fromkeys(markers, 0)
    oversized_files = 0
    roots = [home]
    if tmpdir is not None and not tmpdir.is_relative_to(home):
        roots.append(tmpdir)
    for root_path in roots:
        for root, _directories, filenames in os.walk(root_path):
            for filename in filenames:
                path = Path(root) / filename
                try:
                    if path.is_symlink() or not path.is_file():
                        continue
                    size = path.stat().st_size
                    if size > 16 * 1024 * 1024 or scanned_bytes + size > 64 * 1024 * 1024:
                        oversized_files += 1
                        continue
                    content = path.read_bytes()
                except OSError:
                    continue
                scanned_files += 1
                scanned_bytes += len(content)
                for label, marker in markers.items():
                    occurrences[label] += content.count(marker)
    return {
        "files_scanned": scanned_files,
        "bytes_scanned": scanned_bytes,
        "oversized_files_skipped": oversized_files,
        "synthetic_marker_occurrences": occurrences,
        "marker_sha256": {
            label: hashlib.sha256(marker).hexdigest() for label, marker in markers.items()
        },
    }


class _ProbeRuntimeSupervisor:
    """Exercise the native runtime against a loopback app and disposable worker home."""

    def __init__(self, binary: Path, home: Path, location_root: Path, environment: dict[str, str]):
        self.binary = binary
        self.home = home
        self.location_root = location_root
        self.environment = dict(environment)
        self.process: subprocess.Popen[bytes] | None = None
        self.password = ""
        self.locations: set[str] = set()
        self.purge_states: dict[str, str] = {}
        self._lock = threading.RLock()
        self._launch_worker()

    def _launch_worker(self) -> None:
        self.password = secrets.token_urlsafe(36)
        self.environment["OPENCODE_SERVER_PASSWORD"] = self.password
        self.process = subprocess.Popen(  # noqa: S603 - fixed local binary from source.
            [str(self.binary), "serve", "--hostname", "127.0.0.1", "--port", "4097"],
            cwd=self.location_root,
            env=self.environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
        )
        deadline = time.monotonic() + 15.0
        with httpx.Client(
            base_url="http://127.0.0.1:4097",
            auth=("opencode", self.password),
            timeout=httpx.Timeout(1.0, connect=0.5),
            trust_env=False,
        ) as client:
            while time.monotonic() < deadline:
                if self.process.poll() is not None:
                    raise RuntimeError("application native worker exited before readiness")
                try:
                    response = client.get("/api/info")
                    if response.status_code == 200:
                        return
                except httpx.HTTPError:
                    time.sleep(0.1)
        raise RuntimeError("application native worker readiness timed out")

    def _stop_worker(self) -> None:
        process, self.process = self.process, None
        if process is None:
            return
        process.terminate()
        try:
            process.wait(timeout=3.0)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=3.0)

    def _purge_and_restart(self, purge_id: str) -> None:
        with self._lock:
            if self.locations:
                self.purge_states[purge_id] = "pending"
                return
            self.purge_states[purge_id] = "pending"
            try:
                self._stop_worker()
                shutil.rmtree(self.home)
                for directory in ("config", "data", "cache", "tmp"):
                    (self.home / directory).mkdir(parents=True, mode=0o700)
                self._launch_worker()
            except Exception:
                self.purge_states[purge_id] = "failed"
                raise
            self.purge_states[purge_id] = "cleared"

    async def status(self) -> dict[str, object]:
        process = self.process
        return {
            "status": "ready" if process is not None and process.poll() is None else "unavailable",
            "api_url": "http://127.0.0.1:4097",
            "api_password": self.password,
        }

    async def prepare_location(self, **values: str) -> dict[str, str]:
        execution_id = values["execution_id"]
        location = self.location_root / execution_id
        location.mkdir(mode=0o700)
        document = _fixed_location_config(
            proxy_base_url=values["proxy_base_url"],
            proxy_capability=values["proxy_capability"],
            mcp_url=values["mcp_url"],
            mcp_capability=values["mcp_capability"],
            adapter_id=values["adapter_id"],
            native_provider_id=values["native_provider_id"],
        )
        (location / "opencode.json").write_text(
            json.dumps(document, ensure_ascii=True, separators=(",", ":")), encoding="utf-8"
        )
        with self._lock:
            self.locations.add(execution_id)
        return {"directory": str(location)}

    async def remove_location(self, execution_id: str) -> str | None:
        location = self.location_root / execution_id
        shutil.rmtree(location, ignore_errors=True)
        with self._lock:
            self.locations.discard(execution_id)
            if self.locations:
                return None
        purge_id = secrets.token_hex(16)
        await asyncio.to_thread(self._purge_and_restart, purge_id)
        return purge_id

    async def request_home_purge(self) -> str:
        purge_id = secrets.token_hex(16)
        await asyncio.to_thread(self._purge_and_restart, purge_id)
        return purge_id

    async def home_purge_status(self, purge_id: str) -> str:
        return self.purge_states.get(purge_id, "failed")

    async def wait_for_home_purge(self, purge_id: str, *, timeout: float = 20.0) -> bool:
        del timeout
        return await self.home_purge_status(purge_id) == "cleared"

    async def disable(self, _reason: str) -> None:
        await asyncio.to_thread(self._stop_worker)


def _sse_chunk(value: dict[str, object]) -> bytes:
    return b"data: " + json.dumps(value, separators=(",", ":")).encode("utf-8") + b"\n\n"


def _native_zen_identity_projection(
    user_agents: list[str],
    clients: list[str],
    *,
    native_sessions: list[str] | None = None,
    native_projects: list[str] | None = None,
    session_affinities: list[str] | None = None,
    session_id_aliases: list[str] | None = None,
    expected_session: str | None = None,
    expected_project: str | None = None,
) -> dict[str, bool]:
    """Project native identity fields to closed booleans without retaining values."""

    user_agent = user_agents[0] if len(user_agents) == 1 else None
    client = clients[0] if len(clients) == 1 else None
    user_agent_parts: list[str] = []
    user_agent_valid = False
    if (
        isinstance(user_agent, str)
        and user_agent.isascii()
        and len(user_agent) <= _NATIVE_ZEN_USER_AGENT_MAX
        and not any(ord(character) < 0x20 or ord(character) == 0x7F for character in user_agent)
    ):
        user_agent_parts = user_agent.split("/")
        user_agent_valid = (
            len(user_agent_parts) == 4
            and user_agent_parts[0] == "opencode"
            and all(
                _NATIVE_ZEN_COMPONENT.fullmatch(part) is not None for part in user_agent_parts[1:]
            )
        )
    client_valid = (
        isinstance(client, str)
        and client.isascii()
        and _NATIVE_ZEN_COMPONENT.fullmatch(client) is not None
    )
    projection = {
        "user_agent_present": bool(user_agents),
        "user_agent_unique": len(user_agents) == 1,
        "user_agent_shape_valid": user_agent_valid,
        "client_present": bool(clients),
        "client_unique": len(clients) == 1,
        "client_shape_valid": client_valid,
        "client_matches_user_agent": bool(
            user_agent_valid and client_valid and user_agent_parts[-1] == client
        ),
    }
    if all(
        value is None
        for value in (
            native_sessions,
            native_projects,
            session_affinities,
            session_id_aliases,
            expected_session,
            expected_project,
        )
    ):
        return projection

    sessions = native_sessions or []
    projects = native_projects or []
    affinities = session_affinities or []
    session_ids = session_id_aliases or []
    session = sessions[0] if len(sessions) == 1 else None
    project = projects[0] if len(projects) == 1 else None
    session_valid = (
        isinstance(session, str)
        and session.isascii()
        and _NATIVE_OPENCODE_SESSION_ID.fullmatch(session) is not None
    )
    project_valid = (
        isinstance(project, str)
        and project not in {"", ".", ".."}
        and len(project) <= _NATIVE_PROJECT_ID_MAX
        and project.isascii()
        and project.strip() == project
        and all(0x21 <= ord(character) <= 0x7E for character in project)
        and "/" not in project
        and "\\" not in project
    )
    aliases = [*affinities, *session_ids]
    aliases_valid = all(value == session for value in aliases)
    return {
        **projection,
        "native_session_present": bool(sessions),
        "native_session_unique": len(sessions) == 1,
        "native_session_shape_valid": session_valid,
        "native_session_matches_active": session_valid and session == expected_session,
        "native_project_present": bool(projects),
        "native_project_unique": len(projects) == 1,
        "native_project_shape_valid": project_valid,
        "native_project_matches_active": project_valid and project == expected_project,
        "session_aliases_match_native": bool(session_valid and aliases_valid),
        "session_affinity_present": bool(affinities),
        "session_affinity_unique": len(affinities) == 1 if affinities else True,
        "session_id_alias_present": bool(session_ids),
        "session_id_alias_unique": len(session_ids) == 1 if session_ids else True,
    }


async def _synthetic_application_provider_stream(
    _url: str,
    *,
    headers: dict[str, str],
    body: bytes,
    timeout_seconds: float,
    max_response_bytes: int,
):
    """Keep the real ProviderManager contract while replacing only its external transport."""

    del timeout_seconds, max_response_bytes
    request = json.loads(body)
    messages = request.get("messages", [])
    tools = request.get("tools", [])
    names = [
        item.get("function", {}).get("name")
        for item in tools
        if isinstance(item, dict) and isinstance(item.get("function"), dict)
    ]
    tool_results = [
        item for item in messages if isinstance(item, dict) and item.get("role") == "tool"
    ]
    (
        expected_user_agent,
        expected_client,
        expected_session,
        expected_project,
        expected_affinity,
        expected_session_id_alias,
    ) = _NATIVE_ZEN_EXPECTED_IDENTITY.get()
    _APP_PROVIDER_CALLS.append(
        {
            "model": request.get("model"),
            "store": request.get("store"),
            "stream": request.get("stream"),
            "stream_options": request.get("stream_options"),
            "request_keys": sorted(request),
            "tool_names": names,
            "message_roles": [item.get("role") for item in messages if isinstance(item, dict)],
            "tool_result_count": len(tool_results),
            "tool_result_receipts": [
                {
                    "bytes": len(item.get("content", "").encode("utf-8"))
                    if isinstance(item.get("content"), str)
                    else None,
                    "sha256": hashlib.sha256(item["content"].encode()).hexdigest()
                    if isinstance(item.get("content"), str)
                    else None,
                }
                for item in tool_results
            ],
            "authorization_present": any(
                key.casefold() == "authorization" and bool(value) for key, value in headers.items()
            ),
            "native_user_agent_forwarded": (
                expected_user_agent is not None and headers.get("user-agent") == expected_user_agent
            ),
            "native_client_forwarded": (
                expected_client is not None and headers.get("x-opencode-client") == expected_client
            ),
            "native_session_forwarded": (
                expected_session is not None
                and headers.get("x-opencode-session") == expected_session
            ),
            "native_project_forwarded": (
                expected_project is not None
                and headers.get("x-opencode-project") == expected_project
            ),
            "native_affinity_matches": (headers.get("x-session-affinity") == expected_affinity),
            "native_session_id_alias_matches": (
                headers.get("x-session-id") == expected_session_id_alias
            ),
        }
    )
    if not tool_results:
        selected = next((name for name in names if name == "signal-ledger_workspace_summary"), None)
        if selected is None:
            raise RuntimeError("native app request omitted exact workspace summary declaration")
        values = [
            {
                "id": "chatcmpl-app-probe",
                "object": "chat.completion.chunk",
                "created": 1,
                "model": request.get("model"),
                "choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}],
            },
            {
                "id": "chatcmpl-app-probe",
                "object": "chat.completion.chunk",
                "created": 1,
                "model": request.get("model"),
                "choices": [
                    {
                        "index": 0,
                        "delta": {
                            "tool_calls": [
                                {
                                    "index": 0,
                                    "id": "app-probe-call",
                                    "type": "function",
                                    "function": {"name": selected, "arguments": "{}"},
                                }
                            ]
                        },
                        "finish_reason": None,
                    }
                ],
            },
            {
                "id": "chatcmpl-app-probe",
                "object": "chat.completion.chunk",
                "created": 1,
                "model": request.get("model"),
                "choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}],
            },
        ]
    else:
        if not _APP_CONTINUATION_WAITING.is_set():
            _APP_CONTINUATION_WAITING.set()
            if not await asyncio.to_thread(_APP_CONTINUE.wait, 25.0):
                raise RuntimeError("synthetic application provider release timed out")
        values = [
            {
                "id": "chatcmpl-app-probe",
                "object": "chat.completion.chunk",
                "created": 1,
                "model": request.get("model"),
                "choices": [
                    {
                        "index": 0,
                        "delta": {
                            "role": "assistant",
                            "content": "Synthetic native application turn completed.",
                        },
                        "finish_reason": None,
                    }
                ],
            },
            {
                "id": "chatcmpl-app-probe",
                "object": "chat.completion.chunk",
                "created": 1,
                "model": request.get("model"),
                "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
            },
        ]
    for value in values:
        yield _sse_chunk(value)
    yield b"data: [DONE]\n\n"


def _with_native_zen_identity(
    upstream: AsyncIterator[bytes],
    user_agent: str | None,
    client: str | None,
    native_session: str | None = None,
    native_project: str | None = None,
    session_affinity: str | None = None,
    session_id_alias: str | None = None,
) -> AsyncIterator[bytes]:
    """Expose native metadata only while the synthetic transport consumes its stream."""

    async def traced_stream() -> AsyncIterator[bytes]:
        token = _NATIVE_ZEN_EXPECTED_IDENTITY.set(
            (
                user_agent,
                client,
                native_session,
                native_project,
                session_affinity,
                session_id_alias,
            )
        )
        try:
            async for chunk in upstream:
                yield chunk
        finally:
            _NATIVE_ZEN_EXPECTED_IDENTITY.reset(token)

    return traced_stream()


def _native_zen_expected_identity(request_context: Mapping[str, object]) -> tuple[str | None, ...]:
    """Read only actual request-context metadata for the synthetic transport seam."""

    names = (
        "native_user_agent",
        "native_client",
        "native_opencode_session",
        "native_opencode_project",
        "native_session_affinity",
        "native_session_id_alias",
    )
    return tuple(
        value if isinstance((value := request_context.get(name)), str) else None for name in names
    )


def _run_application_integration(
    binary: Path, home: Path, tmpdir: Path, root: Path
) -> dict[str, object]:
    """Run two API turns through the real native runtime, app MCP, and provider manager."""

    from unittest.mock import patch

    from stock_probs.api import create_app
    from stock_probs.assistant.api import _validated_provider_request
    from stock_probs.assistant.runtime import OpenCodeV2Runtime
    from stock_probs.auth import CSRF_COOKIE_NAME, SESSION_COOKIE_NAME
    from stock_probs.config import Settings
    from stock_probs.provider import FixtureProvider

    sys.path.insert(0, str(Path(__file__).parent))
    from test_assistant_api import _add_signed_in_user

    now = datetime.now(UTC).replace(microsecond=0)
    model = _synthetic_application_zen_model(now.date().isoformat())

    class _Catalog:
        def list_models(self):
            return (model,)

        def get_model(self, model_id: str):
            return model if model_id == model.model_id else None

    _APP_PROVIDER_CALLS.clear()
    _APP_PROVIDER_HTTP.clear()
    _APP_PROVIDER_REQUESTS.clear()
    _APP_NATIVE_REQUESTS.clear()
    _APP_NATIVE_CLEANUP.clear()
    _APP_CONTINUATION_WAITING.clear()
    _APP_CONTINUE.clear()
    app_port = _free_port()
    origin = f"http://127.0.0.1:{app_port}"
    data_dir = root / "application-data"
    location_root = root / "application-locations"
    data_dir.mkdir(mode=0o700)
    location_root.mkdir(mode=0o700)
    settings = Settings(
        data_dir=data_dir,
        database_path=data_dir / "stock_probs.sqlite3",
        backup_dir=data_dir / "backups",
        provider="fixture",
        host="127.0.0.1",
        port=app_port,
        environment="test",
        auth_mode="github",
        auth_session_secret=secrets.token_urlsafe(48),
        auth_public_origin=origin,
        auth_cookie_secure=False,
        github_client_id="synthetic-client-id",
        github_client_secret=secrets.token_urlsafe(32),
        github_redirect_uri=f"{origin}/api/v1/auth/github/callback",
        assistant_enabled=True,
        assistant_rollout_mode="invited",
        fixture_now=now,
    )
    catalog = _Catalog()
    providers = AssistantProviderManager(settings, catalog, vault_dir=data_dir / "assistant-vault")
    original_provider_proxy = providers.proxy_chat_completion

    def traced_proxy_chat_completion(provider_id, model_id, body, **request_context):
        upstream = original_provider_proxy(provider_id, model_id, body, **request_context)
        return _with_native_zen_identity(upstream, *_native_zen_expected_identity(request_context))

    providers.proxy_chat_completion = traced_proxy_chat_completion
    supervisor = _ProbeRuntimeSupervisor(
        binary,
        home,
        location_root,
        {
            "HOME": str(home),
            "XDG_CONFIG_HOME": str(home / "config"),
            "XDG_DATA_HOME": str(home / "data"),
            "XDG_CACHE_HOME": str(home / "cache"),
            "TMPDIR": str(tmpdir),
            "PATH": os.defpath,
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
            "OPENCODE_SERVER_USERNAME": "opencode",
            "SYNTHETIC_PROVIDER_KEY": "synthetic-probe-capability",
        },
    )
    runtime_module = __import__("stock_probs.assistant.runtime", fromlist=["_APP_BASE_URL"])
    previous_base_url = runtime_module._APP_BASE_URL
    previous_location_root = runtime_module._LOCATION_ROOT
    runtime_module._APP_BASE_URL = origin
    runtime_module._LOCATION_ROOT = location_root
    runtime = OpenCodeV2Runtime(
        settings, providers=providers, catalog=catalog, supervisor=supervisor
    )
    original_request = runtime._request

    def response_object(response: httpx.Response) -> dict[str, object] | None:
        if len(response.content) > 262_144:
            return None
        try:
            payload = response.json()
        except (ValueError, json.JSONDecodeError):
            return None
        return payload if isinstance(payload, dict) else None

    async def trace_native_request(
        method: str,
        path: str,
        *,
        params: Mapping[str, str] | None = None,
        json: Mapping[str, object] | None = None,
        timeout: float,
        allow_startup_probe: bool = False,
    ) -> httpx.Response:
        route = re.sub(r"/ses[A-Za-z0-9_-]{8,128}(?=/|$)", "/<session>", path)
        native_session = re.fullmatch(r"/api/session/(ses[A-Za-z0-9_-]{8,128})", path)
        if method == "DELETE" and native_session is not None:
            session_path = f"/api/session/{native_session.group(1)}"
            state_response = await original_request(
                "GET", session_path, params=None, json=None, timeout=2.0
            )
            messages_response = await original_request(
                "GET", session_path + "/message", params=None, json=None, timeout=2.0
            )
            state_payload = response_object(state_response) or {}
            state_data = state_payload.get("data")
            messages_payload = response_object(messages_response) or {}
            _APP_NATIVE_CLEANUP.append(
                {
                    "state_status": state_response.status_code,
                    "state_outcome": state_data.get("outcome")
                    if isinstance(state_data, Mapping)
                    else None,
                    "messages_status": messages_response.status_code,
                    "messages": _session_message_summary(messages_payload),
                }
            )
        try:
            response = await original_request(
                method,
                path,
                params=params,
                json=json,
                timeout=timeout,
                allow_startup_probe=allow_startup_probe,
            )
        except Exception as exc:
            _APP_NATIVE_REQUESTS.append(
                {"method": method, "path": route, "error_type": type(exc).__name__}
            )
            raise
        _APP_NATIVE_REQUESTS.append(
            {"method": method, "path": route, "status": response.status_code}
        )
        if method == "POST" and path in {"/api/session", "/api/session/"}:
            payload = response_object(response) or {}
            data = payload.get("data")
            _APP_NATIVE_REQUESTS[-1]["envelope_keys"] = sorted(payload)
            _APP_NATIVE_REQUESTS[-1]["data_keys"] = (
                sorted(data) if isinstance(data, Mapping) else []
            )
            _APP_NATIVE_REQUESTS[-1]["session_id_valid"] = (
                isinstance(data, Mapping)
                and isinstance(data.get("id"), str)
                and _NATIVE_OPENCODE_SESSION_ID.fullmatch(data["id"]) is not None
            )
            project_id = data.get("projectID") if isinstance(data, Mapping) else None
            _APP_NATIVE_REQUESTS[-1]["project_id_present"] = isinstance(project_id, str)
            _APP_NATIVE_REQUESTS[-1]["project_id_shape_valid"] = (
                isinstance(project_id, str)
                and project_id not in {"", ".", ".."}
                and len(project_id) <= _NATIVE_PROJECT_ID_MAX
                and project_id.isascii()
                and project_id.strip() == project_id
                and all(0x21 <= ord(character) <= 0x7E for character in project_id)
                and "/" not in project_id
                and "\\" not in project_id
            )
        elif method == "POST" and path.endswith("/prompt"):
            payload = response_object(response)
            if payload is not None:
                _APP_NATIVE_REQUESTS[-1]["envelope_keys"] = sorted(payload)
                error = payload.get("error")
                _APP_NATIVE_REQUESTS[-1]["error_keys"] = (
                    sorted(error) if isinstance(error, Mapping) else []
                )
        elif method == "GET" and native_session is not None:
            payload = response_object(response) or {}
            data = payload.get("data")
            if isinstance(data, Mapping):
                _APP_NATIVE_REQUESTS[-1]["outcome"] = data.get("outcome")
                _APP_NATIVE_REQUESTS[-1]["native_status"] = data.get("status")
        return response

    runtime._request = trace_native_request
    app = create_app(
        settings,
        FixtureProvider(),
        lambda: now,
        assistant_runtime=runtime,
        assistant_catalog=catalog,
        assistant_providers=providers,
    )

    async def trace_provider_route(request, call_next):
        execution_match = re.fullmatch(
            r"/api/v1/assistant/internal/provider/([0-9a-f]{32})/chat/completions",
            request.url.path,
        )
        expected_identity = (
            runtime.native_provider_metadata(execution_match.group(1))
            if execution_match is not None
            else None
        )
        identity_projection = _native_zen_identity_projection(
            request.headers.getlist("user-agent"),
            request.headers.getlist("x-opencode-client"),
            native_sessions=request.headers.getlist("x-opencode-session"),
            native_projects=request.headers.getlist("x-opencode-project"),
            session_affinities=request.headers.getlist("x-session-affinity"),
            session_id_aliases=request.headers.getlist("x-session-id"),
            expected_session=expected_identity[0] if expected_identity else None,
            expected_project=expected_identity[1] if expected_identity else None,
        )
        response = await call_next(request)
        if request.url.path.startswith("/api/v1/assistant/internal/provider/"):
            route = re.sub(r"/([0-9a-f]{32})/", r"/<execution>/", request.url.path)
            _APP_PROVIDER_HTTP.append(
                {
                    "method": request.method,
                    "path": route,
                    "status": response.status_code,
                    "content_type": response.headers.get("content-type"),
                    **identity_projection,
                }
            )
        return response

    app.middleware("http")(trace_provider_route)
    server = uvicorn.Server(
        uvicorn.Config(
            app,
            host="127.0.0.1",
            port=app_port,
            log_level="critical",
            access_log=False,
            lifespan="on",
        )
    )
    server_thread = threading.Thread(target=server.run, daemon=True)
    server_thread_started = False
    result: dict[str, object] = {}

    def trace_provider_validation(value: object, app_tools: list[dict[str, object]]):
        if isinstance(value, Mapping):
            messages = value.get("messages")
            tools = value.get("tools")
            expected_declarations: dict[str, dict[str, object]] = {}
            for app_tool in app_tools:
                raw_name = str(app_tool["name"])
                expected_declarations[raw_name] = app_tool
                expected_declarations["signal-ledger_" + raw_name.replace(".", "_")] = app_tool
            native_tool_shapes = []
            for item in tools[:16] if isinstance(tools, list) else []:
                if not isinstance(item, Mapping):
                    continue
                function = item.get("function")
                function = function if isinstance(function, Mapping) else {}
                name = function.get("name")
                expected = expected_declarations.get(name) if isinstance(name, str) else None
                actual_parameters = function.get("parameters")
                expected_parameters = expected.get("inputSchema") if expected else None
                native_tool_shapes.append(
                    {
                        "name": name,
                        "parameters_equal": actual_parameters == expected_parameters,
                        "parameters_keys": sorted(actual_parameters)
                        if isinstance(actual_parameters, Mapping)
                        else [],
                        "parameter_property_names": sorted(actual_parameters.get("properties", {}))
                        if isinstance(actual_parameters, Mapping)
                        and isinstance(actual_parameters.get("properties"), Mapping)
                        else [],
                        "required": actual_parameters.get("required")
                        if isinstance(actual_parameters, Mapping)
                        else None,
                        "additional_properties": actual_parameters.get("additionalProperties")
                        if isinstance(actual_parameters, Mapping)
                        else None,
                        "description_equal": (
                            function.get("description") == expected.get("description")
                            if expected
                            else name == "websearch"
                            and function.get("description")
                            == "Search public web pages for a user-approved query."
                        ),
                    }
                )
            _APP_PROVIDER_REQUESTS.append(
                {
                    "request_keys": sorted(value),
                    "model": value.get("model"),
                    "stream": value.get("stream"),
                    "store": value.get("store"),
                    "stream_options": value.get("stream_options"),
                    "message_count": len(messages) if isinstance(messages, list) else None,
                    "messages": [
                        {
                            "role": item.get("role"),
                            "keys": sorted(item),
                            "content_type": type(item.get("content")).__name__,
                            "content_bytes": len(item["content"].encode("utf-8"))
                            if isinstance(item.get("content"), str)
                            else None,
                            "tool_calls": [
                                {
                                    "keys": sorted(call),
                                    "function_keys": sorted(call.get("function", {}))
                                    if isinstance(call.get("function"), Mapping)
                                    else [],
                                    "name": call.get("function", {}).get("name")
                                    if isinstance(call.get("function"), Mapping)
                                    else None,
                                }
                                for call in item.get("tool_calls", [])[:8]
                                if isinstance(item.get("tool_calls"), list)
                                and isinstance(call, Mapping)
                            ],
                        }
                        for item in messages[:32]
                        if isinstance(messages, list) and isinstance(item, Mapping)
                    ]
                    if isinstance(messages, list)
                    else [],
                    "tool_count": len(tools) if isinstance(tools, list) else None,
                    "tools": [
                        {
                            "keys": sorted(item),
                            "function_keys": sorted(item.get("function", {}))
                            if isinstance(item.get("function"), Mapping)
                            else [],
                            "name": item.get("function", {}).get("name")
                            if isinstance(item.get("function"), Mapping)
                            else None,
                            "strict": item.get("function", {}).get("strict")
                            if isinstance(item.get("function"), Mapping)
                            else None,
                        }
                        for item in tools[:16]
                        if isinstance(tools, list) and isinstance(item, Mapping)
                    ]
                    if isinstance(tools, list)
                    else [],
                    "tool_schema_comparisons": native_tool_shapes,
                    "native_websearch_declaration": next(
                        (
                            {
                                "type": item.get("type"),
                                "function": {
                                    "description": item.get("function", {}).get("description"),
                                    "parameters": item.get("function", {}).get("parameters"),
                                    "strict": item.get("function", {}).get("strict"),
                                },
                            }
                            for item in (tools if isinstance(tools, list) else [])
                            if isinstance(item, Mapping)
                            and isinstance(item.get("function"), Mapping)
                            and item.get("function", {}).get("name") == "websearch"
                        ),
                        None,
                    ),
                }
            )
        bounded = _validated_provider_request(value, app_tools)
        if _APP_PROVIDER_REQUESTS:
            _APP_PROVIDER_REQUESTS[-1]["accepted_by_validator"] = bounded is not None
        return bounded

    try:
        with (
            patch(
                "stock_probs.assistant.providers.stream_public_https",
                _synthetic_application_provider_stream,
            ),
            patch(
                "stock_probs.assistant.api._validated_provider_request", trace_provider_validation
            ),
        ):
            server_thread.start()
            server_thread_started = True
            deadline = time.monotonic() + 15.0
            with (
                httpx.Client(
                    base_url=origin,
                    headers={"origin": origin, "referer": origin + "/overview"},
                    timeout=httpx.Timeout(8.0, connect=1.0),
                    trust_env=False,
                ) as owner_a,
                httpx.Client(
                    base_url=origin,
                    headers={"origin": origin, "referer": origin + "/overview"},
                    timeout=httpx.Timeout(8.0, connect=1.0),
                    trust_env=False,
                ) as owner_b,
            ):
                while time.monotonic() < deadline:
                    try:
                        ready = owner_a.get("/api/v1/health")
                        if ready.status_code == 200:
                            break
                    except httpx.HTTPError:
                        time.sleep(0.1)
                else:
                    raise RuntimeError("synthetic FastAPI loopback readiness timed out")
                identity_a = _add_signed_in_user(app, 91820001)
                identity_b = _add_signed_in_user(app, 91820002)
                for client, identity in ((owner_a, identity_a), (owner_b, identity_b)):
                    client.cookies.set(SESSION_COOKIE_NAME, str(identity["token"]), path="/")
                    client.cookies.set(CSRF_COOKIE_NAME, str(identity["csrf"]), path="/")

                def create_consent_and_turn(client: httpx.Client, identity: dict[str, object]):
                    context_response = client.get(
                        "/api/v1/assistant/context", params={"route": "/overview"}
                    )
                    if context_response.status_code != 200:
                        raise RuntimeError("assistant context request failed")
                    context = context_response.json()["context"]
                    csrf = {"x-csrf-token": str(identity["csrf"])}
                    conversation_response = client.post(
                        "/api/v1/assistant/conversations",
                        json={"context": context},
                        headers=csrf,
                    )
                    if conversation_response.status_code != 201:
                        raise RuntimeError("assistant conversation creation failed")
                    envelope = conversation_response.json()["conversation"]
                    conversation = envelope.get("conversation", envelope)
                    model_policy_version = str(
                        providers.model_policy_state(model.model_id)["policy_version"]
                    )
                    consent_response = client.put(
                        "/api/v1/assistant/models/" + quote(model.model_id, safe="") + "/consent",
                        json={
                            "policy_version": model_policy_version,
                            "accepted_terms": True,
                            "data_collection_opt_in": False,
                        },
                        headers=csrf,
                    )
                    if consent_response.status_code != 200:
                        try:
                            consent_body = consent_response.json()
                            error = consent_body.get("error")
                            error_code = error.get("code") if isinstance(error, Mapping) else None
                        except (ValueError, json.JSONDecodeError):
                            error_code = None
                        safe_code = (
                            error_code
                            if isinstance(error_code, str)
                            and re.fullmatch(r"[a-z0-9_]{1,64}", error_code)
                            else "unclassified"
                        )
                        raise RuntimeError(
                            "synthetic model consent failed; "
                            f"status={consent_response.status_code}; "
                            f"code={safe_code}"
                        )
                    turn_response = client.post(
                        f"/api/v1/assistant/conversations/{conversation['id']}/turns",
                        json={
                            "prompt": "Use the synthetic workspace summary tool and then answer.",
                            "model_id": model.model_id,
                            "policy_version": model_policy_version,
                            "context": context,
                            "context_preview_accepted": True,
                        },
                        headers=csrf,
                    )
                    if turn_response.status_code != 202:
                        try:
                            error_payload = turn_response.json()
                            error = error_payload.get("error")
                            turn_error = error.get("code") if isinstance(error, Mapping) else None
                        except (ValueError, json.JSONDecodeError):
                            turn_error = None
                        worker_process = supervisor.process
                        worker_exit = worker_process.poll() if worker_process is not None else None
                        raise RuntimeError(
                            "assistant turn creation failed: "
                            f"http={turn_response.status_code}; code={turn_error}; "
                            f"runtime={runtime.status().status}; worker_exit={worker_exit}; "
                            f"worker_alive={worker_process is not None and worker_exit is None}; "
                            f"native_requests={_APP_NATIVE_REQUESTS}; "
                            f"provider_http={_APP_PROVIDER_HTTP}"
                        )
                    turn = turn_response.json()["turn"]
                    lease_ref = app.state.assistant.storage.execution_for_turn(
                        int(identity["user_id"]), str(conversation["id"]), str(turn["id"])
                    )
                    if not isinstance(lease_ref, dict):
                        raise RuntimeError("assistant execution lease missing")
                    return context, conversation, turn, lease_ref

                context_a, conversation_a, turn_a, lease_a = create_consent_and_turn(
                    owner_a, identity_a
                )
                if not _APP_CONTINUATION_WAITING.wait(12.0):
                    turn_state = app.state.assistant.storage.get_turn(
                        int(identity_a["user_id"]),
                        str(conversation_a["id"]),
                        str(turn_a["id"]),
                    )
                    process = supervisor.process
                    worker_exit = process.poll() if process is not None else "missing"
                    raise RuntimeError(
                        "native app tool continuation gate timed out: "
                        f"turn={turn_state.get('status')}:{turn_state.get('error_code')}; "
                        f"runtime={runtime.status().status}; "
                        f"worker_exit={worker_exit}; "
                        f"provider_calls={len(_APP_PROVIDER_CALLS)}; "
                        f"provider_http={_APP_PROVIDER_HTTP}; "
                        f"provider_shape={_APP_PROVIDER_REQUESTS}; "
                        f"active={len(runtime._active)}; "
                        f"locations={len(runtime._locations)}; "
                        f"native_requests={_APP_NATIVE_REQUESTS}; "
                        f"native_cleanup={_APP_NATIVE_CLEANUP}"
                    )

                # B owns a live, unrelated lease. Its session token is deliberately not a valid
                # capability for A's active execution, even on the private loopback endpoint.
                context_b = owner_b.get(
                    "/api/v1/assistant/context", params={"route": "/overview"}
                ).json()["context"]
                conversation_b = app.state.assistant.storage.create_conversation(
                    int(identity_b["user_id"]),
                    title="Synthetic cross-owner capability fixture",
                    context=context_b,
                    context_version=str(context_b["context_version"]),
                    created_at=now,
                )
                conversation_b_id = str(conversation_b["conversation"]["id"])
                capability_b = secrets.token_urlsafe(36)
                lease_b = app.state.assistant.storage.create_turn(
                    int(identity_b["user_id"]),
                    conversation_b_id,
                    prompt="synthetic cross-owner lease",
                    model_id=model.model_id,
                    policy_version=model.policy_version,
                    context=context_b,
                    context_version=str(context_b["context_version"]),
                    session_id=str(identity_b["session_id"]),
                    session_token_hash=str(identity_b["token_hash"]),
                    capability=capability_b,
                    now=now,
                    expires_at=now + timedelta(seconds=120),
                )
                app.state.assistant.storage.set_turn_status(
                    int(identity_b["user_id"]),
                    conversation_b_id,
                    str(lease_b["id"]),
                    status="running",
                    now=now,
                )
                cross_owner = httpx.post(
                    origin + f"/api/v1/assistant/internal/mcp/{lease_a['execution_id']}",
                    headers={"Authorization": f"Bearer {capability_b}"},
                    json={
                        "jsonrpc": "2.0",
                        "id": "cross-owner-probe",
                        "method": "tools/call",
                        "params": {"name": "workspace.summary", "arguments": {}},
                    },
                    timeout=httpx.Timeout(4.0, connect=1.0),
                    trust_env=False,
                )
                app.state.assistant.storage.close_execution(str(lease_b["execution_id"]), now=now)
                app.state.assistant.storage.set_turn_status(
                    int(identity_b["user_id"]),
                    conversation_b_id,
                    str(lease_b["id"]),
                    status="cancelled",
                    now=now,
                )
                _APP_CONTINUE.set()

                def wait_turn(
                    identity: dict[str, object],
                    conversation: dict[str, object],
                    turn: dict[str, object],
                ):
                    deadline = time.monotonic() + 35.0
                    while time.monotonic() < deadline:
                        current = app.state.assistant.storage.get_turn(
                            int(identity["user_id"]),
                            str(conversation["id"]),
                            str(turn["id"]),
                        )
                        if current.get("status") not in {"queued", "running"}:
                            return current
                        time.sleep(0.1)
                    raise RuntimeError("assistant application turn did not finish within bound")

                completed_a = wait_turn(identity_a, conversation_a, turn_a)
                detail_a = owner_a.get(f"/api/v1/assistant/conversations/{conversation_a['id']}")
                if detail_a.status_code != 200:
                    raise RuntimeError("owner A could not read canonical assistant transcript")
                messages_a = detail_a.json().get("messages", {}).get("items", [])
                events_a = detail_a.json().get("events", {}).get("items", [])
                receipts_a = [
                    event.get("data")
                    for event in events_a
                    if isinstance(event, dict)
                    and event.get("type") == "tool"
                    and isinstance(event.get("data"), dict)
                    and event["data"].get("status") == "completed"
                    and event["data"].get("name") == "workspace.summary"
                ]
                answer_a = any(
                    isinstance(message, dict)
                    and message.get("role") == "assistant"
                    and message.get("text") == "Synthetic native application turn completed."
                    for message in messages_a
                )
                context_b, conversation_b_api, turn_b, lease_b_api = create_consent_and_turn(
                    owner_b, identity_b
                )
                completed_b = wait_turn(identity_b, conversation_b_api, turn_b)
                detail_b = owner_b.get(
                    f"/api/v1/assistant/conversations/{conversation_b_api['id']}"
                )
                if detail_b.status_code != 200:
                    raise RuntimeError("owner B could not read canonical assistant transcript")
                messages_b = detail_b.json().get("messages", {}).get("items", [])
                events_b = detail_b.json().get("events", {}).get("items", [])
                receipts_b = [
                    event.get("data")
                    for event in events_b
                    if isinstance(event, dict)
                    and event.get("type") == "tool"
                    and isinstance(event.get("data"), dict)
                    and event["data"].get("status") == "completed"
                    and event["data"].get("name") == "workspace.summary"
                ]
                answer_b = any(
                    isinstance(message, dict)
                    and message.get("role") == "assistant"
                    and message.get("text") == "Synthetic native application turn completed."
                    for message in messages_b
                )
                owner_b_denied_a_transcript = (
                    owner_b.get(
                        f"/api/v1/assistant/conversations/{conversation_a['id']}"
                    ).status_code
                    == 404
                )
                time.sleep(0.2)
                cache_scan = _scan_synthetic_storage(home, tmpdir)
                app_calls = list(_APP_PROVIDER_CALLS)
                result = {
                    "app_base_url_loopback": origin.startswith("http://127.0.0.1:"),
                    "native_runtime_type": type(runtime).__name__,
                    "provider_manager_type": type(providers).__name__,
                    "fastapi_turn_statuses": [completed_a.get("status"), completed_b.get("status")],
                    "persisted_answers": [answer_a, answer_b],
                    "workspace_summary_receipts": [
                        [
                            {
                                "name": row.get("name"),
                                "status": row.get("status"),
                                "result_bytes": row.get("result_bytes"),
                                "result_sha256": row.get("result_sha256"),
                            }
                            for row in receipts
                        ]
                        for receipts in (receipts_a, receipts_b)
                    ],
                    "cross_owner_mcp_status": cross_owner.status_code,
                    "cross_owner_mcp_error": cross_owner.json().get("error", {}).get("code")
                    if cross_owner.headers.get("content-type", "").startswith("application/json")
                    and isinstance(cross_owner.json(), dict)
                    else None,
                    "cross_owner_transcript_denied": owner_b_denied_a_transcript,
                    "provider_manager_calls": app_calls,
                    "provider_http_requests": list(_APP_PROVIDER_HTTP),
                    "provider_request_shapes": list(_APP_PROVIDER_REQUESTS),
                    "native_api_requests": list(_APP_NATIVE_REQUESTS),
                    "native_session_before_delete": list(_APP_NATIVE_CLEANUP),
                    "native_worker_exit_code": (
                        supervisor.process.poll() if supervisor.process is not None else None
                    ),
                    "native_worker_alive": (
                        supervisor.process is not None and supervisor.process.poll() is None
                    ),
                    "native_worker_purge_count": len(supervisor.purge_states),
                    "native_worker_purge_states": sorted(supervisor.purge_states.values()),
                    "transient_cache_after_app_cleanup": cache_scan,
                }
                result["app_native_integration_success"] = (
                    result["fastapi_turn_statuses"] == ["completed", "completed"]
                    and result["persisted_answers"] == [True, True]
                    and all(
                        len(rows) == 1
                        and rows[0].get("name") == "workspace.summary"
                        and rows[0].get("status") == "completed"
                        and isinstance(rows[0].get("result_sha256"), str)
                        for rows in result["workspace_summary_receipts"]
                    )
                    and cross_owner.status_code == 404
                    and owner_b_denied_a_transcript
                    and len(supervisor.purge_states) == 2
                    and all(status == "cleared" for status in supervisor.purge_states.values())
                    and all(
                        value == 0 for value in cache_scan["synthetic_marker_occurrences"].values()
                    )
                    and len(app_calls) >= 4
                    and all(call.get("store") is False for call in app_calls)
                    and all(call.get("authorization_present") is True for call in app_calls)
                    and bool(result["provider_http_requests"])
                    and all(
                        row.get("user_agent_present") is True
                        and row.get("user_agent_unique") is True
                        and row.get("user_agent_shape_valid") is True
                        and row.get("client_present") is True
                        and row.get("client_unique") is True
                        and row.get("client_shape_valid") is True
                        and row.get("client_matches_user_agent") is True
                        and row.get("native_session_present") is True
                        and row.get("native_session_unique") is True
                        and row.get("native_session_shape_valid") is True
                        and row.get("native_session_matches_active") is True
                        and row.get("native_project_present") is True
                        and row.get("native_project_unique") is True
                        and row.get("native_project_shape_valid") is True
                        and row.get("native_project_matches_active") is True
                        and row.get("session_aliases_match_native") is True
                        for row in result["provider_http_requests"]
                    )
                    and all(
                        call.get("native_user_agent_forwarded") is True
                        and call.get("native_client_forwarded") is True
                        and call.get("native_session_forwarded") is True
                        and call.get("native_project_forwarded") is True
                        and call.get("native_affinity_matches") is True
                        and call.get("native_session_id_alias_matches") is True
                        for call in app_calls
                    )
                    and all(
                        row.get("session_id_valid") is True
                        and row.get("project_id_present") is True
                        and row.get("project_id_shape_valid") is True
                        for row in _APP_NATIVE_REQUESTS
                        if row.get("method") == "POST" and row.get("path") == "/api/session"
                    )
                )
                result["application_model_calls"] = len(app_calls)
                result["application_locations"] = [
                    {"owner": "A", "execution_present": bool(lease_a.get("execution_id"))},
                    {"owner": "B", "execution_present": bool(lease_b_api.get("execution_id"))},
                ]
                result["native_cache_clear"] = all(
                    value == 0 for value in cache_scan["synthetic_marker_occurrences"].values()
                )
                return result
    finally:
        _APP_CONTINUE.set()
        server.should_exit = True
        if server_thread_started and server_thread.is_alive():
            server_thread.join(timeout=8.0)
        server_thread_stopped = server_thread_started and not server_thread.is_alive()
        cleanup_facts = _emit_application_server_cleanup_diagnostic(
            app_port,
            server_started=server.started,
            thread_started=server_thread_started,
            thread_stopped=server_thread_stopped,
        )
        result.update(cleanup_facts)
        result["app_native_integration_success"] = (
            result.get("app_native_integration_success") is True
            and cleanup_facts["owned_app_server_cleanup"] is True
        )
        runtime_module._APP_BASE_URL = previous_base_url
        runtime_module._LOCATION_ROOT = previous_location_root
        supervisor._stop_worker()


def run_native_probe() -> None:
    """Run bounded V2 model, MCP, and location discovery against synthetic fixtures."""

    started_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    binary = _binary()
    version_result = subprocess.run(  # noqa: S603 - fixed local binary from source.
        [str(binary), "--version"],
        check=True,
        capture_output=True,
        text=True,
        env={"PATH": os.defpath, "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"},
        timeout=5,
    )
    binary_version = version_result.stdout.strip()
    if binary_version != "opencode v2.0.7":
        raise RuntimeError("The native probe requires the pinned OpenCode V2.0.7 binary")
    with tempfile.TemporaryDirectory(prefix="stock-probs-native-v2-") as temporary:
        root = Path(temporary)
        home = root / "home"
        location_a, location_b = root / "location-a", root / "location-b"
        for path in (
            home / "config",
            home / "data",
            home / "cache",
            home / "tmp",
            location_a,
            location_b,
        ):
            path.mkdir(parents=True, mode=0o700)
        mcp_servers = [
            ThreadingHTTPServer(("127.0.0.1", 0), _mcp_handler("synthetic-mcp-a")),
            ThreadingHTTPServer(("127.0.0.1", 0), _mcp_handler("synthetic-mcp-b")),
        ]
        provider_server = ThreadingHTTPServer(("127.0.0.1", 0), _ProviderHandler)
        mcp_threads = [
            threading.Thread(target=server.serve_forever, daemon=True) for server in mcp_servers
        ]
        provider_thread = threading.Thread(target=provider_server.serve_forever, daemon=True)
        _MCP_REQUESTS.clear()
        _PROVIDER_REQUESTS.clear()
        _PROVIDER_CALLS = 0
        for thread in mcp_threads:
            thread.start()
        provider_thread.start()
        mcp_urls = [f"http://127.0.0.1:{server.server_port}/mcp" for server in mcp_servers]
        provider_url = f"http://127.0.0.1:{provider_server.server_port}/v1"
        generated_config = _fixed_location_config(
            proxy_base_url=provider_url,
            proxy_capability="synthetic-provider-capability-location-a",
            mcp_url=mcp_urls[0],
            mcp_capability="synthetic-mcp-capability-location-a",
        )
        _write_location_config(location_a, mcp_urls[0], provider_url)
        _write_location_config(location_b, mcp_urls[1], provider_url)

        port = 4097
        password = secrets.token_urlsafe(32)
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
            "OPENCODE_SERVER_PASSWORD": password,
            "SYNTHETIC_PROVIDER_KEY": "synthetic-probe-capability",
        }
        environment.pop("OPENCODE_DISABLE_PROJECT_CONFIG", None)
        debug_config = subprocess.run(  # noqa: S603 - fixed local binary from source.
            [str(binary), "debug", "config"],
            cwd=location_a,
            env=environment,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=8,
            check=False,
        )
        debug_text = debug_config.stdout
        try:
            debug_object = json.loads(debug_text)
        except json.JSONDecodeError:
            debug_object = {}
        debug_documents = (
            [
                item.get("info")
                for item in debug_object
                if isinstance(item, dict)
                and item.get("type") == "document"
                and isinstance(item.get("info"), dict)
            ]
            if isinstance(debug_object, list)
            else []
        )
        debug_mapping = debug_documents[-1] if debug_documents else {}
        debug_providers = debug_mapping.get("providers", {})
        debug_mcp = debug_mapping.get("mcp", {})
        process = subprocess.Popen(  # noqa: S603 - fixed local binary from source.
            [str(binary), "serve", "--hostname", "127.0.0.1", "--port", str(port)],
            cwd=location_a,
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            close_fds=True,
        )
        auth = ("opencode", password)
        base_url = f"http://127.0.0.1:{port}"
        try:
            with httpx.Client(
                base_url=base_url,
                auth=auth,
                timeout=httpx.Timeout(4.0, connect=1.0),
                trust_env=False,
            ) as client:
                deadline = time.monotonic() + 20
                while time.monotonic() < deadline:
                    if process.poll() is not None:
                        diagnostic = process.stderr.read(16_384) if process.stderr else b""
                        text = diagnostic.decode("utf-8", "replace")
                        text = text.replace(password, "[redacted]")[-2000:]
                        raise RuntimeError(
                            "native server exited before readiness: " + " ".join(text.split())
                        )
                    try:
                        info = client.get("/api/info")
                        if info.status_code == 200:
                            break
                    except httpx.HTTPError:
                        time.sleep(0.1)
                else:
                    raise RuntimeError("native server readiness timed out")

                locations = (location_a, location_b)
                observations: list[dict[str, object]] = []
                turns: list[dict[str, object]] = []
                for location in locations:
                    params = {"location[directory]": str(location)}
                    native_provider_response = client.get("/api/provider", params=params)
                    native_provider_payload = (
                        native_provider_response.json()
                        if native_provider_response.status_code == 200
                        else {}
                    )
                    native_auth_response = client.get("/api/provider/auth", params=params)
                    native_auth_payload = (
                        native_auth_response.json()
                        if native_auth_response.status_code == 200
                        else {}
                    )
                    location_response = client.get("/api/location", params=params)
                    model_list_started = time.monotonic()
                    model_response = client.get("/api/model", params=params)
                    model_payload = (
                        model_response.json() if model_response.status_code == 200 else {}
                    )
                    model_rows = model_payload.get("data", [])
                    settle_deadline = time.monotonic() + 5.0
                    while (
                        not any(
                            isinstance(row, dict)
                            and row.get("id") == "assistant-selected"
                            and row.get("providerID") == "assistant-proxy"
                            for row in model_rows
                        )
                        and time.monotonic() < settle_deadline
                    ):
                        time.sleep(0.2)
                        model_response = client.get("/api/model", params=params)
                        model_payload = (
                            model_response.json() if model_response.status_code == 200 else {}
                        )
                        model_rows = model_payload.get("data", [])
                    mcp_started = time.monotonic()
                    mcp_response = client.get("/api/mcp", params=params)
                    mcp_payload = mcp_response.json() if mcp_response.status_code == 200 else {}
                    mcp_deadline = time.monotonic() + 5.0
                    while (
                        _mcp_status(mcp_payload) != "connected" and time.monotonic() < mcp_deadline
                    ):
                        time.sleep(0.2)
                        mcp_response = client.get("/api/mcp", params=params)
                        mcp_payload = mcp_response.json() if mcp_response.status_code == 200 else {}
                    location_payload = (
                        location_response.json() if location_response.status_code == 200 else {}
                    )
                    mcp_rows = mcp_payload.get("data", [])
                    observations.append(
                        {
                            "location_status": location_response.status_code,
                            "model_status": model_response.status_code,
                            "mcp_status": mcp_response.status_code,
                            "native_provider_inventory": _native_provider_inventory_summary(
                                native_provider_response.status_code,
                                native_provider_payload,
                                native_auth_response.status_code,
                                native_auth_payload,
                            ),
                            "model_settle_seconds": round(time.monotonic() - model_list_started, 3),
                            "mcp_settle_seconds": round(time.monotonic() - mcp_started, 3),
                            "resolved_directory": location_payload.get("directory"),
                            "project_directory": (location_payload.get("project") or {}).get(
                                "directory"
                            ),
                            "selected_model": {
                                "id": "assistant-selected",
                                "providerID": "assistant-proxy",
                            }
                            if any(
                                isinstance(row, dict)
                                and row.get("id") == "assistant-selected"
                                and row.get("providerID") == "assistant-proxy"
                                for row in model_rows
                            )
                            else None,
                            "mcp_servers": [
                                {
                                    "name": row.get("name"),
                                    "status": (
                                        row.get("status", {}).get("status")
                                        if isinstance(row.get("status"), dict)
                                        else row.get("status")
                                    ),
                                }
                                for row in mcp_rows
                                if isinstance(row, dict)
                            ],
                        }
                    )
                    selected = next(
                        (
                            row
                            for row in model_rows
                            if isinstance(row, dict)
                            and row.get("id") == "assistant-selected"
                            and row.get("providerID") == "assistant-proxy"
                        ),
                        None,
                    )
                    if selected is None or _mcp_status(mcp_payload) != "connected":
                        turns.append(
                            {
                                "location": location.name,
                                "attempted": False,
                                "reason": "native model or MCP discovery unavailable",
                            }
                        )
                        continue

                    session_payload = {
                        "title": "Synthetic native protocol turn",
                        "agent": "build",
                        "model": {
                            "providerID": selected["providerID"],
                            "id": selected["id"],
                        },
                        "location": {"directory": str(location)},
                        "permissions": [
                            {"action": "*", "resource": "*", "effect": "deny"},
                            *[
                                {"action": action, "resource": "*", "effect": "allow"}
                                for action in _TOOL_ACTIONS
                            ],
                            {"action": "websearch", "resource": "*", "effect": "ask"},
                            {"action": "webfetch", "resource": "*", "effect": "ask"},
                            *[
                                {"action": action, "resource": "*", "effect": "deny"}
                                for action in (
                                    "execute",
                                    "browser",
                                    "subagent",
                                    "question",
                                    "skill",
                                    "plugins",
                                )
                            ],
                        ],
                    }
                    session_response = client.post("/api/session", json=session_payload, timeout=10)
                    session_body = session_response.json() if session_response.content else {}
                    session_data = (
                        session_body.get("data") if isinstance(session_body, dict) else None
                    )
                    session_id = session_data.get("id") if isinstance(session_data, dict) else None
                    turn: dict[str, object] = {
                        "location": location.name,
                        "attempted": True,
                        "model_ref": {
                            "providerID": selected["providerID"],
                            "id": selected["id"],
                        },
                        "session_create_status": session_response.status_code,
                        "permission_actions": [
                            row.get("action")
                            for row in session_payload.get("permissions", [])
                            if isinstance(row, dict)
                        ],
                        "session_create_envelope_keys": sorted(session_body)
                        if isinstance(session_body, dict)
                        else [],
                        "session_create_error": {
                            key: session_body.get(key)
                            for key in ("_tag", "kind", "message")
                            if key in session_body
                        }
                        if isinstance(session_body, dict)
                        else {},
                    }
                    if not isinstance(session_id, str):
                        turns.append(turn)
                        continue
                    _EXPECTED_MCP_SESSIONS.add(session_id)
                    mcp_start = len(_MCP_REQUESTS)
                    provider_start = len(_PROVIDER_REQUESTS)
                    prompt_response = client.post(
                        f"/api/session/{session_id}/prompt",
                        json={"text": "Use the synthetic workspace summary tool and then answer."},
                        timeout=45,
                    )
                    turn["prompt_status"] = prompt_response.status_code
                    try:
                        wait_response = client.post(
                            f"/api/experimental/session/{session_id}/wait", timeout=40
                        )
                        turn["wait_status"] = wait_response.status_code
                    except httpx.TimeoutException:
                        turn["wait_status"] = None
                        turn["wait_timed_out"] = True
                    messages_response = client.get(
                        f"/api/session/{session_id}/message", params=params, timeout=5
                    )
                    messages_body = (
                        messages_response.json() if messages_response.status_code == 200 else {}
                    )
                    turn["messages_status"] = messages_response.status_code
                    turn["messages"] = _session_message_summary(messages_body)
                    session_state_response = client.get(
                        f"/api/session/{session_id}", params=params, timeout=5
                    )
                    session_state = (
                        session_state_response.json()
                        if session_state_response.status_code == 200
                        and session_state_response.content
                        else {}
                    )
                    session_state_data = (
                        session_state.get("data", {}) if isinstance(session_state, dict) else {}
                    )
                    turn["session_state"] = {
                        "status": session_state_response.status_code,
                        "envelope_keys": sorted(session_state)
                        if isinstance(session_state, dict)
                        else [],
                        "data_keys": sorted(session_state_data)
                        if isinstance(session_state_data, dict)
                        else [],
                        "status_value": session_state_data.get("status")
                        if isinstance(session_state_data, dict)
                        else None,
                        "outcome": session_state_data.get("outcome")
                        if isinstance(session_state_data, dict)
                        else None,
                    }
                    log_response = client.get(
                        f"/api/experimental/session/{session_id}/log",
                        params={"after": "0", "follow": "false"},
                        headers={"accept": "text/event-stream"},
                        timeout=8,
                    )
                    turn["log_status"] = log_response.status_code
                    turn["log_content_type"] = log_response.headers.get("content-type")
                    turn["log"] = _session_log_summary(log_response.content, session_id)
                    history_response = client.get(
                        f"/api/session/{session_id}/history",
                        params={"limit": "100"},
                        timeout=8,
                    )
                    history_body = (
                        history_response.json() if history_response.status_code == 200 else {}
                    )
                    turn["history_status"] = history_response.status_code
                    turn["history"] = _session_history_summary(history_body, session_id)
                    turn["provider_calls"] = _PROVIDER_REQUESTS[provider_start:]
                    turn["mcp_calls"] = [
                        row
                        for row in _MCP_REQUESTS[mcp_start:]
                        if row.get("method") == "tools/call"
                    ]
                    turn["native_terminal_answer"] = (
                        turn["messages"].get("expected_synthetic_answer")
                        if isinstance(turn.get("messages"), dict)
                        else None
                    )
                    for call in turn["mcp_calls"]:
                        if call.get("tool_name") == "workspace.summary":
                            call["synthetic_result"] = "synthetic tool result"
                    delete_response = client.delete(
                        f"/api/session/{session_id}", params=params, timeout=5
                    )
                    turn["delete_status"] = delete_response.status_code
                    turn["post_delete_session_status"] = client.get(
                        f"/api/session/{session_id}", params=params, timeout=5
                    ).status_code
                    turn["post_delete_message_status"] = client.get(
                        f"/api/session/{session_id}/message", params=params, timeout=5
                    ).status_code
                    turn["post_delete_history_status"] = client.get(
                        f"/api/session/{session_id}/history", params={"limit": "100"}, timeout=5
                    ).status_code
                    turn["post_delete_export_status"] = client.get(
                        f"/api/experimental/session/{session_id}/export",
                        params=params,
                        timeout=5,
                    ).status_code
                    turns.append(turn)
                native_search = _run_native_search_probe(
                    client,
                    {"providerID": "assistant-proxy", "id": "assistant-selected"},
                    location_a,
                )
                openapi_response = client.get("/openapi.json")
                openapi = openapi_response.json() if openapi_response.status_code == 200 else {}
                interesting_paths = {
                    "/api/provider",
                    "/api/provider/{providerID}",
                    "/api/provider/auth",
                    "/api/model",
                    "/api/session",
                    "/api/session/{sessionID}/prompt",
                    "/api/experimental/session/{sessionID}/wait",
                }
                openapi_shapes = {
                    path: {
                        method: {
                            "query": [
                                {
                                    "name": parameter.get("name"),
                                    "schema": parameter.get("schema"),
                                    "style": parameter.get("style"),
                                    "explode": parameter.get("explode"),
                                }
                                for parameter in operation.get("parameters", [])
                                if parameter.get("in") == "query"
                            ],
                            "body_schema": operation.get("requestBody", {})
                            .get("content", {})
                            .get("application/json", {})
                            .get("schema"),
                        }
                        for method, operation in path_spec.items()
                        if method in {"get", "post"} and isinstance(operation, dict)
                    }
                    for path, path_spec in openapi.get("paths", {}).items()
                    if path in interesting_paths and isinstance(path_spec, dict)
                }
                component_schemas = openapi.get("components", {}).get("schemas", {})
                openapi_contracts = {
                    key: component_schemas.get(key)
                    for key in (
                        "Model.Ref",
                        "Location.PublicRef",
                        "Permission.Ruleset",
                    )
                    if isinstance(component_schemas, dict) and key in component_schemas
                }
                compact_turns = [_compact_turn(turn) for turn in turns]
                process.terminate()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=3)
                try:
                    app_integration = _run_application_integration(binary, home, home / "tmp", root)
                except RuntimeError as exc:
                    message = str(exc)
                    consent_failure = re.fullmatch(
                        r"synthetic model consent failed; status=(\d{3}); "
                        r"code=([a-z0-9_]{1,64})",
                        message,
                    )
                    app_integration = {
                        "app_native_integration_success": False,
                        "failure_code": (
                            "synthetic_model_consent_failed"
                            if consent_failure
                            else "application_integration_failed"
                        ),
                        "consent_status": int(consent_failure.group(1))
                        if consent_failure
                        else None,
                        "consent_error_code": consent_failure.group(2) if consent_failure else None,
                    }
                time.sleep(0.1)
                transient_storage_summary = _scan_synthetic_storage(home, home / "tmp")
                native_protocol_success = (
                    all(
                        turn.get("attempted") is True
                        and turn.get("session_create_status") == 200
                        and turn.get("prompt_status") in {200, 202, 204}
                        and turn.get("wait_status") in {200, 204}
                        and turn.get("messages_status") == 200
                        and turn.get("native_terminal_answer")
                        == "Synthetic native tool continuation completed."
                        and isinstance(turn.get("session_state"), dict)
                        and turn["session_state"].get("outcome") == "succeeded"
                        and turn.get("delete_status") == 204
                        and all(
                            turn.get(key) == 404
                            for key in (
                                "post_delete_session_status",
                                "post_delete_message_status",
                                "post_delete_history_status",
                                "post_delete_export_status",
                            )
                        )
                        and any(
                            row.get("tool_name") == "workspace.summary"
                            and row.get("argument_keys") == []
                            for row in turn.get("mcp_calls", [])
                        )
                        and any(
                            isinstance(call, dict)
                            and call.get("tool_result_count", 0) >= 1
                            and any(
                                isinstance(receipt, dict)
                                and receipt.get("sha256")
                                == hashlib.sha256(b"synthetic tool result").hexdigest()
                                for receipt in call.get("tool_result_content", [])
                            )
                            for call in turn.get("provider_calls", [])
                        )
                        for turn in turns
                    )
                    and len(turns) == 2
                )
                result = {
                    "started_at": started_at,
                    "finished_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
                    "command": ".dev-venv/bin/python tests/native_assistant_probe.py --native",
                    "binary_version": binary_version,
                    "synthetic_only": True,
                    "config_disable_inherited": "OPENCODE_DISABLE_PROJECT_CONFIG"
                    not in environment,
                    "project_provider_loaded": (
                        debug_config.returncode == 0
                        and isinstance(debug_providers, dict)
                        and "assistant-proxy" in debug_providers
                    ),
                    "project_mcp_loaded": (
                        isinstance(debug_mcp, dict)
                        and isinstance(debug_mcp.get("servers"), dict)
                        and "signal-ledger" in debug_mcp["servers"]
                    ),
                    "generated_config": _generated_config_summary(generated_config),
                    "native_tool_actions": list(_TOOL_ACTIONS),
                    "locations": observations,
                    "native_turns": compact_turns,
                    "native_search_feasibility": native_search,
                    "native_tool_declarations": next(
                        (
                            row["tool_declarations"]
                            for row in (
                                _compact_provider_call(item, include_tools=True)
                                for item in _PROVIDER_REQUESTS
                            )
                            if row.get("tool_declarations")
                        ),
                        [],
                    ),
                    "native_mcp_methods": sorted(
                        {
                            row["method"]
                            for row in _MCP_REQUESTS
                            if isinstance(row.get("method"), str)
                        }
                    ),
                    "mcp_wire": [
                        {
                            "method": row.get("method"),
                            "tool_name": row.get("tool_name"),
                            "params_keys": row.get("params_keys"),
                            "argument_keys": row.get("argument_keys"),
                            "session_header_present": row.get("session_header_present"),
                            "protocol_header": row.get("protocol_header"),
                            "server_session_header": row.get("server_session_header"),
                            "opencode_session_id_present": row.get("opencode_session_id_present"),
                        }
                        for row in _MCP_REQUESTS
                        if row.get("method") in {"initialize", "tools/list", "tools/call"}
                    ],
                    "provider_wire": [
                        _compact_provider_call(row, include_tools=index == 0)
                        for index, row in enumerate(_PROVIDER_REQUESTS)
                    ],
                    "provider_ref_contract": openapi_contracts.get("Model.Ref"),
                    "location_query_contract": openapi_shapes.get("/api/model", {})
                    .get("get", {})
                    .get("query"),
                    "native_protocol_success": native_protocol_success,
                    "real_fastapi_native_integration": app_integration,
                    "transient_cache_cleared": all(
                        value == 0
                        for value in transient_storage_summary[
                            "synthetic_marker_occurrences"
                        ].values()
                    ),
                    "integration_success": native_protocol_success
                    and app_integration.get("app_native_integration_success") is True
                    and all(
                        value == 0
                        for value in transient_storage_summary[
                            "synthetic_marker_occurrences"
                        ].values()
                    ),
                    "transient_storage_after_cleanup": transient_storage_summary,
                }
                result["cache_recovery_blocker"] = (
                    None
                    if result["transient_cache_cleared"]
                    else "native_storage_retains_deleted_turn_markers"
                )
                print(
                    json.dumps(
                        result,
                        ensure_ascii=True,
                        separators=(",", ":"),
                    )
                )
                if not result["integration_success"]:
                    raise RuntimeError("Native synthetic integration probe did not complete.")
        finally:
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=3)
            for server in mcp_servers:
                server.shutdown()
                server.server_close()
            for thread in mcp_threads:
                thread.join(timeout=1)
            provider_server.shutdown()
            provider_server.server_close()
            provider_thread.join(timeout=1)


def run_native_app_integration_probe() -> int:
    """Run the real FastAPI/native/ProviderManager bridge with two synthetic owners."""

    started_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    binary = _binary()
    version_result = subprocess.run(  # noqa: S603 - fixed local binary from source.
        [str(binary), "--version"],
        check=True,
        capture_output=True,
        text=True,
        env={"PATH": os.defpath, "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"},
        timeout=5,
    )
    binary_version = version_result.stdout.strip()
    if binary_version != "opencode v2.0.7":
        raise RuntimeError("The native probe requires the pinned OpenCode V2.0.7 binary")
    with tempfile.TemporaryDirectory(prefix="r120-native-app-") as temporary:
        root = Path(temporary)
        home = root / "home"
        for name in ("config", "data", "cache", "tmp"):
            (home / name).mkdir(parents=True, mode=0o700)
        app_result = _run_application_integration(binary, home, home / "tmp", root)
        result = {
            "command": ".dev-venv/bin/python tests/native_assistant_probe.py --app-integration",
            "started_at": started_at,
            "finished_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "binary_version": binary_version,
            "synthetic_model_and_data_only": True,
            "inherited_project_config_disable_removed": True,
            "real_fastapi_native_integration": app_result,
            "app_native_integration_success": app_result.get("app_native_integration_success")
            is True,
        }
        print(json.dumps(result, sort_keys=True, separators=(",", ":")))
        return 0 if result["app_native_integration_success"] else 1


def run_native_live_zen_probe() -> int:
    """Run one synthetic FastAPI turn through native V2 to the approved free Zen route."""

    from stock_probs.api import create_app
    from stock_probs.assistant.model_catalog import AssistantModelCatalog
    from stock_probs.assistant.providers import AssistantProviderManager
    from stock_probs.assistant.runtime import OpenCodeV2Runtime
    from stock_probs.auth import CSRF_COOKIE_NAME, SESSION_COOKIE_NAME
    from stock_probs.config import Settings
    from stock_probs.provider import FixtureProvider

    sys.path.insert(0, str(Path(__file__).parent))
    from test_assistant_api import _add_signed_in_user

    started_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    binary = _binary()
    version_result = subprocess.run(  # noqa: S603 - fixed local binary from source.
        [str(binary), "--version"],
        check=True,
        capture_output=True,
        text=True,
        env={"PATH": os.defpath, "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"},
        timeout=5,
    )
    binary_version = version_result.stdout.strip()
    if binary_version != "opencode v2.0.7":
        raise RuntimeError("The native probe requires the pinned OpenCode V2.0.7 binary")

    with tempfile.TemporaryDirectory(prefix="r120-native-zen-") as temporary:
        root = Path(temporary)
        home = root / "home"
        for name in ("config", "data", "cache", "tmp"):
            (home / name).mkdir(parents=True, mode=0o700)
        data_dir = root / "application-data"
        location_root = root / "application-locations"
        data_dir.mkdir(mode=0o700)
        location_root.mkdir(mode=0o700)
        app_port = _free_port()
        origin = f"http://127.0.0.1:{app_port}"
        now = datetime.now(UTC).replace(microsecond=0)
        settings = Settings(
            data_dir=data_dir,
            database_path=data_dir / "stock_probs.sqlite3",
            backup_dir=data_dir / "backups",
            provider="fixture",
            host="127.0.0.1",
            port=app_port,
            environment="test",
            auth_mode="github",
            auth_session_secret=secrets.token_urlsafe(48),
            auth_public_origin=origin,
            auth_cookie_secure=False,
            github_client_id="synthetic-client-id",
            github_client_secret=secrets.token_urlsafe(32),
            github_redirect_uri=f"{origin}/api/v1/auth/github/callback",
            assistant_enabled=True,
            assistant_rollout_mode="invited",
            fixture_now=now,
        )
        catalog = AssistantModelCatalog(settings)
        discovered = asyncio.run(catalog.refresh())
        reviewed_model_id = _reviewed_free_zen_model_id()
        model = _discovered_reviewed_zen_model(discovered, reviewed_model_id)
        if model is None:
            print(
                json.dumps(
                    {
                        "command": (
                            ".dev-venv/bin/python tests/native_assistant_probe.py --live-zen"
                        ),
                        "started_at": started_at,
                        "finished_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
                        "binary_version": binary_version,
                        "status": "zen_model_unavailable",
                        "discovered_approved_model_count": len(discovered),
                        "credential_used": False,
                        "synthetic_context_only": True,
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                )
            )
            return 1

        providers = AssistantProviderManager(
            settings, catalog, vault_dir=data_dir / "assistant-vault"
        )
        model_policy_version = str(providers.model_policy_state(model.model_id)["policy_version"])
        zen_summary = next(
            (item for item in providers.list_providers() if item.provider_id == "opencode-zen"),
            None,
        )
        if zen_summary is None or zen_summary.credential_configured:
            raise RuntimeError("Zen probe unexpectedly found a stored credential")

        supervisor = _ProbeRuntimeSupervisor(
            binary,
            home,
            location_root,
            {
                "HOME": str(home),
                "XDG_CONFIG_HOME": str(home / "config"),
                "XDG_DATA_HOME": str(home / "data"),
                "XDG_CACHE_HOME": str(home / "cache"),
                "TMPDIR": str(home / "tmp"),
                "PATH": os.defpath,
                "LANG": "C.UTF-8",
                "LC_ALL": "C.UTF-8",
                "OPENCODE_SERVER_USERNAME": "opencode",
            },
        )
        runtime_module = __import__("stock_probs.assistant.runtime", fromlist=["_APP_BASE_URL"])
        previous_base_url = runtime_module._APP_BASE_URL
        previous_location_root = runtime_module._LOCATION_ROOT
        runtime_module._APP_BASE_URL = origin
        runtime_module._LOCATION_ROOT = location_root
        runtime = OpenCodeV2Runtime(
            settings, providers=providers, catalog=catalog, supervisor=supervisor
        )
        providers.attach_runtime(runtime)
        app = create_app(
            settings,
            FixtureProvider(),
            lambda: now,
            assistant_runtime=runtime,
            assistant_catalog=catalog,
            assistant_providers=providers,
        )
        app_loop_ref: list[asyncio.AbstractEventLoop] = []
        loop_task_exceptions: list[dict[str, object]] = []

        async def capture_app_loop(request, call_next):
            loop = asyncio.get_running_loop()
            if not app_loop_ref:
                app_loop_ref.append(loop)
                loop.set_debug(True)

                def capture_loop_exception(_loop, context):
                    exception = context.get("exception")
                    task = context.get("task") or context.get("future")
                    coroutine = (
                        task.get_coro() if callable(getattr(task, "get_coro", None)) else None
                    )
                    source_traceback = context.get("source_traceback")
                    source_frames = []
                    if isinstance(source_traceback, list | tuple):
                        for frame in source_traceback[-8:]:
                            filename = getattr(frame, "filename", None)
                            line_number = getattr(frame, "lineno", None)
                            function = getattr(frame, "name", None)
                            if (
                                isinstance(filename, str)
                                and type(line_number) is int
                                and isinstance(function, str)
                            ):
                                source_frames.append(
                                    {
                                        "file": Path(filename).name,
                                        "line": line_number,
                                        "function": function,
                                    }
                                )
                    loop_task_exceptions.append(
                        {
                            "message": (
                                context.get("message")
                                if context.get("message")
                                in {
                                    "Task exception was never retrieved",
                                    "Exception in callback",
                                }
                                else "asyncio loop exception"
                            ),
                            "exception_type": (
                                type(exception).__name__ if exception is not None else None
                            ),
                            "task_name": (
                                task.get_name()
                                if callable(getattr(task, "get_name", None))
                                else None
                            ),
                            "coroutine_type": type(coroutine).__name__
                            if coroutine is not None
                            else None,
                            "coroutine_name": getattr(coroutine, "__qualname__", None),
                            "source_frames": source_frames,
                        }
                    )

                loop.set_exception_handler(capture_loop_exception)
            return await call_next(request)

        app.middleware("http")(capture_app_loop)
        server = uvicorn.Server(
            uvicorn.Config(
                app,
                host="127.0.0.1",
                port=app_port,
                log_level="critical",
                access_log=False,
                lifespan="on",
            )
        )
        server_thread = threading.Thread(target=server.run, daemon=True)
        observed_tool_result_markers: list[bytes] = []
        trace: dict[str, object] = {
            "provider_requests": [],
            "native_requests": [],
            "answer_bytes": 0,
            "answer_sha256": None,
            "turn_status": None,
            "conversation_detail_status": None,
            "purge_status": None,
            "credential_used": False,
            "loop_task_exceptions": loop_task_exceptions,
        }
        original_clear = runtime.clear_conversation_cache

        async def traced_clear(conversation_id: str) -> bool:
            cleared = await original_clear(conversation_id)
            trace["purge_status"] = "cleared" if cleared is True else "failed"
            return cleared

        runtime.clear_conversation_cache = traced_clear
        native_requests = trace["native_requests"]
        provider_requests = trace["provider_requests"]
        from stock_probs.assistant import runtime as runtime_module

        original_proxy = providers.proxy_chat_completion
        original_request = runtime._request
        original_prepare = supervisor.prepare_location

        async def traced_prepare_location(**values: str) -> dict[str, str]:
            try:
                prepared = await original_prepare(**values)
            except Exception as exc:
                trace["location_prepare_error_type"] = type(exc).__name__
                raise
            trace["location_prepare_provider_id"] = values.get("provider_id")
            trace["location_prepare_model_id"] = values.get("model_id")
            trace["location_prepare_directory"] = prepared.get("directory")
            return prepared

        def traced_proxy_chat_completion(provider_id, model_id_value, body, **request_context):
            messages = body.get("messages", []) if isinstance(body, Mapping) else []
            tools = body.get("tools", []) if isinstance(body, Mapping) else []
            tool_contents = (
                [
                    item.get("content").encode("utf-8")
                    for item in messages
                    if isinstance(item, Mapping)
                    and item.get("role") == "tool"
                    and isinstance(item.get("content"), str)
                    and item.get("content")
                ]
                if isinstance(messages, list)
                else []
            )
            observed_tool_result_markers.extend(tool_contents)
            expected_identity = _native_zen_expected_identity(request_context)
            identity_projection = _native_zen_identity_projection(
                [expected_identity[0]] if expected_identity[0] is not None else [],
                [expected_identity[1]] if expected_identity[1] is not None else [],
                native_sessions=[expected_identity[2]] if expected_identity[2] is not None else [],
                native_projects=[expected_identity[3]] if expected_identity[3] is not None else [],
                session_affinities=[expected_identity[4]]
                if expected_identity[4] is not None
                else [],
                session_id_aliases=[expected_identity[5]]
                if expected_identity[5] is not None
                else [],
                expected_session=expected_identity[2],
                expected_project=expected_identity[3],
            )
            provider_requests.append(
                {
                    "provider_id": provider_id,
                    "approved_model_id": model_id_value,
                    "credential_configured": zen_summary.credential_configured,
                    "native_model_alias": body.get("model") if isinstance(body, Mapping) else None,
                    "store": body.get("store") if isinstance(body, Mapping) else None,
                    "stream": body.get("stream") if isinstance(body, Mapping) else None,
                    "message_roles": [
                        item.get("role") for item in messages if isinstance(item, Mapping)
                    ]
                    if isinstance(messages, list)
                    else [],
                    "tool_result_receipts": [
                        {
                            "bytes": len(content),
                            "sha256": hashlib.sha256(content).hexdigest(),
                        }
                        for content in tool_contents
                    ],
                    "tool_names": [
                        item.get("function", {}).get("name")
                        for item in tools
                        if isinstance(item, Mapping) and isinstance(item.get("function"), Mapping)
                    ]
                    if isinstance(tools, list)
                    else [],
                    "native_identity": identity_projection,
                }
            )
            upstream = original_proxy(provider_id, model_id_value, body, **request_context)

            return _with_native_zen_identity(upstream, *expected_identity)

        providers.proxy_chat_completion = traced_proxy_chat_completion

        original_verify = runtime._verify_location

        async def traced_verify_location(context, directory, descriptor=None):
            trace["location_verify_started"] = True
            trace["location_verify_directory_matches"] = directory == str(
                location_root / context.execution_id
            )
            try:
                result = await original_verify(context, directory, descriptor)
            except Exception as exc:
                trace["location_verify_error_type"] = type(exc).__name__
                raise
            trace["location_verify_provider_ref"] = {
                "id": result.get("id"),
                "providerID": result.get("providerID"),
            }
            return result

        supervisor.prepare_location = traced_prepare_location
        runtime._verify_location = traced_verify_location

        async def traced_native_request(
            method,
            path,
            *,
            params=None,
            json=None,
            timeout,
            allow_startup_probe: bool = False,
        ):
            native_row: dict[str, object] = {
                "method": method,
                "path": re.sub(r"/ses[A-Za-z0-9_-]{8,128}(?=/|$)", "/<session>", path),
            }
            try:
                response = await original_request(
                    method,
                    path,
                    params=params,
                    json=json,
                    timeout=timeout,
                    allow_startup_probe=allow_startup_probe,
                )
            except Exception as exc:
                native_row["error_type"] = type(exc).__name__
                native_requests.append(native_row)
                raise
            native_row["status"] = response.status_code
            if method == "GET" and path.startswith("/api/session/") and path.count("/") == 3:
                try:
                    data = response.json().get("data", {})
                    if isinstance(data, Mapping):
                        native_row["outcome"] = data.get("outcome")
                except (ValueError, json.JSONDecodeError):
                    pass
            native_requests.append(native_row)
            return response

        runtime._request = traced_native_request
        _APP_CONTINUATION_WAITING.clear()
        _APP_CONTINUE.set()
        try:
            with nullcontext():
                server_thread.start()
                deadline = time.monotonic() + 15.0
                with httpx.Client(
                    base_url=origin,
                    headers={"origin": origin, "referer": origin + "/overview"},
                    timeout=httpx.Timeout(130.0, connect=2.0),
                    trust_env=False,
                ) as client:
                    while time.monotonic() < deadline:
                        try:
                            if client.get("/api/v1/health").status_code == 200:
                                break
                        except httpx.HTTPError:
                            time.sleep(0.1)
                    else:
                        raise RuntimeError("live Zen FastAPI loopback readiness timed out")
                    identity = _add_signed_in_user(app, 91820120)
                    client.cookies.set(SESSION_COOKIE_NAME, str(identity["token"]), path="/")
                    client.cookies.set(CSRF_COOKIE_NAME, str(identity["csrf"]), path="/")
                    context_response = client.get(
                        "/api/v1/assistant/context", params={"route": "/overview"}
                    )
                    context = context_response.json()["context"]
                    csrf = {"x-csrf-token": str(identity["csrf"])}
                    conversation_response = client.post(
                        "/api/v1/assistant/conversations",
                        json={"context": context},
                        headers=csrf,
                    )
                    if conversation_response.status_code != 201:
                        raise RuntimeError("live Zen conversation creation failed")
                    conversation_envelope = conversation_response.json()["conversation"]
                    conversation = conversation_envelope.get("conversation", conversation_envelope)
                    consent_response = client.put(
                        "/api/v1/assistant/models/" + quote(model.model_id, safe="") + "/consent",
                        json={
                            "policy_version": model_policy_version,
                            "accepted_terms": True,
                            "data_collection_opt_in": False,
                        },
                        headers=csrf,
                    )
                    if consent_response.status_code != 200:
                        raise RuntimeError("live Zen consent setup failed")
                    prompt = (
                        "Use workspace.summary exactly once, then briefly confirm you reviewed "
                        "the synthetic workspace summary. Do not mention real accounts or "
                        "personal information."
                    )
                    turn_response = client.post(
                        f"/api/v1/assistant/conversations/{conversation['id']}/turns",
                        json={
                            "prompt": prompt,
                            "model_id": model.model_id,
                            "policy_version": model_policy_version,
                            "context": context,
                            "context_preview_accepted": True,
                        },
                        headers=csrf,
                        timeout=10,
                    )
                    if turn_response.status_code != 202:
                        raise RuntimeError(
                            f"live Zen turn rejected with HTTP {turn_response.status_code}"
                        )
                    turn = turn_response.json()["turn"]
                    end = time.monotonic() + 125.0
                    current_turn: Mapping[str, object] = {}
                    while time.monotonic() < end:
                        detail = client.get(
                            f"/api/v1/assistant/conversations/{conversation['id']}", timeout=5
                        )
                        if detail.status_code == 200:
                            turns_payload = detail.json().get("turns", [])
                            current_turns = (
                                turns_payload.get("items", [])
                                if isinstance(turns_payload, Mapping)
                                else turns_payload
                            )
                            current_turn = next(
                                (
                                    row
                                    for row in current_turns
                                    if isinstance(row, Mapping) and row.get("id") == turn["id"]
                                ),
                                {},
                            )
                            if current_turn.get("status") not in {"queued", "running"}:
                                break
                        time.sleep(0.25)
                    trace["turn_status"] = current_turn.get("status")
                    trace["turn_error_code"] = current_turn.get("error_code")
                    trace["runtime_status"] = runtime.status().status
                    stored_turn = app.state.assistant.storage.get_turn(
                        int(identity["user_id"]), str(conversation["id"]), str(turn["id"])
                    )
                    trace["stored_turn_error_code"] = stored_turn.get("error_code")
                    detail = client.get(
                        f"/api/v1/assistant/conversations/{conversation['id']}", timeout=5
                    )
                    trace["conversation_detail_status"] = detail.status_code
                    detail_payload = detail.json() if detail.status_code == 200 else {}
                    messages_payload = detail_payload.get("messages", [])
                    events_payload = detail_payload.get("events", [])
                    messages = (
                        messages_payload.get("items", [])
                        if isinstance(messages_payload, Mapping)
                        else messages_payload
                    )
                    events = (
                        events_payload.get("items", [])
                        if isinstance(events_payload, Mapping)
                        else events_payload
                    )
                    answer = "".join(
                        item.get("text", "")
                        for item in messages
                        if isinstance(item, Mapping)
                        and item.get("role") == "assistant"
                        and isinstance(item.get("text"), str)
                    )
                    trace["answer_bytes"] = len(answer.encode("utf-8"))
                    trace["answer_sha256"] = hashlib.sha256(answer.encode("utf-8")).hexdigest()
                    trace["answer_nonempty"] = bool(answer.strip())
                    trace["workspace_summary_receipts"] = [
                        {
                            "name": item.get("data", {}).get("name"),
                            "status": item.get("data", {}).get("status"),
                            "result_bytes": item.get("data", {}).get("result_bytes"),
                            "result_sha256": item.get("data", {}).get("result_sha256"),
                        }
                        for item in events
                        if isinstance(item, Mapping)
                        and item.get("type") == "tool"
                        and isinstance(item.get("data"), Mapping)
                        and item.get("data", {}).get("name") == "workspace.summary"
                    ]
                    trace["terminal_outcome"] = current_turn.get("status")
                    native_ids = [
                        item.get("outcome")
                        for item in native_requests
                        if isinstance(item, Mapping) and "outcome" in item
                    ]
                    trace["native_terminal_outcomes"] = native_ids
                    conversation_row = detail_payload.get("conversation", {})
                    revision = (
                        conversation_row.get("revision")
                        if isinstance(conversation_row, Mapping)
                        else None
                    )
                    close_response = client.request(
                        "DELETE",
                        f"/api/v1/assistant/conversations/{conversation['id']}",
                        headers=csrf,
                        json={
                            "expected_revision": revision,
                            "confirmation_phrase": f"DELETE {str(conversation['id'])[-8:]}",
                        },
                    )
                    close_status = close_response.status_code
                    trace["conversation_delete_status"] = close_status
                    if trace["purge_status"] == "cleared":
                        live_values = {
                            "user_prompt": prompt,
                            "assistant_answer": answer,
                            **{
                                f"tool_result_{index}": value.decode("utf-8", "strict")
                                for index, value in enumerate(observed_tool_result_markers)
                            },
                        }
                        live_markers: dict[str, bytes] = {}
                        for label, value in live_values.items():
                            if not value:
                                continue
                            live_markers[label] = value.encode("utf-8")
                            live_markers[label + "_json"] = json.dumps(
                                value, ensure_ascii=False, separators=(",", ":")
                            ).encode("utf-8")
                        trace["purge_marker_scan"] = _scan_synthetic_storage(
                            home, home / "tmp", markers=live_markers
                        )
        finally:
            if app_loop_ref and app_loop_ref[0].is_running():
                close_future = asyncio.run_coroutine_threadsafe(runtime.close(), app_loop_ref[0])
                try:
                    close_future.result(timeout=4.0)
                    trace["runtime_close_completed_on_app_loop"] = True
                except Exception as exc:
                    close_future.cancel()
                    trace["runtime_close_error_type"] = type(exc).__name__
                    trace["runtime_close_completed_on_app_loop"] = False
            else:
                trace["runtime_close_completed_on_app_loop"] = False
            server.should_exit = True
            server_thread.join(timeout=8.0)
            trace["app_server_stopped"] = not server_thread.is_alive()
            supervisor._stop_worker()
            runtime_module._APP_BASE_URL = previous_base_url
            runtime_module._LOCATION_ROOT = previous_location_root

        accepted_sources = trace.get("workspace_summary_receipts", [])
        provider_rows = provider_requests if isinstance(provider_requests, list) else []
        native_rows = native_requests if isinstance(native_requests, list) else []
        purge_scan = trace.get("purge_marker_scan", {})
        purge_occurrences = (
            purge_scan.get("synthetic_marker_occurrences", {})
            if isinstance(purge_scan, Mapping)
            else {}
        )
        trace["purge_exact_markers_cleared"] = (
            isinstance(purge_scan, Mapping)
            and purge_scan.get("oversized_files_skipped") == 0
            and len(observed_tool_result_markers) == 1
            and isinstance(purge_occurrences, Mapping)
            and bool(purge_occurrences)
            and all(value == 0 for value in purge_occurrences.values())
        )
        trace["native_v2_mcp_answer_success"] = (
            trace.get("turn_status") == "completed"
            and trace.get("conversation_detail_status") == 200
            and trace.get("answer_nonempty") is True
            and len(accepted_sources) == 1
            and isinstance(accepted_sources[0], Mapping)
            and accepted_sources[0].get("status") == "completed"
            and accepted_sources[0].get("name") == "workspace.summary"
            and any(
                isinstance(row, Mapping)
                and row.get("tool_names")
                and "signal-ledger_workspace_summary" in row.get("tool_names", [])
                for row in provider_rows
            )
            and any(
                isinstance(row, Mapping)
                and isinstance(row.get("message_roles"), list)
                and "tool" in row.get("message_roles", [])
                for row in provider_rows
            )
            and bool(provider_rows)
            and all(
                isinstance(row, Mapping)
                and row.get("provider_id") == model.provider_id
                and row.get("approved_model_id") == model.model_id
                and row.get("credential_configured") is False
                and row.get("native_model_alias") == "assistant-selected"
                and row.get("store") is False
                and row.get("stream") is True
                and isinstance(row.get("native_identity"), Mapping)
                and row["native_identity"].get("native_session_shape_valid") is True
                and row["native_identity"].get("native_session_matches_active") is True
                and row["native_identity"].get("native_project_shape_valid") is True
                and row["native_identity"].get("native_project_matches_active") is True
                and row["native_identity"].get("session_aliases_match_native") is True
                for row in provider_rows
            )
            and any(
                isinstance(row, Mapping) and row.get("outcome") == "succeeded"
                for row in native_rows
            )
            and trace.get("purge_status") == "cleared"
            and trace.get("conversation_delete_status") == 200
            and trace.get("purge_exact_markers_cleared") is True
            and trace.get("runtime_close_completed_on_app_loop") is True
            and trace.get("app_server_stopped") is True
            and loop_task_exceptions == []
        )
        result = {
            "command": ".dev-venv/bin/python tests/native_assistant_probe.py --live-zen",
            "started_at": started_at,
            "finished_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "binary_version": binary_version,
            "approved_model": model.model_id,
            "credential_used": False,
            "synthetic_context_only": True,
            "privacy_policy": {
                "free": model.free,
                "training": model.training,
                "data_collection_allowed": model.data_collection_allowed,
                "data_collection_default": model.data_collection_default,
                "policy_version": model.policy_version,
            },
            "provider_connection_status": zen_summary.connection_status,
            "trace": trace,
            "native_v2_mcp_answer_success": trace["native_v2_mcp_answer_success"],
        }
        print(json.dumps(result, sort_keys=True, separators=(",", ":")))
        return 0 if result["native_v2_mcp_answer_success"] else 1


class _AttachedProbeFailure(Exception):
    """Safe, non-sensitive attached-app probe failure."""

    def __init__(self, code: str, status: int | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.status = status


def _attached_new_interaction_tracker(owner_index: int) -> dict[str, object]:
    if type(owner_index) is not int or owner_index not in {0, 1}:
        raise _AttachedProbeFailure("interaction_timeline_invalid")
    return {
        "owner_index": owner_index,
        "turn_started_monotonic": None,
        "seen_sequences": {},
        "approval_keys": set(),
        "terminal_status": None,
        "phases": {
            phase: {"count": 0, "first_elapsed_ms": None, "last_elapsed_ms": None}
            for phase in _ATTACH_TIMELINE_PHASES
        },
    }


def _attached_timeline_elapsed_ms(tracker: Mapping[str, object], now: object) -> int:
    started = tracker.get("turn_started_monotonic")
    if (
        isinstance(started, bool)
        or not isinstance(started, int | float)
        or isinstance(started, int)
        and abs(started) > 1_000_000_000_000
        or not math.isfinite(started)
        or isinstance(now, bool)
        or not isinstance(now, int | float)
        or isinstance(now, int)
        and abs(now) > 1_000_000_000_000
        or not math.isfinite(now)
    ):
        raise _AttachedProbeFailure("interaction_timeline_invalid")
    elapsed = int(round((now - started) * 1000))
    if not 0 <= elapsed <= _ATTACH_TIMELINE_MAX_ELAPSED_MS:
        raise _AttachedProbeFailure("interaction_timeline_invalid")
    return elapsed


def _attached_record_timeline_phase(
    tracker: dict[str, object],
    phase: str,
    *,
    now: float | None = None,
    dedupe_key: str | None = None,
) -> None:
    phases = tracker.get("phases")
    if not isinstance(phases, dict) or phase not in _ATTACH_TIMELINE_PHASES:
        raise _AttachedProbeFailure("interaction_timeline_invalid")
    approval_keys = tracker.get("approval_keys")
    if dedupe_key is not None:
        if (
            phase not in {"search_approval", "fetch_approval"}
            or not isinstance(dedupe_key, str)
            or not 1 <= len(dedupe_key) <= 64
            or not isinstance(approval_keys, set)
        ):
            raise _AttachedProbeFailure("interaction_timeline_invalid")
        expected_id = r"[0-9a-f-]{36}" if phase == "search_approval" else r"[0-9a-f]{32}"
        if re.fullmatch(expected_id, dedupe_key) is None:
            raise _AttachedProbeFailure("interaction_timeline_invalid")
        marker = f"{phase}:{dedupe_key}"
        if marker in approval_keys:
            return
        approval_keys.add(marker)
    row = phases.get(phase)
    if not isinstance(row, dict) or type(row.get("count")) is not int:
        raise _AttachedProbeFailure("interaction_timeline_invalid")
    count = row["count"]
    maximum = 1 if phase == "terminal" else _ATTACH_TIMELINE_MAX_PHASE_COUNT
    if not 0 <= count < maximum:
        raise _AttachedProbeFailure("interaction_timeline_invalid")
    started = tracker.get("turn_started_monotonic")
    if started is None:
        raise _AttachedProbeFailure("interaction_timeline_invalid")
    elapsed_ms = _attached_timeline_elapsed_ms(tracker, time.monotonic() if now is None else now)
    first = row.get("first_elapsed_ms")
    row["count"] = count + 1
    row["first_elapsed_ms"] = elapsed_ms if first is None else first
    row["last_elapsed_ms"] = elapsed_ms


def _attached_observe_interaction_snapshot(
    tracker: dict[str, object],
    *,
    turn_id: str,
    event_rows: object,
    turn_rows: object,
    now: float | None = None,
) -> None:
    """Count only fixed preview/source classes, deduplicated by app event sequence."""

    if not isinstance(event_rows, list) or len(event_rows) > 200 or not isinstance(turn_rows, list):
        raise _AttachedProbeFailure("interaction_timeline_invalid")
    seen = tracker.get("seen_sequences")
    if not isinstance(seen, dict):
        raise _AttachedProbeFailure("interaction_timeline_invalid")
    observed_at = time.monotonic() if now is None else now
    if (
        isinstance(observed_at, bool)
        or not isinstance(observed_at, int | float)
        or isinstance(observed_at, int)
        and abs(observed_at) > 1_000_000_000_000
        or not math.isfinite(observed_at)
    ):
        raise _AttachedProbeFailure("interaction_timeline_invalid")
    if tracker.get("turn_started_monotonic") is not None:
        _attached_timeline_elapsed_ms(tracker, observed_at)
    relevant = {
        "private_context_preview": "search_preview",
        "webfetch_preview": "fetch_preview",
    }
    for event in event_rows:
        if not isinstance(event, Mapping) or event.get("turn_id") != turn_id:
            continue
        kind = event.get("type")
        data = event.get("data")
        phase = relevant.get(kind) if isinstance(kind, str) else None
        if kind == "source":
            if not isinstance(data, Mapping):
                raise _AttachedProbeFailure("interaction_timeline_invalid")
            source_type = data.get("source_type")
            if source_type == "native_search_text_unverified":
                phase = "search_source"
            elif source_type == "native_webfetch_guarded":
                phase = "fetch_source"
            else:
                raise _AttachedProbeFailure("interaction_timeline_invalid")
        if phase is None:
            continue
        sequence = event.get("sequence")
        if (
            type(sequence) is not int
            or not 1 <= sequence <= _ATTACH_TIMELINE_MAX_EVENT_SEQUENCE
            or not isinstance(data, Mapping)
        ):
            raise _AttachedProbeFailure("interaction_timeline_invalid")
        if phase == "search_preview":
            preview_id = data.get("preview_id")
            if (
                not isinstance(preview_id, str)
                or re.fullmatch(r"[0-9a-f-]{36}", preview_id) is None
            ):
                raise _AttachedProbeFailure("interaction_timeline_invalid")
        elif phase == "fetch_preview":
            preview_id = data.get("preview_id")
            if not isinstance(preview_id, str) or re.fullmatch(r"[0-9a-f]{32}", preview_id) is None:
                raise _AttachedProbeFailure("interaction_timeline_invalid")
        previous = seen.get(sequence)
        if previous is not None:
            if previous != phase:
                raise _AttachedProbeFailure("interaction_timeline_invalid")
            continue
        if len(seen) >= 200:
            raise _AttachedProbeFailure("interaction_timeline_invalid")
        seen[sequence] = phase
        _attached_record_timeline_phase(tracker, phase, now=observed_at)

    terminal_rows = [
        row for row in turn_rows if isinstance(row, Mapping) and row.get("id") == turn_id
    ]
    if len(terminal_rows) > 1:
        raise _AttachedProbeFailure("interaction_timeline_invalid")
    if not terminal_rows:
        return
    status = terminal_rows[0].get("status")
    if isinstance(status, str) and status in {"completed", "cancelled", "failed", "timed_out"}:
        previous_status = tracker.get("terminal_status")
        if previous_status is not None and previous_status != status:
            raise _AttachedProbeFailure("interaction_timeline_invalid")
        tracker["terminal_status"] = status
        phases = tracker.get("phases")
        terminal = phases.get("terminal") if isinstance(phases, dict) else None
        if isinstance(terminal, dict) and terminal.get("count") == 0:
            _attached_record_timeline_phase(tracker, "terminal", now=observed_at)
    elif not isinstance(status, str) or status not in {"queued", "running"}:
        raise _AttachedProbeFailure("interaction_timeline_invalid")


def _attached_interaction_diagnostic(
    trackers: list[dict[str, object]], *, now: float | None = None
) -> dict[str, object]:
    if len(trackers) != 2:
        raise _AttachedProbeFailure("interaction_timeline_invalid")
    observed_at = time.monotonic() if now is None else now
    if (
        isinstance(observed_at, bool)
        or not isinstance(observed_at, int | float)
        or isinstance(observed_at, int)
        and abs(observed_at) > 1_000_000_000_000
        or not math.isfinite(observed_at)
    ):
        raise _AttachedProbeFailure("interaction_timeline_invalid")
    owners: list[dict[str, object]] = []
    for owner_index, tracker in enumerate(trackers):
        if tracker.get("owner_index") != owner_index:
            raise _AttachedProbeFailure("interaction_timeline_invalid")
        started = tracker.get("turn_started_monotonic")
        observed_elapsed_ms = (
            None if started is None else _attached_timeline_elapsed_ms(tracker, observed_at)
        )
        phases = tracker.get("phases")
        if not isinstance(phases, dict) or set(phases) != set(_ATTACH_TIMELINE_PHASES):
            raise _AttachedProbeFailure("interaction_timeline_invalid")
        phase_rows = []
        for phase in _ATTACH_TIMELINE_PHASES:
            row = phases[phase]
            if not isinstance(row, Mapping):
                raise _AttachedProbeFailure("interaction_timeline_invalid")
            count = row.get("count")
            first = row.get("first_elapsed_ms")
            last = row.get("last_elapsed_ms")
            maximum = 1 if phase == "terminal" else _ATTACH_TIMELINE_MAX_PHASE_COUNT
            if type(count) is not int or not 0 <= count <= maximum:
                raise _AttachedProbeFailure("interaction_timeline_invalid")
            if count == 0:
                if first is not None or last is not None:
                    raise _AttachedProbeFailure("interaction_timeline_invalid")
            elif (
                type(first) is not int
                or type(last) is not int
                or not 0 <= first <= last <= _ATTACH_TIMELINE_MAX_ELAPSED_MS
                or observed_elapsed_ms is None
                or last > observed_elapsed_ms
            ):
                raise _AttachedProbeFailure("interaction_timeline_invalid")
            if count:
                phase_rows.append(
                    {
                        "phase": phase,
                        "count": count,
                        "first_elapsed_ms": first,
                        "last_elapsed_ms": last,
                    }
                )
        phase_rows.sort(
            key=lambda row: (
                row["first_elapsed_ms"],
                _ATTACH_TIMELINE_PHASES.index(row["phase"]),
            )
        )
        terminal_status = tracker.get("terminal_status")
        if terminal_status is not None and (
            not isinstance(terminal_status, str)
            or terminal_status not in {"completed", "cancelled", "failed", "timed_out"}
        ):
            raise _AttachedProbeFailure("interaction_timeline_invalid")
        terminal_phase = phases["terminal"]
        terminal_count = terminal_phase.get("count")
        if (terminal_status is None) != (terminal_count == 0):
            raise _AttachedProbeFailure("interaction_timeline_invalid")
        turn_elapsed_ms = (
            terminal_phase["last_elapsed_ms"] if terminal_count == 1 else observed_elapsed_ms
        )
        owners.append(
            {
                "owner_index": owner_index,
                "turn_elapsed_ms": turn_elapsed_ms,
                "terminal_status": terminal_status,
                "phases": phase_rows,
            }
        )
    return {
        "scope": "failure_diagnostic_only",
        "status": "available",
        "elapsed_time_source": "host_monotonic",
        "owners": owners,
        "worker_restart_evidence": "unavailable",
    }


def _attached_totp_code(secret: str, *, at: datetime | None = None) -> str:
    """Create one six-digit synthetic RFC 6238 SHA-1 code without retaining its secret."""

    if re.fullmatch(r"[A-Za-z2-7]{16,64}", secret) is None:
        raise _AttachedProbeFailure("totp_fixture_invalid")
    padded_secret = secret.upper() + "=" * (-len(secret) % 8)
    try:
        key = base64.b32decode(padded_secret, casefold=True)
    except ValueError:
        raise _AttachedProbeFailure("totp_fixture_invalid") from None
    if len(key) < 16:
        raise _AttachedProbeFailure("totp_fixture_invalid")
    timestamp = at if at is not None else datetime.now(UTC)
    counter = int(timestamp.timestamp()) // 30
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    truncated = int.from_bytes(digest[offset : offset + 4], "big") & 0x7FFF_FFFF
    return f"{truncated % 1_000_000:06d}"


def _attached_json(response: httpx.Response) -> dict[str, object]:
    if len(response.content) > _ATTACH_MAX_RESPONSE_BYTES:
        raise _AttachedProbeFailure("response_too_large", response.status_code)
    try:
        value = response.json()
    except (ValueError, json.JSONDecodeError):
        raise _AttachedProbeFailure("response_invalid", response.status_code) from None
    if not isinstance(value, dict):
        raise _AttachedProbeFailure("response_invalid", response.status_code)
    return value


def _attached_require(
    response: httpx.Response, payload: Mapping[str, object], expected: set[int]
) -> dict[str, object]:
    if response.status_code not in expected:
        error = payload.get("error")
        code = error.get("code") if isinstance(error, Mapping) else None
        if not isinstance(code, str) or re.fullmatch(r"[a-z0-9_]{1,64}", code) is None:
            code = "http_error"
        raise _AttachedProbeFailure(code, response.status_code)
    return dict(payload)


def _attached_delete_public_error_code(payload: Mapping[str, object], status_code: int) -> str:
    """Project only a fixed public deletion error code, never its response detail."""

    if status_code == 200:
        return "none"
    error = payload.get("error")
    code = error.get("code") if isinstance(error, Mapping) else None
    if not isinstance(code, str) or len(code) > 64 or code not in _ATTACH_DELETE_PUBLIC_ERROR_CODES:
        return "unknown"
    return code


def _attached_require_search_confirmation(
    payload: Mapping[str, object], preview_id: str, *, allow: bool
) -> None:
    """Require a successful search confirmation to bind to its exact preview and decision."""

    if type(allow) is not bool or not isinstance(preview_id, str) or not preview_id:
        raise _AttachedProbeFailure("search_confirmation_invalid")
    expected_status = "approved" if allow else "denied"
    if payload.get("preview_id") != preview_id or payload.get("status") != expected_status:
        raise _AttachedProbeFailure("search_confirmation_invalid")


def _attached_conversation_detail(
    payload: Mapping[str, object], *, created: bool = False
) -> tuple[Mapping[str, object], Mapping[str, object]]:
    """Validate the app's wrapped conversation detail before using its owner-scoped row."""

    detail_value = payload.get("conversation") if created else payload
    if not isinstance(detail_value, Mapping):
        raise _AttachedProbeFailure("conversation_detail_invalid")
    detail = detail_value
    conversation_value = detail.get("conversation")
    if not isinstance(conversation_value, Mapping):
        raise _AttachedProbeFailure("conversation_detail_invalid")
    conversation_id = conversation_value.get("id")
    revision = conversation_value.get("revision")
    confirmation_phrase = conversation_value.get("delete_confirmation_phrase")
    if (
        not isinstance(conversation_id, str)
        or re.fullmatch(r"[0-9a-f-]{36}", conversation_id) is None
        or type(revision) is not int
        or revision < 1
        or confirmation_phrase != f"DELETE {conversation_id[-8:]}"
    ):
        raise _AttachedProbeFailure("conversation_detail_invalid")
    for key in ("messages", "events"):
        page = detail.get(key)
        if not isinstance(page, Mapping) or not isinstance(page.get("items"), list):
            raise _AttachedProbeFailure("conversation_detail_invalid")
    if not isinstance(detail.get("turns"), list) or not isinstance(detail.get("actions"), list):
        raise _AttachedProbeFailure("conversation_detail_invalid")
    return detail, conversation_value


def _attached_delete_with_pending_retry(
    request: Callable[..., tuple[httpx.Response, dict[str, object]]],
    owner_index: int,
    conversation_id: str,
    *,
    deadline: float,
    diagnostic: dict[str, object],
    now: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> tuple[int, str]:
    """Retry only a pending cache-clear DELETE within the existing probe deadline."""

    if (
        type(owner_index) is not int
        or owner_index not in {0, 1}
        or not isinstance(conversation_id, str)
        or re.fullmatch(r"[0-9a-f-]{36}", conversation_id) is None
        or not math.isfinite(deadline)
    ):
        raise _AttachedProbeFailure("conversation_delete_invalid")
    diagnostic["attempt_count"] = 0
    diagnostic["pending_count"] = 0
    retry_delay = _ATTACH_DELETE_RETRY_INITIAL_SECONDS
    last_status: int | None = None
    last_error_code: str | None = None

    while True:
        remaining = deadline - now()
        if remaining <= 0:
            if last_status is None or last_error_code is None:
                raise _AttachedProbeFailure("assistant_delete_deadline")
            return last_status, last_error_code

        detail_response, detail_payload = request(
            owner_index,
            "GET",
            f"/api/v1/assistant/conversations/{conversation_id}",
            timeout=min(8.0, remaining),
        )
        _attached_require(detail_response, detail_payload, {200})
        _detail, conversation = _attached_conversation_detail(detail_payload)
        if conversation.get("id") != conversation_id:
            raise _AttachedProbeFailure("conversation_owner_mismatch", detail_response.status_code)
        revision = conversation["revision"]
        confirmation_phrase = conversation["delete_confirmation_phrase"]
        remaining = deadline - now()
        if remaining <= 0:
            if last_status is None or last_error_code is None:
                raise _AttachedProbeFailure("assistant_delete_deadline")
            return last_status, last_error_code

        delete_response, delete_payload = request(
            owner_index,
            "DELETE",
            f"/api/v1/assistant/conversations/{conversation_id}",
            body={
                "expected_revision": revision,
                "confirmation_phrase": confirmation_phrase,
            },
            csrf=True,
            timeout=min(8.0, remaining),
        )
        status = delete_response.status_code
        error_code = _attached_delete_public_error_code(delete_payload, status)
        last_status = status
        last_error_code = error_code
        attempt_count = int(diagnostic["attempt_count"]) + 1
        pending_count = int(diagnostic["pending_count"]) + int(
            status == 503 and error_code == "assistant_cache_clear_pending"
        )
        diagnostic["attempt_count"] = attempt_count
        diagnostic["pending_count"] = pending_count
        diagnostic["http_status"] = status
        diagnostic["public_error_code"] = error_code
        if status == 200 or status != 503 or error_code != "assistant_cache_clear_pending":
            return status, error_code
        remaining = deadline - now()
        if remaining <= 0:
            return status, error_code
        sleep(min(retry_delay, remaining))
        retry_delay = min(retry_delay * 2, _ATTACH_DELETE_RETRY_MAX_SECONDS)


def _attached_owner_evidence(
    detail: Mapping[str, object] | None,
    *,
    owner_index: int,
    turn_id: str | None,
    expected_model_id: str | None,
    expected_tool_digest: str | None,
) -> dict[str, object]:
    """Summarize a turn without retaining or returning prompt, answer, or tool content."""

    summary: dict[str, object] = {
        "owner_index": owner_index,
        "terminal_status": "not_started" if turn_id is None else "unknown",
        "model_id_matches": False,
        "assistant_message_count": 0,
        "assistant_text_bytes": 0,
        "answer_nonempty": False,
        "workspace_summary_receipt_count": 0,
        "workspace_summary_digest_present": False,
        "workspace_summary_digest_matches": False,
        "selected_model_event_count": 0,
        "selected_model_id_matches": False,
        "native_search_source_count": 0,
        "native_webfetch_source_count": 0,
        "native_webfetch_source_hosts": [],
        "native_webfetch_source_types": [],
        "native_webfetch_source_url_sha256": [],
        "conversation_event_count": 0,
        "turn_error_code": None,
        "turn_failure_stage": "none",
    }
    if detail is None or turn_id is None:
        return summary

    turns = detail.get("turns")
    turn = next(
        (row for row in turns if isinstance(row, Mapping) and row.get("id") == turn_id)
        if isinstance(turns, list)
        else None,
        None,
    )
    if isinstance(turn, Mapping):
        status = turn.get("status")
        if status in {"running", "completed", "cancelled", "failed", "timed_out"}:
            summary["terminal_status"] = status
        summary["model_id_matches"] = turn.get("model_id") == expected_model_id

    messages_root = detail.get("messages")
    message_rows = messages_root.get("items") if isinstance(messages_root, Mapping) else None
    if isinstance(message_rows, list):
        assistant_messages = [
            row
            for row in message_rows
            if isinstance(row, Mapping)
            and row.get("turn_id") == turn_id
            and row.get("role") == "assistant"
            and isinstance(row.get("text"), str)
        ]
        answer_bytes = sum(len(row["text"].encode("utf-8")) for row in assistant_messages)
        summary["assistant_message_count"] = len(assistant_messages)
        summary["assistant_text_bytes"] = answer_bytes
        summary["answer_nonempty"] = answer_bytes > 0

    events_root = detail.get("events")
    event_rows = events_root.get("items") if isinstance(events_root, Mapping) else None
    if isinstance(event_rows, list):
        turn_events = [
            event
            for event in event_rows
            if isinstance(event, Mapping) and event.get("turn_id") == turn_id
        ]
        summary["conversation_event_count"] = len(event_rows)
        error_rows = [event for event in turn_events if event.get("type") == "error"]
        if summary["terminal_status"] != "completed":
            if len(error_rows) == 1:
                error_data = error_rows[0].get("data")
                error_code = error_data.get("code") if isinstance(error_data, Mapping) else None
                if isinstance(error_code, str) and error_code in _ATTACH_SAFE_TURN_ERROR_CODES:
                    summary["turn_error_code"] = error_code
                    summary["turn_failure_stage"] = (
                        "before_model_session_event"
                        if not any(event.get("type") == "meta" for event in turn_events)
                        else "after_model_session_event"
                    )
                else:
                    summary["turn_failure_stage"] = "unknown_terminal"
            else:
                summary["turn_failure_stage"] = "unknown_terminal"
        summary["native_search_source_count"] = sum(
            event.get("type") == "source" for event in turn_events
        )
        summary["native_webfetch_source_count"] = sum(
            event.get("type") == "source"
            and isinstance(event.get("data"), Mapping)
            and event["data"].get("source_type") == "native_webfetch_guarded"
            for event in turn_events
        )
        fetch_sources = [
            event["data"]
            for event in turn_events
            if event.get("type") == "source"
            and isinstance(event.get("data"), Mapping)
            and event["data"].get("source_type") == "native_webfetch_guarded"
        ]
        summary["native_webfetch_source_hosts"] = sorted(
            {
                host
                for source in fetch_sources
                if (host := _attached_source_host(source)) is not None
            }
        )
        summary["native_webfetch_source_types"] = sorted(
            {
                str(source["source_type"])
                for source in fetch_sources
                if isinstance(source.get("source_type"), str)
            }
        )
        summary["native_webfetch_source_url_sha256"] = sorted(
            {
                hashlib.sha256(source["url"].encode("utf-8")).hexdigest()
                for source in fetch_sources
                if isinstance(source.get("url"), str)
            }
        )
        summary_data = [
            event.get("data")
            for event in turn_events
            if event.get("type") == "tool" and isinstance(event.get("data"), Mapping)
        ]
        completed_summaries = [
            data
            for data in summary_data
            if data.get("name") == "workspace.summary" and data.get("status") == "completed"
        ]
        observed_digests = [
            data.get("result_sha256")
            for data in completed_summaries
            if isinstance(data.get("result_sha256"), str)
        ]
        summary["workspace_summary_receipt_count"] = len(completed_summaries)
        summary["workspace_summary_digest_present"] = bool(observed_digests)
        summary["workspace_summary_digest_matches"] = (
            isinstance(expected_tool_digest, str) and expected_tool_digest in observed_digests
        )
        model_events = [
            event.get("data")
            for event in turn_events
            if event.get("type") == "meta" and isinstance(event.get("data"), Mapping)
        ]
        summary["selected_model_event_count"] = len(model_events)
        summary["selected_model_id_matches"] = bool(model_events) and all(
            data.get("model_id") == expected_model_id for data in model_events
        )
    return summary


def _attached_acceptance_failures(result: Mapping[str, object]) -> list[str]:
    """Return only static condition identifiers for a completed but incomplete probe."""

    failures: list[str] = []
    if result.get("turn_requests_issued_concurrently") is not True:
        failures.append("turn_requests_not_concurrent")
    owners = result.get("owners")
    if not isinstance(owners, list) or len(owners) != 2:
        owners = []
    for owner_index in range(2):
        owner = owners[owner_index] if owner_index < len(owners) else None
        prefix = f"owner{owner_index}_"
        checks = (
            (
                "turn_not_completed",
                isinstance(owner, Mapping) and owner.get("terminal_status") == "completed",
            ),
            (
                "model_id_mismatch",
                isinstance(owner, Mapping) and owner.get("model_id_matches") is True,
            ),
            ("answer_empty", isinstance(owner, Mapping) and owner.get("nonempty_answer") is True),
            (
                "workspace_summary_receipt_count_invalid",
                isinstance(owner, Mapping) and owner.get("workspace_summary_receipt_count") == 1,
            ),
            (
                "workspace_summary_digest_mismatch",
                isinstance(owner, Mapping)
                and owner.get("workspace_summary_digest_matches") is True,
            ),
            (
                "selected_model_mismatch",
                isinstance(owner, Mapping) and owner.get("selected_model_id_matches") is True,
            ),
        )
        failures.extend(prefix + code for code, passed in checks if not passed)
    if result.get("search_approved") is not True:
        failures.append("search_not_approved")
    if result.get("active_search_scan_acknowledged") is not True:
        failures.append("active_search_checkpoint_missing")
    if (
        not owners
        or not isinstance(owners[1], Mapping)
        or owners[1].get("native_search_source_count", 0) < 1
    ):
        failures.append("native_search_sources_missing")
    if result.get("webfetch_approved") is not True or result.get("webfetch_approval_count") != 1:
        failures.append("webfetch_not_approved")
    if (
        not owners
        or not isinstance(owners[0], Mapping)
        or owners[0].get("webfetch_approved") is not False
        or not isinstance(owners[1], Mapping)
        or owners[1].get("webfetch_approved") is not True
    ):
        failures.append("webfetch_approval_not_owner_bound")
    if (
        not owners
        or not isinstance(owners[1], Mapping)
        or owners[1].get("native_webfetch_source_count") != 1
        or owners[1].get("native_webfetch_source_hosts") != ["www.iana.org"]
        or owners[1].get("native_webfetch_source_types") != ["native_webfetch_guarded"]
    ):
        failures.append("native_webfetch_source_missing")
    deletions = result.get("conversation_delete_statuses")
    if not isinstance(deletions, list) or len(deletions) != 2 or deletions[0] != 200:
        failures.append("owner0_conversation_delete_failed")
    if not isinstance(deletions, list) or len(deletions) != 2 or deletions[1] != 200:
        failures.append("owner1_conversation_delete_failed")
    if result.get("cross_owner_conversation_status") != 404:
        failures.append("cross_owner_access_not_denied")
    if result.get("forged_internal_mcp_status") != 404:
        failures.append("forged_internal_mcp_not_denied")
    if result.get("assistant_worker_status_after_turns") != "ready":
        failures.append("worker_not_ready_after_turns")
    if result.get("same_supervised_app_reachable") is not True:
        failures.append("supervised_app_not_reachable")
    if any(code not in _ATTACH_ACCEPTANCE_FAILURES for code in failures):
        raise _AttachedProbeFailure("acceptance_condition_invalid")
    return failures


def _attached_worker_diagnostic(
    request: Callable[..., tuple[httpx.Response, dict[str, object]]],
) -> dict[str, object]:
    """Return only fixed public readiness fields for a bounded worker-status diagnosis."""

    readiness_response, readiness = request(0, "GET", "/api/v1/readiness")
    assistant_readiness = readiness.get("assistant")
    readiness_status = (
        assistant_readiness.get("status") if isinstance(assistant_readiness, Mapping) else None
    )
    return {
        "readiness_http_status": readiness_response.status_code,
        "readiness_status": (
            readiness.get("status") if readiness_response.status_code == 200 else None
        ),
        "schema_version": readiness.get("schema_version")
        if type(readiness.get("schema_version")) is int
        else None,
        "assistant_enabled": assistant_readiness.get("enabled")
        if isinstance(assistant_readiness, Mapping)
        and type(assistant_readiness.get("enabled")) is bool
        else None,
        "assistant_readiness": readiness_status
        if readiness_status in {"disabled", "starting", "ready", "unavailable", "stopped"}
        else None,
    }


def _attached_event_data(event: object) -> tuple[str | None, Mapping[str, object]]:
    if not isinstance(event, Mapping):
        return None, {}
    kind = event.get("type")
    data = event.get("data")
    return (kind if isinstance(kind, str) else None, data if isinstance(data, Mapping) else {})


def _attached_source_host(source: Mapping[str, object]) -> str | None:
    """Accept only complete public HTTPS destinations emitted by the app normalizer."""

    from ipaddress import ip_address

    value = source.get("url")
    if not isinstance(value, str) or not 1 <= len(value) <= 2048:
        return None
    try:
        parsed = urlsplit(value)
        host = parsed.hostname
        if (
            parsed.scheme != "https"
            or not host
            or parsed.username is not None
            or parsed.password is not None
            or parsed.port not in {None, 443}
            or parsed.fragment
            or any(ord(char) < 33 for char in value)
            or host == "localhost"
            or host.endswith(".localhost")
        ):
            return None
        try:
            address = ip_address(host)
        except ValueError:
            address = None
        if address is not None and not address.is_global:
            return None
        return host.casefold()
    except ValueError:
        return None


def _attached_reviewed_model_row(rows: object, reviewed_model_id: str) -> Mapping[str, object]:
    """Require the exact catalog-reviewed model and report only the failed public predicate."""

    if not isinstance(rows, list):
        raise _AttachedProbeFailure("model_inventory_invalid")
    row = next(
        (
            item
            for item in rows
            if isinstance(item, Mapping) and item.get("model_id") == reviewed_model_id
        ),
        None,
    )
    if not isinstance(row, Mapping):
        raise _AttachedProbeFailure("reviewed_model_not_in_inventory")
    if row.get("provider_id") != "opencode-zen":
        raise _AttachedProbeFailure("reviewed_model_provider_mismatch")
    if row.get("available") is not True:
        raise _AttachedProbeFailure("reviewed_model_not_available")
    if row.get("free") is not True:
        raise _AttachedProbeFailure("reviewed_model_not_free")
    if row.get("training_uses_data") is not False:
        raise _AttachedProbeFailure("reviewed_model_training_not_disabled")
    if not isinstance(row.get("privacy_policy_version"), str) or not row["privacy_policy_version"]:
        raise _AttachedProbeFailure("reviewed_model_privacy_version_missing")
    if not isinstance(row.get("billing_policy_version"), str) or not row["billing_policy_version"]:
        raise _AttachedProbeFailure("reviewed_model_billing_version_missing")
    if type(row.get("revision")) is not int or row["revision"] < 0:
        raise _AttachedProbeFailure("reviewed_model_revision_invalid")
    return row


def run_attached_existing_app_probe() -> int:
    """Drive two isolated synthetic owners through an already supervised candidate app."""

    from stock_probs.auth import CSRF_COOKIE_NAME, SESSION_COOKIE_NAME

    started_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    raw = sys.stdin.buffer.readline(_ATTACH_MAX_STDIN_BYTES + 1)
    result: dict[str, object] = {
        "mode": "attach-existing-app",
        "started_at": started_at,
        "origin": _ATTACH_ORIGIN,
        "synthetic_owners": 2,
        "turn_requests_issued_concurrently": False,
        "active_search_scan_acknowledged": False,
        "search_approved": False,
        "search_approval_count": 0,
        "webfetch_approved": False,
        "webfetch_approval_count": 0,
        "webfetch_requested_url_sha256": hashlib.sha256(
            _ATTACH_WEBFETCH_URL.encode("utf-8")
        ).hexdigest(),
        "same_supervised_app_reachable": False,
    }
    clients: list[httpx.Client] = []
    conversations: list[str] = []
    turn_records: list[dict[str, object]] = []
    failure_stage = "input_validation"
    owner_evidence = [
        _attached_owner_evidence(
            None,
            owner_index=index,
            turn_id=None,
            expected_model_id=None,
            expected_tool_digest=None,
        )
        for index in range(2)
    ]
    result["owner_evidence"] = owner_evidence
    attached_request: Callable[..., tuple[httpx.Response, dict[str, object]]] | None = None
    interaction_trackers = [_attached_new_interaction_tracker(index) for index in range(2)]
    try:
        if not raw or len(raw) > _ATTACH_MAX_STDIN_BYTES or not raw.endswith(b"\n"):
            raise _AttachedProbeFailure("stdin_invalid")
        try:
            payload = json.loads(raw[:-1])
        except (ValueError, json.JSONDecodeError):
            raise _AttachedProbeFailure("stdin_invalid") from None
        if not isinstance(payload, dict) or set(payload) != {"base_url", "origin", "users"}:
            raise _AttachedProbeFailure("stdin_invalid")
        base_url = payload.get("base_url")
        if not isinstance(base_url, str) or len(base_url) > 128:
            raise _AttachedProbeFailure("base_url_invalid")
        try:
            base = urlsplit(base_url)
            port = base.port
            if (
                base.scheme != "http"
                or base.hostname not in {"127.0.0.1", "::1", "localhost"}
                or port is None
                or not 1 <= port <= 65_535
                or base.username is not None
                or base.password is not None
                or base.path not in {"", "/"}
                or base.query
                or base.fragment
            ):
                raise ValueError
        except ValueError:
            raise _AttachedProbeFailure("base_url_invalid") from None
        if payload.get("origin") != _ATTACH_ORIGIN:
            raise _AttachedProbeFailure("origin_invalid")
        users = payload.get("users")
        if not isinstance(users, list) or len(users) != 2:
            raise _AttachedProbeFailure("users_invalid")
        validated_users: list[dict[str, str]] = []
        for owner_index, user in enumerate(users):
            expected_user_fields = {
                "session_cookie",
                "csrf_cookie",
                "expected_tool_result_sha256",
            }
            if owner_index == 0:
                expected_user_fields.add("totp_secret")
            if not isinstance(user, dict) or set(user) != expected_user_fields:
                raise _AttachedProbeFailure("users_invalid")
            session_cookie = user.get("session_cookie")
            csrf_cookie = user.get("csrf_cookie")
            expected_digest = user.get("expected_tool_result_sha256")
            if (
                not isinstance(session_cookie, str)
                or re.fullmatch(r"[A-Za-z0-9_-]{32,128}", session_cookie) is None
                or not isinstance(csrf_cookie, str)
                or re.fullmatch(r"[A-Za-z0-9_-]{32,128}", csrf_cookie) is None
                or not isinstance(expected_digest, str)
                or re.fullmatch(r"[0-9a-f]{64}", expected_digest) is None
            ):
                raise _AttachedProbeFailure("users_invalid")
            validated_users.append(
                {
                    "session_cookie": session_cookie,
                    "csrf_cookie": csrf_cookie,
                    "expected_tool_result_sha256": expected_digest,
                }
            )
            if owner_index == 0:
                totp_secret = user.get("totp_secret")
                if not isinstance(totp_secret, str):
                    raise _AttachedProbeFailure("totp_fixture_invalid")
                _attached_totp_code(totp_secret)
                validated_users[0]["totp_secret"] = totp_secret
        if (
            validated_users[0]["expected_tool_result_sha256"]
            == validated_users[1]["expected_tool_result_sha256"]
        ):
            raise _AttachedProbeFailure("owner_fixtures_not_distinct")

        origin_host = urlsplit(_ATTACH_ORIGIN).netloc
        for _user in validated_users:
            clients.append(
                httpx.Client(
                    base_url=base_url,
                    headers={"host": origin_host, "origin": _ATTACH_ORIGIN},
                    timeout=httpx.Timeout(8.0, connect=2.0),
                    follow_redirects=False,
                    trust_env=False,
                )
            )

        def request(
            owner_index: int,
            method: str,
            path: str,
            *,
            body: Mapping[str, object] | None = None,
            csrf: bool = False,
            timeout: float | None = None,
        ) -> tuple[httpx.Response, dict[str, object]]:
            user = validated_users[owner_index]
            headers = {
                "cookie": (
                    f"{SESSION_COOKIE_NAME}={user['session_cookie']}; "
                    f"{CSRF_COOKIE_NAME}={user['csrf_cookie']}"
                ),
                "accept": "application/json",
            }
            if csrf:
                headers["x-csrf-token"] = user["csrf_cookie"]
            request_options = {} if timeout is None else {"timeout": timeout}
            try:
                response = clients[owner_index].request(
                    method, path, json=body, headers=headers, **request_options
                )
            except httpx.HTTPError as exc:
                raise _AttachedProbeFailure(f"transport_{type(exc).__name__.casefold()}") from None
            parsed = _attached_json(response)
            return response, parsed

        attached_request = request

        # The native catalog is the source of reviewed no-training eligibility; admin policy
        # approval still goes through the candidate's protected route and live CAS fields.
        failure_stage = "model_inventory"
        response, models_payload = request(0, "GET", "/api/v1/assistant/models")
        _attached_require(response, models_payload, {200})
        rows = models_payload.get("items")
        if not isinstance(rows, list):
            raise _AttachedProbeFailure("model_inventory_invalid", response.status_code)
        reviewed_model_id = _reviewed_free_zen_model_id()
        try:
            model_row = _attached_reviewed_model_row(rows, reviewed_model_id)
        except _AttachedProbeFailure as exc:
            raise _AttachedProbeFailure(exc.code, response.status_code) from None
        model_id = model_row.get("model_id")
        privacy_version = model_row.get("privacy_policy_version")
        billing_version = model_row.get("billing_policy_version")
        revision = model_row.get("revision")
        if (
            not isinstance(model_id, str)
            or not isinstance(privacy_version, str)
            or not isinstance(billing_version, str)
            or type(revision) is not int
        ):
            raise _AttachedProbeFailure("model_policy_mismatch")

        admin_totp_secret = validated_users[0].pop("totp_secret")
        failure_stage = "admin_step_up"
        step_up_response, step_up_payload = request(
            0,
            "POST",
            "/api/v1/auth/totp/step-up",
            body={"code": _attached_totp_code(admin_totp_secret)},
            csrf=True,
        )
        del admin_totp_secret
        _attached_require(step_up_response, step_up_payload, {200})
        if step_up_payload.get("verified") is not True:
            raise _AttachedProbeFailure("admin_step_up_unverified", step_up_response.status_code)

        policy_path = "/api/v1/assistant/models/" + quote(model_id, safe="/-._:+") + "/policy"
        failure_stage = "admin_model_policy"
        policy_response, policy_payload = request(
            0,
            "PUT",
            policy_path,
            body={
                "enabled": True,
                "acknowledged_privacy_policy_version": privacy_version,
                "acknowledged_billing_policy_version": billing_version,
                "expected_revision": revision,
            },
            csrf=True,
        )
        _attached_require(policy_response, policy_payload, {200})
        model_row = policy_payload.get("model")
        if not isinstance(model_row, Mapping):
            raise _AttachedProbeFailure("model_policy_invalid", policy_response.status_code)
        policy_version = model_row.get("policy_version")
        if (
            model_row.get("model_id") != reviewed_model_id
            or model_row.get("enabled") is not True
            or model_row.get("usable") is not True
            or model_row.get("free") is not True
            or model_row.get("training_uses_data") is not False
            or model_row.get("privacy_policy_version") != privacy_version
            or model_row.get("billing_policy_version") != billing_version
            or not isinstance(policy_version, str)
        ):
            raise _AttachedProbeFailure("model_policy_not_usable", policy_response.status_code)

        model_rows: list[Mapping[str, object]] = []
        for owner_index in range(2):
            response, models_payload = request(owner_index, "GET", "/api/v1/assistant/models")
            _attached_require(response, models_payload, {200})
            rows = models_payload.get("items")
            if not isinstance(rows, list):
                raise _AttachedProbeFailure("model_inventory_invalid", response.status_code)
            current = next(
                (
                    row
                    for row in rows
                    if isinstance(row, Mapping) and row.get("model_id") == reviewed_model_id
                ),
                None,
            )
            if (
                not isinstance(current, Mapping)
                or current.get("usable") is not True
                or current.get("free") is not True
                or current.get("training_uses_data") is not False
                or current.get("policy_version") != policy_version
            ):
                raise _AttachedProbeFailure("approved_free_model_unavailable", response.status_code)
            model_rows.append(current)
        model_id = reviewed_model_id
        if model_rows[1].get("policy_version") != policy_version:
            raise _AttachedProbeFailure("model_policy_mismatch")
        result["approved_model_id"] = model_id
        result["policy_generation_sha256"] = hashlib.sha256(policy_version.encode()).hexdigest()

        contexts: list[dict[str, object]] = []
        failure_stage = "user_consent_and_conversation_setup"
        for owner_index in range(2):
            consent_path = "/api/v1/assistant/models/" + quote(model_id, safe="/-._:+") + "/consent"
            consent_response, consent_payload = request(
                owner_index,
                "PUT",
                consent_path,
                body={
                    "policy_version": policy_version,
                    "accepted_terms": True,
                    "data_collection_opt_in": False,
                },
                csrf=True,
            )
            _attached_require(consent_response, consent_payload, {200})
            context_response, context_payload = request(
                owner_index,
                "GET",
                "/api/v1/assistant/context",
            )
            if context_response.status_code == 422:
                context_response, context_payload = request(
                    owner_index,
                    "GET",
                    "/api/v1/assistant/context?route=%2Foverview",
                )
            _attached_require(context_response, context_payload, {200})
            context_value = context_payload.get("context")
            if not isinstance(context_value, dict):
                raise _AttachedProbeFailure("context_invalid", context_response.status_code)
            contexts.append(context_value)
            conversation_response, conversation_payload = request(
                owner_index,
                "POST",
                "/api/v1/assistant/conversations",
                body={"title": "Synthetic isolated assistant probe", "context": context_value},
                csrf=True,
            )
            _attached_require(conversation_response, conversation_payload, {201})
            _created_detail, conversation = _attached_conversation_detail(
                conversation_payload, created=True
            )
            conversation_id = str(conversation["id"])
            conversations.append(conversation_id)

        prompts = _attached_probe_prompts()
        turn_ids: list[str] = []
        turn_intervals: list[tuple[float, float]] = []

        # Start the existing bounded probe window before checking the same authenticated
        # readiness that keeps the browser composer disabled. Reuse the remaining time for
        # turn polling; readiness does not get an additional deadline.
        deadline = time.monotonic() + 150.0
        failure_stage = "pre_turn_readiness"
        readiness_checks = 0
        ready_statuses: list[dict[str, object]] = []
        while time.monotonic() < deadline:
            readiness_checks += 1
            ready_statuses = []
            all_ready = True
            for owner_index in range(2):
                readiness_response, readiness_payload = request(
                    owner_index, "GET", "/api/v1/assistant/status"
                )
                _attached_require(readiness_response, readiness_payload, {200})
                worker = readiness_payload.get("worker")
                worker_status = worker.get("status") if isinstance(worker, Mapping) else None
                ready = (
                    readiness_payload.get("enabled") is True
                    and readiness_payload.get("available") is True
                    and worker_status == "ready"
                )
                ready_statuses.append(
                    {
                        "owner_index": owner_index,
                        "enabled": readiness_payload.get("enabled") is True,
                        "available": readiness_payload.get("available") is True,
                        "worker_status": (
                            worker_status
                            if worker_status
                            in {"starting", "ready", "unavailable", "disabled", "stopped"}
                            else "unknown"
                        ),
                    }
                )
                all_ready = all_ready and ready
            result["pre_turn_readiness_checks"] = readiness_checks
            result["assistant_worker_status_before_turns"] = ready_statuses
            if all_ready and time.monotonic() < deadline:
                break
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            time.sleep(min(2.0, remaining))
        if (
            time.monotonic() >= deadline
            or len(ready_statuses) != 2
            or any(
                item.get("enabled") is not True
                or item.get("available") is not True
                or item.get("worker_status") != "ready"
                for item in ready_statuses
            )
        ):
            raise _AttachedProbeFailure("assistant_worker_not_ready_before_turns")

        def create_turn_for(
            owner_index: int,
        ) -> tuple[int, dict[str, object], float, float]:
            conversation_id = conversations[owner_index]
            body = {
                "prompt": prompts[owner_index],
                "model_id": model_id,
                "policy_version": policy_version,
                "context": contexts[owner_index],
                "context_preview_accepted": True,
            }
            request_started = time.monotonic()
            interaction_trackers[owner_index]["turn_started_monotonic"] = request_started
            response, turn_payload = request(
                owner_index,
                "POST",
                f"/api/v1/assistant/conversations/{conversation_id}/turns",
                body=body,
                csrf=True,
            )
            if response.status_code != 202:
                _attached_require(response, turn_payload, {202})
            turn = turn_payload.get("turn")
            turn_id = turn.get("id") if isinstance(turn, Mapping) else None
            if not isinstance(turn_id, str) or not re.fullmatch(r"[0-9a-f-]{36}", turn_id):
                raise _AttachedProbeFailure("turn_invalid", response.status_code)
            request_finished = time.monotonic()
            return (
                owner_index,
                {"turn_id": turn_id, "created_status": response.status_code},
                request_started,
                request_finished,
            )

        failure_stage = "concurrent_turn_create"
        with concurrent.futures.ThreadPoolExecutor(
            max_workers=2, thread_name_prefix="assistant-attach-turn"
        ) as executor:
            created = list(executor.map(create_turn_for, (0, 1)))
        turn_records = [dict(value) for _owner, value, _start, _end in created]
        turn_intervals = [(start, end) for _owner, _value, start, end in created]
        turn_ids = [str(item["turn_id"]) for item in turn_records]
        result["turn_requests_issued_concurrently"] = len(turn_intervals) == 2 and max(
            start for start, _end in turn_intervals
        ) < min(end for _start, end in turn_intervals)
        result["turn_request_overlap_seconds"] = round(
            max(
                0.0,
                min(end for _start, end in turn_intervals)
                - max(start for start, _end in turn_intervals),
            ),
            3,
        )

        approved_preview_ids: set[tuple[int, str]] = set()
        denied_preview_ids: set[tuple[int, str]] = set()
        approved_webfetch_preview_ids: set[tuple[int, str]] = set()
        denied_webfetch_preview_ids: set[tuple[int, str]] = set()
        search_approved = False
        webfetch_approved = False
        active_search_scan_acknowledged = False
        result["search_approved"] = search_approved
        result["active_search_scan_acknowledged"] = active_search_scan_acknowledged
        pending_search_confirmation: dict[str, object] | None = None
        terminal_details: list[dict[str, object] | None] = [None, None]
        while time.monotonic() < deadline and any(item is None for item in terminal_details):
            failure_stage = "turn_poll_and_search_confirmation"
            for owner_index in range(2):
                if terminal_details[owner_index] is not None:
                    continue
                conversation_id = conversations[owner_index]
                response, detail = request(
                    owner_index,
                    "GET",
                    f"/api/v1/assistant/conversations/{conversation_id}",
                )
                _attached_require(response, detail, {200})
                detail, _conversation_row = _attached_conversation_detail(detail)
                owner_evidence[owner_index] = _attached_owner_evidence(
                    detail,
                    owner_index=owner_index,
                    turn_id=turn_ids[owner_index],
                    expected_model_id=model_id,
                    expected_tool_digest=validated_users[owner_index][
                        "expected_tool_result_sha256"
                    ],
                )
                result["owner_evidence"] = owner_evidence
                event_root = detail.get("events")
                events = event_root.get("items") if isinstance(event_root, Mapping) else None
                if not isinstance(events, list) or len(events) > 200:
                    raise _AttachedProbeFailure("event_history_invalid", response.status_code)
                turns = detail.get("turns")
                _attached_observe_interaction_snapshot(
                    interaction_trackers[owner_index],
                    turn_id=turn_ids[owner_index],
                    event_rows=events,
                    turn_rows=turns,
                )
                for event in events:
                    kind, data = _attached_event_data(event)
                    if kind == "webfetch_preview":
                        preview_id = data.get("preview_id")
                        event_turn = event.get("turn_id") if isinstance(event, Mapping) else None
                        if (
                            not isinstance(preview_id, str)
                            or re.fullmatch(r"[0-9a-f]{32}", preview_id) is None
                            or event_turn != turn_ids[owner_index]
                        ):
                            raise _AttachedProbeFailure("webfetch_preview_invalid")
                        key = (owner_index, preview_id)
                        if (
                            key in approved_webfetch_preview_ids
                            or key in denied_webfetch_preview_ids
                        ):
                            continue
                        preview_response, preview_payload = request(
                            owner_index,
                            "GET",
                            f"/api/v1/assistant/conversations/{conversation_id}/turns/"
                            f"{turn_ids[owner_index]}/webfetch-previews/{preview_id}",
                        )
                        _attached_require(preview_response, preview_payload, {200})
                        preview = preview_payload.get("preview")
                        if not isinstance(preview, Mapping) or set(preview) != {
                            "preview_id",
                            "url",
                            "reason",
                            "context_version",
                            "expires_at",
                            "confirmation_phrase",
                        }:
                            raise _AttachedProbeFailure("webfetch_preview_invalid")
                        context_version = contexts[owner_index].get("context_version")
                        url = preview.get("url")
                        phrase = preview.get("confirmation_phrase")
                        expires_at = preview.get("expires_at")
                        reason = preview.get("reason")
                        try:
                            expiry = datetime.fromisoformat(str(expires_at)).astimezone(UTC)
                        except (TypeError, ValueError):
                            expiry = None
                        allow = bool(
                            owner_index == 1
                            and not webfetch_approved
                            and preview.get("preview_id") == preview_id
                            and url == _ATTACH_WEBFETCH_URL
                            and preview.get("context_version") == context_version
                            and isinstance(reason, str)
                            and 1 <= len(reason) <= 300
                            and isinstance(phrase, str)
                            and phrase == f"FETCH {preview_id[-8:]}"
                            and expiry is not None
                            and datetime.now(UTC) < expiry
                            and expiry <= datetime.now(UTC) + timedelta(seconds=120)
                        )
                        confirmation_response, confirmation_payload = request(
                            owner_index,
                            "POST",
                            f"/api/v1/assistant/conversations/{conversation_id}/turns/"
                            f"{turn_ids[owner_index]}/webfetch-previews/{preview_id}/confirm",
                            body={
                                "context_version": context_version,
                                "context": contexts[owner_index],
                                "confirmation_phrase": phrase,
                                "allow": allow,
                            },
                            csrf=True,
                        )
                        _attached_require(confirmation_response, confirmation_payload, {200})
                        expected_status = "approved" if allow else "denied"
                        if (
                            confirmation_payload.get("preview_id") != preview_id
                            or confirmation_payload.get("status") != expected_status
                        ):
                            raise _AttachedProbeFailure("webfetch_confirmation_invalid")
                        if allow:
                            webfetch_approved = True
                            approved_webfetch_preview_ids.add(key)
                            _attached_record_timeline_phase(
                                interaction_trackers[owner_index],
                                "fetch_approval",
                                dedupe_key=preview_id,
                            )
                            result["webfetch_approved"] = True
                            result["webfetch_approval_count"] = len(approved_webfetch_preview_ids)
                        else:
                            denied_webfetch_preview_ids.add(key)
                        continue
                    if kind != "private_context_preview":
                        continue
                    preview_id = data.get("preview_id")
                    event_turn = event.get("turn_id") if isinstance(event, Mapping) else None
                    if (
                        not isinstance(preview_id, str)
                        or re.fullmatch(r"[0-9a-f-]{36}", preview_id) is None
                        or event_turn != turn_ids[owner_index]
                    ):
                        raise _AttachedProbeFailure("search_preview_invalid")
                    key = (owner_index, preview_id)
                    if key in approved_preview_ids or key in denied_preview_ids:
                        continue
                    preview_response, preview_payload = request(
                        owner_index,
                        "GET",
                        f"/api/v1/assistant/conversations/{conversation_id}/turns/"
                        f"{turn_ids[owner_index]}/search-previews/{preview_id}",
                    )
                    _attached_require(preview_response, preview_payload, {200})
                    query = preview_payload.get("query")
                    preview_context_version = preview_payload.get("context_version")
                    phrase = preview_payload.get("confirmation_phrase")
                    context_version = contexts[owner_index].get("context_version")
                    allow = bool(
                        owner_index == 1
                        and query == _ATTACH_SEARCH_QUERY
                        and preview_context_version == context_version
                        and preview_payload.get("status") == "pending"
                        and isinstance(phrase, str)
                        and re.fullmatch(r"SEARCH [0-9a-f]{8}", phrase) is not None
                        and not search_approved
                    )
                    if allow:
                        expected_digest = validated_users[owner_index][
                            "expected_tool_result_sha256"
                        ]
                        tool_results = [
                            tool_data
                            for tool_event in events
                            if isinstance(tool_event, Mapping)
                            and tool_event.get("turn_id") == turn_ids[owner_index]
                            and tool_event.get("type") == "tool"
                            and isinstance((tool_data := tool_event.get("data")), Mapping)
                            and tool_data.get("name") == "workspace.summary"
                            and tool_data.get("status") == "completed"
                        ]
                        if not any(
                            tool_data.get("result_sha256") == expected_digest
                            for tool_data in tool_results
                        ):
                            pending_search_confirmation = None
                            continue
                        turns = detail.get("turns")
                        pending_turn = next(
                            (
                                row
                                for row in turns
                                if isinstance(row, Mapping)
                                and row.get("id") == turn_ids[owner_index]
                            )
                            if isinstance(turns, list)
                            else None,
                            None,
                        )
                        if (
                            not isinstance(pending_turn, Mapping)
                            or pending_turn.get("status") != "running"
                        ):
                            raise _AttachedProbeFailure("active_search_turn_not_running")
                        pending_search_confirmation = {
                            "owner_index": owner_index,
                            "conversation_id": conversation_id,
                            "turn_id": turn_ids[owner_index],
                            "preview_id": preview_id,
                            "context_version": context_version,
                            "confirmation_phrase": phrase,
                            "result_digest_matches": True,
                        }
                        break
                    confirmation_response, confirmation_payload = request(
                        owner_index,
                        "POST",
                        f"/api/v1/assistant/conversations/{conversation_id}/turns/"
                        f"{turn_ids[owner_index]}/search-previews/{preview_id}/confirm",
                        body={
                            "context": contexts[owner_index],
                            "context_version": context_version,
                            "confirmation_phrase": phrase,
                            "allow": allow,
                        },
                        csrf=True,
                    )
                    _attached_require(confirmation_response, confirmation_payload, {200})
                    _attached_require_search_confirmation(
                        confirmation_payload, preview_id, allow=allow
                    )
                    if allow:
                        search_approved = True
                        approved_preview_ids.add(key)
                    else:
                        denied_preview_ids.add(key)
                if pending_search_confirmation is not None:
                    break
                turns = detail.get("turns")
                turn = next(
                    (
                        row
                        for row in turns
                        if isinstance(row, Mapping) and row.get("id") == turn_ids[owner_index]
                    )
                    if isinstance(turns, list)
                    else None,
                    None,
                )
                if isinstance(turn, Mapping) and turn.get("status") in {
                    "completed",
                    "cancelled",
                    "failed",
                    "timed_out",
                }:
                    terminal_details[owner_index] = detail
            if pending_search_confirmation is not None:
                phase = {
                    "mode": "attach-existing-app",
                    "phase": "active_search_wait",
                    "origin": _ATTACH_ORIGIN,
                    "owner_index": pending_search_confirmation["owner_index"],
                    "turn_status": "running",
                    "search_preview_pending": True,
                    "workspace_summary_digest_matches": True,
                    "search_query_sha256": hashlib.sha256(
                        _ATTACH_SEARCH_QUERY.encode("utf-8")
                    ).hexdigest(),
                }
                sys.stdout.write(json.dumps(phase, sort_keys=True, separators=(",", ":")) + "\n")
                sys.stdout.flush()
                acknowledgement = sys.stdin.buffer.readline(_ATTACH_MAX_ACK_BYTES + 1)
                if (
                    len(acknowledgement) > _ATTACH_MAX_ACK_BYTES
                    or acknowledgement != b'{"continue":true}\n'
                ):
                    raise _AttachedProbeFailure("active_scan_ack_invalid")
                active_search_scan_acknowledged = True
                result["active_search_scan_acknowledged"] = True
                owner_index = int(pending_search_confirmation["owner_index"])
                confirmation_response, confirmation_payload = request(
                    owner_index,
                    "POST",
                    f"/api/v1/assistant/conversations/{pending_search_confirmation['conversation_id']}"
                    f"/turns/{pending_search_confirmation['turn_id']}/search-previews/"
                    f"{pending_search_confirmation['preview_id']}/confirm",
                    body={
                        "context": contexts[owner_index],
                        "context_version": pending_search_confirmation["context_version"],
                        "confirmation_phrase": pending_search_confirmation["confirmation_phrase"],
                        "allow": True,
                    },
                    csrf=True,
                )
                _attached_require(confirmation_response, confirmation_payload, {200})
                _attached_require_search_confirmation(
                    confirmation_payload,
                    str(pending_search_confirmation["preview_id"]),
                    allow=True,
                )
                search_approved = True
                result["search_approved"] = True
                search_preview_id = str(pending_search_confirmation["preview_id"])
                approved_preview_ids.add((owner_index, search_preview_id))
                _attached_record_timeline_phase(
                    interaction_trackers[owner_index],
                    "search_approval",
                    dedupe_key=search_preview_id,
                )
                pending_search_confirmation = None
            if any(item is None for item in terminal_details):
                time.sleep(0.25)
        if any(item is None for item in terminal_details):
            raise _AttachedProbeFailure("turn_deadline_exceeded")

        owners_result: list[dict[str, object]] = []
        for owner_index, detail in enumerate(terminal_details):
            if not isinstance(detail, Mapping):
                raise _AttachedProbeFailure("turn_detail_invalid")
            turns = detail.get("turns")
            messages_root = detail.get("messages")
            events_root = detail.get("events")
            turn = next(
                (
                    row
                    for row in turns
                    if isinstance(row, Mapping) and row.get("id") == turn_ids[owner_index]
                )
                if isinstance(turns, list)
                else None,
                None,
            )
            message_rows = (
                messages_root.get("items") if isinstance(messages_root, Mapping) else None
            )
            event_rows = events_root.get("items") if isinstance(events_root, Mapping) else None
            if (
                not isinstance(turn, Mapping)
                or not isinstance(message_rows, list)
                or not isinstance(event_rows, list)
            ):
                raise _AttachedProbeFailure("turn_detail_invalid")
            turn_messages = [
                row
                for row in message_rows
                if isinstance(row, Mapping) and row.get("turn_id") == turn_ids[owner_index]
            ]
            assistant_text = "".join(
                str(row.get("text", ""))
                for row in turn_messages
                if row.get("role") == "assistant" and isinstance(row.get("text"), str)
            )
            tool_events = [
                data
                for event in event_rows
                if isinstance(event, Mapping)
                and event.get("turn_id") == turn_ids[owner_index]
                and (kind := event.get("type")) == "tool"
                and isinstance((data := event.get("data")), Mapping)
            ]
            summary_receipts = [
                data
                for data in tool_events
                if data.get("name") == "workspace.summary" and data.get("status") == "completed"
            ]
            expected_digest = validated_users[owner_index]["expected_tool_result_sha256"]
            matching_receipts = [
                data for data in summary_receipts if data.get("result_sha256") == expected_digest
            ]
            meta_events = [
                data
                for event in event_rows
                if isinstance(event, Mapping)
                and event.get("turn_id") == turn_ids[owner_index]
                and event.get("type") == "meta"
                and isinstance((data := event.get("data")), Mapping)
            ]
            source_events = [
                data
                for event in event_rows
                if isinstance(event, Mapping)
                and event.get("turn_id") == turn_ids[owner_index]
                and event.get("type") == "source"
                and isinstance((data := event.get("data")), Mapping)
            ]
            source_hosts: list[str] = []
            source_types: list[str] = []
            fetch_source_hosts: list[str] = []
            fetch_source_types: list[str] = []
            fetch_source_url_hashes: list[str] = []
            for source in source_events:
                host = _attached_source_host(source)
                source_type = source.get("source_type")
                if host is not None and isinstance(source_type, str):
                    source_hosts.append(host)
                    source_types.append(source_type)
                    if source_type == "native_webfetch_guarded":
                        fetch_source_hosts.append(host)
                        fetch_source_types.append(source_type)
                        source_url = source.get("url")
                        if isinstance(source_url, str):
                            fetch_source_url_hashes.append(
                                hashlib.sha256(source_url.encode("utf-8")).hexdigest()
                            )
            owner_result = {
                "terminal_status": turn.get("status"),
                "model_id_matches": turn.get("model_id") == model_id,
                "nonempty_answer": bool(assistant_text.strip()),
                "answer_bytes": len(assistant_text.encode("utf-8")),
                "answer_sha256": hashlib.sha256(assistant_text.encode("utf-8")).hexdigest(),
                "workspace_summary_receipt_count": len(summary_receipts),
                "workspace_summary_digest_matches": len(matching_receipts) == 1,
                "workspace_summary_result_sha256": (
                    matching_receipts[0].get("result_sha256")
                    if len(matching_receipts) == 1
                    else None
                ),
                "selected_model_id_matches": bool(meta_events)
                and all(data.get("model_id") == model_id for data in meta_events),
                "native_search_source_count": len(source_hosts),
                "native_search_source_hosts": sorted(set(source_hosts)),
                "native_search_source_types": sorted(set(source_types)),
                "search_approved": owner_index == 1 and search_approved,
                "native_webfetch_source_count": len(fetch_source_hosts),
                "native_webfetch_source_hosts": sorted(set(fetch_source_hosts)),
                "native_webfetch_source_types": sorted(set(fetch_source_types)),
                "native_webfetch_source_url_sha256": sorted(set(fetch_source_url_hashes)),
                "webfetch_approved": owner_index == 1 and webfetch_approved,
                "conversation_event_count": len(event_rows),
            }
            safe_owner_evidence = _attached_owner_evidence(
                detail,
                owner_index=owner_index,
                turn_id=turn_ids[owner_index],
                expected_model_id=model_id,
                expected_tool_digest=expected_digest,
            )
            owner_result["turn_error_code"] = safe_owner_evidence["turn_error_code"]
            owner_result["turn_failure_stage"] = safe_owner_evidence["turn_failure_stage"]
            owners_result.append(owner_result)
            owner_evidence[owner_index] = safe_owner_evidence
        result["owners"] = owners_result
        result["owner_evidence"] = owner_evidence
        result["search_query_sha256"] = hashlib.sha256(_ATTACH_SEARCH_QUERY.encode()).hexdigest()
        result["search_approval_count"] = len(approved_preview_ids)
        result["webfetch_approval_count"] = len(approved_webfetch_preview_ids)
        result["webfetch_approved"] = webfetch_approved
        result["active_search_scan_acknowledged"] = active_search_scan_acknowledged
        result["search_approved"] = search_approved
        result["cross_owner_conversation_status"] = None
        failure_stage = "owner_evidence_and_isolation"
        cross_response, cross_payload = request(
            1,
            "GET",
            f"/api/v1/assistant/conversations/{conversations[0]}",
        )
        result["cross_owner_conversation_status"] = cross_response.status_code
        result["cross_owner_error_code"] = (
            cross_payload.get("error", {}).get("code")
            if isinstance(cross_payload.get("error"), Mapping)
            else None
        )

        forged_client = httpx.Client(
            base_url=base_url,
            headers={"host": origin_host, "content-type": "application/json"},
            timeout=httpx.Timeout(5.0, connect=2.0),
            follow_redirects=False,
            trust_env=False,
        )
        try:
            forged_response = forged_client.post(
                "/api/v1/assistant/internal/mcp/" + "f" * 32,
                headers={"authorization": "Bearer " + "x" * 48},
                json={"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
            )
        finally:
            forged_client.close()
        result["forged_internal_mcp_status"] = forged_response.status_code

        failure_stage = "conversation_delete_and_health"
        deletions: list[int] = []
        deletion_diagnostics: list[dict[str, object]] = []
        result["conversation_delete_diagnostics"] = deletion_diagnostics
        for owner_index, conversation_id in enumerate(conversations):
            diagnostic: dict[str, object] = {
                "owner_index": owner_index,
                "attempt_count": 0,
                "pending_count": 0,
            }
            try:
                status, error_code = _attached_delete_with_pending_retry(
                    request,
                    owner_index,
                    conversation_id,
                    deadline=deadline,
                    diagnostic=diagnostic,
                )
            finally:
                if "http_status" in diagnostic:
                    deletion_diagnostics.append(diagnostic)
            deletions.append(status)
            result["conversation_delete_statuses"] = list(deletions)
            if status != 200:
                raise _AttachedProbeFailure(error_code, status)
        result["conversation_delete_statuses"] = deletions

        health_response, health_payload = request(0, "GET", "/api/v1/assistant/status")
        _attached_require(health_response, health_payload, {200})
        worker = health_payload.get("worker")
        result["assistant_worker_status_after_turns"] = (
            worker.get("status") if isinstance(worker, Mapping) else None
        )
        result["same_supervised_app_reachable"] = health_response.status_code == 200
        failure_stage = "acceptance_validation"
        missing_conditions = _attached_acceptance_failures(result)
        result["attached_candidate_acceptance"] = not missing_conditions
        if missing_conditions:
            result["safe_error_code"] = "acceptance_conditions_unmet"
            result["acceptance_failure_code"] = "acceptance_conditions_unmet"
            result["missing_conditions"] = missing_conditions
            result["failure_stage"] = failure_stage
    except _AttachedProbeFailure as exc:
        result["attached_candidate_acceptance"] = False
        result["safe_error_code"] = exc.code
        result["failure_stage"] = failure_stage
        if exc.code == "assistant_worker_unavailable" and attached_request is not None:
            try:
                result["worker_readiness_diagnostic"] = _attached_worker_diagnostic(
                    attached_request
                )
            except Exception:
                result["worker_readiness_diagnostic"] = {"readiness_probe": "unavailable"}
        if exc.status is not None:
            result["http_status"] = exc.status
    except Exception as exc:
        result["attached_candidate_acceptance"] = False
        result["safe_error_code"] = f"probe_{type(exc).__name__.casefold()}"
        result["failure_stage"] = failure_stage
    finally:
        for client in clients:
            client.close()
        result["phase"] = "final"
        result["finished_at"] = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        if result.get("attached_candidate_acceptance") is False:
            try:
                result["interaction_diagnostic"] = _attached_interaction_diagnostic(
                    interaction_trackers
                )
            except _AttachedProbeFailure:
                result["interaction_diagnostic"] = {
                    "scope": "failure_diagnostic_only",
                    "status": "unavailable",
                    "elapsed_time_source": "host_monotonic",
                    "owners": [],
                    "worker_restart_evidence": "unavailable",
                }
        print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0 if result.get("attached_candidate_acceptance") is True else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--native",
        action="store_true",
        help="opt in to starting the real OpenCode binary with synthetic local endpoints",
    )
    parser.add_argument(
        "--app-integration",
        action="store_true",
        help="run the real FastAPI/native ProviderManager two-owner integration only",
    )
    parser.add_argument(
        "--live-zen",
        action="store_true",
        help="run one synthetic-context FastAPI turn through native V2 to approved free Zen",
    )
    parser.add_argument(
        "--attach-existing-app",
        action="store_true",
        help="drive two synthetic owners through a supervised app from private stdin",
    )
    arguments = parser.parse_args()
    if (
        sum(
            (
                arguments.native,
                arguments.app_integration,
                arguments.live_zen,
                arguments.attach_existing_app,
            )
        )
        != 1
    ):
        parser.error(
            "pass exactly one of --native, --app-integration, --live-zen, or --attach-existing-app"
        )
    if arguments.attach_existing_app:
        return run_attached_existing_app_probe()
    if arguments.app_integration:
        return run_native_app_integration_probe()
    if arguments.live_zen:
        return run_native_live_zen_probe()
    run_native_probe()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
