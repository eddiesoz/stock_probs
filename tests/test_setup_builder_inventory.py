from __future__ import annotations

import hashlib
import importlib.util
import json
import signal
import subprocess
import sys
from pathlib import Path

import pytest

SETUP_PATH = Path(__file__).resolve().parents[1] / "scripts/setup_bounded_buildkit.py"
SPEC = importlib.util.spec_from_file_location("r120_setup_builder", SETUP_PATH)
assert SPEC is not None and SPEC.loader is not None
setup = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(setup)
BUILD_PATH = Path(__file__).resolve().parents[1] / "scripts/bounded_docker_build.py"
BUILD_SPEC = importlib.util.spec_from_file_location("r120_bounded_docker_build", BUILD_PATH)
assert BUILD_SPEC is not None and BUILD_SPEC.loader is not None
bounded = importlib.util.module_from_spec(BUILD_SPEC)
BUILD_SPEC.loader.exec_module(bounded)


def test_setup_reads_the_tracked_adjacent_buildkit_config() -> None:
    assert SETUP_PATH.with_name("r120-buildkitd.toml") == setup.CONFIG_SOURCE
    assert setup.sha(setup.CONFIG_SOURCE) == setup.CONFIG_SHA


def test_setup_accepts_docker_reformatted_buildkit_config_with_exact_semantics() -> None:
    transformed = (
        b"\n[worker]\n\n  [worker.oci]\n"
        b"    gc = true\n"
        b"    max-parallelism = 1\n"
        b"    maxUsedSpace = 4294967296\n"
        b"    minFreeSpace = 4294967296\n"
        b"    reservedSpace = 1073741824\n"
    )

    assert setup.verify_active_buildkit_config(transformed, setup.CONFIG_SOURCE.read_bytes()) == (
        hashlib.sha256(transformed).hexdigest()
    )
    assert setup.sha(setup.CONFIG_SOURCE) == setup.CONFIG_SHA


@pytest.mark.parametrize(
    "transformed",
    [
        setup.CONFIG_SOURCE.read_bytes() + b"unexpected = true\n",
        setup.CONFIG_SOURCE.read_bytes().replace(b"max-parallelism = 1", b"max-parallelism = true"),
        setup.CONFIG_SOURCE.read_bytes().replace(
            b"reservedSpace = 1073741824", b"reservedSpace = 1"
        ),
        b"[worker.oci\ngc = true\n",
    ],
)
def test_setup_rejects_semantically_changed_or_malformed_buildkit_config(
    transformed: bytes,
) -> None:
    with pytest.raises(setup.SetupError, match="buildkit_config_mismatch"):
        setup.verify_active_buildkit_config(transformed, setup.CONFIG_SOURCE.read_bytes())


def test_setup_reads_driver_from_supported_buildx_json_listing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[list[str]] = []
    listing = b'{"Current":true,"Driver":"docker","Name":"default","Nodes":[]}\n'
    listing += b'{"Current":false,"Driver":"docker-container","Name":"r120-bounded","Nodes":[]}\n'

    def fake_capture(argv: list[str], *, max_bytes: int, timeout: float) -> bytes:
        calls.append(argv)
        assert max_bytes == setup.BUILDX_LISTING_MAX_BYTES
        assert timeout == setup.BUILDX_LISTING_TIMEOUT
        return listing

    monkeypatch.setattr(setup, "_capture_bounded_stdout", fake_capture)

    assert setup.buildx_driver() == "docker-container"
    assert calls == [[setup.DOCKER, "buildx", "ls", "--format", "json"]]


def _network_inspection(
    *,
    network_id: str = "c" * 64,
    name: str = setup.NETWORK_NAME,
    driver: str = "bridge",
    scope: str = "local",
    internal: str = "false",
    ipv6: str = "false",
    labels: dict[str, str] | None = None,
) -> bytes:
    expected_labels = labels or {setup.NETWORK_OWNER_LABEL: setup.NETWORK_OWNER_VALUE}
    return (
        f"{network_id}|{name}|{driver}|{scope}|{internal}|{ipv6}|"
        f"{json.dumps(expected_labels, separators=(',', ':'))}\n"
    ).encode()


def test_setup_creates_missing_owned_build_network_and_inspects_full_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    network_id = "c" * 64
    calls: list[list[str]] = []
    listings = [b"", f"{network_id}|{setup.NETWORK_NAME}\n".encode()]

    def fake_capture(argv: list[str], *, max_bytes: int, timeout: int) -> bytes:
        assert argv == [
            setup.DOCKER,
            "network",
            "ls",
            "--no-trunc",
            "--format",
            "{{.ID}}|{{.Name}}",
        ]
        assert max_bytes == setup.NETWORK_LIST_MAX_BYTES
        assert timeout == setup.NETWORK_LIST_TIMEOUT
        return listings.pop(0)

    def fake_call(
        argv: list[str], *, timeout: int = 30, env: dict[str, str] | None = None
    ) -> bytes:
        calls.append(argv)
        if argv[1:3] == ["network", "create"]:
            assert timeout == 30
            assert argv == [
                setup.DOCKER,
                "network",
                "create",
                "--driver",
                "bridge",
                "--ipv6=false",
                "--label",
                f"{setup.NETWORK_OWNER_LABEL}={setup.NETWORK_OWNER_VALUE}",
                setup.NETWORK_NAME,
            ]
            return f"{network_id}\n".encode()
        if argv[1:3] == ["network", "inspect"]:
            assert argv[-1] == network_id
            return _network_inspection()
        raise AssertionError(f"unexpected fixed command: {argv[1:3]}")

    monkeypatch.setattr(setup, "call", fake_call)
    monkeypatch.setattr(setup, "_capture_bounded_stdout", fake_capture)
    network = setup.ensure_bounded_network()

    assert network == {
        "name": setup.NETWORK_NAME,
        "id": network_id,
        "driver": "bridge",
        "scope": "local",
        "internal": False,
        "enable_ipv6": False,
        "owner_label": {setup.NETWORK_OWNER_LABEL: setup.NETWORK_OWNER_VALUE},
    }
    assert [argv[1:3] for argv in calls] == [
        ["network", "create"],
        ["network", "inspect"],
    ]


def test_setup_rejects_unowned_preexisting_build_network_without_adopting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    network_id = "c" * 64
    calls: list[list[str]] = []

    def fake_capture(argv: list[str], **_kwargs: object) -> bytes:
        assert argv[1:3] == ["network", "ls"]
        return f"{network_id}|{setup.NETWORK_NAME}\n".encode()

    def fake_call(argv: list[str], **_kwargs: object) -> bytes:
        calls.append(argv)
        if argv[1:3] == ["network", "inspect"]:
            return _network_inspection(labels={setup.NETWORK_OWNER_LABEL: "other"})
        raise AssertionError("an existing unowned network must never be mutated")

    monkeypatch.setattr(setup, "call", fake_call)
    monkeypatch.setattr(setup, "_capture_bounded_stdout", fake_capture)
    with pytest.raises(setup.SetupError, match="builder_network_ownership_or_profile_mismatch"):
        setup.ensure_bounded_network()

    assert [argv[1:3] for argv in calls] == [["network", "inspect"]]


@pytest.mark.parametrize(
    "inspection",
    [
        _network_inspection(driver="host"),
        _network_inspection(scope="swarm"),
        _network_inspection(internal="true"),
        _network_inspection(ipv6="true"),
        _network_inspection(labels={setup.NETWORK_OWNER_LABEL: "different"}),
    ],
)
def test_setup_rejects_wrong_build_network_profile(
    monkeypatch: pytest.MonkeyPatch, inspection: bytes
) -> None:
    with pytest.raises(setup.SetupError, match="builder_network_ownership_or_profile_mismatch"):
        monkeypatch.setattr(setup, "call", lambda *_args, **_kwargs: inspection)
        setup.verify_bounded_network("c" * 64)


def test_setup_verifies_exact_controller_network_attachment_and_no_published_ports(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    network_id = "c" * 64
    expected = {
        "name": setup.NETWORK_NAME,
        "id": network_id,
        "driver": "bridge",
        "scope": "local",
        "internal": False,
        "enable_ipv6": False,
        "owner_label": {setup.NETWORK_OWNER_LABEL: setup.NETWORK_OWNER_VALUE},
    }
    commands: list[list[str]] = []

    def fake_call(argv: list[str], **_kwargs: object) -> bytes:
        commands.append(argv)
        if argv[1:3] == ["network", "inspect"]:
            return _network_inspection()
        if argv[1:3] == ["container", "inspect"]:
            return (
                f"{setup.NETWORK_NAME}|{{}}|"
                f'{{"{setup.NETWORK_NAME}":{{"NetworkID":"{network_id}"}}}}\n'
            ).encode()
        raise AssertionError(f"unexpected fixed command: {argv[1:3]}")

    monkeypatch.setattr(setup, "call", fake_call)
    facts = setup.verify_container_bounded_network("a" * 64, expected)

    assert facts == {
        "builder_network": expected,
        "builder_container_networks": {setup.NETWORK_NAME: network_id},
    }
    assert [argv[1:3] for argv in commands] == [
        ["network", "inspect"],
        ["container", "inspect"],
    ]


@pytest.mark.parametrize(
    "container_projection",
    [
        'bridge|{}|{"bridge":{"NetworkID":"' + "c" * 64 + '"}}',
        'host|{}|{"r120-bounded-build":{"NetworkID":"' + "c" * 64 + '"}}',
        'r120-bounded-build|{"80/tcp":[{"HostPort":"8080"}]}|{"r120-bounded-build":{"NetworkID":"'
        + "c" * 64
        + '"}}',
        'r120-bounded-build|{}|{"r120-bounded-build":{"NetworkID":"' + "d" * 64 + '"}}',
        'r120-bounded-build|{}|{"bridge":{"NetworkID":"'
        + "c" * 64
        + '"},"r120-bounded-build":{"NetworkID":"'
        + "c" * 64
        + '"}}',
    ],
)
def test_setup_rejects_missing_wrong_or_unbounded_controller_network(
    monkeypatch: pytest.MonkeyPatch, container_projection: str
) -> None:
    expected = {
        "name": setup.NETWORK_NAME,
        "id": "c" * 64,
        "driver": "bridge",
        "scope": "local",
        "internal": False,
        "enable_ipv6": False,
        "owner_label": {setup.NETWORK_OWNER_LABEL: setup.NETWORK_OWNER_VALUE},
    }

    def fake_call(argv: list[str], **_kwargs: object) -> bytes:
        if argv[1:3] == ["network", "inspect"]:
            return _network_inspection()
        if argv[1:3] == ["container", "inspect"]:
            return f"{container_projection}\n".encode()
        raise AssertionError(f"unexpected fixed command: {argv[1:3]}")

    monkeypatch.setattr(setup, "call", fake_call)
    with pytest.raises(setup.SetupError, match="builder_container_network_mismatch"):
        setup.verify_container_bounded_network("a" * 64, expected)


@pytest.mark.parametrize(
    ("listing", "error"),
    [
        (b"", "builder_driver_listing_invalid"),
        (b"not-json\n", "builder_driver_listing_invalid"),
        (b'{"Driver":"docker-container"}\n', "builder_driver_listing_invalid"),
        (b'{"Name":"r120-bounded","Driver":3}\n', "builder_driver_listing_invalid"),
        (
            b'{"Name":"r120-bounded","Name":"r120-bounded","Driver":"docker-container"}\n',
            "builder_driver_listing_invalid",
        ),
        (
            b'{"Name":"r120-bounded","Driver":"docker-container"}\n'
            b'{"Name":"r120-bounded","Driver":"docker-container"}\n',
            "builder_driver_listing_invalid",
        ),
        (b'{"Name":"default","Driver":"docker"}\n', "builder_driver_mismatch"),
        (b'{"Name":"r120-bounded","Driver":"docker"}\n', "builder_driver_mismatch"),
    ],
)
def test_setup_rejects_invalid_or_unexpected_buildx_driver_listing(
    listing: bytes, error: str
) -> None:
    with pytest.raises(setup.SetupError, match=error):
        setup.verify_buildx_driver_list(listing)


def test_setup_driver_capture_accepts_output_at_exact_limit() -> None:
    output = setup._capture_bounded_stdout(
        [sys.executable, "-c", "import os; os.write(1, b'12345678')"],
        max_bytes=8,
        timeout=2,
    )

    assert output == b"12345678"


def test_setup_driver_capture_rejects_oversize_and_reaps_group(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_popen = setup.subprocess.Popen
    real_killpg = setup.os.killpg
    processes: list[subprocess.Popen[bytes]] = []
    signals: list[int] = []

    def tracked_popen(argv: list[str], **kwargs: object) -> subprocess.Popen[bytes]:
        assert kwargs["stdin"] == subprocess.DEVNULL
        assert kwargs["stdout"] == subprocess.PIPE
        assert kwargs["stderr"] == subprocess.DEVNULL
        assert kwargs["start_new_session"] is True
        assert kwargs["shell"] is False
        process = real_popen(argv, **kwargs)
        processes.append(process)
        return process

    def tracked_killpg(process_id: int, signum: int) -> None:
        signals.append(signum)
        real_killpg(process_id, signum)

    monkeypatch.setattr(setup.subprocess, "Popen", tracked_popen)
    monkeypatch.setattr(setup.os, "killpg", tracked_killpg)

    with pytest.raises(setup.SetupError, match="builder_driver_listing_too_large"):
        setup._capture_bounded_stdout(
            [sys.executable, "-c", "import os; os.write(1, b'x' * 64)"],
            max_bytes=8,
            timeout=2,
        )

    assert len(processes) == 1
    assert processes[0].returncode is not None
    assert signal.SIGTERM in signals
    assert signal.SIGKILL in signals


def test_setup_driver_capture_times_out_after_stdout_eof_and_reaps_group(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_popen = setup.subprocess.Popen
    real_killpg = setup.os.killpg
    processes: list[subprocess.Popen[bytes]] = []
    signals: list[int] = []

    def tracked_popen(argv: list[str], **kwargs: object) -> subprocess.Popen[bytes]:
        process = real_popen(argv, **kwargs)
        processes.append(process)
        return process

    def tracked_killpg(process_id: int, signum: int) -> None:
        signals.append(signum)
        real_killpg(process_id, signum)

    monkeypatch.setattr(setup.subprocess, "Popen", tracked_popen)
    monkeypatch.setattr(setup.os, "killpg", tracked_killpg)

    with pytest.raises(setup.SetupError, match="fixed_command_unavailable_or_timeout"):
        setup._capture_bounded_stdout(
            [sys.executable, "-c", "import os,time; os.close(1); time.sleep(10)"],
            max_bytes=8,
            timeout=0.2,
        )

    assert len(processes) == 1
    assert processes[0].returncode is not None
    assert signal.SIGTERM in signals
    assert signal.SIGKILL in signals


def test_setup_driver_capture_cancels_on_reader_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_popen = setup.subprocess.Popen
    real_read = setup.os.read
    real_killpg = setup.os.killpg
    processes: list[subprocess.Popen[bytes]] = []
    output_fds: set[int] = set()
    signals: list[int] = []

    def tracked_popen(argv: list[str], **kwargs: object) -> subprocess.Popen[bytes]:
        process = real_popen(argv, **kwargs)
        processes.append(process)
        assert process.stdout is not None
        output_fds.add(process.stdout.fileno())
        return process

    def failed_output_read(file_descriptor: int, size: int) -> bytes:
        if file_descriptor in output_fds:
            raise OSError("synthetic reader failure")
        return real_read(file_descriptor, size)

    def tracked_killpg(process_id: int, signum: int) -> None:
        signals.append(signum)
        real_killpg(process_id, signum)

    monkeypatch.setattr(setup.subprocess, "Popen", tracked_popen)
    monkeypatch.setattr(setup.os, "read", failed_output_read)
    monkeypatch.setattr(setup.os, "killpg", tracked_killpg)

    with pytest.raises(setup.SetupError, match="fixed_command_unavailable_or_timeout"):
        setup._capture_bounded_stdout(
            [sys.executable, "-c", "import os,time; os.write(1, b'x'); time.sleep(10)"],
            max_bytes=8,
            timeout=2,
        )

    assert len(processes) == 1
    assert processes[0].returncode is not None
    assert signal.SIGTERM in signals
    assert signal.SIGKILL in signals


def test_setup_skips_apt_when_exact_buildx_package_is_fully_installed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tool_hashes = {
        setup.APT: setup.APT_SHA,
        setup.DPKG_QUERY: setup.DPKG_QUERY_SHA,
        setup.DOCKER: setup.DOCKER_SHA,
        setup.FINDMNT: setup.FINDMNT_SHA,
        setup.PYTHON: setup.PYTHON_SHA,
    }
    monkeypatch.setattr(setup, "sha", lambda path: tool_hashes.get(str(path), ""))
    expected_query = [
        setup.DPKG_QUERY,
        "-W",
        "-f=${Version}|${db:Status-Abbrev}",
        "docker-buildx",
    ]
    calls: list[list[str]] = []

    def exact_installed(argv: list[str], **_kwargs: object) -> subprocess.CompletedProcess[bytes]:
        calls.append(argv)
        assert argv == expected_query
        return subprocess.CompletedProcess(
            argv,
            0,
            stdout=(setup.PACKAGE.split("=", 1)[1] + "|ii ").encode(),
        )

    monkeypatch.setattr(setup.subprocess, "run", exact_installed)

    setup.install_buildx()

    assert calls == [expected_query]


@pytest.mark.parametrize(
    "installed_version_status",
    [
        "0.29.1-0ubuntu1|ii ",
        "0.30.1-0ubuntu1|iU ",
    ],
)
def test_setup_does_not_skip_apt_for_wrong_or_unconfigured_buildx(
    monkeypatch: pytest.MonkeyPatch, installed_version_status: str
) -> None:
    tool_hashes = {
        setup.APT: setup.APT_SHA,
        setup.DPKG_QUERY: setup.DPKG_QUERY_SHA,
    }
    monkeypatch.setattr(setup, "sha", lambda path: tool_hashes.get(str(path), ""))
    query = [
        setup.DPKG_QUERY,
        "-W",
        "-f=${Version}|${db:Status-Abbrev}",
        "docker-buildx",
    ]
    simulation = [
        setup.APT,
        "-s",
        "install",
        "--no-upgrade",
        "--no-remove",
        "--no-install-recommends",
        setup.PACKAGE,
    ]
    calls: list[list[str]] = []

    def wrong_or_unconfigured(
        argv: list[str], **_kwargs: object
    ) -> subprocess.CompletedProcess[bytes]:
        calls.append(argv)
        if argv == query:
            return subprocess.CompletedProcess(argv, 0, stdout=installed_version_status.encode())
        assert argv == simulation
        return subprocess.CompletedProcess(argv, 0, stdout=b"")

    monkeypatch.setattr(setup.subprocess, "run", wrong_or_unconfigured)

    with pytest.raises(setup.SetupError, match="apt_plan_missing_pinned_package"):
        setup.install_buildx()

    assert calls == [query, simulation]


def test_setup_exact_installed_package_still_checks_native_tool_pins(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tool_hashes = {
        setup.APT: setup.APT_SHA,
        setup.DPKG_QUERY: setup.DPKG_QUERY_SHA,
        setup.DOCKER: "wrong-docker-hash",
    }
    monkeypatch.setattr(setup, "sha", lambda path: tool_hashes.get(str(path), ""))
    calls: list[list[str]] = []

    def exact_installed(argv: list[str], **_kwargs: object) -> subprocess.CompletedProcess[bytes]:
        calls.append(argv)
        return subprocess.CompletedProcess(
            argv,
            0,
            stdout=(setup.PACKAGE.split("=", 1)[1] + "|ii ").encode(),
        )

    monkeypatch.setattr(setup.subprocess, "run", exact_installed)

    with pytest.raises(setup.SetupError, match="native_tool_pin_mismatch"):
        setup.install_buildx()

    assert len(calls) == 1


def test_setup_snapshots_large_legacy_tag_inventory(monkeypatch: pytest.MonkeyPatch) -> None:
    rows = [
        f"sha256:{index + 10:064x}|stock-probs:pr-candidate-{index:012x}-{index + 1:012x}"
        for index in range(1, 506)
    ]
    expected_command = [
        setup.DOCKER,
        "image",
        "ls",
        "--no-trunc",
        "--format",
        "{{.ID}}|{{.Repository}}:{{.Tag}}",
    ]

    def fake_call(argv: list[str], **kwargs: object) -> bytes:
        assert argv == expected_command
        assert kwargs == {}
        return ("\n".join(rows) + "\n").encode()

    monkeypatch.setattr(setup, "call", fake_call)
    inventory = setup.legacy_task_image_inventory()

    assert len(inventory) == 505
    assert inventory["stock-probs:pr-candidate-000000000001-000000000002"] == (
        "sha256:" + f"{11:064x}"
    )
    assert inventory["stock-probs:pr-candidate-0000000001f9-0000000001fa"] == (
        "sha256:" + f"{515:064x}"
    )


@pytest.mark.parametrize(
    "output",
    [
        "github.com/docker/buildx 0.30.1 0.30.1-0ubuntu1\n",
        "github.com/docker/buildx v0.30.1\n",
        "github.com/docker/buildx v0.30.1 0.30.1-0ubuntu1\n",
    ],
)
def test_setup_accepts_exact_buildx_version_output(output: str) -> None:
    setup.verify_buildx_version_output(output)


@pytest.mark.parametrize(
    "output",
    [
        "github.com/docker/buildx v0.30.10",
        "github.com/docker/buildx 0.29.1 0.29.1-0ubuntu1",
        "github.com/docker/buildx-other 0.30.1 0.30.1-0ubuntu1",
        "github.com/docker/buildx 0.30.1 opaque-suffix",
        "github.com/docker/buildx 0.30.1 0.30.1-0ubuntu2",
        "github.com/docker/buildx 0.30.1 0.30.1-0ubuntu1 extra-token",
    ],
)
def test_setup_rejects_nonmatching_buildx_version_output(output: str) -> None:
    with pytest.raises(setup.SetupError, match="buildx_version_mismatch"):
        setup.verify_buildx_version_output(output)


def test_bounded_build_inventory_uses_docker_image_id_formatter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tag = "stock-probs:pr-candidate-000000000001-000000000002"
    image_id = "sha256:" + f"{11:064x}"
    expected_command = [
        bounded.DOCKER,
        "image",
        "ls",
        "--no-trunc",
        "--format",
        "{{.ID}}|{{.Repository}}:{{.Tag}}",
    ]

    def fake_checked(argv: list[str], **kwargs: object) -> bytes:
        assert argv == expected_command
        assert kwargs == {}
        return f"{image_id}|{tag}\n".encode()

    monkeypatch.setattr(bounded, "checked", fake_checked)
    assert bounded._image_inventory() == {tag: image_id}


def test_bounded_all_image_ids_uses_docker_image_id_formatter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    image_ids = ["sha256:" + f"{index:064x}" for index in (11, 12)]
    expected_command = [
        bounded.DOCKER,
        "image",
        "ls",
        "--all",
        "--no-trunc",
        "--format",
        "{{.ID}}",
    ]

    def fake_checked(argv: list[str], **kwargs: object) -> bytes:
        assert argv == expected_command
        assert kwargs == {}
        return ("\n".join(image_ids) + "\n").encode()

    monkeypatch.setattr(bounded, "checked", fake_checked)
    assert bounded._all_image_ids() == set(image_ids)


def test_setup_rejects_duplicate_legacy_tag() -> None:
    tag = "stock-probs:pr-candidate-000000000001-000000000002"
    rows = [f"sha256:{11:064x}|{tag}", f"sha256:{12:064x}|{tag}"]
    original = setup.call
    setup.call = lambda _argv, **_kwargs: ("\n".join(rows) + "\n").encode()
    try:
        with pytest.raises(setup.SetupError, match="task_image_inventory_tag_not_unique"):
            setup.legacy_task_image_inventory()
    finally:
        setup.call = original


def test_setup_tracks_preexisting_bounded_local_and_arm_tags_as_legacy() -> None:
    local_tag = "stock-probs:local-" + "a" * 12 + "-" + "b" * 12 + "-" + "c" * 12
    arm_runtime = "stock-probs-r-astra-120-arm64-runtime:20261009T123456Z"
    arm_frontend = "stock-probs-r-astra-120-arm64-frontend:20261009T123456Z"
    rows = [
        f"sha256:{11:064x}|{local_tag}",
        f"sha256:{12:064x}|{arm_runtime}",
        f"sha256:{13:064x}|{arm_frontend}",
    ]
    original = setup.call
    setup.call = lambda _argv, **_kwargs: ("\n".join(rows) + "\n").encode()
    try:
        assert setup.legacy_task_image_inventory() == {
            local_tag: "sha256:" + f"{11:064x}",
            arm_runtime: "sha256:" + f"{12:064x}",
            arm_frontend: "sha256:" + f"{13:064x}",
        }
    finally:
        setup.call = original


def test_setup_volume_check_does_not_traverse_root_only_cache_children(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "docker-root"
    root.mkdir()
    expected = str(root / "volumes" / setup.CACHE_VOLUME / "_data")
    mount = {
        "Type": "volume",
        "Name": setup.CACHE_VOLUME,
        "Source": expected,
        "Destination": "/var/lib/buildkit",
        "RW": True,
    }

    real_resolve = Path.resolve

    def guarded_resolve(self: Path, strict: bool = False) -> Path:
        if str(self) == expected:
            raise PermissionError("synthetic root-only Docker volume")
        return real_resolve(self, strict=strict)

    monkeypatch.setattr(Path, "resolve", guarded_resolve)

    def fake_call(argv: list[str], **_kwargs: object) -> bytes:
        if argv[:3] == [setup.DOCKER, "container", "inspect"]:
            return json.dumps([mount]).encode()
        if argv[:3] == [setup.DOCKER, "volume", "inspect"]:
            return f"local|{expected}".encode()
        if argv[0] == setup.FINDMNT:
            assert argv[-1] == str(root)
            return b"mount-uuid\n"
        raise AssertionError("unexpected fixed command")

    monkeypatch.setattr(setup, "call", fake_call)
    result = setup.inspect_cache_volume(root, "sha256:" + "a" * 64, "mount-uuid")
    assert result == {"name": setup.CACHE_VOLUME, "driver": "local", "mountpoint": expected}
