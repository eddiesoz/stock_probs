"""Public assistant turn and event-stream regressions for runtime boundaries."""

from __future__ import annotations

import asyncio
import hashlib
import json
import secrets
import threading
from collections.abc import Awaitable, Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta, tzinfo
from typing import cast
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from stock_probs import api as application_api
from stock_probs.api import create_app
from stock_probs.assistant import api as assistant_api
from stock_probs.assistant.schemas import AssistantTurnContext, AssistantTurnResult
from stock_probs.assistant.service import AssistantUnavailable
from stock_probs.assistant.storage import (
    AssistantRuntimeWriteGuard,
    AssistantStorageConflict,
    AssistantStorageExecutionStale,
)
from stock_probs.auth import CSRF_COOKIE_NAME, SESSION_COOKIE_NAME
from stock_probs.config import Settings
from stock_probs.provider import FixtureProvider

_NOW = datetime(2026, 10, 6, 12, 0, tzinfo=UTC)
_MODEL_ID = "synthetic-provider/assistant-http-events"
_POLICY_VERSION = "fixture-policy-revision"


class _FrozenHTTPDatetime(datetime):
    """Use one controlled instant for request authentication and stream rechecks."""

    @classmethod
    def now(cls, tz: tzinfo | None = None) -> datetime:
        if tz is None:
            return _NOW.replace(tzinfo=None)
        return _NOW.astimezone(tz)


@pytest.fixture(autouse=True)
def _freeze_http_auth_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep HTTP auth rows and per-event stream checks on the same synthetic clock."""

    monkeypatch.setattr(application_api, "datetime", _FrozenHTTPDatetime)
    monkeypatch.setattr(assistant_api, "datetime", _FrozenHTTPDatetime)


class _FixtureCatalog:
    """Expose one synthetic, consentable model row to the real assistant policy adapter."""

    def list_models(self) -> list[dict[str, object]]:
        return [
            {
                "model_id": _MODEL_ID,
                "provider_id": "synthetic-provider",
                "native_provider_id": "synthetic-provider",
                "display_name": "Synthetic HTTP event model",
                "available": True,
                "free": True,
                "training": False,
                "terms_url": "https://models.example.test/terms",
                "terms_reviewed_at": "2026-10-01",
                "policy_version": _POLICY_VERSION,
                "disclosure": "Synthetic model fixture; no upstream service is used.",
                "data_collection_allowed": False,
                "data_collection_default": False,
                "privacy_policy_version": _POLICY_VERSION,
                "privacy_disclosure": "Synthetic model fixture; no upstream service is used.",
                "billing_class": "free",
                "billing_policy_version": _POLICY_VERSION,
                "cost_disclosure": "Synthetic fixture; no charge.",
                "enabled": True,
                "usable": True,
                "revision": 1,
            }
        ]


EventFactory = Callable[[AssistantTurnContext, str], Sequence[Mapping[str, object]]]


class _ScriptedRuntime:
    """Replace only runtime generation while retaining the real turn service and HTTP flow."""

    def __init__(
        self,
        events: Sequence[Mapping[str, object]] = (),
        *,
        event_factory: EventFactory | None = None,
        result: AssistantTurnResult | None = None,
    ) -> None:
        self.events = tuple(events)
        self.event_factory = event_factory
        self.result = result or AssistantTurnResult(status="completed")
        self.contexts: list[AssistantTurnContext] = []
        self.prompts: list[str] = []

    async def start(self) -> None:
        return None

    def status(self) -> dict[str, object]:
        return {"status": "ready", "message": None}

    async def close(self) -> None:
        return None

    async def clear_conversation_cache(self, conversation_id: str) -> bool:
        del conversation_id
        return True

    async def run_turn(
        self,
        *,
        context: AssistantTurnContext,
        prompt: str,
        emit: Callable[[Mapping[str, object]], Awaitable[None]],
    ) -> AssistantTurnResult:
        self.contexts.append(context)
        self.prompts.append(prompt)
        events = self.event_factory(context, prompt) if self.event_factory else self.events
        for event in events:
            await emit(event)
        return self.result


class _PausedRuntime(_ScriptedRuntime):
    """Pause after one persisted token so a browser session can be revoked mid-stream."""

    def __init__(self) -> None:
        super().__init__()
        self.ready_for_first_event = threading.Event()
        self.start_first_event: asyncio.Event | None = None
        self.first_event_ready = threading.Event()
        self.loop: asyncio.AbstractEventLoop | None = None
        self.resume: asyncio.Event | None = None

    async def run_turn(
        self,
        *,
        context: AssistantTurnContext,
        prompt: str,
        emit: Callable[[Mapping[str, object]], Awaitable[None]],
    ) -> AssistantTurnResult:
        self.contexts.append(context)
        self.prompts.append(prompt)
        self.loop = asyncio.get_running_loop()
        self.start_first_event = asyncio.Event()
        self.resume = asyncio.Event()
        self.ready_for_first_event.set()
        await self.start_first_event.wait()
        await emit(
            {
                "type": "token",
                "data": {"text": "visible-before-revocation:" + ("x" * 320)},
            }
        )
        self.first_event_ready.set()
        await self.resume.wait()
        await emit(
            {
                "type": "token",
                "data": {"text": "must-not-reach-revoked-browser:" + ("y" * 320)},
            }
        )
        return AssistantTurnResult(status="completed")


class _EventResponseSignal:
    """Signal that the selected public SSE request has started its ASGI response."""

    def __init__(
        self,
        app: ASGIApp,
        response_started: threading.Event,
        first_token_sent: threading.Event,
    ) -> None:
        self.app = app
        self.response_started = response_started
        self.first_token_sent = first_token_sent
        self.event_path = ""

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope.get("type") != "http" or scope.get("path") != self.event_path:
            await self.app(scope, receive, send)
            return

        async def signal_send(message: Message) -> None:
            if message.get("type") == "http.response.start":
                self.response_started.set()
            await send(message)
            body = message.get("body")
            if isinstance(body, bytes) and b"visible-before-revocation:" in body:
                self.first_token_sent.set()

        await self.app(scope, receive, signal_send)


class _NoNetworkProviders:
    """Leave provider discovery on the fixture catalog and reject accidental model requests."""

    async def proxy_chat_completion(self, *args: object, **kwargs: object) -> None:
        del args, kwargs
        raise AssertionError("runtime event HTTP tests must not call a model provider")


def _make_app(settings: Settings, runtime: object):
    """Build the normal FastAPI, auth, repository, and assistant stack with offline seams."""

    configured = replace(
        settings,
        environment="test",
        auth_mode="github",
        auth_session_secret="synthetic-http-event-session-secret-000000",  # noqa: S106
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
        assistant_catalog=_FixtureCatalog(),
        assistant_providers=_NoNetworkProviders(),
    )


def _sha256(value: str) -> str:
    """Hash a synthetic session token exactly as the auth repository does."""

    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _add_signed_in_user(
    app: object, github_id: int, *, role: str = "member"
) -> dict[str, str | int]:
    """Create a real owner row, TOTP factor, and authenticated repository session."""

    repository = app.state.repository
    now = app.state.assistant.now().replace(microsecond=0)
    user = repository.auth_create_user(
        {
            "github_id": github_id,
            "github_login": f"fixture-{github_id}",
            "display_name": f"Synthetic user {github_id}",
            "role": role,
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


def _add_parallel_session(app: object, identity: Mapping[str, str | int]) -> dict[str, str | int]:
    """Issue another valid browser session for the same owner after stream revocation."""

    repository = app.state.repository
    user_id = int(identity["user_id"])
    factor = repository.auth_get_totp_factor(user_id)
    assert factor is not None
    now = app.state.assistant.now().replace(microsecond=0)
    expires = now + timedelta(hours=23)
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
                factor["id"],
            ),
        )
        connection.commit()
    return {
        "user_id": user_id,
        "session_id": session_id,
        "token": token,
        "token_hash": token_hash,
        "csrf": csrf,
    }


def _set_browser_session(client: TestClient, identity: Mapping[str, str | int]) -> None:
    """Select one authenticated test identity on a shared in-process browser client."""

    client.cookies.clear()
    client.cookies.set(SESSION_COOKIE_NAME, str(identity["token"]), path="/")
    client.cookies.set(CSRF_COOKIE_NAME, str(identity["csrf"]), path="/")


def _prepare_conversation(
    client: TestClient, identity: Mapping[str, str | int]
) -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
    """Create a conversation and consent through the public routes and fixture catalog."""

    headers = {"x-csrf-token": str(identity["csrf"])}
    context_response = client.get("/api/v1/assistant/context", params={"route": "/overview"})
    assert context_response.status_code == 200, context_response.text
    context = cast(dict[str, object], context_response.json()["context"])
    created = client.post(
        "/api/v1/assistant/conversations",
        headers=headers,
        json={"context": context},
    )
    assert created.status_code == 201, created.text
    conversation = cast(dict[str, object], created.json()["conversation"]["conversation"])
    listed_models = client.get("/api/v1/assistant/models")
    assert listed_models.status_code == 200, listed_models.text
    model = next(row for row in listed_models.json()["items"] if row["model_id"] == _MODEL_ID)
    model_path = quote(str(model["model_id"]), safe="")
    consent = client.put(
        f"/api/v1/assistant/models/{model_path}/consent",
        headers=headers,
        json={
            "policy_version": model["policy_version"],
            "accepted_terms": True,
            "data_collection_opt_in": False,
        },
    )
    assert consent.status_code == 200, consent.text
    return context, conversation, cast(dict[str, object], model)


def _start_turn(
    client: TestClient,
    identity: Mapping[str, str | int],
    context: Mapping[str, object],
    conversation: Mapping[str, object],
    model: Mapping[str, object],
    *,
    prompt: str = "Review this synthetic workspace safely.",
) -> dict[str, object]:
    """Start one turn through the public HTTP endpoint using its catalog policy row."""

    response = client.post(
        f"/api/v1/assistant/conversations/{conversation['id']}/turns",
        headers={"x-csrf-token": str(identity["csrf"])},
        json={
            "prompt": prompt,
            "model_id": model["model_id"],
            "policy_version": model["policy_version"],
            "context": dict(context),
            "context_preview_accepted": True,
        },
    )
    assert response.status_code == 202, response.text
    return cast(dict[str, object], response.json()["turn"])


def _read_events(client: TestClient, conversation_id: str, turn_id: str) -> list[dict[str, object]]:
    """Read one complete authenticated SSE stream and decode its public event frames."""

    response = client.get(
        f"/api/v1/assistant/conversations/{conversation_id}/turns/{turn_id}/events"
    )
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    events: list[dict[str, object]] = []
    for frame in response.text.strip().split("\n\n"):
        lines = frame.splitlines()
        event_type = next(
            (line.removeprefix("event: ") for line in lines if line.startswith("event: ")), None
        )
        data_line = next(
            (line.removeprefix("data: ") for line in lines if line.startswith("data: ")), None
        )
        if event_type is not None and data_line is not None:
            events.append({"type": event_type, "data": json.loads(data_line)})
    return events


def _conversation_detail(client: TestClient, conversation_id: str) -> dict[str, object]:
    """Fetch the real owner-scoped persisted transcript through the public detail route."""

    response = client.get(f"/api/v1/assistant/conversations/{conversation_id}")
    assert response.status_code == 200, response.text
    return cast(dict[str, object], response.json())


def _persisted_error_codes(detail: Mapping[str, object]) -> list[str]:
    """Read projected public error codes from persisted events, not private turn fields."""

    events = cast(Mapping[str, object], detail["events"])
    items = cast(Sequence[Mapping[str, object]], events["items"])
    return [
        str(cast(Mapping[str, object], item["data"])["code"])
        for item in items
        if item["type"] == "error"
    ]


def _meta(context: AssistantTurnContext) -> dict[str, object]:
    """Build a native-style metadata event from the exact selected turn context."""

    return {
        "type": "meta",
        "data": {
            "model_id": context.model_id,
            "policy_version": context.policy_version,
            "context_version": context.context_version,
        },
    }


def test_public_turn_stream_binds_meta_and_projects_safe_runtime_events(settings: Settings) -> None:
    """Public turn and history routes preserve selected context and safe event projections."""

    private_query = "synthetic-private-tool-query-6dd2"
    expected_token = ("😀" * 2048) + " tail"

    def events_for(context: AssistantTurnContext, _prompt: str) -> Sequence[Mapping[str, object]]:
        return [
            _meta(context),
            {"type": "token", "data": {"text": "😀" * 2048}},
            {"type": "token", "data": {"text": " tail"}},
            {
                "type": "tool",
                "data": {
                    "name": "market.news",
                    "call_id": "synthetic-call-1",
                    "status": "completed",
                    "description": "Read the approved synthetic feed.",
                    "arguments": {"query": private_query},
                    "result": {"items": [private_query]},
                },
            },
            {
                "type": "source",
                "data": {
                    "title": "Synthetic public article",
                    "url": "https://news.example.test/story/1",
                    "source_type": "public",
                    "source_ref": "synthetic-source-1",
                    "retrieved_at": "2026-10-06T09:30:00-04:00",
                    "as_of": "2026-10-06T13:15:00+02:00",
                    "metadata": {"private": private_query},
                },
            },
            {
                "type": "source",
                "data": {
                    "title": "Unsafe synthetic local source",
                    "url": "http://127.0.0.1/private",
                    "source_type": "public",
                    "retrieved_at": "not-a-date",
                    "as_of": "not-a-date",
                },
            },
            {
                "type": "proposed_action",
                "data": {"action_type": "theme.set", "payload": {"theme": "dark"}},
            },
        ]

    runtime = _ScriptedRuntime(event_factory=events_for)
    app = _make_app(settings, runtime)
    with TestClient(app, client=("127.0.0.1", 51061)) as browser:
        identity = _add_signed_in_user(app, 80061)
        _set_browser_session(browser, identity)
        context, conversation, model = _prepare_conversation(browser, identity)
        turn = _start_turn(browser, identity, context, conversation, model)
        stream = _read_events(browser, str(conversation["id"]), str(turn["id"]))
        detail = _conversation_detail(browser, str(conversation["id"]))
        saved_events = detail["events"]["items"]

        assert runtime.contexts[0].user_id == identity["user_id"]
        assert runtime.contexts[0].conversation_id == conversation["id"]
        assert runtime.contexts[0].turn_id == turn["id"]
        assert runtime.contexts[0].model_id == model["model_id"]
        assert runtime.contexts[0].policy_version == model["policy_version"]
        assert runtime.contexts[0].context_version == context["context_version"]
        assert runtime.contexts[0].page_context == context
        assert runtime.prompts == ["Review this synthetic workspace safely."]

        stream_meta = next(item["data"] for item in stream if item["type"] == "meta")
        assert stream_meta == {
            "model_id": model["model_id"],
            "policy_version": model["policy_version"],
            "context_version": context["context_version"],
        }
        token_events = [item["data"]["text"] for item in stream if item["type"] == "token"]
        assert "".join(token_events) == expected_token
        assert all(len(token.encode("utf-8")) <= 8192 for token in token_events)

        tool_event = next(item["data"] for item in stream if item["type"] == "tool")
        assert tool_event == {
            "name": "market.news",
            "call_id": "synthetic-call-1",
            "status": "completed",
            "description": "Read the approved synthetic feed.",
        }
        sources = [item["data"] for item in stream if item["type"] == "source"]
        assert sources[0]["url"] == "https://news.example.test/story/1"
        assert sources[0]["retrieved_at"] == "2026-10-06T13:30:00+00:00"
        assert sources[0]["as_of"] == "2026-10-06T11:15:00+00:00"
        assert "metadata" not in sources[0]
        assert sources[1]["url"] is None
        assert sources[1]["retrieved_at"] == _NOW.isoformat()
        assert sources[1]["as_of"] is None

        proposal = next(item["data"] for item in stream if item["type"] == "proposed_action")
        assert proposal["action_type"] == "theme.set"
        assert proposal["title"] == "Change display theme"
        assert proposal["changes"] == [{"label": "Theme", "after": "dark"}]
        assert "payload" not in proposal
        assert stream[-1]["type"] == "complete"
        assert detail["turns"][0]["status"] == "completed"
        assert private_query not in json.dumps(stream)
        assert private_query not in json.dumps(saved_events)


@pytest.mark.parametrize(
    ("event_factory", "expected_code"),
    [
        (
            lambda _context, _prompt: [
                {
                    "type": "unknown-private-runtime-event",
                    "data": {"sentinel": "private-runtime-event-9f4d"},
                }
            ],
            "invalid_runtime_event",
        ),
        (
            lambda context, _prompt: [
                {
                    "type": "meta",
                    "data": {
                        "model_id": "other/selected-model",
                        "policy_version": context.policy_version,
                        "context_version": context.context_version,
                    },
                }
            ],
            "invalid_runtime_event",
        ),
        (
            lambda _context, _prompt: [{"type": "token", "data": {"text": 123}}],
            "invalid_runtime_event",
        ),
    ],
    ids=["unknown-event", "mismatched-selected-meta", "malformed-token"],
)
def test_public_turn_rejects_malformed_or_unknown_runtime_events(
    settings: Settings,
    event_factory: EventFactory,
    expected_code: str,
) -> None:
    """Unknown, malformed, and mismatched runtime events become safe terminal errors."""

    runtime = _ScriptedRuntime(event_factory=event_factory)
    app = _make_app(settings, runtime)
    with TestClient(app, client=("127.0.0.1", 51062)) as browser:
        identity = _add_signed_in_user(app, 80062)
        _set_browser_session(browser, identity)
        context, conversation, model = _prepare_conversation(browser, identity)
        turn = _start_turn(browser, identity, context, conversation, model)
        stream = _read_events(browser, str(conversation["id"]), str(turn["id"]))
        detail = _conversation_detail(browser, str(conversation["id"]))
        errors = [item["data"] for item in stream if item["type"] == "error"]

        assert errors
        assert errors[-1]["code"] == expected_code
        assert errors[-1]["message"] == "The assistant could not complete this turn."
        assert stream[-1]["type"] == "complete"
        assert detail["turns"][0]["status"] == "failed"
        assert _persisted_error_codes(detail)[-1] == expected_code
        assert "private-runtime-event-9f4d" not in json.dumps(stream)
        assert "private-runtime-event-9f4d" not in json.dumps(detail)
        assert not any(item["type"] == "token" for item in stream)


@pytest.mark.parametrize(
    ("event_factory", "expected_code", "maximum_total"),
    [
        (
            lambda _context, _prompt: [{"type": "token", "data": {"text": "😀" * 2049}}],
            "invalid_runtime_event",
            0,
        ),
        (
            lambda _context, _prompt: [
                {"type": "token", "data": {"text": "a" * 8192}} for _ in range(9)
            ],
            "output_too_large",
            65_536,
        ),
    ],
    ids=["utf8-event-limit", "total-output-limit"],
)
def test_public_turn_enforces_utf8_event_and_total_output_caps(
    settings: Settings,
    event_factory: EventFactory,
    expected_code: str,
    maximum_total: int,
) -> None:
    """Public stream persistence never exceeds the per-token or total UTF-8 output bounds."""

    runtime = _ScriptedRuntime(event_factory=event_factory)
    app = _make_app(settings, runtime)
    with TestClient(app, client=("127.0.0.1", 51063)) as browser:
        identity = _add_signed_in_user(app, 80063)
        _set_browser_session(browser, identity)
        context, conversation, model = _prepare_conversation(browser, identity)
        turn = _start_turn(browser, identity, context, conversation, model)
        stream = _read_events(browser, str(conversation["id"]), str(turn["id"]))
        detail = _conversation_detail(browser, str(conversation["id"]))
        token_texts = [item["data"]["text"] for item in stream if item["type"] == "token"]
        errors = [item["data"] for item in stream if item["type"] == "error"]

        assert errors[-1]["code"] == expected_code
        assert detail["turns"][0]["status"] == "failed"
        assert _persisted_error_codes(detail)[-1] == expected_code
        assert all(len(token.encode("utf-8")) <= 8192 for token in token_texts)
        assert sum(len(token.encode("utf-8")) for token in token_texts) <= maximum_total
        if expected_code == "invalid_runtime_event":
            assert token_texts == []


@pytest.mark.parametrize(
    ("credential", "split_at", "leading", "trailing"),
    [
        ("sk-ant-api03-" + ("a" * 40), 13, " ", " "),
        ("sk-ant-api03-" + ("a" * 40), 13, ".", "!"),
        ("sk-ant-api03-" + ("a" * 40), 13, "x", "z"),
        ("sk-ant-api03-" + ("a" * 40), 13, "é", "ø"),
        ("AIza" + ("g" * 35), 19, " ", " "),
        ("AIza" + ("g" * 35), 19, "x", "z"),
        ("AIza" + ("g" * 35), 19, "é", "ø"),
    ],
    ids=[
        "anthropic-whitespace-boundary",
        "anthropic-punctuation-boundary",
        "anthropic-ascii-word-boundary",
        "anthropic-unicode-word-boundary",
        "google-canonical-key-split",
        "google-ascii-joined-key-split",
        "google-unicode-joined-key-split",
    ],
)
def test_public_turn_rejects_split_synthetic_credential_without_transcript_leak(
    settings: Settings, credential: str, split_at: int, leading: str, trailing: str
) -> None:
    """Split provider keys are withheld from SSE and saved history."""

    runtime = _ScriptedRuntime(
        events=(
            {
                "type": "token",
                "data": {
                    "text": "Public summary: " + ("x" * 300) + leading + credential[:split_at]
                },
            },
            {"type": "token", "data": {"text": credential[split_at:] + trailing}},
        )
    )
    app = _make_app(settings, runtime)
    with TestClient(app, client=("127.0.0.1", 51064)) as browser:
        identity = _add_signed_in_user(app, 80064)
        _set_browser_session(browser, identity)
        context, conversation, model = _prepare_conversation(browser, identity)
        turn = _start_turn(browser, identity, context, conversation, model)
        stream = _read_events(browser, str(conversation["id"]), str(turn["id"]))
        detail = _conversation_detail(browser, str(conversation["id"]))
        stream_text = json.dumps(stream)
        history_text = json.dumps(detail)

        assert credential not in stream_text
        assert credential not in history_text
        assert "sensitive_output_rejected" in stream_text + history_text
        assert detail["turns"][0]["status"] == "failed"
        assert _persisted_error_codes(detail)[-1] == "sensitive_output_rejected"
        assert all(item["type"] != "assistant_message" for item in stream)


@pytest.mark.parametrize(
    ("credential", "leading", "trailing"),
    [
        ("sk-proj-" + ("b" * 40), "x", "z"),
        ("sk-proj-" + ("b" * 40), "é", "ø"),
        ("sk-" + ("c" * 40), "x", "z"),
        ("sk-" + ("c" * 40), "é", "ø"),
    ],
    ids=["project-ascii", "project-unicode", "generic-ascii", "generic-unicode"],
)
def test_public_turn_rejects_split_project_and_generic_keys(
    settings: Settings, credential: str, leading: str, trailing: str
) -> None:
    """The remaining known vendor-key families are screened across token boundaries."""

    runtime = _ScriptedRuntime(
        events=(
            {"type": "token", "data": {"text": "Summary " + leading + credential[:9]}},
            {"type": "token", "data": {"text": credential[9:] + trailing}},
        )
    )
    app = _make_app(settings, runtime)
    with TestClient(app, client=("127.0.0.1", 51070)) as browser:
        identity = _add_signed_in_user(app, 80070)
        _set_browser_session(browser, identity)
        context, conversation, model = _prepare_conversation(browser, identity)
        turn = _start_turn(browser, identity, context, conversation, model)
        stream = _read_events(browser, str(conversation["id"]), str(turn["id"]))
        detail = _conversation_detail(browser, str(conversation["id"]))
        text = json.dumps(stream) + json.dumps(detail)

        assert credential not in text
        assert detail["turns"][0]["status"] == "failed"
        assert _persisted_error_codes(detail)[-1] == "sensitive_output_rejected"


@pytest.mark.parametrize(
    ("leading", "trailing"),
    [("x", "z"), ("é", "ø"), (".", "!")],
    ids=["ascii-word-boundary", "unicode-word-boundary", "punctuation-boundary"],
)
def test_public_turn_rejects_synthetic_credential_in_user_prompt(
    settings: Settings, leading: str, trailing: str
) -> None:
    """The public turn endpoint rejects embedded credential-shaped prompt content."""

    credential = "sk-ant-api03-" + ("b" * 40)
    runtime = _ScriptedRuntime()
    app = _make_app(settings, runtime)
    with TestClient(app, client=("127.0.0.1", 51069)) as browser:
        identity = _add_signed_in_user(app, 80069)
        _set_browser_session(browser, identity)
        context, conversation, model = _prepare_conversation(browser, identity)
        response = browser.post(
            f"/api/v1/assistant/conversations/{conversation['id']}/turns",
            headers={"x-csrf-token": str(identity["csrf"])},
            json={
                "prompt": f"Review {leading}{credential}{trailing} safely.",
                "model_id": model["model_id"],
                "policy_version": model["policy_version"],
                "context": dict(context),
                "context_preview_accepted": True,
            },
        )

        assert response.status_code == 422, response.text
        assert "sensitive_input_rejected" in response.text
        assert credential not in response.text
        assert runtime.contexts == []


@pytest.mark.parametrize(
    "credential",
    ["sk-proj-" + ("d" * 40), "sk-" + ("e" * 40)],
    ids=["project-key", "generic-key"],
)
def test_public_turn_rejects_project_and_generic_keys_in_user_prompt(
    settings: Settings, credential: str
) -> None:
    """Project and generic vendor-key prompt shapes fail before turn creation."""

    runtime = _ScriptedRuntime()
    app = _make_app(settings, runtime)
    with TestClient(app, client=("127.0.0.1", 51071)) as browser:
        identity = _add_signed_in_user(app, 80071)
        _set_browser_session(browser, identity)
        context, conversation, model = _prepare_conversation(browser, identity)
        response = browser.post(
            f"/api/v1/assistant/conversations/{conversation['id']}/turns",
            headers={"x-csrf-token": str(identity["csrf"])},
            json={
                "prompt": f"Review x{credential}z safely.",
                "model_id": model["model_id"],
                "policy_version": model["policy_version"],
                "context": dict(context),
                "context_preview_accepted": True,
            },
        )

        assert response.status_code == 422, response.text
        assert "sensitive_input_rejected" in response.text
        assert credential not in response.text
        assert runtime.contexts == []


def test_public_turn_projects_error_events_and_result_codes_to_safe_fallbacks(
    settings: Settings,
) -> None:
    """Runtime-controlled error text and unknown result codes never reach browser history."""

    private_error = "synthetic-private-runtime-path-2c91"
    runtime = _ScriptedRuntime(
        events=(
            {
                "type": "error",
                "data": {
                    "code": "provider_unavailable",
                    "message": private_error,
                    "debug": private_error,
                },
            },
        ),
        result=AssistantTurnResult(status="failed", error_code=private_error),
    )
    app = _make_app(settings, runtime)
    with TestClient(app, client=("127.0.0.1", 51065)) as browser:
        identity = _add_signed_in_user(app, 80065)
        _set_browser_session(browser, identity)
        context, conversation, model = _prepare_conversation(browser, identity)
        turn = _start_turn(browser, identity, context, conversation, model)
        stream = _read_events(browser, str(conversation["id"]), str(turn["id"]))
        detail = _conversation_detail(browser, str(conversation["id"]))
        errors = [item["data"] for item in stream if item["type"] == "error"]

        assert {
            "code": "provider_unavailable",
            "message": "The selected model provider is unavailable.",
        } in errors
        assert errors[-1] == {
            "code": "worker_unavailable",
            "message": "The assistant could not complete this turn.",
        }
        assert _persisted_error_codes(detail)[-1] == "worker_unavailable"
        assert private_error not in json.dumps(stream)
        assert private_error not in json.dumps(detail)


@pytest.mark.parametrize(
    ("action_type", "payload", "expected_code"),
    [
        ("backup.create", {}, "worker_unavailable"),
        ("theme.set", {"theme": "neon"}, "invalid_runtime_event"),
    ],
    ids=["member-cannot-propose-admin-action", "fixed-proposal-schema"],
)
def test_public_proposal_events_enforce_permission_and_format(
    settings: Settings,
    action_type: str,
    payload: Mapping[str, object],
    expected_code: str,
) -> None:
    """Runtime proposal events use the same owner permission and fixed payload schema."""

    runtime = _ScriptedRuntime(
        event_factory=lambda _context, _prompt: [
            {
                "type": "proposed_action",
                "data": {"action_type": action_type, "payload": dict(payload)},
            }
        ]
    )
    app = _make_app(settings, runtime)
    with TestClient(app, client=("127.0.0.1", 51066)) as browser:
        identity = _add_signed_in_user(app, 80066, role="member")
        _set_browser_session(browser, identity)
        context, conversation, model = _prepare_conversation(browser, identity)
        turn = _start_turn(browser, identity, context, conversation, model)
        stream = _read_events(browser, str(conversation["id"]), str(turn["id"]))
        detail = _conversation_detail(browser, str(conversation["id"]))
        errors = [item["data"] for item in stream if item["type"] == "error"]

        assert not any(item["type"] == "proposed_action" for item in stream)
        assert detail["actions"] == []
        assert errors[-1]["code"] == expected_code
        assert detail["turns"][0]["status"] == "failed"
        assert _persisted_error_codes(detail)[-1] == expected_code


def test_two_users_cannot_read_each_others_assistant_events_or_history(settings: Settings) -> None:
    """Conversation lists, event streams, and transcript history remain owner isolated."""

    runtime = _ScriptedRuntime(
        event_factory=lambda context, _prompt: [
            {
                "type": "token",
                "data": {"text": f"owner-{context.user_id}-private-event-marker"},
            }
        ]
    )
    app = _make_app(settings, runtime)
    with TestClient(app, client=("127.0.0.1", 51067)) as browser:
        owner = _add_signed_in_user(app, 80067)
        member = _add_signed_in_user(app, 80068)
        _set_browser_session(browser, owner)
        owner_context, owner_conversation, owner_model = _prepare_conversation(browser, owner)
        owner_turn = _start_turn(browser, owner, owner_context, owner_conversation, owner_model)
        owner_events = _read_events(browser, str(owner_conversation["id"]), str(owner_turn["id"]))
        owner_marker = f"owner-{owner['user_id']}-private-event-marker"

        _set_browser_session(browser, member)
        member_context, member_conversation, member_model = _prepare_conversation(browser, member)
        member_turn = _start_turn(
            browser, member, member_context, member_conversation, member_model
        )
        member_events = _read_events(
            browser, str(member_conversation["id"]), str(member_turn["id"])
        )
        member_marker = f"owner-{member['user_id']}-private-event-marker"
        member_list = browser.get("/api/v1/assistant/conversations")
        owner_detail = browser.get(f"/api/v1/assistant/conversations/{owner_conversation['id']}")
        owner_stream = browser.get(
            "/api/v1/assistant/conversations/"
            f"{owner_conversation['id']}/turns/{owner_turn['id']}/events"
        )

        assert owner_marker in json.dumps(owner_events)
        assert member_marker in json.dumps(member_events)
        assert owner_marker not in json.dumps(member_events)
        assert member_marker not in json.dumps(owner_events)
        assert member_list.status_code == 200
        listed_ids = {item["id"] for item in member_list.json()["items"]}
        assert listed_ids == {member_conversation["id"]}
        assert owner_detail.status_code == 404
        assert owner_stream.status_code == 404


@pytest.mark.parametrize("health_path", ["/api/v1/health", "/api/v1/readiness"])
def test_public_event_storage_wait_preserves_application_health(
    settings: Settings, monkeypatch: pytest.MonkeyPatch, health_path: str
) -> None:
    """An SSE storage wait must not monopolize the application's event loop."""

    app = _make_app(settings, _ScriptedRuntime())
    entered = threading.Event()
    release = threading.Event()
    returned = threading.Event()
    with TestClient(app, client=("127.0.0.1", 51068)) as browser:
        identity = _add_signed_in_user(app, 80070)
        _set_browser_session(browser, identity)
        context, conversation, model = _prepare_conversation(browser, identity)
        turn = _start_turn(browser, identity, context, conversation, model)
        storage = app.state.assistant.storage
        original = storage.events_after

        def delayed_events_after(*args: object, **kwargs: object) -> list[dict[str, object]]:
            entered.set()
            release.wait(timeout=1.5)
            returned.set()
            return original(*args, **kwargs)

        monkeypatch.setattr(storage, "events_after", delayed_events_after)
        event_path = (
            f"/api/v1/assistant/conversations/{conversation['id']}/turns/{turn['id']}/events"
        )
        with ThreadPoolExecutor(max_workers=1) as executor:
            stream = executor.submit(browser.get, event_path)
            try:
                assert entered.wait(timeout=3), "SSE request did not reach storage"
                health = browser.get(health_path)
                assert health.status_code == 200
                assert health.json()["status"] == (
                    "ready" if health_path.endswith("readiness") else "ok"
                )
                assert not returned.is_set(), "health waited for SSE storage to return"
            finally:
                release.set()
                response = stream.result(timeout=5)
            assert response.status_code == 200
            assert "event: complete" in response.text


def test_public_event_projection_wait_rechecks_revoked_session(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A session revoked during browser projection cannot receive the pending token."""

    marker = "must-not-reach-revoked-projection:"
    runtime = _ScriptedRuntime([{"type": "token", "data": {"text": marker + "x" * 400}}])
    app = _make_app(settings, runtime)
    entered = threading.Event()
    release = threading.Event()
    with TestClient(app, client=("127.0.0.1", 51068)) as browser:
        identity = _add_signed_in_user(app, 80071)
        _set_browser_session(browser, identity)
        context, conversation, model = _prepare_conversation(browser, identity)
        turn = _start_turn(browser, identity, context, conversation, model)
        assistant = app.state.assistant
        original = assistant.project_event_for_browser

        def delayed_projection(current: object, event: Mapping[str, object]) -> dict[str, object]:
            if event.get("type") == "token":
                entered.set()
                release.wait(timeout=3)
            return original(current, event)

        monkeypatch.setattr(assistant, "project_event_for_browser", delayed_projection)
        event_path = (
            f"/api/v1/assistant/conversations/{conversation['id']}/turns/{turn['id']}/events"
        )
        with ThreadPoolExecutor(max_workers=1) as executor:
            stream = executor.submit(browser.get, event_path)
            try:
                assert entered.wait(timeout=3), "SSE request did not reach token projection"
                app.state.repository.auth_revoke_session(
                    str(identity["token_hash"]), _NOW.isoformat()
                )
            finally:
                release.set()
                response = stream.result(timeout=5)
            assert response.status_code == 200
            assert marker not in response.text


@pytest.mark.parametrize("completion_state", ["completed", "revoked", "closed-only"])
def test_public_event_stream_preserves_completion_during_execution_recheck(
    settings: Settings, monkeypatch: pytest.MonkeyPatch, completion_state: str
) -> None:
    """A legitimate turn finishing during an SSE recheck must retain its terminal event."""

    runtime = _PausedRuntime()
    app = _make_app(settings, runtime)
    entered = threading.Event()
    release = threading.Event()
    completed = threading.Event()
    with TestClient(app, client=("127.0.0.1", 51068)) as browser:
        identity = _add_signed_in_user(app, 80072)
        _set_browser_session(browser, identity)
        context, conversation, model = _prepare_conversation(browser, identity)
        turn = _start_turn(browser, identity, context, conversation, model)
        assert runtime.ready_for_first_event.wait(timeout=3)
        assert runtime.loop is not None and runtime.start_first_event is not None
        runtime.loop.call_soon_threadsafe(runtime.start_first_event.set)
        assert runtime.first_event_ready.wait(timeout=3)
        assert runtime.resume is not None
        assistant = app.state.assistant
        original_check = assistant._execution_current
        original_status = assistant.storage.finalize_turn

        def delayed_execution_check(*args: object, **kwargs: object) -> bool:
            try:
                asyncio.get_running_loop()
            except RuntimeError:
                if not entered.is_set():
                    entered.set()
                    # The parent's finally owns release; a timer would end the race early.
                    release.wait()
            return original_check(*args, **kwargs)

        def record_terminal_status(*args: object, **kwargs: object) -> object:
            result = original_status(*args, **kwargs)
            if kwargs.get("status") == "completed":
                completed.set()
            return result

        monkeypatch.setattr(assistant, "_execution_current", delayed_execution_check)
        monkeypatch.setattr(assistant.storage, "finalize_turn", record_terminal_status)
        event_path = (
            f"/api/v1/assistant/conversations/{conversation['id']}/turns/{turn['id']}/events"
        )
        with ThreadPoolExecutor(max_workers=1) as executor:
            stream = None
            primary_failure = None
            try:
                stream = executor.submit(browser.get, event_path)
                assert entered.wait(timeout=3), "SSE did not reach execution authorization"
                if completion_state == "closed-only":
                    lease = assistant.storage.execution_for_turn(
                        int(identity["user_id"]), str(conversation["id"]), str(turn["id"])
                    )
                    assert lease is not None
                    assistant.storage.close_execution(str(lease["execution_id"]), now=_NOW)
                else:
                    runtime.loop.call_soon_threadsafe(runtime.resume.set)
                    assert completed.wait(timeout=3), "turn did not commit completion"
                if completion_state == "revoked":
                    app.state.repository.auth_revoke_session(
                        str(identity["token_hash"]), _NOW.isoformat()
                    )
            except BaseException as error:
                primary_failure = error
                raise
            finally:
                release.set()
                try:
                    if stream is not None:
                        try:
                            response = stream.result(timeout=5)
                        except Exception as cleanup_error:
                            if primary_failure is None:
                                raise
                            primary_failure.add_note(
                                f"SSE cleanup also failed ({type(cleanup_error).__name__})."
                            )
                finally:
                    runtime.loop.call_soon_threadsafe(runtime.resume.set)
            assert response.status_code == 200
            if completion_state == "completed":
                assert "event: complete" in response.text
                assert "visible-before-revocation:" in response.text
            else:
                assert response.text == ""


def test_public_event_stream_stops_after_live_session_revocation(settings: Settings) -> None:
    """A live SSE response stops before yielding further events after session revocation."""

    runtime = _PausedRuntime()
    app = _make_app(settings, runtime)
    response_started = threading.Event()
    first_token_sent = threading.Event()
    signal_app = _EventResponseSignal(app, response_started, first_token_sent)
    with TestClient(signal_app, client=("127.0.0.1", 51068)) as browser:
        identity = _add_signed_in_user(app, 80069)
        _set_browser_session(browser, identity)
        context, conversation, model = _prepare_conversation(browser, identity)
        turn = _start_turn(browser, identity, context, conversation, model)
        event_path = (
            f"/api/v1/assistant/conversations/{conversation['id']}/turns/{turn['id']}/events"
        )
        signal_app.event_path = event_path

        with ThreadPoolExecutor(max_workers=1) as executor:
            response_future = executor.submit(browser.get, event_path)
            assert response_started.wait(timeout=3)
            assert runtime.ready_for_first_event.wait(timeout=3)
            assert runtime.loop is not None
            assert runtime.start_first_event is not None
            assert runtime.first_event_ready.wait(timeout=3) is False
            runtime.loop.call_soon_threadsafe(runtime.start_first_event.set)
            assert runtime.first_event_ready.wait(timeout=3)
            assert first_token_sent.wait(timeout=3)
            assert runtime.resume is not None
            app.state.repository.auth_revoke_session(str(identity["token_hash"]), _NOW.isoformat())
            runtime.loop.call_soon_threadsafe(runtime.resume.set)
            response = response_future.result(timeout=5)

        assert response.status_code == 200, response.text
        raw_stream = response.text
        assert "must-not-reach-revoked-browser" not in raw_stream
        assert "visible-before-revocation:" in raw_stream

        replacement = _add_parallel_session(app, identity)
        _set_browser_session(browser, replacement)
        detail = _conversation_detail(browser, str(conversation["id"]))
        stored_events = detail["events"]["items"]
        stored_tokens = [item["data"]["text"] for item in stored_events if item["type"] == "token"]
        assert any("visible-before-revocation:" in token for token in stored_tokens)
        assert not any("must-not-reach-revoked-browser" in token for token in stored_tokens)
        assert detail["turns"][0]["status"] == "failed"
        assert _persisted_error_codes(detail)[-1] == "session_revoked"


@pytest.mark.parametrize("health_path", ["/api/v1/health", "/api/v1/readiness"])
def test_public_turn_history_wait_preserves_application_health(
    settings: Settings, monkeypatch: pytest.MonkeyPatch, health_path: str
) -> None:
    """A pending read for turn history must not delay unrelated health requests."""

    app = _make_app(settings, _ScriptedRuntime())
    entered, release, returned = threading.Event(), threading.Event(), threading.Event()
    with TestClient(app, client=("127.0.0.1", 51068)) as browser:
        identity = _add_signed_in_user(app, 80074)
        _set_browser_session(browser, identity)
        context, conversation, model = _prepare_conversation(browser, identity)
        storage = app.state.assistant.storage
        original = storage.conversation_history

        def held_history(*args: object, **kwargs: object) -> object:
            entered.set()
            release.wait(timeout=1.5)
            returned.set()
            return original(*args, **kwargs)

        monkeypatch.setattr(storage, "conversation_history", held_history)
        with ThreadPoolExecutor(max_workers=1) as executor:
            pending = executor.submit(_start_turn, browser, identity, context, conversation, model)
            try:
                assert entered.wait(timeout=3), "turn did not reach history storage"
                health = browser.get(health_path)
                assert health.status_code == 200
                assert not returned.is_set(), "health waited for turn-history storage to return"
            finally:
                release.set()
                pending.result(timeout=5)


@pytest.mark.parametrize("interruption", ["revoke", "cancel"])
def test_public_turn_history_wait_cannot_start_interrupted_runtime(
    settings: Settings, monkeypatch: pytest.MonkeyPatch, interruption: str
) -> None:
    """A read completing after revocation or cancellation must never start generation."""

    runtime = _ScriptedRuntime()
    app = _make_app(settings, runtime)
    entered, release, returned = threading.Event(), threading.Event(), threading.Event()
    finalized = threading.Event()
    with TestClient(app, client=("127.0.0.1", 51068)) as browser:
        identity = _add_signed_in_user(app, 80075)
        _set_browser_session(browser, identity)
        context, conversation, model = _prepare_conversation(browser, identity)
        storage = app.state.assistant.storage
        original_history = storage.conversation_history
        original_status = storage.set_turn_status
        original_finalize = storage.finalize_turn

        def held_history(*args: object, **kwargs: object) -> object:
            entered.set()
            release.wait(timeout=3)
            try:
                return original_history(*args, **kwargs)
            finally:
                returned.set()

        def observe_terminal(*args: object, **kwargs: object) -> object:
            result = original_status(*args, **kwargs)
            if kwargs.get("status") in {"cancelled", "failed"}:
                finalized.set()
            return result

        monkeypatch.setattr(storage, "conversation_history", held_history)

        def observe_finalization(*args, **kwargs):
            result = original_finalize(*args, **kwargs)
            if kwargs.get("status") in {"cancelled", "failed"}:
                finalized.set()
            return result

        monkeypatch.setattr(storage, "set_turn_status", observe_terminal)
        monkeypatch.setattr(storage, "finalize_turn", observe_finalization)
        try:
            turn = _start_turn(browser, identity, context, conversation, model)
            assert entered.wait(timeout=3), "turn did not reach history storage"
            if interruption == "revoke":
                app.state.repository.auth_revoke_session(
                    str(identity["token_hash"]), _NOW.isoformat()
                )
            else:
                response = browser.post(
                    f"/api/v1/assistant/conversations/{conversation['id']}"
                    f"/turns/{turn['id']}/cancel",
                    headers={"x-csrf-token": str(identity["csrf"])},
                )
                assert response.status_code == 200, response.text
                assert response.json()["status"] == "cancelled"
            assert not returned.is_set(), "history was released before interruption"
        finally:
            release.set()
        assert returned.wait(timeout=3)
        assert finalized.wait(timeout=3)
        assert not runtime.contexts
        stored = storage.get_turn(int(identity["user_id"]), str(conversation["id"]), turn["id"])
        assert stored["status"] == ("failed" if interruption == "revoke" else "cancelled")
        assert stored["error_code"] == (
            "session_revoked" if interruption == "revoke" else "turn_cancelled"
        )


@pytest.mark.parametrize("health_path", ["/api/v1/health", "/api/v1/readiness"])
def test_public_turn_persistence_wait_preserves_application_health(
    settings: Settings, monkeypatch: pytest.MonkeyPatch, health_path: str
) -> None:
    """Persisting a turn must not block unrelated HTTP health requests."""

    app = _make_app(settings, _ScriptedRuntime())
    entered, release, returned = threading.Event(), threading.Event(), threading.Event()
    with TestClient(app, client=("127.0.0.1", 51068)) as browser:
        identity = _add_signed_in_user(app, 80076)
        _set_browser_session(browser, identity)
        context, conversation, model = _prepare_conversation(browser, identity)
        storage = app.state.assistant.storage
        original = storage.create_turn

        def held_create(*args: object, **kwargs: object) -> object:
            entered.set()
            release.wait(timeout=1.5)
            returned.set()
            return original(*args, **kwargs)

        monkeypatch.setattr(storage, "create_turn", held_create)
        with ThreadPoolExecutor(max_workers=1) as executor:
            pending = executor.submit(_start_turn, browser, identity, context, conversation, model)
            try:
                assert entered.wait(timeout=3), "request did not reach turn persistence"
                health = browser.get(health_path)
                assert health.status_code == 200
                assert not returned.is_set(), "health waited for turn persistence to return"
            finally:
                release.set()
                pending.result(timeout=5)


@pytest.mark.parametrize(
    "interruption,phase",
    [
        ("revoke", "write"),
        ("close", "write"),
        ("cancel", "write"),
        ("consent", "write"),
        ("cancel", "authorization"),
    ],
)
def test_interrupted_turn_persistence_closes_late_lease_without_generation(
    settings: Settings, monkeypatch: pytest.MonkeyPatch, interruption: str, phase: str
) -> None:
    """A write returning after interruption must neither leak a slot nor dispatch a model."""

    runtime = _ScriptedRuntime()
    app = _make_app(settings, runtime)
    entered, release, returned = threading.Event(), threading.Event(), threading.Event()
    finalized = threading.Event()
    cancellation_seen = threading.Event()
    cleanup_entered, cleanup_returned = threading.Event(), threading.Event()
    cleanup_errors: list[str] = []
    retirement_calls: list[dict[str, bool]] = []
    records: list[dict[str, object]] = []
    request_task: dict[str, object] = {}
    with TestClient(app, client=("127.0.0.1", 51068)) as browser:
        identity = _add_signed_in_user(app, 80077)
        _set_browser_session(browser, identity)
        context, conversation, model = _prepare_conversation(browser, identity)
        assistant = app.state.assistant
        storage = assistant.storage
        original_create = storage.create_turn
        original_status = storage.set_turn_status
        original_request = assistant.create_turn
        original_live = assistant._assistant_session_is_live
        original_cleanup = assistant._cancel_unstarted_turn
        original_retire = assistant._retire_created_turn
        live_checks = 0

        def held_create(*args: object, **kwargs: object) -> object:
            if phase == "write":
                entered.set()
                release.wait(timeout=5)
            try:
                record = original_create(*args, **kwargs)
                records.append(record)
                return record
            finally:
                if phase == "write":
                    returned.set()

        def observe_live(*args: object, **kwargs: object) -> bool:
            nonlocal live_checks
            live_checks += 1
            hold = phase == "authorization" and live_checks == 2
            if hold:
                entered.set()
                release.wait(timeout=5)
            try:
                return original_live(*args, **kwargs)
            finally:
                if hold:
                    returned.set()

        def observe_cleanup(*args: object, **kwargs: object) -> None:
            cleanup_entered.set()
            try:
                original_cleanup(*args, **kwargs)
            except BaseException as error:
                cleanup_errors.append(type(error).__name__)
                raise
            finally:
                cleanup_returned.set()

        def observe_retire(completed: asyncio.Task[object], *args: object) -> None:
            retirement_calls.append({"done": completed.done(), "cancelled": completed.cancelled()})
            original_retire(completed, *args)

        def observe_status(*args: object, **kwargs: object) -> object:
            result = original_status(*args, **kwargs)
            if kwargs.get("status") == "cancelled":
                finalized.set()
            return result

        async def observe_request(*args: object, **kwargs: object) -> object:
            request_task["loop"] = asyncio.get_running_loop()
            operation = asyncio.create_task(original_request(*args, **kwargs))
            request_task["task"] = operation
            try:
                return await operation
            except asyncio.CancelledError:
                # Keep injected service cancellation observable through Starlette's response task.
                cancellation_seen.set()
                raise AssistantUnavailable("turn_cancelled", 409) from None

        monkeypatch.setattr(storage, "create_turn", held_create)
        monkeypatch.setattr(storage, "set_turn_status", observe_status)
        monkeypatch.setattr(assistant, "create_turn", observe_request)
        monkeypatch.setattr(assistant, "_assistant_session_is_live", observe_live)
        monkeypatch.setattr(assistant, "_cancel_unstarted_turn", observe_cleanup)
        monkeypatch.setattr(assistant, "_retire_created_turn", observe_retire)
        with ThreadPoolExecutor(max_workers=1) as executor:
            pending = executor.submit(
                browser.post,
                f"/api/v1/assistant/conversations/{conversation['id']}/turns",
                headers={"x-csrf-token": str(identity["csrf"])},
                json={
                    "prompt": "Persist this synthetic turn safely.",
                    "model_id": model["model_id"],
                    "policy_version": model["policy_version"],
                    "context": dict(context),
                    "context_preview_accepted": True,
                },
            )
            try:
                assert entered.wait(timeout=3), "request did not reach turn persistence"
                if interruption == "revoke":
                    app.state.repository.auth_revoke_session(
                        str(identity["token_hash"]), _NOW.isoformat()
                    )
                elif interruption == "consent":
                    storage.create_consent(
                        int(identity["user_id"]),
                        model_id=str(model["model_id"]),
                        policy_version=str(model["policy_version"]),
                        accepted_terms=False,
                        data_collection_opt_in=False,
                        recorded_at=_NOW,
                    )
                elif interruption == "close":
                    assert browser.portal is not None
                    browser.portal.call(assistant.close)
                else:
                    loop = cast(asyncio.AbstractEventLoop, request_task["loop"])
                    task = cast(asyncio.Task[object], request_task["task"])
                    loop.call_soon_threadsafe(task.cancel)
                    response = pending.result(timeout=2)
                    assert response.status_code == 409
                    assert response.json()["error"]["code"] == "turn_cancelled"
                    assert cancellation_seen.is_set()
                assert not returned.is_set(), "held operation returned before interruption"
                assert not runtime.contexts
            finally:
                release.set()
            if interruption != "cancel":
                response = pending.result(timeout=5)
                expected_status = {"revoke": 403, "close": 503, "consent": 428}[interruption]
                assert response.status_code == expected_status
            assert returned.wait(timeout=3)
            assert finalized.wait(timeout=3), {
                "message": "late persisted turn was not retired",
                "records": len(records),
                "retirement_calls": retirement_calls,
                "cleanup_entered": cleanup_entered.is_set(),
                "cleanup_returned": cleanup_returned.is_set(),
                "cleanup_errors": cleanup_errors,
                "storage_task_states": [
                    {"done": task.done(), "cancelled": task.cancelled()}
                    for task in assistant._storage_tasks
                ],
            }
        assert len(records) == 1
        record = records[0]
        assert not runtime.contexts
        assert not assistant._tasks
        turn = storage.get_turn(
            int(identity["user_id"]), str(conversation["id"]), str(record["id"])
        )
        assert turn["status"] == "cancelled"
        assert turn["error_code"] == "turn_cancelled"
        lease = storage.execution_lease(str(record["execution_id"]))
        assert lease is not None and lease["status"] == "revoked"


class _WebfetchAuthorizationRuntime(_ScriptedRuntime):
    def __init__(self):
        super().__init__()
        self.ready = threading.Event()
        self.finished = threading.Event()
        self.approved_url = None
        self.approve_immediately = False

    async def run_turn(self, *, context, prompt, emit):
        self.contexts.append(context)
        self.loop = asyncio.get_running_loop()
        self.go = asyncio.Event()
        self.ready.set()
        await self.go.wait()

        async def emit_preview(event):
            await emit(event)
            if self.approve_immediately:
                with self.service._webfetch_waiter_lock:
                    waiters = [
                        waiter
                        for waiter in self.service._webfetch_waiters.values()
                        if waiter.execution_id == context.execution_id
                    ]
                assert len(waiters) == 1
                waiters[0].future.set_result(waiters[0].url)

        try:
            self.approved_url = await self.service.await_webfetch_approval(
                context, "https://example.com/research?fixture=liveness", emit_preview
            )
        finally:
            self.finished.set()
        return AssistantTurnResult(status="completed")


@pytest.mark.parametrize("phase", ["initial", "poll"])
@pytest.mark.parametrize("health_path", ["/api/v1/health", "/api/v1/readiness"])
def test_webfetch_authorization_wait_preserves_application_health(
    settings, monkeypatch, phase, health_path
):
    runtime = _WebfetchAuthorizationRuntime()
    app = _make_app(settings, runtime)
    runtime.service = app.state.assistant
    entered, release, returned = threading.Event(), threading.Event(), threading.Event()
    with TestClient(app, client=("127.0.0.1", 51068)) as browser:
        identity = _add_signed_in_user(app, 80081)
        _set_browser_session(browser, identity)
        context, conversation, model = _prepare_conversation(browser, identity)
        _start_turn(browser, identity, context, conversation, model)
        assert runtime.ready.wait(timeout=3)
        original = app.state.assistant._execution_current
        calls = 0

        def held_check(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == (1 if phase == "initial" else 3):
                entered.set()
                release.wait(timeout=1.5)
                returned.set()
            return original(*args, **kwargs)

        monkeypatch.setattr(app.state.assistant, "_execution_current", held_check)
        try:
            runtime.loop.call_soon_threadsafe(runtime.go.set)
            assert entered.wait(timeout=5), "WebFetch did not reach the selected authorization wait"
            response = browser.get(health_path)
            assert response.status_code == 200
            assert not returned.is_set(), (
                "health waited for WebFetch authorization storage to return"
            )
        finally:
            release.set()


@pytest.mark.parametrize("phase", ["initial", "poll"])
@pytest.mark.parametrize("interruption", ["revoke", "cancel"])
def test_webfetch_authorization_wait_cannot_release_interrupted_request(
    settings, monkeypatch, phase, interruption
):
    """A late authorization result cannot release a URL after session or turn interruption."""
    runtime = _WebfetchAuthorizationRuntime()
    app = _make_app(settings, runtime)
    runtime.service = app.state.assistant
    entered, release, finalized = threading.Event(), threading.Event(), threading.Event()
    with TestClient(app, client=("127.0.0.1", 51068)) as browser:
        identity = _add_signed_in_user(app, 80082)
        _set_browser_session(browser, identity)
        context, conversation, model = _prepare_conversation(browser, identity)
        turn = _start_turn(browser, identity, context, conversation, model)
        assert runtime.ready.wait(timeout=3)
        storage = app.state.assistant.storage
        original_status = storage.set_turn_status
        original_finalize = storage.finalize_turn

        def observe_terminal(*args, **kwargs):
            result = original_status(*args, **kwargs)
            if kwargs.get("status") in {"cancelled", "failed"}:
                finalized.set()
            return result

        def observe_finalization(*args, **kwargs):
            result = original_finalize(*args, **kwargs)
            if kwargs.get("status") in {"cancelled", "failed"}:
                finalized.set()
            return result

        monkeypatch.setattr(storage, "set_turn_status", observe_terminal)
        monkeypatch.setattr(storage, "finalize_turn", observe_finalization)
        original = app.state.assistant._execution_current
        calls = 0

        def held_check(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == (1 if phase == "initial" else 3):
                entered.set()
                release.wait(timeout=3)
            return original(*args, **kwargs)

        monkeypatch.setattr(app.state.assistant, "_execution_current", held_check)
        try:
            runtime.loop.call_soon_threadsafe(runtime.go.set)
            assert entered.wait(timeout=5)
            if interruption == "revoke":
                app.state.repository.auth_revoke_session(
                    str(identity["token_hash"]), _NOW.isoformat()
                )
            else:
                response = browser.post(
                    f"/api/v1/assistant/conversations/{conversation['id']}"
                    f"/turns/{turn['id']}/cancel",
                    headers={"x-csrf-token": str(identity["csrf"])},
                )
                assert response.status_code == 200
                assert response.json()["status"] == "cancelled"
        finally:
            release.set()
        assert runtime.finished.wait(timeout=5)
        assert runtime.approved_url is None
        assert not app.state.assistant._webfetch_waiters
        assert finalized.wait(timeout=5)
        stored = storage.get_turn(int(identity["user_id"]), conversation["id"], turn["id"])
        assert stored["status"] == ("failed" if interruption == "revoke" else "cancelled")
        assert stored["error_code"] == (
            "session_revoked" if interruption == "revoke" else "turn_cancelled"
        )
        lease = storage.execution_for_turn(int(identity["user_id"]), conversation["id"], turn["id"])
        assert lease is not None and lease["status"] == "revoked"


def test_webfetch_delayed_final_authorization_cannot_release_expired_url(settings, monkeypatch):
    """An approved future cannot release its URL when the final async check outlives expiry."""
    runtime = _WebfetchAuthorizationRuntime()
    runtime.approve_immediately = True
    app = _make_app(settings, runtime)
    assistant = app.state.assistant
    runtime.service = assistant
    entered, release = threading.Event(), threading.Event()
    checked = []
    with TestClient(app, client=("127.0.0.1", 51068)) as browser:
        identity = _add_signed_in_user(app, 80083)
        _set_browser_session(browser, identity)
        context, conversation, model = _prepare_conversation(browser, identity)
        turn = _start_turn(browser, identity, context, conversation, model)
        assert runtime.ready.wait(timeout=3)
        execution = assistant.storage.execution_for_turn(
            int(identity["user_id"]), conversation["id"], turn["id"]
        )
        assert execution is not None
        lease = assistant.storage.execution_lease(str(execution["execution_id"]))
        assert lease is not None
        expiry = datetime.fromisoformat(str(lease["expires_at"]))
        original = assistant._execution_current
        calls = 0

        def held_check(*args, **kwargs):
            nonlocal calls
            calls += 1
            final_check = calls == 3
            if final_check:
                entered.set()
                release.wait(timeout=3)
            result = original(*args, **kwargs)
            if final_check:
                checked.append(result)
            return result

        monkeypatch.setattr(assistant, "_execution_current", held_check)
        try:
            runtime.loop.call_soon_threadsafe(runtime.go.set)
            assert entered.wait(timeout=5)
            assistant.clock = lambda: expiry + timedelta(seconds=1)
        finally:
            release.set()
        assert runtime.finished.wait(timeout=5)
        assert checked == [True]
        assert runtime.approved_url is None
        assert not assistant._webfetch_waiters


@pytest.mark.parametrize("health_path", ["/api/v1/health", "/api/v1/readiness"])
@pytest.mark.parametrize("operation", ["normalize", "event", "message", "finalize"])
def test_runtime_storage_wait_preserves_application_health(
    settings, monkeypatch, health_path, operation
):
    """A held synchronous runtime operation must leave unrelated health requests responsive."""

    runtime = _PausedRuntime()
    app = _make_app(settings, runtime)
    entered, release, returned = threading.Event(), threading.Event(), threading.Event()
    with TestClient(app, client=("127.0.0.1", 51068)) as browser:
        identity = _add_signed_in_user(app, 80080)
        _set_browser_session(browser, identity)
        context, conversation, model = _prepare_conversation(browser, identity)
        _start_turn(browser, identity, context, conversation, model)
        assert runtime.ready_for_first_event.wait(timeout=3)
        assistant = app.state.assistant
        target, name = {
            "normalize": (assistant, "_normalize_runtime_event"),
            "event": (assistant.storage, "append_event"),
            "message": (assistant.storage, "append_message"),
            "finalize": (assistant.storage, "finalize_turn"),
        }[operation]
        original = getattr(target, name)

        def held_operation(*args, **kwargs):
            entered.set()
            release.wait(timeout=3)
            returned.set()
            return original(*args, **kwargs)

        monkeypatch.setattr(target, name, held_operation)
        try:
            runtime.loop.call_soon_threadsafe(runtime.start_first_event.set)
            runtime.loop.call_soon_threadsafe(runtime.resume.set)
            assert entered.wait(timeout=5), "runtime did not reach the held operation"
            assert browser.get(health_path).status_code == 200
            assert not returned.is_set(), "health waited for runtime storage to return"
        finally:
            release.set()
            runtime.loop.call_soon_threadsafe(runtime.resume.set)


@pytest.mark.parametrize("interruption", ["live", "revoke", "closed_lease"])
def test_delayed_runtime_event_cannot_write_after_interruption(settings, monkeypatch, interruption):
    runtime = _PausedRuntime()
    app = _make_app(settings, runtime)
    entered, release, returned = threading.Event(), threading.Event(), threading.Event()
    with TestClient(app, client=("127.0.0.1", 51068)) as browser:
        identity = _add_signed_in_user(app, 80084)
        _set_browser_session(browser, identity)
        context, conversation, model = _prepare_conversation(browser, identity)
        turn = _start_turn(browser, identity, context, conversation, model)
        assert runtime.ready_for_first_event.wait(timeout=3)
        storage = app.state.assistant.storage
        original = storage.append_event

        def held_append(*args, **kwargs):
            if kwargs.get("event_type") == "token":
                entered.set()
                release.wait(timeout=3)
                try:
                    return original(*args, **kwargs)
                finally:
                    returned.set()
            return original(*args, **kwargs)

        monkeypatch.setattr(storage, "append_event", held_append)
        try:
            runtime.loop.call_soon_threadsafe(runtime.start_first_event.set)
            assert entered.wait(timeout=5)
            if interruption == "revoke":
                app.state.repository.auth_revoke_session(
                    str(identity["token_hash"]), _NOW.isoformat()
                )
            elif interruption == "closed_lease":
                lease = storage.execution_for_turn(
                    int(identity["user_id"]), conversation["id"], turn["id"]
                )
                assert lease is not None
                storage.close_execution(str(lease["execution_id"]), now=_NOW, revoked=True)
                storage.set_turn_status(
                    int(identity["user_id"]),
                    conversation["id"],
                    turn["id"],
                    status="cancelled",
                    error_code="turn_cancelled",
                    now=_NOW,
                )
            release.set()
            assert returned.wait(timeout=5)
            events = storage.events_after(
                int(identity["user_id"]), conversation["id"], turn["id"], after=0
            )
            tokens = [event["data"].get("text", "") for event in events if event["type"] == "token"]
            visible = any("visible-before-revocation:" in value for value in tokens)
            assert visible is (interruption == "live"), (
                "runtime write must persist only while session and execution remain live"
            )
        finally:
            release.set()
            runtime.loop.call_soon_threadsafe(runtime.resume.set)


@pytest.mark.parametrize(
    "authority",
    [
        "live",
        "revoked",
        "expired",
        "model",
        "context",
        "consent",
        "training",
        "canary_live",
        "canary_demoted",
        "canary_identity",
    ],
)
def test_runtime_write_guard_rechecks_all_output_tables(settings, authority):
    """Every runtime output table rejects stale authority without leaving a partial row."""

    runtime = _PausedRuntime()
    app = _make_app(settings, runtime)
    with TestClient(app, client=("127.0.0.1", 51068)) as browser:
        identity = _add_signed_in_user(app, 80085, role="admin")
        _set_browser_session(browser, identity)
        context, conversation, model = _prepare_conversation(browser, identity)
        turn = _start_turn(browser, identity, context, conversation, model)
        assert runtime.ready_for_first_event.wait(timeout=3)
        storage = app.state.assistant.storage
        owner = int(identity["user_id"])
        conversation_id, turn_id = conversation["id"], turn["id"]
        lease = storage.execution_for_turn(owner, conversation_id, turn_id)
        assert lease is not None
        lease = storage.execution_lease(str(lease["execution_id"]))
        assert lease is not None
        guard = AssistantRuntimeWriteGuard(
            execution_id=str(lease["execution_id"]),
            model_id=_MODEL_ID,
            policy_version=_POLICY_VERSION,
            context_version=str(lease["context_version"]),
            now=lambda: _NOW,
        )
        if authority == "revoked":
            app.state.repository.auth_revoke_session(str(identity["token_hash"]), _NOW.isoformat())
        elif authority == "expired":
            guard = replace(guard, now=lambda: _NOW + timedelta(seconds=121))
        elif authority == "model":
            guard = replace(guard, model_id="synthetic-provider/different")
        elif authority == "context":
            guard = replace(guard, context_version="0" * 64)
        elif authority == "consent":
            storage.create_consent(
                owner,
                model_id=_MODEL_ID,
                policy_version=_POLICY_VERSION,
                accepted_terms=False,
                data_collection_opt_in=False,
                recorded_at=_NOW,
            )
        elif authority == "training":
            guard = replace(guard, require_data_collection_opt_in=True)

        if authority.startswith("canary_"):
            guard = replace(guard, canary_github_ids=(80085,))
            if authority == "canary_demoted":
                with app.state.repository.connect() as connection:
                    connection.execute("UPDATE users SET role = 'member' WHERE id = ?", (owner,))
                    connection.commit()
            elif authority == "canary_identity":
                guard = replace(guard, canary_github_ids=(80086,))

        def counts():
            with app.state.repository.connect() as connection:
                return tuple(
                    connection.execute(statement).fetchone()[0]
                    for statement in (
                        "SELECT COUNT(*) FROM assistant_events",
                        "SELECT COUNT(*) FROM assistant_messages",
                        "SELECT COUNT(*) FROM assistant_sources",
                        "SELECT COUNT(*) FROM assistant_proposed_actions",
                        "SELECT COUNT(*) FROM assistant_search_previews",
                    )
                )

        writes = (
            lambda: storage.append_event(
                owner,
                conversation_id,
                turn_id,
                event_type="token",
                data={"text": "guarded fixture"},
                now=_NOW,
                write_guard=guard,
            ),
            lambda: storage.append_message(
                owner,
                conversation_id,
                turn_id,
                role="assistant",
                content="guarded fixture",
                now=_NOW,
                write_guard=guard,
            ),
            lambda: storage.create_source(
                owner,
                conversation_id,
                turn_id,
                source_type="public",
                title="Fixture",
                url="https://example.com/",
                source_ref=None,
                retrieved_at=_NOW,
                as_of=None,
                metadata={},
                write_guard=guard,
            ),
            lambda: storage.create_action(
                owner,
                conversation_id,
                turn_id,
                action_type="theme.set",
                payload={"theme": "dark"},
                action_version=1,
                session_id=str(lease["session_id"]),
                context_version=str(lease["context_version"]),
                execution_id=str(lease["execution_id"]),
                confirmation_phrase="",
                now=_NOW,
                expires_at=_NOW + timedelta(seconds=60),
                write_guard=guard,
            ),
            lambda: storage.append_tool_receipt(
                owner,
                conversation_id,
                turn_id,
                data={"name": "workspace.summary"},
                sources=[{"title": "Fixture", "url": "https://example.com/"}],
                now=_NOW,
                write_guard=guard,
            ),
            lambda: storage.create_search_preview(
                owner,
                conversation_id,
                turn_id,
                str(lease["execution_id"]),
                query_text="fixture public query",
                context_version=str(lease["context_version"]),
                confirmation_phrase="",
                now=_NOW,
                expires_at=_NOW + timedelta(seconds=60),
                write_guard=guard,
            ),
        )
        try:
            for write in writes:
                before = counts()
                if authority in {"live", "canary_live"}:
                    write()
                    assert sum(counts()) > sum(before)
                else:
                    with pytest.raises(AssistantStorageExecutionStale):
                        write()
                    assert counts() == before
        finally:
            # This direct storage test never releases the paused synthetic model.
            runtime.loop.call_soon_threadsafe(
                app.state.assistant._tasks[str(lease["execution_id"])].cancel
            )


def test_cancelled_emitter_keeps_output_order_until_worker_finishes(settings, monkeypatch):
    """Cancelling a waiter must not release the lock protecting a still-running write."""

    entered, release, emitter_cancelled = threading.Event(), threading.Event(), threading.Event()
    normalized = []

    class ConcurrentRuntime(_ScriptedRuntime):
        async def run_turn(self, *, context, prompt, emit):
            first = asyncio.create_task(emit({"type": "token", "data": {"text": "a" * 320}}))
            assert await asyncio.to_thread(entered.wait, 3)
            first.cancel()
            with pytest.raises(asyncio.CancelledError):
                await first
            emitter_cancelled.set()
            await emit({"type": "token", "data": {"text": "b" * 320}})
            return AssistantTurnResult(status="completed")

    app = _make_app(settings, ConcurrentRuntime())
    assistant = app.state.assistant
    original = assistant._normalize_runtime_event

    def held_normalize(*args, **kwargs):
        normalized.append(args[0])
        if len(normalized) == 1:
            entered.set()
            assert release.wait(timeout=5)
        return original(*args, **kwargs)

    monkeypatch.setattr(assistant, "_normalize_runtime_event", held_normalize)
    with TestClient(app, client=("127.0.0.1", 51068)) as browser:
        identity = _add_signed_in_user(app, 80086)
        _set_browser_session(browser, identity)
        context, conversation, model = _prepare_conversation(browser, identity)
        turn = _start_turn(browser, identity, context, conversation, model)
        try:
            assert emitter_cancelled.wait(timeout=3)
            assert browser.get("/api/v1/health").status_code == 200
            assert normalized == ["token"], "second emit overtook the cancelled waiter's worker"
        finally:
            release.set()
        stream = _read_events(browser, str(conversation["id"]), str(turn["id"]))
        assert normalized == ["token", "token"]
        tokens = [event["data"]["text"] for event in stream if event["type"] == "token"]
        assert "".join(tokens) == "a" * 320 + "b" * 320


@pytest.mark.parametrize("interruption", ["revoked", "closed_lease"])
def test_completion_rechecks_authority_inside_terminal_transaction(
    settings, monkeypatch, interruption
):
    """An authority change after message persistence must prevent a completed transition."""

    runtime = _PausedRuntime()
    cache_cleared = threading.Event()
    timing_statuses = []

    async def clear_cache(conversation_id):
        cache_cleared.set()
        return True

    monkeypatch.setattr(runtime, "clear_conversation_cache", clear_cache)
    monkeypatch.setattr(
        runtime,
        "_finish_turn_timing_diagnostic",
        lambda execution_id, user_id, status: timing_statuses.append(status),
        raising=False,
    )
    app = _make_app(settings, runtime)
    entered, release, finalized = threading.Event(), threading.Event(), threading.Event()
    with TestClient(app, client=("127.0.0.1", 51068)) as browser:
        identity = _add_signed_in_user(app, 80088)
        _set_browser_session(browser, identity)
        context, conversation, model = _prepare_conversation(browser, identity)
        turn = _start_turn(browser, identity, context, conversation, model)
        assert runtime.ready_for_first_event.wait(timeout=3)
        storage = app.state.assistant.storage
        original = storage.finalize_turn

        def held_finalization(*args, **kwargs):
            if kwargs["status"] == "completed":
                entered.set()
                assert release.wait(timeout=5)
            result = original(*args, **kwargs)
            finalized.set()
            return result

        monkeypatch.setattr(storage, "finalize_turn", held_finalization)
        try:
            runtime.loop.call_soon_threadsafe(runtime.start_first_event.set)
            runtime.loop.call_soon_threadsafe(runtime.resume.set)
            assert entered.wait(timeout=5)
            assert browser.get("/api/v1/health").status_code == 200
            if interruption == "revoked":
                app.state.repository.auth_revoke_session(
                    str(identity["token_hash"]), _NOW.isoformat()
                )
            else:
                lease = storage.execution_for_turn(
                    int(identity["user_id"]), conversation["id"], turn["id"]
                )
                assert lease is not None
                storage.close_execution(str(lease["execution_id"]), now=_NOW, revoked=True)
        finally:
            release.set()
        assert finalized.wait(timeout=5)
        durable = storage.get_turn(int(identity["user_id"]), conversation["id"], turn["id"])
        assert durable["status"] == "failed"
        assert durable["error_code"] == "session_revoked"
        events = storage.events_after(
            int(identity["user_id"]), conversation["id"], turn["id"], after=0
        )
        assert [event["data"]["status"] for event in events if event["type"] == "complete"] == [
            "failed"
        ]
        assert cache_cleared.wait(timeout=5), "stale completed fallback skipped runtime cache purge"
        assert timing_statuses == ["failed"]


@pytest.mark.parametrize("operation", ["proposal", "receipt"])
@pytest.mark.parametrize("interruption", ["live", "revoked", "cancelled"])
def test_mcp_persistence_rechecks_authority_after_wait(
    settings, monkeypatch, operation, interruption
):
    """The separate MCP proposal and receipt entry points share fresh durable write checks."""

    runtime = _PausedRuntime()
    app = _make_app(settings, runtime)
    entered, release = threading.Event(), threading.Event()
    with TestClient(app, client=("127.0.0.1", 51068)) as browser:
        identity = _add_signed_in_user(app, 80089)
        _set_browser_session(browser, identity)
        context, conversation, model = _prepare_conversation(browser, identity)
        turn = _start_turn(browser, identity, context, conversation, model)
        assert runtime.ready_for_first_event.wait(timeout=3)
        assistant = app.state.assistant
        storage = assistant.storage
        owner = int(identity["user_id"])
        lease_ref = storage.execution_for_turn(owner, conversation["id"], turn["id"])
        assert lease_ref is not None
        lease = storage.execution_lease(str(lease_ref["execution_id"]))
        assert lease is not None
        target = "create_action" if operation == "proposal" else "append_tool_receipt"
        original = getattr(storage, target)

        def held_write(*args, **kwargs):
            entered.set()
            assert release.wait(timeout=5)
            return original(*args, **kwargs)

        monkeypatch.setattr(storage, target, held_write)

        def write():
            if operation == "proposal":
                return assistant.tool_gateway.call(
                    lease=lease,
                    name="assistant.propose_action",
                    arguments={"action_type": "theme.set", "payload": {"theme": "dark"}},
                )
            return assistant.persist_tool_receipt(lease, "workspace.summary", {"fixture": True})

        with ThreadPoolExecutor(max_workers=1) as executor:
            pending = executor.submit(write)
            try:
                assert entered.wait(timeout=3)
                if interruption == "revoked":
                    app.state.repository.auth_revoke_session(
                        str(identity["token_hash"]), _NOW.isoformat()
                    )
                elif interruption == "cancelled":
                    storage.close_execution(str(lease["execution_id"]), now=_NOW, revoked=True)
                    storage.set_turn_status(
                        owner,
                        conversation["id"],
                        turn["id"],
                        status="cancelled",
                        error_code="turn_cancelled",
                        now=_NOW,
                    )
            finally:
                release.set()
            if interruption == "live":
                assert pending.result(timeout=3) is not None
            else:
                with pytest.raises(AssistantStorageConflict):
                    pending.result(timeout=3)
                with app.state.repository.connect() as connection:
                    assert (
                        connection.execute(
                            "SELECT COUNT(*) FROM assistant_proposed_actions WHERE turn_id = ?",
                            (turn["id"],),
                        ).fetchone()[0]
                        == 0
                    )
                    assert (
                        connection.execute(
                            "SELECT COUNT(*) FROM assistant_events WHERE turn_id = ?", (turn["id"],)
                        ).fetchone()[0]
                        == 0
                    )
        runtime.loop.call_soon_threadsafe(assistant._tasks[str(lease["execution_id"])].cancel)


class _SearchAuthorizationRuntime(_ScriptedRuntime):
    """Exercise exact-query approval with synthetic generation and real durable ownership."""

    def __init__(self):
        super().__init__()
        self.ready = threading.Event()
        self.finished = threading.Event()
        self.preview_emitted = threading.Event()
        self.approval_sent = threading.Event()
        self.approved_query = None
        self.approve_immediately = False

    async def run_turn(self, *, context, prompt, emit):
        self.loop = asyncio.get_running_loop()
        self.go = asyncio.Event()
        self.ready.set()
        await self.go.wait()

        async def emit_preview(event):
            await emit(event)
            self.preview_emitted.set()
            if self.approve_immediately:
                preview_id = event["data"]["preview_id"]
                with self.service._search_waiter_lock:
                    future = self.service._search_waiters[preview_id]
                future.set_result(event["data"]["query"])
                self.approval_sent.set()

        try:
            self.approved_query = await self.service.await_search_approval(
                context, "synthetic public query", emit_preview
            )
        finally:
            self.finished.set()
        return AssistantTurnResult(status="completed")


@pytest.mark.parametrize("phase", ["initial", "preview", "final"])
@pytest.mark.parametrize("health_path", ["/api/v1/health", "/api/v1/readiness"])
def test_search_authorization_wait_preserves_application_health(
    settings, monkeypatch, phase, health_path
):
    """Initial checks, preview persistence and final approval checks must stay off-loop."""

    runtime = _SearchAuthorizationRuntime()
    runtime.approve_immediately = phase == "final"
    app = _make_app(settings, runtime)
    runtime.service = app.state.assistant
    entered, release, returned = threading.Event(), threading.Event(), threading.Event()
    with TestClient(app, client=("127.0.0.1", 51068)) as browser:
        identity = _add_signed_in_user(app, 80090)
        _set_browser_session(browser, identity)
        context, conversation, model = _prepare_conversation(browser, identity)
        turn = _start_turn(browser, identity, context, conversation, model)
        assert runtime.ready.wait(timeout=3)
        target = app.state.assistant.storage if phase == "preview" else app.state.assistant
        name = "create_search_preview" if phase == "preview" else "_execution_current"
        original = getattr(target, name)
        calls = 0

        def held_check(*args, **kwargs):
            nonlocal calls
            calls += 1
            if (
                phase == "preview"
                or (phase == "initial" and calls == 1)
                or (phase == "final" and runtime.approval_sent.is_set() and not entered.is_set())
            ):
                entered.set()
                release.wait(timeout=3)
                returned.set()
            return original(*args, **kwargs)

        monkeypatch.setattr(target, name, held_check)
        try:
            runtime.loop.call_soon_threadsafe(runtime.go.set)
            assert entered.wait(timeout=5)
            if phase == "final":
                assert runtime.preview_emitted.is_set() and runtime.approval_sent.is_set()
            assert browser.get(health_path).status_code == 200
            assert not returned.is_set(), "health waited for search authorization storage"
        finally:
            release.set()
            lease = app.state.assistant.storage.execution_for_turn(
                int(identity["user_id"]), conversation["id"], turn["id"]
            )
            task = app.state.assistant._tasks.get(str(lease["execution_id"])) if lease else None
            if task is not None:
                runtime.loop.call_soon_threadsafe(task.cancel)


@pytest.mark.parametrize("interruption", ["revoke", "cancel"])
def test_search_preview_wait_cannot_release_interrupted_query(settings, monkeypatch, interruption):
    """Revocation/cancellation during preview persistence must release no approved query."""

    runtime = _SearchAuthorizationRuntime()
    app = _make_app(settings, runtime)
    runtime.service = app.state.assistant
    entered, release, returned = threading.Event(), threading.Event(), threading.Event()
    with TestClient(app, client=("127.0.0.1", 51068)) as browser:
        identity = _add_signed_in_user(app, 80091)
        _set_browser_session(browser, identity)
        context, conversation, model = _prepare_conversation(browser, identity)
        turn = _start_turn(browser, identity, context, conversation, model)
        assert runtime.ready.wait(timeout=3)
        storage = app.state.assistant.storage
        original = storage.create_search_preview

        def held_preview(*args, **kwargs):
            entered.set()
            assert release.wait(timeout=5)
            try:
                return original(*args, **kwargs)
            finally:
                returned.set()

        monkeypatch.setattr(storage, "create_search_preview", held_preview)
        try:
            runtime.loop.call_soon_threadsafe(runtime.go.set)
            assert entered.wait(timeout=3)
            if interruption == "revoke":
                app.state.repository.auth_revoke_session(
                    str(identity["token_hash"]), _NOW.isoformat()
                )
            else:
                response = browser.post(
                    f"/api/v1/assistant/conversations/{conversation['id']}/turns/{turn['id']}/cancel",
                    headers={"x-csrf-token": str(identity["csrf"])},
                )
                assert response.status_code == 200
                assert response.json()["status"] == "cancelled"
        finally:
            release.set()
        assert returned.wait(timeout=5), "held preview write did not finish after interruption"
        assert runtime.finished.wait(timeout=5)
        assert runtime.approved_query is None
        with app.state.repository.connect() as connection:
            assert (
                connection.execute(
                    "SELECT COUNT(*) FROM assistant_search_previews WHERE turn_id = ?",
                    (turn["id"],),
                ).fetchone()[0]
                == 0
            )


def test_search_delayed_final_authorization_cannot_release_expired_query(settings, monkeypatch):
    """An already-approved synthetic future still cannot outlive the original lease."""

    runtime = _SearchAuthorizationRuntime()
    runtime.approve_immediately = True
    app = _make_app(settings, runtime)
    assistant = app.state.assistant
    runtime.service = assistant
    with TestClient(app, client=("127.0.0.1", 51068)) as browser:
        identity = _add_signed_in_user(app, 80092)
        _set_browser_session(browser, identity)
        context, conversation, model = _prepare_conversation(browser, identity)
        _start_turn(browser, identity, context, conversation, model)
        assert runtime.ready.wait(timeout=3)
        original = assistant._execution_current
        delayed_check_seen = threading.Event()

        def delayed_final_check(*args, **kwargs):
            if runtime.approval_sent.is_set() and not delayed_check_seen.is_set():
                delayed_check_seen.set()
                assistant.clock = lambda: _NOW + timedelta(seconds=121)
                return True
            return original(*args, **kwargs)

        monkeypatch.setattr(assistant, "_execution_current", delayed_final_check)
        runtime.loop.call_soon_threadsafe(runtime.go.set)
        assert runtime.finished.wait(timeout=5)
        assert runtime.preview_emitted.is_set() and runtime.approval_sent.is_set()
        assert delayed_check_seen.is_set()
        assert runtime.approved_query is None
