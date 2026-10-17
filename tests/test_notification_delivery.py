"""Notification outbox authorization and explicit delivery-consumer regressions."""

from __future__ import annotations

import hashlib
import json
import smtplib
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Event
from uuid import uuid4

import pytest

import stock_probs.notification_delivery as delivery_module
import stock_probs.repository as repository_module
from stock_probs.invitation_mail import InvitationMailSettings
from stock_probs.monitoring_store import (
    MonitoringConflictError,
    MonitoringStore,
)
from stock_probs.notification_delivery import (
    NotificationDeliveryConsumer,
)
from stock_probs.repository import Repository

ROOT = Path(__file__).parents[1]
DRAFT_MIGRATION = ROOT / "src/stock_probs/migrations/016_monitoring_and_report_cards.sql"
NOW = datetime(2026, 10, 14, 12, 0, tzinfo=UTC)


@pytest.fixture
def monitoring_repository(tmp_path, monkeypatch):
    """Create a disposable database with registered migrations and the exact draft 016."""

    migrations_source = ROOT / "src/stock_probs/migrations"
    registered_016 = (
        repository_module.SCHEMA_VERSION >= 16
        and repository_module.MIGRATION_SHA256.get(16)
        == hashlib.sha256(DRAFT_MIGRATION.read_bytes()).hexdigest()
    )
    if not registered_016:
        current15 = tmp_path / "registered-migrations-v15"
        current15.mkdir()
        for migration in sorted(migrations_source.glob("[0-9][0-9][0-9]_*.sql")):
            if int(migration.name[:3]) <= 15:
                (current15 / migration.name).write_bytes(migration.read_bytes())
        previous_files = repository_module.files

        def registered_migrations(package: str):
            if package == "stock_probs.migrations":
                return current15
            return previous_files(package)

        monkeypatch.setattr(repository_module, "files", registered_migrations)

    repository = Repository(tmp_path / "notification-delivery.sqlite3")
    repository.migrate()
    if not registered_016:
        with repository.connect() as connection:
            connection.executescript(DRAFT_MIGRATION.read_text(encoding="utf-8"))
            connection.commit()
    repository.create_user(
        github_user_id=901,
        login="outbox-owner",
        display_name="Outbox owner",
        password_hash=None,
        created_at=NOW,
    )
    return repository


def _queued_delivery(repository: Repository, *, admin_only: bool):
    if admin_only:
        with repository.connect() as connection:
            connection.execute("UPDATE users SET role='admin' WHERE id=1")
            connection.commit()

    store = MonitoringStore(
        repository,
        admin_only=admin_only,
        write_authorization_mode="test_no_auth",
    )
    control = store.get_control()
    enabled = store.set_control(control["revision"], True, NOW)

    address_id = str(uuid4())
    with repository.connect() as connection:
        connection.execute(
            "INSERT INTO notification_addresses(id,owner_user_id,address,verified_at,created_at) "
            "VALUES (?,?,?,?,?)",
            (address_id, 1, "fixture@example.invalid", NOW.isoformat(), NOW.isoformat()),
        )
        connection.execute(
            "INSERT INTO notifications("
            "id,owner_user_id,dedupe_sha256,kind,payload_json,created_at) "
            "VALUES (?,?,?,'price_alert',?,?)",
            (
                str(uuid4()),
                1,
                "a" * 64,
                json.dumps(
                    {
                        "symbol": "SPY",
                        "currency": "USD",
                        "threshold": "100",
                        "direction": "above",
                        "price": "101",
                        "observed_at": NOW.isoformat().replace("+00:00", "Z"),
                        "provider": "Fixture provider",
                        "sensitive_extra": "must not enter the message",
                    },
                    separators=(",", ":"),
                ),
                NOW.isoformat(),
            ),
        )
        notification_id = connection.execute(
            "SELECT id FROM notifications WHERE owner_user_id=1"
        ).fetchone()["id"]
        connection.commit()

    preferences = store.get_notification_preferences(1)
    preferences = store.set_notification_preferences(
        1,
        preferences["revision"],
        alert_email=True,
        digest_email=False,
        address_id=address_id,
        now=NOW,
    )
    outbox = store.enqueue_notification_outbox(
        1,
        notification_id,
        preferences["revision"],
        now=NOW,
    )
    return store, enabled, outbox


def _queue_second_owner(repository: Repository, store: MonitoringStore, *, role: str = "member"):
    user = repository.create_user(
        github_user_id=902,
        login="second-outbox-owner",
        display_name="Second outbox owner",
        password_hash=None,
        created_at=NOW,
        role=role,
    )
    owner = user["id"]
    address_id = str(uuid4())
    notification_id = str(uuid4())
    with repository.connect() as connection:
        connection.execute(
            "INSERT INTO notification_addresses(id,owner_user_id,address,verified_at,created_at) "
            "VALUES (?,?,?,?,?)",
            (address_id, owner, "second@example.invalid", NOW.isoformat(), NOW.isoformat()),
        )
        connection.execute(
            "INSERT INTO notifications("
            "id,owner_user_id,dedupe_sha256,kind,payload_json,created_at) "
            "VALUES (?,?,?,'price_alert',?,?)",
            (
                notification_id,
                owner,
                "b" * 64,
                json.dumps(
                    {
                        "symbol": "VFV.TO",
                        "currency": "CAD",
                        "threshold": "100",
                        "direction": "below",
                        "price": "99",
                        "observed_at": NOW.isoformat().replace("+00:00", "Z"),
                        "provider": "Fixture provider",
                    },
                    separators=(",", ":"),
                ),
                NOW.isoformat(),
            ),
        )
        connection.commit()
    preferences = store.get_notification_preferences(owner)
    preferences = store.set_notification_preferences(
        owner,
        preferences["revision"],
        alert_email=True,
        digest_email=False,
        address_id=address_id,
        now=NOW,
    )
    outbox = store.enqueue_notification_outbox(
        owner,
        notification_id,
        preferences["revision"],
        now=NOW,
    )
    return owner, outbox


def _claimed_delivery(repository: Repository, *, admin_only: bool):
    store, enabled, outbox = _queued_delivery(repository, admin_only=admin_only)
    claims = store.claim_due_notification_outbox(
        "characterization-worker", NOW, limit=1, lease_seconds=30
    )
    assert len(claims) == 1
    assert claims[0]["outbox_id"] == outbox["id"]
    return store, enabled, claims[0]


@pytest.mark.parametrize(
    ("mutation", "admin_only"),
    [("disable_control", False), ("revoke_admin", True)],
)
def test_revocation_after_claim_blocks_submission_checkpoint(
    monitoring_repository, mutation, admin_only
):
    """A stale delivery lease cannot cross the persisted submission boundary."""

    store, enabled_control, claim = _claimed_delivery(
        monitoring_repository,
        admin_only=admin_only,
    )
    checkpoint_at = NOW + timedelta(seconds=1)

    if mutation == "disable_control":
        disabled = store.set_control(enabled_control["revision"], False, checkpoint_at)
        assert disabled["enabled"] is False
        with pytest.raises(MonitoringConflictError, match="stale|expired|owned"):
            store.mark_notification_outbox_submission_started(1, claim, checkpoint_at)
    else:
        with monitoring_repository.connect() as connection:
            connection.execute("UPDATE users SET role='member' WHERE id=1")
            connection.commit()
        result = store.mark_notification_outbox_submission_started(1, claim, checkpoint_at)
        assert result["state"] == "failed"
        assert result["failure_code"] == "delivery_not_eligible"

    with monitoring_repository.connect() as connection:
        row = connection.execute(
            "SELECT state,failure_code,submission_started_at,lease_token FROM "
            "notification_outbox WHERE id=?",
            (claim["outbox_id"],),
        ).fetchone()
        events = connection.execute(
            "SELECT event_kind FROM notification_outbox_attempts WHERE outbox_id=? "
            "ORDER BY revision",
            (claim["outbox_id"],),
        ).fetchall()
        job = connection.execute(
            "SELECT lease_token FROM monitoring_jobs WHERE id=?", (claim["job_id"],)
        ).fetchone()
    assert row["state"] == "failed"
    assert row["failure_code"] == (
        "monitoring_disabled" if mutation == "disable_control" else "delivery_not_eligible"
    )
    assert row["submission_started_at"] is None
    assert row["lease_token"] is None and job["lease_token"] is None
    assert [event["event_kind"] for event in events] == ["claimed", "pre_submission_failed"]


def test_disabling_control_preserves_already_submitting_delivery(monitoring_repository):
    """A post-boundary delivery remains recoverable as uncertain and is never reset."""

    store, enabled_control, claim = _claimed_delivery(monitoring_repository, admin_only=False)
    checkpoint_at = NOW + timedelta(seconds=1)
    submitting = store.mark_notification_outbox_submission_started(1, claim, checkpoint_at)

    disabled = store.set_control(
        enabled_control["revision"],
        False,
        checkpoint_at + timedelta(seconds=1),
    )

    assert disabled["enabled"] is False
    with monitoring_repository.connect() as connection:
        row = connection.execute(
            "SELECT state,submission_started_at,lease_token FROM notification_outbox WHERE id=?",
            (claim["outbox_id"],),
        ).fetchone()
    assert submitting["outbox_state"] == "submitting"
    assert row["state"] == "submitting"
    assert row["submission_started_at"] == (
        checkpoint_at.isoformat(timespec="microseconds").replace("+00:00", "Z")
    )
    assert row["lease_token"] == claim["lease_token"]


def _mail_settings(security: str = "implicit_tls", port: int = 465) -> InvitationMailSettings:
    return InvitationMailSettings(
        host="smtp.example.invalid",
        port=port,
        username="fixture-user",
        password=f"test-{uuid4()}",
        security=security,
        from_address="alerts@example.invalid",
    )


class _FakeSession:
    def __init__(self, result=None, error: Exception | None = None):
        self.result = {} if result is None else result
        self.error = error
        self.messages = []
        self.close_calls = 0

    def send_message(self, message):
        self.messages.append(message)
        if self.error is not None:
            raise self.error
        return self.result

    def close(self):
        self.close_calls += 1


class _FakeTransport:
    def __init__(self, session: _FakeSession, before_return=None, prepare_error=None):
        self.session = session
        self.before_return = before_return
        self.prepare_error = prepare_error
        self.prepare_calls = 0
        self.timeout_seconds = None

    def prepare(self, settings, *, timeout_seconds):
        self.prepare_calls += 1
        self.timeout_seconds = timeout_seconds
        if self.before_return is not None:
            self.before_return()
        if self.prepare_error is not None:
            raise self.prepare_error
        return self.session


def _consumer(store, transport, *, clock_value=NOW + timedelta(seconds=1), origin=None):
    return NotificationDeliveryConsumer(
        store,
        settings=_mail_settings(),
        public_origin=origin or "https://ledger.example.invalid",
        transport=transport,
        clock=lambda: clock_value,
    )


@pytest.mark.parametrize("mutation", ["disable_control", "revoke_admin"])
def test_consumer_never_sends_after_control_or_admin_revocation(monitoring_repository, mutation):
    admin_only = mutation == "revoke_admin"
    store, enabled, _ = _queued_delivery(monitoring_repository, admin_only=admin_only)

    def revoke_during_preparation():
        changed_at = NOW + timedelta(seconds=1)
        if mutation == "disable_control":
            store.set_control(enabled["revision"], False, changed_at)
        else:
            with monitoring_repository.connect() as connection:
                connection.execute("UPDATE users SET role='member' WHERE id=1")
                connection.commit()

    session = _FakeSession()
    transport = _FakeTransport(session, before_return=revoke_during_preparation)
    consumer = _consumer(store, transport, clock_value=NOW + timedelta(seconds=2))
    # Construction itself must not prepare a transport or begin a delivery.
    assert transport.prepare_calls == 0 and session.messages == []

    result = consumer.run_due("delivery-worker", NOW, limit=1, lease_seconds=30)

    assert result.available and result.claimed == 1
    assert result.blocked + result.failed == 1
    assert transport.prepare_calls == 1
    assert session.messages == []
    assert session.close_calls == 1
    with monitoring_repository.connect() as connection:
        row = connection.execute(
            "SELECT state,submission_started_at,failure_code FROM notification_outbox"
        ).fetchone()
    assert row["state"] == "failed"
    assert row["submission_started_at"] is None
    assert row["failure_code"] in {"monitoring_disabled", "delivery_not_eligible"}


def test_consumer_builds_deterministic_minimal_message_and_records_acceptance(
    monitoring_repository,
):
    store, _, outbox = _queued_delivery(monitoring_repository, admin_only=False)
    session = _FakeSession()
    transport = _FakeTransport(session)
    consumer = _consumer(store, transport)

    result = consumer.run_due("delivery-worker", NOW, limit=1, lease_seconds=30)
    repeated = consumer.run_due(
        "delivery-worker-restart", NOW + timedelta(hours=1), limit=1, lease_seconds=30
    )

    assert result == delivery_module.DeliveryRunSummary(available=True, claimed=1, accepted=1)
    assert repeated.claimed == 0
    assert transport.timeout_seconds == delivery_module.SMTP_TIMEOUT_SECONDS == 10.0
    assert len(session.messages) == 1 and session.close_calls == 1
    message = session.messages[0]
    assert message["Message-ID"] == (f"<{outbox['id']}.1@notifications.signal-ledger.invalid>")
    body = message.get_body(preferencelist=("plain",)).get_content()
    assert "https://ledger.example.invalid/notifications" in body
    assert "turn off email notifications" in body
    assert "SPY" in body and "101 USD" in body and "above 100 USD" in body
    assert "Fixture provider" not in body
    assert "sensitive_extra" not in body
    assert "must not enter the message" not in body
    with monitoring_repository.connect() as connection:
        row = connection.execute(
            "SELECT state,submitted_at FROM notification_outbox WHERE id=?", (outbox["id"],)
        ).fetchone()
    assert row["state"] == "accepted" and row["submitted_at"] is not None


def test_consumer_marks_explicit_smtp_rejection_failed_without_resend(monitoring_repository):
    store, _, outbox = _queued_delivery(monitoring_repository, admin_only=False)
    session = _FakeSession(result={"recipient": (550, b"rejected")})
    consumer = _consumer(store, _FakeTransport(session))

    result = consumer.run_due("delivery-worker", NOW, limit=1, lease_seconds=30)
    repeated = consumer.run_due(
        "delivery-worker-2", NOW + timedelta(hours=1), limit=1, lease_seconds=30
    )

    assert result.failed == 1 and result.claimed == 1
    assert repeated.claimed == 0
    assert len(session.messages) == 1
    with monitoring_repository.connect() as connection:
        row = connection.execute(
            "SELECT state,failure_code FROM notification_outbox WHERE id=?", (outbox["id"],)
        ).fetchone()
    assert tuple(row) == ("failed", "smtp_rejected")


def test_consumer_marks_ambiguous_smtp_result_uncertain_and_never_resends(
    monitoring_repository,
):
    store, _, outbox = _queued_delivery(monitoring_repository, admin_only=False)
    session = _FakeSession(error=smtplib.SMTPServerDisconnected("fixture disconnect"))
    consumer = _consumer(store, _FakeTransport(session))

    result = consumer.run_due("delivery-worker", NOW, limit=1, lease_seconds=5)
    repeated = consumer.run_due(
        "delivery-worker-restart", NOW + timedelta(minutes=1), limit=1, lease_seconds=5
    )

    assert result.uncertain == 1 and result.claimed == 1
    assert repeated.claimed == 0
    assert len(session.messages) == 1
    assert "fixture disconnect" not in repr(result)
    with monitoring_repository.connect() as connection:
        row = connection.execute(
            "SELECT state,failure_code FROM notification_outbox WHERE id=?", (outbox["id"],)
        ).fetchone()
    assert tuple(row) == ("uncertain", "smtp_outcome_unknown")


def test_consumer_retries_only_bounded_failure_before_submission(monitoring_repository):
    store, _, outbox = _queued_delivery(monitoring_repository, admin_only=False)
    broken = _FakeTransport(_FakeSession(), prepare_error=OSError("fixture connect failure"))
    first = _consumer(store, broken, clock_value=NOW + timedelta(seconds=1))

    failed_before_data = first.run_due("delivery-worker", NOW, limit=1, lease_seconds=30)

    assert failed_before_data.retry_scheduled == 1
    assert broken.prepare_calls == 1
    assert broken.session.messages == []
    with monitoring_repository.connect() as connection:
        queued = connection.execute(
            "SELECT state,attempts,next_attempt_at FROM notification_outbox WHERE id=?",
            (outbox["id"],),
        ).fetchone()
    assert queued["state"] == "queued" and queued["attempts"] == 1

    next_try = NOW + timedelta(seconds=301)
    accepted_session = _FakeSession()
    retry = _consumer(
        store,
        _FakeTransport(accepted_session),
        clock_value=next_try + timedelta(seconds=1),
    )
    result = retry.run_due("delivery-worker-retry", next_try, limit=1, lease_seconds=30)

    assert result.accepted == 1
    assert len(accepted_session.messages) == 1
    assert broken.session.messages == []


def test_disable_during_prepare_oserror_is_blocked_without_aborting_batch(
    monitoring_repository,
):
    store, enabled, outbox = _queued_delivery(monitoring_repository, admin_only=False)
    session = _FakeSession()
    transport = _FakeTransport(session, prepare_error=OSError("fixture connect failure"))

    def disable_during_prepare():
        store.set_control(enabled["revision"], False, NOW + timedelta(seconds=1))

    transport.before_return = disable_during_prepare
    result = _consumer(store, transport).run_due(
        "disable-race-worker", NOW, limit=1, lease_seconds=30
    )

    assert result.claimed == 1 and result.blocked == 1 and result.failed == 0
    assert transport.prepare_calls == 1 and session.messages == []
    with monitoring_repository.connect() as connection:
        row = connection.execute(
            "SELECT state,lease_token,failure_code FROM notification_outbox WHERE id=?",
            (outbox["id"],),
        ).fetchone()
    assert tuple(row) == ("failed", None, "monitoring_disabled")


def test_safe_prepare_failure_does_not_stop_later_eligible_owner(
    monitoring_repository,
):
    store, _, first_outbox = _queued_delivery(monitoring_repository, admin_only=True)
    second_owner, second_outbox = _queue_second_owner(
        monitoring_repository,
        store,
        role="admin",
    )
    session = _FakeSession()
    transport = _FakeTransport(session, prepare_error=OSError("fixture connect failure"))

    def revoke_first_owner_once():
        if transport.prepare_calls == 1:
            with monitoring_repository.connect() as connection:
                connection.execute("UPDATE users SET role='member' WHERE id=1")
                connection.commit()
            transport.prepare_error = None
            raise OSError("fixture connect failure")

    transport.before_return = revoke_first_owner_once
    result = _consumer(store, transport).run_due(
        "continue-after-revocation-worker", NOW, limit=2, lease_seconds=30
    )

    assert result.claimed == 2 and result.failed == 1 and result.accepted == 1
    assert result.blocked == 0 and result.cancelled is False
    assert second_owner > 1 and transport.prepare_calls == 2
    assert len(session.messages) == 1 and session.close_calls == 1
    with monitoring_repository.connect() as connection:
        first = connection.execute(
            "SELECT owner_user_id,state,failure_code FROM notification_outbox WHERE id=?",
            (first_outbox["id"],),
        ).fetchone()
        second = connection.execute(
            "SELECT owner_user_id,state FROM notification_outbox WHERE id=?",
            (second_outbox["id"],),
        ).fetchone()
    assert tuple(first) == (1, "failed", "delivery_not_eligible")
    assert tuple(second) == (second_owner, "accepted")


def test_cancellation_before_claim_leaves_outbox_untouched(monitoring_repository):
    store, _, outbox = _queued_delivery(monitoring_repository, admin_only=False)
    transport = _FakeTransport(_FakeSession())

    result = _consumer(store, transport).run_due(
        "cancel-before-claim-worker", NOW, limit=1, cancelled=lambda: True
    )

    assert result.available and result.cancelled and result.claimed == 0
    assert transport.prepare_calls == 0
    with monitoring_repository.connect() as connection:
        row = connection.execute(
            "SELECT state,attempts,lease_token FROM notification_outbox WHERE id=?",
            (outbox["id"],),
        ).fetchone()
    assert tuple(row) == ("queued", 0, None)


def test_cancellation_after_prepare_closes_session_and_preserves_lease_for_restart(
    monitoring_repository,
):
    store, _, outbox = _queued_delivery(monitoring_repository, admin_only=False)
    session = _FakeSession()
    transport = _FakeTransport(session)
    cancellation_checks = iter((False, False, False, True))
    consumer = _consumer(store, transport)

    result = consumer.run_due(
        "cancel-after-prepare-worker",
        NOW,
        limit=1,
        lease_seconds=30,
        cancelled=lambda: next(cancellation_checks),
    )

    assert result.cancelled and result.claimed == 1 and result.blocked == 0
    assert transport.prepare_calls == 1 and session.messages == [] and session.close_calls == 1
    with monitoring_repository.connect() as connection:
        row = connection.execute(
            "SELECT state,attempts,lease_token,submission_started_at FROM notification_outbox "
            "WHERE id=?",
            (outbox["id"],),
        ).fetchone()
    assert row["state"] == "claimed" and row["attempts"] == 1
    assert row["lease_token"] and row["submission_started_at"] is None

    recovered_session = _FakeSession()
    recovered = _consumer(
        store,
        _FakeTransport(recovered_session),
        clock_value=NOW + timedelta(seconds=31),
    ).run_due(
        "restart-after-cancel-worker",
        NOW + timedelta(seconds=31),
        limit=1,
        lease_seconds=30,
    )
    assert recovered.accepted == 1 and len(recovered_session.messages) == 1


def test_cancellation_during_session_validation_prevents_submission_checkpoint(
    monitoring_repository,
):
    store, _, outbox = _queued_delivery(monitoring_repository, admin_only=False)
    cancellation_event = Event()

    class _CancelWhenSendMethodIsResolved(_FakeSession):
        def __getattribute__(self, name):
            if name == "send_message":
                object.__getattribute__(self, "cancellation_event").set()
            return super().__getattribute__(name)

        def __init__(self):
            super().__init__()
            self.cancellation_event = cancellation_event

    session = _CancelWhenSendMethodIsResolved()
    transport = _FakeTransport(session)
    result = _consumer(store, transport).run_due(
        "cancel-at-checkpoint-worker",
        NOW,
        limit=1,
        lease_seconds=30,
        cancelled=cancellation_event.is_set,
    )

    assert result.cancelled and result.claimed == 1
    assert result.accepted == 0 and result.failed == 0 and result.blocked == 0
    assert transport.prepare_calls == 1
    assert session.messages == [] and session.close_calls == 1
    with monitoring_repository.connect() as connection:
        row = connection.execute(
            "SELECT state,attempts,lease_token,submission_started_at,submitted_at "
            "FROM notification_outbox WHERE id=?",
            (outbox["id"],),
        ).fetchone()
    assert row["state"] == "claimed" and row["attempts"] == 1
    assert row["lease_token"] is not None
    assert row["submission_started_at"] is None and row["submitted_at"] is None


def test_cancellation_after_checkpoint_records_definite_no_send(monitoring_repository, monkeypatch):
    store, _, outbox = _queued_delivery(monitoring_repository, admin_only=False)
    cancellation_event = Event()
    session = _FakeSession()
    original_checkpoint = store.mark_notification_outbox_submission_started

    def checkpoint_then_request_stop(owner, claim, now):
        checkpoint = original_checkpoint(owner, claim, now)
        cancellation_event.set()
        return checkpoint

    monkeypatch.setattr(
        store,
        "mark_notification_outbox_submission_started",
        checkpoint_then_request_stop,
    )
    result = _consumer(store, _FakeTransport(session)).run_due(
        "cancel-after-checkpoint-worker",
        NOW,
        limit=1,
        lease_seconds=30,
        cancelled=cancellation_event.is_set,
    )

    assert result.cancelled and result.claimed == 1 and result.failed == 1
    assert result.accepted == 0 and result.uncertain == 0
    assert session.messages == [] and session.close_calls == 1
    with monitoring_repository.connect() as connection:
        row = connection.execute(
            "SELECT state,submission_started_at,submitted_at,completed_at,failure_code "
            "FROM notification_outbox WHERE id=?",
            (outbox["id"],),
        ).fetchone()
    assert row["state"] == "failed"
    assert row["submission_started_at"] is not None
    assert row["submitted_at"] is None and row["completed_at"] is not None
    assert row["failure_code"] == "delivery_cancelled_before_send"


def test_cancellation_before_later_claimed_job_prevents_its_send(monitoring_repository):
    store, _, first_outbox = _queued_delivery(monitoring_repository, admin_only=False)
    second_owner, second_outbox = _queue_second_owner(monitoring_repository, store)
    session = _FakeSession()
    transport = _FakeTransport(session)
    cancellation_checks = iter((False, False, False, False, False, False, True))

    result = _consumer(store, transport).run_due(
        "cancel-between-jobs-worker",
        NOW,
        limit=2,
        lease_seconds=30,
        cancelled=lambda: next(cancellation_checks),
    )

    assert result.claimed == 2 and result.accepted == 1 and result.cancelled
    assert transport.prepare_calls == 1 and len(session.messages) == 1
    with monitoring_repository.connect() as connection:
        first = connection.execute(
            "SELECT state FROM notification_outbox WHERE id=?", (first_outbox["id"],)
        ).fetchone()
        second = connection.execute(
            "SELECT owner_user_id,state,lease_token FROM notification_outbox WHERE id=?",
            (second_outbox["id"],),
        ).fetchone()
    assert first["state"] == "accepted"
    assert second["owner_user_id"] == second_owner and second["state"] == "claimed"
    assert second["lease_token"] is not None


def test_consumer_without_settings_is_inert_and_does_not_claim(monitoring_repository):
    store, _, outbox = _queued_delivery(monitoring_repository, admin_only=False)
    transport = _FakeTransport(_FakeSession())
    consumer = NotificationDeliveryConsumer(
        store,
        settings=None,
        public_origin="https://ledger.example.invalid",
        transport=transport,
        clock=lambda: NOW,
    )

    result = consumer.run_due("delivery-worker", NOW, limit=1)

    assert result == delivery_module.DeliveryRunSummary(available=False)
    assert transport.prepare_calls == 0
    with monitoring_repository.connect() as connection:
        row = connection.execute(
            "SELECT state,attempts FROM notification_outbox WHERE id=?", (outbox["id"],)
        ).fetchone()
    assert tuple(row) == ("queued", 0)


@pytest.mark.parametrize(
    ("security", "port", "expected_class", "uses_starttls"),
    [
        ("implicit_tls", 465, "SMTP_SSL", False),
        ("implicit_tls", 2465, "SMTP_SSL", False),
        ("starttls", 587, "SMTP", True),
    ],
)
def test_transport_uses_only_supported_tls_modes_and_fixed_timeout(
    monkeypatch, security, port, expected_class, uses_starttls
):
    calls = []

    class FakeConnection:
        def __init__(self, *args, **kwargs):
            calls.append(("connect", args, kwargs))

        def ehlo(self):
            calls.append(("ehlo",))

        def starttls(self, *, context):
            calls.append(("starttls", context))

        def login(self, username, password):
            calls.append(("login", username, password))

        def close(self):
            calls.append(("close",))

    monkeypatch.setattr(delivery_module.smtplib, expected_class, FakeConnection)
    settings = _mail_settings(security=security, port=port)
    prepared = delivery_module.SMTPNotificationTransport().prepare(
        settings,
        timeout_seconds=delivery_module.SMTP_TIMEOUT_SECONDS,
    )

    assert isinstance(prepared, delivery_module._SMTPSession)
    assert calls[0][0] == "connect"
    assert calls[0][2]["timeout"] == 10.0
    assert calls[0][1][1] == port
    assert any(call[0] == "starttls" for call in calls) is uses_starttls
    assert calls[-1][0] == "login"


@pytest.mark.parametrize(
    "origin",
    [
        "https://ledger.example.invalid/path",
        "https://user:pass@ledger.example.invalid",
        "https://bad host.example.invalid",
        "https://ledger.example.invalid?next=//evil.example",
        "ftp://ledger.example.invalid",
        " https://ledger.example.invalid",
    ],
)
def test_consumer_rejects_non_origin_notification_links(origin):
    with pytest.raises(ValueError):
        delivery_module._configured_origin(origin)
