"""Developer tests cover the fixed bounded portfolio/watchlist and v4 upgrades."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from importlib.resources import files

import pytest

from stock_probs.backup import BackupError, BackupManager
from stock_probs.cli import _migrate_with_backup
from stock_probs.repository import INSTRUMENT_LIST_ITEM_LIMIT, Repository

NOW = datetime(2026, 9, 15, 12, 0, tzinfo=UTC)


def _repository(settings) -> Repository:
    repository = Repository(settings.database_path)
    repository.migrate()
    return repository


def _create_legacy_database(path, version: int) -> Repository:
    migration_dir = files("stock_probs.migrations")
    with sqlite3.connect(path) as connection:
        for applied_version in range(1, version + 1):
            name = next(
                item.name
                for item in migration_dir.iterdir()
                if item.name.startswith(f"{applied_version:03d}_")
            )
            connection.executescript(migration_dir.joinpath(name).read_text())
            connection.execute(
                "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                (applied_version, NOW.isoformat()),
            )
    return Repository(path)


@pytest.mark.parametrize("legacy_version", [1, 2, 3, 4])
def test_every_shipped_legacy_schema_upgrades_to_fixed_lists(settings, legacy_version):
    repository = _create_legacy_database(settings.database_path, legacy_version)

    repository.migrate()

    with repository.connect() as connection:
        versions = connection.execute(
            "SELECT version FROM schema_migrations ORDER BY version"
        ).fetchall()
        columns = connection.execute("PRAGMA table_info(instrument_list_items)").fetchall()
        named_lists = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'instrument_lists'"
        ).fetchone()
        table_sql = connection.execute(
            "SELECT sql FROM sqlite_master "
            "WHERE type = 'table' AND name = 'instrument_list_items'"
        ).fetchone()[0]
        triggers = connection.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type = 'trigger' AND tbl_name = 'instrument_list_items'"
        ).fetchall()
    assert [row[0] for row in versions] == [1, 2, 3, 4, 5, 6]
    assert {row[1] for row in columns} == {
        "kind",
        "provider",
        "canonical_symbol",
        "asset_type",
        "exchange",
        "display_name",
        "quantity",
        "added_at",
    }
    assert named_lists is None
    assert "CHECK (kind = 'portfolio' OR quantity IS NULL)" in table_sql
    assert triggers == []


def _add(repository: Repository, kind: str, symbol: str, added_at=NOW, **holdings):
    return repository.add_instrument_list_item(
        kind,
        provider="yahoo",
        canonical_symbol=symbol,
        asset_type="etf" if symbol == "SPY" else "stock",
        exchange="PCX" if symbol == "SPY" else "NASDAQ",
        display_name="SPDR S&P 500 ETF Trust" if symbol == "SPY" else symbol,
        added_at=added_at,
        **holdings,
    )


def test_v4_migration_backup_and_v6_fixed_list_restore_round_trip(settings):
    repository = _create_legacy_database(settings.database_path, 4)
    repository.record_failure(
        request_id="retained-v4-event",
        submitted_symbol="FAIL",
        normalized_symbol="FAIL",
        asset_type="stock",
        error_code="fixture_failure",
        error_message="retained through v6",
        submitted_at=NOW,
        completed_at=NOW,
    )
    manager = BackupManager(repository, settings.backup_dir)

    migration_backup = _migrate_with_backup(repository, manager)

    assert migration_backup is not None and migration_backup["schema_version"] == 4
    old_manifest, _, old_staging = manager._verify_unlocked(
        migration_backup["name"], require_active_schema=False
    )
    old_staging.cleanup()
    assert old_manifest["schema_version"] == 4
    with pytest.raises(BackupError, match="schema version 4 cannot be restored over active"):
        manager.restore(migration_backup["name"], promote=True)

    _add(repository, "portfolio", "SPY", quantity=2)
    current_backup = manager.create("v6-lists.spbackup")
    repository.set_instrument_list_item_holding(
        "portfolio",
        provider="yahoo",
        canonical_symbol="SPY",
        asset_type="etf",
        quantity=9,
    )

    assert manager.restore(current_backup["name"], promote=True)["promoted"] is True
    restored = Repository(settings.database_path)
    assert restored.instrument_list_items("portfolio")[0]["quantity"] == 2
    assert restored.history()["items"][0]["request_id"] == "retained-v4-event"


def test_fixed_lists_persist_independently_across_restart(settings):
    repository = _repository(settings)
    _add(repository, "portfolio", "ACDC", quantity=10)
    watch_item = _add(repository, "watchlist", "SPY")
    assert watch_item is not None
    assert watch_item["quantity"] is None

    assert repository.set_instrument_list_item_holding(
        "portfolio",
        provider="yahoo",
        canonical_symbol="ACDC",
        asset_type="stock",
        quantity=12.5,
    ) is True
    assert repository.set_instrument_list_item_holding(
        "portfolio",
        provider="yahoo",
        canonical_symbol="MISSING",
        asset_type="stock",
        quantity=1,
    ) is False
    restarted = Repository(settings.database_path)
    restarted.migrate()
    persisted = restarted.instrument_list_items()

    assert json.loads(json.dumps(persisted, allow_nan=False)) == persisted
    assert {(item["kind"], item["canonical_symbol"]) for item in persisted} == {
        ("portfolio", "ACDC"),
        ("watchlist", "SPY"),
    }
    assert restarted.remove_instrument_list_item(
        "watchlist",
        provider="yahoo",
        canonical_symbol="SPY",
        asset_type="etf",
    )
    assert restarted.instrument_list_items("watchlist") == []
    assert not restarted.remove_instrument_list_item(
        "watchlist",
        provider="yahoo",
        canonical_symbol="SPY",
        asset_type="etf",
    )
    assert restarted.instrument_list_items("portfolio")[0]["quantity"] == 12.5


def test_list_item_timestamp_requires_timezone_and_is_stored_as_utc(settings):
    repository = _repository(settings)
    item = _add(
        repository,
        "watchlist",
        "SPY",
        added_at=datetime.fromisoformat("2026-09-15T08:00:00-04:00"),
    )

    assert item is not None and item["added_at"] == NOW.isoformat()
    with pytest.raises(ValueError, match="added_at must include a timezone offset"):
        _add(repository, "watchlist", "ACDC", added_at=datetime(2026, 9, 15, 12))


def test_duplicate_and_per_kind_item_limits_are_rejected(settings):
    repository = _repository(settings)
    _add(repository, "watchlist", "S0")
    with pytest.raises(ValueError, match="already"):
        _add(repository, "watchlist", "S0")
    for index in range(1, INSTRUMENT_LIST_ITEM_LIMIT):
        _add(repository, "watchlist", f"S{index}")
    with pytest.raises(ValueError, match="item limit"):
        _add(repository, "watchlist", "OVER")
    assert len(repository.instrument_list_items("watchlist")) == INSTRUMENT_LIST_ITEM_LIMIT
    _add(repository, "portfolio", "OVER")


def test_database_constraints_reject_invalid_kind_and_watchlist_holdings(settings):
    repository = _repository(settings)
    with pytest.raises(ValueError, match="kind"):
        _add(repository, "invalid", "BAD")
    with pytest.raises(ValueError, match="quantity"):
        _add(repository, "portfolio", "ACDC", quantity=-1)
    with pytest.raises(ValueError, match="require a portfolio"):
        _add(repository, "watchlist", "SPY", quantity=1)
    with repository.connect() as connection, pytest.raises(
        sqlite3.IntegrityError, match="CHECK constraint failed"
    ):
        connection.execute(
            "INSERT INTO instrument_list_items"
            "(kind, provider, canonical_symbol, asset_type, exchange, display_name, quantity, "
            "added_at) VALUES ('watchlist', 'yahoo', 'SPY', 'etf', 'PCX', "
            "'SPDR S&P 500 ETF Trust', 1, ?)",
            (NOW.isoformat(),),
        )
    _add(repository, "watchlist", "SPY")
    with repository.connect() as connection, pytest.raises(
        sqlite3.IntegrityError, match="CHECK constraint failed"
    ):
        connection.execute(
            "UPDATE instrument_list_items SET quantity = 1 "
            "WHERE kind = 'watchlist' AND canonical_symbol = 'SPY'"
        )
