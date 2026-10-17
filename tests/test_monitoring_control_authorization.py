"""Exercise monitoring-control authorization after the bounded body is received."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from _auth_body_barrier import request_with_body_barrier
from fastapi import FastAPI
from fastapi.testclient import TestClient

from stock_probs.api import create_app
from stock_probs.auth import SESSION_COOKIE_NAME, AuthContext
from stock_probs.config import Settings
from stock_probs.provider import FixtureProvider
from stock_probs.totp import code_for_step, time_step

_CONTROL_PATH = "/api/v1/admin/monitoring/control"
_LOCAL_PASSWORD = "r3-development-admin-password"  # noqa: S105


def _authenticate_admin_with_totp(
    client: TestClient, application: FastAPI
) -> tuple[str, str, AuthContext]:
    """Create a disposable admin session and prove TOTP through the real HTTP routes."""

    login = client.post(
        "/api/v1/auth/local/login",
        json={"username": "admin", "password": _LOCAL_PASSWORD},
    )
    assert login.status_code == 200, login.text
    csrf_token = login.json()["csrf_token"]
    headers = {"x-csrf-token": csrf_token}

    started = client.post("/api/v1/auth/totp/enroll/start", headers=headers)
    assert started.status_code == 200, started.text
    secret = started.json()["secret"]
    finished = client.post(
        "/api/v1/auth/totp/enroll/finish",
        json={"code": code_for_step(secret, time_step())},
        headers=headers,
    )
    assert finished.status_code == 200, finished.text
    csrf_token = finished.json()["csrf_token"]
    session_token = client.cookies.get(SESSION_COOKIE_NAME)
    assert isinstance(session_token, str)

    now = datetime.now(UTC)
    context = application.state.auth.authenticate(session_token, now)
    assert context.user.role == "admin"
    assert context.mfa_method == "totp"
    assert application.state.auth.has_recent_step_up(context, now)
    return session_token, csrf_token, context


@pytest.mark.parametrize(
    ("scenario", "expected_status"),
    [
        ("live", 200),
        ("session-revoked", 401),
        ("role-demoted", 403),
        ("account-disabled", 401),
        ("step-up-expired", 403),
    ],
)
def test_monitoring_control_revalidates_after_body_read(
    settings: Settings, scenario: str, expected_status: int
) -> None:
    """Current session, account, role, and TOTP state govern the final mutation."""

    configured = replace(
        settings,
        auth_mode="local",
        auth_session_secret="r" * 48,
        auth_public_origin="http://testserver",
        bootstrap_username="admin",
        bootstrap_password=_LOCAL_PASSWORD,
    )
    application = create_app(configured, FixtureProvider(), lambda: datetime.now(UTC))
    with TestClient(application) as client:
        session_token, csrf_token, context = _authenticate_admin_with_totp(client, application)
        control_before = application.state.monitoring_store.get_control()
        revision = int(control_before["revision"])
        enabled = not bool(control_before["enabled"])
        auth_manager = application.state.auth

        def change_state_after_initial_auth() -> None:
            """Apply one durable authorization change while the final body chunk is held."""

            now = datetime.now(UTC)
            if scenario == "session-revoked":
                auth_manager.store.auth_revoke_session_by_id(
                    context.user.id, context.session_id, now.isoformat()
                )
            elif scenario == "role-demoted":
                assert (
                    auth_manager.store.auth_update_user(context.user.id, {"role": "member"})
                    is not None
                )
            elif scenario == "account-disabled":
                assert (
                    auth_manager.store.auth_update_user(context.user.id, {"status": "disabled"})
                    is not None
                )
            elif scenario == "step-up-expired":
                assert context.mfa_factor_id is not None
                expired_at = now - timedelta(seconds=301)
                assert auth_manager.store.auth_set_session_mfa(
                    context.token_hash,
                    "totp",
                    expired_at.isoformat(),
                    context.mfa_factor_id,
                )

        status, _body = asyncio.run(
            request_with_body_barrier(
                application,
                session_token,
                csrf_token,
                method="PUT",
                path=_CONTROL_PATH,
                body=(
                    f'{{"expected_revision":{revision},"enabled":{"true" if enabled else "false"}}}'
                ).encode("ascii"),
                on_body_paused=change_state_after_initial_auth,
            )
        )

        assert status == expected_status
        control_after = application.state.monitoring_store.get_control()
        if scenario == "live":
            assert control_after["revision"] == revision + 1
            assert control_after["enabled"] is enabled
        else:
            assert control_after == control_before


@pytest.mark.parametrize("mutation", ["alert", "preferences", "address"])
def test_user_mutation_rejects_session_revoked_during_body_read(
    settings: Settings, mutation: str
) -> None:
    """Cached middleware identity is checked again inside each user mutation transaction."""

    configured = replace(
        settings,
        auth_mode="local",
        auth_session_secret="r" * 48,
        auth_public_origin="http://testserver",
        bootstrap_username="admin",
        bootstrap_password=_LOCAL_PASSWORD,
        monitoring_features_enabled=True,
    )
    application = create_app(configured, FixtureProvider(), lambda: datetime.now(UTC))
    with TestClient(application) as client:
        session_token, csrf_token, context = _authenticate_admin_with_totp(client, application)
        store = application.state.monitoring_store
        now = datetime.now(UTC)

        if mutation == "alert":
            alert = store.create_alert(
                context.user.id,
                str(uuid4()),
                {
                    "symbol": "SPY",
                    "currency": "USD",
                    "threshold": "100",
                    "direction": "above",
                    "repeating": True,
                },
                now,
                allow_new_creation=True,
                auth_context=context,
            )
            before = store.get_alert(context.user.id, alert["id"])
            request_method = "POST"
            request_path = f"/api/v1/alerts/{alert['id']}/pause"
            request_body = f'{{"expected_revision":{alert["revision"]}}}'.encode("ascii")
        elif mutation == "preferences":
            before = store.get_notification_preferences(context.user.id)
            request_method = "PUT"
            request_path = "/api/v1/notification-preferences"
            request_body = (
                f'{{"expected_revision":{before["revision"]},'
                '"alert_email":false,"digest_email":false}'
            ).encode("ascii")
        else:
            address_id = str(uuid4())
            with application.state.repository.connect() as connection:
                connection.execute(
                    "INSERT INTO notification_addresses"
                    "(id,owner_user_id,address,verified_at,created_at) VALUES (?,?,?,?,?)",
                    (
                        address_id,
                        context.user.id,
                        "verified@example.test",
                        now.isoformat(),
                        now.isoformat(),
                    ),
                )
                connection.commit()
            before = store.get_notification_preferences(context.user.id)
            request_method = "POST"
            request_path = "/api/v1/notification-addresses/select"
            request_body = (
                f'{{"address_id":"{address_id}","expected_revision":{before["revision"]}}}'
            ).encode("ascii")

        def revoke_session() -> None:
            application.state.auth.store.auth_revoke_session_by_id(
                context.user.id, context.session_id, datetime.now(UTC).isoformat()
            )

        status, body = asyncio.run(
            request_with_body_barrier(
                application,
                session_token,
                csrf_token,
                method=request_method,
                path=request_path,
                body=request_body,
                on_body_paused=revoke_session,
            )
        )

        assert status == 401, body
        if mutation == "alert":
            assert store.get_alert(context.user.id, alert["id"]) == before
        else:
            assert store.get_notification_preferences(context.user.id) == before


def test_monitoring_control_rejects_revocation_between_reauth_and_write(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The final authorization check and control write must share one SQLite transaction."""

    configured = replace(
        settings,
        auth_mode="local",
        auth_session_secret="r" * 48,
        auth_public_origin="http://testserver",
        bootstrap_username="admin",
        bootstrap_password=_LOCAL_PASSWORD,
    )
    application = create_app(configured, FixtureProvider(), lambda: datetime.now(UTC))
    with TestClient(application) as client:
        session_token, csrf_token, context = _authenticate_admin_with_totp(client, application)
        store = application.state.monitoring_store
        control_before = store.get_control()
        auth_manager = application.state.auth
        original_set_control = store.set_control

        def revoke_after_reauthentication(
            expected_revision: int,
            enabled: bool,
            now: datetime,
            **kwargs: object,
        ) -> dict[str, object]:
            """Place a session revocation after route reauth but before the store's write."""

            auth_manager.store.auth_revoke_session_by_id(
                context.user.id, context.session_id, datetime.now(UTC).isoformat()
            )
            return original_set_control(expected_revision, enabled, now, **kwargs)

        monkeypatch.setattr(store, "set_control", revoke_after_reauthentication)
        status, _body = asyncio.run(
            request_with_body_barrier(
                application,
                session_token,
                csrf_token,
                method="PUT",
                path=_CONTROL_PATH,
                body=(
                    f'{{"expected_revision":{control_before["revision"]},'
                    f'"enabled":{str(not bool(control_before["enabled"])).lower()}}}'
                ).encode("ascii"),
                on_body_paused=lambda: None,
            )
        )

        assert status == 401
        assert store.get_control() == control_before
