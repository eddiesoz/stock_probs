"""Test the opt-in native permission probe's closed fixtures and fail-closed receipt."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from stock_probs.container_supervisor import (
    _DENIED_ACTIONS,
    _MCP_ACTIONS,
    _fixed_location_config,
)
from tests.native_assistant_boundary_probe import (
    _ATTEMPTS,
    _attempt_arguments,
    _evaluate_boundary_observations,
    _make_permissions,
    _native_message_shapes,
    _ProbeFailure,
    _provider_message_shapes,
    _RuntimeState,
    _tool_parts,
    _wait_permissions,
)


def _passing_observations() -> list[dict[str, object]]:
    return [
        {
            "attempt": name,
            "provider_requested_unadvertised_tool": True,
            "native_denial_or_rejection_observed": True,
            "pending_permission_actions": [],
            "pending_permission_actions_after_cleanup": [],
            "mcp_tool_call_delta": 0,
            "browser_fixture_request_delta": 0,
            "new_child_process_count": 0,
            "sentinel_marker_returned": False,
            "edit_sentinel_unchanged": True,
            "side_effect_path_exists": False,
            "title_matches_explicit_session_title": True,
        }
        for name, _ in _ATTEMPTS
    ]


def _passing_auxiliary() -> dict[str, object]:
    return {
        "all_provider_calls_used_selected_alias": True,
        "all_provider_calls_used_fixed_proxy_route": True,
        "provider_use_policy_is_proxy_only": True,
        "secondary_model_configured": False,
        "compaction_auto_disabled": True,
        "approved_mcp_action_advertised": True,
        "native_mcp_tool_call_count": 0,
    }


def _evaluate(
    observations: list[dict[str, object]] | None = None,
    advertised_names: set[str] | None = None,
    auxiliary: dict[str, object] | None = None,
) -> dict[str, bool]:
    expected_attempts = {name for name, _ in _ATTEMPTS}
    return _evaluate_boundary_observations(
        observations=observations if observations is not None else _passing_observations(),
        advertised_names=advertised_names or set(),
        expected_attempts=expected_attempts,
        expected_denied=set(_DENIED_ACTIONS) | {"signal-ledger_deployment_publish"},
        auxiliary=auxiliary if auxiliary is not None else _passing_auxiliary(),
        mcp_discovery=True,
        model_discovery=True,
    )


def test_native_probe_reuses_the_supervisor_deny_first_allowlist() -> None:
    permissions = _make_permissions()

    assert permissions[0] == {"action": "*", "resource": "*", "effect": "deny"}
    assert {row["action"] for row in permissions if row.get("effect") == "allow"} == set(
        _MCP_ACTIONS
    )
    assert all(
        {"action": name, "resource": "*", "effect": "deny"} in permissions
        for name in _DENIED_ACTIONS
    )
    assert {"action": "websearch", "resource": "*", "effect": "ask"} in permissions
    assert "signal-ledger_deployment_publish" not in {
        row["action"] for row in permissions if row.get("effect") == "allow"
    }


def test_native_probe_config_keeps_one_provider_model_and_no_auto_compaction() -> None:
    config = _fixed_location_config(
        proxy_base_url="http://127.0.0.1:41321/v1",
        proxy_capability="synthetic-provider-capability-only",
        mcp_url="http://127.0.0.1:41321/mcp",
        mcp_capability="synthetic-mcp-capability-only",
    )

    assert config["model"] == "assistant-proxy/assistant-selected"
    assert set(config["providers"]) == {"assistant-proxy"}
    assert set(config["providers"]["assistant-proxy"]["models"]) == {"assistant-selected"}
    assert config["compaction"] == {"auto": False}
    assert "small_model" not in config
    assert config["experimental"]["policies"] == [
        {"action": "provider.use", "resource": "*", "effect": "deny"},
        {"action": "provider.use", "resource": "assistant-proxy", "effect": "allow"},
    ]


def test_synthetic_tool_attempts_are_bounded_to_local_fixture_paths(tmp_path: Path) -> None:
    state = _RuntimeState()
    state.attempt_paths = {
        "execute_path": str(tmp_path / "execute-created"),
        "shell_path": str(tmp_path / "shell-created"),
        "read_path": str(tmp_path / "read-sentinel"),
        "edit_path": str(tmp_path / "edit-sentinel"),
        "subagent_path": str(tmp_path / "subagent-created"),
    }
    state.browser_port = 43123

    assert _attempt_arguments("execute", state) == {
        "command": f"touch {tmp_path / 'execute-created'} && sleep 0.2"
    }
    assert _attempt_arguments("shell", state) == {
        "command": f"touch {tmp_path / 'shell-created'} && sleep 0.2"
    }
    assert _attempt_arguments("read", state) == {"filePath": str(tmp_path / "read-sentinel")}
    assert _attempt_arguments("edit", state) == {
        "filePath": str(tmp_path / "edit-sentinel"),
        "oldString": "seed",
        "newString": "changed",
    }
    assert _attempt_arguments("subagent", state)["prompt"] == (
        f"Create {tmp_path / 'subagent-created'}"
    )
    assert _attempt_arguments("browser", state) == {
        "url": "http://127.0.0.1:43123/synthetic-boundary"
    }
    assert _attempt_arguments("signal-ledger_deployment_publish", state) == {}


def test_boundary_receipt_passes_only_when_every_runtime_guard_is_observed() -> None:
    checks = _evaluate(
        advertised_names={"signal-ledger_workspace_summary"},
    )

    assert all(checks.values())


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("provider_requested_unadvertised_tool", False),
        ("native_denial_or_rejection_observed", False),
        ("pending_permission_actions", ["execute"]),
        ("pending_permission_actions_after_cleanup", ["execute"]),
        ("mcp_tool_call_delta", 1),
        ("browser_fixture_request_delta", 1),
        ("new_child_process_count", 1),
        ("sentinel_marker_returned", True),
        ("edit_sentinel_unchanged", False),
        ("side_effect_path_exists", True),
        ("title_matches_explicit_session_title", False),
    ],
)
def test_boundary_receipt_fails_closed_on_any_runtime_side_effect(
    field: str, value: object
) -> None:
    observations = _passing_observations()
    observations[0][field] = value

    checks = _evaluate(observations=observations)

    assert checks["actual_runtime_denials_without_side_effects"] is False


def test_boundary_receipt_rejects_advertised_dangerous_tools_and_fallbacks() -> None:
    advertised = _evaluate(advertised_names={"execute"})
    secondary_model = _passing_auxiliary()
    secondary_model["all_provider_calls_used_selected_alias"] = False
    fallback = _evaluate(auxiliary=secondary_model)
    compaction = _passing_auxiliary()
    compaction["compaction_auto_disabled"] = False

    assert advertised["dangerous_tools_not_advertised"] is False
    assert fallback["secondary_model_provider_and_paid_fallback_blocked"] is False
    assert _evaluate(auxiliary=compaction)["automatic_compaction_disabled"] is False


def test_boundary_receipt_requires_the_complete_ordered_attempt_matrix() -> None:
    observations = _passing_observations()[:-1]

    checks = _evaluate(observations=observations)

    assert checks["all_dangerous_requests_attempted"] is False
    assert checks["actual_runtime_denials_without_side_effects"] is False


def test_permission_inspection_error_cannot_be_counted_as_no_pending_actions() -> None:
    class _UnavailablePermissions:
        def get(self, *_args: object, **_kwargs: object) -> object:
            return type("Response", (), {"status_code": 503})()

    with pytest.raises(_ProbeFailure) as failure:
        _wait_permissions(_UnavailablePermissions(), "synthetic-session", {})  # type: ignore[arg-type]

    assert failure.value.code == "native_permission_inspection_failed"


def test_structural_diagnostics_preserve_tool_rejection_without_raw_content() -> None:
    state = _RuntimeState()
    state.attempt_call_ids["execute"] = "call-synthetic"
    state.sentinel_marker = "private-synthetic-sentinel"
    provider_shapes = _provider_message_shapes(
        [
            {
                "role": "assistant",
                "tool_calls": [
                    {
                        "id": "call-synthetic",
                        "function": {"name": "execute", "arguments": "private args"},
                    }
                ],
            },
            {
                "role": "tool",
                "name": "execute",
                "tool_call_id": "call-synthetic",
                "content": "Tool not found: private-synthetic-sentinel",
            },
        ],
        state,
    )
    native_shapes = _native_message_shapes(
        {
            "data": [
                {
                    "info": {"role": "assistant", "finish": "tool_calls", "outcome": "failed"},
                    "parts": [
                        {
                            "type": "tool",
                            "name": "execute",
                            "state": {
                                "status": "denied",
                                "error": {
                                    "name": "PermissionDeniedError",
                                    "code": "permission_denied",
                                    "message": "private-synthetic-sentinel",
                                },
                            },
                        }
                    ],
                }
            ]
        }
    )

    rendered = repr((provider_shapes, native_shapes))
    assert "Tool not found" not in rendered
    assert "private args" not in rendered
    assert state.sentinel_marker not in rendered
    assert provider_shapes[1]["matching_forced_call"] is True
    assert provider_shapes[1]["content_signal"] == "tool_not_found"
    assert native_shapes["messages"][0]["tool_parts"][0]["status"] == "denied"
    assert native_shapes["messages"][0]["tool_parts"][0]["error_code"] == "permission_denied"


def test_native_flat_message_content_keeps_exact_failed_tool_outcome() -> None:
    parts, contains_sentinel = _tool_parts(
        {
            "data": [
                {
                    "content": [
                        {
                            "type": "tool",
                            "name": "execute",
                            "state": {"status": "error", "error": "Tool not found"},
                        }
                    ]
                }
            ]
        }
    )

    assert parts == [
        {
            "name": "execute",
            "status": "error",
            "error_name": None,
            "output_bytes": 0,
            "output_sha256": None,
        }
    ]
    assert contains_sentinel is False


@pytest.mark.skipif(
    os.environ.get("RUN_NATIVE_ASSISTANT_BOUNDARY_PROBE") != "1",
    reason="set RUN_NATIVE_ASSISTANT_BOUNDARY_PROBE=1 to start pinned OpenCode V2.0.7",
)
def test_opt_in_native_boundary_probe_passes() -> None:
    from tests.native_assistant_boundary_probe import _run_probe

    result = _run_probe()

    assert result["binary_version"] == "opencode v2.0.7"
    assert result["probe_pass"] is True
