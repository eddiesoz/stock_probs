"""Standalone HTTP tests for the owner-scoped monitoring router foundation."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from stock_probs.monitoring_api import create_monitoring_router
from stock_probs.monitoring_store import MonitoringStore
from stock_probs.repository import Repository

NOW = datetime(2026, 10, 14, 4, 0, tzinfo=UTC)


@pytest.fixture
def monitoring_store(tmp_path):
    """Create an isolated current-schema repository with two authenticated owners."""
    repository = Repository(tmp_path / "monitoring-api.sqlite3")
    repository.migrate()
    for github_user_id in (91, 92):
        repository.create_user(
            github_user_id=github_user_id,
            login=f"monitoring-member-{github_user_id}",
            display_name="Monitoring member",
            password_hash=None,
            created_at=NOW,
        )
    return MonitoringStore(repository, write_authorization_mode="test_no_auth")


def _client(
    store: MonitoringStore,
    owner: int | None = 1,
    arm_available: Callable[[], bool] | None = None,
    email_available: Callable[[], bool] | None = None,
) -> TestClient:
    """Build a standalone router app with a fixed test session-owner resolver."""
    application = FastAPI()
    application.include_router(
        create_monitoring_router(
            store,
            lambda _request: owner,
            lambda: NOW,
            arm_available=arm_available,
            email_available=email_available,
        )
    )
    return TestClient(application)


def _config(**changes: object) -> dict[str, object]:
    """Return the smallest valid public alert configuration."""
    result: dict[str, object] = {
        "symbol": "SPY",
        "currency": "USD",
        "threshold": "100",
        "direction": "above",
        "repeating": True,
    }
    result.update(changes)
    return result


def _create_alert(store: MonitoringStore, owner: int = 1) -> dict[str, object]:
    """Create a persisted arming rule through the store for route tests."""
    return store.create_alert(owner, str(uuid4()), _config(), NOW)


def _insert_notification(
    store: MonitoringStore,
    owner: int,
    *,
    provider: str = "fixture-provider",
    extra_payload: dict[str, object] | None = None,
) -> str:
    """Insert one test notification, including arbitrary hostile surplus data."""
    notification_id = str(uuid4())
    payload: dict[str, object] = {
        "alert_id": str(uuid4()),
        "generation": 1,
        "symbol": "SPY",
        "currency": "USD",
        "threshold": "100",
        "direction": "above",
        "price": "101",
        "provider": provider,
        "observed_at": "2026-10-14T03:59:00.000000Z",
    }
    if extra_payload:
        payload.update(extra_payload)
    with store.repository.connect() as connection:
        connection.execute(
            "INSERT INTO notifications(id,owner_user_id,dedupe_sha256,kind,payload_json,"
            "created_at) "
            "VALUES (?,?,?,'price_alert',?,?)",
            (
                notification_id,
                owner,
                uuid4().hex * 2,
                json.dumps(payload, sort_keys=True, separators=(",", ":")),
                "2026-10-14T04:00:00.000000Z",
            ),
        )
        connection.commit()
    return notification_id


def test_unauthenticated_requests_return_safe_401_envelope(monitoring_store):
    """Authentication is resolved before any read or mutation reaches the store."""
    client = _client(monitoring_store, None)

    for response in (
        client.get("/api/v1/alerts"),
        client.get("/api/v1/notifications"),
        client.get("/api/v1/notification-preferences"),
    ):
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "AUTHENTICATION_REQUIRED"
        assert response.headers["content-type"].startswith("application/json")

    for invalid_owner in (True, 1.0, "1"):
        application = FastAPI()
        application.include_router(
            create_monitoring_router(
                monitoring_store,
                lambda _request, value=invalid_owner: value,  # type: ignore[arg-type]
                lambda: NOW,
            )
        )
        assert TestClient(application).get("/api/v1/alerts").status_code == 401


def test_alert_reads_are_owner_scoped_and_arming_is_not_reported_as_enabled(monitoring_store):
    """The response distinguishes a configured rule from an accepted arm baseline."""
    alert = _create_alert(monitoring_store)
    owner_one = _client(monitoring_store, 1)
    owner_two = _client(monitoring_store, 2)

    listed = owner_one.get("/api/v1/alerts").json()
    assert len(listed["items"]) == 1
    view = listed["items"][0]
    assert view["state"] == "arming"
    assert view["configured_enabled"] is True
    assert view["enabled"] is False
    assert view["baseline_ready"] is False
    assert "owner_user_id" not in view
    assert owner_two.get("/api/v1/alerts").json()["items"] == []
    hidden = owner_two.get(f"/api/v1/alerts/{alert['id']}")
    assert hidden.status_code == 404
    assert hidden.json()["error"]["code"] == "ALERT_NOT_FOUND"


def test_create_and_resume_fail_closed_before_mutation_or_client_snapshot_acceptance(
    monitoring_store,
):
    """Unsupported arming writes neither create jobs nor accept caller-supplied snapshots."""
    client = _client(monitoring_store)
    idempotency_key = str(uuid4())
    body = _config()
    for _ in range(2):
        response = client.post(
            "/api/v1/alerts",
            headers={"Idempotency-Key": idempotency_key},
            json=body,
        )
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "MONITORING_ARM_UNAVAILABLE"
    with monitoring_store.repository.connect() as connection:
        assert connection.execute("SELECT count(*) FROM price_alerts").fetchone()[0] == 0
        assert connection.execute("SELECT count(*) FROM monitoring_jobs").fetchone()[0] == 0

    forged = client.post(
        "/api/v1/alerts",
        headers={"Idempotency-Key": str(uuid4())},
        json={**body, "initial_observation": {"price": "100", "provider": "client"}},
    )
    assert forged.status_code == 422
    assert (
        client.post(
            "/api/v1/alerts",
            headers={"Idempotency-Key": "not-a-canonical-uuid-000000000000000000"},
            json=body,
        ).status_code
        == 422
    )

    alert = _create_alert(monitoring_store)
    pause = client.post(f"/api/v1/alerts/{alert['id']}/pause", json={"expected_revision": 1})
    assert pause.status_code == 200
    resumed = client.post(f"/api/v1/alerts/{alert['id']}/resume", json={"expected_revision": 2})
    assert resumed.status_code == 503
    assert monitoring_store.get_alert(1, str(alert["id"]))["check_state"] == "paused"


def test_available_scheduler_accepts_only_queued_arming_with_idempotency_and_cas(monitoring_store):
    """Creating and resuming schedule the initial observation without treating it as a crossing."""
    application = FastAPI()
    application.include_router(
        create_monitoring_router(
            monitoring_store, lambda _request: 1, lambda: NOW, arm_available=lambda: True
        )
    )
    client = TestClient(application)
    headers = {"Idempotency-Key": str(uuid4())}
    created = client.post("/api/v1/alerts", headers=headers, json=_config())
    assert created.status_code == 201
    alert = created.json()
    assert alert["state"] == "arming" and alert["enabled"] is False
    assert alert["baseline_ready"] is False and alert["last_observation"] is None
    replay = client.post("/api/v1/alerts", headers=headers, json=_config())
    assert replay.status_code == 200 and replay.json()["id"] == alert["id"]
    assert (
        client.post("/api/v1/alerts", headers=headers, json=_config(threshold="99")).status_code
        == 409
    )
    identifier = alert["id"]
    assert (
        client.post(f"/api/v1/alerts/{identifier}/pause", json={"expected_revision": 1}).status_code
        == 200
    )
    resumed = client.post(f"/api/v1/alerts/{identifier}/resume", json={"expected_revision": 2})
    assert resumed.status_code == 200 and resumed.json()["state"] == "arming"
    assert resumed.json()["arm_generation"] > alert["arm_generation"]
    assert (
        client.post(
            f"/api/v1/alerts/{identifier}/resume", json={"expected_revision": 2}
        ).status_code
        == 409
    )
    edit = client.patch(
        f"/api/v1/alerts/{identifier}", json={**_config(threshold="105"), "expected_revision": 3}
    )
    assert edit.status_code == 200 and edit.json()["state"] == "arming"
    assert edit.json()["baseline_ready"] is False
    with monitoring_store.repository.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM notifications").fetchone()[0] == 0
        jobs = connection.execute("SELECT request_kind FROM monitoring_jobs").fetchall()
    assert len(jobs) == 1 and jobs[0]["request_kind"] == "arm_snapshot"


def test_existing_alert_replay_survives_scheduler_unavailability_without_new_writes(
    monitoring_store,
):
    """Unavailable arming blocks new alerts but preserves owner-bound durable replays."""
    available = [True]

    def arm_available() -> bool:
        return available[0]

    owner_one = _client(monitoring_store, 1, arm_available)
    owner_two = _client(monitoring_store, 2, arm_available)
    key = str(uuid4())
    headers = {"Idempotency-Key": key}

    created_one = owner_one.post("/api/v1/alerts", headers=headers, json=_config())
    created_two = owner_two.post("/api/v1/alerts", headers=headers, json=_config())
    assert created_one.status_code == 201 and created_two.status_code == 201
    assert created_one.json()["id"] != created_two.json()["id"]

    def mutation_counts() -> tuple[int, int, int]:
        with monitoring_store.repository.connect() as connection:
            return (
                connection.execute("SELECT COUNT(*) FROM price_alerts").fetchone()[0],
                connection.execute("SELECT COUNT(*) FROM price_alert_revisions").fetchone()[0],
                connection.execute("SELECT COUNT(*) FROM monitoring_jobs").fetchone()[0],
            )

    before = mutation_counts()
    available[0] = False
    replay_one = owner_one.post("/api/v1/alerts", headers=headers, json=_config())
    replay_two = owner_two.post("/api/v1/alerts", headers=headers, json=_config())
    assert replay_one.status_code == 200
    assert replay_two.status_code == 200
    assert replay_one.json()["id"] == created_one.json()["id"]
    assert replay_two.json()["id"] == created_two.json()["id"]

    conflict = owner_one.post("/api/v1/alerts", headers=headers, json=_config(threshold="99"))
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"
    unavailable = owner_one.post(
        "/api/v1/alerts", headers={"Idempotency-Key": str(uuid4())}, json=_config()
    )
    assert unavailable.status_code == 503
    assert unavailable.json()["error"]["code"] == "MONITORING_ARM_UNAVAILABLE"
    assert mutation_counts() == before


def test_active_edit_delete_and_resume_are_unavailable_but_paused_edit_is_cas_bound(
    monitoring_store,
):
    """Paused edits remain safe, while every operation that would rearm fails closed."""
    client = _client(monitoring_store)
    alert = _create_alert(monitoring_store)
    alert_id = str(alert["id"])

    active_edit = client.patch(
        f"/api/v1/alerts/{alert_id}", json={**_config(threshold="105"), "expected_revision": 1}
    )
    assert active_edit.status_code == 503
    assert monitoring_store.get_alert(1, alert_id)["revision"] == 1

    paused = client.post(f"/api/v1/alerts/{alert_id}/pause", json={"expected_revision": 1})
    assert paused.status_code == 200
    stale_edit = client.patch(
        f"/api/v1/alerts/{alert_id}", json={**_config(threshold="105"), "expected_revision": 1}
    )
    assert stale_edit.status_code == 409
    saved = client.patch(
        f"/api/v1/alerts/{alert_id}", json={**_config(threshold="105"), "expected_revision": 2}
    )
    assert saved.status_code == 200
    assert saved.json()["state"] == "paused"
    assert saved.json()["config"]["threshold"] == "105"
    assert saved.json()["enabled"] is False

    removed = client.delete(f"/api/v1/alerts/{alert_id}?expected_revision=3")
    assert removed.status_code == 503
    resumed = client.post(f"/api/v1/alerts/{alert_id}/resume", json={"expected_revision": 3})
    assert resumed.status_code == 503
    current = monitoring_store.get_alert(1, alert_id)
    assert current["revision"] == 3 and current["check_state"] == "paused"


def test_notification_pages_are_owner_scoped_json_and_strip_unknown_payload_fields(
    monitoring_store,
):
    """Hostile stored text stays a JSON string and surplus private fields are not projected."""
    private_marker = "opaque-owner-address-marker"
    hostile_text = "<script>alert(1)</script>"
    first_id = _insert_notification(
        monitoring_store,
        1,
        provider=hostile_text,
        extra_payload={"recipient_marker": private_marker, "transport_attempt": "internal-only"},
    )
    _insert_notification(monitoring_store, 1)
    owner_one = _client(monitoring_store, 1)
    owner_two = _client(monitoring_store, 2)

    first = owner_one.get("/api/v1/notifications?limit=1")
    assert first.status_code == 200
    assert first.headers["content-type"].startswith("application/json")
    assert private_marker not in first.text
    assert "recipient_marker" not in first.text and "transport_attempt" not in first.text
    assert first.json()["next_cursor"]
    second = owner_one.get(
        "/api/v1/notifications",
        params={"limit": 1, "cursor": first.json()["next_cursor"]},
    )
    assert second.status_code == 200 and len(second.json()["items"]) == 1
    all_items = owner_one.get("/api/v1/notifications?limit=10").json()["items"]
    hostile_item = next(item for item in all_items if item["id"] == first_id)
    assert hostile_item["payload"]["provider"] == hostile_text
    assert owner_two.get("/api/v1/notifications").json()["items"] == []

    changed = owner_one.put(
        f"/api/v1/notifications/{first_id}/read",
        json={"expected_revision": 1, "is_read": True},
    )
    assert changed.status_code == 200
    assert changed.json()["is_read"] is True and changed.json()["revision"] == 2
    stale = owner_one.put(
        f"/api/v1/notifications/{first_id}/read",
        json={"expected_revision": 1, "is_read": False},
    )
    assert stale.status_code == 409
    foreign = owner_two.put(
        f"/api/v1/notifications/{first_id}/read",
        json={"expected_revision": 1, "is_read": True},
    )
    assert foreign.status_code == 404


def test_preferences_are_safe_projection_and_updates_preserve_verified_address_server_side(
    monitoring_store,
):
    """Preference CAS never returns the address ID or raw stored address field."""
    client = _client(monitoring_store, email_available=lambda: True)
    address_id = str(uuid4())
    private_marker = "opaque-owner-address-marker"
    with monitoring_store.repository.connect() as connection:
        connection.execute(
            "INSERT INTO notification_addresses(id,owner_user_id,address,verified_at,created_at) "
            "VALUES (?,?,?,?,?)",
            (address_id, 1, private_marker, NOW.isoformat(), NOW.isoformat()),
        )
        connection.commit()
    monitoring_store.set_notification_preferences(
        1,
        0,
        alert_email=False,
        digest_email=False,
        address_id=address_id,
        now=NOW,
    )

    read = client.get("/api/v1/notification-preferences")
    assert read.status_code == 200
    assert read.json()["address_configured"] is True
    assert "address_id" not in read.json()
    assert address_id not in read.text and private_marker not in read.text

    saved = client.put(
        "/api/v1/notification-preferences",
        json={"expected_revision": 1, "alert_email": True, "digest_email": False},
    )
    assert saved.status_code == 200
    assert saved.json()["revision"] == 2 and saved.json()["alert_email"] is True
    assert "address_id" not in saved.json() and private_marker not in saved.text
    stale = client.put(
        "/api/v1/notification-preferences",
        json={"expected_revision": 1, "alert_email": False, "digest_email": False},
    )
    assert stale.status_code == 409
    non_boolean = client.put(
        "/api/v1/notification-preferences",
        json={"expected_revision": 2, "alert_email": 1, "digest_email": False},
    )
    assert non_boolean.status_code == 422
    forged_owner = client.put(
        "/api/v1/notification-preferences",
        json={
            "expected_revision": 2,
            "alert_email": False,
            "digest_email": False,
            "owner_user_id": 2,
        },
    )
    assert forged_owner.status_code == 422
    forged_address = client.put(
        "/api/v1/notification-preferences",
        json={
            "expected_revision": 2,
            "alert_email": False,
            "digest_email": False,
            "address_id": str(uuid4()),
        },
    )
    assert forged_address.status_code == 422

    with monitoring_store.repository.connect() as connection:
        connection.execute(
            "UPDATE notification_addresses SET verified_at=NULL WHERE id=? AND owner_user_id=1",
            (address_id,),
        )
        connection.commit()
    opted_out = client.put(
        "/api/v1/notification-preferences",
        json={"expected_revision": 2, "alert_email": False, "digest_email": False},
    )
    assert opted_out.status_code == 200
    assert opted_out.json()["alert_email"] is False
    assert opted_out.json()["address_configured"] is False


def test_email_preferences_fail_closed_for_optin_but_allow_optout_when_unavailable(
    monitoring_store,
):
    """An unavailable email capability blocks new opt-in but never blocks opt-out."""
    address_id = str(uuid4())
    with monitoring_store.repository.connect() as connection:
        connection.execute(
            "INSERT INTO notification_addresses(id,owner_user_id,address,verified_at,created_at) "
            "VALUES (?,?,?,?,?)",
            (address_id, 1, "opaque-owner-address-marker", NOW.isoformat(), NOW.isoformat()),
        )
        connection.commit()
    monitoring_store.set_notification_preferences(
        1,
        0,
        alert_email=False,
        digest_email=False,
        address_id=address_id,
        now=NOW,
    )

    unavailable = _client(monitoring_store)
    blocked_optin = unavailable.put(
        "/api/v1/notification-preferences",
        json={"expected_revision": 1, "alert_email": True, "digest_email": False},
    )
    assert blocked_optin.status_code == 503
    assert blocked_optin.json()["error"]["code"] == "ALERT_EMAIL_UNAVAILABLE"
    unchanged = unavailable.get("/api/v1/notification-preferences")
    assert unchanged.status_code == 200
    assert unchanged.json()["revision"] == 1
    assert unchanged.json()["alert_email"] is False
    assert unchanged.json()["address_configured"] is True
    assert address_id not in unchanged.text and "opaque-owner-address-marker" not in unchanged.text

    available = _client(monitoring_store, email_available=lambda: True)
    opted_in = available.put(
        "/api/v1/notification-preferences",
        json={"expected_revision": 1, "alert_email": True, "digest_email": False},
    )
    assert opted_in.status_code == 200
    assert opted_in.json()["revision"] == 2 and opted_in.json()["alert_email"] is True

    opted_out = unavailable.put(
        "/api/v1/notification-preferences",
        json={"expected_revision": 2, "alert_email": False, "digest_email": False},
    )
    assert opted_out.status_code == 200
    assert opted_out.json()["revision"] == 3 and opted_out.json()["alert_email"] is False


def test_page_and_request_bounds_are_enforced_before_store_calls(monitoring_store):
    """Oversized page sizes, cursors and alert fields fail at the HTTP boundary."""
    client = _client(monitoring_store)

    assert client.get("/api/v1/alerts?limit=101").status_code == 422
    assert client.get("/api/v1/notifications?limit=1000").status_code == 422
    assert client.get("/api/v1/alerts", params={"cursor": "x" * 257}).status_code == 422
    assert client.get("/api/v1/alerts?cursor=not-base64").status_code == 422
    invalid_alert = client.post(
        "/api/v1/alerts",
        headers={"Idempotency-Key": str(uuid4())},
        json=_config(symbol="S" * 81),
    )
    assert invalid_alert.status_code == 422
    with monitoring_store.repository.connect() as connection:
        assert connection.execute("SELECT count(*) FROM price_alerts").fetchone()[0] == 0
