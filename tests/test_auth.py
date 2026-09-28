"""Focused authentication tests for the local and server-side auth boundary."""

from __future__ import annotations

import base64
import hashlib
import json
import threading
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from fastapi.testclient import TestClient

from stock_probs.api import _RestoreRequestGate, create_app
from stock_probs.auth import (
    CSRF_COOKIE_NAME,
    OAUTH_TRANSACTION_COOKIE_NAME,
    SESSION_COOKIE_NAME,
    AuthenticationRequired,
    AuthManager,
    AuthSettings,
    AuthUnavailable,
    CsrfRejected,
    InvitationRejected,
    MemoryAuthStore,
    OAuthRejected,
    PasskeyCredential,
    PasskeyRejected,
    UserRecord,
    hash_password,
    verify_password,
)
from stock_probs.config import Settings
from stock_probs.provider import FixtureProvider

NOW = datetime(2025, 1, 10, 17, 3, tzinfo=UTC)


class _FakePasskeyBackend:
    """Exercise the server challenge boundary without inventing browser signatures."""

    def verify_registration(self, response, challenge, user_id, rp_id, origin):
        assert isinstance(response["response"]["clientDataJSON"], str)
        return PasskeyCredential(
            "credential-id-123456",
            user_id,
            "public-key-material-123456",
            0,
            (),
        )

    def verify_assertion(self, response, challenge, credential, rp_id, origin):
        assert isinstance(response["response"]["clientDataJSON"], str)
        return credential.sign_count + 1


def _encoded_client_data(challenge: str) -> str:
    raw = json.dumps({"type": "webauthn.get", "challenge": challenge}).encode()
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _manager(store: MemoryAuthStore | None = None) -> tuple[AuthManager, MemoryAuthStore]:
    selected = store or MemoryAuthStore()
    manager = AuthManager(
        selected,
        AuthSettings(
            mode="local",
            session_secret="a" * 48,
            public_origin="http://testserver",
        ),
    )
    return manager, selected


def test_password_hash_is_salted_and_rejects_malformed_values() -> None:
    encoded = hash_password("development-password-123")
    assert encoded != hash_password("development-password-123")
    assert verify_password("development-password-123", encoded)
    assert not verify_password("wrong-password-123", encoded)
    assert not verify_password("development-password-123", "scrypt$bad")


def test_local_session_is_opaque_csrf_bound_and_revocable() -> None:
    manager, store = _manager()
    manager.ensure_local_bootstrap("admin", "development-password-123", NOW)
    issue = manager.local_login("ADMIN", "development-password-123", NOW)
    assert issue.session_token not in str(store.sessions)
    context = manager.authenticate(issue.session_token, NOW + timedelta(seconds=1))
    manager.require_csrf(context, issue.csrf_token)
    with pytest.raises(CsrfRejected):
        manager.require_csrf(context, "wrong-csrf-token")
    manager.logout(context, NOW + timedelta(seconds=2))
    with pytest.raises(AuthenticationRequired):
        manager.authenticate(issue.session_token, NOW + timedelta(seconds=3))


def test_invitation_is_single_use() -> None:
    store = MemoryAuthStore()
    manager = AuthManager(
        store,
        AuthSettings(
            mode="github",
            session_secret="b" * 48,
            public_origin="https://ledger.example",
            github_client_id="client",
            github_client_secret="secret",  # noqa: S106
            github_redirect_uri="https://ledger.example/api/v1/auth/github/callback",
        ),
        # The OAuth test only exercises invitation persistence and does not contact GitHub.
        passkey_backend=None,
    )
    store.auth_create_user(
        {
            "username": "owner",
            "role": "admin",
            "status": "active",
            "password_hash": None,
        }
    )
    code, _ = manager.create_invitation(123, 1, NOW)
    consumed = manager.consume_invitation(code, NOW + timedelta(seconds=1))
    assert consumed["github_id"] == 123
    with pytest.raises(InvitationRejected):
        manager.consume_invitation(code, NOW + timedelta(seconds=2))


def test_local_api_requires_cookie_and_accepts_valid_credentials(tmp_path) -> None:
    settings = Settings(
        data_dir=tmp_path,
        database_path=tmp_path / "stock_probs.sqlite3",
        backup_dir=tmp_path / "backups",
        provider="fixture",
        auth_mode="local",
        auth_session_secret="c" * 48,
        auth_public_origin="http://testserver",
        bootstrap_username="admin",
        bootstrap_password="development-password-123",  # noqa: S106
    )
    store = MemoryAuthStore()
    app = create_app(settings, FixtureProvider(), lambda: NOW, auth_store=store)
    with TestClient(app) as client:
        assert client.get("/api/v1/auth/status").status_code == 200
        assert client.get("/api/v1/forecasts", follow_redirects=False).status_code in {
            401,
            403,
            405,
        }
        assert client.get("/", follow_redirects=False).status_code == 303
        assert client.head("/sign-in").status_code == 200
        login = client.post(
            "/api/v1/auth/local/login",
            json={"username": "admin", "password": "development-password-123"},
        )
        assert login.status_code == 200, login.text
        assert login.json()["authenticated"] is True
        assert client.get("/api/v1/auth/session").json()["authenticated"] is True
        logout = client.post(
            "/api/v1/auth/logout",
            headers={"x-csrf-token": login.json()["csrf_token"]},
        )
        assert logout.status_code == 204, logout.text
        assert "Max-Age=0" in logout.headers.get("set-cookie", "")
        assert client.get("/api/v1/auth/session").json()["authenticated"] is False


@pytest.mark.parametrize(
    "malformed_host",
    ["testserver/sign-in#", "testserver?path=/sign-in", "testserver#sign-in", "testserver:bad"],
)
def test_host_cannot_rewrite_the_path_used_by_authentication(tmp_path, malformed_host) -> None:
    """Reject Host URL syntax before Starlette can poison request.url.path."""

    settings = Settings(
        data_dir=tmp_path,
        database_path=tmp_path / "stock_probs.sqlite3",
        backup_dir=tmp_path / "backups",
        provider="fixture",
        auth_mode="local",
        auth_session_secret="c" * 48,
        auth_public_origin="http://testserver",
        bootstrap_username="admin",
        bootstrap_password="development-password-123",  # noqa: S106
    )
    app = create_app(settings, FixtureProvider(), lambda: NOW, auth_store=MemoryAuthStore())
    with TestClient(app) as client:
        protected = client.get("/api/v1/quotes", headers={"host": "testserver"})
        assert protected.status_code == 401
        rejected = client.get("/api/v1/quotes", headers={"host": malformed_host})
        assert rejected.status_code == 400
        assert rejected.json()["error"]["code"] == "host_rejected"


def test_production_host_requires_the_configured_public_authority(tmp_path) -> None:
    settings = Settings(
        data_dir=tmp_path,
        database_path=tmp_path / "stock_probs.sqlite3",
        backup_dir=tmp_path / "backups",
        provider="fixture",
        environment="production",
        auth_mode="github",
        auth_session_secret="s" * 48,
        auth_public_origin="https://ledger.example",
        auth_cookie_secure=True,
        github_client_id="client",
        github_client_secret="secret",  # noqa: S106
        github_redirect_uri="https://ledger.example/api/v1/auth/github/callback",
        owner_github_id=123,
    )
    app = create_app(settings, FixtureProvider(), lambda: NOW, auth_store=MemoryAuthStore())
    with TestClient(app) as client:
        assert client.get("/api/v1/health", headers={"host": "ledger.example"}).status_code == 200
        unexpected_port = client.get("/api/v1/health", headers={"host": "ledger.example:8443"})
        assert unexpected_port.status_code == 400
        assert unexpected_port.json()["error"]["code"] == "host_rejected"


def test_production_rejects_local_auth_and_development_secret(tmp_path) -> None:
    with pytest.raises(ValueError):
        Settings(
            data_dir=tmp_path,
            database_path=tmp_path / "db.sqlite3",
            backup_dir=tmp_path / "backups",
            environment="production",
            auth_mode="local",
        ).auth_settings()


def test_production_rejects_domain_scoped_auth_cookie(tmp_path) -> None:
    with pytest.raises(ValueError, match="host-only"):
        Settings(
            data_dir=tmp_path,
            database_path=tmp_path / "db.sqlite3",
            backup_dir=tmp_path / "backups",
            environment="production",
            auth_mode="github",
            auth_session_secret="s" * 48,
            auth_public_origin="https://ledger.example",
            auth_cookie_secure=True,
            auth_cookie_domain=".example",
            github_client_id="client",
            github_client_secret="secret",  # noqa: S106
            github_redirect_uri="https://ledger.example/api/v1/auth/github/callback",
            owner_github_id=123,
        ).auth_settings()


def test_browser_passkey_shape_consumes_encoded_challenge_once() -> None:
    store = MemoryAuthStore()
    manager = AuthManager(
        store,
        AuthSettings(mode="local", session_secret="d" * 48, public_origin="http://testserver"),
        passkey_backend=_FakePasskeyBackend(),
    )
    account = manager.ensure_local_bootstrap(
        "member", "development-password-123", NOW, role="member"
    )
    user = UserRecord.from_record(account)
    options = manager.begin_passkey_registration(user, "testserver", "http://testserver")
    challenge = options["publicKey"]["challenge"]
    response = {
        "id": "credential-id-123456",
        "rawId": "Y3JlZGVudGlhbC1pZC0xMjM0NTY",
        "type": "public-key",
        "response": {"clientDataJSON": _encoded_client_data(challenge)},
    }
    manager.finish_passkey_registration(user, response, "testserver", "http://testserver")
    with pytest.raises(PasskeyRejected):
        manager.finish_passkey_registration(user, response, "testserver", "http://testserver")

    assertion_options = manager.begin_passkey_assertion(user, "testserver")
    assertion_challenge = assertion_options["publicKey"]["challenge"]
    assertion = {
        "id": "credential-id-123456",
        "rawId": "Y3JlZGVudGlhbC1pZC0xMjM0NTY",
        "type": "public-key",
        "response": {"clientDataJSON": _encoded_client_data(assertion_challenge)},
    }
    issue = manager.finish_passkey_assertion(
        user, assertion, "testserver", "http://testserver", NOW
    )
    assert issue.context.auth_method == "passkey"


def test_repository_backed_local_login_scopes_history_and_exports_to_each_user(tmp_path) -> None:
    """A real migrated store must never expose one bootstrap user's research to another."""

    settings = Settings(
        data_dir=tmp_path,
        database_path=tmp_path / "stock_probs.sqlite3",
        backup_dir=tmp_path / "backups",
        provider="fixture",
        auth_mode="local",
        auth_session_secret="e" * 48,
        auth_public_origin="http://testserver",
        bootstrap_username="admin",
        bootstrap_password="development-admin-password-123",  # noqa: S106
        bootstrap_member_username="member",
        bootstrap_member_password="development-member-password-123",  # noqa: S106
    )
    application = create_app(settings, FixtureProvider(), lambda: NOW)
    with TestClient(application) as client:
        admin_login = client.post(
            "/api/v1/auth/local/login",
            json={"username": "admin", "password": "development-admin-password-123"},
        )
        assert admin_login.status_code == 200, admin_login.text
        admin_csrf = admin_login.json()["csrf_token"]
        admin_cookie = client.cookies.get(SESSION_COOKIE_NAME)
        admin_sessions = client.get("/api/v1/auth/sessions")
        assert admin_sessions.status_code == 200, admin_sessions.text
        assert len(admin_sessions.json()["sessions"]) == 1
        assert admin_sessions.json()["sessions"][0]["current"] is True
        created = client.post(
            "/api/v1/forecasts",
            json={"symbol": "ACDC", "asset_type": "stock"},
            headers={"x-csrf-token": admin_csrf},
        )
        assert created.status_code == 201, created.text
        event_id = created.json()["event"]["id"]

        member_login = client.post(
            "/api/v1/auth/local/login",
            json={"username": "member", "password": "development-member-password-123"},
        )
        assert member_login.status_code == 200, member_login.text
        member_history = client.get("/api/v1/history")
        assert member_history.status_code == 200, member_history.text
        assert member_history.json()["items"] == []
        member_export = client.get("/api/v1/history-export.json")
        assert member_export.status_code == 200, member_export.text
        assert member_export.json()["counts"]["events"] == 0
        assert client.get(f"/api/v1/history/{event_id}").status_code == 404

        # Restore the first account's cookie only to prove the record remains available to its
        # owner after a second account has authenticated in the same browser client.
        assert isinstance(admin_cookie, str)
        client.cookies.clear()
        client.cookies.set(SESSION_COOKIE_NAME, admin_cookie, path="/")
        assert client.get("/api/v1/auth/session").json()["authenticated"] is True
        assert client.get(f"/api/v1/history/{event_id}").status_code == 200


def test_authenticated_promoted_restore_verifies_security_state_and_revokes_sessions(
    tmp_path,
) -> None:
    """Web promotion takes a verified pre-snapshot and invalidates every old session."""

    settings = Settings(
        data_dir=tmp_path,
        database_path=tmp_path / "stock_probs.sqlite3",
        backup_dir=tmp_path / "backups",
        provider="fixture",
        auth_mode="local",
        auth_session_secret="i" * 48,
        auth_public_origin="http://testserver",
    )
    store = MemoryAuthStore()
    application = create_app(settings, FixtureProvider(), lambda: NOW, auth_store=store)
    with TestClient(application) as client:
        record = application.state.auth.ensure_local_bootstrap(
            "admin", "development-admin-password-123", NOW
        )
        issue = application.state.auth.issue_session(
            application.state.auth.user_from_record(record), datetime.now(UTC), "passkey"
        )
        target = application.state.backups.create("target-restore.spbackup")
        client.cookies.set(SESSION_COOKIE_NAME, issue.session_token, domain="testserver", path="/")
        client.cookies.set(CSRF_COOKIE_NAME, issue.csrf_token, domain="testserver", path="/")
        restored = client.post(
            "/api/v1/operations/restores",
            json={"name": target["name"], "promote": True},
            headers={"x-csrf-token": issue.csrf_token},
            cookies={
                SESSION_COOKIE_NAME: issue.session_token,
                CSRF_COOKIE_NAME: issue.csrf_token,
            },
        )
        assert restored.status_code == 200, restored.text
        assert restored.json()["promoted"] is True
        # Promotion clears the browser cookies and revokes the server-side session.
        assert client.get("/api/v1/auth/session").json()["authenticated"] is False


def test_promoted_restore_cleanup_failure_keeps_maintenance_barrier(tmp_path, monkeypatch) -> None:
    """A post-swap revocation failure never reopens the restored database to requests."""

    settings = Settings(
        data_dir=tmp_path,
        database_path=tmp_path / "stock_probs.sqlite3",
        backup_dir=tmp_path / "backups",
        provider="fixture",
        auth_mode="local",
        auth_session_secret="k" * 48,
        auth_public_origin="http://testserver",
    )
    store = MemoryAuthStore()
    application = create_app(settings, FixtureProvider(), lambda: NOW, auth_store=store)
    with TestClient(application) as client:
        record = application.state.auth.ensure_local_bootstrap(
            "admin", "development-admin-password-123", NOW
        )
        issue = application.state.auth.issue_session(
            application.state.auth.user_from_record(record), datetime.now(UTC), "passkey"
        )
        target = application.state.backups.create("target-cleanup-failure.spbackup")

        def fail_revoke(*_args, **_kwargs):
            from stock_probs.auth import AuthUnavailable

            raise AuthUnavailable("forced test failure")

        monkeypatch.setattr("stock_probs.api._revoke_every_session", fail_revoke)
        restored = client.post(
            "/api/v1/operations/restores",
            json={"name": target["name"], "promote": True},
            headers={"x-csrf-token": issue.csrf_token},
            cookies={
                SESSION_COOKIE_NAME: issue.session_token,
                CSRF_COOKIE_NAME: issue.csrf_token,
            },
        )
        assert restored.status_code == 503
        assert client.get("/api/v1/readiness").status_code == 503
        assert client.get("/api/v1/health").status_code == 200
        assert client.get("/api/v1/history").status_code == 503


def test_restore_request_gate_drains_in_flight_request_before_promotion() -> None:
    """A promotion blocks new work and waits for the existing request to leave."""

    gate = _RestoreRequestGate()
    assert gate.try_enter() is True
    drained: list[bool] = []
    finished = threading.Event()

    def drain() -> None:
        drained.append(gate.begin_drain(1.0))
        finished.set()

    thread = threading.Thread(target=drain)
    thread.start()
    assert gate.try_enter() is False
    gate.leave()
    assert finished.wait(1.0)
    thread.join()
    assert drained == [True]
    gate.end_drain()
    assert gate.try_enter() is True
    gate.leave()


def test_github_state_is_single_use_and_binds_pkce_verifier() -> None:
    """The OAuth code exchange must use a durable, one-time state and S256 verifier."""

    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.host == "github.com" and request.url.path.endswith("/access_token"):
            return httpx.Response(200, json={"access_token": "test-access-token"})
        if request.url.host == "api.github.com" and request.url.path == "/user":
            return httpx.Response(200, json={"id": 24680, "login": "invited-user", "email": None})
        return httpx.Response(404)

    store = MemoryAuthStore()
    transport = httpx.MockTransport(handler)
    client = httpx.Client(transport=transport)
    manager = AuthManager(
        store,
        AuthSettings(
            mode="github",
            session_secret="f" * 48,
            public_origin="https://ledger.example",
            github_client_id="client-id",
            github_client_secret="client-secret",  # noqa: S106
            github_redirect_uri="https://ledger.example/api/v1/auth/github/callback",
        ),
        http_client=client,
    )
    authorization = manager.begin_github(NOW)
    query = parse_qs(urlparse(authorization.url).query)
    assert query["code_challenge_method"] == ["S256"]
    expected_challenge = (
        base64.urlsafe_b64encode(
            hashlib.sha256(authorization.code_verifier.encode("ascii")).digest()
        )
        .rstrip(b"=")
        .decode("ascii")
    )
    assert query["code_challenge"] == [expected_challenge]
    identity = manager.finish_github(
        "oauth-code",
        authorization.state,
        NOW + timedelta(seconds=1),
        browser_transaction=authorization.state,
    )
    assert identity.github_id == 24680
    assert identity.login == "invited-user"
    with pytest.raises(OAuthRejected):
        manager.finish_github(
            "oauth-code",
            authorization.state,
            NOW + timedelta(seconds=2),
            browser_transaction=authorization.state,
        )
    assert requests[0].content.decode().find("code_verifier=") >= 0
    client.close()


def test_github_start_has_bounded_process_admission(monkeypatch) -> None:
    """Anonymous OAuth starts are bounded before they can create durable state rows."""

    monkeypatch.setattr("stock_probs.auth.MAX_OAUTH_STARTS_PER_WINDOW", 2)
    manager = AuthManager(
        MemoryAuthStore(),
        AuthSettings(
            mode="github",
            session_secret="n" * 48,
            public_origin="https://ledger.example",
            github_client_id="client-id",
            github_client_secret="client-secret",  # noqa: S106
            github_redirect_uri="https://ledger.example/api/v1/auth/github/callback",
        ),
    )
    manager.begin_github(NOW)
    manager.begin_github(NOW + timedelta(seconds=1))
    with pytest.raises(AuthUnavailable):
        manager.begin_github(NOW + timedelta(seconds=2))


def test_github_callback_sets_provisional_cookie_and_consumes_invitation_once(tmp_path) -> None:
    """The browser receives a passkey handoff, never an OAuth token or reusable code."""

    settings = Settings(
        data_dir=tmp_path,
        database_path=tmp_path / "stock_probs.sqlite3",
        backup_dir=tmp_path / "backups",
        provider="fixture",
        environment="test",
        auth_mode="github",
        auth_session_secret="j" * 48,
        auth_public_origin="http://testserver",
        github_client_id="client-id",
        github_client_secret="client-secret",  # noqa: S106
        github_redirect_uri="http://testserver/api/v1/auth/github/callback",
        owner_github_id=99999,
    )
    store = MemoryAuthStore()
    application = create_app(settings, FixtureProvider(), lambda: NOW, auth_store=store)
    oauth_client = httpx.Client(
        transport=httpx.MockTransport(
            lambda request: (
                httpx.Response(200, json={"access_token": "test-access-token"})
                if request.url.host == "github.com"
                else httpx.Response(200, json={"id": 24680, "login": "invited-user"})
            )
        )
    )
    with TestClient(application) as client:
        application.state.auth.http_client = oauth_client
        malformed = client.post("/api/v1/auth/invites/redeem", json={"code": "invalid-qa-code"})
        assert malformed.status_code == 403, malformed.text
        assert malformed.json()["error"]["code"] == "invitation_rejected"
        store.auth_create_user(
            {
                "username": "admin",
                "github_id": 99999,
                "github_login": "owner",
                "role": "admin",
                "status": "active",
                "passkey_required": True,
                "passkey_enrolled": False,
            }
        )
        code, _ = application.state.auth.create_invitation(
            24680, 1, datetime.now(UTC), github_login="invited-user"
        )
        redeemed = client.post("/api/v1/auth/invites/redeem", json={"code": code})
        assert redeemed.status_code == 200, redeemed.text
        assert redeemed.json()["authorization_url"]
        assert OAUTH_TRANSACTION_COOKIE_NAME in redeemed.headers["set-cookie"]
        state = parse_qs(urlparse(redeemed.json()["authorization_url"]).query)["state"][0]
        callback = client.get(
            "/api/v1/auth/github/callback",
            params={"code": "oauth-code", "state": state},
            headers={"Sec-Fetch-Site": "cross-site"},
            follow_redirects=False,
        )
        assert callback.status_code == 303, callback.text
        assert callback.headers["location"].startswith("/passkey?mode=enroll")
        assert "access_token" not in callback.headers.get("location", "")
        assert SESSION_COOKIE_NAME in callback.headers["set-cookie"]
        assert f"{OAUTH_TRANSACTION_COOKIE_NAME}=" in callback.headers["set-cookie"]
        assert "Max-Age=0" in callback.headers["set-cookie"]
        replay = client.get(
            "/api/v1/auth/github/callback",
            params={"code": "oauth-code", "state": state},
            follow_redirects=False,
        )
        assert replay.status_code == 400
        assert replay.json()["error"]["code"] == "oauth_rejected"
    oauth_client.close()


def test_github_callback_requires_the_initiating_browser_transaction(tmp_path) -> None:
    """A copied OAuth URL cannot authenticate a browser with no matching transaction cookie."""

    settings = Settings(
        data_dir=tmp_path,
        database_path=tmp_path / "stock_probs.sqlite3",
        backup_dir=tmp_path / "backups",
        provider="fixture",
        environment="test",
        auth_mode="github",
        auth_session_secret="m" * 48,
        auth_public_origin="http://testserver",
        github_client_id="client-id",
        github_client_secret="client-secret",  # noqa: S106
        github_redirect_uri="http://testserver/api/v1/auth/github/callback",
        owner_github_id=24680,
    )
    store = MemoryAuthStore()
    application = create_app(settings, FixtureProvider(), lambda: NOW, auth_store=store)
    store.auth_create_user(
        {
            "username": "owner",
            "github_id": 24680,
            "github_login": "owner",
            "role": "admin",
            "status": "active",
            "passkey_required": True,
            "passkey_enrolled": False,
        }
    )
    oauth_client = httpx.Client(
        transport=httpx.MockTransport(
            lambda request: (
                httpx.Response(200, json={"access_token": "test-access-token"})
                if request.url.host == "github.com"
                else httpx.Response(200, json={"id": 24680, "login": "owner"})
            )
        )
    )
    with TestClient(application) as client:
        application.state.auth.http_client = oauth_client
        started = client.get("/api/v1/auth/github/start", follow_redirects=False)
        assert started.status_code == 302
        state = parse_qs(urlparse(started.headers["location"]).query)["state"][0]
        assert client.cookies.get(OAUTH_TRANSACTION_COOKIE_NAME) == state

        client.cookies.clear()
        absent = client.get(
            "/api/v1/auth/github/callback",
            params={"code": "oauth-code", "state": state},
            headers={"Sec-Fetch-Site": "cross-site"},
            follow_redirects=False,
        )
        assert absent.status_code == 400
        assert absent.json()["error"]["code"] == "oauth_rejected"

        restarted = client.get("/api/v1/auth/github/start", follow_redirects=False)
        restarted_state = parse_qs(urlparse(restarted.headers["location"]).query)["state"][0]
        client.cookies.set(OAUTH_TRANSACTION_COOKIE_NAME, "wrong-browser-transaction", path="/")
        mismatch = client.get(
            "/api/v1/auth/github/callback",
            params={"code": "oauth-code", "state": restarted_state},
            headers={"Sec-Fetch-Site": "cross-site"},
            follow_redirects=False,
        )
        assert mismatch.status_code == 400
        assert mismatch.json()["error"]["code"] == "oauth_rejected"

        client.cookies.set(OAUTH_TRANSACTION_COOKIE_NAME, restarted_state, path="/")
        valid = client.get(
            "/api/v1/auth/github/callback",
            params={"code": "oauth-code", "state": restarted_state},
            headers={"Sec-Fetch-Site": "cross-site"},
            follow_redirects=False,
        )
        assert valid.status_code == 303
        assert "Max-Age=0" in valid.headers["set-cookie"]

        replay = client.get(
            "/api/v1/auth/github/callback",
            params={"code": "oauth-code", "state": restarted_state},
            headers={"Sec-Fetch-Site": "cross-site"},
            follow_redirects=False,
        )
        assert replay.status_code == 400
        assert replay.json()["error"]["code"] == "oauth_rejected"
    oauth_client.close()


def test_github_session_requires_passkey_even_for_the_admin_owner(tmp_path) -> None:
    """A GitHub-only provisional cookie cannot reach a private route."""

    settings = Settings(
        data_dir=tmp_path,
        database_path=tmp_path / "stock_probs.sqlite3",
        backup_dir=tmp_path / "backups",
        provider="fixture",
        environment="test",
        auth_mode="github",
        auth_session_secret="g" * 48,
        auth_public_origin="http://testserver",
        github_client_id="client-id",
        github_client_secret="client-secret",  # noqa: S106
        github_redirect_uri="http://testserver/api/v1/auth/github/callback",
        owner_github_id=24680,
    )
    store = MemoryAuthStore()
    application = create_app(settings, FixtureProvider(), lambda: NOW, auth_store=store)
    with TestClient(application) as client:
        navigation = {
            "Sec-Fetch-Site": "cross-site",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Dest": "document",
        }
        anonymous_page = client.get("/overview", headers=navigation, follow_redirects=False)
        assert anonymous_page.status_code == 303
        assert anonymous_page.headers["location"].startswith("/sign-in")
        record = store.auth_create_user(
            {
                "github_id": 24680,
                "github_login": "owner",
                "role": "admin",
                "status": "active",
                "active": True,
                "passkey_enrolled": True,
                "passkey_required": False,
            }
        )
        issue = application.state.auth.issue_session(
            application.state.auth.user_from_record(record), datetime.now(UTC), "github"
        )
        response = client.get("/api/v1/history", cookies={SESSION_COOKIE_NAME: issue.session_token})
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "passkey_required"
        provisional_page = client.get(
            "/overview",
            headers=navigation,
            cookies={SESSION_COOKIE_NAME: issue.session_token},
            follow_redirects=False,
        )
        assert provisional_page.status_code == 303
        assert provisional_page.headers["location"].startswith("/passkey?mode=verify")


def test_provisional_github_session_cannot_register_second_passkey(tmp_path) -> None:
    """Adding a credential requires an existing passkey step-up after enrollment."""

    settings = Settings(
        data_dir=tmp_path,
        database_path=tmp_path / "stock_probs.sqlite3",
        backup_dir=tmp_path / "backups",
        provider="fixture",
        environment="test",
        auth_mode="github",
        auth_session_secret="h" * 48,
        auth_public_origin="http://testserver",
        github_client_id="client-id",
        github_client_secret="client-secret",  # noqa: S106
        github_redirect_uri="http://testserver/api/v1/auth/github/callback",
        owner_github_id=24680,
    )
    store = MemoryAuthStore()
    application = create_app(settings, FixtureProvider(), lambda: NOW, auth_store=store)
    with TestClient(application) as client:
        record = store.auth_create_user(
            {
                "github_id": 24680,
                "github_login": "owner",
                "role": "admin",
                "status": "active",
                "active": True,
                "passkey_enrolled": True,
                "passkey_required": False,
            }
        )
        issue = application.state.auth.issue_session(
            application.state.auth.user_from_record(record), datetime.now(UTC), "github"
        )
        response = client.post(
            "/api/v1/auth/passkeys/register/options",
            headers={"x-csrf-token": issue.csrf_token},
            cookies={
                SESSION_COOKIE_NAME: issue.session_token,
                CSRF_COOKIE_NAME: issue.csrf_token,
            },
        )
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "authorization_denied"
