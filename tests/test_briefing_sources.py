"""Owner-bound SQLite adapter contracts for personal briefing sources."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

import pytest

from stock_probs.briefing_domain import PriceObservation
from stock_probs.briefing_service import BriefingSourceUnavailableError
from stock_probs.briefing_sources import RepositoryBriefingSources
from stock_probs.repository import Repository

AS_OF = datetime(2026, 10, 14, 12, tzinfo=UTC)
BASELINE = AS_OF - timedelta(hours=1)


def _text(value: datetime) -> str:
    return value.isoformat(timespec="microseconds").replace("+00:00", "Z")


@pytest.fixture
def repository(tmp_path: Path) -> Repository:
    repository = Repository(tmp_path / "briefing-sources.sqlite3")
    repository.migrate()
    with repository.connect() as connection:
        for user_id in (2, 3):
            connection.execute(
                "INSERT INTO users(id,display_name,role,status,created_at,updated_at) "
                "VALUES(?,?,'member','active',?,?)",
                (
                    user_id,
                    f"Source member {user_id}",
                    _text(AS_OF - timedelta(days=10)),
                    _text(AS_OF),
                ),
            )
        connection.commit()
    return repository


def _watchlist(
    repository: Repository,
    owner_user_id: int,
    symbol: str,
    *,
    asset_type: str = "stock",
    added_at: datetime = AS_OF - timedelta(days=10),
) -> None:
    with repository.connect() as connection:
        connection.execute(
            "INSERT INTO user_instrument_list_items"
            "(owner_user_id,kind,provider,canonical_symbol,asset_type,exchange,display_name,"
            "quantity,added_at) VALUES(?,'watchlist','fixture',?,?, 'TEST', ?,NULL,?)",
            (owner_user_id, symbol, asset_type, symbol, _text(added_at)),
        )
        connection.commit()


def _seed_forecast(
    repository: Repository,
    owner_user_id: int,
    symbol: str,
    bars: list[tuple[datetime, float]],
    *,
    asset_type: str = "stock",
    captured_at: datetime = AS_OF,
    created_at: datetime = AS_OF,
) -> int:
    snapshot = {
        "symbol": symbol,
        "canonical_symbol": symbol,
        "asset_type": asset_type,
        "provider": "fixture",
        "currency": "USD",
        "captured_at": _text(captured_at),
        "selected_daily_bars": [
            {
                "timestamp": _text(at),
                "end": _text(at),
                "close": close,
                "duration_seconds": 0,
            }
            for at, close in bars
        ],
    }
    with repository.connect() as connection:
        run_id = connection.execute(
            "INSERT INTO forecast_runs(symbol,asset_type,content_fingerprint,created_at) "
            "VALUES(?,?,?,?)",
            (symbol, asset_type, str(uuid4()), _text(created_at)),
        ).lastrowid
        input_id = connection.execute(
            "INSERT INTO forecast_inputs(run_id,snapshot_json,created_at) VALUES(?,?,?)",
            (run_id, json.dumps(snapshot, separators=(",", ":")), _text(created_at)),
        ).lastrowid
        result_id = connection.execute(
            "INSERT INTO forecast_results(input_id,horizon,result_json,created_at) "
            "VALUES(?,'close_to_close','{}',?)",
            (input_id, _text(created_at)),
        ).lastrowid
        connection.execute(
            "INSERT INTO forecast_run_owners(run_id,owner_user_id,assigned_at) VALUES(?,?,?)",
            (run_id, owner_user_id, _text(created_at)),
        )
        connection.execute(
            "INSERT INTO forecast_result_owners(result_id,owner_user_id,assigned_at) VALUES(?,?,?)",
            (result_id, owner_user_id, _text(created_at)),
        )
        connection.commit()
    if type(result_id) is not int:
        raise RuntimeError("SQLite did not return a forecast result identifier")
    return result_id


def _seed_outcome(
    repository: Repository,
    result_id: int,
    owner_user_id: int,
    event_at: datetime,
    *,
    state: str = "observed",
) -> int:
    observed_at = event_at - timedelta(seconds=1)
    with repository.connect() as connection:
        outcome_id = connection.execute(
            "INSERT INTO outcomes(result_id,observed_close,observed_return,observed_at,"
            "comparison_rule,state,note,created_at) VALUES(?,10.0,0.1,?,'close_to_close',?,?,?)",
            (result_id, _text(observed_at), state, "private note must not escape", _text(event_at)),
        ).lastrowid
        connection.execute(
            "INSERT INTO outcome_owners(outcome_id,owner_user_id,assigned_at) VALUES(?,?,?)",
            (outcome_id, owner_user_id, _text(event_at)),
        )
        connection.commit()
    if type(outcome_id) is not int:
        raise RuntimeError("SQLite did not return an outcome identifier")
    return outcome_id


def _seed_alert_event(
    repository: Repository,
    owner_user_id: int,
    symbol: str,
    *,
    currency: str = "USD",
    price: str = "101.25",
    observed_at: datetime = AS_OF - timedelta(minutes=3),
    created_at: datetime = AS_OF,
) -> str:
    alert_id, job_id, request_id, lease_token = (str(uuid4()) for _ in range(4))
    idempotency_key = str(uuid4())
    payload = {
        "symbol": symbol,
        "currency": currency,
        "threshold": "100",
        "direction": "above",
        "repeating": False,
    }
    payload_json = json.dumps(payload, separators=(",", ":"), sort_keys=True)
    armed_at = observed_at - timedelta(minutes=2)
    requested_at = observed_at - timedelta(seconds=10)
    received_at = observed_at + timedelta(seconds=2)
    accepted_at = observed_at + timedelta(seconds=3)
    with repository.connect() as connection:
        connection.execute(
            "INSERT INTO price_alerts(id,owner_user_id,idempotency_key,request_sha256,revision,"
            "monitor_revision,payload_json,enabled,armed_at,arm_generation,ready,check_state,"
            "created_at,updated_at) VALUES(?,?,?,?,1,1,?,1,?,1,0,'arming',?,?)",
            (
                alert_id,
                owner_user_id,
                idempotency_key,
                "a" * 64,
                payload_json,
                _text(armed_at),
                _text(armed_at),
                _text(armed_at),
            ),
        )
        connection.execute(
            "INSERT INTO price_alert_revisions"
            "(alert_id,owner_user_id,revision,payload_json,enabled,recorded_at) "
            "VALUES(?,?,1,?,1,?)",
            (alert_id, owner_user_id, payload_json, _text(armed_at)),
        )
        connection.execute(
            "INSERT INTO monitoring_jobs(id,owner_user_id,kind,resource_id,due_at,"
            "alert_generation,expected_monitor_revision,request_kind,lease_token,lease_until,"
            "active_request_id,active_requested_at) "
            "VALUES(?,?,'price',?,?,1,1,'arm_snapshot',?,?,?,?)",
            (
                job_id,
                owner_user_id,
                alert_id,
                _text(requested_at),
                lease_token,
                _text(created_at + timedelta(minutes=1)),
                request_id,
                _text(requested_at),
            ),
        )
        connection.execute(
            "INSERT INTO price_alert_observations(request_id,owner_user_id,alert_id,job_id,"
            "generation,observation_kind,request_sha256,receipt_sha256,dedupe_sha256,lease_token,"
            "requested_at,received_at,accepted_at,observed_at,provider,symbol,currency,price,"
            "disposition,stale,state_revision_before,state_revision_after) "
            "VALUES(?,?,?,?,1,'arm_snapshot',?,?,?,?,?,?,?,?,?,?,?,?, 'initial',0,1,2)",
            (
                request_id,
                owner_user_id,
                alert_id,
                job_id,
                "b" * 64,
                "c" * 64,
                "d" * 64,
                lease_token,
                _text(requested_at),
                _text(received_at),
                _text(accepted_at),
                _text(observed_at),
                "fixture",
                symbol,
                currency,
                price,
            ),
        )
        connection.execute(
            "UPDATE price_alerts SET monitor_revision=2,arm_snapshot_generation=1,"
            "arm_snapshot_request_id=?,arm_snapshot_requested_at=?,arm_snapshot_received_at=?,"
            "last_side=1,ready=1,check_state='watching',last_observed_at=?,"
            "last_observation_json=?,last_success_at=?,last_check_at=?,updated_at=? WHERE id=?",
            (
                request_id,
                _text(requested_at),
                _text(received_at),
                _text(observed_at),
                json.dumps({"price": price}, separators=(",", ":")),
                _text(received_at),
                _text(accepted_at),
                _text(accepted_at),
                alert_id,
            ),
        )
        notification = {
            "alert_id": alert_id,
            "generation": 1,
            "symbol": symbol,
            "currency": currency,
            "threshold": "100",
            "direction": "above",
            "price": price,
            "provider": "fixture",
            "observed_at": _text(observed_at),
        }
        connection.execute(
            "INSERT INTO notifications"
            "(id,owner_user_id,dedupe_sha256,kind,payload_json,created_at) "
            "VALUES(?,?,?,'price_alert',?,?)",
            (
                str(uuid4()),
                owner_user_id,
                sha256(alert_id.encode("ascii")).hexdigest(),
                json.dumps(notification, separators=(",", ":"), sort_keys=True),
                _text(created_at),
            ),
        )
        connection.commit()
    return alert_id


def test_price_adapter_uses_owner_watchlist_and_latest_captured_daily_close(repository):
    _watchlist(repository, 2, "MSFT")
    _watchlist(repository, 3, "AAPL")
    _seed_forecast(
        repository,
        2,
        "MSFT",
        [(AS_OF - timedelta(days=1), 100.0), (AS_OF, 101.5)],
    )
    _seed_forecast(repository, 1, "AAPL", [(AS_OF, 999.0)])
    with repository.connect() as connection:
        connection.execute(
            "INSERT INTO instrument_list_items"
            "(kind,provider,canonical_symbol,asset_type,exchange,display_name,quantity,added_at) "
            "VALUES('watchlist','fixture','AAPL','stock','TEST','Legacy AAPL',NULL,?)",
            (_text(AS_OF - timedelta(days=20)),),
        )
        connection.commit()

    source = RepositoryBriefingSources(repository)
    points = source.list_price_observations(2, observed_as_of=AS_OF, limit=100)
    assert len(points) == 1
    assert points[0] == PriceObservation(
        owner_user_id=2,
        source_ref=points[0].source_ref,
        symbol="MSFT",
        asset_type="stock",
        provider="fixture",
        currency="USD",
        price=points[0].price,
        observed_at=AS_OF,
        received_at=AS_OF,
        state="observed",
    )
    assert points[0].price is not None and str(points[0].price) == "101.5"

    unavailable = source.list_price_observations(3, observed_as_of=AS_OF, limit=100)
    assert len(unavailable) == 1
    assert unavailable[0].symbol == "AAPL"
    assert unavailable[0].state == "unavailable"
    assert unavailable[0].reason == "source_unavailable"
    assert unavailable[0].price is None


def test_price_adapter_rejects_future_capture_and_watchlist_overflow(repository):
    _watchlist(repository, 2, "MSFT")
    _seed_forecast(
        repository,
        2,
        "MSFT",
        [(AS_OF, 101.0)],
        captured_at=AS_OF + timedelta(seconds=1),
        created_at=AS_OF,
    )
    source = RepositoryBriefingSources(repository)
    with pytest.raises(BriefingSourceUnavailableError):
        source.list_price_observations(2, observed_as_of=AS_OF, limit=100)

    _seed_forecast(
        repository,
        2,
        "MSFT",
        [(AS_OF, 101.0), (AS_OF - timedelta(days=1), 100.0)],
        captured_at=AS_OF,
        created_at=AS_OF,
    )
    with pytest.raises(BriefingSourceUnavailableError):
        source.list_price_observations(2, observed_as_of=AS_OF, limit=100)

    with repository.connect() as connection:
        for index in range(51):
            symbol = f"T{index:03d}"
            connection.execute(
                "INSERT INTO user_instrument_list_items"
                "(owner_user_id,kind,provider,canonical_symbol,asset_type,exchange,display_name,"
                "quantity,added_at) VALUES(2,'watchlist','fixture',?,'stock','TEST',?,NULL,?)",
                (symbol, symbol, _text(AS_OF - timedelta(days=1))),
            )
        connection.commit()
    with pytest.raises(BriefingSourceUnavailableError):
        source.list_price_observations(2, observed_as_of=AS_OF, limit=100)


def test_outcomes_are_owner_scoped_and_use_strict_lower_inclusive_upper_window(repository):
    result_id = _seed_forecast(repository, 2, "MSFT", [(AS_OF, 100.0)])
    _seed_outcome(repository, result_id, 2, BASELINE, state="observed")
    _seed_outcome(repository, result_id, 2, BASELINE + timedelta(seconds=1), state="observed")
    corrected_id = _seed_outcome(repository, result_id, 2, AS_OF, state="corrected")
    _seed_outcome(repository, result_id, 2, AS_OF + timedelta(seconds=1), state="observed")
    foreign_result = _seed_forecast(repository, 3, "AAPL", [(AS_OF, 200.0)])
    _seed_outcome(repository, foreign_result, 3, BASELINE + timedelta(seconds=2))
    with repository.connect() as connection:
        connection.execute(
            "INSERT INTO collected_outcome_evidence"
            "(outcome_id,owner_user_id,result_id,state,payload_json,collected_at) "
            "VALUES(?,?,?,'incomparable','{}',?)",
            (corrected_id, 2, result_id, _text(AS_OF)),
        )
        connection.execute(
            "INSERT INTO forecast_outcome_reviews"
            "(owner_user_id,result_id,revision,state,note,reviewed_at) "
            "VALUES(2,?,1,'disputed','private review note',?)",
            (result_id, _text(AS_OF)),
        )
        connection.commit()

    changes = RepositoryBriefingSources(repository).list_outcome_changes(
        2, baseline_at=BASELINE, observed_as_of=AS_OF, limit=100
    )
    assert len(changes) == 4
    assert [item.recorded_at for item in changes] == [
        BASELINE + timedelta(seconds=1),
        AS_OF,
        AS_OF,
        AS_OF,
    ]
    corrected = next(
        item for item in changes if item.source_ref == f"forecast-outcome:{corrected_id}"
    )
    assert corrected.state == "manual_review"
    assert corrected.revision == 3
    assert corrected.correction_of is None
    assert all(item.owner_user_id == 2 for item in changes)
    assert all(not hasattr(item, "note") for item in changes)


def test_alert_notifications_match_owner_observation_and_unknown_asset_is_explicit(repository):
    _watchlist(repository, 2, "SPY", asset_type="etf")
    _watchlist(repository, 2, "DUP", asset_type="stock")
    _watchlist(repository, 2, "DUP", asset_type="etf")
    _seed_alert_event(repository, 2, "SPY")
    _seed_alert_event(repository, 2, "ODD")
    _seed_alert_event(repository, 2, "DUP")
    alerts = RepositoryBriefingSources(repository).list_triggered_alerts(
        2, baseline_at=AS_OF - timedelta(seconds=1), observed_as_of=AS_OF, limit=100
    )
    assert {(item.symbol, item.asset_type) for item in alerts} == {
        ("ODD", "unknown"),
        ("SPY", "etf"),
        ("DUP", "unknown"),
    }
    prices = RepositoryBriefingSources(repository).list_price_observations(
        2, observed_as_of=AS_OF, limit=100
    )
    ambiguous_points = [point for point in prices if point.symbol == "DUP"]
    assert len(ambiguous_points) == 2
    assert {point.asset_type for point in ambiguous_points} == {"stock", "etf"}
    assert all(point.state == "unavailable" for point in ambiguous_points)
    at_boundary = RepositoryBriefingSources(repository).list_triggered_alerts(
        2, baseline_at=AS_OF, observed_as_of=AS_OF, limit=100
    )
    assert at_boundary == []


def test_alert_notification_without_its_persisted_observation_fails_closed(repository):
    alert_id = str(uuid4())
    payload = {
        "alert_id": alert_id,
        "generation": 1,
        "symbol": "SPY",
        "currency": "USD",
        "threshold": "100",
        "direction": "above",
        "price": "101",
        "provider": "fixture",
        "observed_at": _text(AS_OF - timedelta(seconds=1)),
    }
    with repository.connect() as connection:
        connection.execute(
            "INSERT INTO price_alerts(id,owner_user_id,idempotency_key,request_sha256,revision,"
            "monitor_revision,payload_json,enabled,armed_at,arm_generation,ready,check_state,"
            "created_at,updated_at) VALUES(?,2,?,?,1,1,?,0,?,1,0,'paused',?,?)",
            (
                alert_id,
                str(uuid4()),
                "a" * 64,
                json.dumps(
                    {
                        "symbol": "SPY",
                        "currency": "USD",
                        "threshold": "100",
                        "direction": "above",
                        "repeating": False,
                    },
                    separators=(",", ":"),
                    sort_keys=True,
                ),
                _text(AS_OF - timedelta(days=1)),
                _text(AS_OF - timedelta(days=1)),
                _text(AS_OF - timedelta(days=1)),
            ),
        )
        connection.execute(
            "INSERT INTO price_alert_revisions"
            "(alert_id,owner_user_id,revision,payload_json,enabled,recorded_at) "
            "SELECT id,owner_user_id,1,payload_json,enabled,created_at "
            "FROM price_alerts WHERE id=?",
            (alert_id,),
        )
        connection.execute(
            "INSERT INTO notifications"
            "(id,owner_user_id,dedupe_sha256,kind,payload_json,created_at) "
            "VALUES(?,2,?,'price_alert',?,?)",
            (
                str(uuid4()),
                "f" * 64,
                json.dumps(payload, separators=(",", ":"), sort_keys=True),
                _text(AS_OF),
            ),
        )
        connection.commit()
    with pytest.raises(BriefingSourceUnavailableError):
        RepositoryBriefingSources(repository).list_triggered_alerts(
            2, baseline_at=BASELINE, observed_as_of=AS_OF, limit=100
        )


def test_thesis_review_uses_latest_owner_revision_as_of_and_exposes_no_text(repository):
    thesis_id = str(uuid4())
    earlier = AS_OF - timedelta(days=3)
    later = AS_OF + timedelta(days=1)
    first = {
        "symbol": "MSFT",
        "asset_type": "stock",
        "title": "Private title",
        "reasoning": "Private reasoning",
        "risks": "Private risk",
        "invalidation": "Private invalidation",
        "evidence": [],
        "status": "watching",
        "review_date": (AS_OF - timedelta(days=1)).date().isoformat(),
    }
    second = {**first, "status": "archived", "review_date": None}
    with repository.connect() as connection:
        connection.execute(
            "INSERT INTO research_theses(id,owner_user_id,idempotency_key,request_sha256,"
            "revision,payload_json,created_at,updated_at) VALUES(?,2,?,?,2,?,?,?)",
            (
                thesis_id,
                str(uuid4()),
                "a" * 64,
                json.dumps(second, separators=(",", ":")),
                _text(earlier),
                _text(later),
            ),
        )
        for revision, payload, recorded_at in ((1, first, earlier), (2, second, later)):
            connection.execute(
                "INSERT INTO research_thesis_revisions"
                "(thesis_id,owner_user_id,revision,payload_json,recorded_at) VALUES(?,2,?,?,?)",
                (
                    thesis_id,
                    revision,
                    json.dumps(payload, separators=(",", ":")),
                    _text(recorded_at),
                ),
            )
        connection.commit()

    reviews = RepositoryBriefingSources(repository).list_due_thesis_reviews(
        2, observed_as_of=AS_OF, limit=100
    )
    assert len(reviews) == 1
    assert reviews[0].thesis_ref == f"research-thesis:{thesis_id}"
    assert reviews[0].revision == 1
    assert reviews[0].due_at == datetime(2026, 10, 13, tzinfo=UTC)
    assert not hasattr(reviews[0], "title")
