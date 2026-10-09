from __future__ import annotations

import ast
import asyncio
import contextlib
import hashlib
import importlib.util
import inspect
import io
import json
import socket
import subprocess
import sys
from dataclasses import replace
from pathlib import Path
from typing import IO

import pytest

from stock_probs.assistant import api as assistant_api
from stock_probs.assistant import net as assistant_net
from stock_probs.assistant import providers as assistant_providers
from stock_probs.assistant import runtime as assistant_runtime
from stock_probs.assistant.providers import AssistantProviderManager
from stock_probs.config import Settings
from stock_probs.repository import Repository

MODULE_PATH = Path(__file__).with_name("supervised_assistant_probe.py")
SPEC = importlib.util.spec_from_file_location("supervised_assistant_probe", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
probe = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = probe
SPEC.loader.exec_module(probe)
NATIVE_MODULE_PATH = Path(__file__).with_name("native_assistant_probe.py")
NATIVE_SPEC = importlib.util.spec_from_file_location("native_assistant_probe", NATIVE_MODULE_PATH)
assert NATIVE_SPEC is not None and NATIVE_SPEC.loader is not None
native_probe = importlib.util.module_from_spec(NATIVE_SPEC)
sys.modules[NATIVE_SPEC.name] = native_probe
NATIVE_SPEC.loader.exec_module(native_probe)


def _assistant_catalog_document() -> dict[str, object]:
    """Load the maintained assistant policy for selector contract tests."""

    catalog_path = (
        Path(__file__).resolve().parents[1] / "src/stock_probs/assistant/assistant_catalog.json"
    )
    return json.loads(catalog_path.read_text(encoding="utf-8"))


def _probe_zen_model(
    model_id: str,
    *,
    provider_id: str = "opencode-zen",
    available: bool = True,
    free: bool = True,
    training: bool = False,
    data_collection_allowed: bool = False,
    data_collection_default: bool = False,
) -> native_probe.AssistantModel:
    """Build a native discovery row without pinning a real model ID or policy version."""

    return native_probe.AssistantModel(
        model_id=model_id,
        provider_id=provider_id,
        display_name="Fixture reviewed model",
        available=available,
        free=free,
        training=training,
        terms_url="https://fixture.example.test/terms",
        terms_reviewed_at="fixture-date",
        policy_version="fixture-policy",
        disclosure="Synthetic fixture only.",
        data_collection_allowed=data_collection_allowed,
        data_collection_default=data_collection_default,
    )


def test_native_acceptance_selector_uses_the_exact_maintained_catalog_field() -> None:
    """A native acceptance model is explicit in policy, not selected by sort order."""

    catalog = _assistant_catalog_document()
    zen = catalog["zen"]
    selected_suffix = zen["native_acceptance_model_id"]

    assert native_probe._reviewed_free_zen_model_id(catalog) == (
        f"{zen['provider_id']}/{selected_suffix}"
    )


@pytest.mark.parametrize("selection_state", ("missing", "unknown"))
def test_native_acceptance_selector_fails_closed_without_falling_back(
    selection_state: str,
) -> None:
    """An eligible alternative cannot replace an absent or unknown explicit selection."""

    catalog = _assistant_catalog_document()
    zen = catalog["zen"]
    selected_suffix = zen["native_acceptance_model_id"]
    selected_policy = zen["reviewed_models"][selected_suffix]
    zen["reviewed_models"]["eligible-alternate-fixture"] = dict(selected_policy)
    if selection_state == "missing":
        zen.pop("native_acceptance_model_id")
    else:
        zen["native_acceptance_model_id"] = "unknown-fixture-model"

    with pytest.raises(RuntimeError, match="reviewed_zen_acceptance_model_invalid"):
        native_probe._reviewed_free_zen_model_id(catalog)


@pytest.mark.parametrize(
    ("policy_field", "policy_value"),
    (
        ("available", False),
        ("free", False),
        ("training", True),
        ("data_collection_allowed", True),
        ("data_collection_default", True),
        ("route", "unsupported-route-fixture"),
    ),
)
def test_native_acceptance_selector_rejects_ineligible_selection_without_fallback(
    policy_field: str, policy_value: object
) -> None:
    """Every maintained privacy, billing, availability, and route predicate stays strict."""

    catalog = _assistant_catalog_document()
    zen = catalog["zen"]
    selected_suffix = zen["native_acceptance_model_id"]
    selected_policy = zen["reviewed_models"][selected_suffix]
    eligible_alternate = dict(selected_policy)
    selected_policy[policy_field] = policy_value
    zen["reviewed_models"]["eligible-alternate-fixture"] = eligible_alternate

    with pytest.raises(RuntimeError, match="reviewed_zen_acceptance_model_invalid"):
        native_probe._reviewed_free_zen_model_id(catalog)


def test_native_acceptance_selector_rejects_catalog_exclusion() -> None:
    """A selected catalog row remains unavailable when its ID is explicitly excluded."""

    catalog = _assistant_catalog_document()
    zen = catalog["zen"]
    selected_suffix = zen["native_acceptance_model_id"]
    zen["reviewed_models"]["eligible-alternate-fixture"] = dict(
        zen["reviewed_models"][selected_suffix]
    )
    zen["excluded_models"][selected_suffix] = "fixture exclusion"

    with pytest.raises(RuntimeError, match="reviewed_zen_acceptance_model_invalid"):
        native_probe._reviewed_free_zen_model_id(catalog)


def test_live_zen_discovery_uses_only_the_exact_selected_model() -> None:
    """Inventory order cannot choose an alternative or conceal a missing selected row."""

    selected = _probe_zen_model("opencode-zen/selected-fixture")
    alternate = _probe_zen_model("opencode-zen/alternate-fixture")

    assert (
        native_probe._discovered_reviewed_zen_model((alternate, selected), selected.model_id)
        is selected
    )
    assert native_probe._discovered_reviewed_zen_model((alternate,), selected.model_id) is None


def test_attached_zen_inventory_uses_only_the_exact_catalog_selection() -> None:
    """Attached-app inventory cannot substitute an eligible alternative model."""

    selected_model_id = native_probe._reviewed_free_zen_model_id(_assistant_catalog_document())
    selected = {
        "model_id": selected_model_id,
        "provider_id": "opencode-zen",
        "available": True,
        "free": True,
        "training_uses_data": False,
        "privacy_policy_version": "fixture-privacy",
        "billing_policy_version": "fixture-billing",
        "revision": 0,
    }
    alternate = {**selected, "model_id": "opencode-zen/alternate-fixture"}

    assert (
        native_probe._attached_reviewed_model_row([alternate, selected], selected_model_id)
        is selected
    )
    with pytest.raises(native_probe._AttachedProbeFailure, match="reviewed_model_not_in_inventory"):
        native_probe._attached_reviewed_model_row([alternate], selected_model_id)
    with pytest.raises(native_probe._AttachedProbeFailure, match="reviewed_model_not_available"):
        native_probe._attached_reviewed_model_row(
            [alternate, {**selected, "available": False}], selected_model_id
        )


@pytest.mark.parametrize(
    ("model_field", "model_value"),
    (
        ("provider_id", "other-provider"),
        ("available", False),
        ("free", False),
        ("training", True),
        ("data_collection_allowed", True),
        ("data_collection_default", True),
    ),
)
def test_live_zen_discovery_rejects_ineligible_exact_model_without_fallback(
    model_field: str, model_value: object
) -> None:
    """An ineligible exact inventory row cannot cause use of an eligible alternative."""

    selected = _probe_zen_model("opencode-zen/selected-fixture", **{model_field: model_value})
    alternate = _probe_zen_model("opencode-zen/alternate-fixture")

    assert (
        native_probe._discovered_reviewed_zen_model((alternate, selected), selected.model_id)
        is None
    )


def _driver_receipt() -> dict[str, object]:
    digest = "a" * 64
    approved_model_id = native_probe._reviewed_free_zen_model_id()
    owner = {
        "terminal_status": "completed",
        "turn_error_code": None,
        "turn_failure_stage": "none",
        "model_id_matches": True,
        "nonempty_answer": True,
        "answer_bytes": 32,
        "answer_sha256": digest,
        "workspace_summary_receipt_count": 1,
        "workspace_summary_digest_matches": True,
        "workspace_summary_result_sha256": digest,
        "selected_model_id_matches": True,
        "native_search_source_count": 0,
        "native_search_source_hosts": [],
        "native_search_source_types": [],
        "search_approved": True,
        "native_webfetch_source_count": 0,
        "native_webfetch_source_hosts": [],
        "native_webfetch_source_types": [],
        "native_webfetch_source_url_sha256": [],
        "webfetch_approved": False,
        "conversation_event_count": 4,
    }
    return {
        "mode": "attach-existing-app",
        "phase": "final",
        "started_at": "2026-10-04T19:00:00Z",
        "finished_at": "2026-10-04T19:01:00Z",
        "owners": [
            owner,
            {
                **owner,
                "native_search_source_count": 1,
                "native_search_source_hosts": ["www.nasa.gov"],
                "native_search_source_types": ["native_search_text_unverified"],
                "native_webfetch_source_count": 1,
                "native_webfetch_source_hosts": ["www.iana.org"],
                "native_webfetch_source_types": ["native_webfetch_guarded"],
                "native_webfetch_source_url_sha256": [
                    hashlib.sha256(b"https://www.iana.org/domains/reserved").hexdigest()
                ],
                "webfetch_approved": True,
            },
        ],
        "conversation_delete_statuses": [200, 200],
        "cross_owner_conversation_status": 404,
        "cross_owner_error_code": "not_found",
        "forged_internal_mcp_status": 404,
        "same_supervised_app_reachable": True,
        "turn_requests_issued_concurrently": True,
        "conversation_delete_diagnostics": [
            {
                "owner_index": 0,
                "http_status": 200,
                "public_error_code": "none",
                "attempt_count": 1,
                "pending_count": 0,
            },
            {
                "owner_index": 1,
                "http_status": 200,
                "public_error_code": "none",
                "attempt_count": 2,
                "pending_count": 1,
            },
        ],
        "attached_candidate_acceptance": True,
        "assistant_worker_status_after_turns": "ready",
        "search_query_sha256": digest,
        "approved_model_id": approved_model_id,
        "policy_generation_sha256": digest,
        "search_approval_count": 1,
        "webfetch_approval_count": 1,
        "webfetch_approved": True,
        "webfetch_requested_url_sha256": hashlib.sha256(
            b"https://www.iana.org/domains/reserved"
        ).hexdigest(),
        "raw_answer": "must not be projected",
    }


def test_native_zen_identity_capture_keeps_only_closed_boolean_facts() -> None:
    expected = {
        "user_agent_present": True,
        "user_agent_unique": True,
        "user_agent_shape_valid": True,
        "client_present": True,
        "client_unique": True,
        "client_shape_valid": True,
        "client_matches_user_agent": True,
    }
    projection = native_probe._native_zen_identity_projection(
        ["opencode/stable/2.0.7/opencode"], ["opencode"]
    )
    assert projection == expected
    assert native_probe._native_zen_identity_projection(
        ["opencode/stable/2.0.7/opencode", "opencode/stable/2.0.7/opencode"], ["opencode"]
    ) == {
        **expected,
        "user_agent_unique": False,
        "user_agent_shape_valid": False,
        "client_matches_user_agent": False,
    }
    assert (
        native_probe._native_zen_identity_projection(
            ["opencode/stable/2.0.7/opencode\r\nInjected: value"], ["opencode"]
        )["user_agent_shape_valid"]
        is False
    )
    assert set(projection) == set(expected)
    native_session = "ses_0123456789abABCDEFGHIJKLMN"
    native_project = "project-cache-id-0123456789"
    extended = native_probe._native_zen_identity_projection(
        ["opencode/stable/2.0.7/opencode"],
        ["opencode"],
        native_sessions=[native_session],
        native_projects=[native_project],
        session_affinities=[native_session],
        session_id_aliases=[native_session],
        expected_session=native_session,
        expected_project=native_project,
    )
    assert extended["native_session_shape_valid"] is True
    assert extended["native_session_matches_active"] is True
    assert extended["native_project_shape_valid"] is True
    assert extended["native_project_matches_active"] is True
    assert extended["session_aliases_match_native"] is True
    assert native_session not in repr(extended)
    assert native_project not in repr(extended)
    assert (
        native_probe._native_zen_identity_projection(
            ["opencode/stable/2.0.7/opencode"],
            ["opencode"],
            native_sessions=[native_session, native_session],
            native_projects=[native_project],
            expected_session=native_session,
            expected_project=native_project,
        )["native_session_unique"]
        is False
    )
    assert (
        native_probe._native_zen_identity_projection(
            ["opencode/stable/2.0.7/opencode"],
            ["opencode"],
            native_sessions=[native_session],
            native_projects=["../" + native_project],
            expected_session=native_session,
            expected_project=native_project,
        )["native_project_shape_valid"]
        is False
    )


def test_native_capture_request_wrappers_match_runtime_startup_probe_signature() -> None:
    from stock_probs.assistant.runtime import OpenCodeV2Runtime

    runtime_parameter = inspect.signature(OpenCodeV2Runtime._request).parameters[
        "allow_startup_probe"
    ]
    assert runtime_parameter.default is False

    tree = ast.parse(inspect.getsource(native_probe))
    wrappers = {
        node.name: node
        for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef)
        and node.name in {"trace_native_request", "traced_native_request"}
    }
    assert set(wrappers) == {"trace_native_request", "traced_native_request"}
    for wrapper in wrappers.values():
        startup_parameter = next(
            (
                (argument, default)
                for argument, default in zip(
                    wrapper.args.kwonlyargs, wrapper.args.kw_defaults, strict=True
                )
                if argument.arg == "allow_startup_probe"
            ),
            None,
        )
        assert startup_parameter is not None
        argument, default = startup_parameter
        assert isinstance(argument.annotation, ast.Name)
        assert argument.annotation.id == "bool"
        assert isinstance(default, ast.Constant) and default.value is False
        assert any(
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "original_request"
            and any(
                keyword.arg == "allow_startup_probe"
                and isinstance(keyword.value, ast.Name)
                and keyword.value.id == "allow_startup_probe"
                for keyword in node.keywords
            )
            for node in ast.walk(wrapper)
        )


def test_native_identity_context_wraps_both_synthetic_proxy_streams() -> None:
    user_agent = "opencode/stable/2.0.7/opencode"
    client = "opencode"
    native_session = "ses_0123456789abABCDEFGHIJKLMN"
    native_project = "project-cache-id-0123456789"
    headers = {
        "authorization": "Bearer public",
        "user-agent": user_agent,
        "x-opencode-client": client,
        "x-opencode-session": native_session,
        "x-opencode-project": native_project,
        "x-session-affinity": native_session,
        "x-session-id": native_session,
    }
    request_body = json.dumps(
        {
            "model": "synthetic-model",
            "messages": [{"role": "user", "content": "Synthetic local test."}],
            "tools": [{"function": {"name": "signal-ledger_workspace_summary"}}],
        }
    ).encode()

    async def collect() -> list[bytes]:
        stream = native_probe._synthetic_application_provider_stream(
            "https://synthetic.invalid/v1/chat/completions",
            headers=headers,
            body=request_body,
            timeout_seconds=1.0,
            max_response_bytes=4096,
        )
        wrapped = native_probe._with_native_zen_identity(
            stream,
            user_agent,
            client,
            native_session,
            native_project,
            native_session,
            native_session,
        )
        return [chunk async for chunk in wrapped]

    native_probe._APP_PROVIDER_CALLS.clear()
    try:
        assert asyncio.run(collect())
        call = native_probe._APP_PROVIDER_CALLS[-1]
        assert call["native_user_agent_forwarded"] is True
        assert call["native_client_forwarded"] is True
        assert call["native_session_forwarded"] is True
        assert call["native_project_forwarded"] is True
        assert call["native_affinity_matches"] is True
        assert call["native_session_id_alias_matches"] is True
        assert native_session not in repr(call)
        assert native_project not in repr(call)
        assert native_probe._NATIVE_ZEN_EXPECTED_IDENTITY.get() == (None,) * 6
    finally:
        native_probe._APP_PROVIDER_CALLS.clear()

    tree = ast.parse(inspect.getsource(native_probe))
    proxy_wrappers = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "traced_proxy_chat_completion"
    ]
    assert len(proxy_wrappers) == 2
    assert all(
        any(
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "_with_native_zen_identity"
            for node in ast.walk(wrapper)
        )
        for wrapper in proxy_wrappers
    )


def test_native_application_zen_fixture_passes_manager_policy_without_network(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Keep the native fixture's provider identity aligned with the real manager descriptor."""

    def reject_network_request(*args: object, **kwargs: object) -> None:
        raise AssertionError("native fixture preflight must not access the network")

    monkeypatch.setattr(assistant_providers, "request_public_https", reject_network_request)
    monkeypatch.setattr(assistant_providers, "stream_public_https", reject_network_request)

    model = native_probe._synthetic_application_zen_model("2026-10-06")

    class _Catalog:
        def list_models(self) -> tuple[object, ...]:
            return (model,)

        def get_model(self, model_id: str) -> object | None:
            return model if model_id == model.model_id else None

    data_dir = tmp_path / "provider-data"
    settings = Settings(
        data_dir=data_dir,
        database_path=data_dir / "stock_probs.sqlite3",
        backup_dir=data_dir / "backups",
        environment="test",
        auth_session_secret="t" * 64,
    )
    manager = AssistantProviderManager(
        settings,
        catalog=_Catalog(),
        vault_dir=data_dir / "assistant-vault",
    )
    definition = manager._definitions[model.provider_id]

    policy = manager.model_policy_state(model.model_id)
    descriptor = manager.native_execution_descriptor(model.model_id)

    assert policy["usable"] is True
    assert model.native_provider_id == definition["native_provider_id"]
    assert descriptor.native_provider_id == model.native_provider_id
    assert descriptor.adapter_id == definition["adapter_id"]


def test_native_app_port_release_requires_refused_owned_loopback_listener() -> None:
    """Distinguish an exited fixture server from a port that still accepts connections."""

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        port = listener.getsockname()[1]
        active = native_probe._application_server_cleanup_projection(
            port,
            server_started=True,
            thread_started=True,
            thread_stopped=True,
        )
        assert active["app_server_port"] == port
        assert active["app_port_refused_after_shutdown"] is False
        assert active["owned_app_server_cleanup"] is False

    stopped = native_probe._application_server_cleanup_projection(
        port,
        server_started=True,
        thread_started=True,
        thread_stopped=True,
    )
    assert stopped["app_port_refused_after_shutdown"] is True
    assert stopped["owned_app_server_cleanup"] is True
    assert (
        native_probe._application_server_cleanup_projection(
            port,
            server_started=False,
            thread_started=True,
            thread_stopped=False,
        )["owned_app_server_cleanup"]
        is False
    )


def test_native_app_failure_retains_bounded_cleanup_projection_without_masking_error() -> None:
    """Keep owned-server cleanup facts visible when the integration raises."""

    function_tree = ast.parse(inspect.getsource(native_probe._run_application_integration))
    function_node = next(node for node in function_tree.body if isinstance(node, ast.FunctionDef))
    finally_calls = [
        node
        for statement in ast.walk(function_node)
        if isinstance(statement, ast.Try)
        for node in ast.walk(ast.Module(body=statement.finalbody, type_ignores=[]))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "_emit_application_server_cleanup_diagnostic"
    ]
    assert finally_calls

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    captured = io.StringIO()
    with (
        contextlib.redirect_stderr(captured),
        pytest.raises(RuntimeError, match="synthetic_failure_marker"),
    ):
        try:
            raise RuntimeError("synthetic_failure_marker")
        finally:
            native_probe._emit_application_server_cleanup_diagnostic(
                port,
                server_started=True,
                thread_started=True,
                thread_stopped=True,
            )

    lines = captured.getvalue().splitlines()
    assert len(lines) == 1
    assert len(lines[0].encode("utf-8")) < 512
    record = json.loads(lines[0])
    assert set(record) == {
        "event",
        "app_port",
        "app_server_started",
        "app_server_thread_started",
        "app_server_thread_stopped",
        "app_port_refused_after_shutdown",
        "owned_app_server_cleanup",
    }
    assert record == {
        "event": "native_app_server_cleanup_v1",
        "app_port": port,
        "app_server_started": True,
        "app_server_thread_started": True,
        "app_server_thread_stopped": True,
        "app_port_refused_after_shutdown": True,
        "owned_app_server_cleanup": True,
    }
    assert "synthetic_failure_marker" not in lines[0]


def _owner_failure_evidence(index: int) -> dict[str, object]:
    return {
        "owner_index": index,
        "terminal_status": "failed",
        "turn_error_code": "worker_unavailable",
        "turn_failure_stage": "before_model_session_event",
        "model_id_matches": False,
        "assistant_message_count": 1,
        "assistant_text_bytes": 24,
        "answer_nonempty": True,
        "workspace_summary_receipt_count": 1,
        "workspace_summary_digest_present": True,
        "workspace_summary_digest_matches": False,
        "selected_model_event_count": 1,
        "selected_model_id_matches": True,
        "native_search_source_count": 0,
        "native_webfetch_source_count": 0,
        "conversation_event_count": 4,
        "private_prompt": "must not escape",
    }


def _native_delete_failure_receipt() -> dict[str, object]:
    receipt = _driver_receipt()
    receipt.update(
        {
            "attached_candidate_acceptance": False,
            "safe_error_code": "acceptance_conditions_unmet",
            "acceptance_failure_code": "acceptance_conditions_unmet",
            "missing_conditions": ["owner0_conversation_delete_failed"],
            "failure_stage": "conversation_delete_and_health",
            "owner_evidence": [_owner_failure_evidence(0), _owner_failure_evidence(1)],
            "interaction_diagnostic": _interaction_diagnostic(),
        }
    )
    return receipt


def _interaction_diagnostic() -> dict[str, object]:
    return {
        "scope": "failure_diagnostic_only",
        "status": "available",
        "elapsed_time_source": "host_monotonic",
        "owners": [
            {
                "owner_index": index,
                "turn_elapsed_ms": None,
                "terminal_status": None,
                "phases": [],
            }
            for index in range(2)
        ],
        "worker_restart_evidence": "unavailable",
    }


def _native_timing_payload() -> dict[str, object]:
    return {
        "event": "assistant_turn_timing_v1",
        "version": 1,
        "scope": "diagnostic_only",
        "terminal_status": "timed_out",
        "turn_elapsed_ms": 121_250,
        "workspace_summary_completed_ms": 840,
        "provider_requests": [
            {
                "ordinal": 1,
                "start_ms": 12,
                "first_sanitized_chunk_ms": 400,
                "end_ms": None,
                "outcome": "cancelled",
            }
        ],
    }


def _native_timing_v2_payload() -> dict[str, object]:
    return {
        "event": "assistant_turn_timing_v2",
        "version": 2,
        "scope": "diagnostic_only",
        "terminal_status": "timed_out",
        "turn_elapsed_ms": 121_250,
        "workspace_summary_completed_ms": 840,
        "provider_requests": [
            {
                "ordinal": 1,
                "start_ms": 12,
                "first_sanitized_chunk_ms": 400,
                "sanitized_chunk_count": 2,
                "sanitized_byte_count": 24,
                "last_sanitized_yield_ms": 110_000,
                "end_ms": None,
                "outcome": "ended",
                "stream_lifecycle": "clean_eof",
                "stream_lifecycle_observed": True,
            },
            {
                "ordinal": 2,
                "start_ms": 20,
                "first_sanitized_chunk_ms": None,
                "sanitized_chunk_count": 0,
                "sanitized_byte_count": 0,
                "last_sanitized_yield_ms": None,
                "end_ms": None,
                "outcome": "cancelled",
                "stream_lifecycle": "unresolved_at_turn_timeout",
                "stream_lifecycle_observed": False,
            },
        ],
    }


def _native_timing_v3_payload() -> dict[str, object]:
    payload = _native_timing_v2_payload()
    payload["event"] = "assistant_turn_timing_v3"
    payload["version"] = 3
    requests = payload["provider_requests"]
    assert isinstance(requests, list)
    for request in requests:
        assert isinstance(request, dict)
        request["failure_diagnostic"] = None
    return payload


def _native_timing_v3_set_failure(request: dict[str, object], diagnostic: object) -> None:
    request.update(
        outcome="failed",
        stream_lifecycle="safe_protocol_error",
        stream_lifecycle_observed=True,
        failure_diagnostic=diagnostic,
    )


def _native_timing_v4_payload() -> dict[str, object]:
    payload = _native_timing_v3_payload()
    payload["event"] = "assistant_turn_timing_v4"
    payload["version"] = 4
    return payload


def _native_timing_v5_payload() -> dict[str, object]:
    payload = _native_timing_v4_payload()
    payload["event"] = "assistant_turn_timing_v5"
    payload["version"] = 5
    payload["pre_session_phase"] = None
    payload["pre_session_failure_code"] = None
    return payload


def _native_terminal_warning() -> str:
    return (
        probe._NATIVE_WARNING_SNAPSHOT_MARKER
        + "(session_outcome=failed, snapshot=read, assistant_finish=error,stop, "
        "assistant_failure=dns,tls, assistant_error_count=2, "
        "webfetch_state=completed,error, webfetch_failure=dns, "
        "webfetch_timeout_stage=dns_lookup_timeout, "
        "webfetch_timeout_seconds_max=15, webfetch_tool_elapsed_ms_max=110000, "
        "webfetch_completion=approved_destination_present, native_failure=dns,http, "
        "native_tool_error_count=1)."
    )


def _native_empty_terminal_warning() -> str:
    return (
        probe._NATIVE_WARNING_SNAPSHOT_MARKER
        + "(session_outcome=unknown, snapshot=invalid_response, "
        "assistant_finish=none, assistant_failure=none, assistant_error_count=0, "
        "webfetch_state=absent, webfetch_failure=none, webfetch_timeout_stage=none, "
        "webfetch_timeout_seconds_max=none, webfetch_tool_elapsed_ms_max=none, "
        "webfetch_completion=none, native_failure=none, native_tool_error_count=0)."
    )


def _native_model_discovery_warning(
    *,
    outcome: str = "readiness_timeout",
    readiness_attempts: object = 4,
    readiness_timeouts: object = 3,
    catalog_attempts: object = 2,
    catalog_timeouts: object = 1,
    empty_catalog_responses: object = 1,
    missing_alias_responses: object = 1,
    post_readiness_catalog_responses: object = 0,
    post_readiness_missing_alias_responses: object = 0,
    elapsed_ms: object = 8000,
) -> str:
    return (
        probe._NATIVE_WARNING_MODEL_DISCOVERY_MARKER
        + f"(phase=model_discovery, outcome={outcome}, "
        + f"readiness_attempts={readiness_attempts}, "
        + f"readiness_timeouts={readiness_timeouts}, "
        + f"catalog_attempts={catalog_attempts}, catalog_timeouts={catalog_timeouts}, "
        + f"empty_catalog_responses={empty_catalog_responses}, "
        + f"missing_alias_responses={missing_alias_responses}, "
        + f"post_readiness_catalog_responses={post_readiness_catalog_responses}, "
        + f"post_readiness_missing_alias_responses={post_readiness_missing_alias_responses}, "
        + f"elapsed_ms={elapsed_ms})."
    )


def test_native_timing_projection_keeps_only_anonymous_closed_rows() -> None:
    raw = (
        "private unrelated log value must not escape\n"
        "2026-10-06T12:00:00Z app INFO "
        + probe._NATIVE_TIMING_MARKER
        + json.dumps(_native_timing_payload(), separators=(",", ":"))
    )

    projection = probe._native_timing_projection(raw)

    assert projection == {
        "scope": "diagnostic_only",
        "status": "available",
        "rows": [
            {
                "terminal_status": "timed_out",
                "turn_elapsed_ms": 121_250,
                "workspace_summary_completed_ms": 840,
                "provider_requests": [
                    {
                        "ordinal": 1,
                        "start_ms": 12,
                        "first_sanitized_chunk_ms": 400,
                        "end_ms": None,
                        "outcome": "cancelled",
                    }
                ],
            }
        ],
        "runtime_warnings": [],
    }
    encoded = json.dumps(projection)
    assert "private unrelated log value" not in encoded
    assert "owner_id" not in encoded
    assert "execution_id" not in encoded


def test_native_timing_v2_projection_distinguishes_observed_and_synthesized_lifecycle() -> None:
    raw = (
        "private unrelated log value must not escape\n"
        + probe._NATIVE_TIMING_V2_MARKER
        + json.dumps(_native_timing_v2_payload(), separators=(",", ":"))
    )

    projection = probe._native_timing_projection(raw)

    assert projection == {
        "scope": "diagnostic_only",
        "status": "available",
        "rows": [
            {
                "terminal_status": "timed_out",
                "turn_elapsed_ms": 121_250,
                "workspace_summary_completed_ms": 840,
                "provider_requests": [
                    {
                        "ordinal": 1,
                        "start_ms": 12,
                        "first_sanitized_chunk_ms": 400,
                        "sanitized_chunk_count": 2,
                        "sanitized_byte_count": 24,
                        "last_sanitized_yield_ms": 110_000,
                        "end_ms": None,
                        "outcome": "ended",
                        "stream_lifecycle": "clean_eof",
                        "stream_lifecycle_observed": True,
                    },
                    {
                        "ordinal": 2,
                        "start_ms": 20,
                        "first_sanitized_chunk_ms": None,
                        "sanitized_chunk_count": 0,
                        "sanitized_byte_count": 0,
                        "last_sanitized_yield_ms": None,
                        "end_ms": None,
                        "outcome": "cancelled",
                        "stream_lifecycle": "unresolved_at_turn_timeout",
                        "stream_lifecycle_observed": False,
                    },
                ],
            }
        ],
        "runtime_warnings": [],
    }
    encoded = json.dumps(projection)
    assert "private unrelated log value" not in encoded
    assert "owner_id" not in encoded
    assert "execution_id" not in encoded


@pytest.mark.parametrize(
    ("lifecycle", "outcome"),
    [
        ("clean_eof", "ended"),
        ("cancelled_error", "cancelled"),
        ("generator_closed", "cancelled"),
        ("proxy_timeout", "failed"),
        ("safe_protocol_error", "failed"),
    ],
)
def test_native_timing_v2_projection_accepts_each_observed_lifecycle(lifecycle, outcome) -> None:
    value = _native_timing_v2_payload()
    value["provider_requests"][0].update(
        first_sanitized_chunk_ms=100,
        last_sanitized_yield_ms=200,
        end_ms=300,
        outcome=outcome,
        stream_lifecycle=lifecycle,
    )

    projection = probe._native_timing_projection(
        probe._NATIVE_TIMING_V2_MARKER + json.dumps(value, separators=(",", ":"))
    )

    assert projection["rows"][0]["provider_requests"][0]["stream_lifecycle"] == lifecycle


def test_native_warning_projection_keeps_only_closed_terminal_and_timeout_fields() -> None:
    warning = _native_terminal_warning()
    raw = (
        "unrelated private stdout prompt=discard-this\n",
        "2026-10-06T12:00:00Z WARNING stock_probs.assistant.runtime: "
        + warning
        + "\n2026-10-06T12:00:00Z WARNING stock_probs.assistant.runtime: "
        + "Assistant native request timed out "
        "(phase=consume_messages, error_code=request_timeout, elapsed_ms=121250).\n"
        + "unrelated private stderr credential=discard-this",
    )

    projection = probe._native_timing_projection(raw)

    assert projection == {
        "scope": "diagnostic_only",
        "status": "available",
        "rows": [],
        "runtime_warnings": [
            {
                "kind": "native_terminal_failure",
                "occurrence_count": 1,
                "session_outcome": "failed",
                "snapshot_status": "read",
                "assistant_finish": ["error", "stop"],
                "assistant_failure_categories": ["dns", "tls"],
                "assistant_error_count": 2,
                "webfetch_state": ["completed", "error"],
                "webfetch_failure_categories": ["dns"],
                "webfetch_timeout_stages": ["dns_lookup_timeout"],
                "webfetch_timeout_seconds_max": 15.0,
                "webfetch_tool_elapsed_ms_max": 110000,
                "webfetch_completion_categories": ["approved_destination_present"],
                "native_failure_categories": ["dns", "http"],
                "native_tool_error_count": 1,
            },
            {
                "kind": "native_request_timeout",
                "occurrence_count": 1,
                "phase": "consume_messages",
                "error_code": "request_timeout",
                "elapsed_ms": 121250,
            },
        ],
    }
    encoded = json.dumps(projection)
    assert "prompt=discard-this" not in encoded
    assert "credential=discard-this" not in encoded
    assert "stock_probs.assistant.runtime" not in encoded
    assert "session_id" not in encoded
    assert "owner_id" not in encoded


def test_native_warning_projection_accepts_deadline_and_discards_unbounded_failure_text() -> None:
    deadline = probe._NATIVE_WARNING_DEADLINE_MARKER + "(phase=wait_for_idle, elapsed_ms=120001)."
    raw = "\n".join(
        [
            "2026-10-06T12:00:00Z WARNING " + deadline,
            "Assistant turn failed (phase=consume_messages, error_type=PrivateError).",
        ]
    )

    projection = probe._native_timing_projection(raw)

    assert projection == {
        "scope": "diagnostic_only",
        "status": "available",
        "rows": [],
        "runtime_warnings": [
            {
                "kind": "turn_deadline_expired",
                "occurrence_count": 1,
                "phase": "wait_for_idle",
                "elapsed_ms": 120001,
            }
        ],
    }


def test_startup_and_pre_session_warnings_project_only_closed_stage_and_code() -> None:
    startup = (
        probe._NATIVE_WARNING_STARTUP_MARKER
        + "(startup_stage=native_api_info, failure_code=native_api_unavailable)."
    )
    pre_session = (
        probe._NATIVE_WARNING_PRESESSION_MARKER
        + "(stage=create_session, failure_code=request_timeout)."
    )

    projection = probe._native_timing_projection(
        "private exception url=https://private.example/?token=secret\n"
        + startup
        + "\n"
        + pre_session
    )

    assert projection["runtime_warnings"] == [
        {
            "kind": "worker_startup_failure",
            "occurrence_count": 1,
            "stage": "native_api_info",
            "failure_code": "native_api_unavailable",
        },
        {
            "kind": "pre_session_failure",
            "occurrence_count": 1,
            "stage": "create_session",
            "failure_code": "request_timeout",
        },
    ]
    encoded = json.dumps(projection)
    assert "private.example" not in encoded
    assert "token=secret" not in encoded
    assert "exception" not in encoded
    repeated = probe._native_timing_projection("\n".join([startup] * 5))
    assert repeated["runtime_warnings"] == [
        {
            "kind": "worker_startup_failure",
            "occurrence_count": 5,
            "stage": "native_api_info",
            "failure_code": "native_api_unavailable",
        }
    ]
    assert "runtime_warnings_truncated" not in repeated


def test_model_discovery_warning_projects_closed_outcome_and_bounded_counters() -> None:
    warning = _native_model_discovery_warning(
        readiness_attempts=40,
        readiness_timeouts=39,
        catalog_attempts=1,
        catalog_timeouts=1,
        empty_catalog_responses=1,
        missing_alias_responses=1,
        elapsed_ms=7999,
    )
    projection = probe._native_timing_projection(
        "private owner_id=41 url=https://internal.example/?token=secret\n" + warning
    )

    assert projection["runtime_warnings"] == [
        {
            "kind": "model_discovery_diagnostic",
            "occurrence_count": 1,
            "phase": "model_discovery",
            "outcome": "readiness_timeout",
            "readiness_attempts": 40,
            "readiness_timeouts": 39,
            "catalog_attempts": 1,
            "catalog_timeouts": 1,
            "empty_catalog_responses": 1,
            "missing_alias_responses": 1,
            "post_readiness_catalog_responses": 0,
            "post_readiness_missing_alias_responses": 0,
            "elapsed_ms": 7999,
        }
    ]
    encoded = json.dumps(projection)
    assert "internal.example" not in encoded
    assert "token=secret" not in encoded
    assert "owner_id" not in encoded


def test_model_discovery_warning_distinguishes_readiness_and_catalog_exhaustion() -> None:
    readiness = _native_model_discovery_warning(outcome="readiness_timeout")
    catalog = _native_model_discovery_warning(
        outcome="catalog_timeout_after_readiness",
        readiness_attempts=1,
        readiness_timeouts=0,
        catalog_attempts=4,
        catalog_timeouts=4,
        empty_catalog_responses=0,
        missing_alias_responses=4,
        post_readiness_catalog_responses=3,
        post_readiness_missing_alias_responses=3,
    )

    projection = probe._native_timing_projection("\n".join((readiness, catalog)))

    warnings = projection["runtime_warnings"]
    assert [row["outcome"] for row in warnings] == [
        "readiness_timeout",
        "catalog_timeout_after_readiness",
    ]
    assert warnings[0]["readiness_timeouts"] == 3
    assert warnings[1]["post_readiness_missing_alias_responses"] == 3


def test_model_discovery_warning_allowlist_matches_runtime_outcomes() -> None:
    expected = {
        "alias_capabilities_invalid",
        "alias_identity_mismatch",
        "alias_missing",
        "alias_missing_after_readiness",
        "alias_proxy_config_invalid",
        "catalog_http_error",
        "catalog_invalid",
        "catalog_location_mismatch",
        "catalog_timeout",
        "catalog_timeout_after_readiness",
        "readiness_http_error",
        "readiness_invalid",
        "readiness_timeout",
    }

    assert expected == probe._NATIVE_MODEL_DISCOVERY_OUTCOMES
    for outcome in expected:
        projection = probe._native_timing_projection(
            _native_model_discovery_warning(outcome=outcome)
        )
        assert projection["runtime_warnings"][0]["outcome"] == outcome


@pytest.mark.parametrize(
    "warning",
    [
        _native_model_discovery_warning(outcome="private_timeout"),
        _native_model_discovery_warning(readiness_attempts=-1),
        _native_model_discovery_warning(readiness_timeouts="True"),
        _native_model_discovery_warning(catalog_attempts=4097),
        _native_model_discovery_warning(elapsed_ms=180001),
        _native_model_discovery_warning().replace(").", ", private=secret)."),
    ],
)
def test_model_discovery_warning_rejects_malformed_or_unbounded_fields(warning: str) -> None:
    with pytest.raises(probe.ProbeError, match="native .*diagnostic") as error:
        probe._native_timing_projection(warning)
    assert "secret" not in str(error.value)
    assert "private" not in str(error.value)


def test_model_discovery_warning_reuses_distinct_record_and_occurrence_bounds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    outcomes = sorted(probe._NATIVE_MODEL_DISCOVERY_OUTCOMES)
    warnings = [_native_model_discovery_warning(outcome=outcome) for outcome in outcomes[:5]]
    warnings.append(warnings[0])

    projection = probe._native_timing_projection("\n".join(warnings))

    assert len(projection["runtime_warnings"]) == 4
    assert projection["runtime_warnings"][0]["occurrence_count"] == 2
    assert projection["runtime_warnings_truncated"] is True
    assert projection["marker_counts"] == {
        "timing": 0,
        "warning": probe._NATIVE_WARNING_MARKER_COUNT_CAP,
    }
    assert projection["marker_counts_capped"] is True

    monkeypatch.setattr(probe, "_NATIVE_WARNING_OCCURRENCE_COUNT_MAX", 2)
    repeated = _native_model_discovery_warning()
    with pytest.raises(probe.ProbeError, match="record count"):
        probe._native_timing_projection("\n".join([repeated] * 3))


def test_startup_warning_projection_allowlists_match_runtime() -> None:
    runtime_failure_codes = (
        assistant_runtime._RUNTIME_FAILURE_CODES
        | assistant_runtime._APP_EXCEPTION_CODES
        | assistant_runtime._STARTUP_RUNTIME_ERROR_CODES
        | assistant_runtime._SUPERVISOR_ERROR_CODES
        | {"request_timeout", "socket_unavailable", "native_http_error", "diagnostic_unknown"}
    )

    assert probe._NATIVE_WARNING_STARTUP_STAGES == assistant_runtime._STARTUP_DIAGNOSTIC_STAGES
    assert (
        probe._NATIVE_WARNING_PRESESSION_STAGES
        == assistant_runtime._PRESESSION_TURN_DIAGNOSTIC_PHASES
    )
    assert runtime_failure_codes == probe._NATIVE_WARNING_FAILURE_CODES


@pytest.mark.parametrize(
    "warning",
    [
        probe._NATIVE_WARNING_STARTUP_MARKER
        + "(startup_stage=private_value, failure_code=native_api_unavailable).",
        probe._NATIVE_WARNING_STARTUP_MARKER
        + "(startup_stage=supervisor_status, failure_code=private_value).",
        probe._NATIVE_WARNING_PRESESSION_MARKER
        + "(stage=consume_messages, failure_code=request_timeout).",
        probe._NATIVE_WARNING_PRESESSION_MARKER
        + "(stage=verify_location, failure_code=private_value).",
        probe._NATIVE_WARNING_PRESESSION_MARKER
        + "(stage=create_session, failure_code=request_timeout, detail=secret).",
    ],
)
def test_startup_and_pre_session_warnings_reject_unapproved_fields(warning: str) -> None:
    with pytest.raises(probe.ProbeError, match="native warning diagnostic"):
        probe._native_timing_projection(warning)


def test_native_terminal_warning_projects_empty_categories_as_empty_lists() -> None:
    projection = probe._native_timing_projection(_native_empty_terminal_warning())

    assert projection["status"] == "available"
    assert projection["runtime_warnings"] == [
        {
            "kind": "native_terminal_failure",
            "occurrence_count": 1,
            "session_outcome": "unknown",
            "snapshot_status": "invalid_response",
            "assistant_finish": [],
            "assistant_failure_categories": [],
            "assistant_error_count": 0,
            "webfetch_state": [],
            "webfetch_failure_categories": [],
            "webfetch_timeout_stages": [],
            "webfetch_timeout_seconds_max": None,
            "webfetch_tool_elapsed_ms_max": None,
            "webfetch_completion_categories": [],
            "native_failure_categories": [],
            "native_tool_error_count": 0,
        }
    ]


@pytest.mark.parametrize(
    "replacement",
    [
        ("session_outcome=failed", "session_outcome=future"),
        ("snapshot=read", "snapshot=secret"),
        ("assistant_finish=error,stop", "assistant_finish=stop,error"),
        ("assistant_failure=dns,tls", "assistant_failure=dns,secret"),
        ("assistant_error_count=2", "assistant_error_count=4097"),
        ("webfetch_state=completed,error", "webfetch_state=completed,secret"),
        ("webfetch_timeout_stage=dns_lookup_timeout", "webfetch_timeout_stage=private_value"),
        ("webfetch_timeout_seconds_max=15", "webfetch_timeout_seconds_max=NaN"),
        ("webfetch_timeout_seconds_max=15", "webfetch_timeout_seconds_max=inf"),
        ("webfetch_timeout_seconds_max=15", "webfetch_timeout_seconds_max=1e999"),
        ("webfetch_timeout_seconds_max=15", "webfetch_timeout_seconds_max=121"),
        ("webfetch_timeout_seconds_max=15", "webfetch_timeout_seconds_max=15.0"),
        ("webfetch_tool_elapsed_ms_max=110000", "webfetch_tool_elapsed_ms_max=120001"),
        (
            "webfetch_completion=approved_destination_present",
            "webfetch_completion=private_value",
        ),
        ("native_failure=dns,http", "native_failure=http,dns"),
        ("native_tool_error_count=1", "native_tool_error_count=True"),
    ],
)
def test_native_terminal_warning_rejects_malformed_or_out_of_bounds_fields(replacement) -> None:
    warning = _native_terminal_warning()
    raw = warning.replace(*replacement)

    with pytest.raises(probe.ProbeError, match="native .*warning diagnostic"):
        probe._native_timing_projection(raw)


@pytest.mark.parametrize(
    "warning",
    [
        probe._NATIVE_WARNING_DEADLINE_MARKER + "(phase=not_a_phase, elapsed_ms=12).",
        probe._NATIVE_WARNING_DEADLINE_MARKER + "(phase=prompt, elapsed_ms=180001).",
        probe._NATIVE_WARNING_DEADLINE_MARKER + "(phase=prompt, elapsed_ms=1.5).",
        probe._NATIVE_WARNING_REQUEST_TIMEOUT_MARKER
        + "(phase=consume_messages, error_code=request_timeout, elapsed_ms=NaN).",
        probe._NATIVE_WARNING_REQUEST_TIMEOUT_MARKER
        + "(phase=consume_messages, error_code=private_value, elapsed_ms=12).",
        probe._NATIVE_WARNING_SNAPSHOT_MARKER + "(session_outcome=failed, private=secret).",
    ],
)
def test_native_warning_projection_rejects_malformed_matching_markers(warning: str) -> None:
    with pytest.raises(probe.ProbeError, match="native .*warning diagnostic"):
        probe._native_timing_projection(warning)


def test_native_warning_projection_keeps_first_four_distinct_records_on_overflow() -> None:
    phases = (
        "prompt",
        "wait_for_idle",
        "consume_messages",
        "create_session",
        "search_discovery",
    )
    warnings = [
        probe._NATIVE_WARNING_DEADLINE_MARKER + f"(phase={phase}, elapsed_ms={index + 1})."
        for index, phase in enumerate(phases)
    ]
    warnings.append(warnings[0])

    projection = probe._native_timing_projection(("\n".join(warnings[:2]), "\n".join(warnings[2:])))

    assert projection["runtime_warnings"] == [
        {
            "kind": "turn_deadline_expired",
            "occurrence_count": 2 if index == 0 else 1,
            "phase": phase,
            "elapsed_ms": index + 1,
        }
        for index, phase in enumerate(phases[:4])
    ]
    assert projection["runtime_warnings_truncated"] is True
    assert projection["marker_counts"] == {"timing": 0, "warning": 5}
    assert projection["marker_counts_capped"] is True


@pytest.mark.parametrize(
    "invalid_warning",
    [
        probe._NATIVE_WARNING_STARTUP_MARKER
        + "(startup_stage=private_stage, failure_code=native_api_unavailable).",
        probe._NATIVE_WARNING_PRESESSION_MARKER
        + "(stage=create_session, failure_code=private_code).",
        probe._NATIVE_WARNING_STARTUP_MARKER
        + "(startup_stage=native_api_info, failure_code=native_api_unavailable, detail=secret).",
    ],
)
def test_native_warning_projection_rejects_invalid_records_after_overflow(
    invalid_warning: str,
) -> None:
    prefix = [
        probe._NATIVE_WARNING_DEADLINE_MARKER + f"(phase={phase}, elapsed_ms=1)."
        for phase in ("prompt", "wait_for_idle", "consume_messages", "create_session")
    ]

    with pytest.raises(probe.ProbeError, match="native warning diagnostic") as error:
        probe._native_timing_projection("\n".join([*prefix, invalid_warning]))
    assert "secret" not in str(error.value)
    assert "private" not in str(error.value)


def test_candidate_timing_projection_keeps_bounded_warning_counts_and_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidate = probe.Candidate(
        container="assistant-r120-candidate-abc123def456",
        container_id="container-id",
        image_id="sha256:" + "c" * 64,
        data_volume="stock-probs-assistant-r120-abc123def456",
        base_url="http://127.0.0.1:8000",
        host_port=8000,
        host_pid=1,
        cgroup=Path("unused"),
    )
    warning = probe._NATIVE_WARNING_DEADLINE_MARKER + "(phase=prompt, elapsed_ms=1)."

    def command(
        _arguments: list[str], *, _stderr_capture: bytearray | None = None, **_kwargs: object
    ) -> str:
        assert _stderr_capture is not None
        _stderr_capture.extend("\n".join([warning] * 256).encode("utf-8"))
        return "\n".join([warning] * 256)

    monkeypatch.setattr(probe, "_command", command)

    projection = probe._candidate_native_timing_projection(candidate, "2026-10-06T12:00:00Z")

    assert projection["runtime_warnings"] == [
        {
            "kind": "turn_deadline_expired",
            "occurrence_count": 512,
            "phase": "prompt",
            "elapsed_ms": 1,
        }
    ]
    assert "runtime_warnings_truncated" not in projection
    assert len(json.dumps(projection)) < 4096


def test_native_warning_occurrence_count_rejects_values_above_tail_bound() -> None:
    warning = probe._NATIVE_WARNING_DEADLINE_MARKER + "(phase=prompt, elapsed_ms=1)."

    with pytest.raises(probe.ProbeError, match="record count"):
        probe._native_timing_projection("\n".join([warning] * 513))


def test_native_timing_projection_accepts_two_owner_timeout_warning_pairs() -> None:
    timing = probe._NATIVE_TIMING_V2_MARKER + json.dumps(
        _native_timing_v2_payload(), separators=(",", ":")
    )
    timeout = (
        probe._NATIVE_WARNING_REQUEST_TIMEOUT_MARKER
        + "(phase=consume_messages, error_code=request_timeout, elapsed_ms=121250)."
    )
    terminal = _native_terminal_warning()
    raw = "\n".join([timing, terminal, timeout, timing, terminal, timeout])

    projection = probe._native_timing_projection(raw)

    assert projection["status"] == "available"
    assert len(projection["rows"]) == 2
    assert [warning["kind"] for warning in projection["runtime_warnings"]] == [
        "native_terminal_failure",
        "native_request_timeout",
    ]
    assert projection["runtime_warnings"][0]["occurrence_count"] == 2
    assert projection["runtime_warnings"][1]["occurrence_count"] == 2


def test_native_timing_projection_marks_absent_marker_unavailable() -> None:
    assert probe._native_timing_projection("ordinary bounded app output") == {
        "scope": "diagnostic_only",
        "status": "unavailable",
        "rows": [],
        "runtime_warnings": [],
    }


def test_provider_stream_failure_projection_keeps_only_closed_fields() -> None:
    marker = probe._NATIVE_PROVIDER_STREAM_FAILURE_MARKER
    raw = (
        "private prompt must not escape\n"
        "2026-10-06T12:00:00Z WARNING stock_probs.assistant.api: "
        + marker
        + "stage=upstream_stream error_code=provider_upstream_unavailable http_status=503"
    )

    projection = probe._native_timing_projection(raw)

    assert projection["status"] == "available"
    assert projection["provider_stream_failures"] == [
        {
            "kind": "provider_stream_failure",
            "stage": "upstream_stream",
            "error_code": "provider_upstream_unavailable",
            "http_status": 503,
        }
    ]
    encoded = json.dumps(projection)
    assert "private prompt" not in encoded
    assert "stock_probs.assistant.api" not in encoded


def test_provider_stream_failure_projection_rejects_error_type_on_legacy_v1() -> None:
    raw = (
        probe._NATIVE_PROVIDER_STREAM_FAILURE_MARKER
        + "stage=upstream_stream error_code=provider_upstream_unavailable "
        + "http_status=403 provider_error_type_class=free_usage_limit_error"
    )

    with pytest.raises(probe.ProbeError, match="native provider stream diagnostic payload"):
        probe._native_timing_projection(raw)


def test_provider_stream_failure_projection_matches_app_closed_enums() -> None:
    assert probe._NATIVE_PROVIDER_STREAM_FAILURE_MARKER == (
        assistant_api._PROVIDER_STREAM_FAILURE_MARKER
    )
    assert probe._NATIVE_PROVIDER_STREAM_FAILURE_STAGES == (
        assistant_api._PROVIDER_STREAM_FAILURE_STAGES
    )
    assert probe._NATIVE_PROVIDER_STREAM_FAILURE_CODES == (
        assistant_api._PROVIDER_STREAM_FAILURE_ERROR_CODES
    )
    assert probe._NATIVE_PROVIDER_403_CONTENT_TYPE_CLASSES == (
        assistant_api._PROVIDER_403_CONTENT_TYPE_CLASSES
    )
    assert assistant_api._PROVIDER_403_CONTENT_TYPE_CLASSES == (
        assistant_runtime._TURN_TIMING_PROVIDER_403_CONTENT_TYPE_CLASSES
    )
    assert probe._NATIVE_PROVIDER_403_CF_MITIGATED_CLASSES == (
        assistant_api._PROVIDER_403_CF_MITIGATED_CLASSES
    )
    assert assistant_api._PROVIDER_403_CF_MITIGATED_CLASSES == (
        assistant_runtime._TURN_TIMING_PROVIDER_403_CF_MITIGATED_CLASSES
    )
    assert probe._NATIVE_PROVIDER_403_ERROR_TYPE_CLASSES == (
        assistant_api._PROVIDER_403_ERROR_TYPE_CLASSES
    )
    assert assistant_api._PROVIDER_403_ERROR_TYPE_CLASSES == (
        assistant_runtime._TURN_TIMING_PROVIDER_403_ERROR_TYPE_CLASSES
    )
    assert assistant_api._PROVIDER_403_ERROR_TYPE_CLASSES == (
        assistant_net._PROVIDER_403_ERROR_TYPE_CLASSES
    )


@pytest.mark.parametrize(
    "payload",
    [
        "stage=unknown error_code=provider_unavailable",
        "stage=upstream_stream error_code=private-code",
        "stage=upstream_stream error_code=provider_upstream_unavailable http_status=99",
        (
            "stage=upstream_stream error_code=provider_upstream_unavailable "
            "http_status=503 extra=secret"
        ),
        "stage=upstream_stream error_code=provider_upstream_unavailable http_status=999",
    ],
)
def test_provider_stream_failure_projection_rejects_malformed_or_unknown_fields(
    payload: str,
) -> None:
    with pytest.raises(probe.ProbeError, match="native provider stream diagnostic"):
        probe._native_timing_projection(probe._NATIVE_PROVIDER_STREAM_FAILURE_MARKER + payload)


def test_provider_stream_failure_projection_rejects_excess_records() -> None:
    failure = (
        probe._NATIVE_PROVIDER_STREAM_FAILURE_MARKER
        + "stage=upstream_stream error_code=upstream_error_unknown"
    )

    with pytest.raises(probe.ProbeError, match="record count"):
        probe._native_timing_projection("\n".join([failure] * 17))

    projection = probe._native_timing_projection("\n".join([failure] * 16))
    assert projection["status"] == "available"
    assert len(projection["provider_stream_failures"]) == 16


def test_provider_stream_failure_projection_rejects_unknown_marker_version() -> None:
    with pytest.raises(probe.ProbeError, match="marker was invalid"):
        probe._native_timing_projection(
            "ASSISTANT_PROVIDER_STREAM_FAILURE_V2 "
            "stage=upstream_stream error_code=upstream_error_unknown"
        )


def test_native_timing_v3_projects_embedded_provider_failures_as_closed_records() -> None:
    payload = _native_timing_v3_payload()
    requests = payload["provider_requests"]
    assert isinstance(requests, list)
    _native_timing_v3_set_failure(
        requests[0],
        {
            "stage": "upstream_stream",
            "error_code": "provider_upstream_unavailable",
            "http_status": 503,
        },
    )
    _native_timing_v3_set_failure(
        requests[1],
        {"stage": "proxy_guard", "error_code": "upstream_error_unknown", "http_status": None},
    )
    raw = probe._NATIVE_TIMING_V3_MARKER + json.dumps(payload)

    projection = probe._native_timing_projection(raw)

    assert projection["status"] == "available"
    assert len(projection["rows"]) == 1
    assert projection["provider_stream_failures"] == [
        {
            "kind": "provider_stream_failure",
            "stage": "upstream_stream",
            "error_code": "provider_upstream_unavailable",
            "http_status": 503,
        },
        {
            "kind": "provider_stream_failure",
            "stage": "proxy_guard",
            "error_code": "upstream_error_unknown",
            "http_status": None,
        },
    ]
    encoded = json.dumps(projection)
    assert "execution_id" not in encoded
    assert "owner_id" not in encoded
    assert "private" not in encoded


def test_native_timing_v4_projects_closed_403_header_classes() -> None:
    payload = _native_timing_v4_payload()
    requests = payload["provider_requests"]
    assert isinstance(requests, list)
    _native_timing_v3_set_failure(
        requests[0],
        {
            "stage": "upstream_stream",
            "error_code": "provider_upstream_unavailable",
            "http_status": 403,
            "content_type_class": "html",
            "cf_mitigated_class": "challenge",
            "provider_error_type_class": "free_usage_limit_error",
        },
    )

    projection = probe._native_timing_projection(
        probe._NATIVE_TIMING_V4_MARKER + json.dumps(payload)
    )

    assert projection["provider_stream_failures"] == [
        {
            "kind": "provider_stream_failure",
            "stage": "upstream_stream",
            "error_code": "provider_upstream_unavailable",
            "http_status": 403,
            "content_type_class": "html",
            "cf_mitigated_class": "challenge",
            "provider_error_type_class": "free_usage_limit_error",
        }
    ]
    encoded = json.dumps(projection)
    assert "execution_id" not in encoded
    assert "owner_id" not in encoded
    assert "challenge token=" not in encoded


def test_native_timing_v4_projects_error_type_class_without_header_classes() -> None:
    payload = _native_timing_v4_payload()
    requests = payload["provider_requests"]
    assert isinstance(requests, list)
    _native_timing_v3_set_failure(
        requests[0],
        {
            "stage": "upstream_stream",
            "error_code": "provider_upstream_unavailable",
            "http_status": 403,
            "provider_error_type_class": "region_error",
        },
    )

    projection = probe._native_timing_projection(
        probe._NATIVE_TIMING_V4_MARKER + json.dumps(payload)
    )

    assert projection["provider_stream_failures"] == [
        {
            "kind": "provider_stream_failure",
            "stage": "upstream_stream",
            "error_code": "provider_upstream_unavailable",
            "http_status": 403,
            "provider_error_type_class": "region_error",
        }
    ]
    assert "execution_id" not in json.dumps(projection)
    assert "owner_id" not in json.dumps(projection)


def test_native_timing_v4_preserves_legacy_unclassified_403_shape() -> None:
    payload = _native_timing_v4_payload()
    requests = payload["provider_requests"]
    assert isinstance(requests, list)
    _native_timing_v3_set_failure(
        requests[0],
        {
            "stage": "upstream_stream",
            "error_code": "provider_upstream_unavailable",
            "http_status": 403,
        },
    )

    projection = probe._native_timing_projection(
        probe._NATIVE_TIMING_V4_MARKER + json.dumps(payload)
    )

    assert projection["provider_stream_failures"] == [
        {
            "kind": "provider_stream_failure",
            "stage": "upstream_stream",
            "error_code": "provider_upstream_unavailable",
            "http_status": 403,
        }
    ]


def test_native_timing_v5_projects_two_concurrent_closed_pre_session_failures() -> None:
    startup = _native_timing_v5_payload()
    startup.update(
        terminal_status="failed",
        turn_elapsed_ms=900,
        workspace_summary_completed_ms=None,
        pre_session_phase="startup",
        pre_session_failure_code="worker_unavailable",
        provider_requests=[],
    )
    model_discovery = _native_timing_v5_payload()
    model_discovery.update(
        terminal_status="failed",
        turn_elapsed_ms=8120,
        workspace_summary_completed_ms=None,
        pre_session_phase="model_discovery",
        pre_session_failure_code="model_alias_unavailable",
        provider_requests=[],
    )

    projection = probe._native_timing_projection(
        "\n".join(
            probe._NATIVE_TIMING_V5_MARKER + json.dumps(payload)
            for payload in (startup, model_discovery)
        )
    )

    assert [
        (row["pre_session_phase"], row["pre_session_failure_code"]) for row in projection["rows"]
    ] == [
        ("startup", "worker_unavailable"),
        ("model_discovery", "model_alias_unavailable"),
    ]
    assert all(row["provider_requests"] == [] for row in projection["rows"])
    encoded = json.dumps(projection)
    assert "execution_id" not in encoded
    assert "owner_id" not in encoded


def test_native_timing_v5_keeps_success_record_anonymous_and_unclassified() -> None:
    payload = _native_timing_v5_payload()
    payload.update(terminal_status="completed", provider_requests=[])

    projection = probe._native_timing_projection(
        probe._NATIVE_TIMING_V5_MARKER + json.dumps(payload)
    )

    assert projection["rows"][0]["pre_session_phase"] is None
    assert projection["rows"][0]["pre_session_failure_code"] is None
    assert projection["rows"][0]["provider_requests"] == []
    assert "owner_id" not in json.dumps(projection)


def test_native_timing_v5_preserves_existing_provider_failure_projection() -> None:
    payload = _native_timing_v5_payload()
    requests = payload["provider_requests"]
    assert isinstance(requests, list)
    _native_timing_v3_set_failure(
        requests[0],
        {
            "stage": "upstream_stream",
            "error_code": "provider_upstream_unavailable",
            "http_status": 403,
            "content_type_class": "html",
            "cf_mitigated_class": "challenge",
        },
    )

    projection = probe._native_timing_projection(
        probe._NATIVE_TIMING_V5_MARKER + json.dumps(payload)
    )

    assert projection["provider_stream_failures"] == [
        {
            "kind": "provider_stream_failure",
            "stage": "upstream_stream",
            "error_code": "provider_upstream_unavailable",
            "http_status": 403,
            "content_type_class": "html",
            "cf_mitigated_class": "challenge",
        }
    ]
    assert projection["rows"][0]["pre_session_phase"] is None
    assert projection["rows"][0]["pre_session_failure_code"] is None


def test_native_timing_v5_schema_covers_only_runtime_emitter_classifications() -> None:
    assert (
        assistant_runtime._TURN_TIMING_PRESESSION_PHASES <= probe._NATIVE_TIMING_PRESESSION_PHASES
    )
    assert (
        assistant_runtime._TURN_TIMING_PRESESSION_FAILURE_CODES
        <= probe._NATIVE_TIMING_PRESESSION_FAILURE_CODES
    )


@pytest.mark.parametrize(
    "change",
    [
        lambda payload: payload.pop("pre_session_phase"),
        lambda payload: payload.pop("pre_session_failure_code"),
        lambda payload: payload.update(pre_session_failure_code=None),
        lambda payload: payload.update(pre_session_failure_code="private token=synthetic"),
        lambda payload: payload.update(pre_session_phase="private phase=forged"),
        lambda payload: payload.update(pre_session_phase=7),
        lambda payload: payload.update(workspace_summary_completed_ms=840),
        lambda payload: payload.update(
            provider_requests=_native_timing_v4_payload()["provider_requests"]
        ),
        lambda payload: payload.update(owner_id=42),
        lambda payload: payload.update(
            terminal_status="completed",
            pre_session_phase="startup",
            pre_session_failure_code="worker_unavailable",
        ),
    ],
)
def test_native_timing_v5_rejects_missing_unknown_or_forged_pre_session_values(change) -> None:
    payload = _native_timing_v5_payload()
    payload.update(
        terminal_status="failed",
        workspace_summary_completed_ms=None,
        pre_session_phase="startup",
        pre_session_failure_code="worker_unavailable",
        provider_requests=[],
    )
    change(payload)

    with pytest.raises(probe.ProbeError, match="pre-session classification|schema was malformed"):
        probe._native_timing_projection(probe._NATIVE_TIMING_V5_MARKER + json.dumps(payload))


@pytest.mark.parametrize(
    "failure",
    [
        {
            "stage": "upstream_stream",
            "error_code": "provider_upstream_unavailable",
            "http_status": 403,
            "content_type_class": "application/json",
            "cf_mitigated_class": "absent",
        },
        {
            "stage": "upstream_stream",
            "error_code": "provider_upstream_unavailable",
            "http_status": 403,
            "content_type_class": "json",
            "cf_mitigated_class": "private-detail",
        },
        {
            "stage": "upstream_stream",
            "error_code": "provider_upstream_unavailable",
            "http_status": True,
            "content_type_class": "json",
            "cf_mitigated_class": "challenge",
        },
        {
            "stage": "proxy_guard",
            "error_code": "upstream_error_unknown",
            "http_status": 403,
            "content_type_class": "json",
            "cf_mitigated_class": "challenge",
        },
        {
            "stage": "upstream_stream",
            "error_code": "provider_upstream_unavailable",
            "http_status": 403,
            "content_type_class": "json",
            "cf_mitigated_class": "challenge",
            "private": "must not escape",
        },
        {
            "stage": "upstream_stream",
            "error_code": "provider_upstream_unavailable",
            "http_status": 403,
            "provider_error_type_class": "FreeUsageLimitError",
        },
        {
            "stage": "upstream_stream",
            "error_code": "provider_upstream_unavailable",
            "http_status": True,
            "provider_error_type_class": "free_usage_limit_error",
        },
        {
            "stage": "upstream_stream",
            "error_code": "provider_upstream_unavailable",
            "http_status": 503,
            "provider_error_type_class": "free_usage_limit_error",
        },
        {
            "stage": "upstream_stream",
            "error_code": "provider_upstream_unavailable",
            "http_status": 403,
            "provider_error_type_class": "free_usage_limit_error token=synthetic-private",
        },
    ],
)
def test_native_timing_v4_rejects_malformed_403_classes(failure: object) -> None:
    payload = _native_timing_v4_payload()
    requests = payload["provider_requests"]
    assert isinstance(requests, list)
    _native_timing_v3_set_failure(requests[0], failure)

    with pytest.raises(probe.ProbeError, match="native provider stream diagnostic"):
        probe._native_timing_projection(probe._NATIVE_TIMING_V4_MARKER + json.dumps(payload))


def test_native_timing_v3_rejects_v4_classification_fields() -> None:
    payload = _native_timing_v3_payload()
    requests = payload["provider_requests"]
    assert isinstance(requests, list)
    _native_timing_v3_set_failure(
        requests[0],
        {
            "stage": "upstream_stream",
            "error_code": "provider_upstream_unavailable",
            "http_status": 403,
            "content_type_class": "json",
            "cf_mitigated_class": "absent",
        },
    )
    with pytest.raises(probe.ProbeError, match="native provider stream diagnostic"):
        probe._native_timing_projection(probe._NATIVE_TIMING_V3_MARKER + json.dumps(payload))


def test_native_timing_v3_rejects_v4_error_type_class() -> None:
    payload = _native_timing_v3_payload()
    requests = payload["provider_requests"]
    assert isinstance(requests, list)
    _native_timing_v3_set_failure(
        requests[0],
        {
            "stage": "upstream_stream",
            "error_code": "provider_upstream_unavailable",
            "http_status": 403,
            "provider_error_type_class": "free_usage_limit_error",
        },
    )
    with pytest.raises(probe.ProbeError, match="native provider stream diagnostic"):
        probe._native_timing_projection(probe._NATIVE_TIMING_V3_MARKER + json.dumps(payload))


def test_native_timing_v4_accepts_exact_two_by_eight_failure_bound() -> None:
    payloads = [_native_timing_v4_payload(), _native_timing_v4_payload()]
    for payload in payloads:
        requests = payload["provider_requests"]
        assert isinstance(requests, list)
        failure = {
            "stage": "upstream_stream",
            "error_code": "provider_upstream_unavailable",
            "http_status": 403,
            "content_type_class": "json",
            "cf_mitigated_class": "absent",
            "provider_error_type_class": "free_usage_limit_error",
        }
        requests[:] = [
            {
                "ordinal": ordinal,
                "start_ms": ordinal,
                "first_sanitized_chunk_ms": None,
                "sanitized_chunk_count": 0,
                "sanitized_byte_count": 0,
                "last_sanitized_yield_ms": None,
                "end_ms": ordinal + 1,
                "outcome": "failed",
                "stream_lifecycle": "safe_protocol_error",
                "stream_lifecycle_observed": True,
                "failure_diagnostic": dict(failure),
            }
            for ordinal in range(1, 9)
        ]
    raw = "\n".join(probe._NATIVE_TIMING_V4_MARKER + json.dumps(payload) for payload in payloads)

    projection = probe._native_timing_projection(raw)

    assert len(projection["rows"]) == 2
    assert len(projection["provider_stream_failures"]) == 16
    assert all(
        row["content_type_class"] == "json"
        and row["cf_mitigated_class"] == "absent"
        and row["provider_error_type_class"] == "free_usage_limit_error"
        for row in projection["provider_stream_failures"]
    )


@pytest.mark.parametrize(
    "failure",
    [
        {"stage": "private-stage", "error_code": "upstream_error_unknown", "http_status": None},
        {"stage": "proxy_guard", "error_code": "private-code", "http_status": None},
        {"stage": "proxy_guard", "error_code": "upstream_error_unknown", "http_status": True},
        {"stage": "proxy_guard", "error_code": "upstream_error_unknown", "http_status": 99},
        {"stage": "proxy_guard", "error_code": "upstream_error_unknown", "http_status": 600},
        {
            "stage": "proxy_guard",
            "error_code": "upstream_error_unknown",
            "http_status": None,
            "prompt": "must not escape",
        },
        {"stage": "proxy_guard", "error_code": "upstream_error_unknown"},
        "untrusted failure field",
    ],
)
def test_native_timing_v3_rejects_malformed_embedded_provider_failures(
    failure: object,
) -> None:
    payload = _native_timing_v3_payload()
    requests = payload["provider_requests"]
    assert isinstance(requests, list)
    _native_timing_v3_set_failure(requests[0], failure)

    with pytest.raises(probe.ProbeError, match="native provider stream diagnostic"):
        probe._native_timing_projection(probe._NATIVE_TIMING_V3_MARKER + json.dumps(payload))


def test_native_timing_v3_rejects_duplicate_embedded_fields_and_mixed_legacy_markers() -> None:
    payload = _native_timing_v3_payload()
    encoded = json.dumps(payload).replace(
        '"failure_diagnostic": null',
        '{"failure_diagnostic":{"stage":"proxy_guard",'
        '"stage":"upstream_stream","error_code":"upstream_error_unknown",'
        '"http_status":null},"failure_diagnostic":null}',
        1,
    )
    with pytest.raises(probe.ProbeError, match="native timing diagnostic payload"):
        probe._native_timing_projection(probe._NATIVE_TIMING_V3_MARKER + encoded)

    requests = payload["provider_requests"]
    assert isinstance(requests, list)
    _native_timing_v3_set_failure(
        requests[0],
        {"stage": "proxy_guard", "error_code": "upstream_error_unknown", "http_status": None},
    )
    legacy = (
        probe._NATIVE_PROVIDER_STREAM_FAILURE_MARKER
        + "stage=proxy_guard error_code=upstream_error_unknown"
    )
    with pytest.raises(probe.ProbeError, match="mixed"):
        probe._native_timing_projection(
            probe._NATIVE_TIMING_V3_MARKER + json.dumps(payload) + "\n" + legacy
        )


def test_native_timing_projection_rejects_mixed_or_mislabeled_versions() -> None:
    v2 = probe._NATIVE_TIMING_V2_MARKER + json.dumps(_native_timing_v2_payload())
    v3 = probe._NATIVE_TIMING_V3_MARKER + json.dumps(_native_timing_v3_payload())
    with pytest.raises(probe.ProbeError, match="marker version was mixed"):
        probe._native_timing_projection(v2 + "\n" + v3)

    with pytest.raises(probe.ProbeError, match="schema was malformed"):
        probe._native_timing_projection(
            probe._NATIVE_TIMING_V2_MARKER + json.dumps(_native_timing_v3_payload())
        )

    v4 = probe._NATIVE_TIMING_V4_MARKER + json.dumps(_native_timing_v4_payload())
    with pytest.raises(probe.ProbeError, match="marker version was mixed"):
        probe._native_timing_projection(v3 + "\n" + v4)

    legacy = (
        probe._NATIVE_PROVIDER_STREAM_FAILURE_MARKER
        + "stage=upstream_stream error_code=provider_upstream_unavailable http_status=403"
    )
    with pytest.raises(probe.ProbeError, match="source was mixed"):
        probe._native_timing_projection(v4 + "\n" + legacy)


def test_native_timing_v3_accepts_exact_two_by_eight_failure_bound() -> None:
    payload = _native_timing_v3_payload()
    requests = payload["provider_requests"]
    assert isinstance(requests, list)
    failure = {
        "stage": "upstream_stream",
        "error_code": "provider_upstream_unavailable",
        "http_status": 503,
    }
    requests[:] = [
        {
            "ordinal": ordinal,
            "start_ms": ordinal,
            "first_sanitized_chunk_ms": None,
            "sanitized_chunk_count": 0,
            "sanitized_byte_count": 0,
            "last_sanitized_yield_ms": None,
            "end_ms": ordinal + 1,
            "outcome": "failed",
            "stream_lifecycle": "safe_protocol_error",
            "stream_lifecycle_observed": True,
            "failure_diagnostic": dict(failure),
        }
        for ordinal in range(1, 9)
    ]
    first = probe._NATIVE_TIMING_V3_MARKER + json.dumps(payload)
    second_payload = _native_timing_v3_payload()
    second_requests = second_payload["provider_requests"]
    assert isinstance(second_requests, list)
    second_requests[:] = [dict(request) for request in requests]
    second = probe._NATIVE_TIMING_V3_MARKER + json.dumps(second_payload)

    projection = probe._native_timing_projection(first + "\n" + second)

    assert len(projection["rows"]) == 2
    assert len(projection["provider_stream_failures"]) == 16


@pytest.mark.parametrize(
    "change",
    [
        lambda value: value.update(owner_id=4),
        lambda value: value.update(terminal_status=None),
        lambda value: value.update(terminal_status="future"),
        lambda value: value.update(turn_elapsed_ms=True),
        lambda value: value.update(turn_elapsed_ms=180_001),
        lambda value: value.update(workspace_summary_completed_ms=121_000),
        lambda value: value["provider_requests"][0].update(start_ms=120_001),
        lambda value: value["provider_requests"][0].update(first_sanitized_chunk_ms=11),
        lambda value: value["provider_requests"][0].update(end_ms=390),
        lambda value: value["provider_requests"][0].update(outcome="future"),
        lambda value: value["provider_requests"][0].update(end_ms=None, outcome="ended"),
        lambda value: value.update(
            provider_requests=[
                {
                    "ordinal": index,
                    "start_ms": 0,
                    "first_sanitized_chunk_ms": None,
                    "end_ms": 1,
                    "outcome": "ended",
                }
                for index in range(1, 10)
            ]
        ),
    ],
)
def test_native_timing_projection_rejects_unknown_or_out_of_bounds_values(change) -> None:
    value = _native_timing_payload()
    change(value)
    raw = probe._NATIVE_TIMING_MARKER + json.dumps(value, allow_nan=False)

    with pytest.raises(probe.ProbeError, match="native timing diagnostic"):
        probe._native_timing_projection(raw)


@pytest.mark.parametrize(
    "change",
    [
        lambda value: value["provider_requests"][0].update(stream_lifecycle="future"),
        lambda value: value["provider_requests"][0].update(stream_lifecycle_observed=1),
        lambda value: value["provider_requests"][0].update(sanitized_chunk_count=True),
        lambda value: value["provider_requests"][0].update(sanitized_chunk_count=1_048_577),
        lambda value: value["provider_requests"][0].update(sanitized_byte_count=1_048_577),
        lambda value: value["provider_requests"][0].update(last_sanitized_yield_ms=399),
        lambda value: value["provider_requests"][0].update(
            stream_lifecycle="proxy_timeout", outcome="ended"
        ),
        lambda value: value["provider_requests"][1].update(
            stream_lifecycle="unresolved_at_turn_terminal"
        ),
        lambda value: value["provider_requests"][1].update(end_ms=120_001),
        lambda value: value["provider_requests"][0].update(private_data="discard-me"),
    ],
)
def test_native_timing_v2_projection_rejects_malformed_lifecycle_and_counters(change) -> None:
    value = _native_timing_v2_payload()
    change(value)
    raw = probe._NATIVE_TIMING_V2_MARKER + json.dumps(value, allow_nan=False)

    with pytest.raises(probe.ProbeError, match="native timing diagnostic"):
        probe._native_timing_projection(raw)


def test_native_timing_projection_rejects_duplicate_nonfinite_and_excess_markers() -> None:
    payload = json.dumps(_native_timing_payload(), separators=(",", ":"))
    duplicate = probe._NATIVE_TIMING_MARKER + payload[:-1] + ',"event":"forged"}'
    with pytest.raises(probe.ProbeError, match="payload was malformed"):
        probe._native_timing_projection(duplicate)

    nonfinite = probe._NATIVE_TIMING_MARKER + payload.replace("121250", "NaN")
    with pytest.raises(probe.ProbeError, match="payload was malformed"):
        probe._native_timing_projection(nonfinite)

    marker = probe._NATIVE_TIMING_MARKER + payload
    with pytest.raises(probe.ProbeError, match="marker count"):
        probe._native_timing_projection("\n".join([marker] * 3))

    mixed = (
        probe._NATIVE_TIMING_MARKER
        + payload
        + " "
        + probe._NATIVE_TIMING_V2_MARKER
        + json.dumps(_native_timing_v2_payload())
    )
    with pytest.raises(probe.ProbeError, match="marker count"):
        probe._native_timing_projection(mixed)


def test_candidate_timing_log_reader_discards_raw_logs_and_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidate = probe.Candidate(
        container="assistant-r120-candidate-abc123def456",
        container_id="container-id",
        image_id="sha256:" + "c" * 64,
        data_volume="stock-probs-assistant-r120-abc123def456",
        base_url="http://127.0.0.1:8000",
        host_port=8000,
        host_pid=1,
        cgroup=Path("unused"),
    )
    raw = probe._NATIVE_TIMING_MARKER + json.dumps(_native_timing_payload())
    calls: list[list[str]] = []

    def command(
        args: list[str], *, timeout: float, _stderr_capture: bytearray | None = None
    ) -> str:
        calls.append(args)
        assert timeout == 4
        assert _stderr_capture == bytearray()
        return raw

    monkeypatch.setattr(probe, "_command", command)
    projection = probe._candidate_native_timing_projection(candidate, "2026-10-06T12:00:00Z")
    assert projection["status"] == "available"
    assert calls == [
        [
            "docker",
            "logs",
            "--timestamps",
            "--since",
            "2026-10-06T12:00:00Z",
            "--tail",
            "256",
            candidate.container,
        ]
    ]
    assert probe._command_operation(calls[0]) == "docker_logs"

    monkeypatch.setattr(
        probe,
        "_command",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(probe.ProbeError("private")),
    )
    unavailable = probe._candidate_native_timing_projection(candidate, "2026-10-06T12:00:00Z")
    assert unavailable == {
        "scope": "diagnostic_only",
        "status": "unavailable",
        "rows": [],
        "runtime_warnings": [],
    }

    monkeypatch.setattr(probe, "_command", lambda *_args, **_kwargs: "private malformed log")
    absent = probe._candidate_native_timing_projection(candidate, "2026-10-06T12:00:00Z")
    assert absent["status"] == "unavailable"


def test_candidate_timing_projection_retains_embedded_failures_after_log_noise(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidate = probe.Candidate(
        container="assistant-r120-candidate-abc123def456",
        container_id="container-id",
        image_id="sha256:" + "c" * 64,
        data_volume="stock-probs-assistant-r120-abc123def456",
        base_url="http://127.0.0.1:8000",
        host_port=8000,
        host_pid=1,
        cgroup=Path("unused"),
    )
    payloads = [_native_timing_v3_payload(), _native_timing_v3_payload()]
    for payload in payloads:
        requests = payload["provider_requests"]
        assert isinstance(requests, list)
        requests[:] = [
            {
                "ordinal": ordinal,
                "start_ms": ordinal,
                "first_sanitized_chunk_ms": None,
                "sanitized_chunk_count": 0,
                "sanitized_byte_count": 0,
                "last_sanitized_yield_ms": None,
                "end_ms": ordinal + 1,
                "outcome": "failed",
                "stream_lifecycle": "safe_protocol_error",
                "stream_lifecycle_observed": True,
                "failure_diagnostic": {
                    "stage": "upstream_stream",
                    "error_code": "provider_upstream_unavailable",
                    "http_status": 503,
                },
            }
            for ordinal in range(1, 9)
        ]

    synthetic_records = [
        probe._NATIVE_PROVIDER_STREAM_FAILURE_MARKER
        + "stage=upstream_stream error_code=provider_upstream_unavailable http_status=503"
        for _ in range(16)
    ]
    synthetic_records.extend(f"INFO synthetic bounded log noise {index}" for index in range(256))
    timing_records = [probe._NATIVE_TIMING_V3_MARKER + json.dumps(payload) for payload in payloads]
    synthetic_records.extend(timing_records)
    captured_tail = synthetic_records[-256:]
    assert not any(probe._NATIVE_PROVIDER_STREAM_FAILURE_MARKER in line for line in captured_tail)
    stdout_capture = "\n".join(captured_tail[:-2])
    stderr_capture = "\n".join(captured_tail[-2:])
    calls: list[list[str]] = []

    def command(
        arguments: list[str], *, timeout: float, _stderr_capture: bytearray | None = None
    ) -> str:
        calls.append(arguments)
        assert timeout == 4
        assert _stderr_capture is not None
        _stderr_capture.extend(stderr_capture.encode("utf-8"))
        return stdout_capture

    monkeypatch.setattr(probe, "_command", command)

    projection = probe._candidate_native_timing_projection(candidate, "2026-10-06T12:00:00Z")

    assert calls[0][calls[0].index("--tail") + 1] == "256"
    assert projection["status"] == "available"
    assert len(projection["rows"]) == 2
    assert len(projection["provider_stream_failures"]) == 16
    encoded = json.dumps(projection)
    assert "synthetic bounded log noise" not in encoded
    assert "container-id" not in encoded


def test_candidate_timing_log_reader_projects_invalid_marker_without_raw_detail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidate = probe.Candidate(
        container="assistant-r120-candidate-abc123def456",
        container_id="container-id",
        image_id="sha256:" + "c" * 64,
        data_volume="stock-probs-assistant-r120-abc123def456",
        base_url="http://127.0.0.1:8000",
        host_port=8000,
        host_pid=1,
        cgroup=Path("unused"),
    )
    monkeypatch.setattr(
        probe,
        "_command",
        lambda *_args, **_kwargs: probe._NATIVE_TIMING_MARKER + '{"private":"secret"}',
    )

    projection = probe._candidate_native_timing_projection(candidate, "2026-10-06T12:00:00Z")

    assert projection == {
        "scope": "diagnostic_only",
        "status": "invalid",
        "rows": [],
        "runtime_warnings": [],
        "failure_reason": "timing_schema_invalid",
        "marker_counts": {"timing": 1, "warning": 0},
    }
    assert "private" not in json.dumps(projection)
    assert "secret" not in json.dumps(projection)

    monkeypatch.setattr(
        probe,
        "_native_timing_projection",
        lambda _raw: (_ for _ in ()).throw(probe.ProbeError("private credential detail")),
    )
    unknown = probe._candidate_native_timing_projection(candidate, "2026-10-06T12:00:00Z")
    assert unknown["failure_reason"] == "projection_invalid"
    assert unknown["marker_counts"] == {"timing": 1, "warning": 0}
    assert "private" not in json.dumps(unknown)
    assert "credential" not in json.dumps(unknown)


@pytest.mark.parametrize(
    ("raw", "expected_reason", "expected_counts"),
    [
        (
            "x" * (probe.OUTPUT_LIMIT + 1) + probe._NATIVE_TIMING_MARKER * 100,
            "log_input_invalid",
            {"timing": probe._NATIVE_TIMING_MARKER_COUNT_CAP, "warning": 0},
        ),
    ],
)
def test_candidate_timing_projection_rejects_oversized_logs(
    monkeypatch: pytest.MonkeyPatch,
    raw: str,
    expected_reason: str,
    expected_counts: dict[str, int],
) -> None:
    candidate = probe.Candidate(
        container="assistant-r120-candidate-abc123def456",
        container_id="container-id",
        image_id="sha256:" + "c" * 64,
        data_volume="stock-probs-assistant-r120-abc123def456",
        base_url="http://127.0.0.1:8000",
        host_port=8000,
        host_pid=1,
        cgroup=Path("unused"),
    )
    monkeypatch.setattr(probe, "_command", lambda *_args, **_kwargs: raw)

    projection = probe._candidate_native_timing_projection(candidate, "2026-10-06T12:00:00Z")

    assert projection["status"] == "invalid"
    assert projection["failure_reason"] == expected_reason
    assert projection["marker_counts"] == expected_counts
    assert projection["rows"] == []
    assert projection["runtime_warnings"] == []


def test_candidate_provider_stream_diagnostic_fails_closed_with_capped_count(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidate = probe.Candidate(
        container="assistant-r120-candidate-abc123def456",
        container_id="container-id",
        image_id="sha256:" + "c" * 64,
        data_volume="stock-probs-assistant-r120-abc123def456",
        base_url="http://127.0.0.1:8000",
        host_port=8000,
        host_pid=1,
        cgroup=Path("unused"),
    )
    marker = probe._NATIVE_PROVIDER_STREAM_FAILURE_MARKER
    failure = marker + "stage=upstream_stream error_code=upstream_error_unknown"
    monkeypatch.setattr(probe, "_command", lambda *_args, **_kwargs: "\n".join([failure] * 17))

    projection = probe._candidate_native_timing_projection(candidate, "2026-10-06T12:00:00Z")

    assert projection == {
        "scope": "diagnostic_only",
        "status": "invalid",
        "rows": [],
        "runtime_warnings": [],
        "failure_reason": "provider_stream_count_invalid",
        "marker_counts": {"timing": 0, "warning": 0, "provider_stream_failures": 17},
    }
    encoded = json.dumps(projection)
    assert "credential" not in encoded
    assert "secret" not in encoded


def test_candidate_malformed_provider_stream_diagnostic_discards_raw_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidate = probe.Candidate(
        container="assistant-r120-candidate-abc123def456",
        container_id="container-id",
        image_id="sha256:" + "c" * 64,
        data_volume="stock-probs-assistant-r120-abc123def456",
        base_url="http://127.0.0.1:8000",
        host_port=8000,
        host_pid=1,
        cgroup=Path("unused"),
    )
    line = (
        probe._NATIVE_PROVIDER_STREAM_FAILURE_MARKER
        + "stage=upstream_stream error_code=private credential=synthetic-secret"
    )
    monkeypatch.setattr(probe, "_command", lambda *_args, **_kwargs: line)

    projection = probe._candidate_native_timing_projection(candidate, "2026-10-06T12:00:00Z")

    assert projection["status"] == "invalid"
    assert projection["failure_reason"] == "provider_stream_payload_invalid"
    assert projection["marker_counts"] == {
        "timing": 0,
        "warning": 0,
        "provider_stream_failures": 1,
    }
    encoded = json.dumps(projection)
    assert "credential" not in encoded
    assert "synthetic-secret" not in encoded


def test_candidate_timing_log_reader_projects_bounded_stderr_and_discards_other_lines(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidate = probe.Candidate(
        container="assistant-r120-candidate-abc123def456",
        container_id="container-id",
        image_id="sha256:" + "c" * 64,
        data_volume="stock-probs-assistant-r120-abc123def456",
        base_url="http://127.0.0.1:8000",
        host_port=8000,
        host_pid=1,
        cgroup=Path("unused"),
    )
    stderr_lines = (
        "unrelated private stderr token=discard-this\n"
        "WARNING stock_probs.assistant.runtime: "
        + _native_terminal_warning()
        + "\n"
        + probe._NATIVE_TIMING_MARKER
        + json.dumps(_native_timing_payload(), separators=(",", ":"))
        + "\n"
    )

    def command(
        _args: list[str], *, timeout: float, _stderr_capture: bytearray | None = None
    ) -> str:
        assert timeout == 4
        assert _stderr_capture is not None
        _stderr_capture.extend(stderr_lines.encode("utf-8"))
        return "unrelated private stdout authorization=discard-this"

    monkeypatch.setattr(probe, "_command", command)
    projected = probe._candidate_native_timing_projection(candidate, "2026-10-06T12:00:00Z")

    assert projected["status"] == "available"
    assert projected["runtime_warnings"][0]["kind"] == "native_terminal_failure"
    encoded = json.dumps(projected)
    assert "discard-this" not in encoded
    assert "token=" not in encoded
    assert "authorization=" not in encoded


def test_fixed_command_returns_only_explicit_bounded_stderr_buffer() -> None:
    stderr_capture = bytearray()
    output = probe._command(
        [
            sys.executable,
            "-c",
            "import sys; sys.stdout.write('public stdout marker\\n'); "
            "sys.stderr.write('private stderr token=drop-me\\n')",
        ],
        timeout=5,
        _stderr_capture=stderr_capture,
    )

    assert output == "public stdout marker"
    assert bytes(stderr_capture) == b"private stderr token=drop-me\n"
    assert len(stderr_capture) <= probe.ERROR_OUTPUT_LIMIT


def test_active_search_checkpoint_is_exact_and_bounded() -> None:
    receipt = {
        "mode": "attach-existing-app",
        "phase": "active_search_wait",
        "origin": probe.PUBLIC_ORIGIN,
        "owner_index": 1,
        "turn_status": "running",
        "search_preview_pending": True,
        "workspace_summary_digest_matches": True,
        "search_query_sha256": hashlib.sha256(
            probe._WORKER_CACHE_MARKERS["search_query"].encode("utf-8")
        ).hexdigest(),
    }
    probe._validate_active_search_checkpoint(receipt)
    receipt["turn_status"] = "completed"
    with pytest.raises(probe.ProbeError, match="active-search checkpoint"):
        probe._validate_active_search_checkpoint(receipt)


def test_worker_cache_markers_follow_native_attached_probe_contract() -> None:
    prompts = native_probe._attached_probe_prompts()

    assert probe._ATTACH_SEARCH_QUERY == native_probe._ATTACH_SEARCH_QUERY
    assert prompts == probe._ATTACH_PROMPTS
    assert probe._WORKER_CACHE_MARKERS["search_query"] == native_probe._ATTACH_SEARCH_QUERY
    assert probe._WORKER_CACHE_MARKERS["owner_a_prompt"] == prompts[0]
    assert probe._WORKER_CACHE_MARKERS["owner_b_prompt"] == prompts[1]


@pytest.mark.parametrize("fail_dac", [False, True])
def test_native_active_search_ack_precedes_dac_and_requires_dac_before_purge(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, fail_dac: bool
) -> None:
    owner1_cookie = "B" * 43
    config_path = f"/run/assistant/worker-locations/{'2' * 32}/opencode.json"
    ack_path = tmp_path / "acknowledged"
    release_path = tmp_path / "release"
    checkpoint = {
        "mode": "attach-existing-app",
        "phase": "active_search_wait",
        "origin": probe.PUBLIC_ORIGIN,
        "owner_index": 1,
        "turn_status": "running",
        "search_preview_pending": True,
        "workspace_summary_digest_matches": True,
        "search_query_sha256": hashlib.sha256(
            probe._WORKER_CACHE_MARKERS["search_query"].encode("utf-8")
        ).hexdigest(),
    }
    final_line = json.dumps(_driver_receipt(), separators=(",", ":"))
    checkpoint_line = json.dumps(checkpoint, separators=(",", ":"))
    driver_script = "\n".join(
        (
            "import pathlib,sys,time",
            "sys.stdin.readline()",
            f"sys.stdout.write({checkpoint_line!r}+'\\n'); sys.stdout.flush()",
            "if sys.stdin.readline() != '{\"continue\":true}\\n': sys.exit(2)",
            f"pathlib.Path({str(ack_path)!r}).write_text('ack')",
            f"release=pathlib.Path({str(release_path)!r})",
            "while not release.exists(): time.sleep(0.01)",
            f"sys.stdout.write({final_line!r}+'\\n'); sys.stdout.flush()",
        )
    )
    real_popen = subprocess.Popen
    launched: list[subprocess.Popen[bytes]] = []
    events: list[str] = []
    ack_sent = {"value": False}

    class TrackingStdin:
        def __init__(self, stream: IO[bytes]) -> None:
            self._stream = stream
            self._last_write = b""

        def write(self, value: bytes) -> int:
            self._last_write = value
            return self._stream.write(value)

        def flush(self) -> None:
            self._stream.flush()
            if self._last_write == b'{"continue":true}\n':
                ack_sent["value"] = True
                events.append("ack")

        def close(self) -> None:
            self._stream.close()

    def popen_fixture(_args: object, **kwargs: object) -> subprocess.Popen[bytes]:
        child = real_popen([sys.executable, "-c", driver_script], **kwargs)
        assert child.stdin is not None
        child.stdin = TrackingStdin(child.stdin)  # type: ignore[assignment]
        launched.append(child)
        return child

    monkeypatch.setattr(probe.subprocess, "Popen", popen_fixture)
    monkeypatch.setattr(probe, "_read_resources", lambda _candidate: _resource_sample())
    monkeypatch.setattr(
        probe,
        "_health",
        lambda _candidate: {
            "status": "ready",
            "schema_version": 13,
            "assistant": {"status": "ready"},
        },
    )
    cache_scans: list[str] = []

    def scan_cache(_candidate: object) -> dict[str, object]:
        cache_scans.append("checkpoint" if not cache_scans else "purge")
        events.append("cache_checkpoint" if len(cache_scans) == 1 else "cache_purge")
        return {
            "complete": True,
            "marker_counts": {"search_query": 1 if len(cache_scans) == 1 else 0},
        }

    original_active_health = probe._active_native_health_sample

    def active_health(health: object) -> dict[str, object]:
        events.append("active_health")
        return original_active_health(health)

    def active_config(_candidate: object, cookie: str) -> str:
        assert cookie == owner1_cookie
        assert not ack_sent["value"]
        events.append("active_config")
        return config_path

    def private_boundaries(
        _candidate: object, users: list[dict[str, str]], path: str
    ) -> dict[str, object]:
        assert users[1]["session_cookie"] == owner1_cookie
        assert path == config_path
        assert ack_sent["value"]
        events.append("dac")
        if fail_dac:
            raise probe.ProbeError("synthetic DAC denial")
        release_path.write_text("release")
        return {"worker_uid_10002": "denied"}

    monkeypatch.setattr(probe, "_scan_worker_cache", scan_cache)
    monkeypatch.setattr(probe, "_active_native_health_sample", active_health)
    monkeypatch.setattr(probe, "_active_owner_config_path", active_config)
    monkeypatch.setattr(probe, "_probe_private_boundaries", private_boundaries)
    monkeypatch.setattr(
        probe,
        "_candidate_native_timing_projection",
        lambda _candidate, _since: {"scope": "diagnostic_only", "status": "unavailable"},
    )
    candidate = probe.Candidate(
        container="assistant-r120-candidate-abc123def456",
        container_id="container-id",
        image_id="sha256:" + "c" * 64,
        data_volume="stock-probs-assistant-r120-abc123def456",
        base_url="http://127.0.0.1:8000",
        host_port=8000,
        host_pid=1,
        cgroup=Path("unused"),
    )
    users = [
        {"session_cookie": "A" * 43},
        {"session_cookie": owner1_cookie},
    ]

    if fail_dac:
        with pytest.raises(probe.ProbeError, match="synthetic DAC denial"):
            probe._run_native_driver(candidate, users)
        assert cache_scans == ["checkpoint"]
        assert events == ["active_health", "cache_checkpoint", "active_config", "ack", "dac"]
        assert launched and launched[0].poll() is not None
    else:
        driver, _resources, _config, dac, cache = probe._run_native_driver(candidate, users)
        events.append("returned")
        assert driver["acceptance"]["attached_candidate_acceptance"] is True
        assert dac == {"worker_uid_10002": "denied"}
        assert cache["after_cleanup"]["marker_counts"] == {"search_query": 0}
        assert cache_scans == ["checkpoint", "purge"]
        assert events == [
            "active_health",
            "cache_checkpoint",
            "active_config",
            "ack",
            "dac",
            "cache_purge",
            "returned",
        ]


def test_active_config_is_selected_from_owner_one_session_lease(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner0_id = "1" * 32
    owner1_id = "2" * 32
    owner1_cookie = "C" * 43
    captured: list[tuple[str, str, tuple[str, ...], str]] = []

    def resolve_lease(
        _candidate: object,
        user: str,
        script: str,
        *args: str,
        **kwargs: object,
    ) -> dict[str, str]:
        input_text = kwargs.get("input_text")
        assert isinstance(input_text, str)
        captured.append((user, script, args, input_text))
        return {"execution_id": owner1_id}

    monkeypatch.setattr(probe, "_docker_exec_json", resolve_lease)
    monkeypatch.setattr(
        probe,
        "_fixed_location_snapshot",
        lambda _candidate: [
            {
                "path": f"/run/assistant/worker-locations/{owner0_id}/opencode.json",
                "uid": 0,
                "gid": 10002,
                "mode": 0o640,
                "regular": True,
            },
            {
                "path": f"/run/assistant/worker-locations/{owner1_id}/opencode.json",
                "uid": 0,
                "gid": 10002,
                "mode": 0o640,
                "regular": True,
            },
        ],
    )
    candidate = probe.Candidate(
        container="assistant-r120-candidate-abc123def456",
        container_id="container-id",
        image_id="sha256:" + "c" * 64,
        data_volume="stock-probs-assistant-r120-abc123def456",
        base_url="http://127.0.0.1:8000",
        host_port=8000,
        host_pid=1,
        cgroup=Path("unused"),
    )

    path = probe._active_owner_config_path(candidate, owner1_cookie)

    assert path == f"/run/assistant/worker-locations/{owner1_id}/opencode.json"
    assert captured == [
        (
            "10001:10001",
            probe._ACTIVE_OWNER_EXECUTION_SCRIPT,
            (),
            json.dumps(
                {"session_token_sha256": hashlib.sha256(owner1_cookie.encode("ascii")).hexdigest()},
                separators=(",", ":"),
            ),
        )
    ]
    assert owner1_cookie not in captured[0][3]
    compile(probe._ACTIVE_OWNER_EXECUTION_SCRIPT, "<active-owner-lease-script>", "exec")


def test_active_config_fails_closed_if_owner_one_config_is_absent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        probe,
        "_docker_exec_json",
        lambda *args, **kwargs: {"execution_id": "2" * 32},
    )
    monkeypatch.setattr(
        probe,
        "_fixed_location_snapshot",
        lambda _candidate: [
            {
                "path": f"/run/assistant/worker-locations/{'1' * 32}/opencode.json",
                "uid": 0,
                "gid": 10002,
                "mode": 0o640,
                "regular": True,
            }
        ],
    )
    candidate = probe.Candidate(
        container="assistant-r120-candidate-abc123def456",
        container_id="container-id",
        image_id="sha256:" + "c" * 64,
        data_volume="stock-probs-assistant-r120-abc123def456",
        base_url="http://127.0.0.1:8000",
        host_port=8000,
        host_pid=1,
        cgroup=Path("unused"),
    )

    with pytest.raises(probe.ProbeError, match="owner-1 active worker config"):
        probe._active_owner_config_path(candidate, "C" * 43)


def test_active_config_recheck_fails_if_owner_one_lease_changes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = f"/run/assistant/worker-locations/{'2' * 32}/opencode.json"
    monkeypatch.setattr(probe, "_active_owner_config_path", lambda _candidate, _cookie: path)
    candidate = probe.Candidate(
        container="assistant-r120-candidate-abc123def456",
        container_id="container-id",
        image_id="sha256:" + "c" * 64,
        data_volume="stock-probs-assistant-r120-abc123def456",
        base_url="http://127.0.0.1:8000",
        host_port=8000,
        host_pid=1,
        cgroup=Path("unused"),
    )

    with pytest.raises(probe.ProbeError, match="changed during DAC checks"):
        probe._require_active_owner_config(
            candidate,
            "C" * 43,
            f"/run/assistant/worker-locations/{'1' * 32}/opencode.json",
        )


def test_private_boundary_checks_owner_one_lease_around_existing_denials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner1_cookie = "C" * 43
    config_path = f"/run/assistant/worker-locations/{'2' * 32}/opencode.json"
    config_checks: list[str] = []
    docker_calls: list[tuple[str, tuple[str, ...]]] = []
    random_bytes = iter((b"a" * 8, b"b" * 32))
    monkeypatch.setattr(probe.os, "urandom", lambda _size: next(random_bytes))
    monkeypatch.setattr(
        probe,
        "_require_active_owner_config",
        lambda _candidate, cookie, path: config_checks.append(path)
        if cookie == owner1_cookie
        else pytest.fail("DAC config check used the wrong owner session"),
    )
    monkeypatch.setattr(
        probe,
        "_process_snapshot",
        lambda _candidate: [{"role": "app_wrapper", "pid": 4321}],
    )

    worker_probe = {
        "uid": 10002,
        "gid": 10002,
        "data_read_denied": True,
        "data_write_denied": True,
        "data_unlink_denied": True,
        "app_proc_environ_denied": True,
        "control_socket_denied": True,
        "config_readable": True,
        "config_write_denied": True,
        "tmp_read_denied": True,
        "tmp_owner_uid": 10001,
        "tmp_owner_gid": 10001,
        "tmp_mode": 0o700,
    }
    app_probe = {"uid": 10001, "config_write_denied": True}
    app_tmp_probe = {
        "uid": 10001,
        "gid": 10001,
        "tmp_uid": 10001,
        "tmp_gid": 10001,
        "tmp_mode": 0o700,
        "write_unlink_succeeded": True,
    }

    def docker_probe(
        _candidate: object, user: str, script: str, *args: str, **kwargs: object
    ) -> dict[str, object]:
        docker_calls.append((script, args))
        if script == probe._WORKER_DENIAL_SCRIPT:
            return worker_probe
        if script == probe._APP_CONFIG_DENIAL_SCRIPT:
            return app_probe
        if script == probe._APP_TMP_BOUNDARY_SCRIPT:
            return app_tmp_probe
        pytest.fail(f"unexpected DAC helper for {user}")

    monkeypatch.setattr(probe, "_docker_exec_json", docker_probe)
    marker_digest = hashlib.sha256(b"b" * 32).hexdigest()
    monkeypatch.setattr(
        probe,
        "_command",
        lambda args, **kwargs: marker_digest
        if args[args.index("-c") + 1].startswith("import hashlib")
        else "",
    )
    candidate = probe.Candidate(
        container="assistant-r120-candidate-abc123def456",
        container_id="container-id",
        image_id="sha256:" + "c" * 64,
        data_volume="stock-probs-assistant-r120-abc123def456",
        base_url="http://127.0.0.1:8000",
        host_port=8000,
        host_pid=1,
        cgroup=Path("unused"),
    )

    receipt = probe._probe_private_boundaries(
        candidate,
        [{"session_cookie": "A" * 43}, {"session_cookie": owner1_cookie}],
        config_path,
    )

    assert config_checks == [config_path] * 4
    assert docker_calls[0] == (
        probe._WORKER_DENIAL_SCRIPT,
        ("/data/.assistant-r120-private-probe-" + (b"a" * 8).hex(), "4321", config_path),
    )
    assert docker_calls[1] == (probe._APP_CONFIG_DENIAL_SCRIPT, (config_path,))
    assert receipt["worker_uid_10002"].startswith("denied app data")


def test_native_worker_must_be_ready_during_the_active_turn_checkpoint() -> None:
    sample = probe._active_native_health_sample(
        {
            "status": "ready",
            "schema_version": 13,
            "assistant": {"enabled": True, "status": "ready"},
        }
    )
    assert sample == {
        "status": "ready",
        "schema_version": 13,
        "worker_status": "ready",
        "native_turn_active": True,
    }
    with pytest.raises(probe.ProbeError, match="active native-turn checkpoint"):
        probe._active_native_health_sample(
            {
                "status": "ready",
                "schema_version": 13,
                "assistant": {"enabled": True, "status": "starting"},
            }
        )


def test_readiness_rejects_the_obsolete_nested_worker_shape() -> None:
    with pytest.raises(probe.ProbeError, match="active native-turn checkpoint"):
        probe._active_native_health_sample(
            {
                "status": "ready",
                "schema_version": 13,
                "assistant": {"worker": {"status": "ready"}},
            }
        )


@pytest.mark.parametrize(
    "capabilities",
    [
        {"SETUID", "SETGID"},
        {"CAP_SETUID", "CAP_SETGID"},
    ],
)
def test_docker_capability_prefix_normalization_preserves_exact_allowlist(
    capabilities: set[str],
) -> None:
    assert probe._normalize_added_capabilities(capabilities) == {"SETUID", "SETGID"}


@pytest.mark.parametrize(
    "capabilities",
    [
        {"CAP_SETUID", "CAP_SETGID", "CAP_NET_RAW"},
        {"CAP_SETUID", "SETUID", "CAP_SETGID"},
        {"cap_setuid", "CAP_SETGID"},
    ],
)
def test_docker_capability_normalization_rejects_extra_or_ambiguous_values(
    capabilities: set[str],
) -> None:
    message = "fixed set" if "CAP_NET_RAW" in capabilities else "unknown spelling"
    with pytest.raises(probe.ProbeError, match=message):
        probe._normalize_added_capabilities(capabilities)


def _fixed_tmpfs() -> dict[str, str]:
    return {
        "/tmp": "rw,nosuid,nodev,noexec,size=64m,uid=10001,gid=10001,mode=0700",  # noqa: S108
        "/run/assistant": "rw,nosuid,nodev,noexec,size=16m,mode=0711",
        "/run/assistant-worker-home": (
            "rw,nosuid,nodev,noexec,size=64m,uid=10002,gid=10002,mode=0700"
        ),
    }


@pytest.mark.parametrize(
    "mount_rows",
    [
        ["volume|stock-probs-assistant-r120-abc123def456|/data|true"],
        [
            "volume|stock-probs-assistant-r120-abc123def456|/data|true",
            "tmpfs||/tmp|true",
            "tmpfs||/run/assistant|true",
            "tmpfs||/run/assistant-worker-home|true",
        ],
    ],
)
def test_candidate_mount_contract_accepts_hostconfig_tmpfs_and_bounded_mount_views(
    mount_rows: list[str],
) -> None:
    probe._validate_candidate_mounts(
        mount_rows, _fixed_tmpfs(), "stock-probs-assistant-r120-abc123def456"
    )


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (
            "/run/assistant-worker-home",
            "rw,nosuid,nodev,noexec,size=64m,uid=10001,gid=10002,mode=0700",
        ),
        ("/tmp", "rw,nosuid,nodev,noexec,size=64m,uid=10001,gid=10001,mode=0777"),  # noqa: S108
        ("/tmp", "rw,nosuid,nodev,noexec,size=64m,uid=10001,gid=10001,mode=0700,extra=1"),  # noqa: S108
        ("/tmp", "rw,rw,nosuid,nodev,noexec,size=64m,uid=10001,gid=10001,mode=0700"),  # noqa: S108
    ],
)
def test_candidate_mount_contract_rejects_wrong_or_extra_tmpfs_options(
    path: str, value: str
) -> None:
    options = _fixed_tmpfs()
    options[path] = value
    with pytest.raises(probe.ProbeError, match="fixed volume and tmpfs"):
        probe._validate_candidate_mounts(
            ["volume|stock-probs-assistant-r120-abc123def456|/data|true"],
            options,
            "stock-probs-assistant-r120-abc123def456",
        )


@pytest.mark.parametrize(
    "mount_rows",
    [
        [],
        ["volume|some-other-volume|/data|true"],
        [
            "volume|stock-probs-assistant-r120-abc123def456|/data|true",
            "bind|host-path|/etc|true",
        ],
        [
            "volume|stock-probs-assistant-r120-abc123def456|/data|true",
            "tmpfs|unexpected-name|/tmp|true",
        ],
        [
            "volume|stock-probs-assistant-r120-abc123def456|/data|true",
            "tmpfs||/tmp|false",
        ],
    ],
)
def test_candidate_mount_contract_rejects_missing_or_unexpected_mounts(
    mount_rows: list[str],
) -> None:
    with pytest.raises(probe.ProbeError, match="fixed volume and tmpfs"):
        probe._validate_candidate_mounts(
            mount_rows, _fixed_tmpfs(), "stock-probs-assistant-r120-abc123def456"
        )


def test_candidate_mount_contract_rejects_missing_or_extra_hostconfig_paths() -> None:
    options = _fixed_tmpfs()
    del options["/tmp"]  # noqa: S108
    with pytest.raises(probe.ProbeError, match="fixed volume and tmpfs"):
        probe._validate_candidate_mounts(
            ["volume|stock-probs-assistant-r120-abc123def456|/data|true"],
            options,
            "stock-probs-assistant-r120-abc123def456",
        )
    options = _fixed_tmpfs()
    options["/opt/extra"] = "rw,size=1m"
    with pytest.raises(probe.ProbeError, match="fixed volume and tmpfs"):
        probe._validate_candidate_mounts(
            ["volume|stock-probs-assistant-r120-abc123def456|/data|true"],
            options,
            "stock-probs-assistant-r120-abc123def456",
        )


def _candidate_network_fixture(
    *,
    network_mode: str = "stock-probs-assistant-r120-012345abcdef-candidate-network",
    network_name: str = "stock-probs-assistant-r120-012345abcdef-candidate-network",
    network_id: str = "d" * 64,
    attached_networks: dict[str, object] | None = None,
    members: dict[str, object] | None = None,
    driver: str = "bridge",
    scope: str = "local",
    internal: str = "false",
    ipam_driver: str = "default",
) -> dict[str, object]:
    """Return a Docker-free candidate bridge fixture with one exact member."""

    container = "assistant-r120-candidate-012345abcdef"
    container_id = "c" * 64
    volume = "stock-probs-assistant-r120-012345abcdef"
    if attached_networks is None:
        attached_networks = {network_name: {"NetworkID": network_id}}
    if members is None:
        members = {container_id: {"Name": container}}
    inspect = "|".join(
        [
            network_id,
            network_name,
            driver,
            scope,
            internal,
            ipam_driver,
            json.dumps(members, separators=(",", ":")),
        ]
    )
    return {
        "container": container,
        "container_id": container_id,
        "volume": volume,
        "network_mode": network_mode,
        "attached_networks": attached_networks,
        "network_inspect": inspect,
    }


def test_candidate_network_requires_owned_bridge_and_exact_single_membership() -> None:
    fixture = _candidate_network_fixture()

    assert probe._validate_candidate_network(**fixture) == (
        "stock-probs-assistant-r120-012345abcdef-candidate-network",
        "d" * 64,
    )


@pytest.mark.parametrize(
    "change",
    [
        {"network_mode": "bridge"},
        {"network_name": "bridge"},
        {"driver": "host"},
        {"scope": "global"},
        {"internal": "true"},
        {"ipam_driver": "custom"},
        {
            "attached_networks": {
                "stock-probs-assistant-r120-012345abcdef-candidate-network": {"NetworkID": "e" * 64}
            }
        },
        {
            "attached_networks": {
                "stock-probs-assistant-r120-012345abcdef-candidate-network": {
                    "NetworkID": "d" * 64
                },
                "bridge": {"NetworkID": "f" * 64},
            }
        },
        {
            "members": {
                "c" * 64: {"Name": "assistant-r120-candidate-012345abcdef"},
                "e" * 64: {"Name": "other-container"},
            }
        },
        {"members": {"c" * 64: {"Name": "other-container"}}},
    ],
)
def test_candidate_network_rejects_wrong_mode_identity_or_membership(
    change: dict[str, object],
) -> None:
    fixture = _candidate_network_fixture(**change)

    with pytest.raises(probe.ProbeError, match="candidate"):
        probe._validate_candidate_network(**fixture)


def _worker_process_snapshot_fixture() -> list[dict[str, object]]:
    """Build the exact synthetic process credentials expected by the supervisor verifier."""

    return [
        {
            "role": "supervisor",
            "uid": 0,
            "gid": 0,
            "cap_eff": "00000000000000c0",
            "cap_prm": "00000000000000c0",
            "cap_bnd": "00000000000000c0",
            "no_new_privileges": "1",
            "oom_score_adj": "0",
        },
        {
            "role": "app_wrapper",
            "uid": 10001,
            "gid": 10001,
            "cap_eff": "0000000000000000",
            "cap_prm": "0000000000000000",
            "cap_bnd": "00000000000000c0",
            "no_new_privileges": "1",
            "oom_score_adj": "0",
        },
        {
            "role": "worker_wrapper",
            "uid": 10002,
            "gid": 10002,
            "cap_eff": "0000000000000000",
            "cap_prm": "0000000000000000",
            "cap_bnd": "00000000000000c0",
            "no_new_privileges": "1",
            "oom_score_adj": "500",
        },
        {
            "role": "native_worker",
            "uid": 10002,
            "gid": 10002,
            "cap_eff": "0000000000000000",
            "cap_prm": "0000000000000000",
            "cap_bnd": "00000000000000c0",
            "no_new_privileges": "1",
            "oom_score_adj": "500",
        },
    ]


def test_worker_process_verifier_projects_role_gids_and_permitted_capabilities() -> None:
    profile = probe._verify_worker_processes(_worker_process_snapshot_fixture())

    assert profile["roles"]["supervisor"]["gid"] == 0
    assert profile["roles"]["supervisor"]["cap_prm"] == "00000000000000c0"
    for role in ("app_wrapper", "worker_wrapper", "native_worker"):
        assert profile["roles"][role]["cap_prm"] == "0000000000000000"


@pytest.mark.parametrize(
    ("role", "gid"),
    (
        ("supervisor", 1),
        ("app_wrapper", 10002),
        ("worker_wrapper", 10001),
        ("native_worker", 10001),
    ),
)
def test_worker_process_verifier_rejects_wrong_role_gid(role: str, gid: int) -> None:
    snapshot = _worker_process_snapshot_fixture()
    next(row for row in snapshot if row["role"] == role)["gid"] = gid

    with pytest.raises(probe.ProbeError, match="process identity missing"):
        probe._verify_worker_processes(snapshot)


@pytest.mark.parametrize(
    ("role", "cap_prm"),
    (
        ("supervisor", "0000000000000000"),
        ("app_wrapper", "0000000000000001"),
        ("worker_wrapper", "0000000000000001"),
        ("native_worker", "0000000000000001"),
    ),
)
def test_worker_process_verifier_rejects_wrong_role_permitted_capabilities(
    role: str, cap_prm: str
) -> None:
    snapshot = _worker_process_snapshot_fixture()
    next(row for row in snapshot if row["role"] == role)["cap_prm"] = cap_prm

    with pytest.raises(probe.ProbeError, match="permitted capabilities"):
        probe._verify_worker_processes(snapshot)


def test_native_projection_keeps_reviewable_facts_and_drops_content() -> None:
    receipt = _driver_receipt()
    receipt["interaction_diagnostic"] = {"raw_prompt": "must not be success evidence"}
    projection = probe._native_driver_projection(receipt)
    assert projection["attached_candidate_acceptance"] is True
    assert projection["owners"][1]["native_search_source_hosts"] == ["www.nasa.gov"]
    assert projection["owners"][1]["native_webfetch_source_hosts"] == ["www.iana.org"]
    assert projection["webfetch_approved"] is True
    assert projection["webfetch_approval_count"] == 1
    assert projection["conversation_delete_diagnostics"] == [
        {
            "owner_index": 0,
            "http_status": 200,
            "public_error_code": "none",
            "attempt_count": 1,
            "pending_count": 0,
        },
        {
            "owner_index": 1,
            "http_status": 200,
            "public_error_code": "none",
            "attempt_count": 2,
            "pending_count": 1,
        },
    ]
    assert "https://www.iana.org/domains/reserved" not in repr(projection)
    assert "raw_answer" not in projection
    assert "raw_answer" not in repr(projection)
    assert "interaction_diagnostic" not in projection


@pytest.mark.parametrize("host", ["https://nasa.gov", "user@example.com", "bad host"])
def test_native_projection_rejects_unsafe_search_hosts(host: str) -> None:
    receipt = _driver_receipt()
    receipt["owners"][1]["native_search_source_hosts"] = [host]
    with pytest.raises(probe.ProbeError, match="unsafe search source host"):
        probe._native_driver_projection(receipt)


def test_native_projection_requires_final_phase_and_both_deletions() -> None:
    receipt = _driver_receipt()
    receipt["phase"] = "active_search_wait"
    with pytest.raises(probe.ProbeError, match="receipt type"):
        probe._native_driver_projection(receipt)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("conversation_delete_statuses", [200, 503]),
        ("conversation_delete_diagnostics", None),
        (
            "conversation_delete_diagnostics",
            [
                {
                    "owner_index": 0,
                    "http_status": 200,
                    "public_error_code": "none",
                    "attempt_count": 1,
                    "pending_count": 0,
                }
            ],
        ),
        (
            "conversation_delete_diagnostics",
            [
                {
                    "owner_index": 0,
                    "http_status": 200,
                    "public_error_code": "none",
                    "attempt_count": 257,
                    "pending_count": 0,
                },
                {
                    "owner_index": 1,
                    "http_status": 200,
                    "public_error_code": "none",
                    "attempt_count": 1,
                    "pending_count": 0,
                },
            ],
        ),
        (
            "conversation_delete_diagnostics",
            [
                {
                    "owner_index": 0,
                    "http_status": 200,
                    "public_error_code": "none",
                    "attempt_count": 1,
                    "pending_count": 2,
                },
                {
                    "owner_index": 1,
                    "http_status": 200,
                    "public_error_code": "none",
                    "attempt_count": 1,
                    "pending_count": 0,
                },
            ],
        ),
    ],
)
def test_native_projection_fails_closed_on_incomplete_delete_retry_acceptance(
    field: str, value: object
) -> None:
    receipt = _driver_receipt()
    receipt[field] = value

    with pytest.raises(probe.ProbeError, match="deletion"):
        probe._native_driver_projection(receipt)


@pytest.mark.parametrize(
    "changes",
    [
        {"webfetch_approved": False},
        {"webfetch_approval_count": 2},
        {"webfetch_requested_url_sha256": "b" * 64},
        {
            "owners": [
                _driver_receipt()["owners"][0],
                {**_driver_receipt()["owners"][1], "native_webfetch_source_hosts": ["127.0.0.1"]},
            ]
        },
        {
            "owners": [
                {**_driver_receipt()["owners"][0], "webfetch_approved": True},
                _driver_receipt()["owners"][1],
            ]
        },
    ],
)
def test_native_projection_rejects_missing_or_misattributed_webfetch(
    changes: dict[str, object],
) -> None:
    receipt = _driver_receipt()
    receipt.update(changes)
    with pytest.raises(probe.ProbeError):
        probe._native_driver_projection(receipt)
    receipt = _driver_receipt()
    receipt["conversation_delete_statuses"] = [200]
    with pytest.raises(probe.ProbeError, match="deletion statuses"):
        probe._native_driver_projection(receipt)


def test_native_failure_projection_preserves_only_bounded_safe_fields() -> None:
    projection = probe._native_driver_failure_projection(
        {
            "mode": "attach-existing-app",
            "phase": "final",
            "safe_error_code": "model_inventory_invalid",
            "http_status": 503,
            "failure_stage": "model_inventory",
            "started_at": "2026-10-04T20:10:00Z",
            "finished_at": "2026-10-04T20:10:02Z",
            "turn_requests_issued_concurrently": False,
            "active_search_scan_acknowledged": False,
            "attached_candidate_acceptance": False,
            "assistant_worker_status_after_turns": "starting",
            "owner_evidence": [_owner_failure_evidence(0), _owner_failure_evidence(1)],
            "worker_readiness_diagnostic": {
                "readiness_http_status": 200,
                "readiness_status": "ready",
                "schema_version": 13,
                "assistant_enabled": True,
                "assistant_readiness": "starting",
            },
            "interaction_diagnostic": _interaction_diagnostic(),
            "private_prompt": "must not escape",
            "session_cookie": "must not escape",
        }
    )
    assert projection["safe_error_code"] == "model_inventory_invalid"
    assert projection["http_status"] == 503
    assert projection["attached_candidate_acceptance"] is False
    assert projection["failure_stage"] == "model_inventory"
    assert projection["owner_evidence"][1]["workspace_summary_digest_present"] is True
    assert projection["assistant_worker_status_after_turns"] == "starting"
    assert projection["worker_readiness_diagnostic"]["assistant_readiness"] == "starting"
    assert projection["interaction_diagnostic"]["scope"] == "failure_diagnostic_only"
    assert projection["interaction_diagnostic"]["status"] == "available"
    assert projection["interaction_diagnostic"]["elapsed_time_source"] == "host_monotonic"
    assert projection["interaction_diagnostic"]["worker_restart_evidence"] == "unavailable"
    assert "private_prompt" not in projection
    assert "session_cookie" not in projection
    assert "private_prompt" not in repr(projection)
    assert "must not escape" not in repr(projection)


def test_native_failure_projection_preserves_safe_per_owner_deletion_diagnostics() -> None:
    receipt = _native_delete_failure_receipt()
    receipt["conversation_delete_diagnostics"] = [
        {
            "owner_index": 0,
            "http_status": 200,
            "public_error_code": "none",
            "attempt_count": 1,
            "pending_count": 0,
            "response_body": "private deletion response",
        },
        {
            "owner_index": 1,
            "http_status": 503,
            "public_error_code": "assistant_cache_clear_pending",
            "attempt_count": 2,
            "pending_count": 2,
            "detail": "private deletion detail",
        },
    ]
    receipt["unrecognized_private_field"] = "private top-level value"

    projection = probe._native_driver_failure_projection(receipt)

    assert projection["conversation_delete_diagnostics"] == [
        {
            "owner_index": 0,
            "http_status": 200,
            "public_error_code": "none",
            "attempt_count": 1,
            "pending_count": 0,
        },
        {
            "owner_index": 1,
            "http_status": 503,
            "public_error_code": "assistant_cache_clear_pending",
            "attempt_count": 2,
            "pending_count": 2,
        },
    ]
    assert "approved_model_id" not in projection
    assert "raw_answer" not in projection
    assert "unrecognized_private_field" not in projection
    assert "private deletion" not in repr(projection)
    assert "private top-level value" not in repr(projection)


@pytest.mark.parametrize(
    "error_code",
    [None, {"code": "not_found"}, "unrecognized_public_code", "x" * 4096],
)
def test_native_failure_projection_maps_unknown_delete_codes_to_fixed_unknown(
    error_code: object,
) -> None:
    receipt = _native_delete_failure_receipt()
    receipt["conversation_delete_diagnostics"] = [
        {
            "owner_index": 0,
            "http_status": 503,
            "public_error_code": error_code,
            "attempt_count": 1,
            "pending_count": 0,
        }
    ]

    projection = probe._native_driver_failure_projection(receipt)

    assert projection["conversation_delete_diagnostics"] == [
        {
            "owner_index": 0,
            "http_status": 503,
            "public_error_code": "unknown",
            "attempt_count": 1,
            "pending_count": 0,
        }
    ]
    assert error_code is None or str(error_code) not in repr(projection)


@pytest.mark.parametrize("status", [True, 99, 600, 1_000_000, "503", None])
def test_native_failure_projection_rejects_invalid_deletion_http_status(status: object) -> None:
    receipt = _native_delete_failure_receipt()
    receipt["conversation_delete_diagnostics"] = [
        {
            "owner_index": 0,
            "http_status": status,
            "public_error_code": "unknown",
            "attempt_count": 1,
            "pending_count": 0,
        }
    ]

    with pytest.raises(probe.ProbeError, match="deletion HTTP status was malformed"):
        probe._native_driver_failure_projection(receipt)


@pytest.mark.parametrize(
    ("attempt_count", "pending_count"),
    [(True, 0), (-1, 0), (257, 0), (0, 1), (1, -1), (1, 2)],
)
def test_native_failure_projection_rejects_invalid_deletion_retry_counts(
    attempt_count: object, pending_count: object
) -> None:
    receipt = _native_delete_failure_receipt()
    receipt["conversation_delete_diagnostics"] = [
        {
            "owner_index": 0,
            "attempt_count": attempt_count,
            "pending_count": pending_count,
        }
    ]

    with pytest.raises(probe.ProbeError, match="deletion retry counts were malformed"):
        probe._native_driver_failure_projection(receipt)


@pytest.mark.parametrize(
    ("status", "error_code", "attempt_count", "pending_count"),
    [
        (200, "none", 1, 1),
        (503, "assistant_cache_clear_pending", 2, 1),
        (503, "assistant_storage_unavailable", 2, 2),
    ],
)
def test_native_failure_projection_rejects_inconsistent_pending_delete_counts(
    status: int, error_code: str, attempt_count: int, pending_count: int
) -> None:
    receipt = _native_delete_failure_receipt()
    receipt["conversation_delete_diagnostics"] = [
        {
            "owner_index": 0,
            "http_status": status,
            "public_error_code": error_code,
            "attempt_count": attempt_count,
            "pending_count": pending_count,
        }
    ]

    with pytest.raises(probe.ProbeError, match="pending-delete count was inconsistent"):
        probe._native_driver_failure_projection(receipt)


def test_native_failure_projection_allows_owner_with_no_delete_attempt() -> None:
    receipt = _native_delete_failure_receipt()
    receipt["conversation_delete_diagnostics"] = [
        {"owner_index": 0, "attempt_count": 0, "pending_count": 0}
    ]

    projection = probe._native_driver_failure_projection(receipt)

    assert projection["conversation_delete_diagnostics"] == [
        {"owner_index": 0, "attempt_count": 0, "pending_count": 0}
    ]


def test_native_failure_projection_rejects_misattributed_deletion_owner_slot() -> None:
    receipt = _native_delete_failure_receipt()
    receipt["conversation_delete_diagnostics"] = [
        {
            "owner_index": 1,
            "http_status": 503,
            "public_error_code": "unknown",
            "attempt_count": 1,
            "pending_count": 0,
        }
    ]

    with pytest.raises(probe.ProbeError, match="deletion diagnostics were misattributed"):
        probe._native_driver_failure_projection(receipt)


def test_native_failure_projection_accepts_legacy_receipt_without_deletion_diagnostics() -> None:
    receipt = _native_delete_failure_receipt()
    receipt.pop("conversation_delete_diagnostics")

    projection = probe._native_driver_failure_projection(receipt)

    assert "conversation_delete_diagnostics" not in projection


@pytest.mark.parametrize(
    ("payload", "status", "expected"),
    [
        (
            {"error": {"code": "assistant_cache_clear_pending"}},
            503,
            "assistant_cache_clear_pending",
        ),
        ({"error": {"code": "not_found", "message": "private"}}, 404, "not_found"),
        ({"error": {"code": "unreviewed_code", "message": "private"}}, 503, "unknown"),
        ({"error": {"code": "x" * 4096}}, 503, "unknown"),
        ({"error": {"code": "not_found"}}, 200, "none"),
        ({"detail": "private"}, 503, "unknown"),
    ],
)
def test_native_driver_projects_only_fixed_public_deletion_error_codes(
    payload: dict[str, object], status: int, expected: str
) -> None:
    assert native_probe._attached_delete_public_error_code(payload, status) == expected


@pytest.mark.parametrize(
    "worker_status",
    ["unknown_state", None, 17, {"status": "starting"}, ["starting"]],
)
def test_native_failure_projection_rejects_invalid_worker_status(worker_status: object) -> None:
    receipt: dict[str, object] = {
        "mode": "attach-existing-app",
        "phase": "final",
        "safe_error_code": "assistant_worker_unavailable",
        "attached_candidate_acceptance": False,
        "failure_stage": "turn_poll_and_search_confirmation",
        "assistant_worker_status_after_turns": worker_status,
        "owner_evidence": [_owner_failure_evidence(0), _owner_failure_evidence(1)],
        "interaction_diagnostic": _interaction_diagnostic(),
    }

    with pytest.raises(probe.ProbeError, match="failure worker status was malformed"):
        probe._native_driver_failure_projection(receipt)


def test_starting_worker_status_cannot_project_as_success() -> None:
    receipt = _driver_receipt()
    receipt["assistant_worker_status_after_turns"] = "starting"

    with pytest.raises(probe.ProbeError, match="worker status was malformed"):
        probe._native_driver_projection(receipt)


def test_native_failure_projection_derives_static_acceptance_failure_code() -> None:
    projection = probe._native_driver_failure_projection(
        {
            "mode": "attach-existing-app",
            "phase": "final",
            "attached_candidate_acceptance": False,
            "safe_error_code": "acceptance_conditions_unmet",
            "acceptance_failure_code": "acceptance_conditions_unmet",
            "missing_conditions": [
                "owner1_workspace_summary_digest_mismatch",
                "worker_not_ready_after_turns",
            ],
            "failure_stage": "acceptance_validation",
            "owner_evidence": [_owner_failure_evidence(0), _owner_failure_evidence(1)],
            "interaction_diagnostic": _interaction_diagnostic(),
        }
    )
    assert projection["safe_error_code"] == "acceptance_conditions_unmet"
    assert projection["missing_conditions"] == [
        "owner1_workspace_summary_digest_mismatch",
        "worker_not_ready_after_turns",
    ]
    assert projection["owner_evidence"][1]["terminal_status"] == "failed"
    assert projection["owner_evidence"][1]["turn_error_code"] == "worker_unavailable"
    assert projection["owner_evidence"][1]["turn_failure_stage"] == "before_model_session_event"
    assert "private_prompt" not in repr(projection)


@pytest.mark.parametrize(
    "changes",
    [
        {"safe_error_code": "owner@example.com"},
        {"http_status": 0},
        {"attached_candidate_acceptance": True},
        {"failure_stage": "unsafe stage"},
        {"missing_conditions": ["raw private data"]},
        {
            "owner_evidence": [
                _owner_failure_evidence(0),
                {**_owner_failure_evidence(1), "turn_error_code": "token=private"},
            ]
        },
        {
            "owner_evidence": [
                _owner_failure_evidence(0),
                {**_owner_failure_evidence(1), "turn_failure_stage": "raw traceback"},
            ]
        },
        {
            "owner_evidence": [
                _owner_failure_evidence(0),
                {**_owner_failure_evidence(1), "turn_error_code": {"unsafe": "value"}},
            ]
        },
    ],
)
def test_native_failure_projection_rejects_unsafe_or_inconsistent_fields(
    changes: dict[str, object],
) -> None:
    receipt: dict[str, object] = {
        "mode": "attach-existing-app",
        "phase": "final",
        "safe_error_code": "model_inventory_invalid",
        "attached_candidate_acceptance": False,
        "failure_stage": "model_inventory",
        "owner_evidence": [_owner_failure_evidence(0), _owner_failure_evidence(1)],
        "interaction_diagnostic": _interaction_diagnostic(),
    }
    receipt.update(changes)
    with pytest.raises(probe.ProbeError):
        probe._native_driver_failure_projection(receipt)


@pytest.mark.parametrize(
    "status",
    [None, "future", 1],
)
def test_native_failure_projection_rejects_unknown_interaction_status(
    status: object,
) -> None:
    timeline = _interaction_diagnostic()
    timeline["status"] = status
    receipt = {
        "mode": "attach-existing-app",
        "phase": "final",
        "safe_error_code": "model_inventory_invalid",
        "attached_candidate_acceptance": False,
        "failure_stage": "model_inventory",
        "owner_evidence": [_owner_failure_evidence(0), _owner_failure_evidence(1)],
        "interaction_diagnostic": timeline,
    }
    with pytest.raises(probe.ProbeError, match="interaction diagnostic was malformed"):
        probe._native_driver_failure_projection(receipt)


def test_native_failure_projection_requires_explicit_available_interaction_status() -> None:
    timeline = _interaction_diagnostic()
    del timeline["status"]
    receipt = {
        "mode": "attach-existing-app",
        "phase": "final",
        "safe_error_code": "model_inventory_invalid",
        "attached_candidate_acceptance": False,
        "failure_stage": "model_inventory",
        "owner_evidence": [_owner_failure_evidence(0), _owner_failure_evidence(1)],
        "interaction_diagnostic": timeline,
    }
    with pytest.raises(probe.ProbeError, match="interaction diagnostic was malformed"):
        probe._native_driver_failure_projection(receipt)


def test_native_failure_projection_accepts_explicit_unavailable_interaction_status() -> None:
    receipt = {
        "mode": "attach-existing-app",
        "phase": "final",
        "safe_error_code": "model_inventory_invalid",
        "attached_candidate_acceptance": False,
        "failure_stage": "model_inventory",
        "owner_evidence": [_owner_failure_evidence(0), _owner_failure_evidence(1)],
        "interaction_diagnostic": {
            "scope": "failure_diagnostic_only",
            "status": "unavailable",
            "elapsed_time_source": "host_monotonic",
            "owners": [],
            "worker_restart_evidence": "unavailable",
        },
    }
    projection = probe._native_driver_failure_projection(receipt)
    assert projection["interaction_diagnostic"]["status"] == "unavailable"


def test_native_failure_projection_rejects_ambiguous_readiness_fields() -> None:
    receipt: dict[str, object] = {
        "mode": "attach-existing-app",
        "phase": "final",
        "safe_error_code": "assistant_worker_unavailable",
        "attached_candidate_acceptance": False,
        "failure_stage": "turn_poll_and_search_confirmation",
        "owner_evidence": [_owner_failure_evidence(0), _owner_failure_evidence(1)],
        "interaction_diagnostic": _interaction_diagnostic(),
        "worker_readiness_diagnostic": {
            "readiness_http_status": 200,
            "readiness_status": "ready",
            "schema_version": 13,
            "assistant_enabled": 1,
            "assistant_readiness": "ready",
        },
    }
    with pytest.raises(probe.ProbeError, match="readiness diagnostic"):
        probe._native_driver_failure_projection(receipt)


@pytest.mark.parametrize("schema_version", [None, 12])
def test_native_failure_projection_rejects_ready_without_schema_13(
    schema_version: object,
) -> None:
    receipt = {
        "mode": "attach-existing-app",
        "phase": "final",
        "safe_error_code": "assistant_worker_unavailable",
        "attached_candidate_acceptance": False,
        "failure_stage": "turn_poll_and_search_confirmation",
        "owner_evidence": [_owner_failure_evidence(0), _owner_failure_evidence(1)],
        "interaction_diagnostic": _interaction_diagnostic(),
        "worker_readiness_diagnostic": {
            "readiness_http_status": 200,
            "readiness_status": "ready",
            "schema_version": schema_version,
            "assistant_enabled": True,
            "assistant_readiness": "ready",
        },
    }
    with pytest.raises(probe.ProbeError, match="readiness diagnostic was malformed"):
        probe._native_driver_failure_projection(receipt)


def test_native_failure_projection_allows_unavailable_readiness_without_schema() -> None:
    receipt = {
        "mode": "attach-existing-app",
        "phase": "final",
        "safe_error_code": "assistant_worker_unavailable",
        "attached_candidate_acceptance": False,
        "failure_stage": "turn_poll_and_search_confirmation",
        "owner_evidence": [_owner_failure_evidence(0), _owner_failure_evidence(1)],
        "interaction_diagnostic": _interaction_diagnostic(),
        "worker_readiness_diagnostic": {
            "readiness_http_status": 503,
            "readiness_status": "unavailable",
            "schema_version": None,
            "assistant_enabled": None,
            "assistant_readiness": "unavailable",
        },
    }
    projection = probe._native_driver_failure_projection(receipt)
    assert projection["worker_readiness_diagnostic"]["schema_version"] is None


def test_native_failure_projection_accepts_closed_two_owner_timeline() -> None:
    timeline = _interaction_diagnostic()
    timeline["owners"] = [
        {
            "owner_index": 0,
            "turn_elapsed_ms": 120_001,
            "terminal_status": "timed_out",
            "phases": [
                {
                    "phase": "terminal",
                    "count": 1,
                    "first_elapsed_ms": 120_001,
                    "last_elapsed_ms": 120_001,
                }
            ],
        },
        {
            "owner_index": 1,
            "turn_elapsed_ms": 119_000,
            "terminal_status": None,
            "phases": [
                {
                    "phase": "search_preview",
                    "count": 1,
                    "first_elapsed_ms": 800,
                    "last_elapsed_ms": 800,
                },
                {
                    "phase": "search_approval",
                    "count": 1,
                    "first_elapsed_ms": 1_200,
                    "last_elapsed_ms": 1_200,
                },
                {
                    "phase": "search_source",
                    "count": 8,
                    "first_elapsed_ms": 2_000,
                    "last_elapsed_ms": 4_000,
                },
            ],
        },
    ]
    receipt = {
        "mode": "attach-existing-app",
        "phase": "final",
        "safe_error_code": "acceptance_conditions_unmet",
        "acceptance_failure_code": "acceptance_conditions_unmet",
        "missing_conditions": ["owner1_turn_not_completed"],
        "attached_candidate_acceptance": False,
        "failure_stage": "acceptance_validation",
        "owner_evidence": [
            {**_owner_failure_evidence(0), "terminal_status": "timed_out"},
            _owner_failure_evidence(1),
        ],
        "interaction_diagnostic": timeline,
    }
    projection = probe._native_driver_failure_projection(receipt)
    assert projection["interaction_diagnostic"]["owners"][1]["phases"][0]["phase"] == (
        "search_preview"
    )
    assert "worker_restart_evidence" in projection["interaction_diagnostic"]


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value["owners"][0].update({"owner_index": 1}),
        lambda value: value["owners"][0].update({"turn_elapsed_ms": float("nan")}),
        lambda value: value["owners"][0].update({"turn_elapsed_ms": 180_001}),
        lambda value: value["owners"][0].update({"raw_prompt": "private"}),
        lambda value: value["owners"][0]["phases"].append(
            {
                "phase": "search_preview",
                "count": 1,
                "first_elapsed_ms": 10,
                "last_elapsed_ms": 10,
            }
        ),
        lambda value: value.update({"worker_restart_evidence": "restarted"}),
    ],
)
def test_native_failure_projection_rejects_unbounded_or_untrusted_timeline(
    mutation: object,
) -> None:
    timeline = _interaction_diagnostic()
    mutation(timeline)
    receipt = {
        "mode": "attach-existing-app",
        "phase": "final",
        "safe_error_code": "model_inventory_invalid",
        "attached_candidate_acceptance": False,
        "failure_stage": "model_inventory",
        "owner_evidence": [_owner_failure_evidence(0), _owner_failure_evidence(1)],
        "interaction_diagnostic": timeline,
    }
    with pytest.raises(probe.ProbeError, match="interaction"):
        probe._native_driver_failure_projection(receipt)


def _resource_sample(
    *,
    current: int = 100,
    peak: int = 120,
    pids: int = 4,
    cpu: int = 20,
    periods: int = 10,
    throttled: int = 2,
    throttled_usec: int = 3,
    high: int = 0,
    maximum: int = 0,
    oom: int = 0,
    oom_kill: int = 0,
) -> dict[str, int]:
    return {
        "memory_current": current,
        "memory_peak": peak,
        "pids_current": pids,
        "cpu_usage_usec": cpu,
        "cpu_nr_periods": periods,
        "cpu_nr_throttled": throttled,
        "cpu_throttled_usec": throttled_usec,
        "memory_events_high": high,
        "memory_events_max": maximum,
        "memory_events_oom": oom,
        "memory_events_oom_kill": oom_kill,
    }


def test_native_failure_resource_projection_is_failure_only_aggregate() -> None:
    baseline = _resource_sample()
    samples = [
        baseline,
        _resource_sample(
            current=110,
            peak=150,
            pids=8,
            cpu=200,
            periods=150,
            throttled=8,
            throttled_usec=40,
            high=2,
            maximum=1,
            oom=1,
            oom_kill=0,
        ),
    ]
    health = [
        {
            "status": "ready",
            "schema_version": 13,
            "worker_status": "starting",
            "native_turn_active": True,
        },
        {
            "status": "unavailable",
            "schema_version": None,
            "worker_status": None,
            "native_turn_active": None,
        },
        {
            "status": "ready",
            "schema_version": 13,
            "worker_status": "ready",
            "native_turn_active": False,
        },
    ]
    projection = probe._native_failure_resource_projection(samples, baseline, health, 12.5)
    assert projection == {
        "scope": "failure_diagnostic_only",
        "sample_count": 2,
        "duration_ms": 12_500,
        "duration_source": "host_monotonic",
        "memory_start_bytes": 100,
        "memory_peak_bytes": 150,
        "memory_end_bytes": 110,
        "memory_limit_bytes": probe.MEMORY_LIMIT_BYTES,
        "memory_events_baseline": {"high": 0, "max": 0, "oom": 0, "oom_kill": 0},
        "memory_events_delta": {"high": 2, "max": 1, "oom": 1, "oom_kill": 0},
        "cpu_usage_delta_usec": 180,
        "cpu_throttling_baseline": {
            "nr_periods": 10,
            "nr_throttled": 2,
            "throttled_usec": 3,
        },
        "cpu_throttling_delta": {
            "nr_periods": 140,
            "nr_throttled": 6,
            "throttled_usec": 37,
        },
        "pids_peak": 8,
        "health_sample_count": 3,
        "app_readiness_counts": {"ready": 2, "unavailable": 1},
        "worker_readiness_counts": {
            "ready": 1,
            "starting": 1,
            "unavailable": 1,
            "disabled": 0,
            "stopped": 0,
        },
        "native_turn_active_samples": 1,
        "worker_restart_evidence": "unavailable",
    }


@pytest.mark.parametrize(
    "change",
    [
        lambda samples, base, health: samples[1].update({"untrusted": 1}),
        lambda samples, base, health: samples[1].update({"memory_events_oom": -1}),
        lambda samples, base, health: samples[1].update({"cpu_usage_usec": 1}),
        lambda samples, base, health: samples[1].update({"cpu_nr_periods": 1}),
        lambda samples, base, health: samples[1].update({"cpu_nr_throttled": 1}),
        lambda samples, base, health: samples[1].update({"cpu_throttled_usec": 1}),
        lambda samples, base, health: samples[1].update({"cpu_nr_periods": True}),
        lambda samples, base, health: samples[1].update({"cpu_nr_throttled": -1}),
        lambda samples, base, health: samples[1].update(
            {"cpu_throttled_usec": probe._RESOURCE_COUNTER_MAX + 1}
        ),
        lambda samples, base, health: samples[1].pop("cpu_nr_periods"),
        lambda samples, base, health: base.update({"memory_current": 101}),
        lambda samples, base, health: health[0].update({"worker_status": "secret-state"}),
        lambda samples, base, health: health[0].update({"native_turn_active": 1}),
        lambda samples, base, health: health[0].update({"schema_version": None}),
        lambda samples, base, health: health[0].update({"schema_version": 12}),
    ],
)
def test_native_failure_resource_projection_rejects_invalid_samples(change: object) -> None:
    baseline = _resource_sample()
    samples = [baseline.copy(), _resource_sample(current=110, peak=150, cpu=200)]
    health = [
        {
            "status": "ready",
            "schema_version": 13,
            "worker_status": "ready",
            "native_turn_active": True,
        }
    ]
    change(samples, baseline, health)
    with pytest.raises(probe.ProbeError):
        probe._native_failure_resource_projection(samples, baseline, health, 1.0)


@pytest.mark.parametrize("duration", [float("nan"), float("inf"), -1, 201])
def test_native_failure_resource_projection_rejects_invalid_duration(duration: object) -> None:
    baseline = _resource_sample()
    with pytest.raises(probe.ProbeError):
        probe._native_failure_resource_projection([baseline], baseline, [], duration)


def test_native_cpu_throttling_projection_reports_success_sample_deltas() -> None:
    baseline = _resource_sample()
    ending = _resource_sample(periods=18, throttled=5, throttled_usec=23)
    assert probe._native_cpu_throttling_projection([baseline, ending], baseline) == {
        "baseline": {"nr_periods": 10, "nr_throttled": 2, "throttled_usec": 3},
        "delta": {"nr_periods": 8, "nr_throttled": 3, "throttled_usec": 20},
    }


@pytest.mark.parametrize("invalid", [True, 1.0, "1"])
def test_native_cpu_throttling_projection_rejects_noninteger_baseline(
    invalid: object,
) -> None:
    baseline = _resource_sample(periods=1)
    samples = [baseline.copy(), _resource_sample(periods=2)]
    baseline["cpu_nr_periods"] = invalid  # type: ignore[assignment]

    with pytest.raises(probe.ProbeError, match="CPU throttling"):
        probe._native_cpu_throttling_projection(samples, baseline)


@pytest.mark.parametrize(
    "change",
    [
        lambda samples, baseline: samples[1].update({"cpu_nr_periods": 1}),
        lambda samples, baseline: samples[1].update({"cpu_nr_throttled": False}),
        lambda samples, baseline: samples[1].update({"cpu_throttled_usec": -1}),
        lambda samples, baseline: samples[1].pop("cpu_nr_periods"),
        lambda samples, baseline: baseline.update({"cpu_nr_periods": 11}),
        lambda samples, baseline: baseline.update({"unexpected": 1}),
        lambda samples, baseline: baseline.pop("cpu_nr_periods"),
    ],
)
def test_native_cpu_throttling_projection_rejects_invalid_or_nonmonotonic_samples(
    change: object,
) -> None:
    baseline = _resource_sample()
    samples = [baseline.copy(), _resource_sample(periods=12, throttled=3, throttled_usec=5)]
    change(samples, baseline)
    with pytest.raises(probe.ProbeError, match="CPU throttling"):
        probe._native_cpu_throttling_projection(samples, baseline)


def test_native_success_resource_projection_reports_exact_success_deltas() -> None:
    baseline = _resource_sample(high=1, maximum=2, oom=3, oom_kill=4)
    samples = [
        baseline.copy(),
        _resource_sample(
            current=110,
            peak=150,
            pids=8,
            cpu=200,
            periods=150,
            throttled=8,
            throttled_usec=40,
            high=2,
            maximum=3,
            oom=4,
            oom_kill=5,
        ),
    ]

    assert probe._native_success_resource_projection(samples, baseline) == {
        "samples": 2,
        "memory_start_bytes": 100,
        "memory_peak_bytes": 150,
        "memory_end_bytes": 110,
        "memory_limit_bytes": probe.MEMORY_LIMIT_BYTES,
        "memory_events_baseline": {"high": 1, "max": 2, "oom": 3, "oom_kill": 4},
        "memory_events_delta": {"high": 1, "max": 1, "oom": 1, "oom_kill": 1},
        "cpu_usage_delta_usec": 180,
        "cpu_throttling_baseline": {
            "nr_periods": 10,
            "nr_throttled": 2,
            "throttled_usec": 3,
        },
        "cpu_throttling_delta": {
            "nr_periods": 140,
            "nr_throttled": 6,
            "throttled_usec": 37,
        },
        "pids_peak": 8,
        "within_memory_limit": True,
    }


@pytest.mark.parametrize(
    ("field", "decreased_value"),
    [
        ("cpu_usage_usec", 19),
        ("cpu_nr_periods", 9),
        ("cpu_nr_throttled", 1),
        ("cpu_throttled_usec", 2),
        ("memory_peak", 115),
        ("memory_events_high", 0),
        ("memory_events_max", 0),
        ("memory_events_oom", 0),
        ("memory_events_oom_kill", 0),
    ],
)
def test_native_success_resource_projection_rejects_decreasing_counters(
    field: str, decreased_value: int
) -> None:
    baseline = _resource_sample(high=1, maximum=1, oom=1, oom_kill=1)
    ending = _resource_sample(
        current=110,
        peak=150,
        cpu=200,
        periods=12,
        throttled=3,
        throttled_usec=5,
        high=1,
        maximum=1,
        oom=1,
        oom_kill=1,
    )
    ending[field] = decreased_value

    with pytest.raises(probe.ProbeError, match="monotonic"):
        probe._native_success_resource_projection([baseline.copy(), ending], baseline)


@pytest.mark.parametrize("invalid", [True, 1.0, "1"])
def test_native_failure_resource_projection_rejects_noninteger_baseline(
    invalid: object,
) -> None:
    baseline = _resource_sample(high=1)
    samples = [baseline.copy(), _resource_sample(high=2)]
    baseline["memory_events_high"] = invalid  # type: ignore[assignment]

    with pytest.raises(probe.ProbeError, match="failure resource"):
        probe._native_failure_resource_projection(samples, baseline, [], 1.0)


def _write_resource_cgroup(path: Path, *, cpu_stat: str) -> None:
    path.mkdir()
    (path / "cpu.stat").write_text(cpu_stat, encoding="ascii")
    (path / "memory.events").write_text("high 0\nmax 0\noom 0\noom_kill 0\n", encoding="ascii")
    (path / "memory.current").write_text("100\n", encoding="ascii")
    (path / "memory.peak").write_text("120\n", encoding="ascii")
    (path / "pids.current").write_text("4\n", encoding="ascii")


def _resource_candidate(path: Path) -> probe.Candidate:
    return probe.Candidate(
        container="assistant-candidate",
        container_id="a" * 64,
        image_id="sha256:" + "b" * 64,
        data_volume="stock-probs-assistant-test",
        base_url="http://127.0.0.1:8000",
        host_port=8000,
        host_pid=1,
        cgroup=path,
    )


def test_read_resources_requires_and_preserves_cpu_throttling_counters(
    tmp_path: Path,
) -> None:
    _write_resource_cgroup(
        tmp_path / "cgroup",
        cpu_stat=(
            "usage_usec 20\nuser_usec 12\nsystem_usec 8\n"
            "nr_periods 10\nnr_throttled 2\nthrottled_usec 3\n"
        ),
    )
    assert probe._read_resources(_resource_candidate(tmp_path / "cgroup")) == {
        "memory_current": 100,
        "memory_peak": 120,
        "pids_current": 4,
        "cpu_usage_usec": 20,
        "cpu_nr_periods": 10,
        "cpu_nr_throttled": 2,
        "cpu_throttled_usec": 3,
        "memory_events_high": 0,
        "memory_events_max": 0,
        "memory_events_oom": 0,
        "memory_events_oom_kill": 0,
    }


@pytest.mark.parametrize(
    "cpu_stat",
    [
        "usage_usec 20\nnr_periods 10\nnr_throttled 2\n",
        "usage_usec 20\nnr_periods 10\nnr_periods 11\nnr_throttled 2\nthrottled_usec 3\n",
        "usage_usec 20\nnr_periods -1\nnr_throttled 2\nthrottled_usec 3\n",
        f"usage_usec 20\nnr_periods {probe._RESOURCE_COUNTER_MAX + 1}\n"
        "nr_throttled 2\nthrottled_usec 3\n",
        "usage_usec 20\nnr_periods 10 extra\nnr_throttled 2\nthrottled_usec 3\n",
    ],
)
def test_read_resources_fails_closed_on_missing_or_invalid_cpu_throttling_counters(
    tmp_path: Path, cpu_stat: str
) -> None:
    _write_resource_cgroup(tmp_path / "cgroup", cpu_stat=cpu_stat)
    with pytest.raises(probe.ProbeError, match="resource counters became unavailable"):
        probe._read_resources(_resource_candidate(tmp_path / "cgroup"))


def _seed_candidate_fixture() -> probe.Candidate:
    """Return an inspected synthetic candidate with a full immutable Docker identity."""

    volume = "stock-probs-assistant-r120-abc123def456"
    return probe.Candidate(
        container="assistant-r120-candidate-abc123def456",
        container_id="a" * 64,
        image_id="sha256:" + "c" * 64,
        data_volume=volume,
        base_url="http://127.0.0.1:8000",
        host_port=8000,
        host_pid=12345,
        cgroup=Path("/sys/fs/cgroup/synthetic-candidate"),
        network_name=f"{volume}-candidate-network",
        network_id="d" * 64,
    )


def test_refresh_candidate_for_write_rechecks_exact_context_and_full_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidate = _seed_candidate_fixture()
    context_sha256 = "abc123def456" + "0" * 52
    calls: list[tuple[str, str, str, str, str | None]] = []

    def inspect(
        name: str,
        image: str,
        context: str,
        volume: str,
        candidate_revision: str | None = None,
    ) -> probe.Candidate:
        calls.append((name, image, context, volume, candidate_revision))
        return candidate

    monkeypatch.setattr(probe, "_candidate_container", inspect)

    assert probe._refresh_candidate_for_write(candidate, context_sha256) is candidate
    assert calls == [
        (candidate.container, candidate.image_id, context_sha256, candidate.data_volume, None)
    ]


def test_refresh_candidate_for_write_preserves_reviewed_candidate_revision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidate_revision = "a" * 40
    candidate = replace(_seed_candidate_fixture(), candidate_revision=candidate_revision)
    context_sha256 = "abc123def456" + "0" * 52
    calls: list[tuple[str, str, str, str, str | None]] = []

    def inspect(
        name: str,
        image: str,
        context: str,
        volume: str,
        expected_revision: str | None = None,
    ) -> probe.Candidate:
        calls.append((name, image, context, volume, expected_revision))
        return candidate

    monkeypatch.setattr(probe, "_candidate_container", inspect)

    assert probe._refresh_candidate_for_write(candidate, context_sha256) is candidate
    assert calls == [
        (
            candidate.container,
            candidate.image_id,
            context_sha256,
            candidate.data_volume,
            candidate_revision,
        )
    ]


def test_refresh_candidate_for_write_rejects_revision_substitution_before_inspection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidate = replace(_seed_candidate_fixture(), candidate_revision="a" * 40)
    calls: list[str] = []
    monkeypatch.setattr(probe, "_candidate_container", lambda *_args: calls.append("inspect"))

    with pytest.raises(probe.ProbeError, match="candidate revision changed"):
        probe._refresh_candidate_for_write(candidate, "c" * 64, "b" * 40)

    assert calls == []


@pytest.mark.parametrize("candidate_revision", ["A" * 40, "a" * 39, "a" * 41, "x" * 40])
def test_candidate_revision_rejects_malformed_values_before_image_inspection(
    monkeypatch: pytest.MonkeyPatch,
    candidate_revision: str,
) -> None:
    commands: list[list[str]] = []
    monkeypatch.setattr(probe, "_command", lambda args, **_kwargs: commands.append(args) or "")

    with pytest.raises(probe.ProbeError, match="exact lowercase commit SHA"):
        probe._image_identity("sha256:" + "b" * 64, "c" * 64, candidate_revision)

    assert commands == []


@pytest.mark.parametrize(
    ("candidate_revision", "observed_label"),
    [
        (None, "local-source-" + "c" * 64),
        ("a" * 40, "a" * 40),
    ],
)
def test_image_identity_accepts_exact_default_or_reviewed_revision_label(
    monkeypatch: pytest.MonkeyPatch,
    candidate_revision: str | None,
    observed_label: str,
) -> None:
    image_id = "sha256:" + "b" * 64
    commands: list[list[str]] = []
    monkeypatch.setattr(
        probe,
        "_command",
        lambda args, **_kwargs: commands.append(args) or f"{image_id}|linux|amd64|{observed_label}",
    )

    probe._image_identity(image_id, "c" * 64, candidate_revision)

    assert commands[0][-1] == image_id


def test_image_identity_rejects_a_different_reviewed_revision_label(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    image_id = "sha256:" + "b" * 64
    monkeypatch.setattr(
        probe,
        "_command",
        lambda *_args, **_kwargs: f"{image_id}|linux|amd64|{'d' * 40}",
    )

    with pytest.raises(probe.ProbeError, match="image ID, platform, or frozen source label"):
        probe._image_identity(image_id, "c" * 64, "a" * 40)


@pytest.mark.parametrize("candidate_revision", ["A" * 40, "a" * 39, "a" * 41, "x" * 40])
def test_run_probe_rejects_malformed_revision_before_candidate_inspection(
    monkeypatch: pytest.MonkeyPatch,
    candidate_revision: str,
) -> None:
    calls: list[object] = []
    monkeypatch.setattr(probe, "_candidate_container", lambda *_args: calls.append("inspect"))

    with pytest.raises(probe.ProbeError, match="exact lowercase commit SHA"):
        probe.run_probe(
            "assistant-r120-candidate-012345abcdef",
            "sha256:" + "b" * 64,
            "c" * 64,
            "stock-probs-assistant-r120-012345abcdef",
            candidate_revision,
        )

    assert calls == []


def test_probe_cli_passes_candidate_revision_to_run_probe(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    candidate_revision = "a" * 40
    calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def run_probe(*args: object, **kwargs: object) -> dict[str, object]:
        calls.append((args, kwargs))
        return {"status": "pass"}

    monkeypatch.setattr(probe, "run_probe", run_probe)

    assert (
        probe.main(
            [
                "--candidate-container",
                "assistant-r120-candidate-012345abcdef",
                "--candidate-image-id",
                "sha256:" + "b" * 64,
                "--source-context-sha256",
                "c" * 64,
                "--candidate-volume",
                "stock-probs-assistant-r120-012345abcdef",
                "--candidate-revision",
                candidate_revision,
            ]
        )
        == 0
    )

    assert calls == [
        (
            (
                "assistant-r120-candidate-012345abcdef",
                "sha256:" + "b" * 64,
                "c" * 64,
                "stock-probs-assistant-r120-012345abcdef",
                candidate_revision,
            ),
            {},
        )
    ]
    assert json.loads(capsys.readouterr().out) == {"status": "pass"}


@pytest.mark.parametrize(
    ("candidate_revision", "expected_label"),
    [(None, "local-source-" + "c" * 64), ("a" * 40, "a" * 40)],
)
def test_probe_receipt_keeps_candidate_revision_and_image_label(
    monkeypatch: pytest.MonkeyPatch,
    candidate_revision: str | None,
    expected_label: str,
) -> None:
    candidate = replace(_seed_candidate_fixture(), candidate_revision=candidate_revision)
    monkeypatch.setattr(probe, "_candidate_container", lambda *_args: candidate)
    monkeypatch.setattr(probe, "_health", lambda _candidate: {})
    monkeypatch.setattr(probe, "_refresh_candidate_for_write", lambda *_args: candidate)
    monkeypatch.setattr(probe, "_seed_users", lambda _candidate: [])
    monkeypatch.setattr(
        probe,
        "_run_native_driver",
        lambda _candidate, _users: ("driver", "resources", "config", "dac", "cache"),
    )
    monkeypatch.setattr(probe, "_process_snapshot", lambda _candidate: [])
    monkeypatch.setattr(probe, "_verify_worker_processes", lambda _snapshot: "process")

    report = probe.run_probe(
        candidate.container,
        candidate.image_id,
        "c" * 64,
        candidate.data_volume,
        candidate_revision,
    )

    assert report["candidate"]["candidate_revision"] == candidate_revision
    assert report["candidate"]["revision_label"] == expected_label


@pytest.mark.parametrize(
    ("field", "changed"),
    (
        ("container", "assistant-r120-candidate-012345abcdef"),
        ("container_id", "b" * 64),
        ("image_id", "sha256:" + "e" * 64),
        ("data_volume", "stock-probs-assistant-r120-012345abcdef"),
        ("base_url", "http://127.0.0.1:8001"),
        ("host_port", 8001),
        ("host_pid", 12346),
        ("cgroup", Path("/sys/fs/cgroup/other-candidate")),
        ("network_name", "stock-probs-assistant-r120-other-candidate-network"),
        ("network_id", "e" * 64),
    ),
)
def test_refresh_candidate_for_write_rejects_changed_identity(
    monkeypatch: pytest.MonkeyPatch, field: str, changed: object
) -> None:
    candidate = _seed_candidate_fixture()
    observed = replace(candidate, **{field: changed})
    monkeypatch.setattr(probe, "_candidate_container", lambda *_args: observed)

    with pytest.raises(probe.ProbeError, match="identity changed before synthetic state seeding"):
        probe._refresh_candidate_for_write(candidate, "abc123def456" + "0" * 52)


def test_seeder_passes_admin_totp_only_through_private_fixture_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    compile(probe._SEED_SCRIPT, "<synthetic-seed-script>", "exec")
    secret = "JBSWY3DPEHPK3PXP"  # noqa: S105 - deterministic test-only TOTP fixture.
    users = [
        {
            "session_cookie": "A" * 43,
            "csrf_cookie": "B" * 43,
            "expected_tool_result_sha256": "a" * 64,
            "totp_secret": secret,
        },
        {
            "session_cookie": "C" * 43,
            "csrf_cookie": "D" * 43,
            "expected_tool_result_sha256": "b" * 64,
        },
    ]
    commands: list[list[str]] = []

    def command(args: list[str], **_kwargs: object) -> str:
        commands.append(args)
        return json.dumps({"users": users})

    monkeypatch.setattr(probe, "_command", command)
    candidate = _seed_candidate_fixture()

    selected = probe._seed_users(candidate)

    assert selected[0]["totp_secret"] == secret
    assert "totp_secret" not in selected[1]
    assert commands[0][5] == candidate.container_id


@pytest.mark.parametrize(
    ("field", "changed"),
    (
        ("container_id", "legacy-name-only-id"),
        ("network_name", None),
        ("network_id", None),
        ("network_id", "invalid-network-id"),
    ),
)
def test_seeder_fails_closed_without_full_candidate_and_network_identity(
    monkeypatch: pytest.MonkeyPatch, field: str, changed: object
) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr(probe, "_command", lambda args, **_kwargs: calls.append(args) or "{}")

    with pytest.raises(probe.ProbeError, match="exact inspected candidate identity"):
        probe._seed_users(replace(_seed_candidate_fixture(), **{field: changed}))

    assert calls == []


def test_candidate_exec_uses_immutable_container_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidate = _seed_candidate_fixture()
    calls: list[list[str]] = []
    monkeypatch.setattr(probe, "_command", lambda args, **_kwargs: calls.append(args) or "{}")

    assert probe._docker_exec_json(candidate, "10001:10001", "print('{}')") == {}

    assert calls[0][5] == candidate.container_id


def test_embedded_seeder_creates_admin_totp_factor_in_a_temporary_repository(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data_dir = tmp_path / "seed-data"
    settings = Settings(
        data_dir=data_dir,
        database_path=data_dir / "stock_probs.sqlite3",
        backup_dir=data_dir / "backups",
        environment="test",
        auth_session_secret="synthetic-seed-test-session-secret-2026-10-04",  # noqa: S106
    )
    repository = Repository(settings.database_path)
    repository.migrate()
    monkeypatch.setattr(Settings, "from_env", classmethod(lambda cls: settings))

    with contextlib.redirect_stdout(io.StringIO()):
        exec(  # noqa: S102 - execute the fixed test seeder against this temporary repository.
            compile(probe._SEED_SCRIPT, "<synthetic-seed-script>", "exec"),
            {"__name__": "__main__"},
        )

    with repository.connect() as connection:
        rows = connection.execute(
            "SELECT role FROM users WHERE login LIKE 'r120-probe-%' ORDER BY id"
        ).fetchall()
        assert [row["role"] for row in rows] == ["admin", "member"]
        factor_count, encrypted_factor_count = connection.execute(
            """SELECT COUNT(*), SUM(length(secret_ciphertext) > 50)
            FROM totp_factors
            WHERE user_id IN (SELECT id FROM users WHERE login LIKE 'r120-probe-%')"""
        ).fetchone()
        assert (factor_count, encrypted_factor_count) == (2, 1)
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM sessions s JOIN users u ON u.id=s.user_id "
                "WHERE u.login LIKE 'r120-probe-%'"
            ).fetchone()[0]
            == 2
        )
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM user_instrument_list_items WHERE provider='Synthetic Test'"
            ).fetchone()[0]
            == 3
        )


def test_seeder_rejects_totp_secret_on_non_admin_fixture(monkeypatch: pytest.MonkeyPatch) -> None:
    users = [
        {
            "session_cookie": "A" * 43,
            "csrf_cookie": "B" * 43,
            "expected_tool_result_sha256": "a" * 64,
            "totp_secret": "JBSWY3DPEHPK3PXP",
        },
        {
            "session_cookie": "C" * 43,
            "csrf_cookie": "D" * 43,
            "expected_tool_result_sha256": "b" * 64,
            "totp_secret": "KRSXG5DSNFXGOIDB",
        },
    ]
    monkeypatch.setattr(probe, "_command", lambda *args, **kwargs: json.dumps({"users": users}))
    candidate = _seed_candidate_fixture()
    with pytest.raises(probe.ProbeError, match="bounded identity"):
        probe._seed_users(candidate)


def test_fixed_command_drains_both_streams_without_unbounded_capture() -> None:
    script = "import sys; sys.stdout.write('o' * 90000); sys.stderr.write('e' * 24000)"
    result = probe._command([sys.executable, "-c", script], timeout=5)
    assert result == "o" * 90000


def test_fixed_command_retries_nonblocking_stdin_without_dropping_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = "synthetic-input-" * 4096
    original_write = probe.os.write
    calls = 0

    def write_with_one_eagain(descriptor: int, value: bytes) -> int:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise BlockingIOError
        return original_write(descriptor, value)

    monkeypatch.setattr(probe.os, "write", write_with_one_eagain)
    script = "import sys; value=sys.stdin.buffer.read(); print(len(value))"
    result = probe._command([sys.executable, "-c", script], timeout=5, input_text=payload)

    assert result == str(len(payload.encode("utf-8")))
    assert calls >= 2


def test_fixed_command_reports_bounded_secret_stderr_without_echoing_it() -> None:
    stderr_marker = "synthetic-command-stderr-secret"
    script = "import sys; sys.stderr.write(" + repr(stderr_marker) + " + 'x' * 150000)"
    with pytest.raises(probe.ProbeError) as captured:
        probe._command([sys.executable, "-c", script], timeout=5)

    error = captured.value
    assert stderr_marker not in str(error)
    assert stderr_marker not in json.dumps(error.safe_details)
    assert error.safe_details["command_operation"] == "python"
    assert error.safe_details["command_stage"] == "stderr_limit"
    assert error.safe_details["stdout_bytes"] == 0
    assert error.safe_details["stderr_bytes"] == probe.ERROR_OUTPUT_LIMIT + 1
    assert error.safe_details["command_exit_code"] in {0, -9, -15}


def test_fixed_command_enforces_stdout_limit_too() -> None:
    script = "import sys; sys.stdout.write('o' * 150000)"
    with pytest.raises(probe.ProbeError) as captured:
        probe._command([sys.executable, "-c", script], timeout=5)

    assert captured.value.safe_details["command_stage"] == "stdout_limit"
    assert captured.value.safe_details["stdout_bytes"] == probe.OUTPUT_LIMIT + 1
    assert captured.value.safe_details["command_exit_code"] in {0, -9, -15}


def test_fixed_command_timeout_reaps_direct_child_and_closes_pipes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_popen = subprocess.Popen
    children: list[subprocess.Popen[bytes]] = []

    def capture_child(*args: object, **kwargs: object) -> subprocess.Popen[bytes]:
        child = real_popen(*args, **kwargs)  # type: ignore[arg-type]
        children.append(child)
        return child

    monkeypatch.setattr(probe.subprocess, "Popen", capture_child)
    with pytest.raises(probe.ProbeError) as captured:
        probe._command(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            timeout=0.1,
            input_text="synthetic-input",
        )

    assert len(children) == 1
    child = children[0]
    assert child.poll() is not None
    assert child.returncode is not None
    assert child.stdin is not None and child.stdin.closed
    assert child.stdout is not None and child.stdout.closed
    assert child.stderr is not None and child.stderr.closed
    assert captured.value.safe_details["command_stage"] == "timeout"


def test_fixed_command_nonzero_diagnostic_does_not_include_private_stderr() -> None:
    stderr_marker = "synthetic-nonzero-stderr-secret"
    script = "import sys; sys.stderr.write(" + repr(stderr_marker) + "); sys.exit(23)"
    with pytest.raises(probe.ProbeError) as captured:
        probe._command([sys.executable, "-c", script], timeout=5)

    assert stderr_marker not in str(captured.value)
    assert stderr_marker not in json.dumps(captured.value.safe_details)
    assert captured.value.safe_details["command_exit_code"] == 23
    assert captured.value.safe_details["stderr_bytes"] == len(stderr_marker)


def test_fixed_docker_operation_diagnostics_are_closed_names() -> None:
    assert probe._command_operation(["docker", "inspect", "private-name"]) == "docker_inspect"
    assert (
        probe._command_operation(["docker", "exec", "-c", probe._SEED_SCRIPT]) == "docker_seed_exec"
    )


def test_docker_command_uses_only_fixed_local_endpoint_and_empty_private_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_popen = subprocess.Popen
    captured: dict[str, object] = {}
    for key in ("DOCKER_HOST", "DOCKER_CONTEXT", "DOCKER_CONFIG", "DOCKER_CERT_PATH"):
        monkeypatch.setenv(key, "synthetic-untrusted-value")

    def fake_docker_popen(args: object, **kwargs: object) -> subprocess.Popen[bytes]:
        if args == ["docker", "info"]:
            environment = kwargs.get("env")
            assert isinstance(environment, dict)
            captured["environment"] = environment
            config_path = Path(environment["DOCKER_CONFIG"])
            captured["config_path"] = config_path
            assert config_path.is_dir()
            assert list(config_path.iterdir()) == []
            return real_popen([sys.executable, "-c", "print('synthetic-docker-command')"], **kwargs)
        return real_popen(args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(probe.subprocess, "Popen", fake_docker_popen)

    assert probe._command(["docker", "info"], timeout=5) == "synthetic-docker-command"

    environment = captured["environment"]
    assert isinstance(environment, dict)
    assert set(environment) == {"PATH", "DOCKER_CONFIG", "DOCKER_HOST"}
    assert environment["PATH"] == "/usr/bin:/bin"
    assert environment["DOCKER_HOST"] == probe.DOCKER_DAEMON_ENDPOINT
    assert environment["DOCKER_HOST"] == "unix:///var/run/docker.sock"
    assert not Path(str(captured["config_path"])).exists()
