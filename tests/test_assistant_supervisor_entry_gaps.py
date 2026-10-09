"""Exercise fixed supervisor entry, child, startup, and bounded IPC transitions."""

from __future__ import annotations

import json
import os
import signal
import socket
import stat
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from stock_probs import container_supervisor as supervisor


class _LiveChild:
    """Stand in for a live child without starting a process."""

    def poll(self) -> None:
        return None


class _Child:
    """Stand in for the child wrapper used by ``_run_child``."""

    def __init__(self, polls: list[int | None], waits: list[int | BaseException] | None = None):
        self.polls = list(polls)
        self.waits = list(waits or [])
        self.returncode: int | None = None
        self.signals: list[int] = []
        self.killed = False

    def poll(self) -> int | None:
        if self.polls:
            result = self.polls.pop(0)
            if result is not None:
                self.returncode = result
            return result
        return self.returncode

    def wait(self, *, timeout: float) -> int:
        if not self.waits:
            raise AssertionError("unexpected child wait")
        result = self.waits.pop(0)
        if isinstance(result, BaseException):
            raise result
        self.returncode = result
        return result

    def send_signal(self, signum: int) -> None:
        self.signals.append(signum)

    def kill(self) -> None:
        self.killed = True


class _Selector:
    """Provide deterministic selector readiness without registering a real pipe."""

    def __init__(self, events: list[list[object]] | None = None, on_select=None):
        self.events = list(events or [])
        self.on_select = on_select
        self.registered: object | None = None
        self.timeouts: list[float] = []
        self.closed = False

    def register(self, fileobj: object, _events: int) -> None:
        self.registered = fileobj

    def select(self, *, timeout: float) -> list[object]:
        self.timeouts.append(timeout)
        if self.on_select is not None:
            self.on_select()
            self.on_select = None
        return self.events.pop(0) if self.events else []

    def close(self) -> None:
        self.closed = True


def _new_supervisor(
    monkeypatch: pytest.MonkeyPatch,
    *,
    worker_enabled: bool = True,
    environment: dict[str, str] | None = None,
) -> supervisor.ContainerSupervisor:
    # Keep tests away from the image's fixed native binary and build-receipt paths.
    monkeypatch.setattr(supervisor, "_native_build_receipt_valid", lambda: False)
    return supervisor.ContainerSupervisor(
        worker_enabled=worker_enabled,
        environment={} if environment is None else environment,
    )


def test_child_target_is_a_closed_command_and_identity_map() -> None:
    app_command, app_uid, app_gid = supervisor._child_target("app")
    worker_command, worker_uid, worker_gid = supervisor._child_target("worker")

    assert app_command == [
        str(supervisor.APPLICATION_BINARY),
        "serve",
        "--host",
        "0.0.0.0",  # noqa: S104 - the fixed container port is published only on loopback.
        "--port",
        "8000",
        "--allow-non-loopback",
    ]
    assert (app_uid, app_gid) == (supervisor.APPLICATION_UID, supervisor.APPLICATION_GID)
    assert worker_command == [
        str(supervisor.WORKER_BINARY),
        "serve",
        "--hostname",
        "127.0.0.1",
        "--port",
        "4097",
    ]
    assert (worker_uid, worker_gid) == (supervisor.WORKER_UID, supervisor.WORKER_GID)
    with pytest.raises(supervisor.SupervisorError, match="child_role_invalid"):
        supervisor._child_target("shell")


def test_spawn_uses_the_fixed_wrapper_and_role_specific_least_privilege_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    instance = _new_supervisor(
        monkeypatch,
        environment={"STOCK_PROBS_ASSISTANT_ENABLED": "1", "TEST_PARENT_SENTINEL": "keep-out"},
    )
    popen_calls: list[tuple[list[str], dict[str, object]]] = []
    identities: list[tuple[int, int, bool]] = []

    def fake_popen(command: list[str], **options: object) -> _LiveChild:
        popen_calls.append((command, options))
        return _LiveChild()

    monkeypatch.setattr(supervisor.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(
        supervisor,
        "_drop_identity",
        lambda uid, gid, *, prefer_oom_termination=False: identities.append(
            (uid, gid, prefer_oom_termination)
        ),
    )

    for role in ("app", "worker"):
        instance._spawn(role)

    expected_wrapper = lambda role: [  # noqa: E731 - compact fixed-command fixture.
        sys.executable,
        "-m",
        "stock_probs.container_supervisor",
        "--child",
        role,
    ]
    assert [command for command, _ in popen_calls] == [
        expected_wrapper("app"),
        expected_wrapper("worker"),
    ]
    app_options, worker_options = (options for _, options in popen_calls)
    assert app_options["env"] == instance.environment
    assert worker_options["env"] == supervisor._clean_worker_environment(instance.api_password)
    assert "TEST_PARENT_SENTINEL" not in worker_options["env"]
    assert all(options["stdin"] == subprocess.PIPE for _, options in popen_calls)
    assert all(options["start_new_session"] is True for _, options in popen_calls)
    for _, options in popen_calls:
        options["preexec_fn"]()  # type: ignore[operator]
    assert identities == [
        (supervisor.APPLICATION_UID, supervisor.APPLICATION_GID, False),
        (supervisor.WORKER_UID, supervisor.WORKER_GID, True),
    ]


def _install_child_wrapper_fakes(
    monkeypatch: pytest.MonkeyPatch,
    child: _Child,
    selector: _Selector,
    *,
    parent_environment: dict[str, str],
    stdin: object,
) -> tuple[list[tuple[list[str], dict[str, object]]], list[tuple[int, int]], dict[int, object]]:
    popen_calls: list[tuple[list[str], dict[str, object]]] = []
    group_signals: list[tuple[int, int]] = []
    handlers: dict[int, object] = {}
    monkeypatch.setattr(
        supervisor,
        "os",
        SimpleNamespace(
            environ=parent_environment,
            getpgrp=lambda: 43210,
            killpg=lambda group, signum: group_signals.append((group, signum)),
        ),
    )
    monkeypatch.setattr(supervisor, "sys", SimpleNamespace(stdin=stdin, executable=sys.executable))
    monkeypatch.setattr(supervisor.selectors, "DefaultSelector", lambda: selector)
    monkeypatch.setattr(
        supervisor.signal,
        "signal",
        lambda signum, handler: handlers.__setitem__(signum, handler),
    )

    def fake_popen(command: list[str], **options: object) -> _Child:
        popen_calls.append((command, options))
        return child

    monkeypatch.setattr(supervisor.subprocess, "Popen", fake_popen)
    return popen_calls, group_signals, handlers


def test_worker_child_wrapper_executes_fixed_local_target_with_clean_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    child = _Child([None, 0])
    selector = _Selector()
    stdin = object()
    calls, _, handlers = _install_child_wrapper_fakes(
        monkeypatch,
        child,
        selector,
        parent_environment={
            "OPENCODE_SERVER_PASSWORD": "synthetic-worker-password",
            "OPENAI_API_KEY": "fixture-parent-secret-sentinel",
        },
        stdin=stdin,
    )

    assert supervisor._run_child("worker") == 0

    command, options = calls[0]
    assert command == supervisor._child_target("worker")[0]
    assert options["env"] == supervisor._clean_worker_environment("synthetic-worker-password")
    assert "OPENAI_API_KEY" not in options["env"]
    assert options["stdin"] == subprocess.DEVNULL
    assert selector.registered is stdin
    assert selector.timeouts == [0.2]
    assert selector.closed is True
    assert set(handlers) == {signal.SIGTERM, signal.SIGINT}


def test_worker_child_stop_pipe_sends_only_group_termination_and_closes_selector(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    child = _Child([None], waits=[23])
    selector = _Selector(events=[[object()]])
    stdin = SimpleNamespace(buffer=SimpleNamespace(readline=lambda _limit: b"stop\n"))
    _, group_signals, _ = _install_child_wrapper_fakes(
        monkeypatch,
        child,
        selector,
        parent_environment={},
        stdin=stdin,
    )

    assert supervisor._run_child("app") == 23

    assert group_signals == [(43210, signal.SIGTERM)]
    assert selector.closed is True
    assert child.signals == []
    assert child.waits == []


def test_worker_child_stop_pipe_uses_bounded_group_kill_after_term_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    child = _Child(
        [None],
        waits=[subprocess.TimeoutExpired("fixed-child", supervisor.SHUTDOWN_GRACE_SECONDS)],
    )
    selector = _Selector(events=[[object()]])
    stdin = SimpleNamespace(buffer=SimpleNamespace(readline=lambda _limit: b"stop\n"))
    _, group_signals, _ = _install_child_wrapper_fakes(
        monkeypatch,
        child,
        selector,
        parent_environment={},
        stdin=stdin,
    )

    assert supervisor._run_child("worker") == 137

    assert group_signals == [
        (43210, signal.SIGTERM),
        (43210, signal.SIGKILL),
    ]
    assert child.waits == []
    assert selector.closed is True


def test_worker_child_escalates_its_fake_wrapper_after_bounded_signal_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    child = _Child(
        [None, None],
        waits=[subprocess.TimeoutExpired("fixed-child", supervisor.SHUTDOWN_GRACE_SECONDS), 137],
    )
    selector = _Selector()
    stdin = object()
    _, _, installed_handlers = _install_child_wrapper_fakes(
        monkeypatch,
        child,
        selector,
        parent_environment={},
        stdin=stdin,
    )
    selector.on_select = lambda: installed_handlers[signal.SIGTERM](  # type: ignore[operator]
        signal.SIGTERM, None
    )

    assert supervisor._run_child("app") == 137

    assert child.signals == [signal.SIGTERM]
    assert child.killed is True
    assert selector.closed is True


@pytest.mark.parametrize(
    ("effective_uid", "arguments", "expected_exec", "expected_drop"),
    (
        (
            0,
            ["stock-probs", "migrate", "--check"],
            [str(supervisor.APPLICATION_BINARY), "migrate", "--check"],
            True,
        ),
        (
            0,
            [],
            [
                str(supervisor.APPLICATION_BINARY),
                "serve",
                "--host",
                "0.0.0.0",  # noqa: S104 - the fixed container port is published only on loopback.
                "--port",
                "8000",
                "--allow-non-loopback",
            ],
            True,
        ),
        (1000, ["version"], [str(supervisor.APPLICATION_BINARY), "version"], False),
        (
            1000,
            [],
            [
                str(supervisor.APPLICATION_BINARY),
                "serve",
                "--host",
                "0.0.0.0",  # noqa: S104 - fixed app command remains loopback-published.
                "--port",
                "8000",
                "--allow-non-loopback",
            ],
            False,
        ),
    ),
)
def test_main_one_shot_cli_execs_as_app_without_constructing_supervisor(
    monkeypatch: pytest.MonkeyPatch,
    effective_uid: int,
    arguments: list[str],
    expected_exec: list[str],
    expected_drop: bool,
) -> None:
    calls: list[tuple[object, ...]] = []
    fake_os = SimpleNamespace(
        geteuid=lambda: effective_uid,
        setgroups=lambda groups: calls.append(("setgroups", groups)),
        setgid=lambda gid: calls.append(("setgid", gid)),
        setuid=lambda uid: calls.append(("setuid", uid)),
        execv=lambda path, command: calls.append(("execv", path, command)),
    )
    monkeypatch.setattr(supervisor, "os", fake_os)
    monkeypatch.setattr(
        supervisor,
        "ContainerSupervisor",
        lambda **_kwargs: pytest.fail("one-shot CLI must not construct the supervisor"),
    )
    monkeypatch.setattr(
        supervisor,
        "_enable_subreaper",
        lambda: pytest.fail("one-shot CLI must not enable supervisor child reaping"),
    )
    monkeypatch.setattr(
        supervisor,
        "_no_new_privileges",
        lambda: calls.append(("no_new_privileges",)),
    )

    assert supervisor.main(arguments) == 127

    assert calls[-1] == ("execv", str(supervisor.APPLICATION_BINARY), expected_exec)
    assert calls[:-1] == (
        [
            ("setgroups", []),
            ("setgid", supervisor.APPLICATION_GID),
            ("setuid", supervisor.APPLICATION_UID),
            ("no_new_privileges",),
        ]
        if expected_drop
        else []
    )


def test_main_serve_path_enables_supervisor_then_closes_on_shutdown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[object] = []

    class FakeSupervisor:
        def __init__(self, *, worker_enabled: bool, environment: dict[str, str]):
            events.append(("construct", worker_enabled, set(environment)))

        def serve_forever(self) -> None:
            events.append(("serve",))
            raise KeyboardInterrupt

        def close(self) -> None:
            events.append(("close",))

    fake_os = SimpleNamespace(
        geteuid=lambda: 0,
        environ={"STOCK_PROBS_ASSISTANT_ENABLED": "yes"},
    )
    monkeypatch.setattr(supervisor, "os", fake_os)
    monkeypatch.setattr(supervisor, "ContainerSupervisor", FakeSupervisor)
    monkeypatch.setattr(supervisor, "_enable_subreaper", lambda: events.append(("subreaper",)))
    monkeypatch.setattr(
        supervisor.signal,
        "signal",
        lambda signum, _handler: events.append(("signal", signum)),
    )

    assert supervisor.main(["serve"]) == 0

    assert events == [
        ("subreaper",),
        ("construct", True, {"STOCK_PROBS_ASSISTANT_ENABLED"}),
        ("signal", signal.SIGTERM),
        ("signal", signal.SIGINT),
        ("serve",),
        ("close",),
    ]


def _use_temporary_control_paths(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    control_directory = tmp_path / "c"
    control_socket = control_directory / "s"
    monkeypatch.setattr(supervisor, "CONTROL_DIRECTORY", control_directory)
    monkeypatch.setattr(supervisor, "CONTROL_SOCKET", control_socket)
    monkeypatch.setattr(supervisor, "_ensure_location_root", lambda _fd: None)
    real_os = os
    # The test uses a real temporary directory/socket but substitutes root identity checks
    # and effective-gid changes so it never changes process credentials or touches /run.
    monkeypatch.setattr(
        supervisor,
        "os",
        SimpleNamespace(
            O_RDONLY=real_os.O_RDONLY,
            O_DIRECTORY=real_os.O_DIRECTORY,
            O_NOFOLLOW=real_os.O_NOFOLLOW,
            open=real_os.open,
            fstat=lambda _fd: SimpleNamespace(st_mode=stat.S_IFDIR | 0o711, st_uid=0),
            fchmod=real_os.fchmod,
            close=real_os.close,
            setegid=lambda _gid: None,
            chmod=real_os.chmod,
        ),
    )
    return control_socket


@pytest.mark.parametrize("startup_failure", ("worker_home_reset", "worker_spawn"))
def test_start_keeps_app_available_on_worker_boot_failure_and_close_removes_socket(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    startup_failure: str,
) -> None:
    control_socket = _use_temporary_control_paths(monkeypatch, tmp_path)
    instance = _new_supervisor(monkeypatch, worker_enabled=True, environment={})
    app = _LiveChild()
    spawned_roles: list[str] = []
    worker_spawn_attempts: list[str] = []
    stopped: list[tuple[object, int, int]] = []
    reset_attempts: list[str] = []

    def spawn(role: str) -> _LiveChild:
        spawned_roles.append(role)
        return app

    def spawn_worker() -> _LiveChild:
        worker_spawn_attempts.append("worker")
        if startup_failure == "worker_spawn":
            raise OSError("synthetic worker spawn failure")
        return _LiveChild()

    def reset_home() -> None:
        reset_attempts.append("reset")
        if startup_failure == "worker_home_reset":
            raise OSError("synthetic private HOME reset failure")

    monkeypatch.setattr(instance, "_spawn", spawn)
    monkeypatch.setattr(instance, "_spawn_worker", spawn_worker)
    monkeypatch.setattr(supervisor, "_reset_worker_home", reset_home)
    monkeypatch.setattr(
        instance,
        "_stop_child",
        lambda child, *, uid, gid: stopped.append((child, uid, gid)),
    )

    instance.start()

    assert instance._app is app and app.poll() is None
    assert instance._worker is None
    assert spawned_roles == ["app"]
    assert worker_spawn_attempts == ([] if startup_failure == "worker_home_reset" else ["worker"])
    assert instance._home_unavailable is (startup_failure == "worker_home_reset")
    assert control_socket.is_socket()
    assert stat.S_IMODE(control_socket.stat().st_mode) == 0o660
    server = instance._server

    instance.close()

    assert server is not None and server.fileno() == -1
    assert instance._server is None and instance._app is None and instance._worker is None
    assert not control_socket.exists()
    assert stopped == [
        (None, supervisor.WORKER_UID, supervisor.WORKER_GID),
        (app, supervisor.APPLICATION_UID, supervisor.APPLICATION_GID),
    ]
    assert len(reset_attempts) == 2


@pytest.mark.parametrize(
    "payload",
    (
        b"x" * (supervisor.REQUEST_LIMIT + 1) + b"\n",
        b'{"version":1}\n{"op":"status"}\n',
        b'{"version":\xff}\n',
        b"[]\n",
    ),
)
def test_read_request_rejects_oversized_or_malformed_frames(payload: bytes) -> None:
    receiver, sender = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        sender.sendall(payload)
        sender.shutdown(socket.SHUT_WR)
        with pytest.raises(supervisor.SupervisorError, match="request_invalid"):
            supervisor.ContainerSupervisor._read_request(receiver)
    finally:
        receiver.close()
        sender.close()


def test_read_request_rejects_an_expired_absolute_deadline_without_blocking() -> None:
    receiver, sender = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        with pytest.raises(supervisor.SupervisorError, match="request_timeout"):
            supervisor.ContainerSupervisor._read_request(receiver, deadline=0.0)
    finally:
        receiver.close()
        sender.close()


def test_serve_connection_replaces_an_oversized_dispatch_response_with_fixed_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    instance = _new_supervisor(monkeypatch, worker_enabled=False, environment={})
    monkeypatch.setattr(supervisor, "APPLICATION_UID", os.getuid())
    monkeypatch.setattr(
        instance,
        "_dispatch",
        lambda _request: {"ok": True, "oversized": "x" * (supervisor.RESPONSE_LIMIT + 1)},
    )
    client, server = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        client.sendall(b'{"version":1,"op":"status"}\n')
        client.shutdown(socket.SHUT_WR)
        instance._serve_connection(server)
        response_line = client.makefile("rb").readline(supervisor.RESPONSE_LIMIT + 2)
    finally:
        client.close()
        server.close()

    assert json.loads(response_line) == {"ok": False, "error": "response_invalid"}
    assert len(response_line) <= supervisor.RESPONSE_LIMIT + 1
