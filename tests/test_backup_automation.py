"""M05 developer checks cover automatic triggers and trust-key lifecycle failures."""

from __future__ import annotations

import asyncio
import json
import sqlite3
import sys
import threading
import time
from datetime import UTC, datetime, timedelta
from importlib.resources import files

import pytest

import stock_probs.backup as backup_module
import stock_probs.cli as cli
from stock_probs.backup import BackupError, BackupManager
from stock_probs.config import Settings
from stock_probs.repository import SCHEMA_VERSION, Repository


def _record_failure(repository: Repository, request_id: str) -> None:
    now = datetime(2025, 1, 1, tzinfo=UTC)
    repository.record_failure(
        request_id=request_id,
        submitted_symbol="FAIL",
        normalized_symbol="FAIL",
        asset_type="stock",
        error_code="fixture_failure",
        error_message="retained automation fixture",
        submitted_at=now,
        completed_at=now,
    )


def _version_one_database(settings: Settings) -> None:
    script = files("stock_probs.migrations").joinpath("001_initial.sql").read_text()
    with sqlite3.connect(settings.database_path) as connection:
        connection.executescript(script)
        connection.execute(
            "INSERT INTO schema_migrations(version, applied_at) VALUES (1, ?)",
            (datetime(2025, 1, 1, tzinfo=UTC).isoformat(),),
        )
        connection.execute(
            "INSERT INTO search_events "
            "(request_id, submitted_symbol, normalized_symbol, asset_type, status, error_code, "
            "error_message, submitted_at, completed_at) "
            "VALUES ('before-upgrade', 'FAIL', 'FAIL', 'stock', 'failed', 'fixture', "
            "'retained', ?, ?)",
            (datetime(2025, 1, 1, tzinfo=UTC).isoformat(),) * 2,
        )


def _cli_environment(monkeypatch: pytest.MonkeyPatch, settings: Settings) -> None:
    monkeypatch.setenv("STOCK_PROBS_DATA_DIR", str(settings.data_dir))
    monkeypatch.setenv("STOCK_PROBS_PROVIDER", "fixture")


def test_migrate_cli_creates_and_reports_verified_pre_migration_backup(
    settings, monkeypatch, capsys
):
    _version_one_database(settings)
    _cli_environment(monkeypatch, settings)
    monkeypatch.setattr(sys, "argv", ["stock-probs", "migrate"])

    cli.main()

    response = json.loads(capsys.readouterr().out)
    receipt = response["pre_migration_backup"]
    assert response["status"] == "migrated"
    assert receipt["trigger"] == "pre_migration" and receipt["verified"] is True
    assert receipt["schema_version"] == 1
    repository = Repository(settings.database_path)
    with repository.connect() as connection:
        assert connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0] == (
            SCHEMA_VERSION
        )
    manager = BackupManager(repository, settings.backup_dir)
    manifest, database, staging = manager._verify_unlocked(
        receipt["name"], require_active_schema=False
    )
    try:
        assert manifest["schema_version"] == 1
        with sqlite3.connect(database) as connection:
            assert connection.execute("SELECT request_id FROM search_events").fetchone()[0] == (
                "before-upgrade"
            )
    finally:
        staging.cleanup()


def test_failed_pre_migration_backup_blocks_every_pending_migration(
    settings, monkeypatch, capsys
):
    _version_one_database(settings)
    _cli_environment(monkeypatch, settings)
    monkeypatch.setattr(sys, "argv", ["stock-probs", "migrate"])

    def fail_backup(*args, **kwargs):
        raise BackupError("intentional pre-migration failure")

    monkeypatch.setattr(BackupManager, "create", fail_backup)
    with pytest.raises(SystemExit) as failure:
        cli.main()

    assert failure.value.code == 2
    assert "intentional pre-migration failure" in capsys.readouterr().err
    with sqlite3.connect(settings.database_path) as connection:
        assert connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0] == 1


@pytest.mark.parametrize(
    ("arguments", "method_name"),
    [
        (["backup"], "create"),
        (["restore", "source.spbackup"], "restore"),
        (["backup-key", "rotate"], "rotate_key"),
        (["backup-key", "retire"], "retire_key"),
    ],
)
def test_every_operational_cli_command_protects_pending_migration(
    settings, monkeypatch, arguments, method_name
):
    _version_one_database(settings)
    _cli_environment(monkeypatch, settings)
    original = cli._migration_operations
    receipts = []
    operations = []

    def protected_operations(configured):
        manager, receipt = original(configured)
        receipts.append(receipt)

        def command(*args, **kwargs):
            operations.append(method_name)
            return {"status": "completed"}

        monkeypatch.setattr(manager, method_name, command)
        return manager, receipt

    monkeypatch.setattr(cli, "_migration_operations", protected_operations)
    monkeypatch.setattr(sys, "argv", ["stock-probs", *arguments])

    cli.main()

    assert operations == [method_name]
    assert len(receipts) == 1
    receipt = receipts[0]
    assert receipt["trigger"] == "pre_migration" and receipt["verified"] is True
    assert receipt["schema_version"] == 1
    assert (settings.backup_dir / receipt["name"]).is_file()
    with sqlite3.connect(settings.database_path) as connection:
        assert connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0] == (
            SCHEMA_VERSION
        )


def test_due_backup_creates_only_when_due_and_never_expires_query_history(
    settings, monkeypatch
):
    repository = Repository(settings.database_path)
    repository.migrate()
    _record_failure(repository, "retained-due-event")
    manager = BackupManager(repository, settings.backup_dir)
    now = datetime.now(UTC)

    class OldDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return now - timedelta(seconds=61)

    monkeypatch.setattr(backup_module, "datetime", OldDatetime)
    manager.create("old.spbackup")
    monkeypatch.setattr(backup_module, "datetime", datetime)
    created = manager.create_if_due(60, now=now)
    assert created["status"] == "created"
    assert repository.history()["total"] == 1

    not_due = manager.create_if_due(60, now=datetime.now(UTC))
    assert not_due["status"] == "not_due"
    assert not_due["newest_backup"] == created["backup"]["name"]

    def fail_due(*args, **kwargs):
        raise BackupError("intentional due-backup failure")

    monkeypatch.setattr(manager, "create", fail_due)
    with pytest.raises(BackupError, match="intentional due-backup failure"):
        manager.create_if_due(60, now=datetime.now(UTC) + timedelta(seconds=61))
    assert repository.history()["items"][0]["request_id"] == "retained-due-event"


def test_due_check_manifest_delay_times_out_before_creating_an_artifact(
    settings, monkeypatch
):
    repository = Repository(settings.database_path)
    repository.migrate()
    _record_failure(repository, "retained-timeout-event")
    manager = BackupManager(repository, settings.backup_dir)
    manager.create("existing.spbackup")
    original_manifest = manager._authenticated_manifest
    entered = threading.Event()
    release = threading.Event()
    completed = threading.Event()

    def delayed_manifest(name):
        entered.set()
        try:
            release.wait()
            return original_manifest(name)
        finally:
            completed.set()

    monkeypatch.setattr(backup_module, "BACKUP_TIMEOUT_SECONDS", 0.5)
    monkeypatch.setattr(manager, "_authenticated_manifest", delayed_manifest)
    try:
        with pytest.raises(BackupError, match="wall-clock time limit"):
            manager.create_if_due(0, now=datetime.now(UTC))
        assert entered.is_set()
        assert not completed.is_set()
        assert [path.name for path in settings.backup_dir.glob("*.spbackup")] == [
            "existing.spbackup"
        ]
    finally:
        release.set()

    assert completed.wait(timeout=1)
    assert repository.history()["items"][0]["request_id"] == "retained-timeout-event"
    assert [path.name for path in settings.backup_dir.iterdir()] == ["existing.spbackup"]


def test_direct_create_delay_times_out_without_artifact_or_staging(settings, monkeypatch):
    repository = Repository(settings.database_path)
    repository.migrate()
    _record_failure(repository, "retained-create-timeout-event")
    manager = BackupManager(repository, settings.backup_dir)

    def delayed_snapshot(snapshot):
        time.sleep(0.05)

    monkeypatch.setattr(backup_module, "BACKUP_TIMEOUT_SECONDS", 0.001)
    monkeypatch.setattr(manager, "_online_snapshot", delayed_snapshot)
    started = time.monotonic()
    with pytest.raises(BackupError, match="wall-clock time limit"):
        manager.create("must-not-publish.spbackup")
    elapsed = time.monotonic() - started

    assert elapsed < 0.04
    assert not list(settings.backup_dir.glob("*.spbackup"))
    assert repository.history()["items"][0]["request_id"] == (
        "retained-create-timeout-event"
    )
    assert not list(settings.backup_dir.iterdir())


@pytest.mark.parametrize("operation", ["verify", "restore"])
def test_public_verification_paths_timeout_and_clean_staging(
    settings, monkeypatch, operation
):
    repository = Repository(settings.database_path)
    repository.migrate()
    _record_failure(repository, f"retained-{operation}-timeout-event")
    manager = BackupManager(repository, settings.backup_dir)
    manager.create("timeout-source.spbackup")
    original_verify = manager._verify_unlocked
    completed = threading.Event()

    def delayed_verify(*args, **kwargs):
        try:
            time.sleep(0.05)
            return original_verify(*args, **kwargs)
        finally:
            completed.set()

    monkeypatch.setattr(backup_module, "BACKUP_TIMEOUT_SECONDS", 0.001)
    monkeypatch.setattr(manager, "_verify_unlocked", delayed_verify)
    started = time.monotonic()
    with pytest.raises(BackupError, match="wall-clock time limit"):
        getattr(manager, operation)("timeout-source.spbackup")
    elapsed = time.monotonic() - started

    assert elapsed < 0.04
    assert completed.wait(timeout=0.2)
    assert repository.history()["items"][0]["request_id"] == (
        f"retained-{operation}-timeout-event"
    )
    assert [path.name for path in settings.backup_dir.iterdir()] == [
        "timeout-source.spbackup"
    ]


def test_public_verify_and_non_promoting_restore_complete_normally(settings):
    repository = Repository(settings.database_path)
    repository.migrate()
    _record_failure(repository, "retained-normal-verification-event")
    manager = BackupManager(repository, settings.backup_dir)
    created = manager.create("normal-verification.spbackup")

    manifest, _, staging = manager.verify(created["name"])
    staging.cleanup()
    restored = manager.restore(created["name"])

    assert manifest["counts"]["search_events"] == 1
    assert restored["verified"] is True and restored["promoted"] is False
    assert repository.history()["items"][0]["request_id"] == (
        "retained-normal-verification-event"
    )
    assert [path.name for path in settings.backup_dir.iterdir()] == [
        "normal-verification.spbackup"
    ]


def test_pre_migration_verification_delay_never_publishes_or_migrates(
    settings, monkeypatch
):
    _version_one_database(settings)
    original_verify = BackupManager._verify_unlocked
    completed = threading.Event()

    def delayed_verify(self, *args, **kwargs):
        try:
            time.sleep(0.1)
            return original_verify(self, *args, **kwargs)
        finally:
            completed.set()

    monkeypatch.setattr(backup_module, "BACKUP_TIMEOUT_SECONDS", 0.02)
    monkeypatch.setattr(BackupManager, "_verify_unlocked", delayed_verify)
    started = time.monotonic()
    with pytest.raises(BackupError, match="wall-clock time limit"):
        cli._migration_operations(settings)
    elapsed = time.monotonic() - started

    assert elapsed < 0.06
    assert not list(settings.backup_dir.glob("*.spbackup"))
    assert completed.wait(timeout=0.2)
    with sqlite3.connect(settings.database_path) as connection:
        assert connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0] == 1
        assert connection.execute("SELECT request_id FROM search_events").fetchone()[0] == (
            "before-upgrade"
        )
    assert not list(settings.backup_dir.iterdir())


def test_serve_lifespan_runs_observable_due_check_and_surfaces_failure(
    settings, monkeypatch, capsys
):
    called = []

    async def application(scope, receive, send):
        called.append(scope["type"])

    class Manager:
        def create_if_due(self, interval):
            return {"trigger": "due", "status": "created", "interval_seconds": interval}

    monkeypatch.setattr(cli, "create_app", lambda: application)
    monkeypatch.setattr(cli, "_migration_operations", lambda configured: (Manager(), None))
    wrapped = cli._serve_app(settings)

    async def receive():
        return {"type": "lifespan.startup"}

    async def send(message):
        return None

    asyncio.run(wrapped({"type": "lifespan"}, receive, send))
    assert called == ["lifespan"]
    assert json.loads(capsys.readouterr().out)["due_backup"]["status"] == "created"

    class FailingManager:
        def create_if_due(self, interval):
            raise BackupError("startup backup failed")

    monkeypatch.setattr(cli, "_migration_operations", lambda configured: (FailingManager(), None))
    with pytest.raises(BackupError, match="startup backup failed"):
        asyncio.run(cli._serve_app(settings)({"type": "lifespan"}, receive, send))
    assert "startup backup failed" in capsys.readouterr().err


def test_serve_lifespan_watchdog_bounds_a_non_cooperative_due_check(
    settings, monkeypatch, capsys
):
    called = []
    completed = threading.Event()

    async def application(scope, receive, send):
        called.append(scope["type"])

    class SlowManager:
        def create_if_due(self, interval):
            try:
                time.sleep(0.05)
                return {"trigger": "due", "status": "created"}
            finally:
                completed.set()

    async def receive():
        return {"type": "lifespan.startup"}

    async def send(message):
        return None

    monkeypatch.setattr(backup_module, "BACKUP_TIMEOUT_SECONDS", 0.001)
    monkeypatch.setattr(cli, "create_app", lambda: application)
    monkeypatch.setattr(cli, "_migration_operations", lambda configured: (SlowManager(), None))
    started = time.monotonic()
    with pytest.raises(BackupError, match="wall-clock time limit"):
        asyncio.run(cli._serve_app(settings)({"type": "lifespan"}, receive, send))
    elapsed = time.monotonic() - started

    assert elapsed < 0.04
    assert completed.wait(timeout=0.2)
    assert called == []
    assert "wall-clock time limit" in capsys.readouterr().err


def test_backup_key_rotate_command_resigns_all_verified_artifacts(
    settings, monkeypatch, capsys
):
    repository = Repository(settings.database_path)
    repository.migrate()
    _record_failure(repository, "retained-rotation-event")
    manager = BackupManager(repository, settings.backup_dir)
    names = [manager.create(f"rotate-{index}.spbackup")["name"] for index in range(2)]
    old_key = manager.trust_key_path.read_bytes()
    _cli_environment(monkeypatch, settings)
    monkeypatch.setattr(sys, "argv", ["stock-probs", "backup-key", "rotate"])

    cli.main()

    response = json.loads(capsys.readouterr().out)
    new_key = manager.trust_key_path.read_bytes()
    assert response == {"status": "rotated", "artifacts_resigned": 2}
    assert new_key != old_key
    for name in names:
        _, _, staging = manager.verify(name)
        staging.cleanup()
    manager.trust_key_path.write_bytes(old_key)
    with pytest.raises(BackupError, match="authenticity"):
        manager.verify(names[0])
    manager.trust_key_path.write_bytes(new_key)
    assert repository.history()["items"][0]["request_id"] == "retained-rotation-event"


def test_rotation_and_retirement_fail_closed_then_retirement_succeeds(
    settings, monkeypatch, capsys
):
    repository = Repository(settings.database_path)
    repository.migrate()
    _record_failure(repository, "retained-key-event")
    manager = BackupManager(repository, settings.backup_dir)
    first = manager.create("first-key.spbackup")["name"]
    second = manager.create("second-key.spbackup")["name"]
    key_before = manager.trust_key_path.read_bytes()
    first_before = (settings.backup_dir / first).read_bytes()
    with (settings.backup_dir / second).open("ab") as artifact:
        artifact.write(b"tampered")
    _cli_environment(monkeypatch, settings)

    monkeypatch.setattr(sys, "argv", ["stock-probs", "backup-key", "rotate"])
    with pytest.raises(SystemExit) as rotation_failure:
        cli.main()
    assert rotation_failure.value.code == 2
    assert manager.trust_key_path.read_bytes() == key_before
    assert (settings.backup_dir / first).read_bytes() == first_before

    monkeypatch.setattr(sys, "argv", ["stock-probs", "backup-key", "retire"])
    with pytest.raises(SystemExit) as retirement_failure:
        cli.main()
    assert retirement_failure.value.code == 2
    assert "managed backups remain; transfer or remove them explicitly" in capsys.readouterr().err
    assert repository.history()["items"][0]["request_id"] == "retained-key-event"

    for name in (first, second):
        (settings.backup_dir / name).unlink()
    cli.main()
    assert json.loads(capsys.readouterr().out) == {
        "status": "retired",
        "artifacts_remaining": 0,
    }
    assert not manager.trust_key_path.exists()


def test_backup_interval_validation_and_help_document_transfer(monkeypatch, capsys):
    monkeypatch.setenv("STOCK_PROBS_BACKUP_INTERVAL_SECONDS", "3600")
    assert Settings.from_env().backup_interval_seconds == 3600
    monkeypatch.setenv("STOCK_PROBS_BACKUP_INTERVAL_SECONDS", "0")
    with pytest.raises(ValueError, match="BACKUP_INTERVAL"):
        Settings.from_env()

    for arguments in (["--help"], ["backup-key", "--help"]):
        monkeypatch.setattr(sys, "argv", ["stock-probs", *arguments])
        with pytest.raises(SystemExit) as help_exit:
            cli.main()
        help_text = capsys.readouterr().out
        assert help_exit.value.code == 0
        assert all(
            term in help_text for term in (".backup-auth.key", "protected", "0600", "verify")
        )
