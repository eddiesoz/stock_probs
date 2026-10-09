"""Synthetic tests for the Buildx setup probe's Docker-root space guard."""

from __future__ import annotations

import hashlib
import importlib.util
import signal
import sys
from pathlib import Path

import pytest

SETUP_PATH = Path(__file__).resolve().parents[1] / "scripts/setup_bounded_buildkit.py"
SPEC = importlib.util.spec_from_file_location("r120_setup_builder_space", SETUP_PATH)
assert SPEC is not None and SPEC.loader is not None
setup = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = setup
SPEC.loader.exec_module(setup)
EXPECTED_UUID = "00000000-0000-0000-0000-000000000000"
IMAGE_ID = "sha256:" + "a" * 64
CONTAINER_ID = "a" * 64
NETWORK_ID = "c" * 64
CONTROLLER_PID = 123
WORKER_PID = 456
BOUNDED_NETWORK = {
    "name": setup.NETWORK_NAME,
    "id": NETWORK_ID,
    "driver": "bridge",
    "scope": "local",
    "internal": False,
    "enable_ipv6": False,
    "owner_label": {setup.NETWORK_OWNER_LABEL: setup.NETWORK_OWNER_VALUE},
}


def bounded_network_facts(_container_id: str, network: dict[str, object]) -> dict[str, object]:
    return {
        "builder_network": network,
        "builder_container_networks": {setup.NETWORK_NAME: NETWORK_ID},
    }


def prepare_cgroup_scope(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    controller_relative: tuple[str, ...],
    worker_relative: tuple[str, ...],
    memory_limit: str = str(setup.MEMORY),
    reported_host_pid: int = CONTROLLER_PID,
) -> tuple[Path, Path, Path, list[str]]:
    """Bind synthetic process paths to one exact Docker cgroup scope."""
    cgroup_root = tmp_path / "cgroup"
    boundary = cgroup_root / "system.slice" / f"docker-{CONTAINER_ID}.scope"
    boundary.mkdir(parents=True)
    (boundary / "memory.max").write_text(memory_limit, encoding="ascii")
    (boundary / "cpu.max").write_text(f"{setup.CPU_QUOTA} {setup.CPU_PERIOD}\n", encoding="ascii")
    controller_path = cgroup_root.joinpath(*controller_relative)
    worker_path = cgroup_root.joinpath(*worker_relative)
    controller_path.mkdir(parents=True, exist_ok=True)
    worker_path.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(setup, "CGROUP_ROOT", cgroup_root)
    monkeypatch.setattr(setup, "one_container_id", lambda: CONTAINER_ID)
    inspected_ids: list[str] = []

    def container_pid(container_id: str) -> int:
        inspected_ids.append(container_id)
        return reported_host_pid

    monkeypatch.setattr(setup, "container_host_pid", container_pid)
    paths = {CONTROLLER_PID: controller_path, WORKER_PID: worker_path}
    monkeypatch.setattr(setup, "cgroup_v2_path", lambda pid: paths[pid])
    return boundary, controller_path, worker_path, inspected_ids


@pytest.mark.parametrize("controller_suffix", [(), ("init",)])
def test_worker_cgroup_binds_limits_to_exact_container_scope(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    controller_suffix: tuple[str, ...],
) -> None:
    scope_name = f"docker-{CONTAINER_ID}.scope"
    controller_relative = ("system.slice", scope_name, *controller_suffix)
    worker_relative = ("system.slice", scope_name, "buildkit", "worker")
    boundary, controller_path, worker_path, inspected_ids = prepare_cgroup_scope(
        monkeypatch,
        tmp_path,
        controller_relative=controller_relative,
        worker_relative=worker_relative,
    )

    proof = setup.verify_worker_cgroup(CONTROLLER_PID, WORKER_PID)

    def digest_path(value: Path) -> str:
        return hashlib.sha256(str(value).encode()).hexdigest()

    assert inspected_ids == [CONTAINER_ID]
    assert proof["worker_cgroup_descendant"] is True
    assert proof["controller_cgroup_scope_verified"] is True
    assert proof["controller_cgroup_path_sha256"] == digest_path(boundary)
    assert proof["controller_process_cgroup_path_sha256"] == digest_path(controller_path)
    assert proof["worker_cgroup_path_sha256"] == digest_path(worker_path)
    assert proof["memory_max_bytes"] == setup.MEMORY
    assert (proof["cpu_quota"], proof["cpu_period"]) == (setup.CPU_QUOTA, setup.CPU_PERIOD)


def test_worker_cgroup_rejects_sibling_escape_and_mismatched_container_scope(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    expected_scope = f"docker-{CONTAINER_ID}.scope"
    sibling_scope = f"docker-{'b' * 64}.scope"
    _boundary, _controller, _worker, _inspected = prepare_cgroup_scope(
        monkeypatch,
        tmp_path,
        controller_relative=("system.slice", expected_scope, "init"),
        worker_relative=("system.slice", sibling_scope, "buildkit", "worker"),
    )

    with pytest.raises(setup.SetupError, match="worker_step_outside_bounded_builder"):
        setup.verify_worker_cgroup(CONTROLLER_PID, WORKER_PID)

    wrong_controller = tmp_path / "cgroup" / "system.slice" / sibling_scope / "init"
    wrong_controller.mkdir(parents=True)
    expected_worker = tmp_path / "cgroup" / "system.slice" / expected_scope / "worker"

    def cgroup_path(pid: int) -> Path:
        if pid == CONTROLLER_PID:
            return wrong_controller
        return expected_worker

    monkeypatch.setattr(setup, "cgroup_v2_path", cgroup_path)
    with pytest.raises(setup.SetupError, match="builder_controller_cgroup_scope_mismatch"):
        setup.verify_worker_cgroup(CONTROLLER_PID, WORKER_PID)


def test_worker_cgroup_rejects_unknown_ancestor_unbounded_scope_and_pid_mismatch(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    scope_name = f"docker-{CONTAINER_ID}.scope"
    _boundary, _controller, _worker, _inspected = prepare_cgroup_scope(
        monkeypatch,
        tmp_path,
        controller_relative=("unexpected.slice", "system.slice", scope_name, "init"),
        worker_relative=("system.slice", scope_name, "buildkit", "worker"),
    )
    with pytest.raises(setup.SetupError, match="builder_controller_cgroup_scope_mismatch"):
        setup.verify_worker_cgroup(CONTROLLER_PID, WORKER_PID)

    boundary = tmp_path / "cgroup" / "system.slice" / scope_name
    (boundary / "memory.max").write_text("max", encoding="ascii")

    def cgroup_path(pid: int) -> Path:
        if pid == CONTROLLER_PID:
            return boundary / "init"
        return boundary / "buildkit" / "worker"

    monkeypatch.setattr(setup, "cgroup_v2_path", cgroup_path)
    with pytest.raises(setup.SetupError, match="builder_cgroup_limits_unbounded_or_invalid"):
        setup.verify_worker_cgroup(CONTROLLER_PID, WORKER_PID)

    (boundary / "memory.max").write_text(str(setup.MEMORY), encoding="ascii")
    monkeypatch.setattr(setup, "container_host_pid", lambda _container_id: CONTROLLER_PID + 1)
    with pytest.raises(setup.SetupError, match="builder_container_pid_identity_mismatch"):
        setup.verify_worker_cgroup(CONTROLLER_PID, WORKER_PID)


def prepare_probe_files(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Redirect fixed probe paths into the pytest temporary directory."""
    monkeypatch.setattr(setup, "call", lambda *_args, **_kwargs: f"{IMAGE_ID}|linux/amd64".encode())
    monkeypatch.setattr(setup, "matching_probe_pids", lambda: [])
    monkeypatch.setattr(setup, "one_container_id", lambda: CONTAINER_ID)
    monkeypatch.setattr(setup, "container_host_pid", lambda _container_id: CONTROLLER_PID)
    monkeypatch.setattr(setup, "bounded_network_ids", lambda: [NETWORK_ID])
    monkeypatch.setattr(setup, "verify_bounded_network", lambda _network_id: BOUNDED_NETWORK)
    monkeypatch.setattr(setup, "verify_container_bounded_network", bounded_network_facts)
    monkeypatch.setattr(
        setup,
        "write_probe_context",
        lambda: (tmp_path, "b" * 64),
    )
    monkeypatch.setattr(setup, "PROBE_OUTPUT", tmp_path / "probe-output")


def test_worker_probe_checks_four_gib_before_starting_build(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A low fresh preflight prevents the worker-probe process from starting."""
    prepare_probe_files(monkeypatch, tmp_path)
    calls: list[dict[str, object]] = []

    def low_space(_expected_uuid: str, **kwargs: object) -> tuple[Path, int]:
        calls.append(kwargs)
        raise setup.SetupError("docker_root_below_4gib")

    monkeypatch.setattr(setup, "data_root", low_space)
    popen_called = False

    def unexpected_popen(*_args: object, **_kwargs: object) -> object:
        nonlocal popen_called
        popen_called = True
        raise AssertionError("low-space preflight must stop before Popen")

    monkeypatch.setattr(setup.subprocess, "Popen", unexpected_popen)

    with pytest.raises(setup.SetupError, match="docker_root_below_4gib"):
        setup.run_worker_cgroup_probe(123, tmp_path, EXPECTED_UUID)

    assert calls == [{"command_timeout": setup.PROBE_SPACE_COMMAND_TIMEOUT}]
    assert not popen_called


def test_worker_probe_rejects_wrong_controller_network_before_build(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    prepare_probe_files(monkeypatch, tmp_path)

    def wrong_network(*_args: object) -> dict[str, object]:
        raise setup.SetupError("builder_container_network_mismatch")

    monkeypatch.setattr(setup, "verify_container_bounded_network", wrong_network)
    popen_called = False

    def unexpected_popen(*_args: object, **_kwargs: object) -> object:
        nonlocal popen_called
        popen_called = True
        raise AssertionError("an invalid network must stop before Popen")

    monkeypatch.setattr(setup.subprocess, "Popen", unexpected_popen)
    with pytest.raises(setup.SetupError, match="builder_container_network_mismatch"):
        setup.run_worker_cgroup_probe(CONTROLLER_PID, tmp_path, EXPECTED_UUID)

    assert not popen_called


def test_worker_probe_cancels_when_space_falls_below_one_gib(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A low-space observation after the worker appears cancels the active build."""
    prepare_probe_files(monkeypatch, tmp_path)
    root = tmp_path / "docker-root"
    root.mkdir()
    data_root_calls: list[dict[str, object]] = []

    def observe_space(expected_uuid: str, **kwargs: object) -> tuple[Path, int]:
        assert expected_uuid == EXPECTED_UUID
        data_root_calls.append(kwargs)
        if len(data_root_calls) == 1:
            return root, setup.MIN_FREE
        if len(data_root_calls) == 2:
            assert kwargs["known_root"] == root
            assert kwargs["minimum_free_bytes"] == setup.STOP_FREE
            return root, setup.STOP_FREE
        raise setup.SetupError("docker_root_below_1gib")

    monkeypatch.setattr(setup, "data_root", observe_space)

    class FakeProcess:
        """Represent only the owned build process used by the cancellation path."""

        pid = 987654
        returncode: int | None = None

        def poll(self) -> int | None:
            return self.returncode

        def wait(self, timeout: float | None = None) -> int:
            assert timeout == 5
            self.returncode = -signal.SIGTERM
            return self.returncode

    process = FakeProcess()
    started = False

    def start_process(*_args: object, **_kwargs: object) -> FakeProcess:
        nonlocal started
        started = True
        return process

    monkeypatch.setattr(setup.subprocess, "Popen", start_process)

    def matching_pids() -> list[int]:
        if started and process.returncode is None:
            return [24680]
        return []

    monkeypatch.setattr(setup, "matching_probe_pids", matching_pids)
    monkeypatch.setattr(
        setup,
        "verify_worker_cgroup",
        lambda _controller, _worker: {"worker_cgroup_descendant": True},
    )
    killed_groups: list[tuple[int, int]] = []
    monkeypatch.setattr(
        setup.os,
        "killpg",
        lambda pid, sig: killed_groups.append((pid, sig)),
    )

    class FakeClock:
        """Advance the loop deterministically without wall-clock sleeps."""

        now = 0.0

        def monotonic(self) -> float:
            self.now += 0.2
            return self.now

        def sleep(self, seconds: float) -> None:
            self.now += seconds

    clock = FakeClock()
    monkeypatch.setattr(setup.time, "monotonic", clock.monotonic)
    monkeypatch.setattr(setup.time, "sleep", clock.sleep)

    with pytest.raises(setup.SetupError, match="docker_root_below_1gib"):
        setup.run_worker_cgroup_probe(123, root, EXPECTED_UUID)

    assert started
    assert len(data_root_calls) >= 3
    assert data_root_calls[0] == {"command_timeout": setup.PROBE_SPACE_COMMAND_TIMEOUT}
    assert killed_groups == [(process.pid, signal.SIGTERM)]
    assert process.returncode == -signal.SIGTERM


def test_worker_probe_rejects_success_reported_after_deadline(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A successful process poll after the fixed deadline cannot be accepted."""
    prepare_probe_files(monkeypatch, tmp_path)
    root = tmp_path / "docker-root"
    root.mkdir()
    monkeypatch.setattr(
        setup,
        "data_root",
        lambda _uuid, **_kwargs: (root, setup.MIN_FREE),
    )

    class FakeClock:
        """Advance through the full probe deadline without sleeping."""

        now = 0.0

        def monotonic(self) -> float:
            current = self.now
            self.now += 5.0
            return current

        def sleep(self, seconds: float) -> None:
            self.now += seconds

    clock = FakeClock()

    class LateSuccessProcess:
        """Report success only after the probe's 120-second deadline."""

        pid = 987655
        returncode: int | None = None

        def poll(self) -> int | None:
            if clock.now >= 120.0:
                self.returncode = 0
            return self.returncode

        def wait(self, timeout: float | None = None) -> int:
            assert timeout == 5
            return self.returncode or 0

    process = LateSuccessProcess()
    started = False

    def start_process(*_args: object, **_kwargs: object) -> LateSuccessProcess:
        nonlocal started
        started = True
        return process

    monkeypatch.setattr(setup.subprocess, "Popen", start_process)
    monkeypatch.setattr(
        setup,
        "matching_probe_pids",
        lambda: [24681] if started and process.returncode is None else [],
    )
    monkeypatch.setattr(
        setup,
        "verify_worker_cgroup",
        lambda _controller, _worker: {"worker_cgroup_descendant": True},
    )
    monkeypatch.setattr(setup.time, "monotonic", clock.monotonic)
    monkeypatch.setattr(setup.time, "sleep", clock.sleep)

    with pytest.raises(setup.SetupError, match="worker_probe_build_timeout"):
        setup.run_worker_cgroup_probe(123, root, EXPECTED_UUID)

    assert process.returncode == 0
