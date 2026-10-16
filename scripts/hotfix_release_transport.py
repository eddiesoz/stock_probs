#!/usr/bin/env python3
"""Publish the fixed D282 image and helper-bound pair as separate immutable releases."""

from __future__ import annotations

import hashlib
import json
import os
import re
import selectors
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = ROOT / "test-results" / "assistant-r120-pr-pair"
HOTFIX_SCRATCH_ROOT = Path("/var/tmp/r12r")  # noqa: S108 - task requires UUID-verified private scratch.
HOTFIX_SCRATCH_UUID = "54243c97-49f4-4cf6-a8cb-f6c0f3d48f4e"
REPOSITORY = "eddiesoz/stock_probs"
MAX_ARCHIVE_BYTES = 512 * 1024 * 1024
MAX_JSON_BYTES = 65_536
REVISION_PATTERN = re.compile(r"[0-9a-f]{40}")
DIGEST_PATTERN = re.compile(r"[0-9a-f]{64}")
IMAGE_ID_PATTERN = re.compile(r"sha256:[0-9a-f]{64}")

HOTFIX_CANDIDATE_REVISION = "d282d696937f279ca4af4c38341f82a8af7afb6d"
HOTFIX_CANDIDATE_IMAGE_ID = (
    "sha256:ba607be79055ee3a09d916e51788135590e7e0ead8f0922aa78128c478644c03"
)
HOTFIX_CANDIDATE_CONTEXT_SHA256 = "c2135215d9a96c37841190ff611b49d48e7a08ca88ad073ebcf1973a7abc86a9"
HOTFIX_BUILD_RECEIPT_SHA256 = "bb808883d862aafe8851bfeffc75fa3140866e72e770420699db0f11a4377608"
HOTFIX_CANDIDATE_ARCHIVE_SHA256 = "6b30af17fadf8ffd5af104c7f557c767edee1200551b8f8ef7dc3e932cf7acc7"
HOTFIX_CANDIDATE_ARCHIVE_SIZE = 202_159_985
PRODUCTION_PREDECESSOR_REVISION = "5ad2c3fddfce5a5a631b72cd832a53f24757c44a"
PRODUCTION_PREDECESSOR_IMAGE_ID = (
    "sha256:78746f600815cac1941a9060f91bba41aca08f363714db466200c2d77e8ad7b1"
)
PRODUCTION_PREDECESSOR_CONTEXT_SHA256 = (
    "9f2abef917d4832783d32cfbf31290cc50df76c942b4238aa7f1330d4bc4f7bb"
)
PRODUCTION_PREDECESSOR_ARCHIVE_SHA256 = (
    "99b198f169958e63a4b1ee2380fa805c82a3bc75352d17f8feae2e4ad41185e5"
)
PRODUCTION_PREDECESSOR_ARCHIVE_SIZE = 202_156_038
PRODUCTION_PREDECESSOR_PRIOR_PAIR_SHA256 = (
    "e9b7462aa6d5bf04201717a28644df085c58b5634125a2f9bb1aa096a7253ed3"
)
HOTFIX_EMPTY_OVERLAY_SHA256 = hashlib.sha256(b"[]").hexdigest()
HOTFIX_PAIR_CONTRACT = "schema13_same_schema_hotfix_v1"
SCANNER_PATH = ROOT / "scripts" / "verify-release-archive.py"
# PR12 is the reviewed scanner that inspects every archive member and Docker config metadata.
RELEASE_SCANNER_SHA256 = "314179e4b41d34c0f060867c1868b36b13528cd1567da938f5f72b401b617163"
DOWNLOAD_TIMEOUT_SECONDS = 180
COMMAND_OUTPUT_LIMIT = 16_384


class PublicationError(ValueError):
    """A bounded, sanitized publication failure."""


@dataclass(frozen=True)
class Archive:
    """One fixed image archive bound to its v2 manifest."""

    name: str
    path: Path
    sha256: str
    size: int
    image_id: str
    revision: str
    source_context_sha256: str


@dataclass(frozen=True)
class Package:
    """A validated pair package prepared from the frozen D282 and 5ad images."""

    root: Path
    helper_revision: str
    manifest_name: str
    manifest_path: Path
    manifest_sha256: str
    manifest_size: int
    candidate: Archive
    predecessor: Archive


def _valid(pattern: re.Pattern[str], value: object) -> bool:
    return isinstance(value, str) and pattern.fullmatch(value) is not None


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise PublicationError("duplicate_package_json_key")
        value[key] = item
    return value


def _same_file_state(before: os.stat_result, after: os.stat_result) -> bool:
    return all(
        getattr(before, field) == getattr(after, field)
        for field in (
            "st_dev",
            "st_ino",
            "st_mode",
            "st_uid",
            "st_gid",
            "st_size",
            "st_mtime_ns",
            "st_ctime_ns",
        )
    )


def _read_regular_file(path: Path, maximum: int, *, private: bool = True) -> bytes:
    try:
        before = path.lstat()
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or before.st_uid != os.getuid()
            or (private and stat.S_IMODE(before.st_mode) & 0o077)
            or not 1 <= before.st_size <= maximum
        ):
            raise PublicationError("package_file_unsafe")
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK)
        try:
            opened = os.fstat(descriptor)
            if not _same_file_state(before, opened):
                raise PublicationError("package_file_changed")
            chunks: list[bytes] = []
            size = 0
            while chunk := os.read(descriptor, min(1024 * 1024, maximum + 1 - size)):
                size += len(chunk)
                if size > maximum:
                    raise PublicationError("package_file_too_large")
                chunks.append(chunk)
            after = os.fstat(descriptor)
        finally:
            os.close(descriptor)
        try:
            current = path.lstat()
        except OSError as exc:
            raise PublicationError("package_file_changed") from exc
        if (
            not _same_file_state(before, after)
            or not _same_file_state(before, current)
            or size != before.st_size
        ):
            raise PublicationError("package_file_changed")
        return b"".join(chunks)
    except PublicationError:
        raise
    except OSError as exc:
        raise PublicationError("package_file_unavailable") from exc


def _hash_regular_file(path: Path, maximum: int, *, private: bool = True) -> tuple[str, int]:
    try:
        before = path.lstat()
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or before.st_uid != os.getuid()
            or (private and stat.S_IMODE(before.st_mode) & 0o077)
            or not 1 <= before.st_size <= maximum
        ):
            raise PublicationError("package_file_unsafe")
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK)
        digest = hashlib.sha256()
        size = 0
        try:
            opened = os.fstat(descriptor)
            if not _same_file_state(before, opened):
                raise PublicationError("package_file_changed")
            while chunk := os.read(descriptor, min(1024 * 1024, maximum + 1 - size)):
                size += len(chunk)
                if size > maximum:
                    raise PublicationError("package_file_too_large")
                digest.update(chunk)
            after = os.fstat(descriptor)
        finally:
            os.close(descriptor)
        current = path.lstat()
        if (
            not _same_file_state(before, after)
            or not _same_file_state(before, current)
            or size != before.st_size
        ):
            raise PublicationError("package_file_changed")
        return digest.hexdigest(), size
    except PublicationError:
        raise
    except OSError as exc:
        raise PublicationError("package_file_unavailable") from exc


def _read_json(path: Path) -> tuple[dict[str, Any], bytes]:
    raw = _read_regular_file(path, MAX_JSON_BYTES)
    try:
        value = json.loads(raw, object_pairs_hook=_unique_object)
    except (UnicodeDecodeError, json.JSONDecodeError, PublicationError) as exc:
        raise PublicationError("package_json_invalid") from exc
    if not isinstance(value, dict):
        raise PublicationError("package_json_invalid")
    return value, raw


def _fixed_archive_name(revision: str) -> str:
    if not _valid(REVISION_PATTERN, revision):
        raise PublicationError("archive_revision_invalid")
    return f"signal-ledger-image-{revision}.tar.gz"


def _expected_manifest(helper_revision: str) -> dict[str, Any]:
    if not _valid(REVISION_PATTERN, helper_revision):
        raise PublicationError("helper_revision_invalid")
    candidate_name = _fixed_archive_name(HOTFIX_CANDIDATE_REVISION)
    predecessor_name = _fixed_archive_name(PRODUCTION_PREDECESSOR_REVISION)
    return {
        "format_version": 2,
        "contract": HOTFIX_PAIR_CONTRACT,
        "repository": REPOSITORY,
        "revision": helper_revision,
        "helper_source": {"pull_number": 11, "revision": helper_revision},
        "candidate": {
            "asset": candidate_name,
            "archive_sha256": HOTFIX_CANDIDATE_ARCHIVE_SHA256,
            "archive_size": HOTFIX_CANDIDATE_ARCHIVE_SIZE,
            "image_id": HOTFIX_CANDIDATE_IMAGE_ID,
            "platform": "linux/amd64",
            "pull_number": 9,
            "revision": HOTFIX_CANDIDATE_REVISION,
            "schema_version": 13,
            "source_context_sha256": HOTFIX_CANDIDATE_CONTEXT_SHA256,
            "build_receipt_sha256": HOTFIX_BUILD_RECEIPT_SHA256,
        },
        "recovery": {
            "asset": predecessor_name,
            "archive_sha256": PRODUCTION_PREDECESSOR_ARCHIVE_SHA256,
            "archive_size": PRODUCTION_PREDECESSOR_ARCHIVE_SIZE,
            "image_id": PRODUCTION_PREDECESSOR_IMAGE_ID,
            "platform": "linux/amd64",
            "revision": PRODUCTION_PREDECESSOR_REVISION,
            "schema_version": 13,
            "source_context_sha256": PRODUCTION_PREDECESSOR_CONTEXT_SHA256,
            "kind": "previous_production_candidate",
            "prior_pair_manifest_sha256": PRODUCTION_PREDECESSOR_PRIOR_PAIR_SHA256,
            "assistant_rollout_mode": "invited",
        },
        "transition": {"from_schema": 13, "to_schema": 13, "migrations": [], "restore": False},
        "recovery_overlay": {"kind": "none", "sha256": HOTFIX_EMPTY_OVERLAY_SHA256},
    }


def _validate_package_root(root: Path) -> None:
    try:
        parent = root.parent
        parent_info = parent.lstat()
        info = root.lstat()
    except OSError as exc:
        raise PublicationError("package_directory_unavailable") from exc
    if (
        not stat.S_ISDIR(parent_info.st_mode)
        or stat.S_ISLNK(parent_info.st_mode)
        or parent_info.st_uid != os.getuid()
        or not stat.S_ISDIR(info.st_mode)
        or stat.S_ISLNK(info.st_mode)
        or info.st_uid != os.getuid()
        or stat.S_IMODE(info.st_mode) != 0o700
    ):
        raise PublicationError("package_directory_unsafe")


def validate_package(root: Path, helper_revision: str) -> Package:
    """Verify fixed D282/5ad archive bytes and all v2 publication/source identities."""

    _validate_package_root(root)
    if not _valid(REVISION_PATTERN, helper_revision):
        raise PublicationError("helper_revision_invalid")
    receipt, _ = _read_json(root / "package-receipt.json")
    candidate_name = _fixed_archive_name(HOTFIX_CANDIDATE_REVISION)
    predecessor_name = _fixed_archive_name(PRODUCTION_PREDECESSOR_REVISION)
    manifest_name = f"signal-ledger-pair-{helper_revision}.json"
    expected_receipt = {
        "status": "prepared",
        "contract": HOTFIX_PAIR_CONTRACT,
        "helper_source_revision": helper_revision,
        "hotfix_pull_number": 9,
        "candidate_archive_name": candidate_name,
        "candidate_archive_sha256": HOTFIX_CANDIDATE_ARCHIVE_SHA256,
        "candidate_archive_size": HOTFIX_CANDIDATE_ARCHIVE_SIZE,
        "candidate_image": {
            "architecture": "linux/amd64",
            "id": HOTFIX_CANDIDATE_IMAGE_ID,
            "revision_label": HOTFIX_CANDIDATE_REVISION,
            "source_context_sha256": HOTFIX_CANDIDATE_CONTEXT_SHA256,
        },
        "recovery_archive_name": predecessor_name,
        "recovery_archive_sha256": PRODUCTION_PREDECESSOR_ARCHIVE_SHA256,
        "recovery_archive_size": PRODUCTION_PREDECESSOR_ARCHIVE_SIZE,
        "recovery_image": {
            "architecture": "linux/amd64",
            "id": PRODUCTION_PREDECESSOR_IMAGE_ID,
            "revision_label": PRODUCTION_PREDECESSOR_REVISION,
            "source_context_sha256": PRODUCTION_PREDECESSOR_CONTEXT_SHA256,
        },
        "prior_pair_manifest_sha256": PRODUCTION_PREDECESSOR_PRIOR_PAIR_SHA256,
        "migration_commands": 0,
        "restore_commands": 0,
        "manifest_name": manifest_name,
    }
    if set(receipt) != set(expected_receipt) | {"manifest_sha256"}:
        raise PublicationError("package_receipt_fields_invalid")
    for field, expected in expected_receipt.items():
        actual = receipt.get(field)
        if type(actual) is not type(expected) or actual != expected:
            raise PublicationError("package_receipt_identity_mismatch")
    if not _valid(DIGEST_PATTERN, receipt.get("manifest_sha256")):
        raise PublicationError("package_receipt_identity_mismatch")

    manifest_path = root / manifest_name
    manifest, raw_manifest = _read_json(manifest_path)
    canonical = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    manifest_sha256 = hashlib.sha256(raw_manifest).hexdigest()
    if (
        raw_manifest != canonical
        or manifest_sha256 != receipt["manifest_sha256"]
        or manifest != _expected_manifest(helper_revision)
    ):
        raise PublicationError("hotfix_manifest_identity_mismatch")

    candidate_path = root / candidate_name
    predecessor_path = root / predecessor_name
    candidate_sha256, candidate_size = _hash_regular_file(candidate_path, MAX_ARCHIVE_BYTES)
    predecessor_sha256, predecessor_size = _hash_regular_file(predecessor_path, MAX_ARCHIVE_BYTES)
    if (candidate_sha256, candidate_size) != (
        HOTFIX_CANDIDATE_ARCHIVE_SHA256,
        HOTFIX_CANDIDATE_ARCHIVE_SIZE,
    ) or (predecessor_sha256, predecessor_size) != (
        PRODUCTION_PREDECESSOR_ARCHIVE_SHA256,
        PRODUCTION_PREDECESSOR_ARCHIVE_SIZE,
    ):
        raise PublicationError("hotfix_archive_identity_mismatch")
    return Package(
        root=root,
        helper_revision=helper_revision,
        manifest_name=manifest_name,
        manifest_path=manifest_path,
        manifest_sha256=manifest_sha256,
        manifest_size=len(raw_manifest),
        candidate=Archive(
            candidate_name,
            candidate_path,
            candidate_sha256,
            candidate_size,
            HOTFIX_CANDIDATE_IMAGE_ID,
            HOTFIX_CANDIDATE_REVISION,
            HOTFIX_CANDIDATE_CONTEXT_SHA256,
        ),
        predecessor=Archive(
            predecessor_name,
            predecessor_path,
            predecessor_sha256,
            predecessor_size,
            PRODUCTION_PREDECESSOR_IMAGE_ID,
            PRODUCTION_PREDECESSOR_REVISION,
            PRODUCTION_PREDECESSOR_CONTEXT_SHA256,
        ),
    )


def _command(argv: list[str], *, timeout: int = 30) -> str:
    process: subprocess.Popen[bytes] | None = None
    selector = selectors.DefaultSelector()
    output = {"stdout": bytearray(), "stderr": bytearray()}
    deadline = time.monotonic() + timeout
    completed = False
    try:
        process = subprocess.Popen(  # noqa: S603 - internal callers supply fixed command templates and validated identifiers.
            argv,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=ROOT,
            start_new_session=True,
        )
        assert process.stdout is not None and process.stderr is not None
        for name, stream in (("stdout", process.stdout), ("stderr", process.stderr)):
            os.set_blocking(stream.fileno(), False)
            selector.register(stream, selectors.EVENT_READ, name)
        while selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise PublicationError("bounded_command_timeout")
            for key, _ in selector.select(remaining):
                try:
                    buffered = len(output["stdout"]) + len(output["stderr"])
                    chunk = os.read(
                        key.fileobj.fileno(),
                        min(4096, COMMAND_OUTPUT_LIMIT + 1 - buffered),
                    )
                except BlockingIOError:
                    continue
                if not chunk:
                    selector.unregister(key.fileobj)
                    key.fileobj.close()
                    continue
                if (
                    len(output["stdout"]) + len(output["stderr"]) + len(chunk)
                    > COMMAND_OUTPUT_LIMIT
                ):
                    raise PublicationError("bounded_command_output_exceeded")
                output[key.data].extend(chunk)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise PublicationError("bounded_command_timeout")
        returncode = process.wait(timeout=remaining)
        completed = True
    except PublicationError:
        raise
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise PublicationError("bounded_command_unavailable") from exc
    finally:
        selector.close()
        if process is not None and not completed:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            except OSError:
                if process.poll() is None:
                    process.kill()
            if process.poll() is None:
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired as exc:
                        raise PublicationError("bounded_command_cleanup_unavailable") from exc
        if process is not None:
            for stream in (process.stdout, process.stderr):
                if stream is not None and not stream.closed:
                    stream.close()
    if returncode != 0:
        raise PublicationError("bounded_command_failed")
    try:
        return output["stdout"].decode("utf-8")
    except UnicodeDecodeError as exc:
        raise PublicationError("bounded_command_output_invalid") from exc


def _validate_current_source(helper_revision: str) -> None:
    """Require the publisher entry point's clean exact-origin/main boundary again."""

    try:
        git = shutil.which("git", path=os.defpath)
        if git is None:
            raise PublicationError("reviewed_source_unavailable")
        head = _command([git, "rev-parse", "--verify", "HEAD"]).strip()
        status = _command([git, "status", "--porcelain", "--untracked-files=normal"])
        remote = _command([git, "ls-remote", "origin", "refs/heads/main"]).split()
        ancestor = subprocess.run(  # noqa: S603 - fixed Git executable and validated commit IDs.
            [git, "merge-base", "--is-ancestor", HOTFIX_CANDIDATE_REVISION, helper_revision],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=10,
            check=False,
            cwd=ROOT,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise PublicationError("reviewed_source_unavailable") from exc
    if (
        head != helper_revision
        or status
        or not remote
        or remote[0] != helper_revision
        or ancestor.returncode != 0
    ):
        raise PublicationError("reviewed_source_identity_mismatch")


def _verify_scanner_source() -> None:
    digest, _ = _hash_regular_file(SCANNER_PATH, 1024 * 1024, private=False)
    if digest != RELEASE_SCANNER_SHA256:
        raise PublicationError("reviewed_release_scanner_unavailable")


def _scan_archive(archive: Archive) -> None:
    _verify_scanner_source()
    output = _command(
        [sys.executable, str(SCANNER_PATH), str(archive.path)],
        timeout=DOWNLOAD_TIMEOUT_SECONDS,
    )
    try:
        result = json.loads(output, object_pairs_hook=_unique_object)
    except (json.JSONDecodeError, PublicationError) as exc:
        raise PublicationError("release_archive_scan_invalid") from exc
    if (
        not isinstance(result, dict)
        or result.get("status") != "pass"
        or result.get("archive_sha256") != archive.sha256
        or type(result.get("archive_size")) is not int
        or result.get("archive_size") != archive.size
        or type(result.get("layer_count")) is not int
        or result.get("layer_count", 0) < 1
    ):
        raise PublicationError("release_archive_scan_mismatch")


def _gh(arguments: list[str], *, timeout: int = 60) -> str:
    return _command(["gh", *arguments], timeout=timeout)


def _require_hotfix_scratch_mount() -> None:
    """Require the task-approved UUID-backed scratch before creating readback files."""

    try:
        metadata = HOTFIX_SCRATCH_ROOT.lstat()
    except OSError as exc:
        raise PublicationError("release_readback_scratch_unavailable") from exc
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or stat.S_ISLNK(metadata.st_mode)
        or metadata.st_uid != os.getuid()
        or stat.S_IMODE(metadata.st_mode) != 0o700
    ):
        raise PublicationError("release_readback_scratch_unsafe")
    findmnt = shutil.which("findmnt", path=os.defpath)
    if findmnt is None:
        raise PublicationError("release_readback_scratch_unavailable")
    actual_uuid = _command(
        [findmnt, "--noheadings", "--output", "UUID", "--target", str(HOTFIX_SCRATCH_ROOT)]
    ).strip()
    if actual_uuid != HOTFIX_SCRATCH_UUID:
        raise PublicationError("release_readback_scratch_identity_mismatch")


def _make_download_private(path: Path, maximum: int) -> None:
    """Set a just-downloaded regular file to mode 0600 through a no-follow descriptor."""

    try:
        before = path.lstat()
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_nlink != 1
            or before.st_uid != os.getuid()
            or not 1 <= before.st_size <= maximum
        ):
            raise PublicationError("release_readback_file_unsafe")
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK)
        try:
            opened = os.fstat(descriptor)
            if not _same_file_state(before, opened):
                raise PublicationError("release_readback_file_changed")
            os.fchmod(descriptor, 0o600)
            after = os.fstat(descriptor)
        finally:
            os.close(descriptor)
        current = path.lstat()
        stable_fields = (
            "st_dev",
            "st_ino",
            "st_uid",
            "st_gid",
            "st_size",
            "st_mtime_ns",
        )
        if (
            any(getattr(before, field) != getattr(after, field) for field in stable_fields)
            or not stat.S_ISREG(after.st_mode)
            or stat.S_IMODE(after.st_mode) != 0o600
            or not _same_file_state(after, current)
        ):
            raise PublicationError("release_readback_file_changed")
    except PublicationError:
        raise
    except OSError as exc:
        raise PublicationError("release_readback_file_unavailable") from exc


def _release_view(tag: str, asset_name: str) -> dict[str, Any]:
    if not re.fullmatch(r"signal-ledger-(?:[0-9a-f]{40}|hotfix-pair-[0-9a-f]{40})", tag):
        raise PublicationError("release_tag_invalid")
    if not re.fullmatch(
        r"signal-ledger-(?:image|pair)-[0-9a-f]{40}\.tar\.gz|signal-ledger-pair-[0-9a-f]{40}\.json",
        asset_name,
    ):
        raise PublicationError("release_asset_invalid")
    query = (
        "{targetCommitish,assetCount:(.assets|length),matches:"
        f'([.assets[]|select(.name=="{asset_name}")|{{name,size}}][:2])}}'
    )
    output = _gh(
        [
            "release",
            "view",
            tag,
            "--repo",
            REPOSITORY,
            "--json",
            "targetCommitish,assets",
            "--jq",
            query,
        ]
    )
    try:
        value = json.loads(output, object_pairs_hook=_unique_object)
    except (json.JSONDecodeError, PublicationError) as exc:
        raise PublicationError("release_metadata_invalid") from exc
    if not isinstance(value, dict):
        raise PublicationError("release_metadata_invalid")
    return value


def _assert_release_asset(
    tag: str,
    target_revision: str,
    archive: Archive,
    *,
    exact_asset_count: bool,
) -> None:
    value = _release_view(tag, archive.name)
    matches = value.get("matches")
    if (
        value.get("targetCommitish") != target_revision
        or (exact_asset_count and value.get("assetCount") != 1)
        or not isinstance(matches, list)
        or len(matches) != 1
        or not isinstance(matches[0], dict)
        or matches[0].get("name") != archive.name
        or type(matches[0].get("size")) is not int
        or matches[0]["size"] != archive.size
    ):
        raise PublicationError("published_release_identity_mismatch")


def _download_and_verify(tag: str, archive: Archive, directory: Path) -> None:
    directory.mkdir(mode=0o700)
    directory.chmod(0o700)
    _gh(
        [
            "release",
            "download",
            tag,
            "--repo",
            REPOSITORY,
            "--pattern",
            archive.name,
            "--dir",
            str(directory),
        ],
        timeout=DOWNLOAD_TIMEOUT_SECONDS,
    )
    downloaded = directory / archive.name
    entries = list(directory.iterdir())
    if len(entries) != 1 or entries[0] != downloaded:
        raise PublicationError("published_asset_readback_mismatch")
    _make_download_private(downloaded, MAX_ARCHIVE_BYTES)
    digest, size = _hash_regular_file(downloaded, MAX_ARCHIVE_BYTES)
    if (digest, size) != (archive.sha256, archive.size):
        raise PublicationError("published_asset_readback_mismatch")


def _temporary_readback() -> tempfile.TemporaryDirectory[str]:
    _require_hotfix_scratch_mount()
    try:
        return tempfile.TemporaryDirectory(
            prefix="signal-ledger-hotfix-readback-",
            dir=HOTFIX_SCRATCH_ROOT,
        )
    except OSError as exc:
        raise PublicationError("release_readback_scratch_unavailable") from exc


def _copy_verified_package_file(
    source: Path,
    destination: Path,
    *,
    expected_sha256: str,
    expected_size: int,
    maximum: int,
    mismatch_error: str,
) -> None:
    """Copy one pinned package member into an exclusive private snapshot."""

    source_descriptor = -1
    destination_descriptor = -1
    try:
        source_before = source.lstat()
        if (
            not stat.S_ISREG(source_before.st_mode)
            or source_before.st_nlink != 1
            or source_before.st_uid != os.getuid()
            or stat.S_IMODE(source_before.st_mode) & 0o077
            or not 1 <= source_before.st_size <= maximum
        ):
            raise PublicationError("package_file_unsafe")
        if source_before.st_size != expected_size:
            raise PublicationError(mismatch_error)

        source_descriptor = os.open(
            source,
            os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK,
        )
        destination_descriptor = os.open(
            destination,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK,
            0o600,
        )
        source_opened = os.fstat(source_descriptor)
        if not _same_file_state(source_before, source_opened):
            raise PublicationError("package_file_changed")

        digest = hashlib.sha256()
        copied_size = 0
        while True:
            chunk = os.read(
                source_descriptor,
                min(1024 * 1024, expected_size + 1 - copied_size),
            )
            if not chunk:
                break
            copied_size += len(chunk)
            if copied_size > expected_size or copied_size > maximum:
                raise PublicationError(mismatch_error)
            digest.update(chunk)
            view = memoryview(chunk)
            while view:
                written = os.write(destination_descriptor, view)
                if written <= 0:
                    raise PublicationError("package_snapshot_write_failed")
                view = view[written:]

        os.fsync(destination_descriptor)
        os.fchmod(destination_descriptor, 0o600)
        source_after = os.fstat(source_descriptor)
        destination_after = os.fstat(destination_descriptor)
        source_path_after = source.lstat()
        destination_path_after = destination.lstat()
        if (
            not _same_file_state(source_before, source_after)
            or not _same_file_state(source_before, source_path_after)
            or copied_size != expected_size
        ):
            raise PublicationError("package_file_changed")
        if digest.hexdigest() != expected_sha256:
            raise PublicationError(mismatch_error)
        if (
            not stat.S_ISREG(destination_after.st_mode)
            or destination_after.st_nlink != 1
            or destination_after.st_uid != os.getuid()
            or stat.S_IMODE(destination_after.st_mode) != 0o600
            or destination_after.st_size != copied_size
            or not _same_file_state(destination_after, destination_path_after)
        ):
            raise PublicationError("package_snapshot_invalid")
        snapshot_sha256, snapshot_size = _hash_regular_file(destination, maximum)
        if (snapshot_sha256, snapshot_size) != (expected_sha256, expected_size):
            raise PublicationError("package_snapshot_invalid")
    except PublicationError:
        raise
    except OSError as exc:
        raise PublicationError("package_snapshot_unavailable") from exc
    finally:
        if source_descriptor >= 0:
            os.close(source_descriptor)
        if destination_descriptor >= 0:
            os.close(destination_descriptor)


@contextmanager
def _staged_package(package: Package) -> Iterator[Package]:
    """Publish only the verified private copies, never mutable package inputs."""

    _require_hotfix_scratch_mount()
    try:
        with tempfile.TemporaryDirectory(
            prefix=f"signal-ledger-hotfix-stage-{uuid.uuid4()}-",
            dir=HOTFIX_SCRATCH_ROOT,
        ) as temporary:
            root = Path(temporary)
            root_metadata = root.lstat()
            if (
                not stat.S_ISDIR(root_metadata.st_mode)
                or stat.S_ISLNK(root_metadata.st_mode)
                or root_metadata.st_uid != os.getuid()
                or stat.S_IMODE(root_metadata.st_mode) != 0o700
            ):
                raise PublicationError("package_snapshot_directory_unsafe")
            candidate_path = root / package.candidate.name
            predecessor_path = root / package.predecessor.name
            manifest_path = root / package.manifest_name
            _copy_verified_package_file(
                package.candidate.path,
                candidate_path,
                expected_sha256=package.candidate.sha256,
                expected_size=package.candidate.size,
                maximum=MAX_ARCHIVE_BYTES,
                mismatch_error="hotfix_archive_identity_mismatch",
            )
            _copy_verified_package_file(
                package.predecessor.path,
                predecessor_path,
                expected_sha256=package.predecessor.sha256,
                expected_size=package.predecessor.size,
                maximum=MAX_ARCHIVE_BYTES,
                mismatch_error="hotfix_archive_identity_mismatch",
            )
            _copy_verified_package_file(
                package.manifest_path,
                manifest_path,
                expected_sha256=package.manifest_sha256,
                expected_size=package.manifest_size,
                maximum=MAX_JSON_BYTES,
                mismatch_error="hotfix_manifest_identity_mismatch",
            )
            yield Package(
                root=root,
                helper_revision=package.helper_revision,
                manifest_name=package.manifest_name,
                manifest_path=manifest_path,
                manifest_sha256=package.manifest_sha256,
                manifest_size=package.manifest_size,
                candidate=Archive(
                    package.candidate.name,
                    candidate_path,
                    package.candidate.sha256,
                    package.candidate.size,
                    package.candidate.image_id,
                    package.candidate.revision,
                    package.candidate.source_context_sha256,
                ),
                predecessor=Archive(
                    package.predecessor.name,
                    predecessor_path,
                    package.predecessor.sha256,
                    package.predecessor.size,
                    package.predecessor.image_id,
                    package.predecessor.revision,
                    package.predecessor.source_context_sha256,
                ),
            )
    except PublicationError:
        raise
    except OSError as exc:
        raise PublicationError("package_snapshot_unavailable") from exc


def _create_release(tag: str, target: str, title: str, notes: str, *assets: Path) -> None:
    if not assets or any(not asset.is_file() or asset.is_symlink() for asset in assets):
        raise PublicationError("release_asset_unavailable")
    _gh(
        [
            "release",
            "create",
            tag,
            *(str(asset) for asset in assets),
            "--repo",
            REPOSITORY,
            "--target",
            target,
            "--title",
            title,
            "--notes",
            notes,
            "--latest=false",
        ],
        timeout=DOWNLOAD_TIMEOUT_SECONDS,
    )


def _publish_candidate(package: Package) -> dict[str, object]:
    tag = f"signal-ledger-{HOTFIX_CANDIDATE_REVISION}"
    _create_release(
        tag,
        HOTFIX_CANDIDATE_REVISION,
        "Signal Ledger reviewed assistant candidate D282",
        "Publishes the exact reviewed D282 Linux amd64 candidate archive.",
        package.candidate.path,
    )
    _assert_release_asset(
        tag,
        HOTFIX_CANDIDATE_REVISION,
        package.candidate,
        exact_asset_count=True,
    )
    with _temporary_readback() as temporary:
        _download_and_verify(tag, package.candidate, Path(temporary) / "candidate")
    return {
        "status": "published_candidate_asset_verified",
        "release_tag": tag,
        "asset": package.candidate.name,
        "archive_sha256": package.candidate.sha256,
        "image_id": package.candidate.image_id,
    }


def _publish_pair(package: Package) -> dict[str, object]:
    candidate_tag = f"signal-ledger-{HOTFIX_CANDIDATE_REVISION}"
    predecessor_tag = f"signal-ledger-{PRODUCTION_PREDECESSOR_REVISION}"
    _assert_release_asset(
        candidate_tag,
        HOTFIX_CANDIDATE_REVISION,
        package.candidate,
        exact_asset_count=True,
    )
    _assert_release_asset(
        predecessor_tag,
        PRODUCTION_PREDECESSOR_REVISION,
        package.predecessor,
        exact_asset_count=False,
    )
    with _temporary_readback() as temporary:
        root = Path(temporary)
        _download_and_verify(candidate_tag, package.candidate, root / "candidate")
        _download_and_verify(predecessor_tag, package.predecessor, root / "predecessor")
    pair_tag = f"signal-ledger-hotfix-pair-{package.helper_revision}"
    _create_release(
        pair_tag,
        package.helper_revision,
        f"Signal Ledger reviewed hotfix pair {package.helper_revision[:12]}",
        "Binds the immutable D282 assistant candidate to the original 5ad production image.",
        package.manifest_path,
    )
    _assert_pair_release(pair_tag, package)
    return {
        "status": "published_hotfix_pair_asset_verified",
        "release_tag": pair_tag,
        "asset": package.manifest_name,
        "manifest_sha256": package.manifest_sha256,
        "candidate_release_tag": candidate_tag,
        "predecessor_release_tag": predecessor_tag,
    }


def _assert_pair_release(tag: str, package: Package) -> None:
    query = (
        '{targetCommitish,assetCount:(.assets|length),matches:([.assets[]|select(.name=="'
        + package.manifest_name
        + '")|{name,size}][:2])}'
    )
    output = _gh(
        [
            "release",
            "view",
            tag,
            "--repo",
            REPOSITORY,
            "--json",
            "targetCommitish,assets",
            "--jq",
            query,
        ]
    )
    try:
        value = json.loads(output, object_pairs_hook=_unique_object)
    except (json.JSONDecodeError, PublicationError) as exc:
        raise PublicationError("release_metadata_invalid") from exc
    if (
        not isinstance(value, dict)
        or value.get("targetCommitish") != package.helper_revision
        or value.get("assetCount") != 1
        or value.get("matches")
        != [{"name": package.manifest_name, "size": package.manifest_path.stat().st_size}]
    ):
        raise PublicationError("published_release_identity_mismatch")
    with _temporary_readback() as temporary:
        directory = Path(temporary) / "pair"
        directory.mkdir(mode=0o700)
        directory.chmod(0o700)
        _gh(
            [
                "release",
                "download",
                tag,
                "--repo",
                REPOSITORY,
                "--pattern",
                package.manifest_name,
                "--dir",
                str(directory),
            ],
            timeout=DOWNLOAD_TIMEOUT_SECONDS,
        )
        downloaded = directory / package.manifest_name
        entries = list(directory.iterdir())
        if len(entries) != 1 or entries[0] != downloaded:
            raise PublicationError("published_asset_readback_mismatch")
        _make_download_private(downloaded, MAX_JSON_BYTES)
        raw = _read_regular_file(downloaded, MAX_JSON_BYTES)
        if hashlib.sha256(raw).hexdigest() != package.manifest_sha256:
            raise PublicationError("published_asset_readback_mismatch")


def publish(
    mode: str, helper_revision: str, package_root: Path = PACKAGE_ROOT
) -> dict[str, object]:
    """Validate current source and package, then publish one immutable release step."""

    if mode not in {"hotfix-candidate", "hotfix-pair"}:
        raise PublicationError("hotfix_publish_mode_invalid")
    _validate_current_source(helper_revision)
    _require_hotfix_scratch_mount()
    package = validate_package(package_root, helper_revision)
    with _staged_package(package) as staged:
        _scan_archive(staged.candidate)
        _scan_archive(staged.predecessor)
        if mode == "hotfix-candidate":
            return _publish_candidate(staged)
        return _publish_pair(staged)


def main(argv: list[str] | None = None) -> int:
    arguments = sys.argv[1:] if argv is None else argv
    if len(arguments) != 2:
        print(
            "hotfix release transport requires a fixed mode and reviewed source revision",
            file=sys.stderr,
        )
        return 2
    try:
        result = publish(arguments[0], arguments[1])
    except PublicationError as exc:
        print(f"hotfix release publication failed: {exc}", file=sys.stderr)
        return 4
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
