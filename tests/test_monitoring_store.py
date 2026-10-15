"""Persistence contract tests for the unregistered monitoring migration draft."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest

import stock_probs.repository as repository_module
from stock_probs.monitoring_domain import PriceObservation
from stock_probs.monitoring_store import (
    MAX_OUTBOX_PAYLOAD_BYTES,
    MonitoringArmingUnavailableError,
    MonitoringConflictError,
    MonitoringStore,
    MonitoringStoreError,
)
from stock_probs.repository import Repository

ROOT = Path(__file__).parents[1]
DRAFT_MIGRATION = ROOT / "src/stock_probs/migrations/016_monitoring_and_report_cards.sql"
FRIDAY_ARMED = datetime(2026, 10, 9, 20, 30, tzinfo=UTC)
FRIDAY_REQUEST = datetime(2026, 10, 9, 20, 30, 1, tzinfo=UTC)
FRIDAY_RECEIVED = datetime(2026, 10, 9, 20, 32, tzinfo=UTC)
FRIDAY_PROVIDER = datetime(2026, 10, 9, 20, 0, tzinfo=UTC)
MONDAY = datetime(2026, 10, 12, 13, 30, tzinfo=UTC)


@pytest.fixture
def monitoring_store(tmp_path, monkeypatch):
    """Use registered schema 016 when available, otherwise apply its draft after v15."""
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
        github_user_id=91,
        login="monitoring-member",
        display_name="Monitoring member",
        password_hash=None,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    return MonitoringStore(repository)


def _config(**changes):
    value = {
        "symbol": "SPY",
        "currency": "USD",
        "threshold": "100",
        "direction": "above",
        "repeating": True,
    }
    value.update(changes)
    return value


def _new_alert(store, now=MONDAY, **changes):
    return store.create_alert(1, str(uuid4()), _config(**changes), now)


def _enable_jobs(store):
    with store.repository.connect() as connection:
        connection.execute(
            "UPDATE monitoring_control SET enabled=1,revision=revision+1,updated_at=? WHERE id=1",
            (MONDAY.isoformat(),),
        )
        connection.commit()


def _claim_price(store, alert_id, now, *, lease_seconds=120):
    claims = store.claim_due_jobs("worker-a", now, limit=20, lease_seconds=lease_seconds)
    matches = [
        claim for claim in claims if claim["kind"] == "price" and claim["resource_id"] == alert_id
    ]
    assert len(matches) == 1
    return matches[0]


def _price_step(store, alert_id, now, value, *, provider_at=None, owner=1, symbol="SPY"):
    claim = _claim_price(store, alert_id, now)
    received = now + timedelta(seconds=1)
    observation = PriceObservation(
        symbol,
        value,
        "USD",
        provider_at or now,
        "fixture provider",
    )
    result = store.record_price_observation(
        owner,
        alert_id,
        claim,
        observation,
        received,
        received,
        next_due_at=received + timedelta(minutes=1),
    )
    return result, claim, observation, received


def test_create_is_owner_bound_idempotent_and_editor_cas_is_separate(monitoring_store):
    store = monitoring_store
    key = str(uuid4())
    created = store.create_alert(1, key, _config(), MONDAY)
    replay = store.create_alert(1, key, _config(), MONDAY + timedelta(seconds=1))

    assert replay["id"] == created["id"] and replay["replayed"]
    assert created["arm_generation"] == 1
    assert created["revision"] == 1 and created["monitor_revision"] == 1
    assert store.list_alerts(2)["items"] == []
    with pytest.raises(MonitoringStoreError, match="unavailable"):
        store.get_alert(2, created["id"])
    with pytest.raises(MonitoringConflictError, match="different alert"):
        store.create_alert(1, key, _config(threshold="101"), MONDAY)

    edited = store.edit_alert(
        1,
        created["id"],
        1,
        _config(threshold="102"),
        MONDAY + timedelta(minutes=1),
    )
    assert edited["revision"] == 2
    assert edited["monitor_revision"] == 2
    assert edited["arm_generation"] == 2
    assert edited["arm_snapshot_generation"] is None
    with pytest.raises(MonitoringConflictError, match="changed"):
        store.edit_alert(1, created["id"], 1, _config(threshold="103"), MONDAY)
    with store.repository.connect() as connection:
        rows = connection.execute(
            "SELECT revision,payload_json,enabled FROM price_alert_revisions "
            "WHERE alert_id=? ORDER BY revision",
            (created["id"],),
        ).fetchall()
    assert [row["revision"] for row in rows] == [1, 2]


def test_create_replay_precedes_new_creation_gate_and_gate_is_strict_boolean(monitoring_store):
    store = monitoring_store
    store.repository.create_user(
        github_user_id=92,
        login="second-monitoring-member",
        display_name="Second monitoring member",
        password_hash=None,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    key = str(uuid4())
    first = store.create_alert(1, key, _config(), MONDAY)
    second_owner = store.create_alert(2, key, _config(), MONDAY)
    assert first["id"] != second_owner["id"]

    def mutation_counts() -> tuple[int, int, int]:
        with store.repository.connect() as connection:
            return (
                connection.execute("SELECT COUNT(*) FROM price_alerts").fetchone()[0],
                connection.execute("SELECT COUNT(*) FROM price_alert_revisions").fetchone()[0],
                connection.execute("SELECT COUNT(*) FROM monitoring_jobs").fetchone()[0],
            )

    before = mutation_counts()
    first_replay = store.create_alert(
        1, key, _config(), MONDAY + timedelta(seconds=1), allow_new_creation=False
    )
    second_replay = store.create_alert(
        2, key, _config(), MONDAY + timedelta(seconds=1), allow_new_creation=False
    )
    assert first_replay["replayed"] and first_replay["id"] == first["id"]
    assert second_replay["replayed"] and second_replay["id"] == second_owner["id"]
    assert store.list_alerts(1)["items"][0]["id"] == first["id"]
    assert store.list_alerts(2)["items"][0]["id"] == second_owner["id"]

    with pytest.raises(MonitoringConflictError, match="different alert"):
        store.create_alert(1, key, _config(threshold="101"), MONDAY, allow_new_creation=False)
    with pytest.raises(MonitoringArmingUnavailableError, match="unavailable"):
        store.create_alert(1, str(uuid4()), _config(), MONDAY, allow_new_creation=False)
    with pytest.raises(MonitoringArmingUnavailableError, match="unavailable"):
        store.create_alert(2, str(uuid4()), _config(), MONDAY, allow_new_creation=False)

    for invalid_flag in (None, 0, 1, "false"):
        with pytest.raises(MonitoringStoreError, match="boolean"):
            store.create_alert(
                1,
                str(uuid4()),
                _config(),
                MONDAY,
                allow_new_creation=invalid_flag,
            )
    assert mutation_counts() == before


def test_friday_provider_snapshot_is_durable_and_mondays_first_live_crossing_triggers(
    monitoring_store,
):
    store = monitoring_store
    alert = _new_alert(store, FRIDAY_ARMED)
    _enable_jobs(store)
    claim = _claim_price(store, alert["id"], FRIDAY_REQUEST, lease_seconds=300)
    assert claim["request_kind"] == "arm_snapshot"
    assert claim["arm_generation"] == alert["arm_generation"]
    snapshot = PriceObservation("SPY", "99", "USD", FRIDAY_PROVIDER, "fixture provider")
    baseline_result = store.record_price_observation(
        1,
        alert["id"],
        claim,
        snapshot,
        FRIDAY_RECEIVED,
        FRIDAY_RECEIVED,
        next_due_at=MONDAY,
    )

    assert baseline_result["disposition"] == "initial" and baseline_result["stale"]
    baseline = store.get_alert(1, alert["id"])
    assert baseline["revision"] == 1
    assert baseline["monitor_revision"] == 2
    assert baseline["last_observed_at"] == "2026-10-09T20:00:00.000000Z"
    assert baseline["arm_snapshot_generation"] == alert["arm_generation"]
    assert baseline["arm_snapshot_requested_at"] == "2026-10-09T20:30:01.000000Z"
    assert baseline["arm_snapshot_received_at"] == "2026-10-09T20:32:00.000000Z"

    crossing, claim, monday_observation, received = _price_step(store, alert["id"], MONDAY, "101")
    assert crossing["disposition"] == "triggered"
    assert store.get_alert(1, alert["id"])["revision"] == 1
    assert store.get_alert(1, alert["id"])["monitor_revision"] == 3
    replay = store.record_price_observation(
        1,
        alert["id"],
        claim,
        monday_observation,
        received,
        received,
        next_due_at=received + timedelta(minutes=1),
    )
    assert replay["replayed"] and replay["disposition"] == "triggered"
    assert store.list_notifications(1)["items"][0]["kind"] == "price_alert"
    with store.repository.connect() as connection:
        assert (
            connection.execute(
                "SELECT count(*) FROM price_alert_observations WHERE alert_id=?", (alert["id"],)
            ).fetchone()[0]
            == 2
        )
        assert (
            connection.execute(
                "SELECT count(*) FROM notifications WHERE owner_user_id=1"
            ).fetchone()[0]
            == 1
        )


def test_target_side_snapshot_needs_opposite_then_target_before_notification(monitoring_store):
    store = monitoring_store
    alert = _new_alert(store)
    _enable_jobs(store)
    at = MONDAY
    result, _, _, received = _price_step(store, alert["id"], at, "101")
    assert result["disposition"] == "initial"
    assert store.list_notifications(1)["items"] == []

    at = received + timedelta(minutes=1)
    first_live, _, _, received = _price_step(store, alert["id"], at, "102")
    assert first_live["disposition"] == "observed"
    assert store.list_notifications(1)["items"] == []

    at = received + timedelta(minutes=1)
    opposite, _, _, received = _price_step(store, alert["id"], at, "99")
    assert opposite["disposition"] == "observed"
    assert store.get_alert(1, alert["id"])["ready"]
    assert store.list_notifications(1)["items"] == []

    at = received + timedelta(minutes=1)
    crossed, _, _, _ = _price_step(store, alert["id"], at, "101")
    assert crossed["disposition"] == "triggered"
    items = store.list_notifications(1)["items"]
    assert len(items) == 1 and items[0]["kind"] == "price_alert"


def test_pause_resume_invalidates_old_generation_and_outstanding_lease(monitoring_store):
    store = monitoring_store
    alert = _new_alert(store)
    _enable_jobs(store)
    old_claim = _claim_price(store, alert["id"], MONDAY)
    paused = store.pause_alert(1, alert["id"], 1, MONDAY + timedelta(seconds=5))
    resumed = store.resume_alert(1, alert["id"], paused["revision"], MONDAY + timedelta(seconds=10))
    assert not paused["enabled"] and paused["arm_generation"] > old_claim["arm_generation"]
    assert resumed["enabled"] and resumed["arm_generation"] > paused["arm_generation"]
    assert resumed["arm_snapshot_generation"] is None and not resumed["ready"]

    with pytest.raises(MonitoringConflictError, match="stale generation or server lease"):
        store.record_price_observation(
            1,
            alert["id"],
            old_claim,
            PriceObservation("SPY", "101", "USD", MONDAY, "fixture provider"),
            MONDAY + timedelta(seconds=11),
            MONDAY + timedelta(seconds=11),
            next_due_at=MONDAY + timedelta(minutes=1),
        )
    new_claim = _claim_price(store, alert["id"], MONDAY + timedelta(seconds=12))
    assert new_claim["arm_generation"] == resumed["arm_generation"]
    assert new_claim["request_kind"] == "arm_snapshot"


def test_duplicate_workers_reclaim_only_after_expiry_and_checkpoint_is_cas(monitoring_store):
    store = monitoring_store
    due = MONDAY + timedelta(hours=1)
    job_id = store.schedule_job(
        1, "outcome", "outcome:42", due, checkpoint={"cursor": 0}, now=MONDAY
    )
    _enable_jobs(store)
    first = store.claim_due_jobs("worker-one", due, limit=1, lease_seconds=5)[0]
    assert first["job_id"] == job_id
    assert store.claim_due_jobs("worker-two", due + timedelta(seconds=4), limit=1) == []
    reclaimed = store.claim_due_jobs("worker-two", due + timedelta(seconds=5), limit=1)[0]
    assert reclaimed["job_id"] == job_id
    assert reclaimed["lease_token"] != first["lease_token"]
    assert reclaimed["job_revision"] > first["job_revision"]
    with pytest.raises(MonitoringConflictError, match="stale or no longer owned"):
        store.checkpoint_job(
            1, first, {"cursor": 1}, due + timedelta(seconds=6), due_at=due + timedelta(minutes=1)
        )
    saved = store.checkpoint_job(
        1,
        reclaimed,
        {"cursor": 1},
        due + timedelta(seconds=6),
        due_at=due + timedelta(minutes=1),
    )
    assert saved["checkpoint"] == {"cursor": 1}
    with store.repository.connect() as connection:
        row = connection.execute(
            "SELECT attempts,lease_token,checkpoint_json FROM monitoring_jobs WHERE id=?", (job_id,)
        ).fetchone()
    assert row["attempts"] == 2 and row["lease_token"] is None
    assert json.loads(row["checkpoint_json"]) == {"cursor": 1}


@pytest.mark.parametrize(
    "forged_owner",
    [
        pytest.param(True, id="bool"),
        pytest.param(1.0, id="float"),
        pytest.param("1", id="string"),
    ],
)
def test_checkpoint_rejects_forged_claim_owner_types_without_mutating_lease(
    monitoring_store, forged_owner
):
    store = monitoring_store
    due = MONDAY + timedelta(hours=1)
    job_id = store.schedule_job(
        1, "outcome", "owner-id-claim", due, checkpoint={"cursor": 0}, now=MONDAY
    )
    _enable_jobs(store)
    claim = store.claim_due_jobs("owner-id-check", due, limit=1, lease_seconds=60)[0]
    assert claim["job_id"] == job_id
    claim["owner_user_id"] = forged_owner

    with pytest.raises(MonitoringStoreError, match="owner is unavailable"):
        store.checkpoint_job(
            1,
            claim,
            {"cursor": 1},
            due + timedelta(seconds=1),
            due_at=due + timedelta(minutes=1),
        )

    with store.repository.connect() as connection:
        row = connection.execute(
            "SELECT revision,lease_token,active_request_id,checkpoint_json "
            "FROM monitoring_jobs WHERE id=?",
            (job_id,),
        ).fetchone()
    assert row["revision"] == claim["job_revision"]
    assert row["lease_token"] == claim["lease_token"]
    assert row["active_request_id"] == claim["request_id"]
    assert json.loads(row["checkpoint_json"])["cursor"] == 0


def test_job_claims_are_fair_between_active_owners_and_reject_revoked_owners(monitoring_store):
    store = monitoring_store
    due = MONDAY + timedelta(hours=2)
    store.schedule_job(1, "outcome", "one-a", due, now=MONDAY)
    store.schedule_job(1, "digest", "one-b", due, now=MONDAY)
    store.schedule_job(2, "outcome", "two-a", due, now=MONDAY)
    _enable_jobs(store)
    claims = store.claim_due_jobs("fair-worker", due, limit=3, lease_seconds=60)
    assert [claim["owner_user_id"] for claim in claims] == [1, 2, 1]

    with store.repository.connect() as connection:
        connection.execute("UPDATE users SET status='disabled' WHERE id=2")
        connection.commit()
    with pytest.raises(MonitoringStoreError, match="owner is unavailable"):
        store.schedule_job(2, "outcome", "blocked", due, now=due)
    assert all(
        claim["owner_user_id"] == 1 for claim in store.claim_due_jobs("fair-worker", due, limit=10)
    )


def _trigger_alert(store, now, *, symbol="SPY"):
    alert = store.create_alert(
        1,
        str(uuid4()),
        _config(symbol=symbol, repeating=False),
        now,
    )
    _enable_jobs(store)
    at = now + timedelta(seconds=1)
    baseline, _, _, received = _price_step(store, alert["id"], at, "99", symbol=symbol)
    assert baseline["disposition"] == "initial"
    at = received + timedelta(minutes=1)
    triggered, claim, observation, received = _price_step(
        store, alert["id"], at, "101", symbol=symbol
    )
    assert triggered["disposition"] == "triggered"
    return alert, claim, observation, received


def _enable_price_email(store, now):
    address_id = str(uuid4())
    with store.repository.connect() as connection:
        connection.execute(
            "INSERT INTO notification_addresses(id,owner_user_id,address,verified_at,created_at) "
            "VALUES (?,?,?,?,?)",
            (
                address_id,
                1,
                "fixture@example.invalid",
                now.isoformat(),
                now.isoformat(),
            ),
        )
        connection.commit()
    preferences = store.get_notification_preferences(1)
    return store.set_notification_preferences(
        1,
        preferences["revision"],
        alert_email=True,
        digest_email=False,
        address_id=address_id,
        now=now,
    )


def _prepare_price_outbox(store):
    _, _, _, received = _trigger_alert(store, MONDAY)
    notification = store.list_notifications(1)["items"][0]
    preferences = _enable_price_email(store, received)
    enqueued_at = received + timedelta(seconds=1)
    outbox = store.enqueue_notification_outbox(
        1,
        notification["id"],
        preferences["revision"],
        now=enqueued_at,
    )
    return notification, preferences, enqueued_at, outbox


def test_notification_outbox_enqueue_is_owner_bound_idempotent_and_persisted(monitoring_store):
    store = monitoring_store
    notification, preferences, enqueued_at, created = _prepare_price_outbox(store)
    replay = store.enqueue_notification_outbox(
        1,
        notification["id"],
        preferences["revision"],
        now=enqueued_at + timedelta(seconds=1),
    )
    restarted = MonitoringStore(store.repository)
    persisted = restarted.enqueue_notification_outbox(
        1,
        notification["id"],
        preferences["revision"],
        now=enqueued_at + timedelta(seconds=2),
    )
    assert created["id"] == replay["id"] == persisted["id"]
    assert created["state"] == "queued" and created["attempts"] == 0
    assert created["revision"] == 1 and created["attempt_revision"] == 0
    with store.repository.connect() as connection:
        row = connection.execute(
            "SELECT payload_json,notification_id,delivery_version,job_id FROM notification_outbox "
            "WHERE id=?",
            (created["id"],),
        ).fetchone()
        assert row["notification_id"] == notification["id"]
        assert row["delivery_version"] == 1
        assert row["job_id"]
        assert "fixture@example.invalid" not in row["payload_json"]
        assert (
            connection.execute(
                "SELECT count(*) FROM notification_outbox WHERE notification_id=?",
                (notification["id"],),
            ).fetchone()[0]
            == 1
        )
        assert (
            connection.execute(
                "SELECT count(*) FROM monitoring_jobs WHERE id=? AND kind='mail' AND resource_id=?",
                (row["job_id"], created["id"]),
            ).fetchone()[0]
            == 1
        )


def test_outbox_delivery_version_is_unique_and_enqueue_uses_preference_cas(monitoring_store):
    store = monitoring_store
    notification, preferences, enqueued_at, original = _prepare_price_outbox(store)
    next_version = store.enqueue_notification_outbox(
        1,
        notification["id"],
        preferences["revision"],
        delivery_version=2,
        now=enqueued_at + timedelta(seconds=1),
    )
    assert next_version["id"] != original["id"]
    assert next_version["delivery_version"] == 2
    opted_out = store.set_notification_preferences(
        1,
        preferences["revision"],
        alert_email=False,
        digest_email=False,
        address_id=preferences["address_id"],
        now=enqueued_at + timedelta(seconds=2),
    )
    with pytest.raises(MonitoringConflictError, match="preferences changed"):
        store.enqueue_notification_outbox(
            1,
            notification["id"],
            preferences["revision"],
            delivery_version=3,
            now=enqueued_at + timedelta(seconds=3),
        )
    with pytest.raises(MonitoringStoreError, match="not enabled"):
        store.enqueue_notification_outbox(
            1,
            notification["id"],
            opted_out["revision"],
            delivery_version=3,
            now=enqueued_at + timedelta(seconds=3),
        )


@pytest.mark.parametrize("owner", [True, 1.0, "1"])
def test_notification_outbox_rejects_noninteger_owner(monitoring_store, owner):
    store = monitoring_store
    notification, preferences, enqueued_at, _ = _prepare_price_outbox(store)
    with pytest.raises(MonitoringStoreError):
        store.enqueue_notification_outbox(
            owner,
            notification["id"],
            preferences["revision"],
            delivery_version=2,
            now=enqueued_at + timedelta(seconds=1),
        )


@pytest.mark.parametrize("version", [True, 1.0, "1", 0, -1])
def test_notification_outbox_rejects_noninteger_or_nonpositive_version(monitoring_store, version):
    store = monitoring_store
    notification, preferences, enqueued_at, _ = _prepare_price_outbox(store)
    with pytest.raises(MonitoringStoreError):
        store.enqueue_notification_outbox(
            1,
            notification["id"],
            preferences["revision"],
            delivery_version=version,
            now=enqueued_at + timedelta(seconds=1),
        )


def test_outbox_claims_reclaim_only_pre_submission_expiry_and_bound_safe_retries(monitoring_store):
    store = monitoring_store
    _, _, enqueued_at, created = _prepare_price_outbox(store)
    first = store.claim_due_notification_outbox(
        "mail-worker-a", enqueued_at, limit=1, lease_seconds=5
    )[0]
    first_expiry = datetime.fromisoformat(first["lease_until"].replace("Z", "+00:00"))
    second = store.claim_due_notification_outbox(
        "mail-worker-b", first_expiry, limit=1, lease_seconds=5
    )[0]
    assert second["outbox_id"] == created["id"]
    assert second["attempt_id"] != first["attempt_id"]
    assert second["attempt_revision"] == 2
    with pytest.raises(MonitoringConflictError, match="stale|expired"):
        store.mark_notification_outbox_submission_started(1, first, first_expiry)

    retry_at = first_expiry + timedelta(seconds=1)
    safely_requeued = store.record_notification_outbox_pre_submission_failure(
        1,
        second,
        "smtp_not_started",
        retry_at,
        retryable=True,
        retry_after_seconds=10,
    )
    assert safely_requeued["state"] == "queued"
    assert safely_requeued["attempts"] == 2
    due_again = retry_at + timedelta(seconds=10)
    third = store.claim_due_notification_outbox(
        "mail-worker-c", due_again, limit=1, lease_seconds=5
    )[0]
    exhausted = store.record_notification_outbox_pre_submission_failure(
        1,
        third,
        "smtp_not_started",
        due_again + timedelta(seconds=1),
        retryable=True,
    )
    assert exhausted["state"] == "failed"
    assert exhausted["attempts"] == 3


@pytest.mark.parametrize(
    "field,value",
    [
        ("recipient", "attacker@example.invalid"),
        ("outbox_payload", {"redirected": True}),
    ],
)
def test_outbox_checkpoint_rejects_claim_payload_or_recipient_tampering(
    monitoring_store, field, value
):
    store = monitoring_store
    _, _, enqueued_at, created = _prepare_price_outbox(store)
    claim = store.claim_due_notification_outbox(
        "mail-worker", enqueued_at, limit=1, lease_seconds=30
    )[0]
    forged = dict(claim)
    forged[field] = value
    with pytest.raises(MonitoringConflictError, match="stale|owned"):
        store.mark_notification_outbox_submission_started(
            1, forged, enqueued_at + timedelta(seconds=1)
        )
    with store.repository.connect() as connection:
        row = connection.execute(
            "SELECT state,revision FROM notification_outbox WHERE id=?", (created["id"],)
        ).fetchone()
        assert tuple(row) == ("claimed", 2)


def test_outbox_submission_checkpoint_crash_recovers_uncertain_and_denies_resend(monitoring_store):
    store = monitoring_store
    _, _, enqueued_at, created = _prepare_price_outbox(store)
    claim = store.claim_due_notification_outbox(
        "mail-worker", enqueued_at, limit=1, lease_seconds=5
    )[0]
    checkpoint_at = enqueued_at + timedelta(seconds=1)
    submitting = store.mark_notification_outbox_submission_started(1, claim, checkpoint_at)
    assert submitting["outbox_state"] == "submitting"
    expiry = datetime.fromisoformat(claim["lease_until"].replace("Z", "+00:00"))
    assert (
        store.claim_due_notification_outbox("mail-worker-restart", expiry, limit=1, lease_seconds=5)
        == []
    )
    with store.repository.connect() as connection:
        row = connection.execute(
            "SELECT state,attempts,revision,failure_code,lease_token "
            "FROM notification_outbox WHERE id=?",
            (created["id"],),
        ).fetchone()
        assert tuple(row) == ("uncertain", 1, 4, "submission_lease_expired", None)
        assert [
            tuple(row)
            for row in connection.execute(
                "SELECT event_kind FROM notification_outbox_attempts "
                "WHERE outbox_id=? ORDER BY revision",
                (created["id"],),
            ).fetchall()
        ] == [("claimed",), ("submission_started",), ("uncertain",)]
        with pytest.raises(sqlite3.IntegrityError, match="transition"):
            connection.execute(
                "UPDATE notification_outbox SET state='queued',failure_code=NULL,"
                "revision=revision+1,"
                "transitioned_at=? WHERE id=?",
                ((expiry + timedelta(seconds=1)).isoformat(), created["id"]),
            )
        connection.rollback()
    assert (
        store.claim_due_notification_outbox(
            "mail-worker-later", expiry + timedelta(hours=1), limit=1, lease_seconds=5
        )
        == []
    )


@pytest.mark.parametrize(
    "mutation", ["opt_out", "address_revoked", "address_changed", "owner_disabled"]
)
def test_outbox_submission_checkpoint_rechecks_owner_optin_and_verified_address(
    monitoring_store, mutation
):
    store = monitoring_store
    _, preferences, enqueued_at, created = _prepare_price_outbox(store)
    claim = store.claim_due_notification_outbox(
        "mail-worker", enqueued_at, limit=1, lease_seconds=30
    )[0]
    changed_at = enqueued_at + timedelta(seconds=1)
    if mutation == "opt_out":
        store.set_notification_preferences(
            1,
            preferences["revision"],
            alert_email=False,
            digest_email=False,
            address_id=preferences["address_id"],
            now=changed_at,
        )
    elif mutation == "address_revoked":
        with store.repository.connect() as connection:
            connection.execute(
                "UPDATE notification_addresses SET verified_at=NULL WHERE id=? AND owner_user_id=1",
                (preferences["address_id"],),
            )
            connection.commit()
    elif mutation == "address_changed":
        new_address_id = str(uuid4())
        with store.repository.connect() as connection:
            connection.execute(
                "INSERT INTO notification_addresses(id,owner_user_id,address,verified_at,"
                "created_at) "
                "VALUES (?,?,?,?,?)",
                (
                    new_address_id,
                    1,
                    "replacement@example.invalid",
                    changed_at.isoformat(),
                    changed_at.isoformat(),
                ),
            )
            connection.commit()
        store.set_notification_preferences(
            1,
            preferences["revision"],
            alert_email=True,
            digest_email=False,
            address_id=new_address_id,
            now=changed_at,
        )
    else:
        with store.repository.connect() as connection:
            connection.execute("UPDATE users SET status='disabled' WHERE id=1")
            connection.commit()

    result = store.mark_notification_outbox_submission_started(1, claim, changed_at)
    assert result["state"] == "failed"
    assert result["failure_code"] == "delivery_not_eligible"
    assert result["id"] == created["id"]
    with pytest.raises(MonitoringConflictError):
        store.mark_notification_outbox_submission_started(
            1, claim, changed_at + timedelta(seconds=1)
        )


@pytest.mark.parametrize("outcome", ["accepted", "failed", "uncertain"])
def test_outbox_finalization_preserves_distinct_submission_outcomes(monitoring_store, outcome):
    store = monitoring_store
    _, _, enqueued_at, created = _prepare_price_outbox(store)
    claim = store.claim_due_notification_outbox(
        "mail-worker", enqueued_at, limit=1, lease_seconds=30
    )[0]
    submission = store.mark_notification_outbox_submission_started(
        1, claim, enqueued_at + timedelta(seconds=1)
    )
    result = store.finalize_notification_outbox(
        1,
        submission,
        outcome,
        enqueued_at + timedelta(seconds=2),
        failure_code=None if outcome == "accepted" else "smtp_outcome_unknown",
    )
    assert result["id"] == created["id"]
    assert result["state"] == outcome
    assert (result["submitted_at"] is not None) is (outcome == "accepted")
    assert (
        store.claim_due_notification_outbox(
            "mail-worker-again", enqueued_at + timedelta(minutes=1), limit=1, lease_seconds=30
        )
        == []
    )


def test_outbox_payload_byte_limit_is_enforced_by_sqlite(monitoring_store):
    store = monitoring_store
    notification, preferences, enqueued_at, _ = _prepare_price_outbox(store)
    outbox_id = str(uuid4())
    job_id = str(uuid4())
    with store.repository.connect() as connection:
        connection.execute(
            "INSERT INTO monitoring_jobs(id,owner_user_id,kind,resource_id,due_at) "
            "VALUES (?,1,'mail',?,?)",
            (job_id, outbox_id, enqueued_at.isoformat()),
        )
        with pytest.raises(sqlite3.IntegrityError, match="CHECK constraint failed"):
            connection.execute(
                "INSERT INTO notification_outbox(id,owner_user_id,notification_id,delivery_version,"
                "preference_revision,job_id,dedupe_sha256,address_id,kind,payload_json,state,"
                "next_attempt_at,created_at,transitioned_at) "
                "VALUES (?,1,?,2,?,?,?,?,'price_alert',?,'queued',?,?,?)",
                (
                    outbox_id,
                    notification["id"],
                    preferences["revision"],
                    job_id,
                    "b" * 64,
                    preferences["address_id"],
                    "x" * (MAX_OUTBOX_PAYLOAD_BYTES + 1),
                    enqueued_at.isoformat(),
                    enqueued_at.isoformat(),
                    enqueued_at.isoformat(),
                ),
            )
        connection.rollback()


def test_notifications_page_read_cas_persists_and_preferences_require_verified_address(
    monitoring_store,
):
    store = monitoring_store
    alerts = []
    cursor_time = MONDAY
    for symbol in ("SPY", "QQQ", "DIA"):
        alert, _, _, received = _trigger_alert(store, cursor_time, symbol=symbol)
        alerts.append(alert)
        cursor_time = received + timedelta(minutes=1)
    first = store.list_notifications(1, limit=1)
    second = store.list_notifications(1, limit=1, cursor=first["next_cursor"])
    third = store.list_notifications(1, limit=1, cursor=second["next_cursor"])
    ids = [first["items"][0]["id"], second["items"][0]["id"], third["items"][0]["id"]]
    assert len(set(ids)) == 3 and third["next_cursor"] is None
    assert store.list_notifications(2)["items"] == []

    read = store.set_notification_read(1, ids[0], 1, True, cursor_time)
    assert read["revision"] == 2 and read["is_read"]
    with pytest.raises(MonitoringConflictError, match="changed"):
        store.set_notification_read(1, ids[0], 1, False, cursor_time)
    restarted = MonitoringStore(store.repository)
    persisted = {item["id"]: item for item in restarted.list_notifications(1)["items"]}
    assert persisted[ids[0]]["is_read"] and persisted[ids[0]]["revision"] == 2

    default = store.get_notification_preferences(1)
    assert default["revision"] == 0 and not default["alert_email"] and not default["digest_email"]
    off = store.set_notification_preferences(
        1, 0, alert_email=False, digest_email=False, now=cursor_time
    )
    assert off["revision"] == 1 and not off["alert_email"] and not off["digest_email"]
    address = str(uuid4())
    with store.repository.connect() as connection:
        connection.execute(
            "INSERT INTO notification_addresses(id,owner_user_id,address,created_at) "
            "VALUES (?,?,?,?)",
            (address, 1, "fixture@example.invalid", cursor_time.isoformat()),
        )
        connection.commit()
    with pytest.raises(MonitoringStoreError, match="verified notification address"):
        store.set_notification_preferences(
            1,
            1,
            alert_email=True,
            digest_email=False,
            address_id=address,
            now=cursor_time,
        )
    with store.repository.connect() as connection:
        connection.execute(
            "UPDATE notification_addresses SET verified_at=? WHERE id=? AND owner_user_id=1",
            (cursor_time.isoformat(), address),
        )
        connection.commit()
    enabled = store.set_notification_preferences(
        1,
        1,
        alert_email=True,
        digest_email=False,
        address_id=address,
        now=cursor_time,
    )
    assert enabled["alert_email"] and not enabled["digest_email"]
    with store.repository.connect() as connection:
        assert connection.execute("SELECT count(*) FROM notification_outbox").fetchone()[0] == 0


def test_observation_notification_job_and_alert_checkpoint_rollback_as_one_transaction(
    monitoring_store,
):
    store = monitoring_store
    alert = _new_alert(store)
    _enable_jobs(store)
    first, _, _, received = _price_step(store, alert["id"], MONDAY, "99")
    assert first["disposition"] == "initial"
    due = received + timedelta(minutes=1)
    claim = _claim_price(store, alert["id"], due)
    received = due + timedelta(seconds=1)
    observation = PriceObservation("SPY", "101", "USD", due, "fixture provider")
    with store.repository.connect() as connection:
        connection.execute(
            "CREATE TRIGGER test_block_price_notification BEFORE INSERT ON notifications "
            "WHEN NEW.kind='price_alert' BEGIN SELECT RAISE(ABORT,'test notification failure'); END"
        )
        connection.commit()
    before = store.get_alert(1, alert["id"])
    with pytest.raises(sqlite3.IntegrityError, match="test notification failure"):
        store.record_price_observation(
            1,
            alert["id"],
            claim,
            observation,
            received,
            received,
            next_due_at=received + timedelta(minutes=1),
        )
    after = store.get_alert(1, alert["id"])
    assert after == before
    with store.repository.connect() as connection:
        assert (
            connection.execute(
                "SELECT count(*) FROM price_alert_observations WHERE alert_id=?", (alert["id"],)
            ).fetchone()[0]
            == 1
        )
        job = connection.execute(
            "SELECT lease_token,active_request_id FROM monitoring_jobs WHERE "
            "resource_id=? AND kind='price'",
            (alert["id"],),
        ).fetchone()
        assert job["lease_token"] == claim["lease_token"]
        assert job["active_request_id"] == claim["request_id"]
        connection.execute("DROP TRIGGER test_block_price_notification")
        connection.commit()
    accepted = store.record_price_observation(
        1,
        alert["id"],
        claim,
        observation,
        received,
        received,
        next_due_at=received + timedelta(minutes=1),
    )
    assert accepted["disposition"] == "triggered"
    assert len(store.list_notifications(1)["items"]) == 1
    with store.repository.connect() as connection:
        observation_row = connection.execute(
            "SELECT disposition,state_revision_before,state_revision_after,request_sh"
            "a256,receipt_sha256 "
            "FROM price_alert_observations WHERE alert_id=? ORDER BY accepted_at DESC LIMIT 1",
            (alert["id"],),
        ).fetchone()
        assert (
            observation_row["state_revision_after"] == observation_row["state_revision_before"] + 1
        )


def test_store_refuses_disabled_owner_and_invalid_bounded_inputs(monitoring_store):
    store = monitoring_store
    with store.repository.connect() as connection:
        connection.execute("UPDATE users SET status='disabled' WHERE id=2")
        connection.commit()
    with pytest.raises(MonitoringStoreError, match="owner is unavailable"):
        store.create_alert(2, str(uuid4()), _config(), MONDAY)
    with pytest.raises(MonitoringStoreError):
        store.create_alert(1, str(uuid4()), _config(symbol=""), MONDAY)
    with pytest.raises(MonitoringStoreError):
        store.create_alert(1, str(uuid4()), _config(direction=[]), MONDAY)
    with pytest.raises(MonitoringStoreError):
        store.list_alerts(1, limit=101)
    with pytest.raises(MonitoringStoreError):
        store.claim_due_jobs("bad worker", MONDAY)


def test_price_claim_filter_preserves_owner_fairness_without_claiming_other_work(monitoring_store):
    store = monitoring_store
    first = store.create_alert(1, str(uuid4()), _config(), MONDAY)
    second = store.create_alert(2, str(uuid4()), _config(symbol="ACDC"), MONDAY)
    outcome_id = store.schedule_job(1, "outcome", "outcome:price-filter", MONDAY, now=MONDAY)
    _enable_jobs(store)

    claims = store.claim_due_price_jobs("price-only-worker", MONDAY, limit=2)

    assert [claim["kind"] for claim in claims] == ["price", "price"]
    assert [claim["owner_user_id"] for claim in claims] == [1, 2]
    assert [claim["resource_id"] for claim in claims] == [first["id"], second["id"]]
    with store.repository.connect() as connection:
        outcome = connection.execute(
            "SELECT attempts,lease_token FROM monitoring_jobs WHERE id=?", (outcome_id,)
        ).fetchone()
    assert outcome["attempts"] == 0 and outcome["lease_token"] is None


def test_price_failure_is_cas_recorded_and_preserves_last_successful_observation(
    monitoring_store,
):
    store = monitoring_store
    alert = _new_alert(store, MONDAY)
    _enable_jobs(store)
    baseline, _, _, received = _price_step(store, alert["id"], MONDAY, "99")
    assert baseline["disposition"] == "initial"
    before = store.get_alert(1, alert["id"])
    due = received + timedelta(minutes=1)
    claim = _claim_price(store, alert["id"], due)
    failed_at = due + timedelta(seconds=2)
    next_due = failed_at + timedelta(minutes=15)

    failure = store.record_price_failure(
        1,
        alert["id"],
        claim,
        "provider_unavailable",
        failed_at,
        next_due_at=next_due,
    )
    replay = store.record_price_failure(
        1,
        alert["id"],
        claim,
        "provider_unavailable",
        failed_at,
        next_due_at=next_due,
    )
    after = store.get_alert(1, alert["id"])

    assert failure["replayed"] is False and replay["replayed"] is True
    assert after["check_state"] == "unavailable"
    assert after["last_check_at"] == "2026-10-12T13:31:03.000000Z"
    assert after["last_success_at"] == before["last_success_at"]
    assert after["last_observed_at"] == before["last_observed_at"]
    assert after["last_observation"] == before["last_observation"]
    with store.repository.connect() as connection:
        job = connection.execute(
            "SELECT due_at,expected_monitor_revision,lease_token,failure_code "
            "FROM monitoring_jobs WHERE owner_user_id=1 AND kind='price' AND resource_id=?",
            (alert["id"],),
        ).fetchone()
    assert job["due_at"] == "2026-10-12T13:46:03.000000Z"
    assert job["expected_monitor_revision"] == after["monitor_revision"]
    assert job["lease_token"] is None and job["failure_code"] == "provider_unavailable"

    replay = store.record_price_failure(
        1,
        alert["id"],
        claim,
        "provider_unavailable",
        next_due,
        next_due_at=next_due + timedelta(minutes=15),
    )
    assert replay["replayed"] is True and replay["monitor_revision"] == after["monitor_revision"]


def test_monitoring_control_cas_disable_invalidates_price_lease_and_blocks_effects(
    monitoring_store,
):
    store = monitoring_store
    alert = _new_alert(store, MONDAY)
    enabled = store.set_control(1, True, MONDAY)
    assert enabled == {
        "enabled": True,
        "revision": 2,
        "updated_at": "2026-10-12T13:30:00.000000Z",
    }
    assert store.set_control(2, True, MONDAY + timedelta(seconds=1)) == enabled
    claim = _claim_price(store, alert["id"], MONDAY)

    disabled = store.set_control(2, False, MONDAY + timedelta(seconds=1))

    assert disabled["enabled"] is False and disabled["revision"] == 3
    assert store.get_control()["enabled"] is False
    with pytest.raises(MonitoringConflictError, match="Monitoring was disabled"):
        store.record_price_failure(
            1,
            alert["id"],
            claim,
            "provider_unavailable",
            MONDAY + timedelta(seconds=2),
            next_due_at=MONDAY + timedelta(minutes=15),
        )
    with store.repository.connect() as connection:
        job = connection.execute(
            "SELECT lease_token,active_request_id FROM monitoring_jobs WHERE id=?",
            (claim["job_id"],),
        ).fetchone()
    assert job["lease_token"] is None and job["active_request_id"] is None
    assert store.claim_due_price_jobs("stopped-worker", MONDAY + timedelta(minutes=1)) == []
    with pytest.raises(MonitoringConflictError, match="control changed"):
        store.set_control(2, False, MONDAY + timedelta(seconds=2))


@pytest.mark.parametrize("enabled", [1, 0, "true", None])
def test_monitoring_control_rejects_non_boolean_switch_values(monitoring_store, enabled):
    with pytest.raises(MonitoringStoreError, match="must be a boolean"):
        monitoring_store.set_control(1, enabled, MONDAY)
