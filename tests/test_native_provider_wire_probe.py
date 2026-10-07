"""Opt-in contract test for the installed native vendor packages."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_PROBE = _ROOT / "tests" / "native_provider_wire_probe.py"
_SPEC = importlib.util.spec_from_file_location("native_provider_wire_probe", _PROBE)
assert _SPEC is not None and _SPEC.loader is not None
_PROBE_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_PROBE_MODULE)


@pytest.mark.skipif(
    os.environ.get("STOCK_PROBS_RUN_NATIVE_PROVIDER_WIRE_PROBE") != "1",
    reason="requires the pinned OpenCode V2.0.7 executable and an isolated native run",
)
def test_pinned_native_packages_forward_only_the_synthetic_execution_capability() -> None:
    """Exercise the real packages against loopback and inspect only sanitized headers."""

    completed = subprocess.run(  # noqa: S603 - fixed probe and pinned Python executable.
        [sys.executable, str(_PROBE), "--run"],
        cwd=_ROOT,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=90,
        check=False,
    )

    assert completed.returncode == 0, completed.stdout
    result = json.loads(completed.stdout)
    assert result["native_version"] == "opencode v2.0.7"
    assert result["real_credentials_used"] is False
    assert result["provider_upstream_is_loopback"] is True
    assert result["all_vendor_packages_exercised"] is True
    assert result["all_capabilities_forwarded"] is True
    assert result["all_mcp_handshakes_ready_before_prompt"] is True
    assert result["all_native_app_tool_schemas_advertised"] is True
    assert result["native_search_advertised"] is True
    assert result["native_webfetch_not_advertised"] is True
    assert {row["native_provider_id"] for row in result["vendor_adapter_checks"]} == {
        "openai",
        "anthropic",
        "google",
    }
    assert all(row["request_observed"] for row in result["vendor_adapter_checks"])
    assert all(row["capability_forwarded"] for row in result["vendor_adapter_checks"])
    assert all(row["request_path_matches_observed"] for row in result["vendor_adapter_checks"])


@pytest.mark.skipif(
    os.environ.get("STOCK_PROBS_RUN_NATIVE_WEBFETCH_WIRE_PROBE") != "1",
    reason="requires the patched pinned OpenCode binary and an isolated native run",
)
def test_pinned_native_webfetch_declaration_matches_the_closed_protocol_allowlist() -> None:
    """Verify actual pinned vendor request declarations, without fetching a destination."""

    completed = subprocess.run(  # noqa: S603 - fixed probe and pinned Python executable.
        [sys.executable, str(_PROBE), "--run", "--with-webfetch"],
        cwd=_ROOT,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=90,
        check=False,
    )

    assert completed.returncode == 0, completed.stdout
    result = json.loads(completed.stdout)
    assert result["native_version"] == "opencode v2.0.7"
    assert result["real_credentials_used"] is False
    assert result["native_webfetch_advertised"] is True
    assert result["native_webfetch_schema_matches"] is True
    assert all(
        row["request_observed"] and row["webfetch_schema_matches"]
        for row in result["vendor_adapter_checks"]
    )


def test_schema_capture_reports_only_structure_and_digest() -> None:
    schema = {
        "type": "object",
        "required": ["query"],
        "additionalProperties": False,
        "properties": {
            "query": {"type": "string", "description": "Sensitive fixture description"},
            "count": {"type": "integer", "enum": [1, 2]},
        },
    }

    facts = _PROBE_MODULE._safe_schema_facts(
        schema,
        description="Unprinted description bytes",
    )

    assert facts["valid"] is True
    assert facts["schema_type"] == "object"
    assert facts["required"] == ["query"]
    assert facts["additional_properties"] is False
    assert facts["properties"] == {
        "query": {"type": "string"},
        "count": {"type": "integer", "enum": [1, 2]},
    }
    serialized = json.dumps(facts)
    assert "Sensitive fixture description" not in serialized
    assert "Unprinted description bytes" not in serialized
    assert len(facts["schema_sha256"]) == 64


def test_native_model_capability_projection_is_closed() -> None:
    projection = _PROBE_MODULE._safe_model_capabilities(
        {
            "tools": True,
            "input": ["text", "image"],
            "output": ["text"],
            "provider_options": {"credential": "must not escape"},
        }
    )

    assert projection == {
        "present": True,
        "tools": True,
        "input": ["image", "text"],
        "output": ["text"],
    }
    assert "credential" not in json.dumps(projection)


def test_native_wire_group_facts_count_all_function_declarations_without_echoing_content() -> None:
    facts = _PROBE_MODULE._safe_tool_group_facts(
        {
            "tools": [
                {
                    "functionDeclarations": [
                        {"name": "private-marker-a", "parameters": {"type": "object"}},
                        {"name": "private-marker-b", "parameters": {"type": "object"}},
                    ]
                },
                {"function": {"name": "private-marker-c"}},
                {"type": "websearch", "name": "private-marker-d"},
            ]
        }
    )

    assert facts == {
        "valid": True,
        "group_count": 3,
        "declaration_count": 4,
        "groups": [
            {"kind": "function_declarations", "declaration_count": 2},
            {"kind": "function", "declaration_count": 1},
            {"kind": "declaration", "declaration_count": 1},
        ],
    }
    assert "private-marker" not in json.dumps(facts)


def test_native_wire_group_facts_fail_closed_on_unbounded_group_count() -> None:
    facts = _PROBE_MODULE._safe_tool_group_facts({"tools": [{}] * 17})

    assert facts == {
        "valid": False,
        "group_count": 0,
        "declaration_count": 0,
        "groups": [],
    }


def test_prompt_readiness_requires_connected_mcp_and_successful_exact_tool_list() -> None:
    connected = {
        "rows": [
            {"name": "signal-ledger", "status": "connected"},
        ]
    }
    methods = [
        {"method": "initialize", "capability_matches": True},
        {"method": "notifications/initialized", "capability_matches": True},
        {
            "method": "tools/list",
            "capability_matches": True,
            "response_status": 200,
            "response_tool_count": 11,
        },
    ]

    assert _PROBE_MODULE._mcp_ready_for_prompt(connected, methods, 11) is True
    assert (
        _PROBE_MODULE._mcp_ready_for_prompt(
            connected, methods[:-1] + [{"method": "tools/list", "capability_matches": True}], 11
        )
        is False
    )
    assert (
        _PROBE_MODULE._mcp_ready_for_prompt(
            connected,
            methods[:-1] + [{**methods[-1], "capability_matches": False}],
            11,
        )
        is False
    )
    assert (
        _PROBE_MODULE._mcp_ready_for_prompt(
            {"rows": [{"name": "signal-ledger", "status": "pending"}]}, methods, 11
        )
        is False
    )


def test_provider_schema_gate_uses_first_request_and_handles_missing_fields() -> None:
    expected = {"one", "two"}
    complete = {
        "app_tool_names_observed": ["one", "two"],
        "missing_app_tool_names": [],
        "app_tool_schema_mismatch_names": [],
    }
    delayed_complete = {
        "request_attempts": [
            {**complete, "app_tool_names_observed": ["one"], "missing_app_tool_names": ["two"]},
            complete,
        ]
    }

    assert _PROBE_MODULE._first_request_has_expected_app_schemas([complete], expected) is True
    assert (
        _PROBE_MODULE._first_request_has_expected_app_schemas(
            delayed_complete["request_attempts"], expected
        )
        is False
    )
    assert (
        _PROBE_MODULE._native_app_schemas_advertised(
            [{"request_attempts": [{"main_prompt_marker_present": True, **complete}]}], expected
        )
        is True
    )
    assert _PROBE_MODULE._native_app_schemas_advertised([{}], expected) is False


def test_provider_schema_gate_ignores_auxiliary_request_but_never_a_main_retry() -> None:
    expected = {"one", "two"}
    complete = {
        "app_tool_names_observed": ["one", "two"],
        "missing_app_tool_names": [],
        "app_tool_schema_mismatch_names": [],
    }
    incomplete = {
        "app_tool_names_observed": ["one"],
        "missing_app_tool_names": ["two"],
        "app_tool_schema_mismatch_names": ["two"],
    }

    assert (
        _PROBE_MODULE._native_app_schemas_advertised(
            [
                {
                    "request_attempts": [
                        {"main_prompt_marker_present": False, **incomplete},
                        {"main_prompt_marker_present": True, **complete},
                    ],
                }
            ],
            expected,
        )
        is True
    )
    assert (
        _PROBE_MODULE._native_app_schemas_advertised(
            [
                {
                    "main_request_attempts": [
                        {"main_prompt_marker_present": True, **incomplete},
                        {"main_prompt_marker_present": True, **complete},
                    ]
                }
            ],
            expected,
        )
        is False
    )


def test_main_marker_detection_is_bounded_and_does_not_return_input_text() -> None:
    marker = "NATIVE_PROVIDER_MAIN_PROMPT_R120"
    assert (
        _PROBE_MODULE._contains_marker({"contents": [{"parts": [{"text": marker}]}]}, marker)
        is True
    )
    assert _PROBE_MODULE._contains_marker({"messages": [{"content": "other"}]}, marker) is False
    assert _PROBE_MODULE._contains_marker([[[]]], marker) is False
    assert _PROBE_MODULE._marker_top_level_fields(
        {
            "contents": [{"parts": [{"text": marker}]}],
            "systemInstruction": {"parts": [{"text": "private"}]},
        },
        marker,
    ) == ["contents"]


def test_native_message_facts_keep_only_role_mode_model_and_part_shape() -> None:
    facts = _PROBE_MODULE._session_message_facts(
        {
            "data": [
                {
                    "info": {
                        "role": "assistant",
                        "mode": "title",
                        "agent": "title",
                        "model": {"providerID": "openai", "modelID": "synthetic-model"},
                    },
                    "parts": [
                        {"type": "text", "text": "private synthetic prompt"},
                        {"type": "tool", "name": "websearch", "input": {"query": "secret"}},
                    ],
                }
            ]
        }
    )

    assert facts == [
        {
            "role": "assistant",
            "role_value_type": "str",
            "message_type": None,
            "mode": "title",
            "agent": "title",
            "finish_tag": None,
            "error_kind": None,
            "error_status": None,
            "error_keys": [],
            "provider_id": "openai",
            "model_id": "synthetic-model",
            "part_count": 2,
            "parts_source": "parts",
            "part_types": ["text", "tool"],
            "tool_names": ["websearch"],
            "fixed_final_text_present": False,
            "row_keys": ["info", "parts"],
            "info_keys": ["agent", "mode", "model", "role"],
        }
    ]
    serialized = json.dumps(facts)
    assert "private synthetic prompt" not in serialized
    assert "secret" not in serialized


def test_google_continuation_fixture_frames_are_fixed_and_data_only() -> None:
    app_name, native_name = _PROBE_MODULE._google_continuation_tool_names()
    assert app_name == "workspace.summary"
    assert native_name == "signal-ledger_workspace_summary"

    call_frame = _PROBE_MODULE._google_sse_frame(
        "function_call", native_tool_name=native_name
    ).decode("utf-8")
    call_payload = json.loads(call_frame.removeprefix("data: ").strip())
    call = call_payload["candidates"][0]["content"]["parts"][0]["functionCall"]
    assert call == {
        "id": "synthetic-summary-call",
        "name": native_name,
        "args": {},
    }
    assert call_payload["candidates"][0]["finishReason"] == "STOP"

    text_frame = _PROBE_MODULE._google_sse_frame("text", native_tool_name=native_name).decode(
        "utf-8"
    )
    text_payload = json.loads(text_frame.removeprefix("data: ").strip())
    assert (
        text_payload["candidates"][0]["content"]["parts"][0]["text"]
        == _PROBE_MODULE._GOOGLE_CONTINUATION_TEXT
    )
    with pytest.raises(ValueError, match="unknown_google_fixture_frame"):
        _PROBE_MODULE._google_sse_frame("other", native_tool_name=native_name)


def test_google_request_still_uses_capture_only_401_by_default() -> None:
    captured: list[dict[str, object]] = []
    handler = _PROBE_MODULE._request_handler("synthetic-capability", captured)
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with _PROBE_MODULE.httpx.Client(trust_env=False, timeout=2.0) as client:
            response = client.post(
                f"http://127.0.0.1:{server.server_port}/v1/models/synthetic-model:streamGenerateContent",
                json={"model": "synthetic-model", "contents": []},
            )
        assert response.status_code == 401
        assert captured[-1]["fixture_response"] == "capture_only_401"
        assert captured[-1]["capability_matches"] is False
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=1.0)


def test_google_function_response_projection_keeps_only_known_tool_names() -> None:
    _app_name, native_name = _PROBE_MODULE._google_continuation_tool_names()
    projected = _PROBE_MODULE._google_function_response_names(
        {
            "contents": [
                {
                    "parts": [
                        {"functionResponse": {"name": native_name, "response": {"ok": True}}},
                        {"functionResponse": {"name": "private-unrecognized-tool", "response": {}}},
                    ]
                }
            ]
        }
    )
    assert projected == [native_name, "unclassified"]
    assert "private-unrecognized-tool" not in json.dumps(projected)
    assert _PROBE_MODULE._google_function_response_names({"contents": [{"parts": [None]}]}) == []


def test_google_continuation_receipt_requires_two_bound_requests_and_exact_mcp_call() -> None:
    app_name, native_name = _PROBE_MODULE._google_continuation_tool_names()
    app_names = sorted(_PROBE_MODULE._EXPECTED_NATIVE_APP_TOOL_NAMES)
    common = {
        "protocol": "google-generative-language",
        "native_tool_count": len(app_names) + 2,
        "app_tool_names_observed": app_names,
        "missing_app_tool_names": [],
        "app_tool_schema_mismatch_names": [],
        "builtin_tool_names_observed": ["webfetch", "websearch"],
        "websearch_schema_matches": True,
        "webfetch_schema_matches": True,
    }
    attempts = [
        {
            **common,
            "main_prompt_marker_present": True,
            "fixture_response": "google_tool_call",
            "function_response_names": [],
            "event_order": 1,
        },
        {
            **common,
            "main_prompt_marker_present": True,
            "fixture_response": "google_final_text",
            "function_response_names": [native_name],
            "event_order": 3,
        },
    ]
    mcp_requests = [
        {
            "method": "tools/call",
            "requested_tool": app_name,
            "arguments_empty_object": True,
            "arguments_key_count": 0,
            "capability_matches": True,
            "response_status": 200,
            "event_order": 2,
        }
    ]
    messages = [
        {
            "role": None,
            "message_type": "assistant",
            "fixed_final_text_present": True,
            "tool_names": [],
        }
    ]

    facts = _PROBE_MODULE._google_continuation_facts(attempts, mcp_requests, messages, enabled=True)
    assert facts["main_request_count"] == 2
    assert facts["main_request_tool_declarations_match"] is True
    assert facts["workspace_summary_call_count"] == 1
    assert facts["workspace_summary_call_succeeded"] is True
    assert facts["continuation_response_bound"] is True
    assert facts["event_order_proves_tool_between_requests"] is True
    assert facts["final_synthetic_text_observed"] is True
    assert facts["no_native_search_or_fetch_invocation_observed"] is True

    omitted_builtin = [
        {**attempt, "builtin_tool_names_observed": ["websearch"]} for attempt in attempts
    ]
    failed = _PROBE_MODULE._google_continuation_facts(
        omitted_builtin, mcp_requests, messages, enabled=True
    )
    assert failed["main_request_tool_declarations_match"] is False

    wrong_order = [{**attempts[1], "event_order": 2}, attempts[0]]
    failed_order = _PROBE_MODULE._google_continuation_facts(
        wrong_order, mcp_requests, messages, enabled=True
    )
    assert failed_order["event_order_proves_tool_between_requests"] is False


def test_native_binary_build_facts_bind_size_and_hash_to_adjacent_manifest(tmp_path: Path) -> None:
    binary = tmp_path / "opencode"
    binary.write_bytes(b"synthetic native binary fixture")
    digest = hashlib.sha256(binary.read_bytes()).hexdigest()
    manifest = {
        "binary_sha256": digest,
        "binary_bytes": binary.stat().st_size,
        "native_version": "2.0.7",
        "source_commit": "a" * 40,
        "oauth_transformed_source_set_sha256": "b" * 64,
        "ignored_secret_field": "must not project",
    }
    binary.with_name("build.json").write_text(json.dumps(manifest), encoding="utf-8")

    facts = _PROBE_MODULE._binary_build_facts(binary)
    assert facts["binary_sha256"] == digest
    assert facts["binary_bytes"] == binary.stat().st_size
    assert facts["manifest_present"] is True
    assert facts["manifest_binary_binding_matches"] is True
    assert facts["manifest_facts"] == {
        "native_version": "2.0.7",
        "source_commit": "a" * 40,
        "oauth_transformed_source_set_sha256": "b" * 64,
    }
