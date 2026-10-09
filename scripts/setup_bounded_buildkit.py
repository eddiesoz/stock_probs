#!/usr/bin/python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import pwd
import re
import selectors
import shutil
import signal
import stat
import subprocess
import sys
import time
import tomllib
from contextlib import suppress
from pathlib import Path

STATE = Path("/var/lib/stock-probs/r120-buildkit-v1")
USER = pwd.getpwnam("james")
USER_STATE = Path(USER.pw_dir) / ".local/state/stock-probs/r120-buildkit-v1"
CONFIG_SOURCE = Path(__file__).resolve().with_name("r120-buildkitd.toml")
CONFIG_FILE = STATE / "buildkitd.toml"
DOCKER_CONFIG = USER_STATE / "docker-config"
RECEIPT = STATE / "setup-receipt.json"
DOCKER = "/usr/bin/docker"
APT = "/usr/bin/apt-get"
FINDMNT = "/usr/bin/findmnt"
DPKG_QUERY = "/usr/bin/dpkg-query"
PYTHON = "/usr/bin/python3"
PACKAGE = "docker-buildx=0.30.1-0ubuntu1"
BUILDER = "r120-bounded"
BUILDX_LISTING_MAX_BYTES = 65536
BUILDX_LISTING_TIMEOUT = 30
NETWORK_LIST_MAX_BYTES = 65536
NETWORK_LIST_TIMEOUT = 30
CONTAINER_NAME = "/buildx_buildkit_r120-bounded0"
CACHE_VOLUME = "buildx_buildkit_r120-bounded0_state"
NETWORK_NAME = "r120-bounded-build"
NETWORK_OWNER_LABEL = "io.signal-ledger.r120-bounded-builder"
NETWORK_OWNER_VALUE = "r120-bounded"
DOCKER_SHA = "40cdaf7fd0f21089dd9e15b0c3a7dd7f2399027f010e366dac6304ae0615954a"
APT_SHA = "92ac3ad596716b94d82ece0355f29698a1ec580367b4ed26d8b5502e74c6fa7b"
FINDMNT_SHA = "104f0c23a239d1582a052caa52e0bb81bf67ad1da974274dbdb470d23704015d"
DPKG_QUERY_SHA = "82a19acac53907f83faca7d6494289fe2d074514cf1b09933114635415c2e876"
PYTHON_SHA = "52e0a13e60a981d8c4b6478be2ba5176f69da07948a056bf49cf6f077e30cb41"
CONFIG_SHA = "13cd7fdb92639849d02db6d2f9773ddb812ba777a07d409d49ddebad2e56cdb6"
BUILDX_VERSION = "0.30.1"
PROBE_BASE = (
    "python:3.11.15-slim@sha256:90744cff8f32887f075c47d747a173ff333e9e98801667af93c357fa9f5e28ff"
)
PROBE_COMM = "r12runproof"
PROBE_MARKER = b"r120-worker-cgroup-probe-v1\n"
PROBE_CONTEXT = STATE / "worker-cgroup-probe-context"
PROBE_OUTPUT = STATE / "worker-cgroup-probe-output"
CGROUP_ROOT = Path("/sys/fs/cgroup")
MEMORY = 1280 * 1024 * 1024
SWAP = 2048 * 1024 * 1024
CPU_QUOTA = 100000
CPU_PERIOD = 100000
PIDS_LIMIT = 128
MIN_FREE = 4 * 1024**3
STOP_FREE = 1024**3
PROBE_SPACE_CHECK_INTERVAL = 1.0
PROBE_SPACE_COMMAND_TIMEOUT = 2
TASK_TAG_PATTERNS = (
    re.compile(r"stock-probs:pr-candidate-[0-9a-f]{12}-[0-9a-f]{12}"),
    re.compile(r"stock-probs:schema12-base-[0-9a-f]{12}"),
    re.compile(r"stock-probs:schema13-recovery-[0-9a-f]{12}"),
    re.compile(r"stock-probs:local-[0-9a-f]{12}-[0-9a-f]{12}-[0-9a-f]{12}"),
    re.compile(r"stock-probs-[a-z0-9-]+-arm64-(?:runtime|frontend):[0-9]{8}T[0-9]{6}Z"),
    re.compile(r"ghcr\.io/jtmb/signal-ledger:sha-[0-9a-f]{40}"),
)
ENV = {
    "PATH": "/usr/bin:/bin",
    "LC_ALL": "C",
    "DOCKER_HOST": "unix:///var/run/docker.sock",
    "DOCKER_CONFIG": str(DOCKER_CONFIG),
}


class SetupError(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


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


def verify_active_buildkit_config(raw: bytes, expected_raw: bytes) -> str:
    try:
        actual = tomllib.loads(raw.decode("utf-8"))
        expected = tomllib.loads(expected_raw.decode("utf-8"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise SetupError("buildkit_config_mismatch") from exc
    if not _same_toml_value(actual, expected):
        raise SetupError("buildkit_config_mismatch")
    return hashlib.sha256(raw).hexdigest()


def call(argv: list[str], timeout: int = 30, env: dict[str, str] | None = None) -> bytes:
    try:
        result = subprocess.run(  # noqa: S603 - Fixed absolute executable and list arguments; no shell.
            argv,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env=env or ENV,
            timeout=timeout,
            check=False,
            shell=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise SetupError("fixed_command_unavailable_or_timeout") from exc
    if result.returncode:
        raise SetupError("fixed_command_failed")
    return result.stdout


def uuid_ok(value: str) -> bool:
    return (
        len(value) == 36
        and all(c in "0123456789abcdef-" for c in value)
        and value[8] == value[13] == value[18] == value[23] == "-"
    )


def data_root(
    expected_uuid: str,
    *,
    known_root: Path | None = None,
    minimum_free_bytes: int = MIN_FREE,
    insufficient_space_error: str = "docker_root_below_4gib",
    command_timeout: int = 30,
) -> tuple[Path, int]:
    if known_root is None:
        sock = Path("/var/run/docker.sock")
        try:
            sock_info = sock.lstat()
        except OSError as exc:
            raise SetupError("docker_socket_unavailable") from exc
        if stat.S_ISLNK(sock_info.st_mode) or not stat.S_ISSOCK(sock_info.st_mode):
            raise SetupError("docker_socket_unavailable")
        raw = call([DOCKER, "info", "--format", "{{.DockerRootDir}}"], timeout=command_timeout)
        root_text = raw.decode("utf-8", "strict").strip()
        if (
            not root_text
            or "\n" in root_text
            or "\r" in root_text
            or not Path(root_text).is_absolute()
        ):
            raise SetupError("docker_root_unparseable")
        root = Path(root_text).resolve(strict=True)
    else:
        try:
            root = known_root.resolve(strict=True)
        except OSError as exc:
            raise SetupError("docker_root_unavailable") from exc
        if root != known_root:
            raise SetupError("docker_root_changed_during_worker_probe")
    observed_uuid = call(
        [FINDMNT, "-n", "-o", "UUID", "--target", str(root)],
        timeout=command_timeout,
        env={"PATH": "/usr/bin:/bin", "LC_ALL": "C"},
    )
    if observed_uuid.decode("ascii", "strict").strip().lower() != expected_uuid:
        raise SetupError("docker_root_uuid_mismatch")
    free = shutil.disk_usage(root).free
    if free < minimum_free_bytes:
        raise SetupError(insufficient_space_error)
    return root, free


def validate_state_path() -> None:
    for path in (Path("/var"), Path("/var/lib"), Path("/var/lib/stock-probs"), STATE):
        try:
            info = path.lstat()
        except FileNotFoundError:
            continue
        if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode):
            raise SetupError("private_state_path_not_directory")
        if info.st_uid != 0 or info.st_mode & 0o022:
            raise SetupError("private_state_path_owner_or_mode_invalid")


def install_root_config() -> str:
    try:
        source_info = CONFIG_SOURCE.lstat()
    except OSError as exc:
        raise SetupError("buildkit_config_source_unavailable") from exc
    if not stat.S_ISREG(source_info.st_mode) or stat.S_ISLNK(source_info.st_mode):
        raise SetupError("buildkit_config_source_not_regular_file")
    raw = CONFIG_SOURCE.read_bytes()
    if hashlib.sha256(raw).hexdigest() != CONFIG_SHA:
        raise SetupError("buildkit_config_source_sha_mismatch")
    try:
        fd = os.open(CONFIG_FILE, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
        try:
            os.fchown(fd, 0, 0)
            stream = os.fdopen(fd, "wb")
            fd = -1
            with stream:
                stream.write(raw)
        finally:
            if fd >= 0:
                os.close(fd)
    except OSError as exc:
        raise SetupError("root_buildkit_config_install_failed") from exc
    os.chmod(CONFIG_FILE, 0o644)
    installed = CONFIG_FILE.lstat()
    if (
        not stat.S_ISREG(installed.st_mode)
        or installed.st_uid != 0
        or installed.st_mode & 0o022
        or hashlib.sha256(CONFIG_FILE.read_bytes()).hexdigest() != CONFIG_SHA
    ):
        raise SetupError("root_buildkit_config_verification_failed")
    return CONFIG_SHA


def write_once(path: Path, obj: dict[str, object]) -> str:
    raw = (json.dumps(obj, sort_keys=True, indent=2) + "\n").encode()
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    with os.fdopen(fd, "wb") as stream:
        stream.write(raw)
    os.chmod(path, 0o644)
    return hashlib.sha256(raw).hexdigest()


def write_fixed_file(path: Path, data: bytes) -> None:
    try:
        fd = os.open(
            path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
    except OSError as exc:
        raise SetupError("worker_probe_context_create_failed") from exc


def install_buildx() -> None:
    if sha(Path(APT)) != APT_SHA or sha(Path(DPKG_QUERY)) != DPKG_QUERY_SHA:
        raise SetupError("package_tool_binary_pin_mismatch")
    sim_env = {"PATH": "/usr/bin:/bin", "LC_ALL": "C"}
    try:
        installed = subprocess.run(  # noqa: S603 - Pinned dpkg-query executable and fixed arguments.
            [DPKG_QUERY, "-W", "-f=${Version}|${db:Status-Abbrev}", "docker-buildx"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env=sim_env,
            timeout=15,
            check=False,
            shell=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise SetupError("apt_package_version_query_unavailable") from exc
    installed_version_status = installed.stdout.decode("ascii", "replace")
    if installed.returncode == 0 and installed_version_status == (
        PACKAGE.split("=", 1)[1] + "|ii "
    ):
        if (
            sha(Path(DOCKER)) != DOCKER_SHA
            or sha(Path(FINDMNT)) != FINDMNT_SHA
            or sha(Path(PYTHON)) != PYTHON_SHA
            or sha(Path(DPKG_QUERY)) != DPKG_QUERY_SHA
        ):
            raise SetupError("native_tool_pin_mismatch")
        return
    if installed.returncode not in (0, 1):
        raise SetupError("apt_package_version_query_failed")
    try:
        sim = subprocess.run(  # noqa: S603 - Exact pinned apt package and no shell.
            [
                APT,
                "-s",
                "install",
                "--no-upgrade",
                "--no-remove",
                "--no-install-recommends",
                PACKAGE,
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env=sim_env,
            timeout=120,
            check=False,
            shell=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise SetupError("apt_simulation_unavailable") from exc
    lines = sim.stdout.decode("utf-8", "replace").splitlines()
    if sim.returncode or any(line.startswith("Remv ") for line in lines):
        raise SetupError("apt_plan_failed_or_would_remove")
    if not any(line.startswith("Inst docker-buildx ") for line in lines):
        raise SetupError("apt_plan_missing_pinned_package")
    try:
        result = subprocess.run(  # noqa: S603 - Exact pinned apt package and no shell.
            [
                APT,
                "-y",
                "install",
                "--no-upgrade",
                "--no-remove",
                "--no-install-recommends",
                PACKAGE,
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=sim_env,
            timeout=600,
            check=False,
            shell=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise SetupError("apt_install_unavailable") from exc
    if result.returncode:
        raise SetupError("apt_install_failed")
    if (
        sha(Path(DOCKER)) != DOCKER_SHA
        or sha(Path(FINDMNT)) != FINDMNT_SHA
        or sha(Path(PYTHON)) != PYTHON_SHA
        or sha(Path(DPKG_QUERY)) != DPKG_QUERY_SHA
    ):
        raise SetupError("native_tool_pin_changed_during_install")
    version = subprocess.run(  # noqa: S603 - Pinned dpkg-query executable and fixed arguments.
        [DPKG_QUERY, "-W", "-f=${Version}", "docker-buildx"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        env=sim_env,
        timeout=15,
        check=False,
        shell=False,
    )
    if version.returncode or version.stdout.decode("ascii", "replace") != PACKAGE.split("=", 1)[1]:
        raise SetupError("apt_package_version_mismatch")


def verify_manifest(image: str) -> str:
    expected = image.split("@sha256:", 1)[1]
    manifest = call([DOCKER, "buildx", "imagetools", "inspect", "--raw", image], timeout=90)
    if not manifest or len(manifest) > 2 * 1024 * 1024:
        raise SetupError("remote_manifest_size_invalid")
    if hashlib.sha256(manifest).hexdigest() != expected:
        raise SetupError("remote_manifest_digest_mismatch")
    try:
        data = json.loads(manifest)
    except json.JSONDecodeError as exc:
        raise SetupError("remote_manifest_invalid") from exc
    if not isinstance(data, dict):
        raise SetupError("remote_manifest_invalid")
    descriptors = data.get("manifests")
    if descriptors is not None and not any(
        isinstance(row, dict)
        and isinstance(row.get("platform"), dict)
        and row["platform"].get("os") == "linux"
        and row["platform"].get("architecture") == "amd64"
        for row in descriptors
    ):
        raise SetupError("remote_manifest_missing_linux_amd64")
    return expected


def legacy_task_image_inventory() -> dict[str, str]:
    raw = call(
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
            raise SetupError("task_image_inventory_invalid")
        if any(pattern.fullmatch(fields[1]) for pattern in TASK_TAG_PATTERNS):
            if fields[1] in inventory:
                raise SetupError("task_image_inventory_tag_not_unique")
            inventory[fields[1]] = fields[0]
    return inventory


def verify_buildx_version_output(output: str) -> None:
    version_pattern = re.escape(BUILDX_VERSION)
    package_version_pattern = re.escape(PACKAGE.split("=", 1)[1])
    match = re.fullmatch(
        rf"github\.com/docker/buildx v?{version_pattern}(?:\s+{package_version_pattern})?",
        output.strip(),
    )
    if match is None:
        raise SetupError("buildx_version_mismatch")


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
        raise SetupError("builder_driver_cancel_unverified") from exc
    time.sleep(0.05)
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    except OSError as exc:
        raise SetupError("builder_driver_cancel_unverified") from exc
    try:
        process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        except OSError as exc:
            raise SetupError("builder_driver_cancel_unverified") from exc
        try:
            process.wait(timeout=2)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise SetupError("builder_driver_cancel_unverified") from exc
    except OSError as exc:
        raise SetupError("builder_driver_cancel_unverified") from exc
    for _ in range(20):
        try:
            os.killpg(process.pid, 0)
        except ProcessLookupError:
            return
        except OSError as exc:
            raise SetupError("builder_driver_cancel_unverified") from exc
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            return
        except OSError as exc:
            raise SetupError("builder_driver_cancel_unverified") from exc
        time.sleep(0.05)
    raise SetupError("builder_driver_cancel_unverified")


def _capture_bounded_stdout(argv: list[str], *, max_bytes: int, timeout: float) -> bytes:
    if max_bytes < 1 or timeout <= 0:
        raise SetupError("builder_driver_capture_limits_invalid")
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
        raise SetupError("fixed_command_unavailable_or_timeout") from exc

    stream = process.stdout
    selector: selectors.BaseSelector | None = None
    completed = False
    output = bytearray()
    try:
        if stream is None:
            raise SetupError("builder_driver_capture_unavailable")
        selector = selectors.DefaultSelector()
        os.set_blocking(stream.fileno(), False)
        selector.register(stream, selectors.EVENT_READ)
        stdout_eof = False
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise SetupError("fixed_command_unavailable_or_timeout")
            if stdout_eof:
                return_code = process.poll()
                if return_code is not None:
                    completed = True
                    if return_code:
                        raise SetupError("fixed_command_failed")
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
                    raise SetupError("builder_driver_listing_too_large")
                output.extend(chunk)
    except SetupError:
        if not completed:
            _cancel_bounded_capture(process)
        raise
    except (OSError, ValueError) as exc:
        if not completed:
            _cancel_bounded_capture(process)
        raise SetupError("fixed_command_unavailable_or_timeout") from exc
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
        raise SetupError("builder_driver_listing_invalid")
    try:
        lines = raw.decode("utf-8", "strict").splitlines()
    except UnicodeDecodeError as exc:
        raise SetupError("builder_driver_listing_invalid") from exc
    if not lines or len(lines) > 64 or any(not line or len(line) > 16384 for line in lines):
        raise SetupError("builder_driver_listing_invalid")
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
            raise SetupError("builder_driver_listing_invalid") from exc
        if not isinstance(row, dict):
            raise SetupError("builder_driver_listing_invalid")
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
            raise SetupError("builder_driver_listing_invalid")
        names.add(name)
        if name == BUILDER:
            target_drivers.append(driver)
    if len(target_drivers) != 1 or target_drivers[0] != "docker-container":
        raise SetupError("builder_driver_mismatch")
    return target_drivers[0]


def buildx_driver() -> str:
    raw = _capture_bounded_stdout(
        [DOCKER, "buildx", "ls", "--format", "json"],
        max_bytes=BUILDX_LISTING_MAX_BYTES,
        timeout=BUILDX_LISTING_TIMEOUT,
    )
    return verify_buildx_driver_list(raw)


def one_container_id() -> str:
    raw = call(
        [
            DOCKER,
            "container",
            "ls",
            "--all",
            "--no-trunc",
            "--format",
            "{{.ID}}",
            "--filter",
            "name=^/buildx_buildkit_r120-bounded0$",
        ]
    )
    rows = [row for row in raw.decode("ascii", "strict").splitlines() if row]
    if len(rows) != 1 or not re.fullmatch(r"[0-9a-f]{64}", rows[0]):
        raise SetupError("builder_container_id_not_unique")
    return rows[0]


def bounded_network_ids() -> list[str]:
    raw = _capture_bounded_stdout(
        [DOCKER, "network", "ls", "--no-trunc", "--format", "{{.ID}}|{{.Name}}"],
        max_bytes=NETWORK_LIST_MAX_BYTES,
        timeout=NETWORK_LIST_TIMEOUT,
    )
    try:
        rows = raw.decode("ascii", "strict").splitlines()
    except UnicodeDecodeError as exc:
        raise SetupError("builder_network_listing_invalid") from exc
    matches: list[str] = []
    for row in rows:
        fields = row.split("|")
        if len(fields) != 2:
            raise SetupError("builder_network_listing_invalid")
        network_id, name = fields
        if name != NETWORK_NAME:
            continue
        if not re.fullmatch(r"[0-9a-f]{64}", network_id):
            raise SetupError("builder_network_id_invalid")
        matches.append(network_id)
    if len(matches) > 1:
        raise SetupError("builder_network_not_unique")
    return matches


def verify_bounded_network(network_id: str) -> dict[str, object]:
    if not re.fullmatch(r"[0-9a-f]{64}", network_id):
        raise SetupError("builder_network_id_invalid")
    fmt = "{{.Id}}|{{.Name}}|{{.Driver}}|{{.Scope}}|{{.Internal}}|{{.EnableIPv6}}|{{json .Labels}}"
    try:
        fields = (
            call([DOCKER, "network", "inspect", "--format", fmt, network_id])
            .decode("utf-8", "strict")
            .strip()
            .split("|", 6)
        )
    except UnicodeDecodeError as exc:
        raise SetupError("builder_network_inspection_invalid") from exc
    if len(fields) != 7:
        raise SetupError("builder_network_inspection_invalid")
    observed_id, name, driver, scope, internal, ipv6, labels_raw = fields
    try:
        labels = json.loads(
            labels_raw,
            object_pairs_hook=_unique_json_object,
            parse_constant=_reject_json_constant,
        )
    except (json.JSONDecodeError, RecursionError, ValueError) as exc:
        raise SetupError("builder_network_inspection_invalid") from exc
    if (
        observed_id != network_id
        or name != NETWORK_NAME
        or driver != "bridge"
        or scope != "local"
        or internal != "false"
        or ipv6 != "false"
        or not isinstance(labels, dict)
        or labels != {NETWORK_OWNER_LABEL: NETWORK_OWNER_VALUE}
    ):
        raise SetupError("builder_network_ownership_or_profile_mismatch")
    return {
        "name": NETWORK_NAME,
        "id": network_id,
        "driver": "bridge",
        "scope": "local",
        "internal": False,
        "enable_ipv6": False,
        "owner_label": {NETWORK_OWNER_LABEL: NETWORK_OWNER_VALUE},
    }


def ensure_bounded_network() -> dict[str, object]:
    matches = bounded_network_ids()
    if matches:
        network_id = matches[0]
    else:
        try:
            created = (
                call(
                    [
                        DOCKER,
                        "network",
                        "create",
                        "--driver",
                        "bridge",
                        "--ipv6=false",
                        "--label",
                        f"{NETWORK_OWNER_LABEL}={NETWORK_OWNER_VALUE}",
                        NETWORK_NAME,
                    ],
                    timeout=30,
                )
                .decode("ascii", "strict")
                .strip()
            )
        except UnicodeDecodeError as exc:
            raise SetupError("builder_network_create_result_invalid") from exc
        if not re.fullmatch(r"[0-9a-f]{64}", created):
            raise SetupError("builder_network_create_result_invalid")
        matches = bounded_network_ids()
        if matches != [created]:
            raise SetupError("builder_network_create_identity_mismatch")
        network_id = created
    return verify_bounded_network(network_id)


def verify_container_bounded_network(
    container_id: str, network: dict[str, object]
) -> dict[str, object]:
    network_id = network.get("id")
    if (
        network.get("name") != NETWORK_NAME
        or not isinstance(network_id, str)
        or not re.fullmatch(r"[0-9a-f]{64}", network_id)
    ):
        raise SetupError("builder_network_binding_invalid")
    current = verify_bounded_network(network_id)
    if current != network:
        raise SetupError("builder_network_changed")
    raw = call(
        [
            DOCKER,
            "container",
            "inspect",
            "--format",
            "{{.HostConfig.NetworkMode}}|{{json .HostConfig.PortBindings}}|"
            "{{json .NetworkSettings.Networks}}",
            container_id,
        ]
    )
    try:
        fields = raw.decode("utf-8", "strict").strip().split("|", 2)
        if len(fields) != 3:
            raise ValueError("container_network_fields_invalid")
        mode, bindings_raw, attached_raw = fields
        bindings = json.loads(
            bindings_raw,
            object_pairs_hook=_unique_json_object,
            parse_constant=_reject_json_constant,
        )
        attached = json.loads(
            attached_raw,
            object_pairs_hook=_unique_json_object,
            parse_constant=_reject_json_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError, ValueError) as exc:
        raise SetupError("builder_container_network_inspection_invalid") from exc
    if (
        mode not in {NETWORK_NAME, "bridge"}
        or bindings not in (None, {})
        or not isinstance(attached, dict)
        or set(attached) != {NETWORK_NAME}
        or not isinstance(attached[NETWORK_NAME], dict)
        or attached[NETWORK_NAME].get("NetworkID") != network_id
    ):
        raise SetupError("builder_container_network_mismatch")
    return {
        "builder_network": current,
        "builder_container_networks": {NETWORK_NAME: network_id},
    }


def inspect_container(container_id: str) -> dict[str, str]:
    fmt = (
        "{{.Id}}|{{.Name}}|{{.Image}}|{{.HostConfig.Memory}}|"
        "{{.HostConfig.MemorySwap}}|{{.HostConfig.CpuQuota}}|"
        "{{.HostConfig.CpuPeriod}}|{{.HostConfig.PidsLimit}}|{{.State.Running}}"
    )
    raw = call([DOCKER, "container", "inspect", "--format", fmt, container_id])
    fields = raw.decode("ascii", "strict").strip().split("|")
    if len(fields) != 9:
        raise SetupError("builder_container_inspection_invalid")
    names = (
        "id",
        "name",
        "image_id",
        "memory",
        "swap",
        "quota",
        "period",
        "pids",
        "running",
    )
    return dict(zip(names, fields, strict=True))


def container_host_pid(container_id: str) -> int:
    raw = call([DOCKER, "container", "inspect", "--format", "{{.State.Pid}}", container_id])
    try:
        pid = int(raw.decode("ascii", "strict").strip())
    except (UnicodeError, ValueError) as exc:
        raise SetupError("builder_host_pid_invalid") from exc
    if pid <= 1:
        raise SetupError("builder_host_pid_invalid")
    return pid


def cgroup_v2_path(pid: int) -> Path:
    try:
        rows = Path(f"/proc/{pid}/cgroup").read_text(encoding="ascii").splitlines()
    except (OSError, UnicodeError) as exc:
        raise SetupError("worker_cgroup_membership_unavailable") from exc
    unified = [row.split("::", 1)[1] for row in rows if row.startswith("0::")]
    if len(unified) != 1 or not unified[0].startswith("/"):
        raise SetupError("worker_cgroup_v2_membership_invalid")
    relative = Path(unified[0].lstrip("/"))
    if not relative.parts or any(part in {".", ".."} for part in relative.parts):
        raise SetupError("worker_cgroup_path_invalid")
    try:
        root = CGROUP_ROOT.resolve(strict=True)
        resolved = (root / relative).resolve(strict=True)
    except OSError as exc:
        raise SetupError("worker_cgroup_path_unavailable") from exc
    if not resolved.is_relative_to(root):
        raise SetupError("worker_cgroup_path_outside_root")
    return resolved


def cgroup_limits(path: Path) -> tuple[int, int, int]:
    try:
        memory = (path / "memory.max").read_text(encoding="ascii").strip()
        cpu = (path / "cpu.max").read_text(encoding="ascii").split()
    except (OSError, UnicodeError) as exc:
        raise SetupError("builder_cgroup_limits_unavailable") from exc
    if not memory.isdecimal() or len(cpu) != 2 or not all(item.isdecimal() for item in cpu):
        raise SetupError("builder_cgroup_limits_unbounded_or_invalid")
    memory_bytes, quota, period = int(memory), int(cpu[0]), int(cpu[1])
    if quota <= 0 or period <= 0:
        raise SetupError("builder_cgroup_limits_unbounded_or_invalid")
    return memory_bytes, quota, period


def matching_probe_pids() -> list[int]:
    matches = []
    try:
        entries = list(Path("/proc").iterdir())
    except OSError as exc:
        raise SetupError("worker_process_scan_unavailable") from exc
    for entry in entries:
        if not entry.name.isdecimal():
            continue
        try:
            comm = (entry / "comm").read_text(encoding="ascii").strip()
        except FileNotFoundError:
            continue
        except (OSError, UnicodeError) as exc:
            raise SetupError("worker_process_scan_incomplete") from exc
        if comm == PROBE_COMM:
            matches.append(int(entry.name))
    return matches


def verify_worker_cgroup(controller_pid: int, worker_pid: int) -> dict[str, object]:
    container_id = one_container_id()
    if re.fullmatch(r"[0-9a-f]{64}", container_id) is None:
        raise SetupError("builder_container_id_not_unique")
    if container_host_pid(container_id) != controller_pid:
        raise SetupError("builder_container_pid_identity_mismatch")
    try:
        cgroup_root = CGROUP_ROOT.resolve(strict=True)
        system_slice = cgroup_root / "system.slice"
        resolved_system_slice = system_slice.resolve(strict=True)
        boundary_candidate = system_slice / f"docker-{container_id}.scope"
        boundary = boundary_candidate.resolve(strict=True)
    except OSError as exc:
        raise SetupError("builder_container_scope_unavailable") from exc
    if (
        resolved_system_slice != system_slice
        or boundary != boundary_candidate
        or not boundary.is_relative_to(cgroup_root)
    ):
        raise SetupError("builder_container_scope_mismatch")
    controller_process = cgroup_v2_path(controller_pid)
    if controller_process not in {boundary, boundary / "init"}:
        raise SetupError("builder_controller_cgroup_scope_mismatch")
    worker = cgroup_v2_path(worker_pid)
    if not worker.is_relative_to(boundary):
        raise SetupError("worker_step_outside_bounded_builder")
    memory, quota, period = cgroup_limits(boundary)
    if (memory, quota, period) != (MEMORY, CPU_QUOTA, CPU_PERIOD):
        raise SetupError("builder_cgroup_limits_mismatch")
    return {
        "worker_cgroup_descendant": True,
        "controller_cgroup_scope_verified": True,
        "worker_cgroup_path_sha256": hashlib.sha256(str(worker).encode()).hexdigest(),
        "controller_cgroup_path_sha256": hashlib.sha256(str(boundary).encode()).hexdigest(),
        "controller_process_cgroup_path_sha256": hashlib.sha256(
            str(controller_process).encode()
        ).hexdigest(),
        "memory_max_bytes": memory,
        "cpu_quota": quota,
        "cpu_period": period,
    }


def write_probe_context() -> tuple[Path, str]:
    dockerfile = (
        f"FROM {PROBE_BASE} AS probe\n"
        "COPY probe.py /probe.py\n"
        "RUN python /probe.py\n"
        "FROM scratch\n"
        "COPY --from=probe /proof.txt /proof.txt\n"
    ).encode()
    probe = (
        b"import ctypes, pathlib, time\n"
        b"libc = ctypes.CDLL(None)\n"
        b"if libc.prctl(15, ctypes.c_char_p(b'r12runproof'), 0, 0, 0) != 0:\n"
        b"    raise SystemExit('probe process name unavailable')\n"
        b"pathlib.Path('/proof.txt').write_bytes(b'r120-worker-cgroup-probe-v1\\n')\n"
        b"time.sleep(5)\n"
    )
    try:
        PROBE_CONTEXT.mkdir(mode=0o700)
        os.chmod(PROBE_CONTEXT, 0o700)
    except FileExistsError as exc:
        raise SetupError("worker_probe_context_already_exists") from exc
    except OSError as exc:
        raise SetupError("worker_probe_context_create_failed") from exc
    write_fixed_file(PROBE_CONTEXT / "Dockerfile", dockerfile)
    write_fixed_file(PROBE_CONTEXT / "probe.py", probe)
    digest = hashlib.sha256(dockerfile + b"\0" + probe).hexdigest()
    return PROBE_CONTEXT, digest


def run_worker_cgroup_probe(
    controller_pid: int, expected_root: Path, expected_uuid: str
) -> dict[str, object]:
    container_id = one_container_id()
    if container_host_pid(container_id) != controller_pid:
        raise SetupError("builder_container_pid_identity_mismatch")
    network_ids = bounded_network_ids()
    if len(network_ids) != 1:
        raise SetupError("builder_network_missing_or_not_unique")
    network = verify_bounded_network(network_ids[0])
    network_facts = verify_container_bounded_network(container_id, network)
    image_facts = (
        call(
            [
                DOCKER,
                "image",
                "inspect",
                "--format",
                "{{.Id}}|{{.Os}}/{{.Architecture}}",
                PROBE_BASE,
            ]
        )
        .decode("ascii", "strict")
        .strip()
        .split("|")
    )
    if (
        len(image_facts) != 2
        or not re.fullmatch(r"sha256:[0-9a-f]{64}", image_facts[0])
        or image_facts[1] != "linux/amd64"
    ):
        raise SetupError("worker_probe_base_image_unavailable_or_invalid")
    if matching_probe_pids():
        raise SetupError("worker_probe_process_already_present")
    context, context_sha = write_probe_context()
    try:
        PROBE_OUTPUT.mkdir(mode=0o700)
        os.chmod(PROBE_OUTPUT, 0o700)
    except OSError as exc:
        raise SetupError("worker_probe_output_create_failed") from exc
    argv = [
        DOCKER,
        "buildx",
        "build",
        "--builder",
        BUILDER,
        "--pull=false",
        "--no-cache",
        "--network=none",
        "--platform=linux/amd64",
        "--progress=quiet",
        "--file",
        str(context / "Dockerfile"),
        "--output",
        f"type=local,dest={PROBE_OUTPUT}",
        str(context),
    ]
    checked_root, _ = data_root(expected_uuid, command_timeout=PROBE_SPACE_COMMAND_TIMEOUT)
    if checked_root != expected_root:
        raise SetupError("docker_root_changed_before_worker_probe")
    try:
        process = subprocess.Popen(  # noqa: S603 - fixed Docker probe command, no shell.
            argv,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=ENV,
            start_new_session=True,
            shell=False,
        )
    except OSError as exc:
        raise SetupError("worker_probe_build_start_failed") from exc
    deadline = time.monotonic() + 120
    next_space_check = 0.0
    observed: dict[str, object] | None = None
    return_code: int | None = None
    try:
        while True:
            if time.monotonic() >= deadline:
                break
            return_code = process.poll()
            polled_at = time.monotonic()
            if return_code is not None:
                if polled_at >= deadline:
                    return_code = None
                break
            if polled_at >= deadline:
                break
            now = polled_at
            if now >= next_space_check:
                checked_root, _ = data_root(
                    expected_uuid,
                    known_root=expected_root,
                    minimum_free_bytes=STOP_FREE,
                    insufficient_space_error="docker_root_below_1gib",
                    command_timeout=1,
                )
                if checked_root != expected_root:
                    raise SetupError("docker_root_changed_during_worker_probe")
                next_space_check = time.monotonic() + PROBE_SPACE_CHECK_INTERVAL
            pids = matching_probe_pids()
            if len(pids) > 1:
                raise SetupError("worker_step_cgroup_proof_unavailable")
            if len(pids) == 1 and observed is None:
                observed = verify_worker_cgroup(controller_pid, pids[0])
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            until_space_check = next_space_check - time.monotonic()
            sleep_for = min(0.05, remaining)
            if until_space_check > 0:
                sleep_for = min(sleep_for, until_space_check)
            time.sleep(sleep_for)
    except SetupError:
        cancel_probe_build(process)
        raise
    if observed is None:
        cancel_probe_build(process)
        raise SetupError("worker_step_cgroup_proof_unavailable")
    if return_code is None:
        cancel_probe_build(process)
        raise SetupError("worker_probe_build_timeout")
    if return_code:
        raise SetupError("worker_probe_build_failed")
    if matching_probe_pids():
        raise SetupError("worker_probe_process_remains")
    proof_path = PROBE_OUTPUT / "proof.txt"
    try:
        info = proof_path.lstat()
        content = proof_path.read_bytes()
    except OSError as exc:
        raise SetupError("worker_probe_output_missing") from exc
    if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode) or content != PROBE_MARKER:
        raise SetupError("worker_probe_output_invalid")
    if verify_container_bounded_network(container_id, network) != network_facts:
        raise SetupError("builder_container_network_changed_during_worker_probe")
    observed.update(
        {
            "schema": "r120-buildkit-run-cgroup-v1",
            "status": "passed",
            "network_none": True,
            "probe_image_id": image_facts[0],
            "probe_sha256": context_sha,
            "probe_output_sha256": hashlib.sha256(content).hexdigest(),
            **network_facts,
        }
    )
    return observed


def cancel_probe_build(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is None:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        except OSError as exc:
            raise SetupError("worker_probe_cancel_failed") from exc
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        except OSError as exc:
            raise SetupError("worker_probe_cancel_failed") from exc
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired as exc:
            raise SetupError("worker_probe_cancel_unverified") from exc
    stop_deadline = time.monotonic() + 5
    while matching_probe_pids() and time.monotonic() < stop_deadline:
        time.sleep(0.05)
    if matching_probe_pids():
        raise SetupError("worker_probe_cancel_unverified")


def inspect_cache_volume(root: Path, container_id: str, expected_uuid: str) -> dict[str, str]:
    raw_mounts = call(
        [DOCKER, "container", "inspect", "--format", "{{json .Mounts}}", container_id]
    )
    try:
        mounts = json.loads(raw_mounts)
    except json.JSONDecodeError as exc:
        raise SetupError("builder_mount_metadata_invalid") from exc
    if not isinstance(mounts, list):
        raise SetupError("builder_mount_metadata_invalid")
    state_mounts = [
        row
        for row in mounts
        if isinstance(row, dict) and row.get("Destination") == "/var/lib/buildkit"
    ]
    if len(state_mounts) != 1:
        raise SetupError("buildkit_state_volume_not_unique")
    mount = state_mounts[0]
    if (
        mount.get("Type") != "volume"
        or mount.get("Name") != CACHE_VOLUME
        or mount.get("RW") is not True
    ):
        raise SetupError("buildkit_state_volume_identity_mismatch")
    volume = (
        call(
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
    if len(volume) != 2 or volume[0] != "local":
        raise SetupError("buildkit_state_volume_driver_mismatch")
    source_text = mount.get("Source")
    if (
        not isinstance(source_text, str)
        or not source_text.startswith("/")
        or not volume[1].startswith("/")
    ):
        raise SetupError("buildkit_state_volume_path_invalid")
    try:
        root_path = root.resolve(strict=True)
    except OSError as exc:
        raise SetupError("buildkit_state_volume_path_invalid") from exc
    expected_mountpoint = str(root_path / "volumes" / CACHE_VOLUME / "_data")
    if source_text != expected_mountpoint or volume[1] != expected_mountpoint:
        raise SetupError("buildkit_state_volume_outside_docker_root")
    actual_uuid = (
        call(
            [FINDMNT, "-n", "-o", "UUID", "--target", str(root_path)],
            env={"PATH": "/usr/bin:/bin", "LC_ALL": "C"},
        )
        .decode("ascii", "strict")
        .strip()
        .lower()
    )
    if actual_uuid != expected_uuid:
        raise SetupError("buildkit_state_volume_uuid_mismatch")
    return {"name": CACHE_VOLUME, "driver": volume[0], "mountpoint": expected_mountpoint}


def ensure_user_state() -> None:
    home = Path(USER.pw_dir)
    if home != Path("/home/james"):
        raise SetupError("project_user_home_changed")
    chain = (
        home,
        home / ".local",
        home / ".local/state",
        home / ".local/state/stock-probs",
    )
    for path in chain:
        try:
            info = path.lstat()
        except FileNotFoundError:
            os.mkdir(path, 0o755)
            os.chown(path, USER.pw_uid, USER.pw_gid)
            info = path.lstat()
        if (
            not stat.S_ISDIR(info.st_mode)
            or stat.S_ISLNK(info.st_mode)
            or info.st_uid != USER.pw_uid
            or info.st_mode & 0o022
        ):
            raise SetupError("project_user_state_parent_invalid")
    try:
        USER_STATE.lstat()
    except FileNotFoundError:
        os.mkdir(USER_STATE, 0o700)
        os.chown(USER_STATE, USER.pw_uid, USER.pw_gid)
    else:
        raise SetupError("project_user_state_already_exists")
    info = USER_STATE.lstat()
    if (
        not stat.S_ISDIR(info.st_mode)
        or stat.S_ISLNK(info.st_mode)
        or info.st_uid != USER.pw_uid
        or info.st_mode & 0o077
    ):
        raise SetupError("project_user_state_owner_or_mode_invalid")


def handoff_user_docker_config() -> None:
    for current, directory_names, file_names in os.walk(
        USER_STATE, topdown=True, followlinks=False
    ):
        root = Path(current)
        root_info = root.lstat()
        if not stat.S_ISDIR(root_info.st_mode) or stat.S_ISLNK(root_info.st_mode):
            raise SetupError("project_user_state_handoff_invalid")
        for name in (*directory_names, *file_names):
            path = root / name
            info = path.lstat()
            if stat.S_ISLNK(info.st_mode) or not (
                stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode)
            ):
                raise SetupError("project_user_state_handoff_invalid")
            os.chown(path, USER.pw_uid, USER.pw_gid, follow_symlinks=False)
        os.chown(root, USER.pw_uid, USER.pw_gid, follow_symlinks=False)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Dry-run by default; set up only the pinned R120 Buildx builder."
    )
    parser.add_argument("--expected-docker-root-uuid", required=True)
    parser.add_argument("--buildkit-image", required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    uuid = args.expected_docker_root_uuid.lower()
    image = args.buildkit_image
    if not uuid_ok(uuid):
        parser.error("DockerRootDir UUID must be canonical")
    prefix = "moby/buildkit@sha256:"
    if not image.startswith(prefix) or not re.fullmatch(r"[0-9a-f]{64}", image[len(prefix) :]):
        parser.error("image must be moby/buildkit@sha256:<64 lowercase hex>")
    if not args.apply:
        print(
            json.dumps(
                {
                    "status": "dry_run",
                    "builder": BUILDER,
                    "package": PACKAGE,
                    "image": image,
                    "mutations_require": "--apply",
                },
                sort_keys=True,
            )
        )
        return 0
    if os.geteuid() != 0:
        raise SetupError("apply_requires_root")
    if sha(Path(PYTHON)) != PYTHON_SHA:
        raise SetupError("python_binary_pin_mismatch")
    validate_state_path()
    if STATE.exists() and any(STATE.iterdir()):
        raise SetupError("builder_state_not_empty")
    STATE.mkdir(parents=True, mode=0o755, exist_ok=True)
    os.chmod(STATE, 0o755)  # noqa: S103 - public read-only policy path
    receipt: dict[str, object] = {
        "schema": "r120-buildkit-setup-v1",
        "status": "failed",
        "builder": BUILDER,
        "expected_docker_root_uuid": uuid,
        "buildkit_image": image,
        "default_builder_changed": False,
    }
    container_id: str | None = None
    try:
        if sha(Path(DOCKER)) != DOCKER_SHA or sha(Path(FINDMNT)) != FINDMNT_SHA:
            raise SetupError("native_tool_pin_mismatch")
        root, free = data_root(uuid)
        legacy_inventory = legacy_task_image_inventory()
        receipt.update(
            {
                "docker_root": str(root),
                "docker_root_free_before_bytes": free,
                "legacy_task_image_inventory": legacy_inventory,
            }
        )
        receipt["buildkit_config_sha256"] = install_root_config()
        install_buildx()
        version = call([DOCKER, "buildx", "version"]).decode("utf-8", "replace")
        verify_buildx_version_output(version)
        receipt["buildx_version"] = BUILDX_VERSION
        ensure_user_state()
        DOCKER_CONFIG.mkdir(mode=0o700, parents=False, exist_ok=False)
        os.chown(DOCKER_CONFIG, USER.pw_uid, USER.pw_gid)
        receipt["verified_remote_manifest_sha256"] = verify_manifest(image)
        call([DOCKER, "pull", image], timeout=600)
        image_facts = (
            call(
                [
                    DOCKER,
                    "image",
                    "inspect",
                    "--format",
                    "{{.Id}}|{{.Os}}/{{.Architecture}}",
                    image,
                ]
            )
            .decode("ascii")
            .strip()
            .split("|")
        )
        if (
            len(image_facts) != 2
            or not re.fullmatch(r"sha256:[0-9a-f]{64}", image_facts[0])
            or image_facts[1] != "linux/amd64"
        ):
            raise SetupError("pinned_image_identity_or_platform_invalid")
        image_id = image_facts[0]
        receipt["buildkit_image_id"] = image_id
        existing = subprocess.run(  # noqa: S603 - Fixed Docker CLI command and no shell.
            [DOCKER, "buildx", "inspect", BUILDER],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=ENV,
            timeout=15,
            check=False,
            shell=False,
        )
        if existing.returncode == 0:
            raise SetupError("builder_name_already_exists")
        network = ensure_bounded_network()
        opts = (
            f"image={image},memory=1280m,memory-swap=2048m,cpu-quota=100000,"
            f"cpu-period=100000,network={NETWORK_NAME}"
        )
        call(
            [
                DOCKER,
                "buildx",
                "create",
                "--name",
                BUILDER,
                "--driver",
                "docker-container",
                "--driver-opt",
                opts,
                "--buildkitd-config",
                str(CONFIG_FILE),
                "--bootstrap",
            ],
            timeout=180,
        )
        container_id = one_container_id()
        facts = inspect_container(container_id)
        if facts["id"] != container_id or facts["name"] != CONTAINER_NAME:
            raise SetupError("created_container_identity_mismatch")
        if facts["image_id"] != image_id or facts["running"] != "true":
            raise SetupError("created_container_image_or_state_mismatch")
        verify_container_bounded_network(container_id, network)
        cache_volume = inspect_cache_volume(root, container_id, uuid)
        call(
            [
                DOCKER,
                "container",
                "update",
                "--pids-limit",
                str(PIDS_LIMIT),
                container_id,
            ]
        )
        facts = inspect_container(container_id)
        expected = {
            "memory": str(MEMORY),
            "swap": str(SWAP),
            "quota": str(CPU_QUOTA),
            "period": str(CPU_PERIOD),
            "pids": str(PIDS_LIMIT),
            "running": "true",
        }
        if any(facts.get(key) != value for key, value in expected.items()):
            raise SetupError("builder_resource_profile_mismatch")
        verify_container_bounded_network(container_id, network)
        actual = call([DOCKER, "exec", container_id, "cat", "/etc/buildkit/buildkitd.toml"])
        config_raw = CONFIG_FILE.read_bytes()
        config_sha = hashlib.sha256(config_raw).hexdigest()
        if config_sha != CONFIG_SHA:
            raise SetupError("root_buildkit_config_verification_failed")
        active_config_sha = verify_active_buildkit_config(actual, config_raw)
        driver = buildx_driver()
        worker_proof = run_worker_cgroup_probe(container_host_pid(container_id), root, uuid)
        handoff_user_docker_config()
        if legacy_task_image_inventory() != legacy_inventory:
            raise SetupError("legacy_task_image_inventory_changed_during_setup")
        root_after, free_after = data_root(uuid)
        if root_after != root or free_after < MIN_FREE:
            raise SetupError("docker_root_changed_or_below_4gib")
        receipt.update(
            {
                "status": "configured",
                "stage": "complete",
                "builder_driver": driver,
                "builder_container_id": container_id,
                "builder_container_name": CONTAINER_NAME,
                "buildkit_config_sha256": config_sha,
                "buildkit_config_path": str(CONFIG_FILE),
                "active_buildkit_config_sha256": active_config_sha,
                "active_buildkit_config_semantically_verified": True,
                "buildkit_image_id": image_id,
                "docker_root_free_after_bytes": free_after,
                "docker_host": "unix:///var/run/docker.sock",
                "docker_binary_sha256": DOCKER_SHA,
                "apt_binary_sha256": APT_SHA,
                "dpkg_query_binary_sha256": DPKG_QUERY_SHA,
                "python_binary_sha256": PYTHON_SHA,
                "findmnt_binary_sha256": FINDMNT_SHA,
                "apt_package": PACKAGE,
                "builder_container_profile": {
                    "memory_bytes": MEMORY,
                    "memory_plus_swap_bytes": SWAP,
                    "cpu_quota": CPU_QUOTA,
                    "cpu_period": CPU_PERIOD,
                    "pids_limit": PIDS_LIMIT,
                    "pids_scope": (
                        "builder controller container only; worker-step PID ceiling is not inferred"
                    ),
                },
                "buildkit_state_volume": cache_volume,
                "worker_step_cgroup_proof": worker_proof,
                "buildkit_cache_profile": {
                    "reserved_space_bytes": 1073741824,
                    "maximum_cache_bytes": 4294967296,
                    "minimum_free_bytes": 4294967296,
                    "max_parallelism": 1,
                },
            }
        )
        digest = write_once(RECEIPT, receipt)
        print(
            json.dumps(
                {
                    "status": "configured",
                    "receipt": str(RECEIPT),
                    "receipt_sha256": digest,
                    "builder": BUILDER,
                },
                sort_keys=True,
            )
        )
        return 0
    except SetupError as exc:
        receipt.update(
            {
                "stage": exc.code,
                "partial_builder_container_id": container_id,
                "partial_resource_retained_for_review": container_id is not None,
            }
        )
        digest = write_once(RECEIPT, receipt) if not RECEIPT.exists() else ""
        print(
            json.dumps(
                {
                    "status": "failed",
                    "stage": exc.code,
                    "receipt": str(RECEIPT),
                    "receipt_sha256": digest,
                },
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
