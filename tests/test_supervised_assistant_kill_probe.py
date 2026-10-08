"""Unit tests for the opt-in same-container assistant kill acceptance probe."""

from __future__ import annotations

import io
import json
import os
import re
from pathlib import Path

import pytest

from tests import supervised_assistant_kill_probe as kill_probe
from tests import supervised_assistant_probe as supervised


def _candidate(
    *,
    container: str = "assistant-r120-candidate-012345abcdef",
    volume: str = "stock-probs-assistant-r120-012345abcdef",
    network_name: str | None = "stock-probs-assistant-r120-012345abcdef-candidate-network",
    network_id: str | None = "c" * 64,
    candidate_revision: str | None = None,
) -> supervised.Candidate:
    """Return the exact synthetic candidate metadata shape expected by the probe."""

    return supervised.Candidate(
        container=container,
        container_id="a" * 64,
        image_id="sha256:" + "b" * 64,
        data_volume=volume,
        base_url="http://127.0.0.1:49152",
        host_port=49152,
        host_pid=12345,
        cgroup=Path("/sys/fs/cgroup/synthetic-candidate"),
        network_name=network_name,
        network_id=network_id,
        candidate_revision=candidate_revision,
    )


def _checkpoint(**updates: object) -> dict[str, object]:
    """Build the closed active-search checkpoint with synthetic values only."""

    result: dict[str, object] = {
        "mode": "attach-existing-app",
        "phase": "active_search_wait",
        "origin": kill_probe.PUBLIC_ORIGIN,
        "owner_index": 1,
        "turn_status": "running",
        "search_preview_pending": True,
        "workspace_summary_digest_matches": True,
        "search_query_sha256": kill_probe._expected_search_query_sha256(),
    }
    result.update(updates)
    return result


def test_candidate_scope_rejects_unsafe_metadata_before_docker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An arbitrary container name cannot reach the metadata inspection commands."""

    calls: list[list[str]] = []
    monkeypatch.setattr(supervised, "_command", lambda args, **_kwargs: calls.append(args) or "")

    with pytest.raises(kill_probe.ProbeError, match="dedicated R-ASTRA-120 names"):
        kill_probe.run_probe(
            "production-ledger",
            "sha256:" + "b" * 64,
            "0" * 64,
            "stock-probs-assistant-r120-000000000000",
        )

    assert calls == []


@pytest.mark.parametrize("candidate_revision", ["A" * 40, "a" * 39, "a" * 41, "x" * 40])
def test_kill_probe_rejects_malformed_candidate_revision_before_docker(
    monkeypatch: pytest.MonkeyPatch,
    candidate_revision: str,
) -> None:
    calls: list[list[str]] = []
    monkeypatch.setattr(supervised, "_command", lambda args, **_kwargs: calls.append(args) or "")

    with pytest.raises(kill_probe.ProbeError, match="exact lowercase commit SHA"):
        kill_probe.run_probe(
            "assistant-r120-candidate-012345abcdef",
            "sha256:" + "b" * 64,
            "0" * 64,
            "stock-probs-assistant-r120-012345abcdef",
            candidate_revision,
        )

    assert calls == []


def test_kill_probe_preserves_candidate_revision_through_seed_refresh(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidate_revision = "a" * 40
    candidate = _candidate(candidate_revision=candidate_revision)
    context_sha256 = "012345abcdef" + "0" * 52
    inspect_revisions: list[str | None] = []

    def inspect(
        _container: str,
        _image_id: str,
        _context_sha256: str,
        _volume: str,
        expected_revision: str | None = None,
    ) -> supervised.Candidate:
        inspect_revisions.append(expected_revision)
        return candidate

    monkeypatch.setattr(supervised, "_candidate_container", inspect)
    monkeypatch.setattr(
        kill_probe,
        "_sample_resource_state",
        lambda _candidate: {
            "memory_peak": 1,
            "pids_current": 1,
            "memory_events_oom": 0,
            "memory_events_oom_kill": 0,
        },
    )
    monkeypatch.setattr(
        supervised,
        "_health",
        lambda _candidate: {"assistant": {"status": "ready", "enabled": True}},
    )

    def stop_after_refresh(_candidate: supervised.Candidate) -> list[dict[str, str]]:
        raise kill_probe.ProbeError("stop after checked refresh")

    monkeypatch.setattr(supervised, "_seed_users", stop_after_refresh)

    with pytest.raises(kill_probe.ProbeError, match="stop after checked refresh"):
        kill_probe.run_probe(
            candidate.container,
            candidate.image_id,
            context_sha256,
            candidate.data_volume,
            candidate_revision,
        )

    assert inspect_revisions == [candidate_revision, candidate_revision]


def test_kill_refuses_wrong_candidate_shape_before_command(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The kill helper independently rejects a non-candidate container argument."""

    calls: list[list[str]] = []
    monkeypatch.setattr(supervised, "_command", lambda args, **_kwargs: calls.append(args) or "{}")

    with pytest.raises(kill_probe.ProbeError, match="fixed disposable scope"):
        kill_probe._run_kill(_candidate(container="signal-ledger", volume="signal-ledger-data"))

    assert calls == []


@pytest.mark.parametrize(
    "updates",
    [
        {"network_name": None},
        {"network_id": None},
        {"network_name": "bridge"},
        {"network_id": "not-a-full-network-id"},
    ],
)
def test_kill_requires_bound_candidate_network_before_command(
    monkeypatch: pytest.MonkeyPatch,
    updates: dict[str, object],
) -> None:
    """Legacy candidate fixtures cannot invoke a mutating kill without exact network identity."""

    calls: list[list[str]] = []
    monkeypatch.setattr(supervised, "_command", lambda args, **_kwargs: calls.append(args) or "{}")

    with pytest.raises(kill_probe.ProbeError, match="exact network identity"):
        kill_probe._run_kill(_candidate(**updates))

    assert calls == []


def test_kill_uses_fixed_nonroot_module_command_without_operational_arguments(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The command reaches only the app-owned CLI and has no caller-controlled arguments."""

    calls: list[tuple[list[str], float]] = []

    def command(args: list[str], *, timeout: float, input_text: str | None = None) -> str:
        assert input_text is None
        calls.append((args, timeout))
        return '{"status":"assistant_disabled"}'

    monkeypatch.setattr(supervised, "_command", command)

    result = kill_probe._run_kill(_candidate())

    assert result == {"status": "assistant_disabled", "uid": 10001, "gid": 10001}
    assert len(calls) == 1
    assert calls[0][0] == [
        "docker",
        "exec",
        "--user",
        "10001:10001",
        "a" * 64,
        "python",
        "-m",
        "stock_probs.cli",
        "assistant-kill",
    ]
    assert calls[0][1] == kill_probe.KILL_TIMEOUT_SECONDS


@pytest.mark.parametrize(
    "updates",
    [
        {"phase": "final"},
        {"owner_index": 0},
        {"turn_status": "completed"},
        {"search_preview_pending": False},
        {"workspace_summary_digest_matches": False},
        {"search_query_sha256": "0" * 64},
        {"cookie": "synthetic-session-material"},
    ],
)
def test_active_checkpoint_rejects_mismatch_or_open_projection(
    updates: dict[str, object],
) -> None:
    """Only the driver's exact running pending-search phase can authorize the kill test."""

    with pytest.raises(kill_probe.ProbeError, match="exact pending-search checkpoint"):
        kill_probe._validate_active_search_checkpoint(_checkpoint(**updates))


def test_active_checkpoint_projection_is_closed_and_contains_no_search_text() -> None:
    """The checkpoint receipt retains a query digest rather than native prompt content."""

    projection = kill_probe._validate_active_search_checkpoint(_checkpoint())

    assert set(projection) == {
        "phase",
        "owner_index",
        "turn_status",
        "search_preview_pending",
        "workspace_summary_digest_matches",
        "search_query_sha256",
    }
    assert projection["search_query_sha256"] == kill_probe._expected_search_query_sha256()
    assert "NASA Artemis" not in repr(projection)


def test_new_turn_reuses_catalog_model_and_active_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Post-kill denial uses the exact maintained-catalog model from the native turn."""

    monkeypatch.setattr(
        kill_probe.native_assistant_probe,
        "_reviewed_free_zen_model_id",
        lambda: "maintained/provider-model",
    )

    assert kill_probe._maintained_model_policy(
        {"model_id": "maintained/provider-model", "policy_version": "policy-current"}
    ) == ("maintained/provider-model", "policy-current")


@pytest.mark.parametrize(
    "turn",
    [
        {"model_id": "pinned/model", "policy_version": "policy-current"},
        {"model_id": "maintained/provider-model", "policy_version": "bad\nversion"},
        {"model_id": "maintained/provider-model", "policy_version": ""},
    ],
)
def test_new_turn_rejects_noncatalog_model_or_invalid_policy(
    monkeypatch: pytest.MonkeyPatch, turn: dict[str, object]
) -> None:
    """The denied call cannot invent a pinned model or malformed policy version."""

    monkeypatch.setattr(
        kill_probe.native_assistant_probe,
        "_reviewed_free_zen_model_id",
        lambda: "maintained/provider-model",
    )

    with pytest.raises(kill_probe.ProbeError, match="maintained catalog model policy"):
        kill_probe._maintained_model_policy(turn)


def test_owner_projection_is_fixed_owner_scoped_readonly_and_sanitized(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The post-kill database view is bounded, read-only, and carries only a digest outward."""

    candidate = _candidate()
    session_cookie = "synthetic-session-cookie-0123456789abcdef"
    row_counts = {table: 0 for table in kill_probe._OWNER_TABLE_QUERIES}
    value: dict[str, object] = {
        "conversation_id": "00000000-0000-0000-0000-000000000001",
        "context_route_matches": True,
        "turn_id": "00000000-0000-0000-0000-000000000002",
        "turn_status": "cancelled",
        "turn_error_code": "assistant_disabled",
        "model_id": "maintained/provider-model",
        "policy_version": "current-policy",
        "turn_context_version": "a" * 64,
        "preview_id": "00000000-0000-0000-0000-000000000003",
        "preview_status": "pending",
        "preview_context_version": "a" * 64,
        "search_query_sha256": kill_probe._expected_search_query_sha256(),
        "row_counts": row_counts,
        "saved_record_sha256": "c" * 64,
        "state_sha256": "b" * 64,
    }
    calls: list[tuple[supervised.Candidate, str, str, dict[str, object]]] = []

    def docker_exec(
        actual_candidate: supervised.Candidate,
        user: str,
        script: str,
        *,
        input_text: str | None = None,
        timeout: float,
    ) -> dict[str, object]:
        assert input_text is not None
        assert json.loads(input_text) == {"session_cookie": session_cookie}
        calls.append((actual_candidate, user, script, {"timeout": timeout}))
        return value

    monkeypatch.setattr(supervised, "_docker_exec_json", docker_exec)
    monkeypatch.setattr(
        kill_probe.native_assistant_probe,
        "_reviewed_free_zen_model_id",
        lambda: "maintained/provider-model",
    )

    projection = kill_probe._owner_state_snapshot(candidate, {"session_cookie": session_cookie})

    assert projection == value
    assert len(calls) == 1
    assert calls[0][0] == candidate
    assert calls[0][1] == "10001:10001"
    assert calls[0][3] == {"timeout": 5}
    script = calls[0][2]
    compile(script, "<owner-projection>", "exec")
    assert session_cookie not in script
    assert "?mode=ro" in script
    assert "PRAGMA query_only=ON" in script
    assert "connection.rollback()" in script
    assert "connection.commit()" not in script
    assert "context_route_matches" in script
    normalized_script = re.sub(r'["\s]+', " ", script)
    for table, query in kill_probe._OWNER_TABLE_QUERIES.items():
        assert table in script
        assert query in normalized_script
    assert "private tool content" not in repr(projection)
    assert session_cookie not in repr(projection)


@pytest.mark.parametrize(
    "updates",
    [
        {"context_route_matches": False},
        {"preview_status": "approved"},
        {"state_sha256": "not-a-digest"},
        {"row_counts": {"assistant_turns": 257}},
        {"turn_context_version": "b" * 64},
    ],
)
def test_owner_projection_fails_closed_on_malformed_or_unbounded_data(
    monkeypatch: pytest.MonkeyPatch, updates: dict[str, object]
) -> None:
    """A malformed terminal-state projection cannot be promoted to probe evidence."""

    row_counts = {table: 0 for table in kill_probe._OWNER_TABLE_QUERIES}
    value: dict[str, object] = {
        "conversation_id": "00000000-0000-0000-0000-000000000001",
        "context_route_matches": True,
        "turn_id": "00000000-0000-0000-0000-000000000002",
        "turn_status": "cancelled",
        "turn_error_code": "assistant_disabled",
        "model_id": "maintained/provider-model",
        "policy_version": "current-policy",
        "turn_context_version": "a" * 64,
        "preview_id": "00000000-0000-0000-0000-000000000003",
        "preview_status": "pending",
        "preview_context_version": "a" * 64,
        "search_query_sha256": kill_probe._expected_search_query_sha256(),
        "row_counts": row_counts,
        "saved_record_sha256": "c" * 64,
        "state_sha256": "b" * 64,
    }
    value.update(updates)
    monkeypatch.setattr(supervised, "_docker_exec_json", lambda *_args, **_kwargs: value)
    monkeypatch.setattr(
        kill_probe.native_assistant_probe,
        "_reviewed_free_zen_model_id",
        lambda: "maintained/provider-model",
    )

    with pytest.raises(kill_probe.ProbeError, match="projection"):
        kill_probe._owner_state_snapshot(
            _candidate(), {"session_cookie": "synthetic-session-cookie-0123456789abcdef"}
        )


def _surviving_process_snapshot() -> list[dict[str, object]]:
    """Return a synthetic app/supervisor process tree after workers have exited."""

    return [
        {
            "pid": 1,
            "role": "supervisor",
            "uid": 0,
            "gid": 0,
            "cap_eff": "00000000000000c0",
            "cap_prm": "00000000000000c0",
            "cap_bnd": "00000000000000c0",
            "no_new_privileges": "1",
        },
        {
            "pid": 12346,
            "role": "app_wrapper",
            "uid": 10001,
            "gid": 10001,
            "cap_eff": "0000000000000000",
            "cap_prm": "0000000000000000",
            "cap_bnd": "00000000000000c0",
            "no_new_privileges": "1",
        },
    ]


def test_kill_probe_validates_surviving_app_identity_profile_and_worker_exit() -> None:
    snapshot = _surviving_process_snapshot()

    result = kill_probe._verify_surviving_app_profile(
        snapshot, {"pid": 12346, "uid": 10001, "gid": 10001}
    )

    assert result["app_wrapper"] == {
        "pid": 12346,
        "uid": 10001,
        "gid": 10001,
        "cap_eff": "0000000000000000",
        "cap_prm": "0000000000000000",
        "no_new_privileges": "1",
    }
    assert result["supervisor"]["pid"] == 1


@pytest.mark.parametrize(
    "change",
    [
        "changed_app_pid",
        "wrong_app_gid",
        "app_capability",
        "app_permitted_capability",
        "app_privilege_escalation",
        "wrong_supervisor_capability",
        "wrong_supervisor_permitted_capability",
        "worker_survived",
        "duplicate_app",
    ],
)
def test_kill_probe_rejects_changed_or_unsafe_surviving_process_profile(change: str) -> None:
    snapshot = _surviving_process_snapshot()
    app = next(row for row in snapshot if row["role"] == "app_wrapper")
    supervisor = next(row for row in snapshot if row["role"] == "supervisor")
    expected = {"pid": 12346, "uid": 10001, "gid": 10001}
    if change == "changed_app_pid":
        app["pid"] = 12347
    elif change == "wrong_app_gid":
        app["gid"] = 10002
    elif change == "app_capability":
        app["cap_eff"] = "0000000000000001"
    elif change == "app_permitted_capability":
        app["cap_prm"] = "0000000000000001"
    elif change == "app_privilege_escalation":
        app["no_new_privileges"] = "0"
    elif change == "wrong_supervisor_capability":
        supervisor["cap_bnd"] = "0000000000000000"
    elif change == "wrong_supervisor_permitted_capability":
        supervisor["cap_prm"] = "0000000000000000"
    elif change == "worker_survived":
        snapshot.append({"pid": 12347, "role": "worker_wrapper"})
    else:
        snapshot.append(app.copy())

    with pytest.raises(kill_probe.ProbeError, match="after assistant kill"):
        kill_probe._verify_surviving_app_profile(snapshot, expected)


def test_saved_record_projection_reads_only_a_bounded_owner_digest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Seeded portfolio rows are compared by digest without exposing any holding fields."""

    session_cookie = "synthetic-session-cookie-0123456789abcdef"
    expected = {"saved_record_count": 2, "saved_record_sha256": "c" * 64}
    calls: list[tuple[str, str, str | None, float]] = []

    def docker_exec(
        _candidate: supervised.Candidate,
        user: str,
        script: str,
        *,
        input_text: str | None = None,
        timeout: float,
    ) -> dict[str, object]:
        calls.append((user, script, input_text, timeout))
        return expected

    monkeypatch.setattr(supervised, "_docker_exec_json", docker_exec)

    projection = kill_probe._saved_record_projection(
        _candidate(), {"session_cookie": session_cookie}
    )

    assert projection == expected
    assert len(calls) == 1
    assert calls[0][0] == "10001:10001"
    assert calls[0][2] is not None
    assert json.loads(calls[0][2]) == {"session_cookie": session_cookie}
    assert calls[0][3] == 5
    script = calls[0][1]
    compile(script, "<saved-record-projection>", "exec")
    assert session_cookie not in script
    assert "user_instrument_list_items WHERE owner_user_id = ?" in script
    assert "?mode=ro" in script
    assert "PRAGMA query_only=ON" in script
    assert "connection.rollback()" in script
    assert "connection.commit()" not in script
    assert "Synthetic probe holding" not in repr(projection)
    assert session_cookie not in repr(projection)


@pytest.mark.parametrize(
    "value",
    [
        {"saved_record_count": 257, "saved_record_sha256": "c" * 64},
        {"saved_record_count": 2, "saved_record_sha256": "invalid"},
        {"saved_record_count": 2, "saved_record_sha256": "c" * 64, "items": ["private"]},
    ],
)
def test_saved_record_projection_rejects_open_or_unbounded_receipts(
    monkeypatch: pytest.MonkeyPatch, value: dict[str, object]
) -> None:
    """The saved-record contract cannot accept raw or over-limit projection data."""

    monkeypatch.setattr(supervised, "_docker_exec_json", lambda *_args, **_kwargs: value)

    with pytest.raises(kill_probe.ProbeError, match="saved-record projection"):
        kill_probe._saved_record_projection(
            _candidate(), {"session_cookie": "synthetic-session-cookie-0123456789abcdef"}
        )


@pytest.mark.parametrize(
    ("status", "payload"),
    [
        (200, {"error": {"code": "assistant_worker_unavailable"}}),
        (503, {"error": {"code": "unexpected_failure"}}),
        (503, {"error": {"code": "assistant_worker_unavailable"}, "content": "private"}),
    ],
)
def test_closed_assistant_api_projection_requires_exact_disabled_response(
    status: int, payload: dict[str, object]
) -> None:
    """Assistant API closure accepts only its fixed 503 code and emits no response content."""

    if status == 503 and kill_probe._error_code(payload) == "assistant_worker_unavailable":
        projection = kill_probe._require_disabled_error((status, payload), stage="test")
        assert projection == {
            "http_status": 503,
            "error_code": "assistant_worker_unavailable",
        }
        assert "private" not in repr(projection)
        return

    with pytest.raises(kill_probe.ProbeError, match="denied by the kill latch"):
        kill_probe._require_disabled_error((status, payload), stage="test")


def test_private_app_history_projection_stays_readable_and_discards_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Normal authenticated app history remains available after assistant disable."""

    candidate = _candidate()
    user = {"session_cookie": "synthetic-session-cookie-0123456789abcdef"}
    calls: list[tuple[supervised.Candidate, dict[str, str], str, str, str]] = []

    def request(
        actual_candidate: supervised.Candidate,
        actual_user: dict[str, str],
        method: str,
        path: str,
        **_kwargs: object,
    ) -> tuple[int, dict[str, object]]:
        calls.append((actual_candidate, actual_user, method, path, "not-retained"))
        return 200, {
            "items": [{"content": "private history content"}],
            "total": 1,
            "extra": "synthetic secret material",
        }

    monkeypatch.setattr(kill_probe, "_request", request)

    projection = kill_probe._private_history_projection(candidate, user)

    assert projection == {
        "http_status": 200,
        "visible_event_count": 1,
        "total_event_count": 1,
    }
    assert calls == [(candidate, user, "GET", "/api/v1/history", "not-retained")]
    assert "private history content" not in repr(projection)
    assert "synthetic secret material" not in repr(projection)


def test_driver_failure_projection_discards_secrets_and_tool_content() -> None:
    """The final child receipt is reduced to a closed fail-closed approval status."""

    projection = kill_probe._driver_failure_projection(
        {
            "mode": "attach-existing-app",
            "phase": "final",
            "attached_candidate_acceptance": False,
            "safe_error_code": "active_scan_ack_invalid",
            "failure_stage": "turn_poll_and_search_confirmation",
            "active_search_scan_acknowledged": False,
            "search_approved": False,
            "search_approval_count": 0,
            "session_cookie": "synthetic-cookie-value",
            "answer": "private tool content",
            "argv": ["secret-like-argument"],
        }
    )

    assert projection == {
        "phase": "final",
        "active_search_scan_acknowledged": False,
        "search_approved": False,
        "search_approval_count": 0,
        "safe_error_code": "active_scan_ack_invalid",
    }
    assert "synthetic-cookie-value" not in repr(projection)
    assert "private tool content" not in repr(projection)
    assert "secret-like-argument" not in repr(projection)


@pytest.mark.parametrize(
    "updates",
    [
        {"attached_candidate_acceptance": True},
        {"safe_error_code": "unexpected_failure"},
        {"search_approved": True},
        {"search_approval_count": 1},
        {"active_search_scan_acknowledged": True},
    ],
)
def test_driver_terminal_projection_rejects_approval_or_wrong_failure(
    updates: dict[str, object],
) -> None:
    """A native turn cannot pass the kill probe after reaching or approving its search."""

    value: dict[str, object] = {
        "mode": "attach-existing-app",
        "phase": "final",
        "attached_candidate_acceptance": False,
        "safe_error_code": "active_scan_ack_invalid",
        "failure_stage": "turn_poll_and_search_confirmation",
        "active_search_scan_acknowledged": False,
        "search_approved": False,
        "search_approval_count": 0,
    }
    value.update(updates)

    with pytest.raises(kill_probe.ProbeError, match="without approving"):
        kill_probe._driver_failure_projection(value)


def test_native_driver_failure_cleans_up_child_process(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Malformed checkpoint output terminates and reaps the bounded native child."""

    read_fd, write_fd = os.pipe()
    os.write(write_fd, b"not-json\n")
    os.close(write_fd)

    class Child:
        def __init__(self) -> None:
            self.stdin = io.BytesIO()
            self.stdout = os.fdopen(read_fd, "rb", buffering=0)
            self.stderr = None
            self.returncode: int | None = None
            self.terminated = False
            self.waited = False

        def poll(self) -> int | None:
            return self.returncode

        def terminate(self) -> None:
            self.terminated = True
            self.returncode = -15

        def kill(self) -> None:
            self.returncode = -9

        def wait(self, timeout: float | None = None) -> int:
            del timeout
            self.waited = True
            return self.returncode or 0

    child = Child()
    monkeypatch.setattr(kill_probe.subprocess, "Popen", lambda *_args, **_kwargs: child)
    monkeypatch.setattr(
        supervised,
        "_read_resources",
        lambda _candidate: {
            "memory_current": 1,
            "memory_peak": 1,
            "pids_current": 1,
            "cpu_usage_usec": 1,
            "memory_events_high": 0,
            "memory_events_max": 0,
            "memory_events_oom": 0,
            "memory_events_oom_kill": 0,
        },
    )

    with pytest.raises(kill_probe.ProbeError, match="checkpoint was malformed"):
        kill_probe._start_native_driver(
            _candidate(),
            [
                {"session_cookie": "a" * 32, "csrf_cookie": "b" * 32},
                {"session_cookie": "c" * 32, "csrf_cookie": "d" * 32},
            ],
        )

    assert child.terminated is True
    assert child.waited is True
    assert child.returncode == -15


def test_candidate_projection_does_not_include_raw_command_arguments() -> None:
    """Public receipts identify the exact candidate without retaining an argv transcript."""

    candidate = _candidate()

    assert kill_probe._candidate_is_scoped(candidate) is True
    receipt = {
        "container": candidate.container,
        "container_id": candidate.container_id,
        "image_id": candidate.image_id,
        "data_volume": candidate.data_volume,
        "source_context_sha256": "0" * 64,
    }
    assert "argv" not in receipt
    assert "session_cookie" not in receipt
    assert re.fullmatch(r"sha256:[0-9a-f]{64}", receipt["image_id"])


def test_kill_probe_cli_passes_candidate_revision_to_run_probe(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    candidate_revision = "a" * 40
    calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def run_probe(*args: object, **kwargs: object) -> dict[str, object]:
        calls.append((args, kwargs))
        return {"status": "pass"}

    monkeypatch.setattr(kill_probe, "run_probe", run_probe)

    assert (
        kill_probe.main(
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


def test_cli_mode_invocation_is_the_valid_module_entrypoint() -> None:
    """The project package has no __main__; its CLI module is the runnable Python entry point."""

    assert (kill_probe.ROOT / "src/stock_probs/__main__.py").exists() is False
    source = (kill_probe.ROOT / "src/stock_probs/cli.py").read_text(encoding="utf-8")
    assert 'if __name__ == "__main__":' in source
    assert 'stock-probs = "stock_probs.cli:main"' in (kill_probe.ROOT / "pyproject.toml").read_text(
        encoding="utf-8"
    )
