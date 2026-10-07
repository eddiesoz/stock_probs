"""Public HTTP regressions for retained assistant history and restart recovery."""

from __future__ import annotations

import hashlib
import secrets
from collections import deque
from collections.abc import AsyncIterator, Mapping
from dataclasses import replace
from datetime import UTC, datetime, timedelta, tzinfo
from typing import cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpx import Response

from stock_probs import api as application_api
from stock_probs.api import create_app
from stock_probs.assistant import api as assistant_api
from stock_probs.assistant import storage as assistant_storage
from stock_probs.auth import CSRF_COOKIE_NAME, SESSION_COOKIE_NAME
from stock_probs.config import Settings
from stock_probs.provider import FixtureProvider

_NOW = datetime(2026, 10, 6, 12, 0, tzinfo=UTC)
_MODEL_ID = "fixture-provider/history-recovery"
_POLICY_VERSION = "history-recovery-policy"


class _FrozenHTTPDatetime(datetime):
    """Keep test sessions valid while two app instances share one database."""

    @classmethod
    def now(cls, tz: tzinfo | None = None) -> datetime:
        if tz is None:
            return _NOW.replace(tzinfo=None)
        return _NOW.astimezone(tz)


@pytest.fixture(autouse=True)
def _freeze_http_auth_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    """Use one deterministic timestamp for session and assistant HTTP checks."""

    monkeypatch.setattr(application_api, "datetime", _FrozenHTTPDatetime)
    monkeypatch.setattr(assistant_api, "datetime", _FrozenHTTPDatetime)


class _Catalog:
    """Return one offline model row whose unavailable state is explicit to the browser."""

    def list_models(self) -> list[dict[str, object]]:
        return [
            {
                "model_id": _MODEL_ID,
                "provider_id": "fixture-provider",
                "display_name": "Synthetic history fixture",
                "available": False,
                "free": True,
                "training": False,
                "terms_url": "https://models.example.test/terms",
                "terms_reviewed_at": "2026-10-01",
                "policy_version": _POLICY_VERSION,
                "disclosure": "Offline fixture; no upstream service is used.",
                "data_collection_allowed": False,
                "data_collection_default": False,
                "usable": False,
                "revision": 1,
            }
        ]


class _ControlledRuntime:
    """Expose readiness and deterministic cache-purge outcomes without a worker process."""

    def __init__(
        self,
        *,
        ready: bool = True,
        purge_results: tuple[bool, ...] = (),
    ) -> None:
        self.ready = ready
        self.purge_results = deque(purge_results)
        self.purged_conversations: list[str] = []

    async def start(self) -> None:
        return None

    def status(self) -> dict[str, object]:
        return {"status": "ready" if self.ready else "unavailable", "message": None}

    async def close(self) -> None:
        return None

    async def clear_conversation_cache(self, conversation_id: str) -> bool:
        self.purged_conversations.append(conversation_id)
        return self.purge_results.popleft() if self.purge_results else True


class _NoNetworkProviders:
    """Make every accidental provider request fail locally and count the attempted boundary."""

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
        raise AssertionError("history recovery must not call a model provider")
        yield b""


def _make_app(
    settings: Settings,
    runtime: _ControlledRuntime,
    providers: _NoNetworkProviders,
) -> FastAPI:
    """Build the normal FastAPI, auth, repository, and assistant stack with offline seams."""

    configured = replace(
        settings,
        environment="test",
        auth_mode="github",
        auth_session_secret="synthetic-history-recovery-session-secret-000000",  # noqa: S106
        auth_public_origin="http://testserver",
        github_client_id="synthetic-client-id",
        github_client_secret="synthetic-client-secret",  # noqa: S106
        github_redirect_uri="http://testserver/api/v1/auth/github/callback",
        assistant_enabled=True,
        assistant_rollout_mode="invited",
    )
    return create_app(
        configured,
        FixtureProvider(),
        lambda: _NOW,
        assistant_runtime=runtime,
        assistant_catalog=_Catalog(),
        assistant_providers=providers,
    )


def _sha256(value: str) -> str:
    """Hash a synthetic browser token using the repository's session convention."""

    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _add_signed_in_user(app: FastAPI, github_id: int) -> dict[str, str | int]:
    """Create one active owner, TOTP factor, and authenticated repository session."""

    repository = app.state.repository
    now = app.state.assistant.now().replace(microsecond=0)
    user = repository.auth_create_user(
        {
            "github_id": github_id,
            "github_login": f"fixture-{github_id}",
            "display_name": f"Synthetic owner {github_id}",
            "role": "member",
            "status": "active",
            "created_at": now,
        }
    )
    user_id = int(user["id"])
    expires = now + timedelta(hours=23)
    with repository.connect() as connection:
        cursor = connection.execute(
            """INSERT INTO totp_factors
            (user_id, secret_ciphertext, created_at, confirmed_at,
             last_accepted_step, updated_at)
            VALUES (?, ?, ?, ?, -1, ?)""",
            (
                user_id,
                "synthetic-encrypted-factor-material",
                now.isoformat(),
                now.isoformat(),
                now.isoformat(),
            ),
        )
        factor_id = int(cursor.lastrowid)
        connection.commit()
    token = secrets.token_urlsafe(32)
    csrf = secrets.token_urlsafe(32)
    session_id = secrets.token_hex(16)
    token_hash = _sha256(token)
    with repository.connect() as connection:
        connection.execute(
            """INSERT INTO sessions
            (user_id, session_id, token_hash, csrf_token_hash, issued_at, last_seen_at,
             idle_expires_at, absolute_expires_at, auth_method, mfa_method,
             mfa_verified_at, mfa_factor_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'github', 'totp', ?, ?)""",
            (
                user_id,
                session_id,
                token_hash,
                _sha256(csrf),
                now.isoformat(),
                now.isoformat(),
                expires.isoformat(),
                expires.isoformat(),
                now.isoformat(),
                factor_id,
            ),
        )
        connection.commit()
    assert repository.auth_get_session(token_hash) is not None
    return {
        "user_id": user_id,
        "session_id": session_id,
        "token": token,
        "token_hash": token_hash,
        "csrf": csrf,
    }


def _set_browser_session(client: TestClient, identity: Mapping[str, str | int]) -> None:
    """Select one authenticated synthetic owner on an in-process browser client."""

    client.cookies.clear()
    client.cookies.set(SESSION_COOKIE_NAME, str(identity["token"]), path="/")
    client.cookies.set(CSRF_COOKIE_NAME, str(identity["csrf"]), path="/")


def _create_conversation(
    client: TestClient,
    identity: Mapping[str, str | int],
    *,
    title: str = "Retained history fixture",
) -> tuple[dict[str, object], dict[str, object]]:
    """Create an owner conversation using the public context and conversation endpoints."""

    context_response = client.get("/api/v1/assistant/context", params={"route": "/overview"})
    assert context_response.status_code == 200, context_response.text
    context = cast(dict[str, object], context_response.json()["context"])
    created = client.post(
        "/api/v1/assistant/conversations",
        headers={"x-csrf-token": str(identity["csrf"])},
        json={"context": context, "title": title},
    )
    assert created.status_code == 201, created.text
    nested = cast(dict[str, object], created.json()["conversation"])
    return context, cast(dict[str, object], nested["conversation"])


def _seed_turn(
    app: FastAPI,
    identity: Mapping[str, str | int],
    context: Mapping[str, object],
    conversation_id: str,
    *,
    prompt: str,
    answer: str | None = None,
) -> dict[str, object]:
    """Persist a real owner turn and, when supplied, a completed assistant transcript."""

    storage = app.state.assistant.storage
    context_version = str(context["context_version"])
    turn = storage.create_turn(
        int(identity["user_id"]),
        conversation_id,
        prompt=prompt,
        model_id=_MODEL_ID,
        policy_version=_POLICY_VERSION,
        context=context,
        context_version=context_version,
        session_id=str(identity["session_id"]),
        session_token_hash=str(identity["token_hash"]),
        capability=secrets.token_urlsafe(36),
        now=_NOW,
        expires_at=_NOW + timedelta(seconds=120),
    )
    storage.set_turn_status(
        int(identity["user_id"]), conversation_id, str(turn["id"]), status="running", now=_NOW
    )
    if answer is not None:
        storage.append_message(
            int(identity["user_id"]),
            conversation_id,
            str(turn["id"]),
            role="assistant",
            content=answer,
            now=_NOW,
        )
        storage.append_event(
            int(identity["user_id"]),
            conversation_id,
            str(turn["id"]),
            event_type="token",
            data={"text": answer},
            now=_NOW,
        )
        storage.append_event(
            int(identity["user_id"]),
            conversation_id,
            str(turn["id"]),
            event_type="complete",
            data={"status": "completed"},
            now=_NOW,
        )
        storage.set_turn_status(
            int(identity["user_id"]), conversation_id, str(turn["id"]), status="completed", now=_NOW
        )
        storage.close_execution(str(turn["execution_id"]), now=_NOW)
    return cast(dict[str, object], turn)


def _conversation_detail(client: TestClient, conversation_id: str) -> dict[str, object]:
    """Read a conversation from its public owner-scoped HTTP endpoint."""

    response = client.get(f"/api/v1/assistant/conversations/{conversation_id}")
    assert response.status_code == 200, response.text
    return response.json()


def _delete_conversation(
    client: TestClient,
    identity: Mapping[str, str | int],
    conversation_id: str,
    revision: int,
) -> Response:
    """Submit the exact revision-bound deletion confirmation through HTTP."""

    return client.request(
        "DELETE",
        f"/api/v1/assistant/conversations/{conversation_id}",
        headers={"x-csrf-token": str(identity["csrf"])},
        json={
            "expected_revision": revision,
            "confirmation_phrase": f"DELETE {conversation_id[-8:]}",
        },
    )


def test_saved_conversation_reopens_over_http_when_provider_is_unavailable(
    settings: Settings,
) -> None:
    """Historical conversation reads remain available when the selected provider is offline."""

    runtime = _ControlledRuntime(ready=False)
    providers = _NoNetworkProviders()
    app = _make_app(settings, runtime, providers)
    with TestClient(app, client=("127.0.0.1", 51131)) as client:
        owner = _add_signed_in_user(app, 83101)
        _set_browser_session(client, owner)
        context, conversation = _create_conversation(client, owner)
        conversation_id = str(conversation["id"])
        prompt = "Review my saved local workspace history."
        answer = "The saved assistant response remains available offline."
        _seed_turn(
            app,
            owner,
            context,
            conversation_id,
            prompt=prompt,
            answer=answer,
        )

        models = client.get("/api/v1/assistant/models")
        reopened = client.get(f"/api/v1/assistant/conversations/{conversation_id}")
        listing = client.get("/api/v1/assistant/conversations")

        assert models.status_code == 200, models.text
        assert models.json()["items"][0]["available"] is False
        assert reopened.status_code == 200, reopened.text
        body = reopened.json()
        messages = body["messages"]["items"]
        assert [(item["role"], item["text"]) for item in messages] == [
            ("user", prompt),
            ("assistant", answer),
        ]
        assert body["turns"][0]["status"] == "completed"
        assert any(
            event["type"] == "token" and event["data"]["text"] == answer
            for event in body["events"]["items"]
        )
        assert listing.status_code == 200, listing.text
        assert [item["id"] for item in listing.json()["items"]] == [conversation_id]
        assert providers.calls == 0


def test_cache_purge_retry_preserves_history_then_recovers_owner_quota(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failed cache purge preserves the transcript; retry deletes only the selected owner chat."""

    runtime = _ControlledRuntime(purge_results=(False, True))
    providers = _NoNetworkProviders()
    app = _make_app(settings, runtime, providers)
    with TestClient(app, client=("127.0.0.1", 51132)) as client:
        owner = _add_signed_in_user(app, 83102)
        peer = _add_signed_in_user(app, 83103)
        _set_browser_session(client, owner)
        owner_context, owner_chat = _create_conversation(client, owner, title="Owner record")
        owner_chat_id = str(owner_chat["id"])
        owner_prompt = "Owner's saved question remains visible after purge failure." * 4
        owner_answer = "Owner's retained assistant reply." * 8
        _seed_turn(
            app,
            owner,
            owner_context,
            owner_chat_id,
            prompt=owner_prompt,
            answer=owner_answer,
        )

        _set_browser_session(client, peer)
        peer_context, peer_chat = _create_conversation(client, peer, title="Peer record")
        peer_chat_id = str(peer_chat["id"])
        peer_prompt = "Peer's independent saved question."
        peer_answer = "Peer's untouched assistant reply."
        _seed_turn(
            app,
            peer,
            peer_context,
            peer_chat_id,
            prompt=peer_prompt,
            answer=peer_answer,
        )

        storage = app.state.assistant.storage
        owner_usage = storage.usage(int(owner["user_id"]))["user_bytes"]
        next_conversation_bytes = (
            len(b"New conversation") + len(storage._json(owner_context).encode("utf-8")) + 192
        )
        assert owner_usage > next_conversation_bytes
        monkeypatch.setattr(assistant_storage, "ASSISTANT_USER_HISTORY_LIMIT", owner_usage + 1)
        _set_browser_session(client, owner)
        over_quota = client.post(
            "/api/v1/assistant/conversations",
            headers={"x-csrf-token": str(owner["csrf"])},
            json={"context": owner_context},
        )
        assert over_quota.status_code == 413, over_quota.text
        assert over_quota.json()["error"]["code"] == "assistant_quota_exceeded"

        before_delete = _conversation_detail(client, owner_chat_id)
        failed_delete = _delete_conversation(
            client,
            owner,
            owner_chat_id,
            int(before_delete["conversation"]["revision"]),
        )
        assert failed_delete.status_code == 503, failed_delete.text
        assert failed_delete.json()["error"]["code"] == "assistant_cache_clear_pending"
        retained = _conversation_detail(client, owner_chat_id)
        assert [item["text"] for item in retained["messages"]["items"]] == [
            owner_prompt,
            owner_answer,
        ]
        assert retained["turns"][0]["status"] == "completed"
        still_over_quota = client.post(
            "/api/v1/assistant/conversations",
            headers={"x-csrf-token": str(owner["csrf"])},
            json={"context": owner_context},
        )
        assert still_over_quota.status_code == 413, still_over_quota.text

        retry = _delete_conversation(
            client,
            owner,
            owner_chat_id,
            int(retained["conversation"]["revision"]),
        )
        assert retry.status_code == 200, retry.text
        assert retry.json()["canonical_content_removed"] is True
        assert client.get(f"/api/v1/assistant/conversations/{owner_chat_id}").status_code == 404
        owner_list = client.get("/api/v1/assistant/conversations")
        assert owner_list.status_code == 200
        assert owner_list.json()["items"] == []

        recovered = client.post(
            "/api/v1/assistant/conversations",
            headers={"x-csrf-token": str(owner["csrf"])},
            json={"context": owner_context},
        )
        assert recovered.status_code == 201, recovered.text
        assert runtime.purged_conversations == [owner_chat_id, owner_chat_id]

        _set_browser_session(client, peer)
        peer_after = _conversation_detail(client, peer_chat_id)
        assert [item["text"] for item in peer_after["messages"]["items"]] == [
            peer_prompt,
            peer_answer,
        ]
        peer_listing = client.get("/api/v1/assistant/conversations")
        assert peer_listing.status_code == 200, peer_listing.text
        assert [item["id"] for item in peer_listing.json()["items"]] == [peer_chat_id]
        assert providers.calls == 0


def test_restart_retains_exact_search_preview_but_cannot_replay_it(
    settings: Settings,
) -> None:
    """Restart recovery closes an interrupted turn before its exact search preview can execute."""

    providers = _NoNetworkProviders()
    first_app = _make_app(settings, _ControlledRuntime(), providers)
    with TestClient(first_app, client=("127.0.0.1", 51133)) as first_client:
        owner = _add_signed_in_user(first_app, 83104)
        _set_browser_session(first_client, owner)
        context, conversation = _create_conversation(first_client, owner, title="Interrupted turn")
        conversation_id = str(conversation["id"])
        turn = _seed_turn(
            first_app,
            owner,
            context,
            conversation_id,
            prompt="Search only this exact private-context preview.",
        )
        storage = first_app.state.assistant.storage
        preview = storage.create_search_preview(
            int(owner["user_id"]),
            conversation_id,
            str(turn["id"]),
            str(turn["execution_id"]),
            query_text=(
                "exact private query: compare my saved forecast with the selected public page"
            ),
            context_version=str(context["context_version"]),
            confirmation_phrase="ignored input; storage derives the exact phrase",
            now=_NOW,
            expires_at=_NOW + timedelta(seconds=90),
        )
        storage.append_event(
            int(owner["user_id"]),
            conversation_id,
            str(turn["id"]),
            event_type="private_context_preview",
            data={
                "preview_id": str(preview["id"]),
                "query": str(preview["query"]),
                "reason": "Review this exact search before it leaves the local service.",
                "context_version": str(preview["context_version"]),
                "expires_at": str(preview["expires_at"]),
                "confirmation_phrase": str(preview["confirmation_phrase"]),
            },
            now=_NOW,
        )
        first_detail = _conversation_detail(first_client, conversation_id)
        preview_path = (
            f"/api/v1/assistant/conversations/{conversation_id}/turns/{turn['id']}"
            f"/search-previews/{preview['id']}"
        )
        exact_preview = first_client.get(preview_path)
        assert exact_preview.status_code == 200, exact_preview.text
        assert exact_preview.json()["query"] == preview["query"]
        assert exact_preview.json()["confirmation_phrase"] == preview["confirmation_phrase"]
        assert first_detail["turns"][0]["status"] == "running"

        restarted_app = _make_app(settings, _ControlledRuntime(), providers)
        with TestClient(restarted_app, client=("127.0.0.1", 51134)) as restarted_client:
            _set_browser_session(restarted_client, owner)
            recovered_detail = _conversation_detail(restarted_client, conversation_id)
            recovered_turn = recovered_detail["turns"][0]
            assert recovered_turn["status"] == "failed"
            assert [item["text"] for item in recovered_detail["messages"]["items"]] == [
                "Search only this exact private-context preview."
            ]
            assert any(
                event["type"] == "error" and event["data"]["code"] == "runtime_restarted"
                for event in recovered_detail["events"]["items"]
            )
            preview_event = next(
                event
                for event in recovered_detail["events"]["items"]
                if event["type"] == "private_context_preview"
            )
            assert preview_event["data"]["query"] == preview["query"]
            assert preview_event["data"]["confirmation_phrase"] == preview["confirmation_phrase"]

            reopened_preview = restarted_client.get(preview_path)
            assert reopened_preview.status_code == 200, reopened_preview.text
            assert reopened_preview.json()["status"] == "pending"
            assert reopened_preview.json()["query"] == preview["query"]
            replay = restarted_client.post(
                preview_path + "/confirm",
                headers={"x-csrf-token": str(owner["csrf"])},
                json={
                    "context": context,
                    "context_version": context["context_version"],
                    "confirmation_phrase": preview["confirmation_phrase"],
                    "allow": True,
                },
            )
            assert replay.status_code == 409, replay.text
            assert replay.json()["error"]["code"] == "search_context_stale"
            assert restarted_client.get(preview_path).json()["status"] == "pending"
            assert providers.calls == 0
