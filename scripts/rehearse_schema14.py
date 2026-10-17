"""Rehearse schema-14 recovery for one reviewed R1/F6 candidate in a local disposable volume."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Literal, Protocol
from uuid import UUID

from scripts import research_recovery_overlay as overlay

_MAX_BINDING_BYTES = 16_384
_MAX_RUNTIME_HELPER_BYTES = 2 * 1024 * 1024
_CANONICAL_IMAGE_MEMORY_BYTES = 768 * 1024 * 1024
_CANONICAL_IMAGE_CPUS = 1
_CANONICAL_IMAGE_PIDS = 128
_CANONICAL_APP_READINESS_TIMEOUT_SECONDS = 60
_FIXTURE_CLOCK = "2025-01-13T20:00:00+00:00"
_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_IMAGE_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_SCHEMA14_VOLUME = re.compile(r"^stock-probs-schema14-[0-9a-f]{12}$")
_RUNTIME_VERIFIER = "/run/assistant/rehearsal.py"
_OVERLAY_RUNTIME_PATH = "/run/assistant/research_recovery_overlay.py"
_SCHEMA13_RUNTIME_PATH = Path(__file__).with_name("rehearse_schema13.py")
_OVERLAY_RUNTIME_SOURCE = Path(__file__).with_name("research_recovery_overlay.py")
_OWNER_SLOTS = ("owner_a", "owner_b")
_API_ENDPOINTS = frozenset(
    {
        "thesis_get",
        "thesis_revisions",
        "theses_export_json",
        "theses_export_csv",
        "comparison_get",
        "comparison_export_json",
        "comparison_export_csv",
    }
)
_FOREIGN_ENDPOINTS = frozenset(
    {
        "thesis_get",
        "thesis_revisions",
        "comparison_get",
        "comparison_export_json",
        "comparison_export_csv",
    }
)
_API_CONTENT_CHECKS = {
    "thesis_get": ("fixture_thesis_content",),
    "thesis_revisions": ("fixture_revision_history",),
    "theses_export_json": ("owner_scoped_thesis_json",),
    "theses_export_csv": ("owner_scoped_thesis_csv",),
    "comparison_get": ("fixture_comparison_content",),
    "comparison_export_json": ("owner_scoped_comparison_json",),
    "comparison_export_csv": ("owner_scoped_comparison_csv",),
}


class Schema14RehearsalError(ValueError):
    """Expose only fixed safe categories from source-binding and rehearsal failures."""


def _matches(pattern: re.Pattern[str], value: object) -> bool:
    return isinstance(value, str) and pattern.fullmatch(value) is not None


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    values: dict[str, object] = {}
    for key, value in pairs:
        if key in values:
            raise Schema14RehearsalError("review_binding_invalid")
        values[key] = value
    return values


@dataclass(frozen=True)
class ReviewedCandidateBinding:
    """Immutable exact source/image identities from explicit independent review input."""

    f6_merge_commit: str
    candidate_source_commit: str
    candidate_image_digest: str
    candidate_repository_blob_sha1: str
    candidate_repository_sha256: str
    recovery_image_digest: str
    source_review_sha256: str
    independent_qa_sha256: str
    parent_review_sha256: str
    binding_file_sha256: str


def parse_reviewed_candidate_binding(raw: bytes, expected_sha256: str) -> ReviewedCandidateBinding:
    """Require canonical, fully reviewed F6/candidate/recovery pins with no moving ref."""

    if not _matches(_HEX64, expected_sha256) or hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise Schema14RehearsalError("review_binding_digest_mismatch")
    if len(raw) > _MAX_BINDING_BYTES:
        raise Schema14RehearsalError("review_binding_limit")
    try:
        value = json.loads(raw, object_pairs_hook=_reject_duplicate_keys)
    except Schema14RehearsalError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise Schema14RehearsalError("review_binding_invalid") from None
    required = {
        "format_version",
        "status",
        "review_scope",
        "f6_merged",
        "f6_merge_commit",
        "f6_merge_is_candidate_ancestor",
        "candidate_source_commit",
        "candidate_image_digest",
        "candidate_repository_blob_sha1",
        "candidate_repository_sha256",
        "recovery_image_digest",
        "recovery_source_revision",
        "recovery_repository_sha256",
        "recovery_overlay_sha256",
        "migration14_sha256",
        "source_review_sha256",
        "independent_qa_sha256",
        "parent_review_sha256",
    }
    if not isinstance(value, dict) or set(value) != required:
        raise Schema14RehearsalError("review_binding_invalid")
    try:
        canonical = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("ascii")
    except (TypeError, UnicodeEncodeError):
        raise Schema14RehearsalError("review_binding_invalid") from None
    if raw != canonical:
        raise Schema14RehearsalError("review_binding_not_canonical")
    if (
        type(value["format_version"]) is not int
        or value["format_version"] != 1
        or value["status"] != "Pass"
        or value["review_scope"] != "r1-schema14-f6-recovery-input"
        or value["f6_merged"] is not True
        or value["f6_merge_is_candidate_ancestor"] is not True
        or value["recovery_source_revision"] != overlay.BASELINE_REVISION
        or value["recovery_repository_sha256"] != overlay.OVERLAY_REPOSITORY_SHA256
        or value["recovery_overlay_sha256"] != overlay.OVERLAY_SHA256
        or value["migration14_sha256"] != overlay.MIGRATION_SHA256
    ):
        raise Schema14RehearsalError("review_binding_invalid")
    if not _matches(_HEX40, value["f6_merge_commit"]):
        raise Schema14RehearsalError("review_binding_invalid")
    if not _matches(_HEX40, value["candidate_source_commit"]):
        raise Schema14RehearsalError("review_binding_invalid")
    if not _matches(_IMAGE_DIGEST, value["candidate_image_digest"]):
        raise Schema14RehearsalError("review_binding_invalid")
    if not _matches(_HEX40, value["candidate_repository_blob_sha1"]):
        raise Schema14RehearsalError("review_binding_invalid")
    if not _matches(_HEX64, value["candidate_repository_sha256"]):
        raise Schema14RehearsalError("review_binding_invalid")
    if not _matches(_IMAGE_DIGEST, value["recovery_image_digest"]):
        raise Schema14RehearsalError("review_binding_invalid")
    receipt_hashes = (
        value["source_review_sha256"],
        value["independent_qa_sha256"],
        value["parent_review_sha256"],
    )
    if any(not _matches(_HEX64, item) for item in receipt_hashes):
        raise Schema14RehearsalError("review_binding_invalid")
    return ReviewedCandidateBinding(
        f6_merge_commit=value["f6_merge_commit"],
        candidate_source_commit=value["candidate_source_commit"],
        candidate_image_digest=value["candidate_image_digest"],
        candidate_repository_blob_sha1=value["candidate_repository_blob_sha1"],
        candidate_repository_sha256=value["candidate_repository_sha256"],
        recovery_image_digest=value["recovery_image_digest"],
        source_review_sha256=value["source_review_sha256"],
        independent_qa_sha256=value["independent_qa_sha256"],
        parent_review_sha256=value["parent_review_sha256"],
        binding_file_sha256=expected_sha256,
    )


def load_reviewed_candidate_binding(path: Path, expected_sha256: str) -> ReviewedCandidateBinding:
    """Read one private, stable, no-follow binding file and validate its external digest."""

    descriptor: int | None = None
    try:
        before_path = path.lstat()
        if (
            not stat.S_ISREG(before_path.st_mode)
            or before_path.st_uid != os.getuid()
            or stat.S_IMODE(before_path.st_mode) != 0o600
            or before_path.st_nlink != 1
            or before_path.st_size > _MAX_BINDING_BYTES
        ):
            raise Schema14RehearsalError("review_binding_file_invalid")
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        before_fd = os.fstat(descriptor)
        if (before_fd.st_dev, before_fd.st_ino) != (before_path.st_dev, before_path.st_ino):
            raise Schema14RehearsalError("review_binding_file_changed")
        chunks: list[bytes] = []
        total = 0
        while True:
            block = os.read(descriptor, min(4096, _MAX_BINDING_BYTES + 1 - total))
            if not block:
                break
            total += len(block)
            if total > _MAX_BINDING_BYTES:
                raise Schema14RehearsalError("review_binding_limit")
            chunks.append(block)
        after_fd = os.fstat(descriptor)
        after_path = path.lstat()
        before_signature = (
            before_fd.st_dev,
            before_fd.st_ino,
            before_fd.st_uid,
            before_fd.st_mode,
            before_fd.st_nlink,
            before_fd.st_size,
            before_fd.st_mtime_ns,
        )
        after_signature = (
            after_fd.st_dev,
            after_fd.st_ino,
            after_fd.st_uid,
            after_fd.st_mode,
            after_fd.st_nlink,
            after_fd.st_size,
            after_fd.st_mtime_ns,
        )
        path_signature = (
            after_path.st_dev,
            after_path.st_ino,
            after_path.st_uid,
            after_path.st_mode,
            after_path.st_nlink,
            after_path.st_size,
            after_path.st_mtime_ns,
        )
        if before_signature != after_signature or after_signature != path_signature:
            raise Schema14RehearsalError("review_binding_file_changed")
        return parse_reviewed_candidate_binding(b"".join(chunks), expected_sha256)
    except Schema14RehearsalError:
        raise
    except OSError:
        raise Schema14RehearsalError("review_binding_file_invalid") from None
    finally:
        if descriptor is not None:
            os.close(descriptor)


@dataclass(frozen=True)
class Deployment:
    """Bound immutable app identity and data-volume association from one phase."""

    phase: Literal["candidate", "recovery"]
    image_digest: str
    source_commit: str
    repository_blob_sha1: str | None
    repository_sha256: str
    schema_version: int
    ready: bool
    volume_id: str
    assistant_enabled: bool
    research_enabled: bool
    research_canary_only: bool | None
    database_restored: bool
    overlay_sha256: str | None = None


@dataclass(frozen=True)
class OwnerFixture:
    """Opaque fixture identifiers for one of the two disposable authenticated owners."""

    owner_slot: Literal["owner_a", "owner_b"]
    owner_id: int
    thesis_id: str
    comparison_id: str


@dataclass(frozen=True)
class ResponseDigest:
    endpoint: str
    status_code: int
    body_sha256: str
    content_checks: tuple[str, ...]


@dataclass(frozen=True)
class OwnerApiEvidence:
    """Only status and digest projections from fixed research API routes are retained."""

    owner_slot: Literal["owner_a", "owner_b"]
    owner_id: int
    thesis_id: str
    comparison_id: str
    foreign_owner_slot: Literal["owner_a", "owner_b"]
    foreign_thesis_id: str
    foreign_comparison_id: str
    revision_numbers: tuple[int, ...]
    responses: tuple[ResponseDigest, ...]
    foreign_statuses: tuple[tuple[str, int], ...]


class Schema14Adapter(Protocol):
    """Narrow call surface for a separately reviewed disposable-pair adapter."""

    def start_candidate(
        self,
        binding: ReviewedCandidateBinding,
        *,
        volume_id: str | None,
        assistant_enabled: bool,
        research_enabled: bool,
        research_canary_only: Literal[False],
    ) -> Deployment:
        """Start exactly the bound disposable candidate; failed starts must leave no process."""
        ...

    def start_recovery(
        self,
        binding: ReviewedCandidateBinding,
        *,
        volume_id: str,
        assistant_enabled: Literal[False],
        research_enabled: Literal[False],
        research_canary_only: Literal[False],
        restore_database: Literal[False],
    ) -> Deployment:
        """Start only the fixed disabled recovery image; failed starts leave no process."""
        ...

    def create_two_owner_research_fixtures(
        self, deployment: Deployment
    ) -> tuple[OwnerFixture, ...]: ...

    def read_research_api(
        self, deployment: Deployment, fixtures: tuple[OwnerFixture, ...]
    ) -> tuple[OwnerApiEvidence, ...]: ...

    def snapshot_database(self, deployment: Deployment) -> dict[str, object]: ...

    def stop(self, deployment: Deployment) -> None: ...


@dataclass(frozen=True)
class DatabaseSnapshot:
    schema_versions: tuple[int, ...]
    tables: tuple[tuple[str, int, str, str], ...]
    sha256: str


def _snapshot(value: object) -> DatabaseSnapshot:
    if not isinstance(value, dict) or set(value) != {
        "schema_version",
        "schema_versions",
        "tables",
        "sha256",
    }:
        raise Schema14RehearsalError("database_snapshot_invalid")
    versions = value["schema_versions"]
    tables_value = value["tables"]
    if (
        type(value["schema_version"]) is not int
        or value["schema_version"] != overlay.SCHEMA_VERSION
        or not isinstance(versions, list)
        or any(type(version) is not int for version in versions)
        or versions != list(range(1, overlay.SCHEMA_VERSION + 1))
        or not isinstance(tables_value, dict)
        or set(tables_value) != overlay.RECOVERY_REQUIRED_TABLES
    ):
        raise Schema14RehearsalError("database_snapshot_invalid")
    tables: list[tuple[str, int, str, str]] = []
    normalized: dict[str, dict[str, object]] = {}
    for table in sorted(overlay.RECOVERY_REQUIRED_TABLES):
        fields = tables_value[table]
        if not isinstance(fields, dict) or set(fields) != {"columns_sha256", "rows", "sha256"}:
            raise Schema14RehearsalError("database_snapshot_invalid")
        rows = fields["rows"]
        columns_sha256 = fields["columns_sha256"]
        table_sha256 = fields["sha256"]
        if (
            type(rows) is not int
            or rows < 0
            or not isinstance(columns_sha256, str)
            or not _HEX64.fullmatch(columns_sha256)
            or not isinstance(table_sha256, str)
            or not _HEX64.fullmatch(table_sha256)
        ):
            raise Schema14RehearsalError("database_snapshot_invalid")
        tables.append((table, rows, columns_sha256, table_sha256))
        normalized[table] = {
            "columns_sha256": columns_sha256,
            "rows": rows,
            "sha256": table_sha256,
        }
    canonical = json.dumps(
        {"schema_versions": versions, "tables": normalized},
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("ascii")
    digest = hashlib.sha256(canonical).hexdigest()
    if value["sha256"] != digest:
        raise Schema14RehearsalError("database_snapshot_digest_invalid")
    return DatabaseSnapshot(tuple(versions), tuple(tables), digest)


def _validate_fixtures(value: object) -> tuple[OwnerFixture, ...]:
    if (
        not isinstance(value, tuple)
        or len(value) != 2
        or any(not isinstance(item, OwnerFixture) for item in value)
    ):
        raise Schema14RehearsalError("owner_fixture_invalid")
    if any(item.owner_slot not in _OWNER_SLOTS for item in value):
        raise Schema14RehearsalError("owner_fixture_invalid")
    fixtures = tuple(sorted(value, key=lambda item: item.owner_slot))
    if tuple(item.owner_slot for item in fixtures) != _OWNER_SLOTS:
        raise Schema14RehearsalError("owner_fixture_invalid")
    if len({item.owner_id for item in fixtures}) != 2 or any(
        type(item.owner_id) is not int or item.owner_id < 1 for item in fixtures
    ):
        raise Schema14RehearsalError("owner_fixture_invalid")
    thesis_ids = [item.thesis_id for item in fixtures]
    comparison_ids = [item.comparison_id for item in fixtures]
    all_ids = thesis_ids + comparison_ids
    for identifier in all_ids:
        if not isinstance(identifier, str):
            raise Schema14RehearsalError("owner_fixture_invalid")
        try:
            if str(UUID(identifier)) != identifier:
                raise ValueError
        except ValueError:
            raise Schema14RehearsalError("owner_fixture_invalid") from None
    if len(set(all_ids)) != 4:
        raise Schema14RehearsalError("owner_fixture_invalid")
    return fixtures


def _validate_api_evidence(
    value: object, fixtures: tuple[OwnerFixture, ...]
) -> tuple[OwnerApiEvidence, ...]:
    if (
        not isinstance(value, tuple)
        or len(value) != 2
        or any(not isinstance(item, OwnerApiEvidence) for item in value)
    ):
        raise Schema14RehearsalError("api_evidence_invalid")
    if any(item.owner_slot not in _OWNER_SLOTS for item in value):
        raise Schema14RehearsalError("api_evidence_invalid")
    evidence = tuple(sorted(value, key=lambda item: item.owner_slot))
    if tuple(item.owner_slot for item in evidence) != _OWNER_SLOTS:
        raise Schema14RehearsalError("api_evidence_invalid")
    for item, fixture in zip(evidence, fixtures, strict=True):
        foreign_fixture = next(candidate for candidate in fixtures if candidate != fixture)
        if (
            item.owner_id != fixture.owner_id
            or item.thesis_id != fixture.thesis_id
            or item.comparison_id != fixture.comparison_id
            or item.foreign_owner_slot != foreign_fixture.owner_slot
            or item.foreign_thesis_id != foreign_fixture.thesis_id
            or item.foreign_comparison_id != foreign_fixture.comparison_id
            or item.revision_numbers != (1, 2)
        ):
            raise Schema14RehearsalError("api_evidence_identity_mismatch")
        if (
            not isinstance(item.responses, tuple)
            or len(item.responses) != len(_API_ENDPOINTS)
            or any(not isinstance(response, ResponseDigest) for response in item.responses)
        ):
            raise Schema14RehearsalError("api_evidence_invalid")
        expected_responses = {
            f"thesis_get:{fixture.thesis_id}",
            f"thesis_revisions:{fixture.thesis_id}",
            "theses_export_json",
            "theses_export_csv",
            f"comparison_get:{fixture.comparison_id}",
            f"comparison_export_json:{fixture.comparison_id}",
            f"comparison_export_csv:{fixture.comparison_id}",
        }
        if any(not isinstance(response.endpoint, str) for response in item.responses):
            raise Schema14RehearsalError("api_evidence_invalid")
        responses = {response.endpoint: response for response in item.responses}
        if set(responses) != expected_responses or any(
            type(response.status_code) is not int
            or response.status_code != 200
            or not isinstance(response.body_sha256, str)
            or not _HEX64.fullmatch(response.body_sha256)
            for response in responses.values()
        ):
            raise Schema14RehearsalError("api_evidence_invalid")
        expected_content = {
            f"thesis_get:{fixture.thesis_id}": _API_CONTENT_CHECKS["thesis_get"],
            f"thesis_revisions:{fixture.thesis_id}": _API_CONTENT_CHECKS["thesis_revisions"],
            "theses_export_json": _API_CONTENT_CHECKS["theses_export_json"],
            "theses_export_csv": _API_CONTENT_CHECKS["theses_export_csv"],
            f"comparison_get:{fixture.comparison_id}": _API_CONTENT_CHECKS["comparison_get"],
            f"comparison_export_json:{fixture.comparison_id}": _API_CONTENT_CHECKS[
                "comparison_export_json"
            ],
            f"comparison_export_csv:{fixture.comparison_id}": _API_CONTENT_CHECKS[
                "comparison_export_csv"
            ],
        }
        if any(
            not isinstance(response.content_checks, tuple)
            or response.content_checks != expected_content[endpoint]
            for endpoint, response in responses.items()
        ):
            raise Schema14RehearsalError("api_content_checks_missing")
        if not isinstance(item.foreign_statuses, tuple) or any(
            not isinstance(entry, tuple) or len(entry) != 2 or not isinstance(entry[0], str)
            for entry in item.foreign_statuses
        ):
            raise Schema14RehearsalError("api_evidence_invalid")
        foreign = dict(item.foreign_statuses)
        if (
            len(item.foreign_statuses) != len(_FOREIGN_ENDPOINTS)
            or set(foreign) != _FOREIGN_ENDPOINTS
            or any(
                type(status) is not int or status != 404
                for endpoint, status in item.foreign_statuses
            )
        ):
            raise Schema14RehearsalError("owner_isolation_failed")
    return evidence


def _validate_candidate(
    deployment: Deployment,
    binding: ReviewedCandidateBinding,
    *,
    volume_id: str | None,
) -> None:
    if not isinstance(deployment, Deployment) or (
        deployment.phase != "candidate"
        or deployment.image_digest != binding.candidate_image_digest
        or deployment.source_commit != binding.candidate_source_commit
        or deployment.repository_blob_sha1 != binding.candidate_repository_blob_sha1
        or deployment.repository_sha256 != binding.candidate_repository_sha256
        or deployment.schema_version != overlay.SCHEMA_VERSION
        or deployment.ready is not True
        or deployment.assistant_enabled is not False
        or deployment.research_enabled is not True
        or deployment.research_canary_only is not False
        or deployment.database_restored is not False
        or deployment.overlay_sha256 is not None
        or not deployment.volume_id
        or (volume_id is not None and deployment.volume_id != volume_id)
    ):
        raise Schema14RehearsalError("candidate_identity_or_control_mismatch")


def _validate_recovery(
    deployment: Deployment,
    binding: ReviewedCandidateBinding,
    *,
    volume_id: str,
) -> None:
    if not isinstance(deployment, Deployment) or (
        deployment.phase != "recovery"
        or deployment.image_digest != binding.recovery_image_digest
        or deployment.source_commit != overlay.BASELINE_REVISION
        or deployment.repository_blob_sha1 is not None
        or deployment.repository_sha256 != overlay.OVERLAY_REPOSITORY_SHA256
        or deployment.schema_version != overlay.SCHEMA_VERSION
        or deployment.ready is not True
        or deployment.volume_id != volume_id
        or deployment.assistant_enabled is not False
        or deployment.research_enabled is not False
        or deployment.research_canary_only is not None
        or deployment.database_restored is not False
        or deployment.overlay_sha256 != overlay.OVERLAY_SHA256
    ):
        raise Schema14RehearsalError("recovery_identity_or_control_mismatch")


def run_schema14_rehearsal(
    adapter: Schema14Adapter, binding_path: Path, expected_binding_sha256: str
) -> dict[str, object]:
    """Require the external reviewed binding file before starting any rehearsal phase."""

    binding = load_reviewed_candidate_binding(binding_path, expected_binding_sha256)
    return _run_with_binding(adapter, binding)


def _run_with_binding(
    adapter: Schema14Adapter, binding: ReviewedCandidateBinding
) -> dict[str, object]:
    """Run the reviewed two-image, same-volume choreography through a narrow injected adapter."""

    if (
        not isinstance(binding, ReviewedCandidateBinding)
        or not _matches(_HEX40, binding.f6_merge_commit)
        or not _matches(_HEX40, binding.candidate_source_commit)
        or not _matches(_IMAGE_DIGEST, binding.candidate_image_digest)
        or not _matches(_HEX40, binding.candidate_repository_blob_sha1)
        or not _matches(_HEX64, binding.candidate_repository_sha256)
        or not _matches(_IMAGE_DIGEST, binding.recovery_image_digest)
        or any(
            not _matches(_HEX64, value)
            for value in (
                binding.source_review_sha256,
                binding.independent_qa_sha256,
                binding.parent_review_sha256,
                binding.binding_file_sha256,
            )
        )
    ):
        raise Schema14RehearsalError("review_binding_invalid")
    active: Deployment | None = None
    cleanup_unverified = False
    try:
        try:
            candidate = adapter.start_candidate(
                binding,
                volume_id=None,
                assistant_enabled=False,
                research_enabled=True,
                research_canary_only=False,
            )
        except Exception:
            raise Schema14RehearsalError("candidate_start_failed") from None
        active = candidate
        _validate_candidate(candidate, binding, volume_id=None)
        volume_id = candidate.volume_id

        try:
            fixtures = _validate_fixtures(adapter.create_two_owner_research_fixtures(candidate))
            initial_api = _validate_api_evidence(
                adapter.read_research_api(candidate, fixtures), fixtures
            )
        except Schema14RehearsalError:
            raise
        except Exception:
            raise Schema14RehearsalError("candidate_fixture_or_api_failed") from None

        active = None
        try:
            adapter.stop(candidate)
        except Exception:
            raise Schema14RehearsalError("candidate_stop_unverified") from None
        try:
            before_snapshot = _snapshot(adapter.snapshot_database(candidate))
        except Schema14RehearsalError:
            raise
        except Exception:
            raise Schema14RehearsalError("candidate_database_snapshot_failed") from None
        research_counts = {
            name: rows
            for name, rows, _columns_digest, _table_digest in before_snapshot.tables
            if name in {"research_theses", "research_thesis_revisions", "research_comparisons"}
        }
        if research_counts != {
            "research_comparisons": 2,
            "research_theses": 2,
            "research_thesis_revisions": 4,
        }:
            raise Schema14RehearsalError("candidate_research_rows_incomplete")

        try:
            recovery = adapter.start_recovery(
                binding,
                volume_id=volume_id,
                assistant_enabled=False,
                research_enabled=False,
                research_canary_only=False,
                restore_database=False,
            )
        except Exception:
            raise Schema14RehearsalError("recovery_start_failed") from None
        active = recovery
        _validate_recovery(recovery, binding, volume_id=volume_id)
        try:
            recovery_snapshot = _snapshot(adapter.snapshot_database(recovery))
        except Schema14RehearsalError:
            raise
        except Exception:
            raise Schema14RehearsalError("recovery_database_snapshot_failed") from None
        if recovery_snapshot != before_snapshot:
            raise Schema14RehearsalError("recovery_data_changed")

        active = None
        try:
            adapter.stop(recovery)
        except Exception:
            raise Schema14RehearsalError("recovery_stop_unverified") from None

        try:
            resumed = adapter.start_candidate(
                binding,
                volume_id=volume_id,
                assistant_enabled=False,
                research_enabled=True,
                research_canary_only=False,
            )
        except Exception:
            raise Schema14RehearsalError("candidate_reentry_failed") from None
        active = resumed
        _validate_candidate(resumed, binding, volume_id=volume_id)
        try:
            final_api = _validate_api_evidence(
                adapter.read_research_api(resumed, fixtures), fixtures
            )
        except Schema14RehearsalError:
            raise
        except Exception:
            raise Schema14RehearsalError("candidate_reentry_api_failed") from None
        if final_api != initial_api:
            raise Schema14RehearsalError("research_api_data_changed")

        active = None
        try:
            adapter.stop(resumed)
        except Exception:
            raise Schema14RehearsalError("candidate_final_stop_unverified") from None
        return {
            "status": "Pass",
            "scope": "schema14_same_volume_recovery_orchestration",
            "f6_merge_commit": binding.f6_merge_commit,
            "candidate_source_commit": binding.candidate_source_commit,
            "candidate_image_digest": binding.candidate_image_digest,
            "recovery_image_digest": binding.recovery_image_digest,
            "candidate_repository_blob_sha1": binding.candidate_repository_blob_sha1,
            "candidate_repository_sha256": binding.candidate_repository_sha256,
            "binding_file_sha256": binding.binding_file_sha256,
            "volume_id_sha256": hashlib.sha256(volume_id.encode("utf-8")).hexdigest(),
            "schema_versions": list(before_snapshot.schema_versions),
            "database_snapshot_sha256": before_snapshot.sha256,
            "database_snapshot_tables": [
                {
                    "table": table,
                    "rows": rows,
                    "columns_sha256": columns_digest,
                    "sha256": table_digest,
                }
                for table, rows, columns_digest, table_digest in before_snapshot.tables
            ],
            "owner_slots": list(_OWNER_SLOTS),
            "api_endpoint_keys": sorted(_API_ENDPOINTS),
            "foreign_endpoint_keys": sorted(_FOREIGN_ENDPOINTS),
            "fixture_provider": "deterministic_fixture",
            "comparison_price_data": "synthetic_fixture_not_live_market_data",
            "network_mode": "none",
            "data_path_evidence": {
                "initial_thesis_and_comparison_writes": "authenticated_candidate_api",
                "recovery_retention_check": "read_only_sqlite_snapshot",
                "candidate_reentry_check": "authenticated_candidate_api",
            },
            "api_evidence": [
                {
                    "owner_slot": item.owner_slot,
                    "responses": [
                        {
                            "endpoint": response.endpoint,
                            "status_code": response.status_code,
                            "body_sha256": response.body_sha256,
                            "content_checks": list(response.content_checks),
                        }
                        for response in sorted(item.responses, key=lambda item: item.endpoint)
                    ],
                    "foreign_owner_slot": item.foreign_owner_slot,
                    "foreign_statuses": [
                        {"endpoint": endpoint, "status_code": status}
                        for endpoint, status in sorted(item.foreign_statuses)
                    ],
                }
                for item in initial_api
            ],
            "database_restored": False,
            "production_or_release_acceptance": False,
        }
    finally:
        if active is not None:
            try:
                adapter.stop(active)
            except Exception:
                cleanup_unverified = True
        if cleanup_unverified:
            raise Schema14RehearsalError("active_phase_cleanup_unverified") from None


def _runtime_verifier_source() -> str:
    """Return the fixed, bounded in-container API and read-only snapshot verifier."""

    return r"""from __future__ import annotations

import hashlib
import csv
import http.client
import importlib.util
import io
import json
import os
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from uuid import UUID

BASE = "http://127.0.0.1:8000"
OVERLAY_PATH = "/run/assistant/research_recovery_overlay.py"
MAX_BODY = 1_048_576
FIXTURE_NOW = datetime.fromisoformat("2025-01-13T20:00:00+00:00")
USERS = (("owner_a", "schema14-admin"), ("owner_b", "schema14-member"))
PASSWORDS = {
    "schema14-admin": "schema14-local-admin-0123456789",
    "schema14-member": "schema14-local-member-0123456789",
}


class CheckFailure(Exception):
    def __init__(self, step):
        self.step = step


def need(ok, step):
    if not ok:
        raise CheckFailure(step)


def emit(value):
    print(json.dumps(value, sort_keys=True, separators=(",", ":")))


def probe(phase):
    need(phase in {"candidate", "recovery"}, "readiness_phase")
    connection = http.client.HTTPConnection("127.0.0.1", 8000, timeout=2.0)
    try:
        connection.request("GET", "/api/v1/readiness", headers={"Host": "localhost"})
        response = connection.getresponse()
        body = response.read(16_385)
        need(response.status == 200 and len(body) <= 16_384, "readiness")
        value = json.loads(body)
        need(isinstance(value, dict), "readiness")
        expected_keys = {"status", "schema_version", "provider", "assistant"}
        if phase == "candidate":
            expected_keys.add("research")
        need(set(value) == expected_keys, "readiness")
        need(
            value.get("status") == "ready"
            and type(value.get("schema_version")) is int
            and value.get("schema_version") == 14
            and value.get("provider") == "fixture"
            and value.get("assistant") == {"enabled": False, "status": "disabled"},
            "readiness",
        )
        if phase == "candidate":
            need(
                value.get("research") == {"enabled": True, "rollout_mode": "invited"},
                "readiness",
            )
        emit({key: value[key] for key in sorted(expected_keys)})
    finally:
        connection.close()


def client_login(httpx, username):
    client = httpx.Client(base_url=BASE, timeout=3.0)
    response = client.post(
        "/api/v1/auth/local/login",
        json={"username": username, "password": PASSWORDS[username]},
    )
    need(response.status_code == 200, "login")
    value = response.json()
    need(isinstance(value, dict) and value.get("authenticated") is True, "login")
    user = value.get("user")
    csrf = value.get("csrf_token")
    need(isinstance(user, dict) and type(user.get("id")) is int and user["id"] > 0, "login")
    need(isinstance(csrf, str) and 16 <= len(csrf) <= 256, "login")
    need(client.cookies.get("signal_ledger_csrf") == csrf, "login")
    return client, user["id"], csrf


def checked(response, status, step):
    need(response.status_code == status, step)
    need(len(response.content) <= MAX_BODY, "api_body_limit")
    return response


def expected_identity(symbol, asset_type):
    from stock_probs.provider import FixtureProvider

    provider = FixtureProvider(clock=lambda: FIXTURE_NOW)
    matches = provider.lookup(symbol, 1, FIXTURE_NOW)
    need(
        len(matches) == 1
        and matches[0].canonical_symbol == symbol
        and matches[0].asset_type == asset_type,
        "fixture_identity",
    )
    return matches[0].as_dict()


def expected_thesis_data(slot, revision):
    symbols = {"owner_a": ("SPY", "etf"), "owner_b": ("ACDC", "stock")}
    need(slot in symbols and revision in {1, 2}, "thesis_fixture_content")
    symbol, asset_type = symbols[slot]
    return {
        "symbol": symbol,
        "asset_type": asset_type,
        "title": "Schema 14 retained thesis " + slot,
        "reasoning": (
            "Initial fixed recovery fixture."
            if revision == 1
            else "Revised fixed recovery fixture."
        ),
        "risks": "Deterministic fixture risk.",
        "invalidation": "Deterministic fixture invalidation.",
        "status": "watching",
        "review_date": None,
        "evidence": [],
        "identity": expected_identity(symbol, asset_type),
    }


def expected_comparison_data():
    from stock_probs.provider import FixtureProvider
    from stock_probs.research import compare_series

    provider = FixtureProvider(clock=lambda: FIXTURE_NOW)
    series = []
    for symbol, asset_type in (("SPY", "etf"), ("ACDC", "stock")):
        bars = provider.historical_bars(symbol, asset_type, FIXTURE_NOW, range="1mo").as_dict()
        identity = expected_identity(symbol, asset_type)
        series.append({**bars, "identity": identity, "source": bars["provider"]})
    expected = compare_series(series)
    expected["captured_at"] = FIXTURE_NOW.isoformat()
    return expected


def verify_api_content(
    slot,
    thesis_id,
    foreign_thesis_id,
    comparison_id,
    foreign_comparison_id,
    thesis_record,
    revision_history,
    thesis_json_export,
    thesis_csv_export,
    comparison_record,
    comparison_json_export,
    comparison_csv_export,
):
    def need_thesis_data(data, revision):
        expected = expected_thesis_data(slot, revision)
        need(isinstance(data, dict) and data == expected, "thesis_fixture_content")

    def need_thesis_record(record, revision):
        need(
            isinstance(record, dict)
            and set(record) == {"id", "revision", "created_at", "updated_at", "data"}
            and record.get("id") == thesis_id
            and record.get("revision") == revision
            and record.get("created_at") == FIXTURE_NOW.isoformat()
            and record.get("updated_at") == FIXTURE_NOW.isoformat(),
            "thesis_fixture_identity",
        )
        need_thesis_data(record.get("data"), revision)

    need_thesis_record(thesis_record, 2)
    need(
        isinstance(revision_history, dict)
        and set(revision_history) == {"items", "page", "page_size", "total", "has_next"}
        and revision_history.get("total") == 2
        and revision_history.get("page") == 1
        and revision_history.get("page_size") == 20
        and revision_history.get("has_next") is False
        and isinstance(revision_history.get("items"), list)
        and len(revision_history["items"]) == 2,
        "thesis_fixture_history",
    )
    for item, revision in zip(revision_history["items"], (2, 1), strict=True):
        need(
            isinstance(item, dict)
            and set(item) == {"revision", "data", "recorded_at"}
            and item.get("revision") == revision
            and item.get("recorded_at") == FIXTURE_NOW.isoformat(),
            "thesis_fixture_history",
        )
        need_thesis_data(item.get("data"), revision)

    need(
        isinstance(thesis_json_export, dict)
        and set(thesis_json_export) == {"format_version", "items", "revisions"}
        and thesis_json_export.get("format_version") == 1
        and isinstance(thesis_json_export.get("items"), list)
        and len(thesis_json_export["items"]) == 1
        and isinstance(thesis_json_export.get("revisions"), list)
        and len(thesis_json_export["revisions"]) == 2,
        "thesis_json_export_content",
    )
    exported_thesis = thesis_json_export["items"][0]
    need(
        isinstance(exported_thesis, dict)
        and exported_thesis.get("id") == thesis_id,
        "thesis_json_export_owner",
    )
    need_thesis_record(exported_thesis, 2)
    for item, revision in zip(thesis_json_export["revisions"], (1, 2), strict=True):
        need(
            isinstance(item, dict)
            and set(item) == {"thesis_id", "revision", "data", "recorded_at"}
            and item.get("thesis_id") == thesis_id
            and item.get("revision") == revision
            and item.get("recorded_at") == FIXTURE_NOW.isoformat(),
            "thesis_json_export_owner",
        )
        need_thesis_data(item.get("data"), revision)
    need(
        foreign_thesis_id not in json.dumps(thesis_json_export, sort_keys=True),
        "thesis_json_export_owner",
    )

    thesis_reader = csv.DictReader(io.StringIO(thesis_csv_export))
    thesis_rows = list(thesis_reader)
    thesis_columns = [
        "thesis_id",
        "revision",
        "recorded_at",
        "symbol",
        "asset_type",
        "title",
        "reasoning",
        "risks",
        "invalidation",
        "status",
        "review_date",
        "reviewed_at",
        "evidence_json",
        "identity_json",
    ]
    need(
        thesis_reader.fieldnames == thesis_columns
        and len(thesis_rows) == 2
        and [row.get("revision") for row in thesis_rows] == ["1", "2"],
        "thesis_csv_export_content",
    )
    for row, revision in zip(thesis_rows, (1, 2), strict=True):
        data = expected_thesis_data(slot, revision)
        need(
            row.get("thesis_id") == thesis_id
            and row.get("recorded_at") == FIXTURE_NOW.isoformat()
            and all(
                row.get(key) == ("" if data.get(key) is None else str(data.get(key)))
                for key in thesis_columns[3:12]
            )
            and row.get("evidence_json") == "[]"
            and json.loads(row.get("identity_json", "null")) == data["identity"],
            "thesis_csv_export_content",
        )
    need(foreign_thesis_id not in thesis_csv_export, "thesis_csv_export_owner")

    expected_comparison = expected_comparison_data()
    def need_comparison_record(record, *, exported):
        need(
            isinstance(record, dict)
            and record.get("id") == comparison_id,
            "comparison_fixture_identity",
        )
        if exported:
            need(set(record) == {"id", "created_at", "data"}, "comparison_export_content")
        else:
            need(
                set(record) == {"id", "revision", "created_at", "updated_at", "data"},
                "comparison_fixture_content",
            )
        need(record.get("created_at") == FIXTURE_NOW.isoformat(), "comparison_fixture_content")
        if not exported:
            need(
                record.get("revision") is None and record.get("updated_at") is None,
                "comparison_fixture_content",
            )
        data = record.get("data")
        need(
            isinstance(data, dict)
            and isinstance(data.get("preview_id"), str)
            and data == {**expected_comparison, "preview_id": data.get("preview_id")},
            "comparison_fixture_content",
        )
        try:
            need(
                str(UUID(data["preview_id"])) == data["preview_id"],
                "comparison_fixture_content",
            )
        except (ValueError, TypeError, KeyError):
            raise CheckFailure("comparison_fixture_content") from None

    need_comparison_record(comparison_record, exported=False)
    need_comparison_record(comparison_json_export, exported=True)
    need(
        foreign_comparison_id not in json.dumps(comparison_json_export, sort_keys=True),
        "comparison_export_owner",
    )
    comparison_reader = csv.DictReader(io.StringIO(comparison_csv_export))
    comparison_rows = list(comparison_reader)
    instruments = expected_comparison["instruments"]
    comparison_columns = [
        "snapshot_id",
        "captured_at",
        "symbol",
        "currency",
        "source",
        "as_of",
        "price_change",
        "volatility",
        "max_drawdown",
        "sample_count",
        "quality",
    ]
    need(
        comparison_reader.fieldnames == comparison_columns
        and len(comparison_rows) == len(instruments),
        "comparison_csv_export_content",
    )
    for row, instrument in zip(comparison_rows, instruments, strict=True):
        need(
            row.get("snapshot_id") == comparison_id
            and row.get("captured_at") == FIXTURE_NOW.isoformat()
            and all(
                row.get(key) == ("" if instrument.get(key) is None else str(instrument.get(key)))
                for key in comparison_columns[2:]
            ),
            "comparison_csv_export_content",
        )
    need(foreign_comparison_id not in comparison_csv_export, "comparison_export_owner")
    return {
        "thesis_get": ["fixture_thesis_content"],
        "thesis_revisions": ["fixture_revision_history"],
        "theses_export_json": ["owner_scoped_thesis_json"],
        "theses_export_csv": ["owner_scoped_thesis_csv"],
        "comparison_get": ["fixture_comparison_content"],
        "comparison_export_json": ["owner_scoped_comparison_json"],
        "comparison_export_csv": ["owner_scoped_comparison_csv"],
    }


def create_assistant_fixture(owner_id):
    from datetime import UTC, timedelta, datetime

    from stock_probs.assistant.storage import AssistantStorage
    from stock_probs.config import Settings
    from stock_probs.repository import Repository

    repository = Repository(Settings.from_env().database_path)
    storage = AssistantStorage(repository)
    now = datetime.now(UTC)
    context = {"fixture": "schema14-recovery"}
    context_version = hashlib.sha256(b"schema14-recovery-context-v1").hexdigest()
    conversation = storage.create_conversation(
        owner_id,
        title="Synthetic schema 14 recovery conversation",
        context=context,
        context_version=context_version,
        created_at=now,
    )
    conversation_id = conversation.get("conversation", {}).get("id")
    need(isinstance(conversation_id, str), "assistant_fixture_conversation")
    turn = storage.create_turn(
        owner_id,
        conversation_id,
        prompt="Synthetic retained user prompt.",
        model_id="fixture/recovery-test",
        policy_version="schema14-recovery-fixture-v1",
        context=context,
        context_version=context_version,
        session_id="schema14-owner-a-session",
        session_token_hash=hashlib.sha256(b"schema14-local-session").hexdigest(),
        capability="schema14-fixture-capability-" + "a" * 40,
        now=now,
        expires_at=now + timedelta(seconds=120),
    )
    turn_id = turn.get("id")
    execution_id = turn.get("execution_id")
    need(isinstance(turn_id, str) and isinstance(execution_id, str), "assistant_fixture_turn")
    need(
        storage.set_turn_status(owner_id, conversation_id, turn_id, status="running", now=now),
        "assistant_fixture_turn",
    )
    storage.append_message(
        owner_id,
        conversation_id,
        turn_id,
        role="assistant",
        content="Synthetic assistant answer retained across schema 14 recovery.",
        now=now,
    )
    need(
        storage.set_turn_status(owner_id, conversation_id, turn_id, status="completed", now=now),
        "assistant_fixture_turn",
    )
    storage.close_execution(execution_id, now=now)


def create_fixtures():
    import httpx
    from uuid import uuid4

    fixtures = []
    for slot, username in USERS:
        client, owner_id, csrf = client_login(httpx, username)
        try:
            symbol, asset_type = ("SPY", "etf") if slot == "owner_a" else ("ACDC", "stock")
            payload = {
                "symbol": symbol,
                "asset_type": asset_type,
                "title": "Schema 14 retained thesis " + slot,
                "reasoning": "Initial fixed recovery fixture.",
                "risks": "Deterministic fixture risk.",
                "invalidation": "Deterministic fixture invalidation.",
                "evidence": [],
                "idempotency_key": str(uuid4()),
            }
            created = checked(
                client.post("/api/v1/theses", json=payload, headers={"x-csrf-token": csrf}),
                201,
                "thesis_create",
            ).json()
            thesis_id = created.get("id")
            need(isinstance(thesis_id, str), "thesis_create")
            edited = {
                **payload,
                "reasoning": "Revised fixed recovery fixture.",
                "revision": created.get("revision"),
            }
            updated = checked(
                client.put(
                    "/api/v1/theses/" + thesis_id, json=edited, headers={"x-csrf-token": csrf}
                ),
                200,
                "thesis_update",
            ).json()
            need(updated.get("id") == thesis_id and updated.get("revision") == 2, "thesis_revision")
            preview = checked(
                client.post(
                    "/api/v1/comparisons/preview",
                    json={
                        "instruments": [
                            {"symbol": "SPY", "asset_type": "etf"},
                            {"symbol": "ACDC", "asset_type": "stock"},
                        ],
                        "range": "1mo",
                    },
                    headers={"x-csrf-token": csrf},
                ),
                200,
                "comparison_preview",
            ).json()
            preview_id = preview.get("preview_id")
            need(isinstance(preview_id, str), "comparison_preview")
            saved = checked(
                client.post(
                    "/api/v1/comparisons",
                    json={"preview_id": preview_id, "idempotency_key": str(uuid4())},
                    headers={"x-csrf-token": csrf},
                ),
                201,
                "comparison_save",
            ).json()
            comparison_id = saved.get("id")
            need(isinstance(comparison_id, str), "comparison_save")
            fixtures.append(
                {
                    "owner_slot": slot,
                    "owner_id": owner_id,
                    "thesis_id": thesis_id,
                    "comparison_id": comparison_id,
                }
            )
            if slot == "owner_a":
                create_assistant_fixture(owner_id)
        finally:
            client.close()
    emit({"fixtures": fixtures})


def read_api(raw_fixtures):
    import httpx

    fixtures = json.loads(raw_fixtures)
    need(isinstance(fixtures, list) and len(fixtures) == 2, "fixture_input")
    by_slot = {item.get("owner_slot"): item for item in fixtures if isinstance(item, dict)}
    need(set(by_slot) == {"owner_a", "owner_b"}, "fixture_input")
    output = []
    for slot, username in USERS:
        fixture = by_slot[slot]
        other_slot = "owner_b" if slot == "owner_a" else "owner_a"
        other = by_slot[other_slot]
        client, owner_id, _csrf = client_login(httpx, username)
        try:
            own_thesis = fixture.get("thesis_id")
            own_comparison = fixture.get("comparison_id")
            need(isinstance(own_thesis, str) and isinstance(own_comparison, str), "fixture_input")
            thesis_response = checked(client.get("/api/v1/theses/" + own_thesis), 200, "thesis_get")
            thesis_value = thesis_response.json()
            need(
                thesis_value.get("id") == own_thesis and thesis_value.get("revision") == 2,
                "thesis_get",
            )
            history_response = checked(
                client.get("/api/v1/theses/" + own_thesis + "/revisions"), 200, "thesis_revisions"
            )
            history = history_response.json()
            revisions = sorted(
                item.get("revision") for item in history.get("items", []) if isinstance(item, dict)
            )
            need(history.get("total") == 2 and revisions == [1, 2], "thesis_revisions")
            thesis_json = checked(
                client.get("/api/v1/theses/export?format=json"), 200, "theses_export_json"
            )
            thesis_csv = checked(
                client.get("/api/v1/theses/export?format=csv"), 200, "theses_export_csv"
            )
            comparison_response = checked(
                client.get("/api/v1/comparisons/" + own_comparison), 200, "comparison_get"
            )
            comparison_value = comparison_response.json()
            need(comparison_value.get("id") == own_comparison, "comparison_get")
            comparison_json = checked(
                client.get("/api/v1/comparisons/" + own_comparison + "/export?format=json"),
                200,
                "comparison_export_json",
            )
            comparison_csv = checked(
                client.get("/api/v1/comparisons/" + own_comparison + "/export?format=csv"),
                200,
                "comparison_export_csv",
            )
            content_checks = verify_api_content(
                slot,
                own_thesis,
                other["thesis_id"],
                own_comparison,
                other["comparison_id"],
                thesis_value,
                history,
                thesis_json.json(),
                thesis_csv.text,
                comparison_value,
                comparison_json.json(),
                comparison_csv.text,
            )
            responses = [
                ("thesis_get:" + own_thesis, thesis_response),
                ("thesis_revisions:" + own_thesis, history_response),
                ("theses_export_json", thesis_json),
                ("theses_export_csv", thesis_csv),
                ("comparison_get:" + own_comparison, comparison_response),
                ("comparison_export_json:" + own_comparison, comparison_json),
                ("comparison_export_csv:" + own_comparison, comparison_csv),
            ]
            foreign = []
            for endpoint, path in [
                ("thesis_get", "/api/v1/theses/" + other["thesis_id"]),
                ("thesis_revisions", "/api/v1/theses/" + other["thesis_id"] + "/revisions"),
                ("comparison_get", "/api/v1/comparisons/" + other["comparison_id"]),
                (
                    "comparison_export_json",
                    "/api/v1/comparisons/" + other["comparison_id"] + "/export?format=json",
                ),
                (
                    "comparison_export_csv",
                    "/api/v1/comparisons/" + other["comparison_id"] + "/export?format=csv",
                ),
            ]:
                foreign_response = checked(client.get(path), 404, "owner_isolation")
                foreign.append([endpoint, foreign_response.status_code])
            output.append(
                {
                    "owner_slot": slot,
                    "owner_id": owner_id,
                    "thesis_id": own_thesis,
                    "comparison_id": own_comparison,
                    "foreign_owner_slot": other_slot,
                    "foreign_thesis_id": other["thesis_id"],
                    "foreign_comparison_id": other["comparison_id"],
                    "revision_numbers": revisions,
                    "responses": [
                        {
                            "endpoint": name,
                            "status_code": response.status_code,
                            "body_sha256": hashlib.sha256(response.content).hexdigest(),
                            "content_checks": content_checks[name.split(":", 1)[0]],
                        }
                        for name, response in responses
                    ],
                    "foreign_statuses": foreign,
                }
            )
        finally:
            client.close()
    emit({"evidence": output})


def snapshot():
    import importlib.util
    from stock_probs.config import Settings

    spec = importlib.util.spec_from_file_location("schema14_recovery_overlay", OVERLAY_PATH)
    need(spec is not None and spec.loader is not None, "snapshot_module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    path = Path(Settings.from_env().database_path).resolve(strict=True)
    connection = module.open_schema14_recovery_reader(path)
    try:
        emit(module.recovery_database_snapshot(connection))
    finally:
        connection.close()


def identity(recovery):
    values = {}
    for line in Path("/proc/1/status").read_text().splitlines():
        if line.startswith(("Uid:", "Gid:", "CapEff:", "CapPrm:", "CapBnd:", "NoNewPrivs:")):
            name, value = line.split(":", 1)
            values[name] = value.strip()
    need(bool(values.get("Uid")) and values["Uid"].split()[0] == "10001", "process_uid")
    need(bool(values.get("Gid")) and values["Gid"].split()[0] == "10001", "process_gid")
    expected_bound = 0xC0 if recovery else 0
    need(
        int(values.get("CapEff", "-1"), 16) == 0 and int(values.get("CapPrm", "-1"), 16) == 0,
        "process_capabilities",
    )
    need(int(values.get("CapBnd", "-1"), 16) == expected_bound, "process_bounding_capabilities")
    need(values.get("NoNewPrivs") == "1", "process_no_new_privileges")
    emit({"uid": 10001, "gid": 10001, "capabilities_zero": True, "no_new_privileges": True})


def main():
    try:
        action = sys.argv[1]
        if action == "probe":
            need(len(sys.argv) == 3 and sys.argv[2] in {"candidate", "recovery"}, "readiness_phase")
            probe(sys.argv[2])
        elif action == "fixtures":
            create_fixtures()
        elif action == "api":
            need(len(sys.argv) == 3, "fixture_input")
            read_api(sys.argv[2])
        elif action == "snapshot":
            snapshot()
        elif action == "identity":
            need(len(sys.argv) == 3 and sys.argv[2] in {"candidate", "recovery"}, "identity_input")
            identity(sys.argv[2] == "recovery")
        else:
            raise CheckFailure("fixed_action")
    except CheckFailure as error:
        emit({"failure": error.step})
        raise SystemExit(1) from None
    except BaseException:
        emit({"failure": "internal"})
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()

"""


def _load_runtime_primitives(expected_sha256: str) -> ModuleType:
    """Load only the maintained schema13 Docker/process primitives by an external exact pin."""

    if not _matches(_HEX64, expected_sha256):
        raise Schema14RehearsalError("runtime_helper_pin_invalid")
    try:
        metadata = _SCHEMA13_RUNTIME_PATH.lstat()
        if (
            not stat.S_ISREG(metadata.st_mode)
            or stat.S_ISLNK(metadata.st_mode)
            or metadata.st_size > _MAX_RUNTIME_HELPER_BYTES
        ):
            raise Schema14RehearsalError("runtime_helper_invalid")
        raw = _SCHEMA13_RUNTIME_PATH.read_bytes()
        after = _SCHEMA13_RUNTIME_PATH.lstat()
    except Schema14RehearsalError:
        raise
    except OSError:
        raise Schema14RehearsalError("runtime_helper_unavailable") from None
    if hashlib.sha256(raw).hexdigest() != expected_sha256 or (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_size,
        metadata.st_mtime_ns,
    ) != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns):
        raise Schema14RehearsalError("runtime_helper_pin_mismatch")
    module = ModuleType("_schema14_schema13_runtime")
    module.__file__ = str(_SCHEMA13_RUNTIME_PATH)
    try:
        # The executable bytes are fixed by the external digest above; compilation avoids rereading
        # a path that could change between verification and module loading.
        exec(compile(raw, str(_SCHEMA13_RUNTIME_PATH), "exec"), module.__dict__)  # noqa: S102
    except Exception:
        raise Schema14RehearsalError("runtime_helper_invalid") from None
    required_callables = (
        "_docker_environment",
        "_image_run_args",
        "_run",
        "_stop_container",
        "_recovery_profile_mismatch",
        "_string_set",
    )
    required_values = (
        "IMAGE_MEMORY_BYTES",
        "IMAGE_CPUS",
        "IMAGE_PIDS",
        "_APP_READINESS_TIMEOUT_SECONDS",
    )
    if any(not callable(getattr(module, name, None)) for name in required_callables) or any(
        not hasattr(module, name) for name in required_values
    ):
        raise Schema14RehearsalError("runtime_helper_invalid")
    if (
        type(module.IMAGE_MEMORY_BYTES) is not int
        or module.IMAGE_MEMORY_BYTES != _CANONICAL_IMAGE_MEMORY_BYTES
        or type(module.IMAGE_CPUS) is not int
        or module.IMAGE_CPUS != _CANONICAL_IMAGE_CPUS
        or type(module.IMAGE_PIDS) is not int
        or module.IMAGE_PIDS != _CANONICAL_IMAGE_PIDS
        or type(module._APP_READINESS_TIMEOUT_SECONDS) is not int
        or module._APP_READINESS_TIMEOUT_SECONDS != _CANONICAL_APP_READINESS_TIMEOUT_SECONDS
    ):
        raise Schema14RehearsalError("runtime_helper_profile_mismatch")
    return module


_CONTAINER_INSPECT_FORMAT = (
    '{"Id":{{json .Id}},"Image":{{json .Image}},'
    '"State":{"Running":{{json .State.Running}}},'
    '"Config":{"User":{{json .Config.User}},"Revision":'
    '{{json (index .Config.Labels "org.opencontainers.image.revision")}},'
    '"Mounts":[{{range $i, $m := .Mounts}}{{if $i}},{{end}}'
    '{"Type":{{json $m.Type}},"Name":{{json $m.Name}},'
    '"Destination":{{json $m.Destination}},"RW":{{json $m.RW}}}{{end}}]},'
    '"HostConfig":{"ReadonlyRootfs":{{json .HostConfig.ReadonlyRootfs}},'
    '"NetworkMode":{{json .HostConfig.NetworkMode}},"Memory":{{json .HostConfig.Memory}},'
    '"NanoCpus":{{json .HostConfig.NanoCpus}},"PidsLimit":{{json .HostConfig.PidsLimit}},'
    '"CapDrop":{{json .HostConfig.CapDrop}},"CapAdd":{{json .HostConfig.CapAdd}},'
    '"SecurityOpt":{{json .HostConfig.SecurityOpt}}}}'
)


class LocalDockerSchema14Adapter:
    """Fixed local-only Docker adapter; builds nothing and never contacts a remote host."""

    def __init__(self, runtime: ModuleType, binding: ReviewedCandidateBinding, workspace: Path):
        self.runtime = runtime
        self.binding = binding
        self.workspace = workspace
        self.docker_env = runtime._docker_environment(workspace / "docker-config")
        self.verifier = workspace / "schema14_rehearsal.py"
        self.verifier.write_text(_runtime_verifier_source(), encoding="utf-8")
        self.verifier.chmod(0o644)
        overlay_bytes = _OVERLAY_RUNTIME_SOURCE.read_bytes()
        if hashlib.sha256(overlay_bytes).hexdigest() != _OVERLAY_RUNTIME_SOURCE_SHA256:
            raise Schema14RehearsalError("overlay_runtime_source_pin_mismatch")
        self.overlay_path = workspace / "research_recovery_overlay.py"
        self.overlay_path.write_bytes(overlay_bytes)
        self.overlay_path.chmod(0o644)
        self.volume_id: str | None = None
        self._volume_created = False
        self._volume_creation_uncertain = False
        self._containers: dict[int, str] = {}
        self._container_ids: set[str] = set()
        self._secret_environment = {
            "STOCK_PROBS_AUTH_SESSION_SECRET": "schema14-local-session-secret-0123456789abcdef",
            "STOCK_PROBS_BOOTSTRAP_PASSWORD": "schema14-local-admin-0123456789",
            "STOCK_PROBS_BOOTSTRAP_MEMBER_PASSWORD": "schema14-local-member-0123456789",
        }

    def _volume(self) -> str:
        if self.volume_id is None:
            volume = "stock-probs-schema14-" + os.urandom(6).hex()
            existing = self.runtime._run(
                ["docker", "volume", "inspect", "--format", "{{.Name}}", volume],
                env=self.docker_env,
                timeout=10,
                check=False,
            )
            if existing.returncode == 0 or existing.stdout.strip():
                raise Schema14RehearsalError("volume_name_collision")
            self.volume_id = volume
            created = self.runtime._run(
                ["docker", "volume", "create", volume],
                env=self.docker_env,
                timeout=15,
                check=False,
            )
            if created.returncode != 0 or created.stdout.strip() != volume:
                self._volume_creation_uncertain = True
                raise Schema14RehearsalError("volume_identity_invalid")
            inspect = self.runtime._run(
                ["docker", "volume", "inspect", "--format", "{{.Name}}|{{.Driver}}", volume],
                env=self.docker_env,
                timeout=10,
            ).stdout.strip()
            if inspect != f"{volume}|local":
                self._volume_creation_uncertain = True
                raise Schema14RehearsalError("volume_identity_invalid")
            self._volume_created = True
            self.volume_id = volume
        if not _SCHEMA14_VOLUME.fullmatch(self.volume_id):
            raise Schema14RehearsalError("volume_identity_invalid")
        return self.volume_id

    def _verify_image(self, image: str, *, candidate: bool) -> None:
        result = (
            self.runtime._run(
                [
                    "docker",
                    "image",
                    "inspect",
                    "--format",
                    "{{.Id}}|{{.Os}}|{{.Architecture}}|"
                    '{{index .Config.Labels "org.opencontainers.image.revision"}}',
                    image,
                ],
                env=self.docker_env,
                timeout=10,
            )
            .stdout.strip()
            .split("|")
        )
        expected_revision = (
            self.binding.candidate_source_commit if candidate else overlay.BASELINE_REVISION
        )
        if len(result) != 4 or result[:3] != [image, "linux", "amd64"]:
            raise Schema14RehearsalError("image_identity_mismatch")
        if candidate and result[3] != expected_revision:
            raise Schema14RehearsalError("candidate_source_label_mismatch")
        if not candidate and result[3] not in {
            overlay.BASELINE_REVISION,
            self.binding.candidate_source_commit,
            "schema14-recovery-" + overlay.OVERLAY_SHA256,
        }:
            raise Schema14RehearsalError("recovery_source_label_mismatch")

    def _readiness(self, container: str, *, candidate: bool) -> dict[str, object]:
        deadline = time.monotonic() + self.runtime._APP_READINESS_TIMEOUT_SECONDS
        last = "starting"
        while time.monotonic() < deadline:
            state = self.runtime._run(
                ["docker", "inspect", "--format", "{{.State.Running}}", container],
                env=self.docker_env,
                timeout=10,
                check=False,
                diagnostic_stage="schema14_readiness_state",
            )
            if state.returncode or state.stdout.strip() != "true":
                raise Schema14RehearsalError("container_stopped_before_readiness")
            probe = self.runtime._run(
                [
                    "docker",
                    "exec",
                    "--user",
                    "10001:10001",
                    container,
                    "python",
                    _RUNTIME_VERIFIER,
                    "probe",
                    "candidate" if candidate else "recovery",
                ],
                env=self.docker_env,
                timeout=10,
                check=False,
                diagnostic_stage="schema14_readiness_probe",
            )
            if probe.returncode == 0 and len(probe.stdout) <= 16_384:
                try:
                    value = json.loads(probe.stdout)
                except json.JSONDecodeError:
                    value = None
                if isinstance(value, dict) and value.get("status") == "ready":
                    expected_keys = {"status", "schema_version", "provider", "assistant"}
                    if candidate:
                        expected_keys.add("research")
                    if (
                        set(value) == expected_keys
                        and value.get("schema_version") == overlay.SCHEMA_VERSION
                        and value.get("provider") == "fixture"
                        and value.get("assistant") == {"enabled": False, "status": "disabled"}
                        and (
                            not candidate
                            or value.get("research") == {"enabled": True, "rollout_mode": "invited"}
                        )
                    ):
                        return value
                    last = "invalid"
            time.sleep(0.5)
        raise Schema14RehearsalError(
            "candidate_readiness_timeout" if last == "starting" else "readiness_contract_mismatch"
        )

    def _inspect_container(
        self, container: str, image: str, volume: str, *, recovery: bool
    ) -> dict[str, object]:
        raw = self.runtime._run(
            ["docker", "inspect", "--format", _CONTAINER_INSPECT_FORMAT, container],
            env=self.docker_env,
            timeout=10,
        ).stdout
        if len(raw) > 16_384:
            raise Schema14RehearsalError("container_inspection_limit")
        try:
            value = json.loads(raw)
        except json.JSONDecodeError:
            raise Schema14RehearsalError("container_inspection_invalid") from None
        if (
            not isinstance(value, dict)
            or value.get("Id") != container
            or value.get("Image") != image
            or value.get("State") != {"Running": True}
        ):
            raise Schema14RehearsalError("container_identity_mismatch")
        expected_user = "0:0" if recovery else "10001:10001"
        config = value.get("Config")
        if not isinstance(config, dict):
            raise Schema14RehearsalError("container_identity_mismatch")
        mounts = config.get("Mounts")
        expected_revisions = (
            {
                overlay.BASELINE_REVISION,
                self.binding.candidate_source_commit,
                "schema14-recovery-" + overlay.OVERLAY_SHA256,
            }
            if recovery
            else {self.binding.candidate_source_commit}
        )
        if (
            config.get("User") != expected_user
            or not isinstance(config.get("Revision"), str)
            or config.get("Revision") not in expected_revisions
            or not isinstance(mounts, list)
        ):
            raise Schema14RehearsalError("container_identity_mismatch")
        data_mounts = [
            item for item in mounts if isinstance(item, dict) and item.get("Destination") == "/data"
        ]
        verifier_mounts = [
            item
            for item in mounts
            if isinstance(item, dict) and item.get("Destination") == _RUNTIME_VERIFIER
        ]
        overlay_mounts = [
            item
            for item in mounts
            if isinstance(item, dict) and item.get("Destination") == _OVERLAY_RUNTIME_PATH
        ]
        if (
            len(data_mounts) != 1
            or data_mounts[0]
            != {"Type": "volume", "Name": volume, "Destination": "/data", "RW": True}
            or len(verifier_mounts) != 1
            or verifier_mounts[0].get("Type") != "bind"
            or verifier_mounts[0].get("RW") is not False
            or len(overlay_mounts) != 1
            or overlay_mounts[0].get("Type") != "bind"
            or overlay_mounts[0].get("RW") is not False
        ):
            raise Schema14RehearsalError("container_volume_mismatch")
        host = value.get("HostConfig")
        if not isinstance(host, dict):
            raise Schema14RehearsalError("container_profile_mismatch")
        if recovery:
            if self.runtime._recovery_profile_mismatch(host) is not None:
                raise Schema14RehearsalError("recovery_container_profile_mismatch")
        else:
            if (
                host.get("ReadonlyRootfs") is not True
                or host.get("NetworkMode") != "none"
                or host.get("Memory") != _CANONICAL_IMAGE_MEMORY_BYTES
                or host.get("NanoCpus") != 1_000_000_000
                or host.get("PidsLimit") != _CANONICAL_IMAGE_PIDS
                or self.runtime._string_set(host.get("CapDrop")) != frozenset({"ALL"})
                or host.get("CapAdd") not in (None, [])
                or "no-new-privileges:true" not in (host.get("SecurityOpt") or [])
            ):
                raise Schema14RehearsalError("candidate_container_profile_mismatch")
        return value

    def _verify_process_identity(self, container: str, *, recovery: bool) -> None:
        result = self.runtime._run(
            [
                "docker",
                "exec",
                "--user",
                "10001:10001",
                container,
                "python",
                _RUNTIME_VERIFIER,
                "identity",
                "recovery" if recovery else "candidate",
            ],
            env=self.docker_env,
            timeout=10,
            diagnostic_stage="schema14_process_identity",
        ).stdout
        if len(result) > 2048:
            raise Schema14RehearsalError("process_identity_output_limit")
        try:
            value = json.loads(result)
        except json.JSONDecodeError:
            raise Schema14RehearsalError("process_identity_invalid") from None
        if value != {
            "uid": 10001,
            "gid": 10001,
            "capabilities_zero": True,
            "no_new_privileges": True,
        }:
            raise Schema14RehearsalError("process_identity_mismatch")

    def _start(
        self, binding: ReviewedCandidateBinding, volume_id: str | None, *, recovery: bool
    ) -> Deployment:
        if binding != self.binding:
            raise Schema14RehearsalError("review_binding_changed")
        volume = self._volume()
        if volume_id is not None and volume_id != volume:
            raise Schema14RehearsalError("volume_identity_mismatch")
        image = binding.recovery_image_digest if recovery else binding.candidate_image_digest
        self._verify_image(image, candidate=not recovery)
        flags = "0" if recovery else "1"
        env_values = [
            "--env=STOCK_PROBS_DATA_DIR=/data",
            "--env=STOCK_PROBS_PROVIDER=fixture",
            "--env=STOCK_PROBS_ENV=test",
            f"--env=STOCK_PROBS_FIXTURE_NOW={_FIXTURE_CLOCK}",
            "--env=STOCK_PROBS_AUTH_MODE=local",
            "--env=STOCK_PROBS_AUTH_SESSION_SECRET",
            "--env=STOCK_PROBS_PUBLIC_ORIGIN=http://127.0.0.1:8000",
            "--env=STOCK_PROBS_BOOTSTRAP_USERNAME=schema14-admin",
            "--env=STOCK_PROBS_BOOTSTRAP_PASSWORD",
            "--env=STOCK_PROBS_BOOTSTRAP_MEMBER_USERNAME=schema14-member",
            "--env=STOCK_PROBS_BOOTSTRAP_MEMBER_PASSWORD",
            "--env=STOCK_PROBS_ASSISTANT_ENABLED=0",
            "--env=STOCK_PROBS_ASSISTANT_ROLLOUT=disabled",
            f"--env=STOCK_PROBS_RESEARCH_FEATURES_ENABLED={flags}",
            "--env=STOCK_PROBS_RESEARCH_FEATURES_CANARY_ONLY=0",
            "--env=STOCK_PROBS_HOST=127.0.0.1",
            "--env=STOCK_PROBS_PORT=8000",
        ]
        command = [
            "docker",
            "run",
            *self.runtime._image_run_args(
                volume, env_values, self.verifier, identity_drop=recovery
            ),
            "--mount",
            f"type=bind,src={self.overlay_path},dst={_OVERLAY_RUNTIME_PATH},readonly",
            image,
        ]
        child_env = {**self.docker_env, **self._secret_environment}
        raw = self.runtime._run(
            command, env=child_env, timeout=30, diagnostic_stage="schema14_container_start"
        ).stdout.strip()
        if not re.fullmatch(r"[0-9a-f]{64}", raw):
            raise Schema14RehearsalError("container_identity_invalid")
        self._container_ids.add(raw)
        try:
            readiness = self._readiness(raw, candidate=not recovery)
            self._inspect_container(raw, image, volume, recovery=recovery)
            self._verify_process_identity(raw, recovery=recovery)
            mode = readiness["research"]["rollout_mode"] if not recovery else None
            deployment = Deployment(
                phase="recovery" if recovery else "candidate",
                image_digest=image,
                source_commit=overlay.BASELINE_REVISION
                if recovery
                else binding.candidate_source_commit,
                repository_blob_sha1=None if recovery else binding.candidate_repository_blob_sha1,
                repository_sha256=overlay.OVERLAY_REPOSITORY_SHA256
                if recovery
                else binding.candidate_repository_sha256,
                schema_version=overlay.SCHEMA_VERSION,
                ready=True,
                volume_id=volume,
                assistant_enabled=False,
                research_enabled=not recovery,
                research_canary_only=None if recovery else mode == "owner_canary",
                database_restored=False,
                overlay_sha256=overlay.OVERLAY_SHA256 if recovery else None,
            )
            self._containers[id(deployment)] = raw
            return deployment
        except Exception:
            try:
                self.runtime._stop_container(raw, self.docker_env)
                self._container_ids.discard(raw)
            except Exception:  # noqa: S110 - keep the id tracked for the outer cleanup retry
                self._container_ids.add(raw)
            raise

    def start_candidate(
        self,
        binding: ReviewedCandidateBinding,
        *,
        volume_id: str | None,
        assistant_enabled: bool,
        research_enabled: bool,
        research_canary_only: Literal[False],
    ) -> Deployment:
        if (
            assistant_enabled is not False
            or research_enabled is not True
            or research_canary_only is not False
        ):
            raise Schema14RehearsalError("candidate_control_request_invalid")
        return self._start(binding, volume_id, recovery=False)

    def start_recovery(
        self,
        binding: ReviewedCandidateBinding,
        *,
        volume_id: str,
        assistant_enabled: Literal[False],
        research_enabled: Literal[False],
        research_canary_only: Literal[False],
        restore_database: Literal[False],
    ) -> Deployment:
        if (
            assistant_enabled is not False
            or research_enabled is not False
            or research_canary_only is not False
            or restore_database is not False
        ):
            raise Schema14RehearsalError("recovery_control_request_invalid")
        return self._start(binding, volume_id, recovery=True)

    def _container_for(self, deployment: Deployment) -> str:
        container = self._containers.get(id(deployment))
        if container is None:
            raise Schema14RehearsalError("deployment_identity_unknown")
        return container

    def _exec_json(
        self, deployment: Deployment, action: str, argument: str | None = None
    ) -> object:
        container = self._container_for(deployment)
        command = [
            "docker",
            "exec",
            "--user",
            "10001:10001",
            container,
            "python",
            _RUNTIME_VERIFIER,
            action,
        ]
        if argument is not None:
            command.append(argument)
        raw = self.runtime._run(
            command, env=self.docker_env, timeout=90, diagnostic_stage="schema14_" + action
        ).stdout
        if len(raw) > 256 * 1024:
            raise Schema14RehearsalError("runtime_verifier_output_limit")
        try:
            result = json.loads(raw)
        except json.JSONDecodeError:
            raise Schema14RehearsalError("runtime_verifier_output_invalid") from None
        if not isinstance(result, dict) or "failure" in result:
            raise Schema14RehearsalError("runtime_verifier_check_failed")
        return result

    def create_two_owner_research_fixtures(
        self, deployment: Deployment
    ) -> tuple[OwnerFixture, ...]:
        if deployment.phase != "candidate" or not deployment.research_enabled:
            raise Schema14RehearsalError("candidate_fixture_phase_invalid")
        result = self._exec_json(deployment, "fixtures")
        items = result.get("fixtures") if isinstance(result, dict) else None
        if not isinstance(items, list) or len(items) != 2:
            raise Schema14RehearsalError("owner_fixture_invalid")
        fixtures = []
        for item in items:
            if not isinstance(item, dict) or set(item) != {
                "owner_slot",
                "owner_id",
                "thesis_id",
                "comparison_id",
            }:
                raise Schema14RehearsalError("owner_fixture_invalid")
            fixtures.append(OwnerFixture(**item))
        return tuple(fixtures)

    def read_research_api(
        self, deployment: Deployment, fixtures: tuple[OwnerFixture, ...]
    ) -> tuple[OwnerApiEvidence, ...]:
        payload = json.dumps(
            [vars(item) for item in fixtures], sort_keys=True, separators=(",", ":")
        )
        result = self._exec_json(deployment, "api", payload)
        items = result.get("evidence") if isinstance(result, dict) else None
        if not isinstance(items, list):
            raise Schema14RehearsalError("api_evidence_invalid")
        evidence = []
        for item in items:
            if not isinstance(item, dict):
                raise Schema14RehearsalError("api_evidence_invalid")
            responses = tuple(
                ResponseDigest(
                    endpoint=entry.get("endpoint"),
                    status_code=entry.get("status_code"),
                    body_sha256=entry.get("body_sha256"),
                    content_checks=tuple(entry.get("content_checks", [])),
                )
                for entry in item.get("responses", [])
                if isinstance(entry, dict)
            )
            statuses = tuple((entry[0], entry[1]) for entry in item.get("foreign_statuses", []))
            evidence.append(
                OwnerApiEvidence(
                    owner_slot=item.get("owner_slot"),
                    owner_id=item.get("owner_id"),
                    thesis_id=item.get("thesis_id"),
                    comparison_id=item.get("comparison_id"),
                    foreign_owner_slot=item.get("foreign_owner_slot"),
                    foreign_thesis_id=item.get("foreign_thesis_id"),
                    foreign_comparison_id=item.get("foreign_comparison_id"),
                    revision_numbers=tuple(item.get("revision_numbers", [])),
                    responses=responses,
                    foreign_statuses=statuses,
                )
            )
        return tuple(evidence)

    def snapshot_database(self, deployment: Deployment) -> dict[str, object]:
        image = deployment.image_digest
        volume = deployment.volume_id
        if not _IMAGE_DIGEST.fullmatch(image) or not _SCHEMA14_VOLUME.fullmatch(volume):
            raise Schema14RehearsalError("snapshot_identity_invalid")
        command = [
            "docker",
            "run",
            "--rm",
            "--network=none",
            "--read-only",
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges:true",
            "--user",
            "10001:10001",
            "--memory",
            str(_CANONICAL_IMAGE_MEMORY_BYTES),
            "--cpus",
            str(_CANONICAL_IMAGE_CPUS),
            "--pids-limit",
            str(_CANONICAL_IMAGE_PIDS),
            "--tmpfs",
            "/tmp:rw,nosuid,nodev,noexec,size=64m,uid=10001,gid=10001,mode=0700",  # noqa: S108 - bounded app-private tmpfs
            "--mount",
            f"type=volume,src={volume},dst=/data,readonly",
            "--mount",
            f"type=bind,src={self.verifier},dst={_RUNTIME_VERIFIER},readonly",
            "--mount",
            f"type=bind,src={self.overlay_path},dst={_OVERLAY_RUNTIME_PATH},readonly",
            "--env=STOCK_PROBS_DATA_DIR=/data",
            "--env=STOCK_PROBS_ENV=test",
            "--env=STOCK_PROBS_PROVIDER=fixture",
            "--env=STOCK_PROBS_AUTH_MODE=local",
            "--env=STOCK_PROBS_ASSISTANT_ENABLED=0",
            "--env=STOCK_PROBS_ASSISTANT_ROLLOUT=disabled",
            "--env=STOCK_PROBS_RESEARCH_FEATURES_ENABLED=0",
            "--env=STOCK_PROBS_RESEARCH_FEATURES_CANARY_ONLY=0",
            "--env=STOCK_PROBS_HOST=127.0.0.1",
            "--env=STOCK_PROBS_PORT=8000",
            "--entrypoint",
            "python",
            image,
            _RUNTIME_VERIFIER,
            "snapshot",
        ]
        raw = self.runtime._run(
            command, env=self.docker_env, timeout=120, diagnostic_stage="schema14_snapshot"
        ).stdout
        if len(raw) > 256 * 1024:
            raise Schema14RehearsalError("snapshot_output_limit")
        try:
            value = json.loads(raw)
        except json.JSONDecodeError:
            raise Schema14RehearsalError("database_snapshot_invalid") from None
        return value

    def stop(self, deployment: Deployment) -> None:
        container = self._container_for(deployment)
        self.runtime._stop_container(container, self.docker_env)
        self._container_ids.discard(container)
        self._containers.pop(id(deployment), None)

    def close(self) -> dict[str, object]:
        stopped = True
        for container in tuple(self._container_ids):
            try:
                self.runtime._stop_container(container, self.docker_env)
                self._container_ids.discard(container)
            except Exception:
                stopped = False
        volume_removed = self.volume_id is None and not self._volume_creation_uncertain
        if self._volume_creation_uncertain:
            volume_removed = False
        if self.volume_id is not None and self._volume_created and stopped:
            volume = self.volume_id
            if not _SCHEMA14_VOLUME.fullmatch(volume):
                return {"containers_removed": False, "volume_removed": False}
            current = self.runtime._run(
                ["docker", "volume", "inspect", "--format", "{{.Name}}|{{.Driver}}", volume],
                env=self.docker_env,
                timeout=10,
                check=False,
                diagnostic_stage="schema14_volume_inspect_before_cleanup",
            )
            if current.returncode != 0:
                volume_removed = False
            elif current.stdout.strip() == f"{volume}|local":
                references = self.runtime._run(
                    [
                        "docker",
                        "ps",
                        "--all",
                        "--quiet",
                        "--no-trunc",
                        "--filter",
                        "volume=" + volume,
                    ],
                    env=self.docker_env,
                    timeout=10,
                    check=False,
                    diagnostic_stage="schema14_volume_reference_verify",
                )
                if references.returncode == 0 and not references.stdout.strip():
                    removed = self.runtime._run(
                        ["docker", "volume", "rm", volume],
                        env=self.docker_env,
                        timeout=15,
                        check=False,
                        diagnostic_stage="schema14_volume_remove",
                    )
                    if removed.returncode == 0:
                        check = self.runtime._run(
                            ["docker", "volume", "ls", "--quiet", "--filter", "name=" + volume],
                            env=self.docker_env,
                            timeout=10,
                            check=False,
                            diagnostic_stage="schema14_volume_absence",
                        )
                        volume_removed = check.returncode == 0 and not check.stdout.strip()
        return {
            "containers_removed": stopped and not self._container_ids,
            "volume_removed": volume_removed,
        }


def execute_local_schema14_rehearsal(
    binding_path: Path, expected_binding_sha256: str, expected_runtime_helper_sha256: str
) -> dict[str, object]:
    """Execute one fixed local Docker lifecycle only after exact reviewed pins are supplied."""

    binding = load_reviewed_candidate_binding(binding_path, expected_binding_sha256)
    runtime = _load_runtime_primitives(expected_runtime_helper_sha256)
    try:
        overlay_metadata = _OVERLAY_RUNTIME_SOURCE.lstat()
        if not stat.S_ISREG(overlay_metadata.st_mode) or stat.S_ISLNK(overlay_metadata.st_mode):
            raise Schema14RehearsalError("overlay_runtime_source_invalid")
        overlay_hash = hashlib.sha256(_OVERLAY_RUNTIME_SOURCE.read_bytes()).hexdigest()
    except OSError:
        raise Schema14RehearsalError("overlay_runtime_source_unavailable") from None
    if overlay_hash != _OVERLAY_RUNTIME_SOURCE_SHA256:
        raise Schema14RehearsalError("overlay_runtime_source_pin_mismatch")
    with tempfile.TemporaryDirectory(prefix="stock-probs-schema14-") as temporary:
        workspace = Path(temporary)
        adapter = LocalDockerSchema14Adapter(runtime, binding, workspace)
        try:
            result = _run_with_binding(adapter, binding)
        except Exception as exc:
            cleanup = adapter.close()
            if cleanup != {"containers_removed": True, "volume_removed": True}:
                raise Schema14RehearsalError("runtime_cleanup_unverified") from exc
            raise
        cleanup = adapter.close()
        if cleanup != {"containers_removed": True, "volume_removed": True}:
            raise Schema14RehearsalError("runtime_cleanup_unverified")
        result["cleanup"] = cleanup
        result["runtime_helper_sha256"] = expected_runtime_helper_sha256
        result["overlay_runtime_source_sha256"] = overlay_hash
        return result


_OVERLAY_RUNTIME_SOURCE_SHA256 = "e80d49b9eabc64f467503fbe7a70fdad90e844ca96e255737760e756a79586aa"


def main(argv: list[str] | None = None) -> int:
    """Validate a reviewed pair binding or execute one explicit local rehearsal."""

    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--prepare-only", action="store_true")
    mode.add_argument("--execute", action="store_true")
    parser.add_argument("--binding", type=Path, required=True)
    parser.add_argument("--binding-sha256", required=True)
    parser.add_argument("--runtime-helper-sha256")
    args = parser.parse_args(argv)
    try:
        binding = load_reviewed_candidate_binding(args.binding, args.binding_sha256)
        if args.prepare_only:
            print(
                json.dumps(
                    {
                        "status": "prepared",
                        "executed": False,
                        "binding_sha256": binding.binding_file_sha256,
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                )
            )
            return 0
        if args.runtime_helper_sha256 is None:
            raise Schema14RehearsalError("runtime_helper_pin_required")
        result = execute_local_schema14_rehearsal(
            args.binding, args.binding_sha256, args.runtime_helper_sha256
        )
        print(json.dumps(result, sort_keys=True, separators=(",", ":")))
        return 0
    except Schema14RehearsalError as exc:
        parser.exit(2, f"schema14_rehearsal_failed:{exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
