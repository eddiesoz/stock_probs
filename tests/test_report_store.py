"""Owner and publication-time boundaries for persisted forecast report cards."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

from stock_probs.report_store import ReportCardStore, ReportConflictError, ReportNotFoundError
from stock_probs.repository import Repository

NOW = datetime(2026, 10, 12, 22, tzinfo=UTC)
TARGET = datetime(2026, 10, 12, 20, tzinfo=UTC)
PROVIDER = "FixtureMarketProvider"
ADJUSTMENT = "unadjusted provider closes (actions=False, auto_adjust=False)"


def _iso(value: datetime | str) -> str:
    return value if isinstance(value, str) else value.isoformat()


def _forecast(horizon: str = "daily_1") -> dict[str, object]:
    duration = 300 if horizon in {"five_min_forward", "completed_5m_to_close"} else 0
    origin = TARGET - timedelta(seconds=duration or 86_400)
    return {
        "horizon": horizon,
        "canonical_symbol": "SPY",
        "currency": "USD",
        "origin_timestamp": origin.isoformat(),
        "model": {"version": "report-fixture-v1"},
        "provenance": {
            "model_version": "report-fixture-v1",
            "source": PROVIDER,
            "instrument_identity": {
                "canonical_symbol": "SPY",
                "currency": "USD",
                "provider": PROVIDER,
            },
        },
        "origin_price": 100.0,
        "adjustment_basis": ADJUSTMENT,
        "target_timestamp": TARGET.isoformat(),
        "direction_probabilities": {"down": 0.1, "unchanged": 0.2, "up": 0.7},
        "magnitude_intervals": [{"level": 0.8, "price": {"low": 90.0, "high": 110.0}}],
        "evaluation": {"direction_accuracy": 1.0, "coverage": 1.0},
    }


def _comparability(close: float = 105.0, horizon: str = "five_min_forward") -> dict[str, object]:
    duration = 300 if horizon in {"five_min_forward", "completed_5m_to_close"} else 0
    origin = TARGET - timedelta(seconds=duration or 86_400)
    return {
        "schema": "forecast-outcome-comparability-v1",
        "state": "comparable",
        "provider": PROVIDER,
        "symbol": "SPY",
        "currency": "USD",
        "adjustment_basis": ADJUSTMENT,
        "origin": {"timestamp": origin.isoformat(), "close": 100.0},
        "target": {"timestamp": TARGET.isoformat(), "close": close},
        "corporate_actions": {
            "state": "checked",
            "provider": PROVIDER,
            "symbol": "SPY",
            "currency": "USD",
            "from_timestamp": origin.isoformat(),
            "through_timestamp": TARGET.isoformat(),
            "events": [],
        },
    }


def _add_saved_result(
    repository: Repository,
    result_id: int,
    owner_id: int,
    *,
    horizon: str = "daily_1",
    created_at: datetime | str | None = None,
    analysis_kind: str = "submitted_forecast",
) -> None:
    recorded = created_at or (TARGET - timedelta(hours=1))
    recorded_text = _iso(recorded)
    with repository.connect() as connection:
        connection.execute(
            "INSERT INTO forecast_runs(id,symbol,asset_type,content_fingerprint,created_at) "
            "VALUES(?,?,?,?,?)",
            (result_id, "SPY", "stock", f"fingerprint-{result_id}", recorded_text),
        )
        connection.execute(
            "INSERT INTO forecast_run_owners(run_id,owner_user_id,assigned_at) VALUES(?,?,?)",
            (result_id, owner_id, recorded_text),
        )
        connection.execute(
            "INSERT INTO forecast_inputs(id,run_id,snapshot_json,created_at) VALUES(?,?,?,?)",
            (result_id, result_id, "{}", recorded_text),
        )
        connection.execute(
            "INSERT INTO forecast_results(id,input_id,horizon,result_json,created_at) "
            "VALUES(?,?,?,?,?)",
            (
                result_id,
                result_id,
                horizon,
                json.dumps(_forecast(horizon), separators=(",", ":")),
                recorded_text,
            ),
        )
        connection.execute(
            "INSERT INTO forecast_result_owners(result_id,owner_user_id,assigned_at) VALUES(?,?,?)",
            (result_id, owner_id, recorded_text),
        )
        if analysis_kind == "submitted_forecast":
            event_id = result_id
            event = (
                event_id,
                f"request-{result_id}",
                "SPY",
                "SPY",
                "stock",
                "successful",
                0,
                None,
                None,
                result_id,
                recorded_text,
                recorded_text,
                analysis_kind,
                None,
                None,
            )
            connection.execute(
                "INSERT INTO search_events(id,request_id,submitted_symbol,normalized_symbol,"
                "asset_type,"
                "status,is_repeat,error_code,error_message,run_id,submitted_at,completed_at,"
                "analysis_kind,source_event_id,requested_cutoff) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                event,
            )
            connection.execute(
                "INSERT INTO search_event_owners(event_id,owner_user_id,assigned_at) VALUES(?,?,?)",
                (event_id, owner_id, recorded_text),
            )
        connection.commit()


def _add_unavailable_outcome(
    repository: Repository, result_id: int, owner_id: int, outcome_id: int, created_at: datetime
) -> None:
    with repository.connect() as connection:
        connection.execute(
            "INSERT INTO outcomes(id,result_id,observed_close,observed_return,observed_at,"
            "comparison_rule,state,note,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
            (
                outcome_id,
                result_id,
                None,
                None,
                TARGET.isoformat(),
                "fixture",
                "unavailable",
                "",
                created_at.isoformat(),
            ),
        )
        connection.execute(
            "INSERT INTO outcome_owners(outcome_id,owner_user_id,assigned_at) VALUES(?,?,?)",
            (outcome_id, owner_id, created_at.isoformat()),
        )
        connection.execute(
            "INSERT INTO collected_outcome_evidence(outcome_id,owner_user_id,result_id,state,"
            "payload_json,collected_at) "
            "VALUES(?,?,?,?,?,?)",
            (
                outcome_id,
                owner_id,
                result_id,
                "unavailable",
                json.dumps({"reason_code": "provider_unavailable"}),
                (created_at + timedelta(seconds=1)).isoformat(),
            ),
        )
        connection.commit()


@pytest.fixture
def repository(tmp_path) -> Repository:
    """Create a disposable schema-16 database with two active owners."""
    repo = Repository(tmp_path / "report.sqlite3")
    repo.migrate()
    for user_id in (1, 2):
        repo.create_user(
            github_user_id=1000 + user_id,
            login=f"report-user-{user_id}",
            display_name=f"Report User {user_id}",
            password_hash=None,
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
    return repo


def test_report_page_is_owner_bound_and_excludes_future_backtests_and_evaluation(
    repository: Repository,
) -> None:
    _add_saved_result(repository, 1, 1)
    _add_saved_result(repository, 2, 1, created_at=NOW + timedelta(seconds=1))
    _add_saved_result(repository, 3, 1, analysis_kind="fresh_historical_reconstruction")
    _add_saved_result(repository, 4, 2)
    _add_unavailable_outcome(repository, 1, 1, 101, TARGET + timedelta(seconds=1))
    with repository.connect() as connection:
        connection.execute(
            "INSERT INTO forecast_outcome_reviews(owner_user_id,result_id,revision,state,note,"
            "reviewed_at) "
            "VALUES(?,?,?,?,?,?)",
            (1, 1, 1, "disputed", "future review", (NOW + timedelta(seconds=1)).isoformat()),
        )
        connection.commit()

    report = ReportCardStore(repository).list_report(1, NOW, page_size=1)

    assert report["total"] == 1
    assert report["denominator_scope"] == "current_page"
    assert report["denominator_count"] == 1
    assert report["counts"]["unavailable"] == 1
    assert report["groups"][0]["direction"]["denominator"] == 0
    assert report["items"][0]["result_id"] == 1
    assert report["items"][0]["outcome"]["id"] == 101
    assert report["items"][0]["source"] is None
    assert report["items"][0]["state"] == "unavailable"


def test_report_as_of_filters_use_exact_instants_for_offsets_and_microseconds(
    repository: Repository,
) -> None:
    _add_saved_result(repository, 1, 1, created_at="2026-10-12T23:00:00+02:00")
    _add_saved_result(repository, 2, 1, created_at="2026-10-12T21:30:00-02:00")
    _add_saved_result(repository, 3, 1, created_at="2026-10-13T00:00:00+02:00")
    _add_saved_result(repository, 4, 1, created_at="2026-10-12T22:00:00.000001Z")
    _add_saved_result(repository, 5, 1, created_at="2026-02-30T10:00:00Z")
    _add_saved_result(repository, 6, 1, created_at="2026-10-12T17:00:00-05:00")
    _add_saved_result(repository, 7, 1, created_at="2026-10-13T00:15:00+03:00")

    report = ReportCardStore(repository).list_report(1, NOW, page_size=10)

    assert report["total"] == 4
    assert [item["result_id"] for item in report["items"]] == [6, 3, 7, 1]
    assert report["denominator_count"] == 4


def test_latest_outcome_evidence_and_review_queries_use_exact_instants(
    repository: Repository,
) -> None:
    _add_saved_result(repository, 1, 1, horizon="five_min_forward")
    earlier_outcome_time = "2026-10-12T23:30:00+02:00"  # 21:30 UTC
    latest_past_outcome_time = "2026-10-12T21:45:00Z"  # 21:45 UTC
    future_outcome_time = "2026-10-12T21:30:00-02:00"  # 23:30 UTC
    past_review_time = "2026-10-12T23:50:00+02:00"  # 21:50 UTC
    future_review_time = "2026-10-12T21:30:00-02:00"  # 23:30 UTC
    with repository.connect() as connection:
        for outcome_id, created_at in (
            (101, earlier_outcome_time),
            (103, latest_past_outcome_time),
            (102, future_outcome_time),
        ):
            connection.execute(
                "INSERT INTO outcomes(id,result_id,observed_close,observed_return,observed_at,"
                "comparison_rule,state,note,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                (
                    outcome_id,
                    1,
                    105.0,
                    0.05,
                    TARGET.isoformat(),
                    "close divided by immutable origin price minus one",
                    "observed",
                    "",
                    created_at,
                ),
            )
            connection.execute(
                "INSERT INTO outcome_owners(outcome_id,owner_user_id,assigned_at) VALUES(?,?,?)",
                (outcome_id, 1, created_at),
            )
        source = {
            "method": "manual_review",
            "review_revision": 1,
            "comparability": _comparability(),
        }
        connection.execute(
            "INSERT INTO collected_outcome_evidence(outcome_id,owner_user_id,result_id,state,"
            "payload_json,collected_at) VALUES(?,?,?,?,?,?)",
            (
                103,
                1,
                1,
                "observed",
                json.dumps(source, separators=(",", ":")),
                "2026-10-12T23:55:00+02:00",  # 21:55 UTC, after the outcome
            ),
        )
        for revision, state, reviewed_at in (
            (1, "confirmed", "2026-10-12T21:00:00Z"),
            (2, "disputed", past_review_time),
            (3, "confirmed", future_review_time),
        ):
            connection.execute(
                "INSERT INTO forecast_outcome_reviews(owner_user_id,result_id,revision,state,note,"
                "reviewed_at) VALUES(?,?,?,?,?,?)",
                (1, 1, revision, state, "fixture", reviewed_at),
            )
        connection.commit()

    store = ReportCardStore(repository)
    report = store.list_report(1, NOW)
    history = store.review_history(1, 1, NOW)

    assert report["items"][0]["outcome"]["id"] == 103
    assert report["items"][0]["state"] == "disputed"
    assert report["items"][0]["source"] is None
    assert history["total"] == 2
    assert [item["revision"] for item in history["items"]] == [2, 1]
    assert history["items"][0]["state"] == "disputed"


def test_page_counts_and_denominators_describe_only_the_bounded_page(
    repository: Repository,
) -> None:
    _add_saved_result(repository, 1, 1)
    _add_saved_result(repository, 2, 1, created_at=TARGET - timedelta(minutes=30))
    store = ReportCardStore(repository)

    first = store.list_report(1, NOW, page=1, page_size=1)
    second = store.list_report(1, NOW, page=2, page_size=1)

    assert first["total"] == second["total"] == 2
    assert first["denominator_count"] == second["denominator_count"] == 1
    assert first["has_next"] is True and second["has_next"] is False
    assert first["items"][0]["result_id"] == 2
    assert second["items"][0]["result_id"] == 1
    assert first["counts"]["pending"] == 1
    assert second["counts"]["pending"] == 1
    assert first["items"][0]["direction_correct"] is None
    assert second["items"][0]["interval_80_covered"] is None


def test_malformed_saved_json_is_reported_as_incomparable_without_crashing(
    repository: Repository,
) -> None:
    _add_saved_result(repository, 1, 1)
    with repository.connect() as connection:
        connection.execute("DROP TRIGGER immutable_forecast_results_update")
        connection.execute("UPDATE forecast_results SET result_json=? WHERE id=1", ("{broken",))
        connection.commit()

    report = ReportCardStore(repository).list_report(1, NOW)

    assert report["counts"]["incomparable"] == 1
    assert report["items"][0]["direction_correct"] is None
    assert report["items"][0]["interval_80_covered"] is None


def test_malformed_evidence_json_is_incomparable_without_crashing(
    repository: Repository,
) -> None:
    _add_saved_result(repository, 1, 1)
    outcome_created = TARGET + timedelta(seconds=1)
    with repository.connect() as connection:
        connection.execute(
            "INSERT INTO outcomes(id,result_id,observed_close,observed_return,observed_at,"
            "comparison_rule,state,note,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
            (
                101,
                1,
                105.0,
                0.05,
                TARGET.isoformat(),
                "close divided by immutable origin price minus one",
                "observed",
                "",
                outcome_created.isoformat(),
            ),
        )
        connection.execute(
            "INSERT INTO outcome_owners(outcome_id,owner_user_id,assigned_at) VALUES(?,?,?)",
            (101, 1, outcome_created.isoformat()),
        )
        connection.execute(
            "INSERT INTO collected_outcome_evidence(outcome_id,owner_user_id,result_id,state,"
            "payload_json,collected_at) VALUES(?,?,?,?,?,?)",
            (
                101,
                1,
                1,
                "observed",
                "{broken",
                (outcome_created + timedelta(seconds=1)).isoformat(),
            ),
        )
        connection.commit()

    report = ReportCardStore(repository).list_report(1, NOW)

    assert report["counts"]["incomparable"] == 1
    assert report["items"][0]["direction_correct"] is None
    assert report["items"][0]["interval_80_covered"] is None


def test_inactive_owner_and_cross_owner_review_history_are_not_disclosed(
    repository: Repository,
) -> None:
    _add_saved_result(repository, 1, 1)
    _add_saved_result(repository, 2, 2)
    store = ReportCardStore(repository)
    assert store.list_report(2, NOW)["total"] == 1
    assert store.review_history(1, 2, NOW) is None
    with repository.connect() as connection:
        connection.execute("UPDATE users SET status='disabled' WHERE id=1")
        connection.commit()
    with pytest.raises(ReportNotFoundError):
        store.list_report(1, NOW)


def test_manual_review_requires_exact_matching_existing_evidence_and_cas(
    repository: Repository,
) -> None:
    _add_saved_result(repository, 1, 1, horizon="five_min_forward")
    created_at = TARGET + timedelta(seconds=1)
    with repository.connect() as connection:
        connection.execute(
            "INSERT INTO outcomes(id,result_id,observed_close,observed_return,observed_at,"
            "comparison_rule,state,note,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
            (
                101,
                1,
                105.0,
                0.05,
                TARGET.isoformat(),
                "close divided by immutable origin price minus one",
                "observed",
                "",
                created_at.isoformat(),
            ),
        )
        connection.execute(
            "INSERT INTO outcome_owners(outcome_id,owner_user_id,assigned_at) VALUES(?,?,?)",
            (101, 1, created_at.isoformat()),
        )
        payload = {
            "method": "manual_review",
            "review_revision": 1,
            "comparability": _comparability(),
        }
        connection.execute(
            "INSERT INTO collected_outcome_evidence(outcome_id,owner_user_id,result_id,state,"
            "payload_json,collected_at) "
            "VALUES(?,?,?,?,?,?)",
            (
                101,
                1,
                1,
                "observed",
                json.dumps(payload, separators=(",", ":")),
                (created_at + timedelta(seconds=1)).isoformat(),
            ),
        )
        connection.commit()
    store = ReportCardStore(repository)

    review = store.append_manual_review(1, 1, 0, "confirmed", "Checked source endpoints.", NOW)
    assert review["revision"] == 1
    assert store.list_report(1, NOW)["items"][0]["state"] == "scored"
    with repository.connect() as connection:
        connection.execute(
            "INSERT INTO outcomes(id,result_id,observed_close,observed_return,observed_at,"
            "comparison_rule,state,note,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
            (
                102,
                1,
                200.0,
                1.0,
                TARGET.isoformat(),
                "close divided by immutable origin price minus one",
                "corrected",
                "future correction",
                (NOW + timedelta(seconds=1)).isoformat(),
            ),
        )
        connection.execute(
            "INSERT INTO outcome_owners(outcome_id,owner_user_id,assigned_at) VALUES(?,?,?)",
            (102, 1, (NOW + timedelta(seconds=1)).isoformat()),
        )
        connection.execute(
            "INSERT INTO forecast_outcome_reviews(owner_user_id,result_id,revision,state,note,"
            "reviewed_at) VALUES(?,?,?,?,?,?)",
            (1, 1, 2, "disputed", "future review", (NOW + timedelta(seconds=1)).isoformat()),
        )
        connection.commit()
    report = store.list_report(1, NOW)
    assert report["items"][0]["outcome"]["id"] == 101
    assert report["items"][0]["state"] == "scored"
    assert store.review_history(1, 1, NOW)["total"] == 1
    with pytest.raises(ReportConflictError):
        store.append_manual_review(1, 1, 0, "disputed", "stale write", NOW)
    with repository.connect() as connection:
        assert (
            connection.execute("SELECT COUNT(*) FROM outcomes WHERE result_id=1").fetchone()[0] == 2
        )
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM collected_outcome_evidence WHERE result_id=1"
            ).fetchone()[0]
            == 1
        )
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM forecast_outcome_reviews WHERE result_id=1"
            ).fetchone()[0]
            == 2
        )
