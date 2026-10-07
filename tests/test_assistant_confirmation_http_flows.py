"""Public HTTP regressions for assistant confirmations and protected invitation handoff."""

from __future__ import annotations

import secrets
from collections.abc import AsyncIterator
from dataclasses import replace
from datetime import UTC, datetime, timedelta, tzinfo
from email.utils import parsedate_to_datetime
from http.cookies import SimpleCookie
from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from stock_probs import api as application_api
from stock_probs.api import create_app
from stock_probs.assistant import api as assistant_api
from stock_probs.assistant.schemas import AssistantModelPolicy
from stock_probs.auth import CSRF_COOKIE_NAME, SESSION_COOKIE_NAME
from stock_probs.config import Settings
from stock_probs.invitation_mail import InvitationMailSettings, InviteEmailSubmission
from stock_probs.provider import FixtureProvider
from stock_probs.totp import code_for_step, time_step

_NOW = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)
_CURRENT_TIME = _NOW
_MODEL_ID = "fixture-provider/confirmation-http-flow"


class _TestDatetime(datetime):
    """Keep repository, HTTP, and assistant checks on one controllable test clock."""

    @classmethod
    def now(cls, tz: tzinfo | None = None) -> datetime:
        if tz is None:
            return _CURRENT_TIME.replace(tzinfo=None)
        return _CURRENT_TIME.astimezone(tz)


class _Catalog:
    """Supply a synthetic policy row without a pinned production model identity."""

    def list_models(self) -> list[dict[str, object]]:
        policy = AssistantModelPolicy(
            model_id=_MODEL_ID,
            provider_id="fixture-provider",
            display_name="Synthetic confirmation-flow model",
            available=True,
            free=True,
            training=False,
            terms_url="https://models.example.test/terms",
            terms_reviewed_at="2026-10-01",
            policy_version="synthetic-confirmation-policy",
            disclosure="Synthetic model fixture; no upstream service is used.",
            data_collection_allowed=False,
            data_collection_default=False,
        )
        return [
            {
                "model_id": policy.model_id,
                "provider_id": policy.provider_id,
                "native_provider_id": policy.provider_id,
                "display_name": policy.display_name,
                "available": policy.available,
                "free": policy.free,
                "training": policy.training,
                "terms_url": policy.terms_url,
                "terms_reviewed_at": policy.terms_reviewed_at,
                "policy_version": policy.policy_version,
                "disclosure": policy.disclosure,
                "data_collection_allowed": policy.data_collection_allowed,
                "data_collection_default": policy.data_collection_default,
                "privacy_policy_version": policy.policy_version,
                "privacy_disclosure": policy.disclosure,
                "billing_class": "free",
                "billing_policy_version": policy.policy_version,
                "cost_disclosure": "Synthetic test fixture; no charge.",
                "enabled": True,
                "usable": True,
                "revision": 1,
            }
        ]


class _Runtime:
    """Satisfy the assistant lifecycle without launching a worker process."""

    async def start(self) -> None:
        return None

    def status(self) -> dict[str, object]:
        return {"status": "ready", "message": None}

    async def close(self) -> None:
        return None

    async def clear_conversation_cache(self, conversation_id: str) -> bool:
        del conversation_id
        return True


class _NoNetworkProvider:
    """Make accidental model access fail locally instead of opening a network connection."""

    def __init__(self) -> None:
        self.calls = 0

    async def proxy_chat_completion(
        self,
        provider_id: str,
        model_id: str,
        body: dict[str, object],
        **context: object,
    ) -> AsyncIterator[bytes]:
        del provider_id, model_id, body, context
        self.calls += 1
        raise AssertionError("the direct synthetic MCP proposal must not call a model provider")
        yield b""


def _synthetic_mail_settings() -> InvitationMailSettings:
    """Use inert test settings; the patched sender below never opens an SMTP connection."""

    return InvitationMailSettings(
        host="smtp.example.test",
        port=465,
        username="synthetic-mailer",
        password="synthetic-password",  # noqa: S106
        security="implicit_tls",
        from_address="invites@example.test",
    )


def _make_app(settings: Settings) -> tuple[FastAPI, _NoNetworkProvider]:
    """Build the normal repository/auth/service stack with only external seams replaced."""

    configured = replace(
        settings,
        environment="test",
        auth_mode="github",
        auth_session_secret="synthetic-confirmation-http-session-secret-000000",  # noqa: S106
        auth_public_origin="http://testserver",
        github_client_id="synthetic-client-id",
        github_client_secret="synthetic-client-secret",  # noqa: S106
        github_redirect_uri="http://testserver/api/v1/auth/github/callback",
        assistant_enabled=True,
        assistant_rollout_mode="invited",
        invitation_mail=_synthetic_mail_settings(),
    )
    providers = _NoNetworkProvider()
    app = create_app(
        configured,
        FixtureProvider(),
        lambda: _CURRENT_TIME,
        assistant_runtime=_Runtime(),
        assistant_catalog=_Catalog(),
        assistant_providers=providers,
    )
    return app, providers


def _install_session_cookies(client: TestClient, identity: dict[str, object]) -> None:
    """Select one test user's browser session on the shared local client."""

    client.cookies.clear()
    client.cookies.set(SESSION_COOKIE_NAME, cast(str, identity["token"]), path="/")
    client.cookies.set(CSRF_COOKIE_NAME, cast(str, identity["csrf"]), path="/")


def _enroll_user(
    app: FastAPI,
    client: TestClient,
    *,
    github_id: int,
    role: str,
) -> dict[str, object]:
    """Create a real repository account and finish its synthetic TOTP enrollment over HTTP."""

    repository = app.state.repository
    user = repository.auth_create_user(
        {
            "github_id": github_id,
            "github_login": f"fixture-{github_id}",
            "display_name": f"Synthetic user {github_id}",
            "role": role,
            "status": "active",
            "created_at": _CURRENT_TIME,
        }
    )
    provisional = app.state.auth.issue_session(
        app.state.auth.user_from_record(user), _CURRENT_TIME, "github"
    )
    provisional_identity: dict[str, object] = {
        "user_id": int(user["id"]),
        "token": provisional.session_token,
        "csrf": provisional.csrf_token,
    }
    _install_session_cookies(client, provisional_identity)
    headers = {"x-csrf-token": provisional.csrf_token}

    started = client.post("/api/v1/auth/totp/enroll/start", json={}, headers=headers)
    assert started.status_code == 200
    secret = cast(str, started.json()["secret"])
    code = code_for_step(secret, time_step(_CURRENT_TIME))
    finished = client.post(
        "/api/v1/auth/totp/enroll/finish",
        json={"code": code},
        headers=headers,
    )
    assert finished.status_code == 200
    finish_data = cast(dict[str, object], finished.json())
    csrf = cast(str, finish_data["csrf_token"])
    # httpx expires jar cookies by host time, which can be later than this fixture clock.
    set_cookie_headers = finished.headers.get_list("set-cookie")
    assert len(set_cookie_headers) == 2
    response_cookies = SimpleCookie()
    for set_cookie_header in set_cookie_headers:
        response_cookies.load(set_cookie_header)
    assert set(response_cookies) == {SESSION_COOKIE_NAME, CSRF_COOKIE_NAME}

    session_cookie = response_cookies[SESSION_COOKIE_NAME]
    csrf_cookie = response_cookies[CSRF_COOKIE_NAME]
    expires_at = datetime.fromisoformat(cast(str, finish_data["expires_at"]).replace("Z", "+00:00"))
    assert parsedate_to_datetime(session_cookie["expires"]) == expires_at
    assert parsedate_to_datetime(csrf_cookie["expires"]) == expires_at
    assert expires_at > _CURRENT_TIME
    assert session_cookie["path"] == csrf_cookie["path"] == "/"
    assert not session_cookie["domain"] and not csrf_cookie["domain"]
    assert session_cookie["samesite"].lower() == csrf_cookie["samesite"].lower() == "lax"
    assert session_cookie["httponly"]
    assert not csrf_cookie["httponly"]
    assert not session_cookie["secure"] and not csrf_cookie["secure"]

    token = session_cookie.value
    rotated_csrf = csrf_cookie.value
    assert token != cast(str, provisional_identity["token"])
    assert rotated_csrf == csrf
    assert rotated_csrf != cast(str, provisional_identity["csrf"])
    finished_identity = {"user_id": int(user["id"]), "token": token, "csrf": rotated_csrf}
    _install_session_cookies(client, finished_identity)
    assert client.cookies.get(SESSION_COOKIE_NAME) == token
    assert client.cookies.get(CSRF_COOKIE_NAME) == rotated_csrf
    context = app.state.auth.authenticate(token, _CURRENT_TIME)
    return {
        "user_id": int(user["id"]),
        "session_id": context.session_id,
        "token": token,
        "token_hash": context.token_hash,
        "csrf": csrf,
        "totp_secret": secret,
    }


def _propose_invitation(
    app: FastAPI,
    client: TestClient,
    machine: TestClient,
    identity: dict[str, object],
) -> tuple[dict[str, object], str, dict[str, object], str]:
    """Create a real owner-scoped turn and call its typed proposal through the HTTP MCP route."""

    context_response = client.get("/api/v1/assistant/context", params={"route": "/overview"})
    assert context_response.status_code == 200
    context = cast(dict[str, object], context_response.json()["context"])
    created = client.post(
        "/api/v1/assistant/conversations",
        json={"context": context},
        headers={"x-csrf-token": cast(str, identity["csrf"])},
    )
    assert created.status_code == 201
    conversation = cast(dict[str, object], created.json()["conversation"]["conversation"])
    conversation_id = cast(str, conversation["id"])
    assistant = app.state.assistant
    policy_version = assistant.policy(_MODEL_ID).policy_version
    assistant.storage.create_consent(
        int(identity["user_id"]),
        model_id=_MODEL_ID,
        policy_version=policy_version,
        accepted_terms=True,
        data_collection_opt_in=False,
        recorded_at=_CURRENT_TIME,
    )
    capability = secrets.token_urlsafe(32)
    turn = assistant.storage.create_turn(
        int(identity["user_id"]),
        conversation_id,
        prompt="Prepare the invitation settings handoff.",
        model_id=_MODEL_ID,
        policy_version=policy_version,
        context=context,
        context_version=cast(str, context["context_version"]),
        session_id=cast(str, identity["session_id"]),
        session_token_hash=cast(str, identity["token_hash"]),
        capability=capability,
        now=_CURRENT_TIME,
        expires_at=_CURRENT_TIME + timedelta(seconds=120),
    )
    assistant.storage.set_turn_status(
        int(identity["user_id"]),
        conversation_id,
        str(turn["id"]),
        status="running",
        now=_CURRENT_TIME,
    )
    execution_id = cast(str, turn["execution_id"])
    # The capability route deliberately rejects browser cookies, so its local model-side
    # connection uses a separate cookie-free client while sharing the same in-process app.
    proposed = machine.post(
        f"/api/v1/assistant/internal/mcp/{execution_id}",
        headers={"Authorization": f"Bearer {capability}"},
        json={
            "jsonrpc": "2.0",
            "id": "synthetic-invitation-proposal",
            "method": "tools/call",
            "params": {
                "name": "assistant.propose_action",
                "arguments": {"action_type": "invitation.create", "payload": {}},
            },
        },
    )
    assert proposed.status_code == 200, proposed.text
    result = proposed.json()["result"]
    assert result["isError"] is False
    assert "confirmation_phrase" not in str(result)

    events = assistant.storage.events_after(
        int(identity["user_id"]), conversation_id, str(turn["id"]), after=0, limit=20
    )
    proposal_events = [event["data"] for event in events if event["type"] == "proposed_action"]
    assert len(proposal_events) == 1
    card = cast(dict[str, object], proposal_events[0])
    assert card["action_type"] == "invitation.create"
    assistant.storage.set_turn_status(
        int(identity["user_id"]),
        conversation_id,
        str(turn["id"]),
        status="completed",
        now=_CURRENT_TIME,
    )
    assistant.storage.close_execution(execution_id, now=_CURRENT_TIME)
    return context, conversation_id, card, execution_id


@pytest.fixture(autouse=True)
def _freeze_http_and_assistant_clocks(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep cross-route expiry checks on one mutable synthetic clock."""

    global _CURRENT_TIME
    _CURRENT_TIME = _NOW
    monkeypatch.setattr(application_api, "datetime", _TestDatetime)
    monkeypatch.setattr(assistant_api, "datetime", _TestDatetime)


def test_public_confirmation_rejects_wrong_phrase_and_version_before_one_success(
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Wrong phrase/version leave the proposal untouched; a correct phrase is one-use."""

    app, providers = _make_app(settings)
    with TestClient(app, client=("127.0.0.1", 51061)) as machine:
        client = TestClient(app, client=("127.0.0.1", 51063))
        try:
            admin = _enroll_user(app, client, github_id=82001, role="admin")
            member = _enroll_user(app, client, github_id=82002, role="member")
            _install_session_cookies(client, admin)
            context, conversation_id, card, _execution_id = _propose_invitation(
                app, client, machine, admin
            )
            service = app.state.assistant
            dispatch_calls: list[str] = []
            real_dispatch = service.dispatch_confirmed_action

            def observe_dispatch(*args: object, **kwargs: object) -> tuple[str, dict[str, object]]:
                action_type = cast(str, args[1])
                dispatch_calls.append(action_type)
                return real_dispatch(*args, **kwargs)

            monkeypatch.setattr(service, "dispatch_confirmed_action", observe_dispatch)
            action_url = (
                f"/api/v1/assistant/conversations/{conversation_id}/actions/"
                f"{card['action_id']}/confirm"
            )

            def confirm(identity: dict[str, object], *, version: int, phrase: str):
                return client.post(
                    action_url,
                    headers={"x-csrf-token": cast(str, identity["csrf"])},
                    json={
                        "action_version": version,
                        "context": context,
                        "allow": True,
                        "confirmation_phrase": phrase,
                    },
                )

            wrong_phrase = confirm(
                admin,
                version=int(cast(int, card["version"])),
                phrase="CONFIRM incorrect-fixture-phrase",
            )
            assert wrong_phrase.status_code == 409
            assert wrong_phrase.json()["error"]["code"] == "action_confirmation"

            stale_version = confirm(
                admin,
                version=int(cast(int, card["version"])) + 1,
                phrase=cast(str, card["confirmation_phrase"]),
            )
            assert stale_version.status_code == 409
            assert stale_version.json()["error"]["code"] == "action_version"

            _install_session_cookies(client, member)
            member_context = client.get(
                "/api/v1/assistant/context", params={"route": "/overview"}
            ).json()["context"]
            forged_owner_action = client.post(
                action_url,
                headers={"x-csrf-token": cast(str, member["csrf"])},
                json={
                    "action_version": int(cast(int, card["version"])),
                    "context": member_context,
                    "allow": True,
                    "confirmation_phrase": card["confirmation_phrase"],
                },
            )
            assert forged_owner_action.status_code == 404

            stored_action = service.storage.get_action(
                int(admin["user_id"]), cast(str, card["action_id"])
            )
            assert stored_action["status"] == "pending"
            assert (
                service.storage.get_action_receipt(
                    int(admin["user_id"]), cast(str, card["action_id"])
                )
                is None
            )
            assert dispatch_calls == []
            assert app.state.repository.auth_list_invitations() == []

            _install_session_cookies(client, admin)
            succeeded = confirm(
                admin,
                version=int(cast(int, card["version"])),
                phrase=cast(str, card["confirmation_phrase"]),
            )
            assert succeeded.status_code == 200, succeeded.text
            assert succeeded.json()["status"] == "handed_off"
            assert succeeded.json()["destination"] == "/admin#invitations"
            receipt = service.storage.get_action_receipt(
                int(admin["user_id"]), cast(str, card["action_id"])
            )
            assert receipt is not None and receipt["outcome"] == "handed_off"

            replay = confirm(
                admin,
                version=int(cast(int, card["version"])),
                phrase=cast(str, card["confirmation_phrase"]),
            )
            assert replay.status_code == 409
            assert replay.json()["error"]["code"] == "action_replayed"
            assert dispatch_calls == ["invitation.create"]
            assert app.state.repository.auth_list_invitations() == []
            assert providers.calls == 0
        finally:
            client.close()


def test_invitation_handoff_email_stays_in_smtp_seam_and_requires_fresh_totp(
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The assistant only hands off; the protected email route owns code delivery."""

    global _CURRENT_TIME
    app, providers = _make_app(settings)
    submissions: list[dict[str, object]] = []

    def fake_send(
        mail_settings: InvitationMailSettings,
        *,
        public_origin: str,
        recipient: str,
        github_id: int | None,
        github_login: str | None,
        code: str,
        expires_at: datetime,
    ) -> InviteEmailSubmission:
        submissions.append(
            {
                "settings": mail_settings,
                "public_origin": public_origin,
                "recipient": recipient,
                "github_id": github_id,
                "github_login": github_login,
                "code": code,
                "expires_at": expires_at,
            }
        )
        return InviteEmailSubmission("f" * 32, _CURRENT_TIME)

    monkeypatch.setattr(application_api, "send_invitation_email", fake_send)
    with TestClient(app, client=("127.0.0.1", 51062)) as machine:
        client = TestClient(app, client=("127.0.0.1", 51064))
        try:
            admin = _enroll_user(app, client, github_id=82011, role="admin")
            member = _enroll_user(app, client, github_id=82012, role="member")
            _install_session_cookies(client, admin)
            context, conversation_id, card, _execution_id = _propose_invitation(
                app, client, machine, admin
            )
            handoff = client.post(
                f"/api/v1/assistant/conversations/{conversation_id}/actions/"
                f"{card['action_id']}/confirm",
                headers={"x-csrf-token": cast(str, admin["csrf"])},
                json={
                    "action_version": int(cast(int, card["version"])),
                    "context": context,
                    "allow": True,
                    "confirmation_phrase": card["confirmation_phrase"],
                },
            )
            assert handoff.status_code == 200
            assert handoff.json()["destination"] == "/admin#invitations"
            assert app.state.repository.auth_list_invitations() == []

            recipient = "synthetic-invitee@example.test"
            email_payload = {"email": recipient}
            _install_session_cookies(client, member)
            member_handoff = client.post(
                f"/api/v1/assistant/conversations/{conversation_id}/actions/"
                f"{card['action_id']}/confirm",
                headers={"x-csrf-token": cast(str, member["csrf"])},
                json={
                    "action_version": int(cast(int, card["version"])),
                    "context": client.get(
                        "/api/v1/assistant/context", params={"route": "/overview"}
                    ).json()["context"],
                    "allow": True,
                    "confirmation_phrase": card["confirmation_phrase"],
                },
            )
            assert member_handoff.status_code == 404
            member_email = client.post(
                "/api/v1/auth/invites/email",
                json=email_payload,
                headers={"x-csrf-token": cast(str, member["csrf"])},
            )
            assert member_email.status_code == 403
            assert member_email.json()["error"]["code"] == "authorization_denied"
            assert submissions == []
            assert app.state.repository.auth_list_invitations() == []

            _install_session_cookies(client, admin)
            # Age the proof through the clock so the request exercises the real freshness check.
            _CURRENT_TIME = _NOW + timedelta(minutes=10)
            stale_email = client.post(
                "/api/v1/auth/invites/email",
                json=email_payload,
                headers={"x-csrf-token": cast(str, admin["csrf"])},
            )
            assert stale_email.status_code == 403
            assert stale_email.json()["error"]["code"] == "authorization_denied"
            assert submissions == []
            assert app.state.repository.auth_list_invitations() == []

            current_code = code_for_step(cast(str, admin["totp_secret"]), time_step(_CURRENT_TIME))
            stepped_up = client.post(
                "/api/v1/auth/totp/step-up",
                json={"code": current_code},
                headers={"x-csrf-token": cast(str, admin["csrf"])},
            )
            assert stepped_up.status_code == 200
            accepted = client.post(
                "/api/v1/auth/invites/email",
                json=email_payload,
                headers={"x-csrf-token": cast(str, admin["csrf"])},
            )
            assert accepted.status_code == 201, accepted.text
            body = accepted.json()
            assert body["submission_status"] == "smtp_accepted"
            assert body["email_bound"] is True
            assert "code" not in body
            assert recipient not in accepted.text
            assert len(submissions) == 1
            secret_code = cast(str, submissions[0]["code"])

            assistant_detail = client.get(f"/api/v1/assistant/conversations/{conversation_id}")
            assert assistant_detail.status_code == 200
            assert secret_code not in assistant_detail.text
            action_receipt = app.state.assistant.storage.get_action_receipt(
                int(admin["user_id"]), cast(str, card["action_id"])
            )
            assert action_receipt is not None
            assert secret_code not in str(action_receipt)
            invitation_listing = client.get("/api/v1/auth/invites")
            assert invitation_listing.status_code == 200
            assert secret_code not in invitation_listing.text
            assert recipient not in invitation_listing.text
            assert providers.calls == 0
        finally:
            client.close()
