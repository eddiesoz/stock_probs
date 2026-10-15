#!/usr/bin/env python3
"""Run the fixed, host-side Signal Ledger release protocol.

The SSH entry point accepts one bounded JSON request and never accepts a shell command,
filesystem path, image name, or network URL from its caller.  The setup script installs this
file behind a root-owned wrapper and a narrowly scoped sudo rule; the state and Docker commands
below are therefore the only production mutations available to the deployment MCP.
"""

from __future__ import annotations

import fcntl
import gzip
import hashlib
import json
import math
import os
import re
import secrets
import selectors
import stat
import subprocess
import sys
import tarfile
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
TEMPORARY_RECOVERY_ROOT = STATE_ROOT / "temporary-recovery"
TEMPORARY_RECOVERY_MANIFEST = TEMPORARY_RECOVERY_ROOT / "manifest.json"
TEMPORARY_RECOVERY_ARCHIVE = TEMPORARY_RECOVERY_ROOT / "image.tar.gz"
TEMPORARY_RECOVERY_OPERATION = STATE_ROOT / "temporary-recovery-operation.json"
TEMPORARY_RECOVERY_APPROVAL = Path("/etc/signal-ledger/temporary-recovery.approval.json")
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
PRODUCTION_PREDECESSOR_REVISION = "5ad2c3fddfce5a5a631b72cd832a53f24757c44a"
PRODUCTION_PREDECESSOR_IMAGE_ID = (
    "sha256:78746f600815cac1941a9060f91bba41aca08f363714db466200c2d77e8ad7b1"
)
PRODUCTION_PREDECESSOR_COMPOSE_SHA256 = (
    "01028e5b02cc0eded5f7b5207950a54b5a111b169f2a60a4ae8abdc6dfdb92b0"
)
PROTECTED_A9_IMAGE_ID = "sha256:a9b5147cff0016e443589e8c7b72e83764ca4bac45866ef3ad9bbcd3b308c13f"
TEMPORARY_RECOVERY_SOURCE_REVISION = "63597953c9d1ab387563dadfe705b78a2861a426"
TEMPORARY_RECOVERY_SOURCE_MANIFEST_SHA256 = (
    "9443700f5248606c1f50a6e4e1bb2a20782a44aaa06fe62ffc3de2d17c4c2994"
)
TEMPORARY_RECOVERY_BASE_ARCHIVE_SHA256 = (
    "a197b69829076e75bdc1c51830761d1bb4d4c0fda9074372abb45b6d972d59d7"
)
TEMPORARY_RECOVERY_BASE_CONTEXT_SHA256 = (
    "38a2098f81fde0d3b73e7e3b3d31f84b5731492ff04b9ace2bfe5fd83c53c97b"
)
TEMPORARY_RECOVERY_CONTEXT_SHA256 = (
    "964d7ca16ac1733c031780fc5dd3c271461489cc58cb9a653371cb060b26baa9"
)
TEMPORARY_RECOVERY_OVERLAY_SHA256 = (
    "272949c0fcaafcc0b217265619ba3eb76d9e9e92d69c18a2492100f5e14a0a6f"
)
TEMPORARY_RECOVERY_FILE_SHA256 = {
    "Dockerfile": "e904ce9e9dc842be12860efd19f4e6f4e6eb4a1a04e696ba00d065456dcca7d4",
    "src/stock_probs/api.py": "91cadf3c9dec6b599e9a27c54105a38097c2a2e5db44d4874af9e5bb841eb568",
    "src/stock_probs/migrations/013_assistant_conversations.sql": PAIR_MIGRATION_SHA256,
    "src/stock_probs/provider.py": (
        "1b4a4c94f049a3068985d11919e96f1b5c4b459bdfdae7e985bec8b888eb3ad1"
    ),
    "src/stock_probs/recovery_supervisor.py": (
        "35972aad9f7c58339c703afaa3767203dbb2e4e8fce017162f316e6550759803"
    ),
    "src/stock_probs/repository.py": (
        "cab534210e18fb2fd493fd147bbda59a2460721db931600de701d6e489500710"
    ),
}
TEMPORARY_RECOVERY_SOURCE_CONTEXT_SHA256 = TEMPORARY_RECOVERY_CONTEXT_SHA256
MAX_RELEASE_ARCHIVE_BYTES = 512 * 1024 * 1024
MAX_TEMPORARY_RECOVERY_MANIFEST_BYTES = 8_192
MAX_TEMPORARY_RECOVERY_APPROVAL_BYTES = 1_024
MAX_TEMPORARY_ARCHIVE_MEMBERS = 100_000
MAX_TEMPORARY_ARCHIVE_MANIFEST_BYTES = 65_536
MAX_TEMPORARY_ARCHIVE_MEMBER_BYTES = MAX_RELEASE_ARCHIVE_BYTES
MAX_TEMPORARY_ARCHIVE_METADATA_BYTES = 65_536
MAX_TEMPORARY_ARCHIVE_METADATA_MEMBERS = 256
MAX_TEMPORARY_ARCHIVE_DECODED_BYTES = MAX_RELEASE_ARCHIVE_BYTES
MAX_TEMPORARY_ARCHIVE_READ_BYTES = 1 * 1024 * 1024
TEMPORARY_RECOVERY_HEALTHCHECK_TIMEOUT_SECONDS = 5.0
TEMPORARY_RECOVERY_MEMORY_SAMPLE_INTERVAL_SECONDS = 0.25
TEMPORARY_RECOVERY_ARCHIVE_VERIFY_TIMEOUT_SECONDS = 60.0
TEMPORARY_RECOVERY_AVAILABLE_RESERVE_KIB = 128 * 1024
TEMPORARY_RECOVERY_STARTUP_FLOOR_KIB = 512 * 1024
TEMPORARY_RECOVERY_COMMAND = [
    "serve",
    "--host",
    "0.0.0.0",  # noqa: S104 - the fixed production Compose publish is loopback-only.
    "--port",
    "8000",
    "--allow-non-loopback",
]
RELEASE_DOWNLOAD_TIMEOUT_SECONDS = 600
HEALTH_URL = "http://127.0.0.1:8000/api/v1/readiness"
HEALTH_ATTEMPTS = 30
HEALTH_DELAY_SECONDS = 1.0
ASSISTANT_MINIMUM_SCHEMA = 13
ASSISTANT_ROLLOUT_MODES = frozenset({"disabled", "owner_canary", "invited"})
ASSISTANT_RUNTIME_STATUS = frozenset({"disabled", "starting", "ready", "unavailable", "stopped"})
MAX_COMPOSE_SNAPSHOT_BYTES = 128 * 1024

_ALLOWED_OPERATIONS = frozenset(
    {
        "inspect",
        "plan_deploy",
        "deploy",
        "status",
        "rollback",
        "set_assistant_rollout",
        "start_temporary_recovery",
        "restore_temporary_recovery",
    }
)
_EXPECTED_PAYLOAD_KEYS = {
    "inspect": frozenset(),
    "status": frozenset(),
    "plan_deploy": frozenset({"revision", "archive_sha256", "image_id"}),
    "deploy": frozenset({"plan_id", "revision", "archive_sha256", "image_id"}),
    "rollback": frozenset({"revision", "image_id"}),
    "set_assistant_rollout": frozenset({"mode", "revision", "archive_sha256", "image_id"}),
    "start_temporary_recovery": frozenset(),
    "restore_temporary_recovery": frozenset({"operation_id"}),
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


def _canonical_json_object(raw: bytes, error_code: str) -> dict[str, Any]:
    """Decode one duplicate-free canonical JSON object for reviewed root-owned inputs."""

    def object_without_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in pairs:
            if key in value:
                raise ValueError("duplicate key")
            value[key] = item
        return value

    try:
        value = json.loads(raw, object_pairs_hook=object_without_duplicates)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise HostError(error_code) from exc
    if not isinstance(value, dict):
        raise HostError(error_code)
    canonical = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    if canonical != raw:
        raise HostError(error_code)
    return value


def _read_root_owned_json(
    path: Path, *, maximum_bytes: int, error_code: str
) -> tuple[dict[str, Any], bytes]:
    """Read one exact-mode root-owned regular file without following links or accepting aliases."""

    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    except FileNotFoundError as exc:
        raise HostError(error_code) from exc
    except OSError as exc:
        raise HostError(error_code) from exc
    try:
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != 0
            or stat.S_IMODE(metadata.st_mode) != 0o600
            or metadata.st_nlink != 1
            or metadata.st_size > maximum_bytes
        ):
            raise HostError(error_code)
        chunks: list[bytes] = []
        total = 0
        while total <= maximum_bytes:
            chunk = os.read(descriptor, min(4_096, maximum_bytes + 1 - total))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
        raw = b"".join(chunks)
        if len(raw) != metadata.st_size or len(raw) > maximum_bytes:
            raise HostError(error_code)
    except OSError as exc:
        raise HostError(error_code) from exc
    finally:
        os.close(descriptor)
    return _canonical_json_object(raw, error_code), raw


def _assert_root_owned_directory(path: Path, *, private: bool) -> None:
    """Require fixed state directories to be root-owned and non-writable by other users."""

    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    except OSError as exc:
        raise HostError("temporary_recovery_state_unsafe") from exc
    try:
        metadata = os.fstat(descriptor)
        mode = stat.S_IMODE(metadata.st_mode)
        if (
            not stat.S_ISDIR(metadata.st_mode)
            or metadata.st_uid != 0
            or (mode != 0o700 if private else bool(mode & 0o022))
        ):
            raise HostError("temporary_recovery_state_unsafe")
    except OSError as exc:
        raise HostError("temporary_recovery_state_unsafe") from exc
    finally:
        os.close(descriptor)


def _validate_temporary_recovery_manifest(value: object) -> dict[str, Any]:
    """Accept only the reviewed app-only schema-13 source and later-bound artifact identity."""

    expected = {
        "format_version",
        "kind",
        "built_or_published",
        "source_revision",
        "source_manifest_sha256",
        "base_revision",
        "base_source_archive_sha256",
        "base_source_context_sha256",
        "source_context_sha256",
        "migration_sha256",
        "overlay_sha256",
        "overlay_files",
        "schema_version",
        "image",
    }
    if not isinstance(value, dict) or set(value) != expected:
        raise HostError("temporary_recovery_manifest_invalid")
    if type(value.get("format_version")) is not int:
        raise HostError("temporary_recovery_manifest_invalid")
    static_values = {
        "format_version": 1,
        "kind": "temporary_recovery",
        "built_or_published": True,
        "source_revision": TEMPORARY_RECOVERY_SOURCE_REVISION,
        "source_manifest_sha256": TEMPORARY_RECOVERY_SOURCE_MANIFEST_SHA256,
        "base_revision": PAIR_BASE_REVISION,
        "base_source_archive_sha256": TEMPORARY_RECOVERY_BASE_ARCHIVE_SHA256,
        "base_source_context_sha256": TEMPORARY_RECOVERY_BASE_CONTEXT_SHA256,
        "source_context_sha256": TEMPORARY_RECOVERY_SOURCE_CONTEXT_SHA256,
        "migration_sha256": PAIR_MIGRATION_SHA256,
        "overlay_sha256": TEMPORARY_RECOVERY_OVERLAY_SHA256,
        "overlay_files": TEMPORARY_RECOVERY_FILE_SHA256,
        "schema_version": ASSISTANT_MINIMUM_SCHEMA,
    }
    if any(value.get(key) != expected_value for key, expected_value in static_values.items()):
        raise HostError("temporary_recovery_manifest_invalid")
    image = value.get("image")
    image_keys = {
        "archive_sha256",
        "archive_size",
        "image_id",
        "platform",
        "image_revision",
        "repo_tag",
        "entrypoint",
        "command",
    }
    if not isinstance(image, dict) or set(image) != image_keys:
        raise HostError("temporary_recovery_manifest_invalid")
    image_id = image.get("image_id")
    archive_sha256 = image.get("archive_sha256")
    archive_size = image.get("archive_size")
    repo_tag = image.get("repo_tag")
    if (
        not isinstance(image_id, str)
        or IMAGE_ID_PATTERN.fullmatch(image_id) is None
        or image_id in {PRODUCTION_PREDECESSOR_IMAGE_ID, PROTECTED_A9_IMAGE_ID}
        or not isinstance(archive_sha256, str)
        or DIGEST_PATTERN.fullmatch(archive_sha256) is None
        or type(archive_size) is not int
        or not 1 <= archive_size <= MAX_RELEASE_ARCHIVE_BYTES
        or image.get("platform") != "linux/amd64"
        or image.get("image_revision") != TEMPORARY_RECOVERY_SOURCE_REVISION
        or repo_tag
        != f"signal-ledger:temporary-recovery-build-{TEMPORARY_RECOVERY_SOURCE_REVISION[:12]}"
        or image.get("entrypoint") != ["python", "-m", "stock_probs.recovery_supervisor"]
        or image.get("command") != TEMPORARY_RECOVERY_COMMAND
    ):
        raise HostError("temporary_recovery_manifest_invalid")
    return value


def _load_temporary_recovery_authorization() -> tuple[dict[str, Any], str]:
    """Bind the fixed root-owned artifact manifest to a separate reviewed approval file."""

    _assert_root_owned_directory(TEMPORARY_RECOVERY_ROOT, private=True)
    _assert_root_owned_directory(TEMPORARY_RECOVERY_APPROVAL.parent, private=False)
    approval, _ = _read_root_owned_json(
        TEMPORARY_RECOVERY_APPROVAL,
        maximum_bytes=MAX_TEMPORARY_RECOVERY_APPROVAL_BYTES,
        error_code="temporary_recovery_approval_unavailable",
    )
    if (
        set(approval) != {"format_version", "kind", "review_status", "manifest_sha256"}
        or type(approval.get("format_version")) is not int
        or approval.get("format_version") != 1
        or approval.get("kind") != "temporary_recovery"
        or approval.get("review_status") != "approved"
        or not isinstance(approval.get("manifest_sha256"), str)
        or DIGEST_PATTERN.fullmatch(approval["manifest_sha256"]) is None
    ):
        raise HostError("temporary_recovery_approval_invalid")
    manifest, raw = _read_root_owned_json(
        TEMPORARY_RECOVERY_MANIFEST,
        maximum_bytes=MAX_TEMPORARY_RECOVERY_MANIFEST_BYTES,
        error_code="temporary_recovery_manifest_unavailable",
    )
    manifest_sha256 = hashlib.sha256(raw).hexdigest()
    if manifest_sha256 != approval["manifest_sha256"]:
        raise HostError("temporary_recovery_manifest_digest_mismatch")
    return _validate_temporary_recovery_manifest(manifest), manifest_sha256


def _assert_temporary_recovery_archive(
    manifest: dict[str, Any], *, memory_reserve_kib: int | None = None
) -> None:
    """Verify the exact tag and config identity in a bounded legacy or OCI image save."""

    def monotonic_now(previous: float | None) -> float:
        try:
            value = time.monotonic()
            if type(value) not in (int, float) or not math.isfinite(value):
                raise ValueError("invalid monotonic clock value")
            value = float(value)
        except (OSError, OverflowError, TypeError, ValueError) as exc:
            raise HostError("temporary_recovery_archive_clock_invalid") from exc
        if previous is not None and value < previous:
            raise HostError("temporary_recovery_archive_clock_invalid")
        return value

    if memory_reserve_kib is not None and (
        type(memory_reserve_kib) is not int or memory_reserve_kib <= 0
    ):
        raise HostError("temporary_recovery_archive_invalid")
    started = monotonic_now(None)
    deadline = started + TEMPORARY_RECOVERY_ARCHIVE_VERIFY_TIMEOUT_SECONDS
    if not math.isfinite(deadline) or deadline <= started:
        raise HostError("temporary_recovery_archive_clock_invalid")
    last_clock = started
    last_memory_sample: float | None = None

    def check_verification_budget() -> None:
        nonlocal last_clock, last_memory_sample
        now = monotonic_now(last_clock)
        last_clock = now
        if now >= deadline:
            raise HostError("temporary_recovery_archive_timeout")
        if memory_reserve_kib is None or (
            last_memory_sample is not None
            and now - last_memory_sample < TEMPORARY_RECOVERY_MEMORY_SAMPLE_INTERVAL_SECONDS
        ):
            return
        available = _memory_available_kib()
        sampled_at = monotonic_now(last_clock)
        last_clock = sampled_at
        if sampled_at >= deadline:
            raise HostError("temporary_recovery_archive_timeout")
        if available < memory_reserve_kib:
            raise HostError("host_memory_reserve_breached")
        last_memory_sample = sampled_at

    check_verification_budget()
    try:
        archive_fd = os.open(
            TEMPORARY_RECOVERY_ARCHIVE,
            os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC,
        )
    except OSError as exc:
        raise HostError("temporary_recovery_archive_unavailable") from exc
    try:
        metadata = os.fstat(archive_fd)
        check_verification_budget()
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != 0
            or stat.S_IMODE(metadata.st_mode) != 0o600
            or metadata.st_nlink != 1
            or metadata.st_size != manifest["image"]["archive_size"]
        ):
            raise HostError("temporary_recovery_archive_unsafe")
        identity = (
            metadata.st_dev,
            metadata.st_ino,
            metadata.st_size,
            metadata.st_mtime_ns,
            metadata.st_ctime_ns,
        )
        digest = hashlib.sha256()
        while True:
            check_verification_budget()
            chunk = os.read(archive_fd, 1024 * 1024)
            if not chunk:
                check_verification_budget()
                break
            digest.update(chunk)
            check_verification_budget()
        if digest.hexdigest() != manifest["image"]["archive_sha256"]:
            raise HostError("temporary_recovery_archive_digest_mismatch")

        def object_without_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
            value: dict[str, Any] = {}
            for key, item in pairs:
                if key in value:
                    raise ValueError("duplicate key")
                value[key] = item
            return value

        class BoundedReader:
            """Limit bytes expanded from the outer gzip tar without buffering its members."""

            def __init__(self, source: gzip.GzipFile) -> None:
                self.source = source
                self.decoded_bytes = 0

            def read(self, size: int = -1) -> bytes:
                if size < 0 or size > MAX_TEMPORARY_ARCHIVE_READ_BYTES:
                    raise HostError("temporary_recovery_archive_invalid")
                remaining = size
                chunks: list[bytes] = []
                while remaining:
                    check_verification_budget()
                    allowance = MAX_TEMPORARY_ARCHIVE_DECODED_BYTES - self.decoded_bytes
                    chunk = self.source.read(
                        min(remaining, MAX_TEMPORARY_ARCHIVE_READ_BYTES, allowance + 1)
                    )
                    check_verification_budget()
                    if not chunk:
                        break
                    self.decoded_bytes += len(chunk)
                    if self.decoded_bytes > MAX_TEMPORARY_ARCHIVE_DECODED_BYTES:
                        raise HostError("temporary_recovery_archive_invalid")
                    chunks.append(chunk)
                    remaining -= len(chunk)
                return b"".join(chunks)

        class BoundedTarInfo(tarfile.TarInfo):
            """Reject oversized extension metadata and unsupported sparse entries."""

            @staticmethod
            def _reserve_metadata(tar_file: tarfile.TarFile, size: int) -> None:
                count = int(getattr(tar_file, "_temporary_metadata_members", 0)) + 1
                total = int(getattr(tar_file, "_temporary_metadata_bytes", 0)) + size
                if (
                    size < 0
                    or size > MAX_TEMPORARY_ARCHIVE_METADATA_BYTES
                    or total > MAX_TEMPORARY_ARCHIVE_METADATA_BYTES
                    or count > MAX_TEMPORARY_ARCHIVE_METADATA_MEMBERS
                ):
                    raise HostError("temporary_recovery_archive_invalid")
                tar_file._temporary_metadata_members = count
                tar_file._temporary_metadata_bytes = total

            def _proc_pax(self, tar_file: tarfile.TarFile):
                self._reserve_metadata(tar_file, self.size)
                return super()._proc_pax(tar_file)

            def _proc_gnulong(self, tar_file: tarfile.TarFile):
                self._reserve_metadata(tar_file, self.size)
                return super()._proc_gnulong(tar_file)

            def _proc_sparse(self, tar_file: tarfile.TarFile):
                raise HostError("temporary_recovery_archive_invalid")

            def _proc_gnusparse_00(self, next_member, raw_headers):
                raise HostError("temporary_recovery_archive_invalid")

            def _proc_gnusparse_01(self, next_member, pax_headers):
                raise HostError("temporary_recovery_archive_invalid")

            def _proc_gnusparse_10(self, next_member, pax_headers, tar_file):
                raise HostError("temporary_recovery_archive_invalid")

        def normalized_name(member: tarfile.TarInfo) -> str:
            name = member.name
            is_directory = member.isdir()
            if is_directory and name.endswith("/"):
                name = name[:-1]
            if (
                not isinstance(name, str)
                or not name
                or len(name) > 4_096
                or name.startswith("/")
                or name.endswith("/")
                or "\\" in name
                or any(ord(char) < 32 or ord(char) == 127 for char in name)
                or any(part in {"", ".", ".."} for part in name.split("/"))
            ):
                raise HostError("temporary_recovery_archive_invalid")
            if not (member.isfile() or is_directory):
                raise HostError("temporary_recovery_archive_invalid")
            return name

        def scan_archive(
            capture_names: set[str],
        ) -> tuple[dict[str, tuple[str, int]], dict[str, bytes]]:
            check_verification_budget()
            os.lseek(archive_fd, 0, os.SEEK_SET)
            check_verification_budget()
            entries: dict[str, tuple[str, int]] = {}
            captured: dict[str, bytes] = {}
            total_member_bytes = 0
            try:
                with (
                    os.fdopen(os.dup(archive_fd), "rb") as raw_stream,
                    gzip.GzipFile(fileobj=raw_stream, mode="rb") as compressed,
                ):
                    bounded = BoundedReader(compressed)
                    with tarfile.open(
                        fileobj=bounded, mode="r|", tarinfo=BoundedTarInfo
                    ) as archive:
                        for member_count, member in enumerate(archive, start=1):
                            check_verification_budget()
                            if member_count > MAX_TEMPORARY_ARCHIVE_MEMBERS:
                                raise HostError("temporary_recovery_archive_invalid")
                            name = normalized_name(member)
                            if name in entries:
                                raise HostError("temporary_recovery_archive_invalid")
                            if member.isdir():
                                if member.size != 0:
                                    raise HostError("temporary_recovery_archive_invalid")
                                entry = ("directory", 0)
                            else:
                                if (
                                    type(member.size) is not int
                                    or member.size < 0
                                    or member.size > MAX_TEMPORARY_ARCHIVE_MEMBER_BYTES
                                ):
                                    raise HostError("temporary_recovery_archive_invalid")
                                total_member_bytes += member.size
                                if total_member_bytes > MAX_TEMPORARY_ARCHIVE_DECODED_BYTES:
                                    raise HostError("temporary_recovery_archive_invalid")
                                entry = ("file", member.size)
                            entries[name] = entry
                            if name not in capture_names:
                                continue
                            limit = (
                                16
                                if name.endswith("/VERSION")
                                else MAX_TEMPORARY_ARCHIVE_MANIFEST_BYTES
                            )
                            if entry[0] != "file" or entry[1] > limit:
                                raise HostError("temporary_recovery_archive_invalid")
                            source = archive.extractfile(member)
                            if source is None:
                                raise HostError("temporary_recovery_archive_invalid")
                            with source:
                                check_verification_budget()
                                raw = source.read(limit + 1)
                                check_verification_budget()
                            if len(raw) != entry[1] or len(raw) > limit:
                                raise HostError("temporary_recovery_archive_invalid")
                            captured[name] = raw
            except HostError:
                raise
            except (OSError, EOFError, gzip.BadGzipFile, tarfile.TarError, ValueError) as exc:
                raise HostError("temporary_recovery_archive_invalid") from exc
            return entries, captured

        try:
            entries, metadata_members = scan_archive(
                {"manifest.json", "oci-layout", "index.json", "repositories"}
            )
            raw = metadata_members.get("manifest.json")
            if raw is None:
                raise HostError("temporary_recovery_archive_invalid")
            docker_manifest = json.loads(raw, object_pairs_hook=object_without_duplicates)
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            raise HostError("temporary_recovery_archive_invalid") from exc
        if (
            not isinstance(docker_manifest, list)
            or len(docker_manifest) != 1
            or not isinstance(docker_manifest[0], dict)
            or set(docker_manifest[0]) != {"Config", "RepoTags", "Layers"}
            or docker_manifest[0].get("RepoTags") != [manifest["image"]["repo_tag"]]
            or not isinstance(docker_manifest[0].get("Config"), str)
            or not isinstance(docker_manifest[0].get("Layers"), list)
            or not 1 <= len(docker_manifest[0]["Layers"]) <= 128
        ):
            raise HostError("temporary_recovery_archive_invalid")
        entry = docker_manifest[0]
        expected_id = manifest["image"]["image_id"].removeprefix("sha256:")
        config_path = entry["Config"]
        layers = entry["Layers"]
        if (
            not all(isinstance(name, str) for name in layers)
            or len(set(layers)) != len(layers)
            or any(
                not name
                or name.startswith("/")
                or "\\" in name
                or any(part in {"", ".", ".."} for part in name.split("/"))
                for name in [config_path, *layers]
            )
        ):
            raise HostError("temporary_recovery_archive_invalid")

        files = {name for name, kind_size in entries.items() if kind_size[0] == "file"}
        directories = {name for name, kind_size in entries.items() if kind_size[0] == "directory"}
        oci_present = "oci-layout" in files or "index.json" in files
        if oci_present != ("oci-layout" in files and "index.json" in files):
            raise HostError("temporary_recovery_archive_invalid")

        def parsed_json(name: str) -> Any:
            raw_value = metadata_members.get(name)
            if raw_value is None:
                raise HostError("temporary_recovery_archive_invalid")
            try:
                return json.loads(raw_value, object_pairs_hook=object_without_duplicates)
            except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
                raise HostError("temporary_recovery_archive_invalid") from exc

        if oci_present:
            if "repositories" in files or config_path != f"blobs/sha256/{expected_id}":
                raise HostError("temporary_recovery_archive_invalid")
            layout = parsed_json("oci-layout")
            index = parsed_json("index.json")
            if layout != {"imageLayoutVersion": "1.0.0"} or (
                not isinstance(index, dict)
                or set(index) != {"schemaVersion", "mediaType", "manifests"}
                or index.get("schemaVersion") != 2
                or index.get("mediaType") != "application/vnd.oci.image.index.v1+json"
                or not isinstance(index.get("manifests"), list)
                or len(index["manifests"]) != 1
            ):
                raise HostError("temporary_recovery_archive_invalid")
            descriptor = index["manifests"][0]
            descriptor_keys = {"digest", "mediaType", "size"}
            if isinstance(descriptor, dict) and "annotations" in descriptor:
                descriptor_keys.add("annotations")
            if isinstance(descriptor, dict) and "platform" in descriptor:
                descriptor_keys.add("platform")
            if (
                not isinstance(descriptor, dict)
                or set(descriptor) != descriptor_keys
                or descriptor.get("mediaType") != "application/vnd.oci.image.manifest.v1+json"
                or not isinstance(descriptor.get("digest"), str)
                or re.fullmatch(r"sha256:[0-9a-f]{64}", descriptor["digest"]) is None
                or type(descriptor.get("size")) is not int
                or not 1 <= descriptor["size"] <= MAX_TEMPORARY_ARCHIVE_MANIFEST_BYTES
            ):
                raise HostError("temporary_recovery_archive_invalid")
            annotations = descriptor.get("annotations")
            if "annotations" in descriptor:
                if (
                    not isinstance(annotations, dict)
                    or not annotations
                    or set(annotations)
                    - {
                        "org.opencontainers.image.created",
                        "org.opencontainers.image.ref.name",
                    }
                    or (
                        "org.opencontainers.image.ref.name" in annotations
                        and annotations["org.opencontainers.image.ref.name"]
                        != manifest["image"]["repo_tag"]
                    )
                ):
                    raise HostError("temporary_recovery_archive_invalid")
                if "org.opencontainers.image.created" in annotations:
                    created = annotations["org.opencontainers.image.created"]
                    if (
                        not isinstance(created, str)
                        or re.fullmatch(
                            r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,9})?Z",
                            created,
                        )
                        is None
                    ):
                        raise HostError("temporary_recovery_archive_invalid")
                    try:
                        datetime.fromisoformat(created[:-1] + "+00:00")
                    except ValueError as exc:
                        raise HostError("temporary_recovery_archive_invalid") from exc
            if "platform" in descriptor and descriptor["platform"] != {
                "architecture": "amd64",
                "os": "linux",
            }:
                raise HostError("temporary_recovery_archive_invalid")

            image_manifest_hex = descriptor["digest"].removeprefix("sha256:")
            image_manifest_path = f"blobs/sha256/{image_manifest_hex}"
            if entries.get(image_manifest_path) != ("file", descriptor["size"]):
                raise HostError("temporary_recovery_archive_invalid")
            second_entries, second_metadata = scan_archive({image_manifest_path})
            if entries != second_entries:
                raise HostError("temporary_recovery_archive_invalid")
            image_manifest_raw = second_metadata.get(image_manifest_path)
            if (
                image_manifest_raw is None
                or hashlib.sha256(image_manifest_raw).hexdigest() != image_manifest_hex
            ):
                raise HostError("temporary_recovery_archive_invalid")
            try:
                image_manifest = json.loads(
                    image_manifest_raw, object_pairs_hook=object_without_duplicates
                )
            except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
                raise HostError("temporary_recovery_archive_invalid") from exc
            if (
                not isinstance(image_manifest, dict)
                or set(image_manifest) != {"schemaVersion", "mediaType", "config", "layers"}
                or image_manifest.get("schemaVersion") != 2
                or image_manifest.get("mediaType") != "application/vnd.oci.image.manifest.v1+json"
            ):
                raise HostError("temporary_recovery_archive_invalid")
            config_descriptor = image_manifest["config"]
            if (
                not isinstance(config_descriptor, dict)
                or set(config_descriptor) != {"mediaType", "digest", "size"}
                or config_descriptor.get("mediaType") != "application/vnd.oci.image.config.v1+json"
                or config_descriptor.get("digest") != f"sha256:{expected_id}"
                or type(config_descriptor.get("size")) is not int
                or not 1 <= config_descriptor["size"] <= MAX_TEMPORARY_ARCHIVE_MEMBER_BYTES
                or entries.get(config_path) != ("file", config_descriptor["size"])
            ):
                raise HostError("temporary_recovery_archive_invalid")
            layer_descriptors = image_manifest.get("layers")
            if not isinstance(layer_descriptors, list) or not 1 <= len(layer_descriptors) <= 128:
                raise HostError("temporary_recovery_archive_invalid")
            expected_layers: list[str] = []
            for layer in layer_descriptors:
                if (
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
                    or not 1 <= layer["size"] <= MAX_TEMPORARY_ARCHIVE_MEMBER_BYTES
                ):
                    raise HostError("temporary_recovery_archive_invalid")
                layer_path = f"blobs/sha256/{layer['digest'].removeprefix('sha256:')}"
                if entries.get(layer_path) != ("file", layer["size"]):
                    raise HostError("temporary_recovery_archive_invalid")
                expected_layers.append(layer_path)
            if len(set(expected_layers)) != len(expected_layers) or layers != expected_layers:
                raise HostError("temporary_recovery_archive_invalid")
            expected_files = {
                "manifest.json",
                "oci-layout",
                "index.json",
                image_manifest_path,
                config_path,
                *expected_layers,
            }
            if (
                len(expected_files) != 5 + len(expected_layers)
                or files != expected_files
                or directories != {"blobs", "blobs/sha256"}
            ):
                raise HostError("temporary_recovery_archive_invalid")
        else:
            if config_path != f"{expected_id}.json" or "repositories" not in files:
                raise HostError("temporary_recovery_archive_invalid")
            layer_ids: list[str] = []
            layer_dirs: set[str] = set()
            for layer_path in layers:
                match = re.fullmatch(r"([0-9a-f]{64})/layer\.tar", layer_path)
                if match is None:
                    raise HostError("temporary_recovery_archive_invalid")
                layer_id = match.group(1)
                if layer_id in layer_ids:
                    raise HostError("temporary_recovery_archive_invalid")
                layer_ids.append(layer_id)
                layer_dirs.add(layer_id)
            if not layer_ids or entries.get(config_path, (None, 0))[0] != "file":
                raise HostError("temporary_recovery_archive_invalid")
            repositories = parsed_json("repositories")
            repository, tag = manifest["image"]["repo_tag"].rsplit(":", 1)
            repository_values = {expected_id, layer_ids[-1]}
            if (
                not isinstance(repositories, dict)
                or set(repositories) != {repository}
                or not isinstance(repositories[repository], dict)
                or set(repositories[repository]) != {tag}
                or not isinstance(repositories[repository][tag], str)
                or repositories[repository][tag] not in repository_values
            ):
                raise HostError("temporary_recovery_archive_invalid")
            expected_files = {
                "manifest.json",
                "repositories",
                config_path,
                *layers,
            }
            expected_directories: set[str] = set()
            version_names: set[str] = set()
            for layer_id in layer_ids:
                expected_directories.add(layer_id)
                expected_files.update({f"{layer_id}/VERSION", f"{layer_id}/json"})
                version_names.add(f"{layer_id}/VERSION")
                if (
                    entries.get(f"{layer_id}/json", (None, 0))[0] != "file"
                    or entries[f"{layer_id}/json"][1] > MAX_TEMPORARY_ARCHIVE_MANIFEST_BYTES
                ):
                    raise HostError("temporary_recovery_archive_invalid")
            if files != expected_files or directories != expected_directories:
                raise HostError("temporary_recovery_archive_invalid")
            second_entries, versions = scan_archive(version_names)
            if entries != second_entries or any(
                versions.get(name) not in {b"1.0", b"1.0\n"} for name in version_names
            ):
                raise HostError("temporary_recovery_archive_invalid")

        check_verification_budget()
        final_metadata = os.fstat(archive_fd)
        if identity != (
            final_metadata.st_dev,
            final_metadata.st_ino,
            final_metadata.st_size,
            final_metadata.st_mtime_ns,
            final_metadata.st_ctime_ns,
        ):
            raise HostError("temporary_recovery_archive_invalid")
    except OSError as exc:
        raise HostError("temporary_recovery_archive_unavailable") from exc
    finally:
        os.close(archive_fd)


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
        "operation_id",
        "operation_kind",
        "phase",
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
    command: list[str],
    *,
    timeout: float,
    cwd: Path | None = None,
    memory_reserve_kib: int | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run one fixed argv with bounded output, duration, and optional memory sampling."""

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

    def require_memory_reserve() -> None:
        if memory_reserve_kib is None:
            return
        try:
            available = _memory_available_kib()
        except HostError:
            kill_and_reap()
            raise
        if available < memory_reserve_kib:
            kill_and_reap()
            raise HostError("host_memory_reserve_breached")

    poll_interval = (
        TEMPORARY_RECOVERY_MEMORY_SAMPLE_INTERVAL_SECONDS
        if memory_reserve_kib is not None
        else None
    )

    try:
        require_memory_reserve()
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
            require_memory_reserve()
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                kill_and_reap()
                raise HostError("host_command_timeout")
            wait_for = remaining if poll_interval is None else min(remaining, poll_interval)
            events = selector.select(wait_for)
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
        while True:
            require_memory_reserve()
            remaining = max(0.0, deadline - time.monotonic())
            if remaining <= 0:
                kill_and_reap()
                raise HostError("host_command_timeout")
            wait_for = remaining if poll_interval is None else min(remaining, poll_interval)
            try:
                return_code = process.wait(timeout=wait_for)
                break
            except subprocess.TimeoutExpired:
                continue
        try:
            stdout = bytes(outputs["stdout"]).decode()
            stderr = bytes(outputs["stderr"]).decode()
        except UnicodeDecodeError as exc:
            raise HostError("host_command_output_invalid") from exc
    except OSError as exc:
        kill_and_reap()
        raise HostError("host_command_failed") from exc
    finally:
        try:
            if process is not None and process.poll() is None:
                kill_and_reap()
        finally:
            if selector is not None:
                selector.close()
            if process is not None:
                for stream in (process.stdout, process.stderr):
                    if stream is not None:
                        stream.close()
    if return_code != 0:
        raise HostError("host_command_failed")
    return subprocess.CompletedProcess(command, return_code, stdout, stderr)


def _run_with_memory_reserve(
    command: list[str],
    *,
    timeout: float,
    cwd: Path | None = None,
    memory_reserve_kib: int | None = None,
) -> subprocess.CompletedProcess[str]:
    """Preserve the legacy call shape when the optional reserve sampler is not requested."""

    options: dict[str, Any] = {"timeout": timeout}
    if cwd is not None:
        options["cwd"] = cwd
    if memory_reserve_kib is not None:
        options["memory_reserve_kib"] = memory_reserve_kib
    return _run(command, **options)


def _call_with_memory_reserve(
    function: Any,
    *arguments: Any,
    memory_reserve_kib: int | None,
    **options: Any,
) -> Any:
    """Keep existing injectable helper seams unchanged when reserve sampling is absent."""

    if memory_reserve_kib is None:
        return function(*arguments, **options)
    return function(*arguments, **options, memory_reserve_kib=memory_reserve_kib)


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


def _image_revision(image_ref: str, *, memory_reserve_kib: int | None = None) -> str:
    """Read the OCI source revision label from a pulled image."""

    revision = _run_with_memory_reserve(
        [
            "docker",
            "image",
            "inspect",
            "--format",
            '{{index .Config.Labels "org.opencontainers.image.revision"}}',
            image_ref,
        ],
        timeout=30,
        memory_reserve_kib=memory_reserve_kib,
    ).stdout.strip()
    if REVISION_PATTERN.fullmatch(revision) is None:
        raise HostError("image_revision_unavailable")
    return revision


def _image_id(image_ref: str, *, memory_reserve_kib: int | None = None) -> str:
    """Read the immutable Docker image ID for an already loaded local image."""

    image_id = _run_with_memory_reserve(
        ["docker", "image", "inspect", "--format", "{{.Id}}", image_ref],
        timeout=30,
        memory_reserve_kib=memory_reserve_kib,
    ).stdout.strip()
    if IMAGE_ID_PATTERN.fullmatch(image_id) is None:
        raise HostError("image_id_unavailable")
    return image_id


def _image_platform(image_ref: str, *, memory_reserve_kib: int | None = None) -> str:
    """Require the published archive to contain the production Linux amd64 image."""

    platform = _run_with_memory_reserve(
        ["docker", "image", "inspect", "--format", "{{.Os}}/{{.Architecture}}", image_ref],
        timeout=30,
        memory_reserve_kib=memory_reserve_kib,
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


def _image_schema(image_ref: str, *, memory_reserve_kib: int | None = None) -> int:
    value = _run_with_memory_reserve(
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
        memory_reserve_kib=memory_reserve_kib,
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
    memory_reserve_kib: int | None = None,
) -> str:
    return _run_with_memory_reserve(
        [*_compose_prefix(compose_file), *arguments],
        timeout=timeout,
        memory_reserve_kib=memory_reserve_kib,
    ).stdout.strip()


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
    memory_reserve_kib: int | None = None,
) -> str:
    """Start a verified image without allowing Compose to pull a mutable fallback tag."""

    arguments = ["up", "--detach", "--no-build"]
    if force_recreate:
        arguments.append("--force-recreate")
    if _is_release_record(record) or record.get("operation_kind") == "temporary_recovery":
        arguments.extend(("--pull", "never"))
    arguments.append("app")
    return _compose(
        *arguments,
        timeout=timeout,
        compose_file=compose_file,
        memory_reserve_kib=memory_reserve_kib,
    )


def _memory_available_kib() -> int:
    """Read the one host memory counter used by the temporary transition admission guard."""

    try:
        with Path("/proc/meminfo").open("rb") as stream:
            raw = stream.read(65_537)
    except OSError as exc:
        raise HostError("host_memory_unavailable") from exc
    if len(raw) > 65_536:
        raise HostError("host_memory_unavailable")
    matches = re.findall(rb"(?m)^MemAvailable:\s+([0-9]+)\s+kB\s*$", raw)
    if len(matches) != 1:
        raise HostError("host_memory_unavailable")
    return int(matches[0])


def _require_temporary_service_reserve() -> int:
    available = _memory_available_kib()
    if available < TEMPORARY_RECOVERY_AVAILABLE_RESERVE_KIB:
        raise HostError("host_memory_reserve_breached")
    return available


def _temporary_image_reference_id(
    image_ref: str, *, memory_reserve_kib: int | None = None
) -> str | None:
    """Read a fixed, validated local tag without exposing image configuration."""

    output = _run_with_memory_reserve(
        [
            "docker",
            "image",
            "ls",
            "--all",
            "--no-trunc",
            "--format",
            "{{.ID}}",
            "--filter",
            f"reference={image_ref}",
        ],
        timeout=30,
        memory_reserve_kib=memory_reserve_kib,
    ).stdout.strip()
    if not output:
        return None
    identifiers = output.splitlines()
    if len(identifiers) != 1 or IMAGE_ID_PATTERN.fullmatch(identifiers[0]) is None:
        raise HostError("temporary_recovery_image_tag_ambiguous")
    return identifiers[0]


def _read_container_process_status(pid: int) -> dict[str, Any]:
    """Read bounded PID, namespace, UID, and capability facts for one Docker-top PID."""

    if type(pid) is not int or pid <= 1:
        raise HostError("temporary_recovery_process_profile_invalid")
    path = Path("/proc") / str(pid) / "status"
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    except OSError as exc:
        raise HostError("temporary_recovery_process_race") from exc
    try:
        chunks: list[bytes] = []
        total = 0
        while total <= 16_384:
            chunk = os.read(descriptor, min(4_096, 16_385 - total))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
        raw = b"".join(chunks)
        if len(raw) > 16_384:
            raise HostError("temporary_recovery_process_profile_invalid")
    except OSError as exc:
        raise HostError("temporary_recovery_process_race") from exc
    finally:
        os.close(descriptor)

    fields: dict[str, str] = {}
    for line in raw.splitlines():
        name, separator, value = line.partition(b":")
        if separator and name in {
            b"Name",
            b"Pid",
            b"PPid",
            b"Uid",
            b"NSpid",
            b"CapPrm",
            b"CapEff",
            b"CapBnd",
            b"CapAmb",
        }:
            key = name.decode("ascii")
            if key in fields:
                raise HostError("temporary_recovery_process_profile_invalid")
            fields[key] = value.decode("ascii", errors="strict").strip()
    try:
        pid_value = int(fields["Pid"])
        ppid = int(fields["PPid"])
        uids = tuple(int(value) for value in fields["Uid"].split())
        namespace_pids = tuple(int(value) for value in fields["NSpid"].split())
        caps = {name: int(fields[name], 16) for name in ("CapPrm", "CapEff", "CapBnd", "CapAmb")}
    except (KeyError, UnicodeDecodeError, ValueError) as exc:
        raise HostError("temporary_recovery_process_profile_invalid") from exc
    if (
        pid_value != pid
        or ppid < 0
        or len(uids) != 4
        or len(namespace_pids) < 1
        or any(value <= 0 for value in namespace_pids)
        or not fields.get("Name")
    ):
        raise HostError("temporary_recovery_process_profile_invalid")
    return {
        "pid": pid_value,
        "ppid": ppid,
        "uid": uids[1],
        "uids": uids,
        "name": fields["Name"],
        "namespace_pid": namespace_pids[-1],
        **caps,
    }


def _temporary_process_snapshot(
    container_id: str,
    *,
    memory_reserve_kib: int | None,
) -> dict[int, dict[str, Any]]:
    output = _run_with_memory_reserve(
        ["docker", "top", container_id, "-eo", "pid,ppid,uid,comm"],
        timeout=15,
        memory_reserve_kib=memory_reserve_kib,
    ).stdout.strip()
    lines = output.splitlines()
    if not lines or [field.upper() for field in lines[0].split()] != [
        "PID",
        "PPID",
        "UID",
        "COMMAND",
    ]:
        raise HostError("temporary_recovery_process_profile_invalid")
    processes: dict[int, dict[str, Any]] = {}
    for line in lines[1:]:
        fields = line.split()
        if len(fields) != 4 or not all(value.isdecimal() for value in fields[:3]):
            raise HostError("temporary_recovery_process_profile_invalid")
        pid, ppid, uid = (int(value) for value in fields[:3])
        if pid in processes:
            raise HostError("temporary_recovery_process_profile_invalid")
        process = _read_container_process_status(pid)
        if process["ppid"] != ppid or process["uid"] != uid or process["name"] != fields[3]:
            raise HostError("temporary_recovery_process_race")
        processes[pid] = process
    if not processes:
        raise HostError("temporary_recovery_process_profile_invalid")
    return processes


def _is_temporary_healthcheck_process(process: dict[str, Any]) -> bool:
    """Recognize only an outsider root Python process as a possible transient healthcheck."""

    return (
        process["uid"] == 0
        and process["namespace_pid"] != 1
        and process["name"] in {"python", "python3"}
        and process["CapPrm"] == 0xC0
        and process["CapEff"] == 0xC0
        and process["CapBnd"] == 0xC0
        and process["CapAmb"] == 0
    )


def _wait_out_temporary_healthcheck(memory_reserve_kib: int | None) -> None:
    """Wait one fixed Compose healthcheck timeout, sampling the reserve while it expires."""

    deadline = time.monotonic() + TEMPORARY_RECOVERY_HEALTHCHECK_TIMEOUT_SECONDS + 0.25
    while True:
        if memory_reserve_kib is not None:
            available = _memory_available_kib()
            if available < memory_reserve_kib:
                raise HostError("host_memory_reserve_breached")
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return
        time.sleep(min(TEMPORARY_RECOVERY_MEMORY_SAMPLE_INTERVAL_SECONDS, remaining))


def _assert_container_process_profile(
    container_id: str,
    init_pid: int,
    process_profile: str,
    *,
    memory_reserve_kib: int | None,
) -> None:
    if process_profile not in {
        "retained_supervisor_app_disabled",
        "retained_supervisor_app_invited",
        "temporary_app_pid1",
    }:
        raise HostError("temporary_recovery_process_profile_invalid")

    def is_pid1_descendant(processes: dict[int, dict[str, Any]], pid: int) -> bool:
        seen: set[int] = set()
        current = processes.get(pid)
        while current is not None:
            parent = current["ppid"]
            if parent == init_pid:
                return True
            if parent in seen:
                raise HostError("temporary_recovery_process_profile_invalid")
            seen.add(parent)
            current = processes.get(parent)
        return False

    def has_unprivileged_caps(process: dict[str, Any], uid: int) -> bool:
        return (
            process["uid"] == uid
            and process.get("uids") == (uid, uid, uid, uid)
            and process["CapPrm"] == 0
            and process["CapEff"] == 0
            and process["CapBnd"] == 0xC0
            and process["CapAmb"] == 0
        )

    def validate(processes: dict[int, dict[str, Any]]) -> list[int]:
        init = processes.get(init_pid)
        if init is None or init["namespace_pid"] != 1:
            raise HostError("temporary_recovery_worker_present")
        if process_profile == "temporary_app_pid1":
            if (
                init["name"] != "stock-probs"
                or init["uid"] != 10001
                or init.get("uids") != (10001, 10001, 10001, 10001)
                or any(init[key] != 0 for key in ("CapPrm", "CapEff", "CapAmb"))
                or init["CapBnd"] != 0xC0
            ):
                raise HostError("temporary_recovery_process_profile_invalid")
            expected_pids = {init_pid}
        else:
            if (
                init["name"] not in {"python", "python3"}
                or init["uid"] != 0
                or init.get("uids") != (0, 0, 0, 0)
                or any(init[key] != 0xC0 for key in ("CapPrm", "CapEff", "CapBnd"))
                or init["CapAmb"] != 0
            ):
                raise HostError("temporary_recovery_process_profile_invalid")
            app_relays = [
                process
                for pid, process in processes.items()
                if pid != init_pid
                and process["ppid"] == init_pid
                and process["name"] in {"python", "python3"}
                and has_unprivileged_caps(process, 10001)
            ]
            if len(app_relays) != 1 or app_relays[0]["namespace_pid"] == 1:
                raise HostError("temporary_recovery_process_profile_invalid")
            app_children = [
                process
                for process in processes.values()
                if process["ppid"] == app_relays[0]["pid"]
                and process["name"] in {"python", "python3", "stock-probs"}
                and has_unprivileged_caps(process, 10001)
            ]
            if len(app_children) != 1 or app_children[0]["namespace_pid"] == 1:
                raise HostError("temporary_recovery_process_profile_invalid")
            expected_pids = {init_pid, app_relays[0]["pid"], app_children[0]["pid"]}

            if process_profile == "retained_supervisor_app_invited":
                worker_relays = [
                    process
                    for process in processes.values()
                    if process["ppid"] == init_pid
                    and process["name"] in {"python", "python3"}
                    and has_unprivileged_caps(process, 10002)
                ]
                if len(worker_relays) != 1:
                    raise HostError("temporary_recovery_process_profile_invalid")
                worker_children = [
                    process
                    for process in processes.values()
                    if process["ppid"] == worker_relays[0]["pid"]
                    and process["name"] == "opencode"
                    and has_unprivileged_caps(process, 10002)
                ]
                if len(worker_children) != 1:
                    raise HostError("temporary_recovery_process_profile_invalid")
                expected_pids.update({worker_relays[0]["pid"], worker_children[0]["pid"]})

        healthchecks = [
            pid
            for pid, process in processes.items()
            if pid not in expected_pids
            and not is_pid1_descendant(processes, pid)
            and _is_temporary_healthcheck_process(process)
        ]
        unexpected = set(processes) - expected_pids - set(healthchecks)
        if unexpected or len(healthchecks) > 1:
            raise HostError("temporary_recovery_worker_present")
        return healthchecks

    first = _temporary_process_snapshot(container_id, memory_reserve_kib=memory_reserve_kib)
    transient = validate(first)
    if not transient:
        return
    _wait_out_temporary_healthcheck(memory_reserve_kib)
    second = _temporary_process_snapshot(container_id, memory_reserve_kib=memory_reserve_kib)
    if validate(second):
        raise HostError("temporary_recovery_worker_present")


def _assert_temporary_container_profile(
    compose_snapshot: Path,
    *,
    expected_image_id: str,
    process_profile: str,
    memory_reserve_kib: int | None = None,
) -> str:
    """Verify fixed container settings and the exact app-only or retained process tree."""

    container_id, init_pid = _call_with_memory_reserve(
        _app_container_identity,
        compose_snapshot,
        memory_reserve_kib=memory_reserve_kib,
    )
    template = (
        "{{.Id}}|{{.Image}}|{{.State.Pid}}|{{.State.Running}}|"
        "{{.HostConfig.ReadonlyRootfs}}|{{json .HostConfig.Init}}|{{.Config.User}}|"
        "{{json .HostConfig.SecurityOpt}}|{{json .HostConfig.CapDrop}}|"
        "{{json .HostConfig.CapAdd}}|{{json .HostConfig.PortBindings}}|"
        "{{.HostConfig.Memory}}|{{.HostConfig.NanoCpus}}|{{.HostConfig.PidsLimit}}"
    )
    output = _run_with_memory_reserve(
        ["docker", "inspect", "--format", template, container_id],
        timeout=15,
        memory_reserve_kib=memory_reserve_kib,
    ).stdout.strip()
    parts = output.split("|")
    if (
        len(parts) != 14
        or parts[0] != container_id
        or parts[1] != expected_image_id
        or not parts[2].isdecimal()
        or int(parts[2]) != init_pid
    ):
        raise HostError("temporary_recovery_container_identity_mismatch")
    try:
        init_enabled = json.loads(parts[5])
        security_options = json.loads(parts[7])
        cap_drop = json.loads(parts[8])
        cap_add = json.loads(parts[9])
        port_bindings = json.loads(parts[10])
    except json.JSONDecodeError as exc:
        raise HostError("temporary_recovery_container_profile_invalid") from exc
    expected_ports = {"8000/tcp": [{"HostIp": "127.0.0.1", "HostPort": "8000"}]}
    if (
        parts[3] != "true"
        or parts[4] != "true"
        or (init_enabled is not None and init_enabled is not False)
        or parts[6] != "0:0"
        or security_options != ["no-new-privileges:true"]
        or cap_drop != ["ALL"]
        or not isinstance(cap_add, list)
        or any(not isinstance(capability, str) for capability in cap_add)
        or len(cap_add) != 2
        or set(cap_add) != {"SETUID", "SETGID"}
        or port_bindings != expected_ports
        or parts[11] != str(768 * 1024 * 1024)
        or parts[12] != str(1_000_000_000)
        or parts[13] != "128"
    ):
        raise HostError("temporary_recovery_container_profile_invalid")
    _assert_container_process_profile(
        container_id,
        init_pid,
        process_profile,
        memory_reserve_kib=memory_reserve_kib,
    )
    return container_id


def _stop_app(compose_file: Path | None = None, *, memory_reserve_kib: int | None = None) -> None:
    """Establish and verify the maintenance boundary before a snapshot or schema migration."""

    _compose(
        "stop",
        "app",
        timeout=60,
        compose_file=compose_file,
        memory_reserve_kib=memory_reserve_kib,
    )
    running = _compose(
        "ps",
        "--status",
        "running",
        "--services",
        timeout=30,
        compose_file=compose_file,
        memory_reserve_kib=memory_reserve_kib,
    )
    if "app" in running.split():
        raise HostError("maintenance_boundary_failed")


def _app_container_identity(
    compose_file: Path, *, memory_reserve_kib: int | None = None
) -> tuple[str, int]:
    """Return the exact running Compose app container ID and host PID."""

    container_id = _call_with_memory_reserve(
        _compose,
        "ps",
        "--status",
        "running",
        "--quiet",
        "app",
        timeout=20,
        compose_file=compose_file,
        memory_reserve_kib=memory_reserve_kib,
    )
    if CONTAINER_ID_PATTERN.fullmatch(container_id) is None:
        raise HostError("assistant_app_identity_unavailable")
    result = _call_with_memory_reserve(
        _run,
        [
            "docker",
            "inspect",
            "--format",
            "{{.Id}}|{{.State.Pid}}|{{.State.Running}}",
            container_id,
        ],
        timeout=10,
        memory_reserve_kib=memory_reserve_kib,
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


def _assert_loaded_image(record: dict[str, Any], *, memory_reserve_kib: int | None = None) -> None:
    """Bind Compose to the image identity that was verified during planning."""

    if _is_release_record(record):
        if (
            _call_with_memory_reserve(
                _image_id, record["image_ref"], memory_reserve_kib=memory_reserve_kib
            )
            != record["image_id"]
        ):
            raise HostError("image_id_mismatch")
        if (
            _call_with_memory_reserve(
                _image_revision,
                record["image_ref"],
                memory_reserve_kib=memory_reserve_kib,
            )
            != record["revision"]
        ):
            raise HostError("image_revision_mismatch")
        _call_with_memory_reserve(
            _image_platform,
            record["image_ref"],
            memory_reserve_kib=memory_reserve_kib,
        )
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


def _image_has_recovery_entrypoint(
    image_ref: str, *, memory_reserve_kib: int | None = None
) -> bool:
    """Require the fixed UID-dropping app-only entrypoint in the recovery image."""

    try:
        output = _run_with_memory_reserve(
            [
                "docker",
                "image",
                "inspect",
                "--format",
                "{{json .Config.Entrypoint}}|{{json .Config.Cmd}}",
                image_ref,
            ],
            timeout=30,
            memory_reserve_kib=memory_reserve_kib,
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


def _health_check(
    *,
    assistant_rollout_mode: str | None = None,
    memory_reserve_kib: int | None = None,
) -> dict[str, Any]:
    """Wait within the existing budget for app health and the requested worker state."""

    if assistant_rollout_mode is not None and assistant_rollout_mode not in ASSISTANT_ROLLOUT_MODES:
        raise HostError("assistant_rollout_invalid")
    for _ in range(HEALTH_ATTEMPTS):
        try:
            result = _run_with_memory_reserve(
                ["curl", "--fail", "--silent", "--show-error", "--max-time", "3", HEALTH_URL],
                timeout=5,
                memory_reserve_kib=memory_reserve_kib,
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
                    if assistant_rollout_mode is not None:
                        _require_assistant_ready(
                            health, assistant_rollout_mode, schema_version=schema
                        )
                    return health
        except HostError as exc:
            if exc.code in {"host_memory_reserve_breached", "host_memory_unavailable"}:
                raise
        except (json.JSONDecodeError, TypeError, ValueError):
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
    response = {
        "status": "ok",
        "service": PROJECT_NAME,
        "current": current,
        "failed": _read_json(FAILED_RECORD),
        "loopback_only": True,
    }
    temporary = _temporary_operation_view()
    if temporary is not None:
        response["temporary_recovery"] = temporary
    return response


def _inspect() -> dict[str, Any]:
    _ensure_layout()
    current = _read_json(CURRENT_RECORD)
    health: dict[str, Any] = {"status": "unknown"}
    if current is not None:
        try:
            health = _health_check()
        except HostError:
            health = {"status": "unavailable"}
    response = {
        "status": "ok",
        "current": current,
        "failed": _read_json(FAILED_RECORD),
        "health": health,
        "loopback_only": True,
    }
    temporary = _temporary_operation_view()
    if temporary is not None:
        response["temporary_recovery"] = temporary
    return response


_TEMPORARY_RECOVERY_PHASES = frozenset(
    {
        "prepared",
        "verifying_predecessor_schema",
        "loading_archive",
        "archive_verified",
        "tagging_image",
        "image_verified",
        "verifying_backup",
        "backup_verified",
        "stopping_original_app",
        "original_app_stopped",
        "writing_temporary_runtime",
        "recording_temporary_app",
        "starting_temporary_app",
        "verifying_temporary_app",
        "temporary_app_ready",
        "startup_floor_passed",
        "startup_floor_unmet",
        "restore_requested",
        "stopping_temporary_app",
        "temporary_app_stopped",
        "verifying_shared_schema",
        "writing_original_runtime",
        "recording_original_app",
        "starting_original_app",
        "verifying_original_app",
        "restored",
    }
)


def _temporary_operation_record() -> dict[str, Any] | None:
    operation = _read_json(TEMPORARY_RECOVERY_OPERATION)
    if operation is None:
        return None
    if (
        operation.get("operation_kind") != "temporary_recovery"
        or not isinstance(operation.get("operation_id"), str)
        or PLAN_PATTERN.fullmatch(operation["operation_id"]) is None
        or not isinstance(operation.get("phase"), str)
        or operation["phase"] not in _TEMPORARY_RECOVERY_PHASES
        or operation.get("source_revision") != TEMPORARY_RECOVERY_SOURCE_REVISION
        or operation.get("schema_version") != ASSISTANT_MINIMUM_SCHEMA
        or operation.get("compose_digest") != PRODUCTION_PREDECESSOR_COMPOSE_SHA256
        or operation.get("source_manifest_sha256") != TEMPORARY_RECOVERY_SOURCE_MANIFEST_SHA256
        or operation.get("source_context_sha256") != TEMPORARY_RECOVERY_SOURCE_CONTEXT_SHA256
        or operation.get("base_revision") != PAIR_BASE_REVISION
        or operation.get("migration_sha256") != PAIR_MIGRATION_SHA256
        or operation.get("overlay_sha256") != TEMPORARY_RECOVERY_OVERLAY_SHA256
        or operation.get("original_compose_revision") != PRODUCTION_PREDECESSOR_REVISION
        or not isinstance(operation.get("image_id"), str)
        or IMAGE_ID_PATTERN.fullmatch(operation["image_id"]) is None
        or operation["image_id"] in {PRODUCTION_PREDECESSOR_IMAGE_ID, PROTECTED_A9_IMAGE_ID}
        or operation.get("image_ref")
        != f"{LOCAL_IMAGE_REPOSITORY}:temporary-recovery-{operation['operation_id']}"
        or not isinstance(operation.get("archive_sha256"), str)
        or DIGEST_PATTERN.fullmatch(operation["archive_sha256"]) is None
        or type(operation.get("archive_size")) is not int
        or not 1 <= operation["archive_size"] <= MAX_RELEASE_ARCHIVE_BYTES
        or not isinstance(operation.get("manifest_sha256"), str)
        or DIGEST_PATTERN.fullmatch(operation["manifest_sha256"]) is None
        or not isinstance(operation.get("original_record"), dict)
    ):
        raise HostError("temporary_recovery_state_invalid")
    return operation


def _temporary_operation_view() -> dict[str, Any] | None:
    operation = _temporary_operation_record()
    if operation is None:
        return None
    view: dict[str, Any] = {
        "operation_kind": "temporary_recovery",
        "operation_id": operation["operation_id"],
        "phase": operation["phase"],
        "image_id": operation.get("image_id"),
        "image_ref": operation.get("image_ref"),
        "startup_floor_kib": operation.get("startup_floor_kib"),
        "start_admission_allowed": operation.get("start_admission_allowed"),
    }
    if isinstance(operation.get("failure_code"), str):
        view["failure_code"] = operation["failure_code"]
    return view


def _ensure_no_active_temporary_recovery() -> None:
    operation = _temporary_operation_record()
    if operation is not None and operation["phase"] != "restored":
        raise HostError("temporary_recovery_active")


def _write_temporary_recovery_phase(
    operation: dict[str, Any], phase: str, **updates: object
) -> None:
    if phase not in _TEMPORARY_RECOVERY_PHASES:
        raise HostError("temporary_recovery_state_invalid")
    operation.update(updates)
    operation["phase"] = phase
    operation["updated_at"] = _utc_now()
    _write_json(TEMPORARY_RECOVERY_OPERATION, operation)
    _audit(
        "temporary_recovery",
        phase,
        operation_id=operation.get("operation_id"),
        operation_kind="temporary_recovery",
        phase=phase,
    )


def _record_temporary_recovery_failure(operation: dict[str, Any], error: HostError) -> None:
    operation["failure_code"] = error.code
    operation["failed_at"] = _utc_now()
    with suppress(HostError):
        _write_json(TEMPORARY_RECOVERY_OPERATION, operation)


def _protected_production_image_refs() -> tuple[str, str]:
    return (
        _local_image_ref(PRODUCTION_PREDECESSOR_REVISION),
        _local_recovery_image_ref(PRODUCTION_PREDECESSOR_REVISION),
    )


def _assert_protected_production_images(*, memory_reserve_kib: int | None = None) -> None:
    candidate_ref, recovery_ref = _protected_production_image_refs()
    if (
        _call_with_memory_reserve(_image_id, candidate_ref, memory_reserve_kib=memory_reserve_kib)
        != PRODUCTION_PREDECESSOR_IMAGE_ID
        or _call_with_memory_reserve(_image_id, recovery_ref, memory_reserve_kib=memory_reserve_kib)
        != PROTECTED_A9_IMAGE_ID
    ):
        raise HostError("temporary_recovery_protected_image_mismatch")


def _temporary_compose_snapshot(
    current: dict[str, Any], *, memory_reserve_kib: int | None = None
) -> Path:
    """Require the retained original snapshot and live Compose bytes to match 5ad exactly."""

    if (
        current.get("revision") != PRODUCTION_PREDECESSOR_REVISION
        or current.get("image_id") != PRODUCTION_PREDECESSOR_IMAGE_ID
        or current.get("schema_version") != ASSISTANT_MINIMUM_SCHEMA
        or current.get("compose_digest") != PRODUCTION_PREDECESSOR_COMPOSE_SHA256
        or current.get("image_ref") != _local_image_ref(PRODUCTION_PREDECESSOR_REVISION)
        or not _is_release_record(current)
        or current.get("release_role", "candidate") != "candidate"
    ):
        raise HostError("temporary_recovery_predecessor_mismatch")
    release = _read_json(RELEASE_ROOT / f"{PRODUCTION_PREDECESSOR_REVISION}.json")
    if (
        release is None
        or release.get("revision") != PRODUCTION_PREDECESSOR_REVISION
        or release.get("image_id") != PRODUCTION_PREDECESSOR_IMAGE_ID
        or release.get("schema_version") != ASSISTANT_MINIMUM_SCHEMA
        or release.get("compose_digest") != PRODUCTION_PREDECESSOR_COMPOSE_SHA256
        or release.get("image_ref") != _local_image_ref(PRODUCTION_PREDECESSOR_REVISION)
        or not _is_release_record(release)
    ):
        raise HostError("temporary_recovery_predecessor_record_invalid")
    for key in (
        "transport",
        "image_ref",
        "image_digest",
        "archive_sha256",
        "image_id",
        "platform",
        "archive_size",
        "schema_version",
        "compose_digest",
    ):
        if current.get(key) != release.get(key):
            raise HostError("temporary_recovery_predecessor_record_invalid")
    try:
        _assert_image_record(current)
        _assert_image_record(release)
        _assert_loaded_image(current, memory_reserve_kib=memory_reserve_kib)
        _assert_loaded_image(release, memory_reserve_kib=memory_reserve_kib)
        snapshot = _compose_snapshot_path(PRODUCTION_PREDECESSOR_REVISION)
        content = _read_compose_snapshot(snapshot)
        live_digest = _compose_digest()
    except HostError as exc:
        raise HostError("temporary_recovery_predecessor_unavailable") from exc
    if (
        hashlib.sha256(content).hexdigest() != PRODUCTION_PREDECESSOR_COMPOSE_SHA256
        or live_digest != PRODUCTION_PREDECESSOR_COMPOSE_SHA256
    ):
        raise HostError("temporary_recovery_compose_mismatch")
    return snapshot


def _temporary_archive_stage_id(
    manifest: dict[str, Any], *, memory_reserve_kib: int | None = None
) -> str | None:
    image = manifest["image"]
    image_ref = image["repo_tag"]
    actual = _call_with_memory_reserve(
        _temporary_image_reference_id, image_ref, memory_reserve_kib=memory_reserve_kib
    )
    if actual is not None and actual != image["image_id"]:
        raise HostError("temporary_recovery_build_tag_collision")
    return actual


def _assert_temporary_image(
    manifest: dict[str, Any],
    image_ref: str,
    *,
    memory_reserve_kib: int | None = None,
) -> None:
    expected = manifest["image"]
    if (
        _call_with_memory_reserve(_image_id, image_ref, memory_reserve_kib=memory_reserve_kib)
        != expected["image_id"]
        or _call_with_memory_reserve(
            _image_revision, image_ref, memory_reserve_kib=memory_reserve_kib
        )
        != TEMPORARY_RECOVERY_SOURCE_REVISION
        or _call_with_memory_reserve(
            _image_platform, image_ref, memory_reserve_kib=memory_reserve_kib
        )
        != "linux/amd64"
        or _call_with_memory_reserve(
            _image_schema, image_ref, memory_reserve_kib=memory_reserve_kib
        )
        != ASSISTANT_MINIMUM_SCHEMA
        or not _call_with_memory_reserve(
            _image_has_recovery_entrypoint,
            image_ref,
            memory_reserve_kib=memory_reserve_kib,
        )
    ):
        raise HostError("temporary_recovery_image_contract_mismatch")


def _assert_temporary_recovery_source_health(
    current: dict[str, Any], *, memory_reserve_kib: int
) -> None:
    if (
        current.get("assistant_rollout_mode") != "invited"
        or _call_with_memory_reserve(
            _image_id, current["image_ref"], memory_reserve_kib=memory_reserve_kib
        )
        != PRODUCTION_PREDECESSOR_IMAGE_ID
    ):
        raise HostError("temporary_recovery_predecessor_unready")
    health = _health_check(
        assistant_rollout_mode="invited",
        memory_reserve_kib=memory_reserve_kib,
    )
    if health.get("schema_version") != ASSISTANT_MINIMUM_SCHEMA:
        raise HostError("temporary_recovery_predecessor_unready")


def _temporary_active_record(operation: dict[str, Any], *, status: str) -> dict[str, Any]:
    return {
        "operation_kind": "temporary_recovery",
        "operation_id": operation["operation_id"],
        "status": status,
        "revision": TEMPORARY_RECOVERY_SOURCE_REVISION,
        "image_ref": operation["image_ref"],
        "image_digest": operation["archive_sha256"],
        "archive_sha256": operation["archive_sha256"],
        "archive_size": operation["archive_size"],
        "image_id": operation["image_id"],
        "transport": "temporary_recovery",
        "platform": "linux/amd64",
        "schema_version": ASSISTANT_MINIMUM_SCHEMA,
        "assistant_rollout_mode": "disabled",
        "compose_digest": operation["compose_digest"],
        "manifest_sha256": operation["manifest_sha256"],
        "source_manifest_sha256": TEMPORARY_RECOVERY_SOURCE_MANIFEST_SHA256,
        "source_context_sha256": TEMPORARY_RECOVERY_SOURCE_CONTEXT_SHA256,
        "base_revision": PAIR_BASE_REVISION,
        "migration_sha256": PAIR_MIGRATION_SHA256,
        "overlay_sha256": TEMPORARY_RECOVERY_OVERLAY_SHA256,
        "started_at": operation["created_at"],
    }


def _plan_deploy(
    revision: str,
    expected_image_digest: str,
    expected_image_id: str | None = None,
    expected_pair_manifest_sha256: str | None = None,
) -> dict[str, Any]:
    with _exclusive_lock():
        _ensure_layout()
        _ensure_no_active_temporary_recovery()
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


def _database_schema(
    image_ref: str,
    *,
    compose_file: Path | None = None,
    prepare_runtime: bool = True,
    memory_reserve_kib: int | None = None,
) -> int:
    """Read the actual volume schema without importing the app or running migrations."""

    if prepare_runtime:
        _runtime_file(image_ref)
    value = _call_with_memory_reserve(
        _compose,
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
        memory_reserve_kib=memory_reserve_kib,
    )
    if not value.isdigit() or not 1 <= int(value) <= 100:
        raise HostError("database_schema_unavailable")
    return int(value)


def _verified_backup(
    image_ref: str,
    revision: str,
    *,
    compose_file: Path | None = None,
    memory_reserve_kib: int | None = None,
) -> dict[str, Any]:
    name = _backup_name(revision)
    _runtime_file(image_ref)
    output = _call_with_memory_reserve(
        _compose,
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
        memory_reserve_kib=memory_reserve_kib,
    )
    # The command is intentionally synchronous so the signed archive is complete before the
    # helper performs any migration or starts the new application image.
    try:
        value = json.loads(output)
    except json.JSONDecodeError as exc:
        raise HostError("backup_unverified") from exc
    expected_schema = _call_with_memory_reserve(
        _image_schema, image_ref, memory_reserve_kib=memory_reserve_kib
    )
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
    verification = _call_with_memory_reserve(
        _compose,
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
        memory_reserve_kib=memory_reserve_kib,
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
        _ensure_no_active_temporary_recovery()
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
        _ensure_no_active_temporary_recovery()
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
        _ensure_no_active_temporary_recovery()
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
            health = _health_check(assistant_rollout_mode=mode)
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
                    disabled_health = _health_check(assistant_rollout_mode="disabled")
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


def _start_temporary_recovery() -> dict[str, Any]:
    """Start the separately approved app-only baseline without creating release provenance."""

    with _exclusive_lock():
        _ensure_layout()
        if _read_json(TEMPORARY_RECOVERY_OPERATION) is not None:
            raise HostError("temporary_recovery_already_recorded")
        current = _read_json(CURRENT_RECORD)
        if current is None:
            raise HostError("temporary_recovery_predecessor_unavailable")
        initial_available = _require_temporary_service_reserve()
        compose_snapshot = _temporary_compose_snapshot(
            current,
            memory_reserve_kib=TEMPORARY_RECOVERY_AVAILABLE_RESERVE_KIB,
        )
        _assert_protected_production_images(
            memory_reserve_kib=TEMPORARY_RECOVERY_AVAILABLE_RESERVE_KIB
        )
        _assert_temporary_recovery_source_health(
            current, memory_reserve_kib=TEMPORARY_RECOVERY_AVAILABLE_RESERVE_KIB
        )
        _assert_temporary_container_profile(
            compose_snapshot,
            expected_image_id=PRODUCTION_PREDECESSOR_IMAGE_ID,
            process_profile="retained_supervisor_app_invited",
            memory_reserve_kib=TEMPORARY_RECOVERY_AVAILABLE_RESERVE_KIB,
        )
        manifest, manifest_sha256 = _load_temporary_recovery_authorization()
        _assert_temporary_recovery_archive(
            manifest, memory_reserve_kib=TEMPORARY_RECOVERY_AVAILABLE_RESERVE_KIB
        )
        stage_id = _temporary_archive_stage_id(
            manifest, memory_reserve_kib=TEMPORARY_RECOVERY_AVAILABLE_RESERVE_KIB
        )
        operation_id = secrets.token_hex(16)
        temporary_image_ref = f"{LOCAL_IMAGE_REPOSITORY}:temporary-recovery-{operation_id}"
        if (
            _temporary_image_reference_id(
                temporary_image_ref,
                memory_reserve_kib=TEMPORARY_RECOVERY_AVAILABLE_RESERVE_KIB,
            )
            is not None
        ):
            raise HostError("temporary_recovery_operation_tag_collision")
        image = manifest["image"]
        operation: dict[str, Any] = {
            "operation_kind": "temporary_recovery",
            "operation_id": operation_id,
            "phase": "prepared",
            "created_at": _utc_now(),
            "manifest_sha256": manifest_sha256,
            "source_manifest_sha256": TEMPORARY_RECOVERY_SOURCE_MANIFEST_SHA256,
            "source_revision": TEMPORARY_RECOVERY_SOURCE_REVISION,
            "source_context_sha256": TEMPORARY_RECOVERY_SOURCE_CONTEXT_SHA256,
            "base_revision": PAIR_BASE_REVISION,
            "migration_sha256": PAIR_MIGRATION_SHA256,
            "overlay_sha256": TEMPORARY_RECOVERY_OVERLAY_SHA256,
            "archive_sha256": image["archive_sha256"],
            "archive_size": image["archive_size"],
            "image_id": image["image_id"],
            "build_tag": image["repo_tag"],
            "image_ref": temporary_image_ref,
            "schema_version": ASSISTANT_MINIMUM_SCHEMA,
            "compose_digest": PRODUCTION_PREDECESSOR_COMPOSE_SHA256,
            "original_record": current,
            "original_compose_revision": PRODUCTION_PREDECESSOR_REVISION,
            "initial_available_kib": initial_available,
            "backup": None,
        }
        _write_temporary_recovery_phase(operation, "prepared")
        try:
            available = _require_temporary_service_reserve()
            _write_temporary_recovery_phase(
                operation,
                "verifying_predecessor_schema",
                available_kib=available,
            )
            if (
                _database_schema(
                    current["image_ref"],
                    compose_file=compose_snapshot,
                    prepare_runtime=False,
                    memory_reserve_kib=TEMPORARY_RECOVERY_AVAILABLE_RESERVE_KIB,
                )
                != ASSISTANT_MINIMUM_SCHEMA
            ):
                raise HostError("temporary_recovery_schema_mismatch")
            if stage_id is None:
                available = _require_temporary_service_reserve()
                _write_temporary_recovery_phase(
                    operation, "loading_archive", available_kib=available
                )
                _run(
                    ["docker", "load", "--input", str(TEMPORARY_RECOVERY_ARCHIVE)],
                    timeout=300,
                    memory_reserve_kib=TEMPORARY_RECOVERY_AVAILABLE_RESERVE_KIB,
                )
                if (
                    _temporary_image_reference_id(
                        image["repo_tag"],
                        memory_reserve_kib=TEMPORARY_RECOVERY_AVAILABLE_RESERVE_KIB,
                    )
                    != image["image_id"]
                ):
                    raise HostError("temporary_recovery_image_id_mismatch")
                _require_temporary_service_reserve()
            _assert_protected_production_images(
                memory_reserve_kib=TEMPORARY_RECOVERY_AVAILABLE_RESERVE_KIB
            )
            _write_temporary_recovery_phase(operation, "archive_verified")

            _require_temporary_service_reserve()
            _write_temporary_recovery_phase(operation, "tagging_image")
            if (
                _temporary_image_reference_id(
                    temporary_image_ref,
                    memory_reserve_kib=TEMPORARY_RECOVERY_AVAILABLE_RESERVE_KIB,
                )
                is not None
            ):
                raise HostError("temporary_recovery_operation_tag_collision")
            _run(
                ["docker", "tag", image["image_id"], temporary_image_ref],
                timeout=30,
                memory_reserve_kib=TEMPORARY_RECOVERY_AVAILABLE_RESERVE_KIB,
            )
            if (
                _temporary_image_reference_id(
                    temporary_image_ref,
                    memory_reserve_kib=TEMPORARY_RECOVERY_AVAILABLE_RESERVE_KIB,
                )
                != image["image_id"]
            ):
                raise HostError("temporary_recovery_image_id_mismatch")
            self_image_ref = temporary_image_ref
            _assert_temporary_image(
                manifest,
                self_image_ref,
                memory_reserve_kib=TEMPORARY_RECOVERY_AVAILABLE_RESERVE_KIB,
            )
            _assert_protected_production_images(
                memory_reserve_kib=TEMPORARY_RECOVERY_AVAILABLE_RESERVE_KIB
            )
            _require_temporary_service_reserve()
            _write_temporary_recovery_phase(operation, "image_verified")

            available = _require_temporary_service_reserve()
            _write_temporary_recovery_phase(operation, "verifying_backup", available_kib=available)
            backup = _verified_backup(
                current["image_ref"],
                PRODUCTION_PREDECESSOR_REVISION,
                compose_file=compose_snapshot,
                memory_reserve_kib=TEMPORARY_RECOVERY_AVAILABLE_RESERVE_KIB,
            )
            if (
                backup.get("verified") is not True
                or backup.get("schema_version") != ASSISTANT_MINIMUM_SCHEMA
                or not isinstance(backup.get("name"), str)
                or BACKUP_NAME_PATTERN.fullmatch(backup["name"]) is None
                or not isinstance(backup.get("sha256"), str)
                or DIGEST_PATTERN.fullmatch(backup["sha256"]) is None
            ):
                raise HostError("temporary_recovery_backup_unverified")
            operation["backup"] = {**backup, "promoted": False}
            _require_temporary_service_reserve()
            _write_temporary_recovery_phase(operation, "backup_verified")

            available = _require_temporary_service_reserve()
            _write_temporary_recovery_phase(
                operation, "stopping_original_app", available_kib=available
            )
            _stop_app(
                compose_snapshot,
                memory_reserve_kib=TEMPORARY_RECOVERY_AVAILABLE_RESERVE_KIB,
            )
            _write_temporary_recovery_phase(operation, "original_app_stopped")
            _require_temporary_service_reserve()
            if (
                _database_schema(
                    current["image_ref"],
                    compose_file=compose_snapshot,
                    prepare_runtime=False,
                    memory_reserve_kib=TEMPORARY_RECOVERY_AVAILABLE_RESERVE_KIB,
                )
                != ASSISTANT_MINIMUM_SCHEMA
            ):
                raise HostError("temporary_recovery_schema_mismatch")

            available = _require_temporary_service_reserve()
            _write_temporary_recovery_phase(
                operation, "writing_temporary_runtime", available_kib=available
            )
            _runtime_file(temporary_image_ref, "disabled")
            temporary_record = _temporary_active_record(operation, status="starting")
            _write_temporary_recovery_phase(operation, "recording_temporary_app")
            _write_json(CURRENT_RECORD, temporary_record)

            available = _require_temporary_service_reserve()
            _write_temporary_recovery_phase(
                operation, "starting_temporary_app", available_kib=available
            )
            _compose_up(
                temporary_record,
                timeout=180,
                compose_file=compose_snapshot,
                force_recreate=True,
                memory_reserve_kib=TEMPORARY_RECOVERY_AVAILABLE_RESERVE_KIB,
            )
            _write_temporary_recovery_phase(operation, "verifying_temporary_app")
            _require_temporary_service_reserve()
            health = _health_check(
                assistant_rollout_mode="disabled",
                memory_reserve_kib=TEMPORARY_RECOVERY_AVAILABLE_RESERVE_KIB,
            )
            if health.get("schema_version") != ASSISTANT_MINIMUM_SCHEMA:
                raise HostError("temporary_recovery_readiness_schema_mismatch")
            if (
                _database_schema(
                    temporary_image_ref,
                    compose_file=compose_snapshot,
                    prepare_runtime=False,
                    memory_reserve_kib=TEMPORARY_RECOVERY_AVAILABLE_RESERVE_KIB,
                )
                != ASSISTANT_MINIMUM_SCHEMA
            ):
                raise HostError("temporary_recovery_schema_mismatch")
            _assert_temporary_container_profile(
                compose_snapshot,
                expected_image_id=image["image_id"],
                process_profile="temporary_app_pid1",
                memory_reserve_kib=TEMPORARY_RECOVERY_AVAILABLE_RESERVE_KIB,
            )
            available = _require_temporary_service_reserve()
            _write_temporary_recovery_phase(operation, "temporary_app_ready")
            _write_json(CURRENT_RECORD, _temporary_active_record(operation, status="ready"))
            startup_floor_met = available >= TEMPORARY_RECOVERY_STARTUP_FLOOR_KIB
            floor_phase = "startup_floor_passed" if startup_floor_met else "startup_floor_unmet"
            _write_temporary_recovery_phase(
                operation,
                floor_phase,
                startup_floor_kib=available,
                start_admission_allowed=startup_floor_met,
            )
            result = (
                "temporary_recovery_ready"
                if startup_floor_met
                else "temporary_recovery_ready_startup_floor_unmet"
            )
            _audit(
                "temporary_recovery",
                result,
                operation_id=operation_id,
                operation_kind="temporary_recovery",
                phase=floor_phase,
            )
            return {
                "status": "ok",
                "result": result,
                "operation_kind": "temporary_recovery",
                "operation_id": operation_id,
                "source_revision": TEMPORARY_RECOVERY_SOURCE_REVISION,
                "image_ref": temporary_image_ref,
                "image_id": image["image_id"],
                "archive_sha256": image["archive_sha256"],
                "manifest_sha256": manifest_sha256,
                "schema_version": ASSISTANT_MINIMUM_SCHEMA,
                "assistant_rollout_mode": "disabled",
                "backup": operation["backup"],
                "available_kib": available,
                "startup_floor_kib": TEMPORARY_RECOVERY_STARTUP_FLOOR_KIB,
                "start_admission_allowed": startup_floor_met,
                "health": health,
            }
        except HostError as error:
            _record_temporary_recovery_failure(operation, error)
            raise


def _restore_temporary_recovery(operation_id: str) -> dict[str, Any]:
    """Restore the exact retained 5ad image with assistant disabled; never restore a database."""

    if PLAN_PATTERN.fullmatch(operation_id) is None:
        raise HostError("temporary_recovery_operation_id_invalid")
    with _exclusive_lock():
        _ensure_layout()
        operation = _temporary_operation_record()
        if operation is None:
            raise HostError("temporary_recovery_not_found")
        if operation.get("operation_id") != operation_id:
            raise HostError("temporary_recovery_operation_id_mismatch")
        if operation["phase"] == "restored":
            return {
                "status": "ok",
                "result": "already_restored",
                "operation_kind": "temporary_recovery",
                "operation_id": operation_id,
            }
        original = operation.get("original_record")
        if not isinstance(original, dict):
            raise HostError("temporary_recovery_original_record_invalid")
        _require_temporary_service_reserve()
        compose_snapshot = _temporary_compose_snapshot(
            original,
            memory_reserve_kib=TEMPORARY_RECOVERY_AVAILABLE_RESERVE_KIB,
        )
        _assert_protected_production_images(
            memory_reserve_kib=TEMPORARY_RECOVERY_AVAILABLE_RESERVE_KIB
        )
        current = _read_json(CURRENT_RECORD)
        if current is None:
            raise HostError("temporary_recovery_current_state_unknown")
        is_temp_current = (
            current.get("operation_kind") == "temporary_recovery"
            and current.get("operation_id") == operation_id
            and current.get("revision") == TEMPORARY_RECOVERY_SOURCE_REVISION
            and current.get("image_id") == operation.get("image_id")
            and current.get("image_ref") == operation.get("image_ref")
            and current.get("image_digest") == operation.get("archive_sha256")
            and current.get("archive_sha256") == operation.get("archive_sha256")
            and current.get("archive_size") == operation.get("archive_size")
            and current.get("transport") == "temporary_recovery"
            and current.get("platform") == "linux/amd64"
            and current.get("schema_version") == ASSISTANT_MINIMUM_SCHEMA
            and current.get("assistant_rollout_mode") == "disabled"
            and current.get("compose_digest") == PRODUCTION_PREDECESSOR_COMPOSE_SHA256
            and current.get("manifest_sha256") == operation.get("manifest_sha256")
            and current.get("source_manifest_sha256") == TEMPORARY_RECOVERY_SOURCE_MANIFEST_SHA256
            and current.get("source_context_sha256") == TEMPORARY_RECOVERY_SOURCE_CONTEXT_SHA256
            and current.get("base_revision") == PAIR_BASE_REVISION
            and current.get("migration_sha256") == PAIR_MIGRATION_SHA256
            and current.get("overlay_sha256") == TEMPORARY_RECOVERY_OVERLAY_SHA256
        )
        is_original_current = (
            current.get("revision") == PRODUCTION_PREDECESSOR_REVISION
            and current.get("image_id") == PRODUCTION_PREDECESSOR_IMAGE_ID
            and current.get("image_ref") == _local_image_ref(PRODUCTION_PREDECESSOR_REVISION)
            and current.get("compose_digest") == PRODUCTION_PREDECESSOR_COMPOSE_SHA256
            and current.get("schema_version") == ASSISTANT_MINIMUM_SCHEMA
            and current.get("assistant_rollout_mode") in {"invited", "disabled"}
        )
        if not (is_temp_current or is_original_current):
            raise HostError("temporary_recovery_current_state_unknown")
        if (
            is_temp_current
            and _temporary_image_reference_id(
                operation["image_ref"],
                memory_reserve_kib=TEMPORARY_RECOVERY_AVAILABLE_RESERVE_KIB,
            )
            != operation["image_id"]
        ):
            raise HostError("temporary_recovery_image_id_mismatch")
        available = _require_temporary_service_reserve()
        _write_temporary_recovery_phase(
            operation, "restore_requested", restore_initial_available_kib=available
        )
        try:
            available = _require_temporary_service_reserve()
            _write_temporary_recovery_phase(
                operation, "stopping_temporary_app", available_kib=available
            )
            _stop_app(
                compose_snapshot,
                memory_reserve_kib=TEMPORARY_RECOVERY_AVAILABLE_RESERVE_KIB,
            )
            _write_temporary_recovery_phase(operation, "temporary_app_stopped")

            _write_temporary_recovery_phase(operation, "verifying_shared_schema")
            if (
                _database_schema(
                    original["image_ref"],
                    compose_file=compose_snapshot,
                    prepare_runtime=False,
                    memory_reserve_kib=TEMPORARY_RECOVERY_AVAILABLE_RESERVE_KIB,
                )
                != ASSISTANT_MINIMUM_SCHEMA
            ):
                raise HostError("temporary_recovery_schema_mismatch")

            restored = dict(original)
            restored["assistant_rollout_mode"] = "disabled"
            restored["temporary_recovery_restored_operation_id"] = operation_id
            available = _require_temporary_service_reserve()
            _write_temporary_recovery_phase(
                operation, "writing_original_runtime", available_kib=available
            )
            _runtime_file(original["image_ref"], "disabled")
            _write_temporary_recovery_phase(operation, "recording_original_app")
            _write_json(CURRENT_RECORD, restored)

            available = _require_temporary_service_reserve()
            _write_temporary_recovery_phase(
                operation, "starting_original_app", available_kib=available
            )
            _compose_up(
                restored,
                timeout=180,
                compose_file=compose_snapshot,
                force_recreate=True,
                memory_reserve_kib=TEMPORARY_RECOVERY_AVAILABLE_RESERVE_KIB,
            )
            _write_temporary_recovery_phase(operation, "verifying_original_app")
            _require_temporary_service_reserve()
            health = _health_check(
                assistant_rollout_mode="disabled",
                memory_reserve_kib=TEMPORARY_RECOVERY_AVAILABLE_RESERVE_KIB,
            )
            if health.get("schema_version") != ASSISTANT_MINIMUM_SCHEMA:
                raise HostError("temporary_recovery_restore_readiness_mismatch")
            if (
                _database_schema(
                    original["image_ref"],
                    compose_file=compose_snapshot,
                    prepare_runtime=False,
                    memory_reserve_kib=TEMPORARY_RECOVERY_AVAILABLE_RESERVE_KIB,
                )
                != ASSISTANT_MINIMUM_SCHEMA
            ):
                raise HostError("temporary_recovery_schema_mismatch")
            _assert_temporary_container_profile(
                compose_snapshot,
                expected_image_id=PRODUCTION_PREDECESSOR_IMAGE_ID,
                process_profile="retained_supervisor_app_disabled",
                memory_reserve_kib=TEMPORARY_RECOVERY_AVAILABLE_RESERVE_KIB,
            )
            _write_temporary_recovery_phase(
                operation,
                "restored",
                restored_at=_utc_now(),
                assistant_rollout_mode="disabled",
                restored_image_id=PRODUCTION_PREDECESSOR_IMAGE_ID,
            )
            return {
                "status": "ok",
                "result": "temporary_recovery_restored",
                "operation_kind": "temporary_recovery",
                "operation_id": operation_id,
                "revision": PRODUCTION_PREDECESSOR_REVISION,
                "image_id": PRODUCTION_PREDECESSOR_IMAGE_ID,
                "schema_version": ASSISTANT_MINIMUM_SCHEMA,
                "assistant_rollout_mode": "disabled",
                "health": health,
            }
        except HostError as error:
            _record_temporary_recovery_failure(operation, error)
            raise


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
    if operation == "start_temporary_recovery":
        return _start_temporary_recovery()
    if operation == "restore_temporary_recovery":
        operation_id = payload["operation_id"]
        if not isinstance(operation_id, str):
            raise HostError("temporary_recovery_operation_id_invalid")
        return _restore_temporary_recovery(operation_id)
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
