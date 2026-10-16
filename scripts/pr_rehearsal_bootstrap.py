#!/usr/bin/env python3
"""Install the separately rooted PR rehearsal helper after exact-source verification."""

from __future__ import annotations

import fcntl
import grp
import hashlib
import http.client
import json
import os
import pwd
import re
import stat
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

REPOSITORY = "eddiesoz/stock_probs"
PULL_NUMBER = 2
HELPER_SOURCE_PR_NUMBER = 11
HELPER_SOURCE_CONTRACT = "schema13_same_schema_hotfix_v1"
HOST = "raw.githubusercontent.com"
INCOMING = Path("/var/lib/signal-ledger-pr-rehearsal/incoming")
INSTALL_ROOT = Path("/usr/local/libexec/signal-ledger-pr-rehearsal")
STATE_ROOT = Path("/var/lib/signal-ledger-pr-rehearsal")
INSTALLED_MANIFEST = INSTALL_ROOT / "installed.json"
DEPLOY_STATE_ROOT = Path("/var/lib/signal-ledger")
DEPLOY_LOCK = DEPLOY_STATE_ROOT / "deploy.lock"
REHEARSAL_LOCK = STATE_ROOT / "rehearsal.lock"
PRODUCTION_HELPER = Path("/usr/local/libexec/signal-ledger-deploy-helper")
PREVIOUS_PRODUCTION_HELPER = STATE_ROOT / "previous-production-deploy-helper.py"
PRODUCTION_HELPER_MAX_BYTES = 512 * 1024
PREVIOUS_PRODUCTION_HELPER_SIZE = 108_471
PREVIOUS_PRODUCTION_HELPER_SHA256 = (
    "57b88adc91b13689d83c0d56a2dd9f756000624e847f0c7a107dff7cb382a915"
)
KNOWN_INTERMEDIATE_PRODUCTION_HELPER_SHA256 = (
    "0d65ad8f1fa9825b1e4a964fa112f49b87a08ed415a8e5ce67802549045f6cd8"
)
KNOWN_INTERMEDIATE_REVIEWED_HEAD_SHA = "cebe3870a62d3d433baaeba45845cf59ebb1e9bc"
KNOWN_INTERMEDIATE_PAIR_MANIFEST_SHA256 = (
    "6346e9d8d1f0ecb64e7ec1fa81a6b8cf56ee8e752ded7199219ae1a204bdf90c"
)
KNOWN_INTERMEDIATE_INSTALLED_FILES = {
    "host_helper.py": "c2929e6d129cc56eeb21d3dcec7be484345e9d39ff1ed910dcb16901d62faf76",
    "seed.py": "56e79454482f20a2964766aa016e6f985673bb41571ac36bba21d09302d72b15",
    "native_driver.py": "5e72113ddbacff3d2cc44f44671bbb6e8dc5a1a49ae3292f0d8b2f91afd33c10",
    "production-deploy-helper.py": KNOWN_INTERMEDIATE_PRODUCTION_HELPER_SHA256,
}
KNOWN_INTERMEDIATE_INSTALL_MANIFEST = {
    "format_version": 1,
    "repository": REPOSITORY,
    "pull_number": HELPER_SOURCE_PR_NUMBER,
    "reviewed_head_sha": KNOWN_INTERMEDIATE_REVIEWED_HEAD_SHA,
    "reviewed_pair_manifest_sha256": KNOWN_INTERMEDIATE_PAIR_MANIFEST_SHA256,
    "files": KNOWN_INTERMEDIATE_INSTALLED_FILES,
    "helper_source_contract": HELPER_SOURCE_CONTRACT,
    "previous_production_helper_sha256": PREVIOUS_PRODUCTION_HELPER_SHA256,
}
# Exact helper installation observed on PR11 head 67723d36 before the source-only
# helper refresh. Keep this state separate from the older cebe intermediate above:
# both receipts are valid rollback inputs, but they identify different source bundles.
KNOWN_INSTALLED_67723_PRODUCTION_HELPER_SHA256 = (
    "85ea6568514188b37c6b6f7b93dc902cf7003836b60983255e4a0337fc575371"
)
KNOWN_INSTALLED_67723_REVIEWED_HEAD_SHA = "67723d36ea03b0628e59007af20c2910a64d06fb"
KNOWN_INSTALLED_67723_PAIR_MANIFEST_SHA256 = (
    "60f1288183685f104452b1fc1f51a823a31a09501f3807fe7023d988f950335e"
)
KNOWN_INSTALLED_67723_INSTALLED_FILES = {
    "host_helper.py": "c2929e6d129cc56eeb21d3dcec7be484345e9d39ff1ed910dcb16901d62faf76",
    "seed.py": "56e79454482f20a2964766aa016e6f985673bb41571ac36bba21d09302d72b15",
    "native_driver.py": "5e72113ddbacff3d2cc44f44671bbb6e8dc5a1a49ae3292f0d8b2f91afd33c10",
    "production-deploy-helper.py": KNOWN_INSTALLED_67723_PRODUCTION_HELPER_SHA256,
}
KNOWN_INSTALLED_67723_INSTALL_MANIFEST = {
    "format_version": 1,
    "repository": REPOSITORY,
    "pull_number": HELPER_SOURCE_PR_NUMBER,
    "reviewed_head_sha": KNOWN_INSTALLED_67723_REVIEWED_HEAD_SHA,
    "reviewed_pair_manifest_sha256": KNOWN_INSTALLED_67723_PAIR_MANIFEST_SHA256,
    "files": KNOWN_INSTALLED_67723_INSTALLED_FILES,
    "helper_source_contract": HELPER_SOURCE_CONTRACT,
    "previous_production_helper_sha256": PREVIOUS_PRODUCTION_HELPER_SHA256,
}
# The c408e914 PR11 source refresh retained the same production-helper bytes as
# 67723, but its installed receipt binds a newer reviewed bundle and sidecars.
KNOWN_INSTALLED_C408_PRODUCTION_HELPER_SHA256 = (
    "85ea6568514188b37c6b6f7b93dc902cf7003836b60983255e4a0337fc575371"
)
KNOWN_INSTALLED_C408_REVIEWED_HEAD_SHA = "c408e9143143c4d71d0bb3a363e6f05f2c8dc221"
KNOWN_INSTALLED_C408_PAIR_MANIFEST_SHA256 = (
    "73bb45b1f03f59eccde7972aa9550ea97882f61d0810a21fdba65c3c676f74ee"
)
KNOWN_INSTALLED_C408_INSTALLED_FILES = {
    "host_helper.py": "383719bfd2700adcc76e662b15774ca3e32dd87f61b77a9fe65ff2458f6f6a8c",
    "seed.py": "56e79454482f20a2964766aa016e6f985673bb41571ac36bba21d09302d72b15",
    "native_driver.py": "5e72113ddbacff3d2cc44f44671bbb6e8dc5a1a49ae3292f0d8b2f91afd33c10",
    "production-deploy-helper.py": KNOWN_INSTALLED_C408_PRODUCTION_HELPER_SHA256,
}
KNOWN_INSTALLED_C408_INSTALL_MANIFEST = {
    "format_version": 1,
    "repository": REPOSITORY,
    "pull_number": HELPER_SOURCE_PR_NUMBER,
    "reviewed_head_sha": KNOWN_INSTALLED_C408_REVIEWED_HEAD_SHA,
    "reviewed_pair_manifest_sha256": KNOWN_INSTALLED_C408_PAIR_MANIFEST_SHA256,
    "files": KNOWN_INSTALLED_C408_INSTALLED_FILES,
    "helper_source_contract": HELPER_SOURCE_CONTRACT,
    "previous_production_helper_sha256": PREVIOUS_PRODUCTION_HELPER_SHA256,
}
# Exact DD7 helper installation observed before the source-only profile-query repair.
KNOWN_INSTALLED_DD7_PRODUCTION_HELPER_SHA256 = (
    "0d99260dfdc09f2e49a486932bd3b820ea62d4eec614f26899350d640b0ab76d"
)
KNOWN_INSTALLED_DD7_REVIEWED_HEAD_SHA = "dd7f327202358c244253e36e4a0b0f52185a0f1c"
KNOWN_INSTALLED_DD7_PAIR_MANIFEST_SHA256 = (
    "f35dedd6ba9d49c9cb53aa036f1912b3082b7af144204dbae10378b341a08095"
)
KNOWN_INSTALLED_DD7_INSTALLED_FILES = {
    "host_helper.py": "383719bfd2700adcc76e662b15774ca3e32dd87f61b77a9fe65ff2458f6f6a8c",
    "seed.py": "56e79454482f20a2964766aa016e6f985673bb41571ac36bba21d09302d72b15",
    "native_driver.py": "5e72113ddbacff3d2cc44f44671bbb6e8dc5a1a49ae3292f0d8b2f91afd33c10",
    "production-deploy-helper.py": KNOWN_INSTALLED_DD7_PRODUCTION_HELPER_SHA256,
}
KNOWN_INSTALLED_DD7_INSTALL_MANIFEST = {
    "format_version": 1,
    "repository": REPOSITORY,
    "pull_number": HELPER_SOURCE_PR_NUMBER,
    "reviewed_head_sha": KNOWN_INSTALLED_DD7_REVIEWED_HEAD_SHA,
    "reviewed_pair_manifest_sha256": KNOWN_INSTALLED_DD7_PAIR_MANIFEST_SHA256,
    "files": KNOWN_INSTALLED_DD7_INSTALLED_FILES,
    "helper_source_contract": HELPER_SOURCE_CONTRACT,
    "previous_production_helper_sha256": PREVIOUS_PRODUCTION_HELPER_SHA256,
}
REVISION_RE = re.compile(r"^[0-9a-f]{40}$")
DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
ASSETS = {
    "bootstrap": ("scripts/pr_rehearsal_bootstrap.py", "bootstrap.py", 256 * 1024),
    "host_helper": ("scripts/pr_rehearsal_host_helper.py", "host_helper.py", 256 * 1024),
    "seed": ("scripts/pr_rehearsal_seed.py", "seed.py", 64 * 1024),
    "driver": ("tests/native_assistant_probe.py", "native_driver.py", 2 * 1024 * 1024),
    "production_helper": (
        "scripts/production-deploy-helper.py",
        "production-deploy-helper.py",
        PRODUCTION_HELPER_MAX_BYTES,
    ),
}
REQUEST_LIMIT = 8 * 1024
# The fixed public PR record is about 21 KiB. Keep a bounded 64 KiB response cap
# consistently with the controller, while never recording or echoing the raw body.
RESPONSE_LIMIT = 64 * 1024


class InstallError(Exception):
    """A safe bootstrap failure category without path or network diagnostics."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class _DuplicateManifestKey(ValueError):
    """Reject duplicate keys before interpreting a trusted install receipt."""


def _manifest_object_without_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateManifestKey
        result[key] = value
    return result


def _safe_directory(path: Path, mode: int, *, create: bool, group: str | None = None) -> None:
    if create:
        path.mkdir(mode=mode, parents=True, exist_ok=True)
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    except OSError as exc:
        raise InstallError("install_directory_unsafe") from exc
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0:
            raise InstallError("install_directory_unsafe")
        if group is not None:
            try:
                expected_gid = grp.getgrnam(group).gr_gid
            except KeyError as exc:
                raise InstallError("install_directory_unsafe") from exc
            if info.st_gid != expected_gid:
                os.fchown(descriptor, 0, expected_gid)
        os.fchmod(descriptor, mode)
    finally:
        os.close(descriptor)


def _safe_incoming_directory() -> None:
    try:
        info = INCOMING.lstat()
        expected_uid = pwd.getpwnam("signalops").pw_uid
    except (OSError, KeyError) as exc:
        raise InstallError("incoming_directory_unavailable") from exc
    if (
        not stat.S_ISDIR(info.st_mode)
        or info.st_uid != expected_uid
        or stat.S_IMODE(info.st_mode) != 0o700
    ):
        raise InstallError("incoming_directory_unsafe")


def _check_root_directory(path: Path) -> None:
    try:
        info = path.lstat()
    except OSError as exc:
        raise InstallError("install_parent_unavailable") from exc
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0:
        raise InstallError("install_parent_unsafe")


def _read_staged(path: Path, maximum: int) -> bytes:
    try:
        info = path.lstat()
    except OSError as exc:
        raise InstallError("bootstrap_asset_unavailable") from exc
    if not stat.S_ISREG(info.st_mode) or not 1 <= info.st_size <= maximum:
        raise InstallError("bootstrap_asset_unsafe")
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(descriptor, "rb") as source:
            result = source.read(maximum + 1)
    except OSError as exc:
        raise InstallError("bootstrap_asset_unavailable") from exc
    if len(result) != info.st_size or len(result) > maximum:
        raise InstallError("bootstrap_asset_changed")
    return result


def _staged_asset_path(revision: str, role: str) -> Path:
    """Resolve one fixed source basename beneath the validated SHA namespace."""

    if REVISION_RE.fullmatch(revision) is None or role not in ASSETS:
        raise InstallError("bootstrap_asset_name_invalid")
    staged_name = ASSETS[role][1]
    return INCOMING / f"signal-ledger-pr1-{revision}-{staged_name}"


def _verify_pull_request(revision: str, *, pull_number: int = PULL_NUMBER) -> None:
    if type(pull_number) is not int or pull_number not in {PULL_NUMBER, HELPER_SOURCE_PR_NUMBER}:
        raise InstallError("reviewed_pr_invalid")
    connection = http.client.HTTPSConnection("api.github.com", timeout=10)
    try:
        connection.request(
            "GET",
            f"/repos/{REPOSITORY}/pulls/{pull_number}",
            headers={
                "Accept": "application/vnd.github+json",
                "User-Agent": "signal-ledger-r120-pr-rehearsal-bootstrap",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        response = connection.getresponse()
        raw = response.read(RESPONSE_LIMIT + 1)
        if response.status != 200 or len(raw) > RESPONSE_LIMIT:
            raise InstallError("reviewed_pr_unavailable")
    except (OSError, TimeoutError, http.client.HTTPException) as exc:
        raise InstallError("reviewed_pr_unavailable") from exc
    finally:
        connection.close()
    try:
        payload: object = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise InstallError("reviewed_pr_invalid") from exc
    if not isinstance(payload, dict):
        raise InstallError("reviewed_pr_invalid")
    base = payload.get("base")
    head = payload.get("head")
    repository = head.get("repo") if isinstance(head, dict) else None
    if (
        payload.get("state") != "open"
        or not isinstance(base, dict)
        or base.get("ref") != "main"
        or not isinstance(head, dict)
        or head.get("sha") != revision
        or not isinstance(repository, dict)
        or repository.get("full_name") != REPOSITORY
    ):
        raise InstallError("reviewed_pr_mismatch")


def _fetch_reviewed_source(revision: str, relative_path: str, maximum: int) -> bytes:
    connection = http.client.HTTPSConnection(HOST, timeout=15)
    path = f"/{REPOSITORY}/{revision}/{relative_path}"
    try:
        connection.request(
            "GET",
            path,
            headers={"User-Agent": "signal-ledger-r120-pr-rehearsal-bootstrap"},
        )
        response = connection.getresponse()
        content = response.read(maximum + 1)
        if response.status != 200 or len(content) > maximum:
            raise InstallError("reviewed_source_unavailable")
        if response.getheader("Content-Type", "").split(";", 1)[0] not in {
            "text/plain",
            "application/octet-stream",
        }:
            raise InstallError("reviewed_source_invalid")
        return content
    except (OSError, TimeoutError, http.client.HTTPException) as exc:
        raise InstallError("reviewed_source_unavailable") from exc
    finally:
        connection.close()


def _atomic_root_file(path: Path, contents: bytes, mode: int) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            mode,
        )
        with os.fdopen(descriptor, "wb") as destination:
            destination.write(contents)
            destination.flush()
            os.fsync(destination.fileno())
        os.chown(temporary, 0, 0)
        os.chmod(temporary, mode)
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    except OSError as exc:
        temporary.unlink(missing_ok=True)
        raise InstallError("sidecar_install_failed") from exc


@contextmanager
def _install_locks() -> Iterator[None]:
    """Serialize fixed source installation with deployment and rehearsal operations."""

    descriptors: list[int] = []
    try:
        _safe_directory(DEPLOY_STATE_ROOT, 0o750, create=False, group="signalops")
        _safe_directory(STATE_ROOT, 0o750, create=False, group="signalops")
        for path, mode in ((DEPLOY_LOCK, 0o640), (REHEARSAL_LOCK, 0o600)):
            try:
                descriptor = os.open(
                    path,
                    os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC,
                    mode,
                )
            except OSError as exc:
                raise InstallError("install_lock_unavailable") from exc
            descriptors.append(descriptor)
            info = os.fstat(descriptor)
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_uid != 0
                or stat.S_IMODE(info.st_mode) != mode
            ):
                raise InstallError("install_lock_unsafe")
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except (BlockingIOError, OSError) as exc:
                raise InstallError("install_operation_busy") from exc
        yield
    finally:
        for descriptor in reversed(descriptors):
            try:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
            finally:
                os.close(descriptor)


def _read_fixed_root_file(path: Path, maximum: int, mode: int) -> bytes:
    """Read one root-owned, bounded file without following links."""

    try:
        before = path.lstat()
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_uid != 0
            or stat.S_IMODE(before.st_mode) != mode
            or not 1 <= before.st_size <= maximum
        ):
            raise InstallError("production_helper_file_unsafe")
        descriptor = os.open(
            path,
            os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC,
        )
        with os.fdopen(descriptor, "rb") as stream:
            opened = os.fstat(stream.fileno())
            contents = stream.read(maximum + 1)
            after = os.fstat(stream.fileno())
    except InstallError:
        raise
    except OSError as exc:
        raise InstallError("production_helper_file_unavailable") from exc
    identity = (
        "st_dev",
        "st_ino",
        "st_mode",
        "st_uid",
        "st_gid",
        "st_size",
        "st_mtime_ns",
        "st_ctime_ns",
    )
    if (
        len(contents) != before.st_size
        or len(contents) > maximum
        or any(getattr(before, field) != getattr(opened, field) for field in identity)
        or any(getattr(opened, field) != getattr(after, field) for field in identity)
    ):
        raise InstallError("production_helper_file_changed")
    return contents


def _valid_installed_at(value: object) -> bool:
    if type(value) is not str or not value.endswith("Z"):
        return False
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        return False
    return (
        parsed.utcoffset() == UTC.utcoffset(None)
        and parsed.isoformat().replace("+00:00", "Z") == value
    )


def _require_installed_manifest(expected_fields: dict[str, object]) -> None:
    """Require one exact root-owned install receipt apart from its generated timestamp."""

    try:
        raw = _read_fixed_root_file(INSTALLED_MANIFEST, 8192, 0o640)
    except InstallError as exc:
        raise InstallError("production_helper_manifest_mismatch") from exc
    try:
        value: object = json.loads(raw, object_pairs_hook=_manifest_object_without_duplicates)
    except (UnicodeDecodeError, json.JSONDecodeError, _DuplicateManifestKey, RecursionError) as exc:
        raise InstallError("production_helper_manifest_mismatch") from exc
    if (
        type(value) is not dict
        or set(value) != set(expected_fields) | {"installed_at"}
        or not _valid_installed_at(value.get("installed_at"))
    ):
        raise InstallError("production_helper_manifest_mismatch")
    for key, expected in expected_fields.items():
        actual = value[key]
        if type(actual) is not type(expected) or actual != expected:
            raise InstallError("production_helper_manifest_mismatch")
        if type(expected) is dict and any(
            type(name) is not str or type(digest) is not str for name, digest in actual.items()
        ):
            raise InstallError("production_helper_manifest_mismatch")
    installed_files = value["files"]
    for role, (_relative, installed_name, maximum) in ASSETS.items():
        if role == "bootstrap":
            continue
        path = PRODUCTION_HELPER if role == "production_helper" else INSTALL_ROOT / installed_name
        mode = 0o750 if role in {"host_helper", "production_helper"} else 0o640
        try:
            contents = _read_fixed_root_file(path, maximum, mode)
        except InstallError as exc:
            raise InstallError("production_helper_manifest_mismatch") from exc
        if hashlib.sha256(contents).hexdigest() != installed_files[installed_name]:
            raise InstallError("production_helper_manifest_mismatch")


def _prepare_previous_production_helper(
    candidate: bytes,
    *,
    candidate_manifest_fields: dict[str, object],
) -> tuple[bytes, str]:
    """Validate the prior helper state and return exact transaction rollback bytes."""

    candidate_digest = hashlib.sha256(candidate).hexdigest()
    if candidate_digest in {
        PREVIOUS_PRODUCTION_HELPER_SHA256,
        KNOWN_INTERMEDIATE_PRODUCTION_HELPER_SHA256,
    }:
        raise InstallError("production_helper_candidate_is_previous")
    backup_exists = PREVIOUS_PRODUCTION_HELPER.exists() or PREVIOUS_PRODUCTION_HELPER.is_symlink()
    if backup_exists:
        immutable_backup = _read_fixed_root_file(
            PREVIOUS_PRODUCTION_HELPER,
            PRODUCTION_HELPER_MAX_BYTES,
            0o600,
        )
        if (
            len(immutable_backup) != PREVIOUS_PRODUCTION_HELPER_SIZE
            or hashlib.sha256(immutable_backup).hexdigest() != PREVIOUS_PRODUCTION_HELPER_SHA256
        ):
            raise InstallError("production_helper_backup_mismatch")
        current = _read_fixed_root_file(PRODUCTION_HELPER, PRODUCTION_HELPER_MAX_BYTES, 0o750)
        current_digest = hashlib.sha256(current).hexdigest()
        if current_digest == KNOWN_INTERMEDIATE_PRODUCTION_HELPER_SHA256:
            _require_installed_manifest(KNOWN_INTERMEDIATE_INSTALL_MANIFEST)
        elif current_digest == KNOWN_INSTALLED_DD7_PRODUCTION_HELPER_SHA256:
            _require_installed_manifest(KNOWN_INSTALLED_DD7_INSTALL_MANIFEST)
        elif current_digest in {
            KNOWN_INSTALLED_67723_PRODUCTION_HELPER_SHA256,
            KNOWN_INSTALLED_C408_PRODUCTION_HELPER_SHA256,
        }:
            # Source-only upgrades can retain identical helper bytes while their
            # installed receipt still binds the previous reviewed source bundle.
            # Accept only the exact known installed receipt or the exact candidate
            # receipt for an already-completed retry.
            try:
                _require_installed_manifest(candidate_manifest_fields)
            except InstallError:
                try:
                    _require_installed_manifest(KNOWN_INSTALLED_67723_INSTALL_MANIFEST)
                except InstallError:
                    _require_installed_manifest(KNOWN_INSTALLED_C408_INSTALL_MANIFEST)
        elif current_digest == candidate_digest:
            _require_installed_manifest(candidate_manifest_fields)
        elif current_digest != PREVIOUS_PRODUCTION_HELPER_SHA256:
            raise InstallError("production_helper_drift")
        return current, PREVIOUS_PRODUCTION_HELPER_SHA256

    previous = _read_fixed_root_file(PRODUCTION_HELPER, PRODUCTION_HELPER_MAX_BYTES, 0o750)
    digest = hashlib.sha256(previous).hexdigest()
    if (
        len(previous) != PREVIOUS_PRODUCTION_HELPER_SIZE
        or digest != PREVIOUS_PRODUCTION_HELPER_SHA256
    ):
        raise InstallError("production_helper_drift")
    _atomic_root_file(PREVIOUS_PRODUCTION_HELPER, previous, 0o600)
    stored = _read_fixed_root_file(
        PREVIOUS_PRODUCTION_HELPER,
        PRODUCTION_HELPER_MAX_BYTES,
        0o600,
    )
    if stored != previous:
        raise InstallError("production_helper_backup_mismatch")
    return previous, digest


def install(payload: object) -> dict[str, object]:
    base_keys = {
        "reviewed_head_sha",
        "reviewed_pair_manifest_sha256",
        "asset_sha256",
    }
    if not isinstance(payload, dict):
        raise InstallError("payload_invalid")
    if set(payload) == base_keys:
        helper_source_contract = None
        helper_source_pull_number = PULL_NUMBER
        selected_assets = {
            key: value for key, value in ASSETS.items() if key != "production_helper"
        }
    elif (
        set(payload) == base_keys | {"helper_source_contract"}
        and payload.get("helper_source_contract") == HELPER_SOURCE_CONTRACT
    ):
        helper_source_contract = HELPER_SOURCE_CONTRACT
        helper_source_pull_number = HELPER_SOURCE_PR_NUMBER
        selected_assets = ASSETS
    else:
        raise InstallError("payload_invalid")
    revision = payload.get("reviewed_head_sha")
    pair_manifest_digest = payload.get("reviewed_pair_manifest_sha256")
    hashes = payload.get("asset_sha256")
    if not isinstance(revision, str) or REVISION_RE.fullmatch(revision) is None:
        raise InstallError("reviewed_pr_head_invalid")
    if (
        not isinstance(pair_manifest_digest, str)
        or DIGEST_RE.fullmatch(pair_manifest_digest) is None
    ):
        raise InstallError("reviewed_pair_manifest_invalid")
    if not isinstance(hashes, dict) or set(hashes) != set(selected_assets):
        raise InstallError("asset_manifest_invalid")
    for digest in hashes.values():
        if not isinstance(digest, str) or DIGEST_RE.fullmatch(digest) is None:
            raise InstallError("asset_manifest_invalid")

    _safe_directory(STATE_ROOT, 0o750, create=True, group="signalops")
    _safe_incoming_directory()
    _check_root_directory(Path("/usr/local/libexec"))
    if INSTALL_ROOT.exists() or INSTALL_ROOT.is_symlink():
        _safe_directory(INSTALL_ROOT, 0o750, create=False)
    else:
        _safe_directory(INSTALL_ROOT, 0o750, create=True)
    _verify_pull_request(revision, pull_number=helper_source_pull_number)

    verified: dict[str, str] = {}
    contents: dict[str, bytes] = {}
    for key, (relative_path, _staged_name, maximum) in selected_assets.items():
        local = _read_staged(_staged_asset_path(revision, key), maximum)
        digest = hashlib.sha256(local).hexdigest()
        if digest != hashes[key]:
            raise InstallError("asset_digest_mismatch")
        upstream = _fetch_reviewed_source(revision, relative_path, maximum)
        if upstream != local:
            raise InstallError("asset_source_mismatch")
        contents[key] = local
        verified[key] = digest
    receipt_fields: dict[str, object] = {
        "format_version": 1,
        "repository": REPOSITORY,
        "pull_number": helper_source_pull_number,
        "reviewed_head_sha": revision,
        "reviewed_pair_manifest_sha256": pair_manifest_digest,
        "files": {
            installed_name: verified[key]
            for key, (_relative, installed_name, _maximum) in selected_assets.items()
            if key != "bootstrap"
        },
    }
    if helper_source_contract is not None:
        receipt_fields.update(
            {
                "helper_source_contract": helper_source_contract,
                "previous_production_helper_sha256": PREVIOUS_PRODUCTION_HELPER_SHA256,
            }
        )

    def installed_path(key: str) -> Path:
        if key == "production_helper":
            return PRODUCTION_HELPER
        return INSTALL_ROOT / selected_assets[key][1]

    def previous_file(path: Path, *, maximum: int, mode: int) -> bytes | None:
        if not path.exists() and not path.is_symlink():
            return None
        return _read_fixed_root_file(path, maximum, mode)

    def write_install() -> dict[str, object]:
        previous_helper: bytes | None = None
        previous_helper_digest: str | None = None
        helper_replacement_started = False
        snapshots: dict[Path, bytes | None] = {}
        for key in selected_assets:
            if key == "bootstrap":
                continue
            path = installed_path(key)
            mode = 0o750 if key == "host_helper" or key == "production_helper" else 0o640
            snapshots[path] = previous_file(path, maximum=selected_assets[key][2], mode=mode)
        old_manifest = previous_file(INSTALLED_MANIFEST, maximum=8192, mode=0o640)
        try:
            if helper_source_contract is not None:
                assert "production_helper" in contents
                previous_helper, previous_helper_digest = _prepare_previous_production_helper(
                    contents["production_helper"],
                    candidate_manifest_fields=receipt_fields,
                )
            for key, (_relative, installed_name, _maximum) in selected_assets.items():
                if key == "bootstrap" or key == "production_helper":
                    continue
                _atomic_root_file(
                    INSTALL_ROOT / installed_name,
                    contents[key],
                    0o750 if key == "host_helper" else 0o640,
                )
            if helper_source_contract is not None:
                current_helper = _read_fixed_root_file(
                    PRODUCTION_HELPER,
                    PRODUCTION_HELPER_MAX_BYTES,
                    0o750,
                )
                if current_helper != contents["production_helper"]:
                    helper_replacement_started = True
                    _atomic_root_file(PRODUCTION_HELPER, contents["production_helper"], 0o750)

            receipt = {
                **receipt_fields,
                "installed_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            }
            if helper_source_contract is not None:
                assert previous_helper_digest is not None
                receipt["previous_production_helper_sha256"] = previous_helper_digest
            _atomic_root_file(
                INSTALLED_MANIFEST,
                (json.dumps(receipt, sort_keys=True, separators=(",", ":")) + "\n").encode(),
                0o640,
            )
        except (InstallError, OSError, ValueError, TypeError) as error:
            try:
                if helper_replacement_started and previous_helper is not None:
                    _atomic_root_file(PRODUCTION_HELPER, previous_helper, 0o750)
                for path, contents_before in snapshots.items():
                    if path == PRODUCTION_HELPER:
                        continue
                    if contents_before is None:
                        path.unlink(missing_ok=True)
                    else:
                        mode = 0o750 if path.name == "host_helper.py" else 0o640
                        _atomic_root_file(path, contents_before, mode)
                if old_manifest is None:
                    INSTALLED_MANIFEST.unlink(missing_ok=True)
                else:
                    _atomic_root_file(INSTALLED_MANIFEST, old_manifest, 0o640)
            except (InstallError, OSError, ValueError, TypeError) as rollback_error:
                raise InstallError("install_rollback_unverified") from rollback_error
            if isinstance(error, InstallError):
                raise
            raise InstallError("sidecar_install_failed") from error

        result: dict[str, object] = {
            "status": "installed",
            "reviewed_head_sha": revision,
            "reviewed_pair_manifest_sha256": pair_manifest_digest,
            "asset_sha256": verified,
        }
        if helper_source_contract is not None:
            result["pull_number"] = helper_source_pull_number
            result["helper_source_contract"] = helper_source_contract
            result["production_helper_sha256"] = verified["production_helper"]
            result["previous_production_helper_sha256"] = previous_helper_digest
        return result

    _safe_directory(STATE_ROOT, 0o750, create=True, group="signalops")
    if helper_source_contract is not None:
        with _install_locks():
            result = write_install()
    else:
        result = write_install()
    for key in selected_assets:
        _staged_asset_path(revision, key).unlink(missing_ok=True)
    return result


def main() -> int:
    if os.geteuid() != 0:
        result: dict[str, object] = {"status": "error", "code": "root_required"}
    else:
        raw = sys.stdin.buffer.read(REQUEST_LIMIT + 1)
        if not raw or len(raw) > REQUEST_LIMIT:
            result = {"status": "error", "code": "request_invalid"}
        else:
            try:
                request: object = json.loads(raw)
                if (
                    not isinstance(request, dict)
                    or set(request) != {"operation", "payload"}
                    or request.get("operation") != "install"
                ):
                    raise InstallError("request_invalid")
                result = install(request.get("payload"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                result = {"status": "error", "code": "request_invalid"}
            except InstallError as exc:
                result = {"status": "error", "code": exc.code}
    encoded = (json.dumps(result, sort_keys=True, separators=(",", ":")) + "\n").encode()
    sys.stdout.buffer.write(encoded[:REQUEST_LIMIT])
    return 0 if result.get("status") == "installed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
