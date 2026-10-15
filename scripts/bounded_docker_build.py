#!/usr/bin/python3
from __future__ import annotations

import argparse
import fcntl
import fnmatch
import functools
import hashlib
import importlib.util
import json
import os
import platform
import pwd
import re
import selectors
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import threading
import time
import tomllib
from collections.abc import Callable, Iterator
from contextlib import contextmanager, suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import BinaryIO, ParamSpec, TypeVar

ROOT = Path(__file__).resolve().parents[1]
ROOT_STATE = Path("/var/lib/stock-probs/r120-buildkit-v1")
USER = pwd.getpwnam("james")
STATE = Path(USER.pw_dir) / ".local/state/stock-probs/r120-buildkit-v1"
CONFIG_FILE = ROOT_STATE / "buildkitd.toml"
DOCKER_CONFIG = STATE / "docker-config"
SETUP_RECEIPT = ROOT_STATE / "setup-receipt.json"
RUNS = STATE / "build-runs"
DOCKER = "/usr/bin/docker"
GIT = "/usr/bin/git"
FINDMNT = "/usr/bin/findmnt"
SOCKET = Path("/var/run/docker.sock")
DOCKER_SHA = "40cdaf7fd0f21089dd9e15b0c3a7dd7f2399027f010e366dac6304ae0615954a"
APT_SHA = "92ac3ad596716b94d82ece0355f29698a1ec580367b4ed26d8b5502e74c6fa7b"
DPKG_QUERY_SHA = "82a19acac53907f83faca7d6494289fe2d074514cf1b09933114635415c2e876"
GIT_SHA = "5516c9f362c29376ab9a499a33082f9f611941d8c75930c880e30ad109e39c9a"
PYTHON_SHA = "52e0a13e60a981d8c4b6478be2ba5176f69da07948a056bf49cf6f077e30cb41"
FINDMNT_SHA = "104f0c23a239d1582a052caa52e0bb81bf67ad1da974274dbdb470d23704015d"
CONFIG_SHA = "13cd7fdb92639849d02db6d2f9773ddb812ba777a07d409d49ddebad2e56cdb6"
BUILD_X_PACKAGE = "docker-buildx=0.30.1-0ubuntu1"
BUILDX_VERSION = "0.30.1"
BUILDX_PACKAGE_VERSION = "0.30.1-0ubuntu1"
DOCKERFILE_SHA = "f2dc019c11f6c981cb31bcb277446743c0e90b650932290c56322cdf76f8c9aa"
DOCKERIGNORE_SHA = "f70781201adb36c390bcb9155b9c4836046285ea842ad642a3cebaaaf475b210"
BUILDER = "r120-bounded"
BUILDER_NETWORK = "r120-bounded-build"
BUILDER_NETWORK_OWNER_LABEL = "io.signal-ledger.r120-bounded-builder"
BUILDER_NETWORK_OWNER_VALUE = "r120-bounded"
BUILDX_LISTING_MAX_BYTES = 65536
BUILDX_LISTING_TIMEOUT = 30
LOCAL_OBSERVATION_MAX_BYTES = 262144
LOCAL_BUILDKIT_STOP_GRACE_SECONDS = 5
LOCAL_BUILDKIT_STOP_TIMEOUT_SECONDS = 15
LOCAL_BUILDKIT_STOP_QUERY_TIMEOUT_SECONDS = 3
LOCAL_BUILDKIT_CGROUP_SYSTEM_SLICE = Path("/sys/fs/cgroup/system.slice")
LOCAL_BUILDKIT_CGROUP_MAX_DEPTH = 16
LOCAL_BUILDKIT_CGROUP_MAX_ENTRIES = 1024
LOCAL_BUILDKIT_CGROUP_MAX_PIDS = 4096
LOCAL_FAILURE_SCHEMA = "r120-bounded-local-build-failure-v1"
LOCAL_RECONCILIATION_SCHEMA = "r120-bounded-local-inflight-reconciliation-v1"
LOCAL_BUILD_PHASE_SCHEMA = "r120-bounded-local-build-phase-v1"
LOCAL_BUILD_PHASE_MAX_RAW_BYTES = 4 * 1024 * 1024
LOCAL_BUILD_PHASE_MAX_LINE_BYTES = 16 * 1024
LOCAL_BUILD_PHASE_MAX_FRAMES = 65536
LOCAL_BUILD_PHASE_MAX_VERTICES = 128
LOCAL_BUILD_PHASE_MAX_SKIPPED_VERTICES = 65_535
LOCAL_BUILD_PHASE_MAX_ARRAY_ITEMS = 256
LOCAL_BUILD_PHASE_MAX_ARTIFACT_BYTES = 64 * 1024
LOCAL_BUILD_PHASE_READ_CHUNK_BYTES = 8192
LOCAL_BUILD_PHASE_READER_JOIN_SECONDS = 0.25
LOCAL_BUILD_PHASE_READER_FINAL_JOIN_SECONDS = 0.1
LOCAL_BUILD_PHASE_MAX_INSTRUCTION_BYTES = 4096
LOCAL_BUILD_PHASE_MAX_VERTEX_DURATION_MS = 900_000
LOCAL_BUILD_PHASE_STAGES = {
    "opencode-amd64": "native_base_image",
    "opencode-arm64": "native_base_image",
    "opencode-assets": "native_asset_stage",
    "opencode-patched-builder": "native_builder_stage",
    "frontend-builder": "frontend_stage",
    "builder": "python_package_stage",
    "stage-6": "runtime_stage",
}
LOCAL_BUILD_PHASE_INTERNAL_NAMES = {
    "[internal] load build definition from Dockerfile": "dockerfile_definition",
    "[internal] load .dockerignore": "build_policy",
    "[internal] load build context": "source_context",
}
LOCAL_BUILD_PHASE_TOP_FIELDS = {"vertexes", "statuses", "logs", "warnings"}
LOCAL_BUILD_PHASE_VERTEX_FIELDS = {
    "digest",
    "inputs",
    "name",
    "started",
    "completed",
    "cached",
    "error",
    "progressGroup",
}
LOCAL_BUILD_PHASE_ARRAY_FIELDS = {
    "statuses": {
        "vertex",
        "id",
        "name",
        "current",
        "total",
        "timestamp",
        "started",
        "completed",
        "units",
    },
    "logs": {"vertex", "stream", "data", "timestamp"},
    "warnings": {
        "vertex",
        "level",
        "short",
        "detail",
        "url",
        "sourceInfo",
        "range",
    },
}
LOCAL_BUILD_PHASE_PATTERN = re.compile(
    r"^\[(?P<stage>[a-z0-9][a-z0-9-]{0,63}) "
    r"(?P<step>[1-9][0-9]{0,2})/(?P<count>[1-9][0-9]{0,2})\] "
    r"(?P<opcode>[A-Z]+)(?: (?P<instruction>.*))?$"
)
LOCAL_BUILD_PHASE_DIGEST_PATTERN = re.compile(r"sha256:[0-9a-f]{64}")
LOCAL_BUILD_PHASE_TIMESTAMP_PATTERN = re.compile(
    r"(?P<base>[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2})"
    r"(?:\.(?P<fraction>[0-9]{1,9}))?(?P<zone>Z|[+-][0-9]{2}:[0-9]{2})"
)
LOCAL_OBSERVATION_ROOT = Path("/var") / "tmp" / "r12r"
LOCAL_OBSERVATION_UUID = "54243c97-49f4-4cf6-a8cb-f6c0f3d48f4e"
_SCHEMA13_ROOTFS_INVENTORY_MAX_BYTES = 8 * 1024 * 1024
_SCHEMA13_ROOTFS_MAX_LAYERS = 128
_SCHEMA13_ROOTFS_CHUNK_SIZE = 32
_SCHEMA13_ROOTFS_CHUNK_MAX_BYTES = 512 * 1024
_SCHEMA13_ROOTFS_GLOBAL_TIMEOUT = 75.0
BUILDX_HISTORY_REF_PATTERN = re.compile(r"r120-bounded/r120-bounded0/[a-z0-9]{25}")
BUILDX_HISTORY_STEP_LIMIT = 64
CONTAINER_NAME = "/buildx_buildkit_r120-bounded0"
CACHE_VOLUME = "buildx_buildkit_r120-bounded0_state"
MIN_FREE = 4 * 1024**3
STOP_FREE = 1 * 1024**3
TIMEOUT = 900
COMPOSE_BUILD_TIMEOUT = 1800
POLL = 0.5
UUID_POLL = 2.0
MEMORY = 1280 * 1024 * 1024
SWAP = 2048 * 1024 * 1024
CPU_QUOTA = 100000
CPU_PERIOD = 100000
PIDS_LIMIT = 128
PROBE_MARKER_SHA256 = "31a12180b43e847a671b2afb8cfeb6ead4fbb23de6b4d14f5f0af7c1a3b01a98"
LEDGER_FILE = STATE / "candidate-ledger.json"
LEDGER_LOCK_FILE = STATE / "candidate-ledger.lock"
LOCAL_CURRENT_FILE = STATE / "local-current.json"
LEDGER_SCHEMA = "r120-bounded-candidate-ledger-v1"
LEDGER_ROLES = {"current", "recovery", "transient"}
TASK_TAG_PATTERNS = (
    re.compile(r"stock-probs:pr-candidate-[0-9a-f]{12}-[0-9a-f]{12}"),
    re.compile(r"stock-probs:schema12-base-[0-9a-f]{12}"),
    re.compile(r"stock-probs:schema13-recovery-[0-9a-f]{12}"),
    re.compile(r"stock-probs:local-[0-9a-f]{12}-[0-9a-f]{12}-[0-9a-f]{12}"),
    re.compile(r"stock-probs-[a-z0-9-]+-arm64-(?:runtime|frontend):[0-9]{8}T[0-9]{6}Z"),
    re.compile(r"ghcr\.io/jtmb/signal-ledger:sha-[0-9a-f]{40}"),
)
ARM64_COMPOSE_SHA256 = "18fc92d156e5196f9305819fd5a32a03c563e111246acfc8e5760d5cf0aae1de"
ENV = {
    "PATH": "/usr/bin:/bin",
    "LC_ALL": "C",
    "DOCKER_HOST": "unix:///var/run/docker.sock",
    "DOCKER_CONFIG": str(DOCKER_CONFIG),
}


class BuildError(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code
        self.secondary_errors: list[str] = []

    def add_secondary(self, code: str) -> None:
        if re.fullmatch(r"[a-z0-9_]{1,96}", code) is not None:
            self.secondary_errors.append(code)


_LEDGER_THREAD_GUARD = threading.RLock()
_LEDGER_LOCK_LOCAL = threading.local()
_LedgerArgs = ParamSpec("_LedgerArgs")
_LedgerResult = TypeVar("_LedgerResult")


@contextmanager
def _candidate_ledger_lock() -> Iterator[None]:
    _LEDGER_THREAD_GUARD.acquire()
    outermost = getattr(_LEDGER_LOCK_LOCAL, "depth", 0) == 0
    lock_fd: int | None = None
    locked = False
    try:
        if outermost:
            try:
                parent = LEDGER_LOCK_FILE.parent.lstat()
                if (
                    not stat.S_ISDIR(parent.st_mode)
                    or parent.st_uid != USER.pw_uid
                    or parent.st_mode & 0o077
                ):
                    raise BuildError("candidate_ledger_lock_directory_invalid")
                flags = os.O_CREAT | os.O_RDWR | getattr(os, "O_CLOEXEC", 0)
                flags |= getattr(os, "O_NOFOLLOW", 0)
                lock_fd = os.open(LEDGER_LOCK_FILE, flags, 0o600)
                lock_info = os.fstat(lock_fd)
                if (
                    not stat.S_ISREG(lock_info.st_mode)
                    or lock_info.st_uid != USER.pw_uid
                    or lock_info.st_mode & 0o077
                    or lock_info.st_nlink != 1
                ):
                    raise BuildError("candidate_ledger_lock_file_invalid")
                fcntl.flock(lock_fd, fcntl.LOCK_EX)
                locked = True
                _LEDGER_LOCK_LOCAL.fd = lock_fd
            except BuildError:
                raise
            except OSError as exc:
                raise BuildError("candidate_ledger_lock_unavailable") from exc
        _LEDGER_LOCK_LOCAL.depth = getattr(_LEDGER_LOCK_LOCAL, "depth", 0) + 1
        yield
    finally:
        if getattr(_LEDGER_LOCK_LOCAL, "depth", 0) > 0:
            _LEDGER_LOCK_LOCAL.depth -= 1
        if outermost and lock_fd is not None:
            if locked:
                with suppress(OSError):
                    fcntl.flock(lock_fd, fcntl.LOCK_UN)
            with suppress(OSError):
                os.close(lock_fd)
            with suppress(AttributeError):
                del _LEDGER_LOCK_LOCAL.fd
        _LEDGER_THREAD_GUARD.release()


def _ledger_serialized(
    function: Callable[_LedgerArgs, _LedgerResult],
) -> Callable[_LedgerArgs, _LedgerResult]:
    @functools.wraps(function)
    def wrapped(*args: _LedgerArgs.args, **kwargs: _LedgerArgs.kwargs) -> _LedgerResult:
        with _candidate_ledger_lock():
            return function(*args, **kwargs)

    return wrapped


def _worker_step_proof_valid(proof: object) -> bool:
    if not isinstance(proof, dict):
        return False
    return (
        proof.get("schema") == "r120-buildkit-run-cgroup-v1"
        and proof.get("status") == "passed"
        and proof.get("memory_max_bytes") == MEMORY
        and proof.get("cpu_quota") == CPU_QUOTA
        and proof.get("cpu_period") == CPU_PERIOD
        and proof.get("network_none") is True
        and proof.get("worker_cgroup_descendant") is True
        and proof.get("controller_cgroup_scope_verified") is True
        and _builder_network_proof_valid(proof)
        and isinstance(proof.get("probe_image_id"), str)
        and re.fullmatch(r"sha256:[0-9a-f]{64}", str(proof.get("probe_image_id"))) is not None
        and all(
            isinstance(proof.get(key), str)
            and re.fullmatch(r"[0-9a-f]{64}", str(proof.get(key))) is not None
            for key in (
                "probe_sha256",
                "probe_output_sha256",
                "worker_cgroup_path_sha256",
                "controller_cgroup_path_sha256",
                "controller_process_cgroup_path_sha256",
            )
        )
        and proof.get("probe_output_sha256") == PROBE_MARKER_SHA256
    )


def _builder_network_proof_valid(proof: dict[str, object]) -> bool:
    network = proof.get("builder_network")
    attachments = proof.get("builder_container_networks")
    if not isinstance(network, dict) or not isinstance(attachments, dict):
        return False
    network_id = network.get("id")
    return (
        network.keys()
        == {"name", "id", "driver", "scope", "enable_ipv6", "internal", "owner_label"}
        and network.get("name") == BUILDER_NETWORK
        and isinstance(network_id, str)
        and re.fullmatch(r"[0-9a-f]{64}", network_id) is not None
        and network.get("driver") == "bridge"
        and network.get("scope") == "local"
        and network.get("enable_ipv6") is False
        and network.get("internal") is False
        and network.get("owner_label") == {BUILDER_NETWORK_OWNER_LABEL: BUILDER_NETWORK_OWNER_VALUE}
        and attachments == {BUILDER_NETWORK: network_id}
    )


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def cmd(
    argv: list[str], *, timeout: float = 30, capture: bool = True
) -> subprocess.CompletedProcess[bytes]:
    environment = (
        ENV
        if argv[0] == DOCKER
        else {
            "PATH": "/usr/bin:/bin",
            "LC_ALL": "C",
            "GIT_OPTIONAL_LOCKS": "0",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": "/dev/null",
        }
    )
    try:
        return subprocess.run(  # noqa: S603 - Fixed absolute programs and internal argv lists; no shell.
            argv,
            cwd=ROOT,
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE if capture else subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=timeout,
            check=False,
            shell=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise BuildError("fixed_command_unavailable_or_timeout") from exc


def checked(argv: list[str], timeout: float = 30) -> bytes:
    result = cmd(argv, timeout=timeout)
    if result.returncode:
        raise BuildError("fixed_command_failed")
    return result.stdout


def _command_timeout(maximum: float, deadline: float | None) -> float:
    if deadline is None:
        return maximum
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise BuildError("bounded_build_timeout")
    return min(maximum, remaining)


def check_uuid(value: str) -> bool:
    return (
        len(value) == 36
        and all(c in "0123456789abcdef-" for c in value)
        and value[8] == value[13] == value[18] == value[23] == "-"
    )


def data_root(
    expected_uuid: str,
    expected_path: str | None = None,
    *,
    deadline: float | None = None,
) -> tuple[Path, int]:
    try:
        socket_info = SOCKET.lstat()
    except OSError as exc:
        raise BuildError("docker_socket_unavailable") from exc
    if stat.S_ISLNK(socket_info.st_mode) or not stat.S_ISSOCK(socket_info.st_mode):
        raise BuildError("docker_socket_unavailable")
    raw = checked(
        [DOCKER, "info", "--format", "{{.DockerRootDir}}"],
        timeout=_command_timeout(15, deadline),
    )
    text = raw.decode("utf-8", "strict").strip()
    if not text or "\n" in text or "\r" in text or not Path(text).is_absolute():
        raise BuildError("docker_root_unparseable")
    root = Path(text).resolve(strict=True)
    if expected_path and str(root) != expected_path:
        raise BuildError("docker_root_path_changed")
    observed = checked(
        [FINDMNT, "-n", "-o", "UUID", "--target", str(root)],
        timeout=_command_timeout(30, deadline),
    )
    if observed.decode("ascii", "strict").strip().lower() != expected_uuid:
        raise BuildError("docker_root_uuid_mismatch")
    return root, shutil.disk_usage(root).free


def verify_build_mount(expected_uuid: str, expected_path: str, *, deadline: float) -> None:
    try:
        root = Path(expected_path).resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise BuildError("build_mount_path_unavailable") from exc
    if not root.is_dir():
        raise BuildError("build_mount_path_invalid")
    if str(root) != expected_path:
        raise BuildError("build_mount_path_changed")
    try:
        observed = checked(
            [FINDMNT, "-n", "-o", "UUID", "--target", str(root)],
            timeout=_command_timeout(30, deadline),
        )
    except BuildError as exc:
        if exc.code == "bounded_build_timeout":
            raise
        raise BuildError("build_mount_lookup_failed") from exc
    try:
        observed_uuid = observed.decode("ascii", "strict").strip().lower()
    except UnicodeDecodeError as exc:
        raise BuildError("build_mount_uuid_unparseable") from exc
    if observed_uuid != expected_uuid:
        raise BuildError("build_mount_uuid_mismatch")


def check_space(paths: tuple[Path, ...], minimum: int) -> dict[str, int]:
    devices: set[int] = set()
    rows: dict[str, int] = {}
    for path in paths:
        try:
            device = path.stat().st_dev
            free = shutil.disk_usage(path).free
        except OSError as exc:
            raise BuildError("build_filesystem_unavailable") from exc
        if device in devices:
            continue
        devices.add(device)
        rows[str(path)] = free
        if free < minimum:
            raise BuildError("build_disk_floor_breached")
    return rows


def setup_receipt() -> dict[str, object]:
    try:
        receipt_info = SETUP_RECEIPT.lstat()
        state_info = ROOT_STATE.lstat()
    except OSError as exc:
        raise BuildError("setup_receipt_missing") from exc
    if (
        not stat.S_ISREG(receipt_info.st_mode)
        or receipt_info.st_uid != 0
        or receipt_info.st_mode & 0o022
        or not stat.S_ISDIR(state_info.st_mode)
        or state_info.st_uid != 0
        or state_info.st_mode & 0o022
    ):
        raise BuildError("setup_receipt_owner_or_mode_invalid")
    try:
        raw = SETUP_RECEIPT.read_bytes()
    except OSError as exc:
        raise BuildError("setup_receipt_missing") from exc
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise BuildError("setup_receipt_invalid") from exc
    if not isinstance(data, dict):
        raise BuildError("setup_receipt_invalid")
    legacy = data.get("legacy_task_image_inventory")
    if not isinstance(legacy, dict) or len(legacy) > 10000:
        raise BuildError("setup_legacy_inventory_invalid")
    if any(
        not isinstance(tag, str)
        or not _safe_tag(tag)
        or not isinstance(image_id, str)
        or re.fullmatch(r"sha256:[0-9a-f]{64}", image_id) is None
        for tag, image_id in legacy.items()
    ):
        raise BuildError("setup_legacy_inventory_invalid")
    profile = data.get("builder_container_profile", {})
    cache = data.get("buildkit_cache_profile", {})
    state_volume = data.get("buildkit_state_volume", {})
    worker_proof = data.get("worker_step_cgroup_proof", {})
    if (
        not isinstance(profile, dict)
        or not isinstance(cache, dict)
        or not isinstance(state_volume, dict)
        or not isinstance(worker_proof, dict)
    ):
        raise BuildError("setup_receipt_invalid")
    if not _worker_step_proof_valid(worker_proof):
        raise BuildError("worker_step_cgroup_limits_unproven")
    config = verify_installed_config()
    buildkit_image = data.get("buildkit_image")
    active_config_sha = data.get("active_buildkit_config_sha256")
    if (
        not isinstance(buildkit_image, str)
        or not re.fullmatch(r"moby/buildkit@sha256:[0-9a-f]{64}", buildkit_image)
        or data.get("verified_remote_manifest_sha256") != buildkit_image.rsplit("sha256:", 1)[1]
    ):
        raise BuildError("setup_receipt_buildkit_digest_invalid")
    if (
        data.get("status") != "configured"
        or data.get("builder") != BUILDER
        or data.get("builder_driver") != "docker-container"
        or data.get("docker_host") != "unix:///var/run/docker.sock"
        or data.get("builder_container_name") != CONTAINER_NAME
        or profile.get("memory_bytes") != MEMORY
        or profile.get("memory_plus_swap_bytes") != SWAP
        or profile.get("cpu_quota") != CPU_QUOTA
        or profile.get("cpu_period") != CPU_PERIOD
        or profile.get("pids_limit") != PIDS_LIMIT
        or profile.get("pids_scope")
        != "builder controller container only; worker-step PID ceiling is not inferred"
        or data.get("apt_package") != BUILD_X_PACKAGE
        or data.get("buildx_version") != "0.30.1"
        or data.get("docker_binary_sha256") != DOCKER_SHA
        or data.get("apt_binary_sha256") != APT_SHA
        or data.get("dpkg_query_binary_sha256") != DPKG_QUERY_SHA
        or data.get("python_binary_sha256") != PYTHON_SHA
        or data.get("findmnt_binary_sha256") != FINDMNT_SHA
        or data.get("buildkit_config_path") != str(CONFIG_FILE)
        or data.get("buildkit_config_sha256") != CONFIG_SHA
        or not isinstance(active_config_sha, str)
        or re.fullmatch(r"[0-9a-f]{64}", active_config_sha) is None
        or data.get("active_buildkit_config_semantically_verified") is not True
        or config != CONFIG_SHA
        or cache.get("reserved_space_bytes") != 1073741824
        or cache.get("maximum_cache_bytes") != 4294967296
        or cache.get("minimum_free_bytes") != 4294967296
        or cache.get("max_parallelism") != 1
        or state_volume.get("name") != CACHE_VOLUME
        or state_volume.get("driver") != "local"
        or not isinstance(state_volume.get("mountpoint"), str)
    ):
        raise BuildError("setup_receipt_contract_mismatch")
    return data


def verify_installed_config() -> str:
    try:
        info = CONFIG_FILE.lstat()
    except OSError as exc:
        raise BuildError("root_buildkit_config_missing") from exc
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_uid != 0
        or info.st_mode & 0o022
        or sha(CONFIG_FILE) != CONFIG_SHA
    ):
        raise BuildError("root_buildkit_config_pin_or_mode_mismatch")
    return CONFIG_SHA


def verify_active_buildkit_config(raw: bytes, expected_raw: bytes) -> str:
    try:
        actual = tomllib.loads(raw.decode("utf-8"))
        expected = tomllib.loads(expected_raw.decode("utf-8"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise BuildError("active_buildkit_config_changed") from exc
    if not _same_toml_value(actual, expected):
        raise BuildError("active_buildkit_config_changed")
    return hashlib.sha256(raw).hexdigest()


def _same_toml_value(actual: object, expected: object) -> bool:
    if type(actual) is not type(expected):
        return False
    if isinstance(actual, dict) and isinstance(expected, dict):
        return actual.keys() == expected.keys() and all(
            _same_toml_value(actual[key], expected[key]) for key in expected
        )
    if isinstance(actual, list) and isinstance(expected, list):
        return len(actual) == len(expected) and all(
            _same_toml_value(left, right) for left, right in zip(actual, expected, strict=True)
        )
    return actual == expected


def _unique_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate_json_key")
        result[key] = value
    return result


def _reject_json_constant(_value: str) -> object:
    raise ValueError("nonstandard_json_constant")


def _cancel_bounded_capture(process: subprocess.Popen[bytes]) -> None:
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    except OSError as exc:
        raise BuildError("builder_driver_cancel_unverified") from exc
    time.sleep(0.05)
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    except OSError as exc:
        raise BuildError("builder_driver_cancel_unverified") from exc
    try:
        process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        except OSError as exc:
            raise BuildError("builder_driver_cancel_unverified") from exc
        try:
            process.wait(timeout=2)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise BuildError("builder_driver_cancel_unverified") from exc
    except OSError as exc:
        raise BuildError("builder_driver_cancel_unverified") from exc
    for _ in range(20):
        try:
            os.killpg(process.pid, 0)
        except ProcessLookupError:
            return
        except OSError as exc:
            raise BuildError("builder_driver_cancel_unverified") from exc
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            return
        except OSError as exc:
            raise BuildError("builder_driver_cancel_unverified") from exc
        time.sleep(0.05)
    raise BuildError("builder_driver_cancel_unverified")


def _capture_bounded_stdout(argv: list[str], *, max_bytes: int, timeout: float) -> bytes:
    if max_bytes < 1 or timeout <= 0:
        raise BuildError("builder_driver_capture_limits_invalid")
    deadline = time.monotonic() + timeout
    try:
        process = subprocess.Popen(  # noqa: S603 - fixed driver command, no shell.
            argv,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env=ENV,
            start_new_session=True,
            shell=False,
        )
    except OSError as exc:
        raise BuildError("fixed_command_unavailable_or_timeout") from exc

    stream = process.stdout
    selector: selectors.BaseSelector | None = None
    completed = False
    output = bytearray()
    try:
        if stream is None:
            raise BuildError("builder_driver_capture_unavailable")
        selector = selectors.DefaultSelector()
        os.set_blocking(stream.fileno(), False)
        selector.register(stream, selectors.EVENT_READ)
        stdout_eof = False
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise BuildError("fixed_command_unavailable_or_timeout")
            if stdout_eof:
                return_code = process.poll()
                if return_code is not None:
                    completed = True
                    if return_code:
                        raise BuildError("fixed_command_failed")
                    return bytes(output)
                time.sleep(min(remaining, 0.05))
                continue
            for key, _ in selector.select(remaining):
                try:
                    chunk = os.read(
                        key.fileobj.fileno(),
                        min(8192, max_bytes - len(output) + 1),
                    )
                except BlockingIOError:
                    continue
                if not chunk:
                    selector.unregister(key.fileobj)
                    stdout_eof = True
                    continue
                if len(output) + len(chunk) > max_bytes:
                    raise BuildError("builder_driver_listing_too_large")
                output.extend(chunk)
    except BuildError:
        if not completed:
            _cancel_bounded_capture(process)
        raise
    except (OSError, ValueError) as exc:
        if not completed:
            _cancel_bounded_capture(process)
        raise BuildError("fixed_command_unavailable_or_timeout") from exc
    except BaseException:
        if not completed:
            _cancel_bounded_capture(process)
        raise
    finally:
        if selector is not None:
            with suppress(OSError):
                selector.close()
        if stream is not None:
            with suppress(OSError):
                stream.close()


def verify_buildx_driver_list(raw: bytes) -> str:
    if not raw or len(raw) > BUILDX_LISTING_MAX_BYTES:
        raise BuildError("builder_driver_listing_invalid")
    try:
        lines = raw.decode("utf-8", "strict").splitlines()
    except UnicodeDecodeError as exc:
        raise BuildError("builder_driver_listing_invalid") from exc
    if not lines or len(lines) > 64 or any(not line or len(line) > 16384 for line in lines):
        raise BuildError("builder_driver_listing_invalid")
    names: set[str] = set()
    target_drivers: list[str] = []
    for line in lines:
        try:
            row = json.loads(
                line,
                object_pairs_hook=_unique_json_object,
                parse_constant=_reject_json_constant,
            )
        except (json.JSONDecodeError, RecursionError, ValueError) as exc:
            raise BuildError("builder_driver_listing_invalid") from exc
        if not isinstance(row, dict):
            raise BuildError("builder_driver_listing_invalid")
        name = row.get("Name")
        driver = row.get("Driver")
        if (
            not isinstance(name, str)
            or not name
            or len(name) > 128
            or name.strip() != name
            or not isinstance(driver, str)
            or not driver
            or len(driver) > 128
            or driver.strip() != driver
            or name in names
        ):
            raise BuildError("builder_driver_listing_invalid")
        names.add(name)
        if name == BUILDER:
            target_drivers.append(driver)
    if len(target_drivers) != 1 or target_drivers[0] != "docker-container":
        raise BuildError("builder_driver_changed")
    return target_drivers[0]


def buildx_driver() -> str:
    raw = _capture_bounded_stdout(
        [DOCKER, "buildx", "ls", "--format", "json"],
        max_bytes=BUILDX_LISTING_MAX_BYTES,
        timeout=BUILDX_LISTING_TIMEOUT,
    )
    return verify_buildx_driver_list(raw)


def verify_buildx_version_output(output: str) -> None:
    version_pattern = re.escape(BUILDX_VERSION)
    if (
        re.fullmatch(
            rf"github\.com/docker/buildx v?{version_pattern}"
            rf"(?:\s+{re.escape(BUILDX_PACKAGE_VERSION)})?",
            output.strip(),
        )
        is None
    ):
        raise BuildError("buildx_version_changed")


def inspect_builder(data: dict[str, object]) -> None:
    version = checked([DOCKER, "buildx", "version"]).decode("utf-8", "replace")
    verify_buildx_version_output(version)
    buildx_driver()
    cid = str(data.get("builder_container_id", ""))
    if not re.fullmatch(r"[0-9a-f]{64}", cid):
        raise BuildError("builder_container_id_invalid")
    fmt = (
        "{{.Id}}|{{.Name}}|{{.Image}}|{{.HostConfig.Memory}}|"
        "{{.HostConfig.MemorySwap}}|{{.HostConfig.CpuQuota}}|"
        "{{.HostConfig.CpuPeriod}}|{{.HostConfig.PidsLimit}}|{{.State.Running}}"
    )
    fields = (
        checked([DOCKER, "container", "inspect", "--format", fmt, cid])
        .decode("ascii")
        .strip()
        .split("|")
    )
    if len(fields) != 9:
        raise BuildError("builder_container_inspection_invalid")
    actual = dict(
        zip(
            (
                "id",
                "name",
                "image",
                "memory",
                "swap",
                "quota",
                "period",
                "pids",
                "running",
            ),
            fields,
            strict=True,
        )
    )
    expected = {
        "id": cid,
        "name": CONTAINER_NAME,
        "image": data.get("buildkit_image_id"),
        "memory": str(MEMORY),
        "swap": str(SWAP),
        "quota": str(CPU_QUOTA),
        "period": str(CPU_PERIOD),
        "pids": str(PIDS_LIMIT),
        "running": "true",
    }
    if actual != expected:
        raise BuildError("builder_container_profile_changed")
    verify_builder_network(data, cid)
    active_config = checked([DOCKER, "exec", cid, "cat", "/etc/buildkit/buildkitd.toml"])
    verify_installed_config()
    try:
        expected_config = CONFIG_FILE.read_bytes()
    except OSError as exc:
        raise BuildError("root_buildkit_config_missing") from exc
    active_config_sha = verify_active_buildkit_config(active_config, expected_config)
    if active_config_sha != data.get("active_buildkit_config_sha256"):
        raise BuildError("active_buildkit_config_changed")
    verify_cache_volume(data, cid)


def _builder_generation(data: dict[str, object], *, timeout: float = 10) -> dict[str, object]:
    """Read the exact builder container identity and current start generation."""
    container_id = data.get("builder_container_id")
    image_id = data.get("buildkit_image_id")
    if (
        not isinstance(container_id, str)
        or re.fullmatch(r"[0-9a-f]{64}", container_id) is None
        or not isinstance(image_id, str)
        or re.fullmatch(r"sha256:[0-9a-f]{64}", image_id) is None
    ):
        raise BuildError("local_builder_generation_identity_invalid")
    fmt = (
        "{{.Id}}|{{.Name}}|{{.Image}}|{{.Created}}|{{.State.StartedAt}}|"
        "{{.RestartCount}}|{{.State.Running}}|{{.State.Pid}}"
    )
    try:
        fields = (
            checked(
                [DOCKER, "container", "inspect", "--format", fmt, container_id],
                timeout=timeout,
            )
            .decode("ascii", "strict")
            .strip()
            .split("|")
        )
    except UnicodeDecodeError as exc:
        raise BuildError("local_builder_generation_invalid") from exc
    if len(fields) != 8:
        raise BuildError("local_builder_generation_invalid")
    observed_id, name, observed_image, created, started, restart_text, running_text, pid_text = (
        fields
    )
    try:
        _parse_buildkit_utc(created)
        _parse_buildkit_utc(started)
    except BuildError as exc:
        raise BuildError("local_builder_generation_invalid") from exc
    if (
        observed_id != container_id
        or name != CONTAINER_NAME
        or observed_image != image_id
        or restart_text.isdecimal() is False
        or running_text not in {"true", "false"}
        or pid_text.isdecimal() is False
    ):
        raise BuildError("local_builder_generation_invalid")
    pid = int(pid_text)
    running = running_text == "true"
    if (running and pid <= 0) or (not running and pid != 0):
        raise BuildError("local_builder_generation_invalid")
    return {
        "container_id": observed_id,
        "name": name,
        "image_id": observed_image,
        "created": created,
        "started": started,
        "restart_count": int(restart_text),
        "running": running,
        "pid": pid,
    }


def _same_builder_generation(before: dict[str, object], after: dict[str, object]) -> bool:
    identity_fields = (
        "container_id",
        "name",
        "image_id",
        "created",
        "started",
        "restart_count",
    )
    return all(before.get(field) == after.get(field) for field in identity_fields)


def _cleanup_timeout(
    deadline: float, maximum: float = LOCAL_BUILDKIT_STOP_QUERY_TIMEOUT_SECONDS
) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise BuildError("local_builder_stop_deadline_exceeded")
    return min(maximum, remaining)


def _cleanup_checked(
    argv: list[str],
    deadline: float,
    *,
    maximum: float = LOCAL_BUILDKIT_STOP_QUERY_TIMEOUT_SECONDS,
) -> bytes:
    return checked(argv, timeout=_cleanup_timeout(deadline, maximum))


def _verify_builder_stop_target(
    setup: dict[str, object], expected_generation: dict[str, object], deadline: float
) -> None:
    """Recheck the setup-pinned host configuration and exact builder profile without exec."""
    container_id = expected_generation.get("container_id")
    if not isinstance(container_id, str) or re.fullmatch(r"[0-9a-f]{64}", container_id) is None:
        raise BuildError("local_builder_generation_identity_invalid")
    fmt = "|".join(
        (
            "{{.Id}}",
            "{{.Name}}",
            "{{.Image}}",
            "{{.HostConfig.Memory}}",
            "{{.HostConfig.MemorySwap}}",
            "{{.HostConfig.CpuQuota}}",
            "{{.HostConfig.CpuPeriod}}",
            "{{.HostConfig.PidsLimit}}",
            "{{.State.Running}}",
            "{{.State.Pid}}",
            "{{.Created}}",
            "{{.State.StartedAt}}",
            "{{.RestartCount}}",
        )
    )
    try:
        fields = (
            _cleanup_checked(
                [DOCKER, "container", "inspect", "--format", fmt, container_id], deadline
            )
            .decode("ascii", "strict")
            .strip()
            .split("|")
        )
    except UnicodeDecodeError as exc:
        raise BuildError("local_builder_profile_invalid") from exc
    profile = {
        "id": container_id,
        "name": CONTAINER_NAME,
        "image": setup.get("buildkit_image_id"),
        "memory": str(MEMORY),
        "swap": str(SWAP),
        "quota": str(CPU_QUOTA),
        "period": str(CPU_PERIOD),
        "pids": str(PIDS_LIMIT),
        "running": "true" if expected_generation.get("running") is True else "false",
        "pid": str(expected_generation.get("pid")),
        "created": expected_generation.get("created"),
        "started": expected_generation.get("started"),
        "restart_count": str(expected_generation.get("restart_count")),
    }
    if len(fields) != len(profile) or dict(zip(profile, fields, strict=True)) != profile:
        raise BuildError("local_builder_profile_changed")

    if verify_installed_config() != CONFIG_SHA:
        raise BuildError("local_builder_config_pin_changed")
    try:
        config_bytes = CONFIG_FILE.read_bytes()
    except OSError as exc:
        raise BuildError("local_builder_config_unavailable") from exc
    active_config_sha = setup.get("active_buildkit_config_sha256")
    if (
        sha(CONFIG_FILE) != CONFIG_SHA
        or setup.get("buildkit_config_sha256") != CONFIG_SHA
        or setup.get("active_buildkit_config_semantically_verified") is not True
        or not isinstance(active_config_sha, str)
        or re.fullmatch(r"[0-9a-f]{64}", active_config_sha) is None
        or not config_bytes
    ):
        raise BuildError("local_builder_config_pin_changed")

    def command(argv: list[str]) -> bytes:
        return _cleanup_checked(argv, deadline)

    verify_builder_network(setup, container_id, check=command)
    verify_cache_volume(setup, container_id, check=command)


def _local_buildkit_cgroup_proof(container_id: str) -> dict[str, object]:
    """Prove that the exact builder cgroup is absent or has no process/thread descendants."""
    if re.fullmatch(r"[0-9a-f]{64}", container_id) is None:
        raise BuildError("local_reconciliation_builder_identity_invalid")
    system_slice = LOCAL_BUILDKIT_CGROUP_SYSTEM_SLICE
    current = Path(system_slice.anchor)
    for part in system_slice.parts[1:]:
        current = current / part
        try:
            metadata = current.lstat()
        except OSError as exc:
            raise BuildError("local_reconciliation_cgroup_metadata_unavailable") from exc
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
            raise BuildError("local_reconciliation_cgroup_metadata_invalid")

    scope = system_slice / f"docker-{container_id}.scope"
    try:
        scope_metadata = scope.lstat()
    except FileNotFoundError:
        return {
            "status": "absent",
            "scope_path": str(scope),
            "directories_scanned": 0,
            "entries_scanned": 0,
            "process_ids_observed": 0,
        }
    except OSError as exc:
        raise BuildError("local_reconciliation_cgroup_metadata_unavailable") from exc
    if stat.S_ISLNK(scope_metadata.st_mode) or not stat.S_ISDIR(scope_metadata.st_mode):
        raise BuildError("local_reconciliation_cgroup_metadata_invalid")

    pending: list[tuple[Path, int]] = [(scope, 0)]
    directories_scanned = 0
    entries_scanned = 0
    process_ids_observed = 0
    while pending:
        directory, depth = pending.pop()
        if depth > LOCAL_BUILDKIT_CGROUP_MAX_DEPTH:
            raise BuildError("local_reconciliation_cgroup_depth_exceeded")
        try:
            directory_metadata = directory.lstat()
        except OSError as exc:
            raise BuildError("local_reconciliation_cgroup_metadata_unavailable") from exc
        if stat.S_ISLNK(directory_metadata.st_mode) or not stat.S_ISDIR(directory_metadata.st_mode):
            raise BuildError("local_reconciliation_cgroup_metadata_invalid")
        directories_scanned += 1
        if directories_scanned > LOCAL_BUILDKIT_CGROUP_MAX_ENTRIES:
            raise BuildError("local_reconciliation_cgroup_entries_exceeded")
        for filename in ("cgroup.procs", "cgroup.threads"):
            task_file = directory / filename
            try:
                descriptor = os.open(
                    task_file,
                    os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0),
                )
                with os.fdopen(descriptor, "rb") as stream:
                    task_metadata = os.fstat(stream.fileno())
                    if not stat.S_ISREG(task_metadata.st_mode):
                        raise BuildError("local_reconciliation_cgroup_metadata_invalid")
                    raw = stream.read(65537)
            except BuildError:
                raise
            except OSError as exc:
                raise BuildError("local_reconciliation_cgroup_metadata_unavailable") from exc
            if len(raw) > 65536:
                raise BuildError("local_reconciliation_cgroup_entries_exceeded")
            try:
                lines = raw.decode("ascii", "strict").splitlines()
            except UnicodeDecodeError as exc:
                raise BuildError("local_reconciliation_cgroup_metadata_invalid") from exc
            if any(
                len(line) > 10 or not line.isdecimal() or line.startswith("0") or int(line) <= 0
                for line in lines
            ):
                raise BuildError("local_reconciliation_cgroup_metadata_invalid")
            process_ids_observed += len(lines)
            if process_ids_observed > LOCAL_BUILDKIT_CGROUP_MAX_PIDS:
                raise BuildError("local_reconciliation_cgroup_entries_exceeded")
            if lines:
                raise BuildError("local_reconciliation_buildkit_worker_active")

        try:
            with os.scandir(directory) as children:
                for child in children:
                    entries_scanned += 1
                    if entries_scanned > LOCAL_BUILDKIT_CGROUP_MAX_ENTRIES:
                        raise BuildError("local_reconciliation_cgroup_entries_exceeded")
                    metadata = child.stat(follow_symlinks=False)
                    if stat.S_ISLNK(metadata.st_mode):
                        raise BuildError("local_reconciliation_cgroup_metadata_invalid")
                    if stat.S_ISDIR(metadata.st_mode):
                        pending.append((Path(child.path), depth + 1))
                    elif not stat.S_ISREG(metadata.st_mode):
                        raise BuildError("local_reconciliation_cgroup_metadata_invalid")
        except BuildError:
            raise
        except OSError as exc:
            raise BuildError("local_reconciliation_cgroup_metadata_unavailable") from exc

    return {
        "status": "empty",
        "scope_path": str(scope),
        "directories_scanned": directories_scanned,
        "entries_scanned": entries_scanned,
        "process_ids_observed": process_ids_observed,
    }


def _verify_local_stopped_builder(
    setup: dict[str, object], expected_generation: dict[str, object]
) -> dict[str, object]:
    """Bind fresh stopped-builder and empty-cgroup evidence to one setup generation."""
    deadline = time.monotonic() + LOCAL_BUILDKIT_STOP_TIMEOUT_SECONDS
    before = _builder_generation(setup, timeout=_cleanup_timeout(deadline, 10))
    if (
        not _same_builder_generation(expected_generation, before)
        or before.get("running") is not False
        or before.get("pid") != 0
    ):
        raise BuildError("local_reconciliation_builder_generation_unverified")
    _verify_builder_stop_target(setup, before, deadline)
    cgroup_proof = _local_buildkit_cgroup_proof(str(before["container_id"]))
    after = _builder_generation(setup, timeout=_cleanup_timeout(deadline, 5))
    if (
        not _same_builder_generation(before, after)
        or after.get("running") is not False
        or after.get("pid") != 0
    ):
        raise BuildError("local_reconciliation_builder_generation_unverified")
    return {
        "status": "verified_stopped_same_generation",
        "builder_container_id": after["container_id"],
        "current_generation": after,
        "generation": {key: after[key] for key in ("created", "started", "restart_count")},
        "worker_cgroup": cgroup_proof,
    }


def _stop_owned_builder_after_local_failure(
    setup: dict[str, object], expected_generation: dict[str, object]
) -> dict[str, object]:
    """Stop only the verified builder instance captured immediately before a local build."""
    deadline = time.monotonic() + LOCAL_BUILDKIT_STOP_TIMEOUT_SECONDS
    current = _builder_generation(setup, timeout=_cleanup_timeout(deadline, 10))
    if not _same_builder_generation(expected_generation, current):
        raise BuildError("local_builder_generation_changed")
    _verify_builder_stop_target(setup, current, deadline)
    checked_generation = _builder_generation(setup, timeout=_cleanup_timeout(deadline, 5))
    if not _same_builder_generation(expected_generation, checked_generation):
        raise BuildError("local_builder_generation_changed")
    if (
        checked_generation["running"] is not current["running"]
        or checked_generation["pid"] != current["pid"]
    ):
        raise BuildError("local_builder_state_changed_before_stop")

    stop_error: BuildError | None = None
    stop_attempted = checked_generation["running"] is True
    if stop_attempted:
        try:
            _cleanup_checked(
                [
                    DOCKER,
                    "container",
                    "stop",
                    "--time",
                    str(LOCAL_BUILDKIT_STOP_GRACE_SECONDS),
                    str(expected_generation["container_id"]),
                ],
                deadline,
                maximum=LOCAL_BUILDKIT_STOP_TIMEOUT_SECONDS,
            )
        except BuildError as exc:
            stop_error = exc

    stopped = _builder_generation(setup, timeout=_cleanup_timeout(deadline, 5))
    if not _same_builder_generation(expected_generation, stopped):
        raise BuildError("local_builder_generation_changed_after_stop") from stop_error
    if stopped["running"] is not False or stopped["pid"] != 0:
        raise BuildError("local_builder_stop_unverified") from stop_error
    cgroup_proof = _local_buildkit_cgroup_proof(str(stopped["container_id"]))
    result: dict[str, object] = {
        "status": "verified_stopped_same_generation",
        "builder_container_id": stopped["container_id"],
        "generation": {
            key: expected_generation[key] for key in ("created", "started", "restart_count")
        },
        "stop_grace_seconds": LOCAL_BUILDKIT_STOP_GRACE_SECONDS,
        "worker_cgroup": cgroup_proof,
        "stop_command_result": (
            "unavailable_but_state_verified"
            if stop_error is not None
            else "completed"
            if stop_attempted
            else "already_stopped"
        ),
    }
    if stop_error is not None:
        result["stop_error_code"] = stop_error.code
    return result


def verify_builder_network(
    data: dict[str, object],
    container_id: str,
    *,
    check: Callable[[list[str]], bytes] | None = None,
) -> None:
    proof = data.get("worker_step_cgroup_proof")
    if (
        re.fullmatch(r"[0-9a-f]{64}", container_id) is None
        or not isinstance(proof, dict)
        or not _builder_network_proof_valid(proof)
    ):
        raise BuildError("builder_network_receipt_invalid")
    network = proof["builder_network"]
    if not isinstance(network, dict):
        raise BuildError("builder_network_receipt_invalid")
    network_id = network["id"]
    if not isinstance(network_id, str):
        raise BuildError("builder_network_receipt_invalid")

    attached_format = (
        "{{.HostConfig.NetworkMode}}|"
        '{{if .HostConfig.PortBindings}}present{{else}}empty{{end}}{{"\\n"}}'
        "{{range $name, $network := .NetworkSettings.Networks}}"
        '{{$name}}|{{$network.NetworkID}}{{"\\n"}}{{end}}'
    )
    command = checked if check is None else check
    attached_raw = command(
        [DOCKER, "container", "inspect", "--format", attached_format, container_id]
    )
    try:
        attached_lines = attached_raw.decode("ascii", "strict").strip().splitlines()
    except UnicodeDecodeError as exc:
        raise BuildError("builder_network_attachment_invalid") from exc
    if (
        len(attached_lines) != 2
        or attached_lines[0].split("|") not in (["bridge", "empty"], [BUILDER_NETWORK, "empty"])
        or attached_lines[1] != f"{BUILDER_NETWORK}|{network_id}"
    ):
        raise BuildError("builder_network_attachment_mismatch")

    network_format = (
        "{{.Name}}|{{.Id}}|{{.Driver}}|{{.Scope}}|{{.EnableIPv6}}|{{.Internal}}|{{json .Labels}}"
    )
    try:
        network_fields = (
            command([DOCKER, "network", "inspect", "--format", network_format, BUILDER_NETWORK])
            .decode("ascii", "strict")
            .strip()
            .split("|", maxsplit=6)
        )
    except UnicodeDecodeError as exc:
        raise BuildError("builder_network_inspection_invalid") from exc
    if len(network_fields) != 7:
        raise BuildError("builder_network_inspection_invalid")
    name, observed_id, driver, scope, enable_ipv6, internal, labels_raw = network_fields
    try:
        labels = json.loads(
            labels_raw,
            object_pairs_hook=_unique_json_object,
            parse_constant=_reject_json_constant,
        )
    except (json.JSONDecodeError, RecursionError, ValueError) as exc:
        raise BuildError("builder_network_inspection_invalid") from exc
    if (
        name != BUILDER_NETWORK
        or observed_id != network_id
        or driver != "bridge"
        or scope != "local"
        or enable_ipv6 != "false"
        or internal != "false"
        or labels != {BUILDER_NETWORK_OWNER_LABEL: BUILDER_NETWORK_OWNER_VALUE}
    ):
        raise BuildError("builder_network_identity_mismatch")


def verify_cache_volume(
    data: dict[str, object],
    container_id: str,
    *,
    check: Callable[[list[str]], bytes] | None = None,
) -> None:
    command = checked if check is None else check
    raw_mounts = command(
        [DOCKER, "container", "inspect", "--format", "{{json .Mounts}}", container_id]
    )
    try:
        mounts = json.loads(raw_mounts)
    except json.JSONDecodeError as exc:
        raise BuildError("builder_mount_metadata_invalid") from exc
    if not isinstance(mounts, list):
        raise BuildError("builder_mount_metadata_invalid")
    state_mounts = [
        row
        for row in mounts
        if isinstance(row, dict) and row.get("Destination") == "/var/lib/buildkit"
    ]
    if len(state_mounts) != 1:
        raise BuildError("buildkit_state_volume_not_unique")
    mount = state_mounts[0]
    if (
        mount.get("Type") != "volume"
        or mount.get("Name") != CACHE_VOLUME
        or mount.get("RW") is not True
    ):
        raise BuildError("buildkit_state_volume_identity_mismatch")
    volume = (
        command(
            [
                DOCKER,
                "volume",
                "inspect",
                "--format",
                "{{.Driver}}|{{.Mountpoint}}",
                CACHE_VOLUME,
            ]
        )
        .decode("utf-8", "strict")
        .strip()
        .split("|", maxsplit=1)
    )
    if len(volume) != 2 or volume[0] != "local" or not volume[1].startswith("/"):
        raise BuildError("buildkit_state_volume_driver_mismatch")
    root_text = data.get("docker_root")
    state_volume = data.get("buildkit_state_volume")
    source_text = mount.get("Source")
    if (
        not isinstance(root_text, str)
        or not root_text.startswith("/")
        or not isinstance(state_volume, dict)
        or not isinstance(source_text, str)
        or not source_text.startswith("/")
    ):
        raise BuildError("buildkit_state_volume_path_invalid")
    try:
        root = Path(root_text).resolve(strict=True)
    except OSError as exc:
        raise BuildError("buildkit_state_volume_path_invalid") from exc
    expected_mountpoint = str(root / "volumes" / CACHE_VOLUME / "_data")
    if (
        source_text != expected_mountpoint
        or volume[1] != expected_mountpoint
        or state_volume.get("mountpoint") != expected_mountpoint
    ):
        raise BuildError("buildkit_state_volume_outside_or_changed")
    observed_uuid = (
        command([FINDMNT, "-n", "-o", "UUID", "--target", str(root)])
        .decode("ascii", "strict")
        .strip()
        .lower()
    )
    if observed_uuid != str(data.get("expected_docker_root_uuid", "")):
        raise BuildError("buildkit_state_volume_uuid_mismatch")


def verify_source(head: str, branch: str) -> None:
    pins = {
        Path(DOCKER): DOCKER_SHA,
        Path(GIT): GIT_SHA,
        Path("/usr/bin/python3"): PYTHON_SHA,
        Path(FINDMNT): FINDMNT_SHA,
        ROOT / "Dockerfile": DOCKERFILE_SHA,
        ROOT / ".dockerignore": DOCKERIGNORE_SHA,
    }
    if any(sha(path) != expected for path, expected in pins.items()):
        raise BuildError("source_or_tool_pin_mismatch")
    git = [GIT, "-c", f"safe.directory={ROOT}"]
    if checked([*git, "rev-parse", "HEAD"]).decode("ascii").strip() != head:
        raise BuildError("reviewed_head_mismatch")
    actual_branch = checked([*git, "branch", "--show-current"]).decode("utf-8", "strict").strip()
    if actual_branch != branch:
        raise BuildError("reviewed_branch_mismatch")
    if checked([*git, "status", "--porcelain", "--untracked-files=all"]).decode("utf-8", "strict"):
        raise BuildError("source_tree_not_clean")


def _context_sha256(context: Path, owner_uid: int) -> str:
    digest = hashlib.sha256()
    try:
        entries = sorted(context.rglob("*"))
    except OSError as exc:
        raise BuildError("candidate_context_unavailable") from exc
    if not context.is_dir() or context.is_symlink():
        raise BuildError("candidate_context_not_directory")
    denied = {
        ".env",
        "credentials",
        "credential",
        "credentials.json",
        "auth.json",
        "secrets",
        "secret",
        "tokens",
        "token",
    }
    denied_patterns = (
        "*.pem",
        "*.key",
        "*.p12",
        "*.pfx",
        "*.spbackup*",
        "*.db*",
        "*.sqlite*",
        "*.tfstate*",
        "*.tfvars*",
        "*.tfplan",
        "*.py[cod]",
    )
    if context.lstat().st_uid != owner_uid:
        raise BuildError("candidate_context_owner_or_type_invalid")
    for path in entries:
        relative_path = path.relative_to(context)
        parts = relative_path.parts
        if any(part.casefold() in denied for part in parts) or any(
            part.casefold().startswith(
                (".env.", "credentials.", "credential.", "secrets.", "secret.")
            )
            or any(fnmatch.fnmatchcase(part.casefold(), pattern) for pattern in denied_patterns)
            for part in parts
        ):
            raise BuildError("candidate_context_excluded_path")
        try:
            metadata = path.lstat()
        except OSError as exc:
            raise BuildError("candidate_context_unavailable") from exc
        if stat.S_ISLNK(metadata.st_mode):
            raise BuildError("candidate_context_symlink")
        if stat.S_ISDIR(metadata.st_mode):
            continue
        if not stat.S_ISREG(metadata.st_mode):
            raise BuildError("candidate_context_special_file")
        if metadata.st_uid != owner_uid:
            raise BuildError("candidate_context_owner_or_type_invalid")
        relative = relative_path.as_posix().encode("utf-8")
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        digest.update(metadata.st_size.to_bytes(8, "big"))
        try:
            with path.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
        except OSError as exc:
            raise BuildError("candidate_context_read_failed") from exc
    return digest.hexdigest()


def _safe_tag(tag: str) -> bool:
    return any(pattern.fullmatch(tag) for pattern in TASK_TAG_PATTERNS)


def _atomic_json(path: Path, data: dict[str, object]) -> None:
    if path == LEDGER_FILE and getattr(_LEDGER_LOCK_LOCAL, "depth", 0) < 1:
        raise BuildError("candidate_ledger_write_without_lock")
    payload = (json.dumps(data, sort_keys=True, indent=2) + "\n").encode()
    temporary = path.with_name(path.name + ".new")
    try:
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    except OSError as exc:
        with suppress(OSError):
            temporary.unlink(missing_ok=True)
        raise BuildError("candidate_ledger_write_failed") from exc


def _ledger_read(*, allow_inflight: bool = False) -> dict[str, object]:
    try:
        info = LEDGER_FILE.lstat()
    except OSError as exc:
        raise BuildError("candidate_ledger_missing") from exc
    if not stat.S_ISREG(info.st_mode) or info.st_uid != USER.pw_uid or info.st_mode & 0o077:
        raise BuildError("candidate_ledger_owner_or_mode_invalid")
    try:
        data = json.loads(LEDGER_FILE.read_bytes())
    except (OSError, json.JSONDecodeError) as exc:
        raise BuildError("candidate_ledger_invalid") from exc
    _validate_ledger_document(data, allow_inflight=allow_inflight)
    return data


def _reservation_image_id(tag: str) -> str:
    digest = hashlib.sha256(("r120-inflight\0" + tag).encode()).hexdigest()
    return "sha256:" + digest


def _read_private_file(
    path: Path,
    *,
    owner_uid: int,
    max_bytes: int,
    error_code: str,
    reject_group_write: bool = False,
) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise BuildError(error_code) from exc
    try:
        info = os.fstat(descriptor)
        forbidden_mode = 0o022 if reject_group_write else 0o077
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != owner_uid
            or info.st_mode & forbidden_mode
            or info.st_nlink != 1
            or info.st_size > max_bytes
        ):
            raise BuildError(error_code)
        chunks: list[bytes] = []
        remaining = max_bytes + 1
        while remaining:
            chunk = os.read(descriptor, min(65536, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        raw = b"".join(chunks)
        if len(raw) > max_bytes or len(raw) != info.st_size:
            raise BuildError(error_code)
        return raw
    except OSError as exc:
        raise BuildError(error_code) from exc
    finally:
        os.close(descriptor)


def _parse_buildkit_utc(value: object) -> datetime:
    if not isinstance(value, str) or not value or len(value) > 64:
        raise BuildError("failed_reservation_buildkit_history_invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise BuildError("failed_reservation_buildkit_history_invalid") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise BuildError("failed_reservation_buildkit_history_invalid")
    return parsed.astimezone(UTC)


def verify_failed_buildkit_history(
    raw: bytes, *, build_started: datetime, build_finished: datetime
) -> dict[str, object]:
    if not raw or len(raw) > BUILDX_LISTING_MAX_BYTES:
        raise BuildError("failed_reservation_buildkit_history_invalid")
    try:
        text = raw.decode("utf-8", "strict")
    except UnicodeDecodeError as exc:
        raise BuildError("failed_reservation_buildkit_history_invalid") from exc
    # Buildx emits JSON Lines here: one object per record and optionally one final LF.
    lines = text.split("\n")
    if lines[-1] == "":
        lines.pop()
    fields = {
        "cached_steps",
        "completed_at",
        "completed_steps",
        "created_at",
        "name",
        "ref",
        "status",
        "total_steps",
    }
    if not lines or len(lines) > 64 or any(not line or line.strip() != line for line in lines):
        raise BuildError("failed_reservation_buildkit_history_invalid")

    refs: set[str] = set()
    possible_matches: list[dict[str, object]] = []
    now = datetime.now(UTC)
    terminal_statuses = {"completed", "error", "canceled", "cancelled"}
    for line in lines:
        if len(line) > 16384:
            raise BuildError("failed_reservation_buildkit_history_invalid")
        try:
            row = json.loads(
                line,
                object_pairs_hook=_unique_json_object,
                parse_constant=_reject_json_constant,
            )
        except (json.JSONDecodeError, RecursionError, ValueError) as exc:
            raise BuildError("failed_reservation_buildkit_history_invalid") from exc
        if not isinstance(row, dict) or set(row) != fields:
            raise BuildError("failed_reservation_buildkit_history_invalid")
        ref = row.get("ref")
        name = row.get("name")
        status = row.get("status")
        if (
            not isinstance(ref, str)
            or BUILDX_HISTORY_REF_PATTERN.fullmatch(ref) is None
            or ref in refs
            or not isinstance(name, str)
            or re.fullmatch(r"[A-Za-z0-9._/-]{1,128}", name) is None
            or not isinstance(status, str)
            or status.casefold() not in terminal_statuses
        ):
            raise BuildError("failed_reservation_buildkit_history_invalid")
        refs.add(ref)

        created = _parse_buildkit_utc(row.get("created_at"))
        completed = _parse_buildkit_utc(row.get("completed_at"))
        completed_steps = row.get("completed_steps")
        cached_steps = row.get("cached_steps")
        total_steps = row.get("total_steps")
        if (
            completed < created
            or completed > now
            or not all(
                isinstance(value, int) and not isinstance(value, bool)
                for value in (completed_steps, cached_steps, total_steps)
            )
            or not 0 <= cached_steps <= completed_steps <= total_steps <= BUILDX_HISTORY_STEP_LIMIT
        ):
            raise BuildError("failed_reservation_buildkit_history_invalid")
        if name == "context" and build_started <= created <= build_finished:
            possible_matches.append(
                {
                    "ref": ref,
                    "status": status.casefold(),
                    "created_at": created.isoformat(),
                    "completed_at": completed.isoformat(),
                    "completed_steps": completed_steps,
                    "cached_steps": cached_steps,
                    "total_steps": total_steps,
                }
            )

    if len(possible_matches) != 1 or possible_matches[0]["status"] != "error":
        raise BuildError("failed_reservation_buildkit_record_not_unique_error")
    return possible_matches[0]


def _validate_ledger_document(data: object, *, allow_inflight: bool = False) -> None:
    if not isinstance(data, dict) or data.get("schema") != LEDGER_SCHEMA:
        raise BuildError("candidate_ledger_invalid")
    entries = data.get("entries")
    if not isinstance(entries, list) or len(entries) > 3:
        raise BuildError("candidate_ledger_limit_or_shape_invalid")
    seen_ids: set[str] = set()
    seen_tags: set[str] = set()
    for row in entries:
        if not isinstance(row, dict):
            raise BuildError("candidate_ledger_entry_invalid")
        image_id, tag, role, status = (
            row.get("image_id"),
            row.get("tag"),
            row.get("role"),
            row.get("status"),
        )
        revision = row.get("revision")
        context_hash = row.get("context_sha256")
        receipt_path = row.get("receipt_path")
        receipt_hash = row.get("receipt_sha256")
        if (
            not isinstance(image_id, str)
            or re.fullmatch(r"sha256:[0-9a-f]{64}", image_id) is None
            or not isinstance(tag, str)
            or not _safe_tag(tag)
            or not isinstance(revision, str)
            or re.fullmatch(r"(?:[0-9a-f]{40}|schema13-recovery-[0-9a-f]{64})", revision) is None
            or not isinstance(context_hash, str)
            or re.fullmatch(r"[0-9a-f]{64}", context_hash) is None
            or role not in LEDGER_ROLES
            or status not in {"complete", "inflight"}
            or tag in seen_tags
        ):
            raise BuildError("candidate_ledger_entry_invalid")
        seen_tags.add(tag)
        if status == "inflight":
            if (
                not allow_inflight
                or image_id != _reservation_image_id(tag)
                or receipt_path is not None
                or receipt_hash is not None
            ):
                raise BuildError("candidate_ledger_unresolved_inflight")
            continue
        if (
            not isinstance(receipt_path, str)
            or not receipt_path.startswith(str(RUNS) + "/")
            or not isinstance(receipt_hash, str)
            or re.fullmatch(r"[0-9a-f]{64}", receipt_hash) is None
            or image_id in seen_ids
        ):
            raise BuildError("candidate_ledger_entry_invalid")
        seen_ids.add(image_id)


def _image_inventory() -> dict[str, str]:
    raw = checked(
        [
            DOCKER,
            "image",
            "ls",
            "--no-trunc",
            "--format",
            "{{.ID}}|{{.Repository}}:{{.Tag}}",
        ]
    )
    inventory: dict[str, str] = {}
    for line in raw.decode("utf-8", "strict").splitlines():
        fields = line.split("|", 1)
        if len(fields) != 2 or re.fullmatch(r"sha256:[0-9a-f]{64}", fields[0]) is None:
            raise BuildError("image_inventory_invalid")
        if _safe_tag(fields[1]):
            if fields[1] in inventory:
                raise BuildError("task_image_tag_not_unique")
            inventory[fields[1]] = fields[0]
    return inventory


def _all_image_ids() -> set[str]:
    raw = checked([DOCKER, "image", "ls", "--all", "--no-trunc", "--format", "{{.ID}}"])
    image_ids: set[str] = set()
    for line in raw.decode("ascii", "strict").splitlines():
        if re.fullmatch(r"sha256:[0-9a-f]{64}", line) is None:
            raise BuildError("image_id_inventory_invalid")
        image_ids.add(line)
    return image_ids


def _container_uses_image_id(image_id: str) -> bool:
    raw = checked(
        [
            DOCKER,
            "container",
            "ls",
            "--all",
            "--no-trunc",
            "--quiet",
            "--filter",
            f"ancestor={image_id}",
        ]
    )
    container_ids = raw.decode("ascii", "strict").splitlines()
    if any(re.fullmatch(r"[0-9a-f]{64}", value) is None for value in container_ids):
        raise BuildError("arm64_cleanup_container_inventory_invalid")
    return bool(container_ids)


def _validate_arm64_build_receipt(row: dict[str, object]) -> None:
    path = Path(str(row.get("receipt_path", "")))
    try:
        info = path.lstat()
        raw = path.read_bytes()
        receipt = json.loads(raw)
    except (OSError, json.JSONDecodeError) as exc:
        raise BuildError("arm64_cleanup_receipt_invalid") from exc
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_uid != USER.pw_uid
        or info.st_mode & 0o077
        or hashlib.sha256(raw).hexdigest() != row.get("receipt_sha256")
        or not isinstance(receipt, dict)
        or receipt.get("schema") != "r120-bounded-image-build-v1"
        or receipt.get("status") != "built"
        or receipt.get("build_kind") != "arm64-compose"
        or receipt.get("candidate_role") != "transient"
        or receipt.get("candidate_tag") != row.get("tag")
        or receipt.get("image_id") != row.get("image_id")
        or receipt.get("revision_label") != row.get("revision")
        or receipt.get("context_sha256") != row.get("context_sha256")
        or receipt.get("platform") != "linux/arm64"
    ):
        raise BuildError("arm64_cleanup_receipt_mismatch")


def _inspect_arm64_image(tag: str, image_id: str) -> None:
    fmt = "{{.Id}}|{{.Os}}/{{.Architecture}}|{{json .RepoTags}}"
    fields = checked([DOCKER, "image", "inspect", "--format", fmt, tag])
    try:
        image_id_seen, platform_name, raw_tags = (
            fields.decode("utf-8", "strict").strip().split("|", 2)
        )
        repo_tags = json.loads(raw_tags)
    except (UnicodeDecodeError, ValueError, json.JSONDecodeError) as exc:
        raise BuildError("arm64_cleanup_image_metadata_invalid") from exc
    if (
        image_id_seen != image_id
        or platform_name != "linux/arm64"
        or not isinstance(repo_tags, list)
        or repo_tags != [tag]
    ):
        raise BuildError("arm64_cleanup_image_identity_mismatch")


@_ledger_serialized
def _plan_arm64_cleanup(tags: tuple[str, ...], revision: str) -> dict[str, object]:
    _validate_arm64_cleanup_args(tags, revision)
    setup = setup_receipt()
    ledger = _ledger_read(allow_inflight=True)
    entries = ledger["entries"]
    assert isinstance(entries, list)
    inventory = _image_inventory()
    rows = [row for row in entries if isinstance(row, dict) and row.get("tag") in tags]
    unrelated_inflight = [
        row
        for row in entries
        if isinstance(row, dict) and row.get("status") == "inflight" and row.get("tag") not in tags
    ]
    if unrelated_inflight:
        raise BuildError("arm64_cleanup_unrelated_inflight")
    if rows and (
        len(rows) != 2
        or {str(row.get("tag")) for row in rows} != set(tags)
        or any(row.get("role") != "transient" or row.get("revision") != revision for row in rows)
    ):
        raise BuildError("arm64_cleanup_ledger_mismatch")
    if not rows and any(tag in inventory for tag in tags):
        raise BuildError("arm64_cleanup_unregistered_tag_present")

    all_image_ids = _all_image_ids()
    registered_ids: list[str] = []
    remove_ids: list[str] = []
    for row in rows:
        tag = str(row["tag"])
        status = row["status"]
        if status == "complete":
            _validate_arm64_build_receipt(row)
            image_id = str(row["image_id"])
            registered_ids.append(image_id)
            current_id = inventory.get(tag)
            if current_id is not None:
                if current_id != image_id:
                    raise BuildError("arm64_cleanup_tag_rebound")
                _inspect_arm64_image(tag, image_id)
                if _container_uses_image_id(image_id):
                    raise BuildError("arm64_cleanup_image_in_use")
                remove_ids.append(image_id)
            elif image_id in all_image_ids:
                raise BuildError("arm64_cleanup_registered_image_untagged")
            elif _container_uses_image_id(image_id):
                raise BuildError("arm64_cleanup_image_in_use")
        elif status == "inflight":
            if row.get("image_id") != _reservation_image_id(tag):
                raise BuildError("arm64_cleanup_reservation_invalid")
            if tag in inventory:
                # An interrupted build has no immutable completed receipt to bind a loaded tag.
                raise BuildError("arm64_cleanup_inflight_image_unverified")
        else:
            raise BuildError("arm64_cleanup_ledger_status_invalid")
    if not rows:
        _verify_ledger_inventory(ledger, setup)
    return {
        "status": "ready",
        "tags": list(tags),
        "registered_image_ids": sorted(registered_ids),
        "remove_image_ids": sorted(remove_ids),
        "revision": revision,
    }


def _validate_arm64_cleanup_args(tags: tuple[str, ...], revision: str) -> None:
    if len(tags) != 2 or len(set(tags)) != 2 or re.fullmatch(r"[0-9a-f]{40}", revision) is None:
        raise BuildError("arm64_cleanup_identity_invalid")
    if any(not _safe_tag(tag) or "-arm64-" not in tag for tag in tags):
        raise BuildError("arm64_cleanup_tag_invalid")


@_ledger_serialized
def _ack_arm64_cleanup(
    tags: tuple[str, ...], revision: str, registered_ids: tuple[str, ...]
) -> dict[str, object]:
    _validate_arm64_cleanup_args(tags, revision)
    if len(set(registered_ids)) != len(registered_ids) or any(
        re.fullmatch(r"sha256:[0-9a-f]{64}", value) is None for value in registered_ids
    ):
        raise BuildError("arm64_cleanup_registered_ids_invalid")
    setup = setup_receipt()
    ledger = _ledger_read(allow_inflight=True)
    entries = ledger["entries"]
    assert isinstance(entries, list)
    rows = [row for row in entries if isinstance(row, dict) and row.get("tag") in tags]
    if rows and (
        len(rows) != 2
        or {str(row.get("tag")) for row in rows} != set(tags)
        or any(row.get("role") != "transient" or row.get("revision") != revision for row in rows)
    ):
        raise BuildError("arm64_cleanup_ledger_mismatch")
    if any(
        isinstance(row, dict) and row.get("status") == "inflight" and row.get("tag") not in tags
        for row in entries
    ):
        raise BuildError("arm64_cleanup_unrelated_inflight")
    expected_registered_ids: set[str] = set()
    for row in rows:
        if row.get("status") == "complete":
            _validate_arm64_build_receipt(row)
            expected_registered_ids.add(str(row["image_id"]))
        elif row.get("status") != "inflight" or row.get("image_id") != _reservation_image_id(
            str(row["tag"])
        ):
            raise BuildError("arm64_cleanup_ledger_status_invalid")
    if set(registered_ids) != expected_registered_ids:
        raise BuildError("arm64_cleanup_registered_ids_mismatch")
    if expected_registered_ids.intersection(_all_image_ids()):
        raise BuildError("arm64_cleanup_image_still_present")
    inventory = _image_inventory()
    if any(tag in inventory for tag in tags):
        raise BuildError("arm64_cleanup_tag_still_present")
    if any(_container_uses_image_id(image_id) for image_id in expected_registered_ids):
        raise BuildError("arm64_cleanup_image_in_use")
    ledger["entries"] = [row for row in entries if row not in rows]
    if rows:
        _atomic_json(LEDGER_FILE, ledger)
    _verify_ledger_inventory(ledger, setup)
    return {
        "status": "retired",
        "tags": list(tags),
        "removed_image_ids": sorted(expected_registered_ids),
        "revision": revision,
    }


def _expected_managed_inventory(
    ledger: dict[str, object], legacy_inventory: dict[str, str]
) -> dict[str, str]:
    entries = ledger["entries"]
    assert isinstance(entries, list)
    expected = dict(legacy_inventory)
    for row in entries:
        assert isinstance(row, dict)
        tag = str(row["tag"])
        if tag in expected:
            raise BuildError("candidate_tag_conflicts_with_held_baseline")
        expected[tag] = str(row["image_id"])
    return expected


def _verify_local_inflight_inventory(
    ledger: dict[str, object],
    setup: dict[str, object],
    *,
    tag: str,
    revision: str,
    context_hash: str,
) -> None:
    """Verify a retained local reservation without treating its placeholder as a loaded image."""
    row = _validate_local_inflight_identity(
        ledger, tag=tag, revision=revision, context_hash=context_hash
    )
    entries = ledger.get("entries")
    legacy = setup.get("legacy_task_image_inventory")
    if not isinstance(entries, list) or not isinstance(legacy, dict):
        raise BuildError("candidate_ledger_invalid")
    remaining = [candidate for candidate in entries if candidate is not row]
    _verify_ledger_inventory({"schema": LEDGER_SCHEMA, "entries": remaining}, setup)


def _verify_ledger_inventory(ledger: dict[str, object], setup: dict[str, object]) -> None:
    entries = ledger["entries"]
    assert isinstance(entries, list)
    legacy = setup.get("legacy_task_image_inventory")
    if not isinstance(legacy, dict):
        raise BuildError("setup_legacy_inventory_invalid")
    inventory = _image_inventory()
    expected = _expected_managed_inventory(ledger, legacy)
    if inventory != expected:
        raise BuildError("candidate_ledger_inventory_mismatch")
    for row in entries:
        assert isinstance(row, dict)
        fmt = '{{.Id}}|{{index .Config.Labels "org.opencontainers.image.revision"}}'
        fields = checked([DOCKER, "image", "inspect", "--format", fmt, str(row["image_id"])])
        observed_id, observed_revision = fields.decode("ascii", "strict").strip().split("|", 1)
        if observed_id != row["image_id"] or observed_revision != row["revision"]:
            raise BuildError("candidate_ledger_image_metadata_mismatch")
        _managed_build_receipt(row)


@_ledger_serialized
def _initialize_empty_ledger() -> None:
    if LEDGER_FILE.exists() or LEDGER_FILE.is_symlink():
        raise BuildError("candidate_ledger_already_exists")
    setup = setup_receipt()
    legacy = setup.get("legacy_task_image_inventory")
    if not isinstance(legacy, dict) or _image_inventory() != legacy:
        raise BuildError("candidate_ledger_bootstrap_requires_reviewed_inventory")
    _atomic_json(LEDGER_FILE, {"schema": LEDGER_SCHEMA, "entries": []})


def _managed_build_receipt(row: dict[str, object]) -> dict[str, object]:
    path = Path(str(row.get("receipt_path", "")))
    try:
        info = path.lstat()
        raw = path.read_bytes()
    except OSError as exc:
        raise BuildError("candidate_ledger_build_receipt_unavailable") from exc
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_uid != USER.pw_uid
        or info.st_mode & 0o077
        or hashlib.sha256(raw).hexdigest() != row.get("receipt_sha256")
    ):
        raise BuildError("candidate_ledger_build_receipt_mismatch")
    try:
        receipt = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise BuildError("candidate_ledger_build_receipt_invalid") from exc
    if (
        not isinstance(receipt, dict)
        or receipt.get("schema") != "r120-bounded-image-build-v1"
        or receipt.get("status") != "built"
        or receipt.get("image_id") != row.get("image_id")
        or receipt.get("candidate_tag") != row.get("tag")
        or receipt.get("revision_label") != row.get("revision")
        or receipt.get("context_sha256") != row.get("context_sha256")
        or receipt.get("candidate_role") != row.get("role")
    ):
        raise BuildError("candidate_ledger_build_receipt_contract_mismatch")
    return receipt


def _failed_candidate_run_directory(revision: str, tag: str, context_hash: str) -> Path:
    run_key = hashlib.sha256((tag + "\0" + context_hash).encode()).hexdigest()
    run_dir = RUNS / revision / run_key
    for directory in (RUNS, RUNS / revision, run_dir):
        try:
            info = directory.lstat()
        except OSError as exc:
            raise BuildError("failed_reservation_receipt_unavailable") from exc
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != USER.pw_uid or info.st_mode & 0o077:
            raise BuildError("failed_reservation_receipt_path_invalid")
    return run_dir


def _record_timeout_cancellation_contract(data: dict[str, object]) -> None:
    """Record the timeout contract only after process-group cancellation is verified."""
    if any(
        data.get(field) is True
        for field in ("process_group_cancel_verified", "build_deadline_cancel_verified")
    ):
        data["timeout_cancellation_contract"] = "bounded-cancel-v1"


def _failed_build_receipt(
    *,
    run_dir: Path,
    tag: str,
    revision: str,
    context_hash: str,
    role: str,
    expected_sha256: str,
    setup_sha256: str,
) -> tuple[dict[str, object], datetime, datetime]:
    raw = _read_private_file(
        run_dir / "build-receipt.json",
        owner_uid=USER.pw_uid,
        max_bytes=1024 * 1024,
        error_code="failed_reservation_receipt_unavailable",
    )
    observed_sha256 = hashlib.sha256(raw).hexdigest()
    if observed_sha256 != expected_sha256:
        raise BuildError("failed_reservation_receipt_sha256_mismatch")
    try:
        receipt = json.loads(
            raw,
            object_pairs_hook=_unique_json_object,
            parse_constant=_reject_json_constant,
        )
    except (json.JSONDecodeError, RecursionError, ValueError) as exc:
        raise BuildError("failed_reservation_receipt_invalid") from exc
    if not isinstance(receipt, dict):
        raise BuildError("failed_reservation_receipt_invalid")
    if (
        receipt.get("schema") != "r120-bounded-image-build-v1"
        or receipt.get("status") != "failed"
        or receipt.get("builder") != BUILDER
        or receipt.get("source_head") != revision
        or receipt.get("revision_label") != revision
        or receipt.get("context_sha256") != context_hash
        or receipt.get("candidate_tag") != tag
        or receipt.get("candidate_role") != role
        or receipt.get("setup_receipt_sha256") != setup_sha256
        or receipt.get("ledger_reservation_retained") is not True
        or any(key in receipt for key in ("image_id", "image_platform"))
    ):
        raise BuildError("failed_reservation_receipt_contract_mismatch")
    started = _parse_buildkit_utc(receipt.get("build_started_utc"))
    finished = _parse_buildkit_utc(receipt.get("finished_utc"))
    run_started = _parse_buildkit_utc(receipt.get("started_utc"))
    stage = receipt.get("stage")
    if stage == "fixed_command_unavailable_or_timeout":
        if (
            receipt.get("process_group_cancel_verified") is not True
            or "build_exit_code" in receipt
            or "build_finished_utc" in receipt
        ):
            raise BuildError("failed_reservation_receipt_contract_mismatch")
        build_finished = finished
    elif stage == "buildx_exit_nonzero":
        exit_code = receipt.get("build_exit_code")
        if (
            type(exit_code) is not int
            or exit_code == 0
            or "process_group_cancel_verified" in receipt
        ):
            raise BuildError("failed_reservation_receipt_contract_mismatch")
        build_finished = _parse_buildkit_utc(receipt.get("build_finished_utc"))
        if not started <= build_finished <= finished:
            raise BuildError("failed_reservation_receipt_artifact_or_time_invalid")
    elif stage == "build_timeout_after_900s":
        cancellation_fields = (
            "process_group_cancel_verified",
            "build_deadline_cancel_verified",
        )
        cancellation_values = [receipt[field] for field in cancellation_fields if field in receipt]
        cancellation_contract = receipt.get("timeout_cancellation_contract")
        if (
            type(receipt.get("timeout_seconds")) is not int
            or receipt["timeout_seconds"] != 900
            or (finished - started).total_seconds() < 900
            or "build_exit_code" in receipt
            or "build_finished_utc" in receipt
            or any(type(value) is not bool or value is not True for value in cancellation_values)
            or (
                "timeout_cancellation_contract" in receipt
                and (cancellation_contract != "bounded-cancel-v1" or not cancellation_values)
            )
        ):
            raise BuildError("failed_reservation_receipt_contract_mismatch")
        build_finished = finished
    else:
        raise BuildError("failed_reservation_receipt_contract_mismatch")
    if not run_started <= started <= build_finished <= finished <= datetime.now(
        UTC
    ) or os.path.lexists(run_dir / "image.iid"):
        raise BuildError("failed_reservation_receipt_artifact_or_time_invalid")
    return receipt, started, build_finished


def _current_setup_receipt_sha256() -> tuple[dict[str, object], str]:
    setup = setup_receipt()
    try:
        state_info = ROOT_STATE.lstat()
    except OSError as exc:
        raise BuildError("setup_receipt_missing") from exc
    if not stat.S_ISDIR(state_info.st_mode):
        raise BuildError("setup_receipt_owner_or_mode_invalid")
    raw = _read_private_file(
        SETUP_RECEIPT,
        owner_uid=state_info.st_uid,
        max_bytes=1024 * 1024,
        error_code="setup_receipt_missing",
        reject_group_write=True,
    )
    return setup, hashlib.sha256(raw).hexdigest()


def _failed_buildkit_history_record(
    build_started: datetime, build_finished: datetime
) -> dict[str, object]:
    raw = _capture_bounded_stdout(
        [
            DOCKER,
            "buildx",
            "history",
            "ls",
            "--builder",
            BUILDER,
            "--no-trunc",
            "--format",
            "json",
        ],
        max_bytes=BUILDX_LISTING_MAX_BYTES,
        timeout=BUILDX_LISTING_TIMEOUT,
    )
    return verify_failed_buildkit_history(
        raw, build_started=build_started, build_finished=build_finished
    )


def _read_local_observation_bytes(path: Path, expected_sha256: str) -> bytes:
    """Read one bounded private task artifact without following path links."""
    root = LOCAL_OBSERVATION_ROOT
    if (
        not path.is_absolute()
        or not path.is_relative_to(root)
        or re.fullmatch(r"[0-9a-f]{64}", expected_sha256) is None
    ):
        raise BuildError("local_reconciliation_observation_path_invalid")
    try:
        root_info = root.lstat()
    except OSError as exc:
        raise BuildError("local_reconciliation_observation_unavailable") from exc
    if (
        not stat.S_ISDIR(root_info.st_mode)
        or root_info.st_uid != USER.pw_uid
        or root_info.st_mode & 0o077
    ):
        raise BuildError("local_reconciliation_observation_path_invalid")
    _verify_local_observation_mount(root)
    parent = path.parent
    components = parent.relative_to(root).parts
    current = root
    for component in components:
        current = current / component
        try:
            info = current.lstat()
        except OSError as exc:
            raise BuildError("local_reconciliation_observation_unavailable") from exc
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != USER.pw_uid or info.st_mode & 0o077:
            raise BuildError("local_reconciliation_observation_path_invalid")
    raw = _read_private_file(
        path,
        owner_uid=USER.pw_uid,
        max_bytes=LOCAL_OBSERVATION_MAX_BYTES,
        error_code="local_reconciliation_observation_unavailable",
    )
    if hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise BuildError("local_reconciliation_observation_sha256_mismatch")
    return raw


def _verify_local_observation_mount(root: Path) -> None:
    try:
        observed = (
            checked([FINDMNT, "-n", "-o", "UUID", "--target", str(root)], timeout=10)
            .decode("ascii", "strict")
            .strip()
            .lower()
        )
    except (BuildError, UnicodeDecodeError) as exc:
        raise BuildError("local_reconciliation_observation_mount_unavailable") from exc
    if observed != LOCAL_OBSERVATION_UUID:
        raise BuildError("local_reconciliation_observation_mount_mismatch")


def _read_local_observation(path: Path, expected_sha256: str) -> tuple[dict[str, object], bytes]:
    raw = _read_local_observation_bytes(path, expected_sha256)
    try:
        document = json.loads(
            raw,
            object_pairs_hook=_unique_json_object,
            parse_constant=_reject_json_constant,
        )
    except (json.JSONDecodeError, RecursionError, ValueError) as exc:
        raise BuildError("local_reconciliation_observation_invalid") from exc
    if not isinstance(document, dict):
        raise BuildError("local_reconciliation_observation_invalid")
    return document, raw


def _parse_local_history_snapshot(
    raw: bytes, *, terminal_started: datetime, settled_at: datetime
) -> tuple[int, int]:
    if not raw or len(raw) > BUILDX_LISTING_MAX_BYTES:
        raise BuildError("local_reconciliation_history_invalid")
    try:
        lines = raw.decode("utf-8", "strict").split("\n")
    except UnicodeDecodeError as exc:
        raise BuildError("local_reconciliation_history_invalid") from exc
    if lines[-1] == "":
        lines.pop()
    fields = {
        "cached_steps",
        "completed_at",
        "completed_steps",
        "created_at",
        "name",
        "ref",
        "status",
        "total_steps",
    }
    if not lines or len(lines) > 64 or any(not line or line.strip() != line for line in lines):
        raise BuildError("local_reconciliation_history_invalid")
    seen_refs: set[str] = set()
    terminal_statuses = {"completed", "error", "canceled", "cancelled"}
    in_window = 0
    for line in lines:
        if len(line) > 16384:
            raise BuildError("local_reconciliation_history_invalid")
        try:
            row = json.loads(
                line,
                object_pairs_hook=_unique_json_object,
                parse_constant=_reject_json_constant,
            )
        except (json.JSONDecodeError, RecursionError, ValueError) as exc:
            raise BuildError("local_reconciliation_history_invalid") from exc
        if not isinstance(row, dict) or set(row) != fields:
            raise BuildError("local_reconciliation_history_invalid")
        ref = row.get("ref")
        name = row.get("name")
        status = row.get("status")
        if (
            not isinstance(ref, str)
            or BUILDX_HISTORY_REF_PATTERN.fullmatch(ref) is None
            or ref in seen_refs
            or not isinstance(name, str)
            or re.fullmatch(r"[A-Za-z0-9._/-]{1,128}", name) is None
            or not isinstance(status, str)
        ):
            raise BuildError("local_reconciliation_history_invalid")
        seen_refs.add(ref)
        if status.casefold() not in terminal_statuses:
            raise BuildError("local_reconciliation_buildkit_worker_active")
        created = _parse_buildkit_utc(row.get("created_at"))
        completed = _parse_buildkit_utc(row.get("completed_at"))
        completed_steps = row.get("completed_steps")
        cached_steps = row.get("cached_steps")
        total_steps = row.get("total_steps")
        if (
            completed < created
            or completed > settled_at
            or not all(
                isinstance(value, int) and not isinstance(value, bool)
                for value in (completed_steps, cached_steps, total_steps)
            )
            or not 0 <= cached_steps <= completed_steps <= total_steps <= BUILDX_HISTORY_STEP_LIMIT
        ):
            raise BuildError("local_reconciliation_history_invalid")
        if terminal_started <= created <= settled_at:
            in_window += 1
    return len(lines), in_window


def _assert_no_running_buildkit_history() -> dict[str, object]:
    raw = _capture_bounded_stdout(
        [
            DOCKER,
            "buildx",
            "history",
            "ls",
            "--builder",
            BUILDER,
            "--no-trunc",
            "--format",
            "json",
        ],
        max_bytes=BUILDX_LISTING_MAX_BYTES,
        timeout=BUILDX_LISTING_TIMEOUT,
    )
    now = datetime.now(UTC)
    count, active_count = _parse_local_history_snapshot(raw, terminal_started=now, settled_at=now)
    if active_count:
        raise BuildError("local_reconciliation_buildkit_worker_active")
    return {"row_count": count, "sha256": hashlib.sha256(raw).hexdigest()}


def _builder_status_line(document: dict[str, object], key: str) -> tuple[str, str, int]:
    record = document.get(key)
    if not isinstance(record, dict) or record.get("exit_code") != 0:
        raise BuildError("local_reconciliation_builder_observation_invalid")
    output = record.get("stdout")
    if not isinstance(output, str) or len(output) > 4096:
        raise BuildError("local_reconciliation_builder_observation_invalid")
    lines = output.splitlines()
    if len(lines) != 1:
        raise BuildError("local_reconciliation_builder_observation_invalid")
    fields = lines[0].split("|")
    if len(fields) < 3 or not re.fullmatch(r"[0-9a-f]{64}", fields[0]) or not fields[2].isdecimal():
        raise BuildError("local_reconciliation_builder_observation_invalid")
    return fields[0], fields[1], int(fields[2])


def _builder_status_fields(document: dict[str, object], key: str) -> list[str]:
    record = document.get(key)
    if not isinstance(record, dict) or record.get("exit_code") != 0:
        raise BuildError("local_reconciliation_builder_observation_invalid")
    output = record.get("stdout")
    if not isinstance(output, str) or len(output) > 4096:
        raise BuildError("local_reconciliation_builder_observation_invalid")
    lines = output.splitlines()
    if len(lines) != 1:
        raise BuildError("local_reconciliation_builder_observation_invalid")
    return lines[0].split("|")


def _validate_orphan_observations(
    *,
    tag: str,
    revision: str,
    context_hash: str,
    setup: dict[str, object],
    terminal: dict[str, object],
    terminal_sha256: str,
    preflight: dict[str, object],
    preflight_sha256: str,
    cancellation: dict[str, object],
    settled: dict[str, object],
    settled_sha256: str,
    cancellation_sha256: str,
    settled_path: Path,
) -> dict[str, object]:
    if (
        terminal.get("command") != ["./scripts/local-compose.sh", "build"]
        or terminal.get("exit_code") != 1
        or terminal.get("source_unchanged") is not True
        or terminal.get("reason") is not None
        or not isinstance(terminal.get("log_sha256"), str)
        or re.fullmatch(r"[0-9a-f]{64}", str(terminal.get("log_sha256"))) is None
        or type(terminal.get("log_bytes")) is not int
        or not 0 <= terminal["log_bytes"] <= 65536
    ):
        raise BuildError("local_reconciliation_terminal_mismatch")
    terminal_started = _parse_buildkit_utc(terminal.get("started"))
    terminal_finished = _parse_buildkit_utc(terminal.get("finished"))
    source_after = terminal.get("source_after")
    if (
        terminal_finished < terminal_started
        or not isinstance(source_after, dict)
        or source_after.get("context_sha256") != context_hash
        or not isinstance(source_after.get("files"), dict)
        or not source_after["files"]
        or len(source_after["files"]) > 4096
    ):
        raise BuildError("local_reconciliation_terminal_mismatch")
    source_files = source_after["files"]
    if any(
        not isinstance(path, str)
        or Path(path).is_absolute()
        or ".." in Path(path).parts
        or not isinstance(digest, str)
        or re.fullmatch(r"[0-9a-f]{64}", digest) is None
        for path, digest in source_files.items()
    ):
        raise BuildError("local_reconciliation_terminal_mismatch")

    build_result = preflight.get("build_result")
    preflight_time = _parse_buildkit_utc(preflight.get("recorded_at"))
    if (
        preflight.get("kind") != "read_only_failed_build_worker_preflight"
        or preflight.get("mutation") != "none"
        or preflight.get("build_terminal_sha256") != terminal_sha256
        or preflight.get("source_context_sha256") != context_hash
        or type(preflight.get("source_inputs")) is not int
        or preflight.get("source_inputs") != len(source_files)
        or not isinstance(build_result, dict)
        or build_result.get("started") != terminal.get("started")
        or build_result.get("finished") != terminal.get("finished")
        or build_result.get("exit_code") != terminal.get("exit_code")
        or build_result.get("source_unchanged") is not True
        or build_result.get("log_sha256") != terminal.get("log_sha256")
        or build_result.get("log_bytes") != terminal.get("log_bytes")
        or preflight_time < terminal_finished
    ):
        raise BuildError("local_reconciliation_preflight_mismatch")
    preflight_ledger_sha = preflight.get("ledger_sha256")
    preflight_ledger = preflight.get("ledger")
    if (
        not isinstance(preflight_ledger_sha, str)
        or re.fullmatch(r"[0-9a-f]{64}", preflight_ledger_sha) is None
        or not isinstance(preflight_ledger, dict)
        or preflight_ledger.get("schema") != LEDGER_SCHEMA
        or not isinstance(preflight_ledger.get("entries"), list)
    ):
        raise BuildError("local_reconciliation_preflight_mismatch")
    preflight_row = _validate_local_inflight_identity(
        preflight_ledger, tag=tag, revision=revision, context_hash=context_hash
    )

    builder_id = setup.get("builder_container_id")
    if not isinstance(builder_id, str) or re.fullmatch(r"[0-9a-f]{64}", builder_id) is None:
        raise BuildError("local_reconciliation_builder_identity_invalid")
    builder_inspect = preflight.get("builder_inspect")
    if not isinstance(builder_inspect, dict):
        raise BuildError("local_reconciliation_preflight_mismatch")
    preflight_builder_id, preflight_builder_state, preflight_builder_pid = _builder_status_line(
        {"builder": builder_inspect}, "builder"
    )
    if (
        preflight_builder_id != builder_id
        or preflight_builder_state != "running"
        or preflight_builder_pid <= 0
    ):
        raise BuildError("local_reconciliation_builder_identity_invalid")

    processes = preflight.get("processes")
    if not isinstance(processes, list) or not processes or len(processes) > 256:
        raise BuildError("local_reconciliation_worker_observation_invalid")
    workers: list[dict[str, object]] = []
    for process in processes:
        if not isinstance(process, dict):
            raise BuildError("local_reconciliation_worker_observation_invalid")
        process_status = process.get("status")
        if (
            isinstance(process_status, dict)
            and isinstance(process_status.get("Name"), str)
            and process_status["Name"].startswith("next-build")
        ):
            workers.append(process)
    if len(workers) != 1:
        raise BuildError("local_reconciliation_worker_observation_invalid")
    worker_pid = workers[0].get("pid")
    worker_cgroup = workers[0].get("cgroup")
    if (
        type(worker_pid) is not int
        or worker_pid <= 0
        or not isinstance(worker_cgroup, str)
        or not worker_cgroup.startswith(f"0::/system.slice/docker-{builder_id}.scope/buildkit/")
        or len(worker_cgroup) > 2048
    ):
        raise BuildError("local_reconciliation_worker_identity_invalid")

    cancel_started = _parse_buildkit_utc(cancellation.get("started"))
    cancel_finished = _parse_buildkit_utc(cancellation.get("finished"))
    if (
        cancellation.get("kind") != "exact_owned_failed_build_cancellation"
        or cancellation.get("preflight_sha256") != preflight_sha256
        or cancellation.get("builder_id") != builder_id
        or cancellation.get(f"owned_worker_{worker_pid}_absent") is not True
        or cancellation.get("unrelated_app_unchanged") is not True
        or cancellation.get("ledger_unchanged") is not True
        or cancellation.get("no_image_cache_or_ledger_mutation") is not True
        or cancel_started < preflight_time
        or cancel_finished < cancel_started
    ):
        raise BuildError("local_reconciliation_cancellation_mismatch")
    before_id, before_state, before_pid = _builder_status_line(cancellation, "builder_before")
    after_id, after_state, after_pid = _builder_status_line(cancellation, "builder_after")
    before_fields = _builder_status_fields(cancellation, "builder_before")
    after_fields = _builder_status_fields(cancellation, "builder_after")
    preflight_fields = _builder_status_fields({"builder": builder_inspect}, "builder")
    stop_result = cancellation.get("stop_result")
    if (
        before_id != builder_id
        or before_state != "running"
        or before_pid <= 0
        or after_id != builder_id
        or after_state != "exited"
        or after_pid != 0
        or not isinstance(stop_result, dict)
        or stop_result.get("exit_code") != 0
        or cancellation.get("unrelated_app_before") != cancellation.get("unrelated_app_after")
        or len(before_fields) != 7
        or len(after_fields) != 7
        or len(preflight_fields) != 6
        or before_fields[0] != after_fields[0]
        or before_fields[3:] != after_fields[3:]
        or before_fields[0] != preflight_fields[0]
        or before_fields[5] != preflight_fields[5]
        or before_fields[6] != setup.get("buildkit_image_id")
    ):
        raise BuildError("local_reconciliation_cancellation_mismatch")

    settled_at = _parse_buildkit_utc(settled.get("recorded_at"))
    history = settled.get("history")
    exact_tag = settled.get("exact_tag_inventory")
    if (
        settled.get("kind") != "post_cancellation_read_only_history_and_exact_tag"
        or settled.get("mutation") != "none"
        or settled.get("ledger_sha256") != preflight_ledger_sha
        or settled.get("ledger_entries") != len(preflight_ledger["entries"])
        or not isinstance(history, dict)
        or not isinstance(exact_tag, dict)
        or exact_tag.get("tag") != tag
        or exact_tag.get("absent") is not True
        or exact_tag.get("stdout") != ""
        or settled_at < cancel_finished
    ):
        raise BuildError("local_reconciliation_settled_readback_mismatch")
    history_path = history.get("path")
    history_sha256 = history.get("sha256")
    history_bytes = history.get("bytes")
    if (
        not isinstance(history_path, str)
        or not isinstance(history_sha256, str)
        or re.fullmatch(r"[0-9a-f]{64}", history_sha256) is None
        or type(history_bytes) is not int
        or not 1 <= history_bytes <= BUILDX_LISTING_MAX_BYTES
        or history.get("current_window_rows") != []
        or history.get("running_rows") != []
    ):
        raise BuildError("local_reconciliation_settled_readback_mismatch")
    history_raw = _read_local_observation_bytes(Path(history_path), history_sha256)
    if len(history_raw) != history_bytes:
        raise BuildError("local_reconciliation_history_invalid")
    history_count, window_count = _parse_local_history_snapshot(
        history_raw, terminal_started=terminal_started, settled_at=settled_at
    )
    if history_count != history.get("row_count") or window_count != 0:
        raise BuildError("local_reconciliation_history_window_mismatch")

    return {
        "terminal_sha256": terminal_sha256,
        "preflight_sha256": preflight_sha256,
        "cancellation_sha256": cancellation_sha256,
        "settled_sha256": settled_sha256,
        "history_sha256": history_sha256,
        "history_row_count": history_count,
        "terminal_started_utc": terminal_started.isoformat(),
        "terminal_finished_utc": terminal_finished.isoformat(),
        "preflight_recorded_utc": preflight_time.isoformat(),
        "cancellation_finished_utc": cancel_finished.isoformat(),
        "settled_recorded_utc": settled_at.isoformat(),
        "builder_container_id": builder_id,
        "observed_worker_pid": worker_pid,
        "inflight_row": preflight_row,
        "settled_path": str(settled_path),
    }


@_ledger_serialized
def _reconcile_local_inflight_reservation(
    *,
    tag: str,
    revision: str,
    context_hash: str,
    role: str,
    local_failure_receipt_sha256: str | None = None,
    terminal_observation: Path | None = None,
    terminal_sha256: str | None = None,
    preflight_observation: Path | None = None,
    preflight_sha256: str | None = None,
    cancellation_observation: Path | None = None,
    cancellation_sha256: str | None = None,
    settled_observation: Path | None = None,
    settled_sha256: str | None = None,
) -> dict[str, object]:
    """Remove one proven local-build reservation without treating it as a PR failure."""
    if role != "current":
        raise BuildError("local_inflight_role_invalid")
    local_mode = local_failure_receipt_sha256 is not None
    external_values = (
        terminal_observation,
        terminal_sha256,
        preflight_observation,
        preflight_sha256,
        cancellation_observation,
        cancellation_sha256,
        settled_observation,
        settled_sha256,
    )
    external_mode = all(value is not None for value in external_values)
    any_external_value = any(value is not None for value in external_values)
    if local_mode == external_mode or any_external_value != external_mode:
        raise BuildError("local_reconciliation_evidence_mode_invalid")
    if external_mode:
        _verify_local_observation_mount(LOCAL_OBSERVATION_ROOT)

    setup, setup_sha256 = _current_setup_receipt_sha256()
    ledger = _ledger_read(allow_inflight=True)
    row = _validate_local_inflight_identity(
        ledger, tag=tag, revision=revision, context_hash=context_hash
    )
    before_ledger_raw = _read_private_file(
        LEDGER_FILE,
        owner_uid=USER.pw_uid,
        max_bytes=4 * 1024 * 1024,
        error_code="candidate_ledger_invalid",
    )
    before_ledger_sha256 = hashlib.sha256(before_ledger_raw).hexdigest()
    if not isinstance(setup.get("legacy_task_image_inventory"), dict):
        raise BuildError("setup_legacy_inventory_invalid")

    evidence: dict[str, object]
    evidence_sha256: str
    if local_mode:
        if re.fullmatch(r"[0-9a-f]{64}", str(local_failure_receipt_sha256)) is None:
            raise BuildError("local_reconciliation_failure_receipt_sha256_invalid")
        run_dir = _failed_candidate_run_directory(revision, tag, context_hash)
        raw = _read_private_file(
            run_dir / "local-failure.json",
            owner_uid=USER.pw_uid,
            max_bytes=LOCAL_OBSERVATION_MAX_BYTES,
            error_code="local_reconciliation_failure_receipt_unavailable",
        )
        if hashlib.sha256(raw).hexdigest() != local_failure_receipt_sha256:
            raise BuildError("local_reconciliation_failure_receipt_sha256_mismatch")
        try:
            failure = json.loads(
                raw,
                object_pairs_hook=_unique_json_object,
                parse_constant=_reject_json_constant,
            )
        except (json.JSONDecodeError, RecursionError, ValueError) as exc:
            raise BuildError("local_reconciliation_failure_receipt_invalid") from exc
        backend = failure.get("backend_cancellation") if isinstance(failure, dict) else None
        builder_before = (
            failure.get("builder_generation_before") if isinstance(failure, dict) else None
        )
        failure_finished = (
            _parse_buildkit_utc(failure.get("finished_utc")) if isinstance(failure, dict) else None
        )
        if (
            not isinstance(failure, dict)
            or failure.get("schema") != LOCAL_FAILURE_SCHEMA
            or failure.get("status") != "failed"
            or failure.get("tag") != tag
            or failure.get("revision") != revision
            or failure.get("context_sha256") != context_hash
            or failure.get("role") != role
            or failure.get("builder") != BUILDER
            or failure.get("setup_receipt_sha256") != setup_sha256
            or failure.get("ledger_reservation_retained") is not True
            or failure.get("failure_cause") != "unproven"
            or failure.get("reservation_ledger_sha256") != before_ledger_sha256
            or failure.get("failure_ledger_sha256") != before_ledger_sha256
            or failure.get("build_completed") is not False
            or not isinstance(backend, dict)
            or not isinstance(builder_before, dict)
            or failure_finished is None
            or failure_finished > datetime.now(UTC)
        ):
            raise BuildError("local_reconciliation_failure_receipt_contract_mismatch")
        historical_tag_absent = failure.get("local_tag_and_placeholder_absent")
        historical_inventory_matches = failure.get("remaining_inventory_matches")
        reservation_error = failure.get("reservation_verification_error")
        backend_status = backend.get("status")
        if (
            not (
                historical_tag_absent is None
                or (type(historical_tag_absent) is bool and historical_tag_absent is True)
            )
            or not (
                historical_inventory_matches is None
                or (
                    type(historical_inventory_matches) is bool
                    and historical_inventory_matches is True
                )
            )
            or reservation_error not in (None, "fixed_command_unavailable_or_timeout")
            or backend_status not in {"verified_stopped_same_generation", "unverified"}
        ):
            raise BuildError("local_reconciliation_failure_receipt_contract_mismatch")
        backend_generation = backend.get("generation")
        if (
            set(builder_before)
            != {
                "container_id",
                "name",
                "image_id",
                "created",
                "started",
                "restart_count",
                "running",
                "pid",
            }
            or builder_before.get("name") != CONTAINER_NAME
            or builder_before.get("image_id") != setup.get("buildkit_image_id")
            or builder_before.get("container_id") != setup.get("builder_container_id")
            or not isinstance(builder_before.get("container_id"), str)
            or re.fullmatch(r"[0-9a-f]{64}", str(builder_before.get("container_id"))) is None
            or type(builder_before.get("restart_count")) is not int
            or builder_before.get("restart_count", -1) < 0
        ):
            raise BuildError("local_reconciliation_failure_receipt_contract_mismatch")
        _parse_buildkit_utc(builder_before.get("created"))
        _parse_buildkit_utc(builder_before.get("started"))
        if (
            builder_before.get("running") is not True
            or type(builder_before.get("pid")) is not int
            or builder_before.get("pid", 0) <= 0
        ):
            raise BuildError("local_reconciliation_failure_receipt_contract_mismatch")
        if backend_status == "verified_stopped_same_generation":
            if (
                backend.get("builder_container_id") != builder_before.get("container_id")
                or backend.get("stop_grace_seconds") != LOCAL_BUILDKIT_STOP_GRACE_SECONDS
                or not isinstance(backend_generation, dict)
                or any(
                    builder_before.get(source_field) != backend_generation.get(target_field)
                    for source_field, target_field in (
                        ("created", "created"),
                        ("started", "started"),
                        ("restart_count", "restart_count"),
                    )
                )
            ):
                raise BuildError("local_reconciliation_failure_receipt_contract_mismatch")
        elif (
            backend.get("error_code") != "fixed_command_unavailable_or_timeout"
            or reservation_error != "fixed_command_unavailable_or_timeout"
            or failure.get("primary_error_code") != "bounded_build_timeout_cancel_unverified"
        ):
            raise BuildError("local_reconciliation_failure_receipt_contract_mismatch")
        if backend_status == "unverified":
            secondary_errors = failure.get("secondary_error_codes")
            if (
                not isinstance(secondary_errors, list)
                or not secondary_errors
                or any(
                    error != "fixed_command_unavailable_or_timeout" for error in secondary_errors
                )
            ):
                raise BuildError("local_reconciliation_failure_receipt_contract_mismatch")
        evidence = {
            "mode": "local_failure_receipt",
            "failure_receipt_sha256": local_failure_receipt_sha256,
            "failure_finished_utc": failure_finished.isoformat(),
            "primary_error_code": failure.get("primary_error_code"),
            "backend_cancellation": backend,
            "historical_buildkit_terminal": "unavailable",
            "historical_tag_absence": "passed" if historical_tag_absent is True else "unavailable",
            "historical_inventory_match": "passed"
            if historical_inventory_matches is True
            else "unavailable",
        }
        evidence_sha256 = str(local_failure_receipt_sha256)
    else:
        if any(value is None for value in external_values):
            raise BuildError("local_reconciliation_evidence_mode_invalid")
        if (
            terminal_observation is None
            or terminal_sha256 is None
            or preflight_observation is None
            or preflight_sha256 is None
            or cancellation_observation is None
            or cancellation_sha256 is None
            or settled_observation is None
            or settled_sha256 is None
        ):
            raise BuildError("local_reconciliation_evidence_mode_invalid")
        terminal, _terminal_raw = _read_local_observation(terminal_observation, terminal_sha256)
        preflight, _preflight_raw = _read_local_observation(preflight_observation, preflight_sha256)
        cancellation, _cancellation_raw = _read_local_observation(
            cancellation_observation, cancellation_sha256
        )
        settled, _settled_raw = _read_local_observation(settled_observation, settled_sha256)
        evidence = _validate_orphan_observations(
            tag=tag,
            revision=revision,
            context_hash=context_hash,
            setup=setup,
            terminal=terminal,
            terminal_sha256=terminal_sha256,
            preflight=preflight,
            preflight_sha256=preflight_sha256,
            cancellation=cancellation,
            cancellation_sha256=cancellation_sha256,
            settled=settled,
            settled_sha256=settled_sha256,
            settled_path=settled_observation,
        )
        if preflight.get("ledger_sha256") != before_ledger_sha256:
            raise BuildError("local_reconciliation_ledger_binding_mismatch")
        preflight_ledger = preflight.get("ledger")
        preflight_row = _validate_local_inflight_identity(
            preflight_ledger, tag=tag, revision=revision, context_hash=context_hash
        )
        if preflight_row != row:
            raise BuildError("local_reconciliation_ledger_binding_mismatch")
        evidence["mode"] = "external_terminal_and_readback"
        evidence_sha256 = hashlib.sha256(
            json.dumps(
                {
                    "terminal": terminal_sha256,
                    "preflight": preflight_sha256,
                    "cancellation": cancellation_sha256,
                    "settled": settled_sha256,
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()

    if local_mode:
        if not isinstance(builder_before, dict):
            raise BuildError("local_reconciliation_failure_receipt_contract_mismatch")
        fresh_stop = _verify_local_stopped_builder(setup, builder_before)
        generation = fresh_stop["current_generation"]
        if not isinstance(generation, dict):
            raise BuildError("local_reconciliation_builder_identity_invalid")
        evidence["fresh_stopped_backend"] = fresh_stop
        live_history: dict[str, object] = {
            "status": "unavailable_backend_stopped",
            "historical_terminal": "unavailable",
        }
    else:
        generation = _builder_generation(setup)
        if (
            generation.get("container_id") != setup.get("builder_container_id")
            or generation.get("image_id") != setup.get("buildkit_image_id")
            or generation.get("name") != CONTAINER_NAME
        ):
            raise BuildError("local_reconciliation_builder_identity_invalid")
        live_history = _assert_no_running_buildkit_history()
    inventory = _image_inventory()
    all_image_ids = _all_image_ids()
    if tag in inventory or row["image_id"] in all_image_ids:
        raise BuildError("local_reconciliation_candidate_image_still_present")
    entries = ledger.get("entries")
    if not isinstance(entries, list):
        raise BuildError("candidate_ledger_invalid")
    remaining_entries = [candidate for candidate in entries if candidate is not row]
    remaining_ledger: dict[str, object] = {
        "schema": LEDGER_SCHEMA,
        "entries": remaining_entries,
    }
    legacy = setup["legacy_task_image_inventory"]
    expected_inventory = _expected_managed_inventory(remaining_ledger, legacy)
    if inventory != expected_inventory:
        raise BuildError("local_reconciliation_inventory_mismatch")
    _verify_ledger_inventory(remaining_ledger, setup)
    if local_mode:
        evidence["fresh_inventory"] = {
            "ledger_sha256": before_ledger_sha256,
            "exact_tag_absent": tag not in inventory,
            "placeholder_image_id_absent": row["image_id"] not in all_image_ids,
            "protected_inventory_matches": True,
            "inventory_sha256": hashlib.sha256(
                json.dumps(inventory, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest(),
        }

    run_dir = _failed_candidate_run_directory(revision, tag, context_hash)
    recovery_path = run_dir / f"local-inflight-reconciliation-{evidence_sha256}.json"
    if os.path.lexists(recovery_path):
        raise BuildError("local_reconciliation_receipt_already_exists")
    receipt: dict[str, object] = {
        "schema": LOCAL_RECONCILIATION_SCHEMA,
        "status": "local_inflight_reconciled",
        "tag": tag,
        "revision": revision,
        "context_sha256": context_hash,
        "role": role,
        "inflight_image_id": row["image_id"],
        "setup_receipt_sha256": setup_sha256,
        "pre_reconciliation_ledger_sha256": before_ledger_sha256,
        "external_evidence": evidence,
        "current_builder": {
            key: generation[key]
            for key in (
                "container_id",
                "created",
                "started",
                "restart_count",
                "running",
                "pid",
            )
        },
        "current_buildkit_history": live_history,
        "current_managed_inventory_sha256": hashlib.sha256(
            json.dumps(inventory, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
        "cause": "unproven",
        "reconciled_utc": datetime.now(UTC).isoformat(),
    }
    temporary: Path | None = None
    temporary_identity: tuple[int, int] | None = None
    try:
        temporary, temporary_identity, receipt_sha256, receipt_size = _prepare_receipt_publication(
            recovery_path, receipt
        )
        if _ledger_file_sha256() != before_ledger_sha256:
            raise BuildError("local_reconciliation_ledger_changed_before_write")
        _atomic_json(LEDGER_FILE, remaining_ledger)
        try:
            committed_ledger = _ledger_read()
            if committed_ledger != remaining_ledger:
                raise BuildError("local_reconciliation_ledger_commit_mismatch")
            _verify_ledger_inventory(committed_ledger, setup)
            if temporary is None or temporary_identity is None:
                raise BuildError("local_reconciliation_receipt_temporary_invalid")
            _publish_receipt_no_replace(temporary, recovery_path, temporary_identity, receipt_size)
        except (BuildError, OSError) as publish_error:
            try:
                _atomic_json(LEDGER_FILE, ledger)
                if _ledger_file_sha256() != before_ledger_sha256:
                    raise BuildError("local_reconciliation_ledger_rollback_unverified")
                _verify_local_inflight_inventory(
                    ledger,
                    setup,
                    tag=tag,
                    revision=revision,
                    context_hash=context_hash,
                )
            except (BuildError, OSError) as rollback_error:
                failure = BuildError("local_reconciliation_commit_and_rollback_failed")
                if isinstance(publish_error, BuildError):
                    failure.add_secondary(publish_error.code)
                else:
                    failure.add_secondary("local_reconciliation_receipt_publish_failed")
                if isinstance(rollback_error, BuildError):
                    failure.add_secondary(rollback_error.code)
                else:
                    failure.add_secondary("local_reconciliation_ledger_rollback_failed")
                raise failure from publish_error
            if isinstance(publish_error, BuildError):
                raise publish_error
            raise BuildError("local_reconciliation_receipt_publish_failed") from publish_error
    except OSError as exc:
        raise BuildError("local_reconciliation_receipt_write_failed") from exc
    finally:
        if temporary is not None and temporary_identity is not None:
            _unlink_owned_receipt_temporary(temporary, temporary_identity)
    return {
        "status": "local_inflight_reconciled",
        "tag": tag,
        "revision": revision,
        "context_sha256": context_hash,
        "evidence_sha256": evidence_sha256,
        "reconciliation_receipt": str(recovery_path),
        "reconciliation_receipt_sha256": receipt_sha256,
    }


@_ledger_serialized
def _release_failed_inflight_reservation(
    tag: str,
    revision: str,
    context_hash: str,
    role: str,
    failure_receipt_sha256: str,
) -> dict[str, object]:
    if (
        re.fullmatch(r"[0-9a-f]{40}", revision) is None
        or re.fullmatch(r"[0-9a-f]{64}", context_hash) is None
        or re.fullmatch(r"[0-9a-f]{64}", failure_receipt_sha256) is None
        or role != "current"
        or re.fullmatch(rf"stock-probs:pr-candidate-{re.escape(revision[:12])}-[0-9a-f]{{12}}", tag)
        is None
    ):
        raise BuildError("failed_reservation_identity_invalid")

    ledger = _ledger_read(allow_inflight=True)
    entries = ledger["entries"]
    assert isinstance(entries, list)
    inflight = [row for row in entries if isinstance(row, dict) and row.get("status") == "inflight"]
    matches = [row for row in inflight if row.get("tag") == tag]
    if (
        len(inflight) != 1
        or len(matches) != 1
        or set(matches[0]) != {"image_id", "tag", "revision", "context_sha256", "role", "status"}
        or matches[0].get("image_id") != _reservation_image_id(tag)
        or matches[0].get("revision") != revision
        or matches[0].get("context_sha256") != context_hash
        or matches[0].get("role") != role
    ):
        raise BuildError("failed_reservation_ledger_binding_mismatch")

    run_dir = _failed_candidate_run_directory(revision, tag, context_hash)
    setup, setup_sha256 = _current_setup_receipt_sha256()
    _failure, build_started, build_finished = _failed_build_receipt(
        run_dir=run_dir,
        tag=tag,
        revision=revision,
        context_hash=context_hash,
        role=role,
        expected_sha256=failure_receipt_sha256,
        setup_sha256=setup_sha256,
    )
    history_record = _failed_buildkit_history_record(build_started, build_finished)
    history_observed_utc = datetime.now(UTC)

    remaining_entries = [row for row in entries if row is not matches[0]]
    remaining_ledger: dict[str, object] = {"schema": LEDGER_SCHEMA, "entries": remaining_entries}
    _validate_ledger_document(remaining_ledger)
    inventory = _image_inventory()
    if tag in inventory:
        raise BuildError("failed_reservation_candidate_tag_still_present")
    legacy = setup.get("legacy_task_image_inventory")
    if not isinstance(legacy, dict) or inventory != _expected_managed_inventory(
        remaining_ledger, legacy
    ):
        raise BuildError("candidate_ledger_inventory_mismatch")
    _verify_ledger_inventory(remaining_ledger, setup)

    recovery_path = run_dir / f"failed-reservation-release-{failure_receipt_sha256}.json"
    if os.path.lexists(recovery_path):
        raise BuildError("failed_reservation_recovery_receipt_already_exists")
    recovery_utc = datetime.now(UTC).isoformat()
    recovery_receipt: dict[str, object] = {
        "schema": "r120-bounded-failed-reservation-release-v1",
        "status": "failed_build_reservation_released",
        "failure_receipt_sha256": failure_receipt_sha256,
        "tag": tag,
        "revision": revision,
        "context_sha256": context_hash,
        "role": role,
        "builder": BUILDER,
        "setup_receipt_sha256": setup_sha256,
        "buildkit_history": history_record,
        "released_utc": recovery_utc,
    }
    if _failure.get("stage") == "build_timeout_after_900s":
        cancellation_verified = any(
            _failure.get(field) is True
            for field in ("process_group_cancel_verified", "build_deadline_cancel_verified")
        )
        recovery_receipt.update(
            {
                "client_process_group_cancellation": (
                    "verified" if cancellation_verified else "unavailable"
                ),
                "backend_terminal_error_observed_utc": history_observed_utc.isoformat(),
            }
        )
    temporary_receipt: Path | None = None
    temporary_identity: tuple[int, int] | None = None
    try:
        (
            temporary_receipt,
            temporary_identity,
            recovery_sha256,
            recovery_size,
        ) = _prepare_receipt_publication(recovery_path, recovery_receipt)
        _atomic_json(LEDGER_FILE, remaining_ledger)
        try:
            assert temporary_receipt is not None and temporary_identity is not None
            _publish_receipt_no_replace(
                temporary_receipt,
                recovery_path,
                temporary_identity,
                recovery_size,
            )
        except OSError:
            _atomic_json(LEDGER_FILE, ledger)
            raise
    except OSError as exc:
        raise BuildError("failed_reservation_recovery_receipt_write_failed") from exc
    finally:
        if temporary_receipt is not None and temporary_identity is not None:
            _unlink_owned_receipt_temporary(temporary_receipt, temporary_identity)
    return {
        "status": "failed_build_reservation_released",
        "tag": tag,
        "revision": revision,
        "context_sha256": context_hash,
        "role": role,
        "failure_receipt_sha256": failure_receipt_sha256,
        "recovery_receipt": str(recovery_path),
        "recovery_receipt_sha256": recovery_sha256,
    }


def _schema13_rehearsal_image_facts(
    tag: str, image_id: str, revision: str, repo_tags_expected: list[str]
) -> None:
    fmt = (
        "{{.Id}}|{{.Os}}/{{.Architecture}}|{{json .RepoTags}}|"
        '{{index .Config.Labels "org.opencontainers.image.revision"}}'
    )
    fields = checked([DOCKER, "image", "inspect", "--format", fmt, image_id])
    try:
        observed_id, platform_name, raw_tags, observed_revision = (
            fields.decode("utf-8", "strict").strip().split("|", 3)
        )
        repo_tags = json.loads(raw_tags)
    except (UnicodeDecodeError, ValueError, json.JSONDecodeError) as exc:
        raise BuildError("schema13_rehearsal_image_metadata_invalid") from exc
    if (
        observed_id != image_id
        or platform_name != "linux/amd64"
        or observed_revision != revision
        or not isinstance(repo_tags, list)
        or any(not isinstance(value, str) for value in repo_tags)
        or repo_tags != repo_tags_expected
    ):
        raise BuildError("schema13_rehearsal_image_identity_mismatch")


def _restore_schema13_rehearsal_tag(tag: str, image_id: str, revision: str) -> bool:
    inventory = _image_inventory()
    image_ids = _all_image_ids()
    legacy = setup_receipt().get("legacy_task_image_inventory")
    if (
        not isinstance(legacy, dict)
        or image_id not in image_ids
        or tag in inventory
        or image_id in inventory.values()
        or tag in legacy
        or image_id in legacy.values()
    ):
        return False
    try:
        _schema13_rehearsal_image_facts(tag, image_id, revision, [])
        checked([DOCKER, "image", "tag", image_id, tag])
        _schema13_rehearsal_image_facts(tag, image_id, revision, [tag])
    except BuildError:
        return False
    return _image_inventory().get(tag) == image_id


def _schema13_rehearsal_rootfs_layers(image_ids: set[str]) -> dict[str, tuple[str, ...]]:
    if not image_ids or any(
        re.fullmatch(r"sha256:[0-9a-f]{64}", image_id) is None for image_id in image_ids
    ):
        raise BuildError("schema13_rehearsal_ancestry_metadata_invalid")
    if len(image_ids) > 8192:
        raise BuildError("schema13_rehearsal_image_inventory_too_large")

    requested = tuple(sorted(image_ids))
    fmt = "{{.Id}}|{{.RootFS.Type}}|{{json .RootFS.Layers}}"
    deadline = time.monotonic() + _SCHEMA13_ROOTFS_GLOBAL_TIMEOUT
    total_bytes = 0
    layers_by_id: dict[str, tuple[str, ...]] = {}
    for offset in range(0, len(requested), _SCHEMA13_ROOTFS_CHUNK_SIZE):
        chunk = requested[offset : offset + _SCHEMA13_ROOTFS_CHUNK_SIZE]
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise BuildError("schema13_rehearsal_ancestry_metadata_timeout")
        byte_budget = min(
            _SCHEMA13_ROOTFS_CHUNK_MAX_BYTES,
            _SCHEMA13_ROOTFS_INVENTORY_MAX_BYTES - total_bytes,
        )
        if byte_budget < 1:
            raise BuildError("schema13_rehearsal_image_inventory_too_large")
        try:
            fields = _capture_bounded_stdout(
                [DOCKER, "image", "inspect", "--format", fmt, *chunk],
                max_bytes=byte_budget,
                timeout=min(BUILDX_LISTING_TIMEOUT, remaining),
            )
        except BuildError as exc:
            if exc.code == "builder_driver_listing_too_large":
                raise BuildError("schema13_rehearsal_image_inventory_too_large") from exc
            raise
        if time.monotonic() >= deadline:
            raise BuildError("schema13_rehearsal_ancestry_metadata_timeout")
        if len(fields) > byte_budget:
            raise BuildError("schema13_rehearsal_image_inventory_too_large")
        total_bytes += len(fields)
        if total_bytes > _SCHEMA13_ROOTFS_INVENTORY_MAX_BYTES:
            raise BuildError("schema13_rehearsal_image_inventory_too_large")
        try:
            lines = fields.decode("ascii", "strict").splitlines()
        except UnicodeDecodeError as exc:
            raise BuildError("schema13_rehearsal_ancestry_metadata_invalid") from exc
        if len(lines) != len(chunk):
            raise BuildError("schema13_rehearsal_ancestry_metadata_invalid")
        for line in lines:
            try:
                observed_id, rootfs_type, raw_layers = line.split("|", 2)
            except ValueError as exc:
                raise BuildError("schema13_rehearsal_ancestry_metadata_invalid") from exc
            if observed_id not in chunk or observed_id in layers_by_id or rootfs_type != "layers":
                raise BuildError("schema13_rehearsal_ancestry_metadata_invalid")
            try:
                layers = json.loads(raw_layers)
            except (json.JSONDecodeError, RecursionError, ValueError) as exc:
                raise BuildError("schema13_rehearsal_ancestry_metadata_invalid") from exc
            if not isinstance(layers, list) or not layers:
                raise BuildError("schema13_rehearsal_ancestry_metadata_invalid")
            if len(layers) > _SCHEMA13_ROOTFS_MAX_LAYERS:
                raise BuildError("schema13_rehearsal_image_inventory_too_large")
            if any(
                not isinstance(layer, str) or re.fullmatch(r"sha256:[0-9a-f]{64}", layer) is None
                for layer in layers
            ) or len(layers) != len(set(layers)):
                raise BuildError("schema13_rehearsal_ancestry_metadata_invalid")
            layers_by_id[observed_id] = tuple(layers)
        if time.monotonic() >= deadline:
            raise BuildError("schema13_rehearsal_ancestry_metadata_timeout")
    if set(layers_by_id) != image_ids:
        raise BuildError("schema13_rehearsal_ancestry_metadata_invalid")
    return layers_by_id


@_ledger_serialized
def _retire_schema13_rehearsal_tag(tag: str, expected_image_id: str) -> dict[str, object]:
    if re.fullmatch(r"stock-probs:(?:schema12-base|schema13-recovery)-[0-9a-f]{12}", tag) is None:
        raise BuildError("schema13_rehearsal_tag_invalid")
    if re.fullmatch(r"sha256:[0-9a-f]{64}", expected_image_id) is None:
        raise BuildError("schema13_rehearsal_expected_image_id_invalid")
    ledger = _ledger_read()
    entries = ledger["entries"]
    assert isinstance(entries, list)
    matches = [row for row in entries if isinstance(row, dict) and row.get("tag") == tag]
    if len(matches) != 1:
        raise BuildError("schema13_rehearsal_image_unregistered")
    row = matches[0]
    if row.get("role") != "recovery" or row.get("status") != "complete":
        raise BuildError("schema13_rehearsal_image_role_or_status_invalid")
    image_id = row.get("image_id")
    if not isinstance(image_id, str) or re.fullmatch(r"sha256:[0-9a-f]{64}", image_id) is None:
        raise BuildError("schema13_rehearsal_image_id_invalid")
    if image_id != expected_image_id:
        raise BuildError("schema13_rehearsal_expected_image_id_mismatch")
    setup = setup_receipt()
    legacy = setup.get("legacy_task_image_inventory")
    if not isinstance(legacy, dict):
        raise BuildError("setup_legacy_inventory_invalid")
    _managed_build_receipt(row)
    if tag in legacy or image_id in legacy.values():
        raise BuildError("schema13_rehearsal_protected_image")

    inventory = _image_inventory()
    image_ids = _all_image_ids()
    remaining_entries = [candidate for candidate in entries if candidate is not row]
    if image_id in image_ids:
        if inventory.get(tag) != image_id or any(
            value == image_id and candidate_tag != tag for candidate_tag, value in inventory.items()
        ):
            if (
                tag not in inventory
                and image_id not in inventory.values()
                and _restore_schema13_rehearsal_tag(tag, image_id, str(row["revision"]))
            ):
                raise BuildError("schema13_rehearsal_partial_cleanup_tag_restored")
            raise BuildError("schema13_rehearsal_image_shared_or_rebound")
        _verify_ledger_inventory(ledger, setup)
        _schema13_rehearsal_image_facts(tag, image_id, str(row["revision"]), [tag])
        rootfs_layers = _schema13_rehearsal_rootfs_layers(image_ids)
        image_layers = rootfs_layers[image_id]
        for other_image_id, other_layers in rootfs_layers.items():
            if other_image_id == image_id or len(other_layers) < len(image_layers):
                continue
            if other_layers[: len(image_layers)] == image_layers:
                if len(other_layers) == len(image_layers):
                    raise BuildError("schema13_rehearsal_image_rootfs_ancestry_ambiguous")
                raise BuildError("schema13_rehearsal_image_has_child")
        if _container_uses_image_id(image_id):
            raise BuildError("schema13_rehearsal_image_in_use")
        try:
            checked([DOCKER, "image", "rm", "--no-prune", image_id])
        except BuildError as exc:
            _restore_schema13_rehearsal_tag(tag, image_id, str(row["revision"]))
            raise BuildError("schema13_rehearsal_image_remove_failed") from exc
        image_ids = _all_image_ids()
        inventory = _image_inventory()
        if (
            image_id in image_ids
            or tag in inventory
            or image_id in inventory.values()
            or _container_uses_image_id(image_id)
        ):
            if (
                image_id in image_ids
                and tag not in inventory
                and image_id not in inventory.values()
            ):
                _restore_schema13_rehearsal_tag(tag, image_id, str(row["revision"]))
            raise BuildError("schema13_rehearsal_image_removal_unverified")
    else:
        if tag in inventory or image_id in inventory.values():
            raise BuildError("schema13_rehearsal_image_inventory_mismatch")
        _verify_ledger_inventory({**ledger, "entries": remaining_entries}, setup)
        if _container_uses_image_id(image_id):
            raise BuildError("schema13_rehearsal_image_in_use")

    updated = dict(ledger)
    updated["entries"] = [
        candidate
        for candidate in entries
        if not (isinstance(candidate, dict) and candidate.get("tag") == tag)
    ]
    _verify_ledger_inventory(updated, setup)
    _atomic_json(LEDGER_FILE, updated)
    _verify_ledger_inventory(_ledger_read(), setup)
    return {"status": "retired", "tag": tag, "image_id": image_id}


@_ledger_serialized
def _apply_retirement_ack(receipt_path: Path) -> None:
    try:
        state = STATE.resolve(strict=True)
        info = receipt_path.lstat()
        resolved = receipt_path.resolve(strict=True)
    except OSError as exc:
        raise BuildError("retirement_receipt_unavailable") from exc
    retirements = state / "retirements"
    try:
        retirement_dir = retirements.lstat()
        resolved_retirements = retirements.resolve(strict=True)
    except OSError as exc:
        raise BuildError("retirement_receipt_directory_unavailable") from exc
    if (
        not stat.S_ISDIR(retirement_dir.st_mode)
        or retirement_dir.st_uid != USER.pw_uid
        or retirement_dir.st_mode & 0o077
        or not stat.S_ISREG(info.st_mode)
        or info.st_uid != USER.pw_uid
        or info.st_mode & 0o077
        or not resolved.is_relative_to(resolved_retirements)
    ):
        raise BuildError("retirement_receipt_owner_path_or_mode_invalid")
    try:
        receipt = json.loads(receipt_path.read_bytes())
    except (OSError, json.JSONDecodeError) as exc:
        raise BuildError("retirement_receipt_invalid") from exc
    removed = receipt.get("removed_image_ids") if isinstance(receipt, dict) else None
    if (
        not isinstance(receipt, dict)
        or receipt.get("schema") != "r120-exact-image-retirement-v1"
        or receipt.get("status") != "passed"
        or not isinstance(removed, list)
        or not removed
        or any(
            not isinstance(value, str) or re.fullmatch(r"sha256:[0-9a-f]{64}", value) is None
            for value in removed
        )
    ):
        raise BuildError("retirement_receipt_invalid")
    ledger = _ledger_read()
    entries = ledger["entries"]
    assert isinstance(entries, list)
    removed_ids = set(removed)
    known_ids = {row["image_id"] for row in entries if isinstance(row, dict)}
    if not removed_ids.issubset(known_ids):
        raise BuildError("retirement_receipt_unrecognized_image")
    if removed_ids.intersection(_image_inventory().values()):
        raise BuildError("retired_image_still_present")
    ledger["entries"] = [
        row for row in entries if not isinstance(row, dict) or row["image_id"] not in removed_ids
    ]
    _atomic_json(LEDGER_FILE, ledger)


@_ledger_serialized
def _reserve(
    ledger: dict[str, object], tag: str, revision: str, context_hash: str, role: str
) -> None:
    entries = ledger["entries"]
    assert isinstance(entries, list)
    if len(entries) >= 3:
        raise BuildError("candidate_retention_limit_reached")
    if any(isinstance(row, dict) and row.get("tag") == tag for row in entries):
        raise BuildError("candidate_tag_already_registered")
    entries.append(
        {
            "image_id": _reservation_image_id(tag),
            "tag": tag,
            "revision": revision,
            "context_sha256": context_hash,
            "role": role,
            "status": "inflight",
        }
    )
    _atomic_json(LEDGER_FILE, ledger)


def _check_retention_capacity(ledger: dict[str, object], requested: int) -> None:
    entries = ledger.get("entries")
    if not isinstance(entries, list) or requested < 1 or len(entries) + requested > 3:
        raise BuildError("candidate_retention_limit_reached")


def _managed_run_dir(revision: str, tag: str, context_hash: str) -> Path:
    run_key = hashlib.sha256((tag + "\0" + context_hash).encode()).hexdigest()
    run_dir = RUNS / revision / run_key
    try:
        RUNS.mkdir(parents=True, mode=0o700, exist_ok=True)
        runs_info = RUNS.lstat()
        if (
            not stat.S_ISDIR(runs_info.st_mode)
            or runs_info.st_uid != USER.pw_uid
            or runs_info.st_mode & 0o077
        ):
            raise BuildError("build_receipt_directory_owner_or_mode_invalid")
        run_dir.parent.mkdir(mode=0o700, exist_ok=True)
        revision_info = run_dir.parent.lstat()
        if (
            not stat.S_ISDIR(revision_info.st_mode)
            or revision_info.st_uid != USER.pw_uid
            or revision_info.st_mode & 0o077
        ):
            raise BuildError("build_receipt_directory_owner_or_mode_invalid")
        run_dir.mkdir(mode=0o700, exist_ok=False)
    except BuildError:
        raise
    except OSError as exc:
        raise BuildError("build_receipt_directory_unavailable") from exc
    os.chmod(run_dir, 0o700)
    return run_dir


@_ledger_serialized
def _reserve_managed_tags(
    setup: dict[str, object],
    tags: tuple[str, ...],
    revision: str,
    context_hash: str,
    role: str,
) -> dict[str, object]:
    if not tags or len(set(tags)) != len(tags) or role not in LEDGER_ROLES:
        raise BuildError("managed_build_identity_invalid")
    if any(not _safe_tag(tag) for tag in tags):
        raise BuildError("managed_build_tag_invalid")
    ledger = _ledger_read()
    _check_retention_capacity(ledger, len(tags))
    _verify_ledger_inventory(ledger, setup)
    inventory = _image_inventory()
    if any(tag in inventory for tag in tags):
        raise BuildError("managed_build_tag_already_exists")
    for tag in tags:
        _reserve(ledger, tag, revision, context_hash, role)
    return ledger


def _find_reusable_local_image(
    ledger: dict[str, object], revision: str, context_hash: str, platform_name: str
) -> dict[str, str] | None:
    entries = ledger.get("entries")
    if not isinstance(entries, list):
        raise BuildError("candidate_ledger_invalid")
    for row in entries:
        if (
            not isinstance(row, dict)
            or row.get("status") != "complete"
            or row.get("role") != "current"
            or row.get("revision") != revision
            or row.get("context_sha256") != context_hash
        ):
            continue
        tag = row.get("tag")
        image_id = row.get("image_id")
        receipt_path = row.get("receipt_path")
        receipt_hash = row.get("receipt_sha256")
        if (
            not isinstance(tag, str)
            or not _safe_tag(tag)
            or not isinstance(image_id, str)
            or not isinstance(receipt_path, str)
            or not isinstance(receipt_hash, str)
        ):
            raise BuildError("local_reuse_ledger_row_invalid")
        try:
            path = Path(receipt_path)
            info = path.lstat()
            raw = path.read_bytes()
            receipt = json.loads(raw)
        except (OSError, json.JSONDecodeError) as exc:
            raise BuildError("local_reuse_receipt_invalid") from exc
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != USER.pw_uid
            or info.st_mode & 0o077
            or hashlib.sha256(raw).hexdigest() != receipt_hash
            or not isinstance(receipt, dict)
            or receipt.get("image_id") != image_id
            or receipt.get("revision_label") != revision
            or receipt.get("context_sha256") != context_hash
            or receipt.get("candidate_role") != "current"
            or receipt.get("platform", receipt.get("image_platform")) != platform_name
        ):
            continue
        return {"tag": tag, "image_id": image_id}
    return None


@_ledger_serialized
def _complete_managed_image(
    ledger: dict[str, object],
    *,
    tag: str,
    image_id: str,
    revision: str,
    context_hash: str,
    role: str,
    platform_name: str,
    kind: str,
    run_dir: Path,
) -> None:
    receipt_path = run_dir / "build-receipt.json"
    payload: dict[str, object] = {
        "schema": "r120-bounded-image-build-v1",
        "status": "built",
        "stage": "complete",
        "source_head": revision,
        "source_branch": "local-managed-build",
        "revision_label": revision,
        "context_sha256": context_hash,
        "candidate_tag": tag,
        "candidate_role": role,
        "build_kind": kind,
        "builder": BUILDER,
        "platform": platform_name,
        "image_id": image_id,
        "finished_utc": datetime.now(UTC).isoformat(),
    }
    receipt_hash = save_receipt(receipt_path, payload)
    _complete_reservation(
        ledger,
        tag,
        image_id,
        revision,
        context_hash,
        role,
        receipt_path,
        receipt_hash,
    )


def _local_inflight_rows(ledger: dict[str, object]) -> list[dict[str, object]]:
    entries = ledger.get("entries")
    if not isinstance(entries, list):
        raise BuildError("candidate_ledger_invalid")
    return [row for row in entries if isinstance(row, dict) and row.get("status") == "inflight"]


def _validate_local_inflight_identity(
    ledger: dict[str, object], *, tag: str, revision: str, context_hash: str
) -> dict[str, object]:
    if (
        re.fullmatch(r"[0-9a-f]{40}", revision) is None
        or re.fullmatch(r"[0-9a-f]{64}", context_hash) is None
        or re.fullmatch(
            rf"stock-probs:local-{re.escape(revision[:12])}-{re.escape(context_hash[:12])}-[0-9a-f]{{12}}",
            tag,
        )
        is None
    ):
        raise BuildError("local_inflight_identity_invalid")
    rows = _local_inflight_rows(ledger)
    matches = [row for row in rows if row.get("tag") == tag]
    if (
        len(rows) != 1
        or len(matches) != 1
        or set(matches[0]) != {"image_id", "tag", "revision", "context_sha256", "role", "status"}
        or matches[0].get("image_id") != _reservation_image_id(tag)
        or matches[0].get("revision") != revision
        or matches[0].get("context_sha256") != context_hash
        or matches[0].get("role") != "current"
    ):
        raise BuildError("local_inflight_ledger_binding_mismatch")
    return matches[0]


def _ledger_file_sha256() -> str:
    raw = _read_private_file(
        LEDGER_FILE,
        owner_uid=USER.pw_uid,
        max_bytes=4 * 1024 * 1024,
        error_code="candidate_ledger_invalid",
    )
    return hashlib.sha256(raw).hexdigest()


def _record_local_build_failure(
    *,
    run_dir: Path,
    tag: str,
    revision: str,
    context_hash: str,
    setup_sha256: str | None,
    reservation_ledger_sha256: str,
    started_utc: str,
    build_started_utc: str | None,
    build_completed: bool,
    primary_error_code: str,
    secondary_errors: list[str],
    builder_generation: dict[str, object] | None,
    backend_cancellation: dict[str, object],
    phase_observation: dict[str, object] | None = None,
) -> str:
    """Publish bounded failure facts without releasing an in-flight reservation."""
    ledger_retained = False
    reservation_error: str | None = None
    failure_ledger_sha256: str | None = None
    tag_absent: bool | None = None
    inventory_matches_remaining: bool | None = None
    try:
        with _candidate_ledger_lock():
            ledger = _ledger_read(allow_inflight=True)
            row = _validate_local_inflight_identity(
                ledger, tag=tag, revision=revision, context_hash=context_hash
            )
            failure_ledger_sha256 = _ledger_file_sha256()
            if failure_ledger_sha256 != reservation_ledger_sha256:
                raise BuildError("local_inflight_ledger_changed_during_build")
            ledger_retained = True
            setup = setup_receipt()
            legacy = setup.get("legacy_task_image_inventory")
            if not isinstance(legacy, dict):
                raise BuildError("setup_legacy_inventory_invalid")
            inventory = _image_inventory()
            all_image_ids = _all_image_ids()
            tag_absent = tag not in inventory and row["image_id"] not in all_image_ids
            remaining = [candidate for candidate in ledger["entries"] if candidate is not row]
            remaining_ledger = {"schema": LEDGER_SCHEMA, "entries": remaining}
            inventory_matches_remaining = inventory == _expected_managed_inventory(
                remaining_ledger, legacy
            )
    except BuildError as exc:
        reservation_error = exc.code
        secondary_errors.append(exc.code)

    payload: dict[str, object] = {
        "schema": LOCAL_FAILURE_SCHEMA,
        "status": "failed",
        "tag": tag,
        "revision": revision,
        "context_sha256": context_hash,
        "role": "current",
        "builder": BUILDER,
        "setup_receipt_sha256": setup_sha256,
        "reservation_ledger_sha256": reservation_ledger_sha256,
        "failure_ledger_sha256": failure_ledger_sha256,
        "ledger_reservation_retained": ledger_retained,
        "reservation_verification_error": reservation_error,
        "local_tag_and_placeholder_absent": tag_absent,
        "remaining_inventory_matches": inventory_matches_remaining,
        "run_started_utc": started_utc,
        "build_started_utc": build_started_utc,
        "build_completed": build_completed,
        "finished_utc": datetime.now(UTC).isoformat(),
        "primary_error_code": primary_error_code,
        "secondary_error_codes": list(secondary_errors),
        "builder_generation_before": builder_generation,
        "backend_cancellation": backend_cancellation,
        "failure_cause": "unproven",
    }
    if phase_observation is not None:
        payload["build_phase_observation"] = phase_observation
    receipt_path = run_dir / "local-failure.json"
    temporary: Path | None = None
    identity: tuple[int, int] | None = None
    try:
        temporary, identity, digest, size = _prepare_receipt_publication(receipt_path, payload)
        _publish_receipt_no_replace(temporary, receipt_path, identity, size)
        return digest
    except OSError as exc:
        raise BuildError("local_failure_receipt_write_failed") from exc
    finally:
        if temporary is not None and identity is not None:
            _unlink_owned_receipt_temporary(temporary, identity)


@_ledger_serialized
def _complete_reservation(
    ledger: dict[str, object],
    tag: str,
    image_id: str,
    revision: str,
    context_hash: str,
    role: str,
    receipt_path: Path,
    receipt_hash: str,
) -> None:
    entries = ledger["entries"]
    assert isinstance(entries, list)
    row = next(
        (item for item in entries if isinstance(item, dict) and item.get("tag") == tag),
        None,
    )
    if not isinstance(row, dict) or row.get("status") != "inflight":
        raise BuildError("candidate_ledger_reservation_lost")
    row.update(
        {
            "image_id": image_id,
            "revision": revision,
            "context_sha256": context_hash,
            "role": role,
            "status": "complete",
            "receipt_path": str(receipt_path),
            "receipt_sha256": receipt_hash,
        }
    )
    _atomic_json(LEDGER_FILE, ledger)


def _buildx_argv(tag: str, revision: str, context: Path, iidfile: Path) -> list[str]:
    if (
        not _safe_tag(tag)
        or re.fullmatch(r"(?:[0-9a-f]{40}|schema13-recovery-[0-9a-f]{64})", revision) is None
    ):
        raise BuildError("build_identity_invalid")
    return [
        DOCKER,
        "buildx",
        "build",
        "--builder",
        BUILDER,
        "--pull=false",
        "--platform=linux/amd64",
        "--build-arg",
        f"REVISION={revision}",
        "--iidfile",
        str(iidfile),
        "--tag",
        tag,
        "--load",
        str(context),
    ]


def _native_platform() -> str:
    machine = platform.machine().casefold()
    if machine in {"x86_64", "amd64"}:
        return "linux/amd64"
    if machine in {"aarch64", "arm64"}:
        return "linux/arm64"
    raise BuildError("local_build_host_architecture_unsupported")


def _local_buildx_argv(
    tag: str,
    revision: str,
    platform_name: str,
    context: Path,
    iidfile: Path,
    rawjson_progress: bool = False,
) -> list[str]:
    if (
        not _safe_tag(tag)
        or not tag.startswith("stock-probs:local-")
        or re.fullmatch(r"[0-9a-f]{40}", revision) is None
        or platform_name not in {"linux/amd64", "linux/arm64"}
        or type(rawjson_progress) is not bool
    ):
        raise BuildError("local_build_identity_invalid")
    command = [
        DOCKER,
        "buildx",
        "build",
        "--builder",
        BUILDER,
        "--pull=false",
        f"--platform={platform_name}",
        "--build-arg",
        f"REVISION={revision}",
        "--iidfile",
        str(iidfile),
        "--tag",
        tag,
    ]
    if rawjson_progress:
        command.extend(("--progress=rawjson",))
    command.extend(("--load", str(context)))
    return command


def _arm64_compose_argv(project: str, compose_file: Path) -> list[str]:
    if re.fullmatch(r"stock-probs-[a-z0-9-]+-arm64-[0-9]+", project) is None:
        raise BuildError("arm64_compose_project_invalid")
    return [
        DOCKER,
        "compose",
        "--project-directory",
        str(ROOT),
        "--project-name",
        project,
        "--file",
        str(compose_file),
        "build",
        "--builder",
        BUILDER,
        "--pull",
        "arm64-frontend-builder",
        "arm64-app",
    ]


def _render_arm64_compose(compose_text: str, context: Path) -> str:
    if any(char in str(context) for char in ('"', "\n", "\r")):
        raise BuildError("arm64_build_context_path_invalid")
    if compose_text.count("context: ..") != 2:
        raise BuildError("arm64_compose_build_context_shape_invalid")
    return compose_text.replace("context: ..", f'context: "{context}"')


def _build_phase_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate_json_key")
        result[key] = value
    return result


def _build_phase_time(value: object) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, str) or len(value) > 40:
        raise ValueError("invalid_vertex_clock")
    match = LOCAL_BUILD_PHASE_TIMESTAMP_PATTERN.fullmatch(value)
    if match is None:
        raise ValueError("invalid_vertex_clock")
    fraction = match.group("fraction")
    fractional = f".{fraction[:6].ljust(6, '0')}" if fraction is not None else ""
    zone = "+00:00" if match.group("zone") == "Z" else match.group("zone")
    try:
        parsed = datetime.fromisoformat(f"{match.group('base')}{fractional}{zone}")
    except ValueError as exc:
        raise ValueError("invalid_vertex_clock") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("invalid_vertex_clock")
    return parsed.astimezone(UTC)


def _build_phase_name(name: str) -> str | None:
    internal = LOCAL_BUILD_PHASE_INTERNAL_NAMES.get(name)
    if internal is not None:
        return internal
    if name.startswith("[internal] load metadata for "):
        return "base_image_metadata"

    match = LOCAL_BUILD_PHASE_PATTERN.fullmatch(name)
    if match is None:
        return None
    stage = match.group("stage")
    if stage not in LOCAL_BUILD_PHASE_STAGES:
        return None
    opcode = match.group("opcode")
    instruction = match.group("instruction") or ""
    if len(instruction.encode("utf-8", "strict")) > LOCAL_BUILD_PHASE_MAX_INSTRUCTION_BYTES:
        return None
    if opcode == "FROM":
        return "base_image_stage"
    if opcode == "COPY":
        return "stage_copy"
    if opcode in {"ARG", "ENV", "WORKDIR"}:
        return "stage_setup"
    if (
        opcode
        in {
            "CMD",
            "ENTRYPOINT",
            "EXPOSE",
            "HEALTHCHECK",
            "LABEL",
            "USER",
        }
        and stage == "stage-6"
    ):
        return "runtime_configuration"
    if opcode != "RUN":
        return None

    if stage == "opencode-patched-builder":
        if instruction.startswith("python /patch/build_native.py "):
            return "native_builder_run"
        if instruction.startswith("install --directory --owner=0 --group=0 --mode=0700 /build-tmp"):
            return "native_builder_setup_run"
        return None
    if stage == "frontend-builder":
        if (
            instruction
            == "npm run typecheck && npm run build && npm run test -- --test-concurrency=1"
        ):
            return "frontend_checks_run"
        if instruction == "npm ci":
            return "frontend_dependency_setup_run"
        if instruction.startswith("mkdir -p /static-next/tools"):
            return "frontend_export_run"
        return None
    if stage == "opencode-assets":
        if instruction.startswith("mkdir -p /assets/") or instruction.startswith("mkdir -p /out "):
            return "native_asset_run"
        return None
    if stage == "builder" and instruction.startswith("python -m pip wheel "):
        return "python_package_run"
    if stage == "stage-6" and instruction.startswith(
        ("python -m pip uninstall ", "install --directory ", "chown ")
    ):
        return "runtime_image_run"
    return None


class _LocalBuildPhaseObserver:
    """Drain bounded local Buildx JSON without placing output work in the monitor loop."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._stream: BinaryIO | None = None
        self._thread: threading.Thread | None = None
        self._buffer = bytearray()
        self._raw_bytes_read = 0
        self._frames_read = 0
        self._vertices: dict[str, dict[str, object]] = {}
        self._skipped_vertices = 0
        self._skipped_vertices_truncated = False
        self._reason_code: str | None = None
        self._reader_eof = False
        self._attached = False
        self._closed = False
        self._finalized = False

    @property
    def attached(self) -> bool:
        return self._attached

    def attach(self, stream: BinaryIO) -> None:
        if self._attached or self._finalized:
            raise RuntimeError("phase_reader_state_invalid")
        self._stream = stream
        os.set_blocking(stream.fileno(), False)
        self._thread = threading.Thread(
            target=self._read,
            name="bounded-local-build-phase-reader",
            daemon=True,
        )
        self._thread.start()
        self._attached = True

    def _set_reason(self, reason_code: str) -> None:
        with self._lock:
            if not self._closed and self._reason_code is None:
                self._reason_code = reason_code
                self._buffer.clear()

    def _read(self) -> None:
        stream = self._stream
        if stream is None:
            self._set_reason("reader_stream_unavailable")
            return
        selector: selectors.BaseSelector | None = None
        try:
            selector = selectors.DefaultSelector()
            selector.register(stream, selectors.EVENT_READ)
            while not self._stop.is_set():
                events = selector.select(timeout=0.05)
                if not events:
                    continue
                try:
                    chunk = os.read(stream.fileno(), LOCAL_BUILD_PHASE_READ_CHUNK_BYTES)
                except BlockingIOError:
                    continue
                except OSError:
                    self._set_reason("reader_stream_error")
                    with suppress(OSError, ValueError):
                        stream.close()
                    return
                if not chunk:
                    with self._lock:
                        self._reader_eof = True
                        if self._buffer and self._reason_code is None:
                            self._reason_code = "unterminated_frame"
                            self._buffer.clear()
                    return
                self._consume(chunk)
        except BaseException:
            self._set_reason("reader_failed")
            self._drain_discard(stream)
        finally:
            if selector is not None:
                with suppress(Exception):
                    selector.close()

    def _drain_discard(self, stream: BinaryIO) -> None:
        """Keep the child pipe moving after an observer fault without parsing further bytes."""
        while not self._stop.is_set():
            try:
                chunk = os.read(stream.fileno(), LOCAL_BUILD_PHASE_READ_CHUNK_BYTES)
            except BlockingIOError:
                time.sleep(0.01)
                continue
            except OSError:
                with suppress(OSError, ValueError):
                    stream.close()
                return
            if not chunk:
                with self._lock:
                    self._reader_eof = True
                return
            with self._lock:
                if self._closed:
                    return
                self._raw_bytes_read = min(
                    LOCAL_BUILD_PHASE_MAX_RAW_BYTES,
                    self._raw_bytes_read + len(chunk),
                )

    def _consume(self, chunk: bytes) -> None:
        with self._lock:
            if self._closed:
                return
            remaining = LOCAL_BUILD_PHASE_MAX_RAW_BYTES - self._raw_bytes_read
            if remaining <= 0:
                if self._reason_code is None:
                    self._reason_code = "raw_byte_limit"
                return
            accepted = chunk[:remaining]
            self._raw_bytes_read += len(accepted)
            if self._reason_code is not None:
                return

        offset = 0
        while offset < len(accepted):
            newline = accepted.find(b"\n", offset)
            if newline < 0:
                fragment = accepted[offset:]
                with self._lock:
                    if self._closed or self._reason_code is not None:
                        return
                    self._buffer.extend(fragment)
                    if len(self._buffer) > LOCAL_BUILD_PHASE_MAX_LINE_BYTES:
                        self._reason_code = "line_byte_limit"
                        self._buffer.clear()
                break

            fragment = accepted[offset:newline]
            with self._lock:
                if self._closed or self._reason_code is not None:
                    return
                self._buffer.extend(fragment)
                line = bytes(self._buffer)
                self._buffer.clear()
                if len(line) > LOCAL_BUILD_PHASE_MAX_LINE_BYTES:
                    self._reason_code = "line_byte_limit"
                    return
                self._frames_read += 1
                if self._frames_read > LOCAL_BUILD_PHASE_MAX_FRAMES:
                    self._reason_code = "frame_limit"
                    return
            self._consume_frame(line)
            offset = newline + 1

        if len(chunk) > len(accepted):
            self._set_reason("raw_byte_limit")

    def _consume_frame(self, line: bytes) -> None:
        if not line:
            self._set_reason("malformed_frame")
            return
        try:
            document = json.loads(
                line.decode("utf-8", "strict"),
                object_pairs_hook=_build_phase_object,
                parse_constant=lambda _value: (_ for _ in ()).throw(ValueError("invalid_number")),
            )
        except (UnicodeDecodeError, json.JSONDecodeError, RecursionError, ValueError):
            self._set_reason("malformed_frame")
            return
        if not isinstance(document, dict) or not set(document).issubset(
            LOCAL_BUILD_PHASE_TOP_FIELDS
        ):
            self._set_reason("unknown_or_invalid_frame")
            return

        vertices = document.get("vertexes", [])
        if not isinstance(vertices, list) or len(vertices) > LOCAL_BUILD_PHASE_MAX_ARRAY_ITEMS:
            self._set_reason("array_limit_or_shape")
            return
        for field, allowed_fields in LOCAL_BUILD_PHASE_ARRAY_FIELDS.items():
            rows = document.get(field, [])
            if not isinstance(rows, list) or len(rows) > LOCAL_BUILD_PHASE_MAX_ARRAY_ITEMS:
                self._set_reason("array_limit_or_shape")
                return
            if any(
                not isinstance(item, dict) or not set(item).issubset(allowed_fields)
                for item in rows
            ):
                self._set_reason("unknown_or_invalid_frame")
                return

        for vertex in vertices:
            if not isinstance(vertex, dict) or not set(vertex).issubset(
                LOCAL_BUILD_PHASE_VERTEX_FIELDS
            ):
                self._set_reason("unknown_or_invalid_vertex")
                return
            digest = vertex.get("digest")
            name = vertex.get("name")
            if (
                not isinstance(digest, str)
                or LOCAL_BUILD_PHASE_DIGEST_PATTERN.fullmatch(digest) is None
                or not isinstance(name, str)
                or len(name.encode("utf-8", "strict")) > LOCAL_BUILD_PHASE_MAX_INSTRUCTION_BYTES
            ):
                self._set_reason("invalid_vertex_identity")
                return
            phase = _build_phase_name(name)

            inputs = vertex.get("inputs", [])
            if (
                not isinstance(inputs, list)
                or len(inputs) > LOCAL_BUILD_PHASE_MAX_ARRAY_ITEMS
                or any(
                    not isinstance(item, str)
                    or LOCAL_BUILD_PHASE_DIGEST_PATTERN.fullmatch(item) is None
                    for item in inputs
                )
            ):
                self._set_reason("invalid_vertex_inputs")
                return
            if "progressGroup" in vertex and vertex["progressGroup"] is not None:
                if not isinstance(vertex["progressGroup"], dict):
                    self._set_reason("invalid_vertex_progress_group")
                    return
                progress_group = vertex["progressGroup"]
                if not set(progress_group).issubset({"id", "name", "weak"}):
                    self._set_reason("unknown_vertex_progress_group")
                    return
                if "weak" in progress_group and type(progress_group["weak"]) is not bool:
                    self._set_reason("invalid_vertex_progress_group")
                    return

            try:
                started_at = _build_phase_time(vertex.get("started"))
                completed_at = _build_phase_time(vertex.get("completed"))
            except ValueError:
                self._set_reason("invalid_vertex_clock")
                return
            if (completed_at is not None and started_at is None) or (
                completed_at is not None and started_at is not None and completed_at < started_at
            ):
                self._set_reason("invalid_vertex_clock")
                return
            elapsed_ms: int | None = None
            if completed_at is not None and started_at is not None:
                elapsed_ms = int((completed_at - started_at).total_seconds() * 1000)
                if elapsed_ms < 0 or elapsed_ms > LOCAL_BUILD_PHASE_MAX_VERTEX_DURATION_MS:
                    self._set_reason("invalid_vertex_clock")
                    return

            cached = vertex.get("cached", False)
            error = vertex.get("error")
            if type(cached) is not bool or (error is not None and not isinstance(error, str)):
                self._set_reason("invalid_vertex_state")
                return
            if isinstance(error, str) and len(error.encode("utf-8", "strict")) > 4096:
                self._set_reason("invalid_vertex_state")
                return

            with self._lock:
                if self._closed or self._reason_code is not None:
                    return
                if phase is None:
                    self._skipped_vertices += 1
                    if self._skipped_vertices > LOCAL_BUILD_PHASE_MAX_SKIPPED_VERTICES:
                        self._skipped_vertices = LOCAL_BUILD_PHASE_MAX_SKIPPED_VERTICES
                        self._skipped_vertices_truncated = True
                    continue
                prior = self._vertices.get(digest)
                if prior is None and len(self._vertices) >= LOCAL_BUILD_PHASE_MAX_VERTICES:
                    self._reason_code = "vertex_limit"
                    return
                if prior is not None and prior.get("phase") != phase:
                    self._reason_code = "vertex_identity_changed"
                    return
                ordinal = int(prior["ordinal"]) if prior is not None else len(self._vertices) + 1
                self._vertices[digest] = {
                    "phase": phase,
                    "ordinal": ordinal,
                    "started": started_at is not None or bool(prior and prior["started"]),
                    "completed": completed_at is not None or bool(prior and prior["completed"]),
                    "cached": cached or bool(prior and prior["cached"]),
                    "error": bool(error) or bool(prior and prior["error"]),
                    "elapsed_ms": elapsed_ms
                    if elapsed_ms is not None
                    else (prior or {}).get("elapsed_ms"),
                }

        if self._artifact_size_exceeded():
            self._set_reason("artifact_size_limit")

    def _artifact_size_exceeded(self) -> bool:
        with self._lock:
            projection = self._projection_locked(status="available", reason_code=None)
        try:
            return (
                len((json.dumps(projection, sort_keys=True, separators=(",", ":")) + "\n").encode())
                > LOCAL_BUILD_PHASE_MAX_ARTIFACT_BYTES
            )
        except (TypeError, ValueError):
            return True

    def finish(self) -> None:
        try:
            if not self._attached or self._finalized:
                return
            thread = self._thread
            if thread is None:
                self._set_reason("reader_thread_unavailable")
                self._finalized = True
                return
            thread.join(timeout=LOCAL_BUILD_PHASE_READER_JOIN_SECONDS)
            with self._lock:
                self._closed = True
                if not self._reader_eof and self._reason_code is None:
                    self._reason_code = "reader_eof_unobserved"
            self._stop.set()
            stream = self._stream
            if stream is not None:
                with suppress(OSError, ValueError):
                    stream.close()
            thread.join(timeout=LOCAL_BUILD_PHASE_READER_FINAL_JOIN_SECONDS)
            if thread.is_alive():
                with self._lock:
                    if self._reason_code is None:
                        self._reason_code = "reader_join_timeout"
        except BaseException:
            with suppress(BaseException):
                self._set_reason("reader_finalize_failed")
                self._stop.set()
                self._closed = True
        finally:
            self._finalized = True

    def _projection_locked(self, *, status: str, reason_code: str | None) -> dict[str, object]:
        phases = sorted(self._vertices.values(), key=lambda phase: int(phase["ordinal"]))
        return {
            "schema": LOCAL_BUILD_PHASE_SCHEMA,
            "status": status,
            "reason_code": reason_code,
            "frames_read": min(self._frames_read, LOCAL_BUILD_PHASE_MAX_FRAMES),
            "raw_bytes_read": min(self._raw_bytes_read, LOCAL_BUILD_PHASE_MAX_RAW_BYTES),
            "vertices_observed": len(phases),
            "unknown_vertices_skipped": self._skipped_vertices,
            "unknown_vertices_truncated": self._skipped_vertices_truncated,
            "phases": phases,
        }

    def snapshot(self) -> dict[str, object] | None:
        try:
            if not self._attached:
                return None
            if not self._finalized:
                self.finish()
            with self._lock:
                reason_code = self._reason_code
                if reason_code is None and self._skipped_vertices:
                    reason_code = "unknown_vertices_skipped"
                if reason_code is None and not self._vertices:
                    reason_code = "no_progress_vertices"
                if self._reason_code is not None or not self._vertices:
                    status = "unavailable"
                elif self._skipped_vertices:
                    status = "partial"
                else:
                    status = "available"
                projection = self._projection_locked(status=status, reason_code=reason_code)
            raw = (json.dumps(projection, sort_keys=True, separators=(",", ":")) + "\n").encode()
        except BaseException:
            return {
                "schema": LOCAL_BUILD_PHASE_SCHEMA,
                "status": "unavailable",
                "reason_code": "observer_snapshot_failed",
                "frames_read": 0,
                "raw_bytes_read": 0,
                "vertices_observed": 0,
                "unknown_vertices_skipped": 0,
                "unknown_vertices_truncated": False,
                "phases": [],
            }
        if len(raw) > LOCAL_BUILD_PHASE_MAX_ARTIFACT_BYTES:
            return {
                "schema": LOCAL_BUILD_PHASE_SCHEMA,
                "status": "unavailable",
                "reason_code": "artifact_size_limit",
                "frames_read": min(self._frames_read, LOCAL_BUILD_PHASE_MAX_FRAMES),
                "raw_bytes_read": min(self._raw_bytes_read, LOCAL_BUILD_PHASE_MAX_RAW_BYTES),
                "vertices_observed": 0,
                "unknown_vertices_skipped": min(
                    self._skipped_vertices, LOCAL_BUILD_PHASE_MAX_SKIPPED_VERTICES
                ),
                "unknown_vertices_truncated": self._skipped_vertices_truncated,
                "phases": [],
            }
        return projection


def _run_bounded_build(
    command: list[str],
    *,
    expected_uuid: str,
    docker_root: Path,
    space_paths: tuple[Path, ...],
    env: dict[str, str],
    timeout: int,
    phase_observer: _LocalBuildPhaseObserver | None = None,
) -> None:
    try:
        process = subprocess.Popen(  # noqa: S603 - Fixed command vector, no shell.
            command,
            cwd=ROOT,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE if phase_observer is not None else subprocess.DEVNULL,
            shell=False,
            start_new_session=True,
        )
    except OSError as exc:
        raise BuildError("bounded_build_command_start_failed") from exc

    if phase_observer is not None:
        try:
            if process.stderr is None:
                raise RuntimeError("phase_reader_stream_unavailable")
            phase_observer.attach(process.stderr)
        except BaseException as exc:
            if not cancel(process):
                if process.stderr is not None:
                    with suppress(OSError, ValueError):
                        process.stderr.close()
                raise BuildError("bounded_build_phase_reader_start_cancel_unverified") from exc
            if process.stderr is not None:
                with suppress(OSError, ValueError):
                    process.stderr.close()
            raise BuildError("bounded_build_phase_reader_start_failed") from exc

    started = time.monotonic()
    deadline = started + timeout
    next_uuid_check = started
    original_term_handler = signal.getsignal(signal.SIGTERM)

    def terminate_as_interrupt(_signum: int, _frame: object) -> None:
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, terminate_as_interrupt)
    try:
        while True:
            now = time.monotonic()
            result = process.poll()
            if result is not None:
                if time.monotonic() >= deadline:
                    raise BuildError("bounded_build_timeout")
                try:
                    os.killpg(process.pid, 0)
                except ProcessLookupError:
                    return_code = result
                    break
                except OSError as exc:
                    raise BuildError("bounded_build_process_group_unverified") from exc
                if not cancel(process):
                    raise BuildError("bounded_build_child_process_cancel_unverified")
                raise BuildError("bounded_build_left_child_processes")

            if now >= deadline:
                if not cancel(process):
                    raise BuildError("bounded_build_timeout_cancel_unverified")
                raise BuildError("bounded_build_timeout")
            if now >= next_uuid_check:
                try:
                    verify_build_mount(
                        expected_uuid,
                        str(docker_root),
                        deadline=deadline,
                    )
                except BuildError as exc:
                    if exc.code == "bounded_build_timeout":
                        if not cancel(process):
                            raise BuildError("bounded_build_timeout_cancel_unverified") from exc
                        raise BuildError("bounded_build_timeout") from exc
                    if not cancel(process):
                        suffix = exc.code.removeprefix("build_mount_")
                        raise BuildError(f"bounded_build_mount_cancel_unverified_{suffix}") from exc
                    suffix = exc.code.removeprefix("build_mount_")
                    raise BuildError(f"bounded_build_mount_{suffix}") from exc
                if time.monotonic() >= deadline:
                    if not cancel(process):
                        raise BuildError("bounded_build_timeout_cancel_unverified")
                    raise BuildError("bounded_build_timeout")
                next_uuid_check = time.monotonic() + UUID_POLL
            try:
                check_space(space_paths, STOP_FREE)
            except BuildError as exc:
                if not cancel(process):
                    raise BuildError("bounded_build_space_cancel_unverified") from exc
                if exc.code == "build_disk_floor_breached":
                    raise BuildError("bounded_build_cancelled_below_1gib") from exc
                raise
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                if not cancel(process):
                    raise BuildError("bounded_build_timeout_cancel_unverified")
                raise BuildError("bounded_build_timeout")
            time.sleep(min(POLL, remaining))
    except KeyboardInterrupt as exc:
        if not cancel(process):
            raise BuildError("bounded_build_interrupt_cancel_unverified") from exc
        raise BuildError("bounded_build_interrupted") from exc
    finally:
        signal.signal(signal.SIGTERM, original_term_handler)
        if phase_observer is not None:
            phase_observer.finish()

    if return_code == 0:
        try:
            data_root(expected_uuid, str(docker_root), deadline=deadline)
        except BuildError as exc:
            if exc.code == "bounded_build_timeout":
                raise
            raise BuildError(f"bounded_build_post_root_identity_failed_{exc.code}") from exc
        if time.monotonic() >= deadline:
            raise BuildError("bounded_build_timeout")
    if return_code != 0:
        raise BuildError("bounded_build_exit_nonzero")


def _build_context(destination: Path) -> str:
    source = ROOT / "scripts/rehearse_schema13.py"
    spec = importlib.util.spec_from_file_location("r120_build_context_source", source)
    if spec is None or spec.loader is None:
        raise BuildError("fixed_build_context_filter_unavailable")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    except (ImportError, OSError, SyntaxError) as exc:
        raise BuildError("fixed_build_context_filter_unavailable") from exc
    try:
        context_hash = module._candidate_context(ROOT, destination)
    except module.RehearsalError as exc:
        raise BuildError("fixed_build_context_rejected") from exc
    if not isinstance(context_hash, str) or re.fullmatch(r"[0-9a-f]{64}", context_hash) is None:
        raise BuildError("fixed_build_context_digest_invalid")
    return context_hash


def _builder_preflight() -> tuple[dict[str, object], Path, str]:
    setup = setup_receipt()
    inspect_builder(setup)
    expected_uuid = str(setup.get("expected_docker_root_uuid", "")).lower()
    if not check_uuid(expected_uuid):
        raise BuildError("setup_docker_uuid_invalid")
    try:
        docker_root, _free = data_root(expected_uuid, str(setup.get("docker_root")))
    except BuildError:
        raise
    check_space((docker_root, ROOT, STATE), MIN_FREE)
    return setup, docker_root, expected_uuid


def build_local_image() -> dict[str, str]:
    setup, docker_root, expected_uuid = _builder_preflight()
    head = checked([GIT, "-c", f"safe.directory={ROOT}", "rev-parse", "HEAD"])
    revision = head.decode("ascii", "strict").strip()
    if re.fullmatch(r"[0-9a-f]{40}", revision) is None:
        raise BuildError("local_source_head_invalid")

    with tempfile.TemporaryDirectory(prefix="local-image-context-", dir=STATE) as directory:
        temporary = Path(directory)
        context = temporary / "context"
        context_hash = _build_context(context)
        if _context_sha256(context, USER.pw_uid) != context_hash:
            raise BuildError("local_build_context_digest_mismatch")
        expected_platform = _native_platform()
        space_paths = (docker_root, ROOT, STATE, temporary, context)
        with _candidate_ledger_lock():
            ledger = _ledger_read()
            _verify_ledger_inventory(ledger, setup)
            reusable = _find_reusable_local_image(ledger, revision, context_hash, expected_platform)
            if reusable is not None:
                tag = reusable["tag"]
                image_id = reusable["image_id"]
                fmt = (
                    "{{.Id}}|{{.Os}}/{{.Architecture}}|"
                    '{{index .Config.Labels "org.opencontainers.image.revision"}}'
                )
                fields = checked([DOCKER, "image", "inspect", "--format", fmt, tag])
                if fields.decode("ascii", "strict").strip().split("|") != [
                    image_id,
                    expected_platform,
                    revision,
                ]:
                    raise BuildError("local_reuse_image_validation_failed")
                _write_local_current(tag, image_id, revision, context_hash)
                return {
                    "status": "reused",
                    "tag": tag,
                    "image_id": image_id,
                    "platform": expected_platform,
                    "source_revision": revision,
                    "context_sha256": context_hash,
                    "builder": BUILDER,
                }
            nonce = hashlib.sha256(os.urandom(32)).hexdigest()[:12]
            tag = f"stock-probs:local-{revision[:12]}-{context_hash[:12]}-{nonce}"
            iidfile = temporary / "image.iid"
            check_space(space_paths, MIN_FREE)
            run_dir = _managed_run_dir(revision, tag, context_hash)
            ledger = _reserve_managed_tags(setup, (tag,), revision, context_hash, "current")
        reservation_ledger_sha256 = ""
        setup_sha256: str | None = None
        run_started_utc = datetime.now(UTC).isoformat()
        build_started_utc: str | None = None
        builder_generation: dict[str, object] | None = None
        build_attempt_started = False
        build_completed = False
        backend_cancellation: dict[str, object] = {"status": "not_started"}
        phase_observer = _LocalBuildPhaseObserver()
        try:
            reservation_ledger_sha256 = _ledger_file_sha256()
            setup, setup_sha256 = _current_setup_receipt_sha256()
            inspect_builder(setup)
            builder_generation = _builder_generation(setup)
            if builder_generation["running"] is not True:
                raise BuildError("local_builder_not_running_before_build")
            command = _local_buildx_argv(tag, revision, expected_platform, context, iidfile, True)
            build_started_utc = datetime.now(UTC).isoformat()
            build_attempt_started = True
            _run_bounded_build(
                command,
                expected_uuid=expected_uuid,
                docker_root=docker_root,
                space_paths=space_paths,
                env=ENV,
                timeout=TIMEOUT,
                phase_observer=phase_observer,
            )
            build_completed = True
            try:
                image_id = iidfile.read_text(encoding="ascii").strip()
            except OSError as exc:
                raise BuildError("local_build_image_id_unavailable") from exc
            if re.fullmatch(r"sha256:[0-9a-f]{64}", image_id) is None:
                raise BuildError("local_build_image_id_invalid")
            fmt = (
                "{{.Id}}|{{.Os}}/{{.Architecture}}|"
                '{{index .Config.Labels "org.opencontainers.image.revision"}}'
            )
            fields = checked([DOCKER, "image", "inspect", "--format", fmt, tag])
            if fields.decode("ascii", "strict").strip().split("|") != [
                image_id,
                expected_platform,
                revision,
            ]:
                raise BuildError("local_build_image_validation_failed")
            with _candidate_ledger_lock():
                ledger = _ledger_read(allow_inflight=True)
                _complete_managed_image(
                    ledger,
                    tag=tag,
                    image_id=image_id,
                    revision=revision,
                    context_hash=context_hash,
                    role="current",
                    platform_name=expected_platform,
                    kind="local",
                    run_dir=run_dir,
                )
                _verify_ledger_inventory(ledger, setup)
                _write_local_current(tag, image_id, revision, context_hash)
        except BaseException as primary_error:
            if isinstance(primary_error, BuildError):
                primary_error_code = primary_error.code
            elif isinstance(primary_error, KeyboardInterrupt):
                primary_error_code = "local_build_interrupted"
            else:
                primary_error_code = "local_build_unexpected_exception"
            secondary_errors: list[str] = []
            backend_may_be_active = (
                build_attempt_started
                and not build_completed
                and primary_error_code != "bounded_build_command_start_failed"
            )
            if backend_may_be_active:
                try:
                    current_setup, current_setup_sha256 = _current_setup_receipt_sha256()
                    if current_setup_sha256 != setup_sha256:
                        raise BuildError("local_builder_setup_receipt_changed")
                    if builder_generation is None:
                        raise BuildError("local_builder_generation_unavailable")
                    with _candidate_ledger_lock():
                        ledger = _ledger_read(allow_inflight=True)
                        _validate_local_inflight_identity(
                            ledger, tag=tag, revision=revision, context_hash=context_hash
                        )
                    backend_cancellation = _stop_owned_builder_after_local_failure(
                        current_setup, builder_generation
                    )
                    stop_error_code = backend_cancellation.get("stop_error_code")
                    if stop_error_code is not None:
                        if (
                            not isinstance(stop_error_code, str)
                            or re.fullmatch(r"[a-z0-9_]{1,96}", stop_error_code) is None
                        ):
                            raise BuildError("local_builder_stop_error_code_invalid")
                        secondary_errors.append(stop_error_code)
                except BuildError as cancellation_error:
                    backend_cancellation = {
                        "status": "unverified",
                        "error_code": cancellation_error.code,
                    }
                    secondary_errors.append(cancellation_error.code)
            try:
                failure_receipt_sha256 = _record_local_build_failure(
                    run_dir=run_dir,
                    tag=tag,
                    revision=revision,
                    context_hash=context_hash,
                    setup_sha256=setup_sha256,
                    reservation_ledger_sha256=reservation_ledger_sha256,
                    started_utc=run_started_utc,
                    build_started_utc=build_started_utc,
                    build_completed=build_completed,
                    primary_error_code=primary_error_code,
                    secondary_errors=secondary_errors,
                    builder_generation=builder_generation,
                    backend_cancellation=backend_cancellation,
                    phase_observation=phase_observer.snapshot(),
                )
                if isinstance(primary_error, BuildError):
                    primary_error.local_failure_receipt_path = str(run_dir / "local-failure.json")
                    primary_error.local_failure_receipt_sha256 = failure_receipt_sha256
            except (BuildError, OSError) as receipt_error:
                receipt_error_code = (
                    receipt_error.code
                    if isinstance(receipt_error, BuildError)
                    else "local_failure_receipt_write_failed"
                )
                secondary_errors.append(receipt_error_code)
            if isinstance(primary_error, BuildError):
                for error_code in secondary_errors:
                    primary_error.add_secondary(error_code)
            raise
    return {
        "status": "built",
        "tag": tag,
        "image_id": image_id,
        "platform": expected_platform,
        "source_revision": revision,
        "context_sha256": context_hash,
        "builder": BUILDER,
        "receipt": str(run_dir / "build-receipt.json"),
    }


@_ledger_serialized
def _write_local_current(tag: str, image_id: str, revision: str, context_hash: str) -> None:
    if LOCAL_CURRENT_FILE.exists() or LOCAL_CURRENT_FILE.is_symlink():
        try:
            current_info = LOCAL_CURRENT_FILE.lstat()
        except OSError as exc:
            raise BuildError("local_current_pointer_unavailable") from exc
        if (
            not stat.S_ISREG(current_info.st_mode)
            or current_info.st_uid != USER.pw_uid
            or current_info.st_mode & 0o077
        ):
            raise BuildError("local_current_pointer_owner_or_mode_invalid")
    _atomic_json(
        LOCAL_CURRENT_FILE,
        {
            "schema": "r120-local-image-pointer-v1",
            "tag": tag,
            "image_id": image_id,
            "revision": revision,
            "context_sha256": context_hash,
        },
    )


def local_current_image() -> dict[str, str]:
    setup = setup_receipt()
    ledger = _ledger_read()
    _verify_ledger_inventory(ledger, setup)
    try:
        info = LOCAL_CURRENT_FILE.lstat()
        raw = LOCAL_CURRENT_FILE.read_bytes()
        pointer = json.loads(raw)
    except (OSError, json.JSONDecodeError) as exc:
        raise BuildError("local_current_pointer_unavailable") from exc
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_uid != USER.pw_uid
        or info.st_mode & 0o077
        or not isinstance(pointer, dict)
        or pointer.get("schema") != "r120-local-image-pointer-v1"
    ):
        raise BuildError("local_current_pointer_invalid")
    tag = pointer.get("tag")
    image_id = pointer.get("image_id")
    revision = pointer.get("revision")
    context_hash = pointer.get("context_sha256")
    entries = ledger["entries"]
    if not isinstance(entries, list):
        raise BuildError("candidate_ledger_invalid")
    matching = [
        row
        for row in entries
        if isinstance(row, dict)
        and row.get("tag") == tag
        and row.get("image_id") == image_id
        and row.get("revision") == revision
        and row.get("context_sha256") == context_hash
        and row.get("role") == "current"
        and row.get("status") == "complete"
    ]
    if len(matching) != 1 or not isinstance(tag, str):
        raise BuildError("local_current_pointer_unregistered")
    fmt = (
        "{{.Id}}|{{.Os}}/{{.Architecture}}|"
        '{{index .Config.Labels "org.opencontainers.image.revision"}}'
    )
    fields = checked([DOCKER, "image", "inspect", "--format", fmt, tag])
    parts = fields.decode("ascii", "strict").strip().split("|")
    if parts != [image_id, _native_platform(), revision]:
        raise BuildError("local_current_image_mismatch")
    return {"tag": tag, "image_id": image_id, "revision": revision}


@_ledger_serialized
def select_local_current(expected_image_id: str, replacement_image_id: str) -> dict[str, object]:
    """Select a retained verified image without deleting images or changing ledger roles."""
    if (
        any(
            re.fullmatch(r"sha256:[0-9a-f]{64}", value) is None
            for value in (expected_image_id, replacement_image_id)
        )
        or expected_image_id == replacement_image_id
    ):
        raise BuildError("local_current_transition_ids_invalid")
    current = local_current_image()
    if current["image_id"] != expected_image_id:
        raise BuildError("local_current_transition_stale")
    ledger = _ledger_read()
    entries = ledger["entries"]
    assert isinstance(entries, list)
    selected = []
    for image_id in (expected_image_id, replacement_image_id):
        matches = [
            row
            for row in entries
            if isinstance(row, dict)
            and row.get("image_id") == image_id
            and row.get("role") == "current"
            and row.get("status") == "complete"
        ]
        if len(matches) != 1:
            raise BuildError("local_current_transition_unregistered")
        row = matches[0]
        _managed_build_receipt(row)
        _schema13_rehearsal_image_facts(
            str(row["tag"]), image_id, str(row["revision"]), [str(row["tag"])]
        )
        selected.append(row)
    replacement = selected[1]
    _write_local_current(
        str(replacement["tag"]),
        replacement_image_id,
        str(replacement["revision"]),
        str(replacement["context_sha256"]),
    )
    return {
        "schema": "r120-local-current-transition-v1",
        "status": "selected",
        "previous": current,
        "current": {
            key: replacement[key] for key in ("tag", "image_id", "revision", "context_sha256")
        },
        "images_removed": [],
        "ledger_changed": False,
    }


def _arm64_compose_environment(
    *,
    task_id: str,
    revision: str,
    project: str,
    runtime_image: str,
    frontend_image: str,
    port: int,
    qemu_dir: Path,
    artifact_dir: Path,
) -> dict[str, str]:
    task_pattern = (
        r"(?:M0[0-9]|EXP-M0[0-9]|ASTRA-FINAL|EXP-FINAL|R-M0[0-9]-[1-9][0-9]*|R-ASTRA-[0-9]+)"
    )
    task_slug = task_id.casefold()
    if (
        re.fullmatch(task_pattern, task_id) is None
        or re.fullmatch(r"[0-9a-f]{40}", revision) is None
    ):
        raise BuildError("arm64_compose_identity_invalid")
    expected_project = f"stock-probs-{task_slug}-arm64-{USER.pw_uid}"
    if project != expected_project:
        raise BuildError("arm64_compose_project_invalid")
    runtime_prefix = f"stock-probs-{task_slug}-arm64-runtime:"
    frontend_prefix = f"stock-probs-{task_slug}-arm64-frontend:"
    runtime_match = re.fullmatch(re.escape(runtime_prefix) + r"([0-9]{8}T[0-9]{6}Z)", runtime_image)
    frontend_match = re.fullmatch(
        re.escape(frontend_prefix) + r"([0-9]{8}T[0-9]{6}Z)", frontend_image
    )
    if (
        runtime_match is None
        or frontend_match is None
        or runtime_match.group(1) != frontend_match.group(1)
    ):
        raise BuildError("arm64_compose_image_tags_invalid")
    if not 1 <= port <= 65535:
        raise BuildError("arm64_compose_port_invalid")
    if qemu_dir != ROOT / ".tools/qemu-arm64":
        raise BuildError("arm64_compose_qemu_path_invalid")
    try:
        qemu_info = qemu_dir.lstat()
    except OSError as exc:
        raise BuildError("arm64_compose_qemu_path_invalid") from exc
    if (
        not stat.S_ISDIR(qemu_info.st_mode)
        or stat.S_ISLNK(qemu_info.st_mode)
        or qemu_info.st_uid != USER.pw_uid
    ):
        raise BuildError("arm64_compose_qemu_path_invalid")
    try:
        artifact_info = artifact_dir.lstat()
    except OSError as exc:
        raise BuildError("arm64_compose_artifact_path_invalid") from exc
    if (
        not artifact_dir.is_absolute()
        or not stat.S_ISDIR(artifact_info.st_mode)
        or stat.S_ISLNK(artifact_info.st_mode)
        or artifact_info.st_uid != USER.pw_uid
        or "\n" in str(artifact_dir)
    ):
        raise BuildError("arm64_compose_artifact_path_invalid")
    return {
        **ENV,
        "STOCK_PROBS_TASK_ID": task_id,
        "STOCK_PROBS_REVISION": revision,
        "STOCK_PROBS_ARM64_PORT": str(port),
        "STOCK_PROBS_ARM64_IMAGE": runtime_image,
        "STOCK_PROBS_ARM64_FRONTEND_IMAGE": frontend_image,
        "STOCK_PROBS_CONTAINER_UID": str(USER.pw_uid),
        "STOCK_PROBS_CONTAINER_GID": str(USER.pw_gid),
        "STOCK_PROBS_QEMU_DIR": str(qemu_dir),
        "STOCK_PROBS_ARM64_ARTIFACT_DIR": str(artifact_dir),
    }


def build_arm64_compose_images(args: argparse.Namespace) -> dict[str, object]:
    setup, docker_root, expected_uuid = _builder_preflight()
    if sha(ROOT / "scripts/compose.arm64.yml") != ARM64_COMPOSE_SHA256:
        raise BuildError("arm64_compose_source_pin_mismatch")
    if re.fullmatch(r"[0-9a-f]{40}", args.revision) is None:
        raise BuildError("arm64_compose_revision_invalid")
    expected_head = checked([GIT, "-c", f"safe.directory={ROOT}", "rev-parse", "HEAD"])
    if expected_head.decode("ascii", "strict").strip() != args.revision:
        raise BuildError("arm64_compose_head_changed")
    environment = _arm64_compose_environment(
        task_id=args.task_id,
        revision=args.revision,
        project=args.project_name,
        runtime_image=args.runtime_image,
        frontend_image=args.frontend_image,
        port=args.port,
        qemu_dir=args.qemu_dir,
        artifact_dir=args.artifact_dir,
    )
    with tempfile.TemporaryDirectory(prefix="arm64-image-context-", dir=STATE) as directory:
        temporary = Path(directory)
        context = temporary / "context"
        context_hash = _build_context(context)
        if _context_sha256(context, USER.pw_uid) != context_hash:
            raise BuildError("arm64_build_context_digest_mismatch")
        compose_text = (ROOT / "scripts/compose.arm64.yml").read_text(encoding="utf-8")
        rendered = _render_arm64_compose(compose_text, context)
        compose_file = temporary / "compose.arm64.yml"
        compose_file.write_text(rendered, encoding="utf-8")
        tags = (args.frontend_image, args.runtime_image)
        ledger = _reserve_managed_tags(setup, tags, args.revision, context_hash, "transient")
        run_dirs = {tag: _managed_run_dir(args.revision, tag, context_hash) for tag in tags}
        space_paths = (docker_root, ROOT, STATE, temporary, context)
        check_space(space_paths, MIN_FREE)
        command = _arm64_compose_argv(args.project_name, compose_file)
        _run_bounded_build(
            command,
            expected_uuid=expected_uuid,
            docker_root=docker_root,
            space_paths=space_paths,
            env=environment,
            timeout=COMPOSE_BUILD_TIMEOUT,
        )
        image_rows = {}
        for tag in (args.frontend_image, args.runtime_image):
            result = (
                checked(
                    [
                        DOCKER,
                        "image",
                        "inspect",
                        "--format",
                        "{{.Id}}|{{.Os}}/{{.Architecture}}",
                        tag,
                    ]
                )
                .decode("ascii", "strict")
                .strip()
                .split("|")
            )
            if len(result) != 2 or re.fullmatch(r"sha256:[0-9a-f]{64}", result[0]) is None:
                raise BuildError("arm64_compose_image_inspection_invalid")
            if result[1] != "linux/arm64":
                raise BuildError("arm64_compose_image_platform_mismatch")
            image_rows[tag] = result[0]
        with _candidate_ledger_lock():
            ledger = _ledger_read(allow_inflight=True)
            for tag in tags:
                _complete_managed_image(
                    ledger,
                    tag=tag,
                    image_id=image_rows[tag],
                    revision=args.revision,
                    context_hash=context_hash,
                    role="transient",
                    platform_name="linux/arm64",
                    kind="arm64-compose",
                    run_dir=run_dirs[tag],
                )
            _verify_ledger_inventory(ledger, setup)
    return {
        "status": "built",
        "builder": BUILDER,
        "platform": "linux/arm64",
        "context_sha256": context_hash,
        "images": image_rows,
        "receipts": {tag: str(run_dirs[tag] / "build-receipt.json") for tag in tags},
    }


def cancel(process: subprocess.Popen[bytes]) -> bool:
    for sig, grace in ((signal.SIGINT, 5), (signal.SIGTERM, 3), (signal.SIGKILL, 2)):
        try:
            os.killpg(process.pid, sig)
        except ProcessLookupError:
            pass
        except OSError:
            return False
        try:
            process.wait(timeout=grace)
            break
        except subprocess.TimeoutExpired:
            continue
        except OSError:
            return False
    try:
        process.wait(timeout=2)
    except (OSError, subprocess.TimeoutExpired):
        return False
    try:
        os.killpg(process.pid, 0)
    except ProcessLookupError:
        return True
    except OSError:
        return False
    return False


def save_receipt(path: Path, data: dict[str, object]) -> str:
    raw = (json.dumps(data, sort_keys=True, indent=2) + "\n").encode()
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(raw)
    os.chmod(path, 0o600)
    return hashlib.sha256(raw).hexdigest()


def _prepare_receipt_publication(
    path: Path, data: dict[str, object]
) -> tuple[Path, tuple[int, int], str, int]:
    """Write a complete private receipt to an owned temporary file."""
    raw = (json.dumps(data, sort_keys=True, indent=2) + "\n").encode()
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary_path = Path(temporary_name)
    identity: tuple[int, int] | None = None
    try:
        metadata = os.fstat(fd)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != USER.pw_uid
            or metadata.st_mode & 0o077
        ):
            raise OSError("receipt_temporary_file_owner_or_mode_invalid")
        identity = (metadata.st_dev, metadata.st_ino)
        view = memoryview(raw)
        while view:
            written = os.write(fd, view)
            if written <= 0:
                raise OSError("receipt_temporary_write_made_no_progress")
            view = view[written:]
        os.fsync(fd)
        os.fchmod(fd, 0o600)
        os.fsync(fd)
        os.close(fd)
        fd = -1
    except OSError:
        if fd >= 0:
            with suppress(OSError):
                os.close(fd)
        if identity is not None:
            _unlink_owned_receipt_temporary(temporary_path, identity)
        raise
    assert identity is not None
    return temporary_path, identity, hashlib.sha256(raw).hexdigest(), len(raw)


def _publish_receipt_no_replace(
    temporary_path: Path,
    path: Path,
    identity: tuple[int, int],
    expected_size: int,
) -> None:
    """Publish a complete receipt atomically without replacing an existing path."""
    try:
        os.link(temporary_path, path, follow_symlinks=False)
    except OSError:
        if not _is_owned_receipt_file(path, identity, expected_size):
            raise


def _is_owned_receipt_file(path: Path, identity: tuple[int, int], expected_size: int) -> bool:
    try:
        metadata = path.lstat()
    except OSError:
        return False
    return (
        stat.S_ISREG(metadata.st_mode)
        and metadata.st_uid == USER.pw_uid
        and not metadata.st_mode & 0o077
        and (metadata.st_dev, metadata.st_ino) == identity
        and metadata.st_size == expected_size
    )


def _unlink_owned_receipt_temporary(path: Path, identity: tuple[int, int]) -> None:
    """Remove only the private temporary inode created for a receipt write."""
    try:
        metadata = path.lstat()
    except OSError:
        return
    if (
        stat.S_ISREG(metadata.st_mode)
        and metadata.st_uid == USER.pw_uid
        and (metadata.st_dev, metadata.st_ino) == identity
    ):
        with suppress(OSError):
            path.unlink()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build with the installed bounded Buildx builder and guarded storage."
    )
    parser.add_argument("--initialize-empty-ledger", action="store_true")
    parser.add_argument("--ack-retirement-receipt", type=Path)
    parser.add_argument("--release-failed-inflight-reservation", action="store_true")
    parser.add_argument("--failure-receipt-sha256")
    parser.add_argument("--reconcile-local-inflight-reservation", action="store_true")
    parser.add_argument("--local-failure-receipt-sha256")
    parser.add_argument("--terminal-observation", type=Path)
    parser.add_argument("--terminal-observation-sha256")
    parser.add_argument("--preflight-observation", type=Path)
    parser.add_argument("--preflight-observation-sha256")
    parser.add_argument("--cancellation-observation", type=Path)
    parser.add_argument("--cancellation-observation-sha256")
    parser.add_argument("--settled-observation", type=Path)
    parser.add_argument("--settled-observation-sha256")
    parser.add_argument("--retire-schema13-rehearsal-tag")
    parser.add_argument("--retire-schema13-rehearsal-image-id")
    parser.add_argument("--plan-arm64-cleanup", action="store_true")
    parser.add_argument("--ack-arm64-cleanup", action="store_true")
    parser.add_argument("--registered-image-id", action="append", default=[])
    parser.add_argument("--local-current-image", action="store_true")
    parser.add_argument("--select-local-current-image-id")
    parser.add_argument("--expected-local-current-image-id")
    parser.add_argument("--local-image-build", action="store_true")
    parser.add_argument("--arm64-compose-build", action="store_true")
    parser.add_argument("--task-id")
    parser.add_argument("--revision")
    parser.add_argument("--project-name")
    parser.add_argument("--runtime-image")
    parser.add_argument("--frontend-image")
    parser.add_argument("--port", type=int)
    parser.add_argument("--qemu-dir", type=Path)
    parser.add_argument("--artifact-dir", type=Path)
    parser.add_argument("--source-head")
    parser.add_argument("--source-branch")
    parser.add_argument("--revision-label")
    parser.add_argument("--context", type=Path)
    parser.add_argument("--context-sha256")
    parser.add_argument("--context-owner-uid", type=int)
    parser.add_argument("--tag")
    parser.add_argument("--role", choices=("current", "recovery"))
    args = parser.parse_args()
    if os.geteuid() != USER.pw_uid:
        parser.error("the bounded image builder must run as the fixed project user")
    validate_user_state()
    if not os.access(SOCKET, os.W_OK):
        raise BuildError("docker_socket_group_access_unavailable")
    transition_names = {"select_local_current_image_id", "expected_local_current_image_id"}
    if any(getattr(args, name) is not None for name in transition_names):
        if any(getattr(args, name) is None for name in transition_names) or any(
            value != parser.get_default(name)
            for name, value in vars(args).items()
            if name not in transition_names
        ):
            parser.error("local current selection requires only expected and replacement image IDs")
        try:
            result = select_local_current(
                args.expected_local_current_image_id, args.select_local_current_image_id
            )
        except BuildError as exc:
            print(
                json.dumps({"status": "failed", "stage": exc.code}, sort_keys=True), file=sys.stderr
            )
            return 1
        print(json.dumps(result, sort_keys=True))
        return 0
    local_reconciliation_names = {
        "reconcile_local_inflight_reservation",
        "local_failure_receipt_sha256",
        "terminal_observation",
        "terminal_observation_sha256",
        "preflight_observation",
        "preflight_observation_sha256",
        "cancellation_observation",
        "cancellation_observation_sha256",
        "settled_observation",
        "settled_observation_sha256",
        "tag",
        "revision",
        "context_sha256",
        "role",
    }
    local_evidence_names = local_reconciliation_names - {
        "reconcile_local_inflight_reservation",
        "tag",
        "revision",
        "context_sha256",
        "role",
    }
    local_reconciliation_requested = args.reconcile_local_inflight_reservation or any(
        getattr(args, name) is not None for name in local_evidence_names
    )
    if local_reconciliation_requested:
        if not args.reconcile_local_inflight_reservation or any(
            value != parser.get_default(name)
            for name, value in vars(args).items()
            if name not in local_reconciliation_names
        ):
            parser.error(
                "local in-flight reconciliation requires only its explicit evidence and identity"
            )
        if (
            args.tag is None
            or args.revision is None
            or args.context_sha256 is None
            or args.role != "current"
        ):
            parser.error("local in-flight reconciliation requires the exact current local identity")
        local_evidence = args.local_failure_receipt_sha256 is not None
        external_fields = (
            args.terminal_observation,
            args.terminal_observation_sha256,
            args.preflight_observation,
            args.preflight_observation_sha256,
            args.cancellation_observation,
            args.cancellation_observation_sha256,
            args.settled_observation,
            args.settled_observation_sha256,
        )
        external_complete = all(value is not None for value in external_fields)
        if (
            local_evidence == external_complete
            or any(value is not None for value in external_fields) != external_complete
        ):
            parser.error("local in-flight reconciliation requires one complete evidence mode")
        try:
            result = _reconcile_local_inflight_reservation(
                tag=args.tag,
                revision=args.revision,
                context_hash=args.context_sha256,
                role=args.role,
                local_failure_receipt_sha256=args.local_failure_receipt_sha256,
                terminal_observation=args.terminal_observation,
                terminal_sha256=args.terminal_observation_sha256,
                preflight_observation=args.preflight_observation,
                preflight_sha256=args.preflight_observation_sha256,
                cancellation_observation=args.cancellation_observation,
                cancellation_sha256=args.cancellation_observation_sha256,
                settled_observation=args.settled_observation,
                settled_sha256=args.settled_observation_sha256,
            )
        except BuildError as exc:
            failure: dict[str, object] = {"status": "failed", "stage": exc.code}
            if exc.secondary_errors:
                failure["secondary_errors"] = exc.secondary_errors
            print(
                json.dumps(failure, sort_keys=True),
                file=sys.stderr,
            )
            return 1
        print(json.dumps(result, sort_keys=True))
        return 0
    if args.reconcile_local_inflight_reservation:
        parser.error("local in-flight reconciliation requires the exact current local identity")
    if args.release_failed_inflight_reservation or args.failure_receipt_sha256 is not None:
        if (
            not args.release_failed_inflight_reservation
            or args.failure_receipt_sha256 is None
            or args.tag is None
            or args.revision is None
            or args.context_sha256 is None
            or args.role != "current"
            or args.initialize_empty_ledger
            or args.ack_retirement_receipt is not None
            or args.retire_schema13_rehearsal_tag is not None
            or args.retire_schema13_rehearsal_image_id is not None
            or args.plan_arm64_cleanup
            or args.ack_arm64_cleanup
            or args.registered_image_id
            or args.local_current_image
            or args.local_image_build
            or args.arm64_compose_build
            or any(
                value is not None
                for value in (
                    args.task_id,
                    args.project_name,
                    args.runtime_image,
                    args.frontend_image,
                    args.port,
                    args.qemu_dir,
                    args.artifact_dir,
                    args.source_head,
                    args.source_branch,
                    args.revision_label,
                    args.context,
                    args.context_owner_uid,
                )
            )
        ):
            parser.error(
                "failed inflight reservation release requires only its receipt SHA "
                "and bound identity"
            )
        try:
            result = _release_failed_inflight_reservation(
                args.tag,
                args.revision,
                args.context_sha256,
                args.role,
                args.failure_receipt_sha256,
            )
        except BuildError as exc:
            print(
                json.dumps({"status": "failed", "stage": exc.code}, sort_keys=True),
                file=sys.stderr,
            )
            return 1
        print(json.dumps(result, sort_keys=True))
        return 0
    if (
        args.retire_schema13_rehearsal_tag is not None
        or args.retire_schema13_rehearsal_image_id is not None
    ):
        if (
            args.retire_schema13_rehearsal_tag is None
            or args.retire_schema13_rehearsal_image_id is None
        ):
            parser.error("schema13 rehearsal retirement requires a fixed tag and expected image ID")
        if (
            args.initialize_empty_ledger
            or args.ack_retirement_receipt is not None
            or args.plan_arm64_cleanup
            or args.ack_arm64_cleanup
            or args.registered_image_id
            or args.local_current_image
            or args.local_image_build
            or args.arm64_compose_build
            or any(
                value is not None
                for value in (
                    args.task_id,
                    args.revision,
                    args.project_name,
                    args.runtime_image,
                    args.frontend_image,
                    args.port,
                    args.qemu_dir,
                    args.artifact_dir,
                    args.source_head,
                    args.source_branch,
                    args.revision_label,
                    args.context,
                    args.context_sha256,
                    args.context_owner_uid,
                    args.tag,
                    args.role,
                )
            )
        ):
            parser.error("schema13 rehearsal retirement accepts only a fixed tag and image ID")
        try:
            result = _retire_schema13_rehearsal_tag(
                args.retire_schema13_rehearsal_tag,
                args.retire_schema13_rehearsal_image_id,
            )
        except BuildError as exc:
            print(
                json.dumps({"status": "failed", "stage": exc.code}, sort_keys=True),
                file=sys.stderr,
            )
            return 1
        print(json.dumps(result, sort_keys=True))
        return 0
    if args.plan_arm64_cleanup or args.ack_arm64_cleanup:
        if (
            args.revision is None
            or args.runtime_image is None
            or args.frontend_image is None
            or any(
                value is not None
                for value in (
                    args.task_id,
                    args.project_name,
                    args.port,
                    args.qemu_dir,
                    args.artifact_dir,
                    args.source_head,
                    args.source_branch,
                    args.revision_label,
                    args.context,
                    args.context_sha256,
                    args.context_owner_uid,
                    args.tag,
                    args.role,
                )
            )
            or args.initialize_empty_ledger
            or args.ack_retirement_receipt is not None
            or args.local_image_build
            or args.arm64_compose_build
            or args.local_current_image
            or args.plan_arm64_cleanup == args.ack_arm64_cleanup
            or (args.plan_arm64_cleanup and args.registered_image_id)
        ):
            parser.error("ARM64 cleanup requires one exact plan or acknowledgment action")
        try:
            tags = (args.runtime_image, args.frontend_image)
            if args.plan_arm64_cleanup:
                result = _plan_arm64_cleanup(tags, args.revision)
            else:
                result = _ack_arm64_cleanup(tags, args.revision, tuple(args.registered_image_id))
        except BuildError as exc:
            print(
                json.dumps({"status": "failed", "stage": exc.code}, sort_keys=True), file=sys.stderr
            )
            return 1
        print(json.dumps(result, sort_keys=True))
        return 0
    if args.local_current_image:
        if any(
            value is not None
            for value in (
                args.task_id,
                args.revision,
                args.project_name,
                args.runtime_image,
                args.frontend_image,
                args.port,
                args.qemu_dir,
                args.artifact_dir,
                args.source_head,
                args.source_branch,
                args.revision_label,
                args.context,
                args.context_sha256,
                args.context_owner_uid,
                args.tag,
                args.role,
            )
        ) or (
            args.initialize_empty_ledger
            or args.ack_retirement_receipt is not None
            or args.plan_arm64_cleanup
            or args.ack_arm64_cleanup
            or args.registered_image_id
            or args.local_image_build
            or args.arm64_compose_build
        ):
            parser.error("the current local image query accepts no other options")
        try:
            print(json.dumps(local_current_image(), sort_keys=True))
        except BuildError as exc:
            print(
                json.dumps({"status": "failed", "stage": exc.code}, sort_keys=True), file=sys.stderr
            )
            return 1
        return 0
    if args.local_image_build or args.arm64_compose_build:
        candidate_values = (
            args.source_head,
            args.source_branch,
            args.revision_label,
            args.context,
            args.context_sha256,
            args.context_owner_uid,
            args.tag,
            args.role,
        )
        if (
            args.local_image_build == args.arm64_compose_build
            or args.initialize_empty_ledger
            or args.ack_retirement_receipt is not None
            or args.plan_arm64_cleanup
            or args.ack_arm64_cleanup
            or args.registered_image_id
            or args.local_current_image
            or any(value is not None for value in candidate_values)
        ):
            parser.error("select one bounded build mode without candidate or ledger arguments")
        if args.local_image_build:
            if any(
                value is not None
                for value in (
                    args.task_id,
                    args.revision,
                    args.project_name,
                    args.runtime_image,
                    args.frontend_image,
                    args.port,
                    args.qemu_dir,
                    args.artifact_dir,
                )
            ):
                parser.error("local image builds take no Compose arguments")
            print(json.dumps(build_local_image(), sort_keys=True))
            return 0
        if any(
            value is None
            for value in (
                args.task_id,
                args.revision,
                args.project_name,
                args.runtime_image,
                args.frontend_image,
                args.port,
                args.qemu_dir,
                args.artifact_dir,
            )
        ):
            parser.error("ARM64 Compose builds require the exact task identity and output paths")
        print(json.dumps(build_arm64_compose_images(args), sort_keys=True))
        return 0
    if args.initialize_empty_ledger or args.ack_retirement_receipt is not None:
        if (
            any(
                value is not None
                for value in (
                    args.source_head,
                    args.source_branch,
                    args.revision_label,
                    args.context,
                    args.context_sha256,
                    args.context_owner_uid,
                    args.tag,
                    args.role,
                )
            )
            or args.plan_arm64_cleanup
            or args.ack_arm64_cleanup
            or args.registered_image_id
        ):
            parser.error("ledger actions cannot be combined with a build")
        if args.initialize_empty_ledger == (args.ack_retirement_receipt is not None):
            parser.error("select exactly one ledger action")
        try:
            if args.initialize_empty_ledger:
                _initialize_empty_ledger()
            else:
                _apply_retirement_ack(args.ack_retirement_receipt)
        except BuildError as exc:
            print(
                json.dumps({"status": "failed", "stage": exc.code}, sort_keys=True),
                file=sys.stderr,
            )
            return 1
        print(json.dumps({"status": "ledger_updated"}, sort_keys=True))
        return 0
    required = (
        args.source_head,
        args.source_branch,
        args.revision_label,
        args.context,
        args.context_sha256,
        args.context_owner_uid,
        args.tag,
        args.role,
    )
    if any(value is None for value in required):
        parser.error("all build identity and context arguments are required")
    head = str(args.source_head)
    branch = str(args.source_branch)
    revision = str(args.revision_label)
    tag = str(args.tag)
    context = args.context
    context_hash = str(args.context_sha256)
    owner_uid = int(args.context_owner_uid)
    role = str(args.role)
    if (
        re.fullmatch(r"[0-9a-f]{40}", head) is None
        or re.fullmatch(r"[A-Za-z0-9._/-]{1,120}", branch) is None
        or re.fullmatch(r"(?:[0-9a-f]{40}|schema13-recovery-[0-9a-f]{64})", revision) is None
        or re.fullmatch(r"[0-9a-f]{64}", context_hash) is None
        or not _safe_tag(tag)
        or not 0 <= owner_uid <= 2**31 - 1
    ):
        parser.error("build identity, tag, or context pin is invalid")
    if os.path.lexists(context) and context.is_symlink():
        raise BuildError("candidate_context_not_directory")
    try:
        context_info = context.lstat()
    except OSError as exc:
        raise BuildError("candidate_context_unavailable") from exc
    if not stat.S_ISDIR(context_info.st_mode) or context_info.st_uid != owner_uid:
        raise BuildError("candidate_context_owner_or_type_invalid")
    observed_hash = _context_sha256(context, owner_uid)
    if observed_hash != context_hash:
        raise BuildError("candidate_context_sha_mismatch")
    setup = setup_receipt()
    with _candidate_ledger_lock():
        ledger = _ledger_read()
        if len(ledger["entries"]) >= 3:  # type: ignore[arg-type]
            raise BuildError("candidate_retention_limit_reached")
        _verify_ledger_inventory(ledger, setup)
        if tag in _image_inventory():
            raise BuildError("candidate_tag_already_exists")
    run_dir = _managed_run_dir(head, tag, context_hash)
    receipt_path = run_dir / "build-receipt.json"
    data: dict[str, object] = {
        "schema": "r120-bounded-image-build-v1",
        "status": "failed",
        "stage": "initializing",
        "source_head": head,
        "source_branch": branch,
        "revision_label": revision,
        "context_sha256": context_hash,
        "candidate_tag": tag,
        "candidate_role": role,
        "builder": BUILDER,
        "started_utc": datetime.now(UTC).isoformat(),
        "min_free_bytes": MIN_FREE,
        "stop_free_bytes": STOP_FREE,
        "timeout_seconds": TIMEOUT,
    }
    process: subprocess.Popen[bytes] | None = None
    reserved = False
    try:
        data["stage"] = "tool_and_head_pins"
        setup = setup_receipt()
        data["setup_receipt_sha256"] = hashlib.sha256(SETUP_RECEIPT.read_bytes()).hexdigest()
        uuid = str(setup.get("expected_docker_root_uuid", "")).lower()
        if not check_uuid(uuid):
            raise BuildError("setup_docker_uuid_invalid")
        verify_source(head, branch)
        data["stage"] = "builder_and_mount_preflight"
        inspect_builder(setup)
        root, free = data_root(uuid, str(setup.get("docker_root")))
        data["docker_root"] = str(root)
        data["docker_root_free_before_build_bytes"] = free
        if free < MIN_FREE:
            raise BuildError("docker_root_below_4gib_before_build")
        data["distinct_filesystem_free_bytes"] = check_space(
            (root, context, context.parent, RUNS), MIN_FREE
        )
        data["stage"] = "reservation"
        with _candidate_ledger_lock():
            ledger = _ledger_read()
            if len(ledger["entries"]) >= 3:  # type: ignore[arg-type]
                raise BuildError("candidate_retention_limit_reached")
            _verify_ledger_inventory(ledger, setup)
            if tag in _image_inventory():
                raise BuildError("candidate_tag_already_exists")
            _reserve(ledger, tag, revision, context_hash, role)
        reserved = True
        iidfile = run_dir / "image.iid"
        build_cmd = _buildx_argv(tag, revision, context, iidfile)
        data["command_policy"] = {
            "explicit_builder": BUILDER,
            "export": "--load",
            "buildkit_cache_cap_bytes": 4294967296,
            "max_parallelism": 1,
            "controller_profile": "1280m memory, 2048m memory+swap, 1 CPU, 128 PIDs",
            "worker_step_profile": (
                "verified by setup receipt RUN cgroup proof; no unsupported build flag"
            ),
            "output": "discarded",
        }
        data["stage"] = "build"
        data["build_started_utc"] = datetime.now(UTC).isoformat()
        try:
            process = subprocess.Popen(  # noqa: S603 - validated argv from the fixed Buildx builder.
                build_cmd,
                cwd=ROOT,
                env=ENV,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                shell=False,
                start_new_session=True,
            )
        except OSError as exc:
            raise BuildError("build_command_start_failed") from exc
        started = time.monotonic()
        deadline = started + TIMEOUT
        uuid_check = started
        while True:
            now = time.monotonic()
            result = process.poll()
            if result is not None:
                if now >= deadline:
                    data["build_exit_code"] = result
                    data["build_finished_utc"] = datetime.now(UTC).isoformat()
                    if result != 0:
                        raise BuildError("buildx_exit_nonzero")
                    raise BuildError("build_timeout_after_900s")
                break
            if now >= deadline:
                data["build_deadline_cancel_verified"] = cancel(process)
                if data["build_deadline_cancel_verified"] is not True:
                    raise BuildError("build_timeout_cancel_unverified")
                raise BuildError("build_timeout_after_900s")
            if now >= uuid_check:
                try:
                    verify_build_mount(uuid, str(root), deadline=deadline)
                except BuildError as exc:
                    data["build_monitor_mount_error"] = exc.code
                    if exc.code == "bounded_build_timeout":
                        data["build_deadline_cancel_verified"] = cancel(process)
                        if data["build_deadline_cancel_verified"] is not True:
                            raise BuildError("build_timeout_cancel_unverified") from exc
                        raise BuildError("build_timeout_after_900s") from exc
                    raise BuildError("build_monitor_mount_guard_failed") from exc
                if time.monotonic() >= deadline:
                    data["build_deadline_cancel_verified"] = cancel(process)
                    if data["build_deadline_cancel_verified"] is not True:
                        raise BuildError("build_timeout_cancel_unverified")
                    raise BuildError("build_timeout_after_900s")
                uuid_check = time.monotonic() + UUID_POLL
            try:
                data["last_distinct_filesystem_free_bytes"] = check_space(
                    (root, context, context.parent, RUNS), STOP_FREE
                )
            except BuildError as exc:
                if exc.code != "build_disk_floor_breached":
                    raise
                data["below_1gib_cancel_verified"] = cancel(process)
                raise BuildError("build_cancelled_below_1gib") from exc
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                data["build_deadline_cancel_verified"] = cancel(process)
                if data["build_deadline_cancel_verified"] is not True:
                    raise BuildError("build_timeout_cancel_unverified")
                raise BuildError("build_timeout_after_900s")
            time.sleep(min(POLL, remaining))
        data["build_exit_code"] = process.returncode
        data["build_finished_utc"] = datetime.now(UTC).isoformat()
        if process.returncode != 0:
            raise BuildError("buildx_exit_nonzero")
        data["stage"] = "post_build_root_identity"
        try:
            data_root(uuid, str(root), deadline=deadline)
        except BuildError as exc:
            data["post_build_root_identity_error"] = exc.code
            if exc.code == "bounded_build_timeout":
                raise BuildError("build_timeout_after_900s") from exc
            raise BuildError("post_build_root_identity_failed") from exc
        if time.monotonic() >= deadline:
            raise BuildError("build_timeout_after_900s")
        data["post_build_root_identity_verified"] = True
        data["stage"] = "image_validation"
        iid = iidfile.read_text(encoding="ascii").strip()
        if re.fullmatch(r"sha256:[0-9a-f]{64}", iid) is None:
            raise BuildError("build_iid_invalid")
        fmt = (
            "{{.Id}}|{{.Os}}/{{.Architecture}}|"
            '{{index .Config.Labels "org.opencontainers.image.revision"}}'
        )
        facts = (
            checked([DOCKER, "image", "inspect", "--format", fmt, tag])
            .decode("ascii")
            .strip()
            .split("|")
        )
        if facts != [iid, "linux/amd64", revision]:
            raise BuildError("loaded_image_identity_or_revision_mismatch")
        data.update(
            {
                "status": "built",
                "stage": "complete",
                "image_id": iid,
                "image_platform": facts[1],
                "finished_utc": datetime.now(UTC).isoformat(),
            }
        )
        digest = save_receipt(receipt_path, data)
        with _candidate_ledger_lock():
            ledger = _ledger_read(allow_inflight=True)
            _complete_reservation(
                ledger, tag, iid, revision, context_hash, role, receipt_path, digest
            )
            _verify_ledger_inventory(ledger, setup)
        reserved = False
        print(
            json.dumps(
                {
                    "status": "built",
                    "image_id": iid,
                    "receipt": str(receipt_path),
                    "receipt_sha256": digest,
                },
                sort_keys=True,
            )
        )
        return 0
    except KeyboardInterrupt:
        stopped = process is None or process.poll() is not None
        if process is not None and process.poll() is None:
            stopped = cancel(process)
        data.update(
            {
                "status": "failed",
                "stage": "operator_interrupted",
                "process_group_cancel_verified": stopped,
                "finished_utc": datetime.now(UTC).isoformat(),
            }
        )
        if reserved:
            data["ledger_reservation_retained"] = True
        digest = save_receipt(receipt_path, data) if not receipt_path.exists() else ""
        print(
            json.dumps(
                {
                    "status": "failed",
                    "stage": "operator_interrupted",
                    "receipt": str(receipt_path),
                    "receipt_sha256": digest,
                },
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 130
    except BuildError as exc:
        if process is not None and process.poll() is None:
            data["process_group_cancel_verified"] = cancel(process)
        if exc.code == "build_timeout_after_900s":
            _record_timeout_cancellation_contract(data)
        data.update(
            {
                "status": "failed",
                "stage": exc.code,
                "finished_utc": datetime.now(UTC).isoformat(),
            }
        )
        if reserved:
            data["ledger_reservation_retained"] = True
        digest = save_receipt(receipt_path, data) if not receipt_path.exists() else ""
        print(
            json.dumps(
                {
                    "status": "failed",
                    "stage": exc.code,
                    "receipt": str(receipt_path),
                    "receipt_sha256": digest,
                },
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 1


def validate_user_state() -> None:
    paths = (
        Path(USER.pw_dir),
        Path(USER.pw_dir) / ".local",
        Path(USER.pw_dir) / ".local/state",
        Path(USER.pw_dir) / ".local/state/stock-probs",
        STATE,
        DOCKER_CONFIG,
    )
    for path in paths:
        try:
            info = path.lstat()
        except OSError as exc:
            raise BuildError("user_build_state_unavailable") from exc
        if (
            stat.S_ISLNK(info.st_mode)
            or not stat.S_ISDIR(info.st_mode)
            or info.st_uid != USER.pw_uid
            or info.st_mode & 0o022
        ):
            raise BuildError("user_build_state_owner_or_mode_invalid")
    if STATE.stat().st_mode & 0o077 or DOCKER_CONFIG.stat().st_mode & 0o077:
        raise BuildError("user_build_state_owner_or_mode_invalid")


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except BuildError as exc:
        failure: dict[str, object] = {"status": "failed", "stage": exc.code}
        if exc.secondary_errors:
            failure["secondary_errors"] = exc.secondary_errors
        receipt_path = getattr(exc, "local_failure_receipt_path", None)
        receipt_sha256 = getattr(exc, "local_failure_receipt_sha256", None)
        if isinstance(receipt_path, str) and isinstance(receipt_sha256, str):
            failure["local_failure_receipt"] = {
                "path": receipt_path,
                "sha256": receipt_sha256,
            }
        print(json.dumps(failure, sort_keys=True), file=sys.stderr)
        raise SystemExit(1) from exc
