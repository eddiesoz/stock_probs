"""Focused repository regressions for bounded history summaries."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import UTC, datetime

from stock_probs.domain import calculate_forecasts
from stock_probs.provider import FixtureProvider
from stock_probs.repository import Repository
from stock_probs.service import ForecastService

OWNER_USER_ID = 1


def test_history_summarizes_shared_results_and_outcomes_in_one_query(settings, monkeypatch):
    now = datetime(2025, 1, 10, 17, 3, tzinfo=UTC)
    repository = Repository(settings.database_path)
    repository.migrate()
    service = ForecastService(repository, FixtureProvider(), lambda: now)
    created = service.search("ACDC", "stock", owner_user_id=OWNER_USER_ID)
    service.search("ACDC", "stock", owner_user_id=OWNER_USER_ID)
    repository.record_failure(
        owner_user_id=OWNER_USER_ID,
        request_id="failed-summary",
        submitted_symbol="FAIL",
        normalized_symbol="FAIL",
        asset_type="stock",
        error_code="provider_unavailable",
        error_message="fixture failure",
        submitted_at=now,
        completed_at=now,
    )

    statements: list[str] = []
    original_connect = repository.connect

    @contextmanager
    def traced_connect():
        with original_connect() as connection:
            connection.set_trace_callback(statements.append)
            yield connection

    monkeypatch.setattr(repository, "connect", traced_connect)
    page = repository.history(owner_user_id=OWNER_USER_ID, page_size=100)
    reads = [
        statement
        for statement in statements
        if statement.lstrip().upper().startswith(("SELECT", "WITH"))
    ]

    expected_statuses = [result["evaluation"]["status"] for result in created["results"]]
    successful = [item for item in page["items"] if item["run_id"] is not None]
    failed = next(item for item in page["items"] if item["run_id"] is None)
    # Ownership validation performs one bounded principal lookup before the three history reads.
    assert len(reads) == 4
    assert len(successful) == 2
    assert all(
        item["horizons"]
        == [
            "close_to_close",
            "completed_5m_to_close",
        ]
        and item["outcome_count"] == 0
        and item["evaluation_statuses"] == expected_statuses
        and item["forecast_available"] is True
        for item in successful
    )
    assert failed["horizons"] == []
    assert failed["outcome_count"] == 0
    assert failed["evaluation_statuses"] == []
    assert failed["forecast_available"] is False


def test_history_summary_omits_evaluation_status_for_unavailable_horizon(settings):
    now = datetime(2025, 1, 10, 22, 0, tzinfo=UTC)
    repository = Repository(settings.database_path)
    repository.migrate()
    snapshot, results = calculate_forecasts(
        FixtureProvider().fetch("ACDC", "stock", now), now, interval="5min"
    )
    repository.record_success(
        owner_user_id=OWNER_USER_ID,
        request_id="after-close",
        submitted_symbol="ACDC",
        asset_type="stock",
        input_snapshot=snapshot,
        results=results,
        submitted_at=now,
        completed_at=now,
    )

    summary = repository.history(owner_user_id=OWNER_USER_ID)["items"][0]

    assert summary["horizons"] == ["five_min_forward"]
    assert summary["evaluation_statuses"] == [
        result["evaluation"]["status"] for result in results if "evaluation" in result
    ]
