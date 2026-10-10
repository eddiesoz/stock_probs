#!/usr/bin/env python3
"""Install the separately rooted PR rehearsal helper after exact-source verification."""

from __future__ import annotations

import grp
import hashlib
import http.client
import json
import os
import pwd
import re
import stat
import sys
from datetime import UTC, datetime
from pathlib import Path

REPOSITORY = "eddiesoz/stock_probs"
PULL_NUMBER = 2
HOST = "raw.githubusercontent.com"
INCOMING = Path("/var/lib/signal-ledger-pr-rehearsal/incoming")
INSTALL_ROOT = Path("/usr/local/libexec/signal-ledger-pr-rehearsal")
STATE_ROOT = Path("/var/lib/signal-ledger-pr-rehearsal")
INSTALLED_MANIFEST = INSTALL_ROOT / "installed.json"
REVISION_RE = re.compile(r"^[0-9a-f]{40}$")
DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
ASSETS = {
    "bootstrap": ("scripts/pr_rehearsal_bootstrap.py", "bootstrap.py", 256 * 1024),
    "host_helper": ("scripts/pr_rehearsal_host_helper.py", "host_helper.py", 256 * 1024),
    "seed": ("scripts/pr_rehearsal_seed.py", "seed.py", 64 * 1024),
    "driver": ("tests/native_assistant_probe.py", "native_driver.py", 2 * 1024 * 1024),
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


def _verify_pull_request(revision: str) -> None:
    connection = http.client.HTTPSConnection("api.github.com", timeout=10)
    try:
        connection.request(
            "GET",
            f"/repos/{REPOSITORY}/pulls/{PULL_NUMBER}",
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


def install(payload: object) -> dict[str, object]:
    if not isinstance(payload, dict) or set(payload) != {
        "reviewed_head_sha",
        "reviewed_pair_manifest_sha256",
        "asset_sha256",
    }:
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
    if not isinstance(hashes, dict) or set(hashes) != set(ASSETS):
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
    _verify_pull_request(revision)

    verified: dict[str, str] = {}
    contents: dict[str, bytes] = {}
    for key, (relative_path, _staged_name, maximum) in ASSETS.items():
        local = _read_staged(_staged_asset_path(revision, key), maximum)
        digest = hashlib.sha256(local).hexdigest()
        if digest != hashes[key]:
            raise InstallError("asset_digest_mismatch")
        upstream = _fetch_reviewed_source(revision, relative_path, maximum)
        if upstream != local:
            raise InstallError("asset_source_mismatch")
        contents[key] = local
        verified[key] = digest

    for key, (_relative, installed_name, _maximum) in ASSETS.items():
        if key == "bootstrap":
            continue
        _atomic_root_file(
            INSTALL_ROOT / installed_name, contents[key], 0o750 if key == "host_helper" else 0o640
        )

    receipt = {
        "format_version": 1,
        "repository": REPOSITORY,
        "pull_number": PULL_NUMBER,
        "reviewed_head_sha": revision,
        "reviewed_pair_manifest_sha256": pair_manifest_digest,
        "files": {
            installed_name: verified[key]
            for key, (_relative, installed_name, _maximum) in ASSETS.items()
            if key != "bootstrap"
        },
        "installed_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
    }
    _atomic_root_file(
        INSTALLED_MANIFEST,
        (json.dumps(receipt, sort_keys=True, separators=(",", ":")) + "\n").encode(),
        0o640,
    )
    for key in ASSETS:
        _staged_asset_path(revision, key).unlink(missing_ok=True)
    return {
        "status": "installed",
        "reviewed_head_sha": revision,
        "reviewed_pair_manifest_sha256": pair_manifest_digest,
        "asset_sha256": verified,
    }


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
