"""M05 developer tests target manifest strictness, rollback safety, and CLI bounds."""

from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import stat
import sys
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import pytest

import stock_probs.backup as backup_module
import stock_probs.cli as cli
from stock_probs.backup import BackupError, BackupManager
from stock_probs.repository import Repository


def _manager(settings) -> tuple[Repository, BackupManager]:
    """Create the migrated operation boundary without involving provider or presentation code."""

    repository = Repository(settings.database_path)
    repository.migrate()
    return repository, BackupManager(repository, settings.backup_dir)


def _record_failure(repository: Repository, request_id: str) -> None:
    """Use the persistence boundary so fixtures remain valid as schema constraints tighten."""

    now = datetime(2025, 1, 1, tzinfo=UTC)
    repository.record_failure(
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


def test_manifest_records_database_schema_checksum_counts_and_timezone(settings):
    repository, manager = _manager(settings)
    _record_failure(repository, "backup-event")

    created = manager.create("manifest.spbackup")
    manifest, _, staging = manager.verify("manifest.spbackup")
    try:
        assert created["sha256"] == hashlib.sha256(
            (settings.backup_dir / "manifest.spbackup").read_bytes()
        ).hexdigest()
        assert len(manifest["database_sha256"]) == len(manifest["schema_sha256"]) == 64
        assert manifest["counts"]["search_events"] == 1
        assert manifest["created_at"].endswith("+00:00")
    finally:
        staging.cleanup()


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
    assert destination_repository.history()["items"][0]["request_id"] == (
        "cross-installation-event"
    )

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
    assert repository.history()["total"] == 1


def test_backup_count_and_disk_limits_refuse_creation_without_expiring_history(
    settings, monkeypatch
):
    repository, manager = _manager(settings)
    _record_failure(repository, "retained-event")
    monkeypatch.setattr(backup_module, "MAX_MANAGED_BACKUPS", 1)
    manager.create("first.spbackup")

    with pytest.raises(BackupError, match="retention limit"):
        manager.create("count-refused.spbackup")
    assert repository.history()["total"] == 1
    assert not (settings.backup_dir / "count-refused.spbackup").exists()

    monkeypatch.setattr(backup_module, "MAX_MANAGED_BACKUPS", 32)
    monkeypatch.setattr(
        backup_module,
        "MAX_BACKUP_STORAGE_BYTES",
        (settings.backup_dir / "first.spbackup").stat().st_size,
    )
    with pytest.raises(BackupError, match="storage limit"):
        manager.create("disk-refused.spbackup")
    assert repository.history()["total"] == 1
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


def test_operations_harden_existing_runtime_storage_and_sensitive_files(
    settings, monkeypatch
):
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

    def fail_only_after_swap(path: Path) -> dict[str, int]:
        counts = original_counts(path)
        rollback = settings.database_path.with_suffix(".pre-restore.sqlite3")
        if path == settings.database_path and rollback.exists():
            counts["search_events"] += 1
        return counts

    monkeypatch.setattr(manager, "_counts", fail_only_after_swap)
    with pytest.raises(BackupError, match="representative-count"):
        manager.restore("before-later-data.spbackup", promote=True)

    assert repository.representative_counts()["search_events"] == 2
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


def test_cli_serve_passes_loopback_resource_and_timeout_bounds(monkeypatch):
    captured = {}
    monkeypatch.setattr(cli, "create_app", lambda: object())
    monkeypatch.setattr(cli.uvicorn, "run", lambda app, **kwargs: captured.update(kwargs))
    monkeypatch.setattr(sys, "argv", ["stock-probs", "serve", "--host", "127.0.0.1"])

    cli.main()

    assert captured == {
        "host": "127.0.0.1",
        "port": 8000,
        "workers": 1,
        "limit_concurrency": 32,
        "backlog": 64,
        "timeout_keep_alive": 5,
        "timeout_graceful_shutdown": 10,
    }


def test_cli_rejects_invalid_port_before_start(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["stock-probs", "serve", "--port", "0"])
    monkeypatch.setattr(cli.uvicorn, "run", lambda *args, **kwargs: pytest.fail("must not bind"))
    with pytest.raises(SystemExit) as failure:
        cli.main()
    assert failure.value.code == 2


def test_cli_requires_explicit_acknowledgement_for_broader_bind(monkeypatch):
    """The security-sensitive flag is observable and never implied by an environment default."""

    captured = {}
    monkeypatch.setattr(cli, "create_app", lambda: object())
    monkeypatch.setattr(cli.uvicorn, "run", lambda app, **kwargs: captured.update(kwargs))
    monkeypatch.setattr(
        sys,
        "argv",
        ["stock-probs", "serve", "--host", "0.0.0.0", "--allow-non-loopback"],  # noqa: S104
    )

    cli.main()

    assert captured["host"] == "0.0.0.0"  # noqa: S104
