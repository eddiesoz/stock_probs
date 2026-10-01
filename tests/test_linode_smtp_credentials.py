"""Focused checks for the fixed production Resend credential installer."""

from __future__ import annotations

import ast
import base64
import fcntl
import http.client
import importlib.util
import os
import shlex
import stat
import subprocess
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "infra" / "linode" / "install-resend-smtp-key.sh"
HELPER = ROOT / "infra" / "linode" / "smtp-credential-installer.py"


def _helper() -> ModuleType:
    spec = importlib.util.spec_from_file_location("smtp_credential_installer", HELPER)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _sandbox(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[ModuleType, Path]:
    helper = _helper()
    app_directory = tmp_path / "etc" / "signal-ledger"
    state_directory = tmp_path / "var" / "lib" / "signal-ledger"
    compose_directory = tmp_path / "opt" / "signal-ledger"
    for directory in (app_directory, state_directory, compose_directory):
        directory.mkdir(parents=True)
        directory.chmod(0o750)

    app_env = app_directory / "app.env"
    app_env.write_bytes(
        b"STOCK_PROBS_AUTH_MODE=github\n"
        b"KEEP_ME=preserved\n"
        b"STOCK_PROBS_INVITE_SMTP_PASSWORD=re_oldkey_aaaaaaaa\n"
        b"export STOCK_PROBS_INVITE_SMTP_PASSWORD=re_duplicate_bbbbbbbb\n"
    )
    app_env.chmod(0o600)
    runtime_env = state_directory / "runtime.env"
    runtime_env.write_bytes(b"STOCK_PROBS_IMAGE=signal-ledger:sha-" + b"a" * 40 + b"\n")
    runtime_env.chmod(0o640)
    compose_file = compose_directory / "compose.production.yaml"
    compose_file.write_bytes(b"services:\n  app:\n    image: signal-ledger\n")
    compose_file.chmod(0o644)

    monkeypatch.setattr(helper, "ROOT_UID", os.getuid())
    monkeypatch.setattr(helper, "APP_DIRECTORY", str(app_directory))
    monkeypatch.setattr(helper, "APP_ENV", str(app_env))
    monkeypatch.setattr(helper, "STATE_DIRECTORY", str(state_directory))
    monkeypatch.setattr(helper, "RUNTIME_ENV", str(runtime_env))
    monkeypatch.setattr(helper, "COMPOSE_DIRECTORY", str(compose_directory))
    monkeypatch.setattr(helper, "COMPOSE_FILE", str(compose_file))
    monkeypatch.setattr(helper.os, "fchown", lambda *_: None)
    return helper, app_env


def test_shell_entrypoint_has_fixed_host_and_rejects_arbitrary_remote_arguments() -> None:
    result = subprocess.run(  # noqa: S603
        [str(SCRIPT), "--help"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "--api-key-file FILE" in result.stderr

    rejected = subprocess.run(  # noqa: S603
        [str(SCRIPT), "--host", "attacker.example"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert rejected.returncode == 2
    assert "no host, user, command, URL, or remote path" in rejected.stderr

    source = SCRIPT.read_text(encoding="utf-8")
    assert 'readonly REMOTE_HOST="45.79.180.32"' in source
    assert 'readonly REMOTE_USER="signalops"' in source
    assert "StrictHostKeyChecking=yes" in source
    assert "IdentitiesOnly=yes" in source
    assert "ClearAllForwardings=yes" in source
    assert "eval " not in source
    assert "scp " not in source


def test_remote_helper_source_is_valid_and_uses_fixed_immutable_compose_boundary() -> None:
    source = HELPER.read_text(encoding="utf-8")
    ast.parse(source)

    for value in (
        'APP_ENV = f"{APP_DIRECTORY}/{APP_ENV_NAME}"',
        'RUNTIME_ENV = f"{STATE_DIRECTORY}/runtime.env"',
        'COMPOSE_FILE = f"{COMPOSE_DIRECTORY}/{COMPOSE_FILE_NAME}"',
        'HEALTH_URL = "http://127.0.0.1:8000/api/v1/readiness"',
        'SMTP_PASSWORD_NAME = b"STOCK_PROBS_INVITE_SMTP_PASSWORD"',
        'SMTP_HOST_NAME = b"STOCK_PROBS_INVITE_SMTP_HOST"',
        'b"smtp.resend.com"',
        'b"invites@mail.jtmb.cc"',
        "ENV_ASSIGNMENT_PATTERN = re.compile",
        '"--pull",',
        '"never",',
        '"--no-build",',
        '"--force-recreate",',
        "stdin=subprocess.DEVNULL",
        "stdout=subprocess.DEVNULL",
        "stderr=subprocess.DEVNULL",
        "ProxyHandler({})",
    ):
        assert value in source
    assert "sys.stdout" not in source


def test_remote_python_transport_is_a_shell_safe_base64_literal() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assignment = next(line for line in source.splitlines() if line.startswith("remote_command="))
    template = ast.literal_eval(assignment.split("=", 1)[1])
    encoded = base64.b64encode(HELPER.read_bytes()).decode("ascii")
    command = template.replace("${remote_python_base64}", encoded)
    parsed = shlex.split(command)

    assert parsed[:5] == [
        "/usr/bin/sudo",
        "-n",
        "--",
        "/usr/bin/python3",
        "-c",
    ]
    assert parsed[5] == f'import base64;exec(base64.b64decode("{encoded}"))'
    ast.parse(parsed[5])
    assert base64.b64decode(encoded) == HELPER.read_bytes()
    assert "$(" not in template


def test_validate_key_file_requires_private_one_line_resend_key(tmp_path: Path) -> None:
    key_file = tmp_path / "resend-key"
    key = b"re_" + b"a" * 16
    key_file.write_bytes(key + b"\n")
    key_file.chmod(0o600)

    valid = subprocess.run(  # noqa: S603
        [sys.executable, str(HELPER), "--validate-file", str(key_file)],
        capture_output=True,
        check=False,
    )
    assert valid.returncode == 0
    assert valid.stdout == b""
    assert valid.stderr == b""

    key_file.chmod(0o640)
    invalid = subprocess.run(  # noqa: S603
        [sys.executable, str(HELPER), "--validate-file", str(key_file)],
        capture_output=True,
        check=False,
    )
    assert invalid.returncode == 2
    assert invalid.stdout == b""
    assert invalid.stderr == b""

    key_file.chmod(0o600)
    key_file.write_bytes(b"not-a-resend-key\n")
    invalid_key = subprocess.run(  # noqa: S603
        [sys.executable, str(HELPER), "--validate-file", str(key_file)],
        capture_output=True,
        check=False,
    )
    assert invalid_key.returncode == 2
    assert invalid_key.stdout == b""
    assert invalid_key.stderr == b""


def test_install_replaces_smtp_settings_atomically_and_recreates_current_image(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    helper, app_env = _sandbox(tmp_path, monkeypatch)
    compose_calls: list[tuple[list[str], dict[str, object]]] = []
    readiness_calls: list[bool] = []

    def fake_run(command: list[str], **kwargs: object) -> SimpleNamespace:
        compose_calls.append((command, kwargs))
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(helper.subprocess, "run", fake_run)
    monkeypatch.setattr(helper, "_wait_ready", lambda: readiness_calls.append(True))

    helper.install(b"re_" + b"c" * 24)

    value = app_env.read_bytes()
    assert b"KEEP_ME=preserved\n" in value
    expected = {
        b"STOCK_PROBS_INVITE_SMTP_HOST=smtp.resend.com\n",
        b"STOCK_PROBS_INVITE_SMTP_PORT=2465\n",
        b"STOCK_PROBS_INVITE_SMTP_USERNAME=resend\n",
        b"STOCK_PROBS_INVITE_SMTP_PASSWORD=re_" + b"c" * 24 + b"\n",
        b"STOCK_PROBS_INVITE_SMTP_SECURITY=implicit_tls\n",
        b"STOCK_PROBS_INVITE_EMAIL_FROM=invites@mail.jtmb.cc\n",
    }
    assert expected.issubset(set(value.splitlines(keepends=True)))
    for line in expected:
        assert value.count(line.split(b"=", 1)[0] + b"=") == 1
    assert stat.S_IMODE(app_env.stat().st_mode) == 0o600
    assert readiness_calls == [True]

    assert len(compose_calls) == 1
    command, kwargs = compose_calls[0]
    assert command[-6:] == [
        "--detach",
        "--no-build",
        "--pull",
        "never",
        "--force-recreate",
        "app",
    ]
    assert command[0:2] == ["/usr/bin/docker", "compose"]
    assert command[command.index("--env-file") + 1] == str(app_env)
    assert command[command.index("--file") + 1].endswith("/compose.production.yaml")
    assert kwargs["stdin"] is subprocess.DEVNULL
    assert kwargs["stdout"] is subprocess.DEVNULL
    assert kwargs["stderr"] is subprocess.DEVNULL


def test_install_rejects_invalid_key_before_mutating_app_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    helper, app_env = _sandbox(tmp_path, monkeypatch)
    before = app_env.read_bytes()
    compose_called = False

    def fake_run(*_: object, **__: object) -> SimpleNamespace:
        nonlocal compose_called
        compose_called = True
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(helper.subprocess, "run", fake_run)

    with pytest.raises(helper.InstallError):
        helper.install(b"not-a-resend-key")

    assert app_env.read_bytes() == before
    assert compose_called is False


def test_install_populates_all_resend_settings_when_smtp_values_are_absent_or_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    helper, app_env = _sandbox(tmp_path, monkeypatch)
    app_env.write_bytes(
        b"KEEP_ME=preserved\n"
        b"STOCK_PROBS_INVITE_SMTP_HOST=\n"
        b"  export STOCK_PROBS_INVITE_SMTP_PORT = 587\n"
        b"STOCK_PROBS_INVITE_SMTP_USERNAME=\n"
        b"STOCK_PROBS_INVITE_SMTP_PASSWORD=\n"
        b"STOCK_PROBS_INVITE_SMTP_SECURITY=\n"
        b"STOCK_PROBS_INVITE_EMAIL_FROM=\n"
    )
    app_env.chmod(0o600)
    monkeypatch.setattr(helper.subprocess, "run", lambda *args, **kwargs: SimpleNamespace())
    monkeypatch.setattr(helper, "_wait_ready", lambda: None)

    helper.install(b"re_" + b"e" * 24)

    value = app_env.read_bytes()
    assert b"KEEP_ME=preserved\n" in value
    for line in (
        b"STOCK_PROBS_INVITE_SMTP_HOST=smtp.resend.com\n",
        b"STOCK_PROBS_INVITE_SMTP_PORT=2465\n",
        b"STOCK_PROBS_INVITE_SMTP_USERNAME=resend\n",
        b"STOCK_PROBS_INVITE_SMTP_PASSWORD=re_" + b"e" * 24 + b"\n",
        b"STOCK_PROBS_INVITE_SMTP_SECURITY=implicit_tls\n",
        b"STOCK_PROBS_INVITE_EMAIL_FROM=invites@mail.jtmb.cc\n",
    ):
        assert value.count(line) == 1


def test_install_rejects_malformed_preserved_env_before_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    helper, app_env = _sandbox(tmp_path, monkeypatch)
    app_env.write_bytes(b"KEEP_ME=preserved\nmalformed dotenv line\n")
    app_env.chmod(0o600)
    before = app_env.read_bytes()
    compose_called = False

    def fake_run(*_: object, **__: object) -> SimpleNamespace:
        nonlocal compose_called
        compose_called = True
        return SimpleNamespace()

    monkeypatch.setattr(helper.subprocess, "run", fake_run)

    with pytest.raises(helper.InstallError):
        helper.install(b"re_" + b"f" * 24)

    assert app_env.read_bytes() == before
    assert compose_called is False


def test_install_rolls_back_when_recreate_fails_and_recovers_readiness(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    helper, app_env = _sandbox(tmp_path, monkeypatch)
    before = app_env.read_bytes()
    recreate_calls = 0

    def recreate() -> None:
        nonlocal recreate_calls
        recreate_calls += 1
        if recreate_calls == 1:
            raise helper.InstallError

    monkeypatch.setattr(helper, "_compose_recreate", recreate)
    monkeypatch.setattr(helper, "_wait_ready", lambda: None)

    with pytest.raises(helper.RollbackRecovered):
        helper.install(b"re_" + b"r" * 24)

    assert app_env.read_bytes() == before
    assert recreate_calls == 2
    assert not list(Path(helper.STATE_DIRECTORY).glob(".smtp-rollback.*.env"))


def test_install_keeps_private_rollback_artifact_on_concurrent_env_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    helper, app_env = _sandbox(tmp_path, monkeypatch)
    before = app_env.read_bytes()
    concurrent = b"CONCURRENT=changed\n"

    def recreate() -> None:
        app_env.write_bytes(concurrent)
        app_env.chmod(0o600)
        raise helper.InstallError

    monkeypatch.setattr(helper, "_compose_recreate", recreate)

    with pytest.raises(helper.InstallError):
        helper.install(b"re_" + b"s" * 24)

    assert app_env.read_bytes() == concurrent
    artifacts = list(Path(helper.STATE_DIRECTORY).glob(".smtp-rollback.*.env"))
    assert len(artifacts) == 1
    assert artifacts[0].read_bytes() == before
    assert stat.S_IMODE(artifacts[0].stat().st_mode) == 0o600


def test_readiness_accepts_only_ready_schema_response(monkeypatch: pytest.MonkeyPatch) -> None:
    helper = _helper()

    class ReadyResponse:
        status = 200

        def __enter__(self) -> ReadyResponse:
            return self

        def __exit__(self, *_: object) -> None:
            return None

        def read(self, _: int) -> bytes:
            return b'{"status":"ready","schema_version":10}'

    class ReadyOpener:
        def open(self, *_: object, **__: object) -> ReadyResponse:
            return ReadyResponse()

    monkeypatch.setattr(helper, "build_opener", lambda _: ReadyOpener())
    helper._wait_ready()


def test_incomplete_read_enters_bounded_rollback_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    helper, app_env = _sandbox(tmp_path, monkeypatch)
    before = app_env.read_bytes()
    recreate_calls = 0
    readiness_calls = 0

    def recreate() -> None:
        nonlocal recreate_calls
        recreate_calls += 1

    class ReadyResponse:
        status = 200

        def __enter__(self) -> ReadyResponse:
            return self

        def __exit__(self, *_: object) -> None:
            return None

        def read(self, _: int) -> bytes:
            return b'{"status":"ready","schema_version":10}'

    class FailingThenReadyOpener:
        def open(self, *_: object, **__: object) -> ReadyResponse:
            nonlocal readiness_calls
            readiness_calls += 1
            if readiness_calls <= 30:
                raise http.client.IncompleteRead(b"partial")
            return ReadyResponse()

    monkeypatch.setattr(helper, "_compose_recreate", recreate)
    monkeypatch.setattr(helper, "build_opener", lambda _: FailingThenReadyOpener())
    monkeypatch.setattr(helper.time, "sleep", lambda _: None)

    with pytest.raises(helper.RollbackRecovered):
        helper.install(b"re_" + b"t" * 24)

    assert app_env.read_bytes() == before
    assert recreate_calls == 2
    assert readiness_calls == 31


def test_install_does_not_bypass_busy_deploy_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    helper, _ = _sandbox(tmp_path, monkeypatch)
    state_directory = Path(helper.STATE_DIRECTORY)
    lock_path = state_directory / helper.LOCK_FILE_NAME
    lock_fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o640)
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(helper.InstallError):
            helper.install(b"re_" + b"d" * 24)
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        os.close(lock_fd)
