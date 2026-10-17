"""Deterministic persisted-price scheduler tests using disposable SQLite databases."""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest

import stock_probs.repository as repository_module
from stock_probs.monitoring_scheduler import MonitoringScheduler
from stock_probs.monitoring_store import (
    MonitoringConflictError,
    MonitoringStore,
    MonitoringStoreError,
)
from stock_probs.provider import YAHOO_PROVIDER_NAME
from stock_probs.repository import Repository

ROOT = Path(__file__).parents[1]
DRAFT_MIGRATION = ROOT / "src/stock_probs/migrations/016_monitoring_and_report_cards.sql"
NOW = datetime(2026, 10, 12, 13, 30, tzinfo=UTC)


@pytest.fixture
def monitoring_store(tmp_path, monkeypatch):
    """Create a disposable schema-16 database, retaining the unregistered-draft fixture path."""

    migrations_source = ROOT / "src/stock_probs/migrations"
    migration_016 = migrations_source / "016_monitoring_and_report_cards.sql"
    registered_016 = (
        repository_module.SCHEMA_VERSION >= 16
        and repository_module.MIGRATION_SHA256.get(16)
        == hashlib.sha256(migration_016.read_bytes()).hexdigest()
    )
    if not registered_016:
        current15 = tmp_path / "registered-migrations-v15"
        current15.mkdir()
        for path in sorted(migrations_source.glob("[0-9][0-9][0-9]_*.sql")):
            if int(path.name[:3]) <= 15:
                (current15 / path.name).write_bytes(path.read_bytes())
        previous_files = repository_module.files

        def only_registered_migrations(package: str):
            if package == "stock_probs.migrations":
                return current15
            return previous_files(package)

        monkeypatch.setattr(repository_module, "files", only_registered_migrations)
    repository = Repository(tmp_path / "monitoring.sqlite3")
    repository.migrate()
    if not registered_016:
        with repository.connect() as connection:
            connection.executescript(DRAFT_MIGRATION.read_text(encoding="utf-8"))
            connection.commit()
    repository.create_user(
        github_user_id=7201,
        login="scheduler-owner-two",
        display_name="Scheduler owner two",
        password_hash=None,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    return MonitoringStore(repository, write_authorization_mode="test_no_auth")


def _config(symbol: str = "SPY") -> dict[str, object]:
    return {
        "symbol": symbol,
        "currency": "USD",
        "threshold": "100",
        "direction": "above",
        "repeating": True,
    }


def _create_alert(store: MonitoringStore, owner: int = 1, symbol: str = "SPY") -> dict[str, object]:
    return store.create_alert(owner, str(uuid4()), _config(symbol), NOW)


def _enable(store: MonitoringStore) -> None:
    store.set_control(1, True, NOW)


class StubForecastService:
    """Return bounded provider-shaped dictionaries without any network access."""

    def __init__(self, now: datetime) -> None:
        self.now = now
        self.price_value = 99.0
        self.calls: list[tuple[str, str]] = []
        self.lookup_hook: Callable[[str], None] | None = None
        self.quote_hook: Callable[[str], None] | None = None
        self.lookup_error = False
        self.quote_error = False

    def lookup(self, query: str, limit: int = 5) -> object:
        self.calls.append(("lookup", query))
        if self.lookup_hook is not None:
            self.lookup_hook(query)
        if self.lookup_error:
            raise RuntimeError("provider internals are intentionally not retained")
        return {
            "query": query,
            "limit": limit,
            "total": 1,
            "items": [
                {
                    "canonical_symbol": query,
                    "currency": "USD",
                    "asset_type": "etf",
                    "provider": YAHOO_PROVIDER_NAME,
                    "provider_as_of": self.now.isoformat(),
                }
            ],
        }

    def quote_snapshot(self, symbol: str, asset_type: str) -> object:
        self.calls.append(("quote", symbol))
        if self.quote_hook is not None:
            self.quote_hook(symbol)
        if self.quote_error:
            raise RuntimeError("provider internals are intentionally not retained")
        return {
            "symbol": symbol,
            "price": self.price_value,
            "currency": "USD",
            "as_of": (self.now - timedelta(minutes=1)).isoformat(),
            "provider": YAHOO_PROVIDER_NAME,
            "delayed": True,
            "delay_minutes": 15,
            "label": "Yahoo Finance delayed quote.",
        }


class StubOutcomeCollector:
    """Return deterministic batch summaries and record each selected scheduler turn."""

    def __init__(self) -> None:
        self.calls: list[datetime] = []
        self.fail_next = False

    def run_once(
        self,
        now: datetime,
        *,
        worker_id: str,
        limit: int,
        cancelled: Callable[[], bool],
    ) -> dict[str, int]:
        assert worker_id
        assert limit > 0
        self.calls.append(now)
        if self.fail_next:
            self.fail_next = False
            raise RuntimeError("fixture failure")
        return {"claimed": 1, "recorded": 1, "unchanged": 0, "skipped": 0}


def test_constructor_is_inert_and_explicit_lifespan_start_close_are_bounded(
    monitoring_store,
):
    service = StubForecastService(NOW)
    scheduler = MonitoringScheduler(monitoring_store, service, clock=lambda: NOW)

    assert scheduler.status() == {"running": False}
    assert service.calls == []
    asyncio.run(scheduler.start())
    assert scheduler.status() == {"running": True}
    asyncio.run(scheduler.close())

    assert scheduler.status() == {"running": False}
    assert service.calls == []
    with pytest.raises(RuntimeError, match="cannot be restarted"):
        asyncio.run(scheduler.start())


def test_scheduler_uses_fair_price_only_claims_and_first_snapshot_never_notifies(
    monitoring_store,
):
    store = monitoring_store
    first = _create_alert(store, 1, "SPY")
    second = _create_alert(store, 2, "ACDC")
    outcome_id = store.schedule_job(1, "outcome", "outcome:keep", NOW, now=NOW)
    _enable(store)
    service = StubForecastService(NOW)
    scheduler = MonitoringScheduler(
        store, service, clock=lambda: service.now, batch_size=2, worker_id="price-only"
    )

    assert scheduler.run_once() == 2
    assert [name for name, _ in service.calls] == ["lookup", "quote", "lookup", "quote"]
    assert service.calls[0][1] == "SPY" and service.calls[2][1] == "ACDC"
    assert store.get_alert(1, str(first["id"]))["arm_snapshot_generation"] == 1
    assert store.get_alert(2, str(second["id"]))["arm_snapshot_generation"] == 1
    assert store.list_notifications(1)["items"] == []
    assert store.list_notifications(2)["items"] == []
    with store.repository.connect() as connection:
        outcome = connection.execute(
            "SELECT attempts,lease_token FROM monitoring_jobs WHERE id=?", (outcome_id,)
        ).fetchone()
    assert outcome["attempts"] == 0 and outcome["lease_token"] is None


def test_scheduler_alternates_bounded_price_and_outcome_batches(monitoring_store):
    store = monitoring_store
    _create_alert(store)
    _enable(store)
    clock = [NOW]
    service = StubForecastService(NOW)
    collector = StubOutcomeCollector()
    scheduler = MonitoringScheduler(
        store,
        service,
        outcome_collector=collector,
        clock=lambda: clock[0],
        batch_size=1,
    )

    assert scheduler.run_once() == 1
    assert service.calls == [("lookup", "SPY"), ("quote", "SPY")]
    assert scheduler.run_once() == 1
    assert collector.calls == [NOW]
    clock[0] += timedelta(minutes=15)
    service.now = clock[0]
    assert scheduler.run_once() == 1
    assert scheduler.run_once() == 1
    assert collector.calls == [NOW, clock[0]]
    assert [name for name, _ in service.calls].count("lookup") == 2


def test_failed_outcome_batch_does_not_stop_the_next_price_batch(monitoring_store):
    store = monitoring_store
    _create_alert(store)
    _enable(store)
    clock = [NOW]
    service = StubForecastService(NOW)
    collector = StubOutcomeCollector()
    collector.fail_next = True
    scheduler = MonitoringScheduler(
        store,
        service,
        outcome_collector=collector,
        clock=lambda: clock[0],
        batch_size=1,
    )

    assert scheduler.run_once() == 1
    assert scheduler.run_once() == 0
    clock[0] += timedelta(minutes=15)
    service.now = clock[0]
    assert scheduler.run_once() == 1
    assert collector.calls == [NOW]
    assert [name for name, _ in service.calls] == ["lookup", "quote", "lookup", "quote"]


def test_admin_only_claims_exclude_member_alerts_and_reject_member_changes(monitoring_store):
    regular_store = monitoring_store
    admin_alert = _create_alert(regular_store, owner=1)
    member_alert = _create_alert(regular_store, owner=2, symbol="ACDC")
    _enable(regular_store)
    canary_store = MonitoringStore(
        regular_store.repository, admin_only=True, write_authorization_mode="test_no_auth"
    )

    claims = canary_store.claim_due_price_jobs("admin-canary", NOW, limit=2)
    assert [claim["owner_user_id"] for claim in claims] == [1]
    assert claims[0]["resource_id"] == admin_alert["id"]
    with regular_store.repository.connect() as connection:
        member_job = connection.execute(
            "SELECT lease_token,attempts FROM monitoring_jobs "
            "WHERE owner_user_id=2 AND kind='price' AND resource_id=?",
            (member_alert["id"],),
        ).fetchone()
    assert member_job["lease_token"] is None and member_job["attempts"] == 0
    with pytest.raises(MonitoringStoreError, match="owner is unavailable"):
        _create_alert(canary_store, owner=2, symbol="VFV.TO")
    with pytest.raises(TypeError, match="admin_only must be a boolean"):
        MonitoringStore(
            regular_store.repository,
            admin_only=1,  # type: ignore[arg-type]
            write_authorization_mode="test_no_auth",
        )


def test_admin_demotion_during_lookup_blocks_canary_quote_and_write(monitoring_store):
    regular_store = monitoring_store
    alert = _create_alert(regular_store)
    _enable(regular_store)
    canary_store = MonitoringStore(
        regular_store.repository, admin_only=True, write_authorization_mode="test_no_auth"
    )
    service = StubForecastService(NOW)

    def demote_admin(_query: str) -> None:
        with regular_store.repository.connect() as connection:
            connection.execute("UPDATE users SET role='member' WHERE id=1")
            connection.commit()

    service.lookup_hook = demote_admin
    scheduler = MonitoringScheduler(canary_store, service, clock=lambda: NOW, batch_size=1)

    assert scheduler.run_once() == 0
    assert service.calls == [("lookup", "SPY")]
    assert regular_store.get_alert(1, str(alert["id"]))["last_observation"] is None


def test_persisted_tick_triggers_only_after_a_later_crossing(monitoring_store):
    store = monitoring_store
    alert = _create_alert(store)
    _enable(store)
    clock = [NOW]
    service = StubForecastService(NOW)
    scheduler = MonitoringScheduler(
        store, service, clock=lambda: clock[0], worker_id="crossing-worker"
    )

    assert scheduler.run_once() == 1
    initial = store.get_alert(1, str(alert["id"]))
    assert initial["ready"] is True
    assert initial["last_success_at"] == "2026-10-12T13:30:00.000000Z"
    assert store.list_notifications(1)["items"] == []

    clock[0] += timedelta(minutes=15)
    service.now = clock[0]
    service.price_value = 101.0
    assert scheduler.run_once() == 1
    notifications = store.list_notifications(1)["items"]
    assert len(notifications) == 1 and notifications[0]["kind"] == "price_alert"
    updated = store.get_alert(1, str(alert["id"]))
    assert updated["last_observation"]["currency"] == "USD"
    assert updated["last_observation"]["symbol"] == "SPY"
    assert updated["last_observation"]["provider"] == YAHOO_PROVIDER_NAME


def test_restarted_scheduler_waits_for_expired_persisted_lease(monitoring_store):
    store = monitoring_store
    alert = _create_alert(store)
    _enable(store)
    original = store.claim_due_price_jobs("crashed-process", NOW, limit=1, lease_seconds=5)[0]
    service = StubForecastService(NOW + timedelta(seconds=4))
    restarted = MonitoringScheduler(
        store, service, clock=lambda: service.now, worker_id="restarted-process"
    )

    assert restarted.run_once() == 0
    assert service.calls == []
    service.now = NOW + timedelta(seconds=6)
    assert restarted.run_once() == 1
    assert store.get_alert(1, str(alert["id"]))["arm_snapshot_generation"] == 1
    assert service.calls[0] == ("lookup", "SPY")
    with pytest.raises(MonitoringConflictError, match="stale or no longer leased"):
        store.get_price_claim_context(1, str(alert["id"]), original, service.now)


def test_provider_failure_keeps_last_good_observation_and_uses_bounded_retry(monitoring_store):
    store = monitoring_store
    alert = _create_alert(store)
    _enable(store)
    clock = [NOW]
    service = StubForecastService(NOW)
    scheduler = MonitoringScheduler(store, service, clock=lambda: clock[0], worker_id="failure")
    assert scheduler.run_once() == 1
    before = store.get_alert(1, str(alert["id"]))

    clock[0] += timedelta(minutes=15)
    service.now = clock[0]
    service.quote_error = True
    assert scheduler.run_once() == 1
    after = store.get_alert(1, str(alert["id"]))

    assert after["check_state"] == "unavailable"
    assert after["last_observation"] == before["last_observation"]
    assert after["last_observed_at"] == before["last_observed_at"]
    assert after["last_success_at"] == before["last_success_at"]
    assert after["last_check_at"] == "2026-10-12T13:45:00.000000Z"
    with store.repository.connect() as connection:
        job = connection.execute(
            "SELECT due_at,failure_code,lease_token FROM monitoring_jobs "
            "WHERE owner_user_id=1 AND kind='price' AND resource_id=?",
            (alert["id"],),
        ).fetchone()
    assert job["due_at"] == "2026-10-12T14:00:00.000000Z"
    assert job["failure_code"] == "provider_unavailable" and job["lease_token"] is None


def test_disable_during_lookup_prevents_quote_provider_and_any_effect(monitoring_store):
    store = monitoring_store
    alert = _create_alert(store)
    _enable(store)
    service = StubForecastService(NOW)

    def disable_after_lookup(_query: str) -> None:
        current = store.get_control()
        store.set_control(current["revision"], False, NOW + timedelta(seconds=1))

    service.lookup_hook = disable_after_lookup
    scheduler = MonitoringScheduler(store, service, clock=lambda: NOW, worker_id="disabled")

    assert scheduler.run_once() == 0
    assert service.calls == [("lookup", "SPY")]
    current = store.get_alert(1, str(alert["id"]))
    assert current["last_observation"] is None and current["last_success_at"] is None
    assert store.get_control()["enabled"] is False


def test_owner_revocation_before_quote_prevents_provider_call_and_claim_effect(monitoring_store):
    store = monitoring_store
    alert = _create_alert(store)
    _enable(store)
    service = StubForecastService(NOW)

    def revoke_after_lookup(_query: str) -> None:
        with store.repository.connect() as connection:
            connection.execute("UPDATE users SET status='disabled' WHERE id=1")
            connection.commit()

    service.lookup_hook = revoke_after_lookup
    scheduler = MonitoringScheduler(store, service, clock=lambda: NOW, worker_id="revoked")

    assert scheduler.run_once() == 0
    assert service.calls == [("lookup", "SPY")]
    with store.repository.connect() as connection:
        row = connection.execute(
            "SELECT last_observation_json,last_success_at FROM price_alerts WHERE id=?",
            (alert["id"],),
        ).fetchone()
    assert row["last_observation_json"] is None and row["last_success_at"] is None


def test_lookup_must_resolve_exact_live_provider_identity_before_quote(monitoring_store):
    store = monitoring_store
    alert = _create_alert(store)
    _enable(store)
    service = StubForecastService(NOW)
    original = service.lookup

    def simulated_identity(query: str, limit: int = 5) -> object:
        result = original(query, limit)
        assert isinstance(result, dict)
        result["items"][0]["provider"] = "deterministic simulated fixture"
        return result

    service.lookup = simulated_identity  # type: ignore[method-assign]
    scheduler = MonitoringScheduler(store, service, clock=lambda: NOW, worker_id="identity")

    assert scheduler.run_once() == 1
    assert service.calls == [("lookup", "SPY")]
    state = store.get_alert(1, str(alert["id"]))
    assert state["check_state"] == "unavailable"
    assert state["last_observation"] is None
    assert store.list_notifications(1)["items"] == []


@pytest.mark.parametrize(
    "mutation",
    [
        {"currency": "CAD"},
        {"provider": "deterministic simulated fixture"},
        {"as_of": "2026-10-12T13:30:00"},
        {"price": float("nan")},
    ],
)
def test_malformed_or_simulated_quote_is_recorded_as_failure(monitoring_store, mutation):
    store = monitoring_store
    alert = _create_alert(store)
    _enable(store)
    service = StubForecastService(NOW)
    original = service.quote_snapshot

    def malformed_quote(symbol: str, asset_type: str) -> object:
        quote = original(symbol, asset_type)
        assert isinstance(quote, dict)
        quote.update(mutation)
        return quote

    service.quote_snapshot = malformed_quote  # type: ignore[method-assign]
    scheduler = MonitoringScheduler(store, service, clock=lambda: NOW, worker_id="malformed")

    assert scheduler.run_once() == 1
    state = store.get_alert(1, str(alert["id"]))
    assert state["check_state"] == "unavailable"
    assert state["last_observation"] is None
    assert store.list_notifications(1)["items"] == []
