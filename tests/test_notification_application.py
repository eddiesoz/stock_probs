"""Verify application wiring and fail-closed notification email controls."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import fastapi.staticfiles
import pytest
from fastapi.staticfiles import StaticFiles
from fastapi.testclient import TestClient
from starlette.routing import Mount

import stock_probs.api as api_module
from stock_probs.api import create_app
from stock_probs.auth import SESSION_COOKIE_NAME, AuthContext
from stock_probs.config import Settings
from stock_probs.invitation_mail import InvitationMailSettings
from stock_probs.monitoring_scheduler import MonitoringScheduler
from stock_probs.monitoring_store import MonitoringStore
from stock_probs.notification_delivery import MAX_NOTIFICATION_BATCH
from stock_probs.provider import FixtureProvider
from stock_probs.repository import Repository
from stock_probs.totp import code_for_step, time_step

NOW = datetime(2026, 10, 14, 12, 0, tzinfo=UTC)
_ADMIN_PASSWORD = "notification-test-admin-password"  # noqa: S105
_MEMBER_PASSWORD = "notification-test-member-password"  # noqa: S105


class NoNetworkTransport:
    """Make any accidental SMTP preparation fail locally before opening a socket."""

    def prepare(self, *_args, **_kwargs):
        raise AssertionError("application integration tests must not contact SMTP")


@pytest.fixture(autouse=True)
def forbid_network_mail_transport(monkeypatch):
    import stock_probs.notification_delivery as delivery_module
    import stock_probs.notification_verification as verification_module

    monkeypatch.setattr(delivery_module, "SMTPNotificationTransport", NoNetworkTransport)
    monkeypatch.setattr(verification_module, "SMTPNotificationTransport", NoNetworkTransport)


@pytest.fixture
def settings(tmp_path) -> Settings:
    """Provide an isolated application database without relying on shared conftest imports."""

    return Settings(
        data_dir=tmp_path,
        database_path=tmp_path / "stock_probs.sqlite3",
        backup_dir=tmp_path / "backups",
        provider="fixture",
    )


class InertRuntime:
    """Expose lifecycle readiness without starting a background thread."""

    def __init__(self) -> None:
        self.running = False

    async def start(self) -> None:
        self.running = True

    async def close(self) -> None:
        self.running = False

    def status(self) -> dict[str, bool]:
        return {"running": self.running}


def _mail_settings() -> InvitationMailSettings:
    return InvitationMailSettings(
        host="smtp.example.invalid",
        port=465,
        username="fixture-user",
        password="fixture-password",  # noqa: S106
        security="implicit_tls",
        from_address="alerts@example.invalid",
    )


def _local_settings(
    settings: Settings,
    *,
    email_enabled: bool = False,
    with_mail: bool = False,
    scheduler_enabled: bool = False,
) -> Settings:
    return replace(
        settings,
        auth_mode="local",
        auth_session_secret="notification-test-session-secret",  # noqa: S106
        auth_public_origin="http://testserver",
        monitoring_features_enabled=True,
        monitoring_features_canary_only=False,
        monitoring_scheduler_enabled=scheduler_enabled,
        monitoring_email_enabled=email_enabled,
        invitation_mail=_mail_settings() if with_mail else None,
        bootstrap_username="notification-admin",
        bootstrap_password=_ADMIN_PASSWORD,
        bootstrap_member_username="notification-member",
        bootstrap_member_password=_MEMBER_PASSWORD,
    )


def _login(client: TestClient, username: str = "notification-admin") -> tuple[int, str]:
    password = _MEMBER_PASSWORD if username == "notification-member" else _ADMIN_PASSWORD
    response = client.post(
        "/api/v1/auth/local/login", json={"username": username, "password": password}
    )
    assert response.status_code == 200, response.text
    body = response.json()
    return body["user"]["id"], body["csrf_token"]


def _authenticate_admin_with_fresh_step_up(
    client: TestClient, application
) -> tuple[AuthContext, str, datetime]:
    """Enroll the fixture admin through HTTP and return its active TOTP-backed session."""

    user_id, csrf = _login(client)
    headers = {"x-csrf-token": csrf}
    started = client.post("/api/v1/auth/totp/enroll/start", headers=headers)
    assert started.status_code == 200, started.text
    finished = client.post(
        "/api/v1/auth/totp/enroll/finish",
        json={"code": code_for_step(started.json()["secret"], time_step(datetime.now(UTC)))},
        headers=headers,
    )
    assert finished.status_code == 200, finished.text

    session_token = client.cookies.get(SESSION_COOKIE_NAME)
    assert isinstance(session_token, str)
    csrf = finished.json()["csrf_token"]
    auth_now = datetime.now(UTC)
    context = application.state.auth.authenticate(session_token, auth_now)
    assert context.user.id == user_id
    assert context.user.role == "admin"
    assert context.mfa_method == "totp"
    assert application.state.auth.has_recent_step_up(context, auth_now)
    return context, csrf, auth_now


def _insert_verified_address(application, owner_id: int, address: str) -> str:
    identifier = str(uuid4())
    with application.state.repository.connect() as connection:
        connection.execute(
            "INSERT INTO notification_addresses(id,owner_user_id,address,verified_at,created_at) "
            "VALUES (?,?,?,?,?)",
            (identifier, owner_id, address, NOW.isoformat(), NOW.isoformat()),
        )
        connection.commit()
    return identifier


def test_email_setting_is_explicit_and_default_off(monkeypatch, tmp_path, settings):
    names = (
        "STOCK_PROBS_MONITORING_FEATURES_ENABLED",
        "STOCK_PROBS_MONITORING_SCHEDULER_ENABLED",
        "STOCK_PROBS_MONITORING_EMAIL_ENABLED",
        "STOCK_PROBS_INVITE_SMTP_HOST",
        "STOCK_PROBS_INVITE_SMTP_PORT",
        "STOCK_PROBS_INVITE_SMTP_USERNAME",
        "STOCK_PROBS_INVITE_SMTP_PASSWORD",
        "STOCK_PROBS_INVITE_SMTP_SECURITY",
        "STOCK_PROBS_INVITE_EMAIL_FROM",
    )
    for name in names:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("STOCK_PROBS_ENV", "test")
    monkeypatch.setenv("STOCK_PROBS_AUTH_MODE", "disabled")
    monkeypatch.setenv("STOCK_PROBS_PROVIDER", "fixture")
    monkeypatch.setenv("STOCK_PROBS_DATA_DIR", str(tmp_path))

    defaults = Settings.from_env()
    assert defaults.monitoring_email_enabled is False
    assert defaults.monitoring_email_transport_available is False
    assert defaults.monitoring_email_delivery_configured is False

    monkeypatch.setenv("STOCK_PROBS_MONITORING_EMAIL_ENABLED", "yes")
    assert Settings.from_env().monitoring_email_enabled is True
    monkeypatch.setenv("STOCK_PROBS_MONITORING_EMAIL_ENABLED", "maybe")
    with pytest.raises(ValueError, match="must be true or false"):
        Settings.from_env()

    app = create_app(
        replace(settings, monitoring_features_enabled=True, monitoring_scheduler_enabled=False),
        FixtureProvider(),
        lambda: NOW,
    )
    assert app.state.monitoring is None
    assert app.state.notification_verification is None
    assert app.state.notification_delivery is None


def test_transport_missing_reports_unavailable_but_allows_explicit_opt_out(settings):
    runtime = InertRuntime()
    config = _local_settings(settings, email_enabled=True, scheduler_enabled=True)
    application = create_app(config, FixtureProvider(), lambda: NOW, monitoring_runtime=runtime)
    with TestClient(application) as client:
        admin_context, csrf, auth_now = _authenticate_admin_with_fresh_step_up(client, application)
        application.state.monitoring_store.set_control(
            1, True, auth_now, auth_context=admin_context
        )

        features = client.get("/api/v1/monitoring/features")
        assert features.status_code == 200
        assert features.json()["email_available"] is False

        request = client.post(
            "/api/v1/notification-address-verifications",
            json={"address": "owner@example.invalid"},
            headers={"Idempotency-Key": str(uuid4()), "x-csrf-token": csrf},
        )
        assert request.status_code == 503
        assert request.json()["error"]["code"] == "EMAIL_VERIFICATION_UNAVAILABLE"

        enabled = client.put(
            "/api/v1/notification-preferences",
            json={"expected_revision": 0, "alert_email": True, "digest_email": False},
            headers={"x-csrf-token": csrf},
        )
        assert enabled.status_code == 503
        assert enabled.json()["error"]["code"] == "ALERT_EMAIL_UNAVAILABLE"

        digest = client.put(
            "/api/v1/notification-preferences",
            json={"expected_revision": 0, "alert_email": False, "digest_email": True},
            headers={"x-csrf-token": csrf},
        )
        assert digest.status_code == 422
        assert digest.json()["error"]["code"] == "DIGEST_EMAIL_UNAVAILABLE"

        disabled = client.put(
            "/api/v1/notification-preferences",
            json={"expected_revision": 0, "alert_email": False, "digest_email": False},
            headers={"x-csrf-token": csrf},
        )
        assert disabled.status_code == 200, disabled.text
        assert disabled.json()["alert_email"] is False
        assert disabled.json()["digest_email"] is False


def test_address_routes_bind_session_owner_csrf_and_selection_resets_opt_in(settings):
    config = _local_settings(settings)
    application = create_app(config, FixtureProvider(), lambda: NOW)
    with TestClient(application) as client:
        admin_context, _admin_csrf, auth_now = _authenticate_admin_with_fresh_step_up(
            client, application
        )
        admin_id = admin_context.user.id
        member_id, member_csrf = _login(client, "notification-member")
        application.state.monitoring_store.set_control(
            1, True, auth_now, auth_context=admin_context
        )
        admin_address = _insert_verified_address(application, admin_id, "admin@example.invalid")
        member_address = _insert_verified_address(application, member_id, "member@example.invalid")

        member_list = client.get("/api/v1/notification-addresses")
        assert member_list.status_code == 200
        assert [item["id"] for item in member_list.json()["items"]] == [member_address]
        assert "admin@example.invalid" not in member_list.text
        foreign_selection = client.post(
            "/api/v1/notification-addresses/select",
            json={"address_id": admin_address, "expected_revision": 0},
            headers={"x-csrf-token": member_csrf},
        )
        assert foreign_selection.status_code == 404

        admin_id, admin_csrf = _login(client)
        assert admin_id != member_id
        current = application.state.monitoring_store.get_notification_preferences(admin_id)
        application.state.monitoring_store.set_notification_preferences(
            admin_id,
            current["revision"],
            alert_email=True,
            digest_email=False,
            address_id=admin_address,
            now=NOW,
            auth_context=admin_context,
        )
        no_csrf = client.post(
            "/api/v1/notification-addresses/select",
            json={"address_id": admin_address, "expected_revision": 1},
        )
        assert no_csrf.status_code == 403
        selected = client.post(
            "/api/v1/notification-addresses/select",
            json={"address_id": admin_address, "expected_revision": 1},
            headers={"x-csrf-token": admin_csrf},
        )
        assert selected.status_code == 200, selected.text
        preferences = client.get("/api/v1/notification-preferences")
        assert preferences.status_code == 200
        assert preferences.json()["address_configured"] is True
        assert preferences.json()["alert_email"] is False
        assert preferences.json()["digest_email"] is False


def test_address_routes_obey_admin_canary(settings):
    config = replace(_local_settings(settings), monitoring_features_canary_only=True)
    application = create_app(config, FixtureProvider(), lambda: NOW)
    with TestClient(application) as client:
        _login(client, "notification-member")
        assert client.get("/api/v1/notification-addresses").status_code == 403
        _login(client)
        assert client.get("/api/v1/notification-addresses").status_code == 200


def test_full_configuration_is_inert_until_normal_lifespan_and_control_allow_delivery(settings):
    config = _local_settings(settings, email_enabled=True, with_mail=True, scheduler_enabled=True)
    assert config.monitoring_email_transport_available is True
    assert config.monitoring_email_delivery_configured is True
    application = create_app(config, FixtureProvider(), lambda: NOW)
    api_source = Path(api_module.__file__).resolve()
    assert api_source == Path(__file__).resolve().parents[1] / "src/stock_probs/api.py"
    assert api_module.StaticFiles is StaticFiles
    assert api_module.StaticFiles is fastapi.staticfiles.StaticFiles
    next_mounts = [
        route for route in application.routes if isinstance(route, Mount) and route.path == "/_next"
    ]
    assert len(next_mounts) == 1
    assert type(next_mounts[0].app) is StaticFiles
    staged_next = api_source.parent / "static" / "next" / "_next"
    assert Path(next_mounts[0].app.directory).resolve() == staged_next.resolve()
    assert staged_next.is_dir()
    runtime = application.state.monitoring
    assert isinstance(runtime, MonitoringScheduler)
    assert runtime.notification_delivery is application.state.notification_delivery
    assert runtime.notification_delivery is not None
    assert application.state.notification_verification is not None
    assert runtime.status() == {"running": False}

    disabled_scheduler = create_app(
        replace(config, monitoring_scheduler_enabled=False), FixtureProvider(), lambda: NOW
    )
    assert disabled_scheduler.state.monitoring is None
    assert disabled_scheduler.state.notification_delivery is None

    email_disabled = create_app(
        replace(config, monitoring_email_enabled=False), FixtureProvider(), lambda: NOW
    )
    assert isinstance(email_disabled.state.monitoring, MonitoringScheduler)
    assert email_disabled.state.monitoring.notification_delivery is None
    assert email_disabled.state.notification_delivery is None

    with TestClient(application) as client:
        admin_context, csrf, auth_now = _authenticate_admin_with_fresh_step_up(client, application)
        owner_id = admin_context.user.id
        staged_asset = client.get("/_next/static/chunks/09d8-9zfon09i.css")
        assert staged_asset.status_code == 200
        assert staged_asset.headers["content-type"].startswith("text/css")
        assert staged_asset.content
        assert client.get("/api/v1/monitoring/features").json()["email_available"] is False
        application.state.monitoring_store.set_control(
            1, True, auth_now, auth_context=admin_context
        )
        assert client.get("/api/v1/monitoring/features").json()["email_available"] is True
        address_id = _insert_verified_address(application, owner_id, "owner@example.invalid")
        selected = client.post(
            "/api/v1/notification-addresses/select",
            json={"address_id": address_id, "expected_revision": 0},
            headers={"x-csrf-token": csrf},
        )
        assert selected.status_code == 200, selected.text
        enabled = client.put(
            "/api/v1/notification-preferences",
            json={"expected_revision": 1, "alert_email": True, "digest_email": False},
            headers={"x-csrf-token": csrf},
        )
        assert enabled.status_code == 200, enabled.text
        assert enabled.json()["alert_email"] is True
        assert enabled.json()["address_configured"] is True
        disabled = client.put(
            "/api/v1/notification-preferences",
            json={"expected_revision": 2, "alert_email": False, "digest_email": False},
            headers={"x-csrf-token": csrf},
        )
        assert disabled.status_code == 200, disabled.text
        assert disabled.json()["alert_email"] is False
    assert runtime.status() == {"running": False}


class DeliveryProbe:
    """Capture scheduler handoff and prove the global kill is reread by its callback."""

    def __init__(self, store: MonitoringStore) -> None:
        self.store = store
        self.calls = 0
        self.cancelled_during_run: list[bool] = []

    def run_due(self, worker_id, now, *, limit, lease_seconds, cancelled):
        self.calls += 1
        assert limit == MAX_NOTIFICATION_BATCH == 4
        assert lease_seconds == 30
        assert isinstance(worker_id, str) and now == NOW
        self.cancelled_during_run.append(cancelled())
        control = self.store.get_control()
        self.store.set_control(control["revision"], False, NOW + timedelta(seconds=1))
        self.cancelled_during_run.append(cancelled())
        return object()


class BrokenDelivery:
    """Simulate transport failure without invoking a real SMTP client."""

    def run_due(self, *_args, **_kwargs):
        raise RuntimeError("synthetic delivery failure")


def test_scheduler_serial_delivery_handoff_observes_live_kill_and_stop(settings):
    repository = Repository(settings.database_path)
    repository.migrate()
    store = MonitoringStore(repository, write_authorization_mode="test_no_auth")
    store.set_control(1, True, NOW)
    delivery = DeliveryProbe(store)
    runtime = MonitoringScheduler(
        store,
        FixtureProvider(),
        notification_delivery=delivery,
        clock=lambda: NOW,
    )
    assert runtime.status() == {"running": False}
    assert runtime.run_once() == 0
    assert delivery.calls == 1
    assert delivery.cancelled_during_run == [False, True]

    control = store.get_control()
    store.set_control(control["revision"], True, NOW + timedelta(seconds=2))
    asyncio.run(runtime.close())
    assert runtime.run_once() == 0
    assert delivery.calls == 1


def test_scheduler_email_failure_does_not_fail_local_monitoring_iteration(settings):
    repository = Repository(settings.database_path)
    repository.migrate()
    store = MonitoringStore(repository, write_authorization_mode="test_no_auth")
    store.set_control(1, True, NOW)
    runtime = MonitoringScheduler(
        store,
        FixtureProvider(),
        notification_delivery=BrokenDelivery(),
        clock=lambda: NOW,
    )
    assert runtime.run_once() == 0
