"""Focused persistence and orchestration tests for daily forecast outcome collection."""

from __future__ import annotations

import asyncio
import json
import sqlite3
import threading
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import pytest

from stock_probs.domain import Bar
from stock_probs.monitoring_scheduler import MonitoringScheduler
from stock_probs.monitoring_store import MonitoringStore
from stock_probs.outcome_collection import (
    ADJUSTMENT_BASIS,
    CorporateActionCheck,
    DailyOutcomeCollector,
    DailyOutcomeSeries,
)
from stock_probs.outcome_collection_store import (
    OutcomeCollectionLeaseConflict,
    OutcomeCollectionStore,
    OutcomeCollectionStoreError,
    OutcomeForecast,
)
from stock_probs.report_store import ReportCardStore
from stock_probs.repository import Repository

NOW = datetime(2026, 10, 15, 23, tzinfo=UTC)
TARGET = datetime(2026, 10, 15, 20, tzinfo=UTC)
PROVIDER = "FixtureMarketProvider"


def _forecast(
    horizon: str = "daily_1",
    *,
    target: datetime = TARGET,
) -> dict[str, object]:
    origin = target - timedelta(
        seconds=300 if horizon in {"five_min_forward", "completed_5m_to_close"} else 86_400
    )
    return {
        "horizon": horizon,
        "availability": "available",
        "canonical_symbol": "SPY",
        "currency": "USD",
        "origin_timestamp": origin.isoformat(),
        "target_timestamp": target.isoformat(),
        "origin_price": 100.0,
        "adjustment_basis": ADJUSTMENT_BASIS,
        "provenance": {
            "source": PROVIDER,
            "model_version": "collector-fixture-v1",
            "instrument_identity": {
                "provider": PROVIDER,
                "canonical_symbol": "SPY",
                "currency": "USD",
            },
        },
        "direction_probabilities": {"down": 0.1, "unchanged": 0.2, "up": 0.7},
        "magnitude_intervals": [{"level": 0.8, "price": {"low": 90.0, "high": 110.0}}],
    }


def _add_forecast(
    repository: Repository,
    result_id: int,
    owner_id: int,
    *,
    horizon: str = "daily_1",
    target: datetime = TARGET,
    analysis_kind: str = "submitted_forecast",
    forecast_payload: dict[str, object] | None = None,
) -> dict[str, object]:
    recorded = target - timedelta(hours=1)
    recorded_text = recorded.isoformat()
    forecast = (
        forecast_payload if forecast_payload is not None else _forecast(horizon, target=target)
    )
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
                json.dumps(forecast, separators=(",", ":")),
                recorded_text,
            ),
        )
        connection.execute(
            "INSERT INTO forecast_result_owners(result_id,owner_user_id,assigned_at) VALUES(?,?,?)",
            (result_id, owner_id, recorded_text),
        )
        if analysis_kind == "submitted_forecast":
            connection.execute(
                "INSERT INTO search_events(id,request_id,submitted_symbol,normalized_symbol,"
                "asset_type,status,is_repeat,run_id,submitted_at,completed_at,analysis_kind) "
                "VALUES(?,?,?,?,?,'successful',0,?,?,?,?)",
                (
                    result_id,
                    f"request-{result_id}",
                    "SPY",
                    "SPY",
                    "stock",
                    result_id,
                    recorded_text,
                    recorded_text,
                    analysis_kind,
                ),
            )
            connection.execute(
                "INSERT INTO search_event_owners(event_id,owner_user_id,assigned_at) VALUES(?,?,?)",
                (result_id, owner_id, recorded_text),
            )
        connection.commit()
    return forecast


@pytest.fixture
def repository(tmp_path) -> Repository:
    """Create a disposable migrated database with two active owners and monitoring enabled."""
    repository = Repository(tmp_path / "outcomes.sqlite3")
    repository.migrate()
    for user_id in (1, 2):
        repository.create_user(
            github_user_id=5000 + user_id,
            login=f"outcome-user-{user_id}",
            display_name=f"Outcome User {user_id}",
            password_hash=None,
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
    with repository.connect() as connection:
        connection.execute("UPDATE monitoring_control SET enabled=1 WHERE id=1")
        connection.commit()
    return repository


class FixtureOutcomeSource:
    """Return fixed, non-network data while exposing call count for orchestration checks."""

    def __init__(
        self,
        close: float = 105.0,
        *,
        actions: tuple[object, ...] = (),
        as_of: datetime | None = None,
        on_fetch: Callable[[], None] | None = None,
    ):
        self.close = close
        self.actions = actions
        self.as_of = as_of
        self.on_fetch = on_fetch
        self.calls = 0
        self.requested_at: list[datetime] = []

    def fetch_daily_outcome_series(
        self, symbol: str, asset_type: str, origin_at: datetime, target_at: datetime, now: datetime
    ) -> DailyOutcomeSeries:
        self.calls += 1
        self.requested_at.append(now)
        origin = Bar(origin_at, 100.0, 0)
        target = Bar(target_at, self.close, 0)
        series = DailyOutcomeSeries(
            provider=PROVIDER,
            symbol=symbol,
            currency="USD",
            adjustment_basis=ADJUSTMENT_BASIS,
            requested_from=origin_at,
            requested_through=target_at,
            as_of=self.as_of or now,
            complete=True,
            bars=(origin, target),
            corporate_actions=CorporateActionCheck(
                provider=PROVIDER,
                symbol=symbol,
                currency="USD",
                from_timestamp=origin_at,
                through_timestamp=target_at,
                complete=True,
                events=self.actions,
            ),
        )
        if self.on_fetch is not None:
            self.on_fetch()
        return series


def _read_outcomes(repository: Repository, result_id: int) -> list[dict[str, object]]:
    with repository.connect() as connection:
        return [
            dict(row)
            for row in connection.execute(
                "SELECT outcome.*,evidence.state AS evidence_state,evidence.payload_json "
                "FROM outcomes AS outcome LEFT JOIN collected_outcome_evidence AS evidence "
                "ON evidence.outcome_id=outcome.id WHERE outcome.result_id=? ORDER BY outcome.id",
                (result_id,),
            ).fetchall()
        ]


def test_enqueue_scans_only_matured_saved_daily_forecasts(repository: Repository) -> None:
    _add_forecast(repository, 1, 1)
    _add_forecast(repository, 2, 1, horizon="five_min_forward")
    _add_forecast(repository, 3, 1, analysis_kind="fresh_historical_reconstruction")
    _add_forecast(repository, 4, 1, target=TARGET + timedelta(days=1))
    with repository.connect() as connection:
        connection.execute("UPDATE users SET status='disabled' WHERE id=2")
        connection.commit()
    _add_forecast(repository, 5, 2)

    store = OutcomeCollectionStore(repository)
    assert store.enqueue_due(NOW) == 1
    with repository.connect() as connection:
        rows = connection.execute(
            "SELECT owner_user_id,kind,resource_id FROM monitoring_jobs"
        ).fetchall()
    assert [tuple(row) for row in rows] == [(1, "outcome", "1")]


def test_claim_uses_owner_fair_leases_and_reclaims_only_after_expiry(
    repository: Repository,
) -> None:
    _add_forecast(repository, 1, 1)
    _add_forecast(repository, 2, 2)
    store = OutcomeCollectionStore(repository)
    assert store.enqueue_due(NOW) == 2

    claims = store.claim_due("worker-a", NOW, limit=2, lease_seconds=5)
    assert [claim.owner_user_id for claim in claims] == [1, 2]
    renewed = store.claim_due("worker-b", NOW + timedelta(seconds=6), limit=1, lease_seconds=30)
    assert len(renewed) == 1
    assert renewed[0].job_id == claims[0].job_id
    assert renewed[0].lease_token != claims[0].lease_token
    assert store.load_forecast(claims[0], NOW + timedelta(seconds=6)) is None


def test_admin_only_outcome_queue_excludes_member_forecasts_and_existing_jobs(
    repository: Repository,
) -> None:
    _add_forecast(repository, 1, 1)
    _add_forecast(repository, 2, 2)
    ordinary = OutcomeCollectionStore(repository)
    assert ordinary.enqueue_due(NOW) == 2
    canary = OutcomeCollectionStore(repository, admin_only=True)

    claims = canary.claim_due("canary-worker", NOW, limit=2)

    assert [claim.owner_user_id for claim in claims] == [1]
    assert canary.load_forecast(claims[0], NOW) is not None
    with repository.connect() as connection:
        member_job = connection.execute(
            "SELECT attempts,lease_token FROM monitoring_jobs WHERE kind='outcome' "
            "AND owner_user_id=2 AND resource_id='2'"
        ).fetchone()
    assert member_job["attempts"] == 0 and member_job["lease_token"] is None


def test_admin_only_outcome_eligibility_and_owner_policy_are_strict(
    repository: Repository,
) -> None:
    _add_forecast(repository, 1, 1)
    _add_forecast(repository, 2, 2)
    canary = OutcomeCollectionStore(repository, admin_only=True)

    assert canary.enqueue_due(NOW) == 1
    with repository.connect() as connection:
        owners = connection.execute(
            "SELECT owner_user_id FROM monitoring_jobs WHERE kind='outcome' ORDER BY owner_user_id"
        ).fetchall()
    assert [row["owner_user_id"] for row in owners] == [1]
    with pytest.raises(TypeError, match="admin_only must be a boolean"):
        OutcomeCollectionStore(repository, admin_only=1)  # type: ignore[arg-type]


def test_admin_demotion_during_provider_fetch_prevents_outcome_commit(
    repository: Repository,
) -> None:
    _add_forecast(repository, 1, 1)

    def demote_admin() -> None:
        with repository.connect() as connection:
            connection.execute("UPDATE users SET role='member' WHERE id=1")
            connection.commit()

    source = FixtureOutcomeSource(on_fetch=demote_admin)
    store = OutcomeCollectionStore(repository, admin_only=True)
    collector = DailyOutcomeCollector(store, source, completion_clock=lambda: NOW)

    with pytest.raises(OutcomeCollectionLeaseConflict, match="lease is stale"):
        collector.run_once(NOW)

    assert source.calls == 1
    assert _read_outcomes(repository, 1) == []


@pytest.mark.parametrize("change", ["revoke_admin", "disable_control"])
def test_dispatch_rechecks_admin_and_monitoring_control_after_forecast_read(
    repository: Repository, change: str
) -> None:
    _add_forecast(repository, 1, 1)
    store = OutcomeCollectionStore(repository, admin_only=True)
    original_load = store.load_forecast
    changed = False

    def load_then_change(claim, now):
        nonlocal changed
        forecast = original_load(claim, now)
        if forecast is not None and not changed:
            with repository.connect() as connection:
                if change == "revoke_admin":
                    connection.execute("UPDATE users SET role='member' WHERE id=1")
                else:
                    connection.execute("UPDATE monitoring_control SET enabled=0 WHERE id=1")
                connection.commit()
            changed = True
        return forecast

    store.load_forecast = load_then_change
    source = FixtureOutcomeSource()

    with pytest.raises(OutcomeCollectionLeaseConflict, match="changed before dispatch"):
        DailyOutcomeCollector(store, source, completion_clock=lambda: NOW).run_once(NOW)

    assert source.calls == 0
    assert _read_outcomes(repository, 1) == []


def test_dispatch_rechecks_for_manual_outcome_added_after_forecast_read(
    repository: Repository,
) -> None:
    _add_forecast(repository, 1, 1)
    store = OutcomeCollectionStore(repository)
    original_load = store.load_forecast
    added = False

    def load_then_add_manual(claim, now):
        nonlocal added
        forecast = original_load(claim, now)
        if forecast is not None and not added:
            repository.append_outcome(
                1,
                1,
                104.0,
                0.04,
                TARGET,
                "observed",
                "entered by user",
                "close divided by immutable origin price minus one",
                NOW,
            )
            added = True
        return forecast

    store.load_forecast = load_then_add_manual
    source = FixtureOutcomeSource()

    with pytest.raises(OutcomeCollectionLeaseConflict, match="changed before dispatch"):
        DailyOutcomeCollector(store, source, completion_clock=lambda: NOW).run_once(NOW)

    assert source.calls == 0
    rows = _read_outcomes(repository, 1)
    assert len(rows) == 1
    assert rows[0]["note"] == "entered by user"


def test_dispatch_stop_check_prevents_provider_request_after_forecast_revalidation(
    repository: Repository,
) -> None:
    _add_forecast(repository, 1, 1)
    store = OutcomeCollectionStore(repository)
    original_load = store.load_forecast
    stopping = False
    load_count = 0

    def load_then_stop(claim, now):
        nonlocal load_count, stopping
        forecast = original_load(claim, now)
        load_count += 1
        if forecast is not None and load_count == 2:
            stopping = True
        return forecast

    store.load_forecast = load_then_stop
    source = FixtureOutcomeSource()

    with pytest.raises(OutcomeCollectionLeaseConflict, match="worker is stopping"):
        DailyOutcomeCollector(store, source, completion_clock=lambda: NOW).run_once(
            NOW, cancelled=lambda: stopping
        )

    assert source.calls == 0
    assert _read_outcomes(repository, 1) == []


def test_collection_store_rolls_back_when_worker_is_cancelled_before_commit(
    repository: Repository,
) -> None:
    _add_forecast(repository, 1, 1)
    store = OutcomeCollectionStore(repository)
    assert store.enqueue_due(NOW) == 1
    claim = store.claim_due("cancelled-worker", NOW, limit=1)[0]
    forecast = store.load_forecast(claim, NOW)
    assert forecast is not None

    with pytest.raises(OutcomeCollectionLeaseConflict, match="worker is stopping"):
        store.record_collection(
            claim,
            forecast,
            outcome_state="observed",
            observed_close=105.0,
            observed_at=TARGET,
            evidence_state="observed",
            evidence_payload={"method": "provider_bar"},
            now=NOW,
            source_succeeded=True,
            cancelled=lambda: True,
        )

    assert _read_outcomes(repository, 1) == []


class _NoOpPriceService:
    """Satisfy scheduler construction without providing a price job or network path."""

    def lookup(self, query: str, limit: int = 5) -> object:
        raise AssertionError("the test has no price work")

    def quote_snapshot(self, symbol: str, asset_type: str) -> object:
        raise AssertionError("the test has no price work")


def test_scheduler_close_cancels_inflight_outcome_without_a_second_worker(
    repository: Repository,
) -> None:
    _add_forecast(repository, 1, 1)
    entered_provider = threading.Event()
    release_provider = threading.Event()

    def block_provider_return() -> None:
        entered_provider.set()
        assert release_provider.wait(3)

    source = FixtureOutcomeSource(on_fetch=block_provider_return)
    collector = DailyOutcomeCollector(
        OutcomeCollectionStore(repository), source, completion_clock=lambda: NOW
    )
    scheduler = MonitoringScheduler(
        MonitoringStore(repository),
        _NoOpPriceService(),
        outcome_collector=collector,
        clock=lambda: NOW,
        poll_interval_seconds=0.05,
        batch_size=1,
    )
    asyncio.run(scheduler.start())
    assert entered_provider.wait(2)
    assert scheduler.run_once() == 0

    close_started = threading.Event()
    close_finished = threading.Event()

    def close_scheduler() -> None:
        close_started.set()
        asyncio.run(scheduler.close(timeout_seconds=3))
        close_finished.set()

    closer = threading.Thread(target=close_scheduler)
    closer.start()
    assert close_started.wait(1)
    assert scheduler._stop.wait(1)
    release_provider.set()
    closer.join(3)

    assert close_finished.is_set()
    assert not closer.is_alive()
    assert source.calls == 1
    assert _read_outcomes(repository, 1) == []


def test_valid_series_is_atomically_recorded_and_report_scorer_accepts_evidence(
    repository: Repository,
) -> None:
    _add_forecast(repository, 1, 1)
    source = FixtureOutcomeSource()
    result = DailyOutcomeCollector(OutcomeCollectionStore(repository), source).run_once(NOW)

    rows = _read_outcomes(repository, 1)
    assert result["recorded"] == 1
    assert source.calls == 1
    assert len(rows) == 1
    assert rows[0]["state"] == "observed"
    assert rows[0]["evidence_state"] == "observed"
    evidence = json.loads(str(rows[0]["payload_json"]))
    assert evidence["method"] == "provider_bar"
    assert evidence["comparability"]["corporate_actions"]["events"] == []
    scored = ReportCardStore(repository).list_report(1, NOW)
    assert scored["counts"]["scored"] == 1
    assert scored["items"][0]["direction_correct"] is True


def test_provider_latency_uses_completion_time_without_changing_target_session(
    repository: Repository,
) -> None:
    _add_forecast(repository, 1, 1)
    provider_as_of = NOW + timedelta(seconds=3)
    completed_at = NOW + timedelta(seconds=5)
    source = FixtureOutcomeSource(as_of=provider_as_of)
    collector = DailyOutcomeCollector(
        OutcomeCollectionStore(repository), source, completion_clock=lambda: completed_at
    )

    result = collector.run_once(NOW)

    row = _read_outcomes(repository, 1)[0]
    evidence = json.loads(str(row["payload_json"]))
    timestamp = completed_at.isoformat(timespec="microseconds").replace("+00:00", "Z")
    target_source_timestamp = TARGET.isoformat()
    target_outcome_timestamp = TARGET.isoformat(timespec="microseconds").replace("+00:00", "Z")
    assert result["recorded"] == 1
    assert source.requested_at == [completed_at]
    assert row["state"] == "observed"
    assert row["created_at"] == timestamp
    assert row["observed_at"] == target_outcome_timestamp
    assert evidence["bar"]["timestamp"] == target_source_timestamp
    with repository.connect() as connection:
        collected_at = connection.execute(
            "SELECT collected_at FROM collected_outcome_evidence WHERE outcome_id=?",
            (row["id"],),
        ).fetchone()[0]
    assert collected_at == timestamp


def test_provider_dispatch_and_completion_use_fresh_clock_samples(repository: Repository) -> None:
    _add_forecast(repository, 1, 1)
    dispatch_at = NOW + timedelta(seconds=3)
    completed_at = NOW + timedelta(seconds=5)
    source = FixtureOutcomeSource(as_of=NOW + timedelta(seconds=4))
    clock_values = iter((dispatch_at, completed_at))

    result = DailyOutcomeCollector(
        OutcomeCollectionStore(repository), source, completion_clock=lambda: next(clock_values)
    ).run_once(NOW)

    row = _read_outcomes(repository, 1)[0]
    timestamp = completed_at.isoformat(timespec="microseconds").replace("+00:00", "Z")
    assert result["recorded"] == 1
    assert source.calls == 1
    assert source.requested_at == [dispatch_at]
    assert row["state"] == "observed"
    assert row["created_at"] == timestamp


def test_completion_clock_is_not_sampled_during_collector_construction(
    repository: Repository,
) -> None:
    calls = 0

    def clock() -> datetime:
        nonlocal calls
        calls += 1
        return NOW

    DailyOutcomeCollector(OutcomeCollectionStore(repository), None, completion_clock=clock)

    assert calls == 0


def test_provider_as_of_after_completion_is_saved_as_unavailable(
    repository: Repository,
) -> None:
    _add_forecast(repository, 1, 1)
    completed_at = NOW + timedelta(seconds=5)
    source = FixtureOutcomeSource(as_of=completed_at + timedelta(microseconds=1))
    collector = DailyOutcomeCollector(
        OutcomeCollectionStore(repository), source, completion_clock=lambda: completed_at
    )

    collector.run_once(NOW)

    row = _read_outcomes(repository, 1)[0]
    timestamp = completed_at.isoformat(timespec="microseconds").replace("+00:00", "Z")
    assert row["state"] == "unavailable"
    assert row["created_at"] == timestamp
    assert json.loads(str(row["payload_json"])) == {"reason_code": "series_incomplete"}
    with repository.connect() as connection:
        collected_at = connection.execute(
            "SELECT collected_at FROM collected_outcome_evidence WHERE outcome_id=?",
            (row["id"],),
        ).fetchone()[0]
    assert collected_at == timestamp


def test_failed_provider_attempt_is_committed_at_completion_time(repository: Repository) -> None:
    _add_forecast(repository, 1, 1)

    class FailingSource:
        def fetch_daily_outcome_series(self, *args, **kwargs):
            raise TimeoutError("fixture provider timeout")

    completed_at = NOW + timedelta(seconds=7)
    DailyOutcomeCollector(
        OutcomeCollectionStore(repository),
        FailingSource(),
        completion_clock=lambda: completed_at,
    ).run_once(NOW)

    row = _read_outcomes(repository, 1)[0]
    timestamp = completed_at.isoformat(timespec="microseconds").replace("+00:00", "Z")
    assert row["state"] == "unavailable"
    assert row["created_at"] == timestamp
    assert json.loads(str(row["payload_json"])) == {"reason_code": "provider_unavailable"}


@pytest.mark.parametrize(
    "clock_value",
    [datetime(2026, 10, 15, 23, 0, 1), NOW - timedelta(microseconds=1), None],
    ids=["naive", "backward", "missing"],
)
def test_invalid_completion_clock_fails_closed_without_outcome_write(
    repository: Repository, clock_value: datetime | None
) -> None:
    _add_forecast(repository, 1, 1)
    source = FixtureOutcomeSource()

    with pytest.raises(ValueError):
        DailyOutcomeCollector(
            OutcomeCollectionStore(repository),
            source,
            completion_clock=lambda: clock_value,  # type: ignore[return-value]
        ).run_once(NOW)

    assert source.calls == 0
    assert _read_outcomes(repository, 1) == []


def test_expired_lease_after_parsing_prevents_provider_dispatch(
    repository: Repository,
) -> None:
    _add_forecast(repository, 1, 1)
    source = FixtureOutcomeSource()
    dispatch_after_lease = NOW + timedelta(seconds=301)

    with pytest.raises(OutcomeCollectionLeaseConflict, match="changed before dispatch"):
        DailyOutcomeCollector(
            OutcomeCollectionStore(repository),
            source,
            completion_clock=lambda: dispatch_after_lease,
        ).run_once(NOW)

    assert source.calls == 0
    assert _read_outcomes(repository, 1) == []


def test_lease_expiring_during_provider_request_still_blocks_outcome_write(
    repository: Repository,
) -> None:
    _add_forecast(repository, 1, 1)
    source = FixtureOutcomeSource(as_of=NOW + timedelta(seconds=2))
    clock_values = iter((NOW + timedelta(seconds=1), NOW + timedelta(seconds=301)))

    with pytest.raises(OutcomeCollectionLeaseConflict, match="lease is stale"):
        DailyOutcomeCollector(
            OutcomeCollectionStore(repository), source, completion_clock=lambda: next(clock_values)
        ).run_once(NOW)

    assert source.calls == 1
    assert source.requested_at == [NOW + timedelta(seconds=1)]
    assert _read_outcomes(repository, 1) == []


@pytest.mark.parametrize(
    "horizon",
    [None, "", "unknown", {"unhashable": True}],
    ids=["missing", "empty", "unknown", "unhashable"],
)
def test_malformed_horizon_is_unavailable_before_session_lookup(
    repository: Repository, horizon: object
) -> None:
    forecast = _forecast()
    forecast["horizon"] = horizon
    source = FixtureOutcomeSource()
    collector = DailyOutcomeCollector(OutcomeCollectionStore(repository), source)
    target = OutcomeForecast(
        owner_user_id=1,
        result_id=1,
        symbol="SPY",
        asset_type="stock",
        forecast=forecast,
        latest_outcome_is_manual=False,
    )

    result = collector._collect(target, NOW)

    assert result.collection.outcome_state == "unavailable"
    assert result.collection.evidence_state == "unavailable"
    assert result.collection.evidence_payload == {"reason_code": "series_incomplete"}
    assert source.calls == 0


def test_unhashable_saved_horizon_is_safely_deferred(repository: Repository) -> None:
    forecast = _forecast()
    forecast["horizon"] = {"unhashable": True}
    _add_forecast(repository, 1, 1, forecast_payload=forecast)
    source = FixtureOutcomeSource()

    result = DailyOutcomeCollector(OutcomeCollectionStore(repository), source).run_once(NOW)

    assert result["skipped"] == 1
    assert source.calls == 0
    assert _read_outcomes(repository, 1) == []
    with repository.connect() as connection:
        failure_code = connection.execute(
            "SELECT failure_code FROM monitoring_jobs WHERE kind='outcome' AND resource_id='1'"
        ).fetchone()[0]
    assert failure_code == "forecast_unavailable"


def test_invalid_inserted_outcome_id_rolls_back_collection_transaction(
    repository: Repository,
) -> None:
    _add_forecast(repository, 1, 1)
    with repository.connect() as connection:
        connection.execute(
            "CREATE TRIGGER ignore_collected_outcome BEFORE INSERT ON outcomes "
            "BEGIN SELECT RAISE(IGNORE); END"
        )
        connection.commit()

    with pytest.raises(OutcomeCollectionStoreError, match="identifier is invalid"):
        DailyOutcomeCollector(OutcomeCollectionStore(repository), FixtureOutcomeSource()).run_once(
            NOW
        )

    assert _read_outcomes(repository, 1) == []
    with repository.connect() as connection:
        job = connection.execute(
            "SELECT lease_token,active_request_id FROM monitoring_jobs "
            "WHERE kind='outcome' AND resource_id='1'"
        ).fetchone()
    assert job["lease_token"] is not None
    assert job["active_request_id"] is not None


def test_missing_trusted_action_capability_records_unavailable_once(repository: Repository) -> None:
    _add_forecast(repository, 1, 1)
    collector = DailyOutcomeCollector(OutcomeCollectionStore(repository), source=None)

    first = collector.run_once(NOW)
    second = collector.run_once(NOW + timedelta(days=1))

    rows = _read_outcomes(repository, 1)
    assert first["recorded"] == 1
    assert second["unchanged"] == 1
    assert len(rows) == 1
    assert rows[0]["state"] == "unavailable"
    assert rows[0]["evidence_state"] == "unavailable"
    assert json.loads(str(rows[0]["payload_json"])) == {"reason_code": "corporate_action_unknown"}
    report = ReportCardStore(repository).list_report(1, NOW + timedelta(days=1))
    assert report["counts"]["unavailable"] == 1
    assert report["counts"]["scored"] == 0


def test_action_events_are_never_treated_as_a_checked_clear_interval(
    repository: Repository,
) -> None:
    _add_forecast(repository, 1, 1)
    source = FixtureOutcomeSource(actions=("split",))
    DailyOutcomeCollector(OutcomeCollectionStore(repository), source).run_once(NOW)

    row = _read_outcomes(repository, 1)[0]
    assert row["state"] == "unavailable"
    assert row["evidence_state"] == "unavailable"
    assert json.loads(str(row["payload_json"])) == {"reason_code": "corporate_action_unknown"}


def test_missing_daily_sessions_never_become_a_scored_outcome(repository: Repository) -> None:
    _add_forecast(repository, 1, 1, horizon="weekly_5")
    DailyOutcomeCollector(OutcomeCollectionStore(repository), FixtureOutcomeSource()).run_once(NOW)

    row = _read_outcomes(repository, 1)[0]
    assert row["state"] == "unavailable"
    assert row["evidence_state"] == "unavailable"
    assert json.loads(str(row["payload_json"])) == {"reason_code": "series_incomplete"}


def test_provider_correction_appends_a_new_outcome_without_mutating_forecast(
    repository: Repository,
) -> None:
    forecast = _add_forecast(repository, 1, 1)
    store = OutcomeCollectionStore(repository)
    first_completed = NOW + timedelta(seconds=5)
    first_collector = DailyOutcomeCollector(
        store,
        FixtureOutcomeSource(105.0, as_of=NOW + timedelta(seconds=3)),
        completion_clock=lambda: first_completed,
    )
    first_collector.run_once(NOW)
    correction_request = NOW + timedelta(days=1, minutes=1)
    correction_completed = correction_request + timedelta(seconds=5)
    correction_collector = DailyOutcomeCollector(
        store,
        FixtureOutcomeSource(106.0, as_of=correction_request + timedelta(seconds=3)),
        completion_clock=lambda: correction_completed,
    )
    correction_collector.run_once(correction_request)

    rows = _read_outcomes(repository, 1)
    assert [row["state"] for row in rows] == ["observed", "corrected"]
    assert [row["observed_close"] for row in rows] == [105.0, 106.0]
    assert [row["created_at"] for row in rows] == [
        first_completed.isoformat(timespec="microseconds").replace("+00:00", "Z"),
        correction_completed.isoformat(timespec="microseconds").replace("+00:00", "Z"),
    ]
    with repository.connect() as connection:
        stored = json.loads(
            connection.execute("SELECT result_json FROM forecast_results WHERE id=1").fetchone()[0]
        )
    assert stored == forecast


@pytest.mark.parametrize("change", ["revoke_owner", "disable_monitoring"])
def test_completion_commit_rechecks_owner_and_monitoring_controls(
    repository: Repository, change: str
) -> None:
    _add_forecast(repository, 1, 1)

    def update_control() -> None:
        with repository.connect() as connection:
            if change == "revoke_owner":
                connection.execute("UPDATE users SET status='disabled' WHERE id=1")
            else:
                connection.execute("UPDATE monitoring_control SET enabled=0 WHERE id=1")
            connection.commit()

    source = FixtureOutcomeSource(as_of=NOW + timedelta(seconds=1), on_fetch=update_control)
    with pytest.raises(OutcomeCollectionLeaseConflict):
        DailyOutcomeCollector(
            OutcomeCollectionStore(repository),
            source,
            completion_clock=lambda: NOW + timedelta(seconds=2),
        ).run_once(NOW)

    assert source.calls == 1
    assert _read_outcomes(repository, 1) == []


def test_user_outcome_added_after_queue_is_preserved(repository: Repository) -> None:
    _add_forecast(repository, 1, 1)
    store = OutcomeCollectionStore(repository)
    store.enqueue_due(NOW)
    repository.append_outcome(
        1,
        1,
        104.0,
        0.04,
        TARGET,
        "observed",
        "entered by user",
        "close divided by immutable origin price minus one",
        NOW,
    )
    source = FixtureOutcomeSource(105.0)

    result = DailyOutcomeCollector(store, source).run_once(NOW)

    assert result["skipped"] == 1
    assert source.calls == 0
    rows = _read_outcomes(repository, 1)
    assert len(rows) == 1
    assert rows[0]["observed_close"] == 104.0
    with repository.connect() as connection:
        job = connection.execute(
            "SELECT due_at,lease_token,checkpoint_json FROM monitoring_jobs "
            "WHERE kind='outcome' AND resource_id='1'"
        ).fetchone()
    assert job["due_at"] == "9999-12-31T23:59:59.999999Z"
    assert job["lease_token"] is None
    assert json.loads(job["checkpoint_json"])["disposition"] == "manual_outcome_preserved"


def test_outcome_and_evidence_rollback_together_when_sidecar_insert_fails(
    repository: Repository,
) -> None:
    _add_forecast(repository, 1, 1)
    with repository.connect() as connection:
        connection.execute(
            "CREATE TRIGGER reject_fixture_evidence BEFORE INSERT ON collected_outcome_evidence "
            "BEGIN SELECT RAISE(ABORT,'fixture evidence rejection'); END"
        )
        connection.commit()

    with pytest.raises(sqlite3.IntegrityError, match="fixture evidence rejection"):
        DailyOutcomeCollector(OutcomeCollectionStore(repository), FixtureOutcomeSource()).run_once(
            NOW
        )

    assert _read_outcomes(repository, 1) == []
    with repository.connect() as connection:
        job = connection.execute(
            "SELECT lease_token,active_request_id FROM monitoring_jobs "
            "WHERE kind='outcome' AND resource_id='1'"
        ).fetchone()
    assert job["lease_token"] is not None
    assert job["active_request_id"] is not None


def test_lease_expiry_prevents_atomic_outcome_and_evidence_write(repository: Repository) -> None:
    _add_forecast(repository, 1, 1)
    store = OutcomeCollectionStore(repository)
    store.enqueue_due(NOW)
    stale = store.claim_due("worker-a", NOW, limit=1, lease_seconds=5)[0]
    current_time = NOW + timedelta(seconds=6)
    current = store.claim_due("worker-b", current_time, limit=1, lease_seconds=30)[0]
    forecast = store.load_forecast(stale, current_time)
    assert forecast is None
    current_forecast = store.load_forecast(current, current_time)
    assert current_forecast is not None
    with pytest.raises(OutcomeCollectionLeaseConflict):
        store.record_collection(
            stale,
            current_forecast,
            outcome_state="observed",
            observed_close=105.0,
            observed_at=TARGET,
            evidence_state="observed",
            evidence_payload={"method": "provider_bar"},
            now=current_time,
            source_succeeded=True,
        )
    assert _read_outcomes(repository, 1) == []
