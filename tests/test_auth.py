"""Focused authentication tests for the local and server-side auth boundary."""

from __future__ import annotations

import base64
import hashlib
import json
import threading
from collections.abc import Mapping
from dataclasses import replace
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
    AuthorizationDenied,
    AuthSettings,
    AuthUnavailable,
    CsrfRejected,
    InvitationRejected,
    MemoryAuthStore,
    OAuthRejected,
    OAuthStartLimited,
    PasskeyCredential,
    PasskeyRejected,
    TotpRejected,
    TotpThrottled,
    UserRecord,
    hash_password,
    verify_password,
)
from stock_probs.config import Settings
from stock_probs.provider import FixtureProvider
from stock_probs.repository import Repository
from stock_probs.totp import code_for_step, time_step

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


class _RejectingCounterStore(MemoryAuthStore):
    """Simulate durable counter persistence rejecting an otherwise valid assertion."""

    def auth_update_passkey(
        self, credential_id: str, fields: Mapping[str, object]
    ) -> Mapping[str, object] | None:
        del credential_id, fields
        return None


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


def _github_totp_manager(
    store: MemoryAuthStore | None = None,
) -> tuple[AuthManager, MemoryAuthStore, UserRecord]:
    selected = store or MemoryAuthStore()
    manager = AuthManager(
        selected,
        AuthSettings(
            mode="github",
            session_secret="t" * 48,
            public_origin="https://ledger.example",
            github_client_id="client",
            github_client_secret="secret",  # noqa: S106
            github_redirect_uri="https://ledger.example/api/v1/auth/github/callback",
        ),
    )
    record = selected.auth_create_user(
        {
            "github_id": 123456,
            "github_login": "totp-user",
            "role": "admin",
            "status": "active",
            "passkey_enrolled": False,
            "passkey_required": False,
        }
    )
    return manager, selected, manager.user_from_record(record)


def _enroll_totp(
    manager: AuthManager, user: UserRecord, now: datetime = NOW
) -> tuple[object, str, list[str]]:
    provisional = manager.issue_session(user, now, "github")
    setup = manager.begin_totp_enrollment(provisional.context, now)
    secret = setup["secret"]
    assert isinstance(secret, str)
    code = code_for_step(secret, time_step(now))
    issue, recovery_codes = manager.finish_totp_enrollment(provisional.context, code, now)
    return issue, secret, recovery_codes


def test_totp_enrollment_is_atomic_and_returns_one_time_recovery_codes() -> None:
    manager, store, user = _github_totp_manager()

    issue, secret, recovery_codes = _enroll_totp(manager, user)

    assert issue.context.mfa_method == "totp"
    assert store.auth_get_totp_factor(user.id) is not None
    assert store.auth_get_recovery_code_status(user.id)["available_count"] == len(recovery_codes)
    assert len(recovery_codes) == 10
    assert all(len(code.replace("-", "")) == 16 for code in recovery_codes)
    assert store.totp_enrollments == {}
    assert secret not in str(store.totp_factors)


def test_existing_passkey_user_enrolls_totp_from_fresh_github_session() -> None:
    manager, _store, user = _github_totp_manager()
    legacy_user = UserRecord(
        id=user.id,
        role=user.role,
        username=user.username,
        github_id=user.github_id,
        github_login=user.github_login,
        display_name=user.display_name,
        email=user.email,
        active=user.active,
        passkey_enrolled=True,
        passkey_required=False,
    )
    github_session = manager.issue_session(legacy_user, NOW, "github")
    setup = manager.begin_totp_enrollment(github_session.context, NOW)
    assert setup["enrollment"] is True
    with pytest.raises(AuthorizationDenied):
        manager.issue_session(legacy_user, NOW, "passkey", mfa_method="passkey")


def test_totp_enrollment_reuses_pending_key_until_explicit_rotation() -> None:
    manager, store, user = _github_totp_manager()
    provisional = manager.issue_session(user, NOW, "github")

    first = manager.begin_totp_enrollment(provisional.context, NOW)
    repeated = manager.begin_totp_enrollment(provisional.context, NOW + timedelta(seconds=97))
    assert repeated["secret"] == first["secret"]
    assert repeated["expires_at"] == first["expires_at"]

    code = code_for_step(first["secret"], time_step(NOW + timedelta(seconds=97)))
    issue, _recovery_codes = manager.finish_totp_enrollment(
        provisional.context, code, NOW + timedelta(seconds=97)
    )
    assert issue.context.mfa_method == "totp"
    assert store.auth_get_totp_factor(user.id) is not None


def test_totp_enrollment_rotation_invalidates_only_the_old_key() -> None:
    manager, _store, user = _github_totp_manager()
    provisional = manager.issue_session(user, NOW, "github")

    first = manager.begin_totp_enrollment(provisional.context, NOW)
    rotated = manager.begin_totp_enrollment(
        provisional.context, NOW + timedelta(seconds=1), replace=True
    )
    assert rotated["secret"] != first["secret"]
    assert rotated["expires_at"] > first["expires_at"]

    old_code = code_for_step(first["secret"], time_step(NOW + timedelta(seconds=1)))
    with pytest.raises(TotpRejected):
        manager.finish_totp_enrollment(provisional.context, old_code, NOW + timedelta(seconds=1))

    new_code = code_for_step(rotated["secret"], time_step(NOW + timedelta(seconds=2)))
    issue, _recovery_codes = manager.finish_totp_enrollment(
        provisional.context, new_code, NOW + timedelta(seconds=2)
    )
    assert issue.context.mfa_method == "totp"


def test_totp_enrollment_origin_conflict_preserves_original_pending_key() -> None:
    manager, _store, user = _github_totp_manager()
    first_session = manager.issue_session(user, NOW, "github")
    second_session = manager.issue_session(user, NOW + timedelta(seconds=1), "github")

    first = manager.begin_totp_enrollment(first_session.context, NOW)
    with pytest.raises(TotpRejected):
        manager.begin_totp_enrollment(second_session.context, NOW + timedelta(seconds=1))

    repeated = manager.begin_totp_enrollment(first_session.context, NOW + timedelta(seconds=2))
    assert repeated["secret"] == first["secret"]
    assert repeated["expires_at"] == first["expires_at"]


def test_totp_enrollment_expiry_allows_a_new_default_key() -> None:
    manager, _store, user = _github_totp_manager()
    provisional = manager.issue_session(user, NOW, "github")

    first = manager.begin_totp_enrollment(provisional.context, NOW)
    after_expiry = NOW + timedelta(seconds=601)
    replacement = manager.begin_totp_enrollment(provisional.context, after_expiry)
    assert replacement["secret"] != first["secret"]
    assert replacement["expires_at"] == after_expiry + timedelta(minutes=10)


def test_github_user_shape_never_advertises_a_passkey_requirement() -> None:
    manager, _store, user = _github_totp_manager()
    legacy_shape = replace(
        user,
        role="member",
        passkey_enrolled=False,
        passkey_required=True,
    )
    normalized = manager.user_from_record(legacy_shape.public_dict())
    assert normalized.passkey_enrolled is False
    assert normalized.passkey_required is False


def test_totp_replay_is_rejected_but_existing_verified_device_survives_new_login() -> None:
    manager, store, user = _github_totp_manager()
    first, secret, _ = _enroll_totp(manager, user)
    code = code_for_step(secret, time_step(NOW) + 1)
    provisional = manager.issue_session(user, NOW + timedelta(seconds=30), "github")
    second = manager.verify_totp(provisional.context, code, NOW + timedelta(seconds=30))
    assert (
        manager.authenticate(first.session_token, NOW + timedelta(seconds=31)).mfa_method == "totp"
    )
    assert (
        manager.authenticate(second.session_token, NOW + timedelta(seconds=31)).mfa_method == "totp"
    )

    replay = manager.issue_session(user, NOW + timedelta(seconds=60), "github")
    with pytest.raises(TotpRejected):
        manager.verify_totp(replay.context, code, NOW + timedelta(seconds=60))
    assert (
        store.sessions[hashlib.sha256(first.session_token.encode()).hexdigest()].get("revoked_at")
        is None
    )


def test_totp_failed_attempts_are_account_throttled_and_recovery_codes_are_single_use() -> None:
    manager, _store, user = _github_totp_manager()
    _issue, secret, recovery_codes = _enroll_totp(manager, user)
    for attempt in range(5):
        provisional = manager.issue_session(user, NOW + timedelta(minutes=attempt + 1), "github")
        with pytest.raises(TotpRejected):
            manager.verify_totp(provisional.context, "000000", NOW + timedelta(minutes=attempt + 1))
    locked = manager.issue_session(user, NOW + timedelta(minutes=6), "github")
    with pytest.raises(TotpThrottled):
        manager.verify_totp(locked.context, "000000", NOW + timedelta(minutes=6))

    # Recovery consumes one code atomically; the same code cannot create a second session.
    recovery_context = manager.issue_session(user, NOW + timedelta(minutes=25), "github").context
    recovered = manager.recover_with_code(
        recovery_context, recovery_codes[0], NOW + timedelta(minutes=25)
    )
    assert recovered.context.mfa_method == "recovery"
    with pytest.raises(TotpRejected):
        manager.recover_with_code(
            recovery_context,
            recovery_codes[0],
            NOW + timedelta(minutes=25, seconds=1),
        )


def test_old_factor_cannot_issue_a_session_after_replacement_race() -> None:
    """A proof completed against an old factor must fail the generation-bound insert."""

    manager, store, user = _github_totp_manager()
    assured, secret, _ = _enroll_totp(manager, user)
    provisional = manager.issue_session(user, NOW + timedelta(seconds=31), "github")
    entered = threading.Event()
    release = threading.Event()
    original_issue = manager.issue_session
    result: list[object] = []

    def delayed_issue(issue_user, issued_at, auth_method, **kwargs):
        if kwargs.get("origin_token_hash") == provisional.context.token_hash:
            entered.set()
            assert release.wait(timeout=10)
        return original_issue(issue_user, issued_at, auth_method, **kwargs)

    manager.issue_session = delayed_issue  # type: ignore[method-assign]

    def verify() -> None:
        try:
            result.append(
                manager.verify_totp(
                    provisional.context,
                    code_for_step(secret, time_step(NOW) + 1),
                    NOW + timedelta(seconds=31),
                )
            )
        except Exception as exc:  # noqa: BLE001 - assert the guarded failure below
            result.append(exc)

    worker = threading.Thread(target=verify)
    worker.start()
    assert entered.wait(timeout=10)
    factor = store.totp_factors[user.id]
    factor["id"] = int(factor["id"]) + 1
    release.set()
    worker.join(timeout=10)
    assert not worker.is_alive()

    assert len(result) == 1
    assert isinstance(result[0], TotpRejected)
    assert not any(
        session.get("mfa_method") == "totp"
        and session.get("user_id") == user.id
        and session.get("token_hash")
        not in {provisional.context.token_hash, assured.context.token_hash}
        for session in store.sessions.values()
    )


def test_old_recovery_code_cannot_issue_a_replacement_session_after_factor_race() -> None:
    """A recovery code consumed before replacement cannot mint a stale recovery session."""

    manager, store, user = _github_totp_manager()
    _assured, _secret, recovery_codes = _enroll_totp(manager, user)
    provisional = manager.issue_session(user, NOW + timedelta(minutes=1), "github")
    entered = threading.Event()
    release = threading.Event()
    original_issue = manager.issue_session
    result: list[object] = []

    def delayed_issue(issue_user, issued_at, auth_method, **kwargs):
        if kwargs.get("mfa_method") == "recovery":
            entered.set()
            assert release.wait(timeout=10)
        return original_issue(issue_user, issued_at, auth_method, **kwargs)

    manager.issue_session = delayed_issue  # type: ignore[method-assign]

    def recover() -> None:
        try:
            result.append(
                manager.recover_with_code(
                    provisional.context, recovery_codes[0], NOW + timedelta(minutes=1)
                )
            )
        except Exception as exc:  # noqa: BLE001 - assert the guarded failure below
            result.append(exc)

    worker = threading.Thread(target=recover)
    worker.start()
    assert entered.wait(timeout=10)
    factor = store.totp_factors[user.id]
    factor["id"] = int(factor["id"]) + 1
    release.set()
    worker.join(timeout=10)
    assert not worker.is_alive()

    assert len(result) == 1
    assert isinstance(result[0], TotpRejected)
    assert not any(
        session.get("mfa_method") == "recovery" and session.get("user_id") == user.id
        for session in store.sessions.values()
    )


def test_old_factor_cannot_rotate_recovery_codes_after_replacement_race() -> None:
    """A late rotation cannot overwrite recovery material for a newer factor."""

    manager, store, user = _github_totp_manager()
    assured, secret, recovery_codes = _enroll_totp(manager, user)
    original_recovery_hashes = [item["code_hash"] for item in store.recovery_codes[user.id]]
    entered = threading.Event()
    release = threading.Event()
    inner = store
    original_create = inner.auth_create_recovery_codes
    result: list[object] = []

    def delayed_create(user_id, expected_factor_id, code_hashes, created_at, origin_token_hash):
        entered.set()
        assert release.wait(timeout=10)
        return original_create(
            user_id, expected_factor_id, code_hashes, created_at, origin_token_hash
        )

    inner.auth_create_recovery_codes = delayed_create  # type: ignore[method-assign]

    def rotate() -> None:
        try:
            result.append(
                manager.rotate_recovery_codes(
                    assured.context,
                    code_for_step(secret, time_step(NOW) + 1),
                    NOW + timedelta(seconds=31),
                )
            )
        except Exception as exc:  # noqa: BLE001 - assert the guarded failure below
            result.append(exc)

    worker = threading.Thread(target=rotate)
    worker.start()
    assert entered.wait(timeout=10)
    factor = store.totp_factors[user.id]
    factor["id"] = int(factor["id"]) + 1
    release.set()
    worker.join(timeout=10)
    assert not worker.is_alive()

    assert len(result) == 1
    assert isinstance(result[0], TotpRejected)
    assert store.auth_get_recovery_code_status(user.id)["available_count"] == len(recovery_codes)
    assert [item["code_hash"] for item in store.recovery_codes[user.id]] == original_recovery_hashes


def test_concurrent_totp_reservations_bound_crypto_attempts() -> None:
    """The durable reservation gate limits concurrent guesses before matching_step runs."""

    manager, store, user = _github_totp_manager()
    _assured, secret, _ = _enroll_totp(manager, user)
    sessions = [
        manager.issue_session(user, NOW + timedelta(minutes=2, seconds=index), "github")
        for index in range(8)
    ]
    barrier = threading.Barrier(len(sessions))
    count_lock = threading.Lock()
    crypto_calls = 0
    import stock_probs.auth as auth_module

    original_matching_step = auth_module.matching_step

    def counted_matching_step(totp_secret, code, current):
        nonlocal crypto_calls
        with count_lock:
            crypto_calls += 1
        return original_matching_step(totp_secret, code, current)

    # Keep this test deterministic without adding a production hook: all callers rendezvous
    # before attempting the same account-scoped reservation.
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(auth_module, "matching_step", counted_matching_step)
    errors: list[Exception] = []

    def guess(issue) -> None:
        try:
            barrier.wait(timeout=10)
            manager.verify_totp(issue.context, "000000", NOW + timedelta(minutes=2))
        except Exception as exc:  # noqa: BLE001 - classify bounded outcomes below
            errors.append(exc)

    workers = [threading.Thread(target=guess, args=(issue,)) for issue in sessions]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(timeout=15)
        assert not worker.is_alive()
    monkeypatch.undo()

    assert len(errors) == len(sessions)
    assert crypto_calls <= 5
    assert sum(isinstance(error, TotpThrottled) for error in errors) >= 3


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


def test_github_invitation_binds_identity_and_cannot_be_reused(tmp_path) -> None:
    """An invitation remains bound to one GitHub ID across browsers and retries."""

    settings = Settings(
        data_dir=tmp_path,
        database_path=tmp_path / "stock_probs.sqlite3",
        backup_dir=tmp_path / "backups",
        provider="fixture",
        environment="test",
        auth_mode="github",
        auth_session_secret="i" * 48,
        auth_public_origin="http://testserver",
        github_client_id="client-id",
        github_client_secret="client-secret",  # noqa: S106
        github_redirect_uri="http://testserver/api/v1/auth/github/callback",
        owner_github_id=99999,
    )
    store = MemoryAuthStore()
    store.auth_create_user(
        {
            "username": "owner",
            "github_id": 99999,
            "github_login": "owner",
            "role": "admin",
            "status": "active",
            "passkey_required": True,
            "passkey_enrolled": False,
        }
    )
    application = create_app(settings, FixtureProvider(), lambda: NOW, auth_store=store)
    identity_id = 123

    def github_handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "github.com" and request.url.path.endswith("/access_token"):
            return httpx.Response(200, json={"access_token": "test-access-token"})
        if request.url.host == "api.github.com" and request.url.path == "/user":
            return httpx.Response(
                200,
                json={"id": identity_id, "login": f"github-{identity_id}"},
            )
        return httpx.Response(404)

    oauth_client = httpx.Client(transport=httpx.MockTransport(github_handler))

    def finish(client: TestClient, code: str) -> httpx.Response:
        started = client.get(
            "/api/v1/auth/github/start",
            params={"invite": code},
            follow_redirects=False,
        )
        assert started.status_code == 302, started.text
        state = parse_qs(urlparse(started.headers["location"]).query)["state"][0]
        return client.get(
            "/api/v1/auth/github/callback",
            params={"code": "oauth-code", "state": state},
            headers={"Sec-Fetch-Site": "cross-site"},
            follow_redirects=False,
        )

    with TestClient(application) as first_client, TestClient(application) as second_client:
        application.state.auth.http_client = oauth_client
        first_code, _ = application.state.auth.create_invitation(
            123, 1, datetime.now(UTC), github_login="github-123"
        )
        first = finish(first_client, first_code)
        assert first.status_code == 303, first.text
        assert store.auth_get_user_by_github_id(123) is not None

        identity_id = 456
        reused = finish(second_client, first_code)
        assert reused.status_code == 403, reused.text
        assert reused.json()["error"]["code"] == "invitation_rejected"
        assert store.auth_get_user_by_github_id(456) is None

        second_code, _ = application.state.auth.create_invitation(
            456, 1, datetime.now(UTC), github_login="github-456"
        )
        identity_id = 789
        mismatch = finish(second_client, second_code)
        assert mismatch.status_code == 403, mismatch.text
        assert mismatch.json()["error"]["code"] == "invitation_rejected"
        assert store.auth_get_user_by_github_id(789) is None
        assert (
            application.state.auth.inspect_invitation(second_code, datetime.now(UTC))["github_id"]
            == 456
        )

        identity_id = 456
        accepted = finish(second_client, second_code)
        assert accepted.status_code == 303, accepted.text
        assert store.auth_get_user_by_github_id(456) is not None
    oauth_client.close()


def _email_invitation_app(tmp_path, provider_emails, *, repository=None):
    """Build an isolated email-bound OAuth app with a controllable GitHub response."""

    settings = Settings(
        data_dir=tmp_path,
        database_path=tmp_path / "stock_probs.sqlite3",
        backup_dir=tmp_path / "backups",
        provider="fixture",
        environment="test",
        auth_mode="github",
        auth_session_secret="e" * 48,
        auth_public_origin="http://testserver",
        github_client_id="client-id",
        github_client_secret="client-secret",  # noqa: S106
        github_redirect_uri="http://testserver/api/v1/auth/github/callback",
        owner_github_id=99999,
    )
    store = repository or MemoryAuthStore()
    application = create_app(
        settings, FixtureProvider(), lambda: datetime.now(UTC), auth_store=store
    )
    calls: list[httpx.Request] = []

    def github_handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.url.host == "github.com" and request.url.path.endswith("/access_token"):
            return httpx.Response(200, json={"access_token": "test-access-token"})
        if request.url.host == "api.github.com" and request.url.path == "/user":
            return httpx.Response(
                200,
                json=provider_emails.get(
                    "profile",
                    {
                        "id": 24680,
                        "login": "email-invite-member",
                        "email": "unverified-profile@example.test",
                    },
                ),
            )
        if request.url.host == "api.github.com" and request.url.path == "/user/emails":
            if provider_emails.get("timeout"):
                raise httpx.TimeoutException("bounded fake timeout", request=request)
            payload = provider_emails["value"]
            if provider_emails.get("status") is not None:
                return httpx.Response(provider_emails["status"], json=payload)
            return httpx.Response(200, json=payload, headers=provider_emails.get("headers"))
        return httpx.Response(404)

    oauth_client = httpx.Client(transport=httpx.MockTransport(github_handler))
    application.state.auth.http_client = oauth_client
    code, _ = application.state.auth.create_invitation(
        None,
        1,
        datetime.now(UTC),
        email="Invitee+Research@example.test",
    )
    return application, store, code, calls, oauth_client


def _github_callback_app(tmp_path, *, profile=None):
    """Build a minimal GitHub callback fixture without any email-bound invitation."""

    settings = Settings(
        data_dir=tmp_path,
        database_path=tmp_path / "stock_probs.sqlite3",
        backup_dir=tmp_path / "backups",
        provider="fixture",
        environment="test",
        auth_mode="github",
        auth_session_secret="f" * 48,
        auth_public_origin="http://testserver",
        github_client_id="client-id",
        github_client_secret="client-secret",  # noqa: S106
        github_redirect_uri="http://testserver/api/v1/auth/github/callback",
        owner_github_id=99999,
    )
    store = MemoryAuthStore()
    application = create_app(
        settings, FixtureProvider(), lambda: datetime.now(UTC), auth_store=store
    )
    calls: list[httpx.Request] = []

    def github_handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.url.host == "github.com" and request.url.path.endswith("/access_token"):
            return httpx.Response(200, json={"access_token": "test-access-token"})
        if request.url.host == "api.github.com" and request.url.path == "/user":
            return httpx.Response(
                200,
                json=profile or {"id": 24680, "login": "callback-member"},
            )
        return httpx.Response(404)

    oauth_client = httpx.Client(transport=httpx.MockTransport(github_handler))
    application.state.auth.http_client = oauth_client
    return application, store, calls, oauth_client


def _redeem_email_invitation(
    client: TestClient, code: str, *, accept: str | None = None
) -> httpx.Response:
    """Start the invitation transaction and complete its callback in the same browser."""

    redeemed = client.post("/api/v1/auth/invites/redeem", json={"code": code})
    authorization_url = redeemed.json().get("authorization_url")
    if authorization_url is None:
        return redeemed
    state = parse_qs(urlparse(authorization_url).query)["state"][0]
    headers = {"Sec-Fetch-Site": "cross-site"}
    if accept is not None:
        headers["Accept"] = accept
    return client.get(
        "/api/v1/auth/github/callback",
        params={"code": "oauth-code", "state": state},
        headers=headers,
        follow_redirects=False,
    )


def _assert_oauth_transaction_cookie_cleared(response: httpx.Response) -> None:
    """Every callback error expires only the one-time transaction cookie."""

    cookies = response.headers.get_list("set-cookie")
    assert any(
        cookie.startswith(f"{OAUTH_TRANSACTION_COOKIE_NAME}=") and "Max-Age=0" in cookie
        for cookie in cookies
    )
    assert not any(cookie.startswith(f"{SESSION_COOKIE_NAME}=") for cookie in cookies)


def test_email_invitation_requires_matching_verified_github_email_and_can_retry(tmp_path) -> None:
    """Wrong/unverified mailboxes do not burn invites; profile.email is never proof."""

    provider_emails = {"value": [{"email": "invitee+research@example.test", "verified": False}]}
    application, store, code, calls, oauth_client = _email_invitation_app(tmp_path, provider_emails)
    invite_hash = hashlib.sha256(code.encode()).hexdigest()
    with TestClient(application) as client:
        redeemed = client.post("/api/v1/auth/invites/redeem", json={"code": code})
        assert redeemed.status_code == 200, redeemed.text
        assert redeemed.json()["invitation_email_bound"] is True
        assert redeemed.json()["invitation_github_id"] is None
        state = parse_qs(urlparse(redeemed.json()["authorization_url"]).query)["state"][0]
        unverified = client.get(
            "/api/v1/auth/github/callback",
            params={"code": "oauth-code", "state": state},
            headers={"Sec-Fetch-Site": "cross-site"},
            follow_redirects=False,
        )
        assert unverified.status_code == 403
        assert unverified.json()["error"]["code"] == "invitation_email_mismatch"
        _assert_oauth_transaction_cookie_cleared(unverified)
        assert store.auth_get_user_by_github_id(24680) is None
        assert client.get("/api/v1/auth/session").json()["authenticated"] is False
        invitation = store.auth_get_invitation(invite_hash)
        assert invitation is not None
        assert invitation["github_id"] is None
        assert invitation.get("used_at") is None

        provider_emails["value"] = [{"email": "invitee.research@example.test", "verified": True}]
        wrong_alias = _redeem_email_invitation(client, code)
        assert wrong_alias.status_code == 403
        assert wrong_alias.json()["error"]["code"] == "invitation_email_mismatch"
        _assert_oauth_transaction_cookie_cleared(wrong_alias)
        invitation = store.auth_get_invitation(invite_hash)
        assert invitation is not None and invitation["github_id"] is None
        assert invitation.get("used_at") is None

        provider_emails["value"] = []
        missing_email = _redeem_email_invitation(client, code)
        assert missing_email.status_code == 403
        assert missing_email.json()["error"]["code"] == "invitation_email_mismatch"
        _assert_oauth_transaction_cookie_cleared(missing_email)
        invitation = store.auth_get_invitation(invite_hash)
        assert invitation is not None and invitation["github_id"] is None
        assert invitation.get("used_at") is None

        provider_emails["value"] = [{"email": "INVITEE+RESEARCH@example.test", "verified": True}]
        accepted = _redeem_email_invitation(client, code)
        assert accepted.status_code == 303, accepted.text
        assert accepted.headers["location"].startswith("/authenticator?mode=enroll")
        private_history = client.get("/api/v1/history")
        assert private_history.status_code == 403
        assert private_history.json()["error"]["code"] == "totp_required"
        member = store.auth_get_user_by_github_id(24680)
        assert member is not None and member["role"] == "member"
        consumed = store.auth_get_invitation(invite_hash)
        assert consumed is not None
        assert consumed["github_id"] == 24680
        assert consumed["used_at"] is not None
        email_requests = [call for call in calls if call.url.path == "/user/emails"]
        assert len(email_requests) == 4
        assert str(email_requests[-1].url.params) == "per_page=100&page=1"
    oauth_client.close()


def test_email_mismatch_html_recovery_preserves_invite_and_allows_retry(tmp_path) -> None:
    """HTML mismatch gets a safe recovery route; the same invitation can be retried."""

    provider_emails = {"value": [{"email": "other@example.test", "verified": True}]}
    application, store, code, _calls, oauth_client = _email_invitation_app(
        tmp_path, provider_emails
    )
    invite_hash = hashlib.sha256(code.encode()).hexdigest()
    with TestClient(application) as client:
        mismatch = _redeem_email_invitation(client, code, accept="text/html")
        assert mismatch.status_code == 303
        assert mismatch.headers["location"] == "/invite?error=invitation_email_mismatch"
        _assert_oauth_transaction_cookie_cleared(mismatch)
        assert "other@example.test" not in mismatch.headers["location"]
        assert store.auth_get_user_by_github_id(24680) is None
        assert client.get("/api/v1/auth/session").json()["authenticated"] is False
        invitation = store.auth_get_invitation(invite_hash)
        assert invitation is not None
        assert invitation["github_id"] is None
        assert invitation.get("used_at") is None

        provider_emails["value"] = [{"email": "invitee+research@example.test", "verified": True}]
        recovered = _redeem_email_invitation(client, code, accept="text/html")
        assert recovered.status_code == 303
        assert recovered.headers["location"].startswith("/authenticator?mode=enroll")
        member = store.auth_get_user_by_github_id(24680)
        assert member is not None and member["role"] == "member"
        assert client.get("/api/v1/history").json()["error"]["code"] == "totp_required"
    oauth_client.close()


@pytest.mark.parametrize("accept", ["*/*", "text/htmlish", "text/html;q=0", "text/html;q=bad"])
def test_oauth_error_query_uses_only_explicit_html_recovery(accept, tmp_path) -> None:
    """OAuth query values and non-HTML Accept ranges cannot steer redirect locations."""

    application, _store, _calls, oauth_client = _github_callback_app(tmp_path)
    with TestClient(application) as client:
        started = client.get("/api/v1/auth/github/start", follow_redirects=False)
        state = parse_qs(urlparse(started.headers["location"]).query)["state"][0]
        callback = client.get(
            "/api/v1/auth/github/callback",
            params=[
                ("code", "oauth-code"),
                ("state", state),
                ("error", "https://attacker.example/secret"),
                ("error_description", "private-marker"),
                ("next", "//attacker.example/path"),
            ],
            headers={"Accept": accept, "Sec-Fetch-Site": "cross-site"},
            follow_redirects=False,
        )
        assert callback.status_code == 400
        assert callback.json()["error"]["code"] == "oauth_rejected"
        assert "Location" not in callback.headers
        assert "private-marker" not in callback.text
        assert "attacker.example" not in callback.text
        _assert_oauth_transaction_cookie_cleared(callback)
    oauth_client.close()


def test_oauth_callback_html_error_query_uses_fixed_location(tmp_path) -> None:
    """An explicit HTML client gets a fixed OAuth recovery route with no query reflection."""

    application, _store, _calls, oauth_client = _github_callback_app(tmp_path)
    with TestClient(application) as client:
        started = client.get("/api/v1/auth/github/start", follow_redirects=False)
        state = parse_qs(urlparse(started.headers["location"]).query)["state"][0]
        callback = client.get(
            "/api/v1/auth/github/callback",
            params=[
                ("code", "oauth-code"),
                ("state", state),
                ("error", "https://attacker.example/secret"),
                ("next", "//attacker.example/path"),
            ],
            headers={
                "Accept": "application/json, text/html;q=0.8",
                "Sec-Fetch-Site": "cross-site",
            },
            follow_redirects=False,
        )
        assert callback.status_code == 303
        assert callback.headers["location"] == "/sign-in?error=oauth_rejected"
        assert "attacker.example" not in callback.headers["location"]
        _assert_oauth_transaction_cookie_cleared(callback)
    oauth_client.close()


def test_oauth_callback_validation_clears_cookie_and_preserves_openapi_contract(tmp_path) -> None:
    """Manual failure handling retains required code/state query schemas and JSON 422."""

    application, _store, _calls, oauth_client = _github_callback_app(tmp_path)
    with TestClient(application) as client:
        operation = client.get("/api/v1/openapi.json").json()["paths"][
            "/api/v1/auth/github/callback"
        ]["get"]
        parameters = {parameter["name"]: parameter for parameter in operation["parameters"]}
        assert parameters["code"]["required"] is True
        assert parameters["code"]["schema"]["minLength"] == 8
        assert parameters["code"]["schema"]["maxLength"] == 512
        assert parameters["state"]["required"] is True
        assert parameters["state"]["schema"]["minLength"] == 16
        assert parameters["state"]["schema"]["maxLength"] == 256

        started = client.get("/api/v1/auth/github/start", follow_redirects=False)
        state = parse_qs(urlparse(started.headers["location"]).query)["state"][0]
        html_missing = client.get(
            "/api/v1/auth/github/callback",
            params={"state": state},
            headers={"Accept": "text/html", "Sec-Fetch-Site": "cross-site"},
            follow_redirects=False,
        )
        assert html_missing.status_code == 303
        assert html_missing.headers["location"] == "/sign-in?error=oauth_rejected"
        _assert_oauth_transaction_cookie_cleared(html_missing)

        started = client.get("/api/v1/auth/github/start", follow_redirects=False)
        state = parse_qs(urlparse(started.headers["location"]).query)["state"][0]
        json_invalid = client.get(
            "/api/v1/auth/github/callback",
            params={"code": "x" * 513, "state": state},
            headers={"Accept": "application/json", "Sec-Fetch-Site": "cross-site"},
            follow_redirects=False,
        )
        assert json_invalid.status_code == 422
        assert json_invalid.json()["error"]["code"] == "validation_error"
        _assert_oauth_transaction_cookie_cleared(json_invalid)
    oauth_client.close()


@pytest.mark.parametrize(
    ("failure", "accept", "expected_status", "expected_code", "expected_location"),
    [
        ("unavailable", "text/html", 303, None, "/sign-in?error=authentication_unavailable"),
        ("internal", "text/html", 303, None, "/sign-in?error=authentication_unavailable"),
        ("unavailable", "application/json", 503, "authentication_unavailable", None),
        ("internal", "application/json", 500, "internal_error", None),
    ],
)
def test_oauth_callback_unavailable_and_internal_failures_are_sanitized(
    failure, accept, expected_status, expected_code, expected_location, tmp_path, monkeypatch
) -> None:
    """Provider and internal failures clear browser state without leaking details."""

    application, _store, _calls, oauth_client = _github_callback_app(tmp_path)

    def fail(*_args, **_kwargs):
        if failure == "unavailable":
            raise AuthUnavailable()
        raise RuntimeError("private-marker")

    monkeypatch.setattr(application.state.auth, "finish_github", fail)
    with TestClient(application) as client:
        started = client.get("/api/v1/auth/github/start", follow_redirects=False)
        state = parse_qs(urlparse(started.headers["location"]).query)["state"][0]
        callback = client.get(
            "/api/v1/auth/github/callback",
            params={"code": "oauth-code", "state": state},
            headers={"Accept": accept, "Sec-Fetch-Site": "cross-site"},
            follow_redirects=False,
        )
        assert callback.status_code == expected_status
        if expected_location is not None:
            assert callback.headers["location"] == expected_location
        else:
            assert callback.json()["error"]["code"] == expected_code
        assert "private-marker" not in callback.text
        _assert_oauth_transaction_cookie_cleared(callback)
    oauth_client.close()


def test_expired_used_and_wrong_id_invitations_keep_generic_html_recovery(tmp_path) -> None:
    """Only an active email-bound mismatch gets the distinct email recovery message."""

    application, store, _calls, oauth_client = _github_callback_app(tmp_path)
    auth = application.state.auth
    now = datetime.now(UTC)
    wrong_id_code, _ = auth.create_invitation(13579, 1, now)
    expired_code, _ = auth.create_invitation(24680, 1, now)
    used_code, _ = auth.create_invitation(24680, 1, now)

    with TestClient(application) as client:
        for case, code in (
            ("wrong_id", wrong_id_code),
            ("expired", expired_code),
            ("used", used_code),
        ):
            started = client.get(
                "/api/v1/auth/github/start",
                params={"invite": code},
                follow_redirects=False,
            )
            state = parse_qs(urlparse(started.headers["location"]).query)["state"][0]
            if case in {"expired", "used"}:
                record = store.invitations[hashlib.sha256(code.encode()).hexdigest()]
                if case == "expired":
                    record["expires_at"] = (now - timedelta(seconds=1)).isoformat()
                else:
                    record["used_at"] = now.isoformat()
                    record["consumed_at"] = now.isoformat()
            callback = client.get(
                "/api/v1/auth/github/callback",
                params={"code": "oauth-code", "state": state},
                headers={"Accept": "text/html", "Sec-Fetch-Site": "cross-site"},
                follow_redirects=False,
            )
            assert callback.status_code == 303
            assert callback.headers["location"] == "/invite?error=invitation_rejected"
            _assert_oauth_transaction_cookie_cleared(callback)
        assert store.auth_get_user_by_github_id(24680) is None
    oauth_client.close()


@pytest.mark.parametrize(
    "provider_response",
    [
        {"value": {"emails": []}},
        {"value": [{"email": "invitee+research@example.test", "verified": 1}]},
        {"value": [{"email": "invitee+research@example.test", "verified": True}] * 100},
        {
            "value": [{"email": "invitee+research@example.test", "verified": True}],
            "headers": {"Link": '<https://api.github.com/user/emails?page=2>; rel="next"'},
        },
        {"value": [{"email": "invitee+research@example.test", "verified": True}], "status": 503},
        {"value": [{"email": "invitee+research@example.test", "verified": True}], "timeout": True},
        {"value": [{"email": "invitee+research@example.test", "verified": True}], "profile": []},
    ],
)
def test_email_invitation_rejects_malformed_or_unavailable_github_email_lists(
    tmp_path, provider_response
) -> None:
    """Malformed, truncated, and unavailable provider data cannot consume an invite."""

    application, store, code, calls, oauth_client = _email_invitation_app(
        tmp_path, provider_response
    )
    invite_hash = hashlib.sha256(code.encode()).hexdigest()
    with TestClient(application) as client:
        callback = _redeem_email_invitation(client, code)
        assert callback.status_code in {400, 403}
        assert callback.json()["error"]["code"] == "oauth_rejected"
        _assert_oauth_transaction_cookie_cleared(callback)
        invitation = store.auth_get_invitation(invite_hash)
        assert invitation is not None
        assert invitation["github_id"] is None
        assert invitation.get("used_at") is None
        assert store.auth_get_user_by_github_id(24680) is None
        expected_email_calls = 0 if "profile" in provider_response else 1
        assert sum(call.url.path == "/user/emails" for call in calls) == expected_email_calls
    oauth_client.close()


def test_existing_member_email_invite_preserves_role_and_totp_gate(tmp_path) -> None:
    """Email acceptance for an enrolled member lands on verification without changing role."""

    provider_emails = {"value": [{"email": "invitee+research@example.test", "verified": True}]}
    application, store, code, _calls, oauth_client = _email_invitation_app(
        tmp_path, provider_emails
    )
    member = store.auth_create_user(
        {
            "github_id": 24680,
            "github_login": "email-invite-member",
            "role": "member",
            "status": "active",
        }
    )
    store.totp_factors[int(member["id"])] = {"id": 7, "revoked_at": None}
    with TestClient(application) as client:
        accepted = _redeem_email_invitation(client, code)
        assert accepted.status_code == 303, accepted.text
        assert accepted.headers["location"].startswith("/authenticator?mode=verify")
        private_history = client.get("/api/v1/history")
        assert private_history.status_code == 403
        assert private_history.json()["error"]["code"] == "totp_required"
        current = store.auth_get_user_by_github_id(24680)
        assert current is not None
        assert current["role"] == "member"
        assert current["status"] == "active"
        assert store.totp_factors[int(member["id"])]["id"] == 7
    oauth_client.close()


def test_existing_member_normal_github_signin_skips_email_lookup_and_keeps_totp_gate(
    tmp_path,
) -> None:
    """Ordinary GitHub sign-in remains provider-light and still requires TOTP."""

    application, store, calls, oauth_client = _github_callback_app(tmp_path)
    member = store.auth_create_user(
        {
            "github_id": 24680,
            "github_login": "callback-member",
            "role": "member",
            "status": "active",
        }
    )
    store.totp_factors[int(member["id"])] = {"id": 9, "revoked_at": None}
    with TestClient(application) as client:
        started = client.get("/api/v1/auth/github/start", follow_redirects=False)
        state = parse_qs(urlparse(started.headers["location"]).query)["state"][0]
        callback = client.get(
            "/api/v1/auth/github/callback",
            params={"code": "oauth-code", "state": state},
            headers={"Accept": "text/html", "Sec-Fetch-Site": "cross-site"},
            follow_redirects=False,
        )
        assert callback.status_code == 303
        assert callback.headers["location"].startswith("/authenticator?mode=verify")
        assert client.get("/api/v1/history").status_code == 403
        assert client.get("/api/v1/history").json()["error"]["code"] == "totp_required"
        paths = [call.url.path for call in calls]
        assert "/user" in paths
        assert "/user/emails" not in paths
        current = store.auth_get_user_by_github_id(24680)
        assert current is not None and current["role"] == "member"
    oauth_client.close()


def test_email_invitation_redemption_uses_migrated_sqlite_schema(tmp_path) -> None:
    """A real schema-12 repository atomically preserves the private digest when binding ID."""

    repository = Repository(tmp_path / "stock_probs.sqlite3")
    repository.migrate()
    provider_emails = {"value": [{"email": "invitee+research@example.test", "verified": True}]}
    application, _store, code, _calls, oauth_client = _email_invitation_app(
        tmp_path, provider_emails, repository=repository
    )
    invite_hash = hashlib.sha256(code.encode()).hexdigest()
    with TestClient(application) as client:
        accepted = _redeem_email_invitation(client, code)
        assert accepted.status_code == 303, accepted.text
        member = repository.auth_get_user_by_github_id(24680)
        assert member is not None and member["role"] == "member"
        invitation = repository.auth_get_invitation(invite_hash)
        assert invitation is not None
        assert invitation["github_id"] == 24680
        assert invitation["email_hash"] == application.state.auth._email_hash(
            "Invitee+Research@example.test"
        )
        assert invitation["used_at"] is not None
        listed = repository.auth_list_invitations()[0]
        assert listed["email_bound"] is True
        assert "email_hash" not in listed
        assert "invitee+research@example.test" not in str(listed)
    oauth_client.close()


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


def test_authenticator_api_enrollment_returns_secret_once_and_assures_session(tmp_path) -> None:
    settings = Settings(
        data_dir=tmp_path,
        database_path=tmp_path / "stock_probs.sqlite3",
        backup_dir=tmp_path / "backups",
        provider="fixture",
        auth_mode="local",
        auth_session_secret="u" * 48,
        auth_public_origin="http://testserver",
        bootstrap_username="admin",
        bootstrap_password="development-password-123",  # noqa: S106
    )
    application = create_app(settings, FixtureProvider(), lambda: NOW)
    with TestClient(application) as client:
        login = client.post(
            "/api/v1/auth/local/login",
            json={"username": "admin", "password": "development-password-123"},
        )
        assert login.status_code == 200, login.text
        csrf_token = login.json()["csrf_token"]
        headers = {"x-csrf-token": csrf_token}

        status = client.get("/api/v1/auth/totp/status")
        assert status.status_code == 200, status.text
        assert status.json()["enrolled"] is False
        started = client.post("/api/v1/auth/totp/enroll/start", headers=headers)
        assert started.status_code == 200, started.text
        assert started.headers["cache-control"] == "no-store"
        enrollment = started.json()
        assert set(enrollment) == {"enrollment", "secret", "otpauth_uri", "expires_at"}

        repeated = client.post("/api/v1/auth/totp/enroll/start", headers=headers)
        assert repeated.status_code == 200, repeated.text
        assert repeated.json()["secret"] == enrollment["secret"]
        assert repeated.json()["expires_at"] == enrollment["expires_at"]

        malformed_replace = client.post(
            "/api/v1/auth/totp/enroll/start",
            json={"replace": "true"},
            headers=headers,
        )
        assert malformed_replace.status_code == 422

        rotated = client.post(
            "/api/v1/auth/totp/enroll/start",
            json={"replace": True},
            headers=headers,
        )
        assert rotated.status_code == 200, rotated.text
        assert rotated.json()["secret"] != enrollment["secret"]
        assert rotated.json()["expires_at"] != enrollment["expires_at"]

        finished = client.post(
            "/api/v1/auth/totp/enroll/finish",
            json={"code": code_for_step(enrollment["secret"], time_step())},
            headers=headers,
        )
        assert finished.status_code == 403, finished.text

        finished = client.post(
            "/api/v1/auth/totp/enroll/finish",
            json={"code": code_for_step(rotated.json()["secret"], time_step())},
            headers=headers,
        )
        assert finished.status_code == 200, finished.text
        assert finished.json()["mfa_method"] == "totp"
        assert len(finished.json()["recovery_codes"]) == 10
        assert client.get("/api/v1/auth/totp/status").json()["enrolled"] is True


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


def test_passkey_assertion_options_decode_transports_and_exclude_revoked() -> None:
    """Assertion options contain browser-ready transports for active credentials only."""

    manager, store = _manager()
    account = manager.ensure_local_bootstrap(
        "member", "development-password-123", NOW, role="member"
    )
    user = UserRecord.from_record(account)
    store.auth_create_passkey(
        {
            "credential_id": "active-credential-123456",
            "user_id": user.id,
            "public_key": "public-key-material-123456",
            "sign_count": 0,
            "transports": '["internal", "hybrid"]',
            "created_at": NOW.isoformat(),
        }
    )
    store.passkeys["revoked-credential-123456"] = {
        "credential_id": "revoked-credential-123456",
        "user_id": user.id,
        "public_key": "public-key-material-123456",
        "sign_count": 0,
        "transports": '["internal"]',
        "created_at": NOW.isoformat(),
        "revoked_at": NOW.isoformat(),
    }

    allow_credentials = manager.begin_passkey_assertion(user, "testserver")["publicKey"][
        "allowCredentials"
    ]

    assert allow_credentials == [
        {
            "type": "public-key",
            "id": "active-credential-123456",
            "transports": ["internal", "hybrid"],
        }
    ]


def test_revoked_passkey_assertion_cannot_issue_session() -> None:
    """A revoked credential is rejected before assertion verification can create a session."""

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
    store.auth_create_passkey(
        {
            "credential_id": "revoked-credential-123456",
            "user_id": user.id,
            "public_key": "public-key-material-123456",
            "sign_count": 0,
            "transports": "[]",
            "created_at": NOW.isoformat(),
            "revoked_at": NOW.isoformat(),
        }
    )
    options = manager.begin_passkey_assertion(user, "testserver")
    challenge = options["publicKey"]["challenge"]
    response = {
        "id": "revoked-credential-123456",
        "response": {"clientDataJSON": _encoded_client_data(challenge)},
    }

    with pytest.raises(PasskeyRejected):
        manager.finish_passkey_assertion(user, response, "testserver", "http://testserver", NOW)
    assert store.sessions == {}


def test_failed_passkey_counter_persistence_cannot_issue_session() -> None:
    """A successful cryptographic check is insufficient when the counter cannot be stored."""

    store = _RejectingCounterStore()
    manager = AuthManager(
        store,
        AuthSettings(mode="local", session_secret="d" * 48, public_origin="http://testserver"),
        passkey_backend=_FakePasskeyBackend(),
    )
    account = manager.ensure_local_bootstrap(
        "member", "development-password-123", NOW, role="member"
    )
    user = UserRecord.from_record(account)
    store.passkeys["credential-id-123456"] = {
        "credential_id": "credential-id-123456",
        "user_id": user.id,
        "public_key": "public-key-material-123456",
        "sign_count": 0,
        "transports": "[]",
        "created_at": NOW.isoformat(),
    }
    options = manager.begin_passkey_assertion(user, "testserver")
    challenge = options["publicKey"]["challenge"]
    response = {
        "id": "credential-id-123456",
        "response": {"clientDataJSON": _encoded_client_data(challenge)},
    }

    with pytest.raises(PasskeyRejected):
        manager.finish_passkey_assertion(user, response, "testserver", "http://testserver", NOW)
    assert store.sessions == {}


def test_repository_backed_local_login_scopes_history_and_exports_to_each_user(tmp_path) -> None:
    """A real migrated store must never expose one bootstrap user's research to another."""

    settings = Settings(
        data_dir=tmp_path,
        database_path=tmp_path / "stock_probs.sqlite3",
        backup_dir=tmp_path / "backups",
        provider="fixture",
        environment="test",
        auth_mode="local",
        auth_session_secret="e" * 48,
        auth_public_origin="http://testserver",
        bootstrap_username="admin",
        bootstrap_password="development-admin-password-123",  # noqa: S106
        bootstrap_member_username="member",
        bootstrap_member_password="development-member-password-123",  # noqa: S106
    )
    application = create_app(settings, FixtureProvider(), lambda: NOW)
    with TestClient(application) as owner_client, TestClient(application) as member_client:

        def login(client: TestClient, username: str, password: str) -> tuple[dict[str, str], str]:
            response = client.post(
                "/api/v1/auth/local/login",
                json={"username": username, "password": password},
            )
            assert response.status_code == 200, response.text
            csrf_token = response.json()["csrf_token"]
            session_cookie = client.cookies.get(SESSION_COOKIE_NAME)
            csrf_cookie = client.cookies.get(CSRF_COOKIE_NAME)
            assert isinstance(session_cookie, str)
            assert isinstance(csrf_cookie, str)
            assert csrf_cookie == csrf_token
            return {
                SESSION_COOKIE_NAME: session_cookie,
                CSRF_COOKIE_NAME: csrf_cookie,
            }, csrf_token

        owner_cookies, owner_csrf = login(owner_client, "admin", "development-admin-password-123")
        member_cookies, member_csrf = login(
            member_client, "member", "development-member-password-123"
        )

        for client, cookies in (
            (owner_client, owner_cookies),
            (member_client, member_cookies),
        ):
            sessions = client.get("/api/v1/auth/sessions", cookies=cookies)
            assert sessions.status_code == 200, sessions.text
            assert len(sessions.json()["sessions"]) == 1
            assert sessions.json()["sessions"][0]["current"] is True
            history = client.get("/api/v1/history", cookies=cookies)
            assert history.status_code == 200, history.text
            assert history.json()["items"] == []
            export = client.get("/api/v1/history-export.json", cookies=cookies)
            assert export.status_code == 200, export.text
            assert export.json()["counts"] == {"events": 0, "runs": 0, "results": 0}

        owner_created_response = owner_client.post(
            "/api/v1/forecasts",
            json={"symbol": "ACDC", "asset_type": "stock"},
            headers={"x-csrf-token": owner_csrf},
            cookies=owner_cookies,
        )
        member_created_response = member_client.post(
            "/api/v1/forecasts",
            json={"symbol": "SPY", "asset_type": "etf"},
            headers={"x-csrf-token": member_csrf},
            cookies=member_cookies,
        )
        assert owner_created_response.status_code == 201, owner_created_response.text
        assert member_created_response.status_code == 201, member_created_response.text
        owner_created = owner_created_response.json()
        member_created = member_created_response.json()
        owner_event_id = owner_created["event"]["id"]
        member_event_id = member_created["event"]["id"]
        owner_result_id = owner_created["results"][0]["id"]
        member_result_id = member_created["results"][0]["id"]
        assert owner_event_id != member_event_id
        assert owner_result_id != member_result_id

        owner_repeat_response = owner_client.post(
            "/api/v1/forecasts",
            json={"symbol": "ACDC", "asset_type": "stock"},
            headers={"x-csrf-token": owner_csrf},
            cookies=owner_cookies,
        )
        member_repeat_response = member_client.post(
            "/api/v1/forecasts",
            json={"symbol": "SPY", "asset_type": "etf"},
            headers={"x-csrf-token": member_csrf},
            cookies=member_cookies,
        )
        assert owner_repeat_response.status_code == 201, owner_repeat_response.text
        assert member_repeat_response.status_code == 201, member_repeat_response.text
        owner_repeat = owner_repeat_response.json()
        member_repeat = member_repeat_response.json()
        assert owner_repeat["event"]["status"] == "repeated"
        assert owner_repeat["event"]["is_repeat"] is True
        assert member_repeat["event"]["status"] == "repeated"
        assert member_repeat["event"]["is_repeat"] is True
        assert owner_repeat["event"]["id"] != owner_event_id
        assert member_repeat["event"]["id"] != member_event_id
        assert owner_repeat["results"][0]["id"] == owner_result_id
        assert member_repeat["results"][0]["id"] == member_result_id

        for client, cookies, foreign_event_id, foreign_result_id in (
            (owner_client, owner_cookies, member_event_id, member_result_id),
            (member_client, member_cookies, owner_event_id, owner_result_id),
        ):
            assert (
                client.get(f"/api/v1/history/{foreign_event_id}", cookies=cookies).status_code
                == 404
            )
            assert (
                client.get(
                    f"/api/v1/saved-forecasts/{foreign_event_id}", cookies=cookies
                ).status_code
                == 404
            )
            assert (
                client.get(f"/api/v1/forecasts/{foreign_result_id}", cookies=cookies).status_code
                == 404
            )
            assert (
                client.get(
                    f"/api/v1/history/{foreign_event_id}/prices", cookies=cookies
                ).status_code
                == 404
            )
            filtered = client.get(
                "/api/v1/history",
                params={"event_id": foreign_event_id},
                cookies=cookies,
            )
            assert filtered.status_code == 200, filtered.text
            assert filtered.json()["total"] == 0

        owner_fresh_response = owner_client.post(
            f"/api/v1/history/{owner_event_id}/reconstructions",
            json={
                "analysis_kind": "fresh_historical_reconstruction",
                "cutoff": "2025-01-10T16:55:00Z",
            },
            headers={"x-csrf-token": owner_csrf},
            cookies=owner_cookies,
        )
        member_fresh_response = member_client.post(
            f"/api/v1/history/{member_event_id}/reconstructions",
            json={
                "analysis_kind": "fresh_historical_reconstruction",
                "cutoff": "2025-01-10T16:55:00Z",
            },
            headers={"x-csrf-token": member_csrf},
            cookies=member_cookies,
        )
        assert owner_fresh_response.status_code == 201, owner_fresh_response.text
        assert member_fresh_response.status_code == 201, member_fresh_response.text
        owner_fresh = owner_fresh_response.json()
        member_fresh = member_fresh_response.json()
        assert owner_fresh["source_event_id"] == owner_event_id
        assert member_fresh["source_event_id"] == member_event_id
        assert owner_fresh["event"]["id"] != owner_event_id
        assert member_fresh["event"]["id"] != member_event_id

        member_foreign_reconstruction = member_client.post(
            f"/api/v1/history/{owner_event_id}/reconstructions",
            json={"cutoff": "2025-01-10T16:55:00Z"},
            headers={"x-csrf-token": member_csrf},
            cookies=member_cookies,
        )
        owner_foreign_reconstruction = owner_client.post(
            f"/api/v1/history/{member_event_id}/reconstructions",
            json={"cutoff": "2025-01-10T16:55:00Z"},
            headers={"x-csrf-token": owner_csrf},
            cookies=owner_cookies,
        )
        assert member_foreign_reconstruction.status_code == 404
        assert owner_foreign_reconstruction.status_code == 404
        assert (
            member_foreign_reconstruction.json()["error"]["code"] == "historical_source_unavailable"
        )
        assert (
            owner_foreign_reconstruction.json()["error"]["code"] == "historical_source_unavailable"
        )
        assert "ACDC" not in member_foreign_reconstruction.text
        assert "SPY" not in owner_foreign_reconstruction.text

        owner_outcome_response = owner_client.post(
            f"/api/v1/forecasts/{owner_result_id}/outcomes",
            json={
                "observed_close": 24.0,
                "observed_at": "2025-01-13T16:01:00-05:00",
                "state": "observed",
                "note": "owner observation",
            },
            headers={"x-csrf-token": owner_csrf},
            cookies=owner_cookies,
        )
        member_outcome_response = member_client.post(
            f"/api/v1/forecasts/{member_result_id}/outcomes",
            json={
                "observed_close": 24.0,
                "observed_at": "2025-01-13T16:01:00-05:00",
                "state": "observed",
                "note": "member observation",
            },
            headers={"x-csrf-token": member_csrf},
            cookies=member_cookies,
        )
        assert owner_outcome_response.status_code == 201, owner_outcome_response.text
        assert member_outcome_response.status_code == 201, member_outcome_response.text
        owner_correction_response = owner_client.post(
            f"/api/v1/forecasts/{owner_result_id}/corrections",
            json={
                "observed_close": 24.2,
                "observed_at": "2025-01-13T16:02:00-05:00",
                "note": "owner correction",
            },
            headers={"x-csrf-token": owner_csrf},
            cookies=owner_cookies,
        )
        member_correction_response = member_client.post(
            f"/api/v1/forecasts/{member_result_id}/corrections",
            json={
                "observed_close": 24.2,
                "observed_at": "2025-01-13T16:02:00-05:00",
                "note": "member correction",
            },
            headers={"x-csrf-token": member_csrf},
            cookies=member_cookies,
        )
        assert owner_correction_response.status_code == 201, owner_correction_response.text
        assert member_correction_response.status_code == 201, member_correction_response.text
        for client, cookies, csrf_token, foreign_result_id in (
            (owner_client, owner_cookies, owner_csrf, member_result_id),
            (member_client, member_cookies, member_csrf, owner_result_id),
        ):
            rejected = client.post(
                f"/api/v1/forecasts/{foreign_result_id}/outcomes",
                json={
                    "observed_close": 24.1,
                    "observed_at": "2025-01-13T16:02:00-05:00",
                    "state": "observed",
                    "note": "forged owner outcome",
                },
                headers={"x-csrf-token": csrf_token},
                cookies=cookies,
            )
            assert rejected.status_code == 404
            rejected_correction = client.post(
                f"/api/v1/forecasts/{foreign_result_id}/corrections",
                json={
                    "observed_close": 24.1,
                    "observed_at": "2025-01-13T16:02:00-05:00",
                    "note": "forged owner correction",
                },
                headers={"x-csrf-token": csrf_token},
                cookies=cookies,
            )
            assert rejected_correction.status_code == 404

        owner_detail = owner_client.get(f"/api/v1/history/{owner_event_id}", cookies=owner_cookies)
        member_detail = member_client.get(
            f"/api/v1/history/{member_event_id}", cookies=member_cookies
        )
        assert owner_detail.status_code == 200, owner_detail.text
        assert member_detail.status_code == 200, member_detail.text
        assert [item["note"] for item in owner_detail.json()["results"][0]["outcomes"]] == [
            "owner observation",
            "owner correction",
        ]
        assert [item["note"] for item in member_detail.json()["results"][0]["outcomes"]] == [
            "member observation",
            "member correction",
        ]

        owner_list_items = owner_client.post(
            "/api/v1/lists",
            json={
                "kind": "portfolio",
                "item": {"symbol": "SPY", "asset_type": "etf", "quantity": 2.5},
            },
            headers={"x-csrf-token": owner_csrf},
            cookies=owner_cookies,
        )
        owner_watchlist = owner_client.post(
            "/api/v1/lists",
            json={"kind": "watchlist", "item": {"symbol": "ACDC", "asset_type": "stock"}},
            headers={"x-csrf-token": owner_csrf},
            cookies=owner_cookies,
        )
        member_list_items = member_client.post(
            "/api/v1/lists",
            json={
                "kind": "portfolio",
                "item": {"symbol": "ACDC", "asset_type": "stock", "quantity": 7.0},
            },
            headers={"x-csrf-token": member_csrf},
            cookies=member_cookies,
        )
        member_watchlist = member_client.post(
            "/api/v1/lists",
            json={"kind": "watchlist", "item": {"symbol": "SPY", "asset_type": "etf"}},
            headers={"x-csrf-token": member_csrf},
            cookies=member_cookies,
        )
        assert owner_list_items.status_code == 201, owner_list_items.text
        assert owner_watchlist.status_code == 201, owner_watchlist.text
        assert member_list_items.status_code == 201, member_list_items.text
        assert member_watchlist.status_code == 201, member_watchlist.text
        assert [
            item["symbol"]
            for item in owner_client.get(
                "/api/v1/lists", params={"kind": "portfolio"}, cookies=owner_cookies
            ).json()["items"]
        ] == ["SPY"]
        assert [
            item["symbol"]
            for item in owner_client.get(
                "/api/v1/lists", params={"kind": "watchlist"}, cookies=owner_cookies
            ).json()["items"]
        ] == ["ACDC"]
        assert [
            item["symbol"]
            for item in member_client.get(
                "/api/v1/lists", params={"kind": "portfolio"}, cookies=member_cookies
            ).json()["items"]
        ] == ["ACDC"]
        assert [
            item["symbol"]
            for item in member_client.get(
                "/api/v1/lists", params={"kind": "watchlist"}, cookies=member_cookies
            ).json()["items"]
        ] == ["SPY"]
        for (
            client,
            cookies,
            csrf_token,
            foreign_portfolio_symbol,
            foreign_watchlist_symbol,
            own_watchlist_symbol,
        ) in (
            (owner_client, owner_cookies, owner_csrf, "ACDC", "SPY", "ACDC"),
            (member_client, member_cookies, member_csrf, "SPY", "ACDC", "SPY"),
        ):
            for kind, symbol in (
                ("portfolio", foreign_portfolio_symbol),
                ("watchlist", foreign_watchlist_symbol),
            ):
                rejected_delete = client.delete(
                    "/api/v1/lists",
                    params={"kind": kind, "symbol": symbol},
                    headers={"x-csrf-token": csrf_token},
                    cookies=cookies,
                )
                assert rejected_delete.status_code == 404
            own_watchlist = client.get(
                "/api/v1/lists", params={"kind": "watchlist"}, cookies=cookies
            )
            assert own_watchlist.status_code == 200, own_watchlist.text
            assert [item["symbol"] for item in own_watchlist.json()["items"]] == [
                own_watchlist_symbol
            ]

        for operation in (
            member_client.post(
                "/api/v1/operations/backups",
                json={"name": "member-must-not-backup.spbackup"},
                headers={"x-csrf-token": member_csrf},
                cookies=member_cookies,
            ),
            member_client.get("/api/v1/operations/backups/status", cookies=member_cookies),
            member_client.post(
                "/api/v1/operations/restores",
                json={"name": "member-must-not-restore.spbackup", "promote": False},
                headers={"x-csrf-token": member_csrf},
                cookies=member_cookies,
            ),
            member_client.post(
                "/api/v1/operations/restores",
                json={"name": "member-must-not-promote.spbackup", "promote": True},
                headers={"x-csrf-token": member_csrf},
                cookies=member_cookies,
            ),
        ):
            assert operation.status_code == 403, operation.text
            assert operation.json()["error"]["code"] == "authorization_denied"

        owner_history = owner_client.get("/api/v1/history", cookies=owner_cookies).json()
        member_history = member_client.get("/api/v1/history", cookies=member_cookies).json()
        owner_fresh_event_id = owner_fresh["event"]["id"]
        member_fresh_event_id = member_fresh["event"]["id"]
        owner_failed_item = next(
            item
            for item in owner_history["items"]
            if item["requested_source_event_id"] == member_event_id
        )
        member_failed_item = next(
            item
            for item in member_history["items"]
            if item["requested_source_event_id"] == owner_event_id
        )
        assert owner_failed_item["source_event_id"] is None
        assert owner_failed_item["status"] == "failed"
        assert owner_failed_item["forecast_available"] is False
        assert member_failed_item["source_event_id"] is None
        assert member_failed_item["status"] == "failed"
        assert member_failed_item["forecast_available"] is False
        owner_failed_event_id = owner_failed_item["id"]
        member_failed_event_id = member_failed_item["id"]
        owner_event_ids = {
            owner_event_id,
            owner_repeat["event"]["id"],
            owner_fresh_event_id,
            owner_failed_event_id,
        }
        member_event_ids = {
            member_event_id,
            member_repeat["event"]["id"],
            member_fresh_event_id,
            member_failed_event_id,
        }
        assert {item["id"] for item in owner_history["items"]} == owner_event_ids
        assert {item["id"] for item in member_history["items"]} == member_event_ids
        assert owner_event_ids.isdisjoint(member_event_ids)
        assert owner_history["total"] == member_history["total"] == 4
        export_payloads: dict[str, dict] = {}
        for label, client, cookies, expected_ids, included_symbol, excluded_symbol in (
            ("owner", owner_client, owner_cookies, owner_event_ids, "ACDC", "SPY"),
            ("member", member_client, member_cookies, member_event_ids, "SPY", "ACDC"),
        ):
            exported = client.get("/api/v1/history-export.json", cookies=cookies)
            assert exported.status_code == 200, exported.text
            payload = exported.json()
            export_payloads[label] = payload
            assert payload["counts"] == {"events": 4, "runs": 2, "results": 4}
            assert {
                record["event_id"]
                for record in payload["records"]
                if record["record_type"] == "event"
            } == expected_ids
            assert included_symbol in exported.text
            assert excluded_symbol not in exported.text
            csv_export = client.get("/api/v1/history-export.csv", cookies=cookies)
            assert csv_export.status_code == 200, csv_export.text
            assert included_symbol in csv_export.text
            assert excluded_symbol not in csv_export.text

        def outcome_notes(payload: dict) -> set[str]:
            return {
                outcome["note"]
                for record in payload["records"]
                if record["record_type"] == "result"
                for outcome in record["data"].get("outcomes", [])
            }

        assert outcome_notes(export_payloads["owner"]) == {
            "owner observation",
            "owner correction",
        }
        assert outcome_notes(export_payloads["member"]) == {
            "member observation",
            "member correction",
        }


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
        application.state.assistant.storage.create_consent(
            UserRecord.from_record(record).id,
            model_id="catalog-model",
            policy_version="policy-v1",
            accepted_terms=True,
            data_collection_opt_in=True,
            recorded_at=NOW,
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


def test_promoted_restore_rejects_backup_with_superseded_data_collection_consent(tmp_path):
    """An older backup cannot restore data-collection consent after the owner revokes it."""

    settings = Settings(
        data_dir=tmp_path,
        database_path=tmp_path / "stock_probs.sqlite3",
        backup_dir=tmp_path / "backups",
        provider="fixture",
        auth_mode="local",
        auth_session_secret="r" * 48,
        auth_public_origin="http://testserver",
    )
    application = create_app(settings, FixtureProvider(), lambda: NOW, auth_store=MemoryAuthStore())
    with TestClient(application) as client:
        record = application.state.auth.ensure_local_bootstrap(
            "admin", "development-admin-password-123", NOW
        )
        owner_id = UserRecord.from_record(record).id
        storage = application.state.assistant.storage
        storage.create_consent(
            owner_id,
            model_id="catalog-model",
            policy_version="policy-v1",
            accepted_terms=True,
            data_collection_opt_in=True,
            recorded_at=NOW,
        )
        target = application.state.backups.create("old-consent-restore.spbackup")
        storage.create_consent(
            owner_id,
            model_id="catalog-model",
            policy_version="policy-v1",
            accepted_terms=True,
            data_collection_opt_in=False,
            recorded_at=NOW + timedelta(seconds=1),
        )
        issue = application.state.auth.issue_session(
            application.state.auth.user_from_record(record), datetime.now(UTC), "passkey"
        )
        restored = client.post(
            "/api/v1/operations/restores",
            json={"name": target["name"], "promote": True},
            headers={"x-csrf-token": issue.csrf_token},
            cookies={
                SESSION_COOKIE_NAME: issue.session_token,
                CSRF_COOKIE_NAME: issue.csrf_token,
            },
        )

        assert restored.status_code == 403
        assert (
            application.state.assistant.storage.current_consent(
                owner_id, "catalog-model", "policy-v1"
            )["data_collection_opt_in"]
            is False
        )


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
    authorization = manager.begin_github(NOW, caller_identity="198.51.100.10")
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
    """Per-caller admission runs before the retained process-wide safety ceiling."""

    monkeypatch.setattr("stock_probs.auth.MAX_OAUTH_STARTS_PER_WINDOW", 3)
    monkeypatch.setattr("stock_probs.auth.MAX_OAUTH_STARTS_PER_CALLER_WINDOW", 2)
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
    caller = "198.51.100.10"
    manager.begin_github(NOW, caller_identity=caller)
    manager.begin_github(NOW + timedelta(seconds=1), caller_identity=caller)
    with pytest.raises(OAuthStartLimited):
        manager.begin_github(NOW + timedelta(seconds=2), caller_identity=caller)
    manager.begin_github(NOW + timedelta(seconds=2), caller_identity="198.51.100.11")
    with pytest.raises(AuthUnavailable):
        manager.begin_github(NOW + timedelta(seconds=3), caller_identity="198.51.100.12")
    manager.begin_github(NOW + timedelta(seconds=62), caller_identity=caller)


def test_github_start_isolates_trusted_cloudflare_callers_and_invitation_redeems(tmp_path) -> None:
    """The trusted connector IP separates callers for both public OAuth entry points."""

    settings = Settings(
        data_dir=tmp_path,
        database_path=tmp_path / "stock_probs.sqlite3",
        backup_dir=tmp_path / "backups",
        provider="fixture",
        environment="test",
        auth_mode="github",
        auth_session_secret="o" * 48,
        auth_public_origin="http://testserver",
        github_client_id="client-id",
        github_client_secret="client-secret",  # noqa: S106
        github_redirect_uri="http://testserver/api/v1/auth/github/callback",
        owner_github_id=24680,
    )
    application = create_app(settings, FixtureProvider(), lambda: NOW)
    with TestClient(application, client=("127.0.0.1", 51000)) as client:
        for index in range(8):
            response = client.get(
                "/api/v1/auth/github/start",
                headers={
                    "CF-Connecting-IP": "198.51.100.10",
                    "X-Forwarded-For": f"203.0.113.{index + 1}",
                },
                follow_redirects=False,
            )
            assert response.status_code == 302, response.text
        limited = client.get(
            "/api/v1/auth/github/start",
            headers={
                "CF-Connecting-IP": "198.51.100.10",
                "X-Forwarded-For": "203.0.113.200",
            },
            follow_redirects=False,
        )
        assert limited.status_code == 429
        assert limited.headers["retry-after"] == "60"
        assert limited.json()["error"]["code"] == "oauth_start_limited"

        other_caller = client.get(
            "/api/v1/auth/github/start",
            headers={"CF-Connecting-IP": "198.51.100.11"},
            follow_redirects=False,
        )
        assert other_caller.status_code == 302, other_caller.text

        invitation_code, _ = application.state.auth.create_invitation(
            13579, 1, datetime.now(UTC), github_login="invited"
        )
        for _ in range(8):
            redeemed = client.post(
                "/api/v1/auth/invites/redeem",
                json={"code": invitation_code},
                headers={"CF-Connecting-IP": "198.51.100.12"},
            )
            assert redeemed.status_code == 200, redeemed.text
        invitation_limited = client.post(
            "/api/v1/auth/invites/redeem",
            json={"code": invitation_code},
            headers={"CF-Connecting-IP": "198.51.100.12"},
        )
        assert invitation_limited.status_code == 429
        assert (
            application.state.auth.inspect_invitation(invitation_code, datetime.now(UTC))[
                "consumed_at"
            ]
            is None
        )

        with application.state.repository.connect() as connection:
            caller_hashes = {
                row[0]
                for row in connection.execute(
                    "SELECT DISTINCT caller_key_hash FROM oauth_states"
                ).fetchall()
            }
        assert len(caller_hashes) == 3
        assert all(len(value) == 64 for value in caller_hashes)
        assert "198.51.100.10" not in caller_hashes


def test_github_start_ignores_forwarded_identity_from_untrusted_peer(tmp_path) -> None:
    """A direct ASGI peer cannot vary its quota key with forwarded headers."""

    settings = Settings(
        data_dir=tmp_path,
        database_path=tmp_path / "stock_probs.sqlite3",
        backup_dir=tmp_path / "backups",
        provider="fixture",
        environment="test",
        auth_mode="github",
        auth_session_secret="p" * 48,
        auth_public_origin="http://testserver",
        github_client_id="client-id",
        github_client_secret="client-secret",  # noqa: S106
        github_redirect_uri="http://testserver/api/v1/auth/github/callback",
        owner_github_id=24680,
    )
    application = create_app(settings, FixtureProvider(), lambda: NOW)
    with TestClient(application, client=("198.51.100.20", 52000)) as client:
        for index in range(8):
            response = client.get(
                "/api/v1/auth/github/start",
                headers={
                    "CF-Connecting-IP": f"198.51.100.{index + 30}",
                    "X-Forwarded-For": f"203.0.113.{index + 30}",
                },
                follow_redirects=False,
            )
            assert response.status_code == 302, response.text
        forged = client.get(
            "/api/v1/auth/github/start",
            headers={
                "CF-Connecting-IP": "198.51.100.99",
                "X-Forwarded-For": "203.0.113.99",
            },
            follow_redirects=False,
        )
        assert forged.status_code == 429

    with TestClient(application, client=("198.51.100.21", 52001)) as second_client:
        independent = second_client.get(
            "/api/v1/auth/github/start",
            headers={
                "CF-Connecting-IP": "198.51.100.99",
                "X-Forwarded-For": "203.0.113.99",
            },
            follow_redirects=False,
        )
        assert independent.status_code == 302, independent.text


def test_github_callback_sets_provisional_cookie_and_consumes_invitation_once(tmp_path) -> None:
    """The browser receives an authenticator handoff, never an OAuth token or reusable code."""

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
        assert callback.headers["location"].startswith("/authenticator?mode=enroll")
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


def test_github_session_requires_totp_even_for_the_admin_owner(tmp_path) -> None:
    """A provisional cookie cannot reach private data but can revoke itself."""

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
        assert response.json()["error"]["code"] == "totp_required"
        provisional_page = client.get(
            "/overview",
            headers=navigation,
            cookies={SESSION_COOKIE_NAME: issue.session_token},
            follow_redirects=False,
        )
        assert provisional_page.status_code == 303
        assert provisional_page.headers["location"].startswith("/authenticator?mode=enroll")

        missing_csrf = client.post(
            "/api/v1/auth/logout",
            headers={"Origin": "http://testserver"},
            cookies={SESSION_COOKIE_NAME: issue.session_token},
        )
        assert missing_csrf.status_code == 403
        assert missing_csrf.json()["error"]["code"] == "csrf_rejected"

        cross_origin = client.post(
            "/api/v1/auth/logout",
            headers={
                "Origin": "https://attacker.example",
                "x-csrf-token": issue.csrf_token,
            },
            cookies={
                SESSION_COOKIE_NAME: issue.session_token,
                CSRF_COOKIE_NAME: issue.csrf_token,
            },
        )
        assert cross_origin.status_code == 403
        assert cross_origin.json()["error"]["code"] == "origin_rejected"

        logout = client.post(
            "/api/v1/auth/logout",
            headers={
                "Origin": "http://testserver",
                "x-csrf-token": issue.csrf_token,
            },
            cookies={
                SESSION_COOKIE_NAME: issue.session_token,
                CSRF_COOKIE_NAME: issue.csrf_token,
            },
        )
        assert logout.status_code == 204, logout.text
        assert "Max-Age=0" in logout.headers.get("set-cookie", "")
        assert (
            client.get(
                "/api/v1/auth/session",
                cookies={SESSION_COOKIE_NAME: issue.session_token},
            ).json()["authenticated"]
            is False
        )


def test_provisional_github_session_cannot_register_second_passkey(tmp_path) -> None:
    """Production rejects both new WebAuthn credentials and legacy assertion ceremonies."""

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
        assertion = client.post(
            "/api/v1/auth/passkeys/authenticate/options",
            headers={"x-csrf-token": issue.csrf_token},
            cookies={
                SESSION_COOKIE_NAME: issue.session_token,
                CSRF_COOKIE_NAME: issue.csrf_token,
            },
        )
        assert assertion.status_code == 403
        assert assertion.json()["error"]["code"] == "authorization_denied"
        registration_finish = client.post(
            "/api/v1/auth/passkeys/register",
            json={"response": {}, "id": "retired-credential", "raw_id": "retired-raw-id"},
            headers={"x-csrf-token": issue.csrf_token},
            cookies={
                SESSION_COOKIE_NAME: issue.session_token,
                CSRF_COOKIE_NAME: issue.csrf_token,
            },
        )
        assert registration_finish.status_code == 403
        assert registration_finish.json()["error"]["code"] == "authorization_denied"
        assertion_finish = client.post(
            "/api/v1/auth/passkeys/authenticate",
            json={"response": {}, "id": "retired-credential", "raw_id": "retired-raw-id"},
            headers={"x-csrf-token": issue.csrf_token},
            cookies={
                SESSION_COOKIE_NAME: issue.session_token,
                CSRF_COOKIE_NAME: issue.csrf_token,
            },
        )
        assert assertion_finish.status_code == 403
        assert assertion_finish.json()["error"]["code"] == "authorization_denied"


def test_retired_passkey_session_is_rejected_in_production() -> None:
    """An old passkey-issued cookie cannot bootstrap authenticator enrollment."""

    manager, store, user = _github_totp_manager()
    session_value = "retired-passkey-session-token"
    token_hash = hashlib.sha256(session_value.encode()).hexdigest()
    store.auth_create_session(
        {
            "session_id": "retired-passkey-session-0001",
            "user_id": user.id,
            "token_hash": token_hash,
            "csrf_token_hash": hashlib.sha256(b"retired-passkey-csrf").hexdigest(),
            "auth_method": "passkey",
            "created_at": NOW.isoformat(),
            "last_seen_at": NOW.isoformat(),
            "idle_expires_at": (NOW + timedelta(hours=1)).isoformat(),
            "expires_at": (NOW + timedelta(days=1)).isoformat(),
        }
    )
    with pytest.raises(AuthenticationRequired):
        manager.authenticate(session_value, NOW + timedelta(seconds=1))
    assert store.sessions[token_hash]["revoked_at"] is not None

    mfa_session_value = "retired-passkey-mfa-session-token"
    mfa_token_hash = hashlib.sha256(mfa_session_value.encode()).hexdigest()
    store.auth_create_session(
        {
            "session_id": "retired-passkey-mfa-session-0001",
            "user_id": user.id,
            "token_hash": mfa_token_hash,
            "csrf_token_hash": hashlib.sha256(b"retired-passkey-mfa-csrf").hexdigest(),
            "auth_method": "github",
            "mfa_method": "passkey",
            "created_at": NOW.isoformat(),
            "last_seen_at": NOW.isoformat(),
            "idle_expires_at": (NOW + timedelta(hours=1)).isoformat(),
            "expires_at": (NOW + timedelta(days=1)).isoformat(),
        }
    )
    with pytest.raises(AuthenticationRequired):
        manager.authenticate(mfa_session_value, NOW + timedelta(seconds=1))
    assert store.sessions[mfa_token_hash]["revoked_at"] is not None


def test_passkey_deep_link_redirects_to_authenticator_and_rejects_external_next(tmp_path) -> None:
    """Legacy bookmarks reach the authenticator route without accepting an open redirect."""

    settings = Settings(
        data_dir=tmp_path,
        database_path=tmp_path / "stock_probs.sqlite3",
        backup_dir=tmp_path / "backups",
        provider="fixture",
        environment="test",
        auth_mode="github",
        auth_session_secret="p" * 48,
        auth_public_origin="http://testserver",
        github_client_id="client-id",
        github_client_secret="client-secret",  # noqa: S106
        github_redirect_uri="http://testserver/api/v1/auth/github/callback",
        owner_github_id=24680,
    )
    application = create_app(settings, FixtureProvider(), lambda: NOW, auth_store=MemoryAuthStore())
    with TestClient(application) as client:
        local = client.get(
            "/passkey?mode=verify&next=%2Ftools%2Fmarkets",
            follow_redirects=False,
        )
        assert local.status_code == 303
        assert local.headers["location"] == "/authenticator?mode=enroll&next=%2Ftools%2Fmarkets"
        external = client.get(
            "/passkey?next=https%3A%2F%2Fevil.example%2Fsteal",
            follow_redirects=False,
        )
        assert external.status_code == 303
        assert external.headers["location"] == "/authenticator?mode=enroll&next=%2Foverview"
