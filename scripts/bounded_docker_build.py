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
from typing import ParamSpec, TypeVar

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


def verify_builder_network(data: dict[str, object], container_id: str) -> None:
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
    attached_raw = checked(
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
            checked([DOCKER, "network", "inspect", "--format", network_format, BUILDER_NETWORK])
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


def verify_cache_volume(data: dict[str, object], container_id: str) -> None:
    raw_mounts = checked(
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
        checked(
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
        checked([FINDMNT, "-n", "-o", "UUID", "--target", str(root)])
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


@_ledger_serialized
def _discard_unloaded_local_reservation(tag: str, revision: str, setup: dict[str, object]) -> None:
    ledger = _ledger_read(allow_inflight=True)
    entries = ledger["entries"]
    assert isinstance(entries, list)
    rows = [
        row
        for row in entries
        if isinstance(row, dict) and row.get("tag") == tag and row.get("revision") == revision
    ]
    if not rows:
        return
    if (
        len(rows) != 1
        or rows[0].get("status") != "inflight"
        or rows[0].get("role") != "current"
        or tag in _image_inventory()
    ):
        return
    ledger["entries"] = [row for row in entries if row is not rows[0]]
    _atomic_json(LEDGER_FILE, ledger)
    _verify_ledger_inventory(ledger, setup)


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
    tag: str, revision: str, platform_name: str, context: Path, iidfile: Path
) -> list[str]:
    if (
        not _safe_tag(tag)
        or not tag.startswith("stock-probs:local-")
        or re.fullmatch(r"[0-9a-f]{40}", revision) is None
        or platform_name not in {"linux/amd64", "linux/arm64"}
    ):
        raise BuildError("local_build_identity_invalid")
    return [
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
        "--load",
        str(context),
    ]


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


def _run_bounded_build(
    command: list[str],
    *,
    expected_uuid: str,
    docker_root: Path,
    space_paths: tuple[Path, ...],
    env: dict[str, str],
    timeout: int,
) -> None:
    try:
        process = subprocess.Popen(  # noqa: S603 - Fixed command vector, no shell.
            command,
            cwd=ROOT,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            shell=False,
            start_new_session=True,
        )
    except OSError as exc:
        raise BuildError("bounded_build_command_start_failed") from exc

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
        try:
            command = _local_buildx_argv(tag, revision, expected_platform, context, iidfile)
            _run_bounded_build(
                command,
                expected_uuid=expected_uuid,
                docker_root=docker_root,
                space_paths=space_paths,
                env=ENV,
                timeout=TIMEOUT,
            )
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
        except BuildError:
            _discard_unloaded_local_reservation(tag, revision, setup)
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
    parser.add_argument("--retire-schema13-rehearsal-tag")
    parser.add_argument("--retire-schema13-rehearsal-image-id")
    parser.add_argument("--plan-arm64-cleanup", action="store_true")
    parser.add_argument("--ack-arm64-cleanup", action="store_true")
    parser.add_argument("--registered-image-id", action="append", default=[])
    parser.add_argument("--local-current-image", action="store_true")
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
        print(
            json.dumps({"status": "failed", "stage": exc.code}, sort_keys=True),
            file=sys.stderr,
        )
        raise SystemExit(1) from exc
