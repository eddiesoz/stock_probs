from __future__ import annotations

import ast
import builtins
import hashlib
import http.client
import io
import json
import os
import runpy
import sqlite3
import subprocess
import sys
from datetime import UTC, datetime
from importlib.resources import files
from pathlib import Path
from subprocess import CompletedProcess

import httpx
import pytest
from fastapi.testclient import TestClient

from scripts import rehearse_schema13 as rehearsal
from stock_probs.api import create_app
from stock_probs.auth import CSRF_COOKIE_NAME
from stock_probs.backup import BackupError, BackupManager
from stock_probs.config import Settings
from stock_probs.provider import FixtureProvider
from stock_probs.repository import Repository

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def _make_source_tree(root: Path) -> tuple[Path, Path]:
    root.mkdir(parents=True)
    for name in ("Dockerfile", ".dockerignore", "pyproject.toml", "requirements.lock"):
        (root / name).write_text(f"fixed {name}\n", encoding="utf-8")
    (root / "frontend").mkdir()
    (root / "src/stock_probs").mkdir(parents=True)
    (root / "frontend/index.html").write_text("<!doctype html>", encoding="utf-8")
    (root / "src/stock_probs/api.py").write_text("API = True\n", encoding="utf-8")
    patch_tools = root / "tools/opencode-v2-security-patch"
    patch_tools.mkdir(parents=True)
    for name in rehearsal._NATIVE_PATCH_FILES:
        (patch_tools / name).write_text(f"pinned patch input: {name}\n", encoding="utf-8")
    return root / "frontend", root / "src/stock_probs"


def test_local_command_failures_name_only_a_safe_stage(monkeypatch: pytest.MonkeyPatch) -> None:
    def failed_run(command: list[str], **_kwargs: object) -> CompletedProcess[str]:
        return CompletedProcess(command, 2, stdout="synthetic credential output", stderr="private")

    monkeypatch.setattr(rehearsal.subprocess, "run", failed_run)
    with pytest.raises(rehearsal.RehearsalError) as captured:
        rehearsal._run(
            ["docker", "exec", "sensitive-container-id", "--secret=must-not-appear"],
            env={},
        )
    assert str(captured.value) == "local_command_failed:docker_exec:exit_2"
    assert "sensitive" not in str(captured.value)
    assert "credential" not in str(captured.value)


def test_local_command_stage_override_is_validated_and_reports_cli_phase(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def failed_run(command: list[str], **_kwargs: object) -> CompletedProcess[str]:
        return CompletedProcess(command, 2, stdout="", stderr="")

    monkeypatch.setattr(rehearsal.subprocess, "run", failed_run)
    with pytest.raises(rehearsal.RehearsalError, match="schema12_cli_migrate:exit_2"):
        rehearsal._run(
            ["docker", "run", "synthetic-image", "migrate"],
            env={},
            diagnostic_stage="schema12_cli_migrate",
        )


@pytest.mark.parametrize(
    ("stage", "expected"),
    [
        ("historical_backup_verify", "local_command_timeout:historical_backup_verify:after_7s"),
        ("candidate_http_verify", "local_command_timeout:candidate_http_verify:after_7s"),
        ("process_identity", "local_command_timeout:process_identity:after_7s"),
        ("recovery_http_verify", "local_command_timeout:recovery_http_verify:after_7s"),
    ],
)
def test_local_timeouts_report_fixed_phase_without_command_output(
    monkeypatch: pytest.MonkeyPatch, stage: str, expected: str
) -> None:
    def timed_out(command: list[str], **_kwargs: object) -> CompletedProcess[str]:
        raise subprocess.TimeoutExpired(command, timeout=7, output="synthetic private output")

    monkeypatch.setattr(rehearsal.subprocess, "run", timed_out)
    with pytest.raises(rehearsal.RehearsalError) as captured:
        rehearsal._run(
            ["docker", "exec", "synthetic-container", "private-argument"],
            env={},
            timeout=7,
            diagnostic_stage=stage,
        )
    assert str(captured.value) == expected
    assert "private" not in str(captured.value)


def test_wait_ready_accepts_exact_readiness_after_original_20_second_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = {"seconds": 0.0}
    probe_attempts = 0
    sleep_durations: list[float] = []
    readiness = {
        "schema_version": 13,
        "assistant": {"enabled": False, "status": "disabled"},
    }

    def advance_clock(seconds: float) -> None:
        sleep_durations.append(seconds)
        clock["seconds"] += seconds

    def fake_run(command: list[str], **kwargs: object) -> CompletedProcess[str]:
        nonlocal probe_attempts
        assert kwargs["timeout"] == 10
        assert kwargs["check"] is False
        if command[1] == "inspect":
            assert kwargs["diagnostic_stage"] == "candidate_http_verify"
            return CompletedProcess(command, 0, stdout="true\n", stderr="")
        if command[1] == "exec":
            probe_attempts += 1
            assert kwargs["diagnostic_stage"] == "readiness_exec"
            if clock["seconds"] < 20.5:
                return CompletedProcess(command, 1, stdout="", stderr="")
            return CompletedProcess(
                command,
                0,
                stdout=json.dumps(readiness),
                stderr="",
            )
        raise AssertionError("unexpected readiness command")

    monkeypatch.setattr(rehearsal.time, "monotonic", lambda: clock["seconds"])
    monkeypatch.setattr(rehearsal.time, "sleep", advance_clock)
    monkeypatch.setattr(rehearsal, "_run", fake_run)

    assert (
        rehearsal._wait_ready(
            "a" * 64,
            "stock-probs:synthetic",
            {},
            diagnostic_stage="candidate_http_verify",
        )
        == readiness
    )
    assert clock["seconds"] == 20.5
    assert probe_attempts == 42
    assert sleep_durations == [0.5] * 41


def test_local_command_launch_failure_is_distinct_from_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def launch_failed(command: list[str], **_kwargs: object) -> CompletedProcess[str]:
        raise FileNotFoundError("synthetic command details")

    monkeypatch.setattr(rehearsal.subprocess, "run", launch_failed)
    with pytest.raises(rehearsal.RehearsalError) as captured:
        rehearsal._run(["docker", "exec", "synthetic-container"], env={})
    assert str(captured.value) == "local_command_unavailable:docker_exec:os_error"
    assert "synthetic" not in str(captured.value)


@pytest.mark.parametrize(
    "capabilities",
    [
        ["SETUID", "SETGID"],
        ["CAP_SETUID", "CAP_SETGID"],
    ],
)
def test_recovery_profile_accepts_only_the_two_identity_drop_capabilities(
    capabilities: list[str],
) -> None:
    host_config = {
        "ReadonlyRootfs": True,
        "NetworkMode": "none",
        "Memory": rehearsal.IMAGE_MEMORY_BYTES,
        "NanoCpus": 1_000_000_000,
        "PidsLimit": rehearsal.IMAGE_PIDS,
        "CapDrop": ["ALL"],
        "CapAdd": capabilities,
        "SecurityOpt": ["no-new-privileges:true"],
    }
    assert rehearsal._recovery_profile_mismatch(host_config) is None


@pytest.mark.parametrize(
    ("capabilities", "expected"),
    [
        (["SETUID", "SETGID", "NET_ADMIN"], None),
        (["CAP_SETUID", "SETGID", "SYS_ADMIN"], None),
        (["SETUID", "SETUID"], None),
        (["SETUID", "CAP_SETGID", "SYS_ADMIN"], None),
        (["SETUID", "SETGID", "NET_ADMIN"], "CapAdd"),
    ],
)
def test_recovery_profile_rejects_extra_invalid_and_duplicate_capabilities(
    capabilities: list[str], expected: str | None
) -> None:
    if expected is None:
        assert rehearsal._normalized_capabilities(capabilities) is None
        return
    host_config = {
        "ReadonlyRootfs": True,
        "NetworkMode": "none",
        "Memory": rehearsal.IMAGE_MEMORY_BYTES,
        "NanoCpus": 1_000_000_000,
        "PidsLimit": rehearsal.IMAGE_PIDS,
        "CapDrop": ["ALL"],
        "CapAdd": capabilities,
        "SecurityOpt": ["no-new-privileges:true"],
    }
    assert rehearsal._recovery_profile_mismatch(host_config) == expected


def test_recovery_profile_diagnostic_names_only_the_first_fixed_field() -> None:
    host_config = {
        "ReadonlyRootfs": True,
        "NetworkMode": "bridge",
        "Memory": rehearsal.IMAGE_MEMORY_BYTES,
        "NanoCpus": 1_000_000_000,
        "PidsLimit": rehearsal.IMAGE_PIDS,
        "CapDrop": ["ALL"],
        "CapAdd": ["CAP_SETUID", "CAP_SETGID"],
        "SecurityOpt": ["no-new-privileges:true"],
    }
    assert rehearsal._recovery_profile_mismatch(host_config) == "NetworkMode"


def test_container_inspect_uses_only_the_fixed_profile_projection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    container = "c" * 64
    revision = "a" * 40
    host_config = {
        "ReadonlyRootfs": True,
        "NetworkMode": "none",
        "Memory": rehearsal.IMAGE_MEMORY_BYTES,
        "NanoCpus": 1_000_000_000,
        "PidsLimit": rehearsal.IMAGE_PIDS,
        "CapDrop": ["ALL"],
        "CapAdd": ["SETUID", "SETGID"],
        "SecurityOpt": ["no-new-privileges:true"],
    }
    inspection = {
        "HostConfig": host_config,
        "Config": {"Labels": {"org.opencontainers.image.revision": revision}},
    }
    calls: list[list[str]] = []

    def inspect(command: list[str], **_kwargs: object) -> CompletedProcess[str]:
        calls.append(command)
        return CompletedProcess(command, 0, stdout=json.dumps(inspection), stderr="")

    monkeypatch.setattr(rehearsal, "_run", inspect)

    result = rehearsal._container_inspect(container, {"PATH": "/synthetic"})

    assert result == inspection
    assert calls == [
        [
            "docker",
            "inspect",
            "--format",
            rehearsal._CONTAINER_PROFILE_INSPECT_FORMAT,
            container,
        ]
    ]
    assert ".Config.Env" not in rehearsal._CONTAINER_PROFILE_INSPECT_FORMAT
    assert "{{json .HostConfig}}" not in rehearsal._CONTAINER_PROFILE_INSPECT_FORMAT
    assert "{{json .Config}}" not in rehearsal._CONTAINER_PROFILE_INSPECT_FORMAT
    for field in (
        "ReadonlyRootfs",
        "NetworkMode",
        "Memory",
        "NanoCpus",
        "PidsLimit",
        "CapDrop",
        "CapAdd",
        "SecurityOpt",
    ):
        assert f".HostConfig.{field}" in rehearsal._CONTAINER_PROFILE_INSPECT_FORMAT
    assert 'index .Config.Labels "org.opencontainers.image.revision"' in (
        rehearsal._CONTAINER_PROFILE_INSPECT_FORMAT
    )


@pytest.mark.parametrize(
    "stdout",
    [
        "not-json",
        "[]",
        "{}",
        '{"HostConfig": [], "Config": {"Labels": {"org.opencontainers.image.revision": "a"}}}',
        '{"HostConfig": {}, "Config": {"Labels": []}}',
        '{"HostConfig": {}, "Config": {"Labels": {}}}',
    ],
)
def test_container_inspect_rejects_malformed_or_missing_projection_facts(
    monkeypatch: pytest.MonkeyPatch,
    stdout: str,
) -> None:
    def inspect(command: list[str], **_kwargs: object) -> CompletedProcess[str]:
        return CompletedProcess(command, 0, stdout=stdout, stderr="")

    monkeypatch.setattr(rehearsal, "_run", inspect)

    with pytest.raises(rehearsal.RehearsalError, match="inspection was invalid"):
        rehearsal._container_inspect("d" * 64, {})


@pytest.mark.parametrize(
    ("field", "expected"),
    [
        ("ReadonlyRootfs", "ReadonlyRootfs"),
        ("NetworkMode", "NetworkMode"),
        ("Memory", "Memory"),
        ("NanoCpus", "NanoCpus"),
        ("PidsLimit", "PidsLimit"),
        ("CapDrop", "CapDrop"),
        ("CapAdd", "CapAdd"),
        ("SecurityOpt", "SecurityOpt"),
    ],
)
def test_recovery_profile_rejects_each_missing_inspected_fact(
    field: str,
    expected: str,
) -> None:
    host_config: dict[str, object] = {
        "ReadonlyRootfs": True,
        "NetworkMode": "none",
        "Memory": rehearsal.IMAGE_MEMORY_BYTES,
        "NanoCpus": 1_000_000_000,
        "PidsLimit": rehearsal.IMAGE_PIDS,
        "CapDrop": ["ALL"],
        "CapAdd": ["SETUID", "SETGID"],
        "SecurityOpt": ["no-new-privileges:true"],
    }
    del host_config[field]

    assert rehearsal._recovery_profile_mismatch(host_config) == expected


def test_all_literal_docker_inspect_calls_use_cli_format_projection() -> None:
    source = Path(rehearsal.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    inspect_commands: list[tuple[int, list[str | None], ast.List]] = []

    for node in ast.walk(tree):
        if (
            not isinstance(node, ast.Call)
            or not isinstance(node.func, ast.Name)
            or node.func.id != "_run"
            or not node.args
            or not isinstance(node.args[0], ast.List)
        ):
            continue
        command = [
            item.value if isinstance(item, ast.Constant) and isinstance(item.value, str) else None
            for item in node.args[0].elts
        ]
        if command[:2] == ["docker", "inspect"] or command[:3] == [
            "docker",
            "image",
            "inspect",
        ]:
            inspect_commands.append((node.lineno, command, node.args[0]))

    assert any(command[:2] == ["docker", "inspect"] for _, command, _ in inspect_commands)
    assert any(command[:3] == ["docker", "image", "inspect"] for _, command, _ in inspect_commands)
    assert all("--format" in command for _, command, _ in inspect_commands)
    for _, command, expression in inspect_commands:
        template_index = command.index("--format") + 1
        template_expression = expression.elts[template_index]
        if isinstance(template_expression, ast.Constant) and isinstance(
            template_expression.value, str
        ):
            template = template_expression.value
        else:
            assert isinstance(template_expression, ast.Name)
            allowed_formats = {
                "_CONTAINER_PROFILE_INSPECT_FORMAT": rehearsal._CONTAINER_PROFILE_INSPECT_FORMAT,
                "_DEPLOYED_BASELINE_INSPECT_FORMAT": rehearsal._DEPLOYED_BASELINE_INSPECT_FORMAT,
            }
            assert template_expression.id in allowed_formats
            template = allowed_formats[template_expression.id]
        assert ".Config.Env" not in template
        assert "{{json .Config}}" not in template
        assert "{{json .HostConfig}}" not in template


def test_stop_container_requires_confirmation_before_volume_cleanup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[list[str]] = []
    container = "a" * 64

    def still_running(command: list[str], **_kwargs: object) -> CompletedProcess[str]:
        calls.append(command)
        if command[1] == "stop":
            return CompletedProcess(command, 0, stdout=container + "\n", stderr="")
        return CompletedProcess(command, 0, stdout="true\n", stderr="")

    monkeypatch.setattr(rehearsal, "_run", still_running)
    with pytest.raises(rehearsal.RehearsalError, match="container is still running"):
        rehearsal._stop_container(container, {})
    assert [command[1] for command in calls] == ["stop", "inspect"]


def test_stop_container_waits_for_docker_autoremove_before_volume_cleanup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    container = "b" * 64
    inspect_count = 0
    calls: list[str] = []

    def delayed_autoremove(command: list[str], **_kwargs: object) -> CompletedProcess[str]:
        nonlocal inspect_count
        calls.append(command[1])
        if command[1] == "stop":
            return CompletedProcess(command, 0, stdout=container + "\n", stderr="")
        if command[1] == "inspect":
            inspect_count += 1
            if inspect_count == 1:
                return CompletedProcess(command, 0, stdout="false\n", stderr="")
            return CompletedProcess(command, 1, stdout="", stderr="")
        if inspect_count == 1:
            return CompletedProcess(command, 0, stdout=container + "\n", stderr="")
        return CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(rehearsal, "_run", delayed_autoremove)
    monkeypatch.setattr(rehearsal.time, "sleep", lambda _seconds: None)
    rehearsal._stop_container(container, {})
    assert calls == ["stop", "inspect", "ps", "inspect", "ps"]


def test_remove_volume_requires_exact_synthetic_identity_and_no_container_references(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[list[str]] = []

    def remove_volume(command: list[str], **_kwargs: object) -> CompletedProcess[str]:
        calls.append(command)
        if command[1] == "ps":
            return CompletedProcess(command, 0, stdout="", stderr="")
        if command[1] == "volume" and command[2] == "rm":
            return CompletedProcess(
                command, 0, stdout="stock-probs-schema13-012345abcdef\n", stderr=""
            )
        if command[1] == "volume" and command[2] == "ls":
            return CompletedProcess(command, 0, stdout="", stderr="")
        raise AssertionError("unexpected Docker cleanup operation")

    monkeypatch.setattr(rehearsal, "_run", remove_volume)
    assert rehearsal._remove_disposable_volume("stock-probs-schema13-012345abcdef", {}) is None
    assert [command[1:3] for command in calls] == [
        ["ps", "--all"],
        ["volume", "rm"],
        ["volume", "ls"],
    ]


def test_remove_volume_retains_unknown_or_referenced_volumes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[list[str]] = []

    def referenced(command: list[str], **_kwargs: object) -> CompletedProcess[str]:
        calls.append(command)
        return CompletedProcess(command, 0, stdout="d" * 64 + "\n", stderr="")

    monkeypatch.setattr(rehearsal, "_run", referenced)
    assert (
        rehearsal._remove_disposable_volume("production-data-volume", {})
        == "volume_identity_invalid"
    )
    assert calls == []
    assert (
        rehearsal._remove_disposable_volume("stock-probs-schema13-012345abcdef", {})
        == "volume_retained_for_unverified_container"
    )
    assert len(calls) == 1


def test_failure_json_includes_only_closed_cleanup_codes(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def fail_with_cleanup(_repository_root: Path) -> dict[str, object]:
        raise rehearsal.RehearsalError(
            "candidate_data_verify:local_login_csrf_cookie",
            cleanup_unverified=("volume_removal",),
        )

    monkeypatch.setattr(sys, "argv", ["rehearse_schema13.py", "--overlay-manifest"])
    monkeypatch.setattr(rehearsal, "prepare_overlay_manifest", fail_with_cleanup)
    assert rehearsal.main() == 2
    output = json.loads(capsys.readouterr().err)
    assert output == {
        "status": "fail",
        "reason": "candidate_data_verify:local_login_csrf_cookie",
        "cleanup_unverified": ["volume_removal"],
    }


def test_synthetic_passwords_are_environment_values_not_docker_argv(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, object] = {}

    def fake_run(command: list[str], **kwargs: object) -> CompletedProcess[str]:
        captured["command"] = command
        captured["env"] = kwargs["env"]
        return CompletedProcess(command, 0, stdout="a" * 64, stderr="")

    monkeypatch.setattr(rehearsal, "_run", fake_run)
    secret_values = {
        "STOCK_PROBS_AUTH_SESSION_SECRET": "synthetic-session-secret-value",
        "STOCK_PROBS_BOOTSTRAP_PASSWORD": "synthetic-admin-password-value",
        "STOCK_PROBS_BOOTSTRAP_MEMBER_PASSWORD": "synthetic-member-password-value",
    }
    arguments = [
        "--env=STOCK_PROBS_AUTH_SESSION_SECRET",
        "--env=STOCK_PROBS_BOOTSTRAP_PASSWORD",
        "--env=STOCK_PROBS_BOOTSTRAP_MEMBER_PASSWORD",
    ]
    rehearsal._start_app(
        "sha256:" + "b" * 64,
        "synthetic-volume",
        arguments,
        tmp_path / "verifier.py",
        {"PATH": "/usr/bin:/bin"},
        secret_values,
        identity_drop=False,
    )
    command = captured["command"]
    environment = captured["env"]
    assert isinstance(command, list)
    assert isinstance(environment, dict)
    rendered = " ".join(command)
    for value in secret_values.values():
        assert value not in rendered
        assert value not in rehearsal.json.dumps(command)
    assert all(environment[key] == value for key, value in secret_values.items())


def test_generated_readiness_probe_exits_before_app_or_scientific_imports(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    class Response:
        status = 200

        def read(self, size: int) -> bytes:
            assert size == 16_385
            return json.dumps(
                {"status": "ready", "schema_version": 13, "assistant": {"enabled": False}}
            ).encode()

    class Connection:
        def __init__(self, host: str, port: int, *, timeout: float) -> None:
            assert (host, port, timeout) == ("127.0.0.1", 8000, 2.0)

        def request(self, method: str, path: str, *, headers: dict[str, str]) -> None:
            assert method == "GET"
            assert path == "/api/v1/readiness"
            assert headers == {"Host": "localhost"}

        def getresponse(self) -> Response:
            return Response()

        def close(self) -> None:
            pass

    source = rehearsal._verification_source()
    generated = tmp_path / "generated_rehearsal.py"
    generated.write_text(source, encoding="utf-8")
    imported_names: list[str] = []
    real_import = builtins.__import__

    def guarded_import(name: str, *args: object, **kwargs: object) -> object:
        imported_names.append(name)
        if name.startswith(("stock_probs", "numpy", "pandas", "scipy", "sklearn")):
            raise AssertionError(f"readiness probe imported heavy module {name}")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded_import)
    monkeypatch.setattr(http.client, "HTTPConnection", Connection)
    monkeypatch.setattr(sys, "argv", [str(generated), "probe"])
    with pytest.raises(SystemExit) as exited:
        runpy.run_path(str(generated), run_name="__main__")
    assert exited.value.code == 0
    assert not any(
        name.startswith(("stock_probs", "numpy", "pandas", "scipy", "sklearn"))
        for name in imported_names
    )
    assert json.loads(capsys.readouterr().out) == {
        "status": "ready",
        "schema_version": 13,
        "assistant": {"enabled": False},
    }


def test_generated_candidate_verifier_uses_real_local_login_csrf_cookie_contract(
    tmp_path: Path,
) -> None:
    source = rehearsal._verification_source()
    parsed = ast.parse(source)
    selected = [
        node
        for node in parsed.body
        if isinstance(node, ast.ClassDef | ast.FunctionDef)
        and node.name
        in {
            "VerificationFailure",
            "require",
            "_request_safely",
            "_response_payload",
            "_portfolio_items",
            "_login",
        }
    ]
    assert {node.name for node in selected} == {
        "VerificationFailure",
        "require",
        "_request_safely",
        "_response_payload",
        "_portfolio_items",
        "_login",
    }
    generated_module = ast.Module(body=selected, type_ignores=[])
    generated_namespace: dict[str, object] = {
        "httpx": httpx,
        "CSRF_COOKIE_NAME": CSRF_COOKIE_NAME,
    }
    exec(  # noqa: S102 - only the fixed AST-extracted verifier functions are executed.
        compile(generated_module, "generated-schema13-verifier", "exec"),
        generated_namespace,
    )

    settings = Settings(
        data_dir=tmp_path,
        database_path=tmp_path / "stock_probs.sqlite3",
        backup_dir=tmp_path / "backups",
        provider="fixture",
        environment="test",
        auth_mode="local",
        auth_session_secret="c" * 48,
        auth_public_origin="http://testserver",
        bootstrap_username="rehearsal-admin",
        bootstrap_password="test-only-rehearsal-password",  # noqa: S106
    )
    application = create_app(settings, FixtureProvider(), lambda: datetime(2026, 10, 4, tzinfo=UTC))
    with TestClient(application) as client:
        token = generated_namespace["_login"](
            client, "rehearsal-admin", "test-only-rehearsal-password"
        )
        assert token == client.cookies.get(CSRF_COOKIE_NAME)

    failure_type = generated_namespace["VerificationFailure"]
    request_safely = generated_namespace["_request_safely"]
    portfolio_items = generated_namespace["_portfolio_items"]

    def fail_request():
        raise httpx.ConnectError("must-not-cross-generated-diagnostic-boundary")

    with pytest.raises(failure_type, match="portfolio_read_status") as transport_failure:
        request_safely(fail_request, "portfolio_read_status")
    assert str(transport_failure.value) == "portfolio_read_status"

    class WrongStatus:
        status_code = 403

        def json(self):
            raise AssertionError("JSON must not be read for an unexpected status")

    with pytest.raises(failure_type, match="portfolio_read_status"):
        portfolio_items(WrongStatus(), step="portfolio_read_status")

    class WrongPayload:
        status_code = 200

        def json(self):
            return {"error": "shape changed"}

    with pytest.raises(failure_type, match="portfolio_read_payload"):
        portfolio_items(WrongPayload(), step="portfolio_read_payload")


def test_generated_candidate_owner_and_http_verification_runs_against_two_local_users(
    tmp_path: Path,
) -> None:
    source = rehearsal._verification_source()
    parsed = ast.parse(source)
    names = {
        "VerificationFailure",
        "_internal_failure",
        "require",
        "_request_safely",
        "_response_payload",
        "_portfolio_items",
        "repo",
        "_login",
        "_sign_in_pair",
        "_verify_http",
        "_check_assistant_owner_boundary",
    }
    selected = [
        node
        for node in parsed.body
        if isinstance(node, ast.ClassDef | ast.FunctionDef) and node.name in names
    ]
    assert {node.name for node in selected} == names
    generated_module = ast.Module(body=selected, type_ignores=[])

    settings = Settings(
        data_dir=tmp_path,
        database_path=tmp_path / "stock_probs.sqlite3",
        backup_dir=tmp_path / "backups",
        provider="fixture",
        environment="test",
        auth_mode="local",
        auth_session_secret="c" * 48,
        auth_public_origin="http://127.0.0.1:8000",
        bootstrap_username="rehearsal-admin",
        bootstrap_password="test-only-rehearsal-admin-password",  # noqa: S106
        bootstrap_member_username="rehearsal-member",
        bootstrap_member_password="test-only-rehearsal-member-password",  # noqa: S106
    )
    application = create_app(
        settings,
        FixtureProvider(),
        lambda: datetime(2026, 10, 4, 12, tzinfo=UTC),
    )
    with TestClient(application, base_url="http://127.0.0.1:8000"):
        auth_manager = application.state.auth
    repository = Repository(settings.database_path)
    repository.migrate()
    bootstrap_now = datetime(2026, 10, 4, 12, tzinfo=UTC)
    auth_manager.ensure_local_bootstrap(
        "rehearsal-admin", "test-only-rehearsal-admin-password", bootstrap_now
    )
    auth_manager.ensure_local_bootstrap(
        "rehearsal-member",
        "test-only-rehearsal-member-password",
        bootstrap_now,
        role="member",
    )

    class LocalClient:
        instances = []

        def __init__(self, *, base_url: str, timeout: float) -> None:
            assert base_url == "http://127.0.0.1:8000"
            assert timeout == 3.0
            self._client = TestClient(application, base_url=base_url)
            self._client.__enter__()
            self.cookies = self._client.cookies
            self.responses: list[tuple[str, int]] = []
            self.instances.append(self)

        def __enter__(self):
            return self

        def __exit__(self, *_args: object) -> None:
            self.close()

        def get(self, *args: object, **kwargs: object):
            response = self._client.get(*args, **kwargs)
            self.responses.append((str(args[0]), response.status_code))
            return response

        def post(self, *args: object, **kwargs: object):
            response = self._client.post(*args, **kwargs)
            self.responses.append((str(args[0]), response.status_code))
            return response

        def delete(self, *args: object, **kwargs: object):
            response = self._client.delete(*args, **kwargs)
            self.responses.append((str(args[0]), response.status_code))
            return response

        def close(self) -> None:
            self._client.__exit__(None, None, None)

    class HttpxFacade:
        Client = LocalClient
        HTTPError = httpx.HTTPError

    generated_namespace: dict[str, object] = {
        "httpx": HttpxFacade,
        "CSRF_COOKIE_NAME": CSRF_COOKIE_NAME,
        "BASE_URL": "http://127.0.0.1:8000",
        "ADMIN_NAME": "rehearsal-admin",
        "ADMIN_PASSWORD": "test-only-rehearsal-admin-password",
        "MEMBER_NAME": "rehearsal-member",
        "MEMBER_PASSWORD": "test-only-rehearsal-member-password",
        "datetime": datetime,
        "UTC": UTC,
        "hashlib": hashlib,
        "sqlite3": sqlite3,
        "Repository": Repository,
        "Settings": Settings,
        "AssistantStorage": __import__(
            "stock_probs.assistant.storage", fromlist=["AssistantStorage"]
        ).AssistantStorage,
        "AssistantStorageNotFound": __import__(
            "stock_probs.assistant.storage", fromlist=["AssistantStorageNotFound"]
        ).AssistantStorageNotFound,
        "BackupManager": BackupManager,
        "_check_deadline": lambda: None,
        "_run_with_deadline": lambda operation: (operation(), None)[0],
    }
    exec(  # noqa: S102 - only fixed verifier AST nodes execute against disposable local data.
        compile(generated_module, "generated-schema13-owner-verifier", "exec"),
        generated_namespace,
    )
    generated_namespace["repo"] = lambda: repository

    owner_check = generated_namespace["_check_assistant_owner_boundary"]
    verify_http = generated_namespace["_verify_http"]
    assert owner_check() == {"assistant_owner_isolation": True}
    try:
        result = verify_http("candidate", None)
    except generated_namespace["VerificationFailure"] as exc:
        response_statuses = [
            response for client in LocalClient.instances for response in client.responses
        ]
        pytest.fail(f"{exc.step}: {response_statuses}")
    assert result == {
        "stage": "candidate",
        "assistant_tables": {"assistant_conversations": 1, "assistant_model_consents": 0},
        "schema_versions": list(range(1, 14)),
    }
    internal_failure = generated_namespace["_internal_failure"]
    assert internal_failure("assistant_owner_boundary", KeyError("synthetic private text")) == (
        "assistant_owner_boundary_internal:key_error"
    )
    assert internal_failure("candidate_http", RuntimeError("synthetic private text")) == (
        "candidate_http_internal:runtime_error"
    )


def test_schema12_backup_authentication_is_offline_after_schema13_and_cli_restore_stays_denied(
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "data"
    backup_dir = data_dir / "backups"
    backup_dir.mkdir(parents=True)
    database_path = data_dir / "stock_probs.sqlite3"
    repository = Repository(database_path)
    with repository.connect() as connection:
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute(
            "CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
        )
        connection.commit()

    migration_files = sorted(files("stock_probs.migrations").iterdir())
    for migration_file in migration_files:
        if not migration_file.name.endswith(".sql"):
            continue
        version = int(migration_file.name[:3])
        if version > 12:
            continue
        with repository.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            repository._execute_migration(connection, migration_file.read_text(encoding="utf-8"))
            connection.execute(
                "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                (version, f"2026-10-04T00:00:{version:02d}+00:00"),
            )
            connection.commit()

    backup_name = "pre-migration-v12-to-v13-test.spbackup"
    manager = BackupManager(repository, backup_dir)
    backup = manager.create(backup_name, schema_version=12)
    assert backup["schema_version"] == 12
    repository.migrate()
    with repository.connect() as connection:
        versions = [
            row[0]
            for row in connection.execute("SELECT version FROM schema_migrations ORDER BY version")
        ]
    assert versions == list(range(1, 14))

    historical = rehearsal._verify_historical_backup_without_promotion(
        manager, backup_name, expected_schema=12
    )
    assert historical == {
        "verified": True,
        "schema_version": 12,
        "integrity_verified": True,
    }
    with pytest.raises(BackupError, match="cannot be restored over active schema version 13"):
        manager.restore(backup_name, promote=False)

    environment = {
        "PATH": os.environ.get("PATH", os.defpath),
        "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src"),
        "STOCK_PROBS_DATA_DIR": str(data_dir),
        "STOCK_PROBS_ENV": "test",
        "STOCK_PROBS_PROVIDER": "fixture",
    }
    verifier_path = tmp_path / "schema13_rehearsal.py"
    verifier_path.write_text(rehearsal._verification_source(), encoding="utf-8")
    verifier = subprocess.run(  # noqa: S603 - fixed local Python executable and generated fixture.
        [sys.executable, str(verifier_path), "verify-historical-backup", backup_name],
        cwd=Path(__file__).resolve().parents[1],
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert verifier.returncode == 0, "generated rehearsal verifier failed safely"
    assert json.loads(verifier.stdout) == {
        "verified": True,
        "schema_version": 12,
        "integrity_verified": True,
    }

    cli = subprocess.run(  # noqa: S603 - fixed local module and synthetic backup basename.
        [sys.executable, "-m", "stock_probs.cli", "restore", backup_name],
        cwd=Path(__file__).resolve().parents[1],
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert cli.returncode == 2
    assert "cannot be restored over active schema version 13" in cli.stderr
    with sqlite3.connect(database_path) as connection:
        final_versions = [
            row[0]
            for row in connection.execute("SELECT version FROM schema_migrations ORDER BY version")
        ]
    assert final_versions == list(range(1, 14))


def test_source_copy_skips_env_without_opening_and_rejects_links_before_copy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source"
    frontend, _ = _make_source_tree(source)
    env_file = frontend / ".env.production"
    env_file.write_text("synthetic marker; never copy", encoding="utf-8")
    outside = tmp_path / "outside.pem"
    outside.write_text("synthetic private key marker; do not read", encoding="utf-8")
    (frontend / "linked.ts").symlink_to(outside)

    real_open = builtins.open

    def reject_sensitive_open(file: object, *args: object, **kwargs: object):  # type: ignore[no-untyped-def]
        if Path(file).resolve() in {env_file.resolve(), outside.resolve()}:
            raise AssertionError("the source copier opened an excluded or linked file")
        return real_open(file, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", reject_sensitive_open)
    with pytest.raises(rehearsal.RehearsalError, match="symbolic link"):
        rehearsal._copy_source_tree(source, tmp_path / "copy")
    assert not (tmp_path / "copy").exists()


def test_source_copy_omits_credential_named_and_generated_entries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source"
    frontend, package = _make_source_tree(source)
    (frontend / ".env").write_text("synthetic env marker", encoding="utf-8")
    (frontend / "access-token.json").write_text("synthetic token marker", encoding="utf-8")
    (frontend / "node_modules").mkdir()
    (frontend / "node_modules/package.json").write_text("{}", encoding="utf-8")
    (package / "private-key.pem").write_text("synthetic key marker", encoding="utf-8")
    destination = tmp_path / "copy"
    destination.mkdir()

    real_open = builtins.open

    def reject_sensitive_open(file: object, *args: object, **kwargs: object):  # type: ignore[no-untyped-def]
        name = Path(file).name
        if rehearsal._excluded_name(name):
            raise AssertionError("the source copier opened an excluded file")
        return real_open(file, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", reject_sensitive_open)
    rehearsal._copy_source_tree(source, destination)
    assert (destination / "frontend/index.html").is_file()
    assert (destination / "src/stock_probs/api.py").is_file()
    assert not (destination / "frontend/.env").exists()
    assert not (destination / "frontend/access-token.json").exists()
    assert not (destination / "frontend/node_modules").exists()
    assert not (destination / "src/stock_probs/private-key.pem").exists()


def test_candidate_context_excludes_nested_staged_output_without_opening_secret_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source"
    _make_source_tree(source)
    staged_next = source / "src/stock_probs/static/next"
    staged_next.mkdir(parents=True)
    staged_chunk = staged_next / "staged.js"
    staged_chunk.write_text("generated output", encoding="utf-8")
    tsbuildinfo = source / "frontend/tsconfig.tsbuildinfo"
    tsbuildinfo.write_text("synthetic generated cache", encoding="utf-8")
    frontend_routes = (
        "frontend/app/tools/layout.tsx",
        "frontend/app/tools/page.tsx",
        "frontend/tests/tools-page.test.tsx",
    )
    for relative in frontend_routes:
        route_file = source / relative
        route_file.parent.mkdir(parents=True, exist_ok=True)
        route_file.write_text("required frontend build input", encoding="utf-8")
    credentials = source / "src/stock_probs/auth.json"
    database = source / "src/stock_probs/cache.sqlite3-wal"
    backup = source / "frontend/predeploy.spbackup-20261004"
    ssh_key = source / "frontend/.ssh/id_ed25519"
    for item in (credentials, database, backup, ssh_key):
        item.parent.mkdir(parents=True, exist_ok=True)
        item.write_text("synthetic excluded marker", encoding="utf-8")

    real_builtin_open = builtins.open
    real_io_open = io.open
    real_os_open = os.open
    excluded = {
        item.resolve()
        for item in (staged_chunk, tsbuildinfo, credentials, database, backup, ssh_key)
    }

    def assert_not_excluded(file: object) -> None:
        try:
            path = Path(os.fspath(file)).resolve()
        except TypeError:
            return
        if path in excluded:
            raise AssertionError(
                "an excluded staged, credential, database, or backup file was opened"
            )

    def reject_builtin_open(file: object, *args: object, **kwargs: object):  # type: ignore[no-untyped-def]
        assert_not_excluded(file)
        return real_builtin_open(file, *args, **kwargs)

    def reject_io_open(file: object, *args: object, **kwargs: object):  # type: ignore[no-untyped-def]
        assert_not_excluded(file)
        return real_io_open(file, *args, **kwargs)

    def reject_os_open(file: object, *args: object, **kwargs: object):  # type: ignore[no-untyped-def]
        assert_not_excluded(file)
        return real_os_open(file, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", reject_builtin_open)
    monkeypatch.setattr(io, "open", reject_io_open)
    monkeypatch.setattr(os, "open", reject_os_open)
    real_excluded_relative_path = rehearsal._excluded_relative_path
    checked_paths: list[tuple[str, ...]] = []

    def record_filtered_path(parts: tuple[str, ...]) -> bool:
        checked_paths.append(parts)
        return real_excluded_relative_path(parts)

    monkeypatch.setattr(rehearsal, "_excluded_relative_path", record_filtered_path)
    first_context = tmp_path / "first-context"
    first_hash = rehearsal._candidate_context(source, first_context)
    with real_io_open(staged_chunk, "w", encoding="utf-8") as staged_file:
        staged_file.write("different stale generated output")
    with real_io_open(tsbuildinfo, "w", encoding="utf-8") as generated_file:
        generated_file.write("different generated cache")
    second_context = tmp_path / "second-context"
    second_hash = rehearsal._candidate_context(source, second_context)

    assert first_hash == second_hash
    assert (first_context / ".dockerignore").is_file()
    for relative in frontend_routes:
        assert (first_context / relative).is_file()
    assert ("frontend", "tests") in checked_paths
    assert ("frontend", "app", "tools") in checked_paths
    assert rehearsal._excluded_relative_path(("tests", "unit.py"))
    assert not rehearsal._excluded_relative_path(("frontend", "tests", "unit.py"))
    assert not rehearsal._excluded_relative_path(("frontend", "app", "tools", "page.tsx"))
    assert not (first_context / "src/stock_probs/static/next").exists()
    assert not (first_context / "frontend/tsconfig.tsbuildinfo").exists()
    assert rehearsal._excluded_relative_path(("frontend", "tsconfig.tsbuildinfo"))
    assert not (first_context / "src/stock_probs/auth.json").exists()
    assert not (first_context / "src/stock_probs/cache.sqlite3-wal").exists()
    assert not (first_context / "frontend/predeploy.spbackup-20261004").exists()
    assert not (first_context / "frontend/.ssh").exists()
    assert rehearsal._excluded_relative_path(("src", "stock_probs", "static", "next", "staged.js"))
    assert rehearsal._excluded_relative_path(("static", "next", "staged.js"))


def test_candidate_context_includes_only_fixed_native_webfetch_build_inputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source"
    _make_source_tree(source)
    tools_root = source / "tools"
    unrelated = tools_root / "assistant-help/credentials.json"
    unlisted = tools_root / "opencode-v2-security-patch/private-key.pem"
    outside_symlink_target = tmp_path / "outside-private-key"
    tools_root.joinpath("assistant-help").mkdir()
    unrelated.write_text("synthetic excluded data", encoding="utf-8")
    outside_symlink_target.write_text("synthetic private material", encoding="utf-8")
    unlisted.symlink_to(outside_symlink_target)

    real_builtin_open = builtins.open
    real_io_open = io.open
    real_os_open = os.open

    def reject_sensitive_open(file: object, *args: object, **kwargs: object):  # type: ignore[no-untyped-def]
        try:
            path = Path(os.fspath(file)).resolve()
        except TypeError:
            return real_builtin_open(file, *args, **kwargs)
        if path in {unrelated.resolve(), outside_symlink_target.resolve()}:
            raise AssertionError("the candidate filter opened an unrelated tool or credential file")
        return real_builtin_open(file, *args, **kwargs)

    def reject_io_open(file: object, *args: object, **kwargs: object):  # type: ignore[no-untyped-def]
        try:
            path = Path(os.fspath(file)).resolve()
        except TypeError:
            return real_io_open(file, *args, **kwargs)
        if path in {unrelated.resolve(), outside_symlink_target.resolve()}:
            raise AssertionError("the candidate filter opened an unrelated tool or credential file")
        return real_io_open(file, *args, **kwargs)

    def reject_os_open(file: object, *args: object, **kwargs: object):  # type: ignore[no-untyped-def]
        try:
            path = Path(os.fspath(file)).resolve()
        except TypeError:
            return real_os_open(file, *args, **kwargs)
        if path in {unrelated.resolve(), outside_symlink_target.resolve()}:
            raise AssertionError("the candidate filter opened an unrelated tool or credential file")
        return real_os_open(file, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", reject_sensitive_open)
    monkeypatch.setattr(io, "open", reject_io_open)
    monkeypatch.setattr(os, "open", reject_os_open)
    context = tmp_path / "candidate-context"
    rehearsal._candidate_context(source, context)

    copied_tools = context / "tools/opencode-v2-security-patch"
    assert {path.name for path in copied_tools.iterdir()} == set(rehearsal._NATIVE_PATCH_FILES)
    assert not (context / "tools/assistant-help").exists()
    assert not (copied_tools / "private-key.pem").exists()
    assert rehearsal._excluded_relative_path(("tools", "assistant-help", "index.html"))
    assert rehearsal._excluded_relative_path(
        ("tools", "opencode-v2-security-patch", "private-key.pem")
    )
    assert not rehearsal._excluded_relative_path(
        ("tools", "opencode-v2-security-patch", "build_native.py")
    )


def test_fixed_schema12_archive_is_the_observed_deployed_source_and_uses_safe_paths(
    tmp_path: Path,
) -> None:
    paths = rehearsal._fixed_base_source_paths(REPOSITORY_ROOT)
    assert {"Dockerfile", ".dockerignore", "pyproject.toml", "requirements.lock"}.issubset(paths)
    assert all(
        not any(rehearsal._excluded_name(part) for part in path.split("/")) for path in paths
    )

    base_context = tmp_path / "base"
    archive = rehearsal._extract_base_archive(REPOSITORY_ROOT, base_context)
    assert archive["revision"] == "da2764e8477698fa7d686be93a4711e35478e802"
    assert archive["source_context_sha256"] == rehearsal._tree_sha256(base_context)
    assert len(archive["archive_sha256"]) == 64
    assert (base_context / "Dockerfile").is_file()
    assert not (base_context / "src/stock_probs/assistant").exists()
    assert (
        (base_context / "src/stock_probs/repository.py")
        .read_text(encoding="utf-8")
        .startswith('"""SQLite migration')
    )


def test_recovery_overlay_has_fixed_file_hash_manifest_and_migration_identity(
    tmp_path: Path,
) -> None:
    base_context = tmp_path / "base"
    rehearsal._extract_base_archive(REPOSITORY_ROOT, base_context)
    overlay = rehearsal._apply_recovery_overlay(REPOSITORY_ROOT, base_context)

    expected_paths = {
        "Dockerfile",
        "src/stock_probs/api.py",
        "src/stock_probs/migrations/013_assistant_conversations.sql",
        "src/stock_probs/recovery_supervisor.py",
        "src/stock_probs/repository.py",
    }
    assert overlay["base_revision"] == rehearsal.BASE_SHA
    assert overlay["schema_version"] == 13
    assert set(overlay["files"]) == expected_paths
    assert overlay["overlay_sha256"] == rehearsal._sha256(
        rehearsal._canonical_json(
            {
                "base_revision": rehearsal.BASE_SHA,
                "schema_version": 13,
                "files": overlay["files"],
            }
        )
    )
    for relative, expected_hash in overlay["files"].items():
        assert hashlib.sha256((base_context / relative).read_bytes()).hexdigest() == expected_hash

    migration = base_context / "src/stock_probs/migrations/013_assistant_conversations.sql"
    assert hashlib.sha256(migration.read_bytes()).hexdigest() == rehearsal.MIGRATION_013_SHA256
    repository = (base_context / "src/stock_probs/repository.py").read_text(encoding="utf-8")
    assert "SCHEMA_VERSION = 13" in repository
    assert f'13: "{rehearsal.MIGRATION_013_SHA256}"' in repository
    api = (base_context / "src/stock_probs/api.py").read_text(encoding="utf-8")
    assert "assistant: AssistantReadinessResponse" in api
    assert '"assistant": {"enabled": False, "status": "disabled"}' in api
    assert '"assistant_model_consents"' in api
    supervisor = (base_context / "src/stock_probs/recovery_supervisor.py").read_text(
        encoding="utf-8"
    )
    compile(supervisor, "recovery_supervisor.py", "exec")
    assert "APP_UID = 10001" in supervisor
    assert "APP_GID = 10001" in supervisor
    assert "stock-probs" in supervisor
    assert "opencode" not in supervisor


def test_recovery_overlay_fails_closed_when_pinned_base_anchor_changes(tmp_path: Path) -> None:
    base_context = tmp_path / "base"
    rehearsal._extract_base_archive(REPOSITORY_ROOT, base_context)
    api_path = base_context / "src/stock_probs/api.py"
    api_path.write_text(
        api_path.read_text(encoding="utf-8").replace(
            "class ReadinessResponse", "class ReadinessSchemaChanged", 1
        ),
        encoding="utf-8",
    )

    with pytest.raises(rehearsal.RehearsalError, match="anchor changed"):
        rehearsal._apply_recovery_overlay(REPOSITORY_ROOT, base_context)


def test_recovery_image_run_profile_is_private_and_identity_drop_is_fixed() -> None:
    verifier = Path("rehearsal.py")
    recovery = rehearsal._image_run_args("volume", [], verifier, identity_drop=True)
    candidate = rehearsal._image_run_args("volume", [], verifier, identity_drop=False)

    assert "--network=none" in recovery and "--read-only" in recovery
    assert "--cap-drop=ALL" in recovery
    assert "--cap-add=SETUID" in recovery and "--cap-add=SETGID" in recovery
    assert "--user=0:0" in recovery
    assert "--user=10001:10001" in candidate
    assert not any(item.startswith("--cap-add=") for item in candidate)
    assert all(not item.startswith("-p") for item in recovery + candidate)
    assert "--memory" in recovery and str(768 * 1024 * 1024) in recovery
    assert "--cpus" in recovery and "1" in recovery
    assert "--pids-limit" in recovery and "128" in recovery
    app_tmpfs = "/tmp:rw,nosuid,nodev,noexec,size=64m,uid=10001,gid=10001,mode=0700"  # noqa: S108 - assert private mount mode
    worker_home = (
        "/run/assistant-worker-home:rw,nosuid,nodev,noexec,size=64m,uid=10002,gid=10002,mode=0700"
    )
    assert app_tmpfs in recovery and app_tmpfs in candidate
    assert worker_home in recovery and worker_home in candidate


def test_candidate_image_must_match_immutable_id_platform_and_source_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    image_id = "sha256:" + "a" * 64
    context_sha256 = "b" * 64
    expected_label = f"local-source-{context_sha256}"

    def inspect(command: list[str], **kwargs: object) -> CompletedProcess[str]:
        assert command[-1] == image_id
        return CompletedProcess(
            args=command,
            returncode=0,
            stdout=f"{image_id}|linux|amd64|{expected_label}\n",
            stderr="",
        )

    monkeypatch.setattr(rehearsal, "_run", inspect)
    assert rehearsal._verify_candidate_image(image_id, context_sha256, {}) == {
        "id": image_id,
        "architecture": "linux/amd64",
        "source_context_sha256": context_sha256,
        "revision_label": expected_label,
    }
    with pytest.raises(rehearsal.RehearsalError, match="immutable local image ID"):
        rehearsal._verify_candidate_image("stock-probs:latest", context_sha256, {})

    def wrong_platform(command: list[str], **kwargs: object) -> CompletedProcess[str]:
        return CompletedProcess(
            args=command,
            returncode=0,
            stdout=f"{image_id}|linux|arm64|{expected_label}\n",
            stderr="",
        )

    monkeypatch.setattr(rehearsal, "_run", wrong_platform)
    with pytest.raises(rehearsal.RehearsalError, match="does not match"):
        rehearsal._verify_candidate_image(image_id, context_sha256, {})


def test_recovery_metadata_keeps_production_image_identity_separate_from_local_build() -> None:
    assert rehearsal.DEPLOYED_BASELINE == {
        "source_revision": "da2764e8477698fa7d686be93a4711e35478e802",
        "image_id": "sha256:d3e21ae9de800f0151c1eba74fb3d16423e1171985c33ea03057acbfe2278ec1",
        "release_archive_sha256": (
            "669f840a3141b0fb95ae248b5ea0799733b9e5b5b81e224d4637571c24d8f640"
        ),
        "release_transport": "GitHub Release",
        "source": "root-provided observed deployment metadata",
    }


def test_local_pr_head_gate_requires_exact_sha_and_clean_tracked_and_untracked_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    expected_sha = "a" * 40
    repository = tmp_path / "repo"
    repository.mkdir()
    (repository / ".git").mkdir()
    commands: list[list[str]] = []

    def git_run(command: list[str], **kwargs: object) -> CompletedProcess[bytes]:
        commands.append(command)
        return CompletedProcess(command, 0, stdout=f"{expected_sha}\n".encode(), stderr=b"")

    class StatusProcess:
        def __init__(self, output: bytes) -> None:
            read_fd, write_fd = os.pipe()
            if output:
                os.write(write_fd, output)
            os.close(write_fd)
            self.stdout = os.fdopen(read_fd, "rb")
            self.terminated = False

        def wait(self, *, timeout: int) -> int:
            assert timeout in {1, rehearsal._BUILD_STOP_TIMEOUT_SECONDS}
            return 0

        def terminate(self) -> None:
            self.terminated = True

        def kill(self) -> None:
            self.terminated = True

    current_output = b""
    processes: list[StatusProcess] = []

    def git_popen(command: list[str], **kwargs: object) -> StatusProcess:
        commands.append(command)
        process = StatusProcess(current_output)
        processes.append(process)
        return process

    monkeypatch.setattr(rehearsal.subprocess, "run", git_run)
    monkeypatch.setattr(rehearsal.subprocess, "Popen", git_popen)
    rehearsal._verify_local_pr_head(repository, expected_sha)
    assert commands[0] == ["/usr/bin/git", "rev-parse", "--verify", "HEAD"]
    assert commands[1][-1] == "--untracked-files=all"
    assert processes[0].terminated is False

    current_output = b"?? untracked\0"
    with pytest.raises(rehearsal.RehearsalError, match="checkout is not clean"):
        rehearsal._verify_local_pr_head(repository, expected_sha)
    assert processes[1].terminated is True

    with pytest.raises(rehearsal.RehearsalError, match="exact commit SHA"):
        rehearsal._verify_local_pr_head(repository, "A" * 40)


def test_fixed_pr_verifier_uses_only_the_approved_api_endpoint_and_head(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository = tmp_path / "repo"
    scripts = repository / "scripts"
    scripts.mkdir(parents=True)
    verifier_bytes = (REPOSITORY_ROOT / "scripts/pr_rehearsal_bootstrap.py").read_bytes()
    (scripts / "pr_rehearsal_bootstrap.py").write_bytes(verifier_bytes)
    reviewed_sha = "b" * 40
    requests: list[tuple[str, str, dict[str, str]]] = []
    payload = {
        "state": "open",
        "base": {"ref": "main"},
        "head": {"sha": reviewed_sha, "repo": {"full_name": "eddiesoz/stock_probs"}},
    }

    class Response:
        status = 200

        def read(self, size: int) -> bytes:
            assert size == 64 * 1024 + 1
            return json.dumps(payload).encode()

    class Connection:
        def __init__(self, host: str, *, timeout: int) -> None:
            assert host == "api.github.com"
            assert timeout == 10

        def request(self, method: str, path: str, *, headers: dict[str, str]) -> None:
            requests.append((method, path, headers))

        def getresponse(self) -> Response:
            return Response()

        def close(self) -> None:
            pass

    monkeypatch.setattr(http.client, "HTTPSConnection", Connection)
    rehearsal._verify_reviewed_pr(repository, reviewed_sha)
    assert requests[0][0:2] == ("GET", "/repos/eddiesoz/stock_probs/pulls/1")

    payload["head"]["sha"] = "c" * 40
    with pytest.raises(rehearsal.RehearsalError, match="reviewed_pr_mismatch"):
        rehearsal._verify_reviewed_pr(repository, reviewed_sha)


def test_build_image_uses_fixed_amd64_argv_and_discards_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "docker-root"
    root.mkdir()
    context = tmp_path / "workspace/context"
    context.mkdir(parents=True)
    image_id = "sha256:" + "d" * 64
    tag = "stock-probs:pr-candidate-" + "a" * 12 + "-" + "b" * 12
    commands: list[list[str]] = []
    launch: dict[str, object] = {}

    def run(command: list[str], **kwargs: object) -> CompletedProcess[str]:
        commands.append(command)
        if command[1] == "info":
            return CompletedProcess(command, 0, stdout=f"{root}\n", stderr="")
        assert command[-1] == tag
        return CompletedProcess(command, 0, stdout=image_id + "\n", stderr="")

    class Process:
        pid = 42001

        def poll(self) -> int:
            return 0

        def wait(self, *, timeout: int) -> int:
            assert timeout == rehearsal._BUILD_TERM_GRACE_SECONDS
            return 0

    def spawn(command: list[str], **kwargs: object) -> Process:
        launch.update(kwargs)
        launch["command"] = command
        iidfile = Path(command[command.index("--iidfile") + 1])
        iidfile.write_text(image_id + "\n", encoding="ascii")
        return Process()

    monkeypatch.setattr(rehearsal, "_run", run)
    monkeypatch.setattr(rehearsal, "_build_free_bytes", lambda _path: 8 * 1024**3)
    monkeypatch.setattr(rehearsal.subprocess, "Popen", spawn)
    monkeypatch.setattr(
        rehearsal.os,
        "killpg",
        lambda _pgid, _signal: (_ for _ in ()).throw(ProcessLookupError()),
    )
    assert rehearsal._build_image(context, tag, "a" * 40, {}) == image_id
    command = launch["command"]
    assert command[:5] == [
        "docker",
        "build",
        "--pull=false",
        "--platform=linux/amd64",
        "--build-arg",
    ]
    assert command[5] == "REVISION=" + "a" * 40
    assert command[command.index("--tag") + 1] == tag
    assert launch["stdout"] is rehearsal.subprocess.DEVNULL
    assert launch["stderr"] is rehearsal.subprocess.DEVNULL
    assert launch["stdin"] is rehearsal.subprocess.DEVNULL
    assert launch["shell"] is False
    assert launch["start_new_session"] is True
    assert commands[0][0:3] == ["docker", "info", "--format"]


def test_deployed_baseline_verification_projects_only_fixed_image_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    image_id = str(rehearsal.DEPLOYED_BASELINE["image_id"])
    revision = str(rehearsal.DEPLOYED_BASELINE["source_revision"])
    tag = "ghcr.io/eddiesoz/stock_probs:deployed"
    command_calls: list[list[str]] = []

    def inspect(command: list[str], **_kwargs: object) -> CompletedProcess[str]:
        command_calls.append(command)
        return CompletedProcess(
            command,
            0,
            stdout=f"{image_id}|linux|amd64|{revision}|{json.dumps([tag])}\n",
            stderr="",
        )

    monkeypatch.setattr(rehearsal, "_run", inspect)

    verified = rehearsal._verify_deployed_baseline_image({"PATH": "/synthetic"})

    assert verified == {
        "id": image_id,
        "architecture": "linux/amd64",
        "revision_label": revision,
        "retained_tags": [tag],
    }
    assert command_calls == [
        [
            "docker",
            "image",
            "inspect",
            "--format",
            rehearsal._DEPLOYED_BASELINE_INSPECT_FORMAT,
            image_id,
        ]
    ]
    assert ".Config.Env" not in rehearsal._DEPLOYED_BASELINE_INSPECT_FORMAT
    assert ".Config.Labels" in rehearsal._DEPLOYED_BASELINE_INSPECT_FORMAT
    assert ".RepoTags" in rehearsal._DEPLOYED_BASELINE_INSPECT_FORMAT


@pytest.mark.parametrize(
    "stdout",
    [
        "sha256:" + "0" * 64 + "|linux|amd64|" + "a" * 40 + '|["fixed:tag"]',
        str(rehearsal.DEPLOYED_BASELINE["image_id"])
        + "|linux|arm64|"
        + str(rehearsal.DEPLOYED_BASELINE["source_revision"])
        + '|["fixed:tag"]',
        str(rehearsal.DEPLOYED_BASELINE["image_id"])
        + "|linux|amd64|"
        + "a" * 40
        + '|["fixed:tag"]',
        str(rehearsal.DEPLOYED_BASELINE["image_id"])
        + "|linux|amd64|"
        + str(rehearsal.DEPLOYED_BASELINE["source_revision"])
        + "|[]",
        str(rehearsal.DEPLOYED_BASELINE["image_id"])
        + "|linux|amd64|"
        + str(rehearsal.DEPLOYED_BASELINE["source_revision"])
        + "|null",
        str(rehearsal.DEPLOYED_BASELINE["image_id"])
        + "|linux|amd64|"
        + str(rehearsal.DEPLOYED_BASELINE["source_revision"])
        + '|["<none>:<none>"]',
        str(rehearsal.DEPLOYED_BASELINE["image_id"])
        + "|linux|amd64|"
        + str(rehearsal.DEPLOYED_BASELINE["source_revision"])
        + "|not-json",
    ],
)
def test_deployed_baseline_verification_fails_closed_on_invalid_metadata(
    monkeypatch: pytest.MonkeyPatch,
    stdout: str,
) -> None:
    def inspect(command: list[str], **_kwargs: object) -> CompletedProcess[str]:
        return CompletedProcess(command, 0, stdout=stdout, stderr="")

    monkeypatch.setattr(rehearsal, "_run", inspect)

    with pytest.raises(rehearsal.RehearsalError):
        rehearsal._verify_deployed_baseline_image({})


def test_deployed_baseline_verification_rejects_missing_image(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def missing(command: list[str], **_kwargs: object) -> CompletedProcess[str]:
        return CompletedProcess(command, 1, stdout="", stderr="")

    monkeypatch.setattr(rehearsal, "_run", missing)

    with pytest.raises(rehearsal.RehearsalError, match="image is unavailable"):
        rehearsal._verify_deployed_baseline_image({})


def test_schema12_base_defaults_to_local_build_and_preserves_provenance(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = tmp_path / "base-context"
    context.mkdir()
    image_id = "sha256:" + "a" * 64
    calls: list[tuple[Path, str, str]] = []

    def build(
        received_context: Path,
        tag: str,
        revision: str,
        _env: dict[str, str],
    ) -> str:
        calls.append((received_context, tag, revision))
        return image_id

    monkeypatch.setattr(rehearsal, "_build_image", build)
    monkeypatch.setattr(
        rehearsal,
        "_verify_deployed_baseline_image",
        lambda _env: (_ for _ in ()).throw(AssertionError("unexpected baseline reuse")),
    )

    selected_id, image_reference, provenance = rehearsal._prepare_schema12_base_image(
        context,
        "stock-probs:schema12-base-test",
        str(rehearsal.DEPLOYED_BASELINE["source_revision"]),
        {},
        use_deployed_baseline_image=False,
    )

    assert selected_id == image_id
    assert image_reference == "stock-probs:schema12-base-test"
    assert provenance["mode"] == "locally_rebuilt_from_verified_archive"
    assert "not asserted equal" in provenance["relationship_to_deployed_image"]
    assert calls == [
        (
            context,
            "stock-probs:schema12-base-test",
            str(rehearsal.DEPLOYED_BASELINE["source_revision"]),
        )
    ]


def test_schema12_base_reuses_only_verified_image_id_without_alias_or_build(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    image_id = str(rehearsal.DEPLOYED_BASELINE["image_id"])
    projected = {
        "id": image_id,
        "architecture": "linux/amd64",
        "revision_label": str(rehearsal.DEPLOYED_BASELINE["source_revision"]),
        "retained_tags": ["ghcr.io/eddiesoz/stock_probs:deployed"],
    }
    calls: list[str] = []

    def verify(_env: dict[str, str]) -> dict[str, object]:
        calls.append("verify")
        return projected

    monkeypatch.setattr(rehearsal, "_verify_deployed_baseline_image", verify)
    monkeypatch.setattr(
        rehearsal,
        "_build_image",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("unexpected build")),
    )

    selected_id, image_reference, provenance = rehearsal._prepare_schema12_base_image(
        Path("unused"),
        "stock-probs:schema12-base-test",
        str(rehearsal.DEPLOYED_BASELINE["source_revision"]),
        {},
        use_deployed_baseline_image=True,
    )

    assert selected_id == image_id
    assert image_reference == image_id
    assert provenance == {
        "mode": "reused_exact_deployed_image",
        "verified_projected_metadata": projected,
        "relationship_to_deployed_image": "exact immutable deployed image ID reused",
    }
    assert calls == ["verify"]


def test_generated_image_tag_cleanup_disables_ancestor_pruning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tag = "stock-probs:schema13-recovery-abc123"
    calls: list[list[str]] = []

    def run(command: list[str], **_kwargs: object) -> CompletedProcess[str]:
        calls.append(command)
        return CompletedProcess(command, 0 if len(calls) == 1 else 1, stdout="", stderr="")

    monkeypatch.setattr(rehearsal, "_run", run)

    assert rehearsal._remove_generated_image_tag(tag, {}) is True
    assert calls == [
        ["docker", "image", "rm", "--no-prune", tag],
        ["docker", "image", "inspect", "--format", "{{.Id}}", tag],
    ]


def test_build_image_blocks_low_disk_before_spawn_and_stops_mid_build(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "docker-root"
    root.mkdir()
    context = tmp_path / "context"
    context.mkdir()
    tag = "stock-probs:pr-candidate-" + "a" * 12 + "-" + "b" * 12
    monkeypatch.setattr(rehearsal, "_docker_data_root", lambda _env: root)
    launches: list[object] = []
    monkeypatch.setattr(rehearsal.subprocess, "Popen", lambda *_args, **_kwargs: launches.append(1))
    monkeypatch.setattr(rehearsal, "_build_free_bytes", lambda _path: 2 * 1024**3)
    with pytest.raises(rehearsal.RehearsalError, match="at least 4 GiB"):
        rehearsal._build_image(context, tag, "a" * 40, {})
    assert launches == []

    class RunningProcess:
        pid = 42002
        terminated = False
        waited = False

        def poll(self) -> None:
            return None

        def wait(self, *, timeout: int) -> int:
            self.waited = True
            assert timeout == rehearsal._BUILD_TERM_GRACE_SECONDS
            return 0

    process = RunningProcess()
    frees = iter([8 * 1024**3, 512 * 1024**2])
    monkeypatch.setattr(rehearsal, "_build_free_bytes", lambda _path: next(frees))
    monkeypatch.setattr(rehearsal.subprocess, "Popen", lambda *_args, **_kwargs: process)
    signals: list[int] = []
    group = {"exists": True}

    def killpg(_pgid: int, signal_number: int) -> None:
        if signal_number == 0:
            if not group["exists"]:
                raise ProcessLookupError()
            return
        signals.append(signal_number)
        group["exists"] = False

    monkeypatch.setattr(rehearsal.os, "killpg", killpg)
    with pytest.raises(rehearsal.RehearsalError, match="stopped below 1 GiB"):
        rehearsal._build_image(context, tag, "a" * 40, {})
    assert process.waited is True
    assert signals == [rehearsal.signal.SIGTERM]


def test_stopped_build_group_kills_descendant_after_client_exits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "docker-root"
    context = tmp_path / "context"
    root.mkdir()
    context.mkdir()
    tag = "stock-probs:pr-candidate-" + "a" * 12 + "-" + "b" * 12
    monkeypatch.setattr(rehearsal, "_docker_data_root", lambda _env: root)
    monkeypatch.setattr(rehearsal, "_build_free_bytes", lambda _path: 8 * 1024**3)

    class ExitedLeader:
        pid = 42003
        waited = 0

        def poll(self) -> int:
            return 0

        def wait(self, *, timeout: int) -> int:
            self.waited += 1
            assert timeout in {
                rehearsal._BUILD_TERM_GRACE_SECONDS,
                rehearsal._BUILD_KILL_GRACE_SECONDS,
            }
            return 0

    leader = ExitedLeader()
    group = {"exists": True}
    signals: list[int] = []
    ticks = iter([0, 1, 2, 3])

    def killpg(_pgid: int, signal_number: int) -> None:
        if signal_number == 0:
            if not group["exists"]:
                raise ProcessLookupError()
            return
        signals.append(signal_number)
        if signal_number == rehearsal.signal.SIGKILL:
            group["exists"] = False

    ticks = iter([0, 1, 2, 3, 4, 5])
    monkeypatch.setattr(rehearsal.time, "monotonic", lambda: next(ticks, 100))
    monkeypatch.setattr(rehearsal.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(rehearsal.os, "killpg", killpg)
    monkeypatch.setattr(rehearsal.subprocess, "Popen", lambda *_args, **_kwargs: leader)
    with pytest.raises(rehearsal.RehearsalError, match="left child processes"):
        rehearsal._build_image(context, tag, "a" * 40, {})
    assert leader.waited >= 2
    assert signals == [rehearsal.signal.SIGTERM, rehearsal.signal.SIGKILL]
    with pytest.raises(ProcessLookupError):
        os.killpg(leader.pid, 0)


def test_build_timeout_and_keyboard_interrupt_reap_the_owned_group(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "docker-root"
    root.mkdir()
    context = tmp_path / "context"
    context.mkdir()
    tag = "stock-probs:pr-candidate-" + "a" * 12 + "-" + "b" * 12
    monkeypatch.setattr(rehearsal, "_docker_data_root", lambda _env: root)
    monkeypatch.setattr(rehearsal, "_build_free_bytes", lambda _path: 8 * 1024**3)

    class RunningProcess:
        pid = 42004

        def poll(self) -> None:
            return None

        def wait(self, *, timeout: int) -> int:
            assert timeout == rehearsal._BUILD_TERM_GRACE_SECONDS
            return 0

    state = {"exists": True}
    signals: list[int] = []

    def killpg(_pgid: int, signal_number: int) -> None:
        if signal_number == 0:
            if not state["exists"]:
                raise ProcessLookupError()
            return
        signals.append(signal_number)
        state["exists"] = False

    monkeypatch.setattr(rehearsal.os, "killpg", killpg)
    timeout_process = RunningProcess()
    monkeypatch.setattr(rehearsal.subprocess, "Popen", lambda *_args, **_kwargs: timeout_process)
    monkeypatch.setattr(rehearsal, "_BUILD_TIMEOUT_SECONDS", 1)
    clock = {"value": 0}

    def advance_clock() -> int:
        value = clock["value"]
        clock["value"] += 2
        return value

    monkeypatch.setattr(rehearsal.time, "monotonic", advance_clock)
    with pytest.raises(rehearsal.RehearsalError, match="local_build_timeout"):
        rehearsal._build_image(context, tag, "a" * 40, {})
    assert signals == [rehearsal.signal.SIGTERM]

    state["exists"] = True
    signals.clear()
    interrupt_process = RunningProcess()

    class InterruptedProcess(RunningProcess):
        def poll(self) -> None:
            raise KeyboardInterrupt()

    interrupt_process = InterruptedProcess()
    monkeypatch.setattr(rehearsal.subprocess, "Popen", lambda *_args, **_kwargs: interrupt_process)
    monkeypatch.setattr(rehearsal, "_BUILD_TIMEOUT_SECONDS", 900)
    monkeypatch.setattr(rehearsal.time, "monotonic", lambda: 0)
    with pytest.raises(KeyboardInterrupt):
        rehearsal._build_image(context, tag, "a" * 40, {})
    assert signals == [rehearsal.signal.SIGTERM]


def test_pr_candidate_receipt_is_bound_and_failed_revalidation_retains_tag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository = tmp_path / "repo"
    repository.mkdir()
    reviewed_sha = "e" * 40
    context_sha = "f" * 64
    image_id = "sha256:" + "1" * 64
    calls = {"local": 0, "pr": 0}
    monkeypatch.setattr(
        rehearsal,
        "_verify_local_pr_head",
        lambda _root, _sha: calls.__setitem__("local", calls["local"] + 1),
    )
    monkeypatch.setattr(
        rehearsal,
        "_verify_reviewed_pr",
        lambda _root, _sha: calls.__setitem__("pr", calls["pr"] + 1),
    )

    def copy_context(_root: Path, destination: Path) -> str:
        destination.mkdir(parents=True)
        (destination / "Dockerfile").write_text("fixed", encoding="utf-8")
        return context_sha

    inspected_commands: list[list[str]] = []

    def run(command: list[str], **_kwargs: object) -> CompletedProcess[str]:
        inspected_commands.append(command)
        return CompletedProcess(command, 1, stdout="", stderr="")

    monkeypatch.setattr(rehearsal, "_candidate_context", copy_context)
    monkeypatch.setattr(rehearsal, "_run", run)
    monkeypatch.setattr(rehearsal, "_build_image", lambda *_args, **_kwargs: image_id)
    monkeypatch.setattr(
        rehearsal,
        "_verify_candidate_image",
        lambda _id, digest, _env, **kwargs: {
            "id": image_id,
            "architecture": "linux/amd64",
            "source_context_sha256": digest,
            "revision_label": kwargs["expected_revision_label"],
        },
    )
    receipt_path = tmp_path / "private/build-receipt.json"
    receipt = rehearsal.build_pr_candidate(repository, reviewed_sha, receipt_path)
    assert calls == {"local": 3, "pr": 2}
    assert inspected_commands[0][0:3] == ["docker", "image", "inspect"]
    assert receipt["candidate_image"]["id"] == image_id
    assert receipt["reviewed_head"] == reviewed_sha
    assert receipt_path.stat().st_mode & 0o777 == 0o600
    receipt_digest = receipt.pop("receipt_sha256")
    assert receipt_digest == rehearsal._sha256(rehearsal._canonical_json(receipt))

    calls.update(local=0, pr=0)

    def pr_moved(_root: Path, _sha: str) -> None:
        calls["pr"] += 1
        if calls["pr"] == 2:
            raise rehearsal.RehearsalError("reviewed_pr_mismatch")

    monkeypatch.setattr(rehearsal, "_verify_reviewed_pr", pr_moved)
    failed_receipt = tmp_path / "private/no-receipt.json"
    with pytest.raises(rehearsal.RehearsalError, match="generated candidate image tag retained"):
        rehearsal.build_pr_candidate(repository, reviewed_sha, failed_receipt)
    assert not failed_receipt.exists()
    assert not any("rm" in command for command in inspected_commands)


def test_pr_candidate_cli_requires_exact_head_and_private_receipt(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(sys, "argv", ["rehearse_schema13.py", "--build-pr-candidate"])
    assert rehearsal.main() == 2
    failure = json.loads(capsys.readouterr().err)
    assert failure["status"] == "fail"
    assert "--reviewed-pr-head and --receipt" in failure["reason"]

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "rehearse_schema13.py",
            "--build-pr-candidate",
            "--reviewed-pr-head",
            "a" * 40,
            "--receipt",
            str(REPOSITORY_ROOT / "test-results/candidate.json"),
            "--candidate-image-id",
            "sha256:" + "a" * 64,
        ],
    )
    assert rehearsal.main() == 2
    assert "cannot be combined" in json.loads(capsys.readouterr().err)["reason"]


@pytest.mark.parametrize("reuse_baseline", [False, True])
def test_full_rehearsal_cli_passes_explicit_baseline_choice(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    reuse_baseline: bool,
) -> None:
    candidate_id = "sha256:" + "a" * 64
    candidate_context = "b" * 64
    calls: list[dict[str, object]] = []

    def run_rehearsal(
        _repository_root: Path,
        image_id: str,
        context_sha256: str,
        **kwargs: object,
    ) -> dict[str, object]:
        calls.append(
            {
                "image_id": image_id,
                "context_sha256": context_sha256,
                **kwargs,
            }
        )
        return {"status": "pass"}

    monkeypatch.setattr(rehearsal, "run_rehearsal", run_rehearsal)
    arguments = [
        "rehearse_schema13.py",
        "--candidate-image-id",
        candidate_id,
        "--expected-candidate-context-sha256",
        candidate_context,
    ]
    if reuse_baseline:
        arguments.append("--use-deployed-baseline-image")
    monkeypatch.setattr(sys, "argv", arguments)

    assert rehearsal.main() == 0
    capsys.readouterr()
    assert calls == [
        {
            "image_id": candidate_id,
            "context_sha256": candidate_context,
            "candidate_revision": None,
            "release_artifact_directory": None,
            "use_deployed_baseline_image": reuse_baseline,
        }
    ]


@pytest.mark.parametrize(
    "extra_arguments",
    [
        ["--overlay-manifest"],
        ["--source-context-manifest"],
        ["--build-pr-candidate"],
    ],
)
def test_deployed_baseline_flag_is_rejected_outside_full_rehearsal(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    extra_arguments: list[str],
) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        ["rehearse_schema13.py", "--use-deployed-baseline-image", *extra_arguments],
    )

    assert rehearsal.main() == 2
    failure = json.loads(capsys.readouterr().err)
    assert failure["status"] == "fail"
    assert "only valid for a full rehearsal" in failure["reason"]
