from __future__ import annotations

import hashlib
import json
import sqlite3
import sys
import types
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType

import pytest

from scripts import research_recovery_overlay as overlay

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
BASELINE_REVISION = "5ad2c3fddfce5a5a631b72cd832a53f24757c44a"


def _repository_module(source: bytes, name: str) -> ModuleType:
    """Load one pinned repository source in isolation for migration behavior tests."""

    module = types.ModuleType(name)
    module.__package__ = "stock_probs"
    module.__file__ = f"<{name}>"
    sys.modules[name] = module
    exec(compile(source, module.__file__, "exec"), module.__dict__)  # noqa: S102 - pinned source only
    return module


def _copy_migrations(
    destination: Path,
    baseline_pins: dict[int, str],
    migration14: bytes | None = None,
) -> None:
    """Copy the immutable SQL inputs needed by the isolated migration runner."""

    destination.mkdir(exist_ok=True)
    paths = sorted((REPOSITORY_ROOT / "src/stock_probs/migrations").glob("[0-9][0-9][0-9]_*.sql"))
    selected: dict[int, Path] = {}
    for path in paths:
        version = int(path.name[:3])
        if version <= 13:
            selected[version] = path
    assert sorted(selected) == list(range(1, 14))
    for version, path in selected.items():
        contents = path.read_bytes()
        assert hashlib.sha256(contents).hexdigest() == baseline_pins[version]
        (destination / path.name).write_bytes(contents)
    if migration14 is not None:
        target = destination / "014_research_workspaces.sql"
        target.write_bytes(migration14)


def _schema14_database(tmp_path: Path) -> Path:
    """Create a disposable schema-14 database from the pinned migrations."""

    manifest, _ = overlay.load_manifest()
    baseline_source = overlay._read_reviewed_baseline(REPOSITORY_ROOT)
    migration14 = (REPOSITORY_ROOT / overlay.MIGRATION_PATH).read_bytes()
    files = overlay.build_overlay_files(baseline_source, migration14, manifest)
    baseline_module = _repository_module(
        baseline_source, "stock_probs._r1_schema14_contract_baseline"
    )
    migration_directory = tmp_path / "contract-migrations"
    _copy_migrations(migration_directory, baseline_module.MIGRATION_SHA256)
    baseline_module.files = lambda _package: migration_directory
    database_path = tmp_path / "contract-schema14.sqlite3"
    baseline_module.Repository(database_path).migrate()

    recovery_module = _repository_module(
        files[overlay.BASELINE_REPOSITORY_PATH], "stock_probs._r1_schema14_contract_recovery"
    )
    _copy_migrations(migration_directory, baseline_module.MIGRATION_SHA256, migration14)
    recovery_module.files = lambda _package: migration_directory
    recovery_module.Repository(database_path).migrate()
    return database_path


def _insert_research_records(database_path: Path) -> dict[str, list[tuple[object, ...]]]:
    """Store immutable research data for two owners after schema 14 is applied."""

    expected: dict[str, list[tuple[object, ...]]] = {
        "theses": [],
        "revisions": [],
        "comparisons": [],
    }
    owners = (
        (1, "11111111-1111-4111-8111-111111111111", "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"),
        (2, "22222222-2222-4222-8222-222222222222", "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"),
    )
    with sqlite3.connect(database_path) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        for owner_id, thesis_id, comparison_id in owners:
            idempotency_key = (
                "33333333-3333-4333-8333-333333333333"
                if owner_id == 1
                else "44444444-4444-4444-8444-444444444444"
            )
            first_payload = json.dumps(
                {"instrument": "SHOP.TO", "revision": 1, "thesis": "Revenue growth"},
                sort_keys=True,
                separators=(",", ":"),
            )
            latest_payload = json.dumps(
                {"instrument": "SHOP.TO", "revision": 2, "thesis": "Margin expansion"},
                sort_keys=True,
                separators=(",", ":"),
            )
            comparison_payload = json.dumps(
                {"symbols": ["SHOP.TO", "VFV.TO"], "snapshot": owner_id},
                sort_keys=True,
                separators=(",", ":"),
            )
            request_digest = hashlib.sha256(f"owner-{owner_id}".encode()).hexdigest()
            connection.execute(
                """INSERT INTO research_theses
                (id, owner_user_id, idempotency_key, request_sha256, revision, payload_json,
                 created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    thesis_id,
                    owner_id,
                    idempotency_key,
                    request_digest,
                    2,
                    latest_payload,
                    "2026-10-16T12:00:00+00:00",
                    "2026-10-16T12:30:00+00:00",
                ),
            )
            for revision, payload in ((1, first_payload), (2, latest_payload)):
                connection.execute(
                    """INSERT INTO research_thesis_revisions
                    (thesis_id, owner_user_id, revision, payload_json, recorded_at)
                    VALUES (?, ?, ?, ?, ?)""",
                    (
                        thesis_id,
                        owner_id,
                        revision,
                        payload,
                        f"2026-10-16T12:{revision:02d}:00+00:00",
                    ),
                )
                expected["revisions"].append((thesis_id, owner_id, revision, payload))
            connection.execute(
                """INSERT INTO research_comparisons
                (id, owner_user_id, idempotency_key, payload_json, created_at)
                VALUES (?, ?, ?, ?, ?)""",
                (
                    comparison_id,
                    owner_id,
                    "55555555-5555-4555-8555-555555555555"
                    if owner_id == 1
                    else "66666666-6666-4666-8666-666666666666",
                    comparison_payload,
                    "2026-10-16T12:45:00+00:00",
                ),
            )
            expected["theses"].append((thesis_id, owner_id, 2, latest_payload))
            expected["comparisons"].append((comparison_id, owner_id, comparison_payload))
    return expected


def test_manifest_pins_reviewed_baseline_migration_and_disabled_controls() -> None:
    """The overlay manifest binds its exact source and leaves new controls off."""

    manifest, raw = overlay.load_manifest()
    assert json.loads(raw) == manifest
    assert manifest["baseline"]["revision"] == BASELINE_REVISION
    assert manifest["migration"]["sha256"] == overlay.MIGRATION_SHA256
    assert manifest["overlay"]["source_paths"] == [
        "src/stock_probs/repository.py",
        "src/stock_probs/migrations/014_research_workspaces.sql",
    ]
    assert manifest["controls"] == {
        "assistant_enabled": False,
        "research_features_enabled": False,
        "automatic_pair_rollout_enabled": False,
        "schema13_backup_promotion_enabled": False,
    }


def test_prepare_overlay_materializes_only_the_two_pinned_source_paths(tmp_path: Path) -> None:
    """Preparation emits exact private overlay files without building or publishing."""

    destination = tmp_path / "schema14-overlay"
    receipt = overlay.prepare_overlay(REPOSITORY_ROOT, destination)
    assert receipt["status"] == "prepared"
    assert receipt["built_or_published"] is False
    assert receipt["overlay_sha256"] == overlay.OVERLAY_SHA256
    assert sorted(
        path.relative_to(destination).as_posix()
        for path in destination.rglob("*")
        if path.is_file()
    ) == [
        "manifest.json",
        "src/stock_probs/migrations/014_research_workspaces.sql",
        "src/stock_probs/repository.py",
    ]
    repository = (destination / "src/stock_probs/repository.py").read_bytes()
    assert b"SCHEMA_VERSION = 14" in repository
    assert f'14: "{overlay.MIGRATION_SHA256}"'.encode() in repository
    assert hashlib.sha256(repository).hexdigest() == overlay.OVERLAY_REPOSITORY_SHA256
    assert (destination / "manifest.json").read_bytes() == overlay.MANIFEST_PATH.read_bytes()
    assert destination.stat().st_mode & 0o777 == 0o700
    assert all(
        path.stat().st_mode & 0o777 == 0o700 for path in destination.rglob("*") if path.is_dir()
    )
    assert all(
        path.stat().st_mode & 0o777 == 0o600 for path in destination.rglob("*") if path.is_file()
    )


def test_schema13_upgrade_and_recovery_reader_preserve_postmigration_owner_data(
    tmp_path: Path,
) -> None:
    """Schema 14 startup skips migration 14 and retains each owner's complete research rows."""

    manifest, _ = overlay.load_manifest()
    baseline_source = overlay._read_reviewed_baseline(REPOSITORY_ROOT)
    migration14 = (REPOSITORY_ROOT / overlay.MIGRATION_PATH).read_bytes()
    files = overlay.build_overlay_files(baseline_source, migration14, manifest)
    baseline_module = _repository_module(baseline_source, "stock_probs._r1_schema13_baseline")
    migration_directory = tmp_path / "migrations"
    _copy_migrations(migration_directory, baseline_module.MIGRATION_SHA256)
    baseline_module.files = lambda _package: migration_directory
    database_path = tmp_path / "portfolio.sqlite3"
    baseline_module.Repository(database_path).migrate()

    with sqlite3.connect(database_path) as connection:
        assert connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone() == (13,)
        connection.execute(
            """INSERT INTO forecast_runs
            (symbol, asset_type, content_fingerprint, created_at)
            VALUES (?, ?, ?, ?)""",
            ("ACDC", "stock", "preserved-before-v14", "2026-10-15T14:00:00+00:00"),
        )
    baseline_module.Repository(database_path).create_user(
        github_user_id=202,
        login="second-owner",
        display_name="Second Owner",
        password_hash=None,
        created_at=datetime(2026, 10, 15, tzinfo=UTC),
    )

    recovery_source = files["src/stock_probs/repository.py"]
    recovery_module = _repository_module(recovery_source, "stock_probs._r1_schema14_recovery")
    _copy_migrations(migration_directory, baseline_module.MIGRATION_SHA256, migration14)
    recovery_module.files = lambda _package: migration_directory
    recovery_repository = recovery_module.Repository(database_path)
    recovery_repository.migrate()
    with sqlite3.connect(database_path) as connection:
        migration14_applied_at = connection.execute(
            "SELECT applied_at FROM schema_migrations WHERE version = 14"
        ).fetchone()[0]
        assert connection.execute(
            "SELECT symbol, content_fingerprint FROM forecast_runs"
        ).fetchall() == [("ACDC", "preserved-before-v14")]
        assert connection.execute("SELECT id FROM users ORDER BY id").fetchall() == [(1,), (2,)]

    expected = _insert_research_records(database_path)
    recovery_repository.migrate()
    with overlay.open_schema14_recovery_reader(database_path) as reader:
        assert (
            reader.execute(
                "SELECT applied_at FROM schema_migrations WHERE version = 14"
            ).fetchone()[0]
            == migration14_applied_at
        )
        assert tuple(
            reader.execute("SELECT symbol, content_fingerprint FROM forecast_runs").fetchone()
        ) == ("ACDC", "preserved-before-v14")
        actual_theses = [
            tuple(row)
            for row in reader.execute(
                "SELECT id, owner_user_id, revision, payload_json FROM research_theses ORDER BY id"
            )
        ]
        actual_revisions = [
            tuple(row)
            for row in reader.execute(
                """SELECT thesis_id, owner_user_id, revision, payload_json
                FROM research_thesis_revisions ORDER BY thesis_id, revision"""
            )
        ]
        actual_comparisons = [
            tuple(row)
            for row in reader.execute(
                "SELECT id, owner_user_id, payload_json FROM research_comparisons ORDER BY id"
            )
        ]
        assert actual_theses == sorted(expected["theses"])
        assert actual_revisions == sorted(expected["revisions"])
        assert actual_comparisons == sorted(expected["comparisons"])
        with pytest.raises(sqlite3.OperationalError):
            reader.execute(
                "INSERT INTO research_comparisons "
                "(id, owner_user_id, idempotency_key, payload_json, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    "77777777-7777-4777-8777-777777777777",
                    1,
                    "88888888-8888-4888-8888-888888888888",
                    "{}",
                    "2026-10-16T13:00:00+00:00",
                ),
            )


def test_recovery_snapshot_is_canonical_and_includes_assistant_rows(tmp_path: Path) -> None:
    """The bounded read-only fingerprint binds migrations and retained assistant content."""

    database_path = _schema14_database(tmp_path)
    with sqlite3.connect(database_path) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute(
            """INSERT INTO assistant_conversations
            (id, user_id, title, context_json, context_version, revision, created_at, updated_at)
            VALUES (?, 1, ?, '{}', ?, 1, ?, ?)""",
            (
                "77777777-7777-4777-8777-777777777777",
                "Retention fixture",
                "a" * 64,
                "2026-10-16T12:00:00+00:00",
                "2026-10-16T12:00:00+00:00",
            ),
        )
        connection.execute(
            """INSERT INTO assistant_turns
            (id, conversation_id, user_id, status, model_id, policy_version, context_json,
             context_version, created_at, started_at, completed_at)
            VALUES (?, ?, 1, 'completed', 'fixture', 'v1', '{}', ?, ?, ?, ?)""",
            (
                "88888888-8888-4888-8888-888888888888",
                "77777777-7777-4777-8777-777777777777",
                "a" * 64,
                "2026-10-16T12:00:00+00:00",
                "2026-10-16T12:00:01+00:00",
                "2026-10-16T12:00:02+00:00",
            ),
        )
        connection.execute(
            """INSERT INTO assistant_messages
            (id, conversation_id, turn_id, user_id, sequence, role, content, created_at)
            VALUES (?, ?, ?, 1, 1, 'assistant', ?, ?)""",
            (
                "99999999-9999-4999-8999-999999999999",
                "77777777-7777-4777-8777-777777777777",
                "88888888-8888-4888-8888-888888888888",
                "synthetic retained assistant content",
                "2026-10-16T12:00:02+00:00",
            ),
        )
    with overlay.open_schema14_recovery_reader(database_path) as reader:
        first = overlay.recovery_database_snapshot(reader)
    with overlay.open_schema14_recovery_reader(database_path) as reader:
        assert overlay.recovery_database_snapshot(reader) == first
    assert first["schema_versions"] == list(range(1, 15))
    tables = first["tables"]
    assert isinstance(tables, dict)
    assert tables["assistant_conversations"]["rows"] == 1
    assert tables["assistant_messages"]["rows"] == 1

    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """INSERT INTO assistant_messages
            (id, conversation_id, turn_id, user_id, sequence, role, content, created_at)
            VALUES (?, ?, ?, 1, 2, 'assistant', ?, ?)""",
            (
                "abababab-abab-4bab-8bab-abababababab",
                "77777777-7777-4777-8777-777777777777",
                "88888888-8888-4888-8888-888888888888",
                "second retained assistant row",
                "2026-10-16T12:00:03+00:00",
            ),
        )
    with overlay.open_schema14_recovery_reader(database_path) as reader:
        changed = overlay.recovery_database_snapshot(reader)
    assert changed["tables"]["schema_migrations"]["sha256"] == tables["schema_migrations"]["sha256"]
    assert (
        changed["tables"]["assistant_messages"]["sha256"] != tables["assistant_messages"]["sha256"]
    )
    assert changed["sha256"] != first["sha256"]

    with sqlite3.connect(database_path) as connection:
        connection.execute("CREATE TABLE unexpected_content (value TEXT NOT NULL)")
    with (
        overlay.open_schema14_recovery_reader(database_path) as reader,
        pytest.raises(overlay.RecoveryOverlayError, match="recovery_database_tables_unexpected"),
    ):
        overlay.recovery_database_snapshot(reader)


def test_malformed_manifest_pin_and_unreviewed_baseline_fail_closed() -> None:
    """Neither an altered manifest pin nor changed baseline bytes can generate an overlay."""

    manifest, _ = overlay.load_manifest()
    baseline = overlay._read_reviewed_baseline(REPOSITORY_ROOT)
    migration = (REPOSITORY_ROOT / overlay.MIGRATION_PATH).read_bytes()
    malformed = json.loads(json.dumps(manifest))
    malformed["migration"]["sha256"] = "0" * 64
    with pytest.raises(overlay.RecoveryOverlayError, match="overlay_manifest_invalid"):
        overlay.build_overlay_files(baseline, migration, malformed)
    with pytest.raises(overlay.RecoveryOverlayError, match="overlay_baseline_mismatch"):
        overlay.build_overlay_files(baseline + b"# changed\n", migration, manifest)
    with pytest.raises(overlay.RecoveryOverlayError, match="overlay_migration_mismatch"):
        overlay.build_overlay_files(baseline, migration + b"\n", manifest)


def test_schema13_database_is_not_promoted_and_missing_research_table_is_rejected(
    tmp_path: Path,
) -> None:
    """The read-only schema-14 reader rejects schema-13 state and incomplete schema-14 state."""

    for filename, version, missing_table in (
        ("schema13.sqlite3", 13, None),
        ("schema14-missing-table.sqlite3", 14, "research_comparisons"),
    ):
        database_path = tmp_path / filename
        with sqlite3.connect(database_path) as connection:
            connection.execute(
                "CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT)"
            )
            connection.executemany(
                "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                [(item, f"2026-10-16T00:{item:02d}:00+00:00") for item in range(1, version + 1)],
            )
            tables = overlay.RESEARCH_TABLES - ({missing_table} if missing_table else set())
            for table in tables:
                connection.execute(f'CREATE TABLE "{table}" (id TEXT PRIMARY KEY)')

        with pytest.raises(overlay.RecoveryOverlayError):
            overlay.open_schema14_recovery_reader(database_path)


def test_schema14_reader_rejects_research_tables_without_core_baseline(tmp_path: Path) -> None:
    """Research table names and migration numbers cannot replace the schema-13 baseline."""

    database_path = tmp_path / "missing-core-baseline.sqlite3"
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            "CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
        )
        connection.executemany(
            "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
            [(version, f"2026-10-16T00:{version:02d}:00+00:00") for version in range(1, 15)],
        )
        for table in overlay.RESEARCH_TABLES:
            connection.execute(f'CREATE TABLE "{table}" (id TEXT PRIMARY KEY)')

    with pytest.raises(overlay.RecoveryOverlayError, match="recovery_database_tables_missing"):
        overlay.open_schema14_recovery_reader(database_path)


def test_schema14_reader_rejects_missing_core_column(tmp_path: Path) -> None:
    """A migration receipt sequence cannot mask a malformed core table definition."""

    database_path = _schema14_database(tmp_path)
    malformed_path = tmp_path / "missing-core-column.sqlite3"
    with sqlite3.connect(database_path) as source, sqlite3.connect(malformed_path) as target:
        source.backup(target)
    with sqlite3.connect(malformed_path) as connection:
        connection.execute("DROP TABLE forecast_runs")
        connection.execute(
            """CREATE TABLE forecast_runs (
                id INTEGER PRIMARY KEY,
                symbol TEXT NOT NULL,
                asset_type TEXT NOT NULL,
                created_at TEXT NOT NULL
            )"""
        )

    with pytest.raises(overlay.RecoveryOverlayError, match="recovery_database_columns_missing"):
        overlay.open_schema14_recovery_reader(malformed_path)
