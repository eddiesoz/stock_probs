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
    excluded = {item.resolve() for item in (staged_chunk, credentials, database, backup, ssh_key)}

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
