"""M04 domain/service/persistence tests cover rich bounded history data contracts."""

from __future__ import annotations

import json
import random
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from importlib.resources import files

import pytest

from stock_probs.domain import HistoryFilters, calculate_forecasts
from stock_probs.provider import FixtureProvider
from stock_probs.repository import HISTORY_EXPORT_LIMIT, Repository
from stock_probs.service import ForecastService

NOW = datetime(2025, 1, 10, 17, 3, tzinfo=UTC)


def _repository(settings) -> Repository:
    repository = Repository(settings.database_path)
    repository.migrate()
    return repository


def _forecast_payload(symbol: str, asset_type: str):
    return calculate_forecasts(FixtureProvider().fetch(symbol, asset_type, NOW), NOW)


def _record_success(
    repository: Repository,
    request_id: str,
    symbol: str,
    asset_type: str,
    submitted_at: datetime,
    *,
    analysis_kind: str = "submitted_forecast",
    source_event_id: int | None = None,
):
    snapshot, results = _forecast_payload(symbol, asset_type)
    if analysis_kind == "fresh_historical_reconstruction":
        # Fresh analysis always owns a new immutable run, even when this fixture's bars match.
        snapshot["content_fingerprint"] = "f" * 64
        snapshot["provenance"]["content_fingerprint"] = "f" * 64
    return repository.record_success(
        request_id=request_id,
        submitted_symbol=symbol,
        asset_type=asset_type,
        input_snapshot=snapshot,
        results=results,
        submitted_at=submitted_at,
        completed_at=submitted_at + timedelta(seconds=1),
        analysis_kind=analysis_kind,
        source_event_id=source_event_id,
        requested_cutoff=NOW if analysis_kind == "fresh_historical_reconstruction" else None,
        reuse_exact_input=analysis_kind != "fresh_historical_reconstruction",
    )


def test_history_filters_identity_semantics_dates_model_and_request_id(settings):
    repository = _repository(settings)
    first_id, _, _, _ = _record_success(
        repository, "acdc-first", "ACDC", "stock", NOW - timedelta(days=3)
    )
    repeat_id, _, repeated, reused = _record_success(
        repository, "acdc-repeat", "ACDC", "stock", NOW - timedelta(days=2)
    )
    spy_id, _, _, _ = _record_success(
        repository, "spy-first", "SPY", "etf", NOW - timedelta(days=1)
    )
    fresh_id, _, fresh_repeated, fresh_reused = _record_success(
        repository,
        "acdc-fresh",
        "ACDC",
        "stock",
        NOW,
        analysis_kind="fresh_historical_reconstruction",
        source_event_id=first_id,
    )
    repository.record_failure(
        request_id="failure-first",
        submitted_symbol="FAIL",
        normalized_symbol="FAIL",
        asset_type="stock",
        error_code="provider_unavailable",
        error_message="fixture failure",
        submitted_at=NOW + timedelta(hours=1),
        completed_at=NOW + timedelta(hours=1, seconds=1),
    )
    repository.record_failure(
        request_id="failure-repeat",
        submitted_symbol="FAIL",
        normalized_symbol="FAIL",
        asset_type="stock",
        error_code="provider_unavailable",
        error_message="fixture failure",
        submitted_at=NOW + timedelta(hours=2),
        completed_at=NOW + timedelta(hours=2, seconds=1),
    )

    assert repeated is reused is True
    assert fresh_repeated is True and fresh_reused is False
    assert repository.history(query="ProFrac")["total"] == 3
    assert repository.history(symbol="spy")["items"][0]["id"] == spy_id
    assert repository.history(company="S&P 500")["total"] == 1
    assert repository.history(asset_type="etf")["total"] == 1
    assert repository.history(status="failed")["total"] == 2
    assert repository.history(semantics="success")["total"] == 4
    assert repository.history(semantics="failure")["total"] == 2
    assert repository.history(semantics="repeat")["total"] == 3
    assert repository.history(semantics="fresh")["items"][0]["id"] == fresh_id
    assert repository.history(semantics="saved")["total"] == 3
    assert repository.history(
        date_from=NOW - timedelta(days=2), date_to=NOW - timedelta(days=1)
    )["total"] == 2
    assert repository.history(model="volatility-adjusted empirical distribution")["total"] == 4
    assert repository.history(model_version="empirical-ewma-v2")["total"] == 4
    assert repository.history(request_id="acdc-repeat")["items"][0]["id"] == repeat_id

    rich = repository.history(symbol="ACDC", include_analysis=True, include_facets=True)
    assert [item["id"] for item in rich["items"]] == [fresh_id, repeat_id, first_id]
    assert all(item["company_name"] == "ProFrac Holding Corp." for item in rich["items"])
    assert all(item["model_version"] == "empirical-ewma-v2" for item in rich["items"])
    first_page = repository.history(page=1, page_size=2)["items"]
    second_page = repository.history(page=2, page_size=2)["items"]
    assert [item["id"] for item in first_page] == sorted(
        (item["id"] for item in first_page), reverse=True
    )
    assert {item["id"] for item in first_page}.isdisjoint(
        item["id"] for item in second_page
    )


def test_filter_boundaries_reject_ambiguous_or_unbounded_values():
    invalid = [
        {"query": "x" * 31},
        {"symbol": "../SPY"},
        {"company": "\ncompany"},
        {"asset_type": "crypto"},
        {"status": "ok"},
        {"semantics": "recalculated"},
        {"date_from": NOW.replace(tzinfo=None)},
        {"date_from": NOW, "date_to": NOW - timedelta(seconds=1)},
        {"model": "x" * 121},
        {"model_version": "x" * 81},
        {"request_id": "x" * 129},
        {"event_id": 0},
        {"event_id": 2_147_483_648},
        {"event_id": True},
    ]
    for values in invalid:
        with pytest.raises(ValueError):
            HistoryFilters(**values)

    assert HistoryFilters(symbol=" spy ", company=" SPDR ").symbol == "SPY"
    assert HistoryFilters(company=" SPDR ").company == "SPDR"


def test_exact_event_export_filters_before_cap_and_intersects_every_indexed_filter(settings):
    """An old exact event remains selectable after newer rows exceed the export ceiling."""

    repository = _repository(settings)
    oldest_id = repository.record_failure(
        request_id="oldest-selected",
        submitted_symbol="FAIL",
        normalized_symbol="FAIL",
        asset_type="stock",
        error_code="provider_unavailable",
        error_message="oldest failed fixture",
        submitted_at=NOW,
        completed_at=NOW + timedelta(seconds=1),
    )
    for index in range(HISTORY_EXPORT_LIMIT):
        repository.record_failure(
            request_id=f"newer-{index}",
            submitted_symbol="FAIL",
            normalized_symbol="FAIL",
            asset_type="stock",
            error_code="provider_unavailable",
            error_message="newer failed fixture",
            submitted_at=NOW + timedelta(minutes=index + 1),
            completed_at=NOW + timedelta(minutes=index + 1, seconds=1),
        )

    selected = repository.history_export(
        generated_at=NOW,
        event_id=oldest_id,
        request_id="oldest-selected",
        status="failed",
        date_from=NOW,
        date_to=NOW,
    )

    assert selected["filters"]["event_id"] == oldest_id
    assert selected["total_events"] == selected["exported_events"] == 1
    assert selected["counts"] == {"events": 1, "runs": 0, "results": 0}
    assert selected["truncated"] is False
    assert [(record["record_type"], record["event_id"]) for record in selected["records"]] == [
        ("event", oldest_id)
    ]
    for mismatch in (
        {"request_id": "newer-0"},
        {"status": "successful"},
        {"date_from": NOW + timedelta(microseconds=1)},
        {"date_to": NOW - timedelta(microseconds=1)},
    ):
        empty = repository.history_export(
            generated_at=NOW, event_id=oldest_id, **mismatch
        )
        assert empty["total_events"] == empty["exported_events"] == 0
        assert empty["records"] == [] and empty["truncated"] is False

    unknown = repository.history_export(generated_at=NOW, event_id=2_147_483_647)
    assert unknown["counts"] == {"events": 0, "runs": 0, "results": 0}
    assert unknown["total_events"] == 0 and unknown["truncated"] is False


def test_exact_event_export_preserves_repeat_saved_and_fresh_semantics(settings):
    repository = _repository(settings)
    saved_id, _, _, _ = _record_success(
        repository, "saved-first", "ACDC", "stock", NOW
    )
    repeated_id, _, repeated, reused = _record_success(
        repository, "saved-repeat", "ACDC", "stock", NOW + timedelta(minutes=1)
    )
    fresh_id, _, fresh_repeated, fresh_reused = _record_success(
        repository,
        "fresh-analysis",
        "ACDC",
        "stock",
        NOW + timedelta(minutes=2),
        analysis_kind="fresh_historical_reconstruction",
        source_event_id=saved_id,
    )

    assert repeated is reused is True
    assert fresh_repeated is True and fresh_reused is False
    cases = (
        (saved_id, "saved", 1),
        (saved_id, "repeat", 0),
        (repeated_id, "saved", 1),
        (repeated_id, "repeat", 1),
        (fresh_id, "fresh", 1),
        (fresh_id, "saved", 0),
        (fresh_id, "repeat", 1),
    )
    for event_id, semantics, expected in cases:
        exported = repository.history_export(
            generated_at=NOW, event_id=event_id, semantics=semantics
        )
        assert exported["total_events"] == expected
        assert exported["counts"]["events"] == expected
        assert exported["truncated"] is False
        if expected:
            assert next(
                record["event_id"]
                for record in exported["records"]
                if record["record_type"] == "event"
            ) == event_id


def test_property_style_filter_intersections_match_audit_rows(settings):
    """Randomized combinations pin inclusive UTC dates and repeat/failure intersections."""

    repository = _repository(settings)
    generator = random.Random(404)  # noqa: S311 - deterministic property-case selection only.
    symbols = ("BAD1", "BAD2", "BAD3", "BAD4")
    for index in range(80):
        symbol = generator.choice(symbols)
        asset_type = generator.choice(("stock", "etf"))
        submitted = NOW + timedelta(minutes=index)
        repository.record_failure(
            request_id=f"property-{index}",
            submitted_symbol=symbol,
            normalized_symbol=symbol,
            asset_type=asset_type,
            error_code="fixture_failure",
            error_message="property fixture",
            submitted_at=submitted,
            completed_at=submitted + timedelta(seconds=1),
        )
    baseline = repository.history(page_size=100)["items"]

    for _ in range(40):
        asset = generator.choice((None, "stock", "etf"))
        repeat_only = generator.choice((False, True))
        lower = generator.randrange(0, 60)
        upper = generator.randrange(lower, 80)
        date_from = NOW + timedelta(minutes=lower)
        date_to = NOW + timedelta(minutes=upper)
        expected = [
            item
            for item in baseline
            if (asset is None or item["asset_type"] == asset)
            and (not repeat_only or item["is_repeat"])
            and date_from <= datetime.fromisoformat(item["submitted_at"]) <= date_to
        ]
        actual = repository.history(
            asset_type=asset,
            semantics="repeat" if repeat_only else "failure",
            date_from=date_from,
            date_to=date_to,
            page_size=100,
        )
        assert actual["total"] == len(expected)
        assert [item["id"] for item in actual["items"]] == [item["id"] for item in expected]


def test_restart_saved_detail_series_export_and_outcomes_are_faithful(settings):
    repository = _repository(settings)
    service = ForecastService(repository, FixtureProvider(), lambda: NOW)
    created = service.search("ACDC", "stock")
    result_id = created["results"][0]["id"]
    outcome = service.append_outcome(
        result_id,
        24.75,
        datetime(2025, 1, 13, 21, 1, tzinfo=UTC),
        "observed",
        "official close",
    )
    assert outcome is not None
    repository.record_failure(
        request_id="formula-source",
        submitted_symbol="=DANGEROUS()",
        normalized_symbol=None,
        asset_type="stock",
        error_code="invalid_symbol",
        error_message="safe failure",
        submitted_at=NOW,
        completed_at=NOW,
    )

    class ProviderMustNotRun(FixtureProvider):
        def fetch(self, *args, **kwargs):
            pytest.fail("saved history retrieval must not call the provider")

    restarted_repository = Repository(settings.database_path)
    restarted_repository.migrate()
    restarted = ForecastService(restarted_repository, ProviderMustNotRun(), lambda: NOW)
    saved = restarted.saved_forecast(created["event"]["id"])
    detail = restarted.history_detail(created["event"]["id"])
    series = restarted.historical_series(created["event"]["id"], limit=7)
    exported = restarted.history_export()
    selected_export = restarted.history_export(event_id=created["event"]["id"])
    outcomes = restarted_repository.outcome_history(result_id, page_size=1)

    assert saved is not None and detail is not None and series is not None
    assert saved["immutable"] is True and saved["recalculated"] is False
    assert saved["input"] == created["input"]
    assert detail["results"][0]["evaluation"]["forecast_model"]["reliability"]
    assert detail["results"][0]["outcomes"] == [outcome]
    assert len(series["items"]) == 7 and series["total_available"] > 7
    assert series["items"] == detail["input"]["selected_daily_bars"][-7:]
    assert exported["generated_at"] == NOW.isoformat()
    assert selected_export["counts"] == {"events": 1, "runs": 1, "results": 2}
    assert selected_export["filters"]["event_id"] == created["event"]["id"]
    assert selected_export["truncated"] is False
    formula_event = next(
        record
        for record in exported["records"]
        if record["record_type"] == "event" and record["data"]["request_id"] == "formula-source"
    )
    # The source stream is lossless; the transport layer can safely quote this exact CSV cell.
    assert formula_event["data"]["submitted_symbol"] == "=DANGEROUS()"
    assert json.loads(json.dumps(exported, allow_nan=False)) == exported
    assert outcomes["total"] == 1 and outcomes["items"] == [outcome]


def test_bulk_export_query_count_is_constant_and_memory_is_capped(settings, monkeypatch):
    repository = _repository(settings)
    snapshot, results = _forecast_payload("ACDC", "stock")
    for index in range(20):
        unique_snapshot = deepcopy(snapshot)
        fingerprint = f"{index:064x}"
        unique_snapshot["content_fingerprint"] = fingerprint
        unique_snapshot["provenance"]["content_fingerprint"] = fingerprint
        event_id, _, _, _ = repository.record_success(
            request_id=f"unique-{index}",
            submitted_symbol="ACDC",
            asset_type="stock",
            input_snapshot=unique_snapshot,
            results=results,
            submitted_at=NOW + timedelta(seconds=index),
            completed_at=NOW + timedelta(seconds=index + 1),
        )
        detail = repository.reconstruction(event_id)
        assert detail is not None
        repository.append_outcome(
            detail["results"][0]["id"],
            24.0,
            0.01,
            NOW + timedelta(days=3),
            "observed",
            "bulk fixture",
            "fixed comparison",
            NOW + timedelta(days=3),
        )

    statements: list[str] = []
    original_connect = repository.connect

    @contextmanager
    def traced_connect():
        with original_connect() as connection:
            connection.set_trace_callback(statements.append)
            yield connection

    monkeypatch.setattr(repository, "connect", traced_connect)
    exported = repository.history_export(generated_at=NOW)
    reads = [
        statement
        for statement in statements
        if statement.lstrip().upper().startswith(("SELECT", "WITH"))
    ]

    assert exported["counts"] == {"events": 20, "runs": 20, "results": 40}
    assert len(reads) == 5
    assert exported["exported_events"] <= HISTORY_EXPORT_LIMIT
    assert sum(record["record_type"] == "event" for record in exported["records"]) <= 100


def test_concurrent_audit_writes_and_bounded_reads_remain_complete(settings):
    repository = _repository(settings)

    def write(index: int) -> tuple[int, int]:
        symbol = f"C{index % 5}"
        return (
            index,
            repository.record_failure(
                request_id=f"concurrent-{index}",
                submitted_symbol=symbol,
                normalized_symbol=symbol,
                asset_type="stock",
                error_code="fixture_failure",
                error_message="concurrent fixture",
                submitted_at=NOW + timedelta(microseconds=index),
                completed_at=NOW + timedelta(seconds=1, microseconds=index),
            ),
        )

    with ThreadPoolExecutor(max_workers=8) as workers:
        writes = [workers.submit(write, index) for index in range(100)]
        reads = [workers.submit(repository.history, page_size=7) for _ in range(20)]
        indexed_event_ids = [future.result(timeout=10) for future in writes]
        for read in reads:
            payload = read.result(timeout=10)
            assert len(payload["items"]) <= 7

    first = repository.history(page=1, page_size=50)
    second = repository.history(page=2, page_size=50)
    assert first["total"] == second["total"] == 100
    assert len({event_id for _, event_id in indexed_event_ids}) == 100
    expected = [event_id for _, event_id in sorted(indexed_event_ids, reverse=True)]
    assert [item["id"] for item in first["items"] + second["items"]] == expected
    assert repository.history(semantics="repeat")["total"] == 95


@pytest.mark.parametrize("starting_version", [1, 2, 3])
def test_migration_004_preserves_exact_legacy_microseconds_and_canonical_rows(
    settings, tmp_path, starting_version
):
    """Every supported upgrade path normalizes ISO spelling without losing its fraction."""

    snapshot, results = _forecast_payload("SPY", "etf")
    migration_dir = files("stock_probs.migrations")
    timestamps = [
        ("no-fraction", "2025-01-10T17:03:00+00:00", 0),
        ("fraction-1", "2025-01-10T17:03:00.1Z", 100_000),
        ("fraction-2", "2025-01-10T17:03:00.12Z", 120_000),
        ("fraction-3", "2025-01-10T17:03:00.123Z", 123_000),
        ("fraction-4", "2025-01-10T17:03:00.1234Z", 123_400),
        ("fraction-5", "2025-01-10T17:03:00.12345Z", 123_450),
        ("fraction-123456", "2025-01-10T17:03:00.123456+00:00", 123_456),
        ("fraction-000001", "2025-01-10T17:03:00.000001Z", 1),
        ("fraction-999999-offset", "2025-01-10T12:03:00.999999-05:00", 999_999),
        ("positive-offset", "2025-01-10T22:33:00.654321+05:30", 654_321),
        ("equal-instant-offset", "2025-01-10T12:03:00.123456-05:00", 123_456),
    ]
    original_search_columns = (
        "id, request_id, submitted_symbol, normalized_symbol, asset_type, status, is_repeat, "
        "error_code, error_message, run_id, submitted_at, completed_at"
    )
    with sqlite3.connect(settings.database_path) as connection:
        connection.execute(
            "CREATE TABLE schema_migrations "
            "(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)"
        )
        migrations = (
            (1, "001_initial.sql"),
            (2, "002_historical_analysis.sql"),
            (3, "003_restore_and_immutability_guards.sql"),
        )
        for version, name in migrations[:starting_version]:
            connection.executescript(migration_dir.joinpath(name).read_text())
            connection.execute(
                "INSERT INTO schema_migrations(version, applied_at) VALUES (?, ?)",
                (version, NOW.isoformat()),
            )
        run_id = connection.execute(
            "INSERT INTO forecast_runs(symbol, asset_type, content_fingerprint, created_at) "
            "VALUES ('SPY', 'etf', ?, ?)",
            (snapshot["content_fingerprint"], NOW.isoformat()),
        ).lastrowid
        input_id = connection.execute(
            "INSERT INTO forecast_inputs(run_id, snapshot_json, created_at) VALUES (?, ?, ?)",
            (run_id, json.dumps(snapshot), NOW.isoformat()),
        ).lastrowid
        connection.executemany(
            "INSERT INTO forecast_results(input_id, horizon, result_json, created_at) "
            "VALUES (?, ?, ?, ?)",
            [(input_id, item["horizon"], json.dumps(item), NOW.isoformat()) for item in results],
        )
        connection.execute(
            """INSERT INTO search_events
            (request_id, submitted_symbol, normalized_symbol, asset_type, status, is_repeat,
             run_id, submitted_at, completed_at)
            VALUES ('legacy-spy', 'SPY', 'SPY', 'etf', 'successful', 0, ?, ?, ?)""",
            (run_id, timestamps[6][1], timestamps[6][1]),
        )
        for request_id, submitted_at, _ in timestamps:
            if request_id == "fraction-123456":
                continue
            connection.execute(
                """INSERT INTO search_events
                (request_id, submitted_symbol, normalized_symbol, asset_type, status, is_repeat,
                 error_code, error_message, submitted_at, completed_at)
                VALUES (?, 'FAIL', 'FAIL', 'stock', 'failed', 0, 'legacy',
                        'legacy fixture', ?, ?)""",
                (request_id, submitted_at, submitted_at),
            )
        canonical_before = {
            "search_events": connection.execute(
                f"SELECT {original_search_columns} FROM search_events ORDER BY id"  # noqa: S608
            ).fetchall(),
            "forecast_runs": connection.execute(
                "SELECT * FROM forecast_runs ORDER BY id"
            ).fetchall(),
            "forecast_inputs": connection.execute(
                "SELECT * FROM forecast_inputs ORDER BY id"
            ).fetchall(),
            "forecast_results": connection.execute(
                "SELECT * FROM forecast_results ORDER BY id"
            ).fetchall(),
            "outcomes": connection.execute("SELECT * FROM outcomes ORDER BY id").fetchall(),
        }

    repository = Repository(settings.database_path)
    repository.migrate()
    repository.migrate()
    clean = Repository(tmp_path / f"clean-v{starting_version}.sqlite3")
    clean.migrate()
    result = repository.history(
        company="SPDR S&P 500", model_version="empirical-ewma-v2", include_facets=True
    )
    assert result["total"] == 1
    assert result["items"][0]["company_name"] == "SPDR S&P 500 ETF Trust"

    epoch_us = 1_736_528_580_000_000
    with repository.connect() as connection, clean.connect() as clean_connection:
        stored = connection.execute(
            """SELECT event.request_id, event.id, facet.submitted_at_us
            FROM search_events AS event JOIN history_facets AS facet ON facet.event_id = event.id"""
        ).fetchall()
        expected_fractions = {name: fraction for name, _, fraction in timestamps}
        expected_fractions["legacy-spy"] = expected_fractions.pop("fraction-123456")
        assert {row["request_id"]: row["submitted_at_us"] for row in stored} == {
            name: epoch_us + fraction for name, fraction in expected_fractions.items()
        }
        stored_ids = {row["request_id"]: row["id"] for row in stored}
        canonical_after = {
            "search_events": connection.execute(
                f"SELECT {original_search_columns} FROM search_events ORDER BY id"  # noqa: S608
            ).fetchall(),
            "forecast_runs": connection.execute(
                "SELECT * FROM forecast_runs ORDER BY id"
            ).fetchall(),
            "forecast_inputs": connection.execute(
                "SELECT * FROM forecast_inputs ORDER BY id"
            ).fetchall(),
            "forecast_results": connection.execute(
                "SELECT * FROM forecast_results ORDER BY id"
            ).fetchall(),
            "outcomes": connection.execute("SELECT * FROM outcomes ORDER BY id").fetchall(),
        }
        assert {
            table: [tuple(row) for row in rows] for table, rows in canonical_after.items()
        } == {table: [tuple(row) for row in rows] for table, rows in canonical_before.items()}
        schema_sql = connection.execute(
            "SELECT type, name, tbl_name, sql FROM sqlite_master "
            "WHERE name NOT LIKE 'sqlite_%' ORDER BY type, name"
        ).fetchall()
        clean_schema_sql = clean_connection.execute(
            "SELECT type, name, tbl_name, sql FROM sqlite_master "
            "WHERE name NOT LIKE 'sqlite_%' ORDER BY type, name"
        ).fetchall()
        assert [tuple(row) for row in schema_sql] == [tuple(row) for row in clean_schema_sql]
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            connection.execute(
                "UPDATE history_facets SET company_name = 'rewritten' WHERE event_id = ?",
                (result["items"][0]["id"],),
            )

    expected_order = sorted(
        expected_fractions,
        key=lambda name: (expected_fractions[name], stored_ids[name]),
        reverse=True,
    )
    assert [
        item["request_id"] for item in repository.history(page_size=100)["items"]
    ] == expected_order
    exact = datetime(2025, 1, 10, 17, 3, 0, 123456, tzinfo=UTC)
    exact_matches = repository.history(date_from=exact, date_to=exact, page_size=100)["items"]
    assert [item["request_id"] for item in exact_matches] == [
        "equal-instant-offset",
        "legacy-spy",
    ]


def test_indexed_one_hundred_thousand_event_history_query_is_bounded(settings):
    """Native-x86 developer evidence pins the contract-sized projection below 250 ms."""

    repository = _repository(settings)
    with repository.connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        connection.executemany(
            """INSERT INTO search_events
            (request_id, submitted_symbol, normalized_symbol, asset_type, status, is_repeat,
             error_code, error_message, submitted_at, completed_at, analysis_kind)
            VALUES (?, ?, ?, ?, 'failed', 0, 'scale', 'scale fixture', ?, ?,
                    'submitted_forecast')""",
            (
                (
                    f"scale-{index}",
                    f"S{index % 100}",
                    f"S{index % 100}",
                    "etf" if index % 2 else "stock",
                    (NOW + timedelta(seconds=index)).isoformat(),
                    (NOW + timedelta(seconds=index)).isoformat(),
                )
                for index in range(100_000)
            ),
        )
        connection.executemany(
            """INSERT INTO history_facets
            (event_id, canonical_symbol, company_name, model_name, model_version,
             submitted_at_us)
            VALUES (?, ?, ?, ?, ?, ?)""",
            (
                (
                    index + 1,
                    f"S{index % 100}",
                    "Needle Holdings" if index == 50_000 else "Scale Company",
                    "scale-model",
                    "v1",
                    Repository._utc_microseconds(NOW + timedelta(seconds=index)),
                )
                for index in range(100_000)
            ),
        )
        connection.commit()

    started = time.perf_counter()
    result = repository.history(
        company="Needle",
        model="scale-model",
        model_version="v1",
        date_from=NOW,
        date_to=NOW + timedelta(days=2),
        page_size=20,
    )
    elapsed = time.perf_counter() - started
    export_started = time.perf_counter()
    exact_export = repository.history_export(
        generated_at=NOW,
        event_id=1,
        request_id="scale-0",
        status="failed",
        date_from=NOW,
        date_to=NOW,
    )
    export_elapsed = time.perf_counter() - export_started
    with repository.connect() as connection:
        plan = connection.execute(
            "EXPLAIN QUERY PLAN SELECT event_id FROM history_facets "
            "WHERE submitted_at_us >= ? ORDER BY submitted_at_us DESC, event_id DESC LIMIT 20",
            (Repository._utc_microseconds(NOW),),
        ).fetchall()

    assert result["total"] == 1
    assert elapsed < 0.250
    assert exact_export["counts"] == {"events": 1, "runs": 0, "results": 0}
    assert exact_export["total_events"] == 1 and exact_export["truncated"] is False
    assert export_elapsed < 0.250
    assert any("idx_history_facets_submitted" in str(tuple(row)) for row in plan)
