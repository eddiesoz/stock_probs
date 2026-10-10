#!/usr/bin/env python3
"""Run the fixed PR schema-13 recovery pair beside production on a disposable volume."""

from __future__ import annotations

import fcntl
import grp
import gzip
import hashlib
import http.client
import json
import os
import platform
import pwd
import re
import secrets
import selectors
import stat
import subprocess
import tarfile
import time
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import TypedDict

REPOSITORY = "eddiesoz/stock_probs"
PULL_NUMBER = 2
TASK_ID = "R-ASTRA-120"
BASE_REVISION = "da2764e8477698fa7d686be93a4711e35478e802"
BASE_IMAGE_ID = "sha256:d3e21ae9de800f0151c1eba74fb3d16423e1171985c33ea03057acbfe2278ec1"
BASE_ARCHIVE_SHA256 = "669f840a3141b0fb95ae248b5ea0799733b9e5b5b81e224d4637571c24d8f640"
MIGRATION_SHA256 = "41e7d0ef5e5267ab50a67666862bf01e4c6cfd8986b6096bd8b92deed70ff31b"
STATE_ROOT = Path("/var/lib/signal-ledger-pr-rehearsal")
INCOMING = STATE_ROOT / "incoming"
INSTALL_ROOT = Path("/usr/local/libexec/signal-ledger-pr-rehearsal")
INSTALLED_MANIFEST = INSTALL_ROOT / "installed.json"
LOCK_FILE = STATE_ROOT / "rehearsal.lock"
RECEIPT_ROOT = STATE_ROOT / "receipts"
TEMP_ROOT = STATE_ROOT / "tmp"
MAX_REQUEST = 16 * 1024
MAX_RESPONSE = 65_536
MAX_PR_RESPONSE = 65_536
MAX_ARCHIVE = 512 * 1024 * 1024
MAX_ARCHIVE_DECODED_BYTES = 2 * 1024 * 1024 * 1024
MAX_ARCHIVE_MEMBERS = 65_536
MAX_ARCHIVE_SCAN_SECONDS = 120
COPY_CHUNK = 64 * 1024
MAX_ARCHIVE_READ = 1024 * 1024
MAX_ARCHIVE_METADATA_BYTES = 1024 * 1024
MAX_ARCHIVE_METADATA_MEMBERS = 128
MAX_MEMINFO_BYTES = 16 * 1024
MAX_CGROUP_MEMORY_EVENTS_BYTES = 4 * 1024
MAX_CGROUP_CPU_STAT_BYTES = 4 * 1024
MAX_RESOURCE_COUNTER_DIGITS = 20
MAX_RESOURCE_COUNTER_VALUE = (1 << 64) - 1
MAX_OPERATION_SECONDS = 1_080
CLI_MEMORY_LIMIT = 384 * 1024 * 1024
CANDIDATE_MEMORY_LIMIT = 768 * 1024 * 1024
RECOVERY_MEMORY_LIMIT = 384 * 1024 * 1024
START_RESERVE_KIB = 512 * 1024
RUN_RESERVE_KIB = 128 * 1024
OOM_EVENT_COUNTERS = ("oom", "oom_kill", "oom_group_kill")
CPU_STAT_COUNTERS = ("usage_usec", "nr_periods", "nr_throttled", "throttled_usec")


class CgroupMemorySample(TypedDict):
    """Validated memory, OOM, and CPU counters for one container."""

    limit: int
    peak: int
    oom_events: dict[str, int]
    cpu_stat: dict[str, int]


REVISION_RE = re.compile(r"^[0-9a-f]{40}$")
DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
IMAGE_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
ASSET_REVISION_RE = re.compile(r"^[0-9a-f]{40}$")
VOLUME_RE = re.compile(r"^signal-ledger-pr1-[0-9a-f]{8}-[0-9a-f]{16}$")
RUN_ID_RE = re.compile(r"^[0-9a-f]{16}$")
CONTAINER_ID_RE = re.compile(r"^[0-9a-f]{64}$")
NETWORK_ID_RE = re.compile(r"^[0-9a-f]{64}$")
NETWORK_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,254}$")
VOLUME_INSPECT_TEMPLATE = (
    '{{.Driver}}|{{index .Labels "org.stock-probs.pr-rehearsal"}}|'
    '{{index .Labels "org.stock-probs.pr-rehearsal.head"}}|'
    '{{index .Labels "org.stock-probs.pr-rehearsal.pair"}}'
)
FIXTURE_OPERATION_CATEGORIES = {
    "seed": "fixture_seed",
    "verify-backup": "fixture_verify_backup",
    "restore-guard": "fixture_restore_guard",
    "marker": "fixture_marker",
    "snapshot": "fixture_snapshot",
}
CLEANUP_FAILURE_CODES = frozenset(
    {
        "container_removal_unverified",
        "cli_container_removal_unverified",
        "network_or_volume_removal_unverified",
        "disposable_volume_retained_for_running_container",
        "staged_archive_cleanup_unverified",
        "asset_cleanup_unverified",
        "cleanup_unverified",
    }
)
CLI_CONTAINER_NAME_RE = re.compile(
    r"^signal-ledger-pr1-[0-9a-f]{8}-[0-9a-f]{16}-cli-"
    r"(?:migrate|restore|backup|schema)-[0-9a-f]{8}$"
)
MODEL_SEGMENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:+-]{0,95}$")
INSTALLED_FILES = {
    "host_helper.py": 256 * 1024,
    "seed.py": 64 * 1024,
    "native_driver.py": 2 * 1024 * 1024,
}
CONTAINER_ASSET_INSTALLER = """\
import hashlib, os, re, stat, sys
limits = {"native_driver.py": 2 * 1024 * 1024, "seed.py": 64 * 1024}
if len(sys.argv) != 4:
    raise SystemExit(2)
name, size_text, expected_digest = sys.argv[1:]
if name not in limits or re.fullmatch(r"[0-9a-f]{64}", expected_digest) is None:
    raise SystemExit(2)
if not size_text.isascii() or not size_text.isdecimal():
    raise SystemExit(2)
size = int(size_text)
if not 1 <= size <= limits[name]:
    raise SystemExit(2)
data = sys.stdin.buffer.read(limits[name] + 1)
if len(data) != size or hashlib.sha256(data).hexdigest() != expected_digest:
    raise SystemExit(2)
directory_fd = os.open("/run/assistant", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
temporary = "." + name + "." + str(os.getpid()) + ".tmp"
file_fd = None
try:
    directory_info = os.fstat(directory_fd)
    if not stat.S_ISDIR(directory_info.st_mode) or directory_info.st_uid != 0:
        raise SystemExit(2)
    file_fd = os.open(
        temporary,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
        0o600,
        dir_fd=directory_fd,
    )
    view = memoryview(data)
    while view:
        written = os.write(file_fd, view)
        if written <= 0:
            raise OSError("short write")
        view = view[written:]
    os.fchmod(file_fd, 0o444)
    os.fsync(file_fd)
    os.close(file_fd)
    file_fd = None
    os.link(
        temporary,
        name,
        src_dir_fd=directory_fd,
        dst_dir_fd=directory_fd,
        follow_symlinks=False,
    )
    os.unlink(temporary, dir_fd=directory_fd)
    os.fsync(directory_fd)
finally:
    if file_fd is not None:
        os.close(file_fd)
    try:
        os.unlink(temporary, dir_fd=directory_fd)
    except FileNotFoundError:
        pass
    os.close(directory_fd)
"""


class StagedArchive:
    """One digest-verified immutable host-side snapshot of an uploaded image archive."""

    def __init__(self, path: Path, sha256: str, size: int, image_id: str) -> None:
        self.path = path
        self.sha256 = sha256
        self.size = size
        self.image_id = image_id


class _BoundedArchiveReader:
    """Limit gzip expansion and scan time while tarfile reads without extracting."""

    def __init__(self, source: gzip.GzipFile) -> None:
        self.source = source
        self.decoded_bytes = 0
        now = time.monotonic()
        self.deadline = now + MAX_ARCHIVE_SCAN_SECONDS
        if OPERATION_DEADLINE is not None:
            self.deadline = min(self.deadline, OPERATION_DEADLINE)
        self.next_health_check = now + 5

    def read(self, size: int = -1) -> bytes:
        if size < 0:
            raise RehearsalError("image_archive_unbounded_read")
        if size > MAX_ARCHIVE_READ:
            raise RehearsalError("image_archive_read_request_limit")
        remaining = size
        chunks: list[bytes] = []
        while remaining:
            now = time.monotonic()
            if now >= self.deadline:
                raise RehearsalError("image_archive_scan_timeout")
            if MONITOR_ACTIVE and now >= self.next_health_check:
                _check_production(PRODUCTION_SAMPLE_COUNT)
                self.next_health_check = time.monotonic() + 5
            available = MAX_ARCHIVE_DECODED_BYTES - self.decoded_bytes
            chunk = self.source.read(min(remaining, MAX_ARCHIVE_READ, available + 1))
            if not chunk:
                break
            self.decoded_bytes += len(chunk)
            if self.decoded_bytes > MAX_ARCHIVE_DECODED_BYTES:
                raise RehearsalError("image_archive_decoded_limit")
            chunks.append(chunk)
            remaining -= len(chunk)
        return b"".join(chunks)


class _BoundedTarInfo(tarfile.TarInfo):
    """Keep standard tar parsing while bounding retained PAX/GNU extension metadata."""

    @staticmethod
    def _reserve_metadata(tar_file: tarfile.TarFile, size: int) -> None:
        count = int(getattr(tar_file, "_bounded_metadata_members", 0)) + 1
        total = int(getattr(tar_file, "_bounded_metadata_bytes", 0)) + size
        if size > MAX_ARCHIVE_METADATA_BYTES or total > MAX_ARCHIVE_METADATA_BYTES:
            raise RehearsalError("image_archive_metadata_bytes_limit")
        if count > MAX_ARCHIVE_METADATA_MEMBERS:
            raise RehearsalError("image_archive_metadata_member_limit")
        tar_file._bounded_metadata_members = count
        tar_file._bounded_metadata_bytes = total

    def _proc_pax(self, tar_file: tarfile.TarFile):
        self._reserve_metadata(tar_file, self.size)
        return super()._proc_pax(tar_file)

    def _proc_gnulong(self, tar_file: tarfile.TarFile):
        self._reserve_metadata(tar_file, self.size)
        return super()._proc_gnulong(tar_file)

    def _proc_sparse(self, tar_file: tarfile.TarFile):
        raise RehearsalError("image_archive_sparse_member_unsupported")

    def _proc_gnusparse_00(self, next_member, raw_headers):
        raise RehearsalError("image_archive_sparse_member_unsupported")

    def _proc_gnusparse_01(self, next_member, pax_headers):
        raise RehearsalError("image_archive_sparse_member_unsupported")

    def _proc_gnusparse_10(self, next_member, pax_headers, tar_file):
        raise RehearsalError("image_archive_sparse_member_unsupported")


OPERATION_DEADLINE: float | None = None
MONITOR_ACTIVE = False
PRODUCTION_SAMPLE_COUNT = [0]
OPERATION_CONTAINERS: list[tuple[str, str, str, str]] = []


class RehearsalError(Exception):
    """Bounded non-sensitive host-side failure."""

    def __init__(self, code: str, *, details: dict[str, object] | None = None) -> None:
        self.code = code
        self.details = details or {}
        self.cleanup_failure: str | None = None
        super().__init__(code)


def _record_cleanup_failure(primary_error: BaseException, failure_code: str) -> None:
    """Attach the first valid closed cleanup category without replacing the primary error."""
    if not isinstance(failure_code, str) or failure_code not in CLEANUP_FAILURE_CODES:
        failure_code = "cleanup_unverified"
    existing_failure = getattr(primary_error, "cleanup_failure", None)
    if isinstance(existing_failure, str) and existing_failure in CLEANUP_FAILURE_CODES:
        return
    primary_error.cleanup_failure = failure_code  # type: ignore[attr-defined]


def _parse_request(raw: bytes) -> tuple[str, dict[str, object]]:
    if not raw or len(raw) > MAX_REQUEST:
        raise RehearsalError("request_invalid")
    try:
        value: object = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RehearsalError("request_invalid") from exc
    if not isinstance(value, dict) or set(value) != {"operation", "payload"}:
        raise RehearsalError("request_invalid")
    operation = value.get("operation")
    payload = value.get("payload")
    if operation == "cleanup_assets":
        expected = {"reviewed_head_sha"}
    elif operation == "rehearse_pr_pair":
        expected = {
            "repository",
            "pull_number",
            "reviewed_head_sha",
            "candidate_image_id",
            "candidate_source_context_sha256",
            "recovery_image_id",
            "recovery_source_context_sha256",
            "recovery_overlay_sha256",
            "pair_manifest_sha256",
            "candidate_archive_sha256",
            "recovery_archive_sha256",
        }
    else:
        raise RehearsalError("operation_invalid")
    if not isinstance(payload, dict) or set(payload) != expected:
        raise RehearsalError("payload_invalid")
    return operation, payload


def _revision(value: object) -> str:
    if not isinstance(value, str) or REVISION_RE.fullmatch(value) is None:
        raise RehearsalError("reviewed_pr_head_invalid")
    return value


def _digest(value: object, code: str) -> str:
    if not isinstance(value, str) or DIGEST_RE.fullmatch(value) is None:
        raise RehearsalError(code)
    return value


def _image_id(value: object, code: str) -> str:
    if not isinstance(value, str) or IMAGE_RE.fullmatch(value) is None:
        raise RehearsalError(code)
    return value


def _safe_directory(
    path: Path,
    mode: int,
    *,
    create: bool = False,
    group: str | None = None,
) -> None:
    if create:
        path.mkdir(mode=mode, parents=True, exist_ok=True)
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    except OSError as exc:
        raise RehearsalError("state_directory_unsafe") from exc
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0:
            raise RehearsalError("state_directory_unsafe")
        if group is not None:
            try:
                expected_gid = grp.getgrnam(group).gr_gid
            except KeyError as exc:
                raise RehearsalError("state_directory_unsafe") from exc
            if info.st_gid != expected_gid:
                os.fchown(descriptor, 0, expected_gid)
        os.fchmod(descriptor, mode)
    finally:
        os.close(descriptor)


def _read_root_file(path: Path, maximum: int) -> bytes:
    try:
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or not 1 <= info.st_size <= maximum:
            raise RehearsalError("installed_source_unsafe")
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(descriptor, "rb") as source:
            raw = source.read(maximum + 1)
    except RehearsalError:
        raise
    except OSError as exc:
        raise RehearsalError("installed_source_unavailable") from exc
    if len(raw) != info.st_size or len(raw) > maximum:
        raise RehearsalError("installed_source_changed")
    return raw


def _transfer_container_asset(container: str, name: str, contents: bytes) -> None:
    """Install one approved file through bounded stdin into the writable app tmpfs."""

    if (
        re.fullmatch(r"[0-9a-f]{64}", container) is None
        or name not in {"native_driver.py", "seed.py"}
        or not isinstance(contents, bytes)
        or not 1 <= len(contents) <= INSTALLED_FILES.get(name, 0)
    ):
        raise RehearsalError("container_asset_invalid")
    digest = hashlib.sha256(contents).hexdigest()
    _run(
        [
            "/usr/bin/docker",
            "exec",
            "-i",
            "--user",
            "0:0",
            container,
            "python",
            "-c",
            CONTAINER_ASSET_INSTALLER,
            name,
            str(len(contents)),
            digest,
        ],
        timeout=30,
        input_bytes=contents,
        maximum=4_096,
    )


def _install_container_asset(container: str, name: str, expected_digest: str) -> None:
    maximum = INSTALLED_FILES.get(name)
    if (
        maximum is None
        or name not in {"native_driver.py", "seed.py"}
        or not isinstance(expected_digest, str)
        or DIGEST_RE.fullmatch(expected_digest) is None
    ):
        raise RehearsalError("container_asset_invalid")
    contents = _read_root_file(INSTALL_ROOT / name, maximum)
    if hashlib.sha256(contents).hexdigest() != expected_digest:
        raise RehearsalError("installed_source_digest_mismatch")
    _transfer_container_asset(container, name, contents)


def _run(
    command: list[str],
    *,
    timeout: float,
    input_bytes: bytes | None = None,
    maximum: int = 32_768,
    allow_failure: bool = False,
) -> subprocess.CompletedProcess[bytes]:
    """Run fixed argv with bounded output, a hard deadline, and no inherited credentials."""
    process: subprocess.Popen[bytes] | None = None
    selector: selectors.BaseSelector | None = None
    deadline = time.monotonic() + timeout
    try:
        process = subprocess.Popen(  # noqa: S603 - command arguments below are fixed/validated.
            command,
            stdin=subprocess.PIPE if input_bytes is not None else subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env={
                "PATH": "/usr/bin:/bin",
                "HOME": str(DOCKER_HOME),
                "LANG": "C",
                "DOCKER_CONFIG": str(DOCKER_CONFIG),
            },
        )
        if process.stdout is None or process.stderr is None:
            raise RehearsalError("fixed_command_failed")
        selector = selectors.DefaultSelector()
        selector.register(process.stdout, selectors.EVENT_READ, "stdout")
        selector.register(process.stderr, selectors.EVENT_READ, "stderr")
        pending_input = memoryview(input_bytes) if input_bytes is not None else None
        if input_bytes is not None:
            if process.stdin is None:
                raise RehearsalError("fixed_command_failed")
            if pending_input:
                os.set_blocking(process.stdin.fileno(), False)
                selector.register(process.stdin, selectors.EVENT_WRITE, "stdin")
            else:
                process.stdin.close()
        output = {"stdout": bytearray(), "stderr": bytearray()}
        next_health_check = time.monotonic() + 5
        while selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                process.kill()
                with suppress(subprocess.TimeoutExpired):
                    process.wait(timeout=1)
                raise RehearsalError("fixed_command_timeout")
            if OPERATION_DEADLINE is not None:
                operation_remaining = OPERATION_DEADLINE - time.monotonic()
                if operation_remaining <= 0:
                    process.kill()
                    with suppress(subprocess.TimeoutExpired):
                        process.wait(timeout=1)
                    raise RehearsalError("rehearsal_deadline_exceeded")
                remaining = min(remaining, operation_remaining)
            if MONITOR_ACTIVE and time.monotonic() >= next_health_check:
                _check_production(PRODUCTION_SAMPLE_COUNT)
                next_health_check = time.monotonic() + 5
            for key, _ in selector.select(min(remaining, 1.0 if MONITOR_ACTIVE else remaining)):
                stream = key.fileobj
                descriptor = stream if isinstance(stream, int) else stream.fileno()
                if key.data == "stdin":
                    if pending_input is None:
                        raise RehearsalError("fixed_command_input_failed")
                    try:
                        written = os.write(descriptor, pending_input[: 64 * 1024])
                    except BrokenPipeError as exc:
                        raise RehearsalError("fixed_command_input_failed") from exc
                    if written <= 0:
                        raise RehearsalError("fixed_command_input_failed")
                    pending_input = pending_input[written:]
                    if not pending_input:
                        selector.unregister(stream)
                        stream.close()
                    continue
                chunk = os.read(descriptor, 4096)
                if not chunk:
                    selector.unregister(stream)
                    continue
                output[key.data].extend(chunk)
                if len(output[key.data]) > maximum:
                    process.kill()
                    with suppress(subprocess.TimeoutExpired):
                        process.wait(timeout=1)
                    raise RehearsalError("fixed_command_output_too_large")
        wait_remaining = deadline - time.monotonic()
        if OPERATION_DEADLINE is not None:
            operation_remaining = OPERATION_DEADLINE - time.monotonic()
            if operation_remaining <= 0:
                raise RehearsalError("rehearsal_deadline_exceeded")
            wait_remaining = min(wait_remaining, operation_remaining)
        if wait_remaining <= 0:
            raise RehearsalError("fixed_command_timeout")
        try:
            return_code = process.wait(timeout=wait_remaining)
        except subprocess.TimeoutExpired as exc:
            raise RehearsalError("fixed_command_timeout") from exc
        result = subprocess.CompletedProcess(
            command, return_code, bytes(output["stdout"]), bytes(output["stderr"])
        )
        if return_code and not allow_failure:
            raise RehearsalError(
                "fixed_command_failed",
                details={
                    "command_category": _fixed_command_category(command),
                    "exit_status": return_code,
                },
            )
        return result
    except OSError as exc:
        if process is not None and process.poll() is None:
            process.kill()
            with suppress(subprocess.TimeoutExpired):
                process.wait(timeout=1)
        raise RehearsalError("fixed_command_unavailable") from exc
    finally:
        if selector is not None:
            selector.close()
        if process is not None:
            if process.poll() is None:
                process.kill()
                with suppress(subprocess.TimeoutExpired):
                    process.wait(timeout=1)
            for stream in (process.stdin, process.stdout, process.stderr):
                if stream is not None:
                    with suppress(OSError):
                        stream.close()


def _fixed_command_category(command: list[str]) -> str:
    """Classify recognized fixed Docker argv shapes without retaining their values."""
    if (
        not command
        or any(not isinstance(argument, str) for argument in command)
        or command[0] != "/usr/bin/docker"
        or len(command) < 2
    ):
        return "other_fixed"

    if len(command) == 4 and command[1:3] == ["load", "--input"]:
        return "image_load"
    if (
        len(command) == 6
        and command[1:4] == ["image", "inspect", "--format"]
        and IMAGE_RE.fullmatch(command[5]) is not None
    ):
        return "image_inspect"
    if (
        len(command) == 8
        and command[1] == "ps"
        and command[2:4] == ["--filter", "label=com.docker.compose.project=signal-ledger"]
        and command[4:6] == ["--filter", "label=com.docker.compose.service=app"]
        and command[6:] == ["--format", "{{.ID}}"]
    ):
        return "container_list"
    if (
        len(command) == 5
        and command[1] == "inspect"
        and command[2] == "--format"
        and re.fullmatch(r"[0-9a-f]{12,64}", command[4]) is not None
    ):
        return "container_inspect"
    if (
        len(command) == 10
        and command[1:3] == ["volume", "create"]
        and command[3] == "--label"
        and command[4] == "org.stock-probs.pr-rehearsal=true"
        and command[5] == "--label"
        and re.fullmatch(r"org\.stock-probs\.pr-rehearsal\.head=[0-9a-f]{40}", command[6])
        is not None
        and command[7] == "--label"
        and re.fullmatch(r"org\.stock-probs\.pr-rehearsal\.pair=[0-9a-f]{64}", command[8])
        is not None
        and VOLUME_RE.fullmatch(command[9]) is not None
    ):
        return "volume_create"
    if (
        len(command) == 6
        and command[1:4] == ["volume", "inspect", "--format"]
        and command[4] == VOLUME_INSPECT_TEMPLATE
        and VOLUME_RE.fullmatch(command[5]) is not None
    ) or (
        len(command) == 4
        and command[1:3] == ["volume", "inspect"]
        and VOLUME_RE.fullmatch(command[3]) is not None
    ):
        return "volume_inspect"
    if (
        len(command) == 7
        and command[1:3] == ["volume", "ls"]
        and command[3] == "--filter"
        and re.fullmatch(r"name=\^(signal-ledger-pr1-[0-9a-f]{8}-[0-9a-f]{16})\$", command[4])
        is not None
        and command[5:7] == ["--format", "{{.Name}}"]
    ):
        return "volume_list"
    if (
        len(command) == 4
        and command[1:3] == ["volume", "rm"]
        and VOLUME_RE.fullmatch(command[3]) is not None
    ):
        return "volume_remove"
    if (
        len(command) >= 5
        and command[1] == "run"
        and command[2:4] == ["--rm", "--name"]
        and CLI_CONTAINER_NAME_RE.fullmatch(command[4]) is not None
    ):
        return "cli_run"
    if (
        len(command) >= 5
        and command[1] == "run"
        and command[2:4] == ["--detach", "--name"]
        and re.fullmatch(
            r"signal-ledger-pr1-[0-9a-f]{8}-[0-9a-f]{16}-(?:candidate|recovery)",
            command[4],
        )
        is not None
    ):
        return "container_run"
    if command[1] == "exec" and len(command) in {8, 12}:
        if len(command) == 8 and command[2:4] == ["--user", "10001:10001"]:
            identifier_index = 4
            command_shape = command[5:7] == ["python", "-c"]
        elif len(command) == 12 and command[2:5] == ["-i", "--user", "0:0"]:
            identifier_index = 5
            command_shape = command[6:8] == ["python", "-c"]
        else:
            identifier_index = -1
            command_shape = False
        if command_shape and CONTAINER_ID_RE.fullmatch(command[identifier_index]) is not None:
            return "container_exec"
    if (
        len(command) == 9
        and command[1:5] == ["exec", "-i", "--user", "10001:10001"]
        and CONTAINER_ID_RE.fullmatch(command[5]) is not None
        and command[6:8] == ["python", "/run/assistant/seed.py"]
        and command[8] in FIXTURE_OPERATION_CATEGORIES
    ):
        return FIXTURE_OPERATION_CATEGORIES[command[8]]
    if (
        len(command) == 3
        and command[1] == "rm"
        and CONTAINER_ID_RE.fullmatch(command[2]) is not None
    ):
        return "container_remove"
    if (
        len(command) == 4
        and command[1] == "stop"
        and command[2] == "--time=5"
        and CONTAINER_ID_RE.fullmatch(command[3]) is not None
    ):
        return "container_stop"
    if command == ["/usr/bin/docker", "version", "--format", "{{.Server.Version}}"]:
        return "docker_version"
    return "other_fixed"


def _json_output(result: subprocess.CompletedProcess[bytes], code: str) -> object:
    try:
        return json.loads(result.stdout)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RehearsalError(code) from exc


def _verify_pull_request(revision: str) -> None:
    connection = http.client.HTTPSConnection("api.github.com", timeout=10)
    try:
        connection.request(
            "GET",
            f"/repos/{REPOSITORY}/pulls/{PULL_NUMBER}",
            headers={
                "Accept": "application/vnd.github+json",
                "User-Agent": "signal-ledger-pr-rehearsal",
            },
        )
        response = connection.getresponse()
        raw = response.read(MAX_PR_RESPONSE + 1)
        if response.status != 200 or len(raw) > MAX_PR_RESPONSE:
            raise RehearsalError("reviewed_pr_unavailable")
    except (OSError, TimeoutError, http.client.HTTPException) as exc:
        raise RehearsalError("reviewed_pr_unavailable") from exc
    finally:
        connection.close()
    try:
        pr: object = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RehearsalError("reviewed_pr_invalid") from exc
    if not isinstance(pr, dict):
        raise RehearsalError("reviewed_pr_invalid")
    base, head = pr.get("base"), pr.get("head")
    repo = head.get("repo") if isinstance(head, dict) else None
    if (
        pr.get("state") != "open"
        or not isinstance(base, dict)
        or base.get("ref") != "main"
        or not isinstance(head, dict)
        or head.get("sha") != revision
        or not isinstance(repo, dict)
        or repo.get("full_name") != REPOSITORY
    ):
        raise RehearsalError("reviewed_pr_mismatch")


def _verify_installed_source(revision: str, pair_manifest_sha256: str) -> dict[str, str]:
    raw = _read_root_file(INSTALLED_MANIFEST, 8192)
    try:
        value: object = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RehearsalError("installed_manifest_invalid") from exc
    expected_files = INSTALLED_FILES
    if (
        not isinstance(value, dict)
        or set(value)
        != {
            "format_version",
            "repository",
            "pull_number",
            "reviewed_head_sha",
            "reviewed_pair_manifest_sha256",
            "files",
            "installed_at",
        }
        or value.get("format_version") != 1
        or value.get("repository") != REPOSITORY
        or value.get("pull_number") != PULL_NUMBER
        or value.get("reviewed_head_sha") != revision
        or value.get("reviewed_pair_manifest_sha256") != pair_manifest_sha256
        or not isinstance(value.get("files"), dict)
        or set(value["files"]) != set(expected_files)
    ):
        raise RehearsalError("installed_manifest_mismatch")
    files = value["files"]
    verified_files: dict[str, str] = {}
    for name, maximum in expected_files.items():
        content = _read_root_file(INSTALL_ROOT / name, maximum)
        digest = files.get(name)
        if (
            not isinstance(digest, str)
            or DIGEST_RE.fullmatch(digest) is None
            or hashlib.sha256(content).hexdigest() != digest
        ):
            raise RehearsalError("installed_source_digest_mismatch")
        verified_files[name] = digest
    return verified_files


def _read_small_asset(name: str, maximum: int, digest: str) -> bytes:
    path = INCOMING / name
    try:
        info = path.lstat()
        expected_uid = pwd.getpwnam("signalops").pw_uid
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != expected_uid
            or stat.S_IMODE(info.st_mode) & 0o077
            or not 1 <= info.st_size <= maximum
        ):
            raise RehearsalError("pair_asset_unsafe")
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(descriptor, "rb") as source:
            raw = source.read(maximum + 1)
    except RehearsalError:
        raise
    except OSError as exc:
        raise RehearsalError("pair_asset_unavailable") from exc
    if len(raw) != info.st_size or len(raw) > maximum:
        raise RehearsalError("pair_asset_changed")
    if hashlib.sha256(raw).hexdigest() != digest:
        raise RehearsalError("pair_asset_digest_mismatch")
    return raw


def _copy_stream(source_fd: int, destination_fd: int, *, maximum: int) -> tuple[int, str]:
    """Copy and hash with one fixed-size buffer rather than retaining large archive bytes."""

    digest = hashlib.sha256()
    copied = 0
    started = time.monotonic()
    deadline = started + MAX_ARCHIVE_SCAN_SECONDS
    if OPERATION_DEADLINE is not None:
        deadline = min(deadline, OPERATION_DEADLINE)
    next_health_check = started + 5
    while chunk := os.read(source_fd, COPY_CHUNK):
        now = time.monotonic()
        if now >= deadline:
            raise RehearsalError("pair_asset_copy_timeout")
        if MONITOR_ACTIVE and now >= next_health_check:
            _check_production(PRODUCTION_SAMPLE_COUNT)
            next_health_check = time.monotonic() + 5
        copied += len(chunk)
        if copied > maximum:
            raise RehearsalError("pair_asset_too_large")
        digest.update(chunk)
        view = memoryview(chunk)
        while view:
            written = os.write(destination_fd, view)
            if written <= 0:
                raise RehearsalError("pair_asset_copy_failed")
            view = view[written:]
    return copied, digest.hexdigest()


def _stage_asset(
    name: str,
    *,
    maximum: int,
    expected_digest: str,
    role: str,
    image_id: str,
    revision: str,
) -> StagedArchive:
    """Hash/copy an upload in fixed-size chunks into a root-only private snapshot."""

    source_path = INCOMING / name
    try:
        source_info = source_path.lstat()
        expected_uid = pwd.getpwnam("signalops").pw_uid
        if (
            not stat.S_ISREG(source_info.st_mode)
            or source_info.st_uid != expected_uid
            or stat.S_IMODE(source_info.st_mode) & 0o077
            or not 1 <= source_info.st_size <= maximum
        ):
            raise RehearsalError("pair_asset_unsafe")
        source_fd = os.open(source_path, os.O_RDONLY | os.O_NOFOLLOW)
    except RehearsalError:
        raise
    except OSError as exc:
        raise RehearsalError("pair_asset_unavailable") from exc

    destination = TEMP_ROOT / f"{role}-{revision}-{secrets.token_hex(8)}.tar.gz"
    destination_fd = -1
    copied = 0
    try:
        opened_source = os.fstat(source_fd)
        if (opened_source.st_dev, opened_source.st_ino) != (source_info.st_dev, source_info.st_ino):
            raise RehearsalError("pair_asset_changed")
        destination_fd = os.open(
            destination,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
        )
        copied, copied_digest = _copy_stream(source_fd, destination_fd, maximum=maximum)
        if copied != source_info.st_size or copied_digest != expected_digest:
            raise RehearsalError("pair_asset_digest_mismatch")
        final_info = os.fstat(source_fd)
        if (final_info.st_dev, final_info.st_ino, final_info.st_size) != (
            source_info.st_dev,
            source_info.st_ino,
            source_info.st_size,
        ):
            raise RehearsalError("pair_asset_changed")
        os.fsync(destination_fd)
        staged_info = os.fstat(destination_fd)
        if (
            not stat.S_ISREG(staged_info.st_mode)
            or staged_info.st_uid != 0
            or stat.S_IMODE(staged_info.st_mode) != 0o600
            or staged_info.st_size != copied
        ):
            raise RehearsalError("pair_asset_snapshot_unsafe")
    except RehearsalError:
        destination.unlink(missing_ok=True)
        raise
    except OSError as exc:
        destination.unlink(missing_ok=True)
        raise RehearsalError("pair_asset_copy_failed") from exc
    finally:
        os.close(source_fd)
        if destination_fd >= 0:
            os.close(destination_fd)
    _verify_archive_manifest(destination, image_id)
    return StagedArchive(destination, expected_digest, copied, image_id)


OCI_CREATED_ANNOTATION_KEY = "org.opencontainers.image.created"
OCI_CREATED_TIMESTAMP_RE = re.compile(
    r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,9})?Z"
)


def _valid_oci_created_timestamp(value: object) -> bool:
    """Return whether an OCI created annotation is a bounded UTC RFC3339 timestamp."""
    if (
        not isinstance(value, str)
        or len(value) > 30
        or OCI_CREATED_TIMESTAMP_RE.fullmatch(value) is None
    ):
        return False
    try:
        datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        return False
    return True


def _verify_archive_manifest(path: Path, image_id: str) -> None:
    """Validate legacy Docker and OCI-layout saves without extracting or buffering layers."""
    if IMAGE_RE.fullmatch(image_id) is None:
        raise RehearsalError("image_archive_identity_invalid")

    def read_json_member(archive: tarfile.TarFile, member: tarfile.TarInfo) -> tuple[object, bytes]:
        if not member.isfile() or member.size > 64 * 1024:
            raise RehearsalError("image_archive_metadata_invalid")
        stream = archive.extractfile(member)
        if stream is None:
            raise RehearsalError("image_archive_metadata_invalid")
        try:
            payload = stream.read(64 * 1024 + 1)
            if len(payload) != member.size or len(payload) > 64 * 1024:
                raise RehearsalError("image_archive_metadata_invalid")
            return json.loads(payload), payload
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RehearsalError("image_archive_metadata_invalid") from exc

    try:
        with path.open("rb") as raw:
            compressed = gzip.GzipFile(fileobj=raw, mode="rb")
            bounded = _BoundedArchiveReader(compressed)
            metadata: dict[str, object] = {}
            member_sizes: dict[str, int] = {}
            archive_names: set[str] = set()
            member_types: dict[str, str] = {}
            member_count = 0
            image_manifest_path = f"blobs/sha256/{image_id.removeprefix('sha256:')}"
            json_members = {"manifest.json", "oci-layout", "index.json", image_manifest_path}
            with tarfile.open(fileobj=bounded, mode="r|", tarinfo=_BoundedTarInfo) as archive:
                for member in archive:
                    try:
                        member_count += 1
                        if member_count > MAX_ARCHIVE_MEMBERS:
                            raise RehearsalError("image_archive_member_limit")
                        if (
                            not member.name
                            or len(member.name) > 4096
                            or member.name.startswith("/")
                            or "\\" in member.name
                            or any(part in {".", ".."} for part in member.name.split("/"))
                            or any(ord(char) < 32 or ord(char) == 127 for char in member.name)
                            or member.name in archive_names
                        ):
                            raise RehearsalError("image_archive_member_name_invalid")
                        if member.isfile():
                            member_type = "file"
                        elif member.isdir():
                            member_type = "directory"
                        else:
                            raise RehearsalError("image_archive_member_type_invalid")
                        archive_names.add(member.name)
                        member_types[member.name] = member_type
                        if member.name not in json_members:
                            continue
                        if member.name in metadata:
                            raise RehearsalError("image_archive_metadata_duplicate")
                        value, payload = read_json_member(archive, member)
                        if member.name == image_manifest_path and hashlib.sha256(
                            payload
                        ).hexdigest() != image_id.removeprefix("sha256:"):
                            raise RehearsalError("image_archive_manifest_digest_mismatch")
                        metadata[member.name] = value
                        member_sizes[member.name] = member.size
                    finally:
                        # TarFile keeps every visited TarInfo in this list, even in r| mode.
                        archive.members.clear()
            if "manifest.json" not in metadata:
                raise RehearsalError("image_archive_manifest_invalid")
    except RehearsalError:
        raise
    except (
        OSError,
        EOFError,
        gzip.BadGzipFile,
        tarfile.TarError,
        UnicodeDecodeError,
        json.JSONDecodeError,
    ) as exc:
        raise RehearsalError("image_archive_invalid") from exc
    manifest = metadata["manifest.json"]
    if (
        not isinstance(manifest, list)
        or len(manifest) != 1
        or not isinstance(manifest[0], dict)
        or set(manifest[0]) != {"Config", "RepoTags", "Layers"}
        or manifest[0].get("RepoTags") not in ([], None)
        or not isinstance(manifest[0].get("Config"), str)
        or not isinstance(manifest[0].get("Layers"), list)
        or not manifest[0]["Layers"]
        or any(not isinstance(layer, str) or not layer for layer in manifest[0]["Layers"])
    ):
        raise RehearsalError("image_archive_identity_mismatch")

    config_path = manifest[0]["Config"]
    layers = manifest[0]["Layers"]
    if config_path == f"{image_id.removeprefix('sha256:')}.json":
        if any(name in metadata for name in ("oci-layout", "index.json", image_manifest_path)):
            raise RehearsalError("image_archive_identity_mismatch")
        referenced_files = [config_path, *layers]
    else:
        oci_layout = metadata.get("oci-layout")
        index = metadata.get("index.json")
        image_manifest = metadata.get(image_manifest_path)
        image_manifest_size = member_sizes.get(image_manifest_path)
        if (
            oci_layout != {"imageLayoutVersion": "1.0.0"}
            or not isinstance(index, dict)
            or set(index) != {"schemaVersion", "mediaType", "manifests"}
            or index.get("schemaVersion") != 2
            or index.get("mediaType") != "application/vnd.oci.image.index.v1+json"
            or not isinstance(index.get("manifests"), list)
            or len(index["manifests"]) != 1
            or not isinstance(index["manifests"][0], dict)
            or set(index["manifests"][0])
            not in (
                {"digest", "mediaType", "size"},
                {"annotations", "digest", "mediaType", "size"},
            )
            or index["manifests"][0].get("digest") != image_id
            or index["manifests"][0].get("mediaType")
            != "application/vnd.oci.image.manifest.v1+json"
            or type(index["manifests"][0].get("size")) is not int
            or index["manifests"][0].get("size") != image_manifest_size
            or not isinstance(image_manifest, dict)
            or image_manifest.get("schemaVersion") != 2
            or image_manifest.get("mediaType") != "application/vnd.oci.image.manifest.v1+json"
        ):
            raise RehearsalError("image_archive_identity_mismatch")
        descriptor = index["manifests"][0]
        if "annotations" in descriptor:
            annotations = descriptor["annotations"]
            if (
                not isinstance(annotations, dict)
                or set(annotations) != {OCI_CREATED_ANNOTATION_KEY}
                or not _valid_oci_created_timestamp(annotations.get(OCI_CREATED_ANNOTATION_KEY))
            ):
                raise RehearsalError("image_archive_identity_mismatch")
        config = image_manifest.get("config")
        oci_layers = image_manifest.get("layers")
        if (
            not isinstance(config, dict)
            or set(config) != {"mediaType", "digest", "size"}
            or config.get("mediaType") != "application/vnd.oci.image.config.v1+json"
            or not isinstance(config.get("digest"), str)
            or re.fullmatch(r"sha256:[0-9a-f]{64}", config["digest"]) is None
            or type(config.get("size")) is not int
            or not 0 < config["size"] <= MAX_ARCHIVE_DECODED_BYTES
            or not isinstance(oci_layers, list)
            or not oci_layers
            or any(
                not isinstance(layer, dict)
                or set(layer) != {"mediaType", "digest", "size"}
                or layer.get("mediaType")
                not in {
                    "application/vnd.oci.image.layer.v1.tar+gzip",
                    "application/vnd.docker.image.rootfs.diff.tar.gzip",
                }
                or not isinstance(layer.get("digest"), str)
                or re.fullmatch(r"sha256:[0-9a-f]{64}", layer["digest"]) is None
                or type(layer.get("size")) is not int
                or not 0 < layer["size"] <= MAX_ARCHIVE_DECODED_BYTES
                for layer in oci_layers
            )
        ):
            raise RehearsalError("image_archive_identity_mismatch")
        expected_config_path = f"blobs/sha256/{config['digest'].removeprefix('sha256:')}"
        expected_layer_paths = [
            f"blobs/sha256/{layer['digest'].removeprefix('sha256:')}" for layer in oci_layers
        ]
        if config_path != expected_config_path or layers != expected_layer_paths:
            raise RehearsalError("image_archive_identity_mismatch")
        referenced_files = [
            config_path,
            *layers,
            "oci-layout",
            "index.json",
            image_manifest_path,
        ]
    if any(member_types.get(name) != "file" for name in referenced_files):
        raise RehearsalError("image_archive_identity_mismatch")


def _verify_pair(
    payload: dict[str, object], revision: str
) -> tuple[dict[str, object], dict[str, StagedArchive]]:
    candidate_id = _image_id(payload.get("candidate_image_id"), "candidate_image_id_invalid")
    recovery_id = _image_id(payload.get("recovery_image_id"), "recovery_image_id_invalid")
    candidate_context = _digest(
        payload.get("candidate_source_context_sha256"), "candidate_context_invalid"
    )
    recovery_context = _digest(
        payload.get("recovery_source_context_sha256"), "recovery_context_invalid"
    )
    overlay_hash = _digest(payload.get("recovery_overlay_sha256"), "recovery_overlay_invalid")
    manifest_hash = _digest(payload.get("pair_manifest_sha256"), "pair_manifest_invalid")
    candidate_hash = _digest(payload.get("candidate_archive_sha256"), "candidate_archive_invalid")
    recovery_hash = _digest(payload.get("recovery_archive_sha256"), "recovery_archive_invalid")
    names = {
        "candidate": f"signal-ledger-pr1-{revision}-candidate.tar.gz",
        "recovery": f"signal-ledger-pr1-{revision}-recovery.tar.gz",
        "manifest": f"signal-ledger-pr1-{revision}-pair.json",
    }
    assets: dict[str, object] = {
        "manifest": _read_small_asset(names["manifest"], 65_536, manifest_hash),
    }
    manifest_bytes = assets["manifest"]
    if not isinstance(manifest_bytes, bytes):
        raise RehearsalError("pair_manifest_invalid")
    try:
        manifest: object = json.loads(manifest_bytes)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RehearsalError("pair_manifest_invalid") from exc
    if not isinstance(manifest, dict):
        raise RehearsalError("pair_manifest_invalid")
    candidate, recovery, migration = (
        manifest.get("candidate"),
        manifest.get("recovery"),
        manifest.get("migration"),
    )
    candidate_keys = {
        "asset",
        "archive_sha256",
        "archive_size",
        "image_id",
        "platform",
        "revision",
        "schema_version",
        "source_context_sha256",
    }
    recovery_keys = {
        "asset",
        "archive_sha256",
        "archive_size",
        "image_id",
        "platform",
        "revision",
        "schema_version",
        "assistant_enabled",
        "base_revision",
        "base_image_id",
        "base_archive_sha256",
        "base_source_context_sha256",
        "overlay_sha256",
        "source_context_sha256",
        "migration_sha256",
    }
    valid = (
        set(manifest)
        == {
            "format_version",
            "repository",
            "revision",
            "source_context_sha256",
            "migration",
            "candidate",
            "recovery",
        }
        and type(manifest.get("format_version")) is int
        and manifest.get("format_version") == 1
        and manifest.get("repository") == REPOSITORY
        and manifest.get("revision") == revision
        and manifest.get("source_context_sha256") == candidate_context
        and isinstance(migration, dict)
        and migration == {"from_schema": 12, "to_schema": 13, "sha256": MIGRATION_SHA256}
        and isinstance(candidate, dict)
        and set(candidate) == candidate_keys
        and candidate.get("asset") == f"signal-ledger-image-{revision}.tar.gz"
        and candidate.get("archive_sha256") == candidate_hash
        and type(candidate.get("archive_size")) is int
        and candidate.get("archive_size") <= MAX_ARCHIVE
        and candidate.get("image_id") == candidate_id
        and candidate.get("platform") == "linux/amd64"
        and candidate.get("revision") == revision
        and candidate.get("schema_version") == 13
        and candidate.get("source_context_sha256") == candidate_context
        and isinstance(recovery, dict)
        and set(recovery) == recovery_keys
        and recovery.get("asset") == f"signal-ledger-recovery-{revision}.tar.gz"
        and recovery.get("archive_sha256") == recovery_hash
        and type(recovery.get("archive_size")) is int
        and recovery.get("archive_size") <= MAX_ARCHIVE
        and recovery.get("image_id") == recovery_id
        and recovery.get("platform") == "linux/amd64"
        and recovery.get("revision") == revision
        and recovery.get("schema_version") == 13
        and recovery.get("assistant_enabled") is False
        and recovery.get("base_revision") == BASE_REVISION
        and recovery.get("base_image_id") == BASE_IMAGE_ID
        and recovery.get("base_archive_sha256") == BASE_ARCHIVE_SHA256
        and isinstance(recovery.get("base_source_context_sha256"), str)
        and DIGEST_RE.fullmatch(str(recovery.get("base_source_context_sha256"))) is not None
        and recovery.get("source_context_sha256") == recovery_context
        and recovery.get("overlay_sha256") == overlay_hash
        and recovery.get("migration_sha256") == MIGRATION_SHA256
    )
    if not valid:
        raise RehearsalError("pair_manifest_identity_mismatch")
    candidate_archive = _stage_asset(
        names["candidate"],
        maximum=MAX_ARCHIVE,
        expected_digest=candidate_hash,
        role="candidate",
        image_id=candidate_id,
        revision=revision,
    )
    recovery_archive = _stage_asset(
        names["recovery"],
        maximum=MAX_ARCHIVE,
        expected_digest=recovery_hash,
        role="recovery",
        image_id=recovery_id,
        revision=revision,
    )
    if candidate_archive.size != candidate.get(
        "archive_size"
    ) or recovery_archive.size != recovery.get("archive_size"):
        candidate_archive.path.unlink(missing_ok=True)
        recovery_archive.path.unlink(missing_ok=True)
        raise RehearsalError("pair_asset_size_mismatch")
    return manifest, {"candidate": candidate_archive, "recovery": recovery_archive}


def _parse_meminfo_kib(raw: bytes) -> tuple[int, int]:
    """Parse bounded host capacity and available-memory counters from procfs."""

    if len(raw) > MAX_MEMINFO_BYTES:
        raise RehearsalError(
            "host_memory_evidence_too_large",
            details={
                "host_memory_evidence_complete": False,
                "missing_counters": ["MemTotal", "MemAvailable"],
                "capacity_claim": "unavailable",
            },
        )
    try:
        lines = raw.decode("ascii").splitlines()
    except UnicodeDecodeError as exc:
        raise RehearsalError(
            "host_memory_evidence_invalid",
            details={
                "host_memory_evidence_complete": False,
                "missing_counters": ["MemTotal", "MemAvailable"],
                "capacity_claim": "unavailable",
            },
        ) from exc

    values: dict[str, int] = {}
    invalid: list[str] = []
    for line in lines:
        key, separator, value = line.partition(":")
        if key not in {"MemTotal", "MemAvailable"}:
            continue
        fields = value.split()
        if not separator or key in values or len(fields) != 2 or fields[1] != "kB":
            invalid.append(key)
            continue
        if (
            not fields[0].isascii()
            or not fields[0].isdecimal()
            or len(fields[0]) > MAX_RESOURCE_COUNTER_DIGITS
        ):
            invalid.append(key)
            continue
        parsed = int(fields[0])
        if parsed <= 0 or parsed > MAX_RESOURCE_COUNTER_VALUE:
            invalid.append(key)
            continue
        values[key] = parsed

    missing = sorted({"MemTotal", "MemAvailable"} - values.keys())
    if invalid or missing or values.get("MemAvailable", 0) > values.get("MemTotal", 0):
        raise RehearsalError(
            "host_memory_evidence_incomplete",
            details={
                "host_memory_evidence_complete": False,
                "missing_counters": missing,
                "invalid_counters": sorted(set(invalid)),
                "capacity_claim": "unavailable",
            },
        )
    return values["MemTotal"], values["MemAvailable"]


def _host_memory_kib() -> tuple[int, int]:
    """Read actual host MemTotal and MemAvailable using a fixed bounded procfs read."""

    try:
        with Path("/proc/meminfo").open("rb") as source:
            raw = source.read(MAX_MEMINFO_BYTES + 1)
    except OSError as exc:
        raise RehearsalError(
            "host_memory_evidence_unavailable",
            details={
                "host_memory_evidence_complete": False,
                "missing_counters": ["MemTotal", "MemAvailable"],
                "capacity_claim": "unavailable",
            },
        ) from exc
    return _parse_meminfo_kib(raw)


def _memavailable_kib() -> int:
    return _host_memory_kib()[1]


def _memtotal_kib() -> int:
    return _host_memory_kib()[0]


def _readiness() -> dict[str, object]:
    connection = http.client.HTTPConnection("127.0.0.1", 8000, timeout=3)
    try:
        connection.request("GET", "/api/v1/readiness", headers={"Host": "localhost"})
        response = connection.getresponse()
        raw = response.read(16_385)
        if response.status != 200 or len(raw) > 16_384:
            raise RehearsalError("production_health_unavailable")
        value: object = json.loads(raw)
    except RehearsalError:
        raise
    except (
        OSError,
        TimeoutError,
        http.client.HTTPException,
        UnicodeDecodeError,
        json.JSONDecodeError,
    ) as exc:
        raise RehearsalError("production_health_unavailable") from exc
    finally:
        connection.close()
    if not isinstance(value, dict):
        raise RehearsalError("production_health_invalid")
    return value


def _check_production(sample_count: list[int], *, startup: bool = False) -> int:
    available = _memavailable_kib()
    floor = START_RESERVE_KIB if startup else RUN_RESERVE_KIB
    if available < floor:
        raise RehearsalError("host_memory_reserve_breached")
    readiness = _readiness()
    if readiness.get("status") != "ready" or readiness.get("schema_version") != 12:
        raise RehearsalError("production_health_lost")
    sample_count[0] += 1
    return available


def _production_container() -> None:
    result = _run(
        [
            "/usr/bin/docker",
            "ps",
            "--filter",
            "label=com.docker.compose.project=signal-ledger",
            "--filter",
            "label=com.docker.compose.service=app",
            "--format",
            "{{.ID}}",
        ],
        timeout=10,
    )
    identifiers = result.stdout.decode("ascii", errors="strict").splitlines()
    if len(identifiers) != 1 or re.fullmatch(r"[0-9a-f]{12,64}", identifiers[0]) is None:
        raise RehearsalError("production_app_identity_unavailable")
    template = (
        '{{.Image}}|{{.State.Status}}|{{index .Config.Labels "org.opencontainers.image.revision"}}'
    )
    result = _run(["/usr/bin/docker", "inspect", "--format", template, identifiers[0]], timeout=10)
    values = result.stdout.decode("ascii", errors="strict").strip().split("|")
    if values != [BASE_IMAGE_ID, "running", BASE_REVISION]:
        raise RehearsalError("production_baseline_mismatch")
    ready = _readiness()
    if ready.get("status") != "ready" or ready.get("schema_version") != 12:
        raise RehearsalError("production_health_unavailable")


def _image_identity(image_id: str, revision: str) -> None:
    template = (
        "{{.Id}}|{{.Os}}|{{.Architecture}}|"
        '{{index .Config.Labels "org.opencontainers.image.revision"}}'
    )
    result = _run(
        ["/usr/bin/docker", "image", "inspect", "--format", template, image_id], timeout=15
    )
    values = result.stdout.decode("ascii", errors="strict").strip().split("|")
    if values != [image_id, "linux", "amd64", revision]:
        raise RehearsalError("loaded_image_identity_mismatch")


def _verify_staged_archive(archive: StagedArchive) -> None:
    try:
        before = archive.path.lstat()
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_uid != 0
            or stat.S_IMODE(before.st_mode) != 0o600
            or before.st_size != archive.size
        ):
            raise RehearsalError("pair_asset_snapshot_unsafe")
        descriptor = os.open(archive.path, os.O_RDONLY | os.O_NOFOLLOW)
    except RehearsalError:
        raise
    except OSError as exc:
        raise RehearsalError("pair_asset_snapshot_unavailable") from exc
    digest = hashlib.sha256()
    try:
        opened = os.fstat(descriptor)
        if (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
            raise RehearsalError("pair_asset_snapshot_changed")
        size = 0
        while chunk := os.read(descriptor, COPY_CHUNK):
            size += len(chunk)
            if size > archive.size:
                raise RehearsalError("pair_asset_snapshot_changed")
            digest.update(chunk)
        final = os.fstat(descriptor)
        if (
            size != archive.size
            or digest.hexdigest() != archive.sha256
            or (final.st_dev, final.st_ino, final.st_size)
            != (before.st_dev, before.st_ino, before.st_size)
        ):
            raise RehearsalError("pair_asset_snapshot_changed")
    finally:
        os.close(descriptor)


def _load_image(revision: str, role: str, image_id: str, archive: StagedArchive) -> None:
    if archive.image_id != image_id or role not in {"candidate", "recovery"}:
        raise RehearsalError("pair_asset_identity_mismatch")
    _verify_staged_archive(archive)
    try:
        _run(["/usr/bin/docker", "load", "--input", str(archive.path)], timeout=180)
        _image_identity(image_id, revision)
    except OSError as exc:
        raise RehearsalError("image_load_failed") from exc


def _volume_cli(
    image_id: str,
    volume: str,
    args: list[str],
    *,
    revision: str,
    pair_manifest_sha256: str,
    expected_rejection: str | None = None,
) -> object:
    if not (
        args == ["migrate"]
        or (
            len(args) == 2
            and args[0] == "restore"
            and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,95}\.spbackup", args[1])
        )
        or (
            len(args) == 3
            and args[:2] == ["backup", "--name"]
            and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,95}\.spbackup", args[2])
        )
    ):
        raise RehearsalError("migration_operation_invalid")
    stage = args[0]
    run_id = _run_id_for_volume(volume)
    cli_name = f"{volume}-cli-{stage}-{secrets.token_hex(4)}"
    command = [
        "/usr/bin/docker",
        "run",
        "--rm",
        "--name",
        cli_name,
        "--label",
        "org.stock-probs.pr-rehearsal=true",
        "--label",
        f"org.stock-probs.pr-rehearsal.task={TASK_ID}",
        "--label",
        f"org.stock-probs.pr-rehearsal.run={run_id}",
        "--label",
        f"org.stock-probs.pr-rehearsal.head={revision}",
        "--label",
        f"org.stock-probs.pr-rehearsal.pair={pair_manifest_sha256}",
        "--label",
        "org.stock-probs.pr-rehearsal.role=cli",
        "--label",
        f"org.stock-probs.pr-rehearsal.volume={volume}",
        "--network=none",
        "--read-only",
        "--user",
        "10001:10001",
        "--volume",
        f"{volume}:/data",
        "--tmpfs",
        "/tmp:rw,nosuid,nodev,noexec,size=64m,uid=10001,gid=10001,mode=0700",  # noqa: S108 - app-only tmpfs.
        "--memory",
        str(CLI_MEMORY_LIMIT),
        "--memory-swap",
        str(CLI_MEMORY_LIMIT),
        "--cpus",
        "1.0",
        "--pids-limit",
        "128",
        "--env=STOCK_PROBS_DATA_DIR=/data",
        "--env=STOCK_PROBS_ENV=test",
        "--env=STOCK_PROBS_PROVIDER=fixture",
        "--env=STOCK_PROBS_AUTH_MODE=disabled",
        "--entrypoint",
        "stock-probs",
        image_id,
        *args,
    ]
    tracked = (cli_name, volume, revision, pair_manifest_sha256)
    OPERATION_CONTAINERS.append(tracked)
    try:
        result = _run(command, timeout=180, allow_failure=expected_rejection is not None)
    except RehearsalError:
        raise
    else:
        OPERATION_CONTAINERS.remove(tracked)
    if expected_rejection is not None:
        try:
            failure = json.loads(result.stderr)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RehearsalError("restore_refusal_invalid") from exc
        if (
            result.returncode != 2
            or not isinstance(failure, dict)
            or not isinstance(failure.get("error"), str)
            or expected_rejection not in failure["error"]
        ):
            raise RehearsalError("restore_refusal_not_enforced")
        return {"restore_denied": True}
    return _json_output(result, "migration_cli_invalid")


def _schema_probe_source(database_path: str = "/data/stock_probs.sqlite3") -> str:
    if (
        not isinstance(database_path, str)
        or not Path(database_path).is_absolute()
        or "\x00" in database_path
        or "?" in database_path
        or "#" in database_path
    ):
        raise RehearsalError("schema_probe_path_invalid")
    return (  # noqa: S608 - fixed query; the validated path is embedded only in the SQLite URI.
        "import json,sqlite3; "  # noqa: S608 - fixed query; dynamic path is only a SQLite URI.
        f"uri={('file:' + Path(database_path).resolve().as_posix() + '?mode=ro')!r}; "
        "c=sqlite3.connect(uri,uri=True,timeout=3); "
        "c.execute('PRAGMA query_only=ON'); "
        "v=[int(r[0]) for r in c.execute("
        "'SELECT version FROM schema_migrations ORDER BY version')]; "
        "c.close(); print(json.dumps({'versions':v,'max':max(v) if v else 0}))"
    )


def _schema_version(image_id: str, volume: str, *, revision: str, pair_manifest_sha256: str) -> int:
    run_id = _run_id_for_volume(volume)
    cli_name = f"{volume}-cli-schema-{secrets.token_hex(4)}"
    tracked = (cli_name, volume, revision, pair_manifest_sha256)
    OPERATION_CONTAINERS.append(tracked)
    result = _run(
        [
            "/usr/bin/docker",
            "run",
            "--rm",
            "--name",
            cli_name,
            "--label",
            "org.stock-probs.pr-rehearsal=true",
            "--label",
            f"org.stock-probs.pr-rehearsal.task={TASK_ID}",
            "--label",
            f"org.stock-probs.pr-rehearsal.run={run_id}",
            "--label",
            f"org.stock-probs.pr-rehearsal.head={revision}",
            "--label",
            f"org.stock-probs.pr-rehearsal.pair={pair_manifest_sha256}",
            "--label",
            "org.stock-probs.pr-rehearsal.role=cli",
            "--label",
            f"org.stock-probs.pr-rehearsal.volume={volume}",
            "--network=none",
            "--read-only",
            "--user",
            "10001:10001",
            "--volume",
            f"{volume}:/data",
            "--tmpfs",
            "/tmp:rw,nosuid,nodev,noexec,size=64m,uid=10001,gid=10001,mode=0700",  # noqa: S108 - app-only tmpfs.
            "--memory",
            str(CLI_MEMORY_LIMIT),
            "--memory-swap",
            str(CLI_MEMORY_LIMIT),
            "--cpus",
            "1.0",
            "--pids-limit",
            "128",
            "--env=STOCK_PROBS_DATA_DIR=/data",
            "--env=STOCK_PROBS_ENV=test",
            "--env=STOCK_PROBS_PROVIDER=fixture",
            "--env=STOCK_PROBS_AUTH_MODE=disabled",
            "--entrypoint",
            "python",
            image_id,
            "-c",
            _schema_probe_source(),
        ],
        timeout=60,
    )
    OPERATION_CONTAINERS.remove(tracked)
    value = _json_output(result, "schema_query_invalid")
    if (
        not isinstance(value, dict)
        or type(value.get("max")) is not int
        or not isinstance(value.get("versions"), list)
        or value["versions"] != list(range(1, value["max"] + 1))
    ):
        raise RehearsalError("schema_query_invalid")
    return value["max"]


def _write_environment(*, assistant_enabled: bool) -> Path:
    TEMP_ROOT.mkdir(mode=0o700, parents=True, exist_ok=True)
    path = TEMP_ROOT / f"app-{secrets.token_hex(8)}.env"
    env = {
        "STOCK_PROBS_ASSISTANT_ENABLED": "1" if assistant_enabled else "0",
        "STOCK_PROBS_ASSISTANT_ROLLOUT": "invited" if assistant_enabled else "disabled",
        "STOCK_PROBS_DATA_DIR": "/data",
        "STOCK_PROBS_ENV": "production",
        "STOCK_PROBS_HOST": "127.0.0.1",
        "STOCK_PROBS_PORT": "8000",
        "STOCK_PROBS_PROVIDER": "yahoo",
        "STOCK_PROBS_AUTH_MODE": "github",
        "STOCK_PROBS_PUBLIC_ORIGIN": "https://ledger-r120.test",
        "STOCK_PROBS_AUTH_SESSION_SECRET": secrets.token_urlsafe(48),
        "STOCK_PROBS_AUTH_COOKIE_SECURE": "1",
        "STOCK_PROBS_GITHUB_CLIENT_ID": "synthetic-pr-rehearsal-client",
        "STOCK_PROBS_GITHUB_CLIENT_SECRET": secrets.token_urlsafe(32),
        "STOCK_PROBS_GITHUB_REDIRECT_URI": "https://ledger-r120.test/auth/callback",
        "STOCK_PROBS_OWNER_GITHUB_ID": "9820000001",
        "STOCK_PROBS_TRUSTED_PROXY_HOSTS": "127.0.0.1,::1,localhost",
    }
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as target:
        for key, value in env.items():
            target.write(f"{key}={value}\n")
        target.flush()
        os.fsync(target.fileno())
    return path


def _start_app(
    image_id: str,
    volume: str,
    name: str,
    *,
    assistant_enabled: bool,
    network: str,
    network_id: str | None,
    run_id: str,
    reviewed_head_sha: str,
    pair_manifest_sha256: str,
    role: str,
) -> str:
    """Start a fixed app profile on its verified per-run network and volume."""
    expected_network = _candidate_network_name(volume) if role == "candidate" else "none"
    if (
        VOLUME_RE.fullmatch(volume) is None
        or run_id != _run_id_for_volume(volume)
        or name != f"{volume}-{role}"
        or network != expected_network
        or REVISION_RE.fullmatch(reviewed_head_sha) is None
        or DIGEST_RE.fullmatch(pair_manifest_sha256) is None
        or role not in {"candidate", "recovery"}
        or (
            role == "candidate"
            and (network_id is None or NETWORK_ID_RE.fullmatch(network_id) is None)
        )
        or (role == "recovery" and network_id is not None)
    ):
        raise RehearsalError("container_identity_invalid")
    if role == "candidate":
        _inspect_owned_network(
            network,
            reviewed_head_sha,
            pair_manifest_sha256,
            volume,
            expected_id=network_id,
            require_empty=True,
        )
    memory_limit = _memory_limit_for_role(role)
    env_path = _write_environment(assistant_enabled=assistant_enabled)
    command = [
        "/usr/bin/docker",
        "run",
        "--detach",
        "--name",
        name,
        "--label",
        "org.stock-probs.pr-rehearsal=true",
        "--label",
        f"org.stock-probs.pr-rehearsal.task={TASK_ID}",
        "--label",
        f"org.stock-probs.pr-rehearsal.run={run_id}",
        "--label",
        f"org.stock-probs.pr-rehearsal.head={reviewed_head_sha}",
        "--label",
        f"org.stock-probs.pr-rehearsal.pair={pair_manifest_sha256}",
        "--label",
        f"org.stock-probs.pr-rehearsal.role={role}",
        "--label",
        f"org.stock-probs.pr-rehearsal.volume={volume}",
        f"--network={network}",
        "--restart=no",
        "--read-only",
        "--user",
        "0:0",
        "--memory",
        str(memory_limit),
        "--memory-swap",
        str(memory_limit),
        "--cpu-period",
        "100000",
        "--cpu-quota",
        "100000",
        "--pids-limit",
        "128",
        "--cap-drop",
        "ALL",
        "--cap-add",
        "SETUID",
        "--cap-add",
        "SETGID",
        "--security-opt",
        "no-new-privileges:true",
        "--tmpfs",
        "/tmp:rw,nosuid,nodev,noexec,size=64m,uid=10001,gid=10001,mode=0700",  # noqa: S108 - app-only tmpfs.
        "--tmpfs",
        "/run/assistant:rw,nosuid,nodev,noexec,size=16m,mode=0711",
        "--tmpfs",
        "/run/assistant-worker-home:rw,nosuid,nodev,noexec,size=64m,uid=10002,gid=10002,mode=0700",
        "--volume",
        f"{volume}:/data",
        "--env-file",
        str(env_path),
        image_id,
    ]
    try:
        result = _run(command, timeout=30)
        container = result.stdout.decode("ascii", errors="strict").strip()
        if CONTAINER_ID_RE.fullmatch(container) is None:
            raise RehearsalError("app_container_identity_invalid")
        _verify_container_profile(
            container,
            expected_network=network,
            expected_role=role,
            expected_name=name,
            expected_network_id=network_id,
            expected_task=TASK_ID,
            expected_run_id=run_id,
            expected_revision=reviewed_head_sha,
            expected_pair=pair_manifest_sha256,
            expected_volume=volume,
        )
        return container
    finally:
        env_path.unlink(missing_ok=True)


def _wait_ready(
    container: str, *, enabled: bool, sample_count: list[int], timeout: int = 180
) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        _check_production(sample_count)
        probe = (
            "import json,urllib.request; "
            "r=urllib.request.urlopen('http://127.0.0.1:8000/api/v1/readiness',timeout=2); "
            "print(json.dumps(json.loads(r.read(16385))))"
        )
        result = _run(
            ["/usr/bin/docker", "exec", "--user", "10001:10001", container, "python", "-c", probe],
            timeout=5,
            allow_failure=True,
        )
        if result.returncode == 0:
            value = _json_output(result, "app_health_invalid")
            assistant = value.get("assistant") if isinstance(value, dict) else None
            if (
                isinstance(value, dict)
                and value.get("status") == "ready"
                and value.get("schema_version") == 13
                and isinstance(assistant, dict)
                and assistant.get("enabled") is enabled
                and assistant.get("status") == ("ready" if enabled else "disabled")
            ):
                return
        state = (
            _run(
                ["/usr/bin/docker", "inspect", "--format", "{{.State.Running}}", container],
                timeout=10,
            )
            .stdout.decode("ascii", errors="strict")
            .strip()
        )
        if state != "true":
            raise RehearsalError("app_container_stopped")
        time.sleep(2)
    raise RehearsalError("app_health_timeout")


def _copy_probe_files(container: str, source_digests: dict[str, str]) -> None:
    for name in ("native_driver.py", "seed.py"):
        _install_container_asset(container, name, source_digests.get(name, ""))


def _seed(container: str) -> dict[str, object]:
    result = _run(
        [
            "/usr/bin/docker",
            "exec",
            "-i",
            "--user",
            "10001:10001",
            container,
            "python",
            "/run/assistant/seed.py",
            "seed",
        ],
        timeout=30,
        input_bytes=b"",
    )
    value = _json_output(result, "synthetic_fixture_invalid")
    if not isinstance(value, dict) or set(value) != {"users", "synthetic_user_ids"}:
        raise RehearsalError("synthetic_fixture_invalid")
    users, user_ids = value.get("users"), value.get("synthetic_user_ids")
    if (
        not isinstance(users, list)
        or len(users) != 2
        or not isinstance(user_ids, list)
        or len(user_ids) != 2
        or any(type(user_id) is not int or user_id < 1 for user_id in user_ids)
    ):
        raise RehearsalError("synthetic_identity_invalid")
    return value


def _seed_operation(
    container: str, operation: str, request: dict[str, object]
) -> dict[str, object]:
    if operation not in {"marker", "snapshot"}:
        raise RehearsalError("synthetic_operation_invalid")
    result = _run(
        [
            "/usr/bin/docker",
            "exec",
            "-i",
            "--user",
            "10001:10001",
            container,
            "python",
            "/run/assistant/seed.py",
            operation,
        ],
        timeout=30,
        input_bytes=json.dumps(request, separators=(",", ":")).encode(),
    )
    value = _json_output(result, "synthetic_fixture_invalid")
    if not isinstance(value, dict):
        raise RehearsalError("synthetic_fixture_invalid")
    return value


def _run_native_workload(
    container: str,
    users: list[dict[str, str]],
    sample_count: list[int],
) -> dict[str, object]:
    request = (
        json.dumps(
            {
                "base_url": "http://127.0.0.1:8000",
                "origin": "https://ledger-r120.test",
                "users": users,
            },
            separators=(",", ":"),
        ).encode("utf-8")
        + b"\n"
    )
    command = [
        "/usr/bin/docker",
        "exec",
        "-i",
        "--user",
        "10001:10001",
        container,
        "python",
        "/run/assistant/native_driver.py",
        "--attach-existing-app",
    ]
    try:
        child = subprocess.Popen(  # noqa: S603 - immutable container and fixed driver path.
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env={
                "PATH": "/usr/bin:/bin",
                "HOME": str(DOCKER_HOME),
                "LANG": "C",
                "DOCKER_CONFIG": str(DOCKER_CONFIG),
            },
        )
    except OSError as exc:
        raise RehearsalError("native_driver_unavailable") from exc
    if child.stdin is None or child.stdout is None or child.stderr is None:
        raise RehearsalError("native_driver_unavailable")
    try:
        child.stdin.write(request)
        child.stdin.flush()
    except OSError as exc:
        child.kill()
        raise RehearsalError("native_driver_input_failed") from exc

    selector = selectors.DefaultSelector()
    selector.register(child.stdout, selectors.EVENT_READ, "stdout")
    selector.register(child.stderr, selectors.EVENT_READ, "stderr")
    pending = bytearray()
    parsed: list[dict[str, object]] = []
    stdout_bytes = 0
    stderr_bytes = 0
    deadline = time.monotonic() + 360
    next_sample = time.monotonic()
    try:
        while selector.get_map():
            now = time.monotonic()
            if now >= deadline:
                child.kill()
                raise RehearsalError("native_driver_timeout")
            if now >= next_sample:
                _check_production(sample_count)
                next_sample = now + 5
            for key, _ in selector.select(min(1.0, deadline - now)):
                stream = key.fileobj
                fd = stream if isinstance(stream, int) else stream.fileno()
                chunk = os.read(fd, 4096)
                if not chunk:
                    selector.unregister(stream)
                    continue
                if key.data == "stderr":
                    stderr_bytes += len(chunk)
                    if stderr_bytes > 64 * 1024:
                        child.kill()
                        raise RehearsalError("native_driver_output_too_large")
                    continue
                stdout_bytes += len(chunk)
                if stdout_bytes > MAX_RESPONSE:
                    child.kill()
                    raise RehearsalError("native_driver_output_too_large")
                pending.extend(chunk)
                if len(pending) > 32 * 1024 and b"\n" not in pending:
                    child.kill()
                    raise RehearsalError("native_driver_output_too_large")
                while b"\n" in pending:
                    line, _, remainder = pending.partition(b"\n")
                    pending[:] = remainder
                    try:
                        value: object = json.loads(line)
                    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                        child.kill()
                        raise RehearsalError("native_driver_result_invalid") from exc
                    if not isinstance(value, dict):
                        child.kill()
                        raise RehearsalError("native_driver_result_invalid")
                    if value.get("phase") == "active_search_wait":
                        child.stdin.write(b'{"continue":true}\n')
                        child.stdin.flush()
                    else:
                        parsed.append(value)
        return_code = child.wait(timeout=max(0.0, deadline - time.monotonic()))
    except (BrokenPipeError, OSError, subprocess.TimeoutExpired) as exc:
        if child.poll() is None:
            child.kill()
        with suppress(subprocess.TimeoutExpired):
            child.wait(timeout=1)
        raise RehearsalError("native_driver_failed") from exc
    finally:
        selector.close()
        if child.poll() is None:
            child.kill()
            with suppress(subprocess.TimeoutExpired):
                child.wait(timeout=1)
        for stream in (child.stdin, child.stdout, child.stderr):
            if stream is not None:
                with suppress(OSError):
                    stream.close()
    if return_code != 0 or len(parsed) != 1:
        details = _native_failure_projection(parsed[0] if len(parsed) == 1 else None)
        raise RehearsalError("native_driver_failed", details=details)
    result = parsed[0]
    owners = result.get("owners")
    model_id = result.get("approved_model_id")
    model_parts = model_id.split("/") if isinstance(model_id, str) else []
    if (
        result.get("attached_candidate_acceptance") is not True
        or result.get("turn_requests_issued_concurrently") is not True
        or not 2 <= len(model_parts) <= 4
        or any(MODEL_SEGMENT_RE.fullmatch(part) is None for part in model_parts)
        or result.get("search_approved") is not True
        or result.get("active_search_scan_acknowledged") is not True
        or result.get("cross_owner_conversation_status") != 404
        or result.get("forged_internal_mcp_status") != 404
        or result.get("conversation_delete_statuses") != [200, 200]
        or not isinstance(owners, list)
        or len(owners) != 2
        or any(
            not isinstance(owner, dict)
            or owner.get("terminal_status") != "completed"
            or owner.get("model_id_matches") is not True
            or owner.get("selected_model_id_matches") is not True
            or owner.get("workspace_summary_receipt_count") != 1
            or owner.get("workspace_summary_digest_matches") is not True
            for owner in owners
        )
        or not isinstance(owners[1], dict)
        or type(owners[1].get("native_search_source_count")) is not int
        or owners[1]["native_search_source_count"] < 1
    ):
        raise RehearsalError(
            "native_workload_incomplete", details=_native_failure_projection(result)
        )
    return {
        "native_v2": True,
        "model_id": model_id,
        "mcp_workspace_summary_calls": 2,
        "builtin_search_source_count": owners[1]["native_search_source_count"],
        "simultaneous_two_owner_turns": True,
        "owner_isolation": True,
    }


DOCKER_CONFIG = TEMP_ROOT / "docker-config"
DOCKER_HOME = TEMP_ROOT / "home"


def _prepare_docker_cli() -> None:
    for path in (DOCKER_CONFIG, DOCKER_HOME):
        if path.exists() or path.is_symlink():
            try:
                info = path.lstat()
            except OSError as exc:
                raise RehearsalError("docker_cli_config_unsafe") from exc
            if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or any(path.iterdir()):
                raise RehearsalError("docker_cli_config_unsafe")
        else:
            path.mkdir(mode=0o700)


def _memory_limit_for_role(role: str) -> int:
    if role == "candidate":
        return CANDIDATE_MEMORY_LIMIT
    if role == "recovery":
        return RECOVERY_MEMORY_LIMIT
    raise RehearsalError("container_role_invalid")


def _run_id_for_volume(volume: str) -> str:
    """Return the generated operation ID embedded in a valid rehearsal volume name."""
    if VOLUME_RE.fullmatch(volume) is None:
        raise RehearsalError("disposable_volume_identity_invalid")
    run_id = volume.rsplit("-", 1)[1]
    if RUN_ID_RE.fullmatch(run_id) is None:
        raise RehearsalError("disposable_volume_identity_invalid")
    return run_id


def _candidate_network_name(volume: str) -> str:
    """Build the isolated candidate bridge name from its run-owned volume name."""
    if VOLUME_RE.fullmatch(volume) is None:
        raise RehearsalError("disposable_volume_identity_invalid")
    return f"{volume}-candidate-network"


def _network_labels(revision: str, pair_sha256: str, volume: str) -> dict[str, str]:
    """Return the exact ownership labels required on the candidate bridge."""
    if REVISION_RE.fullmatch(revision) is None or DIGEST_RE.fullmatch(pair_sha256) is None:
        raise RehearsalError("candidate_network_identity_invalid")
    return {
        "org.stock-probs.pr-rehearsal": "true",
        "org.stock-probs.pr-rehearsal.task": TASK_ID,
        "org.stock-probs.pr-rehearsal.head": revision,
        "org.stock-probs.pr-rehearsal.pair": pair_sha256,
        "org.stock-probs.pr-rehearsal.volume": volume,
        "org.stock-probs.pr-rehearsal.run": _run_id_for_volume(volume),
    }


def _inspect_owned_network(
    name: str,
    revision: str,
    pair_sha256: str,
    volume: str,
    *,
    expected_id: str | None = None,
    require_empty: bool,
    allow_absent: bool = False,
) -> str | None:
    """Inspect and validate one generated candidate network without trusting its name alone."""
    expected_name = _candidate_network_name(volume)
    if (
        name != expected_name
        or VOLUME_RE.fullmatch(volume) is None
        or REVISION_RE.fullmatch(revision) is None
        or DIGEST_RE.fullmatch(pair_sha256) is None
        or (expected_id is not None and NETWORK_ID_RE.fullmatch(expected_id) is None)
    ):
        raise RehearsalError("candidate_network_identity_invalid")
    template = (
        "{{.Id}}|{{.Name}}|{{.Driver}}|{{.Scope}}|{{.Internal}}|{{.IPAM.Driver}}|"
        '{{index .Labels "org.stock-probs.pr-rehearsal"}}|'
        '{{index .Labels "org.stock-probs.pr-rehearsal.task"}}|'
        '{{index .Labels "org.stock-probs.pr-rehearsal.head"}}|'
        '{{index .Labels "org.stock-probs.pr-rehearsal.pair"}}|'
        '{{index .Labels "org.stock-probs.pr-rehearsal.volume"}}|'
        '{{index .Labels "org.stock-probs.pr-rehearsal.run"}}|{{json .Containers}}'
    )
    inspected = _run(
        ["/usr/bin/docker", "network", "inspect", "--format", template, name],
        timeout=10,
        allow_failure=True,
        maximum=4_096,
    )
    if inspected.returncode != 0:
        if allow_absent:
            listing = _run(
                [
                    "/usr/bin/docker",
                    "network",
                    "ls",
                    "--no-trunc",
                    "--filter",
                    f"name={name}",
                    "--format",
                    "{{.ID}}|{{.Name}}",
                ],
                timeout=10,
                allow_failure=True,
                maximum=4_096,
            )
            if listing.returncode != 0 or listing.stderr or len(listing.stdout) > 4_096:
                raise RehearsalError("candidate_network_inspect_unverified")
            try:
                listing_text = listing.stdout.decode("ascii", errors="strict")
            except UnicodeDecodeError:
                raise RehearsalError("candidate_network_inspect_unverified") from None
            rows = listing_text.split("\n")
            if rows and rows[-1] == "":
                rows.pop()
            identifiers: set[str] = set()
            names: set[str] = set()
            exact_name_present = False
            for row in rows:
                fields = row.split("|")
                if (
                    len(fields) != 2
                    or NETWORK_ID_RE.fullmatch(fields[0]) is None
                    or NETWORK_NAME_RE.fullmatch(fields[1]) is None
                    or fields[0] in identifiers
                    or fields[1] in names
                ):
                    raise RehearsalError("candidate_network_inspect_unverified")
                identifiers.add(fields[0])
                names.add(fields[1])
                exact_name_present = exact_name_present or fields[1] == name
            if not exact_name_present:
                return None
            raise RehearsalError("candidate_network_inspect_unverified")
        raise RehearsalError("candidate_network_inspect_unavailable")
    try:
        fields = inspected.stdout.decode("ascii", errors="strict").strip().split("|")
        if len(fields) != 13:
            raise ValueError("field count")
        endpoints = json.loads(fields[12])
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
        raise RehearsalError("candidate_network_identity_mismatch") from None
    identifier = fields[0]
    expected_labels = _network_labels(revision, pair_sha256, volume)
    actual_labels = dict(zip(expected_labels, fields[6:12], strict=True))
    if (
        NETWORK_ID_RE.fullmatch(identifier) is None
        or (expected_id is not None and identifier != expected_id)
        or fields[1:6] != [name, "bridge", "local", "false", "default"]
        or actual_labels != expected_labels
        or not isinstance(endpoints, dict)
        or (require_empty and endpoints)
    ):
        raise RehearsalError("candidate_network_identity_mismatch")
    return identifier


def _create_candidate_network(name: str, revision: str, pair_sha256: str, volume: str) -> str:
    """Create a default-IPAM bridge and recover its ID only through exact inspection."""
    if name != _candidate_network_name(volume):
        raise RehearsalError("candidate_network_identity_invalid")
    command = ["/usr/bin/docker", "network", "create", "--driver", "bridge"]
    for key, value in _network_labels(revision, pair_sha256, volume).items():
        command.extend(("--label", f"{key}={value}"))
    command.append(name)
    created = _run(command, timeout=15, allow_failure=True, maximum=4_096)
    output = created.stdout.decode("ascii", errors="strict").strip()
    reported_id = output if NETWORK_ID_RE.fullmatch(output) is not None else None
    observed_id = _inspect_owned_network(
        name,
        revision,
        pair_sha256,
        volume,
        expected_id=reported_id,
        require_empty=True,
        allow_absent=reported_id is None,
    )
    if observed_id is None:
        raise RehearsalError("candidate_network_creation_invalid")
    return observed_id


def _remove_owned_network(
    name: str,
    revision: str,
    pair_sha256: str,
    volume: str,
    *,
    expected_id: str | None = None,
) -> None:
    """Remove an empty network only after its complete ownership identity is verified."""
    identifier = _inspect_owned_network(
        name,
        revision,
        pair_sha256,
        volume,
        expected_id=expected_id,
        require_empty=True,
        allow_absent=True,
    )
    if identifier is None:
        return
    _run(
        ["/usr/bin/docker", "network", "rm", identifier],
        timeout=15,
        allow_failure=True,
        maximum=4_096,
    )
    remains = _inspect_owned_network(
        name,
        revision,
        pair_sha256,
        volume,
        expected_id=identifier,
        require_empty=True,
        allow_absent=True,
    )
    if remains is not None:
        raise RehearsalError("candidate_network_removal_unverified")


def _cleanup_network_before_volume(
    *,
    containers_removed: bool,
    network_name: str,
    network_id: str | None,
    network_created: bool,
    revision: str,
    pair_sha256: str,
    volume: str,
    volume_created: bool,
) -> tuple[bool, bool]:
    """Remove the isolated network before its volume, only after containers are absent."""
    if not containers_removed:
        return False, False
    network_removed = not network_created
    if network_created:
        _remove_owned_network(
            network_name,
            revision,
            pair_sha256,
            volume,
            expected_id=network_id,
        )
        network_removed = True
    volume_removed = not volume_created
    if volume_created and network_removed:
        volume_removed = _remove_volume_if_owned(volume, revision, pair_sha256)
    return network_removed, volume_removed


def _cap_add_matches(value: object) -> bool:
    """Accept Docker's two canonical spellings for the exact setuid/setgid pair."""

    if not isinstance(value, list) or len(value) != 2:
        return False
    normalized: list[str] = []
    for capability in value:
        if not isinstance(capability, str):
            return False
        short_name = capability[4:] if capability.startswith("CAP_") else capability
        if short_name not in {"SETUID", "SETGID"}:
            return False
        normalized.append(short_name)
    return len(set(normalized)) == 2 and set(normalized) == {"SETUID", "SETGID"}


def _verify_container_profile(
    container: str,
    *,
    expected_network: str = "bridge",
    expected_role: str,
    expected_name: str | None = None,
    expected_network_id: str | None = None,
    expected_task: str | None = None,
    expected_run_id: str | None = None,
    expected_revision: str | None = None,
    expected_pair: str | None = None,
    expected_volume: str | None = None,
) -> None:
    """Verify limits, ownership labels, port isolation, and the attached network."""
    identity_values = (
        expected_name,
        expected_task,
        expected_run_id,
        expected_revision,
        expected_pair,
        expected_volume,
    )
    verify_identity = (
        any(value is not None for value in identity_values) or expected_network_id is not None
    )
    if verify_identity and (
        any(value is None for value in identity_values)
        or CONTAINER_ID_RE.fullmatch(container) is None
        or (expected_role == "candidate" and expected_network_id is None)
        or (expected_role == "recovery" and expected_network_id is not None)
        or (
            expected_network_id is not None and NETWORK_ID_RE.fullmatch(expected_network_id) is None
        )
    ):
        raise RehearsalError("container_profile_mismatch")
    identity_template = (
        "{{.Id}}|{{.Name}}|"
        '{{index .Config.Labels "org.stock-probs.pr-rehearsal"}}|'
        '{{index .Config.Labels "org.stock-probs.pr-rehearsal.task"}}|'
        '{{index .Config.Labels "org.stock-probs.pr-rehearsal.run"}}|'
        '{{index .Config.Labels "org.stock-probs.pr-rehearsal.head"}}|'
        '{{index .Config.Labels "org.stock-probs.pr-rehearsal.pair"}}|'
        '{{index .Config.Labels "org.stock-probs.pr-rehearsal.role"}}|'
        '{{index .Config.Labels "org.stock-probs.pr-rehearsal.volume"}}|'
        if verify_identity
        else ""
    )
    network_template = "|{{json .NetworkSettings.Networks}}" if verify_identity else ""
    profile_template = (
        "{{.HostConfig.Memory}}|{{.HostConfig.MemorySwap}}|{{.HostConfig.CpuPeriod}}|"
        "{{.HostConfig.CpuQuota}}|{{.HostConfig.NanoCpus}}|"
        "{{.HostConfig.PidsLimit}}|{{.HostConfig.ReadonlyRootfs}}|"
        "{{.HostConfig.NetworkMode}}|{{json .HostConfig.CapDrop}}|"
        "{{json .HostConfig.CapAdd}}|{{json .HostConfig.PortBindings}}|{{.Config.User}}|"
        "{{json .HostConfig.SecurityOpt}}"
    ) + network_template
    template = identity_template + profile_template
    result = _run(["/usr/bin/docker", "inspect", "--format", template, container], timeout=10)
    fields = result.stdout.decode("utf-8", errors="strict").strip().split("|")
    offset = 9 if verify_identity else 0
    if len(fields) != offset + (14 if verify_identity else 13):
        raise RehearsalError("container_profile_mismatch")
    try:
        if verify_identity:
            networks = json.loads(fields[22])
        security_options = json.loads(fields[offset + 12])
        cap_drop = json.loads(fields[offset + 8])
        cap_add = json.loads(fields[offset + 9])
        port_bindings = json.loads(fields[offset + 10])
    except json.JSONDecodeError:
        raise RehearsalError("container_profile_mismatch") from None
    if (
        fields[offset] != str(_memory_limit_for_role(expected_role))
        or fields[offset + 1] != str(_memory_limit_for_role(expected_role))
        or fields[offset + 2] != "100000"
        or fields[offset + 3] != "100000"
        or fields[offset + 4] != "0"
        or fields[offset + 5] != "128"
        or fields[offset + 6] != "true"
        or fields[offset + 7] != expected_network
        or cap_drop != ["ALL"]
        or not _cap_add_matches(cap_add)
        or port_bindings not in (None, {})
        or fields[offset + 11] != "0:0"
        or security_options != ["no-new-privileges:true"]
    ):
        raise RehearsalError("container_profile_mismatch")
    if verify_identity:
        if fields[:9] != [
            container,
            f"/{expected_name}",
            "true",
            expected_task,
            expected_run_id,
            expected_revision,
            expected_pair,
            expected_role,
            expected_volume,
        ] or not isinstance(networks, dict):
            raise RehearsalError("container_profile_mismatch")
        if expected_role == "candidate":
            if (
                set(networks) != {expected_network}
                or not isinstance(networks[expected_network], dict)
                or networks[expected_network].get("NetworkID") != expected_network_id
            ):
                raise RehearsalError("container_profile_mismatch")
        elif set(networks) - {"none"}:
            raise RehearsalError("container_profile_mismatch")


def _copy_fixture_files(container: str, source_digests: dict[str, str]) -> None:
    for name in ("native_driver.py", "seed.py"):
        _install_container_asset(container, name, source_digests.get(name, ""))


def _container_fixture(
    container: str, operation: str, request: dict[str, object] | None = None
) -> dict[str, object]:
    if operation not in FIXTURE_OPERATION_CATEGORIES:
        raise RehearsalError("synthetic_operation_invalid")
    encoded = json.dumps(request, separators=(",", ":")).encode() if request is not None else b""
    result = _run(
        [
            "/usr/bin/docker",
            "exec",
            "-i",
            "--user",
            "10001:10001",
            container,
            "python",
            "/run/assistant/seed.py",
            operation,
        ],
        timeout=30,
        input_bytes=encoded,
    )
    value = _json_output(result, "synthetic_fixture_invalid")
    if not isinstance(value, dict):
        raise RehearsalError("synthetic_fixture_invalid")
    return value


def _parse_cpu_stat(text: str, byte_count: int, *, role: str) -> dict[str, int]:
    """Parse the required bounded cgroup v2 CPU counters for one role."""

    if (
        not isinstance(text, str)
        or type(byte_count) is not int
        or not 0 <= byte_count <= MAX_CGROUP_CPU_STAT_BYTES
        or not text.isascii()
        or byte_count != len(text)
    ):
        raise RehearsalError(
            "cgroup_cpu_stat_unavailable",
            details={"resource_role": role, "cpu_stat_evidence_complete": False},
        )

    counters: dict[str, int] = {}
    invalid: list[str] = []
    for line in text.splitlines():
        parts = line.split()
        if (
            len(parts) != 2
            or len(parts[0]) > 32
            or re.fullmatch(r"[a-z_]+(?:\.[a-z_]+)*", parts[0]) is None
        ):
            invalid.append("cpu.stat")
            continue
        name, count_text = parts
        if name not in CPU_STAT_COUNTERS:
            continue
        if (
            name in counters
            or not count_text.isascii()
            or not count_text.isdecimal()
            or len(count_text) > MAX_RESOURCE_COUNTER_DIGITS
        ):
            invalid.append(name)
            continue
        parsed_count = int(count_text)
        if parsed_count > MAX_RESOURCE_COUNTER_VALUE:
            invalid.append(name)
            continue
        counters[name] = parsed_count

    missing = sorted(set(CPU_STAT_COUNTERS) - counters.keys())
    if missing or invalid:
        raise RehearsalError(
            "cgroup_cpu_stat_counters_incomplete",
            details={
                "resource_role": role,
                "cpu_stat_evidence_complete": False,
                "missing_counters": missing,
                "invalid_counters": sorted(set(invalid)),
            },
        )
    return counters


def _memory_usage(container: str, *, expected_role: str = "candidate") -> CgroupMemorySample:
    """Return bounded cgroup memory, OOM, and CPU counters for one app container."""

    if re.fullmatch(r"[0-9a-f]{64}", container) is None:
        raise RehearsalError("container_identity_invalid")
    if expected_role not in {"candidate", "recovery"}:
        raise RehearsalError("container_role_invalid")
    source = (
        "import json,pathlib;p=pathlib.Path('/sys/fs/cgroup');"
        "f=(p/'memory.events').open('rb');e=f.read(4097);f.close();"
        "c=(p/'cpu.stat').open('rb');s=c.read(4097);c.close();"
        "print(json.dumps({'limit':int((p/'memory.max').read_text()),"
        "'peak':int((p/'memory.peak').read_text()),'events_bytes':len(e),"
        "'events':e.decode('ascii',errors='replace'),'cpu_stat_bytes':len(s),"
        "'cpu_stat':s.decode('ascii',errors='replace')}))"
    )
    try:
        result = _run(
            [
                "/usr/bin/docker",
                "exec",
                "--user",
                "10001:10001",
                container,
                "python",
                "-c",
                source,
            ],
            timeout=10,
        )
        value = _json_output(result, "container_memory_evidence_unavailable")
    except RehearsalError as exc:
        raise RehearsalError(
            "container_memory_evidence_unavailable",
            details={
                "resource_role": expected_role,
                "oom_event_evidence_complete": False,
                "missing_counters": list(OOM_EVENT_COUNTERS),
                "zero_oom_claim": "unavailable",
            },
        ) from exc
    if (
        not isinstance(value, dict)
        or type(value.get("limit")) is not int
        or type(value.get("peak")) is not int
    ):
        raise RehearsalError(
            "container_memory_evidence_invalid",
            details={
                "resource_role": expected_role,
                "oom_event_evidence_complete": False,
                "missing_counters": list(OOM_EVENT_COUNTERS),
                "zero_oom_claim": "unavailable",
            },
        )
    expected_limit = _memory_limit_for_role(expected_role)
    if value["limit"] != expected_limit or value["peak"] > expected_limit:
        raise RehearsalError(
            "container_memory_limit_mismatch",
            details={"resource_role": expected_role},
        )

    event_text = value.get("events")
    event_bytes = value.get("events_bytes")
    if (
        not isinstance(event_text, str)
        or type(event_bytes) is not int
        or not 0 <= event_bytes <= MAX_CGROUP_MEMORY_EVENTS_BYTES
        or not event_text.isascii()
    ):
        raise RehearsalError(
            "cgroup_memory_events_unavailable",
            details={
                "resource_role": expected_role,
                "oom_event_evidence_complete": False,
                "missing_counters": list(OOM_EVENT_COUNTERS),
                "zero_oom_claim": "unavailable",
            },
        )

    event_counts: dict[str, int] = {}
    invalid_counters: list[str] = []
    for line in event_text.splitlines():
        parts = line.split()
        if len(parts) != 2 or not re.fullmatch(r"[a-z_]{1,32}", parts[0]):
            invalid_counters.append("memory.events")
            continue
        name, count_text = parts
        if name not in OOM_EVENT_COUNTERS:
            continue
        if (
            name in event_counts
            or not count_text.isascii()
            or not count_text.isdecimal()
            or len(count_text) > MAX_RESOURCE_COUNTER_DIGITS
        ):
            invalid_counters.append(name)
            continue
        parsed_count = int(count_text)
        if parsed_count > MAX_RESOURCE_COUNTER_VALUE:
            invalid_counters.append(name)
            continue
        event_counts[name] = parsed_count

    missing_counters = sorted(set(OOM_EVENT_COUNTERS) - event_counts.keys())
    if missing_counters or invalid_counters:
        raise RehearsalError(
            "cgroup_memory_event_counters_incomplete",
            details={
                "resource_role": expected_role,
                "oom_event_evidence_complete": False,
                "missing_counters": missing_counters,
                "invalid_counters": sorted(set(invalid_counters)),
                "zero_oom_claim": "unavailable",
            },
        )
    cpu_stat = _parse_cpu_stat(
        value.get("cpu_stat", ""), value.get("cpu_stat_bytes", -1), role=expected_role
    )
    return {
        "limit": value["limit"],
        "peak": value["peak"],
        "oom_events": event_counts,
        "cpu_stat": cpu_stat,
    }


def _oom_event_evidence(
    baseline: CgroupMemorySample, final: CgroupMemorySample, *, role: str
) -> dict[str, object]:
    """Calculate complete OOM counter deltas and reject nonzero or incomplete evidence."""

    baseline_events = baseline["oom_events"]
    final_events = final["oom_events"]
    if any(type(baseline_events.get(name)) is not int for name in OOM_EVENT_COUNTERS) or any(
        type(final_events.get(name)) is not int for name in OOM_EVENT_COUNTERS
    ):
        raise RehearsalError(
            "cgroup_memory_event_counters_incomplete",
            details={
                "resource_role": role,
                "oom_event_evidence_complete": False,
                "missing_counters": [
                    name
                    for name in OOM_EVENT_COUNTERS
                    if type(baseline_events.get(name)) is not int
                    or type(final_events.get(name)) is not int
                ],
                "zero_oom_claim": "unavailable",
            },
        )

    baseline_counts = {name: baseline_events[name] for name in OOM_EVENT_COUNTERS}
    final_counts = {name: final_events[name] for name in OOM_EVENT_COUNTERS}
    if any(final_counts[name] < baseline_counts[name] for name in OOM_EVENT_COUNTERS):
        raise RehearsalError(
            "cgroup_memory_event_counter_reset",
            details={
                "resource_role": role,
                "baseline": baseline_counts,
                "final": final_counts,
                "zero_oom_claim": "unavailable",
            },
        )
    deltas = {name: final_counts[name] - baseline_counts[name] for name in OOM_EVENT_COUNTERS}
    zero_oom_events = all(
        baseline_counts[name] == 0 and deltas[name] == 0 for name in OOM_EVENT_COUNTERS
    )
    evidence: dict[str, object] = {
        "complete": True,
        "baseline": baseline_counts,
        "final": final_counts,
        "delta": deltas,
        "zero_oom_events": zero_oom_events,
    }
    if not zero_oom_events:
        raise RehearsalError(
            "cgroup_oom_event_observed",
            details={"resource_role": role, "oom_event_evidence": evidence},
        )
    return evidence


def _cpu_stat_evidence(
    baseline: CgroupMemorySample, final: CgroupMemorySample, *, role: str
) -> dict[str, object]:
    """Record complete monotonic CPU counters without interpreting throttling."""

    if role not in {"candidate", "recovery"}:
        raise RehearsalError("container_role_invalid")
    snapshots: dict[str, dict[str, int]] = {}
    missing: list[str] = []
    for label, sample in (("baseline", baseline), ("final", final)):
        counters = sample.get("cpu_stat")
        if not isinstance(counters, dict):
            missing.extend(f"{label}.{name}" for name in CPU_STAT_COUNTERS)
            continue
        for name in CPU_STAT_COUNTERS:
            counter = counters.get(name)
            if type(counter) is not int or not 0 <= counter <= MAX_RESOURCE_COUNTER_VALUE:
                missing.append(f"{label}.{name}")
            else:
                snapshots.setdefault(label, {})[name] = counter
    if missing:
        raise RehearsalError(
            "cgroup_cpu_stat_counters_incomplete",
            details={
                "resource_role": role,
                "cpu_stat_evidence_complete": False,
                "missing_counters": missing,
            },
        )

    baseline_counters = snapshots["baseline"]
    final_counters = snapshots["final"]
    if any(final_counters[name] < baseline_counters[name] for name in CPU_STAT_COUNTERS):
        raise RehearsalError(
            "cgroup_cpu_stat_counter_reset",
            details={"resource_role": role, "cpu_stat_evidence_complete": False},
        )
    delta = {name: final_counters[name] - baseline_counters[name] for name in CPU_STAT_COUNTERS}
    return {
        "complete": True,
        "resource_role": role,
        "baseline": baseline_counters,
        "final": final_counters,
        "delta": delta,
    }


_NATIVE_FAILURE_STAGES = {
    "input_validation",
    "model_inventory",
    "admin_step_up",
    "admin_model_policy",
    "user_consent_and_conversation_setup",
    "concurrent_turn_create",
    "turn_poll_and_search_confirmation",
    "owner_evidence_and_isolation",
    "conversation_delete_and_health",
    "acceptance_validation",
}
_NATIVE_MISSING_CONDITIONS = {
    "turn_requests_not_concurrent",
    "search_not_approved",
    "active_search_checkpoint_missing",
    "native_search_sources_missing",
    "owner0_turn_not_completed",
    "owner0_model_id_mismatch",
    "owner0_answer_empty",
    "owner0_workspace_summary_receipt_count_invalid",
    "owner0_workspace_summary_digest_mismatch",
    "owner0_selected_model_mismatch",
    "owner1_turn_not_completed",
    "owner1_model_id_mismatch",
    "owner1_answer_empty",
    "owner1_workspace_summary_receipt_count_invalid",
    "owner1_workspace_summary_digest_mismatch",
    "owner1_selected_model_mismatch",
    "owner0_conversation_delete_failed",
    "owner1_conversation_delete_failed",
    "cross_owner_access_not_denied",
    "forged_internal_mcp_not_denied",
    "worker_not_ready_after_turns",
    "supervised_app_not_reachable",
}
_NATIVE_TURN_ERROR_CODES = {
    "worker_unavailable",
    "provider_unavailable",
    "provider_policy_changed",
    "tool_failed",
    "tool_unavailable",
    "turn_timeout",
    "turn_cancelled",
    "invalid_runtime_event",
    "runtime_restarted",
    "output_too_large",
    "empty_response",
    "sensitive_output_rejected",
    "session_revoked",
}
_NATIVE_TURN_FAILURE_STAGES = {
    "none",
    "before_model_session_event",
    "after_model_session_event",
    "unknown_terminal",
}


def _native_failure_projection(value: object) -> dict[str, object]:
    """Retain only static stage/condition IDs and numeric owner outcomes from the probe."""

    if not isinstance(value, dict):
        return {"failure_stage": "result_unavailable", "missing_conditions": []}
    stage = value.get("failure_stage")
    missing = value.get("missing_conditions")
    if not isinstance(stage, str) or stage not in _NATIVE_FAILURE_STAGES:
        stage = "result_unavailable"
    conditions = (
        [item for item in missing if isinstance(item, str) and item in _NATIVE_MISSING_CONDITIONS]
        if isinstance(missing, list)
        else []
    )
    safe_owners: list[dict[str, object]] = []
    owners = value.get("owners")
    if isinstance(owners, list):
        for owner in owners[:2]:
            if not isinstance(owner, dict):
                continue
            terminal = owner.get("terminal_status")
            safe_owner: dict[str, object] = {
                "terminal_status": terminal
                if terminal in {"running", "completed", "cancelled", "failed", "timed_out"}
                else "unknown",
            }
            for key in (
                "model_id_matches",
                "nonempty_answer",
                "workspace_summary_digest_matches",
                "selected_model_id_matches",
            ):
                if type(owner.get(key)) is bool:
                    safe_owner[key] = owner[key]
            for key in ("workspace_summary_receipt_count", "native_search_source_count"):
                count = owner.get(key)
                if type(count) is int and 0 <= count <= 10_000:
                    safe_owner[key] = count
            safe_owners.append(safe_owner)
    safe_evidence: list[dict[str, object]] = []
    evidence = value.get("owner_evidence")
    if isinstance(evidence, list):
        for row in evidence[:2]:
            if not isinstance(row, dict):
                continue
            owner_index = row.get("owner_index")
            terminal = row.get("terminal_status")
            turn_error = row.get("turn_error_code")
            turn_stage = row.get("turn_failure_stage")
            if (
                type(owner_index) is not int
                or owner_index not in {0, 1}
                or terminal
                not in {
                    "not_started",
                    "running",
                    "completed",
                    "cancelled",
                    "failed",
                    "timed_out",
                    "unknown",
                }
                or (turn_error is not None and turn_error not in _NATIVE_TURN_ERROR_CODES)
                or turn_stage not in _NATIVE_TURN_FAILURE_STAGES
            ):
                continue
            safe_row: dict[str, object] = {
                "owner_index": owner_index,
                "terminal_status": terminal,
                "turn_error_code": turn_error,
                "turn_failure_stage": turn_stage,
            }
            for key in (
                "model_id_matches",
                "answer_nonempty",
                "workspace_summary_digest_present",
                "workspace_summary_digest_matches",
                "selected_model_id_matches",
            ):
                if type(row.get(key)) is bool:
                    safe_row[key] = row[key]
            for key in (
                "assistant_message_count",
                "assistant_text_bytes",
                "workspace_summary_receipt_count",
                "selected_model_event_count",
                "native_search_source_count",
                "conversation_event_count",
            ):
                number = row.get(key)
                if type(number) is int and 0 <= number <= 1_000_000:
                    safe_row[key] = number
            safe_evidence.append(safe_row)
    projected: dict[str, object] = {"failure_stage": stage, "missing_conditions": conditions}
    if safe_owners:
        projected["owners"] = safe_owners
    if safe_evidence:
        projected["owner_evidence"] = safe_evidence
    for key in (
        "turn_requests_issued_concurrently",
        "search_approved",
        "active_search_scan_acknowledged",
        "same_supervised_app_reachable",
        "attached_candidate_acceptance",
    ):
        if type(value.get(key)) is bool:
            projected[key] = value[key]
    for key in (
        "cross_owner_conversation_status",
        "forged_internal_mcp_status",
        "builtin_search_source_count",
    ):
        numeric = value.get(key)
        if type(numeric) is int and 0 <= numeric <= 10_000:
            projected[key] = numeric
    return projected


def _write_receipt(receipt: dict[str, object]) -> str:
    receipt_id = secrets.token_hex(16)
    receipt["receipt_id"] = receipt_id
    path = RECEIPT_ROOT / f"{receipt_id}.json"
    encoded = json.dumps(receipt, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "wb") as output:
        output.write(encoded)
        output.flush()
        os.fsync(output.fileno())
    return receipt_id


def _prepare_host_paths() -> None:
    _safe_directory(STATE_ROOT, 0o750, create=True, group="signalops")
    _safe_directory(INSTALL_ROOT, 0o750, create=False)
    _safe_directory(RECEIPT_ROOT, 0o700, create=True)
    _safe_directory(TEMP_ROOT, 0o700, create=True)
    try:
        incoming = INCOMING.lstat()
        expected_uid = pwd.getpwnam("signalops").pw_uid
    except (OSError, KeyError) as exc:
        raise RehearsalError("incoming_directory_unavailable") from exc
    if (
        not stat.S_ISDIR(incoming.st_mode)
        or stat.S_ISLNK(incoming.st_mode)
        or incoming.st_uid != expected_uid
        or stat.S_IMODE(incoming.st_mode) != 0o700
    ):
        raise RehearsalError("incoming_directory_unsafe")
    _prepare_docker_cli()


def _operation_lock() -> int:
    descriptor = os.open(
        LOCK_FILE,
        os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW,
        0o600,
    )
    info = os.fstat(descriptor)
    if not stat.S_ISREG(info.st_mode) or info.st_uid != 0:
        os.close(descriptor)
        raise RehearsalError("operation_lock_unsafe")
    os.fchmod(descriptor, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as exc:
        os.close(descriptor)
        raise RehearsalError("operation_already_running") from exc
    return descriptor


def _remove_incoming_asset(name: str) -> None:
    if (
        re.fullmatch(
            r"signal-ledger-pr1-[0-9a-f]{40}-(?:candidate\.tar\.gz|recovery\.tar\.gz|pair\.json|bootstrap\.py|host_helper\.py|seed\.py|native_driver\.py)",
            name,
        )
        is None
    ):
        raise RehearsalError("cleanup_asset_name_invalid")
    path = INCOMING / name
    try:
        info = path.lstat()
    except FileNotFoundError:
        return
    except OSError as exc:
        raise RehearsalError("cleanup_asset_unavailable") from exc
    try:
        expected_uid = pwd.getpwnam("signalops").pw_uid
    except KeyError as exc:
        raise RehearsalError("incoming_directory_unavailable") from exc
    if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode) or info.st_uid != expected_uid:
        raise RehearsalError("cleanup_asset_unsafe")
    path.unlink()


def _cleanup_assets(revision: str) -> dict[str, object]:
    removed = 0
    for suffix in (
        "candidate.tar.gz",
        "recovery.tar.gz",
        "pair.json",
        "bootstrap.py",
        "host_helper.py",
        "seed.py",
        "native_driver.py",
    ):
        path = f"signal-ledger-pr1-{revision}-{suffix}"
        before = (INCOMING / path).exists() or (INCOMING / path).is_symlink()
        _remove_incoming_asset(path)
        removed += int(before)
    pattern = re.compile(rf"(?:candidate|recovery)-{revision}-[0-9a-f]{{16}}\.tar\.gz")
    for entry in TEMP_ROOT.iterdir():
        if pattern.fullmatch(entry.name) is None:
            continue
        info = entry.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_uid != 0:
            raise RehearsalError("staged_archive_cleanup_unsafe")
        entry.unlink()
        removed += 1
    return {"status": "cleaned", "reviewed_head_sha": revision, "removed_assets": removed}


def _cleanup_assets_preserving_primary(
    revision: str, primary_error: BaseException | None = None
) -> None:
    """Keep the operation error while reporting asset-cleanup failure separately."""
    try:
        _cleanup_assets(revision)
    except (RehearsalError, OSError, ValueError, TypeError, KeyError):
        if primary_error is None:
            raise RehearsalError("asset_cleanup_unverified") from None
        _record_cleanup_failure(primary_error, "asset_cleanup_unverified")


def _verify_volume(volume: str, revision: str, pair_sha256: str) -> None:
    if (
        VOLUME_RE.fullmatch(volume) is None
        or REVISION_RE.fullmatch(revision) is None
        or DIGEST_RE.fullmatch(pair_sha256) is None
    ):
        raise RehearsalError("disposable_volume_identity_invalid")
    result = _run(
        [
            "/usr/bin/docker",
            "volume",
            "inspect",
            "--format",
            VOLUME_INSPECT_TEMPLATE,
            volume,
        ],
        timeout=10,
    )
    fields = result.stdout.decode("ascii", errors="strict").strip().split("|")
    if fields != ["local", "true", revision, pair_sha256]:
        raise RehearsalError("disposable_volume_identity_mismatch")


def _remove_volume_if_owned(volume: str, revision: str, pair_sha256: str) -> bool:
    if (
        VOLUME_RE.fullmatch(volume) is None
        or REVISION_RE.fullmatch(revision) is None
        or DIGEST_RE.fullmatch(pair_sha256) is None
    ):
        raise RehearsalError("disposable_volume_identity_invalid")
    inspected = _run(
        [
            "/usr/bin/docker",
            "volume",
            "inspect",
            "--format",
            VOLUME_INSPECT_TEMPLATE,
            volume,
        ],
        timeout=10,
        allow_failure=True,
    )
    if inspected.returncode == 0:
        fields = inspected.stdout.decode("ascii", errors="strict").strip().split("|")
        if fields != ["local", "true", revision, pair_sha256]:
            raise RehearsalError("disposable_volume_identity_mismatch")
        _run(["/usr/bin/docker", "volume", "rm", volume], timeout=15)
    else:
        # A timed-out volume-create can still finish asynchronously. Confirm the daemon is
        # responsive and this exact fixed name is absent before treating cleanup as complete.
        _run(["/usr/bin/docker", "version", "--format", "{{.Server.Version}}"], timeout=10)
        existing = (
            _run(
                [
                    "/usr/bin/docker",
                    "volume",
                    "ls",
                    "--filter",
                    f"name=^{volume}$",
                    "--format",
                    "{{.Name}}",
                ],
                timeout=10,
            )
            .stdout.decode("ascii", errors="strict")
            .splitlines()
        )
        if existing:
            raise RehearsalError("disposable_volume_cleanup_unverified")
        return True
    remains = _run(["/usr/bin/docker", "volume", "inspect", volume], timeout=10, allow_failure=True)
    if remains.returncode == 0:
        raise RehearsalError("disposable_volume_removal_unverified")
    return True


def _remove_owned_container(
    name: str,
    revision: str,
    pair_sha256: str,
    volume: str,
) -> None:
    """Stop and remove a named container only after full-ID ownership checks."""
    if (
        VOLUME_RE.fullmatch(volume) is None
        or REVISION_RE.fullmatch(revision) is None
        or DIGEST_RE.fullmatch(pair_sha256) is None
        or re.fullmatch(
            rf"{re.escape(volume)}-(?:candidate|recovery|cli-[a-z]+-[0-9a-f]{{8}})", name
        )
        is None
    ):
        raise RehearsalError("container_cleanup_identity_invalid")
    run_id = _run_id_for_volume(volume)
    expected_role = name[len(volume) + 1 :].split("-", 1)[0]
    identity = _run(
        [
            "/usr/bin/docker",
            "inspect",
            "--format",
            "{{.Id}}|{{.Name}}|"
            '{{index .Config.Labels "org.stock-probs.pr-rehearsal"}}|'
            '{{index .Config.Labels "org.stock-probs.pr-rehearsal.task"}}|'
            '{{index .Config.Labels "org.stock-probs.pr-rehearsal.head"}}|'
            '{{index .Config.Labels "org.stock-probs.pr-rehearsal.pair"}}|'
            '{{index .Config.Labels "org.stock-probs.pr-rehearsal.role"}}|'
            '{{index .Config.Labels "org.stock-probs.pr-rehearsal.volume"}}|'
            '{{index .Config.Labels "org.stock-probs.pr-rehearsal.run"}}|{{.State.Running}}',
            name,
        ],
        timeout=10,
        allow_failure=True,
    )
    if identity.returncode != 0:
        # An absent --rm CLI container is already clean. Never rm by name when its
        # labels could not be verified: a failed inspect is not proof of ownership.
        remaining = _run(
            [
                "/usr/bin/docker",
                "ps",
                "-a",
                "--no-trunc",
                "--filter",
                f"name=^{name}$",
                "--format",
                "{{.ID}}|{{.Names}}",
            ],
            timeout=10,
            allow_failure=True,
        )
        if remaining.returncode != 0 or remaining.stdout.strip():
            raise RehearsalError("container_cleanup_identity_unverified")
        return
    fields = identity.stdout.decode("ascii", errors="strict").strip().split("|")
    if (
        len(fields) != 10
        or CONTAINER_ID_RE.fullmatch(fields[0]) is None
        or fields[1] != f"/{name}"
        or fields[2] != "true"
        or fields[3] != TASK_ID
        or fields[4] != revision
        or fields[5] != pair_sha256
        or fields[6] != expected_role
        or fields[6] not in {"candidate", "recovery", "cli"}
        or fields[7] != volume
        or fields[8] != run_id
        or fields[9] not in {"true", "false"}
    ):
        raise RehearsalError("container_cleanup_identity_mismatch")
    container_id = fields[0]
    if fields[9] == "true":
        stopped = _run(
            ["/usr/bin/docker", "stop", "--time=5", container_id],
            timeout=15,
            allow_failure=True,
        )
        if stopped.returncode != 0:
            raise RehearsalError("container_stop_failed")
        verified_stopped = _run(
            [
                "/usr/bin/docker",
                "inspect",
                "--format",
                "{{.State.Running}}",
                container_id,
            ],
            timeout=10,
        )
        if verified_stopped.stdout.decode("ascii", errors="strict").strip() != "false":
            raise RehearsalError("container_stop_unverified")
    removed = _run(["/usr/bin/docker", "rm", container_id], timeout=15, allow_failure=True)
    remaining = _run(
        [
            "/usr/bin/docker",
            "ps",
            "-a",
            "--no-trunc",
            "--filter",
            f"name=^{name}$",
            "--format",
            "{{.ID}}|{{.Names}}",
        ],
        timeout=10,
        allow_failure=True,
    )
    if (
        remaining.returncode != 0
        or remaining.stdout.strip()
        or (removed.returncode != 0 and identity.returncode == 0)
    ):
        raise RehearsalError("container_removal_unverified")


def _recovery_process_profile(container: str) -> dict[str, object]:
    probe = """import importlib.util
import json
import pathlib

status = {}
for line in pathlib.Path('/proc/1/status').read_text().splitlines():
    if line.startswith(('Uid:', 'Gid:', 'CapEff:', 'CapPrm:', 'CapBnd:', 'NoNewPrivs:')):
        key, value = line.split(':', 1)
        status[key] = value.strip()
assert int(status['Uid'].split()[0]) == 10001
assert int(status['Gid'].split()[0]) == 10001
assert int(status['CapEff'], 16) == 0 and int(status['CapPrm'], 16) == 0
assert int(status['CapBnd'], 16) == 192 and status['NoNewPrivs'] == '1'
assert not pathlib.Path('/usr/local/bin/opencode').exists()
assert importlib.util.find_spec('stock_probs.assistant') is None
command = (
    pathlib.Path('/proc/1/cmdline').read_bytes().replace(b'\\0', b' ').decode(errors='replace')
)
assert 'stock-probs' in command and 'opencode' not in command
pathlib.Path('/tmp/recovery-write-check').write_text('ok')
pathlib.Path('/tmp/recovery-write-check').unlink()
try:
    pathlib.Path('/run/assistant-worker-home/recovery-write-check').write_text('x')
except PermissionError:
    worker_home_private = True
else:
    pathlib.Path('/run/assistant-worker-home/recovery-write-check').unlink()
    raise AssertionError('worker home is writable')
print(json.dumps({'uid': 10001, 'gid': 10001, 'cap_eff': 0, 'cap_prm': 0,
                  'cap_bnd': 192, 'no_new_privileges': True, 'tmp_writable': True,
                  'worker_home_private': worker_home_private, 'native_worker_absent': True}))"""
    result = _run(
        ["/usr/bin/docker", "exec", "--user", "10001:10001", container, "python", "-c", probe],
        timeout=10,
    )
    value = _json_output(result, "recovery_process_identity_invalid")
    if (
        not isinstance(value, dict)
        or value.get("uid") != 10001
        or value.get("gid") != 10001
        or value.get("cap_eff") != 0
        or value.get("cap_prm") != 0
        or value.get("no_new_privileges") is not True
        or value.get("tmp_writable") is not True
        or value.get("worker_home_private") is not True
        or value.get("native_worker_absent") is not True
    ):
        raise RehearsalError("recovery_process_identity_invalid")
    return value


def _validate_pre_migration_backup(value: object) -> dict[str, object]:
    if (
        not isinstance(value, dict)
        or value.get("status") != "migrated"
        or not isinstance(value.get("pre_migration_backup"), dict)
    ):
        raise RehearsalError("pre_migration_backup_missing")
    backup = value["pre_migration_backup"]
    name = backup.get("name")
    if (
        backup.get("verified") is not True
        or backup.get("schema_version") != 12
        or not isinstance(name, str)
        or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,95}\.spbackup", name) is None
        or not isinstance(backup.get("sha256"), str)
        or DIGEST_RE.fullmatch(backup["sha256"]) is None
    ):
        raise RehearsalError("pre_migration_backup_invalid")
    return {"name": name, "sha256": backup["sha256"], "schema_version": 12, "verified": True}


def _run_pair(payload: dict[str, object]) -> dict[str, object]:
    global MONITOR_ACTIVE, OPERATION_DEADLINE, PRODUCTION_SAMPLE_COUNT
    if (
        payload.get("repository") != REPOSITORY
        or type(payload.get("pull_number")) is not int
        or payload.get("pull_number") != PULL_NUMBER
    ):
        raise RehearsalError("fixed_pull_request_mismatch")
    revision = _revision(payload.get("reviewed_head_sha"))
    pair_sha256 = _digest(payload.get("pair_manifest_sha256"), "pair_manifest_invalid")
    source_digests = _verify_installed_source(revision, pair_sha256)
    _verify_pull_request(revision)
    _production_container()
    candidate_id = _image_id(payload.get("candidate_image_id"), "candidate_image_id_invalid")
    recovery_id = _image_id(payload.get("recovery_image_id"), "recovery_image_id_invalid")
    candidate_context = _digest(
        payload.get("candidate_source_context_sha256"), "candidate_context_invalid"
    )
    recovery_context = _digest(
        payload.get("recovery_source_context_sha256"), "recovery_context_invalid"
    )
    overlay_hash = _digest(payload.get("recovery_overlay_sha256"), "recovery_overlay_invalid")
    if _digest(payload.get("candidate_archive_sha256"), "candidate_archive_invalid") == _digest(
        payload.get("recovery_archive_sha256"), "recovery_archive_invalid"
    ):
        raise RehearsalError("pair_archives_must_differ")

    sample_count = [0]
    host_memtotal_before_kib, host_memavailable_before_kib = _host_memory_kib()
    if host_memavailable_before_kib < START_RESERVE_KIB:
        raise RehearsalError("host_memory_reserve_breached")
    _check_production(sample_count, startup=True)
    MONITOR_ACTIVE = True
    PRODUCTION_SAMPLE_COUNT = sample_count
    OPERATION_DEADLINE = time.monotonic() + MAX_OPERATION_SECONDS

    run_id = secrets.token_hex(8)
    volume = f"signal-ledger-pr1-{revision[:8]}-{run_id}"
    candidate_name = f"signal-ledger-pr1-{revision[:8]}-{run_id}-candidate"
    recovery_name = f"signal-ledger-pr1-{revision[:8]}-{run_id}-recovery"
    candidate_network = _candidate_network_name(volume)
    staged: dict[str, StagedArchive] = {}
    containers: list[str] = []
    volume_created = False
    network_created = False
    candidate_network_id: str | None = None
    candidate_removed = False
    recovery_removed = False
    volume_removed = False
    native_summary: dict[str, object] | None = None
    result_receipt: dict[str, object] | None = None
    primary_exception: BaseException | None = None
    started = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    try:
        manifest, staged = _verify_pair(payload, revision)
        if (
            hashlib.sha256(
                _read_small_asset(f"signal-ledger-pr1-{revision}-pair.json", 65_536, pair_sha256)
            ).hexdigest()
            != pair_sha256
        ):
            raise RehearsalError("reviewed_pair_manifest_mismatch")
        if (
            manifest.get("candidate", {}).get("source_context_sha256") != candidate_context
            or manifest.get("recovery", {}).get("source_context_sha256") != recovery_context
            or manifest.get("recovery", {}).get("overlay_sha256") != overlay_hash
        ):
            raise RehearsalError("pair_context_binding_mismatch")

        _image_identity(BASE_IMAGE_ID, BASE_REVISION)
        _load_image(revision, "candidate", candidate_id, staged["candidate"])
        _load_image(revision, "recovery", recovery_id, staged["recovery"])
        volume_created = True
        volume_created_result = _run(
            [
                "/usr/bin/docker",
                "volume",
                "create",
                "--label",
                "org.stock-probs.pr-rehearsal=true",
                "--label",
                f"org.stock-probs.pr-rehearsal.head={revision}",
                "--label",
                f"org.stock-probs.pr-rehearsal.pair={pair_sha256}",
                volume,
            ],
            timeout=15,
        )
        if volume_created_result.stdout.decode("ascii", errors="strict").strip() != volume:
            raise RehearsalError("disposable_volume_creation_invalid")
        _verify_volume(volume, revision, pair_sha256)

        _volume_cli(
            BASE_IMAGE_ID,
            volume,
            ["migrate"],
            revision=revision,
            pair_manifest_sha256=pair_sha256,
        )
        if (
            _schema_version(
                BASE_IMAGE_ID, volume, revision=revision, pair_manifest_sha256=pair_sha256
            )
            != 12
        ):
            raise RehearsalError("schema12_seed_failed")
        migration = _volume_cli(
            candidate_id,
            volume,
            ["migrate"],
            revision=revision,
            pair_manifest_sha256=pair_sha256,
        )
        backup = _validate_pre_migration_backup(migration)
        if (
            _schema_version(
                candidate_id, volume, revision=revision, pair_manifest_sha256=pair_sha256
            )
            != 13
        ):
            raise RehearsalError("candidate_schema13_migration_failed")

        runtime_users: list[dict[str, str]] = []
        candidate_container: str | None = None
        recovery_container: str | None = None
        candidate_operation_failed = False
        try:
            network_created = True
            candidate_network_id = _create_candidate_network(
                candidate_network, revision, pair_sha256, volume
            )
            containers.append(candidate_name)
            candidate_container = _start_app(
                candidate_id,
                volume,
                candidate_name,
                assistant_enabled=True,
                network=candidate_network,
                network_id=candidate_network_id,
                run_id=run_id,
                reviewed_head_sha=revision,
                pair_manifest_sha256=pair_sha256,
                role="candidate",
            )
            candidate_memory_baseline = _memory_usage(candidate_container)
            _oom_event_evidence(
                candidate_memory_baseline, candidate_memory_baseline, role="candidate"
            )
            _cpu_stat_evidence(
                candidate_memory_baseline, candidate_memory_baseline, role="candidate"
            )
            _wait_ready(candidate_container, enabled=True, sample_count=sample_count)
            _copy_fixture_files(candidate_container, source_digests)
            seed_result = _seed(candidate_container)
            users_value = seed_result.get("users")
            user_ids = seed_result.get("synthetic_user_ids")
            if not isinstance(users_value, list) or len(users_value) != 2:
                raise RehearsalError("synthetic_identity_invalid")
            if not isinstance(user_ids, list) or len(user_ids) != 2:
                raise RehearsalError("synthetic_identity_invalid")
            runtime_users = users_value
            verified_backup = _container_fixture(
                candidate_container, "verify-backup", {"backup_name": backup["name"]}
            )
            if verified_backup != {
                "verified": True,
                "schema_version": 12,
                "integrity_verified": True,
            }:
                raise RehearsalError("historical_backup_verification_failed")
            refused = _volume_cli(
                candidate_id,
                volume,
                ["restore", backup["name"]],
                revision=revision,
                pair_manifest_sha256=pair_sha256,
                expected_rejection=(
                    "Backup schema version 12 cannot be restored over active schema version 13"
                ),
            )
            if not isinstance(refused, dict) or refused.get("restore_denied") is not True:
                raise RehearsalError("historical_restore_guard_failed")
            native_summary = _run_native_workload(candidate_container, runtime_users, sample_count)
            restore_guard = _container_fixture(
                candidate_container,
                "restore-guard",
                {"users": runtime_users, "backup_name": backup["name"]},
            )
            if restore_guard.get("restore_guard_denied_without_fresh_step_up") is not True:
                raise RehearsalError("restore_security_guard_failed")
            marker = _container_fixture(
                candidate_container,
                "marker",
                {"user_id": user_ids[0], "revision": revision},
            )
            request_id = marker.get("request_id")
            if not isinstance(request_id, str) or len(request_id) > 96:
                raise RehearsalError("post_migration_write_failed")
            candidate_snapshot = _container_fixture(
                candidate_container, "snapshot", {"request_id": request_id}
            )
            if candidate_snapshot.get("marker_present") is not True:
                raise RehearsalError("post_migration_write_failed")
            candidate_memory_final = _memory_usage(candidate_container)
            candidate_oom_event_evidence = _oom_event_evidence(
                candidate_memory_baseline, candidate_memory_final, role="candidate"
            )
            candidate_cpu_stat_evidence = _cpu_stat_evidence(
                candidate_memory_baseline, candidate_memory_final, role="candidate"
            )
        except BaseException:
            # Let the outer cleanup retry without replacing the active operation error.
            candidate_operation_failed = True
            raise
        finally:
            if not candidate_operation_failed and candidate_name in containers:
                _remove_owned_container(candidate_name, revision, pair_sha256, volume)
                containers.remove(candidate_name)
                candidate_removed = True
                candidate_container = None

        recovery_operation_failed = False
        try:
            containers.append(recovery_name)
            recovery_container = _start_app(
                recovery_id,
                volume,
                recovery_name,
                assistant_enabled=False,
                network="none",
                network_id=None,
                run_id=run_id,
                reviewed_head_sha=revision,
                pair_manifest_sha256=pair_sha256,
                role="recovery",
            )
            recovery_memory_baseline = _memory_usage(recovery_container, expected_role="recovery")
            _oom_event_evidence(
                recovery_memory_baseline,
                recovery_memory_baseline,
                role="recovery",
            )
            _cpu_stat_evidence(recovery_memory_baseline, recovery_memory_baseline, role="recovery")
            _wait_ready(recovery_container, enabled=False, sample_count=sample_count)
            _copy_fixture_files(recovery_container, source_digests)
            process_profile = _recovery_process_profile(recovery_container)
            recovery_snapshot = _container_fixture(
                recovery_container, "snapshot", {"request_id": request_id}
            )
            if (
                recovery_snapshot.get("sha256") != candidate_snapshot.get("sha256")
                or recovery_snapshot.get("security_state_sha256")
                != candidate_snapshot.get("security_state_sha256")
                or recovery_snapshot.get("marker_present") is not True
            ):
                raise RehearsalError("post_migration_write_or_security_state_lost")
            recovery_guard = _container_fixture(
                recovery_container,
                "restore-guard",
                {"users": runtime_users, "backup_name": backup["name"]},
            )
            if recovery_guard.get("restore_guard_denied_without_fresh_step_up") is not True:
                raise RehearsalError("recovery_restore_security_guard_failed")
            if (
                _schema_version(
                    recovery_id, volume, revision=revision, pair_manifest_sha256=pair_sha256
                )
                != 13
            ):
                raise RehearsalError("recovery_schema_changed")
            recovery_memory_final = _memory_usage(recovery_container, expected_role="recovery")
            recovery_oom_event_evidence = _oom_event_evidence(
                recovery_memory_baseline, recovery_memory_final, role="recovery"
            )
            recovery_cpu_stat_evidence = _cpu_stat_evidence(
                recovery_memory_baseline, recovery_memory_final, role="recovery"
            )
        except BaseException:
            # Let the outer cleanup retry without replacing the active operation error.
            recovery_operation_failed = True
            raise
        finally:
            if not recovery_operation_failed and recovery_name in containers:
                _remove_owned_container(recovery_name, revision, pair_sha256, volume)
                containers.remove(recovery_name)
                recovery_removed = True
                recovery_container = None

        _verify_volume(volume, revision, pair_sha256)
        _check_production(sample_count)
        host_memtotal_after_kib, host_memavailable_after_kib = _host_memory_kib()
        if host_memtotal_after_kib != host_memtotal_before_kib:
            raise RehearsalError(
                "host_memory_capacity_changed",
                details={
                    "host_memory_evidence_complete": True,
                    "host_memtotal_before_kib": host_memtotal_before_kib,
                    "host_memtotal_after_kib": host_memtotal_after_kib,
                    "capacity_claim": "unavailable",
                },
            )
        if host_memavailable_after_kib < RUN_RESERVE_KIB:
            raise RehearsalError("host_memory_reserve_breached")
        result_receipt = {
            "status": "pass",
            "reviewed_head_sha": revision,
            "pair_manifest_sha256": pair_sha256,
            "candidate_image_id": candidate_id,
            "recovery_image_id": recovery_id,
            "candidate_source_context_sha256": candidate_context,
            "recovery_source_context_sha256": recovery_context,
            "recovery_overlay_sha256": overlay_hash,
            "same_disposable_volume": True,
            "production_mutation": False,
            "production_health_samples": sample_count[0],
            "host_memavailable_before_kib": host_memavailable_before_kib,
            "host_memavailable_after_kib": host_memavailable_after_kib,
            "host_memory_capacity_evidence": {
                "complete": True,
                "unit": "kib",
                "memtotal_before": host_memtotal_before_kib,
                "memtotal_after": host_memtotal_after_kib,
                "stable": True,
            },
            "candidate_memory_peak_bytes": candidate_memory_final["peak"],
            "candidate_memory_limit_bytes": candidate_memory_final["limit"],
            "candidate_oom_event_evidence": candidate_oom_event_evidence,
            "candidate_cpu_stat_evidence": candidate_cpu_stat_evidence,
            "recovery_memory_peak_bytes": recovery_memory_final["peak"],
            "recovery_memory_limit_bytes": recovery_memory_final["limit"],
            "recovery_oom_event_evidence": recovery_oom_event_evidence,
            "recovery_cpu_stat_evidence": recovery_cpu_stat_evidence,
            "oom_event_evidence_complete": True,
            "zero_oom_events_verified": True,
            "migration_backup_verified": True,
            "post_migration_write_preserved": True,
            "ownership_isolation_verified": native_summary["owner_isolation"],
            "restore_guard_verified": True,
            "recovery_process_isolation_verified": (
                process_profile.get("worker_home_private") is True
                and process_profile.get("native_worker_absent") is True
                and process_profile.get("tmp_writable") is True
            ),
            "architecture": platform.machine(),
            "native_model_id": native_summary["model_id"],
            "mcp_workspace_summary_calls": native_summary["mcp_workspace_summary_calls"],
            "native_search_source_count": native_summary["builtin_search_source_count"],
            "simultaneous_two_owner_turns": native_summary["simultaneous_two_owner_turns"],
            "candidate_container_removed": candidate_removed,
            "recovery_container_removed": recovery_removed,
            "volume_removed": False,
            "images_retained": True,
            "started_at": started,
            "finished_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        }
    except BaseException as exc:
        primary_exception = exc
        raise
    finally:
        cleanup_error: str | None = None
        containers_removed = True
        try:
            # Do not remove the volume while any attached app could still write to it.
            for container in reversed(containers):
                try:
                    _remove_owned_container(container, revision, pair_sha256, volume)
                except (RehearsalError, OSError, ValueError, TypeError, KeyError):
                    containers_removed = False
                    cleanup_error = cleanup_error or "container_removal_unverified"
            for container_name, container_volume, container_revision, container_pair in reversed(
                OPERATION_CONTAINERS
            ):
                try:
                    _remove_owned_container(
                        container_name, container_revision, container_pair, container_volume
                    )
                    OPERATION_CONTAINERS.remove(
                        (container_name, container_volume, container_revision, container_pair)
                    )
                except (RehearsalError, OSError, ValueError, TypeError, KeyError):
                    containers_removed = False
                    cleanup_error = cleanup_error or "cli_container_removal_unverified"
            if containers_removed:
                try:
                    _network_removed, volume_removed = _cleanup_network_before_volume(
                        containers_removed=True,
                        network_name=candidate_network,
                        network_id=candidate_network_id,
                        network_created=network_created,
                        revision=revision,
                        pair_sha256=pair_sha256,
                        volume=volume,
                        volume_created=volume_created,
                    )
                except (RehearsalError, OSError, ValueError, TypeError, KeyError):
                    cleanup_error = cleanup_error or "network_or_volume_removal_unverified"
            elif volume_created or network_created:
                cleanup_error = cleanup_error or "disposable_volume_retained_for_running_container"
            for archive in staged.values():
                try:
                    info = archive.path.lstat()
                    if stat.S_ISREG(info.st_mode) and info.st_uid == 0:
                        archive.path.unlink()
                except FileNotFoundError:
                    pass
                except OSError:
                    cleanup_error = cleanup_error or "staged_archive_cleanup_unverified"
            try:
                _cleanup_assets(revision)
            except (RehearsalError, OSError, ValueError, TypeError, KeyError):
                cleanup_error = cleanup_error or "asset_cleanup_unverified"
        finally:
            MONITOR_ACTIVE = False
            OPERATION_DEADLINE = None
        if cleanup_error is not None:
            if primary_exception is None:
                raise RehearsalError(cleanup_error)
            _record_cleanup_failure(primary_exception, cleanup_error)
    if result_receipt is None:
        raise RehearsalError("rehearsal_result_missing")
    result_receipt["volume_removed"] = volume_removed
    result_receipt["candidate_container_removed"] = candidate_removed
    result_receipt["recovery_container_removed"] = recovery_removed
    return result_receipt


def main() -> int:
    """Serve only the fixed sidecar operations through bounded JSON stdin/stdout."""

    if os.geteuid() != 0:
        response: dict[str, object] = {"status": "error", "code": "root_required"}
    else:
        raw = __import__("sys").stdin.buffer.read(MAX_REQUEST + 1)
        if not raw or len(raw) > MAX_REQUEST:
            response = {"status": "error", "code": "request_invalid"}
        else:
            lock_descriptor = -1
            try:
                operation, payload = _parse_request(raw)
                _prepare_host_paths()
                lock_descriptor = _operation_lock()
                if operation == "cleanup_assets":
                    revision = _revision(payload.get("reviewed_head_sha"))
                    response = _cleanup_assets(revision)
                else:
                    revision = _revision(payload.get("reviewed_head_sha"))
                    try:
                        response = _run_pair(payload)
                    except Exception as exc:
                        _cleanup_assets_preserving_primary(revision, exc)
                        raise
                    else:
                        _cleanup_assets_preserving_primary(revision)
                    response["receipt_id"] = _write_receipt(response)
            except RehearsalError as exc:
                response = {"status": "error", "code": exc.code}
                if exc.details:
                    response["failure"] = exc.details
                if exc.cleanup_failure in CLEANUP_FAILURE_CODES:
                    response["cleanup_failure"] = exc.cleanup_failure
                if lock_descriptor >= 0 and response.get("status") == "error":
                    with suppress(RehearsalError, OSError):
                        response["receipt_id"] = _write_receipt(response)
            except (OSError, ValueError, TypeError, KeyError) as exc:
                # Only the fixed exception type is retained; no path, argv, output, or message.
                response = {
                    "status": "error",
                    "code": f"operation_failed:{type(exc).__name__.casefold()}",
                }
                cleanup_failure = getattr(exc, "cleanup_failure", None)
                if cleanup_failure in CLEANUP_FAILURE_CODES:
                    response["cleanup_failure"] = cleanup_failure
            finally:
                if lock_descriptor >= 0:
                    fcntl.flock(lock_descriptor, fcntl.LOCK_UN)
                    os.close(lock_descriptor)
    encoded = json.dumps(response, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    if len(encoded) > MAX_RESPONSE:
        encoded = b'{"status":"error","code":"response_too_large"}'
    __import__("sys").stdout.buffer.write(encoded + b"\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
