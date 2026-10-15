"""Verify normal application ownership, rollout and scheduler lifecycle boundaries."""

from dataclasses import replace
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from stock_probs.api import create_app
from stock_probs.config import Settings
from stock_probs.provider import FixtureProvider

NOW = datetime(2026, 10, 14, 6, tzinfo=UTC)


class InertMonitoringRuntime:
    """Count lifecycle calls without creating a thread or contacting a provider."""

    def __init__(self, *, fail_start=False):
        self.starts = 0
        self.closes = 0
        self.running = False
        self.fail_start = fail_start

    async def start(self):
        self.starts += 1
        if self.fail_start:
            raise RuntimeError("synthetic startup failure")
        self.running = True

    async def close(self):
        self.closes += 1
        self.running = False

    def status(self):
        return {"running": self.running}


class ReadOnlyFixtureProvider(FixtureProvider):
    """Any provider call during collection reads or queued arming fails the test."""

    def lookup(self, *args, **kwargs):
        raise AssertionError("A collection read must not call the provider.")

    def quote_snapshot(self, *args, **kwargs):
        raise AssertionError("Queued arming must wait for the background worker.")


def _application(settings, runtime, *, enabled=True, scheduler=True, canary=False):
    config = replace(
        settings,
        monitoring_features_enabled=enabled,
        monitoring_features_canary_only=canary,
        monitoring_scheduler_enabled=scheduler,
    )
    return create_app(config, ReadOnlyFixtureProvider(), lambda: NOW, monitoring_runtime=runtime)


def test_construction_is_inert_and_only_normal_enabled_lifespan_starts_runtime(settings):
    runtime = InertMonitoringRuntime()
    application = _application(settings, runtime)
    assert runtime.starts == runtime.closes == 0
    with TestClient(application) as client:
        assert runtime.starts == 1
        assert client.get("/api/v1/readiness").json()["status"] == "ready"
        features = client.get("/api/v1/monitoring/features").json()
        assert features["enabled"] is True and features["can_arm"] is False
        assert features["email_available"] is False
    assert runtime.closes == 1 and runtime.running is False


@pytest.mark.parametrize("canary", [False, True])
def test_normal_runtime_shares_service_and_completion_clock_without_starting(settings, canary):
    """One application worker owns both job kinds and the same rollout policy."""
    application = _application(settings, None, canary=canary)
    runtime = application.state.monitoring
    assert runtime.status() == {"running": False}
    assert runtime.store is application.state.monitoring_store
    assert runtime.store.admin_only is canary
    collector = runtime.outcome_collector
    assert collector is not None
    assert collector.source is runtime.service
    assert collector.store.repository is runtime.store.repository
    assert collector.store.admin_only is canary
    assert collector.completion_clock is runtime.clock
    assert collector.completion_clock() == NOW


def test_disabled_scheduler_constructs_no_runtime_or_collector(settings):
    application = _application(settings, None, scheduler=False)
    assert application.state.monitoring is None


@pytest.mark.parametrize("enabled,scheduler", [(False, True), (True, False), (False, False)])
def test_either_independent_environment_control_prevents_worker_start(settings, enabled, scheduler):
    runtime = InertMonitoringRuntime()
    with TestClient(
        _application(settings, runtime, enabled=enabled, scheduler=scheduler)
    ) as client:
        assert client.get("/api/v1/readiness").json()["status"] == "ready"
        if not enabled:
            assert client.get("/api/v1/alerts").status_code == 503
            assert client.get("/api/v1/report-cards").status_code == 503
    assert runtime.starts == runtime.closes == 0


def test_startup_failure_preserves_service_and_closes_partial_runtime(settings):
    runtime = InertMonitoringRuntime(fail_start=True)
    with TestClient(_application(settings, runtime)) as client:
        assert client.get("/api/v1/readiness").json()["status"] == "ready"
        assert client.get("/api/v1/monitoring/features").json()["can_arm"] is False
        assert client.get("/api/v1/notifications").json()["items"] == []
    assert runtime.starts == runtime.closes == 1


def test_canary_flag_hides_resource_routes_from_disabled_auth_legacy_owner(settings):
    runtime = InertMonitoringRuntime()
    with TestClient(_application(settings, runtime, canary=True)) as client:
        assert client.get("/api/v1/monitoring/features").json()["enabled"] is False
        for path in ("/api/v1/alerts", "/api/v1/notifications", "/api/v1/report-cards"):
            assert client.get(path).status_code == 503


def test_enabled_routes_queue_initial_observation_without_provider_or_notification(settings):
    runtime = InertMonitoringRuntime()
    application = _application(settings, runtime)
    with TestClient(application) as client:
        assert client.get("/api/v1/report-cards").json()["total"] == 0
        assert client.get("/api/v1/alerts").json()["items"] == []
        application.state.monitoring_store.set_control(1, True, NOW)
        assert client.get("/api/v1/monitoring/features").json()["can_arm"] is True
        key = str(uuid4())
        payload = {
            "symbol": "SPY",
            "currency": "USD",
            "threshold": "100",
            "direction": "above",
            "repeating": False,
        }
        created = client.post("/api/v1/alerts", json=payload, headers={"Idempotency-Key": key})
        assert created.status_code == 201, created.text
        assert created.json()["state"] == "arming" and created.json()["baseline_ready"] is False
        replay = client.post("/api/v1/alerts", json=payload, headers={"Idempotency-Key": key})
        assert replay.status_code == 200 and replay.json()["id"] == created.json()["id"]
        assert client.get("/api/v1/notifications").json()["items"] == []
        exported = client.get("/api/v1/monitoring/export?sections=rules&format=csv")
        assert exported.status_code == 200 and "SPY" in exported.text
        assert exported.headers["cache-control"] == "no-store"
        application.state.monitoring_store.set_control(2, False, NOW)
        assert client.get("/api/v1/monitoring/features").json()["can_arm"] is False
        assert (
            client.post(
                "/api/v1/alerts", json=payload, headers={"Idempotency-Key": str(uuid4())}
            ).status_code
            == 503
        )


def test_administrator_control_requires_authenticated_session(settings):
    with TestClient(_application(settings, InertMonitoringRuntime())) as client:
        assert client.get("/api/v1/admin/monitoring/control").status_code == 401
        assert (
            client.put(
                "/api/v1/admin/monitoring/control", json={"expected_revision": 1, "enabled": True}
            ).status_code
            == 401
        )


def test_monitoring_flags_are_explicit_and_default_disabled(monkeypatch):
    names = (
        "STOCK_PROBS_MONITORING_FEATURES_ENABLED",
        "STOCK_PROBS_MONITORING_FEATURES_CANARY_ONLY",
        "STOCK_PROBS_MONITORING_SCHEDULER_ENABLED",
    )
    for name in names:
        monkeypatch.delenv(name, raising=False)
    defaults = Settings.from_env()
    assert not defaults.monitoring_features_enabled and not defaults.monitoring_scheduler_enabled
    assert defaults.monitoring_features_canary_only
    monkeypatch.setenv(names[0], "true")
    monkeypatch.setenv(names[1], "false")
    monkeypatch.setenv(names[2], "true")
    enabled = Settings.from_env()
    assert enabled.monitoring_features_enabled and enabled.monitoring_scheduler_enabled
    assert not enabled.monitoring_features_canary_only
    monkeypatch.setenv(names[2], "unknown")
    with pytest.raises(ValueError, match="must be true or false"):
        Settings.from_env()
