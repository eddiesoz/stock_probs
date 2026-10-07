"""The one-shot emergency CLI must only disable the already-running assistant."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

import stock_probs.cli as cli
from stock_probs.assistant import supervisor_client

ROOT = Path(__file__).resolve().parents[1]


def test_assistant_kill_cli_uses_fixed_disable_and_waits_for_home_purge(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    calls: list[tuple[str, object]] = []

    class Supervisor:
        async def disable(self, reason: str) -> str:
            calls.append(("disable", reason))
            return "a" * 32

        async def wait_for_home_purge(self, purge_id: str) -> bool:
            calls.append(("purge", purge_id))
            return True

    monkeypatch.setattr(supervisor_client, "SupervisorClient", Supervisor)
    monkeypatch.setattr(sys, "argv", ["stock-probs", "assistant-kill"])

    cli.main()

    assert calls == [("disable", "operator"), ("purge", "a" * 32)]
    assert capsys.readouterr().out == '{"status":"assistant_disabled"}\n'


def test_assistant_kill_cli_fails_closed_when_home_purge_is_not_verified(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    class Supervisor:
        async def disable(self, reason: str) -> str:
            assert reason == "operator"
            return "a" * 32

        async def wait_for_home_purge(self, purge_id: str) -> bool:
            assert purge_id == "a" * 32
            return False

    monkeypatch.setattr(supervisor_client, "SupervisorClient", Supervisor)
    monkeypatch.setattr(sys, "argv", ["stock-probs", "assistant-kill"])

    with pytest.raises(SystemExit) as captured:
        cli.main()

    assert captured.value.code == 2
    assert capsys.readouterr().out == ""


def test_assistant_kill_cli_has_no_caller_supplied_operational_arguments(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys, "argv", ["stock-probs", "assistant-kill", "--command", "anything"])

    with pytest.raises(SystemExit) as captured:
        cli.main()

    assert captured.value.code == 2


def test_cli_import_does_not_initialize_app_or_storage_modules() -> None:
    """A kill invocation can run beside PID 1 without constructing app dependencies."""

    code = (
        "import sys; import stock_probs.cli; "
        "blocked={'stock_probs.api','stock_probs.config','stock_probs.repository',"
        "'stock_probs.backup','stock_probs.assistant.providers'}; "
        "assert blocked.isdisjoint(sys.modules)"
    )
    environment = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "PYTHONPATH": str(ROOT / "src"),
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    completed = subprocess.run(  # noqa: S603 - fixed interpreter and fixed import assertion.
        [sys.executable, "-c", code],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        check=False,
        text=True,
        timeout=5,
    )

    assert completed.returncode == 0, "CLI import unexpectedly initialized application modules"
    assert completed.stdout == ""
    assert completed.stderr == ""
