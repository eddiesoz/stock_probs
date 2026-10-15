"""Real-app binding for the owner-authenticated, disabled-by-default briefing mount."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from fastapi.testclient import TestClient

from stock_probs.api import WORKSPACE_PAGE_ROUTES, create_app
from stock_probs.auth import SESSION_COOKIE_NAME
from stock_probs.config import Settings
from stock_probs.provider import FixtureProvider

NOW = datetime(2026, 10, 15, 12, tzinfo=UTC)
_ADMIN_PASSWORD = "briefing-fixture-admin-password"  # noqa: S105
_MEMBER_PASSWORD = "briefing-fixture-member-password"  # noqa: S105


def _settings(settings: Settings, **overrides: Any) -> Settings:
    base = replace(
        settings,
        auth_mode="local",
        auth_session_secret="briefing-fixture-session-secret-with-sufficient-length",  # noqa: S106
        auth_public_origin="http://testserver",
        bootstrap_username="briefing-admin",
        bootstrap_password=_ADMIN_PASSWORD,
        bootstrap_member_username="briefing-member",
        bootstrap_member_password=_MEMBER_PASSWORD,
    )
    return replace(base, **overrides)


def _login(client: TestClient, username: str, password: str) -> str:
    response = client.post(
        "/api/v1/auth/local/login", json={"username": username, "password": password}
    )
    assert response.status_code == 200, response.text
    session = client.cookies.get(SESSION_COOKIE_NAME)
    csrf = response.json()["csrf_token"]
    assert isinstance(session, str) and isinstance(csrf, str)
    return csrf


def test_mount_is_authenticated_and_disabled_by_default(settings: Settings) -> None:
    assert settings.briefing_features_enabled is False
    assert settings.briefing_features_canary_only is True

    disabled_auth_application = create_app(settings, FixtureProvider(), lambda: NOW)
    with TestClient(disabled_auth_application) as disabled_auth_client:
        legacy_fallback = disabled_auth_client.get("/api/v1/briefing-state")

    application = create_app(_settings(settings), FixtureProvider(), lambda: NOW)
    with TestClient(application) as client:
        unauthenticated = client.get("/api/v1/briefing-state")
        _login(client, "briefing-admin", _ADMIN_PASSWORD)
        disabled_state = client.get("/api/v1/briefing-state")
        disabled_page = client.get("/api/v1/briefings")

    assert legacy_fallback.status_code == 401
    assert unauthenticated.status_code == 401
    assert disabled_state.status_code == 200
    assert disabled_state.json()["features"]["enabled"] is False
    assert disabled_page.status_code == 503


def test_admin_canary_and_csrf_gate_real_router_before_local_source_reads(
    settings: Settings,
) -> None:
    protected = _settings(
        settings,
        briefing_features_enabled=True,
        briefing_features_canary_only=True,
    )
    admin_application = create_app(protected, FixtureProvider(), lambda: NOW)
    with TestClient(admin_application) as admin_client:
        # This named browser path is authenticated and included in the safe top-level-navigation
        # exception. The approved R3 stage lacks this R4 export, so the post-auth page is 404.
        assert "/overview/what-changed" in WORKSPACE_PAGE_ROUTES
        cross_site_navigation = admin_client.get(
            "/overview/what-changed",
            headers={
                "sec-fetch-site": "cross-site",
                "sec-fetch-mode": "navigate",
                "sec-fetch-dest": "document",
            },
            follow_redirects=False,
        )
        admin_csrf = _login(admin_client, "briefing-admin", _ADMIN_PASSWORD)
        unavailable_page = admin_client.get("/overview/what-changed")
        admin_state = admin_client.get("/api/v1/briefing-state")
        key = str(uuid4())
        body = {
            "window": "last_24_hours",
            "observed_as_of": NOW.isoformat().replace("+00:00", "Z"),
        }
        missing_csrf = admin_client.post(
            "/api/v1/briefings",
            headers={"Idempotency-Key": key},
            json=body,
        )
        created = admin_client.post(
            "/api/v1/briefings",
            headers={"Idempotency-Key": key, "x-csrf-token": admin_csrf},
            json=body,
        )

    member_application = create_app(protected, FixtureProvider(), lambda: NOW)
    with TestClient(member_application) as member_client:
        _login(member_client, "briefing-member", _MEMBER_PASSWORD)
        member_state = member_client.get("/api/v1/briefing-state")
        member_snapshots = member_client.get("/api/v1/briefings")

    assert cross_site_navigation.status_code == 303
    assert cross_site_navigation.headers["location"].startswith("/sign-in?next=")
    assert unavailable_page.status_code == 404
    assert admin_state.status_code == 200 and admin_state.json()["features"]["enabled"] is True
    assert member_state.status_code == 200 and member_state.json()["features"]["enabled"] is False
    assert member_snapshots.status_code == 503
    # _auth_context also validates CSRF when the authenticated owner callback runs first, so the
    # missing token is rejected at that earlier guard with its stable auth-required envelope.
    assert missing_csrf.status_code == 401, missing_csrf.text
    assert missing_csrf.json()["error"]["code"] == "authentication_required"
    assert created.status_code == 201, created.text


def test_briefing_history_is_owner_scoped_when_canary_is_disabled(settings: Settings) -> None:
    protected = _settings(
        settings,
        briefing_features_enabled=True,
        briefing_features_canary_only=False,
    )
    admin_application = create_app(protected, FixtureProvider(), lambda: NOW)
    with TestClient(admin_application) as admin_client:
        admin_csrf = _login(admin_client, "briefing-admin", _ADMIN_PASSWORD)
        created = admin_client.post(
            "/api/v1/briefings",
            headers={"Idempotency-Key": str(uuid4()), "x-csrf-token": admin_csrf},
            json={
                "window": "last_24_hours",
                "observed_as_of": NOW.isoformat().replace("+00:00", "Z"),
            },
        )
        admin_list = admin_client.get("/api/v1/briefings")

    member_application = create_app(protected, FixtureProvider(), lambda: NOW)
    with TestClient(member_application) as member_client:
        _login(member_client, "briefing-member", _MEMBER_PASSWORD)
        member_list = member_client.get("/api/v1/briefings")
        foreign_snapshot = member_client.get(f"/api/v1/briefings/{created.json()['id']}")

    assert created.status_code == 201, created.text
    assert member_list.status_code == 200 and member_list.json()["items"] == []
    assert foreign_snapshot.status_code == 404
    assert len(admin_list.json()["items"]) == 1
