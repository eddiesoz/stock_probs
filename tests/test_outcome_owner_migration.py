"""Schema 17 makes outcome ownership immutable across SQLite REPLACE settings."""

from __future__ import annotations

import hashlib
import sqlite3
from datetime import UTC, datetime
from importlib.resources import files
from pathlib import Path
from uuid import uuid4

import pytest

import stock_probs.repository as repository_module
from stock_probs.repository import SCHEMA_VERSION, Repository, RepositoryDatabaseError

STAMP = datetime(2025, 1, 2, 3, 4, tzinfo=UTC)
STAMP_TEXT = STAMP.isoformat()


def _insert_owned_result(repository: Repository) -> tuple[int, int]:
    """Create the smallest valid owned forecast chain and one owned outcome."""
    with repository.connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        run = connection.execute(
            "INSERT INTO forecast_runs(symbol,asset_type,content_fingerprint,created_at) "
            "VALUES ('SPY','etf',?,?)",
            (f"migration-test-{uuid4()}", STAMP_TEXT),
        )
        run_id = int(run.lastrowid)
        connection.execute(
            "INSERT INTO forecast_run_owners(run_id,owner_user_id,assigned_at) VALUES (?,1,?)",
            (run_id, STAMP_TEXT),
        )
        input_cursor = connection.execute(
            "INSERT INTO forecast_inputs(run_id,snapshot_json,created_at) VALUES (?, '{}', ?)",
            (run_id, STAMP_TEXT),
        )
        input_id = int(input_cursor.lastrowid)
        result_cursor = connection.execute(
            "INSERT INTO forecast_results(input_id,horizon,result_json,created_at) "
            "VALUES (?, 'daily_1', '{}', ?)",
            (input_id, STAMP_TEXT),
        )
        result_id = int(result_cursor.lastrowid)
        connection.execute(
            "INSERT INTO forecast_result_owners(result_id,owner_user_id,assigned_at) "
            "VALUES (?,1,?)",
            (result_id, STAMP_TEXT),
        )
        outcome_cursor = connection.execute(
            "INSERT INTO outcomes(result_id,observed_close,observed_return,observed_at,"
            "comparison_rule,state,note,created_at) VALUES (?, 100.0, 0.0, ?, 'daily-close', "
            "'observed', '', ?)",
            (result_id, STAMP_TEXT, STAMP_TEXT),
        )
        outcome_id = int(outcome_cursor.lastrowid)
        connection.execute(
            "INSERT INTO outcome_owners(outcome_id,owner_user_id,assigned_at) VALUES (?,1,?)",
            (outcome_id, STAMP_TEXT),
        )
        connection.commit()
    return result_id, outcome_id


def _schema(repository: Repository) -> list[tuple[object, ...]]:
    with repository.connect() as connection:
        rows = connection.execute(
            "SELECT type,name,tbl_name,sql FROM sqlite_master "
            "WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name"
        ).fetchall()
    return [tuple(row) for row in rows]


def _create_schema_16(
    path: Path, migration_root: Path, monkeypatch: pytest.MonkeyPatch
) -> Repository:
    """Apply the already-registered 001-016 migrations before testing the 016→017 upgrade."""
    source = files("stock_probs.migrations")
    migration_root.mkdir()
    for migration in sorted(source.iterdir(), key=lambda item: item.name):
        if migration.name.endswith(".sql") and int(migration.name[:3]) <= 16:
            (migration_root / migration.name).write_bytes(migration.read_bytes())
    original_files = repository_module.files
    with monkeypatch.context() as scoped:
        scoped.setattr(
            repository_module,
            "files",
            lambda package: migration_root
            if package == "stock_probs.migrations"
            else original_files(package),
        )
        scoped.setattr(repository_module, "SCHEMA_VERSION", 16)
        repository = Repository(path)
        repository.migrate()
    return repository


def _insert_second_user(repository: Repository) -> None:
    with repository.connect() as connection:
        connection.execute(
            "INSERT INTO users(display_name,role,status,created_at,updated_at) "
            "VALUES ('Second member','member','active',?,?)",
            (STAMP_TEXT, STAMP_TEXT),
        )


def test_schema_17_clean_creation_and_16_upgrade_match_with_one_backup_hook(tmp_path, monkeypatch):
    assert SCHEMA_VERSION == 17
    upgraded = _create_schema_16(
        tmp_path / "upgrade.sqlite3", tmp_path / "schema-16-migrations", monkeypatch
    )
    _, original_outcome_id = _insert_owned_result(upgraded)
    with upgraded.connect() as connection:
        original_owner = tuple(
            connection.execute(
                "SELECT outcome_id,owner_user_id,assigned_at FROM outcome_owners "
                "WHERE outcome_id=?",
                (original_outcome_id,),
            ).fetchone()
        )

    backup_calls: list[int] = []
    upgraded.migrate(before_migration=backup_calls.append)
    upgraded.migrate(before_migration=backup_calls.append)

    clean = Repository(tmp_path / "clean.sqlite3")
    clean_backup_calls: list[int] = []
    clean.migrate(before_migration=clean_backup_calls.append)
    clean.migrate(before_migration=clean_backup_calls.append)

    assert backup_calls == [16]
    assert clean_backup_calls == []
    assert _schema(upgraded) == _schema(clean)
    with upgraded.connect() as connection:
        assert [
            row[0]
            for row in connection.execute("SELECT version FROM schema_migrations ORDER BY version")
        ] == list(range(1, 18))
        assert (
            tuple(
                connection.execute(
                    "SELECT outcome_id,owner_user_id,assigned_at FROM outcome_owners "
                    "WHERE outcome_id=?",
                    (original_outcome_id,),
                ).fetchone()
            )
            == original_owner
        )

    result_id, _ = _insert_owned_result(upgraded)
    appended = upgraded.append_outcome(
        owner_user_id=1,
        result_id=result_id,
        observed_close=101.0,
        observed_return=0.01,
        observed_at=STAMP,
        state="observed",
        note="appended after upgrade",
        comparison_rule="daily-close",
        created_at=STAMP,
    )
    assert appended is not None
    with upgraded.connect() as connection:
        assert tuple(
            connection.execute(
                "SELECT outcome_id,owner_user_id,assigned_at FROM outcome_owners "
                "WHERE outcome_id=?",
                (appended["id"],),
            ).fetchone()
        ) == (appended["id"], 1, STAMP_TEXT)


@pytest.mark.parametrize("foreign_keys", [0, 1])
@pytest.mark.parametrize("recursive_triggers", [0, 1])
def test_outcome_owner_replace_fails_with_foreign_and_recursive_triggers_off_or_on(
    tmp_path, foreign_keys, recursive_triggers
):
    repository = Repository(tmp_path / f"replace-{foreign_keys}-{recursive_triggers}.sqlite3")
    repository.migrate()
    _, outcome_id = _insert_owned_result(repository)
    _insert_second_user(repository)

    with sqlite3.connect(repository.database_path) as connection:
        connection.execute(f"PRAGMA foreign_keys={foreign_keys}")
        connection.execute(f"PRAGMA recursive_triggers={recursive_triggers}")
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == foreign_keys
        assert connection.execute("PRAGMA recursive_triggers").fetchone()[0] == recursive_triggers
        with pytest.raises(sqlite3.IntegrityError, match="outcome ownership is immutable"):
            connection.execute(
                "INSERT OR REPLACE INTO outcome_owners(outcome_id,owner_user_id,assigned_at) "
                "VALUES (?,2,?)",
                (outcome_id, "2026-01-01T00:00:00+00:00"),
            )
    with repository.connect() as connection:
        assert tuple(
            connection.execute(
                "SELECT outcome_id,owner_user_id,assigned_at FROM outcome_owners "
                "WHERE outcome_id=?",
                (outcome_id,),
            ).fetchone()
        ) == (outcome_id, 1, STAMP_TEXT)


def test_owner_mapping_rejects_same_owner_replace_update_and_delete(tmp_path):
    repository = Repository(tmp_path / "immutable-owner.sqlite3")
    repository.migrate()
    _, outcome_id = _insert_owned_result(repository)
    with sqlite3.connect(repository.database_path) as connection:
        with pytest.raises(sqlite3.IntegrityError, match="outcome ownership is immutable"):
            connection.execute(
                "INSERT OR REPLACE INTO outcome_owners(outcome_id,owner_user_id,assigned_at) "
                "VALUES (?,1,?)",
                (outcome_id, "2026-01-01T00:00:00+00:00"),
            )
        with pytest.raises(sqlite3.IntegrityError, match="outcome ownership is immutable"):
            connection.execute(
                "UPDATE outcome_owners SET assigned_at=? WHERE outcome_id=?",
                ("2026-01-01T00:00:00+00:00", outcome_id),
            )
        with pytest.raises(sqlite3.IntegrityError, match="outcome ownership is append-only"):
            connection.execute("DELETE FROM outcome_owners WHERE outcome_id=?", (outcome_id,))
    with repository.connect() as connection:
        assert tuple(
            connection.execute(
                "SELECT owner_user_id,assigned_at FROM outcome_owners WHERE outcome_id=?",
                (outcome_id,),
            ).fetchone()
        ) == (1, STAMP_TEXT)


def test_new_migration_checksum_drift_fails_before_database_work(tmp_path, monkeypatch):
    original = files("stock_probs.migrations")
    migration_root = tmp_path / "changed-migrations"
    migration_root.mkdir()
    for migration in sorted(original.iterdir(), key=lambda item: item.name):
        if migration.name.endswith(".sql"):
            (migration_root / migration.name).write_bytes(migration.read_bytes())
    target = migration_root / "017_outcome_owner_replace_guard.sql"
    target.write_bytes(target.read_bytes() + b"-- changed after its immutable pin\n")
    monkeypatch.setattr(
        repository_module,
        "files",
        lambda package: migration_root
        if package == "stock_probs.migrations"
        else original(package),
    )
    database_path = tmp_path / "must-not-be-opened.sqlite3"

    with pytest.raises(RepositoryDatabaseError, match="immutable checksum"):
        Repository(database_path).migrate()
    assert not database_path.exists()


def test_new_migration_checksum_matches_exact_sql_bytes():
    migration = files("stock_probs.migrations").joinpath("017_outcome_owner_replace_guard.sql")
    assert (
        repository_module.MIGRATION_SHA256[17] == hashlib.sha256(migration.read_bytes()).hexdigest()
    )
