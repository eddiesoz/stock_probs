"""M05 developer tests target manifest strictness, rollback safety, and CLI bounds."""

from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import stat
import sys
import zipfile
from collections.abc import Callable
from datetime import UTC, datetime
from importlib.resources import files
from pathlib import Path
from types import ModuleType
from uuid import uuid4

import pytest

import stock_probs.backup as backup_module
import stock_probs.cli as cli
from stock_probs.backup import BackupError, BackupManager
from stock_probs.repository import Repository, RepositoryOperationalError
from stock_probs.research import ResearchStore

OWNER_USER_ID = 1


def _install_fake_uvicorn(monkeypatch: pytest.MonkeyPatch, run: Callable[..., object]) -> None:
    """Replace the CLI's lazy Uvicorn import with an observable, network-free seam."""

    module = ModuleType("uvicorn")
    module.run = run  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "uvicorn", module)


def _manager(settings) -> tuple[Repository, BackupManager]:
    """Create the migrated operation boundary without involving provider or presentation code."""

    repository = Repository(settings.database_path)
    repository.migrate()
    return repository, BackupManager(repository, settings.backup_dir)


def _record_failure(repository: Repository, request_id: str) -> None:
    """Use the persistence boundary so fixtures remain valid as schema constraints tighten."""

    now = datetime(2025, 1, 1, tzinfo=UTC)
    repository.record_failure(
        owner_user_id=OWNER_USER_ID,
        request_id=request_id,
        submitted_symbol="FAIL",
        normalized_symbol="FAIL",
        asset_type="stock",
        error_code="fixture_failure",
        error_message="Intentional backup test failure.",
        submitted_at=now,
        completed_at=now,
    )


def _rewrite_artifact(source: Path, target: Path, mutate) -> None:
    """Build a well-formed but intentionally altered artifact for fail-closed checks."""

    with zipfile.ZipFile(source) as archive:
        database = archive.read("database.sqlite3")
        manifest = json.loads(archive.read("manifest.json"))
    database, manifest = mutate(database, manifest)
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("database.sqlite3", database)
        archive.writestr("manifest.json", json.dumps(manifest))


def _version_thirteen_database(path: Path) -> None:
    """Build a genuine schema-13 fixture from the immutable packaged migrations."""

    applied_at = datetime(2025, 1, 1, tzinfo=UTC).isoformat()
    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute(
            "CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
        )
        migrations = sorted(
            migration
            for migration in files("stock_probs.migrations").iterdir()
            if migration.name.endswith(".sql") and int(migration.name[:3]) <= 13
        )
        for version, migration in enumerate(migrations, start=1):
            Repository._execute_migration(connection, migration.read_text())
            connection.execute(
                "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                (version, applied_at),
            )


def _package_legacy_v1_schema_fourteen(
    manager: BackupManager, snapshot: Path, target: Path
) -> dict:
    """Create a correctly signed schema-14 artifact using the preserved v1 count contract."""

    manifest = {
        "format": "stock-probs-backup",
        "format_version": 1,
        "schema_version": 14,
        "schema_sha256": manager._integrity(snapshot, expected_version=14),
        "created_at": datetime(2026, 10, 16, tzinfo=UTC).isoformat(),
        "database_sha256": manager._checksum(snapshot),
        "database_size": snapshot.stat().st_size,
        "counts": manager.repository.backup_counts(snapshot, format_version=1),
    }
    manager._package(snapshot, manifest, manager._trust_key(create=False), target)
    return manifest


def test_manifest_records_database_schema_checksum_counts_and_timezone(settings):
    repository, manager = _manager(settings)
    _record_failure(repository, "backup-event")

    created = manager.create("manifest.spbackup")
    manifest, _, staging = manager.verify("manifest.spbackup")
    try:
        assert (
            created["sha256"]
            == hashlib.sha256((settings.backup_dir / "manifest.spbackup").read_bytes()).hexdigest()
        )
        assert len(manifest["database_sha256"]) == len(manifest["schema_sha256"]) == 64
        assert manifest["counts"]["search_events"] == 1
        assert manifest["created_at"].endswith("+00:00")
    finally:
        staging.cleanup()


def test_signed_legacy_v1_schema_fourteen_backup_remains_verifiable(settings):
    """Legacy schema-14 v1 artifacts retain their authenticated five-count contract."""

    repository, manager = _manager(settings)
    research = ResearchStore(repository)
    thesis = research.save_thesis(
        OWNER_USER_ID,
        {
            "symbol": "SPY",
            "asset_type": "etf",
            "title": "Legacy signed thesis",
            "reasoning": "Saved before the count-format upgrade",
            "risks": "Market risk",
            "invalidation": "The thesis no longer holds",
            "evidence": [],
        },
        datetime(2026, 10, 16, tzinfo=UTC),
    )
    source = manager.create("v2-source.spbackup")
    manifest, snapshot, staging = manager.verify(source["name"])
    legacy_path = settings.backup_dir / "legacy-v1-schema14.spbackup"
    try:
        legacy_manifest = _package_legacy_v1_schema_fourteen(manager, snapshot, legacy_path)
        assert legacy_manifest["format_version"] == 1
        assert set(legacy_manifest["counts"]) == {
            "search_events",
            "forecast_runs",
            "forecast_inputs",
            "forecast_results",
            "outcomes",
        }
    finally:
        staging.cleanup()

    checked, _, checked_staging = manager.verify(legacy_path.name)
    try:
        assert checked["format_version"] == 1
        assert checked["schema_version"] == 14
        assert checked["counts"] == legacy_manifest["counts"]
    finally:
        checked_staging.cleanup()

    restored = manager.restore(legacy_path.name, promote=True)
    assert restored["promoted"] is True
    assert restored["counts"] == legacy_manifest["counts"]
    assert research.get(OWNER_USER_ID, "theses", thesis["id"]) == thesis


def test_schema_thirteen_v1_backup_verifies_but_cannot_replace_active_schema_fourteen(
    settings,
):
    """A signed old-schema artifact remains inspectable but cannot promote over schema 14."""

    active_repository, manager = _manager(settings)
    manager.create("active-v2.spbackup")
    old_database = settings.data_dir / "schema-thirteen.sqlite3"
    _version_thirteen_database(old_database)
    old_repository = Repository(old_database)
    old_manager = BackupManager(old_repository, settings.backup_dir)

    legacy = old_manager.create("legacy-v1-schema13.spbackup", schema_version=13)
    assert legacy["format_version"] == 1
    manifest, snapshot, staging = manager._verify_unlocked(
        legacy["name"], require_active_schema=False
    )
    try:
        assert manifest["format_version"] == 1
        assert manifest["schema_version"] == 13
        assert manager._counts(snapshot, manifest["format_version"]) == manifest["counts"]
    finally:
        staging.cleanup()

    before = active_repository.representative_counts()
    with pytest.raises(BackupError, match="cannot be restored over active schema version"):
        manager.restore(legacy["name"], promote=True)
    assert active_repository.representative_counts() == before
    with pytest.raises(RepositoryOperationalError, match="Representative database counts"):
        old_repository.backup_counts(old_database, format_version=2)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda counts: counts.pop("research_thesis_revisions"), "representative counts"),
        (lambda counts: counts.update({"unapproved_table": 0}), "representative counts"),
        (lambda counts: counts.__setitem__("research_theses", True), "representative counts"),
    ],
)
def test_v2_manifest_rejects_missing_extra_or_boolean_research_counts(settings, mutation, message):
    """Versioned counts require all fixed research tables and exact integer values."""

    _, manager = _manager(settings)
    source = settings.backup_dir / manager.create("strict-v2-source.spbackup")["name"]

    def alter_counts(database: bytes, manifest: dict) -> tuple[bytes, dict]:
        assert manifest["format_version"] == 2
        mutation(manifest["counts"])
        return database, manifest

    _rewrite_artifact(source, settings.backup_dir / "invalid-v2-counts.spbackup", alter_counts)
    with pytest.raises(BackupError, match=message):
        manager.restore("invalid-v2-counts.spbackup", promote=True)


def test_v2_manifest_cannot_downgrade_to_legacy_five_count_shape(settings):
    """Changing a v2 manifest to legacy shape cannot bypass its original HMAC."""

    _, manager = _manager(settings)
    source = settings.backup_dir / manager.create("downgrade-source.spbackup")["name"]

    def downgrade(database: bytes, manifest: dict) -> tuple[bytes, dict]:
        assert manifest["format_version"] == 2
        manifest["format_version"] = 1
        for key in ("research_theses", "research_thesis_revisions", "research_comparisons"):
            del manifest["counts"][key]
        return database, manifest

    _rewrite_artifact(source, settings.backup_dir / "downgraded-v2.spbackup", downgrade)
    with pytest.raises(BackupError, match="authenticity"):
        manager.restore("downgraded-v2.spbackup", promote=True)


def test_v2_manifest_rejects_schema_thirteen_and_legacy_manifest_rejects_v2_counts(settings):
    """The new count shape is bound to schema 14 and cannot be relabeled as v1."""

    repository, manager = _manager(settings)
    source = settings.backup_dir / manager.create("schema-bound-v2.spbackup")["name"]

    def downgrade_schema(database: bytes, manifest: dict) -> tuple[bytes, dict]:
        manifest["schema_version"] = 13
        return database, manifest

    _rewrite_artifact(source, settings.backup_dir / "v2-schema13.spbackup", downgrade_schema)
    with pytest.raises(BackupError, match="incompatible"):
        manager.restore("v2-schema13.spbackup", promote=True)

    _, snapshot, staging = manager.verify("schema-bound-v2.spbackup")
    legacy_path = settings.backup_dir / "v1-with-v2-counts.spbackup"
    try:
        legacy_manifest = _package_legacy_v1_schema_fourteen(manager, snapshot, legacy_path)
        legacy_manifest["format_version"] = 1
        legacy_manifest["counts"] = repository.backup_counts(snapshot, format_version=2)
        with zipfile.ZipFile(legacy_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.write(snapshot, "database.sqlite3")
            archive.writestr("manifest.json", json.dumps(legacy_manifest))
    finally:
        staging.cleanup()

    with pytest.raises(BackupError, match="representative counts"):
        manager.restore(legacy_path.name, promote=True)


def test_restore_rejects_self_consistent_but_incompatible_schema(settings):
    _, manager = _manager(settings)
    source = settings.backup_dir / manager.create("schema-source.spbackup")["name"]

    def alter_schema(database: bytes, manifest: dict) -> tuple[bytes, dict]:
        staged = settings.backup_dir / "altered.sqlite3"
        staged.write_bytes(database)
        with sqlite3.connect(staged) as connection:
            connection.execute("CREATE TABLE incompatible_extension(value TEXT)")
        changed = staged.read_bytes()
        staged.unlink()
        manifest["database_sha256"] = hashlib.sha256(changed).hexdigest()
        manifest["database_size"] = len(changed)
        # Matching the altered DDL in the manifest must not bypass app-schema comparison.
        manifest["schema_sha256"] = "0" * 64
        return changed, manifest

    _rewrite_artifact(source, settings.backup_dir / "incompatible-schema.spbackup", alter_schema)
    # A recomputed checksum/schema claim is rejected at authentication before SQLite work.
    with pytest.raises(BackupError, match="authenticity"):
        manager.restore("incompatible-schema.spbackup", promote=True)
    assert manager.repository.representative_counts()["search_events"] == 0


def test_restore_rejects_forged_recomputed_manifest_without_touching_active_data(settings):
    """A valid altered database plus matching public metadata still lacks local authority."""

    repository, manager = _manager(settings)
    _record_failure(repository, "active-event")
    source = settings.backup_dir / manager.create("auth-source.spbackup")["name"]
    _record_failure(repository, "later-active-event")
    before = settings.database_path.read_bytes()

    def forge(database: bytes, manifest: dict) -> tuple[bytes, dict]:
        staged = settings.backup_dir / "forged.sqlite3"
        staged.write_bytes(database)
        with sqlite3.connect(staged) as connection:
            now = datetime(2025, 1, 2, tzinfo=UTC).isoformat()
            connection.execute(
                "INSERT INTO search_events "
                "(request_id, submitted_symbol, normalized_symbol, asset_type, status, "
                "is_repeat, error_code, error_message, submitted_at, completed_at) "
                "VALUES (?, 'FAIL', 'FAIL', 'stock', 'failed', 1, 'forged', 'forged', ?, ?)",
                ("forged-event", now, now),
            )
        changed = staged.read_bytes()
        staged.unlink()
        # These formerly sufficient public values are deliberately made self-consistent.
        manifest["database_sha256"] = hashlib.sha256(changed).hexdigest()
        manifest["database_size"] = len(changed)
        manifest["counts"]["search_events"] += 1
        return changed, manifest

    forged = settings.backup_dir / "forged.spbackup"
    _rewrite_artifact(source, forged, forge)
    with pytest.raises(BackupError, match="authenticity"):
        manager.restore(forged.name, promote=True)

    assert settings.database_path.read_bytes() == before
    assert repository.representative_counts()["search_events"] == 2
    assert not settings.database_path.with_suffix(".pre-restore.sqlite3").exists()


def test_restore_rejects_unsigned_manifest(settings):
    """Legacy or attacker-created manifests cannot opt out of installation authentication."""

    _, manager = _manager(settings)
    source = settings.backup_dir / manager.create("signed.spbackup")["name"]

    def remove_signature(database: bytes, manifest: dict) -> tuple[bytes, dict]:
        manifest.pop("manifest_hmac_sha256")
        return database, manifest

    _rewrite_artifact(source, settings.backup_dir / "unsigned.spbackup", remove_signature)
    with pytest.raises(BackupError, match="unsigned"):
        manager.restore("unsigned.spbackup")


def test_restore_rejects_zip_slip_member_without_touching_active_data(settings):
    repository, manager = _manager(settings)
    _record_failure(repository, "active-event")
    source = settings.backup_dir / manager.create("safe.spbackup")["name"]
    before = settings.database_path.read_bytes()

    with zipfile.ZipFile(source) as archive:
        database = archive.read("database.sqlite3")
        manifest = archive.read("manifest.json")
    with zipfile.ZipFile(settings.backup_dir / "zip-slip.spbackup", "w") as archive:
        archive.writestr("database.sqlite3", database)
        archive.writestr("manifest.json", manifest)
        archive.writestr("../outside.sqlite3", b"attacker data")

    with pytest.raises(BackupError, match="too many|unexpected or unsafe"):
        manager.restore("zip-slip.spbackup", promote=True)
    assert settings.database_path.read_bytes() == before
    assert not (settings.backup_dir.parent / "outside.sqlite3").exists()


def test_transferred_key_restores_but_wrong_key_fails_closed(settings, tmp_path):
    source_repository, source = _manager(settings)
    _record_failure(source_repository, "cross-installation-event")
    source.create("transfer.spbackup")

    destination_root = tmp_path / "destination"
    destination_repository = Repository(destination_root / "stock_probs.sqlite3")
    destination_repository.migrate()
    destination = BackupManager(destination_repository, destination_root / "backups")
    destination._ensure_backup_dir()
    shutil.copy2(source.trust_key_path, destination.trust_key_path)
    shutil.copy2(
        settings.backup_dir / "transfer.spbackup",
        destination.backup_dir / "transfer.spbackup",
    )

    assert destination.restore("transfer.spbackup", promote=True)["promoted"] is True
    assert destination_repository.history(owner_user_id=OWNER_USER_ID)["items"][0][
        "request_id"
    ] == ("cross-installation-event")

    destination.trust_key_path.write_bytes(b"x" * 32)
    before = destination_repository.representative_counts()
    with pytest.raises(BackupError, match="authenticity"):
        destination.restore("transfer.spbackup", promote=True)
    assert destination_repository.representative_counts() == before


def test_new_backup_does_not_silently_rotate_a_lost_key(settings):
    repository, manager = _manager(settings)
    _record_failure(repository, "preserved-event")
    manager.create("before-key-loss.spbackup")
    manager.trust_key_path.unlink()

    with pytest.raises(BackupError, match="trust key is missing"):
        manager.create("after-key-loss.spbackup")

    assert not manager.trust_key_path.exists()
    assert not (settings.backup_dir / "after-key-loss.spbackup").exists()
    assert repository.history(owner_user_id=OWNER_USER_ID)["total"] == 1


def test_backup_count_and_disk_limits_refuse_creation_without_expiring_history(
    settings, monkeypatch
):
    repository, manager = _manager(settings)
    _record_failure(repository, "retained-event")
    monkeypatch.setattr(backup_module, "MAX_MANAGED_BACKUPS", 1)
    manager.create("first.spbackup")

    with pytest.raises(BackupError, match="retention limit"):
        manager.create("count-refused.spbackup")
    assert repository.history(owner_user_id=OWNER_USER_ID)["total"] == 1
    assert not (settings.backup_dir / "count-refused.spbackup").exists()

    monkeypatch.setattr(backup_module, "MAX_MANAGED_BACKUPS", 32)
    monkeypatch.setattr(
        backup_module,
        "MAX_BACKUP_STORAGE_BYTES",
        (settings.backup_dir / "first.spbackup").stat().st_size,
    )
    with pytest.raises(BackupError, match="storage limit"):
        manager.create("disk-refused.spbackup")
    assert repository.history(owner_user_id=OWNER_USER_ID)["total"] == 1
    assert not (settings.backup_dir / "disk-refused.spbackup").exists()


def test_restore_rejects_entry_flood_during_bounded_zip_preflight(settings, monkeypatch):
    """EOCD entry bounds reject a flood before ZipFile parses central-directory objects."""

    _, manager = _manager(settings)
    manager._ensure_backup_dir()
    flooded = settings.backup_dir / "flooded.spbackup"
    with zipfile.ZipFile(flooded, "w") as archive:
        for index in range(3):
            archive.writestr(f"entry-{index}", b"x")

    def expensive_parser_must_not_run(*args, **kwargs):
        pytest.fail("ZipFile parsing must occur only after bounded metadata preflight")

    monkeypatch.setattr("stock_probs.backup.zipfile.ZipFile", expensive_parser_must_not_run)
    with pytest.raises(BackupError, match="too many entries"):
        manager.restore(flooded.name)


def test_restore_rejects_oversized_central_metadata_before_zip_parser(settings, monkeypatch):
    """A forged EOCD metadata size is bounded before central-directory allocation."""

    _, manager = _manager(settings)
    artifact = settings.backup_dir / manager.create("metadata.spbackup")["name"]
    payload = bytearray(artifact.read_bytes())
    eocd = payload.rfind(b"PK\x05\x06")
    assert eocd >= 0
    payload[eocd + 12 : eocd + 16] = (16 * 1024 + 1).to_bytes(4, "little")
    artifact.write_bytes(payload)

    def expensive_parser_must_not_run(*args, **kwargs):
        pytest.fail("oversized metadata must fail before ZipFile parsing")

    monkeypatch.setattr("stock_probs.backup.zipfile.ZipFile", expensive_parser_must_not_run)
    with pytest.raises(BackupError, match="metadata exceeds"):
        manager.restore(artifact.name)


def test_restore_does_not_regenerate_a_missing_installation_key(settings):
    """Key loss is explicit and cannot silently establish new trust for an old artifact."""

    repository, manager = _manager(settings)
    _record_failure(repository, "preserved-active-event")
    created = manager.create("key-loss.spbackup")
    manager.trust_key_path.unlink()

    with pytest.raises(BackupError, match="trust key is missing"):
        manager.restore(created["name"], promote=True)

    assert not manager.trust_key_path.exists()
    assert repository.representative_counts()["search_events"] == 1


def test_operations_harden_existing_runtime_storage_and_sensitive_files(settings, monkeypatch):
    """Startup and backup access repair permissive modes through no-follow descriptors."""

    settings.ensure_local_dirs()
    settings.data_dir.chmod(0o777)
    settings.backup_dir.chmod(0o777)
    repository, manager = _manager(settings)
    repository.database_path.chmod(0o666)
    original_package = manager._package

    def assert_private_staging(snapshot, manifest, trust_key, target):
        assert stat.S_IMODE(target.parent.stat().st_mode) == 0o700
        assert stat.S_IMODE(snapshot.stat().st_mode) == 0o600
        original_package(snapshot, manifest, trust_key, target)
        assert stat.S_IMODE(target.stat().st_mode) == 0o600

    monkeypatch.setattr(manager, "_package", assert_private_staging)
    created = manager.create("permissions.spbackup")
    artifact = settings.backup_dir / created["name"]
    artifact.chmod(0o666)
    manager.trust_key_path.chmod(0o666)

    settings.ensure_local_dirs()
    with repository.connect():
        pass
    manifest, staged_database, staging = manager.verify(created["name"])

    try:
        assert manifest["manifest_hmac_sha256"]
        for private_directory in (
            settings.data_dir,
            settings.backup_dir,
            Path(staging.name),
        ):
            assert stat.S_IMODE(private_directory.stat().st_mode) == 0o700
        for sensitive in (
            repository.database_path,
            artifact,
            manager.trust_key_path,
            staged_database,
        ):
            assert stat.S_IMODE(sensitive.stat().st_mode) == 0o600
    finally:
        staging.cleanup()


def test_restore_failure_after_swap_atomically_restores_active_database(settings, monkeypatch):
    repository, manager = _manager(settings)
    _record_failure(repository, "event-1")
    manager.create("before-later-data.spbackup")
    _record_failure(repository, "event-2")

    original_counts = manager._counts

    def fail_only_after_swap(path: Path, format_version: int = 1) -> dict[str, int]:
        counts = original_counts(path, format_version)
        rollback = settings.database_path.with_suffix(".pre-restore.sqlite3")
        if path == settings.database_path and rollback.exists():
            counts["search_events"] += 1
        return counts

    monkeypatch.setattr(manager, "_counts", fail_only_after_swap)
    with pytest.raises(BackupError, match="representative-count"):
        manager.restore("before-later-data.spbackup", promote=True)

    assert repository.representative_counts()["search_events"] == 2
    assert not settings.database_path.with_suffix(".pre-restore.sqlite3").exists()


def test_legacy_v1_schema14_promotion_failure_preserves_active_research_rows(settings, monkeypatch):
    """A legacy manifest cannot narrow schema-14 rollback verification after promotion."""

    repository, manager = _manager(settings)
    legacy_source = manager.create("legacy-v1-before-research.spbackup")
    _, snapshot, staging = manager.verify(legacy_source["name"])
    legacy_path = settings.backup_dir / "legacy-v1-before-research-copy.spbackup"
    try:
        _package_legacy_v1_schema_fourteen(manager, snapshot, legacy_path)
    finally:
        staging.cleanup()

    research = ResearchStore(repository)
    thesis = research.save_thesis(
        OWNER_USER_ID,
        {
            "symbol": "VFV.TO",
            "asset_type": "etf",
            "title": "Active thesis",
            "reasoning": "The current allocation remains appropriate",
            "risks": "Canadian market concentration",
            "invalidation": "The investment horizon changes",
            "evidence": [],
        },
        datetime(2026, 10, 16, tzinfo=UTC),
    )
    thesis = research.save_thesis(
        OWNER_USER_ID,
        {**thesis["data"], "reasoning": "Reviewed current reasoning"},
        datetime(2026, 10, 16, tzinfo=UTC),
        thesis_id=thesis["id"],
        revision=1,
    )
    comparison = research.save_comparison(
        OWNER_USER_ID,
        str(uuid4()),
        {"captured_at": datetime(2026, 10, 16, tzinfo=UTC).isoformat(), "instruments": []},
        datetime(2026, 10, 16, tzinfo=UTC),
    )

    original_counts = manager._counts
    formats_checked_while_rollback_exists: list[int] = []
    formats_checked_after_rollback: list[int] = []

    def fail_promoted_counts(path: Path, format_version: int = 1) -> dict[str, int]:
        counts = original_counts(path, format_version)
        rollback = settings.database_path.with_suffix(".pre-restore.sqlite3")
        if path == settings.database_path and rollback.exists():
            formats_checked_while_rollback_exists.append(format_version)
            if format_version != 2:
                raise AssertionError("schema-14 promotion used the legacy count contract")
            counts["research_theses"] += 1
        elif path == settings.database_path and formats_checked_while_rollback_exists:
            formats_checked_after_rollback.append(format_version)
        return counts

    monkeypatch.setattr(manager, "_counts", fail_promoted_counts)
    with pytest.raises(BackupError, match="representative-count"):
        manager.restore(legacy_path.name, promote=True)

    assert formats_checked_while_rollback_exists == [2]
    assert formats_checked_after_rollback == [2]
    assert research.get(OWNER_USER_ID, "theses", thesis["id"]) == thesis
    assert research.revisions(OWNER_USER_ID, thesis["id"], 1, 10)["total"] == 2
    assert research.get(OWNER_USER_ID, "comparisons", comparison["id"]) == comparison
    assert not settings.database_path.with_suffix(".pre-restore.sqlite3").exists()


def test_legacy_v1_restore_rejects_staging_mutation_after_authentication(settings, monkeypatch):
    """Promotion stays bound to the authenticated database bytes, beyond row counts."""

    repository, manager = _manager(settings)
    research = ResearchStore(repository)
    now = datetime(2026, 10, 16, tzinfo=UTC)
    thesis = research.save_thesis(
        OWNER_USER_ID,
        {
            "symbol": "SPY",
            "asset_type": "etf",
            "title": "Authenticated thesis",
            "reasoning": "The original verified content",
            "risks": "Market risk",
            "invalidation": "The thesis changes",
            "evidence": [],
        },
        now,
    )
    comparison = research.save_comparison(
        OWNER_USER_ID,
        str(uuid4()),
        {"captured_at": now.isoformat(), "instruments": [{"symbol": "SPY"}]},
        now,
    )
    source = manager.create("stage-anchor-source.spbackup")
    _, snapshot, source_staging = manager.verify(source["name"])
    legacy_path = settings.backup_dir / "stage-anchor-legacy-v1.spbackup"
    try:
        _package_legacy_v1_schema_fourteen(manager, snapshot, legacy_path)
    finally:
        source_staging.cleanup()

    active_sha256 = manager._checksum(settings.database_path)
    active_counts = manager._counts(settings.database_path, format_version=2)
    active_thesis = research.get(OWNER_USER_ID, "theses", thesis["id"])
    active_comparison = research.get(OWNER_USER_ID, "comparisons", comparison["id"])
    mutation_evidence: dict[str, object] = {}
    original_verify = manager._verify_unlocked

    def mutate_after_authentication(name: str, *, require_active_schema: bool = True):
        manifest, staged_database, staging = original_verify(
            name, require_active_schema=require_active_schema
        )
        mutation_evidence["sha256_before"] = manager._checksum(staged_database)
        mutation_evidence["legacy_counts_before"] = manager._counts(
            staged_database, format_version=1
        )
        mutation_evidence["full_counts_before"] = manager._counts(staged_database, format_version=2)
        with sqlite3.connect(staged_database) as connection:
            row = connection.execute(
                "SELECT payload_json FROM research_theses WHERE id = ?", (thesis["id"],)
            ).fetchone()
            assert row is not None
            payload = json.loads(row[0])
            payload["reasoning"] = "Changed without changing any table row counts"
            connection.execute(
                "UPDATE research_theses SET payload_json = ? WHERE id = ?",
                (json.dumps(payload, separators=(",", ":")), thesis["id"]),
            )
        ResearchStore(Repository(staged_database)).save_thesis(
            OWNER_USER_ID,
            {
                "symbol": "QQQ",
                "asset_type": "etf",
                "title": "Injected staging row",
                "reasoning": "Added after the artifact was authenticated",
                "risks": "Concentration",
                "invalidation": "The assumptions change",
                "evidence": [],
            },
            now,
        )
        with sqlite3.connect(staged_database) as connection:
            checkpoint = connection.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
            assert checkpoint is not None and checkpoint[0] == 0
        mutation_evidence["sha256_after"] = manager._checksum(staged_database)
        mutation_evidence["legacy_counts_after"] = manager._counts(
            staged_database, format_version=1
        )
        mutation_evidence["full_counts_after"] = manager._counts(staged_database, format_version=2)
        mutation_evidence["manifest_sha256"] = manifest["database_sha256"]
        mutation_evidence["manifest_counts"] = manifest["counts"]
        return manifest, staged_database, staging

    monkeypatch.setattr(manager, "_verify_unlocked", mutate_after_authentication)
    with pytest.raises(BackupError, match="checksum"):
        manager.restore(legacy_path.name, promote=True)

    assert mutation_evidence["sha256_before"] == mutation_evidence["manifest_sha256"]
    assert mutation_evidence["sha256_after"] != mutation_evidence["manifest_sha256"]
    assert mutation_evidence["legacy_counts_before"] == mutation_evidence["legacy_counts_after"]
    assert mutation_evidence["legacy_counts_after"] == mutation_evidence["manifest_counts"]
    full_before = mutation_evidence["full_counts_before"]
    full_after = mutation_evidence["full_counts_after"]
    assert isinstance(full_before, dict) and isinstance(full_after, dict)
    assert full_after["research_theses"] == full_before["research_theses"] + 1
    assert manager._checksum(settings.database_path) == active_sha256
    assert manager._counts(settings.database_path, format_version=2) == active_counts
    assert research.get(OWNER_USER_ID, "theses", thesis["id"]) == active_thesis
    assert research.get(OWNER_USER_ID, "comparisons", comparison["id"]) == active_comparison
    assert not settings.database_path.with_suffix(".pre-restore.sqlite3").exists()


def test_restore_rejects_symlinked_artifact(settings):
    _, manager = _manager(settings)
    manager.create("real.spbackup")
    real = settings.backup_dir / "real.spbackup"
    alias = settings.backup_dir / "alias.spbackup"
    try:
        alias.symlink_to(settings.backup_dir / "real.spbackup")
    except OSError:
        pytest.skip("filesystem does not support symlinks")
    real.chmod(0o666)
    with pytest.raises(BackupError, match="regular managed"):
        manager.restore("alias.spbackup")
    # Refusing the alias must not chmod the attacker-selected target as a side effect.
    assert stat.S_IMODE(real.stat().st_mode) == 0o666


def test_backup_mutation_rejects_symlinked_coordination_file(settings):
    _, manager = _manager(settings)
    target = settings.data_dir / "unrelated.txt"
    target.write_text("untouched")
    target.chmod(0o666)
    lock_path = settings.data_dir / backup_module.TRUST_LOCK_NAME
    try:
        lock_path.symlink_to(target)
    except OSError:
        pytest.skip("filesystem does not support symlinks")

    with pytest.raises(BackupError, match="coordinated safely"):
        manager.create("must-not-exist.spbackup")

    assert target.read_text() == "untouched"
    assert stat.S_IMODE(target.stat().st_mode) == 0o666
    assert not (settings.backup_dir / "must-not-exist.spbackup").exists()


def test_cli_serve_passes_loopback_resource_and_timeout_bounds(monkeypatch):
    from stock_probs import api as application_api

    captured = {}
    monkeypatch.setattr(application_api, "create_app", lambda _settings: object())
    _install_fake_uvicorn(monkeypatch, lambda app, **kwargs: captured.update(kwargs))
    monkeypatch.setattr(sys, "argv", ["stock-probs", "serve", "--host", "127.0.0.1"])

    cli.main()

    assert captured == {
        "host": "127.0.0.1",
        "port": 8000,
        "workers": 1,
        "proxy_headers": False,
        "limit_concurrency": 32,
        "backlog": 64,
        "timeout_keep_alive": 5,
        "timeout_graceful_shutdown": 10,
    }


def test_cli_rejects_invalid_port_before_start(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["stock-probs", "serve", "--port", "0"])
    _install_fake_uvicorn(monkeypatch, lambda *args, **kwargs: pytest.fail("must not bind"))
    with pytest.raises(SystemExit) as failure:
        cli.main()
    assert failure.value.code == 2


def test_cli_requires_explicit_acknowledgement_for_broader_bind(monkeypatch):
    """The security-sensitive flag is observable and never implied by an environment default."""
    from stock_probs import api as application_api

    captured = {}
    monkeypatch.setattr(application_api, "create_app", lambda _settings: object())
    _install_fake_uvicorn(monkeypatch, lambda app, **kwargs: captured.update(kwargs))
    monkeypatch.setattr(
        sys,
        "argv",
        ["stock-probs", "serve", "--host", "0.0.0.0", "--allow-non-loopback"],  # noqa: S104
    )

    cli.main()

    assert captured["host"] == "0.0.0.0"  # noqa: S104
