"""M02/M05 tests prove migration, immutability, concurrency, and safe restore behavior."""

from __future__ import annotations

import json
import sqlite3
import zipfile
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import UTC, datetime, timedelta

import pytest

from stock_probs.backup import BackupError, BackupManager
from stock_probs.domain import DomainError, calculate_forecasts
from stock_probs.provider import FixtureProvider
from stock_probs.repository import Repository
from stock_probs.service import ForecastService

NOW = datetime(2025, 1, 10, 17, 3, tzinfo=UTC)


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
    assert [row[0] for row in versions] == [1]


def test_database_triggers_reject_mutation_and_deletion(settings):
    repository, service = _service(settings)
    created = service.search("ACDC", "stock")

    with repository.connect() as connection:
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            connection.execute(
                "UPDATE forecast_inputs SET snapshot_json = '{}' WHERE id = ?",
                (created["input"]["id"],),
            )
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            connection.execute("DELETE FROM search_events")


def test_concurrent_repeats_each_append_one_event(settings):
    repository, service = _service(settings)
    with ThreadPoolExecutor(max_workers=4) as workers:
        results = list(workers.map(lambda _: service.search("SPY", "etf"), range(8)))

    assert len({item["event"]["id"] for item in results}) == 8
    assert repository.representative_counts()["search_events"] == 8
    assert repository.representative_counts()["forecast_runs"] == 1


def test_repeated_provider_failures_are_audited_without_forecast_records(settings):
    """Failure remains the primary status while is_repeat preserves repeat audit context."""

    repository, service = _service(settings)
    for _ in range(2):
        with pytest.raises(DomainError) as failure:
            service.search("FAIL", "stock")
        assert failure.value.code == "provider_unavailable"

    history = repository.history(status="failed")
    assert history["total"] == 2
    assert [item["is_repeat"] for item in reversed(history["items"])] == [0, 1]
    counts = repository.representative_counts()
    assert counts["forecast_runs"] == counts["forecast_inputs"] == 0
    assert counts["forecast_results"] == 0


def test_repository_history_enforces_resource_bounds(settings):
    """Callers outside FastAPI cannot accidentally issue an unbounded history scan."""

    repository, _ = _service(settings)

    with pytest.raises(ValueError, match="page_size"):
        repository.history(page_size=101)
    with pytest.raises(ValueError, match="query"):
        repository.history(query="X" * 31)


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

    first = service.search("ACDC", "stock")
    second = service.search("ACDC", "stock")

    assert first["event"]["status"] == "successful"
    assert second["event"]["status"] == "repeated"
    assert second["reused"] is False
    assert repository.representative_counts()["forecast_runs"] == 2


def test_records_survive_a_fresh_repository_instance(settings):
    repository, service = _service(settings)
    created = service.search("ACDC", "stock")

    restarted = Repository(settings.database_path)
    restarted.migrate()

    assert restarted.history()["total"] == 1
    assert restarted.reconstruction(created["event"]["id"])["input"]["symbol"] == "ACDC"
    stored_identity = restarted.reconstruction(created["event"]["id"])["input"][
        "instrument_identity"
    ]
    assert stored_identity["canonical_symbol"] == "ACDC"
    assert stored_identity["company_name"] == "ProFrac Holding Corp."
    assert stored_identity == created["input"]["provenance"]["instrument_identity"]


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
            request_id="detached-top-level-identity",
            submitted_symbol="ACDC",
            asset_type="stock",
            input_snapshot=detached_top_level,
            results=results,
            submitted_at=NOW,
            completed_at=NOW,
        )
    assert repository.representative_counts()["search_events"] == 0


def test_results_and_outcomes_are_immutable_but_corrections_append(settings):
    """A correction adds an outcome row and cannot rewrite either prior record."""

    repository, service = _service(settings)
    created = service.search("ACDC", "stock")
    result_id = created["results"][0]["id"]
    observed_at = datetime(2025, 1, 13, 21, 1, tzinfo=UTC)
    first = service.append_outcome(result_id, 24.0, observed_at, "observed", "first")
    second = service.append_outcome(result_id, 24.1, observed_at, "corrected", "vendor fix")

    assert first is not None and second is not None and first["id"] != second["id"]
    reconstructed = repository.reconstruction(created["event"]["id"])
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
    created = service.search("ACDC", "stock")
    result_id = created["results"][0]["id"]
    observed_at = datetime(2025, 1, 13, 21, 1, tzinfo=UTC)
    for index in range(102):
        repository.append_outcome(
            result_id,
            24.0,
            0.01,
            observed_at,
            "corrected",
            f"version {index}",
            "test comparison against immutable origin",
            observed_at,
        )

    reconstructed = repository.reconstruction(created["event"]["id"])
    assert reconstructed is not None
    outcomes = reconstructed["results"][0]["outcomes"]
    assert len(outcomes) == 100
    assert outcomes[0]["note"] == "version 2" and outcomes[-1]["note"] == "version 101"
    assert reconstructed["results"][0]["outcomes_truncated"] is True
    assert repository.representative_counts()["outcomes"] == 102


def test_backup_restore_round_trip_reverts_later_data(settings):
    repository, service = _service(settings)
    service.search("ACDC", "stock")
    manager = BackupManager(repository, settings.backup_dir)
    created = manager.create("round-trip.spbackup")
    service.search("SPY", "etf")

    verified = manager.restore(created["name"])
    promoted = manager.restore(created["name"], promote=True)

    assert verified["verified"] is True and verified["promoted"] is False
    assert promoted["promoted"] is True
    assert repository.representative_counts()["search_events"] == 1
    assert not settings.database_path.with_suffix(".pre-restore.sqlite3").exists()


def test_restore_rejects_tampering_and_unsafe_names(settings):
    repository, service = _service(settings)
    service.search("ACDC", "stock")
    manager = BackupManager(repository, settings.backup_dir)
    manager.create("valid-copy.spbackup")

    with pytest.raises(BackupError, match="simple"):
        manager.restore("../valid-copy.spbackup")

    tampered = settings.backup_dir / "tampered.spbackup"
    with zipfile.ZipFile(tampered, "w") as archive:
        archive.writestr("database.sqlite3", b"not sqlite")
        archive.writestr("manifest.json", '{"format":"stock-probs-backup","schema_version":1}')
    with pytest.raises(BackupError):
        manager.restore("tampered.spbackup", promote=True)
    assert repository.representative_counts()["search_events"] == 1


def test_restore_rejects_incompatible_manifest_and_truncated_archive(settings):
    repository, service = _service(settings)
    service.search("ACDC", "stock")
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
    assert rejected.json()["error"]["code"] == "restore_failure"
