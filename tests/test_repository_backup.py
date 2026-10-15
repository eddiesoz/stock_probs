"""M02/M05 tests prove migration, immutability, concurrency, and safe restore behavior."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import zipfile
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from importlib.resources import files
from uuid import uuid4

import pytest

import stock_probs.repository as repository_module
from stock_probs.backup import BackupError, BackupManager
from stock_probs.domain import DomainError, calculate_forecasts
from stock_probs.history_export import (
    build_owner_history_export,
    serialize_owner_history_csv,
    serialize_owner_history_json,
)
from stock_probs.monitoring_store import MonitoringStore
from stock_probs.notification_address_store import (
    NotificationAddressStore,
    NotificationAddressUnavailable,
)
from stock_probs.provider import FixtureProvider
from stock_probs.repository import SCHEMA_VERSION, Repository, RepositoryError
from stock_probs.service import ForecastService

NOW = datetime(2025, 1, 10, 17, 3, tzinfo=UTC)
OWNER_USER_ID = 1


def _service(settings):
    """Construct the storage/service pair used by non-HTTP persistence tests."""

    repository = Repository(settings.database_path)
    repository.migrate()
    return repository, ForecastService(repository, FixtureProvider(), lambda: NOW)


def test_clean_migration_is_idempotent_and_records_version(settings):
    repository = Repository(settings.database_path)
    repository.migrate()
    repository.migrate()

    with repository.connect() as connection:
        versions = connection.execute("SELECT version FROM schema_migrations").fetchall()
    assert [row[0] for row in versions] == list(range(1, SCHEMA_VERSION + 1))


def test_upgrade_from_shipped_initial_schema_matches_clean_schema(settings, tmp_path):
    """The new numbered migration upgrades an actual v1 layout without rewriting 001."""

    upgraded_path = settings.database_path
    initial_sql = files("stock_probs.migrations").joinpath("001_initial.sql").read_text()
    with sqlite3.connect(upgraded_path) as connection:
        # The shipped v1 runner created this receipt table before executing migration 001.
        connection.execute(
            "CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
        )
        connection.executescript(initial_sql)
        connection.execute(
            "INSERT INTO schema_migrations(version, applied_at) VALUES (1, ?)",
            (NOW.isoformat(),),
        )
    upgraded = Repository(upgraded_path)
    upgrade_backups = []
    upgraded.migrate(before_migration=upgrade_backups.append)

    clean = Repository(tmp_path / "clean.sqlite3")
    clean_backups = []
    clean.migrate(before_migration=clean_backups.append)

    def schema(repository):
        with repository.connect() as connection:
            return connection.execute(
                "SELECT type, name, tbl_name, sql FROM sqlite_master "
                "WHERE name NOT LIKE 'sqlite_%' ORDER BY type, name"
            ).fetchall()

    assert [tuple(row) for row in schema(upgraded)] == [tuple(row) for row in schema(clean)]
    assert upgraded.representative_counts() == clean.representative_counts()
    assert upgrade_backups == [1]
    assert clean_backups == []


def test_upgrade_from_v2_preserves_legacy_failed_analysis_and_is_idempotent(settings):
    """Migration 003 constrains future inserts without rewriting valid append-only v2 rows."""

    initial_sql = files("stock_probs.migrations").joinpath("001_initial.sql").read_text()
    historical_sql = (
        files("stock_probs.migrations").joinpath("002_historical_analysis.sql").read_text()
    )
    with sqlite3.connect(settings.database_path) as connection:
        connection.execute(
            "CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
        )
        connection.executescript(initial_sql)
        connection.execute(
            "INSERT INTO schema_migrations(version, applied_at) VALUES (1, ?)",
            (NOW.isoformat(),),
        )
        connection.executescript(historical_sql)
        connection.execute(
            "INSERT INTO schema_migrations(version, applied_at) VALUES (2, ?)",
            (NOW.isoformat(),),
        )
        # Version 2 allowed failed attempts before requested-source context was introduced.
        connection.execute(
            "INSERT INTO search_events "
            "(request_id, submitted_symbol, asset_type, status, error_code, error_message, "
            "submitted_at, completed_at, analysis_kind) "
            "VALUES ('legacy-failure', 'ACDC', 'stock', 'failed', 'legacy', 'legacy', ?, ?, "
            "'fresh_historical_reconstruction')",
            (NOW.isoformat(), NOW.isoformat()),
        )

    repository = Repository(settings.database_path)
    repository.migrate()
    repository.migrate()

    with repository.connect() as connection:
        legacy = connection.execute(
            "SELECT source_event_id, requested_cutoff, requested_source_event_id "
            "FROM search_events WHERE request_id = 'legacy-failure'"
        ).fetchone()
        versions = connection.execute(
            "SELECT version FROM schema_migrations ORDER BY version"
        ).fetchall()
    assert tuple(legacy) == (None, None, None)
    assert [row[0] for row in versions] == list(range(1, SCHEMA_VERSION + 1))


def test_migration_rejects_unknown_or_noncontiguous_history(settings):
    """A newer/partial database fails closed instead of being silently treated as current."""

    with sqlite3.connect(settings.database_path) as connection:
        connection.execute(
            "CREATE TABLE schema_migrations(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
        )
        connection.execute(
            "INSERT INTO schema_migrations(version, applied_at) VALUES (3, ?)",
            (NOW.isoformat(),),
        )

    with pytest.raises(sqlite3.DatabaseError, match="non-contiguous or newer"):
        Repository(settings.database_path).migrate()


def test_migration_rejects_changed_shipped_sql_before_database_work(settings, monkeypatch):
    """Checksum mismatch forces a new migration rather than accepting edited history."""

    monkeypatch.setitem(repository_module.MIGRATION_SHA256, 2, "0" * 64)

    with pytest.raises(sqlite3.DatabaseError, match="immutable checksum"):
        Repository(settings.database_path).migrate()
    assert not settings.database_path.exists()


def test_migration_016_is_checksum_pinned_before_database_work(settings, monkeypatch):
    """The newly registered monitoring DDL must match its reviewed immutable pin."""

    migration = files("stock_probs.migrations").joinpath("016_monitoring_and_report_cards.sql")
    expected = hashlib.sha256(migration.read_bytes()).hexdigest()
    assert repository_module.MIGRATION_SHA256[16] == expected
    monkeypatch.setitem(repository_module.MIGRATION_SHA256, 16, "0" * 64)

    with pytest.raises(sqlite3.DatabaseError, match="immutable checksum"):
        Repository(settings.database_path).migrate()
    assert not settings.database_path.exists()


def test_migration_018_is_checksum_pinned_before_database_work(settings, monkeypatch):
    migration = files("stock_probs.migrations").joinpath("018_notification_address_delivery.sql")
    expected = "c152435ddf599a0715478e5863e5a2d2cd14b72fde5eca8d9a73900ff4981a63"
    assert hashlib.sha256(migration.read_bytes()).hexdigest() == expected
    assert repository_module.MIGRATION_SHA256[18] == expected
    monkeypatch.setitem(repository_module.MIGRATION_SHA256, 18, "0" * 64)

    with pytest.raises(sqlite3.DatabaseError, match="immutable checksum"):
        Repository(settings.database_path).migrate()
    assert not settings.database_path.exists()


def test_concurrent_clean_migration_is_serialized_across_repository_instances(settings):
    """BEGIN IMMEDIATE makes startup safe even when two processes race before version 1."""

    repositories = [Repository(settings.database_path) for _ in range(4)]
    with ThreadPoolExecutor(max_workers=4) as workers:
        list(workers.map(lambda repository: repository.migrate(), repositories))

    with repositories[0].connect() as connection:
        versions = connection.execute(
            "SELECT version FROM schema_migrations ORDER BY version"
        ).fetchall()
    assert [row[0] for row in versions] == list(range(1, SCHEMA_VERSION + 1))


def test_database_triggers_reject_mutation_and_deletion(settings):
    repository, service = _service(settings)
    created = service.search("ACDC", "stock", owner_user_id=OWNER_USER_ID)
    outcome = service.append_outcome(
        created["results"][0]["id"],
        24.0,
        datetime(2025, 1, 13, 21, 1, tzinfo=UTC),
        "observed",
        "mutation target",
        owner_user_id=OWNER_USER_ID,
    )
    assert outcome is not None

    with repository.connect() as connection:
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            connection.execute(
                "UPDATE forecast_inputs SET snapshot_json = '{}' WHERE id = ?",
                (created["input"]["id"],),
            )
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            connection.execute("DELETE FROM search_events")
        ids = {
            "search_events": created["event"]["id"],
            "forecast_runs": created["event"]["run_id"],
            "forecast_inputs": created["input"]["id"],
            "forecast_results": created["results"][0]["id"],
            "outcomes": outcome["id"],
        }
        for table, row_id in ids.items():
            with pytest.raises(sqlite3.IntegrityError, match="immutable|append-only"):
                connection.execute(
                    f"UPDATE {table} SET id = id WHERE id = ?",  # noqa: S608
                    (row_id,),
                )
            with pytest.raises(sqlite3.IntegrityError, match="immutable|append-only"):
                connection.execute(f"DELETE FROM {table} WHERE id = ?", (row_id,))  # noqa: S608
            # Recursive triggers turn REPLACE's hidden delete into the same hard failure.
            with pytest.raises(sqlite3.IntegrityError, match="immutable|append-only"):
                connection.execute(
                    f"INSERT OR REPLACE INTO {table} "  # noqa: S608
                    f"SELECT * FROM {table} WHERE id = ?",  # noqa: S608
                    (row_id,),
                )
        with pytest.raises(sqlite3.IntegrityError, match="schema_migrations are append-only"):
            connection.execute("UPDATE schema_migrations SET applied_at = 'rewritten'")
        with pytest.raises(sqlite3.IntegrityError, match="schema_migrations are append-only"):
            connection.execute("DELETE FROM schema_migrations WHERE version = 1")


def test_raw_default_connection_rejects_primary_and_natural_key_replace(settings):
    """Migration 003 must not depend on a caller enabling recursive DELETE triggers."""

    repository, service = _service(settings)
    created = service.search("ACDC", "stock", owner_user_id=OWNER_USER_ID)
    outcome = service.append_outcome(
        created["results"][0]["id"],
        24.0,
        datetime(2025, 1, 13, 21, 1, tzinfo=UTC),
        "observed",
        "raw replace target",
        owner_user_id=OWNER_USER_ID,
    )
    assert outcome is not None
    ids = {
        "search_events": created["event"]["id"],
        "forecast_runs": created["event"]["run_id"],
        "forecast_inputs": created["input"]["id"],
        "forecast_results": created["results"][0]["id"],
        "outcomes": outcome["id"],
    }
    before = repository.representative_counts()

    with sqlite3.connect(settings.database_path) as raw:
        assert raw.execute("PRAGMA recursive_triggers").fetchone()[0] == 0
        for table, row_id in ids.items():
            with pytest.raises(sqlite3.IntegrityError, match="immutable|append-only"):
                raw.execute(
                    f"INSERT OR REPLACE INTO {table} "  # noqa: S608
                    f"SELECT * FROM {table} WHERE id = ?",  # noqa: S608
                    (row_id,),
                )

        # Omitting id forces REPLACE to conflict through each declared natural key instead.
        for table, row_id in {
            key: value for key, value in ids.items() if key != "outcomes"
        }.items():
            columns = [
                str(row[1])
                for row in raw.execute(f"PRAGMA table_info({table})").fetchall()  # noqa: S608
                if row[1] != "id"
            ]
            names = ", ".join(columns)
            with pytest.raises(sqlite3.IntegrityError, match="immutable|append-only"):
                raw.execute(
                    f"INSERT OR REPLACE INTO {table} ({names}) "  # noqa: S608
                    f"SELECT {names} FROM {table} WHERE id = ?",  # noqa: S608
                    (row_id,),
                )

    assert repository.representative_counts() == before


def test_database_rejects_null_fresh_failure_cutoff_and_requested_source(settings):
    """Failed fresh analyses retain both attempted cutoff and requested-source context."""

    repository, service = _service(settings)
    source = service.search("ACDC", "stock", owner_user_id=OWNER_USER_ID)["event"]["id"]
    columns = (
        "request_id, submitted_symbol, normalized_symbol, asset_type, status, is_repeat, "
        "error_code, error_message, submitted_at, completed_at, analysis_kind, "
        "source_event_id, requested_cutoff, requested_source_event_id"
    )
    values = (
        "?, 'ACDC', 'ACDC', 'stock', 'failed', 0, 'failed', 'failed', ?, ?, "
        "'fresh_historical_reconstruction', ?, ?, ?"
    )

    with sqlite3.connect(settings.database_path) as raw:
        raw.execute("PRAGMA foreign_keys = ON")
        for request_id, cutoff, requested_source in (
            ("null-cutoff", None, source),
            ("null-requested-source", NOW.isoformat(), None),
        ):
            with pytest.raises(sqlite3.IntegrityError, match="analysis contract"):
                raw.execute(
                    f"INSERT INTO search_events ({columns}) VALUES ({values})",  # noqa: S608
                    (
                        request_id,
                        NOW.isoformat(),
                        NOW.isoformat(),
                        source,
                        cutoff,
                        requested_source,
                    ),
                )

    assert repository.history(owner_user_id=OWNER_USER_ID)["total"] == 1


def test_concurrent_repeats_each_append_one_event(settings):
    repository, service = _service(settings)
    with ThreadPoolExecutor(max_workers=4) as workers:
        results = list(
            workers.map(
                lambda _: service.search("SPY", "etf", owner_user_id=OWNER_USER_ID),
                range(8),
            )
        )

    assert len({item["event"]["id"] for item in results}) == 8
    assert repository.representative_counts()["search_events"] == 8
    assert repository.representative_counts()["forecast_runs"] == 1


def test_success_repeat_failure_matrix_appends_exactly_one_event_each(settings):
    repository, service = _service(settings)

    first = service.search("ACDC", "stock", owner_user_id=OWNER_USER_ID)
    repeat = service.search("ACDC", "stock", owner_user_id=OWNER_USER_ID)
    with pytest.raises(DomainError) as failure:
        service.search("FAIL", "stock", owner_user_id=OWNER_USER_ID)

    assert first["event"]["status"] == "successful"
    assert repeat["event"]["status"] == "repeated"
    assert failure.value.request_id
    assert repository.history(owner_user_id=OWNER_USER_ID)["total"] == 3
    assert repository.representative_counts() == {
        "search_events": 3,
        "forecast_runs": 1,
        "forecast_inputs": 1,
        "forecast_results": 2,
        "outcomes": 0,
        "monitoring_control": 1,
        "notification_addresses": 0,
        "notification_preferences": 0,
        "price_alerts": 0,
        "price_alert_revisions": 0,
        "monitoring_owner_queue": 0,
        "monitoring_jobs": 0,
        "price_alert_observations": 0,
        "notifications": 0,
        "notification_read_events": 0,
        "notification_outbox": 0,
        "notification_outbox_attempts": 0,
        "collected_outcome_evidence": 0,
        "forecast_outcome_reviews": 0,
        "notification_address_verifications": 0,
        "notification_address_verification_recipients": 0,
        "notification_address_verification_events": 0,
    }


def test_backup_representative_counts_are_internal_physical_row_semantics(settings):
    """Integrity keys name storage tables, not the public event/run/result vocabulary."""

    repository, service = _service(settings)
    first = service.search("ACDC", "stock", owner_user_id=OWNER_USER_ID)
    service.search("ACDC", "stock", owner_user_id=OWNER_USER_ID)
    service.append_outcome(
        first["results"][0]["id"],
        24.0,
        datetime(2025, 1, 13, 21, 1, tzinfo=UTC),
        "observed",
        "representative count contract",
        owner_user_id=OWNER_USER_ID,
    )
    expected = {
        "search_events": 2,
        "forecast_runs": 1,
        "forecast_inputs": 1,
        "forecast_results": 2,
        "outcomes": 1,
        "monitoring_control": 1,
        "notification_addresses": 0,
        "notification_preferences": 0,
        "price_alerts": 0,
        "price_alert_revisions": 0,
        "monitoring_owner_queue": 0,
        "monitoring_jobs": 0,
        "price_alert_observations": 0,
        "notifications": 0,
        "notification_read_events": 0,
        "notification_outbox": 0,
        "notification_outbox_attempts": 0,
        "collected_outcome_evidence": 0,
        "forecast_outcome_reviews": 0,
        "notification_address_verifications": 0,
        "notification_address_verification_recipients": 0,
        "notification_address_verification_events": 0,
    }

    manager = BackupManager(repository, settings.backup_dir)
    created = manager.create("internal-counts.spbackup")
    manifest, _, staging = manager.verify(created["name"])
    try:
        assert repository.representative_counts() == expected
        assert manifest["counts"] == expected
        assert set(expected).isdisjoint({"events", "runs", "inputs", "results", "forecasts"})
    finally:
        staging.cleanup()


def test_v15_signed_backup_manifest_keeps_legacy_counts_without_synthetic_fields(
    settings, tmp_path, monkeypatch
):
    """A historical signed manifest retains exactly its schema-15 integrity count keys."""

    migrations = tmp_path / "v15-migrations"
    migrations.mkdir()
    for migration in sorted(files("stock_probs.migrations").iterdir(), key=lambda item: item.name):
        if migration.name.endswith(".sql") and int(migration.name[:3]) <= 15:
            (migrations / migration.name).write_bytes(migration.read_bytes())
    original_files = repository_module.files

    def v15_resources(package: str):
        return migrations if package == "stock_probs.migrations" else original_files(package)

    with monkeypatch.context() as schema15:
        schema15.setattr(repository_module, "files", v15_resources)
        schema15.setattr(repository_module, "SCHEMA_VERSION", 15)
        repository = Repository(settings.database_path)
        repository.migrate()
        manager = BackupManager(repository, settings.backup_dir)
        created = manager.create("signed-v15.spbackup", schema_version=15)
        manifest, _, staging = manager._verify_unlocked(
            created["name"], require_active_schema=False
        )
        try:
            legacy_keys = {
                "search_events",
                "forecast_runs",
                "forecast_inputs",
                "forecast_results",
                "outcomes",
            }
            assert manifest["schema_version"] == 15
            assert set(manifest["counts"]) == legacy_keys
            assert repository.representative_counts() == manifest["counts"]
        finally:
            staging.cleanup()

    # The current schema-18 reader still accepts the old signed manifest without fabricating
    # schema-16+ or schema-18 table counts.
    manifest, _, staging = manager._verify_unlocked(created["name"], require_active_schema=False)
    try:
        assert manifest["schema_version"] == 15
        assert set(manifest["counts"]) == legacy_keys
    finally:
        staging.cleanup()


def test_v17_signed_backup_keeps_its_count_shape_and_cannot_promote_over_v18(
    settings, tmp_path, monkeypatch
):
    current_repository, _service_instance = _service(settings)
    current_manager = BackupManager(current_repository, settings.backup_dir)
    migrations = tmp_path / "v17-migrations"
    migrations.mkdir()
    for migration in sorted(files("stock_probs.migrations").iterdir(), key=lambda item: item.name):
        if migration.name.endswith(".sql") and int(migration.name[:3]) <= 17:
            (migrations / migration.name).write_bytes(migration.read_bytes())
    original_files = repository_module.files
    older_database = tmp_path / "schema17" / "older.sqlite3"
    older_database.parent.mkdir()

    def v17_resources(package: str):
        return migrations if package == "stock_probs.migrations" else original_files(package)

    with monkeypatch.context() as version17:
        version17.setattr(repository_module, "files", v17_resources)
        version17.setattr(repository_module, "SCHEMA_VERSION", 17)
        older_repository = Repository(older_database)
        older_repository.migrate()
        older_manager = BackupManager(older_repository, settings.backup_dir)
        created = older_manager.create("signed-v17.spbackup", schema_version=17)
        manifest, _, staging = older_manager._verify_unlocked(
            created["name"], require_active_schema=False
        )
        try:
            expected = set(repository_module._SCHEMA16_REPRESENTATIVE_STORAGE_TABLES)
            assert manifest["schema_version"] == 17
            assert set(manifest["counts"]) == expected
            assert "notification_address_verifications" not in manifest["counts"]
        finally:
            staging.cleanup()

    before = hashlib.sha256(settings.database_path.read_bytes()).hexdigest()
    with pytest.raises(BackupError, match="schema version 17.*schema version 18"):
        current_manager.restore(created["name"], promote=True)
    assert hashlib.sha256(settings.database_path.read_bytes()).hexdigest() == before
    assert not settings.database_path.with_suffix(".pre-restore.sqlite3").exists()


def test_schema18_backup_preserves_address_effects_and_rejects_older_snapshot(settings):
    repository, _service_instance = _service(settings)
    owner_two_id = repository.create_user(
        github_user_id=2042,
        login="backup-address-owner-two",
        display_name="Backup address owner two",
        password_hash=None,
        created_at=NOW,
    )["id"]
    monitoring = MonitoringStore(repository)
    control = monitoring.get_control()
    monitoring.set_control(control["revision"], True, NOW)
    store = NotificationAddressStore(monitoring)

    owner_one_address = "owner-one-private@example.invalid"
    owner_two_old_address = "owner-two-obsolete@example.invalid"
    owner_one = store.request_verification(OWNER_USER_ID, owner_one_address, str(uuid4()), NOW)
    owner_two = store.request_verification(owner_two_id, owner_two_old_address, str(uuid4()), NOW)
    assert owner_one._code is not None
    assert owner_two._code is not None
    with pytest.raises(NotificationAddressUnavailable):
        store.get_status(owner_two_id, owner_one.verification_id, NOW)

    manager = BackupManager(repository, settings.backup_dir)
    before_submission = manager.create("schema18-before-address-effects.spbackup")
    manifest, staged_database, staging = manager.verify(before_submission["name"])
    try:
        new_tables = {
            "notification_address_verifications": 2,
            "notification_address_verification_recipients": 2,
            "notification_address_verification_events": 2,
        }
        assert manifest["schema_version"] == 18
        assert {name: manifest["counts"][name] for name in new_tables} == new_tables
        assert (settings.backup_dir / before_submission["name"]).stat().st_mode & 0o777 == 0o600
        with sqlite3.connect(staged_database) as connection:
            assert {
                "notification_address_verifications": connection.execute(
                    "SELECT COUNT(*) FROM notification_address_verifications"
                ).fetchone()[0],
                "notification_address_verification_recipients": connection.execute(
                    "SELECT COUNT(*) FROM notification_address_verification_recipients"
                ).fetchone()[0],
                "notification_address_verification_events": connection.execute(
                    "SELECT COUNT(*) FROM notification_address_verification_events"
                ).fetchone()[0],
            } == new_tables
            persisted_code_hash = connection.execute(
                "SELECT token_sha256 FROM notification_address_verifications WHERE id=?",
                (owner_one.verification_id,),
            ).fetchone()[0]
            assert persisted_code_hash != owner_one._code
        public_manifest = json.dumps(manifest, sort_keys=True)
        for private_value in (owner_one_address, owner_two_old_address, owner_one._code):
            assert private_value not in public_manifest
    finally:
        staging.cleanup()

    started = store.mark_submission_started(
        OWNER_USER_ID, owner_one.verification_id, owner_one.revision, owner_one._code, NOW
    )
    accepted = store.finish_submission(
        OWNER_USER_ID,
        owner_one.verification_id,
        "accepted",
        NOW + timedelta(seconds=1),
    )
    verified = store.verify_code(
        OWNER_USER_ID,
        owner_one.verification_id,
        owner_one._code,
        accepted.revision,
        NOW + timedelta(seconds=2),
    )
    assert started.state == "submitting"
    assert verified["verified"] is True
    current_preferences = monitoring.get_notification_preferences(OWNER_USER_ID)
    selected = store.select_verified_address(
        OWNER_USER_ID,
        verified["address_id"],
        current_preferences["revision"],
        NOW + timedelta(seconds=3),
    )
    assert selected["address_id"] == verified["address_id"]
    assert selected["alert_email"] is False and selected["digest_email"] is False

    replacement_address = "owner-two-current@example.invalid"
    replacement = store.request_verification(
        owner_two_id,
        replacement_address,
        str(uuid4()),
        NOW + timedelta(seconds=4),
        supersedes_verification_id=owner_two.verification_id,
        expected_revision=owner_two.revision,
    )
    assert replacement.state == "queued"
    assert store.get_status(owner_two_id, owner_two.verification_id, NOW).state == "superseded"
    with repository.connect() as connection:
        assert (
            connection.execute(
                "SELECT 1 FROM notification_address_verification_recipients "
                "WHERE verification_id=?",
                (owner_two.verification_id,),
            ).fetchone()
            is None
        )
        stored_request_hashes = {
            row[0]
            for row in connection.execute(
                "SELECT request_sha256 FROM notification_address_verifications"
            ).fetchall()
        }
        stored_token_hashes = {
            row[0]
            for row in connection.execute(
                "SELECT token_sha256 FROM notification_address_verifications"
            ).fetchall()
        }

    projection = build_owner_history_export(
        repository,
        OWNER_USER_ID,
        ["notifications", "rules", "reviews", "evidence", "preferences"],
        generated_at=NOW + timedelta(seconds=5),
    )
    json_export = serialize_owner_history_json(projection)
    csv_export = serialize_owner_history_csv(
        projection, safe_cell=lambda value: "" if value is None else str(value)
    )
    for private_value in (
        owner_one_address,
        owner_two_old_address,
        replacement_address,
        owner_one._code,
        owner_two._code,
        *stored_request_hashes,
        *stored_token_hashes,
    ):
        assert private_value not in json_export
        assert private_value not in csv_export

    before_digest = manager._notification_effect_digest(settings.database_path)
    with pytest.raises(BackupError, match="change notification consent.*delivery history"):
        manager.restore(before_submission["name"], promote=True)
    assert manager._notification_effect_digest(settings.database_path) == before_digest
    assert not settings.database_path.with_suffix(".pre-restore.sqlite3").exists()

    exact = manager.create("schema18-address-effects.spbackup")
    promoted = manager.restore(exact["name"], promote=True)
    assert promoted["promoted"] is True
    assert manager._notification_effect_digest(settings.database_path) == before_digest
    assert store.get_current_status(owner_two_id, NOW + timedelta(seconds=5)).verification_id == (
        replacement.verification_id
    )
    assert (
        monitoring.get_notification_preferences(OWNER_USER_ID)["address_id"]
        == (verified["address_id"])
    )
    assert (
        store.get_status(OWNER_USER_ID, owner_one.verification_id, NOW + timedelta(seconds=5)).state
        == "verified"
    )
    assert store.get_status(owner_two_id, owner_two.verification_id, NOW).state == "superseded"
    with repository.connect() as connection:
        assert (
            connection.execute(
                "SELECT 1 FROM notification_address_verification_recipients "
                "WHERE verification_id=?",
                (owner_two.verification_id,),
            ).fetchone()
            is None
        )
    with pytest.raises(NotificationAddressUnavailable):
        store.get_status(OWNER_USER_ID, replacement.verification_id, NOW)


@pytest.mark.parametrize("outcome", ["accepted", "uncertain"])
def test_restore_refuses_to_erase_submitted_notification_delivery_history(settings, outcome):
    """An older snapshot cannot erase a later accepted or ambiguous SMTP submission."""

    repository, _ = _service(settings)
    store = MonitoringStore(repository)
    now = NOW
    notification_id = str(uuid4())
    address_id = str(uuid4())
    with repository.connect() as connection:
        connection.execute(
            "INSERT INTO notifications(id,owner_user_id,dedupe_sha256,kind,payload_json,"
            "created_at) VALUES (?,?,?,'price_alert',?,?)",
            (
                notification_id,
                OWNER_USER_ID,
                "a" * 64,
                '{"symbol":"SPY","threshold":"100"}',
                now.isoformat(),
            ),
        )
        connection.execute(
            "INSERT INTO notification_addresses(id,owner_user_id,address,verified_at,created_at) "
            "VALUES (?,?,?,?,?)",
            (
                address_id,
                OWNER_USER_ID,
                "fixture@example.invalid",
                now.isoformat(),
                now.isoformat(),
            ),
        )
        connection.execute(
            "UPDATE monitoring_control SET enabled=1,revision=revision+1,updated_at=? WHERE id=1",
            (now.isoformat(),),
        )
        connection.commit()
    preferences = store.get_notification_preferences(OWNER_USER_ID)
    preferences = store.set_notification_preferences(
        OWNER_USER_ID,
        preferences["revision"],
        alert_email=True,
        digest_email=False,
        address_id=address_id,
        now=now,
    )
    queued = store.enqueue_notification_outbox(
        OWNER_USER_ID,
        notification_id,
        preferences["revision"],
        now=now,
    )
    manager = BackupManager(repository, settings.backup_dir)
    created = manager.create("before-email-acceptance.spbackup")

    claim = store.claim_due_notification_outbox(
        "restore-test-worker", now, limit=1, lease_seconds=30
    )[0]
    submission = store.mark_notification_outbox_submission_started(
        OWNER_USER_ID, claim, now + timedelta(seconds=1)
    )
    finalized = store.finalize_notification_outbox(
        OWNER_USER_ID,
        submission,
        outcome,
        now + timedelta(seconds=2),
        failure_code=None if outcome == "accepted" else "smtp_outcome_unknown",
    )
    assert finalized["state"] == outcome
    before = manager._notification_effect_digest(repository.database_path)
    with pytest.raises(BackupError, match="change notification consent"):
        manager.restore(created["name"], promote=True)

    assert manager._notification_effect_digest(repository.database_path) == before
    assert repository.representative_counts()["notification_outbox"] == 1
    with repository.connect() as connection:
        row = connection.execute(
            "SELECT state,submitted_at FROM notification_outbox WHERE id=?", (queued["id"],)
        ).fetchone()
        assert tuple(row) == (
            outcome,
            (
                (now + timedelta(seconds=2))
                .isoformat(timespec="microseconds")
                .replace("+00:00", "Z")
                if outcome == "accepted"
                else None
            ),
        )
    exact = manager.create(f"matching-{outcome}.spbackup")
    promoted = manager.restore(exact["name"], promote=True)
    assert promoted["promoted"] is True
    assert manager._notification_effect_digest(repository.database_path) == before
    assert not settings.database_path.with_suffix(".pre-restore.sqlite3").exists()


def test_restore_fails_before_staging_when_notification_effect_comparison_is_unavailable(
    settings, monkeypatch
):
    """An unavailable authority comparison rejects promotion before staging any DB swap."""

    repository, service = _service(settings)
    service.search("ACDC", "stock", owner_user_id=OWNER_USER_ID)
    manager = BackupManager(repository, settings.backup_dir)
    created = manager.create("comparison-unavailable.spbackup")
    before = hashlib.sha256(settings.database_path.read_bytes()).hexdigest()

    def unavailable(_path):
        raise BackupError("Notification delivery state could not be compared safely for restore.")

    def staging_must_not_run(*_args, **_kwargs):
        pytest.fail("comparison must complete before promotion staging")

    monkeypatch.setattr(manager, "_notification_effect_digest", unavailable)
    monkeypatch.setattr(manager, "_stage_promotion", staging_must_not_run)
    with pytest.raises(BackupError, match="could not be compared safely"):
        manager.restore(created["name"], promote=True)

    assert hashlib.sha256(settings.database_path.read_bytes()).hexdigest() == before
    assert not settings.database_path.with_suffix(".pre-restore.sqlite3").exists()


def test_failed_event_insert_rolls_back_new_input_and_results(settings):
    """A late event constraint failure cannot leave an unaudited partial forecast run."""

    repository, _ = _service(settings)
    snapshot, results = calculate_forecasts(FixtureProvider().fetch("ACDC", "stock", NOW), NOW)

    with pytest.raises(sqlite3.IntegrityError, match="analysis provenance"):
        repository.record_success(
            owner_user_id=OWNER_USER_ID,
            request_id="invalid-analysis-kind",
            submitted_symbol="ACDC",
            asset_type="stock",
            input_snapshot=snapshot,
            results=results,
            submitted_at=NOW,
            completed_at=NOW,
            analysis_kind="not-a-real-analysis",
        )

    counts = repository.representative_counts()
    assert all(
        counts[name] == 0
        for name in (
            "search_events",
            "forecast_runs",
            "forecast_inputs",
            "forecast_results",
            "outcomes",
        )
    )


def test_new_forecast_write_requires_cardinality_matching_the_input(settings):
    repository = Repository(settings.database_path)
    repository.migrate()
    snapshot, results = calculate_forecasts(FixtureProvider().fetch("ACDC", "stock", NOW), NOW)

    with pytest.raises(ValueError, match="cardinality"):
        repository.record_success(
            owner_user_id=OWNER_USER_ID,
            request_id="missing-quarterly",
            submitted_symbol="ACDC",
            asset_type="stock",
            input_snapshot=snapshot,
            results=results[:1],
            submitted_at=NOW,
            completed_at=NOW,
        )

    counts = repository.representative_counts()
    assert all(
        counts[name] == 0
        for name in (
            "search_events",
            "forecast_runs",
            "forecast_inputs",
            "forecast_results",
            "outcomes",
        )
    )


def test_repeated_provider_failures_are_audited_without_forecast_records(settings):
    """Failure remains the primary status while is_repeat preserves repeat audit context."""

    repository, service = _service(settings)
    for _ in range(2):
        with pytest.raises(DomainError) as failure:
            service.search("FAIL", "stock", owner_user_id=OWNER_USER_ID)
        assert failure.value.code == "provider_unavailable"

    history = repository.history(owner_user_id=OWNER_USER_ID, status="failed")
    assert history["total"] == 2
    assert [item["is_repeat"] for item in reversed(history["items"])] == [0, 1]
    counts = repository.representative_counts()
    assert counts["forecast_runs"] == counts["forecast_inputs"] == 0
    assert counts["forecast_results"] == 0


def test_repository_history_enforces_resource_bounds(settings):
    """Callers outside FastAPI cannot accidentally issue an unbounded history scan."""

    repository, _ = _service(settings)

    with pytest.raises(ValueError, match="page_size"):
        repository.history(owner_user_id=OWNER_USER_ID, page_size=101)
    with pytest.raises(ValueError, match="query"):
        repository.history(owner_user_id=OWNER_USER_ID, query="X" * 31)
    with pytest.raises(ValueError, match="status"):
        repository.history(owner_user_id=OWNER_USER_ID, status="anything")
    with pytest.raises(ValueError, match="analysis_kind"):
        repository.history(owner_user_id=OWNER_USER_ID, analysis_kind="recorded-ish")


def test_history_paginates_without_automatic_expiry(settings):
    """Bounded reads never imply deletion: every older event remains addressable after paging."""

    repository, _ = _service(settings)
    for index in range(125):
        repository.record_failure(
            owner_user_id=OWNER_USER_ID,
            request_id=f"retained-{index}",
            submitted_symbol=f"BAD{index}",
            normalized_symbol=f"BAD{index}",
            asset_type="stock",
            error_code="fixture_failure",
            error_message="retention fixture",
            submitted_at=NOW,
            completed_at=NOW,
        )

    first = repository.history(owner_user_id=OWNER_USER_ID, page=1, page_size=100)
    second = repository.history(owner_user_id=OWNER_USER_ID, page=2, page_size=100)
    assert first["total"] == second["total"] == 125
    assert len(first["items"]) == 100 and len(second["items"]) == 25
    assert second["items"][-1]["request_id"] == "retained-0"


def test_repeat_with_new_provider_as_of_creates_a_new_immutable_run(settings):
    repository = Repository(settings.database_path)
    repository.migrate()
    moments = iter(
        [
            NOW,
            NOW + timedelta(seconds=1),
            NOW + timedelta(minutes=1),
            NOW + timedelta(minutes=1, seconds=1),
        ]
    )
    service = ForecastService(repository, FixtureProvider(), lambda: next(moments))

    first = service.search("ACDC", "stock", owner_user_id=OWNER_USER_ID)
    second = service.search("ACDC", "stock", owner_user_id=OWNER_USER_ID)

    assert first["event"]["status"] == "successful"
    assert second["event"]["status"] == "repeated"
    assert second["reused"] is False
    assert repository.representative_counts()["forecast_runs"] == 2


def test_records_survive_a_fresh_repository_instance(settings):
    repository, service = _service(settings)
    created = service.search("ACDC", "stock", owner_user_id=OWNER_USER_ID)

    restarted = Repository(settings.database_path)
    restarted.migrate()

    assert restarted.history(owner_user_id=OWNER_USER_ID)["total"] == 1
    assert (
        restarted.reconstruction(OWNER_USER_ID, created["event"]["id"])["input"]["symbol"] == "ACDC"
    )
    stored_identity = restarted.reconstruction(OWNER_USER_ID, created["event"]["id"])["input"][
        "instrument_identity"
    ]
    assert stored_identity["canonical_symbol"] == "ACDC"
    assert stored_identity["company_name"] == "ProFrac Holding Corp."
    assert stored_identity == created["input"]["provenance"]["instrument_identity"]
    assert all(
        item["evaluation"]["method"].startswith("bounded chronological")
        for item in created["results"]
    )
    assert all(len(item["forecast_fingerprint"]) == 64 for item in created["results"])
    assert created["input"]["model_fingerprint"] == created["results"][0]["model_fingerprint"]


def test_saved_reopen_never_calls_provider_or_recalculates(settings):
    repository, service = _service(settings)
    created = service.search("ACDC", "stock", owner_user_id=OWNER_USER_ID)
    saved = deepcopy(created)

    class ProviderMustNotRun(FixtureProvider):
        def fetch(self, *args, **kwargs):
            pytest.fail("saved reopen must not fetch")

        def fetch_at_cutoff(self, *args, **kwargs):
            pytest.fail("saved reopen must not fetch historical data")

    restarted_service = ForecastService(repository, ProviderMustNotRun(), lambda: NOW)

    # Reopen is deliberately a repository call; constructing a new service changes nothing.
    assert restarted_service.repository.reconstruction(OWNER_USER_ID, created["event"]["id"]) == {
        key: saved[key] for key in ("event", "input", "results")
    }


def test_fresh_historical_cutoff_has_own_event_input_results_and_provenance(settings):
    repository, service = _service(settings)
    recorded = service.search("ACDC", "stock", owner_user_id=OWNER_USER_ID)
    performed = NOW + timedelta(minutes=1)
    fresh_service = ForecastService(repository, FixtureProvider(), lambda: performed)

    fresh = fresh_service.fresh_historical_reconstruction(
        recorded["event"]["id"], NOW, owner_user_id=OWNER_USER_ID
    )

    assert fresh["analysis_kind"] == "fresh_historical_reconstruction"
    assert fresh["label"] == "Fresh historical-cutoff analysis"
    assert fresh["event"]["analysis_kind"] == "fresh_historical_reconstruction"
    assert fresh["event"]["source_event_id"] == recorded["event"]["id"]
    assert fresh["event"]["requested_cutoff"] == NOW.isoformat()
    assert fresh["event"]["id"] != recorded["event"]["id"]
    assert fresh["input"]["id"] != recorded["input"]["id"]
    assert {item["id"] for item in fresh["results"]}.isdisjoint(
        {item["id"] for item in recorded["results"]}
    )
    analysis = fresh["input"]["provider_query"]["analysis"]
    assert analysis["kind"] == "fresh_historical_reconstruction"
    assert fresh["input"]["provider_query"] == fresh["input"]["provenance"]["query"]
    assert len(analysis["provider_content_fingerprint"]) == 64
    assert analysis["provider_content_fingerprint"] != fresh["input"]["content_fingerprint"]
    assert fresh["input"]["content_fingerprint"] != recorded["input"]["content_fingerprint"]
    assert all(
        datetime.fromisoformat(bar["end"]) <= NOW
        for key in ("selected_daily_bars", "selected_intraday_bars")
        for bar in fresh["input"][key]
    )
    assert all(
        result["evaluation"]["date_range"] is None
        or datetime.fromisoformat(result["evaluation"]["date_range"]["last_target"]) <= NOW
        for result in fresh["results"]
    )
    fresh_history = repository.history(
        owner_user_id=OWNER_USER_ID,
        analysis_kind="fresh_historical_reconstruction",
        include_analysis=True,
    )
    assert fresh_history["total"] == 1
    assert fresh_history["items"][0]["source_event_id"] == recorded["event"]["id"]


def test_each_repeated_fresh_historical_submission_gets_independent_records(settings):
    repository, service = _service(settings)
    recorded = service.search("ACDC", "stock", owner_user_id=OWNER_USER_ID)
    fresh_service = ForecastService(
        repository, FixtureProvider(), lambda: NOW + timedelta(minutes=1)
    )

    first = fresh_service.reconstruct_at_cutoff(
        recorded["event"]["id"], NOW, owner_user_id=OWNER_USER_ID
    )
    second = fresh_service.reconstruct_at_cutoff(
        recorded["event"]["id"], NOW, owner_user_id=OWNER_USER_ID
    )

    assert first["event"]["id"] != second["event"]["id"]
    assert first["input"]["id"] != second["input"]["id"]
    assert (
        first["input"]["provider_query"]["analysis"]["provider_content_fingerprint"]
        == second["input"]["provider_query"]["analysis"]["provider_content_fingerprint"]
    )
    assert first["input"]["content_fingerprint"] != second["input"]["content_fingerprint"]
    counts = repository.representative_counts()
    assert counts["search_events"] == 3 and counts["forecast_runs"] == 3


def test_fresh_historical_failure_appends_exactly_one_audit_event(settings):
    repository, service = _service(settings)
    recorded = service.search("ACDC", "stock", owner_user_id=OWNER_USER_ID)

    class FailingHistoricalProvider(FixtureProvider):
        def fetch_at_cutoff(self, *args, **kwargs):
            raise DomainError("provider_unavailable", "bounded fixture failure", status_code=502)

    fresh_service = ForecastService(
        repository, FailingHistoricalProvider(), lambda: NOW + timedelta(minutes=1)
    )
    with pytest.raises(DomainError) as failure:
        fresh_service.reconstruct_at_cutoff(
            recorded["event"]["id"], NOW, owner_user_id=OWNER_USER_ID
        )

    assert failure.value.request_id
    fresh_history = repository.history(
        owner_user_id=OWNER_USER_ID,
        analysis_kind="fresh_historical_reconstruction",
        include_analysis=True,
    )
    assert fresh_history["total"] == 1
    assert fresh_history["items"][0]["status"] == "failed"
    assert fresh_history["items"][0]["source_event_id"] == recorded["event"]["id"]
    assert repository.representative_counts()["forecast_runs"] == 1


def test_unknown_reconstruction_source_appends_one_failure_without_fabricated_fk(settings):
    repository, service = _service(settings)

    with pytest.raises(DomainError) as failure:
        service.reconstruct_at_cutoff(999, NOW, owner_user_id=OWNER_USER_ID)

    assert failure.value.code == "historical_source_unavailable"
    history = repository.history(
        owner_user_id=OWNER_USER_ID,
        analysis_kind="fresh_historical_reconstruction",
        include_analysis=True,
    )
    assert history["total"] == 1
    event = history["items"][0]
    assert event["status"] == "failed"
    assert event["source_event_id"] is None
    assert event["requested_source_event_id"] == 999
    assert event["requested_cutoff"] == NOW.isoformat()
    assert event["submitted_symbol"] == "<history event 999>"
    assert repository.representative_counts()["search_events"] == 1


def test_ambiguous_reconstruction_cutoff_retains_attempted_context(settings):
    repository, service = _service(settings)
    source = service.search("ACDC", "stock", owner_user_id=OWNER_USER_ID)["event"]["id"]
    attempted = NOW.replace(tzinfo=None)

    with pytest.raises(DomainError) as failure:
        service.reconstruct_at_cutoff(source, attempted, owner_user_id=OWNER_USER_ID)

    assert failure.value.code == "ambiguous_historical_cutoff"
    event = repository.history(
        owner_user_id=OWNER_USER_ID,
        analysis_kind="fresh_historical_reconstruction",
        include_analysis=True,
    )["items"][0]
    assert event["source_event_id"] == event["requested_source_event_id"] == source
    assert event["requested_cutoff"] == attempted.isoformat()


def test_provider_wait_does_not_hold_a_sqlite_write_transaction(settings):
    """A concurrent audit write completes while a slow provider is still outside SQLite."""

    repository, _ = _service(settings)
    entered = threading.Event()
    release = threading.Event()

    class BlockingProvider(FixtureProvider):
        def fetch(self, symbol, asset_type, now):
            entered.set()
            assert release.wait(timeout=5)
            return super().fetch(symbol, asset_type, now)

    service = ForecastService(repository, BlockingProvider(), lambda: NOW)
    with ThreadPoolExecutor(max_workers=1) as workers:
        pending = workers.submit(service.search, "ACDC", "stock", owner_user_id=OWNER_USER_ID)
        assert entered.wait(timeout=2)
        repository.record_failure(
            owner_user_id=OWNER_USER_ID,
            request_id="while-provider-waits",
            submitted_symbol="FAIL",
            normalized_symbol="FAIL",
            asset_type="stock",
            error_code="fixture_failure",
            error_message="concurrent audit",
            submitted_at=NOW,
            completed_at=NOW,
        )
        release.set()
        pending.result(timeout=5)
    assert repository.history(owner_user_id=OWNER_USER_ID)["total"] == 2


def test_service_company_lookup_returns_transport_ready_stock_and_etf_identity(settings):
    _, service = _service(settings)

    stock = service.lookup("ProFrac")
    fund = service.lookup("SPDR", 5)

    assert stock["query"] == "ProFrac" and stock["limit"] == 5
    assert stock["items"][0]["canonical_symbol"] == "ACDC"
    assert fund["items"][0]["canonical_symbol"] == "SPY"
    assert {stock["items"][0]["asset_type"], fund["items"][0]["asset_type"]} == {
        "stock",
        "etf",
    }
    assert all(item["provider_as_of"].endswith("+00:00") for item in stock["items"])


def test_service_lookup_enforces_its_default_bound_on_provider_results(settings):
    repository, _ = _service(settings)

    class OverReturningProvider(FixtureProvider):
        def lookup(self, query, limit=5, now=None):
            identity = super().lookup("ACDC", 1, now)[0]
            return (identity,) * 10

    service = ForecastService(repository, OverReturningProvider(), lambda: NOW)

    payload = service.lookup("company")

    assert payload["limit"] == payload["total"] == 5
    assert len(payload["items"]) == 5


def test_repository_rejects_identity_detached_from_forecast_provenance(settings):
    repository = Repository(settings.database_path)
    repository.migrate()
    snapshot, results = calculate_forecasts(FixtureProvider().fetch("ACDC", "stock", NOW), NOW)
    tampered = deepcopy(snapshot)
    tampered["instrument_identity"]["company_name"] = "Different company"

    with pytest.raises(ValueError, match="instrument identity"):
        repository.record_success(
            owner_user_id=OWNER_USER_ID,
            request_id="detached-identity",
            submitted_symbol="ACDC",
            asset_type="stock",
            input_snapshot=tampered,
            results=results,
            submitted_at=NOW,
            completed_at=NOW,
        )

    detached_top_level = deepcopy(snapshot)
    detached_top_level["company_name"] = "Different company"
    with pytest.raises(ValueError, match="instrument identity"):
        repository.record_success(
            owner_user_id=OWNER_USER_ID,
            request_id="detached-top-level-identity",
            submitted_symbol="ACDC",
            asset_type="stock",
            input_snapshot=detached_top_level,
            results=results,
            submitted_at=NOW,
            completed_at=NOW,
        )
    assert repository.representative_counts()["search_events"] == 0


def test_repository_rejects_tampered_forecast_or_evaluation_fingerprint(settings):
    """Versioned model/evaluation payloads cannot be detached before immutable persistence."""

    repository = Repository(settings.database_path)
    repository.migrate()
    snapshot, results = calculate_forecasts(FixtureProvider().fetch("ACDC", "stock", NOW), NOW)
    tampered = deepcopy(results)
    tampered[0]["evaluation"]["forecast_model"]["direction_brier"]["multiclass_mean"] = 0

    with pytest.raises(ValueError, match="forecast result"):
        repository.record_success(
            owner_user_id=OWNER_USER_ID,
            request_id="tampered-evaluation",
            submitted_symbol="ACDC",
            asset_type="stock",
            input_snapshot=snapshot,
            results=tampered,
            submitted_at=NOW,
            completed_at=NOW,
        )

    detached_model = deepcopy(snapshot)
    detached_model["model_fingerprint"] = "0" * 64
    with pytest.raises(ValueError, match="model and content provenance"):
        repository.record_success(
            owner_user_id=OWNER_USER_ID,
            request_id="detached-model",
            submitted_symbol="ACDC",
            asset_type="stock",
            input_snapshot=detached_model,
            results=results,
            submitted_at=NOW,
            completed_at=NOW,
        )
    assert repository.representative_counts()["search_events"] == 0


def test_results_and_outcomes_are_immutable_but_corrections_append(settings):
    """A correction adds an outcome row and cannot rewrite either prior record."""

    repository, service = _service(settings)
    created = service.search("ACDC", "stock", owner_user_id=OWNER_USER_ID)
    result_id = created["results"][0]["id"]
    observed_at = datetime(2025, 1, 13, 21, 1, tzinfo=UTC)
    first = service.append_outcome(
        result_id, 24.0, observed_at, "observed", "first", owner_user_id=OWNER_USER_ID
    )
    second = service.append_outcome(
        result_id, 24.1, observed_at, "corrected", "vendor fix", owner_user_id=OWNER_USER_ID
    )

    assert first is not None and second is not None and first["id"] != second["id"]
    reconstructed = repository.reconstruction(OWNER_USER_ID, created["event"]["id"])
    assert reconstructed is not None
    assert [item["state"] for item in reconstructed["results"][0]["outcomes"]] == [
        "observed",
        "corrected",
    ]
    with repository.connect() as connection:
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            connection.execute(
                "UPDATE forecast_results SET result_json = '{}' WHERE id = ?", (result_id,)
            )
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            connection.execute("UPDATE outcomes SET note = 'rewrite' WHERE id = ?", (first["id"],))
        original = connection.execute(
            "SELECT input_id, horizon, created_at FROM forecast_results WHERE id = ?", (result_id,)
        ).fetchone()
        # REPLACE internally deletes the old row, so recursive delete triggers must reject it.
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            connection.execute(
                "INSERT OR REPLACE INTO forecast_results "
                "(id, input_id, horizon, result_json, created_at) VALUES (?, ?, ?, '{}', ?)",
                (result_id, original["input_id"], original["horizon"], original["created_at"]),
            )


def test_reconstruction_bounds_outcomes_without_discarding_stored_rows(settings):
    """History returns the newest audit window while SQLite retains every appended outcome."""

    repository, service = _service(settings)
    created = service.search("ACDC", "stock", owner_user_id=OWNER_USER_ID)
    result_id = created["results"][0]["id"]
    observed_at = datetime(2025, 1, 13, 21, 1, tzinfo=UTC)
    for index in range(102):
        repository.append_outcome(
            OWNER_USER_ID,
            result_id,
            24.0,
            0.01,
            observed_at,
            "corrected",
            f"version {index}",
            "test comparison against immutable origin",
            observed_at,
        )

    reconstructed = repository.reconstruction(OWNER_USER_ID, created["event"]["id"])
    assert reconstructed is not None
    outcomes = reconstructed["results"][0]["outcomes"]
    assert len(outcomes) == 100
    assert outcomes[0]["note"] == "version 2" and outcomes[-1]["note"] == "version 101"
    assert reconstructed["results"][0]["outcomes_truncated"] is True
    assert repository.representative_counts()["outcomes"] == 102


def test_backup_restore_round_trip_reverts_later_data(settings):
    repository, service = _service(settings)
    service.search("ACDC", "stock", owner_user_id=OWNER_USER_ID)
    manager = BackupManager(repository, settings.backup_dir)
    created = manager.create("round-trip.spbackup")
    service.search("SPY", "etf", owner_user_id=OWNER_USER_ID)

    verified = manager.restore(created["name"])
    promoted = manager.restore(created["name"], promote=True)

    assert verified["verified"] is True and verified["promoted"] is False
    assert promoted["promoted"] is True
    assert repository.representative_counts()["search_events"] == 1
    assert repository.history(owner_user_id=OWNER_USER_ID, company="ProFrac Holding")["total"] == 1
    assert repository.history(owner_user_id=OWNER_USER_ID, symbol="SPY")["total"] == 0
    assert not settings.database_path.with_suffix(".pre-restore.sqlite3").exists()


def test_backup_restore_preserves_exact_history_microsecond_index(settings):
    repository, _ = _service(settings)
    submitted = datetime.fromisoformat("2025-01-10T12:03:00.123456-05:00")
    event_id = repository.record_failure(
        owner_user_id=OWNER_USER_ID,
        request_id="precise-offset",
        submitted_symbol="FAIL",
        normalized_symbol="FAIL",
        asset_type="stock",
        error_code="fixture_failure",
        error_message="microsecond backup fixture",
        submitted_at=submitted,
        completed_at=submitted,
    )
    manager = BackupManager(repository, settings.backup_dir)
    created = manager.create("precise-history.spbackup")
    repository.record_failure(
        owner_user_id=OWNER_USER_ID,
        request_id="later-event",
        submitted_symbol="FAIL",
        normalized_symbol="FAIL",
        asset_type="stock",
        error_code="fixture_failure",
        error_message="removed by restore",
        submitted_at=submitted + timedelta(seconds=1),
        completed_at=submitted + timedelta(seconds=1),
    )

    restored = manager.restore(created["name"], promote=True)
    exact_utc = datetime(2025, 1, 10, 17, 3, 0, 123456, tzinfo=UTC)

    assert restored["promoted"] is True
    assert [
        item["id"]
        for item in repository.history(
            owner_user_id=OWNER_USER_ID, date_from=exact_utc, date_to=exact_utc
        )["items"]
    ] == [event_id]
    with repository.connect() as connection:
        stored = connection.execute(
            "SELECT submitted_at_us FROM history_facets WHERE event_id = ?", (event_id,)
        ).fetchone()
    assert stored["submitted_at_us"] == 1_736_528_580_123_456


def test_successful_restore_serializes_second_repository_write_without_discarding_it(
    settings, monkeypatch
):
    repository, _ = _service(settings)
    repository.record_failure(
        owner_user_id=OWNER_USER_ID,
        request_id="backup-event",
        submitted_symbol="FAIL",
        normalized_symbol="FAIL",
        asset_type="stock",
        error_code="fixture_failure",
        error_message="backup state",
        submitted_at=NOW,
        completed_at=NOW,
    )
    manager = BackupManager(repository, settings.backup_dir)
    manager.create("coordinated-success.spbackup")
    repository.record_failure(
        owner_user_id=OWNER_USER_ID,
        request_id="discarded-by-requested-restore",
        submitted_symbol="FAIL",
        normalized_symbol="FAIL",
        asset_type="stock",
        error_code="fixture_failure",
        error_message="later state",
        submitted_at=NOW,
        completed_at=NOW,
    )
    second = Repository(settings.database_path.parent / "." / settings.database_path.name)
    entered = threading.Event()
    release = threading.Event()
    writer_started = threading.Event()
    original_stage = manager._stage_promotion

    def paused_stage(*args, **kwargs):
        candidate = original_stage(*args, **kwargs)
        entered.set()
        assert release.wait(timeout=5)
        return candidate

    def write_after_restore_starts():
        writer_started.set()
        return second.record_failure(
            owner_user_id=OWNER_USER_ID,
            request_id="concurrent-preserved",
            submitted_symbol="FAIL",
            normalized_symbol="FAIL",
            asset_type="stock",
            error_code="fixture_failure",
            error_message="must land after promotion",
            submitted_at=NOW,
            completed_at=NOW,
        )

    monkeypatch.setattr(manager, "_stage_promotion", paused_stage)
    with ThreadPoolExecutor(max_workers=2) as workers:
        restore = workers.submit(manager.restore, "coordinated-success.spbackup", promote=True)
        assert entered.wait(timeout=2)
        writer = workers.submit(write_after_restore_starts)
        assert writer_started.wait(timeout=2)
        assert not writer.done()
        release.set()
        assert restore.result(timeout=5)["promoted"] is True
        writer.result(timeout=5)

    request_ids = {
        item["request_id"] for item in repository.history(owner_user_id=OWNER_USER_ID)["items"]
    }
    assert request_ids == {"backup-event", "concurrent-preserved"}


def test_failed_restore_serializes_second_repository_write_and_preserves_active_data(
    settings, monkeypatch
):
    repository, _ = _service(settings)
    for request_id in ("backup-event",):
        repository.record_failure(
            owner_user_id=OWNER_USER_ID,
            request_id=request_id,
            submitted_symbol="FAIL",
            normalized_symbol="FAIL",
            asset_type="stock",
            error_code="fixture_failure",
            error_message="backup state",
            submitted_at=NOW,
            completed_at=NOW,
        )
    manager = BackupManager(repository, settings.backup_dir)
    manager.create("coordinated-failure.spbackup")
    repository.record_failure(
        owner_user_id=OWNER_USER_ID,
        request_id="active-later-event",
        submitted_symbol="FAIL",
        normalized_symbol="FAIL",
        asset_type="stock",
        error_code="fixture_failure",
        error_message="active state",
        submitted_at=NOW,
        completed_at=NOW,
    )
    second = Repository(settings.database_path)
    entered = threading.Event()
    release = threading.Event()
    writer_started = threading.Event()
    original_stage = manager._stage_promotion
    original_counts = manager._counts

    def paused_stage(*args, **kwargs):
        candidate = original_stage(*args, **kwargs)
        entered.set()
        assert release.wait(timeout=5)
        return candidate

    def fail_promoted_counts(path):
        counts = original_counts(path)
        if (
            path == settings.database_path
            and settings.database_path.with_suffix(".pre-restore.sqlite3").exists()
        ):
            counts["search_events"] += 1
        return counts

    def concurrent_write():
        writer_started.set()
        return second.record_failure(
            owner_user_id=OWNER_USER_ID,
            request_id="concurrent-after-failure",
            submitted_symbol="FAIL",
            normalized_symbol="FAIL",
            asset_type="stock",
            error_code="fixture_failure",
            error_message="must land after rollback",
            submitted_at=NOW,
            completed_at=NOW,
        )

    monkeypatch.setattr(manager, "_stage_promotion", paused_stage)
    monkeypatch.setattr(manager, "_counts", fail_promoted_counts)
    with ThreadPoolExecutor(max_workers=2) as workers:
        restore = workers.submit(manager.restore, "coordinated-failure.spbackup", promote=True)
        assert entered.wait(timeout=2)
        writer = workers.submit(concurrent_write)
        assert writer_started.wait(timeout=2)
        assert not writer.done()
        release.set()
        with pytest.raises(BackupError, match="representative-count"):
            restore.result(timeout=5)
        writer.result(timeout=5)

    request_ids = {
        item["request_id"] for item in repository.history(owner_user_id=OWNER_USER_ID)["items"]
    }
    assert request_ids == {
        "backup-event",
        "active-later-event",
        "concurrent-after-failure",
    }


def test_process_coordination_does_not_serialize_different_databases(settings, tmp_path):
    first = Repository(settings.database_path)
    second = Repository(tmp_path / "independent.sqlite3")
    first.migrate()
    second.migrate()

    with first.exclusive(), ThreadPoolExecutor(max_workers=1) as workers:
        write = workers.submit(
            second.record_failure,
            owner_user_id=OWNER_USER_ID,
            request_id="independent",
            submitted_symbol="FAIL",
            normalized_symbol="FAIL",
            asset_type="stock",
            error_code="fixture_failure",
            error_message="different database",
            submitted_at=NOW,
            completed_at=NOW,
        )
        write.result(timeout=2)

    assert second.history(owner_user_id=OWNER_USER_ID)["total"] == 1


def test_process_coordination_wait_is_bounded_for_the_same_database(settings, monkeypatch):
    first = Repository(settings.database_path)
    first.migrate()
    second = Repository(settings.database_path)
    manager = BackupManager(second, settings.backup_dir)
    monkeypatch.setattr(repository_module, "COORDINATION_TIMEOUT_SECONDS", 0.01)

    with first.exclusive(), ThreadPoolExecutor(max_workers=1) as workers:
        blocked = workers.submit(second.history, owner_user_id=OWNER_USER_ID)
        with pytest.raises(sqlite3.OperationalError, match="coordination lock timed out"):
            blocked.result(timeout=1)
        restore = workers.submit(manager.restore, "not-reached.spbackup")
        with pytest.raises(BackupError, match="bounded local lock"):
            restore.result(timeout=1)


def test_repository_error_keeps_injected_path_detail_out_of_public_structure(settings, monkeypatch):
    """Transport gets one category while operators can inspect the chained SQLite cause."""

    repository = Repository(settings.database_path)
    sensitive = "/home/private/database.sqlite3?token=do-not-publish"

    def fail_connect(*args, **kwargs):
        raise sqlite3.OperationalError(sensitive)

    monkeypatch.setattr(repository_module.sqlite3, "connect", fail_connect)
    with pytest.raises(RepositoryError) as failure:
        repository.history(owner_user_id=OWNER_USER_ID)

    error = failure.value
    assert error.public_category == "persistence_unavailable"
    assert sensitive not in str(error)
    assert sensitive not in repr(error)
    assert sensitive not in json.dumps(error.args, default=str)
    assert sensitive not in json.dumps(vars(error), default=str)
    assert not [name for name in vars(error) if not name.startswith("_")]
    assert error.__cause__ is not None and sensitive in str(error.__cause__)


def test_backup_error_keeps_injected_path_detail_out_of_public_structure(settings, monkeypatch):
    """Path diagnostics stay chained and never become public backup metadata."""

    repository = Repository(settings.database_path)
    repository.migrate()
    manager = BackupManager(repository, settings.backup_dir)
    sensitive = "/srv/private/stock.sqlite3 authorization=do-not-publish"

    def fail_counts(path):
        raise OSError(sensitive)

    monkeypatch.setattr(repository, "representative_counts", fail_counts)
    with pytest.raises(BackupError, match="representative-count") as failure:
        manager._counts(settings.database_path)

    error = failure.value
    assert error.public_category == "backup_creation_failed"
    assert sensitive not in str(error)
    assert sensitive not in repr(error)
    assert sensitive not in json.dumps(error.args, default=str)
    assert sensitive not in json.dumps(vars(error), default=str)
    assert not [name for name in vars(error) if not name.startswith("_")]
    assert error.__cause__ is not None and sensitive in str(error.__cause__)


def test_restore_rejects_tampering_and_unsafe_names(settings):
    repository, service = _service(settings)
    service.search("ACDC", "stock", owner_user_id=OWNER_USER_ID)
    manager = BackupManager(repository, settings.backup_dir)
    manager.create("valid-copy.spbackup")

    with pytest.raises(BackupError, match="simple"):
        manager.restore("../valid-copy.spbackup")

    tampered = settings.backup_dir / "tampered.spbackup"
    with zipfile.ZipFile(tampered, "w") as archive:
        archive.writestr("database.sqlite3", b"not sqlite")
        archive.writestr("manifest.json", '{"format":"stock-probs-backup","schema_version":1}')
    with pytest.raises(BackupError) as failure:
        manager.restore("tampered.spbackup", promote=True)
    assert failure.value.public_category == "restore_failed"
    assert vars(failure.value) == {"_public_category": "restore_failed"}
    assert "not sqlite" not in repr(failure.value)
    assert repository.representative_counts()["search_events"] == 1


def test_restore_rejects_incompatible_manifest_and_truncated_archive(settings):
    repository, service = _service(settings)
    service.search("ACDC", "stock", owner_user_id=OWNER_USER_ID)
    manager = BackupManager(repository, settings.backup_dir)
    manager.create("source.spbackup")

    with zipfile.ZipFile(settings.backup_dir / "source.spbackup") as source:
        database = source.read("database.sqlite3")
        manifest = json.loads(source.read("manifest.json"))
    manifest["format_version"] = 99
    with zipfile.ZipFile(settings.backup_dir / "incompatible.spbackup", "w") as target:
        target.writestr("database.sqlite3", database)
        target.writestr("manifest.json", json.dumps(manifest))
    (settings.backup_dir / "truncated.spbackup").write_bytes(b"PK\x03\x04")

    with pytest.raises(BackupError, match="incompatible"):
        manager.restore("incompatible.spbackup", promote=True)
    with pytest.raises(BackupError, match="truncated"):
        manager.restore("truncated.spbackup", promote=True)
    assert repository.representative_counts()["search_events"] == 1


def test_backup_operations_are_available_only_through_managed_names(client):
    client.post("/api/v1/forecasts", json={"symbol": "ACDC", "asset_type": "stock"})
    created = client.post("/api/v1/operations/backups", json={"name": "api-copy.spbackup"})
    checked = client.post(
        "/api/v1/operations/restores", json={"name": "api-copy.spbackup", "promote": False}
    )

    assert created.status_code == 201
    assert checked.json()["verified"] is True
    assert "path" not in str(created.json()).lower()

    rejected = client.post(
        "/api/v1/operations/restores", json={"name": "../escape.spbackup", "promote": True}
    )
    assert rejected.status_code == 422
    assert rejected.json()["error"]["code"] == "restore_failed"
