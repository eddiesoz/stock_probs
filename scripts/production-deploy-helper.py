#!/usr/bin/env python3
"""Run the fixed, host-side Signal Ledger release protocol.

The SSH entry point accepts one bounded JSON request and never accepts a shell command,
filesystem path, image name, or network URL from its caller.  The setup script installs this
file behind a root-owned wrapper and a narrowly scoped sudo rule; the state and Docker commands
below are therefore the only production mutations available to the deployment MCP.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import secrets
import selectors
import stat
import subprocess
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REQUEST_LIMIT = 8_192
RESPONSE_LIMIT = 65_536
REVISION_PATTERN = re.compile(r"^[0-9a-f]{40}$")
PLAN_PATTERN = re.compile(r"^[0-9a-f]{32}$")
DIGEST_PATTERN = re.compile(r"^[0-9a-f]{64}$")
IMAGE_ID_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
BACKUP_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,126}\.spbackup$")

# These paths are deliberately constants.  A tool request can select a release, but cannot
# redirect the helper to an attacker-controlled repository, compose file, or state directory.
REPOSITORY_URL = "https://github.com/eddiesoz/stock_probs.git"
MAIN_BRANCH = "main"
STATE_ROOT = Path("/var/lib/signal-ledger")
SOURCE_ROOT = STATE_ROOT / "source"
RELEASE_ROOT = STATE_ROOT / "releases"
PLAN_ROOT = STATE_ROOT / "plans"
CURRENT_RECORD = STATE_ROOT / "current.json"
FAILED_RECORD = STATE_ROOT / "failed.json"
COMPOSE_FILE = Path("/opt/signal-ledger/compose.production.yaml")
APP_ENV_FILE = Path("/etc/signal-ledger/app.env")
RUNTIME_ENV_FILE = STATE_ROOT / "runtime.env"
AUDIT_LOG = Path("/var/log/signal-ledger/deploy.jsonl")
LOCK_FILE = STATE_ROOT / "deploy.lock"
PROJECT_NAME = "signal-ledger"
# The registry is deliberately fixed in the root-owned helper.  MCP callers can supply a
# reviewed commit and digest, but cannot redirect the host to another registry or image.
IMAGE_REPOSITORY = "ghcr.io/jtmb/signal-ledger"
IMAGE_DIGEST_PREFIX = f"{IMAGE_REPOSITORY}@sha256:"
GITHUB_RELEASE_REPOSITORY = "eddiesoz/stock_probs"
GITHUB_RELEASE_TAG_PREFIX = "signal-ledger-"
GITHUB_RELEASE_ARCHIVE_PREFIX = "signal-ledger-image-"
GITHUB_RELEASE_ARCHIVE_SUFFIX = ".tar.gz"
GITHUB_RELEASE_TRANSPORT = "github_release"
LOCAL_IMAGE_REPOSITORY = "signal-ledger"
MAX_RELEASE_ARCHIVE_BYTES = 512 * 1024 * 1024
RELEASE_DOWNLOAD_TIMEOUT_SECONDS = 600
HEALTH_URL = "http://127.0.0.1:8000/api/v1/readiness"
HEALTH_ATTEMPTS = 30
HEALTH_DELAY_SECONDS = 1.0

_ALLOWED_OPERATIONS = frozenset({"inspect", "plan_deploy", "deploy", "status", "rollback"})
_EXPECTED_PAYLOAD_KEYS = {
    "inspect": frozenset(),
    "status": frozenset(),
    "plan_deploy": frozenset({"revision", "archive_sha256", "image_id"}),
    "deploy": frozenset({"plan_id", "revision", "archive_sha256", "image_id"}),
    "rollback": frozenset({"revision", "image_id"}),
}

# The old GHCR shape remains accepted by the forced command for already prepared hosts.  The
# MCP exposes the release archive shape above; retaining this exact legacy form lets an operator
# finish a previously staged GHCR plan without turning arbitrary registry input into a command.
_LEGACY_PAYLOAD_KEYS = {
    "plan_deploy": frozenset({"revision", "expected_image_digest"}),
    "deploy": frozenset({"plan_id", "revision", "image_digest"}),
    "rollback": frozenset({"revision"}),
}


class HostError(Exception):
    """An operator-safe failure category returned to the MCP controller."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _validate_revision(value: object) -> str:
    if not isinstance(value, str) or REVISION_PATTERN.fullmatch(value) is None:
        raise HostError("revision_invalid")
    return value


def _validate_plan_id(value: object) -> str:
    if not isinstance(value, str) or PLAN_PATTERN.fullmatch(value) is None:
        raise HostError("plan_id_invalid")
    return value


def _validate_digest(value: object) -> str:
    if not isinstance(value, str) or DIGEST_PATTERN.fullmatch(value) is None:
        raise HostError("image_digest_invalid")
    return value


def _validate_image_id(value: object) -> str:
    if not isinstance(value, str) or IMAGE_ID_PATTERN.fullmatch(value) is None:
        raise HostError("image_id_invalid")
    return value


def _release_archive_url(revision: str) -> str:
    """Build the only permitted image archive URL from the reviewed revision."""

    _validate_revision(revision)
    tag = f"{GITHUB_RELEASE_TAG_PREFIX}{revision}"
    return f"https://github.com/{GITHUB_RELEASE_REPOSITORY}/releases/download/{tag}/{_release_archive_name(revision)}"


def _release_archive_name(revision: str) -> str:
    """Return the immutable asset filename derived from a reviewed revision."""

    _validate_revision(revision)
    return f"{GITHUB_RELEASE_ARCHIVE_PREFIX}{revision}{GITHUB_RELEASE_ARCHIVE_SUFFIX}"


def _local_image_ref(revision: str) -> str:
    """Return the deterministic local tag used after an archive is verified and loaded."""

    _validate_revision(revision)
    return f"{LOCAL_IMAGE_REPOSITORY}:sha-{revision}"


def _safe_mode(path: Path, mode: int) -> None:
    """Create a private directory and repair its mode without following a final symlink."""

    path.mkdir(mode=mode, parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        if not stat.S_ISDIR(os.fstat(descriptor).st_mode):
            raise HostError("state_path_unsafe")
        os.fchmod(descriptor, mode)
    except OSError as exc:
        raise HostError("state_path_unsafe") from exc
    finally:
        os.close(descriptor)


def _ensure_layout() -> None:
    for path in (STATE_ROOT, SOURCE_ROOT.parent, RELEASE_ROOT, PLAN_ROOT):
        _safe_mode(path, 0o750)
    _safe_mode(AUDIT_LOG.parent, 0o750)
    _safe_mode(LOCK_FILE.parent, 0o750)
    if not COMPOSE_FILE.is_file() or COMPOSE_FILE.is_symlink():
        raise HostError("compose_unavailable")
    if not APP_ENV_FILE.is_file() or APP_ENV_FILE.is_symlink():
        raise HostError("production_env_unavailable")
    try:
        metadata = APP_ENV_FILE.stat()
    except OSError as exc:
        raise HostError("production_env_unavailable") from exc
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_mode & 0o077:
        raise HostError("production_env_permissions")


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise HostError("state_unavailable") from exc
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > 16_384:
            raise HostError("state_unsafe")
        raw = os.read(descriptor, 16_385)
    except OSError as exc:
        raise HostError("state_unavailable") from exc
    finally:
        os.close(descriptor)
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HostError("state_invalid") from exc
    if not isinstance(value, dict):
        raise HostError("state_invalid")
    return value


def _write_json(path: Path, value: dict[str, Any]) -> None:
    """Publish a small state record atomically so a killed helper cannot tear it in half."""

    _safe_mode(path.parent, 0o750)
    temporary = path.with_name(f".{path.name}.{secrets.token_hex(8)}.tmp")
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    descriptor = os.open(
        temporary,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
        0o600,
    )
    try:
        _write_all(descriptor, encoded)
        os.fsync(descriptor)
    except OSError as exc:
        temporary.unlink(missing_ok=True)
        raise HostError("state_write_failed") from exc
    finally:
        os.close(descriptor)
    try:
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    except OSError as exc:
        temporary.unlink(missing_ok=True)
        raise HostError("state_write_failed") from exc


def _audit(operation: str, result: str, **fields: object) -> None:
    """Append allowlisted release metadata; command output and secrets never enter the log."""

    record: dict[str, object] = {
        "at": _utc_now(),
        "operation": operation,
        "result": result,
    }
    for key in (
        "revision",
        "plan_id",
        "image_digest",
        "compose_digest",
        "schema_version",
        "backup_name",
    ):
        if key in fields and fields[key] is not None:
            record[key] = fields[key]
    try:
        _safe_mode(AUDIT_LOG.parent, 0o750)
        descriptor = os.open(
            AUDIT_LOG,
            os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW,
            0o640,
        )
        try:
            _write_all(descriptor, (json.dumps(record, sort_keys=True) + "\n").encode())
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    except OSError:
        # The release result still goes to the caller; a missing audit receipt is an operator
        # error visible in status rather than a reason to print a filesystem exception.
        return


def _write_all(descriptor: int, value: bytes) -> None:
    """Complete bounded writes even when the host returns a short syscall result."""

    offset = 0
    while offset < len(value):
        try:
            written = os.write(descriptor, value[offset:])
        except OSError as exc:
            raise OSError("bounded state write failed") from exc
        if written <= 0:
            raise OSError("bounded state write returned zero bytes")
        offset += written


@contextmanager
def _exclusive_lock() -> Iterator[None]:
    """Serialize plans and promotions across concurrent SSH sessions."""

    try:
        _safe_mode(LOCK_FILE.parent, 0o750)
        descriptor = os.open(LOCK_FILE, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o640)
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as exc:
        raise HostError("deployment_busy") from exc
    except OSError as exc:
        raise HostError("deployment_lock_unavailable") from exc
    try:
        yield
    finally:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        finally:
            os.close(descriptor)


def _run(
    command: list[str], *, timeout: float, cwd: Path | None = None
) -> subprocess.CompletedProcess[str]:
    """Run one fixed argv while bounding both pipe memory and command duration."""

    process: subprocess.Popen[bytes] | None = None
    selector: selectors.BaseSelector | None = None

    def kill_and_reap() -> None:
        """Stop a timed-out child without leaving an unbounded wait in the host helper."""

        if process is None or process.poll() is not None:
            return
        try:
            process.kill()
        except ProcessLookupError:
            return
        try:
            process.wait(timeout=1.0)
        except subprocess.TimeoutExpired as exc:
            raise HostError("host_command_timeout") from exc

    try:
        process = subprocess.Popen(  # noqa: S603 - argv is fixed or validated before this call.
            command,
            cwd=cwd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        if process.stdout is None or process.stderr is None:
            raise HostError("host_command_failed")
        selector = selectors.DefaultSelector()
        selector.register(process.stdout, selectors.EVENT_READ, "stdout")
        selector.register(process.stderr, selectors.EVENT_READ, "stderr")
        outputs: dict[str, bytearray] = {"stdout": bytearray(), "stderr": bytearray()}
        deadline = time.monotonic() + timeout
        while selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                kill_and_reap()
                raise HostError("host_command_timeout")
            events = selector.select(remaining)
            if not events:
                continue
            for key, _ in events:
                stream = key.fileobj
                descriptor = stream if isinstance(stream, int) else stream.fileno()
                chunk = os.read(descriptor, 4_096)
                if not chunk:
                    selector.unregister(stream)
                    continue
                output = outputs[key.data]
                output.extend(chunk)
                if len(output) > 32_768:
                    kill_and_reap()
                    raise HostError("host_command_output_too_large")
        remaining = max(0.0, deadline - time.monotonic())
        try:
            return_code = process.wait(timeout=remaining)
        except subprocess.TimeoutExpired as exc:
            kill_and_reap()
            raise HostError("host_command_timeout") from exc
        try:
            stdout = bytes(outputs["stdout"]).decode()
            stderr = bytes(outputs["stderr"]).decode()
        except UnicodeDecodeError as exc:
            raise HostError("host_command_output_invalid") from exc
    except OSError as exc:
        kill_and_reap()
        raise HostError("host_command_failed") from exc
    finally:
        if selector is not None:
            selector.close()
    if return_code != 0:
        raise HostError("host_command_failed")
    return subprocess.CompletedProcess(command, return_code, stdout, stderr)


def _git(*arguments: str, timeout: float = 120.0) -> str:
    return _run(["git", "-C", str(SOURCE_ROOT), *arguments], timeout=timeout).stdout.strip()


def _ensure_source() -> None:
    """Fetch only the fixed origin/main ref into the private host checkout."""

    _safe_mode(SOURCE_ROOT.parent, 0o750)
    try:
        source_info = SOURCE_ROOT.lstat()
    except FileNotFoundError:
        source_info = None
    except OSError as exc:
        raise HostError("source_unavailable") from exc
    if source_info is not None and (
        not stat.S_ISDIR(source_info.st_mode) or stat.S_ISLNK(source_info.st_mode)
    ):
        raise HostError("source_unavailable")
    if source_info is None:
        _run(
            ["git", "clone", "--origin", "origin", REPOSITORY_URL, str(SOURCE_ROOT)],
            timeout=600,
        )
    else:
        try:
            git_info = (SOURCE_ROOT / ".git").lstat()
        except OSError as exc:
            raise HostError("source_unavailable") from exc
        if stat.S_ISLNK(git_info.st_mode) or not stat.S_ISDIR(git_info.st_mode):
            raise HostError("source_unavailable")
    _safe_mode(SOURCE_ROOT, 0o750)
    if _git("remote", "get-url", "origin") != REPOSITORY_URL:
        raise HostError("repository_origin_invalid")
    _run(
        [
            "git",
            "-C",
            str(SOURCE_ROOT),
            "fetch",
            "--no-tags",
            "--prune",
            "origin",
            f"{MAIN_BRANCH}:refs/remotes/origin/{MAIN_BRANCH}",
        ],
        timeout=600,
    )


def _assert_main_revision(revision: str) -> None:
    main_revision = _git("rev-parse", f"refs/remotes/origin/{MAIN_BRANCH}")
    if main_revision != revision:
        raise HostError("revision_not_current_main")
    _git("cat-file", "-e", f"{revision}^{{commit}}")


def _checkout_revision(revision: str) -> None:
    """Make the build context exactly the reviewed commit, including no host leftovers."""

    _run(
        ["git", "-C", str(SOURCE_ROOT), "reset", "--hard", "--quiet", revision],
        timeout=120,
    )
    _run(
        ["git", "-C", str(SOURCE_ROOT), "clean", "-ffd", "--quiet"],
        timeout=120,
    )
    if _git("rev-parse", "HEAD") != revision:
        raise HostError("source_revision_mismatch")


def _assert_compose_revision() -> None:
    """Require the installed root-owned Compose file to match reviewed source.

    Compose changes need an operator setup refresh, rather than an MCP-supplied file.
    """

    source_compose = SOURCE_ROOT / "compose.production.yaml"
    try:
        if (
            source_compose.is_symlink()
            or not source_compose.is_file()
            or COMPOSE_FILE.is_symlink()
            or not COMPOSE_FILE.is_file()
        ):
            raise HostError("compose_revision_mismatch")
        if COMPOSE_FILE.read_bytes() != source_compose.read_bytes():
            raise HostError("compose_revision_mismatch")
    except OSError as exc:
        raise HostError("compose_revision_mismatch") from exc


def _compose_digest() -> str:
    """Return the digest of the root-owned Compose file used by the host service."""

    try:
        metadata = COMPOSE_FILE.lstat()
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
            raise HostError("compose_revision_mismatch")
        content = COMPOSE_FILE.read_bytes()
    except OSError as exc:
        raise HostError("compose_revision_mismatch") from exc
    digest = hashlib.sha256(content).hexdigest()
    if DIGEST_PATTERN.fullmatch(digest) is None:
        raise HostError("compose_revision_mismatch")
    return digest


def _assert_record_compose_digest(record: dict[str, Any]) -> None:
    """Reject a release unless its fixed Compose bytes are still installed."""

    expected = record.get("compose_digest")
    if not isinstance(expected, str) or DIGEST_PATTERN.fullmatch(expected) is None:
        raise HostError("compose_revision_mismatch")
    if _compose_digest() != expected:
        raise HostError("compose_revision_mismatch")


def _image_ref(revision: str, image_digest: str) -> str:
    """Return the fixed registry reference for a reviewed revision and receipt digest."""

    if (
        REVISION_PATTERN.fullmatch(revision) is None
        or DIGEST_PATTERN.fullmatch(image_digest) is None
    ):
        raise HostError("image_ref_invalid")
    return f"{IMAGE_DIGEST_PREFIX}{image_digest}"


def _image_digest(image_ref: str) -> str:
    """Read the registry content digest for an already-pulled image."""

    value = _run(
        ["docker", "image", "inspect", "--format", "{{json .RepoDigests}}", image_ref],
        timeout=30,
    ).stdout.strip()
    try:
        repo_digests = json.loads(value)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HostError("image_digest_unavailable") from exc
    if not isinstance(repo_digests, list):
        raise HostError("image_digest_unavailable")
    expected_prefix = f"{IMAGE_REPOSITORY}@sha256:"
    for repo_digest in repo_digests:
        if not isinstance(repo_digest, str) or not repo_digest.startswith(expected_prefix):
            continue
        digest = repo_digest.removeprefix(expected_prefix)
        if DIGEST_PATTERN.fullmatch(digest) is not None:
            return digest
    raise HostError("image_digest_unavailable")


def _image_revision(image_ref: str) -> str:
    """Read the OCI source revision label from a pulled image."""

    revision = _run(
        [
            "docker",
            "image",
            "inspect",
            "--format",
            '{{index .Config.Labels "org.opencontainers.image.revision"}}',
            image_ref,
        ],
        timeout=30,
    ).stdout.strip()
    if REVISION_PATTERN.fullmatch(revision) is None:
        raise HostError("image_revision_unavailable")
    return revision


def _image_id(image_ref: str) -> str:
    """Read the immutable Docker image ID for an already loaded local image."""

    image_id = _run(
        ["docker", "image", "inspect", "--format", "{{.Id}}", image_ref],
        timeout=30,
    ).stdout.strip()
    if IMAGE_ID_PATTERN.fullmatch(image_id) is None:
        raise HostError("image_id_unavailable")
    return image_id


def _image_platform(image_ref: str) -> str:
    """Require the published archive to contain the production Linux amd64 image."""

    platform = _run(
        ["docker", "image", "inspect", "--format", "{{.Os}}/{{.Architecture}}", image_ref],
        timeout=30,
    ).stdout.strip()
    if platform != "linux/amd64":
        raise HostError("image_platform_mismatch")
    return platform


def _archive_sha256(path: Path) -> tuple[str, int]:
    """Hash a bounded archive without loading it into memory."""

    try:
        metadata = path.lstat()
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
            raise HostError("release_archive_unsafe")
        if metadata.st_size <= 0 or metadata.st_size > MAX_RELEASE_ARCHIVE_BYTES:
            raise HostError("release_archive_too_large")
        digest = hashlib.sha256()
        size = 0
        with path.open("rb") as archive:
            while True:
                chunk = archive.read(1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > MAX_RELEASE_ARCHIVE_BYTES:
                    raise HostError("release_archive_too_large")
                digest.update(chunk)
    except HostError:
        raise
    except OSError as exc:
        raise HostError("release_archive_unavailable") from exc
    return digest.hexdigest(), size


def _download_release_archive(revision: str) -> Path:
    """Download the fixed GitHub asset into a private, temporary release directory."""

    _safe_mode(RELEASE_ROOT, 0o750)
    temporary = RELEASE_ROOT / f".image-{revision}-{secrets.token_hex(8)}.tar.gz"
    try:
        descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
        )
        os.close(descriptor)
        _run(
            [
                "curl",
                "--fail",
                "--silent",
                "--show-error",
                "--location",
                "--proto",
                "=https",
                "--proto-redir",
                "=https",
                "--max-redirs",
                "3",
                "--connect-timeout",
                "10",
                "--max-time",
                str(RELEASE_DOWNLOAD_TIMEOUT_SECONDS),
                "--max-filesize",
                str(MAX_RELEASE_ARCHIVE_BYTES),
                "--output",
                str(temporary),
                _release_archive_url(revision),
            ],
            timeout=RELEASE_DOWNLOAD_TIMEOUT_SECONDS + 30,
        )
        metadata = temporary.lstat()
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
            raise HostError("release_archive_unsafe")
        if metadata.st_size <= 0 or metadata.st_size > MAX_RELEASE_ARCHIVE_BYTES:
            raise HostError("release_archive_too_large")
        return temporary
    except HostError:
        temporary.unlink(missing_ok=True)
        raise
    except OSError as exc:
        temporary.unlink(missing_ok=True)
        raise HostError("release_archive_unavailable") from exc


def _load_release_archive(
    revision: str, expected_archive_sha256: str, expected_image_id: str
) -> tuple[str, str, str, str, int, int]:
    """Download, hash, load, and inspect a locally published GitHub image archive."""

    _validate_revision(revision)
    _validate_digest(expected_archive_sha256)
    _validate_image_id(expected_image_id)
    archive = _download_release_archive(revision)
    try:
        archive_sha256, archive_size = _archive_sha256(archive)
        if archive_sha256 != expected_archive_sha256:
            raise HostError("archive_digest_mismatch")
        _run(["docker", "load", "--input", str(archive)], timeout=300)
        loaded_image_id = _image_id(expected_image_id)
        if loaded_image_id != expected_image_id:
            raise HostError("image_id_mismatch")
        if _image_revision(expected_image_id) != revision:
            raise HostError("image_revision_mismatch")
        platform = _image_platform(expected_image_id)
        image_ref = _local_image_ref(revision)
        _run(["docker", "tag", expected_image_id, image_ref], timeout=30)
        if _image_id(image_ref) != expected_image_id:
            raise HostError("image_id_mismatch")
        schema_version = _image_schema(image_ref)
        return image_ref, archive_sha256, expected_image_id, platform, schema_version, archive_size
    finally:
        archive.unlink(missing_ok=True)


def _image_schema(image_ref: str) -> int:
    value = _run(
        [
            "docker",
            "run",
            "--rm",
            "--pull",
            "never",
            "--network",
            "none",
            "--read-only",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
            "--pids-limit",
            "64",
            "--memory",
            "256m",
            "--cpus",
            "0.5",
            "--user",
            "10001:10001",
            "--tmpfs",
            "/tmp:rw,nosuid,nodev,noexec,size=16m",  # noqa: S108 - private in-container tmpfs
            "--entrypoint",
            "python",
            image_ref,
            "-c",
            "from stock_probs.repository import SCHEMA_VERSION; print(SCHEMA_VERSION)",
        ],
        timeout=60,
    ).stdout.strip()
    if not value.isdigit() or not 1 <= int(value) <= 100:
        raise HostError("image_schema_unavailable")
    return int(value)


def _pull_image(revision: str, expected_image_digest: str) -> tuple[str, str, int]:
    """Pull and verify the publisher's immutable digest; no tag lookup or host build occurs."""

    image_ref = _image_ref(revision, expected_image_digest)
    _run(
        [
            "docker",
            "pull",
            "--quiet",
            image_ref,
        ],
        timeout=600,
    )
    image_digest = _image_digest(image_ref)
    if image_digest != expected_image_digest:
        raise HostError("image_digest_mismatch")
    if _image_revision(image_ref) != revision:
        raise HostError("image_revision_mismatch")
    return image_ref, expected_image_digest, _image_schema(image_ref)


def _runtime_file(image_ref: str) -> None:
    encoded = f"STOCK_PROBS_IMAGE={image_ref}\n".encode()
    _safe_mode(RUNTIME_ENV_FILE.parent, 0o750)
    temporary = RUNTIME_ENV_FILE.with_name(f".{RUNTIME_ENV_FILE.name}.{secrets.token_hex(8)}.tmp")
    descriptor = os.open(
        temporary,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
        0o640,
    )
    try:
        _write_all(descriptor, encoded)
        os.fsync(descriptor)
    except OSError:
        temporary.unlink(missing_ok=True)
        raise
    finally:
        os.close(descriptor)
    try:
        os.replace(temporary, RUNTIME_ENV_FILE)
    except OSError as exc:
        temporary.unlink(missing_ok=True)
        raise HostError("runtime_write_failed") from exc


def _compose_prefix() -> list[str]:
    return [
        "docker",
        "compose",
        "--ansi",
        "never",
        "--project-name",
        PROJECT_NAME,
        "--env-file",
        str(APP_ENV_FILE),
        "--env-file",
        str(RUNTIME_ENV_FILE),
        "--file",
        str(COMPOSE_FILE),
    ]


def _compose(*arguments: str, timeout: float = 300.0) -> str:
    return _run([*_compose_prefix(), *arguments], timeout=timeout).stdout.strip()


def _compose_optional(*arguments: str, timeout: float = 300.0) -> bool:
    try:
        _compose(*arguments, timeout=timeout)
    except HostError:
        return False
    return True


def _compose_up(record: dict[str, Any], *, timeout: float = 180.0) -> str:
    """Start a verified image without allowing Compose to pull a mutable fallback tag."""

    arguments = ["up", "--detach", "--no-build"]
    if _is_release_record(record):
        arguments.extend(("--pull", "never"))
    arguments.append("app")
    return _compose(*arguments, timeout=timeout)


def _is_release_record(record: dict[str, Any]) -> bool:
    return record.get("transport") == GITHUB_RELEASE_TRANSPORT


def _assert_image_record(record: dict[str, Any]) -> None:
    """Validate the immutable image identity stored in a plan or release record."""

    revision = record.get("revision")
    image_digest = record.get("image_digest")
    image_ref = record.get("image_ref")
    if not isinstance(revision, str) or REVISION_PATTERN.fullmatch(revision) is None:
        raise HostError("release_invalid")
    if not isinstance(image_digest, str) or DIGEST_PATTERN.fullmatch(image_digest) is None:
        raise HostError("release_invalid")
    if _is_release_record(record):
        if (
            record.get("archive_sha256") != image_digest
            or not isinstance(record.get("image_id"), str)
            or IMAGE_ID_PATTERN.fullmatch(record["image_id"]) is None
            or image_ref != _local_image_ref(revision)
            or record.get("platform") != "linux/amd64"
            or type(record.get("archive_size")) is not int
            or not 1 <= record["archive_size"] <= MAX_RELEASE_ARCHIVE_BYTES
        ):
            raise HostError("release_invalid")
        return
    if image_ref != _image_ref(revision, image_digest):
        raise HostError("release_invalid")


def _assert_loaded_image(record: dict[str, Any]) -> None:
    """Bind Compose to the image identity that was verified during planning."""

    if _is_release_record(record):
        if _image_id(record["image_ref"]) != record["image_id"]:
            raise HostError("image_id_mismatch")
        if _image_revision(record["image_ref"]) != record["revision"]:
            raise HostError("image_revision_mismatch")
        _image_platform(record["image_ref"])
        return
    if _image_digest(record["image_ref"]) != record["image_digest"]:
        raise HostError("image_digest_mismatch")


def _health_check() -> dict[str, Any]:
    for _ in range(HEALTH_ATTEMPTS):
        try:
            result = _run(
                ["curl", "--fail", "--silent", "--show-error", "--max-time", "3", HEALTH_URL],
                timeout=5,
            )
            value = json.loads(result.stdout)
            if isinstance(value, dict) and value.get("status") == "ready":
                schema = value.get("schema_version")
                if type(schema) is int and 1 <= schema <= 100:
                    return {"status": "ready", "schema_version": schema}
        except (HostError, json.JSONDecodeError, TypeError, ValueError):
            pass
        time.sleep(HEALTH_DELAY_SECONDS)
    raise HostError("readiness_failed")


def _load_plan(plan_id: str) -> dict[str, Any]:
    path = PLAN_ROOT / f"{plan_id}.json"
    record = _read_json(path)
    if record is None:
        raise HostError("plan_not_found")
    if (
        record.get("plan_id") != plan_id
        or not isinstance(record.get("revision"), str)
        or REVISION_PATTERN.fullmatch(record["revision"]) is None
        or not isinstance(record.get("image_digest"), str)
        or DIGEST_PATTERN.fullmatch(record["image_digest"]) is None
        or type(record.get("schema_version")) is not int
        or not 1 <= record["schema_version"] <= 100
        or not isinstance(record.get("compose_digest"), str)
        or DIGEST_PATTERN.fullmatch(record["compose_digest"]) is None
    ):
        raise HostError("plan_invalid")
    try:
        _assert_image_record(record)
    except HostError as exc:
        raise HostError("plan_invalid") from exc
    return record


def _state_summary() -> dict[str, Any]:
    current = _read_json(CURRENT_RECORD)
    return {
        "status": "ok",
        "service": PROJECT_NAME,
        "current": current,
        "failed": _read_json(FAILED_RECORD),
        "loopback_only": True,
    }


def _inspect() -> dict[str, Any]:
    _ensure_layout()
    current = _read_json(CURRENT_RECORD)
    health: dict[str, Any] = {"status": "unknown"}
    if current is not None:
        try:
            health = _health_check()
        except HostError:
            health = {"status": "unavailable"}
    return {
        "status": "ok",
        "current": current,
        "failed": _read_json(FAILED_RECORD),
        "health": health,
        "loopback_only": True,
    }


def _plan_deploy(
    revision: str, expected_image_digest: str, expected_image_id: str | None = None
) -> dict[str, Any]:
    with _exclusive_lock():
        _ensure_layout()
        _ensure_source()
        _assert_main_revision(revision)
        _checkout_revision(revision)
        _assert_compose_revision()
        compose_digest = _compose_digest()
        if expected_image_id is None:
            image_ref, image_digest, schema_version = _pull_image(revision, expected_image_digest)
            image_record: dict[str, Any] = {}
        else:
            (
                image_ref,
                image_digest,
                image_id,
                platform,
                schema_version,
                archive_size,
            ) = _load_release_archive(revision, expected_image_digest, expected_image_id)
            image_record = {
                "transport": GITHUB_RELEASE_TRANSPORT,
                "archive_sha256": image_digest,
                "image_id": image_id,
                "platform": platform,
                "archive_size": archive_size,
            }
        plan_id = secrets.token_hex(16)
        record = {
            "plan_id": plan_id,
            "revision": revision,
            "image_ref": image_ref,
            "image_digest": image_digest,
            "schema_version": schema_version,
            "compose_digest": compose_digest,
            "created_at": _utc_now(),
            "status": "prepared",
        }
        record.update(image_record)
        _write_json(PLAN_ROOT / f"{plan_id}.json", record)
        _audit(
            "plan_deploy",
            "prepared",
            revision=revision,
            plan_id=plan_id,
            image_digest=image_digest,
            compose_digest=compose_digest,
            schema_version=schema_version,
        )
        response = {
            "status": "ok",
            "plan_id": plan_id,
            "revision": revision,
            "image_ref": image_ref,
            "image_digest": image_digest,
            "compose_digest": compose_digest,
        }
        if image_record:
            response.update(image_record)
        return response


def _backup_name(revision: str) -> str:
    return f"pre-deploy-{revision[:16]}-{secrets.token_hex(4)}.spbackup"


def _database_present(image_ref: str) -> bool:
    """Check an unowned volume without importing the application or running migrations."""

    _runtime_file(image_ref)
    value = _compose(
        "run",
        "--rm",
        "--no-deps",
        "-T",
        "app",
        "python",
        "-c",
        (
            "from pathlib import Path; "
            "print('1' if Path('/data/stock_probs.sqlite3').is_file() else '0')"
        ),
        timeout=60,
    )
    if value == "0":
        return False
    if value == "1":
        return True
    raise HostError("database_presence_unavailable")


def _database_schema(image_ref: str) -> int:
    """Read the actual volume schema without importing the app or running migrations."""

    _runtime_file(image_ref)
    value = _compose(
        "run",
        "--rm",
        "--no-deps",
        "-T",
        "app",
        "python",
        "-c",
        (
            "import sqlite3; "
            "c=sqlite3.connect('file:/data/stock_probs.sqlite3?mode=ro', uri=True); "
            "c.execute('PRAGMA query_only=ON'); "
            "r=c.execute('SELECT MAX(version) FROM schema_migrations').fetchone(); "
            "print(r[0] if r and r[0] is not None else 0)"
        ),
        timeout=60,
    )
    if not value.isdigit() or not 1 <= int(value) <= 100:
        raise HostError("database_schema_unavailable")
    return int(value)


def _verified_backup(image_ref: str, revision: str) -> dict[str, Any]:
    name = _backup_name(revision)
    _runtime_file(image_ref)
    output = _compose(
        "run",
        "--rm",
        "--no-deps",
        "-T",
        "app",
        "stock-probs",
        "backup",
        "--name",
        name,
        timeout=180,
    )
    # The command is intentionally synchronous so the signed archive is complete before the
    # helper performs any migration or starts the new application image.
    try:
        value = json.loads(output)
    except json.JSONDecodeError as exc:
        raise HostError("backup_unverified") from exc
    if not isinstance(value, dict) or value.get("name") != name:
        raise HostError("backup_unverified")
    # Verify through the app's signed archive reader before allowing migration or promotion.
    verification = _compose(
        "run",
        "--rm",
        "--no-deps",
        "-T",
        "app",
        "stock-probs",
        "restore",
        name,
        timeout=180,
    )
    try:
        verified = json.loads(verification)
    except json.JSONDecodeError as exc:
        raise HostError("backup_unverified") from exc
    if not isinstance(verified, dict) or verified.get("verified") is not True:
        raise HostError("backup_unverified")
    _audit("backup", "verified", revision=revision, backup_name=name)
    return {"name": name, "verified": True}


def _verified_first_release_backup(
    image_ref: str, revision: str, source_schema: int, target_schema: int
) -> dict[str, Any]:
    """Migrate a transferred database only after the image reports a verified old snapshot."""

    _runtime_file(image_ref)
    output = _compose(
        "run",
        "--rm",
        "--no-deps",
        "-T",
        "app",
        "stock-probs",
        "migrate",
        timeout=300,
    )
    try:
        result = json.loads(output)
    except json.JSONDecodeError as exc:
        raise HostError("pre_migration_backup_unverified") from exc
    receipt = result.get("pre_migration_backup") if isinstance(result, dict) else None
    if (
        not isinstance(result, dict)
        or result.get("status") != "migrated"
        or not isinstance(receipt, dict)
        or receipt.get("trigger") != "pre_migration"
        or receipt.get("verified") is not True
        or receipt.get("schema_version") != source_schema
        or type(receipt.get("name")) is not str
        or BACKUP_NAME_PATTERN.fullmatch(receipt["name"]) is None
        or type(receipt.get("sha256")) is not str
        or DIGEST_PATTERN.fullmatch(receipt["sha256"]) is None
    ):
        raise HostError("pre_migration_backup_unverified")
    _audit(
        "backup",
        "verified",
        revision=revision,
        backup_name=receipt["name"],
        schema_version=source_schema,
    )
    # The migration command owns the pre-migration snapshot; the normal backup path verifies a
    # current-schema artifact before the helper allows the release to continue.
    backup = _verified_backup(image_ref, revision)
    if backup.get("verified") is not True or type(backup.get("name")) is not str:
        raise HostError("backup_unverified")
    return {
        "name": backup["name"],
        "verified": True,
        "pre_migration_backup": receipt["name"],
        "schema_version": target_schema,
    }


def _write_failed_record(
    record: dict[str, Any],
    previous: dict[str, Any] | None,
    *,
    failure_code: str,
    actual_schema: int | None,
    rollback_attempted: bool,
    rollback_succeeded: bool,
) -> None:
    """Publish bounded state after a failed promotion, including migration outcome."""

    migrated = actual_schema is not None and (
        previous is None or actual_schema != previous.get("schema_version")
    )
    failed: dict[str, Any] = {
        "status": "failed_migrated" if migrated else "failed",
        "revision": record["revision"],
        "image_ref": record["image_ref"],
        "image_digest": record["image_digest"],
        "schema_version": record["schema_version"],
        "actual_schema_version": actual_schema,
        "failure_code": failure_code,
        "rollback_attempted": rollback_attempted,
        "rollback_succeeded": rollback_succeeded,
        "failed_at": _utc_now(),
    }
    for key in ("transport", "archive_sha256", "image_id", "platform", "archive_size"):
        if key in record:
            failed[key] = record[key]
    if previous is not None:
        failed["previous_revision"] = previous.get("revision")
        failed["previous_schema_version"] = previous.get("schema_version")
    _write_json(FAILED_RECORD, failed)
    _audit(
        "deploy",
        "failed",
        revision=record["revision"],
        image_digest=record["image_digest"],
        schema_version=actual_schema,
    )


def _apply_release(record: dict[str, Any]) -> dict[str, Any]:
    revision = record["revision"]
    image_ref = record["image_ref"]
    image_digest = record["image_digest"]
    schema_version = record["schema_version"]
    current = _read_json(CURRENT_RECORD)
    _assert_loaded_image(record)
    if (
        current is not None
        and current.get("revision") == revision
        and current.get("image_digest") == image_digest
    ):
        return {"status": "ok", "result": "already_applied", "revision": revision}
    previous = current
    if current is not None:
        # Validate the persisted active image before probing its schema.  A local release tag can
        # drift after an image load; schema or Compose work must never run against that tag until
        # its recorded immutable image identity has been re-established.
        _assert_image_record(current)
        _assert_loaded_image(current)
        try:
            active_health = _health_check()
        except HostError as exc:
            raise HostError("active_release_unready") from exc
        if _image_schema(current["image_ref"]) != active_health["schema_version"]:
            raise HostError("active_release_mismatch")
        if schema_version < active_health["schema_version"]:
            raise HostError("schema_incompatible")
    try:
        if current is None:
            if not _database_present(image_ref):
                backup: dict[str, Any] = {"name": None, "verified": True}
            else:
                source_schema = _database_schema(image_ref)
                if source_schema > schema_version:
                    raise HostError("schema_incompatible")
                if source_schema < schema_version:
                    backup = _verified_first_release_backup(
                        image_ref, revision, source_schema, schema_version
                    )
                else:
                    backup = _verified_backup(image_ref, revision)
        else:
            # The old image performs the snapshot and verification.  Its CLI cannot apply the
            # new migration, so the pre-migration boundary remains meaningful.
            backup = _verified_backup(current["image_ref"], revision)
        _runtime_file(image_ref)
        if current is not None:
            _compose("stop", "app", timeout=60)
        _compose("run", "--rm", "--no-deps", "-T", "app", "stock-probs", "migrate", timeout=300)
        _compose_up(record, timeout=180)
        health = _health_check()
        if health.get("schema_version") != schema_version:
            raise HostError("readiness_schema_mismatch")
    except HostError as error:
        # Stop the failed candidate before inspecting the volume.  A migration can commit before
        # readiness fails, so the record on disk cannot establish the schema that old code sees.
        _compose_optional("stop", "app", timeout=60)
        actual_schema: int | None = None
        with suppress(HostError):
            actual_schema = _database_schema(image_ref)

        rollback_attempted = False
        rollback_succeeded = False
        # A code-only rollback is safe only when the volume still has the previous schema.  If
        # migration advanced it, leave the service stopped for operator recovery.
        if (
            previous is not None
            and actual_schema == previous.get("schema_version")
            and previous.get("schema_version") == schema_version
            and isinstance(previous.get("image_ref"), str)
            and isinstance(previous.get("image_digest"), str)
        ):
            try:
                _assert_record_compose_digest(previous)
            except HostError:
                pass
            else:
                rollback_attempted = True
                try:
                    _runtime_file(previous["image_ref"])
                    try:
                        _assert_loaded_image(previous)
                    except HostError:
                        pass
                    else:
                        _compose_up(previous, timeout=180)
                        rollback_health = _health_check()
                        rollback_succeeded = rollback_health.get("schema_version") == previous.get(
                            "schema_version"
                        )
                except HostError:
                    rollback_succeeded = False
                if not rollback_succeeded:
                    _compose_optional("stop", "app", timeout=60)
        _write_failed_record(
            record,
            previous,
            failure_code=error.code,
            actual_schema=actual_schema,
            rollback_attempted=rollback_attempted,
            rollback_succeeded=rollback_succeeded,
        )
        raise
    applied = {
        "revision": revision,
        "image_ref": image_ref,
        "image_digest": image_digest,
        "schema_version": schema_version,
        "backup_name": backup["name"],
        "deployed_at": _utc_now(),
    }
    for key in ("transport", "archive_sha256", "image_id", "platform", "archive_size"):
        if key in record:
            applied[key] = record[key]
    if isinstance(record.get("compose_digest"), str):
        applied["compose_digest"] = record["compose_digest"]
    _write_json(CURRENT_RECORD, applied)
    _write_json(RELEASE_ROOT / f"{revision}.json", applied)
    _audit(
        "deploy",
        "applied",
        revision=revision,
        image_digest=image_digest,
        compose_digest=record.get("compose_digest"),
        schema_version=schema_version,
        backup_name=backup["name"],
    )
    return {"status": "ok", "result": "deployed", "revision": revision, "health": health}


def _deploy(
    plan_id: str, revision: str, image_digest: str, image_id: str | None = None
) -> dict[str, Any]:
    with _exclusive_lock():
        _ensure_layout()
        plan = _load_plan(plan_id)
        if (
            plan["revision"] != revision
            or plan["image_digest"] != image_digest
            or (_is_release_record(plan) and plan.get("image_id") != image_id)
        ):
            raise HostError("plan_mismatch")
        # Bind promotion to the exact Compose bytes reviewed during planning.  SOURCE_ROOT may
        # have been checked out for another plan since then; it is not the deploy authority.
        if _compose_digest() != plan["compose_digest"]:
            raise HostError("compose_revision_mismatch")
        result = _apply_release(plan)
        result.update(
            {
                "plan_id": plan_id,
                "revision": revision,
                "image_digest": image_digest,
                "schema_version": plan["schema_version"],
            }
        )
        if _is_release_record(plan):
            result.update(
                {
                    "transport": GITHUB_RELEASE_TRANSPORT,
                    "archive_sha256": plan["archive_sha256"],
                    "image_id": plan["image_id"],
                    "platform": plan["platform"],
                    "archive_size": plan["archive_size"],
                }
            )
        return result


def _rollback(revision: str, image_id: str | None = None) -> dict[str, Any]:
    with _exclusive_lock():
        _ensure_layout()
        record = _read_json(RELEASE_ROOT / f"{revision}.json")
        if record is None:
            raise HostError("release_not_found")
        if (
            record.get("revision") != revision
            or type(record.get("schema_version")) is not int
            or not 1 <= record["schema_version"] <= 100
            or not isinstance(record.get("compose_digest"), str)
            or DIGEST_PATTERN.fullmatch(record["compose_digest"]) is None
        ):
            raise HostError("release_invalid")
        _assert_image_record(record)
        if _is_release_record(record):
            if image_id != record["image_id"]:
                raise HostError("rollback_identity_mismatch")
        elif image_id is not None:
            raise HostError("rollback_identity_invalid")
        _assert_record_compose_digest(record)
        # Check the immutable image identity before opening the database or starting Compose.  The
        # local release tag is only a convenience alias and may have been replaced since staging.
        _assert_loaded_image(record)
        actual_schema = _database_schema(record["image_ref"])
        if actual_schema != record.get("schema_version"):
            raise HostError("rollback_schema_incompatible")
        _runtime_file(record["image_ref"])
        _compose_up(record, timeout=180)
        health = _health_check()
        if health.get("schema_version") != actual_schema:
            _compose_optional("stop", "app", timeout=60)
            raise HostError("rollback_schema_incompatible")
        _write_json(CURRENT_RECORD, record)
        _audit(
            "rollback",
            "applied",
            revision=revision,
            image_digest=record["image_digest"],
            compose_digest=record["compose_digest"],
            schema_version=record.get("schema_version"),
        )
        response = {
            "status": "ok",
            "result": "rolled_back",
            "revision": revision,
            "image_digest": record["image_digest"],
            "schema_version": record["schema_version"],
            "health": health,
        }
        if _is_release_record(record):
            response.update(
                {
                    "transport": GITHUB_RELEASE_TRANSPORT,
                    "archive_sha256": record["archive_sha256"],
                    "image_id": record["image_id"],
                    "platform": record["platform"],
                    "archive_size": record["archive_size"],
                }
            )
        return response


def _parse_request(raw: bytes) -> tuple[str, dict[str, object]]:
    if len(raw) > REQUEST_LIMIT:
        raise HostError("request_too_large")
    try:
        request = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HostError("request_invalid") from exc
    if not isinstance(request, dict) or set(request) != {"operation", "payload"}:
        raise HostError("request_invalid")
    operation = request["operation"]
    payload = request["payload"]
    if not isinstance(operation, str) or operation not in _ALLOWED_OPERATIONS:
        raise HostError("operation_invalid")
    if not isinstance(payload, dict):
        raise HostError("payload_invalid")
    allowed_keys = {_EXPECTED_PAYLOAD_KEYS[operation]}
    if operation in _LEGACY_PAYLOAD_KEYS:
        allowed_keys.add(_LEGACY_PAYLOAD_KEYS[operation])
    if frozenset(payload) not in allowed_keys:
        raise HostError("payload_invalid")
    return operation, payload


def _dispatch(operation: str, payload: dict[str, object]) -> dict[str, Any]:
    if operation == "inspect":
        return _inspect()
    if operation == "status":
        _ensure_layout()
        return _state_summary()
    if operation == "plan_deploy":
        if "archive_sha256" in payload:
            return _plan_deploy(
                _validate_revision(payload["revision"]),
                _validate_digest(payload["archive_sha256"]),
                _validate_image_id(payload["image_id"]),
            )
        return _plan_deploy(
            _validate_revision(payload["revision"]),
            _validate_digest(payload["expected_image_digest"]),
        )
    if operation == "deploy":
        if "archive_sha256" in payload:
            return _deploy(
                _validate_plan_id(payload["plan_id"]),
                _validate_revision(payload["revision"]),
                _validate_digest(payload["archive_sha256"]),
                _validate_image_id(payload["image_id"]),
            )
        return _deploy(
            _validate_plan_id(payload["plan_id"]),
            _validate_revision(payload["revision"]),
            _validate_digest(payload["image_digest"]),
        )
    if "image_id" in payload:
        return _rollback(
            _validate_revision(payload["revision"]),
            _validate_image_id(payload["image_id"]),
        )
    return _rollback(_validate_revision(payload["revision"]))


def main() -> int:
    """Read one request and emit one bounded response for the SSH forced command."""

    operation = "request"
    try:
        operation, payload = _parse_request(sys.stdin.buffer.read(REQUEST_LIMIT + 1))
        response = _dispatch(operation, payload)
    except HostError as exc:
        _audit(operation, "error")
        response = {"status": "error", "code": exc.code}
    except (OSError, ValueError, TypeError) as exc:
        _audit("unknown", "error")
        response = {"status": "error", "code": "host_failure"}
        del exc
    encoded = json.dumps(response, sort_keys=True, separators=(",", ":")).encode()
    if len(encoded) > RESPONSE_LIMIT:
        encoded = b'{"status":"error","code":"response_too_large"}'
    sys.stdout.buffer.write(encoded + b"\n")
    sys.stdout.buffer.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
