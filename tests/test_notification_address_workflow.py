"""Focused tests for draft notification-address persistence, API, and SMTP semantics."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import sqlite3
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import stock_probs.notification_address_store as notification_address_store_module
import stock_probs.repository as repository_module
from stock_probs.invitation_mail import InvitationMailSettings
from stock_probs.monitoring_store import MonitoringStore
from stock_probs.notification_address_api import create_notification_address_router
from stock_probs.notification_address_store import (
    MAX_CHALLENGES_PER_OWNER,
    MAX_CODE_ATTEMPTS,
    NotificationAddressConflict,
    NotificationAddressRateLimited,
    NotificationAddressStore,
    NotificationAddressUnavailable,
)
from stock_probs.notification_verification import NotificationVerificationService
from stock_probs.repository import Repository

ROOT = Path(__file__).parents[1]
MIGRATION_DIR = ROOT / "src/stock_probs/migrations"
SCHEMA_018 = MIGRATION_DIR / "018_notification_address_delivery.sql"
NOW = datetime(2026, 10, 14, 12, 0, tzinfo=UTC)
WRONG_CODE = "Z" * 43


@pytest.fixture
def address_context(tmp_path, monkeypatch):
    """Create the historical 001-017 base, then apply the exact registered schema-18 SQL."""

    registered = tmp_path / "registered-migrations-001-017"
    registered.mkdir(mode=0o700)
    for migration in sorted(MIGRATION_DIR.glob("[0-9][0-9][0-9]_*.sql")):
        if int(migration.name[:3]) <= 17:
            shutil.copyfile(migration, registered / migration.name)
    original_files = repository_module.files

    def migration_resources(package: str):
        if package == "stock_probs.migrations":
            return registered
        return original_files(package)

    monkeypatch.setattr(repository_module, "files", migration_resources)
    # Preserve the historical schema-18 draft fixture as the 1–17 base. The active package
    # now registers schema 19, which includes notification migration 018 and briefing 019.
    monkeypatch.setattr(repository_module, "SCHEMA_VERSION", 17)
    repository = Repository(tmp_path / "notification-address.sqlite3")
    repository.migrate()
    with repository.connect() as connection:
        connection.executescript(SCHEMA_018.read_text(encoding="utf-8"))
        connection.commit()
    repository.create_user(
        github_user_id=9401,
        login="address-owner-one",
        display_name="Address owner one",
        password_hash=None,
        created_at=NOW,
    )
    repository.create_user(
        github_user_id=9402,
        login="address-owner-two",
        display_name="Address owner two",
        password_hash=None,
        created_at=NOW,
    )
    monitoring = MonitoringStore(repository)
    control = monitoring.get_control()
    monitoring.set_control(control["revision"], True, NOW)
    return repository, monitoring, NotificationAddressStore(monitoring)


class _FakeSession:
    def __init__(
        self, *, refused: dict[str, tuple[int, bytes]] | None = None, error: Exception | None = None
    ):
        self.refused = {} if refused is None else refused
        self.error = error
        self.messages: list[EmailMessage] = []
        self.closed = False

    def send_message(self, message: EmailMessage):
        self.messages.append(message)
        if self.error is not None:
            raise self.error
        return self.refused

    def close(self) -> None:
        self.closed = True


class _FakeTransport:
    def __init__(
        self,
        session: _FakeSession | None = None,
        *,
        prepare_error: Exception | None = None,
        on_prepare: Callable[[], None] | None = None,
    ):
        self.session = _FakeSession() if session is None else session
        self.prepare_error = prepare_error
        self.on_prepare = on_prepare
        self.prepared_settings: list[InvitationMailSettings] = []
        self.timeouts: list[float] = []

    def prepare(self, settings: InvitationMailSettings, *, timeout_seconds: float):
        self.prepared_settings.append(settings)
        self.timeouts.append(timeout_seconds)
        if self.on_prepare is not None:
            self.on_prepare()
        if self.prepare_error is not None:
            raise self.prepare_error
        return self.session


class _HeldSession(_FakeSession):
    def __init__(self) -> None:
        super().__init__()
        self.started = threading.Event()
        self.release = threading.Event()

    def send_message(self, message: EmailMessage) -> dict[str, tuple[int, bytes]]:
        self.messages.append(message)
        self.started.set()
        if not self.release.wait(timeout=4):
            raise TimeoutError("fixture release was not signaled")
        return {}


def _settings(security: str = "implicit_tls", port: int = 465) -> InvitationMailSettings:
    return InvitationMailSettings(
        host="smtp.example.test",
        port=port,
        username="fixture-user",
        password="fixture-" + ("x" * 16),
        security=security,
        from_address="notifications@example.test",
    )


def _service(
    store: NotificationAddressStore,
    transport: _FakeTransport,
    *,
    security: str = "implicit_tls",
    port: int = 465,
    clock: Callable[[], datetime] | None = None,
) -> NotificationVerificationService:
    return NotificationVerificationService(
        store,
        settings=_settings(security, port),
        public_origin="https://app.example.test",
        transport=transport,
        clock=(lambda: NOW) if clock is None else clock,
    )


def _request(store: NotificationAddressStore, address: str = "owner@example.test", owner: int = 1):
    return store.request_verification(owner, address, str(uuid4()), NOW)


def _code_from(message: EmailMessage) -> str:
    plain = message.get_body(preferencelist=("plain",))
    assert plain is not None
    match = re.search(
        r"one-time verification code in your signed-in workspace: ([A-Za-z0-9_-]{43})",
        plain.get_content(),
    )
    assert match is not None
    return match.group(1)


def test_challenge_hash_idempotency_and_payload_privacy(address_context):
    repository, _monitoring, store = address_context
    address = "owner+research@example.test"
    key = str(uuid4())
    issue = store.request_verification(1, address, key, NOW)
    assert issue.state == "queued"
    assert issue._code is not None
    assert address not in repr(issue)
    assert issue._code not in repr(issue)

    with repository.connect() as connection:
        row = connection.execute(
            "SELECT request_sha256,token_sha256,state FROM notification_address_verifications "
            "WHERE id=?",
            (issue.verification_id,),
        ).fetchone()
        assert row["request_sha256"] == hashlib.sha256(address.encode("ascii")).hexdigest()
        assert row["token_sha256"] == hashlib.sha256(issue._code.encode("ascii")).hexdigest()
        assert issue._code not in row["token_sha256"]
        assert row["state"] == "queued"
        columns = {
            column["name"]
            for column in connection.execute(
                "PRAGMA table_info(notification_address_verifications)"
            ).fetchall()
        }
        assert "address" not in columns
        recipient = connection.execute(
            "SELECT address FROM notification_address_verification_recipients "
            "WHERE verification_id=?",
            (issue.verification_id,),
        ).fetchone()
        assert recipient["address"] == address

    replay = store.request_verification(1, address, key, NOW + timedelta(seconds=1))
    assert replay.replayed is True
    assert replay.verification_id == issue.verification_id
    assert replay._code is None
    with pytest.raises(NotificationAddressConflict):
        store.request_verification(1, "different@example.test", key, NOW)
    assert store.get_status(1, issue.verification_id, NOW).state == "queued"
    with pytest.raises(NotificationAddressUnavailable):
        store.get_status(2, issue.verification_id, NOW)


def test_dispatch_recipient_is_persisted_owner_bound_and_code_bound(address_context):
    _repository, monitoring, store = address_context
    mailbox = "persisted-recipient@example.test"
    issue = _request(store, address=mailbox)
    assert (
        store.dispatch_recipient(1, issue.verification_id, issue.revision, issue._code, NOW)
        == mailbox
    )
    with pytest.raises(NotificationAddressUnavailable):
        store.dispatch_recipient(2, issue.verification_id, issue.revision, issue._code, NOW)
    with pytest.raises(NotificationAddressUnavailable):
        store.dispatch_recipient(1, issue.verification_id, issue.revision, WRONG_CODE, NOW)
    with pytest.raises(NotificationAddressUnavailable):
        store.dispatch_recipient(1, issue.verification_id, issue.revision + 1, issue._code, NOW)

    control = monitoring.get_control()
    monitoring.set_control(control["revision"], False, NOW)
    with pytest.raises(NotificationAddressUnavailable):
        store.dispatch_recipient(1, issue.verification_id, issue.revision, issue._code, NOW)


def test_owner_control_revocation_and_admin_canary_are_rechecked(address_context):
    repository, monitoring, store = address_context
    issue = _request(store)
    with repository.connect() as connection:
        connection.execute("UPDATE users SET status='disabled' WHERE id=1")
        connection.commit()
    with pytest.raises(NotificationAddressUnavailable):
        store.mark_submission_started(1, issue.verification_id, issue.revision, issue._code, NOW)

    with repository.connect() as connection:
        connection.execute("UPDATE users SET status='active',role='member' WHERE id=1")
        connection.commit()
    admin_store = NotificationAddressStore(MonitoringStore(repository, admin_only=True))
    with pytest.raises(NotificationAddressUnavailable):
        admin_store.request_verification(1, "admin@example.test", str(uuid4()), NOW)

    control = monitoring.get_control()
    monitoring.set_control(control["revision"], False, NOW)
    with pytest.raises(NotificationAddressUnavailable):
        store.request_verification(2, "member@example.test", str(uuid4()), NOW)


def test_account_revocation_after_smtp_acceptance_blocks_code_verification(address_context):
    repository, _monitoring, store = address_context
    issue = _request(store)
    store.mark_submission_started(1, issue.verification_id, issue.revision, issue._code, NOW)
    accepted = store.finish_submission(1, issue.verification_id, "accepted", NOW)
    with repository.connect() as connection:
        connection.execute("UPDATE users SET status='disabled' WHERE id=1")
        connection.commit()
    with pytest.raises(NotificationAddressUnavailable):
        store.verify_code(1, issue.verification_id, issue._code, accepted.revision, NOW)


def test_new_challenge_invalidates_old_and_owner_rate_limit_is_bounded(address_context):
    _repository, _monitoring, store = address_context
    first = _request(store, address="first@example.test")
    second = store.request_verification(
        1, "second@example.test", str(uuid4()), NOW + timedelta(minutes=1)
    )
    assert store.get_status(1, first.verification_id, NOW).state == "superseded"
    assert second.state == "queued"

    _request(store, address="third@example.test", owner=2)
    _request(store, address="fourth@example.test", owner=2)
    _request(store, address="fifth@example.test", owner=2)
    with pytest.raises(NotificationAddressRateLimited):
        _request(store, address="sixth@example.test", owner=2)


def test_wrong_code_attempts_expire_and_unsubmitted_code_cannot_verify(address_context):
    _repository, _monitoring, store = address_context
    issue = _request(store)
    with pytest.raises(NotificationAddressUnavailable):
        store.verify_code(1, issue.verification_id, issue._code, issue.revision, NOW)

    submitting = store.mark_submission_started(
        1, issue.verification_id, issue.revision, issue._code, NOW
    )
    accepted = store.finish_submission(1, issue.verification_id, "accepted", NOW)
    assert accepted.revision == submitting.revision + 1
    current_revision = accepted.revision
    for attempt in range(MAX_CODE_ATTEMPTS):
        result = store.verify_code(
            1,
            issue.verification_id,
            WRONG_CODE,
            current_revision,
            NOW + timedelta(seconds=attempt + 1),
        )
        current_revision = result["revision"]
    assert result["state"] == "expired"
    assert result["attempts"] == MAX_CODE_ATTEMPTS
    with pytest.raises(NotificationAddressUnavailable):
        store.verify_code(
            1, issue.verification_id, issue._code, result["revision"], NOW + timedelta(minutes=1)
        )


def test_expired_challenge_cannot_verify(address_context):
    repository, _monitoring, store = address_context
    issue = _request(store)
    store.mark_submission_started(1, issue.verification_id, issue.revision, issue._code, NOW)
    accepted = store.finish_submission(1, issue.verification_id, "accepted", NOW)
    result = store.verify_code(
        1,
        issue.verification_id,
        issue._code,
        accepted.revision,
        NOW + timedelta(minutes=20, seconds=1),
    )
    assert result["state"] == "expired"
    assert result.get("verified") is not True
    with repository.connect() as connection:
        assert (
            connection.execute(
                "SELECT 1 FROM notification_address_verification_recipients "
                "WHERE verification_id=?",
                (issue.verification_id,),
            ).fetchone()
            is None
        )


def test_stale_submission_recovers_to_uncertain_and_is_never_replayed(address_context):
    repository, _monitoring, store = address_context
    key = str(uuid4())
    issue = store.request_verification(1, "owner@example.test", key, NOW)
    checkpoint = store.mark_submission_started(
        1, issue.verification_id, issue.revision, issue._code, NOW
    )
    restarted = NotificationAddressStore(MonitoringStore(Repository(repository.database_path)))
    replay = restarted.request_verification(
        1, "owner@example.test", key, NOW + timedelta(seconds=31)
    )
    assert replay.replayed is True
    assert replay._code is None
    assert replay.state == "uncertain"
    assert replay.revision == checkpoint.revision + 1
    transport = _FakeTransport()
    result = _service(restarted, transport).submit(1, replay)
    assert result.state == "uncertain"
    assert transport.prepared_settings == []
    assert transport.session.messages == []
    accepted = restarted.verify_code(
        1,
        issue.verification_id,
        issue._code,
        replay.revision,
        NOW + timedelta(seconds=32),
    )
    assert accepted["verified"] is True


def test_verification_revision_conflict_does_not_consume_code(address_context):
    _repository, _monitoring, store = address_context
    issue = _request(store)
    result = _service(store, _FakeTransport()).submit(1, issue)
    assert result.state == "accepted"
    with pytest.raises(NotificationAddressConflict):
        store.verify_code(
            1,
            issue.verification_id,
            issue._code,
            result.revision - 1,
            NOW,
        )
    verified = store.verify_code(
        1,
        issue.verification_id,
        issue._code,
        result.revision,
        NOW,
    )
    assert verified["verified"] is True


def test_verified_address_never_selects_or_enables_preferences(address_context):
    repository, monitoring, store = address_context
    previous_id = str(uuid4())
    with repository.connect() as connection:
        connection.execute(
            "INSERT INTO notification_addresses(id,owner_user_id,address,verified_at,created_at) "
            "VALUES (?,?,?,?,?)",
            (previous_id, 1, "previous@example.test", NOW.isoformat(), NOW.isoformat()),
        )
        connection.execute(
            "INSERT INTO notification_preferences(owner_user_id,revision,address_id,alert_email,"
            "digest_email,digest_time,digest_timezone,updated_at) VALUES (1,4,?,1,1,'09:00',?,?)",
            (previous_id, "America/Toronto", NOW.isoformat()),
        )
        connection.commit()
    issue = _request(store, address="replacement@example.test")
    store.mark_submission_started(1, issue.verification_id, issue.revision, issue._code, NOW)
    accepted = store.finish_submission(1, issue.verification_id, "accepted", NOW)
    result = store.verify_code(1, issue.verification_id, issue._code, accepted.revision, NOW)
    assert result["verified"] is True
    assert result["address_id"] != previous_id
    prefs = monitoring.get_notification_preferences(1)
    assert prefs["address_id"] == previous_id
    assert prefs["alert_email"] is True and prefs["digest_email"] is True
    assert all("address" not in row for row in store.list_verified_addresses(1))
    selected = store.select_verified_address(1, result["address_id"], 4, NOW)
    assert selected["revision"] == 5
    assert selected["address_id"] == result["address_id"]
    assert selected["alert_email"] is False
    assert selected["digest_email"] is False
    with pytest.raises(NotificationAddressConflict):
        store.select_verified_address(1, previous_id, 4, NOW)
    with pytest.raises(NotificationAddressUnavailable):
        store.select_verified_address(2, result["address_id"], 0, NOW)


def test_new_account_preferences_are_explicitly_off_after_verification(address_context):
    _repository, monitoring, store = address_context
    issue = _request(store, address="new-owner@example.test", owner=2)
    store.mark_submission_started(2, issue.verification_id, issue.revision, issue._code, NOW)
    accepted = store.finish_submission(2, issue.verification_id, "accepted", NOW)
    store.verify_code(2, issue.verification_id, issue._code, accepted.revision, NOW)
    prefs = monitoring.get_notification_preferences(2)
    assert prefs["address_id"] is None
    assert prefs["alert_email"] is False
    assert prefs["digest_email"] is False


def test_service_acceptance_tls_modes_failure_and_uncertainty(address_context):
    _repository, _monitoring, store = address_context
    for security, port in (("implicit_tls", 465), ("starttls", 587)):
        recipient = f"{security}@example.test"
        issue = _request(store, address=recipient, owner=1)
        transport = _FakeTransport()
        service = _service(store, transport, security=security, port=port)
        result = service.submit(1, issue)
        assert result.state == "accepted"
        assert len(transport.session.messages) == 1
        assert transport.session.closed is True
        assert transport.timeouts == [10.0]
        assert transport.prepared_settings[0].security == security
        message = transport.session.messages[0]
        assert str(message["From"]).startswith("Signal Ledger <")
        assert "Signal Ledger" in message.get_body(preferencelist=("plain",)).get_content()
        assert message["Message-ID"] == (
            f"<notification-address-{issue.verification_id.replace('-', '')}@stock-probs.invalid>"
        )
        code = _code_from(message)
        assert issue._code == code
        assert "/notifications" in message.get_body(preferencelist=("plain",)).get_content()
        assert (
            "does not enable alert or digest email"
            in message.get_body(preferencelist=("plain",)).get_content()
        )
        assert str(message["To"]) == recipient
        assert recipient not in repr(issue)
        verified = store.verify_code(1, issue.verification_id, code, result.revision, NOW)
        assert verified["verified"] is True

    issue = _request(store, address="uncertain@example.test", owner=2)
    uncertain_transport = _FakeTransport(_FakeSession(error=OSError("private transport text")))
    uncertain_result = _service(store, uncertain_transport).submit(2, issue)
    assert uncertain_result.state == "uncertain"
    assert len(uncertain_transport.session.messages) == 1
    replay = store.request_verification(
        2, "uncertain@example.test", str(uuid4()), NOW + timedelta(minutes=1)
    )
    assert replay.state == "queued"
    assert replay._code is not None
    # A fresh explicit key is a new challenge; the old idempotency key itself never resends.
    key = str(uuid4())
    issue2 = store.request_verification(
        2, "uncertain@example.test", key, NOW + timedelta(minutes=2)
    )
    issue2_transport = _FakeTransport()
    issue2_service = _service(store, issue2_transport)
    first = issue2_service.submit(2, issue2)
    replay2 = store.request_verification(
        2, "uncertain@example.test", key, NOW + timedelta(minutes=3)
    )
    second = issue2_service.submit(2, replay2)
    assert first.state == "accepted" and second.state == "accepted"
    assert len(issue2_transport.session.messages) == 1


def test_prepare_failure_and_control_change_before_checkpoint_never_send(address_context):
    _repository, monitoring, store = address_context
    issue = _request(store)
    failed_transport = _FakeTransport(prepare_error=OSError("secret transport failure"))
    failed = _service(store, failed_transport).submit(1, issue)
    assert failed.state == "failed"
    assert not failed_transport.session.messages

    second = _request(store, address="second@example.test", owner=2)

    def disable_during_prepare() -> None:
        control = monitoring.get_control()
        monitoring.set_control(control["revision"], False, NOW)

    transport = _FakeTransport(on_prepare=disable_during_prepare)
    result = _service(store, transport).submit(2, second)
    assert result.state == "blocked"
    assert transport.session.closed is True
    assert len(transport.prepared_settings) == 1
    assert transport.session.messages == []


def test_stale_issue_is_blocked_before_smtp_prepare(address_context):
    _repository, _monitoring, store = address_context
    issue = _request(store)
    forged = replace(issue, _code=WRONG_CODE)
    transport = _FakeTransport()
    result = _service(store, transport).submit(1, forged)
    assert result.state == "blocked"
    assert transport.prepared_settings == []
    assert transport.session.messages == []


def test_checkpoint_database_failure_closes_prepared_session_without_sending(
    address_context, monkeypatch
):
    _repository, _monitoring, store = address_context
    issue = _request(store)

    def fail_checkpoint(*_args: object, **_kwargs: object) -> object:
        raise sqlite3.OperationalError("fixture database failure")

    monkeypatch.setattr(store, "mark_submission_started", fail_checkpoint)
    transport = _FakeTransport()
    result = _service(store, transport).submit(1, issue)
    assert result.state == "blocked"
    assert len(transport.prepared_settings) == 1
    assert transport.session.closed is True
    assert transport.session.messages == []


def test_smtp_definite_rejection_is_failed_and_replay_never_sends(address_context):
    _repository, _monitoring, store = address_context
    key = str(uuid4())
    issue = store.request_verification(1, "rejected@example.test", key, NOW)
    transport = _FakeTransport(_FakeSession(refused={"rejected@example.test": (550, b"rejected")}))
    failed = _service(store, transport).submit(1, issue)
    assert failed.state == "failed"
    assert len(transport.session.messages) == 1
    replay = store.request_verification(1, "rejected@example.test", key, NOW + timedelta(seconds=1))
    result = _service(store, transport).submit(1, replay)
    assert replay.replayed is True
    assert result.state == "failed"
    assert len(transport.session.messages) == 1


def _api_client(
    store: NotificationAddressStore,
    owner: object = 1,
    *,
    service: NotificationVerificationService | None = None,
    email_enabled: bool = True,
    allowed: bool = True,
    clock: Callable[[], datetime] | None = None,
) -> TestClient:
    app = FastAPI()
    app.include_router(
        create_notification_address_router(
            store,
            lambda _request: owner,  # type: ignore[arg-type]
            lambda _request, _owner: allowed,
            email_enabled=email_enabled,
            service=service,
            clock=(lambda: NOW) if clock is None else clock,
        )
    )
    return TestClient(app)


def test_api_is_off_by_default_owner_scoped_and_never_echoes_private_input(address_context):
    _repository, _monitoring, store = address_context
    default_off = _api_client(store, email_enabled=False)
    response = default_off.post(
        "/api/v1/notification-address-verifications",
        json={"address": "private+alias@example.test"},
        headers={"Idempotency-Key": str(uuid4())},
    )
    assert response.status_code == 503
    assert "private+alias@example.test" not in response.text

    for invalid_owner in (True, 1.0, "1", None):
        client = _api_client(store, owner=invalid_owner)
        response = client.get("/api/v1/notification-addresses")
        assert response.status_code == 401

    transport = _FakeTransport()
    service = _service(store, transport)
    client = _api_client(store, service=service)
    private_address = "owner+private@example.test"
    key = str(uuid4())
    response = client.post(
        "/api/v1/notification-address-verifications",
        content=f'{{"address":"{private_address}"}}',
        headers={"content-type": "application/json", "Idempotency-Key": key},
    )
    assert response.status_code == 202
    assert private_address not in response.text
    verification_id = response.json()["verification_id"]
    revision = response.json()["revision"]
    code = _code_from(transport.session.messages[0])
    replay = client.post(
        "/api/v1/notification-address-verifications",
        content=f'{{"address":"{private_address}"}}',
        headers={"content-type": "application/json", "Idempotency-Key": key},
    )
    assert replay.json()["replayed"] is True
    assert replay.status_code == 200
    assert len(transport.session.messages) == 1

    denied = _api_client(store, service=service, allowed=False)
    denied_response = denied.post(
        "/api/v1/notification-address-verifications",
        json={"address": "blocked@example.test"},
        headers={"Idempotency-Key": str(uuid4())},
    )
    assert denied_response.status_code == 403
    assert len(transport.session.messages) == 1

    confirm = client.post(
        "/api/v1/notification-address-verifications/confirm",
        json={"verification_id": verification_id, "code": code, "expected_revision": revision},
    )
    assert confirm.status_code == 200
    assert private_address not in confirm.text
    assert code not in confirm.text
    assert confirm.json()["verified"] is True
    addresses = client.get("/api/v1/notification-addresses")
    assert private_address not in addresses.text
    assert addresses.json()["items"][0]["id"] == confirm.json()["address_id"]
    selected = client.post(
        "/api/v1/notification-addresses/select",
        json={"address_id": confirm.json()["address_id"], "expected_revision": 1},
    )
    assert selected.status_code == 200
    assert selected.json()["address_id"] == confirm.json()["address_id"]
    assert selected.json()["alert_email"] is False
    assert selected.json()["digest_email"] is False
    stale_selection = client.post(
        "/api/v1/notification-addresses/select",
        json={"address_id": confirm.json()["address_id"], "expected_revision": 1},
    )
    assert stale_selection.status_code == 409
    foreign_selection = _api_client(store, owner=2).post(
        "/api/v1/notification-addresses/select",
        json={"address_id": confirm.json()["address_id"], "expected_revision": 0},
    )
    assert foreign_selection.status_code == 404

    invalid = client.post(
        "/api/v1/notification-address-verifications",
        content=json.dumps({"address": "private+alias@example.test\r\nBcc: bad@example.test"}),
        headers={"content-type": "application/json", "Idempotency-Key": str(uuid4())},
    )
    assert invalid.status_code == 422
    assert "private+alias@example.test" not in invalid.text
    assert "bad@example.test" not in invalid.text


def test_api_rejects_oversized_request_before_submission(address_context):
    _repository, _monitoring, store = address_context
    transport = _FakeTransport()
    client = _api_client(store, service=_service(store, transport))
    body = b'{"address":"' + (b"a" * 2100) + b'@example.test"}'
    response = client.post(
        "/api/v1/notification-address-verifications",
        content=body,
        headers={
            "content-type": "application/json",
            "Idempotency-Key": str(uuid4()),
        },
    )
    assert response.status_code == 413
    assert body.decode("ascii") not in response.text
    assert transport.prepared_settings == []
    assert transport.session.messages == []


def test_api_rejects_owner_fields_duplicate_keys_foreign_challenge_and_wrong_code_echo(
    address_context,
):
    _repository, _monitoring, store = address_context
    transport = _FakeTransport()
    service = _service(store, transport)
    owner_one = _api_client(store, owner=1, service=service)
    owner_two = _api_client(store, owner=2, service=service)
    key = str(uuid4())
    bad_payload = owner_one.post(
        "/api/v1/notification-address-verifications",
        json={"address": "owner@example.test", "owner_user_id": 2},
        headers={"Idempotency-Key": key},
    )
    assert bad_payload.status_code == 422
    assert not transport.session.messages

    duplicate_key = owner_one.post(
        "/api/v1/notification-address-verifications",
        content='{"address":"owner@example.test","address":"other@example.test"}',
        headers={"content-type": "application/json", "Idempotency-Key": key},
    )
    assert duplicate_key.status_code == 400
    assert "@example.test" not in duplicate_key.text

    issue = store.request_verification(1, "owner@example.test", str(uuid4()), NOW)
    fake = _FakeTransport()
    summary = _service(store, fake).submit(1, issue)
    status = store.get_status(1, issue.verification_id, NOW)
    foreign = owner_two.post(
        "/api/v1/notification-address-verifications/confirm",
        json={
            "verification_id": issue.verification_id,
            "code": _code_from(fake.session.messages[0]),
            "expected_revision": status.revision,
        },
    )
    assert foreign.status_code == 404
    wrong = owner_one.post(
        "/api/v1/notification-address-verifications/confirm",
        json={
            "verification_id": issue.verification_id,
            "code": WRONG_CODE,
            "expected_revision": summary.revision,
        },
    )
    assert wrong.status_code == 422
    assert WRONG_CODE not in wrong.text
    assert "owner@example.test" not in wrong.text


def test_status_recovers_queued_crash_and_new_key_explicitly_replaces_code(address_context):
    repository, _monitoring, store = address_context
    later = NOW + timedelta(seconds=31)
    address = "recover@example.test"
    original_key = str(uuid4())
    issue = store.request_verification(1, address, original_key, NOW)
    transport = _FakeTransport()
    service = _service(store, transport, clock=lambda: later)
    client = _api_client(store, service=service, clock=lambda: later)

    status_response = client.get(
        f"/api/v1/notification-address-verifications/{issue.verification_id}"
    )
    assert status_response.status_code == 200
    status = status_response.json()
    assert status["state"] == "failed"
    assert status["revision"] == issue.revision + 1
    assert address not in status_response.text
    assert issue._code not in status_response.text
    with repository.connect() as connection:
        assert (
            connection.execute(
                "SELECT 1 FROM notification_address_verification_recipients "
                "WHERE verification_id=?",
                (issue.verification_id,),
            ).fetchone()
            is None
        )
        assert "address" not in {
            column["name"]
            for column in connection.execute(
                "PRAGMA table_info(notification_address_verifications)"
            ).fetchall()
        }

    replay = store.request_verification(1, address, original_key, later)
    assert replay.replayed is True and replay.state == "failed" and replay._code is None
    assert service.submit(1, replay).state == "failed"
    assert transport.prepared_settings == []

    replacement_key = str(uuid4())
    payload = {
        "address": address,
        "verification_id": issue.verification_id,
        "expected_revision": status["revision"],
    }
    replacement = client.post(
        "/api/v1/notification-address-verifications/regenerate",
        json=payload,
        headers={"Idempotency-Key": replacement_key},
    )
    assert replacement.status_code == 202
    assert replacement.json()["state"] == "accepted"
    assert replacement.json()["verification_id"] != issue.verification_id
    assert address not in replacement.text
    assert len(transport.session.messages) == 1
    current_status = client.get("/api/v1/notification-address-verifications/current")
    assert current_status.status_code == 200
    assert current_status.json()["verification_id"] == replacement.json()["verification_id"]
    assert current_status.json()["state"] == "accepted"
    assert address not in current_status.text
    reused = client.post(
        "/api/v1/notification-address-verifications/regenerate",
        json=payload,
        headers={"Idempotency-Key": replacement_key},
    )
    assert reused.status_code == 409
    assert len(transport.session.messages) == 1

    old_status = client.get(f"/api/v1/notification-address-verifications/{issue.verification_id}")
    new_status = client.get(
        f"/api/v1/notification-address-verifications/{replacement.json()['verification_id']}"
    )
    assert old_status.json()["state"] == "superseded"
    assert new_status.json()["state"] == "accepted"
    assert address not in old_status.text + new_status.text


def test_current_status_orders_equal_time_challenges_by_creation_event_after_lost_response(
    address_context, monkeypatch
):
    repository, _monitoring, store = address_context
    generated_ids = iter(
        (
            "ffffffff-ffff-4fff-8fff-ffffffffffff",
            "11111111-1111-4111-8111-111111111111",
            "00000000-0000-4000-8000-000000000001",
            "22222222-2222-4222-8222-222222222222",
        )
    )
    monkeypatch.setattr(notification_address_store_module, "uuid4", lambda: next(generated_ids))

    older = store.request_verification(1, "older@example.test", str(uuid4()), NOW)
    newer_id = "00000000-0000-4000-8000-000000000001"
    store.request_verification(1, "newer@example.test", str(uuid4()), NOW)
    assert older.verification_id > newer_id

    with repository.connect() as connection:
        creation_events = connection.execute(
            "SELECT verification_id,event_id FROM notification_address_verification_events "
            "WHERE owner_user_id=? AND revision=1 ORDER BY event_id",
            (1,),
        ).fetchall()
        requested_times = connection.execute(
            "SELECT id,requested_at FROM notification_address_verifications "
            "WHERE owner_user_id=? ORDER BY requested_at,id",
            (1,),
        ).fetchall()
        legacy_selection = connection.execute(
            "SELECT id FROM notification_address_verifications WHERE owner_user_id=? "
            "ORDER BY requested_at DESC,id DESC LIMIT 1",
            (1,),
        ).fetchone()
    assert [row["verification_id"] for row in creation_events] == [
        older.verification_id,
        newer_id,
    ]
    assert creation_events[0]["event_id"] < creation_events[1]["event_id"]
    assert len(requested_times) == 2
    assert requested_times[0]["requested_at"] == requested_times[1]["requested_at"]
    assert legacy_selection["id"] == older.verification_id

    # The second create response is intentionally discarded; this GET is the recovery path.
    client = _api_client(store)
    current = client.get("/api/v1/notification-address-verifications/current")
    assert current.status_code == 200
    assert current.json()["verification_id"] == newer_id
    assert current.json()["state"] == "queued"
    assert store.get_status(1, older.verification_id, NOW).state == "superseded"
    assert "older@example.test" not in current.text
    assert "newer@example.test" not in current.text


def test_async_submission_uses_threadpool_while_health_request_progresses(address_context):
    _repository, _monitoring, store = address_context
    session = _HeldSession()
    transport = _FakeTransport(session)
    service = _service(store, transport)
    app = FastAPI()

    @app.get("/health")
    async def health() -> dict[str, bool]:
        return {"ok": True}

    app.include_router(
        create_notification_address_router(
            store,
            lambda _request: 1,
            lambda _request, _owner: True,
            email_enabled=True,
            service=service,
            clock=lambda: NOW,
        )
    )
    release_timer = threading.Timer(1.5, session.release.set)
    release_timer.start()
    with TestClient(app) as client, ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(
            client.post,
            "/api/v1/notification-address-verifications",
            json={"address": "held@example.test"},
            headers={"Idempotency-Key": str(uuid4())},
        )
        try:
            assert session.started.wait(timeout=1)
            health_started = time.monotonic()
            response = client.get("/health")
            health_elapsed = time.monotonic() - health_started
        finally:
            session.release.set()
            release_timer.cancel()
        submission = future.result(timeout=3)
    assert response.status_code == 200 and response.json() == {"ok": True}
    assert health_elapsed < 0.75
    assert submission.status_code == 202
    assert len(session.messages) == 1


def test_challenge_and_event_history_have_a_hard_bounded_owner_cap(address_context):
    repository, _monitoring, store = address_context
    requested_at = store._format_time(NOW - timedelta(hours=2))
    expires_at = store._format_time(NOW - timedelta(hours=1, minutes=40))
    with repository.connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        connection.executemany(
            "INSERT INTO notification_address_verifications("
            "id,owner_user_id,address_id,idempotency_sha256,request_sha256,token_sha256,state,"
            "revision,attempts,requested_at,expires_at,completed_at) "
            "VALUES (?,?,?, ?,?,?, 'already_verified',1,0,?,?,?)",
            [
                (
                    str(uuid4()),
                    1,
                    str(uuid4()),
                    hashlib.sha256(f"key-{index}".encode()).hexdigest(),
                    hashlib.sha256(f"recipient-{index}".encode()).hexdigest(),
                    hashlib.sha256(f"token-{index}".encode()).hexdigest(),
                    requested_at,
                    expires_at,
                    requested_at,
                )
                for index in range(MAX_CHALLENGES_PER_OWNER)
            ],
        )
        connection.commit()
    with pytest.raises(NotificationAddressRateLimited):
        store.request_verification(
            1,
            "past-cap@example.test",
            str(uuid4()),
            NOW,
        )
    with repository.connect() as connection:
        assert (
            connection.execute(
                "SELECT COUNT(*) AS count FROM notification_address_verifications "
                "WHERE owner_user_id=1"
            ).fetchone()["count"]
            == MAX_CHALLENGES_PER_OWNER
        )
        assert (
            connection.execute(
                "SELECT COUNT(*) AS count FROM notification_address_verification_events "
                "WHERE owner_user_id=1"
            ).fetchone()["count"]
            <= MAX_CHALLENGES_PER_OWNER * 12
        )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO notification_address_verifications("
                "id,owner_user_id,address_id,idempotency_sha256,request_sha256,token_sha256,state,"
                "revision,attempts,requested_at,expires_at,completed_at) "
                "VALUES (?,?,?,?,?,?,'already_verified',1,0,?,?,?)",
                (
                    str(uuid4()),
                    1,
                    str(uuid4()),
                    hashlib.sha256(b"over-cap-key").hexdigest(),
                    hashlib.sha256(b"over-cap-recipient").hexdigest(),
                    hashlib.sha256(b"over-cap-token").hexdigest(),
                    requested_at,
                    expires_at,
                    requested_at,
                ),
            )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO notification_address_verification_events("
                "verification_id,owner_user_id,"
                "revision,event_kind,occurred_at) VALUES (?,?,13,'queued',?)",
                (
                    connection.execute(
                        "SELECT id FROM notification_address_verifications "
                        "WHERE owner_user_id=1 LIMIT 1"
                    ).fetchone()["id"],
                    1,
                    store._format_time(NOW),
                ),
            )


def test_draft_triggers_reject_transition_skip_and_event_mutation(address_context):
    repository, _monitoring, store = address_context
    issue = _request(store)
    with repository.connect() as connection:
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "DELETE FROM notification_address_verification_recipients WHERE verification_id=?",
                (issue.verification_id,),
            )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "UPDATE notification_address_verifications "
                "SET state='accepted',revision=revision+1 "
                "WHERE id=?",
                (issue.verification_id,),
            )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "UPDATE notification_address_verification_events SET event_kind='accepted' "
                "WHERE verification_id=?",
                (issue.verification_id,),
            )
