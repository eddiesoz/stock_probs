"""Focused configuration, SMTP-boundary, and admin API tests for email invitations."""

from __future__ import annotations

import smtplib
import ssl
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from stock_probs.api import create_app
from stock_probs.auth import (
    CSRF_COOKIE_NAME,
    SESSION_COOKIE_NAME,
    InvitationRejected,
    MemoryAuthStore,
)
from stock_probs.config import Settings
from stock_probs.invitation_mail import (
    SMTP_TIMEOUT_SECONDS,
    InvitationMailSettings,
    InviteEmailError,
    InviteEmailSubmission,
    send_invitation_email,
    validate_email_address,
)
from stock_probs.provider import FixtureProvider
from stock_probs.schemas import AuthEmailInvitationRequest

FIXED_NOW = datetime(2026, 9, 30, 12, 0, tzinfo=UTC)
SMTP_ENV = {
    "STOCK_PROBS_INVITE_SMTP_HOST": "smtp.example.test",
    "STOCK_PROBS_INVITE_SMTP_PORT": "465",
    "STOCK_PROBS_INVITE_SMTP_USERNAME": "mailer-user",
    "STOCK_PROBS_INVITE_SMTP_PASSWORD": "private-mail-password",
    "STOCK_PROBS_INVITE_SMTP_SECURITY": "implicit_tls",
    "STOCK_PROBS_INVITE_EMAIL_FROM": "invites@example.test",
}


def _mail_settings(security: str = "implicit_tls", port: int = 465) -> InvitationMailSettings:
    """Return a valid isolated SMTP configuration for fake-transport tests."""

    return InvitationMailSettings(
        host="smtp.example.test",
        port=port,
        username="mailer-user",
        password="private-mail-password",  # noqa: S106
        security=security,
        from_address="invites@example.test",
    )


@pytest.mark.parametrize(
    "security,port", [("implicit_tls", 465), ("implicit_tls", 2465), ("starttls", 587)]
)
def test_invitation_smtp_uses_verified_tls_and_returns_only_submission_metadata(
    monkeypatch: pytest.MonkeyPatch, security: str, port: int
) -> None:
    """Both supported SMTP modes use verified TLS and never return mail credentials or code."""

    calls: list[tuple[object, ...]] = []
    sent_messages: list[EmailMessage] = []

    class FakeSmtp:
        """Record protocol operations without opening a socket or sending a message."""

        def __init__(self, host: str, configured_port: int, **kwargs: object) -> None:
            calls.append(("connect", host, configured_port, kwargs))

        def __enter__(self) -> FakeSmtp:
            return self

        def __exit__(self, *args: object) -> None:
            del args

        def ehlo(self) -> tuple[int, bytes]:
            calls.append(("ehlo",))
            return 250, b"ok"

        def starttls(self, *, context: ssl.SSLContext) -> tuple[int, bytes]:
            calls.append(("starttls", context))
            return 220, b"ready"

        def login(self, username: str, password: str) -> tuple[int, bytes]:
            calls.append(("login", username, password))
            return 235, b"ok"

        def send_message(self, message: EmailMessage) -> dict[str, tuple[int, bytes]]:
            sent_messages.append(message)
            return {}

    if security == "implicit_tls":
        monkeypatch.setattr("stock_probs.invitation_mail.smtplib.SMTP_SSL", FakeSmtp)
    else:
        monkeypatch.setattr("stock_probs.invitation_mail.smtplib.SMTP", FakeSmtp)

    code = "one-time-invitation-code-that-is-not-a-url"
    expires_at = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)
    submission = send_invitation_email(
        _mail_settings(security, port),
        public_origin="https://ledger.example/",
        recipient="member@example.test",
        github_id=24680,
        github_login="member-login",
        code=code,
        expires_at=expires_at,
    )

    assert len(submission.submission_id) == 32
    assert submission.submitted_at.tzinfo is not None
    assert len(sent_messages) == 1
    message = sent_messages[0]
    plain = message.get_body(preferencelist=("plain",))
    rich = message.get_body(preferencelist=("html",))
    assert plain is not None and rich is not None
    plain_body = plain.get_content()
    rich_body = rich.get_content()
    assert code in plain_body and code in rich_body
    assert "https://ledger.example/invite" in plain_body
    assert 'href="https://ledger.example/invite"' in rich_body
    assert f"/invite?{code}" not in plain_body + rich_body
    assert "2026-10-01T12:00:00Z" in plain_body + rich_body
    assert "GitHub account ID 24680" in plain_body
    assert "only that numeric GitHub account can use it" in plain_body
    assert message["To"] == "member@example.test"
    assert "member@example.test" not in repr(submission)
    assert code not in repr(submission)
    assert calls[0][0] == "connect"
    assert calls[0][1:3] == ("smtp.example.test", port)
    assert calls[0][3]["timeout"] == SMTP_TIMEOUT_SECONDS
    if security == "starttls":
        tls_context = next(call[1] for call in calls if call[0] == "starttls")
        assert isinstance(tls_context, ssl.SSLContext)
        assert tls_context.verify_mode == ssl.CERT_REQUIRED
        assert tls_context.check_hostname is True
        assert [call[0] for call in calls].count("ehlo") == 2
    else:
        tls_context = calls[0][3]["context"]
        assert isinstance(tls_context, ssl.SSLContext)
        assert tls_context.verify_mode == ssl.CERT_REQUIRED
        assert tls_context.check_hostname is True


def test_invitation_smtp_failure_is_safe_and_does_not_expose_recipient_or_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SMTP transport and recipient rejection details stay out of the public exception."""

    class FailingSmtp:
        """Raise an SMTP authentication error without contacting a server."""

        def __init__(self, *_args: object, **_kwargs: object) -> None:
            pass

        def __enter__(self) -> FailingSmtp:
            return self

        def __exit__(self, *args: object) -> None:
            del args

        def ehlo(self) -> tuple[int, bytes]:
            return 250, b"ok"

        def login(self, *_args: object) -> None:
            raise smtplib.SMTPAuthenticationError(
                535, b"authentication failed for member@example.test"
            )

    monkeypatch.setattr("stock_probs.invitation_mail.smtplib.SMTP_SSL", FailingSmtp)
    code = "one-time-code-that-must-not-appear-in-errors"
    with pytest.raises(InviteEmailError) as failure:
        send_invitation_email(
            _mail_settings(),
            public_origin="https://ledger.example",
            recipient="member@example.test",
            github_id=24680,
            github_login=None,
            code=code,
            expires_at=datetime(2026, 10, 1, 12, 0, tzinfo=UTC),
        )

    assert failure.value.status_code == 502
    assert failure.value.code == "invite_email_failed"
    assert "member@example.test" not in str(failure.value)
    assert code not in str(failure.value)
    assert "authentication failed" not in str(failure.value)


@pytest.mark.parametrize(
    "invalid",
    ["", "recipient", "name@localhost", "bad..dots@example.test", "a@b.test\r\nBcc:x@y.test"],
)
def test_invitation_email_validator_rejects_header_and_address_injection(invalid: str) -> None:
    """Only bounded ASCII addr-spec values can become SMTP headers or recipients."""

    with pytest.raises(ValueError):
        validate_email_address(invalid)


@pytest.mark.parametrize(
    "github_login", ["-leading", "trailing-", "a" * 40, "аdmin", "safe\u202ename"]
)
def test_email_invitation_login_label_rejects_non_github_or_bidirectional_text(
    github_login: str,
) -> None:
    """The email-specific login label uses GitHub's bounded ASCII username form."""

    with pytest.raises(ValidationError):
        AuthEmailInvitationRequest(
            github_id=24680,
            github_login=github_login,
            email="member@example.test",
        )


@pytest.mark.parametrize("github_id", [True, False, "24680", "1", 24680.0, 0, -1, 2_147_483_648])
def test_email_invitation_github_id_is_strict_and_positive(github_id: object) -> None:
    """Email invites reject coercible, boolean, and out-of-range GitHub IDs."""

    with pytest.raises(ValidationError):
        AuthEmailInvitationRequest.model_validate(
            {"email": "member@example.test", "github_id": github_id}
        )


@pytest.mark.parametrize("field", [{}, {"github_id": None}, {"github_id": 24680}])
def test_email_invitation_github_id_accepts_omitted_null_or_valid(field: dict[str, object]) -> None:
    """Email-only and numeric-ID-bound invitations keep their explicit valid forms."""

    payload = AuthEmailInvitationRequest.model_validate({"email": "member@example.test", **field})
    assert payload.github_id == field.get("github_id")


def test_email_invitation_login_hint_requires_numeric_id() -> None:
    """A GitHub login remains only a display hint for an explicit numeric ID."""

    with pytest.raises(ValidationError, match="github_login requires github_id"):
        AuthEmailInvitationRequest.model_validate(
            {"email": "member@example.test", "github_login": "member"}
        )
    payload = AuthEmailInvitationRequest.model_validate(
        {"email": "member@example.test", "github_id": 24680, "github_login": "member"}
    )
    assert payload.github_id == 24680
    assert payload.github_login == "member"


def test_smtp_environment_is_disabled_when_blank_and_rejects_partial_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Blank Compose defaults disable email, while partial configuration fails closed."""

    for name in SMTP_ENV:
        monkeypatch.setenv(name, " ")
    disabled = Settings.from_env()
    assert disabled.email_invites_enabled is False

    monkeypatch.setenv("STOCK_PROBS_INVITE_SMTP_HOST", SMTP_ENV["STOCK_PROBS_INVITE_SMTP_HOST"])
    monkeypatch.setenv(
        "STOCK_PROBS_INVITE_SMTP_PASSWORD", SMTP_ENV["STOCK_PROBS_INVITE_SMTP_PASSWORD"]
    )
    with pytest.raises(ValueError) as failure:
        Settings.from_env()
    assert SMTP_ENV["STOCK_PROBS_INVITE_SMTP_PASSWORD"] not in str(failure.value)


def test_smtp_environment_validates_mode_port_and_hides_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A complete matching SMTP configuration is available without credential repr leakage."""

    for name, value in SMTP_ENV.items():
        monkeypatch.setenv(name, value)
    settings = Settings.from_env()
    assert settings.email_invites_enabled is True
    assert settings.invitation_mail is not None
    assert settings.invitation_mail.security == "implicit_tls"
    assert settings.invitation_mail.port == 465
    assert SMTP_ENV["STOCK_PROBS_INVITE_SMTP_PASSWORD"] not in repr(settings)
    assert SMTP_ENV["STOCK_PROBS_INVITE_SMTP_USERNAME"] not in repr(settings)

    monkeypatch.setenv("STOCK_PROBS_INVITE_SMTP_PORT", "2465")
    alternate_port_settings = Settings.from_env()
    assert alternate_port_settings.invitation_mail is not None
    assert alternate_port_settings.invitation_mail.port == 2465

    monkeypatch.setenv("STOCK_PROBS_INVITE_SMTP_SECURITY", "starttls")
    with pytest.raises(ValueError, match="implicit_tls on 465 or 2465"):
        Settings.from_env()


@pytest.mark.parametrize("security,port", [("implicit_tls", 587), ("starttls", 2465)])
def test_smtp_rejects_mismatched_security_and_port(security: str, port: int) -> None:
    """Only the configured TLS mode may use each supported SMTP submission port."""

    with pytest.raises(ValueError, match="implicit_tls on 465 or 2465"):
        _mail_settings(security, port)


def _github_admin_app(tmp_path, *, mail_settings: InvitationMailSettings | None):
    """Build an isolated GitHub-authenticated app and a TOTP-bound administrator session."""

    settings = Settings(
        data_dir=tmp_path,
        database_path=tmp_path / "stock_probs.sqlite3",
        backup_dir=tmp_path / "backups",
        provider="fixture",
        environment="test",
        auth_mode="github",
        auth_session_secret="a" * 48,
        auth_public_origin="http://testserver",
        github_client_id="client-id",
        github_client_secret="client-secret",  # noqa: S106
        github_redirect_uri="http://testserver/api/v1/auth/github/callback",
        owner_github_id=99999,
        invitation_mail=mail_settings,
    )
    store = MemoryAuthStore()
    owner_record = store.auth_create_user(
        {
            "github_id": 99999,
            "github_login": "owner",
            "role": "admin",
            "status": "active",
        }
    )
    store.totp_factors[1] = {"id": 7, "revoked_at": None, "last_totp_step": -1}
    session_now = datetime.now(UTC)
    app = create_app(settings, FixtureProvider(), lambda: session_now, auth_store=store)
    user = app.state.auth.user_from_record(owner_record)
    issue = app.state.auth.issue_session(
        user,
        session_now,
        "github",
        mfa_method="totp",
        expected_factor_id=7,
    )
    cookies = {
        SESSION_COOKIE_NAME: issue.session_token,
        CSRF_COOKIE_NAME: issue.csrf_token,
    }
    return app, store, issue, cookies


def test_email_invitation_requires_admin_csrf_and_returns_no_bearer_code(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The email endpoint sends only after admin CSRF validation and returns safe metadata."""

    app, _store, issue, cookies = _github_admin_app(tmp_path, mail_settings=_mail_settings())
    submissions: list[dict[str, object]] = []
    reject_submission = False

    def fake_send(settings: InvitationMailSettings, **kwargs: object) -> InviteEmailSubmission:
        submissions.append({"settings": settings, **kwargs})
        if reject_submission:
            raise InviteEmailError()
        return InviteEmailSubmission("f" * 32, FIXED_NOW)

    monkeypatch.setattr("stock_probs.api.send_invitation_email", fake_send)
    with TestClient(app) as client:
        listing = client.get("/api/v1/auth/invites", cookies=cookies)
        assert listing.status_code == 200
        assert listing.json()["email_invites_enabled"] is True

        payload = {
            "github_id": 24680,
            "github_login": "member-login",
            "email": "member@example.test",
        }
        headers = {"Origin": "http://testserver"}
        missing_csrf = client.post(
            "/api/v1/auth/invites/email", json=payload, headers=headers, cookies=cookies
        )
        assert missing_csrf.status_code == 403
        assert missing_csrf.json()["error"]["code"] == "csrf_rejected"
        assert submissions == []

        submitted = client.post(
            "/api/v1/auth/invites/email",
            json=payload,
            headers={**headers, "x-csrf-token": issue.csrf_token},
            cookies=cookies,
        )
        assert submitted.status_code == 201, submitted.text
        assert submitted.headers["cache-control"] == "no-store"
        body = submitted.json()
        assert body["submission_status"] == "smtp_accepted"
        assert body["submission_id"] == "f" * 32
        assert body["github_id"] == 24680
        assert body["invite_url"] == "http://testserver/invite"
        assert "code" not in body
        assert "email" not in body
        assert "member@example.test" not in submitted.text
        assert len(submissions) == 1
        raw_code = submissions[0]["code"]
        assert isinstance(raw_code, str)
        invitation_now = datetime.now(UTC)
        invitation = app.state.auth.inspect_invitation(raw_code, invitation_now)
        assert invitation["github_id"] == 24680
        assert invitation["github_login"] == "member-login"
        consumed = app.state.auth.consume_invitation(raw_code, invitation_now)
        assert consumed["github_id"] == 24680
        with pytest.raises(InvitationRejected):
            app.state.auth.consume_invitation(raw_code, invitation_now)

        email_only = client.post(
            "/api/v1/auth/invites/email",
            json={"email": "new-member@example.test"},
            headers={**headers, "x-csrf-token": issue.csrf_token},
            cookies=cookies,
        )
        assert email_only.status_code == 201, email_only.text
        email_only_body = email_only.json()
        assert email_only_body["github_id"] is None
        assert email_only_body["github_login"] is None
        assert email_only_body["email_bound"] is True
        assert "new-member@example.test" not in email_only.text
        email_only_code = submissions[-1]["code"]
        email_only_invite = app.state.auth.inspect_invitation(email_only_code, datetime.now(UTC))
        assert email_only_invite["github_id"] is None
        assert isinstance(email_only_invite["email_hash"], str)
        assert "new-member@example.test" not in str(email_only_invite)
        assert len(email_only_invite["email_hash"]) == 64
        listed = client.get("/api/v1/auth/invites", cookies=cookies).json()["invitations"]
        listed_email_invite = next(invite for invite in listed if invite.get("email_bound") is True)
        assert listed_email_invite["github_id"] is None
        assert listed_email_invite["github_login"] is None
        assert listed_email_invite["consumed_at"] is None
        assert listed_email_invite["used_at"] is None
        assert "email" not in listed_email_invite and "email_hash" not in listed_email_invite

        reject_submission = True
        failed = client.post(
            "/api/v1/auth/invites/email",
            json={"github_id": 54321, "email": "private-recipient@example.test"},
            headers={**headers, "x-csrf-token": issue.csrf_token},
            cookies=cookies,
        )
        assert failed.status_code == 502
        assert failed.json()["error"]["code"] == "invite_email_failed"
        assert "private-recipient@example.test" not in failed.text
        assert submissions[-1]["code"] not in failed.text

        manual = client.post(
            "/api/v1/auth/invites",
            json={"github_id": 13579, "github_login": "manual-member"},
            headers={**headers, "x-csrf-token": issue.csrf_token},
            cookies=cookies,
        )
        assert manual.status_code == 201, manual.text
        assert len(manual.json()["code"]) >= 20


def test_email_invitation_capability_is_false_when_smtp_is_not_configured(tmp_path) -> None:
    """The admin list exposes a stable capability bit while the mailer is disabled."""

    app, _store, _issue, cookies = _github_admin_app(tmp_path, mail_settings=None)
    with TestClient(app) as client:
        listing = client.get("/api/v1/auth/invites", cookies=cookies)
        assert listing.status_code == 200, listing.text
        assert listing.json()["email_invites_enabled"] is False

        response = client.post(
            "/api/v1/auth/invites/email",
            json={"github_id": 24680, "email": "member@example.test"},
            headers={"Origin": "http://testserver", "x-csrf-token": _issue.csrf_token},
            cookies=cookies,
        )
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "authentication_unavailable"


@pytest.mark.parametrize("path", ["/api/v1/auth/invites", "/api/v1/auth/invites/email"])
def test_invitation_endpoint_rejects_member_role(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
    path: str,
) -> None:
    """An authenticated member cannot use admin invitation delivery."""

    app, store, _issue, _cookies = _github_admin_app(tmp_path, mail_settings=_mail_settings())
    member_record = store.auth_create_user(
        {
            "github_id": 77777,
            "github_login": "member",
            "role": "member",
            "status": "active",
        }
    )
    store.totp_factors[member_record["id"]] = {
        "id": 8,
        "revoked_at": None,
        "last_totp_step": -1,
    }
    member = app.state.auth.issue_session(
        app.state.auth.user_from_record(member_record),
        datetime.now(UTC),
        "github",
        mfa_method="totp",
        expected_factor_id=8,
    )
    cookies = {
        SESSION_COOKIE_NAME: member.session_token,
        CSRF_COOKIE_NAME: member.csrf_token,
    }
    send_calls: list[bool] = []
    monkeypatch.setattr(
        "stock_probs.api.send_invitation_email",
        lambda *_args, **_kwargs: send_calls.append(True),
    )
    with TestClient(app) as client:
        payload = (
            {"github_id": 24680, "github_login": "member-login"}
            if path == "/api/v1/auth/invites"
            else {"github_id": 24680, "email": "member@example.test"}
        )
        response = client.post(
            path,
            json=payload,
            headers={"Origin": "http://testserver", "x-csrf-token": member.csrf_token},
            cookies=cookies,
        )
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "authorization_denied"
        assert send_calls == []
        assert store.auth_list_invitations() == []


@pytest.mark.parametrize("path", ["/api/v1/auth/invites", "/api/v1/auth/invites/email"])
def test_invitation_endpoints_still_require_csrf(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
    path: str,
) -> None:
    """Reject browser mutation requests without CSRF before invitation side effects."""

    app, store, _issue, cookies = _github_admin_app(tmp_path, mail_settings=_mail_settings())
    submissions: list[dict[str, object]] = []

    def fake_send(_settings: InvitationMailSettings, **kwargs: object) -> InviteEmailSubmission:
        submissions.append(kwargs)
        return InviteEmailSubmission("d" * 32, FIXED_NOW)

    monkeypatch.setattr("stock_probs.api.send_invitation_email", fake_send)
    payload = (
        {"github_id": 24680, "github_login": "member-login"}
        if path == "/api/v1/auth/invites"
        else {"github_id": 24680, "email": "member@example.test"}
    )

    with TestClient(app) as client:
        response = client.post(
            path,
            json=payload,
            headers={"Origin": "http://testserver"},
            cookies=cookies,
        )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "csrf_rejected"
    assert store.auth_list_invitations() == []
    assert submissions == []


@pytest.mark.parametrize("path", ["/api/v1/auth/invites", "/api/v1/auth/invites/email"])
@pytest.mark.parametrize("proof_state", ["stale", "cleared"])
def test_invitation_mutations_require_fresh_totp_before_any_write_or_send(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
    path: str,
    proof_state: str,
) -> None:
    """Reject invitations unless the session still carries fresh TOTP proof."""

    app, store, issue, cookies = _github_admin_app(tmp_path, mail_settings=_mail_settings())
    session = store.sessions[issue.context.token_hash]
    if proof_state == "stale":
        session["mfa_verified_at"] = (datetime.now(UTC) - timedelta(minutes=10)).isoformat()
    else:
        session["mfa_verified_at"] = None

    submissions: list[dict[str, object]] = []

    def fake_send(_settings: InvitationMailSettings, **kwargs: object) -> InviteEmailSubmission:
        submissions.append(kwargs)
        return InviteEmailSubmission("e" * 32, FIXED_NOW)

    monkeypatch.setattr("stock_probs.api.send_invitation_email", fake_send)
    payload = (
        {"github_id": 24680, "github_login": "member-login"}
        if path == "/api/v1/auth/invites"
        else {"github_id": 24680, "email": "member@example.test"}
    )
    headers = {"Origin": "http://testserver", "x-csrf-token": issue.csrf_token}

    with TestClient(app) as client:
        response = client.post(path, json=payload, headers=headers, cookies=cookies)

    invitation_count = len(store.auth_list_invitations())
    send_count = len(submissions)
    assert response.status_code == 403, (
        f"unexpected invitation authorization result: status={response.status_code}, "
        f"stored_invitations={invitation_count}, mail_submissions={send_count}"
    )
    assert response.json()["error"]["code"] == "authorization_denied"
    assert store.auth_list_invitations() == []
    assert submissions == []
