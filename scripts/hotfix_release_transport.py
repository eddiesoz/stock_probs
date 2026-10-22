#!/usr/bin/env python3
"""Publish the fixed reviewed candidate and helper-bound pair as immutable releases."""

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

HOTFIX_CANDIDATE_REVISION = "f6a51d5c821e6b1ab7974a94f4ff795da10130bc"
HOTFIX_V3_IMAGE_SOURCE_REVISION = "e40dbc3b721080057a2ab2b9b23565ebf4d85982"
HOTFIX_V3_REVIEWED_PR_HEAD_SHA = "8622e303d63a6d2bc419ef6a97a2fb9601a63f7e"
HOTFIX_V3_REVIEWED_PR9_COMMITS = (
    "a8eee53c21cca79a2d6ddc7b2451f89f5e60be7c",
    "7f66bc6cddb1f389b052714b4872828a3447b127",
    "9e0680b343cbc1097bc29fdc709a24a7537290a1",
    "1e134da0ad68ad4fe960714e2ea8911e3ee8d8aa",
    "8622e303d63a6d2bc419ef6a97a2fb9601a63f7e",
)
HOTFIX_V3_REVIEWED_PR9_FILE_DELTA = (
    (
        "MVP-PLAN.md",
        "d8c3646dcefd04ff2c8c9f3b8e38475500185405",
        "1d05707f2c7edbc82cec60a6e1e319ab4e3822fd",
        398,
        0,
    ),
    (
        "docs/develop/testing.md",
        "4fdb2800bf272d42e67519745bcb2daa063c70a6",
        "0386703d80211eda58b6740b7bac7904663ff3bf",
        59,
        0,
    ),
    (
        "tests/test_assistant_api.py",
        "888a32b17a2671aea3c2c87126c7e1f8f19e07e5",
        "3fdbecf1554916eb82c8c9cec49f02bd39487110",
        7,
        3,
    ),
    (
        "tests/test_assistant_final_boundary_coverage.py",
        "652d04666bb17f9b1cd9f93f66a6abeb58b8ffa6",
        "a9ea3c43c160123e812e03d82ced3cb9cab3eac7",
        4,
        2,
    ),
    (
        "tests/test_assistant_provider_admin_api_flows.py",
        "29959b587e3a53ce7b3b8f787000130a5771004e",
        "a31ef10d9d2fa226ffb613208e9ce8e5773fa85f",
        4,
        6,
    ),
    (
        "tests/test_assistant_runtime_event_http_flows.py",
        "d076fb753fcf7899082eada854b59e5fc564f6a4",
        "1bb3e947e051a3839494f82df1f75daea944d479",
        17,
        3,
    ),
    (
        "tests/test_backup_automation.py",
        "95d8b5f7305b2ce6e3b8f0db55fa9b19c03deed3",
        "2570d14bf93fac0f6a794fe5aa19bb2fc2ef3f92",
        22,
        2,
    ),
    (
        "tests/test_browser_assistant_fixture.py",
        "0000000000000000000000000000000000000000",
        "1ede43e34010ed48d5282c79c5ea3e1f5424876f",
        85,
        0,
    ),
    (
        "tests/test_history_repository.py",
        "81aae5be41362912d1697b132cc8aa24032fea57",
        "7676736e90ef20b0e80f89bd33e6e1aa18f92bb3",
        11,
        8,
    ),
    (
        "tools/browser/assistant_qa_server.py",
        "ba6bbdd01d5a9e62f5e99d82b99152151f394bf2",
        "2e6e4ecd861a5453b1498b184f57169fbfd68e9d",
        84,
        60,
    ),
    (
        "tools/browser/tests/assistant.spec.js",
        "3734a80eae843a382ac9b49bc2ec51d77b046903",
        "5d4be699bceba523aef8fdb1f25943e01c62ae6f",
        13,
        1,
    ),
    (
        "tools/browser/tests/fixtures.js",
        "89468fe1a51ab1a7fa46b9fc1f169bf3a1028230",
        "c517ba1ff6c8606042cbff041572cc5f628f2b79",
        10,
        1,
    ),
)
HOTFIX_V3_REVIEWED_TEST_PATCH = (
    '-        assert context["authorization_check"]() is True',
    '+        authorization_check = context["authorization_check"]',
    "+        assert callable(authorization_check)",
    "+        assert asyncio.run(authorization_check()) is True",
    '-        assert context["authorization_check"]() is False',
    "+        assert asyncio.run(authorization_check()) is False",
)
HOTFIX_V3_IMAGE_ID = "sha256:76aecf5483a38a0328f8560e1ae6a09d90f248e712d1dc719f765a224c7ccd2a"
HOTFIX_V3_IMAGE_CONTEXT_SHA256 = "16dba274c8485b69d3c798ea5f9a587c980eb37dbf6c0e64db2bcbc49ab8bf6c"
HOTFIX_V3_BUILD_RECEIPT_SHA256 = "b7810ed4ff96e96207a88886c8d9d1ec81625dc6d73ee1cd0d45121f25fd9ced"
HOTFIX_CANDIDATE_IMAGE_ID = (
    "sha256:52154c40d23c785f1d5522977c3add663ba6d3bffcc6c669cc2732c52cfdd196"
)
HOTFIX_CANDIDATE_CONTEXT_SHA256 = "a332dca5d27f4bb6fda4673e826096158c038e218f6291f01069951378c4fbae"
HOTFIX_BUILD_RECEIPT_SHA256 = "d3529f24499ea2f3b7921055a4308be019798b7be083fc6e75f1ad94b205b0b5"
HOTFIX_CANDIDATE_ARCHIVE_SHA256 = "c0e9d0fe89e53fef4c8f3173a5f2403d32a32f69b7591bc89e7d7ae129199f82"
HOTFIX_CANDIDATE_ARCHIVE_SIZE = 202_160_947
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
HOTFIX_PAIR_CONTRACT_V3 = "schema13_same_schema_hotfix_v3"
SCANNER_PATH = ROOT / "scripts" / "verify-release-archive.py"
# PR12 is the reviewed scanner that inspects every archive member and Docker config metadata.
RELEASE_SCANNER_SHA256 = "9b7c1a4a227220282d90b6d3e8fc3d4e5b6904bf3774bf31530c84713df4585e"
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
    """A validated pair package prepared from the reviewed candidate and original 5ad images."""

    root: Path
    helper_revision: str
    manifest_name: str
    manifest_path: Path
    manifest_sha256: str
    manifest_size: int
    candidate: Archive
    predecessor: Archive
    reviewed_pr_head_sha: str | None = None


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


def _expected_manifest_v3(
    helper_revision: str,
    reviewed_pr_head_sha: str,
    *,
    candidate_archive_sha256: str,
    candidate_archive_size: int,
) -> dict[str, Any]:
    """Build the v3 pair manifest with independent PR, helper, and image identities."""

    if not _valid(REVISION_PATTERN, helper_revision):
        raise PublicationError("helper_revision_invalid")
    if not _valid(REVISION_PATTERN, reviewed_pr_head_sha):
        raise PublicationError("reviewed_pr_head_invalid")
    if reviewed_pr_head_sha != HOTFIX_V3_REVIEWED_PR_HEAD_SHA:
        raise PublicationError("reviewed_pr_head_unreviewed")
    if (
        not _valid(DIGEST_PATTERN, candidate_archive_sha256)
        or type(candidate_archive_size) is not int
        or not 1 <= candidate_archive_size <= MAX_ARCHIVE_BYTES
    ):
        raise PublicationError("candidate_archive_identity_invalid")
    candidate_name = _fixed_archive_name(HOTFIX_V3_IMAGE_SOURCE_REVISION)
    predecessor_name = _fixed_archive_name(PRODUCTION_PREDECESSOR_REVISION)
    return {
        "format_version": 3,
        "contract": HOTFIX_PAIR_CONTRACT_V3,
        "repository": REPOSITORY,
        "revision": helper_revision,
        "reviewed_pr_head_sha": reviewed_pr_head_sha,
        "image_source_revision": HOTFIX_V3_IMAGE_SOURCE_REVISION,
        "helper_source": {"pull_number": 11, "revision": helper_revision},
        "candidate": {
            "asset": candidate_name,
            "archive_sha256": candidate_archive_sha256,
            "archive_size": candidate_archive_size,
            "image_id": HOTFIX_V3_IMAGE_ID,
            "platform": "linux/amd64",
            "pull_number": 9,
            "revision": HOTFIX_V3_IMAGE_SOURCE_REVISION,
            "schema_version": 13,
            "source_context_sha256": HOTFIX_V3_IMAGE_CONTEXT_SHA256,
            "build_receipt_sha256": HOTFIX_V3_BUILD_RECEIPT_SHA256,
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


def _v3_pr9_delta_matches(raw_diff: str, numstat: str) -> bool:
    """Match Git's raw metadata and line counts to the frozen exact PR #9 delta."""

    expected = {
        filename: (base_blob, head_blob, additions, deletions)
        for (
            filename,
            base_blob,
            head_blob,
            additions,
            deletions,
        ) in HOTFIX_V3_REVIEWED_PR9_FILE_DELTA
    }
    raw_records = raw_diff.split("\0")
    if not raw_records or raw_records[-1] != "" or (len(raw_records) - 1) % 2:
        return False
    observed_raw: dict[str, tuple[str, str, str, str]] = {}
    for index in range(0, len(raw_records) - 1, 2):
        fields = raw_records[index].split(" ")
        filename = raw_records[index + 1]
        if (
            len(fields) != 5
            or fields[0] not in {":100644", ":000000"}
            or fields[1] != "100644"
            or fields[4] != ("A" if fields[0] == ":000000" else "M")
            or filename in observed_raw
        ):
            return False
        observed_raw[filename] = (fields[2], fields[3], fields[0], fields[1])
    expected_raw = {
        filename: (
            base_blob,
            head_blob,
            ":000000" if base_blob == ("0" * 40) else ":100644",
            "100644",
        )
        for filename, (base_blob, head_blob, _additions, _deletions) in expected.items()
    }
    if observed_raw != expected_raw:
        return False

    stat_records = numstat.split("\0")
    if not stat_records or stat_records[-1] != "":
        return False
    observed_stats: dict[str, tuple[str, str]] = {}
    for record in stat_records[:-1]:
        fields = record.split("\t")
        if len(fields) != 3 or fields[2] in observed_stats:
            return False
        observed_stats[fields[2]] = (fields[0], fields[1])
    expected_stats = {
        filename: (str(additions), str(deletions))
        for filename, (_base_blob, _head_blob, additions, deletions) in expected.items()
    }
    return observed_stats == expected_stats


def _prove_reviewed_pr9_head(reviewed_pr_head_sha: str, helper_revision: str) -> None:
    """Require the exact approved callback-test patch atop the immutable image source."""

    if not _valid(REVISION_PATTERN, reviewed_pr_head_sha):
        raise PublicationError("reviewed_pr_head_invalid")
    if reviewed_pr_head_sha != HOTFIX_V3_REVIEWED_PR_HEAD_SHA:
        raise PublicationError("reviewed_pr_head_unreviewed")
    if not _valid(REVISION_PATTERN, helper_revision):
        raise PublicationError("helper_revision_invalid")
    for base, descendant in (
        (HOTFIX_V3_IMAGE_SOURCE_REVISION, reviewed_pr_head_sha),
        (reviewed_pr_head_sha, helper_revision),
    ):
        _command(
            ["/usr/bin/git", "merge-base", "--is-ancestor", base, descendant],
            timeout=10,
        )
    commits = _command(
        [
            "/usr/bin/git",
            "rev-list",
            "--reverse",
            f"{HOTFIX_V3_IMAGE_SOURCE_REVISION}..{reviewed_pr_head_sha}",
        ],
        timeout=10,
    )
    expected_commits = "\n".join(HOTFIX_V3_REVIEWED_PR9_COMMITS) + "\n"
    if commits != expected_commits:
        raise PublicationError("reviewed_pr_lineage_mismatch")
    path = "tests/test_assistant_final_boundary_coverage.py"
    raw_diff = _command(
        [
            "/usr/bin/git",
            "diff",
            "--raw",
            "--no-abbrev",
            "-z",
            "--no-renames",
            HOTFIX_V3_IMAGE_SOURCE_REVISION,
            reviewed_pr_head_sha,
        ],
        timeout=10,
    )
    line_counts = _command(
        [
            "/usr/bin/git",
            "diff",
            "--numstat",
            "-z",
            "--no-renames",
            HOTFIX_V3_IMAGE_SOURCE_REVISION,
            reviewed_pr_head_sha,
        ],
        timeout=10,
    )
    patch = _command(
        [
            "/usr/bin/git",
            "diff",
            "--no-ext-diff",
            "--no-renames",
            "--unified=0",
            HOTFIX_V3_IMAGE_SOURCE_REVISION,
            reviewed_pr_head_sha,
            "--",
            path,
        ],
        timeout=10,
    )
    changed_lines = [
        line
        for line in patch.splitlines()
        if (line.startswith("+") and not line.startswith("+++"))
        or (line.startswith("-") and not line.startswith("---"))
    ]
    expected_changed_lines = list(HOTFIX_V3_REVIEWED_TEST_PATCH)
    if not _v3_pr9_delta_matches(raw_diff, line_counts) or changed_lines != expected_changed_lines:
        raise PublicationError("reviewed_pr_test_diff_mismatch")


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


def validate_package(
    root: Path, helper_revision: str, *, reviewed_pr_head_sha: str | None = None
) -> Package:
    """Verify the fixed candidate/5ad bytes and versioned pair identity."""

    _validate_package_root(root)
    if not _valid(REVISION_PATTERN, helper_revision):
        raise PublicationError("helper_revision_invalid")
    receipt, _ = _read_json(root / "package-receipt.json")
    v3 = reviewed_pr_head_sha is not None
    if v3 and not _valid(REVISION_PATTERN, reviewed_pr_head_sha):
        raise PublicationError("reviewed_pr_head_invalid")
    if v3 and reviewed_pr_head_sha != HOTFIX_V3_REVIEWED_PR_HEAD_SHA:
        raise PublicationError("reviewed_pr_head_unreviewed")
    candidate_revision = HOTFIX_V3_IMAGE_SOURCE_REVISION if v3 else HOTFIX_CANDIDATE_REVISION
    candidate_image_id = HOTFIX_V3_IMAGE_ID if v3 else HOTFIX_CANDIDATE_IMAGE_ID
    candidate_context = HOTFIX_V3_IMAGE_CONTEXT_SHA256 if v3 else HOTFIX_CANDIDATE_CONTEXT_SHA256
    candidate_build_receipt = HOTFIX_V3_BUILD_RECEIPT_SHA256 if v3 else HOTFIX_BUILD_RECEIPT_SHA256
    candidate_name = _fixed_archive_name(candidate_revision)
    predecessor_name = _fixed_archive_name(PRODUCTION_PREDECESSOR_REVISION)
    manifest_name = f"signal-ledger-pair-{helper_revision}.json"
    expected_receipt = {
        "status": "prepared",
        "contract": HOTFIX_PAIR_CONTRACT_V3 if v3 else HOTFIX_PAIR_CONTRACT,
        "helper_source_revision": helper_revision,
        **({"reviewed_pr_head_sha": reviewed_pr_head_sha} if v3 else {}),
        "hotfix_pull_number": 9,
        "candidate_archive_name": candidate_name,
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
    candidate_path = root / candidate_name
    candidate_sha256, candidate_size = _hash_regular_file(candidate_path, MAX_ARCHIVE_BYTES)
    expected_receipt.update(
        {
            "candidate_archive_sha256": candidate_sha256,
            "candidate_archive_size": candidate_size,
            "candidate_image": {
                "architecture": "linux/amd64",
                "id": candidate_image_id,
                "revision_label": candidate_revision,
                "source_context_sha256": candidate_context,
            },
        }
    )
    if v3:
        expected_receipt["candidate_build_receipt_sha256"] = candidate_build_receipt
    else:
        expected_receipt["candidate_archive_sha256"] = HOTFIX_CANDIDATE_ARCHIVE_SHA256
        expected_receipt["candidate_archive_size"] = HOTFIX_CANDIDATE_ARCHIVE_SIZE
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
    expected_manifest = (
        _expected_manifest_v3(
            helper_revision,
            reviewed_pr_head_sha,
            candidate_archive_sha256=candidate_sha256,
            candidate_archive_size=candidate_size,
        )
        if v3
        else _expected_manifest(helper_revision)
    )
    if (
        raw_manifest != canonical
        or manifest_sha256 != receipt["manifest_sha256"]
        or manifest != expected_manifest
    ):
        raise PublicationError("hotfix_manifest_identity_mismatch")

    predecessor_path = root / predecessor_name
    predecessor_sha256, predecessor_size = _hash_regular_file(predecessor_path, MAX_ARCHIVE_BYTES)
    if (
        not v3
        and (candidate_sha256, candidate_size)
        != (
            HOTFIX_CANDIDATE_ARCHIVE_SHA256,
            HOTFIX_CANDIDATE_ARCHIVE_SIZE,
        )
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
            candidate_image_id,
            candidate_revision,
            candidate_context,
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
        reviewed_pr_head_sha=reviewed_pr_head_sha,
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


def _validate_current_source_v3(helper_revision: str, reviewed_pr_head_sha: str) -> None:
    """Require a clean helper head containing the exact reviewed PR9 test-only descendant."""

    try:
        git = shutil.which("git", path=os.defpath)
        if git is None:
            raise PublicationError("reviewed_source_unavailable")
        head = _command([git, "rev-parse", "--verify", "HEAD"])
        status = _command([git, "status", "--porcelain", "--untracked-files=normal"])
        remote = _command([git, "ls-remote", "origin", "refs/heads/main"]).split()
        _prove_reviewed_pr9_head(reviewed_pr_head_sha, helper_revision)
    except PublicationError:
        raise
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise PublicationError("reviewed_source_unavailable") from exc
    if head.strip() != helper_revision or status or not remote or remote[0] != helper_revision:
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
    candidate_revision = package.candidate.revision
    tag = f"signal-ledger-{candidate_revision}"
    _create_release(
        tag,
        candidate_revision,
        "Signal Ledger reviewed assistant candidate",
        "Publishes the exact reviewed Linux amd64 candidate archive.",
        package.candidate.path,
    )
    _assert_release_asset(
        tag,
        candidate_revision,
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
    candidate_revision = package.candidate.revision
    candidate_tag = f"signal-ledger-{candidate_revision}"
    predecessor_tag = f"signal-ledger-{PRODUCTION_PREDECESSOR_REVISION}"
    _assert_release_asset(
        candidate_tag,
        candidate_revision,
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
        "Binds the immutable reviewed assistant candidate to the original 5ad production image.",
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
    mode: str,
    helper_revision: str,
    package_root: Path = PACKAGE_ROOT,
    *,
    reviewed_pr_head_sha: str | None = None,
) -> dict[str, object]:
    """Validate current source and package, then publish one immutable release step."""

    if mode not in {"hotfix-candidate", "hotfix-pair", "hotfix-pair-v3"}:
        raise PublicationError("hotfix_publish_mode_invalid")
    v3 = mode == "hotfix-pair-v3"
    if v3 != (reviewed_pr_head_sha is not None):
        raise PublicationError("reviewed_pr_head_required")
    if v3:
        _validate_current_source_v3(helper_revision, reviewed_pr_head_sha)
    else:
        _validate_current_source(helper_revision)
    _require_hotfix_scratch_mount()
    package = validate_package(
        package_root,
        helper_revision,
        reviewed_pr_head_sha=reviewed_pr_head_sha,
    )
    with _staged_package(package) as staged:
        _scan_archive(staged.candidate)
        _scan_archive(staged.predecessor)
        if mode == "hotfix-candidate":
            return _publish_candidate(staged)
        return _publish_pair(staged)


def main(argv: list[str] | None = None) -> int:
    arguments = sys.argv[1:] if argv is None else argv
    if len(arguments) not in {2, 3} or (len(arguments) == 3 and arguments[0] != "hotfix-pair-v3"):
        print(
            "hotfix release transport requires a fixed mode and reviewed source revision",
            file=sys.stderr,
        )
        return 2
    try:
        result = publish(
            arguments[0],
            arguments[1],
            reviewed_pr_head_sha=arguments[2] if len(arguments) == 3 else None,
        )
    except PublicationError as exc:
        print(f"hotfix release publication failed: {exc}", file=sys.stderr)
        return 4
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
