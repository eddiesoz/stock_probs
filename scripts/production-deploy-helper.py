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
CONTAINER_ID_PATTERN = re.compile(r"^[0-9a-f]{64}$")
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
GITHUB_RELEASE_RECOVERY_PREFIX = "signal-ledger-recovery-"
GITHUB_RELEASE_PAIR_PREFIX = "signal-ledger-pair-"
GITHUB_RELEASE_TRANSPORT = "github_release"
LOCAL_IMAGE_REPOSITORY = "signal-ledger"
PAIR_MANIFEST_VERSION = 1
PAIR_REPOSITORY = "eddiesoz/stock_probs"
PAIR_BASE_REVISION = "da2764e8477698fa7d686be93a4711e35478e802"
PAIR_MIGRATION_SHA256 = "41e7d0ef5e5267ab50a67666862bf01e4c6cfd8986b6096bd8b92deed70ff31b"
MAX_RELEASE_ARCHIVE_BYTES = 512 * 1024 * 1024
RELEASE_DOWNLOAD_TIMEOUT_SECONDS = 600
HEALTH_URL = "http://127.0.0.1:8000/api/v1/readiness"
HEALTH_ATTEMPTS = 30
HEALTH_DELAY_SECONDS = 1.0
ASSISTANT_MINIMUM_SCHEMA = 13
ASSISTANT_ROLLOUT_MODES = frozenset({"disabled", "owner_canary", "invited"})
ASSISTANT_RUNTIME_STATUS = frozenset({"disabled", "starting", "ready", "unavailable", "stopped"})
MAX_COMPOSE_SNAPSHOT_BYTES = 128 * 1024

_ALLOWED_OPERATIONS = frozenset(
    {"inspect", "plan_deploy", "deploy", "status", "rollback", "set_assistant_rollout"}
)
_EXPECTED_PAYLOAD_KEYS = {
    "inspect": frozenset(),
    "status": frozenset(),
    "plan_deploy": frozenset({"revision", "archive_sha256", "image_id"}),
    "deploy": frozenset({"plan_id", "revision", "archive_sha256", "image_id"}),
    "rollback": frozenset({"revision", "image_id"}),
    "set_assistant_rollout": frozenset({"mode", "revision", "archive_sha256", "image_id"}),
}
_PAIR_PAYLOAD_KEYS = {
    "plan_deploy": frozenset({"revision", "archive_sha256", "image_id", "pair_manifest_sha256"}),
    "deploy": frozenset(
        {"plan_id", "revision", "archive_sha256", "image_id", "pair_manifest_sha256"}
    ),
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


def _release_asset_name(revision: str, role: str) -> str:
    """Derive one of the three immutable pair assets; callers never supply a path or URL."""

    _validate_revision(revision)
    if role == "candidate":
        return _release_archive_name(revision)
    if role == "recovery":
        return f"{GITHUB_RELEASE_RECOVERY_PREFIX}{revision}{GITHUB_RELEASE_ARCHIVE_SUFFIX}"
    if role == "pair":
        return f"{GITHUB_RELEASE_PAIR_PREFIX}{revision}.json"
    raise HostError("release_asset_invalid")


def _release_asset_url(revision: str, role: str) -> str:
    """Build a fixed GitHub Release URL for a candidate, recovery image, or pair manifest."""

    name = _release_asset_name(revision, role)
    tag = f"{GITHUB_RELEASE_TAG_PREFIX}{revision}"
    return f"https://github.com/{GITHUB_RELEASE_REPOSITORY}/releases/download/{tag}/{name}"


def _release_archive_name(revision: str) -> str:
    """Return the immutable asset filename derived from a reviewed revision."""

    _validate_revision(revision)
    return f"{GITHUB_RELEASE_ARCHIVE_PREFIX}{revision}{GITHUB_RELEASE_ARCHIVE_SUFFIX}"


def _local_image_ref(revision: str) -> str:
    """Return the deterministic local tag used after an archive is verified and loaded."""

    _validate_revision(revision)
    return f"{LOCAL_IMAGE_REPOSITORY}:sha-{revision}"


def _local_recovery_image_ref(revision: str) -> str:
    """Return the fixed local tag for the forward-compatible app-only recovery image."""

    _validate_revision(revision)
    return f"{LOCAL_IMAGE_REPOSITORY}:recovery-sha-{revision}"


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
        "image_id",
        "release_role",
        "pair_manifest_sha256",
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


def _compose_snapshot_path(revision: str) -> Path:
    """Return the only state path used to retain this reviewed release's Compose file."""

    return RELEASE_ROOT / f"{_validate_revision(revision)}.compose.yaml"


def _read_compose_snapshot(path: Path) -> bytes:
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except OSError as exc:
        raise HostError("compose_snapshot_unavailable") from exc
    try:
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or stat.S_IMODE(metadata.st_mode) != 0o600
            or metadata.st_size > MAX_COMPOSE_SNAPSHOT_BYTES
        ):
            raise HostError("compose_snapshot_unsafe")
        content = os.read(descriptor, MAX_COMPOSE_SNAPSHOT_BYTES + 1)
    except OSError as exc:
        raise HostError("compose_snapshot_unavailable") from exc
    finally:
        os.close(descriptor)
    if len(content) > MAX_COMPOSE_SNAPSHOT_BYTES:
        raise HostError("compose_snapshot_unsafe")
    return content


def _write_compose_snapshot(revision: str, content: bytes, expected_digest: str) -> Path:
    """Persist one bounded Compose file only when its reviewed digest matches the release."""

    revision = _validate_revision(revision)
    if (
        not isinstance(content, bytes)
        or not 0 < len(content) <= MAX_COMPOSE_SNAPSHOT_BYTES
        or not isinstance(expected_digest, str)
        or DIGEST_PATTERN.fullmatch(expected_digest) is None
        or hashlib.sha256(content).hexdigest() != expected_digest
    ):
        raise HostError("compose_snapshot_invalid")
    path = _compose_snapshot_path(revision)
    existing: os.stat_result | None = None
    try:
        existing = path.lstat()
    except FileNotFoundError:
        existing = None
    except OSError as exc:
        raise HostError("compose_snapshot_unavailable") from exc
    if existing is not None:
        existing = _read_compose_snapshot(path)
        if hashlib.sha256(existing).hexdigest() != expected_digest or existing != content:
            raise HostError("compose_snapshot_mismatch")
        return path
    _safe_mode(path.parent, 0o750)
    temporary = path.with_name(f".{path.name}.{secrets.token_hex(8)}.tmp")
    descriptor = os.open(
        temporary,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
        0o600,
    )
    try:
        _write_all(descriptor, content)
        os.fsync(descriptor)
    except OSError as exc:
        temporary.unlink(missing_ok=True)
        raise HostError("compose_snapshot_write_failed") from exc
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
        raise HostError("compose_snapshot_write_failed") from exc
    return path


def _ensure_compose_snapshot(record: dict[str, Any]) -> Path:
    """Verify or recreate a release snapshot from its fixed, validated Git revision."""

    revision = _validate_revision(record.get("revision"))
    expected = record.get("compose_digest")
    if not isinstance(expected, str) or DIGEST_PATTERN.fullmatch(expected) is None:
        raise HostError("compose_revision_mismatch")
    path = _compose_snapshot_path(revision)
    try:
        content = _read_compose_snapshot(path)
    except HostError as exc:
        if exc.code != "compose_snapshot_unavailable":
            raise
        _ensure_source()
        try:
            _git("cat-file", "-e", f"{revision}^{{commit}}")
            content = _run(
                ["git", "-C", str(SOURCE_ROOT), "show", f"{revision}:compose.production.yaml"],
                timeout=30,
            ).stdout.encode()
        except HostError as source_error:
            raise HostError("compose_snapshot_unavailable") from source_error
        path = _write_compose_snapshot(revision, content, expected)
    if hashlib.sha256(content).hexdigest() != expected:
        raise HostError("compose_revision_mismatch")
    return path


def _assert_record_compose_digest(record: dict[str, Any]) -> Path:
    """Verify the exact per-release Compose bytes used by safe code-only recovery."""

    expected = record.get("compose_digest")
    if not isinstance(expected, str) or DIGEST_PATTERN.fullmatch(expected) is None:
        raise HostError("compose_revision_mismatch")
    snapshot = _ensure_compose_snapshot(record)
    if hashlib.sha256(_read_compose_snapshot(snapshot)).hexdigest() != expected:
        raise HostError("compose_revision_mismatch")
    return snapshot


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

    return _download_release_asset(revision, "candidate")


def _download_release_asset(revision: str, role: str) -> Path:
    """Download exactly one revision-derived immutable release asset."""

    _safe_mode(RELEASE_ROOT, 0o750)
    _release_asset_name(revision, role)
    asset_limit = 65_536 if role == "pair" else MAX_RELEASE_ARCHIVE_BYTES
    suffix = ".json" if role == "pair" else ".tar.gz"
    temporary = RELEASE_ROOT / f".{role}-{revision}-{secrets.token_hex(8)}{suffix}"
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
                str(asset_limit),
                "--output",
                str(temporary),
                _release_asset_url(revision, role),
            ],
            timeout=RELEASE_DOWNLOAD_TIMEOUT_SECONDS + 30,
        )
        metadata = temporary.lstat()
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
            raise HostError("release_archive_unsafe")
        if metadata.st_size <= 0 or metadata.st_size > asset_limit:
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


def _release_pair_source_facts() -> dict[str, Any]:
    """Recompute the fixed source and recovery overlay identities from exact checked-out main."""

    facts: dict[str, Any] = {}
    for mode in ("--source-context-manifest", "--overlay-manifest"):
        try:
            output = _run(
                ["python3", "scripts/rehearse_schema13.py", mode],
                cwd=SOURCE_ROOT,
                timeout=180,
            ).stdout
            value = json.loads(output)
        except (HostError, json.JSONDecodeError, TypeError) as exc:
            raise HostError("release_pair_source_unavailable") from exc
        if not isinstance(value, dict) or value.get("status") != "prepared":
            raise HostError("release_pair_source_invalid")
        facts[mode] = value
    return facts


def _validate_release_pair_manifest(
    manifest: object,
    *,
    revision: str,
    candidate_archive_sha256: str,
    candidate_archive_size: int,
    candidate_image_id: str,
    facts: dict[str, Any],
) -> dict[str, Any]:
    """Accept only the fixed schema-12→13 candidate/recovery pair for this main revision."""

    expected_root = {
        "format_version",
        "repository",
        "revision",
        "source_context_sha256",
        "migration",
        "candidate",
        "recovery",
    }
    if not isinstance(manifest, dict) or set(manifest) != expected_root:
        raise HostError("release_pair_invalid")
    source = facts.get("--source-context-manifest")
    overlay_manifest = facts.get("--overlay-manifest")
    if not isinstance(source, dict) or not isinstance(overlay_manifest, dict):
        raise HostError("release_pair_source_invalid")
    baseline = overlay_manifest.get("observed_deployment_baseline")
    overlay = overlay_manifest.get("recovery_overlay")
    migration_files = overlay.get("files") if isinstance(overlay, dict) else None
    migration = manifest.get("migration")
    candidate = manifest.get("candidate")
    recovery = manifest.get("recovery")
    if not isinstance(recovery, dict):
        raise HostError("release_pair_recovery_invalid")
    if (
        type(manifest.get("format_version")) is not int
        or manifest["format_version"] != PAIR_MANIFEST_VERSION
        or manifest.get("repository") != PAIR_REPOSITORY
        or manifest.get("revision") != revision
        or manifest.get("source_context_sha256") != source.get("source_context_sha256")
        or not isinstance(source.get("source_context_sha256"), str)
        or DIGEST_PATTERN.fullmatch(source["source_context_sha256"]) is None
        or not isinstance(baseline, dict)
        or baseline.get("source_revision") != PAIR_BASE_REVISION
        or not isinstance(overlay, dict)
        or overlay.get("base_revision") != PAIR_BASE_REVISION
        or overlay_manifest.get("base_source_context_sha256")
        != recovery.get("base_source_context_sha256")
    ):
        raise HostError("release_pair_invalid")
    if (
        not isinstance(migration, dict)
        or set(migration) != {"from_schema", "to_schema", "sha256"}
        or type(migration.get("from_schema")) is not int
        or migration.get("from_schema") != 12
        or type(migration.get("to_schema")) is not int
        or migration.get("to_schema") != ASSISTANT_MINIMUM_SCHEMA
        or migration.get("sha256") != PAIR_MIGRATION_SHA256
        or not isinstance(migration_files, dict)
        or migration_files.get("src/stock_probs/migrations/013_assistant_conversations.sql")
        != PAIR_MIGRATION_SHA256
    ):
        raise HostError("release_pair_migration_invalid")
    if (
        not isinstance(candidate, dict)
        or set(candidate)
        != {
            "asset",
            "archive_sha256",
            "archive_size",
            "image_id",
            "platform",
            "revision",
            "schema_version",
            "source_context_sha256",
        }
        or candidate.get("asset") != _release_asset_name(revision, "candidate")
        or candidate.get("archive_sha256") != candidate_archive_sha256
        or type(candidate.get("archive_size")) is not int
        or not 1 <= candidate["archive_size"] <= MAX_RELEASE_ARCHIVE_BYTES
        or candidate.get("archive_size") != candidate_archive_size
        or candidate.get("image_id") != candidate_image_id
        or candidate.get("platform") != "linux/amd64"
        or candidate.get("revision") != revision
        or type(candidate.get("schema_version")) is not int
        or candidate.get("schema_version") != ASSISTANT_MINIMUM_SCHEMA
        or candidate.get("source_context_sha256") != source.get("source_context_sha256")
    ):
        raise HostError("release_pair_candidate_invalid")
    expected_recovery = {
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
    if (
        not isinstance(recovery, dict)
        or set(recovery) != expected_recovery
        or recovery.get("asset") != _release_asset_name(revision, "recovery")
        or recovery.get("platform") != "linux/amd64"
        or recovery.get("revision") != revision
        or type(recovery.get("schema_version")) is not int
        or recovery.get("schema_version") != ASSISTANT_MINIMUM_SCHEMA
        or recovery.get("assistant_enabled") is not False
        or type(recovery.get("archive_size")) is not int
        or not 1 <= recovery["archive_size"] <= MAX_RELEASE_ARCHIVE_BYTES
        or recovery.get("base_revision") != PAIR_BASE_REVISION
        or recovery.get("base_image_id") != baseline.get("image_id")
        or recovery.get("base_archive_sha256") != baseline.get("release_archive_sha256")
        or recovery.get("base_source_context_sha256")
        != overlay_manifest.get("base_source_context_sha256")
        or recovery.get("overlay_sha256") != overlay.get("overlay_sha256")
        or recovery.get("source_context_sha256") != overlay_manifest.get("recovery_context_sha256")
        or recovery.get("migration_sha256") != PAIR_MIGRATION_SHA256
    ):
        raise HostError("release_pair_recovery_invalid")
    for digest in (
        recovery.get("archive_sha256"),
        recovery.get("base_archive_sha256"),
        recovery.get("base_source_context_sha256"),
        recovery.get("overlay_sha256"),
        recovery.get("source_context_sha256"),
        recovery.get("migration_sha256"),
    ):
        if not isinstance(digest, str) or DIGEST_PATTERN.fullmatch(digest) is None:
            raise HostError("release_pair_recovery_invalid")
    if (
        not isinstance(recovery.get("image_id"), str)
        or IMAGE_ID_PATTERN.fullmatch(recovery["image_id"]) is None
    ):
        raise HostError("release_pair_recovery_invalid")
    return manifest


def _load_release_pair(
    revision: str,
    expected_manifest_sha256: str,
    expected_candidate_archive_sha256: str,
    expected_candidate_image_id: str,
    *,
    candidate_archive_size: int,
) -> dict[str, Any]:
    """Verify the manifest, current source context, migration and recovery image before staging."""

    _validate_revision(revision)
    _validate_digest(expected_manifest_sha256)
    if (
        type(candidate_archive_size) is not int
        or not 1 <= candidate_archive_size <= MAX_RELEASE_ARCHIVE_BYTES
    ):
        raise HostError("candidate_archive_size_invalid")
    pair_path = _download_release_asset(revision, "pair")
    try:
        metadata = pair_path.lstat()
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
            raise HostError("release_pair_unsafe")
        if metadata.st_size <= 0 or metadata.st_size > 65_536:
            raise HostError("release_pair_too_large")
        raw = pair_path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != expected_manifest_sha256:
            raise HostError("release_pair_digest_mismatch")
        try:
            manifest = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise HostError("release_pair_invalid") from exc
        facts = _release_pair_source_facts()
        _validate_release_pair_manifest(
            manifest,
            revision=revision,
            candidate_archive_sha256=expected_candidate_archive_sha256,
            candidate_archive_size=candidate_archive_size,
            candidate_image_id=expected_candidate_image_id,
            facts=facts,
        )
    finally:
        pair_path.unlink(missing_ok=True)

    recovery = manifest["recovery"]
    archive = _download_release_asset(revision, "recovery")
    try:
        archive_sha256, archive_size = _archive_sha256(archive)
        if archive_sha256 != recovery["archive_sha256"] or archive_size != recovery["archive_size"]:
            raise HostError("recovery_archive_digest_mismatch")
        _run(["docker", "load", "--input", str(archive)], timeout=300)
        recovery_image_id = _image_id(recovery["image_id"])
        if recovery_image_id != recovery["image_id"]:
            raise HostError("recovery_image_id_mismatch")
        if _image_revision(recovery_image_id) != revision:
            raise HostError("recovery_image_revision_mismatch")
        platform = _image_platform(recovery_image_id)
        image_ref = _local_recovery_image_ref(revision)
        _run(["docker", "tag", recovery_image_id, image_ref], timeout=30)
        if _image_id(image_ref) != recovery_image_id:
            raise HostError("recovery_image_id_mismatch")
        schema_version = _image_schema(image_ref)
        if (
            schema_version != ASSISTANT_MINIMUM_SCHEMA
            or platform != recovery["platform"]
            or not _image_has_recovery_entrypoint(image_ref)
        ):
            raise HostError("recovery_image_contract_mismatch")
    finally:
        archive.unlink(missing_ok=True)
    return {
        "pair_manifest_sha256": expected_manifest_sha256,
        "source_context_sha256": manifest["source_context_sha256"],
        "migration_sha256": manifest["migration"]["sha256"],
        "recovery_image_ref": image_ref,
        "recovery_image_id": recovery_image_id,
        "recovery_archive_sha256": archive_sha256,
        "recovery_archive_size": archive_size,
        "recovery_platform": platform,
        "recovery_schema_version": schema_version,
        "recovery_base_revision": recovery["base_revision"],
        "recovery_overlay_sha256": recovery["overlay_sha256"],
    }


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


def _runtime_file(image_ref: str, rollout_mode: str = "disabled") -> None:
    """Write only the fixed image and bounded assistant rollout settings."""

    if rollout_mode not in ASSISTANT_ROLLOUT_MODES:
        raise HostError("assistant_rollout_invalid")
    enabled = "0" if rollout_mode == "disabled" else "1"
    encoded = (
        f"STOCK_PROBS_IMAGE={image_ref}\n"
        f"STOCK_PROBS_ASSISTANT_ENABLED={enabled}\n"
        f"STOCK_PROBS_ASSISTANT_ROLLOUT={rollout_mode}\n"
        "STOCK_PROBS_ASSISTANT_CANARY_GITHUB_IDS=\n"
    ).encode()
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


def _compose_prefix(compose_file: Path | None = None) -> list[str]:
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
        str(COMPOSE_FILE if compose_file is None else compose_file),
    ]


def _compose(
    *arguments: str,
    timeout: float = 300.0,
    compose_file: Path | None = None,
) -> str:
    return _run([*_compose_prefix(compose_file), *arguments], timeout=timeout).stdout.strip()


def _compose_optional(
    *arguments: str,
    timeout: float = 300.0,
    compose_file: Path | None = None,
) -> bool:
    try:
        _compose(*arguments, timeout=timeout, compose_file=compose_file)
    except HostError:
        return False
    return True


def _compose_up(
    record: dict[str, Any],
    *,
    timeout: float = 180.0,
    compose_file: Path | None = None,
    force_recreate: bool = False,
) -> str:
    """Start a verified image without allowing Compose to pull a mutable fallback tag."""

    arguments = ["up", "--detach", "--no-build"]
    if force_recreate:
        arguments.append("--force-recreate")
    if _is_release_record(record):
        arguments.extend(("--pull", "never"))
    arguments.append("app")
    return _compose(*arguments, timeout=timeout, compose_file=compose_file)


def _stop_app(compose_file: Path | None = None) -> None:
    """Establish and verify the maintenance boundary before a snapshot or schema migration."""

    _compose("stop", "app", timeout=60, compose_file=compose_file)
    running = _compose(
        "ps",
        "--status",
        "running",
        "--services",
        timeout=30,
        compose_file=compose_file,
    )
    if "app" in running.split():
        raise HostError("maintenance_boundary_failed")


def _app_container_identity(compose_file: Path) -> tuple[str, int]:
    """Return the exact running Compose app container ID and host PID."""

    container_id = _compose(
        "ps", "--status", "running", "--quiet", "app", timeout=20, compose_file=compose_file
    )
    if CONTAINER_ID_PATTERN.fullmatch(container_id) is None:
        raise HostError("assistant_app_identity_unavailable")
    result = _run(
        [
            "docker",
            "inspect",
            "--format",
            "{{.Id}}|{{.State.Pid}}|{{.State.Running}}",
            container_id,
        ],
        timeout=10,
    ).stdout.strip()
    parts = result.split("|")
    if len(parts) != 3 or parts[0] != container_id or parts[2] != "true":
        raise HostError("assistant_app_identity_unavailable")
    if not parts[1].isdecimal() or int(parts[1]) <= 1:
        raise HostError("assistant_app_identity_unavailable")
    return container_id, int(parts[1])


def _request_in_place_assistant_kill(container_id: str) -> None:
    """Run only the packaged no-argument kill client inside the verified app container."""

    if CONTAINER_ID_PATTERN.fullmatch(container_id) is None:
        raise HostError("assistant_app_identity_unavailable")
    result = _run(
        [
            "docker",
            "exec",
            "--user",
            "10001:10001",
            container_id,
            "python",
            "-m",
            "stock_probs.cli",
            "assistant-kill",
        ],
        timeout=30,
    )
    try:
        response = json.loads(result.stdout)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HostError("assistant_kill_unverified") from exc
    if response != {"status": "assistant_disabled"}:
        raise HostError("assistant_kill_unverified")


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
        release_role = record.get("release_role", "candidate")
        expected_ref = (
            _local_recovery_image_ref(revision)
            if release_role == "recovery"
            else _local_image_ref(revision)
        )
        if (
            record.get("archive_sha256") != image_digest
            or not isinstance(record.get("image_id"), str)
            or IMAGE_ID_PATTERN.fullmatch(record["image_id"]) is None
            or release_role not in {"candidate", "recovery"}
            or image_ref != expected_ref
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


def _assert_loaded_recovery_image(record: dict[str, Any]) -> None:
    """Recheck the recovery pair's immutable disabled app image immediately before use."""

    image_ref = record.get("recovery_image_ref")
    image_id = record.get("recovery_image_id")
    if (
        record.get("schema_version") != ASSISTANT_MINIMUM_SCHEMA
        or record.get("recovery_schema_version") != ASSISTANT_MINIMUM_SCHEMA
        or record.get("recovery_platform") != "linux/amd64"
        or record.get("recovery_base_revision") != PAIR_BASE_REVISION
        or not isinstance(record.get("pair_manifest_sha256"), str)
        or DIGEST_PATTERN.fullmatch(record["pair_manifest_sha256"]) is None
        or not isinstance(record.get("recovery_overlay_sha256"), str)
        or DIGEST_PATTERN.fullmatch(record["recovery_overlay_sha256"]) is None
        or not isinstance(image_ref, str)
        or image_ref != _local_recovery_image_ref(record["revision"])
        or not isinstance(image_id, str)
        or IMAGE_ID_PATTERN.fullmatch(image_id) is None
    ):
        raise HostError("recovery_image_record_invalid")
    if (
        _image_id(image_ref) != image_id
        or _image_revision(image_ref) != record["revision"]
        or _image_platform(image_ref) != "linux/amd64"
        or _image_schema(image_ref) != ASSISTANT_MINIMUM_SCHEMA
        or not _image_has_recovery_entrypoint(image_ref)
    ):
        raise HostError("recovery_image_contract_mismatch")


def _image_has_recovery_entrypoint(image_ref: str) -> bool:
    """Require the fixed UID-dropping app-only entrypoint in the recovery image."""

    try:
        output = _run(
            [
                "docker",
                "image",
                "inspect",
                "--format",
                "{{json .Config.Entrypoint}}|{{json .Config.Cmd}}",
                image_ref,
            ],
            timeout=30,
        ).stdout.strip()
        entrypoint_raw, command_raw = output.split("|", 1)
        entrypoint = json.loads(entrypoint_raw)
        command = json.loads(command_raw)
    except (HostError, ValueError, json.JSONDecodeError):
        return False
    return entrypoint == ["python", "-m", "stock_probs.recovery_supervisor"] and command == [
        "serve",
        "--host",
        "0.0.0.0",  # noqa: S104 - Compose exposes only 127.0.0.1 on the host.
        "--port",
        "8000",
        "--allow-non-loopback",
    ]


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
                    health: dict[str, Any] = {"status": "ready", "schema_version": schema}
                    assistant = value.get("assistant")
                    if (
                        isinstance(assistant, dict)
                        and type(assistant.get("enabled")) is bool
                        and isinstance(assistant.get("status"), str)
                        and assistant["status"] in ASSISTANT_RUNTIME_STATUS
                    ):
                        health["assistant"] = {
                            "enabled": assistant["enabled"],
                            "status": assistant["status"],
                        }
                    return health
        except (HostError, json.JSONDecodeError, TypeError, ValueError):
            pass
        time.sleep(HEALTH_DELAY_SECONDS)
    raise HostError("readiness_failed")


def _require_assistant_ready(
    health: dict[str, Any], rollout_mode: str, *, schema_version: int | None = None
) -> None:
    """Keep app health independent while requiring worker readiness for enabled rollout."""

    if rollout_mode == "disabled":
        if schema_version is not None and schema_version < ASSISTANT_MINIMUM_SCHEMA:
            # The exact older image has no assistant projection; it is a valid disabled baseline.
            return
        assistant = health.get("assistant")
        if (
            not isinstance(assistant, dict)
            or assistant.get("enabled") is not False
            or assistant.get("status") != "disabled"
        ):
            raise HostError("assistant_disable_unverified")
        return
    assistant = health.get("assistant")
    if (
        not isinstance(assistant, dict)
        or assistant.get("enabled") is not True
        or assistant.get("status") != "ready"
    ):
        raise HostError("assistant_not_ready")


def _record_rollout_failure(
    current: dict[str, Any],
    *,
    requested_mode: str,
    failure_code: str,
    assistant_disabled_verified: bool,
    app_stopped: bool,
) -> None:
    """Persist sanitized failure plus the verified disable or app-stop containment result."""

    failure = {
        "status": "assistant_rollout_failed",
        "revision": current.get("revision"),
        "image_id": current.get("image_id"),
        "schema_version": current.get("schema_version"),
        "requested_mode": requested_mode,
        "failure_code": failure_code,
        "assistant_rollout_mode": "disabled",
        "assistant_disabled_verified": assistant_disabled_verified,
        "app_stopped": app_stopped,
        "containment_status": (
            "assistant_disabled"
            if assistant_disabled_verified
            else "app_stopped"
            if app_stopped
            else "unverified"
        ),
        "failed_at": _utc_now(),
    }
    _write_json(FAILED_RECORD, failure)
    _audit(
        "assistant_rollout",
        "failed",
        revision=current.get("revision"),
        schema_version=current.get("schema_version"),
    )


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
    revision: str,
    expected_image_digest: str,
    expected_image_id: str | None = None,
    expected_pair_manifest_sha256: str | None = None,
) -> dict[str, Any]:
    with _exclusive_lock():
        _ensure_layout()
        _ensure_source()
        _assert_main_revision(revision)
        current = _read_json(CURRENT_RECORD)
        if current is not None:
            _ensure_compose_snapshot(current)
        _checkout_revision(revision)
        _assert_compose_revision()
        compose_digest = _compose_digest()
        _write_compose_snapshot(revision, COMPOSE_FILE.read_bytes(), compose_digest)
        if expected_image_id is None:
            image_ref, image_digest, schema_version = _pull_image(revision, expected_image_digest)
            if schema_version >= ASSISTANT_MINIMUM_SCHEMA:
                raise HostError("release_pair_required")
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
            if expected_pair_manifest_sha256 is not None:
                pair_record = _load_release_pair(
                    revision,
                    expected_pair_manifest_sha256,
                    image_digest,
                    image_id,
                    candidate_archive_size=archive_size,
                )
                image_record.update(pair_record)
            elif schema_version >= ASSISTANT_MINIMUM_SCHEMA:
                raise HostError("release_pair_required")
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


def _database_present(image_ref: str, *, compose_file: Path | None = None) -> bool:
    """Check an unowned volume without importing the application or running migrations."""

    _runtime_file(image_ref)
    value = _compose(
        "run",
        "--rm",
        "--no-deps",
        "-T",
        "--user",
        "10001:10001",
        "--entrypoint",
        "python",
        "app",
        "-c",
        (
            "from pathlib import Path; "
            "print('1' if Path('/data/stock_probs.sqlite3').is_file() else '0')"
        ),
        timeout=60,
        compose_file=compose_file,
    )
    if value == "0":
        return False
    if value == "1":
        return True
    raise HostError("database_presence_unavailable")


def _database_schema(image_ref: str, *, compose_file: Path | None = None) -> int:
    """Read the actual volume schema without importing the app or running migrations."""

    _runtime_file(image_ref)
    value = _compose(
        "run",
        "--rm",
        "--no-deps",
        "-T",
        "--user",
        "10001:10001",
        "--entrypoint",
        "python",
        "app",
        "-c",
        (
            "import sqlite3; "
            "c=sqlite3.connect('file:/data/stock_probs.sqlite3?mode=ro', uri=True); "
            "c.execute('PRAGMA query_only=ON'); "
            "r=c.execute('SELECT MAX(version) FROM schema_migrations').fetchone(); "
            "print(r[0] if r and r[0] is not None else 0)"
        ),
        timeout=60,
        compose_file=compose_file,
    )
    if not value.isdigit() or not 1 <= int(value) <= 100:
        raise HostError("database_schema_unavailable")
    return int(value)


def _verified_backup(
    image_ref: str, revision: str, *, compose_file: Path | None = None
) -> dict[str, Any]:
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
        compose_file=compose_file,
    )
    # The command is intentionally synchronous so the signed archive is complete before the
    # helper performs any migration or starts the new application image.
    try:
        value = json.loads(output)
    except json.JSONDecodeError as exc:
        raise HostError("backup_unverified") from exc
    expected_schema = _image_schema(image_ref)
    if (
        not isinstance(value, dict)
        or value.get("name") != name
        or type(value.get("schema_version")) is not int
        or value.get("schema_version") != expected_schema
        or not isinstance(value.get("sha256"), str)
        or DIGEST_PATTERN.fullmatch(value["sha256"]) is None
    ):
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
        compose_file=compose_file,
    )
    try:
        verified = json.loads(verification)
    except json.JSONDecodeError as exc:
        raise HostError("backup_unverified") from exc
    if (
        not isinstance(verified, dict)
        or verified.get("name") != name
        or verified.get("verified") is not True
        or verified.get("promoted") is not False
    ):
        raise HostError("backup_unverified")
    _audit(
        "backup",
        "verified",
        revision=revision,
        backup_name=name,
        sha256=value["sha256"],
        schema_version=expected_schema,
    )
    return {
        "trigger": "pre_deploy",
        "name": name,
        "sha256": value["sha256"],
        "schema_version": expected_schema,
        "verified": True,
    }


def _verified_first_release_backup(
    image_ref: str,
    revision: str,
    source_schema: int,
    target_schema: int,
    *,
    compose_file: Path | None = None,
) -> dict[str, Any]:
    """Migrate a transferred database only after an exact automatic-backup receipt."""

    receipt = _run_migrations(
        image_ref,
        revision,
        source_schema=source_schema,
        target_schema=target_schema,
        compose_file=compose_file,
    )
    if source_schema > 0 and source_schema < target_schema and receipt is None:
        raise HostError("pre_migration_backup_unverified")
    if _database_schema(image_ref, compose_file=compose_file) != target_schema:
        raise HostError("migration_schema_mismatch")
    backup = _verified_backup(image_ref, revision, compose_file=compose_file)
    backup["pre_migration_backup"] = receipt
    return backup


def _run_migrations(
    image_ref: str,
    revision: str,
    *,
    source_schema: int,
    target_schema: int,
    compose_file: Path | None = None,
) -> dict[str, Any] | None:
    """Run the fixed migration CLI and validate its schema-bound automatic backup receipt."""

    if not 0 <= source_schema <= target_schema <= 100:
        raise HostError("schema_incompatible")
    _runtime_file(image_ref, "disabled")
    output = _compose(
        "run",
        "--rm",
        "--no-deps",
        "-T",
        "app",
        "stock-probs",
        "migrate",
        timeout=300,
        compose_file=compose_file,
    )
    try:
        result = json.loads(output)
    except json.JSONDecodeError as exc:
        raise HostError("migration_result_unverified") from exc
    if not isinstance(result, dict) or result.get("status") != "migrated":
        raise HostError("migration_result_unverified")
    receipt = result.get("pre_migration_backup")
    if source_schema == 0 or source_schema == target_schema:
        if receipt is not None:
            raise HostError("pre_migration_backup_unverified")
        return None
    if (
        not isinstance(receipt, dict)
        or receipt.get("trigger") != "pre_migration"
        or receipt.get("verified") is not True
        or type(receipt.get("schema_version")) is not int
        or receipt.get("schema_version") != source_schema
        or not isinstance(receipt.get("name"), str)
        or BACKUP_NAME_PATTERN.fullmatch(receipt["name"]) is None
        or not isinstance(receipt.get("sha256"), str)
        or DIGEST_PATTERN.fullmatch(receipt["sha256"]) is None
    ):
        raise HostError("pre_migration_backup_unverified")
    safe_receipt = {
        "trigger": "pre_migration",
        "name": receipt["name"],
        "sha256": receipt["sha256"],
        "schema_version": source_schema,
        "verified": True,
    }
    _audit(
        "backup",
        "verified",
        revision=revision,
        backup_name=safe_receipt["name"],
        schema_version=source_schema,
    )
    return safe_receipt


def _write_failed_record(
    record: dict[str, Any],
    previous: dict[str, Any] | None,
    *,
    failure_code: str,
    actual_schema: int | None,
    rollback_attempted: bool,
    rollback_succeeded: bool,
    forward_recovery_attempted: bool = False,
    forward_recovery_succeeded: bool = False,
    backup: dict[str, Any] | None = None,
) -> None:
    """Publish bounded state after a failed promotion, including migration outcome."""

    previous_schema = previous.get("schema_version") if previous is not None else None
    if previous_schema is None and isinstance(backup, dict):
        migration_receipt = backup.get("pre_migration_backup")
        if isinstance(migration_receipt, dict):
            previous_schema = migration_receipt.get("schema_version")
        else:
            pre_deploy_receipt = backup.get("pre_deploy_backup", backup)
            if isinstance(pre_deploy_receipt, dict):
                previous_schema = pre_deploy_receipt.get("schema_version")
    migrated = (
        actual_schema is not None
        and type(previous_schema) is int
        and actual_schema != previous_schema
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
        "forward_recovery_attempted": forward_recovery_attempted,
        "forward_recovery_succeeded": forward_recovery_succeeded,
        "failed_at": _utc_now(),
    }
    for key in (
        "transport",
        "archive_sha256",
        "image_id",
        "platform",
        "archive_size",
        "pair_manifest_sha256",
        "source_context_sha256",
        "migration_sha256",
        "recovery_image_id",
        "recovery_archive_sha256",
        "recovery_archive_size",
        "recovery_platform",
        "recovery_schema_version",
        "recovery_base_revision",
        "recovery_overlay_sha256",
    ):
        if key in record:
            failed[key] = record[key]
    if previous is not None:
        failed["previous_revision"] = previous.get("revision")
        failed["previous_schema_version"] = previous.get("schema_version")
    if isinstance(backup, dict):
        receipts = (
            ("pre_deploy_backup", backup.get("pre_deploy_backup", backup)),
            ("pre_migration_backup", backup.get("pre_migration_backup")),
            ("recovery_backup", backup.get("recovery_backup")),
        )
        for field, receipt in receipts:
            if (
                isinstance(receipt, dict)
                and receipt.get("verified") is True
                and isinstance(receipt.get("name"), str)
                and BACKUP_NAME_PATTERN.fullmatch(receipt["name"]) is not None
                and isinstance(receipt.get("sha256"), str)
                and DIGEST_PATTERN.fullmatch(receipt["sha256"]) is not None
                and type(receipt.get("schema_version")) is int
                and 1 <= receipt["schema_version"] <= 100
            ):
                failed[field] = {
                    "trigger": receipt.get(
                        "trigger", "pre_deploy" if field == "pre_deploy_backup" else None
                    ),
                    "name": receipt["name"],
                    "sha256": receipt["sha256"],
                    "schema_version": receipt["schema_version"],
                    "verified": True,
                }
    _write_json(FAILED_RECORD, failed)
    _audit(
        "deploy",
        "failed",
        revision=record["revision"],
        image_digest=record["image_digest"],
        schema_version=actual_schema,
    )


def _forward_recovery_backup(
    failed: dict[str, Any] | None, current: dict[str, Any], target: dict[str, Any]
) -> dict[str, Any] | None:
    """Recognize only this task's failed schema-12-to-13 forward-recovery boundary."""

    if (
        failed is None
        or failed.get("status") != "failed_migrated"
        or failed.get("actual_schema_version") != ASSISTANT_MINIMUM_SCHEMA
        or failed.get("schema_version") != ASSISTANT_MINIMUM_SCHEMA
        or failed.get("previous_revision") != current.get("revision")
        or failed.get("previous_schema_version") != current.get("schema_version")
        or current.get("schema_version") != ASSISTANT_MINIMUM_SCHEMA - 1
        or target.get("schema_version") != ASSISTANT_MINIMUM_SCHEMA
    ):
        return None
    receipt = failed.get("pre_deploy_backup")
    if (
        not isinstance(receipt, dict)
        or receipt.get("trigger") != "pre_deploy"
        or receipt.get("verified") is not True
        or not isinstance(receipt.get("name"), str)
        or BACKUP_NAME_PATTERN.fullmatch(receipt["name"]) is None
        or not isinstance(receipt.get("sha256"), str)
        or DIGEST_PATTERN.fullmatch(receipt["sha256"]) is None
        or receipt.get("schema_version") != current.get("schema_version")
    ):
        return None
    return dict(receipt)


def _activate_same_schema_recovery(
    record: dict[str, Any],
    *,
    compose_snapshot: Path,
    health_out: dict[str, Any] | None = None,
) -> bool:
    """Run the verified schema-13 recovery image and optionally return its checked readiness."""

    recovery_ref = record.get("recovery_image_ref")
    recovery_archive_sha256 = record.get("recovery_archive_sha256")
    recovery_archive_size = record.get("recovery_archive_size")
    if (
        not isinstance(recovery_archive_sha256, str)
        or DIGEST_PATTERN.fullmatch(recovery_archive_sha256) is None
        or type(recovery_archive_size) is not int
        or not 1 <= recovery_archive_size <= MAX_RELEASE_ARCHIVE_BYTES
    ):
        return False
    try:
        _assert_loaded_recovery_image(record)
        recovered = dict(record)
        recovered.update(
            {
                "candidate_image_id": record.get("image_id"),
                "candidate_archive_sha256": record.get("archive_sha256"),
                "release_role": "recovery",
                "image_ref": recovery_ref,
                "image_digest": recovery_archive_sha256,
                "archive_sha256": recovery_archive_sha256,
                "image_id": record["recovery_image_id"],
                "archive_size": recovery_archive_size,
                "platform": record["recovery_platform"],
                "assistant_rollout_mode": "disabled",
            }
        )
        _assert_image_record(recovered)
        _runtime_file(recovery_ref, "disabled")
        _compose_up(
            recovered,
            timeout=180,
            compose_file=compose_snapshot,
            force_recreate=True,
        )
        health = _health_check()
        if health.get("schema_version") != ASSISTANT_MINIMUM_SCHEMA:
            raise HostError("recovery_readiness_schema_mismatch")
        _require_assistant_ready(health, "disabled", schema_version=ASSISTANT_MINIMUM_SCHEMA)
        _write_json(CURRENT_RECORD, recovered)
        if health_out is not None:
            health_out.update(health)
        return True
    except HostError:
        with suppress(HostError):
            _stop_app(compose_snapshot)
        return False


def _apply_release(record: dict[str, Any]) -> dict[str, Any]:
    revision = record["revision"]
    image_ref = record["image_ref"]
    image_digest = record["image_digest"]
    schema_version = record["schema_version"]
    current = _read_json(CURRENT_RECORD)
    _assert_loaded_image(record)
    if schema_version == ASSISTANT_MINIMUM_SCHEMA:
        _assert_loaded_recovery_image(record)
    if (
        current is not None
        and current.get("revision") == revision
        and current.get("image_digest") == image_digest
    ):
        return {"status": "ok", "result": "already_applied", "revision": revision}

    previous = current
    forward_backup: dict[str, Any] | None = None
    previous_compose: Path | None = None
    if current is not None:
        # Validate the persisted active image and its exact Compose definition before a probe or
        # migration can touch the shared volume.
        _assert_image_record(current)
        _assert_loaded_image(current)
        previous_compose = _assert_record_compose_digest(current)
        try:
            active_health = _health_check()
        except HostError as exc:
            failed = _read_json(FAILED_RECORD)
            forward_backup = _forward_recovery_backup(failed, current, record)
            if forward_backup is None:
                raise HostError("active_release_unready") from exc
        else:
            if _image_schema(current["image_ref"]) != active_health["schema_version"]:
                raise HostError("active_release_mismatch")
            if schema_version < active_health["schema_version"]:
                raise HostError("schema_incompatible")

    backup: dict[str, Any] | None = None
    try:
        # Stop and verify the only application container before taking the pre-migration
        # snapshot. This is the enforced no-admitted-writes boundary for the backup identity.
        if current is None:
            _runtime_file(image_ref, "disabled")
        _stop_app()
        migration_performed = False
        if current is None:
            if not _database_present(image_ref):
                backup = {"name": None, "verified": True}
                source_schema = 0
            else:
                source_schema = _database_schema(image_ref)
                if source_schema > schema_version:
                    raise HostError("schema_incompatible")
                if source_schema < schema_version:
                    backup = _verified_first_release_backup(
                        image_ref, revision, source_schema, schema_version
                    )
                    migration_performed = True
                else:
                    backup = _verified_backup(image_ref, revision)
        elif forward_backup is not None:
            source_schema = _database_schema(image_ref)
            if source_schema != ASSISTANT_MINIMUM_SCHEMA:
                raise HostError("forward_recovery_schema_mismatch")
            backup = _verified_backup(image_ref, revision)
            backup["pre_deploy_backup"] = forward_backup
            backup["recovery_backup"] = {
                "name": backup["name"],
                "sha256": backup.get("sha256"),
                "schema_version": backup.get("schema_version"),
                "verified": backup.get("verified"),
            }
        else:
            # The old image owns this snapshot, and its exact release Compose file runs the
            # backup CLI while the service is stopped. The backup's schema/hash are retained.
            assert previous_compose is not None
            source_schema = _database_schema(current["image_ref"], compose_file=previous_compose)
            if source_schema != current.get("schema_version"):
                raise HostError("active_release_mismatch")
            backup = _verified_backup(current["image_ref"], revision, compose_file=previous_compose)
            backup["pre_deploy_backup"] = dict(backup)

        if not migration_performed:
            migration_receipt = _run_migrations(
                image_ref,
                revision,
                source_schema=source_schema,
                target_schema=schema_version,
            )
            if backup is not None and migration_receipt is not None:
                backup["pre_migration_backup"] = migration_receipt
        if _database_schema(image_ref) != schema_version:
            raise HostError("migration_schema_mismatch")
        _runtime_file(image_ref, "disabled")
        _compose_up(record, timeout=180)
        health = _health_check()
        if health.get("schema_version") != schema_version:
            raise HostError("readiness_schema_mismatch")
        _require_assistant_ready(health, "disabled", schema_version=schema_version)
    except HostError as error:
        # A migration can commit before startup/readiness fails. First re-establish and verify
        # maintenance; inspect the real database schema only after no app writes are admitted.
        stopped = False
        try:
            _stop_app()
            stopped = True
        except HostError:
            pass
        actual_schema: int | None = None
        if stopped:
            with suppress(HostError):
                actual_schema = _database_schema(image_ref)

        rollback_attempted = False
        rollback_succeeded = False
        forward_recovery_attempted = False
        forward_recovery_succeeded = False
        if (
            stopped
            and actual_schema == ASSISTANT_MINIMUM_SCHEMA
            and record.get("schema_version") == ASSISTANT_MINIMUM_SCHEMA
            and record.get("pair_manifest_sha256") is not None
        ):
            forward_recovery_attempted = True
            try:
                target_compose = _assert_record_compose_digest(record)
            except HostError:
                target_compose = None
            if target_compose is not None:
                forward_recovery_succeeded = _activate_same_schema_recovery(
                    record, compose_snapshot=target_compose
                )
        # Code-only fallback is allowed only when the volume is still at the old app's exact
        # schema and the old image plus its reviewed Compose snapshot are available. No DB restore
        # is ever attempted here; schema-13 rows and all admitted data remain intact.
        if (
            stopped
            and previous is not None
            and actual_schema == previous.get("schema_version")
            and isinstance(previous.get("image_ref"), str)
            and isinstance(previous.get("image_digest"), str)
        ):
            try:
                previous_compose = _assert_record_compose_digest(previous)
            except HostError:
                pass
            else:
                rollback_attempted = True
                try:
                    _runtime_file(previous["image_ref"], "disabled")
                    _assert_loaded_image(previous)
                    _compose_up(
                        previous,
                        timeout=180,
                        compose_file=previous_compose,
                        force_recreate=True,
                    )
                    rollback_health = _health_check()
                    rollback_succeeded = rollback_health.get("schema_version") == previous.get(
                        "schema_version"
                    )
                except HostError:
                    rollback_succeeded = False
                if not rollback_succeeded:
                    with suppress(HostError):
                        _stop_app()
        _write_failed_record(
            record,
            previous,
            failure_code=error.code,
            actual_schema=actual_schema,
            rollback_attempted=rollback_attempted,
            rollback_succeeded=rollback_succeeded,
            forward_recovery_attempted=forward_recovery_attempted,
            forward_recovery_succeeded=forward_recovery_succeeded,
            backup=backup,
        )
        raise

    applied = {
        "revision": revision,
        "image_ref": image_ref,
        "image_digest": image_digest,
        "schema_version": schema_version,
        "backup_name": backup["name"] if backup is not None else None,
        "deployed_at": _utc_now(),
        "assistant_rollout_mode": "disabled",
    }
    if backup is not None:
        pre_deploy = backup.get("pre_deploy_backup", backup)
        if (
            isinstance(pre_deploy, dict)
            and pre_deploy.get("verified") is True
            and isinstance(pre_deploy.get("name"), str)
            and BACKUP_NAME_PATTERN.fullmatch(pre_deploy["name"]) is not None
            and isinstance(pre_deploy.get("sha256"), str)
            and DIGEST_PATTERN.fullmatch(pre_deploy["sha256"]) is not None
            and type(pre_deploy.get("schema_version")) is int
        ):
            applied["pre_deploy_backup"] = {
                "trigger": "pre_deploy",
                "name": pre_deploy["name"],
                "sha256": pre_deploy["sha256"],
                "schema_version": pre_deploy["schema_version"],
                "verified": True,
            }
        for field in ("pre_migration_backup", "recovery_backup"):
            receipt = backup.get(field)
            if (
                isinstance(receipt, dict)
                and receipt.get("verified") is True
                and isinstance(receipt.get("name"), str)
                and BACKUP_NAME_PATTERN.fullmatch(receipt["name"]) is not None
                and isinstance(receipt.get("sha256"), str)
                and DIGEST_PATTERN.fullmatch(receipt["sha256"]) is not None
                and type(receipt.get("schema_version")) is int
            ):
                applied[field] = dict(receipt)
    for key in ("transport", "archive_sha256", "image_id", "platform", "archive_size"):
        if key in record:
            applied[key] = record[key]
    for key in (
        "pair_manifest_sha256",
        "source_context_sha256",
        "migration_sha256",
        "recovery_image_ref",
        "recovery_image_id",
        "recovery_archive_sha256",
        "recovery_archive_size",
        "recovery_platform",
        "recovery_schema_version",
        "recovery_base_revision",
        "recovery_overlay_sha256",
    ):
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
        backup_name=applied["backup_name"],
    )
    return {"status": "ok", "result": "deployed", "revision": revision, "health": health}


def _deploy(
    plan_id: str,
    revision: str,
    image_digest: str,
    image_id: str | None = None,
    pair_manifest_sha256: str | None = None,
) -> dict[str, Any]:
    with _exclusive_lock():
        _ensure_layout()
        plan = _load_plan(plan_id)
        if (
            plan["revision"] != revision
            or plan["image_digest"] != image_digest
            or (_is_release_record(plan) and plan.get("image_id") != image_id)
            or plan.get("pair_manifest_sha256") != pair_manifest_sha256
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
        for key in (
            "pair_manifest_sha256",
            "source_context_sha256",
            "migration_sha256",
            "recovery_image_id",
            "recovery_archive_sha256",
            "recovery_archive_size",
            "recovery_platform",
            "recovery_schema_version",
            "recovery_base_revision",
            "recovery_overlay_sha256",
        ):
            if key in plan:
                result[key] = plan[key]
        return result


def _rollback_to_recorded_recovery(
    revision: str,
    record: dict[str, Any],
    recovery_image_id: str,
    compose_snapshot: Path,
) -> dict[str, Any]:
    """Activate only the exact recorded schema-13 recovery image on the existing volume."""

    # This selector is limited to the pinned schema-12-to-13 migration contract.
    if (
        not _is_release_record(record)
        or record.get("release_role", "candidate") != "candidate"
        or record.get("revision") != revision
        or record.get("schema_version") != ASSISTANT_MINIMUM_SCHEMA
        or record.get("image_id") == recovery_image_id
        or record.get("recovery_image_id") != recovery_image_id
        or not isinstance(record.get("pair_manifest_sha256"), str)
        or DIGEST_PATTERN.fullmatch(record["pair_manifest_sha256"]) is None
        or not isinstance(record.get("source_context_sha256"), str)
        or DIGEST_PATTERN.fullmatch(record["source_context_sha256"]) is None
        or record.get("migration_sha256") != PAIR_MIGRATION_SHA256
    ):
        raise HostError("recovery_image_record_invalid")

    _assert_image_record(record)
    _assert_loaded_recovery_image(record)
    recovery_archive_sha256 = record.get("recovery_archive_sha256")
    recovery_archive_size = record.get("recovery_archive_size")
    if (
        not isinstance(recovery_archive_sha256, str)
        or DIGEST_PATTERN.fullmatch(recovery_archive_sha256) is None
        or type(recovery_archive_size) is not int
        or not 1 <= recovery_archive_size <= MAX_RELEASE_ARCHIVE_BYTES
    ):
        raise HostError("recovery_image_record_invalid")
    actual_schema = _database_schema(record["recovery_image_ref"])
    if actual_schema != ASSISTANT_MINIMUM_SCHEMA:
        raise HostError("rollback_schema_incompatible")

    _stop_app()
    try:
        if (
            _database_schema(record["recovery_image_ref"], compose_file=compose_snapshot)
            != ASSISTANT_MINIMUM_SCHEMA
        ):
            raise HostError("rollback_schema_incompatible")
        health: dict[str, Any] = {}
        if not _activate_same_schema_recovery(
            record, compose_snapshot=compose_snapshot, health_out=health
        ):
            raise HostError("recovery_activation_failed")
        recovered = _read_json(CURRENT_RECORD)
        if (
            not isinstance(recovered, dict)
            or recovered.get("revision") != revision
            or recovered.get("release_role") != "recovery"
            or recovered.get("image_ref") != record.get("recovery_image_ref")
            or recovered.get("image_id") != recovery_image_id
            or recovered.get("image_digest") != record.get("recovery_archive_sha256")
            or recovered.get("archive_sha256") != record.get("recovery_archive_sha256")
            or recovered.get("schema_version") != ASSISTANT_MINIMUM_SCHEMA
            or recovered.get("assistant_rollout_mode") != "disabled"
            or recovered.get("compose_digest") != record.get("compose_digest")
            or recovered.get("pair_manifest_sha256") != record.get("pair_manifest_sha256")
        ):
            raise HostError("recovery_identity_mismatch")
        if not health:
            raise HostError("recovery_readiness_unverified")
    except HostError:
        with suppress(HostError):
            _stop_app(compose_snapshot)
        raise

    recovery_archive_sha256 = record["recovery_archive_sha256"]
    _audit(
        "rollback",
        "applied",
        revision=revision,
        image_digest=recovery_archive_sha256,
        image_id=recovery_image_id,
        release_role="recovery",
        pair_manifest_sha256=record["pair_manifest_sha256"],
        compose_digest=record["compose_digest"],
        schema_version=ASSISTANT_MINIMUM_SCHEMA,
    )
    return {
        "status": "ok",
        "result": "rolled_back",
        "revision": revision,
        "image_digest": recovery_archive_sha256,
        "schema_version": ASSISTANT_MINIMUM_SCHEMA,
        "health": health,
        "transport": GITHUB_RELEASE_TRANSPORT,
        "archive_sha256": recovery_archive_sha256,
        "image_id": recovery_image_id,
        "platform": record["recovery_platform"],
        "archive_size": record["recovery_archive_size"],
        "release_role": "recovery",
        "pair_manifest_sha256": record["pair_manifest_sha256"],
    }


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
        recovery_requested = False
        if _is_release_record(record):
            if image_id is not None and image_id == record.get("recovery_image_id"):
                if image_id == record.get("image_id"):
                    raise HostError("rollback_identity_mismatch")
                recovery_requested = True
            elif image_id != record["image_id"]:
                raise HostError("rollback_identity_mismatch")
        elif image_id is not None:
            raise HostError("rollback_identity_invalid")
        compose_snapshot = _assert_record_compose_digest(record)
        if recovery_requested:
            assert image_id is not None
            return _rollback_to_recorded_recovery(revision, record, image_id, compose_snapshot)
        # Check the immutable image identity before opening the database or starting Compose.  The
        # local release tag is only a convenience alias and may have been replaced since staging.
        _assert_loaded_image(record)
        actual_schema = _database_schema(record["image_ref"])
        if actual_schema != record.get("schema_version"):
            raise HostError("rollback_schema_incompatible")
        _stop_app()
        try:
            if (
                _database_schema(record["image_ref"], compose_file=compose_snapshot)
                != actual_schema
            ):
                raise HostError("rollback_schema_incompatible")
            _runtime_file(record["image_ref"], "disabled")
            _compose_up(
                record,
                timeout=180,
                compose_file=compose_snapshot,
                force_recreate=True,
            )
            health = _health_check()
            if health.get("schema_version") != actual_schema:
                raise HostError("rollback_schema_incompatible")
        except HostError:
            with suppress(HostError):
                _stop_app(compose_snapshot)
            raise
        applied = dict(record)
        applied["assistant_rollout_mode"] = "disabled"
        _write_json(CURRENT_RECORD, applied)
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


def _set_assistant_rollout(
    mode: str,
    *,
    revision: str,
    archive_sha256: str,
    image_id: str,
) -> dict[str, Any]:
    """Change only the assistant rollout for the exact current schema-13 release."""

    if mode not in ASSISTANT_ROLLOUT_MODES:
        raise HostError("assistant_rollout_invalid")
    with _exclusive_lock():
        _ensure_layout()
        current = _read_json(CURRENT_RECORD)
        if current is None:
            raise HostError("release_not_found")
        _assert_image_record(current)
        if current.get("release_role") == "recovery" and mode != "disabled":
            raise HostError("recovery_image_assistant_disabled")
        if (
            current.get("revision") != revision
            or current.get("transport") != GITHUB_RELEASE_TRANSPORT
            or current.get("archive_sha256") != archive_sha256
            or current.get("image_digest") != archive_sha256
            or current.get("image_id") != image_id
            or current.get("platform") != "linux/amd64"
            or current.get("schema_version") != ASSISTANT_MINIMUM_SCHEMA
            or _image_schema(current["image_ref"]) != ASSISTANT_MINIMUM_SCHEMA
        ):
            raise HostError("assistant_release_identity_mismatch")
        try:
            compose_snapshot = _assert_record_compose_digest(current)
            if _compose_digest() != current.get("compose_digest"):
                raise HostError("compose_revision_mismatch")
        except HostError:
            raise
        _assert_loaded_image(current)
        previous_mode = current.get("assistant_rollout_mode", "disabled")
        if previous_mode not in ASSISTANT_ROLLOUT_MODES:
            raise HostError("assistant_rollout_state_invalid")
        valid_transition = (
            mode == previous_mode
            or mode == "disabled"
            or (previous_mode == "disabled" and mode == "owner_canary")
            or (previous_mode == "owner_canary" and mode == "invited")
        )
        if not valid_transition:
            raise HostError("assistant_rollout_transition_invalid")

        updated = dict(current)
        updated["assistant_rollout_mode"] = mode
        try:
            running_identity: tuple[str, int] | None = None
            if mode == "disabled":
                # Persist the rollout first so a later container restart remains disabled.
                # The fixed in-container client only asks PID 1 to stop the worker; it never
                # restarts Uvicorn or accepts a path/command from the MCP caller.
                running_identity = _app_container_identity(compose_snapshot)
            _runtime_file(current["image_ref"], mode)
            _write_json(CURRENT_RECORD, updated)
            if mode == "disabled":
                assert running_identity is not None
                _request_in_place_assistant_kill(running_identity[0])
            else:
                _compose_up(
                    current,
                    timeout=180,
                    compose_file=compose_snapshot,
                    force_recreate=True,
                )
            health = _health_check()
            if health.get("schema_version") != ASSISTANT_MINIMUM_SCHEMA:
                raise HostError("readiness_schema_mismatch")
            _require_assistant_ready(health, mode, schema_version=ASSISTANT_MINIMUM_SCHEMA)
            if mode == "disabled" and _app_container_identity(compose_snapshot) != running_identity:
                raise HostError("assistant_app_identity_changed")
        except HostError as error:
            disabled = dict(current)
            disabled["assistant_rollout_mode"] = "disabled"
            disabled_env_written = False
            disabled_record_written = False
            try:
                _runtime_file(current["image_ref"], "disabled")
                disabled_env_written = True
            except HostError:
                pass
            try:
                _write_json(CURRENT_RECORD, disabled)
                disabled_record_written = True
            except HostError:
                pass
            app_stopped = False
            assistant_disabled_verified = False
            if mode != "disabled" and disabled_env_written and disabled_record_written:
                try:
                    _compose_up(
                        current,
                        timeout=180,
                        compose_file=compose_snapshot,
                        force_recreate=True,
                    )
                    disabled_health = _health_check()
                    if disabled_health.get("schema_version") != ASSISTANT_MINIMUM_SCHEMA:
                        raise HostError("readiness_schema_mismatch")
                    _require_assistant_ready(
                        disabled_health, "disabled", schema_version=ASSISTANT_MINIMUM_SCHEMA
                    )
                    assistant_disabled_verified = True
                except HostError:
                    try:
                        _stop_app(compose_snapshot)
                        app_stopped = True
                    except HostError:
                        app_stopped = False
            else:
                # A requested disable that cannot be verified must not leave an enabled worker
                # serving under a durable disabled marker. Stop the whole app if the kill switch
                # recreation or readiness projection is uncertain.
                try:
                    _stop_app(compose_snapshot)
                    app_stopped = True
                except HostError:
                    app_stopped = False
            with suppress(HostError):
                _record_rollout_failure(
                    current,
                    requested_mode=mode,
                    failure_code=error.code,
                    assistant_disabled_verified=assistant_disabled_verified,
                    app_stopped=app_stopped,
                )
            raise error
        _audit(
            "assistant_rollout",
            "updated",
            revision=revision,
            image_digest=archive_sha256,
            schema_version=ASSISTANT_MINIMUM_SCHEMA,
        )
        return {
            "status": "ok",
            "result": "rollout_updated",
            "revision": revision,
            "archive_sha256": archive_sha256,
            "image_id": image_id,
            "schema_version": ASSISTANT_MINIMUM_SCHEMA,
            "assistant_rollout_mode": mode,
            "health": health,
        }


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
    if operation in _PAIR_PAYLOAD_KEYS:
        allowed_keys.add(_PAIR_PAYLOAD_KEYS[operation])
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
                _validate_digest(payload["pair_manifest_sha256"])
                if "pair_manifest_sha256" in payload
                else None,
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
                _validate_digest(payload["pair_manifest_sha256"])
                if "pair_manifest_sha256" in payload
                else None,
            )
        return _deploy(
            _validate_plan_id(payload["plan_id"]),
            _validate_revision(payload["revision"]),
            _validate_digest(payload["image_digest"]),
        )
    if operation == "set_assistant_rollout":
        mode = payload["mode"]
        if not isinstance(mode, str) or mode not in ASSISTANT_ROLLOUT_MODES:
            raise HostError("assistant_rollout_invalid")
        return _set_assistant_rollout(
            mode,
            revision=_validate_revision(payload["revision"]),
            archive_sha256=_validate_digest(payload["archive_sha256"]),
            image_id=_validate_image_id(payload["image_id"]),
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
